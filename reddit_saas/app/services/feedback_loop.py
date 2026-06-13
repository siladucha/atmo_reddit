"""Feedback Loop Service — closes the cycle: outcomes → system adjustments.

This is the orchestration layer that:
1. Reads outcome analysis signals (from outcome_analysis.py)
2. Applies them to Discovery (hypothesis confidence updates)
3. Applies them to Strategy (performance summary injection)
4. Applies them to EPG (subreddit priority adjustments)
5. Logs all adjustments as ActivityEvents for full traceability

The loop runs:
- After each snapshot_comment_outcomes batch (triggered by Celery)
- On-demand via admin trigger (for testing/debugging)

Key principle: all adjustments are LOGGED and TRACEABLE. Every confidence
change, every priority adjustment has a paper trail back to the outcome
data that triggered it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.activity_event import ActivityEvent
from app.models.audit import AuditLog
from app.services.outcome_analysis import (
    OutcomeFeedbackPacket,
    generate_feedback_packet,
)

logger = get_logger(__name__)


def run_feedback_loop(db: Session, avatar_id: UUID) -> dict:
    """Execute the full feedback loop for a single avatar.

    Steps:
    1. Generate feedback packet (outcome analysis)
    2. Apply hypothesis confidence updates (Discovery)
    3. Store subreddit priority adjustments (for EPG to consume)
    4. Update strategy context (for next strategy generation)
    5. Log everything

    Returns summary dict for audit trail.
    """
    packet = generate_feedback_packet(db, avatar_id)

    results = {
        "avatar_id": str(avatar_id),
        "generated_at": packet.generated_at.isoformat(),
        "profile_summary": packet.performance_summary,
        "adjustments_applied": 0,
        "hypotheses_updated": 0,
        "subreddit_adjustments": {},
    }

    # Step 1: Apply Discovery hypothesis confidence updates
    if packet.hypothesis_confidence_updates:
        results["hypotheses_updated"] = _apply_hypothesis_updates(
            db, packet.hypothesis_confidence_updates
        )

    # Step 2: Store subreddit priority adjustments for EPG
    if packet.subreddit_priority_adjustments:
        results["subreddit_adjustments"] = packet.subreddit_priority_adjustments
        results["adjustments_applied"] = _store_epg_adjustments(
            db, avatar_id, packet.subreddit_priority_adjustments
        )

    # Step 3: Store performance summary for Strategy injection
    if packet.performance_summary:
        _store_performance_context(db, avatar_id, packet.performance_summary)

    # Step 4: Log the feedback loop execution
    _log_feedback_event(db, avatar_id, results)

    db.commit()

    logger.info(
        "feedback_loop: avatar=%s hypotheses_updated=%d subreddit_adjustments=%d",
        avatar_id, results["hypotheses_updated"], results["adjustments_applied"],
    )

    return results


def run_feedback_loop_all_avatars(db: Session) -> dict:
    """Run feedback loop for all active avatars with posted content.

    Called by Celery Beat after snapshot_comment_outcomes.
    """
    from app.models.avatar import Avatar
    from app.models.comment_draft import CommentDraft
    from sqlalchemy import func as sa_func

    # Find avatars with posted content (only process those with actual data)
    avatar_ids = (
        db.query(CommentDraft.avatar_id)
        .filter(CommentDraft.status == "posted")
        .group_by(CommentDraft.avatar_id)
        .having(sa_func.count(CommentDraft.id) >= 3)  # Min 3 posted for meaningful analysis
        .all()
    )

    total = 0
    errors = 0
    results_list = []

    for (avatar_id,) in avatar_ids:
        try:
            result = run_feedback_loop(db, avatar_id)
            results_list.append(result)
            total += 1
        except Exception as e:
            errors += 1
            logger.error("feedback_loop error for avatar %s: %s", avatar_id, str(e)[:200])
            db.rollback()

    summary = {
        "avatars_processed": total,
        "errors": errors,
        "total_hypotheses_updated": sum(r["hypotheses_updated"] for r in results_list),
        "total_adjustments": sum(r["adjustments_applied"] for r in results_list),
    }

    logger.info(
        "feedback_loop_all: processed=%d errors=%d hypotheses=%d adjustments=%d",
        total, errors, summary["total_hypotheses_updated"], summary["total_adjustments"],
    )

    return summary


def _apply_hypothesis_updates(db: Session, updates: list[dict]) -> int:
    """Apply confidence delta to Discovery hypotheses.

    Each update: {hypothesis_id, delta, reason, subreddit, data_points}
    Clamps confidence to 0-100.
    """
    from app.models.discovery_hypothesis import DiscoveryHypothesis

    applied = 0

    for update in updates:
        hyp_id = update.get("hypothesis_id")
        delta = update.get("delta", 0)
        reason = update.get("reason", "")

        if not hyp_id or delta == 0:
            continue

        try:
            hyp = db.query(DiscoveryHypothesis).filter(
                DiscoveryHypothesis.id == hyp_id
            ).first()

            if not hyp:
                continue

            old_confidence = hyp.confidence_score
            new_confidence = max(0, min(100, old_confidence + delta))
            hyp.confidence_score = new_confidence
            hyp.confidence_delta = new_confidence - 50  # Track total delta from initial 50

            applied += 1

            logger.info(
                "hypothesis_confidence_update: hyp=%s old=%d new=%d delta=%d reason=%s",
                hyp_id, old_confidence, new_confidence, delta, reason,
            )

        except Exception as e:
            logger.warning("Failed to update hypothesis %s: %s", hyp_id, e)

    return applied


def _store_epg_adjustments(db: Session, avatar_id: UUID, adjustments: dict[str, float]) -> int:
    """Store subreddit priority adjustments for EPG consumption.

    Stored as a SystemSetting with key pattern:
    epg_adjustment:{avatar_id}:{subreddit} = float delta

    EPG reads these during thread selection to boost/penalize subreddits.
    TTL: overwritten on each feedback loop run (always fresh).
    """
    from app.models.settings import SystemSetting

    stored = 0

    # Clear old adjustments for this avatar
    old_keys = (
        db.query(SystemSetting)
        .filter(SystemSetting.key.like(f"epg_adj:{avatar_id}:%"))
        .all()
    )
    for old in old_keys:
        db.delete(old)

    # Store new adjustments
    for subreddit, delta in adjustments.items():
        key = f"epg_adj:{avatar_id}:{subreddit}"
        setting = SystemSetting(
            key=key,
            value=str(round(delta, 3)),
            group="epg_feedback",
        )
        db.add(setting)
        stored += 1

    return stored


def get_epg_subreddit_adjustment(db: Session, avatar_id: UUID, subreddit: str) -> float:
    """Read the current EPG adjustment for a subreddit.

    Called by EPG during thread selection to factor in outcome-based signals.
    Returns 0.0 if no adjustment exists.
    """
    from app.models.settings import SystemSetting

    key = f"epg_adj:{avatar_id}:{subreddit}"
    setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()

    if setting:
        try:
            return float(setting.value)
        except (ValueError, TypeError):
            return 0.0

    return 0.0


def get_all_epg_adjustments(db: Session, avatar_id: UUID) -> dict[str, float]:
    """Read all current EPG adjustments for an avatar.

    Returns dict: {subreddit: delta}
    """
    from app.models.settings import SystemSetting

    prefix = f"epg_adj:{avatar_id}:"
    settings = (
        db.query(SystemSetting)
        .filter(SystemSetting.key.like(f"{prefix}%"))
        .all()
    )

    adjustments = {}
    for s in settings:
        subreddit = s.key.replace(prefix, "")
        try:
            adjustments[subreddit] = float(s.value)
        except (ValueError, TypeError):
            pass

    return adjustments


def _store_performance_context(db: Session, avatar_id: UUID, summary: dict):
    """Store performance summary for next strategy generation.

    The Strategy Engine reads this when generating the next strategy version,
    injecting real outcome data into the prompt.
    """
    from app.models.settings import SystemSetting
    import json

    key = f"perf_ctx:{avatar_id}"

    existing = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if existing:
        existing.value = json.dumps(summary)
    else:
        setting = SystemSetting(
            key=key,
            value=json.dumps(summary),
            group="feedback_context",
        )
        db.add(setting)


def get_performance_context(db: Session, avatar_id: UUID) -> dict | None:
    """Read stored performance context for strategy generation."""
    from app.models.settings import SystemSetting
    import json

    key = f"perf_ctx:{avatar_id}"
    setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()

    if setting and setting.value:
        try:
            return json.loads(setting.value)
        except (json.JSONDecodeError, TypeError):
            return None

    return None


def _log_feedback_event(db: Session, avatar_id: UUID, results: dict):
    """Log the feedback loop execution as an ActivityEvent + AuditLog entry."""
    from app.models.avatar import Avatar

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    client_id = None
    if avatar and avatar.client_ids:
        try:
            client_id = UUID(avatar.client_ids[0])
        except (ValueError, IndexError):
            pass

    event = ActivityEvent(
        event_type="feedback_loop_executed",
        client_id=client_id,
        message=(
            f"Feedback loop: {results['hypotheses_updated']} hypotheses updated, "
            f"{results['adjustments_applied']} EPG adjustments"
        ),
        event_metadata={
            "avatar_id": str(avatar_id),
            "profile_summary": results.get("profile_summary", {}),
            "subreddit_adjustments": results.get("subreddit_adjustments", {}),
            "hypotheses_updated": results["hypotheses_updated"],
        },
    )
    db.add(event)

    audit = AuditLog(
        action="feedback_loop_executed",
        entity_type="avatar",
        entity_id=avatar_id,
        client_id=client_id,
        details={
            "adjustments": results["adjustments_applied"],
            "hypotheses": results["hypotheses_updated"],
            "karma_velocity": results.get("profile_summary", {}).get("karma_velocity_per_day", 0),
        },
    )
    db.add(audit)
