"""Ops Notifications — Telegram + Admin Bell for owner/partner.

Provides alerts for operational events that owner/partner must see:
- LLM generation failures (credits exhausted, model errors)
- Pipeline dead (0 drafts/day for active clients)
- Avatar health transitions (shadowban detected)
- Cost alerts (spend spike)

Usage:
    from app.services.ops_notifications import notify_ops

    # In any service/task:
    notify_ops(
        level="critical",
        title="LLM Credits Exhausted",
        body="Anthropic API returned 'credit balance too low'. All fallback generation blocked.",
        category="llm_failure",
    )
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Literal

import httpx

from app.logging_config import get_logger

logger = get_logger(__name__)

OpsLevel = Literal["info", "warning", "critical"]


def notify_ops(
    level: OpsLevel,
    title: str,
    body: str | None = None,
    category: str = "general",
    link: str | None = None,
    *,
    telegram: bool = True,
    bell: bool = True,
) -> None:
    """Send ops notification to Telegram and/or admin bell.

    Args:
        level: info | warning | critical
        title: Short message (max 200 chars)
        body: Optional details
        category: For dedup/grouping (llm_failure, pipeline_dead, avatar_health, cost_alert)
        link: Optional admin URL
        telegram: Send to Telegram (default True for warning+critical)
        bell: Push to admin bell via Redis (default True)
    """
    # Always log
    log_fn = logger.info if level == "info" else (logger.warning if level == "warning" else logger.error)
    log_fn("OPS_NOTIFY [%s] %s: %s | %s", level, category, title, body or "")

    # Telegram for warning + critical
    if telegram and level in ("warning", "critical"):
        _send_telegram(level, title, body, category)

    # Admin bell via Redis PubSub
    if bell:
        _publish_admin_bell(level, title, body, category, link)


def _send_telegram(level: OpsLevel, title: str, body: str | None, category: str) -> None:
    """Send alert to Telegram via Bot API to all subscribed users."""
    try:
        from app.database import SessionLocal
        from app.services.settings import get_setting
        from app.models.user import User

        db = SessionLocal()
        try:
            bot_token = get_setting(db, "telegram_bot_token")
            if not bot_token:
                logger.debug("Telegram not configured (no bot_token in settings)")
                return

            # Get all users with telegram_chat_id who want this level
            users = (
                db.query(User)
                .filter(
                    User.telegram_chat_id.isnot(None),
                    User.telegram_chat_id != "",
                    User.is_active.is_(True),
                    User.role.in_(["owner", "partner"]),
                )
                .all()
            )

            # Also send to global chat_id (watchdog legacy — always receives all)
            global_chat_id = get_setting(db, "telegram_chat_id")
            chat_ids_sent = set()

            for user in users:
                user_level = user.telegram_notifications_level or "critical"
                # Check if user wants this level
                level_priority = {"off": 0, "critical": 1, "warning": 2, "all": 3}
                msg_priority = {"info": 3, "warning": 2, "critical": 1}
                if level_priority.get(user_level, 0) < msg_priority.get(level, 3):
                    continue  # User doesn't want this level
                chat_ids_sent.add(user.telegram_chat_id)

            # Always include global (watchdog) chat_id for critical
            if global_chat_id and level == "critical":
                chat_ids_sent.add(global_chat_id)

        finally:
            db.close()

        if not chat_ids_sent:
            return

        icon = {"info": "ℹ️", "warning": "⚠️", "critical": "🔴"}.get(level, "📢")
        text = f"{icon} *RAMP {level.upper()}*\n\n*{title}*"
        if body:
            text += f"\n\n{body[:500]}"
        text += f"\n\n_Category: {category}_"

        for chat_id in chat_ids_sent:
            try:
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                resp = httpx.post(
                    url,
                    data={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": "true",
                    },
                    timeout=10,
                )
                if resp.status_code != 200:
                    logger.warning("Telegram send to %s failed: %s", chat_id, resp.text[:100])
            except Exception as e:
                logger.warning("Telegram send to %s error: %s", chat_id, e)
    except Exception as e:
        logger.warning("Telegram notification failed: %s", e)


def _publish_admin_bell(
    level: OpsLevel, title: str, body: str | None, category: str, link: str | None
) -> None:
    """Publish to Redis PubSub for admin bell (owner/partner dashboard)."""
    try:
        import redis
        from app.config import get_settings

        r = redis.from_url(get_settings().redis_url)
        channel = "notifications:ops"
        payload = json.dumps({
            "id": str(uuid.uuid4()),
            "level": level,
            "title": title,
            "body": body,
            "category": category,
            "link": link,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r.publish(channel, payload)
        # Also store in list for popup fetch (last 50)
        r.lpush("ramp:ops_notifications", payload)
        r.ltrim("ramp:ops_notifications", 0, 49)
        r.close()
    except Exception as e:
        logger.debug("Redis ops bell publish failed: %s", e)


def get_recent_ops_notifications(limit: int = 20) -> list[dict]:
    """Get recent ops notifications from Redis (for admin bell popup)."""
    try:
        import redis
        from app.config import get_settings

        r = redis.from_url(get_settings().redis_url)
        raw = r.lrange("ramp:ops_notifications", 0, limit - 1)
        r.close()
        return [json.loads(item) for item in raw]
    except Exception:
        return []


def get_unread_ops_count() -> int:
    """Get count of recent ops notifications (last 24h approximation)."""
    try:
        import redis
        from app.config import get_settings

        r = redis.from_url(get_settings().redis_url)
        count = r.llen("ramp:ops_notifications")
        r.close()
        return count or 0
    except Exception:
        return 0


def clear_ops_notifications() -> None:
    """Clear all ops notifications (mark as read equivalent)."""
    try:
        import redis
        from app.config import get_settings

        r = redis.from_url(get_settings().redis_url)
        r.delete("ramp:ops_notifications")
        r.close()
    except Exception:
        pass



def is_generation_degraded(client_id) -> str | None:
    """Check if content generation is degraded for a client.

    Returns the degradation reason (e.g. "credits", "generation") or None if healthy.
    Used by portal pages to show status banner to clients.
    """
    try:
        import redis
        from app.config import get_settings

        r = redis.from_url(get_settings().redis_url)
        key = f"ramp:generation_degraded:{client_id}"
        value = r.get(key)
        r.close()
        return value.decode() if value else None
    except Exception:
        return None
