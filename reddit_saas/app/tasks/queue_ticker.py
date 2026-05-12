"""Queue Ticker — continuous priority-based scraping queue.

Replaces the batch-oriented cron approach with a single-dispatch-per-tick
model. Each tick selects the most stale subreddit, checks the rate limiter,
acquires a distributed lock, and dispatches a scrape worker.

Tasks:
    queue_tick: Periodic task fired by Celery Beat every 60s.
    scrape_single_subreddit: Legacy scrape task (kept for backward compatibility).
"""

import logging
import time
import uuid
from datetime import datetime, timezone

import redis
import sqlalchemy.exc

from app.database import SessionLocal
from app.models.client import Client
from app.models.scrape_log import ScrapeLog
from app.models.subreddit import ClientSubreddit, Subreddit, ClientSubredditAssignment
from app.models.thread import RedditThread
from app.services.distributed_lock import ScrapeDistributedLock
from app.services.rate_limiter import ScrapeRateLimiter
from app.services.settings import get_setting
from app.services.transparency import record_activity_event
from app.tasks.worker import celery_app

logger = logging.getLogger(__name__)

# Redis key for tick-interval gating
_LAST_TICK_KEY = "queue_tick:last_run"


def _get_redis_client() -> redis.Redis:
    """Create a Redis client from bootstrap config."""
    from app.config import get_settings
    settings = get_settings()
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


@celery_app.task(name="queue_tick")
def queue_tick() -> dict:
    """Single tick of the scrape queue.

    Fired by Celery Beat every 60s. Internally gates execution based on
    the configurable tick interval from system_settings.

    Queries the `subreddits` table ordered by last_scraped_at ASC NULLS FIRST,
    joining to client_subreddit_assignments (at least one active) and clients
    (is_active=true). Dispatches scrape_subreddit_shared(subreddit_id).

    Returns:
        Status dict: {"status": str, "subreddit": str|None, ...}
    """
    from app.tasks.scraping import scrape_subreddit_shared

    try:
        redis_client = _get_redis_client()
    except redis.ConnectionError:
        logger.warning("queue_tick: Redis unavailable, skipping tick")
        return {"status": "error", "reason": "redis_unavailable"}

    # --- Tick interval gating ---
    try:
        db = SessionLocal()
        tick_interval = int(get_setting(db, "scrape_tick_interval_seconds") or "60")
    except (sqlalchemy.exc.OperationalError, Exception) as e:
        logger.warning("queue_tick: Database unavailable for settings: %s", e)
        return {"status": "error", "reason": "db_unavailable"}

    try:
        last_run_str = redis_client.get(_LAST_TICK_KEY)
        if last_run_str:
            elapsed = time.time() - float(last_run_str)
            if elapsed < tick_interval:
                return {"status": "skipped", "reason": "tick_interval_not_elapsed"}
    except (redis.ConnectionError, ValueError):
        pass  # Proceed if we can't check

    # Mark this tick
    try:
        redis_client.set(_LAST_TICK_KEY, str(time.time()), ex=tick_interval * 2)
    except redis.ConnectionError:
        pass  # Non-critical

    # --- Check scrape_enabled ---
    try:
        from app.services.settings import is_scrape_enabled
        if not is_scrape_enabled(db):
            logger.info("queue_tick: Scraping is paused (scrape_enabled=false)")
            db.close()
            return {"status": "paused"}
    except (sqlalchemy.exc.OperationalError, Exception) as e:
        logger.warning("queue_tick: DB error reading scrape_enabled: %s", e)
        db.close()
        return {"status": "error", "reason": "db_unavailable"}

    # --- Check rate limiter ---
    try:
        rate_limiter = ScrapeRateLimiter(redis_client)
        max_rpm = int(get_setting(db, "scrape_rate_limit_rpm") or "30")
        if not rate_limiter.is_allowed(max_rpm):
            logger.debug("queue_tick: Rate limit reached (%d rpm), skipping", max_rpm)
            db.close()
            return {"status": "rate_limited"}
    except redis.ConnectionError:
        logger.warning("queue_tick: Redis unavailable for rate limiter, skipping tick")
        db.close()
        return {"status": "error", "reason": "redis_unavailable"}

    # --- Query next stale subreddit from shared registry ---
    # Query subreddits table, requiring at least one active assignment
    # where the corresponding client is also active.
    try:
        candidates = (
            db.query(
                Subreddit.id,
                Subreddit.subreddit_name,
                Subreddit.last_scraped_at,
            )
            .join(ClientSubredditAssignment, ClientSubredditAssignment.subreddit_id == Subreddit.id)
            .join(Client, Client.id == ClientSubredditAssignment.client_id)
            .filter(
                Subreddit.is_active.is_(True),
                ClientSubredditAssignment.is_active.is_(True),
                Client.is_active.is_(True),
            )
            .group_by(Subreddit.id, Subreddit.subreddit_name, Subreddit.last_scraped_at)
            .order_by(
                Subreddit.last_scraped_at.asc().nulls_first(),
                Subreddit.subreddit_name.asc(),
            )
            .limit(5)
            .all()
        )
    except sqlalchemy.exc.OperationalError as e:
        logger.warning("queue_tick: Database unavailable for queue query: %s", e)
        db.close()
        return {"status": "error", "reason": "db_unavailable"}

    if not candidates:
        logger.debug("queue_tick: No active subreddits found")
        db.close()
        return {"status": "all_fresh"}

    # Check freshness window — if all candidates are fresh, skip
    freshness_hours = int(get_setting(db, "scrape_freshness_window_hours") or "12")
    now = datetime.now(timezone.utc)

    # Filter to only stale candidates (or NULL last_scraped_at)
    stale_candidates = []
    for c in candidates:
        if c.last_scraped_at is None:
            stale_candidates.append(c)
        else:
            age_hours = (now - c.last_scraped_at).total_seconds() / 3600
            if age_hours >= freshness_hours:
                stale_candidates.append(c)

    if not stale_candidates:
        logger.debug("queue_tick: All subreddits are fresh (within %dh window)", freshness_hours)
        db.close()
        return {"status": "all_fresh"}

    # --- Try to acquire lock (up to 3 candidates) ---
    lock = ScrapeDistributedLock(redis_client)
    dispatched_sub = None

    for candidate in stale_candidates[:3]:
        subreddit_name = candidate.subreddit_name
        if lock.acquire(subreddit_name):
            dispatched_sub = candidate
            break

    if dispatched_sub is None:
        logger.debug("queue_tick: All top candidates are locked, skipping")
        db.close()
        return {"status": "all_locked"}

    # --- Record rate limiter hit and dispatch ---
    try:
        rate_limiter.record_request()
    except redis.ConnectionError:
        # Non-critical — we already checked is_allowed
        pass

    subreddit_name = dispatched_sub.subreddit_name
    subreddit_id = str(dispatched_sub.id)

    db.close()

    # Dispatch the shared scrape worker (subreddit-centric, no client_id)
    scrape_subreddit_shared.delay(subreddit_id)

    logger.info("queue_tick: Dispatched shared scrape for r/%s (subreddit_id: %s)", subreddit_name, subreddit_id)
    return {"status": "dispatched", "subreddit": subreddit_name, "subreddit_id": subreddit_id}


