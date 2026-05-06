"""Operations Dashboard service — aggregates daily-ops data across all clients.

Powers the unified `/admin/` dashboard: client status cards, scrape freshness
grouped by client, run history (ActivityEvent feed), avatar health summary,
and the next scheduled Celery Beat run times.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from celery.schedules import crontab
from sqlalchemy import desc, func as sa_func
from sqlalchemy.orm import Session

from app.models.activity_event import ActivityEvent
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.subreddit import ClientSubreddit
from app.models.subreddit_karma import SubredditKarma
from app.models.thread import RedditThread
from app.models.thread_score import ThreadScore


# Schedule entries the dashboard surfaces. Mirrors `app/tasks/worker.py`
# beat_schedule but only the human-relevant pipeline runs (heartbeats and
# queue-tickers are intentionally excluded).
_SCHEDULE_ENTRIES: list[dict[str, Any]] = [
    {
        "key": "ai-pipeline-morning",
        "label": "Morning pipeline (score + generate)",
        "cron": crontab(hour=8, minute=0),
    },
    {
        "key": "hobby-pipeline-daily",
        "label": "Hobby pipeline (all avatars)",
        "cron": crontab(hour=10, minute=0),
    },
    {
        "key": "ai-pipeline-afternoon",
        "label": "Afternoon pipeline (score + generate)",
        "cron": crontab(hour=14, minute=0),
    },
    {
        "key": "avatar-health-check",
        "label": "Avatar health check",
        "cron": crontab(hour="*/12", minute=30),
    },
    {
        "key": "evaluate-avatar-phases-daily",
        "label": "Evaluate avatar warming phases",
        "cron": crontab(hour=6, minute=0),
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _human_delta(delta: timedelta) -> str:
    """Render a timedelta as a short human string ('3h 20m', '2d 4h', '45s')."""
    total = int(delta.total_seconds())
    if total < 0:
        return "now"
    if total < 60:
        return f"{total}s"
    if total < 3600:
        m = total // 60
        s = total % 60
        return f"{m}m {s}s" if s and m < 5 else f"{m}m"
    if total < 86400:
        h = total // 3600
        m = (total % 3600) // 60
        return f"{h}h {m}m" if m else f"{h}h"
    d = total // 86400
    h = (total % 86400) // 3600
    return f"{d}d {h}h" if h else f"{d}d"


def _human_since(when: datetime | None, now: datetime) -> str:
    """Render time elapsed since `when` ('2h ago', 'Never')."""
    if when is None:
        return "Never"
    return f"{_human_delta(now - when)} ago"


# ---------------------------------------------------------------------------
# Top metrics bar
# ---------------------------------------------------------------------------


def get_top_metrics(db: Session) -> dict[str, Any]:
    """Aggregate the four headline numbers shown above the dashboard grid."""
    pending_reviews = (
        db.query(sa_func.count(CommentDraft.id))
        .filter(CommentDraft.status == "pending")
        .scalar()
    ) or 0

    total_clients = (
        db.query(sa_func.count(Client.id))
        .filter(Client.is_active.is_(True))
        .scalar()
    ) or 0

    total_avatars = (
        db.query(sa_func.count(Avatar.id))
        .filter(Avatar.active.is_(True))
        .scalar()
    ) or 0

    schedule = get_schedule_display()
    next_run = schedule[0] if schedule else None

    return {
        "pending_reviews": pending_reviews,
        "total_clients": total_clients,
        "total_avatars": total_avatars,
        "next_run_label": next_run["label"] if next_run else None,
        "next_run_in": next_run["in_human"] if next_run else None,
    }


# ---------------------------------------------------------------------------
# Per-client status cards
# ---------------------------------------------------------------------------


def get_client_status_cards(db: Session) -> list[dict[str, Any]]:
    """Today's pipeline activity for each active client.

    Uses batch queries instead of per-client loops to avoid N+1.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)

    clients = (
        db.query(Client)
        .filter(Client.is_active.is_(True))
        .order_by(Client.client_name)
        .all()
    )

    if not clients:
        return []

    client_ids = [c.id for c in clients]

    # Batch: threads created in last 24h per client
    threads_rows = (
        db.query(RedditThread.client_id, sa_func.count(RedditThread.id))
        .filter(
            RedditThread.client_id.in_(client_ids),
            RedditThread.created_at >= since,
        )
        .group_by(RedditThread.client_id)
        .all()
    )
    threads_map = {row[0]: row[1] for row in threads_rows}

    # Batch: scored threads in last 24h per client
    scored_rows = (
        db.query(RedditThread.client_id, sa_func.count(RedditThread.id))
        .filter(
            RedditThread.client_id.in_(client_ids),
            RedditThread.created_at >= since,
            RedditThread.tag.isnot(None),
        )
        .group_by(RedditThread.client_id)
        .all()
    )
    scored_map = {row[0]: row[1] for row in scored_rows}

    # Batch: generated drafts in last 24h per client
    generated_rows = (
        db.query(CommentDraft.client_id, sa_func.count(CommentDraft.id))
        .filter(
            CommentDraft.client_id.in_(client_ids),
            CommentDraft.created_at >= since,
        )
        .group_by(CommentDraft.client_id)
        .all()
    )
    generated_map = {row[0]: row[1] for row in generated_rows}

    # Batch: pending drafts per client
    pending_rows = (
        db.query(CommentDraft.client_id, sa_func.count(CommentDraft.id))
        .filter(
            CommentDraft.client_id.in_(client_ids),
            CommentDraft.status == "pending",
        )
        .group_by(CommentDraft.client_id)
        .all()
    )
    pending_map = {row[0]: row[1] for row in pending_rows}

    cards: list[dict[str, Any]] = []
    for client in clients:
        threads_24h = threads_map.get(client.id, 0)
        scored_24h = scored_map.get(client.id, 0)
        generated_24h = generated_map.get(client.id, 0)
        pending = pending_map.get(client.id, 0)
        is_idle = (threads_24h + scored_24h + generated_24h) == 0

        cards.append({
            "client_id": str(client.id),
            "client_name": client.client_name,
            "threads_24h": threads_24h,
            "scored_24h": scored_24h,
            "generated_24h": generated_24h,
            "pending": pending,
            "is_idle": is_idle,
        })

    return cards


