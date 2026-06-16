"""Client action rate limiter — enforces daily/weekly limits on expensive operations.

Rate limits (configurable via system settings):
- pipeline: 2 per day per client
- epg_rebuild: 1 per day per client
- strategy: 1 per week per avatar
- discovery: 2 per week per client
- regenerate: unlimited (no check, just tracked)
"""

import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.client_action_log import ClientActionLog

logger = get_logger(__name__)

# Default rate limits
DEFAULT_LIMITS: dict[str, dict] = {
    "pipeline": {"max": 2, "window": "day"},
    "epg_rebuild": {"max": 1, "window": "day"},
    "strategy": {"max": 1, "window": "week"},  # per avatar
    "discovery": {"max": 2, "window": "week"},
    "regenerate": {"max": 0, "window": "none"},  # unlimited, 0 = no limit
}


def _get_window_start(window: str) -> datetime:
    """Get the start of the current rate limit window."""
    now = datetime.now(timezone.utc)
    if window == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif window == "week":
        # Start of current week (Monday)
        days_since_monday = now.weekday()
        return (now - timedelta(days=days_since_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    return now  # no window


def _get_limit_config(db: Session, action_type: str) -> dict:
    """Get rate limit config, checking system settings for overrides."""
    from app.services.settings import get_setting

    default = DEFAULT_LIMITS.get(action_type, {"max": 0, "window": "none"})

    # Check system setting override: e.g. "client_action_limit_pipeline" = "3"
    setting_key = f"client_action_limit_{action_type}"
    override = get_setting(db, setting_key)
    if override and override.isdigit():
        return {"max": int(override), "window": default["window"]}

    return default


def check_rate_limit(
    db: Session,
    client_id: uuid.UUID,
    action_type: str,
    avatar_id: uuid.UUID | None = None,
) -> dict:
    """Check if an action is allowed under current rate limits.

    Returns:
        {
            "allowed": True/False,
            "remaining": int,  # remaining actions in window
            "retry_after": datetime | None,  # when the window resets (if blocked)
            "message": str,
        }
    """
    config = _get_limit_config(db, action_type)

    # Unlimited actions
    if config["max"] == 0:
        return {"allowed": True, "remaining": 999, "retry_after": None, "message": "ok"}

    window_start = _get_window_start(config["window"])

    # Build query
    query = db.query(func.count(ClientActionLog.id)).filter(
        ClientActionLog.client_id == client_id,
        ClientActionLog.action_type == action_type,
        ClientActionLog.triggered_at >= window_start,
    )

    # For per-avatar limits (strategy)
    if avatar_id and action_type == "strategy":
        query = query.filter(ClientActionLog.avatar_id == avatar_id)

    count = query.scalar() or 0
    remaining = max(0, config["max"] - count)

    if remaining > 0:
        return {"allowed": True, "remaining": remaining - 1, "retry_after": None, "message": "ok"}

    # Calculate retry_after
    if config["window"] == "day":
        retry_after = window_start + timedelta(days=1)
    elif config["window"] == "week":
        retry_after = window_start + timedelta(weeks=1)
    else:
        retry_after = None

    return {
        "allowed": False,
        "remaining": 0,
        "retry_after": retry_after,
        "message": f"Rate limit exceeded: max {config['max']} {action_type} per {config['window']}",
    }


def log_action(
    db: Session,
    client_id: uuid.UUID,
    action_type: str,
    user_id: uuid.UUID,
    avatar_id: uuid.UUID | None = None,
) -> ClientActionLog:
    """Log a client-triggered action (call AFTER successful dispatch)."""
    entry = ClientActionLog(
        client_id=client_id,
        action_type=action_type,
        triggered_by=user_id,
        avatar_id=avatar_id,
    )
    db.add(entry)
    db.commit()
    logger.info(
        "Client action logged: type=%s client=%s user=%s avatar=%s",
        action_type, client_id, user_id, avatar_id,
    )
    return entry


def get_action_status(
    db: Session,
    client_id: uuid.UUID,
    action_type: str,
    avatar_id: uuid.UUID | None = None,
) -> dict:
    """Get current rate limit status for display in UI."""
    result = check_rate_limit(db, client_id, action_type, avatar_id)

    # Get last triggered time
    query = (
        db.query(ClientActionLog.triggered_at)
        .filter(
            ClientActionLog.client_id == client_id,
            ClientActionLog.action_type == action_type,
        )
        .order_by(ClientActionLog.triggered_at.desc())
    )
    if avatar_id and action_type == "strategy":
        query = query.filter(ClientActionLog.avatar_id == avatar_id)

    last = query.first()

    return {
        **result,
        "last_triggered": last[0] if last else None,
    }
