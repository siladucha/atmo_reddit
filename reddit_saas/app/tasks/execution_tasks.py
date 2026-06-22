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
