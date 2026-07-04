"""Extension lease management Celery tasks.

Handles:
- Expiring stale task leases (ASSIGNED/EXECUTING past lease_expires_at)
- Re-creating expired diagnostic tasks
- Email fallback for expired content tasks
"""

from app.logging_config import get_logger
from app.tasks.worker import celery_app
from app.database import SessionLocal
from app.services.extension_dispatcher import expire_stale_leases

logger = get_logger(__name__)


@celery_app.task(name="expire_extension_leases")
def expire_extension_leases():
    """Find ASSIGNED/EXECUTING tasks past lease_expires_at and mark EXPIRED.

    Runs every 5 minutes via Celery Beat.

    Expired diagnostic tasks: re-created (new task with fresh lease).
    Expired content tasks: fall back to email delivery.
    """
    db = SessionLocal()
    try:
        expired_tasks = expire_stale_leases(db)

        if not expired_tasks:
            return {"expired": 0}

        recreated = 0
        email_fallback = 0

        for task in expired_tasks:
            if task.priority == "diagnostic":
                # Re-create diagnostic task (CQS check etc.)
                _recreate_diagnostic_task(db, task)
                recreated += 1
            else:
                # Content task — fall back to email if executor has email
                _fallback_to_email(db, task)
                email_fallback += 1

        db.commit()

        logger.info(
            "EXPIRE_EXTENSION_LEASES | expired=%d | recreated=%d | email_fallback=%d",
            len(expired_tasks), recreated, email_fallback,
        )
        return {
            "expired": len(expired_tasks),
            "recreated": recreated,
            "email_fallback": email_fallback,
        }
    except Exception as e:
        logger.error("expire_extension_leases error: %s", str(e)[:200], exc_info=True)
        db.rollback()
        return {"error": str(e)[:200]}
    finally:
        db.close()


def _recreate_diagnostic_task(db, expired_task):
    """Re-create an expired diagnostic task with fresh lease.

    Only re-creates if there's no other pending task for the same avatar+probe_type.
    """
    from app.models.execution_task import ExecutionTask

    # Check if another task already exists for this avatar + probe
    existing = (
        db.query(ExecutionTask)
        .filter(
            ExecutionTask.avatar_id == expired_task.avatar_id,
            ExecutionTask.probe_type == expired_task.probe_type,
            ExecutionTask.task_lifecycle_status.in_(["CREATED", "ASSIGNED", "EXECUTING"]),
        )
        .first()
    )

    if existing:
        return  # Another task already active, don't duplicate

    from app.services.extension_dispatcher import create_extension_task

    create_extension_task(
        db=db,
        avatar_id=expired_task.avatar_id,
        task_type=expired_task.task_type,
        task_data={
            "avatar_username": expired_task.avatar_username,
            "subreddit": expired_task.subreddit,
            "thread_url": expired_task.thread_url,
            "thread_title": expired_task.thread_title,
            "comment_text": expired_task.generated_text,
            "scheduled_at": expired_task.scheduled_at,
            "client_id": expired_task.client_id,
            "client_name": expired_task.client_name,
            "executor_contact": expired_task.executor_contact,
        },
        probe_type=expired_task.probe_type,
    )


def _fallback_to_email(db, expired_task):
    """Fall back to email delivery for an expired content task.

    Updates the task's delivery_channel to 'email' and resets status
    for the existing email dispatch pipeline to pick it up.
    """
    from app.models.avatar import Avatar

    # Only fallback if avatar has a verified email
    if expired_task.avatar_id:
        avatar = db.query(Avatar).filter(Avatar.id == expired_task.avatar_id).first()
        if avatar and avatar.executor_email and avatar.executor_email_verified:
            expired_task.delivery_channel = "email"
            expired_task.status = "generated"
            expired_task.task_lifecycle_status = None  # Remove from extension lifecycle
            expired_task.execution_node_id = None
            expired_task.executor_contact = avatar.executor_email
            logger.info(
                "EXTENSION_EMAIL_FALLBACK | task=%s | avatar=%s",
                expired_task.task_code, expired_task.avatar_username,
            )