@celery_app.task(name="scrape_single_subreddit", bind=True, max_retries=0)
def scrape_single_subreddit(self, subreddit_name: str, client_id: str) -> dict:
    """Scrape one subreddit for one client. Called by queue_tick.

    Args:
        subreddit_name: The subreddit to scrape (without r/ prefix).
        client_id: UUID string of the client.

    Returns:
        Status dict with scrape results.
    """
    from app.services.reddit import scrape_subreddit, deduplicate_posts

    redis_client = _get_redis_client()
    lock = ScrapeDistributedLock(redis_client)
    rate_limiter = ScrapeRateLimiter(redis_client)
    db = SessionLocal()
    client_uuid = uuid.UUID(client_id)
    start_time = time.time()

    try:
        # Record start event
        client = db.query(Client).filter(Client.id == client_id).first()
        client_name = client.client_name if client else "Unknown"

        record_activity_event(
            db,
            "scrape",
            f"Starting scrape of r/{subreddit_name} for {client_name}",
            client_uuid,
            {"subreddit_name": subreddit_name, "phase": "start"},
        )

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

        # Record completion event
        message = f"Scraped r/{subreddit_name}: {len(posts)} found, {len(new_posts)} new ({duration_ms}ms)"
        metadata = {
            "subreddit_name": subreddit_name,
            "posts_found": len(posts),
            "posts_new": len(new_posts),
            "duration_ms": duration_ms,
        }
        record_activity_event(db, "scrape", message, client_uuid, metadata)

        logger.info("scrape_single_subreddit: %s", message)
        return {
            "status": "success",
            "subreddit": subreddit_name,
            "posts_found": len(posts),
            "posts_new": len(new_posts),
            "duration_ms": duration_ms,
        }

    except Exception as e:
        # Check if it's a Reddit 429 (TooManyRequests)
        error_str = str(e)
        is_rate_limited = "429" in error_str or "too many requests" in error_str.lower()

        # last_scraped_at tracks the last attempt (success or failure) so the
        # admin UI doesn't show "Never" forever when scraping is broken.
        # The error itself is preserved in scrape_log.errors and activity_events.
        try:
            db.rollback()
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
            duration_ms = int((time.time() - start_time) * 1000)
            db.add(ScrapeLog(
                client_id=client_uuid,
                subreddit_name=subreddit_name,
                posts_found=0,
                posts_new=0,
                duration_ms=duration_ms,
                errors=error_str[:500],
            ))
            db.commit()
        except Exception as inner:
            logger.warning("scrape_single_subreddit: failed to record error scrape_log: %s", inner)
            db.rollback()

        if is_rate_limited:
            rate_limiter.activate_backoff(duration_seconds=300)
            record_activity_event(
                db,
                "system",
                f"Reddit 429 rate limit for r/{subreddit_name}",
                client_uuid,
                {"subreddit_name": subreddit_name, "error": "HTTP 429"},
            )
            logger.warning("scrape_single_subreddit: Reddit 429 for r/%s, backoff activated", subreddit_name)
            return {"status": "rate_limited", "subreddit": subreddit_name}
        else:
            record_activity_event(
                db,
                "system",
                f"Scrape failed for r/{subreddit_name}: {error_str[:200]}",
                client_uuid,
                {"subreddit_name": subreddit_name, "error": error_str[:500]},
            )
            logger.error("scrape_single_subreddit: Failed for r/%s: %s", subreddit_name, e)
            return {"status": "error", "subreddit": subreddit_name, "error": error_str[:200]}

    finally:
        lock.release(subreddit_name)
        db.close()
