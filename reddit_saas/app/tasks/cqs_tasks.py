"""Celery task for periodic CQS check task generation.

Sends execution task emails to avatar executors prompting them to post
'What is my cqs?' in r/WhatIsMyCQS. Runs daily at 07:00 Israel time.

Beat schedule entry in worker.py:
  "cqs-check-tasks-daily": crontab(hour=7, minute=0)
"""

from app.logging_config import get_logger

from celery import shared_task

from app.database import SessionLocal

logger = get_logger(__name__)


@shared_task(name="generate_cqs_check_tasks_all_avatars")
def generate_cqs_check_tasks_all_avatars():
    """Daily task: generate CQS check execution tasks for eligible avatars.

    Checks kill switch 'cqs_check_tasks_enabled' before processing.
    Creates task_type='cqs_check' ExecutionTasks that flow through
    the standard dispatch pipeline (dispatch_due_email_tasks → email).
    """
    from app.services.settings import get_setting
    from app.services.cqs_task_generator import generate_cqs_check_tasks

    db = SessionLocal()
    try:
        # Kill switch check
        enabled = get_setting(db, "cqs_check_tasks_enabled")
        if enabled not in ("true", "True", "1", None):
            # None = not configured = default enabled
            if enabled is not None:
                logger.info(
                    "generate_cqs_check_tasks_all_avatars: disabled (cqs_check_tasks_enabled=%s)",
                    enabled,
                )
                return {"status": "disabled", "reason": "cqs_check_tasks_enabled != true"}

        logger.info("generate_cqs_check_tasks_all_avatars: starting")

        summary = generate_cqs_check_tasks(db)

        logger.info(
            "generate_cqs_check_tasks_all_avatars: complete | created=%d | errors=%d | duration_ms=%d",
            summary["created"], summary["errors"], summary["duration_ms"],
        )

        return summary

    except Exception as e:
        logger.error("generate_cqs_check_tasks_all_avatars failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()
