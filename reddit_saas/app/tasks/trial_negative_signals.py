"""Celery task: check_trial_negative_signals — periodic negative signal detection.

Runs all time-based negative signal detections for active trial clients:
- 72h inactivity
- Pricing viewed without upgrade (24h window)
- Onboarding abandoned (48h window)
- Export without return (48h window)

Schedule: Every 4h at :30 (Asia/Jerusalem timezone).
"""

from celery import shared_task

from app.database import SessionLocal
from app.logging_config import get_logger

logger = get_logger(__name__)


@shared_task(name="check_trial_negative_signals")
def check_trial_negative_signals():
    """Run time-based negative signal detections for all active trial clients.

    Detections run:
    - detect_inactivity_72h: no signals for 72+ hours
    - detect_pricing_without_upgrade: pricing viewed, no return in 24h
    - detect_onboarding_abandoned: started but not completed in 48h
    - detect_export_without_return: export signal, no activity for 48h

    Returns:
        Summary dict with checked count and signals recorded.
    """
    from app.services.trial_negative_signals import NegativeSignalDetector

    db = SessionLocal()
    try:
        detector = NegativeSignalDetector(db)
        result = detector.run_all_time_based_detections()

        logger.info(
            "check_trial_negative_signals complete: checked=%d, signals_recorded=%d",
            result["checked"],
            result["signals_recorded"],
        )
        return {"status": "ok", **result}

    except Exception as e:
        logger.error("check_trial_negative_signals failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()
