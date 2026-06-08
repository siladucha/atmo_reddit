"""Celery task for EPG 2.0 karma outcome tracking.

Checks actual karma outcomes for opportunities that were selected and posted,
then computes deviation from predicted returns for model correction.

Schedule:
- Runs every 4 hours via Celery Beat
- Processes opportunities linked to EPGSlots in "posted" status
- Checks at 4h, 24h, and 48h after posting
- Updates opportunity.actual_karma, actual_removal, outcome_checked_at
- Logs model_correction_event when |deviation| > 50%

Requirements: 13.1, 13.2, 13.3
"""

from datetime import datetime, timedelta, timezone

from celery import shared_task

from app.database import SessionLocal
from app.logging_config import get_logger

logger = get_logger(__name__)

# Check windows after posting (hours)
OUTCOME_CHECK_WINDOWS_HOURS = [4, 24, 48]


@shared_task(name="check_karma_outcomes")
def check_karma_outcomes():
    """Check karma outcomes for posted EPG 2.0 opportunities.

    Finds opportunities with status 'selected' or 'executed' that have
    associated EPGSlots in 'posted' status. For each, if enough time
    has elapsed since posting (4h, 24h, or 48h), reads actual karma
    from the matching CommentDraft and updates the opportunity record.

    Computes deviation_percentage and logs model_correction_event when
    |deviation| > 50%.
    """
    from app.models.comment_draft import CommentDraft
    from app.models.epg_slot import EPGSlot
    from app.models.opportunity import Opportunity

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        # Find opportunities that need outcome checking:
        # - Status is 'selected' or 'executed' (they were chosen by EPG 2.0)
        # - outcome_checked_at is NULL (never checked) or was checked before 24h window
        # - Have a matching EPGSlot in "posted" status
        opportunities = (
            db.query(Opportunity)
            .filter(
                Opportunity.status.in_(["selected", "executed"]),
            )
            .all()
        )

        if not opportunities:
            logger.debug("check_karma_outcomes: no opportunities to check")
            return {"checked": 0, "updated": 0, "corrections": 0}

        stats = {
            "checked": 0,
            "updated": 0,
            "corrections": 0,
            "errors": 0,
            "skipped_no_slot": 0,
            "skipped_too_early": 0,
        }

        for opportunity in opportunities:
            try:
                _check_single_opportunity(db, opportunity, now, stats)
            except Exception as e:
                stats["errors"] += 1
                logger.error(
                    "check_karma_outcomes: error processing opportunity %s: %s",
                    opportunity.id, str(e)[:200],
                )
                db.rollback()
                continue

        logger.info(
            "check_karma_outcomes complete: checked=%d updated=%d corrections=%d errors=%d",
            stats["checked"], stats["updated"], stats["corrections"], stats["errors"],
        )
        return stats

    except Exception as e:
        logger.error("check_karma_outcomes failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


def _check_single_opportunity(db, opportunity, now: datetime, stats: dict):
    """Check karma outcome for a single opportunity.

    Finds the matching EPGSlot (posted), gets the CommentDraft karma,
    and updates the opportunity record.
    """
    from app.models.comment_draft import CommentDraft
    from app.models.epg_slot import EPGSlot

    stats["checked"] += 1

    # Find the matching EPGSlot in "posted" status for this opportunity's thread
    slot_query = (
        db.query(EPGSlot)
        .filter(
            EPGSlot.avatar_id == opportunity.avatar_id,
            EPGSlot.status == "posted",
        )
    )

    # Match by thread_id or hobby_post_id
    if opportunity.thread_id:
        slot_query = slot_query.filter(EPGSlot.thread_id == opportunity.thread_id)
    elif opportunity.hobby_post_id:
        slot_query = slot_query.filter(EPGSlot.hobby_post_id == opportunity.hobby_post_id)
    else:
        stats["skipped_no_slot"] += 1
        return

    # Get the most recent matching slot
    slot = slot_query.order_by(EPGSlot.posted_at.desc()).first()

    if not slot or not slot.posted_at:
        stats["skipped_no_slot"] += 1
        return

    # Check if enough time has elapsed since posting
    hours_since_posting = (now - slot.posted_at).total_seconds() / 3600

    # Determine which check window we're in
    # We want to check at 4h, 24h, and 48h after posting
    should_check = False
    for window_hours in OUTCOME_CHECK_WINDOWS_HOURS:
        if hours_since_posting >= window_hours:
            # Check if we've already checked at or after this window
            if opportunity.outcome_checked_at is None:
                should_check = True
                break
            else:
                # Re-check if last check was before this window opened
                hours_since_last_check = (now - opportunity.outcome_checked_at).total_seconds() / 3600
                # Only re-check if at least 4 hours since last check (avoid hammering)
                if hours_since_last_check >= 4:
                    should_check = True
                    break

    if not should_check:
        stats["skipped_too_early"] += 1
        return

    # Find the matching CommentDraft via the slot's draft_id or thread_id
    draft = None
    if slot.draft_id:
        draft = db.query(CommentDraft).filter(CommentDraft.id == slot.draft_id).first()
    elif opportunity.thread_id:
        # Fallback: find draft by thread_id + avatar_id + posted status
        draft = (
            db.query(CommentDraft)
            .filter(
                CommentDraft.thread_id == opportunity.thread_id,
                CommentDraft.avatar_id == opportunity.avatar_id,
                CommentDraft.status == "posted",
            )
            .order_by(CommentDraft.posted_at.desc())
            .first()
        )

    if not draft:
        # No draft found — can't determine karma
        stats["skipped_no_slot"] += 1
        return

    # Update opportunity with actual outcomes
    actual_karma = draft.reddit_score if draft.reddit_score is not None else 0
    actual_removal = draft.is_deleted

    opportunity.actual_karma = actual_karma
    opportunity.actual_removal = actual_removal
    opportunity.outcome_checked_at = now

    # Update opportunity status to 'executed' if not already
    if opportunity.status == "selected":
        opportunity.status = "executed"

    stats["updated"] += 1

    # Compute deviation from expected return
    _compute_and_log_deviation(opportunity, actual_karma, stats)

    db.commit()


def _compute_and_log_deviation(opportunity, actual_karma: int, stats: dict):
    """Compute deviation percentage and log model_correction_event if |deviation| > 50%.

    deviation_percentage = ((actual - expected) / expected) × 100
    """
    if not opportunity.expected_return:
        return

    expected_karma = opportunity.expected_return.get("karma")
    if expected_karma is None or expected_karma == 0:
        # Can't compute deviation with zero or missing expected karma
        # If expected was 0 and actual is non-zero, log it as significant
        if expected_karma == 0 and actual_karma != 0:
            logger.info(
                "model_correction_event: opportunity=%s expected_karma=0 actual_karma=%d "
                "(cannot compute percentage deviation, but notable difference)",
                opportunity.id, actual_karma,
            )
            stats["corrections"] += 1
        return

    deviation_percentage = ((actual_karma - expected_karma) / expected_karma) * 100

    if abs(deviation_percentage) > 50:
        stats["corrections"] += 1
        logger.warning(
            "model_correction_event: opportunity=%s avatar_id=%s subreddit=%s "
            "expected_karma=%d actual_karma=%d deviation=%.1f%% "
            "thread_id=%s decision_date=%s",
            opportunity.id,
            opportunity.avatar_id,
            opportunity.subreddit,
            expected_karma,
            actual_karma,
            deviation_percentage,
            opportunity.thread_id,
            opportunity.decision_date,
        )
