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
    """Send emails for execution tasks whose scheduled_at is within the next 30 minutes.

    Runs every 5 minutes via Beat. Ensures executor gets ONE email at a time,
    close to when they need to act — not a batch dump.

    Logic:
    - Find execution_tasks with status='generated' (created but not yet emailed)
    - Where the linked EPG slot's scheduled_at is between now and now+30 min
    - Skip tasks where scheduled_at is more than 30 min in the past (stale)
    - Dispatch one email per task
    """
    import uuid
    from datetime import datetime, timedelta, timezone

    from app.models.execution_task import ExecutionTask

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=5)  # Small grace period for just-passed slots
        window_end = now + timedelta(minutes=30)

        # Find tasks that are generated (not yet emailed) and due soon
        due_tasks = (
            db.query(ExecutionTask)
            .filter(
                ExecutionTask.status == "generated",
                ExecutionTask.delivery_count == 0,  # Never emailed
                ExecutionTask.scheduled_at.isnot(None),
                ExecutionTask.scheduled_at >= window_start,
                ExecutionTask.scheduled_at <= window_end,
            )
            .order_by(ExecutionTask.scheduled_at.asc())
            .all()
        )

        if not due_tasks:
            return {"dispatched": 0, "reason": "no_due_tasks"}

        dispatched = 0
        for task in due_tasks:
            try:
                deliver_execution_task.delay(str(task.id), 1)
                dispatched += 1
                logger.info(
                    "Dispatched email for task %s (avatar=%s, scheduled=%s)",
                    task.task_code, task.avatar_username, task.scheduled_at,
                )
            except Exception as e:
                logger.warning("Failed to dispatch task %s: %s", task.task_code, str(e)[:100])

        logger.info("dispatch_due_email_tasks: dispatched=%d of %d due", dispatched, len(due_tasks))
        return {"dispatched": dispatched, "total_due": len(due_tasks)}

    except Exception as e:
        logger.error("dispatch_due_email_tasks failed: %s", e, exc_info=True)
        return {"error": str(e)}
    finally:
        db.close()
