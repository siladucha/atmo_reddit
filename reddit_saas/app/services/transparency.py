import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import desc, func as sa_func
from sqlalchemy.orm import Session

from app.models.activity_event import ActivityEvent
from app.models.ai_usage import AIUsageLog
from app.models.comment_draft import CommentDraft
from app.models.scrape_log import ScrapeLog
from app.models.subreddit import ClientSubreddit
from app.models.thread import RedditThread


def record_activity_event(
    db: Session,
    event_type: str,
    message: str,
    client_id: uuid.UUID | None = None,
    metadata: dict | None = None,
) -> ActivityEvent:
    """Insert an ActivityEvent record. Commits immediately.

    Args:
        db: SQLAlchemy database session.
        event_type: Type of event (scrape, score, generate, review, system).
        message: Human-readable summary of the event.
        client_id: Optional client scope for the event.
        metadata: Optional JSONB structured details.

    Returns:
        The created ActivityEvent record.
    """
    event = ActivityEvent(
        event_type=event_type,
        message=message,
        client_id=client_id,
        event_metadata=metadata,
    )
    db.add(event)
    db.flush()
    db.commit()
    db.refresh(event)
    return event


def get_activity_events(
    db: Session,
    client_id: uuid.UUID | None = None,
    event_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Retrieve activity events with optional filters, ordered by created_at DESC.

    Args:
        db: SQLAlchemy database session.
        client_id: Filter events to a specific client.
        event_type: Filter events by type.
        limit: Maximum number of events to return (default 50).
        offset: Number of events to skip (default 0).

    Returns:
        List of plain dicts with event data.
    """
    query = db.query(ActivityEvent)

    if client_id is not None:
        query = query.filter(ActivityEvent.client_id == client_id)
    if event_type is not None:
        query = query.filter(ActivityEvent.event_type == event_type)

    events = (
        query
        .order_by(desc(ActivityEvent.created_at))
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        {
            "id": str(event.id),
            "client_id": str(event.client_id) if event.client_id else None,
            "event_type": event.event_type,
            "message": event.message,
            "metadata": event.event_metadata,
            "created_at": event.created_at,
        }
        for event in events
    ]


def get_pipeline_stats(db: Session, client_id: uuid.UUID) -> dict:
    """Compute pipeline statistics for a client.

    Returns a dict with nested structure:
        {
            "threads": {"total": int, "last_24h": int, "last_7d": int},
            "tags": {"engage": int, "monitor": int, "skip": int, "unscored": int},
            "drafts": {"pending": int, "approved": int, "rejected": int, "posted": int},
            "ai_costs": {"total": Decimal, "by_operation": {"scoring": Decimal, ...}},
        }
    """
    now = datetime.now(timezone.utc)
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)

    # --- Thread counts ---
    total_threads = (
        db.query(sa_func.count(RedditThread.id))
        .filter(RedditThread.client_id == client_id)
        .scalar()
    ) or 0

    threads_24h = (
        db.query(sa_func.count(RedditThread.id))
        .filter(
            RedditThread.client_id == client_id,
            RedditThread.created_at >= last_24h,
        )
        .scalar()
    ) or 0

    threads_7d = (
        db.query(sa_func.count(RedditThread.id))
        .filter(
            RedditThread.client_id == client_id,
            RedditThread.created_at >= last_7d,
        )
        .scalar()
    ) or 0

    # --- Tag distribution ---
    tag_rows = (
        db.query(RedditThread.tag, sa_func.count(RedditThread.id))
        .filter(RedditThread.client_id == client_id)
        .group_by(RedditThread.tag)
        .all()
    )

    tag_counts = {row[0]: row[1] for row in tag_rows}
    tags = {
        "engage": tag_counts.get("engage", 0),
        "monitor": tag_counts.get("monitor", 0),
        "skip": tag_counts.get("skip", 0),
        "unscored": tag_counts.get(None, 0),
    }

    # --- Draft status breakdown ---
    draft_rows = (
        db.query(CommentDraft.status, sa_func.count(CommentDraft.id))
        .filter(CommentDraft.client_id == client_id)
        .group_by(CommentDraft.status)
        .all()
    )

    draft_counts = {row[0]: row[1] for row in draft_rows}
    drafts = {
        "pending": draft_counts.get("pending", 0),
        "approved": draft_counts.get("approved", 0),
        "rejected": draft_counts.get("rejected", 0),
        "posted": draft_counts.get("posted", 0),
    }

    # --- AI cost totals ---
    total_cost = (
        db.query(sa_func.sum(AIUsageLog.cost_usd))
        .filter(AIUsageLog.client_id == client_id)
        .scalar()
    ) or Decimal("0")

    cost_rows = (
        db.query(AIUsageLog.operation, sa_func.sum(AIUsageLog.cost_usd))
        .filter(AIUsageLog.client_id == client_id)
        .group_by(AIUsageLog.operation)
        .all()
    )

    by_operation = {row[0]: row[1] or Decimal("0") for row in cost_rows}

    return {
        "threads": {
            "total": total_threads,
            "last_24h": threads_24h,
            "last_7d": threads_7d,
        },
        "tags": tags,
        "drafts": drafts,
        "ai_costs": {
            "total": total_cost,
            "by_operation": by_operation,
        },
    }


def get_scrape_freshness(db: Session, client_id: uuid.UUID) -> list[dict]:
    """Per-subreddit scrape freshness data for a client.

    Returns list of dicts:
        {
            "subreddit_name": str,
            "last_scraped_at": datetime | None,
            "total_posts_found": int,
            "avg_posts_new": float,
            "is_stale": bool,  # last_scraped_at > 24h ago or None
        }
    """
    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(hours=24)

    # Get active subreddits for this client
    subreddits = (
        db.query(ClientSubreddit)
        .filter(
            ClientSubreddit.client_id == client_id,
            ClientSubreddit.is_active == True,  # noqa: E712
        )
        .all()
    )

    results = []
    for sub in subreddits:
        # Aggregate ScrapeLog data for this subreddit
        agg = (
            db.query(
                sa_func.sum(ScrapeLog.posts_found).label("total_posts_found"),
                sa_func.avg(ScrapeLog.posts_new).label("avg_posts_new"),
            )
            .filter(
                ScrapeLog.client_id == client_id,
                ScrapeLog.subreddit_name == sub.subreddit_name,
            )
            .one()
        )

        total_posts_found = int(agg.total_posts_found) if agg.total_posts_found is not None else 0
        avg_posts_new = float(agg.avg_posts_new) if agg.avg_posts_new is not None else 0.0

        last_scraped = sub.last_scraped_at
        is_stale = last_scraped is None or last_scraped < stale_threshold

        results.append({
            "subreddit_name": sub.subreddit_name,
            "last_scraped_at": last_scraped,
            "total_posts_found": total_posts_found,
            "avg_posts_new": avg_posts_new,
            "is_stale": is_stale,
        })

    return results
