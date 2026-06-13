"""Celery task: run_feedback_loop — closes the outcome → adjustment cycle.

Runs after snapshot_comment_outcomes completes. Takes outcome data and:
- Updates Discovery hypothesis confidence based on actual engagement
- Stores EPG subreddit priority adjustments
- Prepares performance context for next strategy generation

Schedule: Daily at 02:00 (after day's outcomes have been collected).
Also triggered on-demand via admin.
"""

from celery import shared_task

from app.database import SessionLocal
from app.logging_config import get_logger

logger = get_logger(__name__)


@shared_task(name="run_feedback_loop_all")
def run_feedback_loop_all():
    """Run feedback loop for all avatars with sufficient posting history.

    This is the main Celery Beat entry point for the feedback layer.
    Processes all avatars with 3+ posted comments.
    """
    from app.services.feedback_loop import run_feedback_loop_all_avatars

    db = SessionLocal()
    try:
        results = run_feedback_loop_all_avatars(db)
        logger.info("run_feedback_loop_all complete: %s", results)
        return results
    except Exception as e:
        logger.error("run_feedback_loop_all failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


@shared_task(name="run_feedback_loop_single")
def run_feedback_loop_single(avatar_id: str):
    """Run feedback loop for a single avatar (on-demand or per-avatar trigger)."""
    import uuid
    from app.services.feedback_loop import run_feedback_loop

    db = SessionLocal()
    try:
        result = run_feedback_loop(db, uuid.UUID(avatar_id))
        return result
    except Exception as e:
        logger.error("run_feedback_loop_single failed for %s: %s", avatar_id, e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()
