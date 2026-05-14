"""Risk Prediction Service — AI-driven ban risk forecasting for avatars.

Computes a composite risk score (0-100) based on multiple signals:
- Posting frequency (high frequency → higher risk)
- CQS level (lowest/low → high risk)
- Shadowban history (previous incidents → higher risk)
- Removal rate (deleted comments → higher risk)
- Account age vs activity ratio
- Subreddit diversity (low diversity → higher risk)

The risk score drives the Decision Center's prioritization and prescriptive actions.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.comment_draft import CommentDraft
from app.models.activity_event import ActivityEvent
from app.models.avatar_subreddit_presence import AvatarSubredditPresence

logger = logging.getLogger(__name__)


@dataclass
class RiskFactor:
    """Individual risk factor contributing to overall score."""

    name: str
    score: float  # 0-100 contribution
    weight: float  # 0-1 weight
    description: str
    severity: str  # "low" | "medium" | "high" | "critical"


@dataclass
class RiskPrediction:
    """Complete risk prediction for an avatar."""

    avatar_id: UUID
    avatar_username: str
    risk_score: int  # 0-100 composite
    risk_level: str  # "low" | "medium" | "high" | "critical"
    ban_probability: int  # 0-100 percentage
    time_horizon: str  # e.g. "24h", "7d"
    factors: list[RiskFactor] = field(default_factory=list)
    recommended_action: str = ""
    action_type: str = ""  # "freeze" | "reduce_frequency" | "switch_subreddits" | "monitor"
    explanation: str = ""


@dataclass
class DecisionItem:
    """A single item in the Decision Queue — a draft with risk context."""

    draft_id: UUID
    avatar_id: UUID
    avatar_username: str
    thread_title: str
    subreddit: str
    comment_text: str
    comment_approach: str | None
    engagement_mode: str | None
    confidence_score: int  # 0-100 AI confidence in the text
    risk_level: str  # "high" | "normal"
    risk_explanation: str | None
    ban_probability: int | None
    created_at: datetime
    thread_url: str | None
    # Generation provenance
    learning_metadata: dict | None = None


# --- Risk Score Weights ---
WEIGHT_FREQUENCY = 0.25
WEIGHT_CQS = 0.20
WEIGHT_REMOVAL_RATE = 0.20
WEIGHT_SHADOWBAN_HISTORY = 0.15
WEIGHT_DIVERSITY = 0.10
WEIGHT_ACCOUNT_AGE = 0.10


def compute_risk_prediction(db: Session, avatar: Avatar) -> RiskPrediction:
    """Compute comprehensive risk prediction for a single avatar.

    Analyzes multiple signals to produce a composite risk score and
    prescriptive action recommendation.
    """
    factors: list[RiskFactor] = []
    now = datetime.now(timezone.utc)

    # --- Factor 1: Posting Frequency (last 24h) ---
    frequency_score = _compute_frequency_risk(db, avatar, now)
    factors.append(frequency_score)

    # --- Factor 2: CQS Level ---
    cqs_score = _compute_cqs_risk(avatar)
    factors.append(cqs_score)

    # --- Factor 3: Removal Rate ---
    removal_score = _compute_removal_risk(db, avatar)
    factors.append(removal_score)

    # --- Factor 4: Shadowban History ---
    shadowban_score = _compute_shadowban_risk(db, avatar, now)
    factors.append(shadowban_score)

    # --- Factor 5: Subreddit Diversity ---
    diversity_score = _compute_diversity_risk(db, avatar)
    factors.append(diversity_score)

    # --- Factor 6: Account Age ---
    age_score = _compute_age_risk(avatar)
    factors.append(age_score)

    # --- Composite Score ---
    composite = sum(f.score * f.weight for f in factors)
    risk_score = min(100, max(0, int(composite)))

    # --- Risk Level Classification ---
    if risk_score >= 80:
        risk_level = "critical"
        ban_probability = min(99, risk_score + 5)
        time_horizon = "24h"
    elif risk_score >= 60:
        risk_level = "high"
        ban_probability = risk_score
        time_horizon = "48h"
    elif risk_score >= 40:
        risk_level = "medium"
        ban_probability = max(20, risk_score - 10)
        time_horizon = "7d"
    else:
        risk_level = "low"
        ban_probability = max(5, risk_score - 15)
        time_horizon = "30d"

    # --- Prescriptive Action ---
    action, action_type, explanation = _determine_action(risk_level, factors)

    return RiskPrediction(
        avatar_id=avatar.id,
        avatar_username=avatar.reddit_username,
        risk_score=risk_score,
        risk_level=risk_level,
        ban_probability=ban_probability,
        time_horizon=time_horizon,
        factors=factors,
        recommended_action=action,
        action_type=action_type,
        explanation=explanation,
    )


def _compute_frequency_risk(db: Session, avatar: Avatar, now: datetime) -> RiskFactor:
    """High posting frequency in short time = detectable pattern."""
    window_24h = now - timedelta(hours=24)
    window_4h = now - timedelta(hours=4)

    posts_24h = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.status.in_(("approved", "posted")),
            CommentDraft.created_at >= window_24h,
        )
        .scalar()
    ) or 0

    posts_4h = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.status.in_(("approved", "posted")),
            CommentDraft.created_at >= window_4h,
        )
        .scalar()
    ) or 0

    # Thresholds: >10 posts/24h or >5 posts/4h = high risk
    if posts_4h >= 5 or posts_24h >= 15:
        score = 100
        severity = "critical"
        desc = f"{posts_24h} posts in 24h, {posts_4h} in last 4h — detectable burst"
    elif posts_24h >= 10 or posts_4h >= 3:
        score = 70
        severity = "high"
        desc = f"{posts_24h} posts in 24h — elevated frequency"
    elif posts_24h >= 5:
        score = 40
        severity = "medium"
        desc = f"{posts_24h} posts in 24h — moderate activity"
    else:
        score = 10
        severity = "low"
        desc = f"{posts_24h} posts in 24h — normal"

    return RiskFactor(
        name="posting_frequency",
        score=score,
        weight=WEIGHT_FREQUENCY,
        description=desc,
        severity=severity,
    )


def _compute_cqs_risk(avatar: Avatar) -> RiskFactor:
    """CQS level directly correlates with Reddit's trust in the account."""
    cqs = avatar.cqs_level

    if cqs == "lowest":
        score = 100
        severity = "critical"
        desc = "CQS LOWEST — Reddit actively suppressing content"
    elif cqs == "low":
        score = 70
        severity = "high"
        desc = "CQS LOW — reduced visibility, approaching suppression"
    elif cqs == "moderate":
        score = 30
        severity = "medium"
        desc = "CQS MODERATE — acceptable but not trusted"
    elif cqs in ("high", "highest"):
        score = 5
        severity = "low"
        desc = f"CQS {(cqs or '').upper()} — trusted account"
    else:
        score = 40
        severity = "medium"
        desc = "CQS not checked — unknown trust level"

    return RiskFactor(
        name="cqs_level",
        score=score,
        weight=WEIGHT_CQS,
        description=desc,
        severity=severity,
    )


