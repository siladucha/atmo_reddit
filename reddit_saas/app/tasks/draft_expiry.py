"""Celery task for automatic expiry of stale comment drafts.

Runs every 60 minutes via Celery Beat. Acquires a distributed lock,
checks the kill switch, then delegates to DraftExpiryService for
the actual expiry processing.

Requirements: 6.1, 6.3, 6.4, 6.5
"""

from app.database import SessionLocal
from app.logging_config import get_logger
from app.services.distributed_lock import DistributedLock
from app.services.settings import get_setting
from app.tasks.worker import celery_app

logger = get_logger(__name__)


@celery_app.task(name="expire_stale_drafts", bind=True)
def expire_stale_drafts(self) -> dict:
    """Scheduled task: acquire lock, check kill switch, run expiry service.

    Requirements:
    - 6.3: Acquire distributed lock (key="expire_stale_drafts_lock", ttl=1800)
    - 6.4: If lock cannot be acquired, log WARNING and skip
    - 6.5: If draft_expiry_enabled is "false", release lock, log, return
    """
    lock = DistributedLock(key="expire_stale_drafts_lock", ttl=1800)

    if not lock.acquire():
        logger.warning(
            "DRAFT_EXPIRY | lock NOT acquired — a previous run is still in progress"
        )
        return {"status": "skipped", "reason": "lock_not_acquired"}

    db = SessionLocal()
    try:
        # Req 6.5: Check kill switch
        enabled = get_setting(db, "draft_expiry_enabled")
        if enabled == "false":
            logger.info("DRAFT_EXPIRY | draft_expiry_enabled=false, skipping")
            return {"status": "disabled"}

        # Delegate to DraftExpiryService
        from app.services.draft_expiry import DraftExpiryService

        result = DraftExpiryService().run(db)
        logger.info(
            "DRAFT_EXPIRY | completed | total_expired=%d | duration_ms=%d",
            result.total_expired,
            result.duration_ms,
        )
        return {
            "status": "completed",
            "total_expired": result.total_expired,
            "approved_expired": result.approved_expired,
            "pending_expired": result.pending_expired,
            "tasks_cancelled": result.tasks_cancelled,
            "duration_ms": result.duration_ms,
        }
    except Exception as e:
        logger.error("DRAFT_EXPIRY | fatal error: %s", str(e)[:200])
        return {"status": "error", "error": str(e)[:200]}
    finally:
        db.close()
        lock.release()
