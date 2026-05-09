"""Celery tasks for avatar subreddit presence scanning."""

import logging

from app.database import SessionLocal
from app.tasks.worker import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="scan_avatar_presence", bind=True, max_retries=3)
def scan_avatar_presence_task(self, avatar_id: str):
    """Async task: fetch avatar's Reddit comments, aggregate by subreddit, persist.

    Sets presence_scan_status to "running" at start, "completed" on success,
    "failed" on error. Retries with exponential backoff (60s × 2^attempt).
    """
    import uuid

    from app.models.avatar import Avatar

    db = SessionLocal()
    try:
        avatar_uuid = uuid.UUID(avatar_id)

        # Mark as running
        avatar = db.query(Avatar).filter(Avatar.id == avatar_uuid).first()
        if not avatar:
            logger.error(
                "scan_avatar_presence_task: avatar not found | avatar_id=%s", avatar_id
            )
            return {"error": "avatar_not_found"}

        avatar.presence_scan_status = "running"
        db.commit()

        logger.info(
            "scan_avatar_presence_task: starting | avatar_id=%s | username=%s",
            avatar_id,
            avatar.reddit_username,
        )

        # Execute the scan
        from app.services.presence import scan_avatar_presence

        records = scan_avatar_presence(db, avatar_uuid)

        logger.info(
            "scan_avatar_presence_task: completed | avatar_id=%s | subreddits=%d",
            avatar_id,
            len(records),
        )

        return {"status": "completed", "subreddits": len(records)}

    except Exception as exc:
        logger.error(
            "scan_avatar_presence_task: failed | avatar_id=%s | error=%s",
            avatar_id,
            exc,
        )
        try:
            countdown = 60 * (2 ** self.request.retries)
            raise self.retry(exc=exc, countdown=countdown)
        except self.MaxRetriesExceededError:
            logger.error(
                "scan_avatar_presence_task: max retries exceeded | avatar_id=%s", avatar_id
            )
            return {"error": str(exc)}
    finally:
        db.close()


@celery_app.task(name="scan_all_avatars_presence", bind=True, max_retries=1)
def scan_all_avatars_presence_task(self):
    """Weekly scheduled task: scan presence for all active, non-frozen avatars.

    Dispatches individual scan_avatar_presence_task for each eligible avatar.
    """
    from app.models.avatar import Avatar

    db = SessionLocal()
    try:
        avatars = (
            db.query(Avatar)
            .filter(
                Avatar.active.is_(True),
                Avatar.is_frozen.is_(False),
            )
            .all()
        )

        dispatched = 0
        skipped = 0

        for avatar in avatars:
            # Skip avatars already being scanned
            if avatar.presence_scan_status in ("pending", "running"):
                skipped += 1
                continue

            avatar.presence_scan_status = "pending"
            scan_avatar_presence_task.delay(str(avatar.id))
            dispatched += 1

        db.commit()

        logger.info(
            "scan_all_avatars_presence_task: batch dispatched | total=%d | dispatched=%d | skipped=%d",
            len(avatars),
            dispatched,
            skipped,
        )

        return {"dispatched": dispatched, "skipped": skipped}

    except Exception as exc:
        logger.error(
            "scan_all_avatars_presence_task: failed | error=%s", exc
        )
        try:
            raise self.retry(exc=exc, countdown=300)
        except self.MaxRetriesExceededError:
            return {"error": str(exc)}
    finally:
        db.close()