def _compute_removal_risk(db: Session, avatar: Avatar) -> RiskFactor:
    """High removal rate signals mod attention or spam detection."""
    total_posted = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.status == "posted",
        )
        .scalar()
    ) or 0

    removed = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.status == "posted",
            CommentDraft.is_deleted == True,  # noqa: E712
        )
        .scalar()
    ) or 0

    if total_posted == 0:
        return RiskFactor(
            name="removal_rate",
            score=20,
            weight=WEIGHT_REMOVAL_RATE,
            description="No posted comments yet — baseline risk",
            severity="low",
        )

    rate = (removed / total_posted) * 100

    if rate >= 30:
        score = 100
        severity = "critical"
        desc = f"{rate:.0f}% removal rate ({removed}/{total_posted}) — heavy mod action"
    elif rate >= 15:
        score = 70
        severity = "high"
        desc = f"{rate:.0f}% removal rate — elevated mod attention"
    elif rate >= 5:
        score = 35
        severity = "medium"
        desc = f"{rate:.0f}% removal rate — some removals"
    else:
        score = 5
        severity = "low"
        desc = f"{rate:.0f}% removal rate — healthy"

    return RiskFactor(
        name="removal_rate",
        score=score,
        weight=WEIGHT_REMOVAL_RATE,
        description=desc,
        severity=severity,
    )


def _compute_shadowban_risk(db: Session, avatar: Avatar, now: datetime) -> RiskFactor:
    """Previous shadowban incidents increase future risk."""
    if avatar.health_status == "shadowbanned":
        return RiskFactor(
            name="shadowban_history",
            score=100,
            weight=WEIGHT_SHADOWBAN_HISTORY,
            description="CURRENTLY SHADOWBANNED",
            severity="critical",
        )

    if avatar.is_shadowbanned:
        return RiskFactor(
            name="shadowban_history",
            score=90,
            weight=WEIGHT_SHADOWBAN_HISTORY,
            description="Legacy shadowban flag active",
            severity="critical",
        )

    # Check for recent health status changes (last 30 days)
    window = now - timedelta(days=30)
    incidents = (
        db.query(func.count(ActivityEvent.id))
        .filter(
            ActivityEvent.event_type == "safety",
            ActivityEvent.created_at >= window,
            ActivityEvent.event_metadata["avatar_id"].astext == str(avatar.id),
        )
        .scalar()
    ) or 0

    if incidents >= 3:
        score = 80
        severity = "high"
        desc = f"{incidents} safety incidents in 30 days"
    elif incidents >= 1:
        score = 50
        severity = "medium"
        desc = f"{incidents} safety incident(s) in 30 days"
    else:
        score = 5
        severity = "low"
        desc = "No recent safety incidents"

    return RiskFactor(
        name="shadowban_history",
        score=score,
        weight=WEIGHT_SHADOWBAN_HISTORY,
        description=desc,
        severity=severity,
    )


