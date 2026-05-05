"""Scrape Queue Dashboard service.

Provides data for the admin queue monitoring dashboard — queue depth,
stale counts, processing speed, waiting list, ETA, and rate limiter
utilization.
"""

import logging
from datetime import datetime, timedelta, timezone

import redis
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.activity_event import ActivityEvent
from app.models.client import Client
from app.models.subreddit import ClientSubreddit
from app.services.distributed_lock import ScrapeDistributedLock
from app.services.rate_limiter import ScrapeRateLimiter

logger = logging.getLogger(__name__)


def get_queue_depth(db: Session) -> int:
    """Get total number of active subreddits in the queue.

    This is the total count of subreddits that could potentially be scraped
    (active subreddit + active client).
    """
    count = (
        db.query(sa_func.count(ClientSubreddit.id))
        .join(Client, Client.id == ClientSubreddit.client_id)
        .filter(
            ClientSubreddit.is_active.is_(True),
            Client.is_active.is_(True),
        )
        .scalar()
    )
    return count or 0


def get_stale_count(db: Session, freshness_hours: int) -> int:
    """Count subreddits past their freshness window.

    Args:
        db: Database session.
        freshness_hours: Freshness window in hours.

    Returns:
        Number of stale subreddits (last_scraped_at > freshness_hours ago or NULL).
    """
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(hours=freshness_hours)

    count = (
        db.query(sa_func.count(ClientSubreddit.id))
        .join(Client, Client.id == ClientSubreddit.client_id)
        .filter(
            ClientSubreddit.is_active.is_(True),
            Client.is_active.is_(True),
        )
        .filter(
            (ClientSubreddit.last_scraped_at.is_(None))
            | (ClientSubreddit.last_scraped_at < threshold)
        )
        .scalar()
    )
    return count or 0


