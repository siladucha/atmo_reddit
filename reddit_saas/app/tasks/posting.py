"""Celery tasks for automated posting.

Tasks:
- execute_pending_posts: Periodic (every 5 min) — finds approved slots due for posting
- post_comment: Per-slot task — executes the full posting flow with retry

Integration:
- Registered in app/tasks/worker.py
- Beat schedule: execute_pending_posts every 300s
- Redis distributed lock per avatar (prevents concurrent posting)
"""

import logging
import uuid
from datetime import datetime, timezone

from celery import shared_task

from app.database import SessionLocal
from app.services.distributed_lock import DistributedLock

logger = logging.getLogger(__name__)

# Lock settings
POSTING_LOCK_PREFIX = "posting_lock:"
POSTING_LOCK_TTL = 300  # 5 minutes — enough for one post + retries


@shared_task(name="execute_pending_posts")
def execute_pending_posts():
    """Periodic task (every 5 min): find approved EPG slots due for posting.

    Dispatches individual post_comment tasks for each eligible slot.
    Respects minimum interval (45 min) between posts for same avatar.
    """
    from app.models.avatar import Avatar
    from app.models.epg_slot import EPGSlot
    from app.services.settings import get_setting
    from app.services.timing_engine import should_dispatch_slot

    db = SessionLocal()
    try:
        # Check global kill switch first
        auto_posting_enabled = get_setting(db, "auto_posting_enabled")
        if auto_posting_enabled in ("false", "False", "0"):
            logger.info("execute_pending_posts: global kill switch OFF, skipping")
            return {"dispatched": 0, "reason": "kill_switch_off"}

        now = datetime.now(timezone.utc)

        # Find approved slots with scheduled_at in the past
        pending_slots = (
            db.query(EPGSlot)
            .filter(
                EPGSlot.status == "approved",
                EPGSlot.scheduled_at <= now,
                EPGSlot.draft_id.isnot(None),
            )
            .order_by(EPGSlot.scheduled_at.asc())
            .limit(50)  # Process max 50 per tick to avoid overload
            .all()
        )

        if not pending_slots:
            return {"dispatched": 0, "reason": "no_pending_slots"}

        dispatched = 0
        skipped = 0

        for slot in pending_slots:
            # Load avatar for interval check
            avatar = db.query(Avatar).filter(Avatar.id == slot.avatar_id).first()
            if not avatar:
                logger.warning("Slot %s: avatar not found, skipping", slot.id)
                skipped += 1
                continue

            # Check if avatar is eligible (basic checks before dispatching)
            if avatar.posting_mode != "auto":
                skipped += 1
                continue
            if avatar.is_frozen:
                skipped += 1
                continue

            # Check minimum interval
            if not should_dispatch_slot(avatar, slot.scheduled_at, now):
                skipped += 1
                continue

            # Dispatch individual posting task
            post_comment.delay(str(slot.id))
            dispatched += 1

        logger.info(
            "execute_pending_posts: dispatched=%d, skipped=%d, total_pending=%d",
            dispatched, skipped, len(pending_slots),
        )
        return {"dispatched": dispatched, "skipped": skipped}

    except Exception as e:
        logger.error("execute_pending_posts failed: %s", e, exc_info=True)
        return {"dispatched": 0, "error": str(e)}
    finally:
        db.close()


@shared_task(
    name="post_comment",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def post_comment(self, epg_slot_id: str):
    """Execute a single comment post with retry on transient errors.

    Acquires Redis distributed lock per avatar before posting.
    Exponential backoff: 60s × 2^attempt.

    Args:
        epg_slot_id: UUID string of the EPG slot to post
    """
    from app.models.avatar import Avatar
    from app.models.epg_slot import EPGSlot
    from app.services.posting import execute_post, PostingRefused
    from app.services.praw_factory import PostingConfigError

    db = SessionLocal()
    try:
        slot_uuid = uuid.UUID(epg_slot_id)

        # Load slot to get avatar_id for lock
        slot = db.query(EPGSlot).filter(EPGSlot.id == slot_uuid).first()
        if not slot:
            logger.error("post_comment: slot %s not found", epg_slot_id)
            return {"outcome": "error", "reason": "slot_not_found"}

        # Check slot hasn't been posted already (idempotency)
        if slot.status == "posted":
            logger.info("post_comment: slot %s already posted, skipping", epg_slot_id)
            return {"outcome": "skipped", "reason": "already_posted"}

        avatar_id = str(slot.avatar_id)

        # Acquire distributed lock per avatar
        lock = DistributedLock(
            key=f"{POSTING_LOCK_PREFIX}{avatar_id}",
            ttl=POSTING_LOCK_TTL,
        )

        if not lock.acquire():
            # Another post in progress for this avatar — retry later
            logger.info("post_comment: lock held for avatar %s, retrying", avatar_id)
            raise self.retry(countdown=60)

        try:
            # Execute the full posting flow
            event = execute_post(db, slot_uuid)
            return {
                "outcome": event.outcome,
                "avatar": avatar_id,
                "reddit_comment_id": event.reddit_comment_id,
                "duration_ms": event.duration_ms,
            }

        except PostingRefused as e:
            # Non-retryable — safety gate or auth error
            logger.info("post_comment refused: %s", e.reason)

            # Mark slot as skipped if not already handled
            if slot.status == "approved":
                slot.status = "skipped"
                slot.skip_reason = e.reason[:255]
                db.commit()

            return {"outcome": "refused", "reason": e.reason}

        except PostingConfigError as e:
            # Configuration error — non-retryable
            logger.error("post_comment config error: %s", e)
            if slot.status == "approved":
                slot.status = "skipped"
                slot.skip_reason = f"config_error: {str(e)[:200]}"
                db.commit()
            return {"outcome": "config_error", "reason": str(e)}

        except Exception as e:
            # Transient error — retry with exponential backoff
            attempt = self.request.retries
            countdown = 60 * (2 ** attempt)  # 60, 120, 240

            logger.warning(
                "post_comment transient error (attempt %d/%d): %s. Retrying in %ds",
                attempt + 1, self.max_retries, str(e)[:200], countdown,
            )

            if attempt >= self.max_retries:
                # All retries exhausted — mark slot as skipped
                if slot.status == "approved":
                    slot.status = "skipped"
                    slot.skip_reason = "posting_failed_after_retries"
                    db.commit()
                logger.error("post_comment: all retries exhausted for slot %s", epg_slot_id)
                return {"outcome": "failed", "reason": "retries_exhausted"}

            raise self.retry(exc=e, countdown=countdown)

        finally:
            lock.release()

    except self.MaxRetriesExceededError:
        logger.error("post_comment: max retries exceeded for slot %s", epg_slot_id)
        return {"outcome": "failed", "reason": "max_retries_exceeded"}
    finally:
        db.close()
