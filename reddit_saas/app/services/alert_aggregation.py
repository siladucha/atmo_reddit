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
    alerts += _get_pipeline_dead_alert(db)
    alerts += _get_frozen_avatar_alerts(db)
    alerts += _get_stale_scrape_alerts(db)
    alerts += _get_expiring_trial_alerts(db)
    alerts += _get_zero_activity_alerts(db)
    alerts += _get_llm_spend_rate_alert(db)

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


def _get_pipeline_dead_alert(db: Session) -> list[Alert]:
    """Check if pipeline has been producing zero output for >24h.

    This catches the scenario where workers are alive but pipeline
    is silently dead (no fresh threads → no scoring → no generation).
    Different from stale_scrape (which checks individual subs) — this
    checks if ANY scrape succeeded recently.
    """
    now = datetime.now(timezone.utc)

    # Check: any subreddit scraped in last 24h?
    recent_threshold = now - timedelta(hours=24)
    any_recent_scrape = (
        db.query(Subreddit.id)
        .filter(
            Subreddit.is_active.is_(True),
            Subreddit.last_scraped_at >= recent_threshold,
        )
        .first()
    )

    if any_recent_scrape:
        return []

    # No scrape in 24h — check if scraping is supposed to be active
    from app.services.settings import get_setting
    scrape_enabled = get_setting(db, "scrape_enabled").lower() == "true"

    if not scrape_enabled:
        return []  # scraping intentionally disabled, not a bug

    # Pipeline is dead: scraping enabled but zero output in 24h
    # Calculate how long it's been since last scrape
    from sqlalchemy import func as _func
    last_scrape = db.query(_func.max(Subreddit.last_scraped_at)).scalar()
    if last_scrape:
        hours_since = int((now - last_scrape).total_seconds() / 3600)
        days_since = hours_since // 24
        if days_since > 1:
            time_str = f"{days_since} days"
        else:
            time_str = f"{hours_since}h"
    else:
        time_str = "never"

    return [Alert(
        type="pipeline_dead",
        severity="critical",
        message=f"Pipeline DEAD — no scrape in {time_str}. Workers may be offline.",
        link="/admin/daily-review",
        icon="💀",
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


def _get_llm_spend_rate_alert(db: Session) -> list[Alert]:
    """Check for abnormal LLM spend rate (R-AI-007 runaway loop detection).

    Two checks:
    1. Cost in last hour > 150% of daily average (from ai_usage_log)
    2. Redis circuit breaker has been tripped (cost window > threshold)
    """
    alerts: list[Alert] = []

    # Check 1: DB-based — cost in last hour vs 7-day hourly average
    try:
        from app.models.ai_usage import AIUsageLog
        now = datetime.now(timezone.utc)
        one_hour_ago = now - timedelta(hours=1)
        seven_days_ago = now - timedelta(days=7)

        # Cost in last hour
        cost_last_hour = (
            db.query(sa_func.coalesce(sa_func.sum(AIUsageLog.cost_usd), 0))
            .filter(AIUsageLog.created_at >= one_hour_ago)
            .scalar()
        ) or 0

        # Average hourly cost over last 7 days
        cost_7d = (
            db.query(sa_func.coalesce(sa_func.sum(AIUsageLog.cost_usd), 0))
            .filter(AIUsageLog.created_at >= seven_days_ago)
            .scalar()
        ) or 0
        avg_hourly_cost = float(cost_7d) / (7 * 24) if cost_7d else 0.05  # default $0.05/hr baseline

        # Alert if last hour > 3x average OR > $3 absolute
        cost_last_hour_float = float(cost_last_hour)
        if cost_last_hour_float > max(avg_hourly_cost * 3, 3.0):
            alerts.append(Alert(
                type="llm_spend_spike",
                severity="critical",
                message=(
                    f"LLM spend spike: ${cost_last_hour_float:.2f} in last hour "
                    f"(avg: ${avg_hourly_cost:.2f}/hr). Possible runaway loop."
                ),
                link="/admin/ai-costs",
                icon="🔥",
            ))
        elif cost_last_hour_float > max(avg_hourly_cost * 1.5, 1.5):
            alerts.append(Alert(
                type="llm_spend_elevated",
                severity="high",
                message=(
                    f"LLM spend elevated: ${cost_last_hour_float:.2f} in last hour "
                    f"(avg: ${avg_hourly_cost:.2f}/hr)"
                ),
                link="/admin/ai-costs",
                icon="💰",
            ))
    except Exception:
        pass  # Don't let alert failure block dashboard

    # Check 2: Redis-based — circuit breaker status
    try:
        import redis as _redis_lib
        from app.config import get_settings
        settings = get_settings()
        r = _redis_lib.from_url(settings.redis_url, decode_responses=True)

        # Check current 10-min cost window
        import datetime as _dt
        now_utc = _dt.datetime.now(_dt.timezone.utc)
        cost_bucket = f"{now_utc.strftime('%Y%m%d%H')}:{now_utc.minute // 10}"
        cost_key = f"ramp:llm:cost:window:{cost_bucket}"
        current_window_cost = r.get(cost_key)

        if current_window_cost and float(current_window_cost) >= 4.0:
            # Approaching or at circuit breaker threshold ($5)
            alerts.append(Alert(
                type="llm_circuit_breaker",
                severity="critical",
                message=(
                    f"LLM circuit breaker near threshold: "
                    f"${float(current_window_cost):.2f}/10min (limit: $5.00)"
                ),
                link="/admin/ai-costs",
                icon="🛑",
            ))

        # Check daily call count
        daily_key = f"ramp:llm:calls:daily:{now_utc.strftime('%Y%m%d')}"
        daily_calls = r.get(daily_key)
        if daily_calls and int(daily_calls) > 2400:  # 80% of 3000
            alerts.append(Alert(
                type="llm_daily_budget_warning",
                severity="high",
                message=f"LLM daily call count high: {daily_calls}/3000",
                link="/admin/ai-costs",
                icon="⚡",
            ))
    except Exception:
        pass  # Redis unavailable — skip this check

    return alerts
