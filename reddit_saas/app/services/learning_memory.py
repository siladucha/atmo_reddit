"""Learning Memory — unified read API for RAMP Closed Feedback Architecture.

Central knowledge store that aggregates learning signals from all 5 loops:
1. Human edit patterns (EditRecord, CorrectionPattern)
2. Avatar profile corrections (AnalysisEditRecord)
3. Reddit outcomes (KarmaSnapshot, Opportunity.actual_karma)
4. Subreddit performance (outcome_analysis SubredditSignal)
5. Discovery findings (DiscoveryHypothesis.confidence_score)

Any service that needs learning context calls this module instead of
reaching into individual loop stores directly.

Architecture principle:
    Human teaches the system → Reddit validates the system →
    System adjusts strategy → Next generation improves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class LearningMemorySnapshot:
    """Complete learning state for an avatar at a point in time.

    This is the single source of truth for "what has the system learned
    about this avatar's optimal engagement strategy?"
    """

    avatar_id: UUID
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # From Loop 1: Self-Learning (human edit patterns)
    correction_rules: list[str] = field(default_factory=list)
    few_shot_count: int = 0

    # From Loop 2: Avatar Analysis
    profile_edit_count: int = 0
    last_profile_correction: datetime | None = None

    # From Loop 3: EPG Feedback (Reddit outcomes)
    avg_karma_30d: float = 0.0
    removal_rate_30d: float = 0.0
    karma_velocity: float = 0.0
    best_subreddits: list[str] = field(default_factory=list)
    worst_subreddits: list[str] = field(default_factory=list)
    best_approach: str = ""
    epg_adjustments: dict[str, float] = field(default_factory=dict)

    # From Loop 4: Risk/Reputation
    risk_level: str = "low"
    triggers_active: list[str] = field(default_factory=list)

    # From Loop 5: Discovery
    confirmed_hypotheses: int = 0
    strategy_review_needed: bool = False
    discovery_confidence_avg: float = 0.0


def get_learning_snapshot(db: Session, avatar_id: UUID) -> LearningMemorySnapshot:
    """Build a complete learning memory snapshot for an avatar.

    Aggregates data from all 5 feedback loops into a single dataclass.
    Used by: strategy generation, EPG planning, admin dashboard, reports.

    This is intentionally a READ-ONLY operation. Each loop writes to its
    own stores; this function only reads and aggregates.

    Args:
        db: Database session.
        avatar_id: UUID of the avatar.

    Returns:
        LearningMemorySnapshot with all available learning data.
    """
    snapshot = LearningMemorySnapshot(avatar_id=avatar_id)

    # --- Loop 1: Self-Learning patterns ---
    try:
        from app.models.correction_pattern import CorrectionPattern

        patterns = (
            db.query(CorrectionPattern)
            .filter(CorrectionPattern.avatar_id == avatar_id)
            .all()
        )
        snapshot.correction_rules = [p.rule_text for p in patterns if p.rule_text]

        from app.models.edit_record import EditRecord
        from sqlalchemy import func as sa_func

        snapshot.few_shot_count = (
            db.query(sa_func.count(EditRecord.id))
            .filter(
                EditRecord.avatar_id == avatar_id,
                EditRecord.is_archived == False,
            )
            .scalar() or 0
        )
    except Exception:
        logger.debug("Loop 1 data unavailable for avatar %s", avatar_id)

    # --- Loop 2: Avatar Analysis edits ---
    try:
        from app.models.analysis_edit import AnalysisEditRecord
        from sqlalchemy import func as sa_func

        snapshot.profile_edit_count = (
            db.query(sa_func.count(AnalysisEditRecord.id))
            .filter(AnalysisEditRecord.avatar_id == avatar_id)
            .scalar() or 0
        )

        last_edit = (
            db.query(AnalysisEditRecord.created_at)
            .filter(AnalysisEditRecord.avatar_id == avatar_id)
            .order_by(AnalysisEditRecord.created_at.desc())
            .first()
        )
        if last_edit:
            snapshot.last_profile_correction = last_edit[0]
    except Exception:
        logger.debug("Loop 2 data unavailable for avatar %s", avatar_id)

    # --- Loop 3: EPG Feedback (outcomes) ---
    try:
        from app.services.outcome_analysis import compute_avatar_outcome_profile
        from app.services.feedback_loop import get_all_epg_adjustments

        profile = compute_avatar_outcome_profile(db, avatar_id, lookback_days=30)
        snapshot.avg_karma_30d = profile.avg_karma
        snapshot.removal_rate_30d = profile.removal_rate
        snapshot.karma_velocity = profile.karma_velocity
        snapshot.best_subreddits = profile.top_performing_subreddits
        snapshot.worst_subreddits = profile.underperforming_subreddits

        if profile.approach_signals:
            snapshot.best_approach = profile.approach_signals[0].approach

        snapshot.epg_adjustments = get_all_epg_adjustments(db, avatar_id)
    except Exception:
        logger.debug("Loop 3 data unavailable for avatar %s", avatar_id)

    # --- Loop 4: Risk/Reputation ---
    try:
        from app.models.avatar import Avatar
        from app.services.karma_feedback import evaluate_reputation_risk

        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if avatar:
            risk = evaluate_reputation_risk(db, avatar)
            snapshot.risk_level = risk["risk_level"]
            snapshot.triggers_active = risk["triggers_fired"]
    except Exception:
        logger.debug("Loop 4 data unavailable for avatar %s", avatar_id)

    # --- Loop 5: Discovery ---
    try:
        from app.models.discovery_hypothesis import DiscoveryHypothesis
        from app.models.discovery_session import DiscoverySession
        from app.models.avatar import Avatar
        from sqlalchemy import func as sa_func

        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if avatar and avatar.client_ids:
            from uuid import UUID as UUIDType
            client_id = UUIDType(avatar.client_ids[0])

            # Find discovery sessions for this client
            session = (
                db.query(DiscoverySession)
                .filter(
                    DiscoverySession.client_id == client_id,
                    DiscoverySession.status.in_(["completed", "in_progress"]),
                )
                .order_by(DiscoverySession.updated_at.desc())
                .first()
            )

            if session:
                confirmed = (
                    db.query(DiscoveryHypothesis)
                    .filter(
                        DiscoveryHypothesis.session_id == session.id,
                        DiscoveryHypothesis.status == "confirmed",
                    )
                    .all()
                )
                snapshot.confirmed_hypotheses = len(confirmed)

                if confirmed:
                    avg_conf = sum(h.confidence_score for h in confirmed) / len(confirmed)
                    snapshot.discovery_confidence_avg = avg_conf
                    snapshot.strategy_review_needed = any(
                        h.confidence_score < 30 for h in confirmed
                    )
    except Exception:
        logger.debug("Loop 5 data unavailable for avatar %s", avatar_id)

    return snapshot


def format_learning_summary_for_prompt(snapshot: LearningMemorySnapshot) -> str:
    """Format learning memory as context for LLM prompt injection.

    Used by strategy generation and comment generation to give the LLM
    awareness of what the system has learned.

    Args:
        snapshot: A LearningMemorySnapshot.

    Returns:
        Formatted string for prompt injection, or empty if no meaningful data.
    """
    if snapshot.avg_karma_30d == 0 and not snapshot.correction_rules:
        return ""

    parts = ["## System Learning Context (auto-generated)"]

    if snapshot.correction_rules:
        parts.append(f"Active correction rules: {'; '.join(snapshot.correction_rules[:5])}")

    if snapshot.avg_karma_30d != 0:
        parts.append(f"Performance (30d): avg karma {snapshot.avg_karma_30d:.1f}, "
                     f"removal rate {snapshot.removal_rate_30d:.0%}, "
                     f"velocity {snapshot.karma_velocity:.1f}/day")

    if snapshot.best_subreddits:
        parts.append(f"Best performing: {', '.join(snapshot.best_subreddits)}")

    if snapshot.worst_subreddits:
        parts.append(f"Avoid/reduce: {', '.join(snapshot.worst_subreddits)}")

    if snapshot.best_approach:
        parts.append(f"Best approach: {snapshot.best_approach}")

    if snapshot.risk_level in ("high", "critical"):
        parts.append(f"⚠️ Risk level: {snapshot.risk_level} "
                     f"(triggers: {', '.join(snapshot.triggers_active)})")

    if snapshot.strategy_review_needed:
        parts.append("⚠️ Strategy review flagged: some hypotheses below confidence threshold")

    return "\n".join(parts)
