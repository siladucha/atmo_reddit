"""Alert aggregation service — collects actionable alerts across the system.

Powers the Owner dashboard "Alerts Bar" and Partner "Attention Needed" section.
Each alert has: type, severity (critical/high/medium/low), message, link, icon.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.subreddit import Subreddit, ClientSubredditAssignment


@dataclass
class Alert:
    """System alert for the dashboard."""

    type: str
    severity: str  # critical, high, medium, low
    message: str
    link: str
    icon: str

    @property
    def severity_order(self) -> int:
        return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(self.severity, 4)


def get_system_alerts(db: Session) -> list[Alert]:
    """Collect all actionable alerts across the system.

    Returns alerts sorted by severity (critical first).
    """
    alerts: list[Alert] = []
    alerts += _get_worker_alert(db)
    alerts += _get_kill_switch_alerts(db)
    alerts += _get_frozen_avatar_alerts(db)
    alerts += _get_stale_scrape_alerts(db)
    alerts += _get_expiring_trial_alerts(db)
    alerts += _get_zero_activity_alerts(db)

    alerts.sort(key=lambda a: a.severity_order)
    return alerts


def _get_worker_alert(db: Session) -> list[Alert]:
    """Check if Celery worker is offline (no heartbeat in 2 min).

    Reads the ramp:heartbeat:last_at key from Redis (written by system_heartbeat task).
    """
    import redis as _redis
    from app.config import get_settings

    now = datetime.now(timezone.utc)

    try:
        settings = get_settings()
        client = _redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)
        last_at_str = client.get('ramp:heartbeat:last_at')
        client.close()
    except Exception:
        last_at_str = None

    if not last_at_str:
        return [Alert(
            type='worker_offline',
            severity='critical',
            message='Worker offline — no heartbeat detected',
            link='/admin/tasks',
            icon='🔴',
        )]

    try:
        last_at = datetime.fromisoformat(last_at_str)
        if (now - last_at).total_seconds() > 180:
            return [Alert(
                type='worker_offline',
                severity='critical',
                message='Worker offline — last heartbeat >3 min ago',
                link='/admin/tasks',
                icon='🔴',
            )]
    except (ValueError, TypeError):
        return [Alert(
            type='worker_offline',
            severity='critical',
            message='Worker offline — invalid heartbeat timestamp',
            link='/admin/tasks',
            icon='🔴',
        )]

    return []


def _get_kill_switch_alerts(db: Session) -> list[Alert]:
    """Check if any kill switches are ON (pipeline disabled)."""
    from app.services.settings import get_setting

    alerts: list[Alert] = []

    if get_setting(db, "pipeline_enabled").lower() != "true":
        alerts.append(Alert(
            type="kill_switch",
            severity="high",
            message="Pipeline DISABLED (kill switch ON)",
            link="/admin/settings",
            icon="⛔",
        ))

    if get_setting(db, "generation_enabled").lower() != "true":
        alerts.append(Alert(
            type="kill_switch",
            severity="high",
            message="Generation DISABLED (kill switch ON)",
            link="/admin/settings",
            icon="⛔",
        ))

    if get_setting(db, "scrape_enabled").lower() != "true":
        alerts.append(Alert(
            type="kill_switch",
            severity="medium",
            message="Scraping DISABLED (kill switch ON)",
            link="/admin/settings",
            icon="⛔",
        ))

    return alerts


def _get_frozen_avatar_alerts(db: Session) -> list[Alert]:
    """Check for frozen avatars."""
    frozen_count = (
        db.query(sa_func.count(Avatar.id))
        .filter(Avatar.active.is_(True), Avatar.is_frozen.is_(True))
        .scalar()
    ) or 0

    if frozen_count == 0:
        return []

    return [Alert(
        type="frozen_avatars",
        severity="high" if frozen_count >= 3 else "medium",
        message=f"{frozen_count} avatar{'s' if frozen_count != 1 else ''} frozen",
        link="/admin/avatars",
        icon="🧊",
    )]


def _get_stale_scrape_alerts(db: Session) -> list[Alert]:
    """Check for subreddits that haven't been scraped in >2x their interval."""
    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(hours=12)  # 2x the default 6h interval

    stale_count = (
        db.query(sa_func.count(Subreddit.id))
        .join(ClientSubredditAssignment, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .join(Client, Client.id == ClientSubredditAssignment.client_id)
        .filter(
            Subreddit.is_active.is_(True),
            ClientSubredditAssignment.is_active.is_(True),
            Client.is_active.is_(True),
            sa_func.coalesce(
                Subreddit.last_scraped_at,
                datetime(2020, 1, 1, tzinfo=timezone.utc),
            ) < stale_threshold,
        )
        .scalar()
    ) or 0

    if stale_count == 0:
        return []

    return [Alert(
        type="stale_scrape",
        severity="medium",
        message=f"{stale_count} subreddit{'s' if stale_count != 1 else ''} stale (>12h since scrape)",
        link="/admin/subreddits",
        icon="⏰",
    )]


def _get_expiring_trial_alerts(db: Session) -> list[Alert]:
    """Check for trials expiring in < 3 days."""
    now = datetime.now(timezone.utc)
    alerts: list[Alert] = []

    trial_clients = (
        db.query(Client)
        .filter(Client.is_active.is_(True), Client.plan_type == "trial")
        .all()
    )

    for c in trial_clients:
        if c.created_at:
            days_left = 14 - (now - c.created_at).days
            if 0 < days_left <= 3:
                alerts.append(Alert(
                    type="trial_expiring",
                    severity="medium",
                    message=f'Trial "{c.client_name}" expires in {days_left}d',
                    link=f"/admin/clients/{c.id}",
                    icon="⏰",
                ))
            elif days_left <= 0:
                alerts.append(Alert(
                    type="trial_expired",
                    severity="low",
                    message=f'Trial "{c.client_name}" expired',
                    link=f"/admin/clients/{c.id}",
                    icon="💀",
                ))

    return alerts


def _get_zero_activity_alerts(db: Session) -> list[Alert]:
    """Check for paying clients with 0 posts in 7 days."""
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    from app.models.comment_draft import CommentDraft

    paying_clients = (
        db.query(Client)
        .filter(Client.is_active.is_(True), Client.plan_type != "trial")
        .all()
    )

    alerts: list[Alert] = []
    for c in paying_clients:
        posts = (
            db.query(sa_func.count(CommentDraft.id))
            .filter(
                CommentDraft.client_id == c.id,
                CommentDraft.status == "posted",
                CommentDraft.posted_at >= week_ago,
            )
            .scalar()
        ) or 0
        if posts == 0:
            # Check if they have avatars (otherwise it's expected)
            has_avatars = (
                db.query(Avatar.id)
                .filter(Avatar.active.is_(True), Avatar.client_ids.any(str(c.id)))
                .first()
            )
            if has_avatars:
                alerts.append(Alert(
                    type="zero_activity",
                    severity="high",
                    message=f'"{c.client_name}" — 0 posts in 7 days',
                    link=f"/admin/clients/{c.id}",
                    icon="⚠️",
                ))

    return alerts
