"""Celery task for periodic avatar health checks (shadowban/suspension detection)."""

import logging

from app.tasks.worker import celery_app
from app.database import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="health_check_all_avatars", bind=True, max_retries=1)
def health_check_all_avatars(self):
    """Periodic task: run health checks for all eligible avatars.

    Calls run_health_check_batch which:
    - Selects eligible avatars (active, not frozen, stale or never checked)
    - Performs profile accessibility + visibility checks per avatar
    - Classifies health status and persists results
    - Auto-freezes shadowbanned/suspended avatars
    - Logs batch summary with duration, checked count, errors, status changes
    """
    db = SessionLocal()
    try:
        from app.services.health_checker import run_health_check_batch

        logger.info("health_check_all_avatars: starting batch health check")

        summary = run_health_check_batch(db)

        logger.info(
            "health_check_all_avatars: batch complete | checked=%d | changed=%d | "
            "errors=%d | duration_ms=%d",
            summary["checked"],
            summary["changed"],
            summary["errors"],
            summary["duration_ms"],
        )

        return summary

    except Exception as exc:
        logger.error("health_check_all_avatars: task failed | error=%s", exc)
        try:
            raise self.retry(exc=exc, countdown=300)
        except self.MaxRetriesExceededError:
            logger.error(
                "health_check_all_avatars: max retries exceeded | error=%s", exc
            )
            return {"error": str(exc)}
    finally:
        db.close()
