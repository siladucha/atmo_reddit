"""Provider Budget Check — periodic alert task.

Runs every 4 hours. Checks AI provider spend against configured budgets.
When thresholds are crossed:
- Telegram push to owner/partner (via notify_ops)
- Email to owner + partner
- Admin bell notification

Cooldown: same alert type not re-sent within 12 hours (Redis key).
"""

from app.tasks.worker import celery_app
from app.logging_config import get_logger

logger = get_logger(__name__)


@celery_app.task(name="check_provider_budgets")
def check_provider_budgets() -> dict:
    """Check provider budget thresholds and send multi-channel alerts.

    Returns dict with results per provider.
    """
    from datetime import datetime, timezone

    import redis as redis_lib

    from app.config import get_settings
    from app.database import SessionLocal
    from app.services.alert_aggregation import _get_provider_budget_alerts
    from app.services.ops_notifications import notify_ops

    db = SessionLocal()
    try:
        alerts = _get_provider_budget_alerts(db)
        if not alerts:
            logger.debug("Provider budget check: all within limits")
            return {"status": "ok", "alerts": 0}

        # Redis cooldown: don't spam same alert type within 12h
        settings = get_settings()
        r = redis_lib.from_url(settings.redis_url)

        sent_count = 0
        for alert in alerts:
            cooldown_key = f"ramp:provider_budget_alert:{alert.type}:{alert.severity}"
            if r.get(cooldown_key):
                logger.debug("Provider budget alert suppressed (cooldown): %s", alert.type)
                continue

            # Set cooldown (12 hours)
            r.setex(cooldown_key, 12 * 3600, "1")

            # 1. Telegram + admin bell (via notify_ops)
            level = "critical" if alert.severity == "critical" else "warning"
            notify_ops(
                level=level,
                title=f"💰 {alert.message}",
                body="Check /admin/ai-costs for details. Consider reducing usage or increasing budget.",
                category="cost_alert",
                link="/admin/ai-costs",
            )

            # 2. Email to owner + partner
            _send_budget_alert_email(alert)

            sent_count += 1

        r.close()
        logger.info("Provider budget check: %d alerts sent (of %d triggered)", sent_count, len(alerts))
        return {"status": "alerted", "alerts_triggered": len(alerts), "alerts_sent": sent_count}

    except Exception as e:
        logger.warning("Provider budget check failed: %s", e)
        return {"status": "error", "error": str(e)[:200]}
    finally:
        db.close()


def _send_budget_alert_email(alert) -> None:
    """Send budget alert email to owner + partner users."""
    from app.services.client_emails import _get_owner_emails, _get_partner_emails
    from app.services.email_sender import send_task_email

    recipients = list(set(_get_owner_emails() + _get_partner_emails()))
    if not recipients:
        return

    severity_icon = "🛑" if alert.severity == "critical" else "⚠️"
    subject = f"{severity_icon} AI Budget Alert: {alert.message}"

    body_text = f"""RAMP — AI Provider Budget Alert
{'=' * 40}

{severity_icon} {alert.message}

Severity: {alert.severity.upper()}
Action: Review AI costs at https://gorampit.com/admin/ai-costs

What to do:
- Check which operations are consuming the most budget
- Consider pausing non-essential AI operations
- Contact provider to increase limits if needed

— RAMP Ops Automation
"""

    body_html = f"""<div style="font-family:system-ui,sans-serif;max-width:550px;margin:0 auto;padding:20px">
<h2 style="margin-bottom:8px">{severity_icon} AI Budget Alert</h2>
<div style="background:{'#fef2f2' if alert.severity == 'critical' else '#fffbeb'};border:1px solid {'#fecaca' if alert.severity == 'critical' else '#fde68a'};border-radius:8px;padding:16px;margin:16px 0">
<p style="font-size:16px;font-weight:600;margin:0">{alert.message}</p>
<p style="font-size:13px;color:#64748b;margin:8px 0 0 0">Severity: {alert.severity.upper()}</p>
</div>
<h3 style="font-size:14px;margin-top:20px">Recommended Actions</h3>
<ul style="font-size:13px;color:#334155">
<li>Review which operations consume the most budget</li>
<li>Consider pausing non-essential AI operations (GEO, discovery)</li>
<li>Check provider console for actual billing status</li>
</ul>
<div style="margin-top:24px">
<a href="https://gorampit.com/admin/ai-costs" style="background:#1e293b;color:white;padding:10px 20px;border-radius:6px;text-decoration:none;display:inline-block">View AI Costs</a>
</div>
<p style="color:#94a3b8;font-size:11px;margin-top:24px">RAMP Ops — Automated budget monitoring (every 4h)</p>
</div>"""

    for email in recipients:
        try:
            send_task_email(email, subject, body_text, body_html)
        except Exception as e:
            logger.warning("Failed to send budget alert to %s: %s", email, e)
