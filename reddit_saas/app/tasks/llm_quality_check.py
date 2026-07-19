"""LLM Quality Check — periodic task to detect model degradation.

Runs every 4 hours. Computes quality metrics for the last 4h window,
compares against 7-day baseline, stores snapshots, and alerts on degradation.
"""

from app.logging_config import get_logger
from app.tasks.worker import celery_app

logger = get_logger(__name__)


@celery_app.task(name="check_llm_quality", bind=True, max_retries=0)
def check_llm_quality(self):
    """Compute LLM quality snapshot and alert on degradation.

    Analyzes the last 4 hours of LLM calls, comparing success rates,
    latency, and fallback frequency against 7-day baselines.
    """
    from app.database import SessionLocal
    from app.services.llm_quality_monitor import compute_quality_snapshot

    db = SessionLocal()
    try:
        snapshots = compute_quality_snapshot(db, window_hours=4)

        if not snapshots:
            logger.info("LLM_QUALITY_CHECK | no data in window | skipping")
            return {"status": "done", "snapshots": 0, "degradations": 0}

        # Store snapshots
        degradation_count = 0
        for snap in snapshots:
            db.add(snap)
            if snap.degradation_detected:
                degradation_count += 1

        db.commit()

        # Alert on degradation
        if degradation_count > 0:
            _send_degradation_alerts(db, snapshots)

        logger.info(
            "LLM_QUALITY_CHECK | snapshots=%d | degradations=%d",
            len(snapshots), degradation_count,
        )

        return {
            "status": "done",
            "snapshots": len(snapshots),
            "degradations": degradation_count,
        }

    except Exception as e:
        logger.error("LLM_QUALITY_CHECK_FAILED | error=%s", str(e)[:200])
        db.rollback()
        raise
    finally:
        db.close()


def _send_degradation_alerts(db, snapshots):
    """Send alerts for detected degradations."""
    degraded = [s for s in snapshots if s.degradation_detected]
    if not degraded:
        return

    # Group by severity
    critical = []
    high = []
    for snap in degraded:
        if not snap.degradation_details:
            continue
        for detail in snap.degradation_details:
            sig_type = detail.get("type", "")
            if sig_type == "success_rate_drop" and detail.get("drop_pp", 0) > 30:
                critical.append(f"{snap.model}/{snap.operation}")
            elif sig_type == "latency_spike" and detail.get("ratio", 1) > 5:
                critical.append(f"{snap.model}/{snap.operation}")
            else:
                high.append(f"{snap.model}/{snap.operation}")

    try:
        from app.services.notifications import notify_ops

        if critical:
            notify_ops(
                db,
                level="critical",
                category="llm_quality",
                message=(
                    f"🔴 LLM quality CRITICAL: {len(critical)} model(s) severely degraded — "
                    f"{', '.join(critical[:3])}"
                    + (f" +{len(critical)-3} more" if len(critical) > 3 else "")
                ),
            )
        elif high:
            notify_ops(
                db,
                level="warning",
                category="llm_quality",
                message=(
                    f"⚠️ LLM quality degraded: {len(high)} model(s) — "
                    f"{', '.join(high[:3])}"
                    + (f" +{len(high)-3} more" if len(high) > 3 else "")
                ),
            )
    except Exception as e:
        logger.error("LLM_QUALITY_ALERT_FAILED | error=%s", str(e)[:100])