def _compute_diversity_risk(db: Session, avatar: Avatar) -> RiskFactor:
    """Low subreddit diversity = concentrated activity = easier to detect."""
    presence_count = (
        db.query(func.count(AvatarSubredditPresence.id))
        .filter(AvatarSubredditPresence.avatar_id == avatar.id)
        .scalar()
    ) or 0

    if presence_count >= 8:
        score = 5
        severity = "low"
        desc = f"Active in {presence_count} subreddits — good diversity"
    elif presence_count >= 4:
        score = 30
        severity = "medium"
        desc = f"Active in {presence_count} subreddits — moderate diversity"
    elif presence_count >= 2:
        score = 60
        severity = "high"
        desc = f"Only {presence_count} subreddits — concentrated activity"
    else:
        score = 80
        severity = "high"
        desc = "1 or fewer subreddits — very concentrated"

    return RiskFactor(
        name="subreddit_diversity",
        score=score,
        weight=WEIGHT_DIVERSITY,
        description=desc,
        severity=severity,
    )


def _compute_age_risk(avatar: Avatar) -> RiskFactor:
    """New accounts with high activity are suspicious."""
    if not avatar.reddit_account_created:
        return RiskFactor(
            name="account_age",
            score=40,
            weight=WEIGHT_ACCOUNT_AGE,
            description="Account age unknown",
            severity="medium",
        )

    now = datetime.now(timezone.utc)
    age_days = (now - avatar.reddit_account_created).days

    if age_days < 30:
        score = 90
        severity = "critical"
        desc = f"Account only {age_days} days old — very new"
    elif age_days < 90:
        score = 60
        severity = "high"
        desc = f"Account {age_days} days old — still young"
    elif age_days < 365:
        score = 30
        severity = "medium"
        desc = f"Account {age_days} days old — moderate age"
    else:
        score = 5
        severity = "low"
        desc = f"Account {age_days} days old — established"

    return RiskFactor(
        name="account_age",
        score=score,
        weight=WEIGHT_ACCOUNT_AGE,
        description=desc,
        severity=severity,
    )


def _determine_action(
    risk_level: str, factors: list[RiskFactor]
) -> tuple[str, str, str]:
    """Determine prescriptive action based on risk level and dominant factors."""
    # Find the highest-severity factor
    critical_factors = [f for f in factors if f.severity == "critical"]
    high_factors = [f for f in factors if f.severity == "high"]

    if risk_level == "critical":
        if any(f.name == "shadowban_history" and f.severity == "critical" for f in factors):
            return (
                "Freeze activity now & switch to read-only",
                "freeze",
                "Avatar is currently shadowbanned or has critical safety incidents. "
                "All posting should stop immediately.",
            )
        if any(f.name == "posting_frequency" and f.severity == "critical" for f in factors):
            return (
                "Freeze activity now & reduce posting frequency",
                "freeze",
                "Posting frequency is dangerously high and creates detectable patterns. "
                "Immediate cooldown required.",
            )
        return (
            "Freeze activity now & investigate",
            "freeze",
            "Multiple critical risk factors detected. Manual investigation required.",
        )

    if risk_level == "high":
        if any(f.name == "posting_frequency" and f.severity in ("high", "critical") for f in factors):
            return (
                "Reduce posting frequency to 3/day max",
                "reduce_frequency",
                "High posting frequency detected. Reduce to avoid pattern detection.",
            )
        if any(f.name == "removal_rate" and f.severity in ("high", "critical") for f in factors):
            return (
                "Switch to safer subreddits & review content quality",
                "switch_subreddits",
                "High removal rate indicates mod attention. Diversify subreddits.",
            )
        return (
            "Monitor closely & reduce activity",
            "reduce_frequency",
            "Elevated risk from multiple factors. Reduce activity volume.",
        )

    if risk_level == "medium":
        return (
            "Monitor — no immediate action needed",
            "monitor",
            "Moderate risk level. Continue monitoring but no urgent action required.",
        )

    return (
        "All clear — continue normal operations",
        "monitor",
        "Low risk. Avatar is operating within safe parameters.",
    )


