"""Freshness guards for Reddit API calls.

Manual UI actions should prefer cached Reddit data unless the cached value is
older than the operation-specific freshness window or the operator explicitly
forces a refresh.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.services.settings import get_setting


def _hours_setting(db: Session, key: str, default: int) -> int:
    try:
        value = int(get_setting(db, key) or default)
    except (TypeError, ValueError):
        return default
    return max(value, 0)


def is_fresh(checked_at: datetime | None, freshness_hours: int) -> bool:
    """Return True when `checked_at` is inside the freshness window."""
    if checked_at is None:
        return False
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    return checked_at >= datetime.now(timezone.utc) - timedelta(hours=freshness_hours)


def reddit_status_freshness_hours(db: Session) -> int:
    """Freshness window for manual account metadata/status refreshes."""
    return _hours_setting(db, "reddit_status_manual_freshness_hours", 6)


def reddit_status_manual_batch_limit(db: Session) -> int:
    """Maximum avatars a manual batch action may refresh at once."""
    return max(_hours_setting(db, "reddit_status_manual_batch_limit", 25), 1)


def profile_analytics_freshness_hours(db: Session) -> int:
    """Freshness window for expensive profile analytics refreshes."""
    return _hours_setting(db, "reddit_profile_analytics_freshness_hours", 24)


def profile_analytics_batch_limit(db: Session) -> int:
    """Maximum avatars refreshed by one scheduled profile analytics run."""
    return max(_hours_setting(db, "reddit_profile_analytics_batch_limit", 20), 1)


def health_check_freshness_hours(db: Session) -> int:
    """Freshness window for manual visibility health checks."""
    return _hours_setting(db, "health_check_interval_hours", 12)


def is_reddit_status_fresh(db: Session, avatar: Avatar) -> bool:
    return is_fresh(avatar.reddit_status_checked_at, reddit_status_freshness_hours(db))


def is_health_check_fresh(db: Session, avatar: Avatar) -> bool:
    return is_fresh(avatar.last_health_check, health_check_freshness_hours(db))