def get_processing_speed(db: Session, window_minutes: int = 5) -> float:
    """Calculate current processing speed from recent ActivityEvents.

    Args:
        db: Database session.
        window_minutes: Time window to measure speed over (default 5 min).

    Returns:
        Requests per minute (float).
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=window_minutes)

    count = (
        db.query(sa_func.count(ActivityEvent.id))
        .filter(
            ActivityEvent.event_type == "scrape",
            ActivityEvent.created_at >= window_start,
            # Only count completion events (have posts_found in metadata)
            ActivityEvent.event_metadata.isnot(None),
        )
        .scalar()
    ) or 0

    if window_minutes <= 0:
        return 0.0

    return count / window_minutes


def get_waiting_list(
    db: Session,
    redis_client: redis.Redis,
    freshness_hours: int,
    limit: int = 50,
) -> list[dict]:
    """Get sorted list of subreddits waiting to be scraped.

    Args:
        db: Database session.
        redis_client: Redis client for lock checking.
        freshness_hours: Freshness window in hours.
        limit: Max items to return.

    Returns:
        List of dicts with subreddit_name, client_name, last_scraped_at,
        staleness_seconds, and is_locked flag.
    """
    now = datetime.now(timezone.utc)

    candidates = (
        db.query(
            ClientSubreddit.subreddit_name,
            ClientSubreddit.client_id,
            Client.client_name,
            ClientSubreddit.last_scraped_at,
        )
        .join(Client, Client.id == ClientSubreddit.client_id)
        .filter(
            ClientSubreddit.is_active.is_(True),
            Client.is_active.is_(True),
        )
        .order_by(
            ClientSubreddit.last_scraped_at.asc().nulls_first(),
            ClientSubreddit.subreddit_name.asc(),
        )
        .limit(limit)
        .all()
    )

    # Get locked subreddits
    try:
        lock = ScrapeDistributedLock(redis_client)
        locked_subs = set(lock.get_all_locks())
    except (redis.ConnectionError, Exception):
        locked_subs = set()

    result = []
    for c in candidates:
        if c.last_scraped_at is None:
            staleness_seconds = float("inf")
            staleness_display = "Never scraped"
        else:
            staleness_seconds = (now - c.last_scraped_at).total_seconds()
            # Format as human-readable
            hours = int(staleness_seconds // 3600)
            minutes = int((staleness_seconds % 3600) // 60)
            if hours > 0:
                staleness_display = f"{hours}h {minutes}m ago"
            else:
                staleness_display = f"{minutes}m ago"

        is_stale = (
            c.last_scraped_at is None
            or (now - c.last_scraped_at).total_seconds() > freshness_hours * 3600
        )

        result.append({
            "subreddit_name": c.subreddit_name,
            "client_name": c.client_name,
            "last_scraped_at": c.last_scraped_at,
            "staleness_seconds": staleness_seconds,
            "staleness_display": staleness_display,
            "is_locked": c.subreddit_name in locked_subs,
            "is_stale": is_stale,
        })

    return result


def get_queue_status(
    db: Session,
    redis_client: redis.Redis,
    freshness_hours: int,
    max_rpm: int,
) -> dict:
    """Build complete queue status for dashboard.

    Args:
        db: Database session.
        redis_client: Redis client.
        freshness_hours: Freshness window in hours.
        max_rpm: Configured max requests per minute.

    Returns:
        Dict with all dashboard metrics.
    """
    queue_depth = get_queue_depth(db)
    stale_count = get_stale_count(db, freshness_hours)
    speed = get_processing_speed(db)

    # ETA calculation
    if speed > 0 and stale_count > 0:
        eta_minutes = round(stale_count / speed, 1)
    elif stale_count == 0:
        eta_minutes = 0.0
    else:
        eta_minutes = None  # Cannot estimate (speed is 0)

    # Rate limiter utilization
    try:
        rate_limiter = ScrapeRateLimiter(redis_client)
        utilization = rate_limiter.get_utilization(max_rpm)
    except (redis.ConnectionError, Exception):
        utilization = {
            "current_count": 0,
            "max_rpm": max_rpm,
            "effective_limit": max_rpm,
            "utilization_pct": 0.0,
            "in_backoff": False,
        }

    # Currently processing (locked subreddits)
    try:
        lock = ScrapeDistributedLock(redis_client)
        currently_processing = lock.get_all_locks()
    except (redis.ConnectionError, Exception):
        currently_processing = []

    return {
        "queue_depth": queue_depth,
        "stale_count": stale_count,
        "processing_speed": round(speed, 2),
        "eta_minutes": eta_minutes,
        "rate_limiter": utilization,
        "currently_processing": currently_processing,
        "all_fresh": stale_count == 0,
    }


def get_pipeline_metrics(db: Session, freshness_hours: int) -> dict:
    """Get pipeline operational metrics for the admin dashboard.

    Returns:
        Dict with pending_comments, avg_generation_to_post_hours,
        and stalest_subreddits.
    """
    from app.models.comment_draft import CommentDraft

    now = datetime.now(timezone.utc)

    # --- Pending comments count ---
    pending_count = (
        db.query(sa_func.count(CommentDraft.id))
        .filter(CommentDraft.status == "pending")
        .scalar()
    ) or 0

    # --- Average delay from generation to post (for posted comments) ---
    # Only consider comments that have been posted (have posted_at)
    posted_comments = (
        db.query(
            CommentDraft.created_at,
            CommentDraft.posted_at,
        )
        .filter(
            CommentDraft.status == "posted",
            CommentDraft.posted_at.isnot(None),
        )
        .order_by(CommentDraft.posted_at.desc())
        .limit(100)  # Last 100 posted for average
        .all()
    )

    if posted_comments:
        total_hours = sum(
            (c.posted_at - c.created_at).total_seconds() / 3600
            for c in posted_comments
            if c.posted_at and c.created_at
        )
        avg_generation_to_post_hours = round(total_hours / len(posted_comments), 1)
    else:
        avg_generation_to_post_hours = None

    # --- Stalest subreddits (top 5 oldest last_scraped_at) ---
    stalest = (
        db.query(
            ClientSubreddit.subreddit_name,
            Client.client_name,
            ClientSubreddit.last_scraped_at,
        )
        .join(Client, Client.id == ClientSubreddit.client_id)
        .filter(
            ClientSubreddit.is_active.is_(True),
            Client.is_active.is_(True),
        )
        .order_by(
            ClientSubreddit.last_scraped_at.asc().nulls_first(),
        )
        .limit(5)
        .all()
    )

    stalest_list = []
    for s in stalest:
        if s.last_scraped_at is None:
            age_display = "Never"
            age_hours = None
        else:
            age_seconds = (now - s.last_scraped_at).total_seconds()
            age_hours = round(age_seconds / 3600, 1)
            if age_hours >= 24:
                age_display = f"{int(age_hours // 24)}d {int(age_hours % 24)}h"
            else:
                age_display = f"{age_hours}h"

        stalest_list.append({
            "subreddit_name": s.subreddit_name,
            "client_name": s.client_name,
            "last_scraped_at": s.last_scraped_at,
            "age_hours": age_hours,
            "age_display": age_display,
        })

    # --- Comments by status breakdown ---
    status_counts = (
        db.query(CommentDraft.status, sa_func.count(CommentDraft.id))
        .group_by(CommentDraft.status)
        .all()
    )
    comments_by_status = {row[0]: row[1] for row in status_counts}

    return {
        "pending_comments": pending_count,
        "approved_comments": comments_by_status.get("approved", 0),
        "posted_comments": comments_by_status.get("posted", 0),
        "rejected_comments": comments_by_status.get("rejected", 0),
        "avg_generation_to_post_hours": avg_generation_to_post_hours,
        "stalest_subreddits": stalest_list,
    }


def scrape_subreddit_immediate(db: Session, subreddit_name: str, client_id: str) -> dict:
    """Synchronously scrape a single subreddit immediately.

    Used when a new subreddit is added — provides instant data without
    waiting for the queue_tick cycle. Respects rate limits but bypasses
    the queue priority system.

    Args:
        db: Database session.
        subreddit_name: Subreddit to scrape (without r/ prefix).
        client_id: UUID string of the client.

    Returns:
        Dict with posts_found, posts_new, duration_ms, or error info.
    """
    import time
    import uuid

    from app.models.scrape_log import ScrapeLog
    from app.models.thread import RedditThread
    from app.services.reddit import scrape_subreddit, deduplicate_posts
    from app.services.transparency import record_activity_event

    client_uuid = uuid.UUID(client_id)
    start_time = time.time()

    try:
        # Scrape
        posts = scrape_subreddit(subreddit_name, limit=50, max_age_hours=24)

        # Deduplicate
        existing_ids = set(
            row[0]
            for row in db.query(RedditThread.reddit_native_id)
            .filter(RedditThread.client_id == client_id)
            .all()
        )
        new_posts = deduplicate_posts(posts, existing_ids)

        # Save new threads
        for post in new_posts:
            thread = RedditThread(
                client_id=client_id,
                type="professional",
                reddit_native_id=post["reddit_native_id"],
                subreddit=post["subreddit"],
                post_title=post["post_title"],
                post_body=post["post_body"],
                comments_json=post["comments_json"],
                url=post["url"],
                author=post["author"],
                score=post["score"],
                ups=post["ups"],
                downs=post["downs"],
                scraped_at=datetime.now(timezone.utc),
            )
            db.add(thread)
        db.commit()

        # Update last_scraped_at
        sub_record = (
            db.query(ClientSubreddit)
            .filter(
                ClientSubreddit.client_id == client_id,
                ClientSubreddit.subreddit_name == subreddit_name,
            )
            .first()
        )
        if sub_record:
            sub_record.last_scraped_at = datetime.now(timezone.utc)

        # Record ScrapeLog
        duration_ms = int((time.time() - start_time) * 1000)
        scrape_log = ScrapeLog(
            client_id=client_uuid,
            subreddit_name=subreddit_name,
            posts_found=len(posts),
            posts_new=len(new_posts),
            duration_ms=duration_ms,
            errors=None,
        )
        db.add(scrape_log)
        db.commit()

        # Record activity event
        record_activity_event(
            db, "scrape",
            f"Immediate scrape: r/{subreddit_name} — {len(posts)} found, {len(new_posts)} new ({duration_ms}ms)",
            client_uuid,
            {"subreddit_name": subreddit_name, "posts_found": len(posts), "posts_new": len(new_posts), "duration_ms": duration_ms, "trigger": "immediate"},
        )

        return {"status": "success", "posts_found": len(posts), "posts_new": len(new_posts), "duration_ms": duration_ms}

    except Exception as e:
        # Log error but don't crash — the subreddit was still added
        try:
            record_activity_event(
                db, "system",
                f"Immediate scrape failed: r/{subreddit_name} — {str(e)[:200]}",
                client_uuid,
                {"subreddit_name": subreddit_name, "error": str(e)[:500], "trigger": "immediate"},
            )
        except Exception:
            pass
        return {"status": "error", "error": str(e)[:200]}
