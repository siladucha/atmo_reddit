"""Continuous Discovery — Environment monitoring and hypothesis re-evaluation.

This is the minimal implementation of Discovery Mode 3 (Continuous Environment Mapping).
It runs periodically and:

1. Reads outcome data (KarmaSnapshots, removal rates) for each active client
2. Cross-references against confirmed Discovery hypotheses
3. Updates hypothesis confidence scores based on real outcomes
4. Emits DiscoveryDelta events when significant changes detected
5. Optionally triggers strategy re-evaluation if confidence drops below threshold

Key principle: Discovery is NOT one-time. It continuously validates whether the 
Reddit ecosystem still supports the strategy. If outcomes contradict hypotheses,
the system signals that strategy needs adjustment.

Schedule: Weekly (Sunday 04:00) via Celery Beat, or on-demand.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.activity_event import ActivityEvent
from app.models.audit import AuditLog
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.discovery_hypothesis import DiscoveryHypothesis
from app.models.discovery_session import DiscoverySession
from app.models.karma_snapshot import KarmaSnapshot

logger = get_logger(__name__)

# Thresholds
CONFIDENCE_DROP_THRESHOLD = 30  # Below this, flag for strategy review
MIN_DATA_POINTS = 3  # Minimum posts per subreddit for meaningful signal
LOOKBACK_DAYS = 30  # Window for outcome aggregation


@dataclass
class DiscoveryDelta:
    """A single environment change detected by continuous discovery."""
    client_id: uuid.UUID
    hypothesis_id: uuid.UUID
    delta_type: str  # "confidence_up" | "confidence_down" | "removal_spike" | "karma_decline"
    subreddit: str
    old_value: float
    new_value: float
    reason: str
    requires_strategy_review: bool = False


@dataclass
class ContinuousDiscoveryResult:
    """Result of a continuous discovery run for a single client."""
    client_id: uuid.UUID
    deltas: list[DiscoveryDelta] = field(default_factory=list)
    hypotheses_updated: int = 0
    strategy_review_flagged: bool = False


def run_continuous_discovery(db: Session, client_id: uuid.UUID) -> ContinuousDiscoveryResult:
    """Run continuous discovery for a single client.

    Steps:
    1. Find the client's Discovery session (most recent completed)
    2. For each confirmed hypothesis, check outcome data in referenced subreddits
    3. Update confidence based on actual engagement results
    4. Emit deltas when changes are significant
    5. Flag for strategy review if confidence drops below threshold

    Args:
        db: Database session
        client_id: UUID of the client to analyze

    Returns:
        ContinuousDiscoveryResult with deltas and update counts
    """
    result = ContinuousDiscoveryResult(client_id=client_id)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=LOOKBACK_DAYS)

    # Find most recent Discovery session with confirmed hypotheses for this client
    session = (
        db.query(DiscoverySession)
        .filter(
            DiscoverySession.client_id == client_id,
            DiscoverySession.status.in_(["completed", "in_progress"]),
        )
        .order_by(DiscoverySession.updated_at.desc())
        .first()
    )

    if not session:
        return result

    # Get confirmed hypotheses
    confirmed = (
        db.query(DiscoveryHypothesis)
        .filter(
            DiscoveryHypothesis.session_id == session.id,
            DiscoveryHypothesis.status == "confirmed",
        )
        .all()
    )

    if not confirmed:
        return result

    # Get all posted comments for this client in the lookback window
    posted_comments = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.client_id == client_id,
            CommentDraft.status == "posted",
            CommentDraft.posted_at >= cutoff,
        )
        .all()
    )

    if not posted_comments:
        return result

    # Build subreddit performance map from KarmaSnapshots
    subreddit_perf = _build_subreddit_performance(db, client_id, cutoff)

    # Evaluate each hypothesis against real outcomes
    for hyp in confirmed:
        delta = _evaluate_hypothesis(db, hyp, subreddit_perf, now)
        if delta:
            result.deltas.append(delta)

            # Apply confidence update
            old_conf = hyp.confidence_score
            new_conf = max(0, min(100, old_conf + delta.new_value - delta.old_value))
            hyp.confidence_score = int(new_conf)
            hyp.confidence_delta = int(new_conf) - 50
            result.hypotheses_updated += 1

            # Check if strategy review needed
            if new_conf < CONFIDENCE_DROP_THRESHOLD and old_conf >= CONFIDENCE_DROP_THRESHOLD:
                delta.requires_strategy_review = True
                result.strategy_review_flagged = True

    # Log activity events for significant deltas
    if result.deltas:
        _log_discovery_deltas(db, client_id, result)

    db.commit()

    logger.info(
        "continuous_discovery: client=%s hypotheses_updated=%d deltas=%d strategy_review=%s",
        client_id, result.hypotheses_updated, len(result.deltas), result.strategy_review_flagged,
    )

    return result


def run_continuous_discovery_all_clients(db: Session) -> dict:
    """Run continuous discovery for all active clients with Discovery sessions.

    Returns summary stats.
    """
    # Find clients with Discovery sessions that have confirmed hypotheses
    client_ids = (
        db.query(DiscoverySession.client_id)
        .filter(
            DiscoverySession.status.in_(["completed", "in_progress"]),
            DiscoverySession.client_id.isnot(None),
        )
        .distinct()
        .all()
    )

    # Filter to active clients only
    active_client_ids = (
        db.query(Client.id)
        .filter(
            Client.is_active == True,
            Client.id.in_([cid for (cid,) in client_ids]),
        )
        .all()
    )

    stats = {
        "clients_processed": 0,
        "total_deltas": 0,
        "total_hypotheses_updated": 0,
        "strategy_reviews_flagged": 0,
        "errors": 0,
    }

    for (client_id,) in active_client_ids:
        try:
            result = run_continuous_discovery(db, client_id)
            stats["clients_processed"] += 1
            stats["total_deltas"] += len(result.deltas)
            stats["total_hypotheses_updated"] += result.hypotheses_updated
            if result.strategy_review_flagged:
                stats["strategy_reviews_flagged"] += 1
        except Exception as e:
            stats["errors"] += 1
            logger.error("continuous_discovery error for client %s: %s", client_id, str(e)[:200])
            db.rollback()

    logger.info(
        "continuous_discovery_all: clients=%d deltas=%d hypotheses=%d reviews=%d errors=%d",
        stats["clients_processed"], stats["total_deltas"],
        stats["total_hypotheses_updated"], stats["strategy_reviews_flagged"], stats["errors"],
    )

    return stats


def _build_subreddit_performance(
    db: Session, client_id: uuid.UUID, cutoff: datetime
) -> dict[str, dict]:
    """Build performance map: {subreddit: {avg_karma, removal_rate, reply_avg, count}}.

    Uses KarmaSnapshot data when available, falls back to CommentDraft.reddit_score.
    """
    from collections import defaultdict

    perf: dict[str, dict] = defaultdict(lambda: {
        "karma_values": [], "removals": 0, "replies": [], "count": 0
    })

    # Get posted comments with subreddit info
    posted = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.client_id == client_id,
            CommentDraft.status == "posted",
            CommentDraft.posted_at >= cutoff,
        )
        .all()
    )

    for draft in posted:
        sub = draft.thread.subreddit if draft.thread else None
        if not sub:
            # Fallback: check KarmaSnapshot for subreddit info
            latest_snap = (
                db.query(KarmaSnapshot)
                .filter(KarmaSnapshot.comment_draft_id == draft.id)
                .order_by(KarmaSnapshot.checked_at.desc())
                .first()
            )
            if latest_snap and latest_snap.subreddit:
                sub = latest_snap.subreddit
        if not sub:
            continue

        sub_lower = sub.lower()
        perf[sub_lower]["count"] += 1

        # Try to get latest KarmaSnapshot
        latest_snap = (
            db.query(KarmaSnapshot)
            .filter(KarmaSnapshot.comment_draft_id == draft.id)
            .order_by(KarmaSnapshot.checked_at.desc())
            .first()
        )

        if latest_snap:
            perf[sub_lower]["karma_values"].append(latest_snap.karma_value)
            perf[sub_lower]["replies"].append(latest_snap.reply_count)
            if latest_snap.is_deleted:
                perf[sub_lower]["removals"] += 1
        else:
            # Fallback to draft-level data
            karma = draft.reddit_score or 0
            perf[sub_lower]["karma_values"].append(karma)
            if draft.is_deleted:
                perf[sub_lower]["removals"] += 1

    # Compute aggregates
    result = {}
    for sub, data in perf.items():
        count = data["count"]
        if count < MIN_DATA_POINTS:
            continue

        karma_vals = data["karma_values"]
        result[sub] = {
            "avg_karma": sum(karma_vals) / len(karma_vals) if karma_vals else 0,
            "removal_rate": data["removals"] / count,
            "avg_replies": sum(data["replies"]) / len(data["replies"]) if data["replies"] else 0,
            "count": count,
        }

    return result


def _evaluate_hypothesis(
    db: Session,
    hypothesis: DiscoveryHypothesis,
    subreddit_perf: dict[str, dict],
    now: datetime,
) -> Optional[DiscoveryDelta]:
    """Evaluate a single hypothesis against real subreddit performance.

    Returns a DiscoveryDelta if a significant change is detected, None otherwise.
    """
    signals = hypothesis.reddit_signals or {}
    signal_subs = signals.get("subreddits", [])

    if not signal_subs:
        return None

    # Check each subreddit referenced by this hypothesis
    for sub_signal in signal_subs:
        sub_name = sub_signal.get("name", "").replace("r/", "").lower()
        if not sub_name:
            continue

        perf = subreddit_perf.get(sub_name)
        if not perf:
            continue  # No data for this subreddit yet

        # Evaluate against hypothesis expectations
        original_confidence = hypothesis.confidence_score

        # High removal rate = hypothesis weakening
        if perf["removal_rate"] > 0.25:
            confidence_delta = -15
            return DiscoveryDelta(
                client_id=hypothesis.session.client_id,
                hypothesis_id=hypothesis.id,
                delta_type="removal_spike",
                subreddit=sub_name,
                old_value=original_confidence,
                new_value=original_confidence + confidence_delta,
                reason=f"High removal rate ({perf['removal_rate']:.0%}) in r/{sub_name} — community may be hostile",
            )

        # Negative karma = hypothesis weakening
        if perf["avg_karma"] < 0:
            confidence_delta = -20
            return DiscoveryDelta(
                client_id=hypothesis.session.client_id,
                hypothesis_id=hypothesis.id,
                delta_type="karma_decline",
                subreddit=sub_name,
                old_value=original_confidence,
                new_value=original_confidence + confidence_delta,
                reason=f"Negative avg karma ({perf['avg_karma']:.1f}) in r/{sub_name} — content not resonating",
            )

        # Good karma = hypothesis strengthening
        if perf["avg_karma"] >= 10 and perf["count"] >= 5:
            confidence_delta = 8
            return DiscoveryDelta(
                client_id=hypothesis.session.client_id,
                hypothesis_id=hypothesis.id,
                delta_type="confidence_up",
                subreddit=sub_name,
                old_value=original_confidence,
                new_value=min(100, original_confidence + confidence_delta),
                reason=f"Strong engagement (avg karma {perf['avg_karma']:.1f}, {perf['count']} posts) in r/{sub_name}",
            )

    return None


def _log_discovery_deltas(db: Session, client_id: uuid.UUID, result: ContinuousDiscoveryResult):
    """Log discovery deltas as ActivityEvents for the audit trail."""
    for delta in result.deltas:
        event = ActivityEvent(
            event_type="discovery_continuous_delta",
            client_id=client_id,
            message=(
                f"Discovery [{delta.delta_type}]: r/{delta.subreddit} — {delta.reason}"
            ),
            event_metadata={
                "hypothesis_id": str(delta.hypothesis_id),
                "delta_type": delta.delta_type,
                "subreddit": delta.subreddit,
                "old_confidence": delta.old_value,
                "new_confidence": delta.new_value,
                "requires_strategy_review": delta.requires_strategy_review,
            },
        )
        db.add(event)

    # Summary audit log
    audit = AuditLog(
        action="continuous_discovery_completed",
        client_id=client_id,
        entity_type="client",
        entity_id=client_id,
        details={
            "hypotheses_updated": result.hypotheses_updated,
            "deltas": len(result.deltas),
            "strategy_review_flagged": result.strategy_review_flagged,
            "delta_types": [d.delta_type for d in result.deltas],
        },
    )
    db.add(audit)
