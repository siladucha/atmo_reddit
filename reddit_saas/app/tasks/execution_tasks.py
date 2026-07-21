"""Celery tasks for execution task delivery.

Tasks:
- deliver_execution_task: Send email for an execution task (async, retryable)
- expire_overdue_execution_tasks: Daily cleanup for tasks past deadline

Beat schedule:
- expire_overdue_execution_tasks: daily at 23:30
"""

from app.logging_config import get_logger

from celery import shared_task

from app.database import SessionLocal

logger = get_logger(__name__)


@shared_task(name="deliver_execution_task", bind=True, max_retries=3)
def deliver_execution_task(self, task_id: str, attempt_number: int):
    """Send delivery for an execution task. Retry on SMTP failure.

    Args:
        task_id: UUID string of the ExecutionTask
        attempt_number: Which delivery attempt this is (1-based)
    """
    import uuid
    from app.services.execution_tasks import dispatch_delivery

    db = SessionLocal()
    try:
        result = dispatch_delivery(db, uuid.UUID(task_id))
        if result and result.status == "sent":
            logger.info(
                "Delivery successful: task=%s attempt=%d recipient=%s",
                task_id[:8], attempt_number, result.recipient,
            )
            return {"status": "sent", "task_id": task_id, "attempt": attempt_number}
        elif result and result.status == "failed":
            # Retry with exponential backoff
            countdown = 60 * (2 ** self.request.retries)
            logger.warning(
                "Delivery failed for task %s, retrying in %ds (attempt %d/%d)",
                task_id[:8], countdown, self.request.retries + 1, self.max_retries,
            )
            raise self.retry(countdown=countdown)
        else:
            # Anti-spam blocked or other issue — don't retry
            logger.info("Delivery skipped for task %s (anti-spam or invalid state)", task_id[:8])
            return {"status": "skipped", "task_id": task_id}

    except self.MaxRetriesExceededError:
        logger.error("Max retries exceeded for task %s delivery", task_id[:8])
        return {"status": "max_retries_exceeded", "task_id": task_id}
    except Exception as e:
        if self.request.retries < self.max_retries:
            countdown = 60 * (2 ** self.request.retries)
            logger.warning("Delivery error for task %s: %s. Retrying in %ds", task_id[:8], str(e)[:100], countdown)
            raise self.retry(countdown=countdown, exc=e)
        logger.error("Delivery permanently failed for task %s: %s", task_id[:8], str(e)[:200])
        return {"status": "error", "task_id": task_id, "error": str(e)[:200]}
    finally:
        db.close()