def list_active_clients(db: Session) -> list[Client]:
    """All currently active clients, sorted by name. Used by Run-All triggers."""
    return (
        db.query(Client)
        .filter(Client.is_active.is_(True))
        .order_by(Client.client_name)
        .all()
    )


# ---------------------------------------------------------------------------
# Scrape freshness, grouped by client
# ---------------------------------------------------------------------------


def get_scrape_freshness_grouped(
    db: Session, stale_hours: int = 24
) -> list[dict[str, Any]]:
    """Per-client subreddit freshness; stale subs sorted to the top of each group."""
    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(hours=stale_hours)

    rows = (
        db.query(ClientSubreddit, Client)
        .join(Client, ClientSubreddit.client_id == Client.id)
        .filter(
            ClientSubreddit.is_active.is_(True),
            Client.is_active.is_(True),
        )
        .order_by(Client.client_name, ClientSubreddit.subreddit_name)
        .all()
    )

    grouped: dict[uuid.UUID, dict[str, Any]] = {}
    for sub, client in rows:
        last = sub.last_scraped_at
        is_never = last is None
        is_stale = is_never or last < stale_threshold

        entry = grouped.setdefault(client.id, {
            "client_id": str(client.id),
            "client_name": client.client_name,
            "subreddits": [],
            "stale_count": 0,
            "total": 0,
        })
        entry["subreddits"].append({
            "subreddit_name": sub.subreddit_name,
            "last_scraped_at": last,
            "since_human": _human_since(last, now),
            "is_stale": is_stale,
            "is_never": is_never,
        })
        entry["total"] += 1
        if is_stale:
            entry["stale_count"] += 1

    # Sort stale subs to the top of each group
    for entry in grouped.values():
        entry["subreddits"].sort(key=lambda s: (not s["is_stale"], s["subreddit_name"]))

    return list(grouped.values())


# ---------------------------------------------------------------------------
# Run history (ActivityEvent feed scoped to pipeline events)
# ---------------------------------------------------------------------------


_PIPELINE_EVENT_TYPES = ("scrape", "score", "generate")