def get_decision_queue(
    db: Session,
    client_id: UUID | None = None,
    avatar_id: UUID | None = None,
    limit: int = 50,
) -> list[DecisionItem]:
    """Build the prioritized Decision Queue for the Decision Center.

    Returns pending drafts enriched with risk context and confidence scores,
    sorted by risk level (HIGH first) then by creation time.
    """
    from app.models.thread import RedditThread

    query = (
        db.query(CommentDraft)
        .filter(CommentDraft.status == "pending")
    )

    if client_id:
        query = query.filter(CommentDraft.client_id == client_id)
    if avatar_id:
        query = query.filter(CommentDraft.avatar_id == avatar_id)

    query = query.order_by(CommentDraft.created_at.desc())
    drafts = query.limit(limit).all()

    # Batch-load avatar risk predictions
    avatar_risks: dict[UUID, RiskPrediction] = {}
    for draft in drafts:
        if draft.avatar_id not in avatar_risks:
            avatar = db.query(Avatar).filter(Avatar.id == draft.avatar_id).first()
            if avatar:
                try:
                    avatar_risks[draft.avatar_id] = compute_risk_prediction(db, avatar)
                except Exception:
                    logger.exception("Risk prediction failed for avatar %s", draft.avatar_id)

    # Build decision items
    items: list[DecisionItem] = []
    for draft in drafts:
        thread = db.query(RedditThread).filter(RedditThread.id == draft.thread_id).first()
        risk = avatar_risks.get(draft.avatar_id)

        # Confidence score: based on learning metadata presence + approach diversity
        confidence = _compute_confidence_score(draft)

        # Risk level for this specific draft
        draft_risk_level = "normal"
        risk_explanation = None
        ban_probability = None

        if risk and risk.risk_level in ("high", "critical"):
            draft_risk_level = "high"
            risk_explanation = (
                f"BAN LIKELY ({risk.ban_probability}%) within {risk.time_horizon} "
                f"due to {risk.factors[0].description if risk.factors else 'multiple factors'}"
            )
            ban_probability = risk.ban_probability

        items.append(DecisionItem(
            draft_id=draft.id,
            avatar_id=draft.avatar_id,
            avatar_username=draft.avatar.reddit_username if draft.avatar else "unknown",
            thread_title=thread.post_title if thread else "Unknown thread",
            subreddit=thread.subreddit if thread else "unknown",
            comment_text=draft.edited_draft or draft.ai_draft or "",
            comment_approach=draft.comment_approach,
            engagement_mode=draft.engagement_mode,
            confidence_score=confidence,
            risk_level=draft_risk_level,
            risk_explanation=risk_explanation,
            ban_probability=ban_probability,
            created_at=draft.created_at,
            thread_url=thread.url if thread else None,
            learning_metadata=draft.learning_metadata,
        ))

    # Sort: HIGH RISK first, then by creation time (newest first)
    items.sort(key=lambda x: (0 if x.risk_level == "high" else 1, -x.created_at.timestamp()))

    return items


def _compute_confidence_score(draft: CommentDraft) -> int:
    """Compute AI confidence score for a draft (0-100).

    Based on:
    - Presence of learning metadata (few-shot examples used)
    - Comment approach (some approaches are more reliable)
    - Text length (very short or very long = lower confidence)
    """
    score = 70  # Base confidence

    # Learning metadata bonus
    if draft.learning_metadata:
        patterns = draft.learning_metadata.get("correction_patterns", [])
        examples = draft.learning_metadata.get("edit_record_ids", [])
        if patterns:
            score += 10
        if examples:
            score += 5

    # Text length check
    text = draft.edited_draft or draft.ai_draft or ""
    word_count = len(text.split())
    if word_count < 10:
        score -= 15  # Too short
    elif word_count > 200:
        score -= 10  # Too long
    elif 30 <= word_count <= 100:
        score += 5  # Sweet spot

    # Approach reliability
    reliable_approaches = {"helpful_expert", "personal_experience", "curious_question"}
    if draft.comment_approach and draft.comment_approach in reliable_approaches:
        score += 5

    return min(100, max(0, score))


def get_avatar_risk_summary(db: Session, avatar_id: UUID) -> RiskPrediction | None:
    """Get risk prediction for a specific avatar. Returns None if avatar not found."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return None
    try:
        return compute_risk_prediction(db, avatar)
    except Exception:
        logger.exception("Risk prediction failed for avatar %s", avatar_id)
        return None
