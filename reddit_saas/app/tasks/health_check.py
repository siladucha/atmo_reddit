"""Celery task for periodic avatar health checks (shadowban/suspension detection)."""

from app.logging_config import get_logger

from app.tasks.worker import celery_app
from app.database import SessionLocal

logger = get_logger(__name__)


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


@celery_app.task(name="check_cqs_all_avatars", bind=True, max_retries=1)
def check_cqs_all_avatars(self):
    """Periodic task: check CQS (Contributor Quality Score) for all eligible avatars.

    Calls run_cqs_check_batch which:
    - Selects eligible avatars (active, not frozen, Phase 2+, stale or never checked)
    - Reads bot replies in r/WhatIsMyCQS for each avatar
    - Updates cqs_level and cqs_checked_at
    - Auto-freezes avatars that drop to CQS lowest (Phase 2+ only)
    - Logs batch summary
    """
    db = SessionLocal()
    try:
        from app.services.cqs_checker import run_cqs_check_batch

        logger.info("check_cqs_all_avatars: starting batch CQS check")

        summary = run_cqs_check_batch(db)

        logger.info(
            "check_cqs_all_avatars: batch complete | checked=%d | updated=%d | "
            "frozen=%d | errors=%d | skipped=%d | duration_ms=%d",
            summary["checked"],
            summary["updated"],
            summary["frozen"],
            summary["errors"],
            summary["skipped"],
            summary["duration_ms"],
        )

        return summary

    except Exception as exc:
        logger.error("check_cqs_all_avatars: task failed | error=%s", exc)
        try:
            raise self.retry(exc=exc, countdown=600)
        except self.MaxRetriesExceededError:
            logger.error(
                "check_cqs_all_avatars: max retries exceeded | error=%s", exc
            )
            return {"error": str(exc)}
    finally:
        db.close()
