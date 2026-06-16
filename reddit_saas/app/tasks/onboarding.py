"""Celery tasks for onboarding — avatar onboarding orchestration.

Triggered when an avatar is assigned to a client that has completed onboarding.
"""

from app.logging_config import get_logger
from celery import shared_task
from app.database import SessionLocal

logger = get_logger(__name__)


@shared_task(name="run_avatar_onboarding", bind=True, max_retries=1)
def run_avatar_onboarding(self, avatar_id: str, client_id: str):
    """Run full avatar onboarding: Discovery → Strategy → Pipeline.

    Called automatically when avatar is assigned to an onboarded client.
    Retries once on transient failure.
    """
    import uuid
    from app.services.onboarding.avatar_onboarding import trigger_avatar_onboarding

    db = SessionLocal()
    try:
        result = trigger_avatar_onboarding(
            db=db,
            avatar_id=uuid.UUID(avatar_id),
            client_id=uuid.UUID(client_id),
        )
        logger.info(
            "Avatar onboarding task complete: avatar=%s result=%s",
            avatar_id, result,
        )
        return result
    except Exception as e:
        logger.error("Avatar onboarding task failed: avatar=%s error=%s", avatar_id, e)
        raise self.retry(countdown=120, exc=e)
    finally:
        db.close()
