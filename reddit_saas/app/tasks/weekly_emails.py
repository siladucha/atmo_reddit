"""Weekly email digest tasks — system health (admin) + business summary (partner).

Schedule: Sunday 19:00 Israel time (via beat_app.py).
"""

from app.logging_config import get_logger
from app.tasks.worker import celery_app

logger = get_logger(__name__)


@celery_app.task(name="send_weekly_system_health_email", bind=True, max_retries=1)
def send_weekly_system_health_email(self):
    """Send weekly system health report to owner/admin emails."""
    try:
        from app.services.client_emails import send_weekly_system_health_report

        result = send_weekly_system_health_report()
        logger.info("Weekly system health email: sent=%s", result)
        return {"status": "sent" if result else "no_recipients"}
    except Exception as e:
        logger.error("Weekly system health email failed: %s", e, exc_info=True)
        raise self.retry(exc=e, countdown=300)


@celery_app.task(name="send_weekly_business_summary_email", bind=True, max_retries=1)
def send_weekly_business_summary_email(self):
    """Send weekly business summary to partner emails."""
    try:
        from app.services.client_emails import send_weekly_business_summary

        result = send_weekly_business_summary()
        logger.info("Weekly business summary email: sent=%s", result)
        return {"status": "sent" if result else "no_recipients"}
    except Exception as e:
        logger.error("Weekly business summary email failed: %s", e, exc_info=True)
        raise self.retry(exc=e, countdown=300)