def get_run_history(
    db: Session,
    client_id: uuid.UUID | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Recent pipeline events, joined with client name for display."""
    now = datetime.now(timezone.utc)

    query = (
        db.query(ActivityEvent, Client.client_name)
        .outerjoin(Client, ActivityEvent.client_id == Client.id)
        .filter(ActivityEvent.event_type.in_(_PIPELINE_EVENT_TYPES))
    )
    if client_id is not None:
        query = query.filter(ActivityEvent.client_id == client_id)

    rows = query.order_by(desc(ActivityEvent.created_at)).limit(limit).all()

    return [
        {
            "id": str(event.id),
            "client_id": str(event.client_id) if event.client_id else None,
            "client_name": client_name or "—",
            "event_type": event.event_type,
            "message": event.message,
            "created_at": event.created_at,
            "since_human": _human_since(event.created_at, now),
        }
        for event, client_name in rows
    ]


# ---------------------------------------------------------------------------
# Avatar health summary
# ---------------------------------------------------------------------------


def get_avatar_health_summary(db: Session) -> dict[str, Any]:
    """Aggregate avatar health: status counts, phase breakdown, eligible-for-promotion."""
    now = datetime.now(timezone.utc)
    promotion_threshold = now - timedelta(days=30)

    status_rows = (
        db.query(Avatar.reddit_status, sa_func.count(Avatar.id))
        .filter(Avatar.active.is_(True))
        .group_by(Avatar.reddit_status)
        .all()
    )
    status_counts = {row[0] or "unknown": row[1] for row in status_rows}

    phase_rows = (
        db.query(Avatar.warming_phase, sa_func.count(Avatar.id))
        .filter(Avatar.active.is_(True))
        .group_by(Avatar.warming_phase)
        .all()
    )
    phase_counts = {int(row[0]): row[1] for row in phase_rows}

    total_active = sum(status_counts.values())

    # Eligible for promotion: warming_phase < 3 AND
    # (last_phase_evaluated_at < 30 days ago OR last_phase_evaluated_at IS NULL).
    eligible_for_promotion = (
        db.query(sa_func.count(Avatar.id))
        .filter(
            Avatar.active.is_(True),
            Avatar.warming_phase < 3,
            sa_func.coalesce(
                Avatar.last_phase_evaluated_at,
                datetime(1970, 1, 1, tzinfo=timezone.utc),
            ) < promotion_threshold,
        )
        .scalar()
    ) or 0

    # Karma diversity (Req 9) — count avatars whose karma is concentrated in
    # only one subreddit, plus the average distinct-subreddit count across all
    # active avatars.
    diversity_rows = (
        db.query(
            SubredditKarma.avatar_id,
            sa_func.count(SubredditKarma.id).label("sub_count"),
        )
        .join(Avatar, Avatar.id == SubredditKarma.avatar_id)
        .filter(
            Avatar.active.is_(True),
            (SubredditKarma.comment_karma + SubredditKarma.post_karma) > 0,
        )
        .group_by(SubredditKarma.avatar_id)
        .all()
    )
    low_diversity_count = sum(1 for row in diversity_rows if row.sub_count <= 1)
    avatars_with_any_karma = len(diversity_rows)
    avg_diversity = (
        round(sum(r.sub_count for r in diversity_rows) / avatars_with_any_karma, 1)
        if avatars_with_any_karma
        else 0.0
    )

    return {
        "status_counts": {
            "active": status_counts.get("active", 0),
            "shadowbanned": status_counts.get("shadowbanned", 0),
            "suspended": status_counts.get("suspended", 0),
            "unknown": status_counts.get("unknown", 0),
        },
        "phase_counts": {
            "phase_1": phase_counts.get(1, 0),
            "phase_2": phase_counts.get(2, 0),
            "phase_3": phase_counts.get(3, 0),
        },
        "total_active": total_active,
        "eligible_for_promotion": eligible_for_promotion,
        "karma_diversity": {
            "low_diversity_count": low_diversity_count,
            "avatars_with_karma": avatars_with_any_karma,
            "avg_subreddits_per_avatar": avg_diversity,
        },
    }


def get_low_diversity_avatars(db: Session) -> list[dict[str, Any]]:
    """List avatars in Phase 1 or 2 whose karma is concentrated in ≤1 subreddit.

    These avatars should diversify before promotion (Req 9.2). Returned items
    carry the avatar id, username, phase, and the count of distinct positive-
    karma subreddits.
    """
    sub_count_subq = (
        db.query(
            SubredditKarma.avatar_id.label("avatar_id"),
            sa_func.count(SubredditKarma.id).label("sub_count"),
        )
        .filter((SubredditKarma.comment_karma + SubredditKarma.post_karma) > 0)
        .group_by(SubredditKarma.avatar_id)
        .subquery()
    )

    rows = (
        db.query(Avatar, sa_func.coalesce(sub_count_subq.c.sub_count, 0))
        .outerjoin(sub_count_subq, sub_count_subq.c.avatar_id == Avatar.id)
        .filter(
            Avatar.active.is_(True),
            Avatar.warming_phase.in_([1, 2]),
        )
        .all()
    )

    out: list[dict[str, Any]] = []
    for avatar, sub_count in rows:
        sub_count = int(sub_count or 0)
        if sub_count <= 1:
            out.append({
                "avatar_id": str(avatar.id),
                "username": avatar.reddit_username,
                "phase": avatar.warming_phase,
                "subreddit_count": sub_count,
            })
    return out


# ---------------------------------------------------------------------------
# Beat schedule display
# ---------------------------------------------------------------------------


def get_schedule_display(now: datetime | None = None) -> list[dict[str, Any]]:
    """Next-run times for the pipeline beat entries, sorted soonest-first.

    The earliest entry is flagged ``is_next=True`` so the template can highlight
    it. ``remaining_estimate`` returns a timedelta to the next firing relative
    to the supplied "last run" timestamp — passing `now` gives us "from now".
    """
    if now is None:
        now = datetime.now(timezone.utc)

    rows: list[dict[str, Any]] = []
    for entry in _SCHEDULE_ENTRIES:
        cron: crontab = entry["cron"]
        try:
            delta = cron.remaining_estimate(now)
        except Exception:
            delta = timedelta(seconds=0)
        next_at = now + delta
        rows.append({
            "key": entry["key"],
            "label": entry["label"],
            "next_at": next_at,
            "in_human": _human_delta(delta),
            "is_next": False,
        })

    rows.sort(key=lambda r: r["next_at"])
    if rows:
        rows[0]["is_next"] = True
    return rows
