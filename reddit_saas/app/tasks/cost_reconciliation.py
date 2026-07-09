"""Daily cost reconciliation — detect pricing drift between expected and logged costs.

Runs daily at 01:05. Compares expected cost (tokens × MODEL_COSTS rates) against
logged cost_usd from ai_usage_log. Alerts if delta > 5% for any model with > $0.01 spend.
"""

from app.logging_config import get_logger
from app.tasks.worker import celery_app

logger = get_logger(__name__)


@celery_app.task(name="run_cost_reconciliation", bind=True, max_retries=0)
def run_cost_reconciliation(self):
    """Compare expected cost (tokens × rates) vs logged cost_usd.

    Checks the 24h window ending at 01:00 today UTC.
    Alerts via notify_ops if delta > 5% for any model with > $0.01 spend.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func

    from app.database import SessionLocal
    from app.models.ai_usage import AIUsageLog
    from app.services.ai import MODEL_COSTS

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        window_end = now.replace(hour=1, minute=0, second=0, microsecond=0)
        if window_end > now:
            # If task runs before 01:00, use yesterday's window
            window_end = window_end - timedelta(days=1)
        window_start = window_end - timedelta(hours=24)

        # Aggregate by model
        rows = (
            db.query(
                AIUsageLog.model,
                func.sum(AIUsageLog.input_tokens).label("total_input"),
                func.sum(AIUsageLog.output_tokens).label("total_output"),
                func.sum(AIUsageLog.cost_usd).label("logged_cost"),
                func.count(AIUsageLog.id).label("call_count"),
            )
            .filter(
                AIUsageLog.created_at >= window_start,
                AIUsageLog.created_at < window_end,
            )
            .group_by(AIUsageLog.model)
            .all()
        )

        if not rows:
            logger.info("RECONCILIATION_COMPLETE | no records in window | skipping")
            return {"status": "done", "models_checked": 0, "alerts_raised": 0, "deltas": []}

        models_checked = 0
        alerts_raised = 0
        deltas = []

        for row in rows:
            model_name = row.model
            logged_cost = float(row.logged_cost or 0)

            # Skip models with negligible spend
            if logged_cost < 0.01:
                continue

            # Skip unknown models
            if model_name not in MODEL_COSTS:
                logger.warning(
                    "RECONCILIATION_UNKNOWN_MODEL | model=%s | calls=%d | logged_cost=%.4f",
                    model_name, row.call_count, logged_cost,
                )
                continue

            # Compute expected cost
            rates = MODEL_COSTS[model_name]
            input_rate = rates["input"]   # $/1M tokens
            output_rate = rates["output"]  # $/1M tokens
            expected_cost = (
                (row.total_input or 0) * input_rate / 1_000_000
                + (row.total_output or 0) * output_rate / 1_000_000
            )

            # Avoid division by zero
            if expected_cost == 0:
                continue

            delta_pct = abs(expected_cost - logged_cost) / expected_cost * 100
            models_checked += 1
            deltas.append({
                "model": model_name,
                "expected": round(expected_cost, 4),
                "logged": round(logged_cost, 4),
                "delta_pct": round(delta_pct, 1),
            })

            if delta_pct > 5.0:
                alerts_raised += 1
                try:
                    from app.services.notifications import notify_ops
                    notify_ops(
                        db,
                        level="warning",
                        category="cost_reconciliation",
                        message=(
                            f"Cost drift detected for {model_name}: "
                            f"expected ${expected_cost:.4f}, logged ${logged_cost:.4f} "
                            f"(delta {delta_pct:.1f}%)"
                        ),
                    )
                except Exception as e:
                    logger.error("RECONCILIATION_NOTIFY_FAILED | error=%s", str(e)[:100])

        logger.info(
            "RECONCILIATION_COMPLETE | models_checked=%d | alerts_raised=%d | deltas=%s",
            models_checked, alerts_raised, deltas,
        )

        return {
            "status": "done",
            "models_checked": models_checked,
            "alerts_raised": alerts_raised,
            "deltas": deltas,
        }
    except Exception as e:
        logger.error("RECONCILIATION_FAILED | error=%s", str(e)[:200])
        raise
    finally:
        db.close()