@shared_task(name="expire_overdue_execution_tasks")
def expire_overdue_execution_tasks():
    """Expire execution tasks past their deadline. Runs daily at 23:30."""
    from app.services.execution_tasks import expire_overdue_tasks

    db = SessionLocal()
    try:
        count = expire_overdue_tasks(db)
        logger.info("Expired %d overdue execution tasks", count)
        return {"expired": count}
    except Exception as e:
        logger.error("expire_overdue_execution_tasks failed: %s", e, exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()


@shared_task(name="dispatch_due_email_tasks")
def dispatch_due_email_tasks():
    """Send emails for execution tasks whose posting window has opened.

    Soft deadline model: each task has a window (scheduled_at → deadline).
    Email goes out when window opens. Executor posts any time before deadline.

    Runs every 5 minutes via Beat.

    Logic:
    - Find execution_tasks with status='generated' (created but not yet emailed)
    - Where scheduled_at <= now (window has opened) AND deadline > now (window still open)
    - CHECK QUIET HOURS before sending (defer if outside 07:00-23:00 Israel time)
    - CHECK AVATAR HEALTH before sending (cancel if frozen/shadowbanned/suspended)
    - CHECK THREAD LIVENESS before sending (cancel if locked/removed/archived)
    - Dispatch one email per task
    """
    import uuid
    from datetime import datetime, timedelta, timezone

    from zoneinfo import ZoneInfo
    import sqlalchemy as sa
    from sqlalchemy import func as sa_func

    from app.models.avatar import Avatar
    from app.models.execution_task import ExecutionTask
    from app.models.thread import RedditThread

    # Quiet hours: no emails between 23:00 and 07:00 Israel time
    QUIET_HOUR_START = 23
    QUIET_HOUR_END = 7

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        # Soft deadline model: email goes out as soon as window opens (scheduled_at ≤ now).
        # Executor has until `deadline` (window_end) to post.
        # Grace period: also catch tasks whose window opened up to 5 min ago (beat tick alignment).
        window_start = now - timedelta(minutes=5)

        # --- Quiet hours gate ---
        israel_tz = ZoneInfo("Asia/Jerusalem")
        now_israel = now.astimezone(israel_tz)
        current_hour = now_israel.hour

        if current_hour >= QUIET_HOUR_START or current_hour < QUIET_HOUR_END:
            logger.info(
                "dispatch_due_email_tasks: quiet hours (%02d:00-%02d:00 Israel), "
                "current=%02d:%02d. Deferring.",
                QUIET_HOUR_START, QUIET_HOUR_END, now_israel.hour, now_israel.minute,
            )
            return {"dispatched": 0, "reason": "quiet_hours", "local_time": now_israel.strftime("%H:%M")}

        # Find tasks whose window has opened: scheduled_at <= now (with 5 min grace)
        # and deadline not yet passed (still within soft window)
        due_tasks = (
            db.query(ExecutionTask)
            .filter(
                ExecutionTask.status == "generated",
                ExecutionTask.delivery_count == 0,  # Never emailed
                ExecutionTask.scheduled_at.isnot(None),
                ExecutionTask.scheduled_at <= now,          # Window has opened
                ExecutionTask.scheduled_at >= window_start,  # Not too stale (opened within last 5 min)
                sa.or_(
                    ExecutionTask.deadline.is_(None),
                    ExecutionTask.deadline > now,            # Window still open
                ),
            )
            .order_by(ExecutionTask.scheduled_at.asc())
            .all()
        )

        if not due_tasks:
            return {"dispatched": 0, "reason": "no_due_tasks"}

        dispatched = 0
        cancelled_locked = 0
        cancelled_health = 0
        skipped_extension = 0

        # --- Extension-first routing ---
        # If a browser extension node is online for this avatar's Reddit account,
        # skip email delivery — the extension will pick up the task via polling.
        # This implements the "extension-first, email-fallback" routing strategy.
        _extension_available_cache: dict[str, bool] = {}
        try:
            from app.models.execution_node import ExecutionNode as _ExtNode
            _extension_check_enabled = True
        except Exception:
            # Extension feature not yet deployed — fall through to email gracefully
            _extension_check_enabled = False

        # Cache avatar health (avoid repeated queries for same avatar)
        _avatar_health_cache: dict[str, bool] = {}

        for task in due_tasks:
            try:
                # --- Extension availability check ---
                # If extension is handling this task (already ASSIGNED/EXECUTING), skip email
                if _extension_check_enabled:
                    if task.task_lifecycle_status in ("ASSIGNED", "EXECUTING"):
                        skipped_extension += 1
                        logger.debug(
                            "Skipping email for task %s: extension already handling (status=%s)",
                            task.task_code, task.task_lifecycle_status,
                        )
                        continue

                    # Check if an online extension node exists for this avatar's account
                    username = task.avatar_username
                    if username and username not in _extension_available_cache:
                        try:
                            heartbeat_threshold = now - timedelta(minutes=30)
                            online_node = (
                                db.query(_ExtNode)
                                .filter(
                                    _ExtNode.is_online.is_(True),
                                    _ExtNode.last_heartbeat >= heartbeat_threshold,
                                    sa_func.lower(_ExtNode.active_reddit_username)
                                    == username.lower(),
                                )
                                .first()
                            )
                            _extension_available_cache[username] = online_node is not None
                        except Exception as ext_err:
                            logger.debug(
                                "Extension availability check failed for %s: %s",
                                username, str(ext_err)[:80],
                            )
                            _extension_available_cache[username] = False

                    if _extension_available_cache.get(username, False):
                        # Convert task to extension delivery
                        task.delivery_channel = "extension"
                        task.task_lifecycle_status = "CREATED"
                        task.priority = "content"
                        # Generate HMAC + idempotency if not set
                        if not task.idempotency_key:
                            import uuid as _uuid
                            task.idempotency_key = str(_uuid.uuid4())
                        if not task.task_hash:
                            try:
                                from app.services.extension_dispatcher import compute_task_hash
                                from app.config import get_config
                                hmac_secret = get_config("extension_hmac_secret")
                                if hmac_secret:
                                    task.task_hash = compute_task_hash(
                                        secret=hmac_secret,
                                        idempotency_key=task.idempotency_key,
                                        task_type="post_comment",
                                        avatar_username=task.avatar_username,
                                        target=task.thread_url or "",
                                    )
                            except Exception:
                                pass
                        if not task.lease_expires_at:
                            task.lease_expires_at = now + timedelta(minutes=30)
                        db.commit()
                        skipped_extension += 1
                        logger.info(
                            "Task %s converted to extension delivery for %s",
                            task.task_code, username,
                        )
                        continue

                # --- Pre-dispatch avatar health check ---
                avatar_id_str = str(task.avatar_id) if task.avatar_id else None
                if avatar_id_str:
                    if avatar_id_str not in _avatar_health_cache:
                        avatar = db.query(Avatar).filter(Avatar.id == task.avatar_id).first()
                        if avatar:
                            is_eligible = (
                                not avatar.is_frozen
                                and not avatar.is_shadowbanned
                                and getattr(avatar, "health_status", "unknown") not in ("shadowbanned", "suspended")
                                and getattr(avatar, "active", True)
                            )
                            _avatar_health_cache[avatar_id_str] = is_eligible
                        else:
                            _avatar_health_cache[avatar_id_str] = False

                    if not _avatar_health_cache.get(avatar_id_str, False):
                        from app.services.execution_tasks import cancel_task
                        cancel_task(db, task.id, "avatar_unhealthy_at_dispatch")
                        cancelled_health += 1
                        logger.info(
                            "Cancelled task %s: avatar %s unhealthy at dispatch",
                            task.task_code, task.avatar_username,
                        )
                        continue

                # --- Pre-dispatch liveness check ---
                if task.thread_id:
                    thread = db.query(RedditThread).filter(RedditThread.id == task.thread_id).first()
                    if thread:
                        if thread.is_locked:
                            _cancel_task_as_locked(db, task, "thread_already_locked")
                            cancelled_locked += 1
                            continue

                        from app.services.thread_liveness import is_thread_stale, refresh_thread_locked_status
                        if is_thread_stale(thread):
                            is_open = refresh_thread_locked_status(db, thread)
                            if not is_open:
                                _cancel_task_as_locked(db, task, "thread_locked_on_liveness_check")
                                cancelled_locked += 1
                                continue

                deliver_execution_task.delay(str(task.id), 1)
                dispatched += 1
                logger.info(
                    "Dispatched email for task %s (avatar=%s, scheduled=%s)",
                    task.task_code, task.avatar_username, task.scheduled_at,
                )
            except Exception as e:
                logger.warning("Failed to dispatch task %s: %s", task.task_code, str(e)[:100])

        logger.info(
            "dispatch_due_email_tasks: dispatched=%d, cancelled_locked=%d, "
            "cancelled_health=%d, skipped_extension=%d, total_due=%d",
            dispatched, cancelled_locked, cancelled_health, skipped_extension, len(due_tasks),
        )
        return {
            "dispatched": dispatched,
            "cancelled_locked": cancelled_locked,
            "cancelled_health": cancelled_health,
            "skipped_extension": skipped_extension,
            "total_due": len(due_tasks),
        }

    except Exception as e:
        logger.error("dispatch_due_email_tasks failed: %s", e, exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()


def _cancel_task_as_locked(db, task, reason: str):
    """Cancel an execution task because its thread is locked/removed/archived.

    Also cancels the linked draft and EPG slot to keep pipeline consistent.
    """
    from datetime import datetime, timezone
    from app.services.execution_tasks import cancel_task

    cancel_task(db, task.id, reason)
    logger.info(
        "Cancelled task %s: %s (thread=%s, subreddit=r/%s)",
        task.task_code, reason, task.thread_id, task.subreddit,
    )

    # Also reject the linked draft if still pending/approved (can't be posted)
    if task.draft_id:
        from app.models.comment_draft import CommentDraft
        draft = db.query(CommentDraft).filter(CommentDraft.id == task.draft_id).first()
        if draft and draft.status in ("pending", "approved"):
            draft.status = "rejected"
            db.commit()
            logger.info("Auto-rejected draft %s (thread locked)", task.draft_id)

    # Skip the EPG slot
    if task.epg_slot_id:
        from app.models.epg_slot import EPGSlot
        slot = db.query(EPGSlot).filter(EPGSlot.id == task.epg_slot_id).first()
        if slot and slot.status not in ("posted", "skipped"):
            slot.status = "skipped"
            slot.skip_reason = f"thread_locked: {reason}"
            db.commit()


@shared_task(name="dispatch_approved_post_drafts")
def dispatch_approved_post_drafts():
    """Create execution tasks for approved PostDrafts that don't yet have tasks.

    Runs every 5 min (same cadence as dispatch_due_email_tasks).
    Finds approved PostDrafts without a corresponding ExecutionTask and creates one.
    The execution task is then picked up by the standard dispatch pipeline
    (email or extension, depending on avatar delivery_channel).
    """
    from datetime import datetime, timezone
    from app.models.post_draft import PostDraft
    from app.models.execution_task import ExecutionTask
    from app.services.execution_tasks import create_post_execution_task

    db = SessionLocal()
    try:
        # Find approved post drafts that don't have execution tasks yet
        # We identify "no task" by checking ExecutionTask table for matching
        # avatar_id + task_type="post" + thread_title match
        approved_drafts = (
            db.query(PostDraft)
            .filter(
                PostDraft.status == "approved",
                PostDraft.posted_at.is_(None),  # Not yet posted
            )
            .order_by(PostDraft.created_at.asc())
            .limit(20)  # Process in batches
            .all()
        )

        if not approved_drafts:
            return {"created": 0}

        created = 0
        skipped = 0

        for draft in approved_drafts:
            try:
                task = create_post_execution_task(db, draft.id)
                if task:
                    created += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.warning(
                    "Failed to create post execution task for draft %s: %s",
                    draft.id, str(e)[:100],
                )
                skipped += 1

        if created > 0:
            logger.info(
                "dispatch_approved_post_drafts: created=%d skipped=%d total=%d",
                created, skipped, len(approved_drafts),
            )

        return {"created": created, "skipped": skipped}

    except Exception as e:
        logger.error("dispatch_approved_post_drafts failed: %s", e, exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()
