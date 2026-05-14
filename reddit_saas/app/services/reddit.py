"""Reddit API service using PRAW.

Handles subreddit scraping, comment tree flattening, and deduplication.
Full logging of all Reddit API interactions for audit trail.

ALL Reddit API calls go through get_reddit_client() which enforces
the global rate limiter (Redis sliding window, 30 RPM default).
"""

import json
import logging
import time
from datetime import datetime, timezone, timedelta

import praw

from app.services.sanitize import ensure_subreddit_bare
from praw.models import Submission
from prawcore.exceptions import (
    NotFound, Forbidden, TooManyRequests,
    RequestException, ResponseException, ServerError,
)

from app.config import get_config

logger = logging.getLogger(__name__)

# Global rate limiter instance (lazy-initialized)
_global_rate_limiter = None
_GLOBAL_MAX_RPM = 30  # Default; overridden by DB setting when available


def _get_global_rate_limiter():
    """Get or create the global Reddit API rate limiter (Redis sliding window)."""
    global _global_rate_limiter
    if _global_rate_limiter is not None:
        return _global_rate_limiter

    try:
        import redis
        from app.config import get_settings
        from app.services.rate_limiter import ScrapeRateLimiter

        settings = get_settings()
        redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        _global_rate_limiter = ScrapeRateLimiter(redis_client)
        return _global_rate_limiter
    except Exception as e:
        logger.warning("Failed to initialize global rate limiter: %s — proceeding without", e)
        return None


def _wait_for_rate_limit(caller: str = "unknown") -> None:
    """Block until the global rate limiter allows a request. Max wait 30s."""
    limiter = _get_global_rate_limiter()
    if limiter is None:
        return  # No limiter available — proceed without blocking

    try:
        # Try to get max_rpm from DB settings (cached)
        max_rpm = _GLOBAL_MAX_RPM
        try:
            from app.services.settings import get_setting
            from app.database import SessionLocal
            db = SessionLocal()
            try:
                val = get_setting(db, "scrape_rate_limit_rpm")
                if val:
                    max_rpm = int(val)
            finally:
                db.close()
        except Exception:
            pass  # Use default

        # Wait loop — check every 1s, max 30s
        waited = 0
        while not limiter.is_allowed(max_rpm):
            if waited >= 30:
                logger.warning(
                    "REDDIT_RATE_LIMIT | caller=%s | action=timeout | waited=30s — proceeding anyway",
                    caller,
                )
                break
            time.sleep(1)
            waited += 1

        if waited > 0:
            logger.info(
                "REDDIT_RATE_LIMIT | caller=%s | action=waited | seconds=%d",
                caller, waited,
            )

        # Record this request
        limiter.record_request()

    except Exception as e:
        logger.warning("Rate limiter error (non-fatal): %s", e)


def get_reddit_client(caller: str = "unknown") -> praw.Reddit:
    """Create a read-only Reddit client. Enforces global rate limit.

    Args:
        caller: Identifier for logging (e.g. "scrape_subreddit", "health_check")
    """
    _wait_for_rate_limit(caller)

    client_id = get_config("reddit_client_id")
    client_secret = get_config("reddit_client_secret")
    user_agent = get_config("reddit_user_agent")
    client = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
    )
    logger.debug(
        "Reddit client created | caller=%s | user_agent=%s | read_only=%s",
        caller, user_agent, client.read_only,
    )
    return client


def _log_rate_limit(reddit: praw.Reddit) -> None:
    """Log Reddit API rate limit status from the auth object."""
    try:
        auth = reddit._core._authorizer
        if hasattr(auth, "_rate_limiter"):
            rl = auth._rate_limiter
            remaining = getattr(rl, "remaining", "?")
            reset_ts = getattr(rl, "reset_timestamp", "?")
            used = getattr(rl, "used", "?")
            logger.info(
                "Reddit rate limit status | remaining=%s | used=%s | reset_ts=%s",
                remaining, used, reset_ts,
            )
    except Exception:
        pass  # Rate limit info not critical


def scrape_subreddit(
    subreddit_name: str,
    limit: int = 50,
    max_age_hours: int = 24,
    sort: str = "hot",
    time_filter: str | None = None,
    min_score: int = 0,
) -> list[dict]:
    """Scrape posts from a subreddit.

    Args:
        subreddit_name: Name without r/ prefix (e.g. 'cybersecurity')
        limit: Max posts to fetch
        max_age_hours: Only return posts newer than this (0 = no age filter)
        sort: 'hot', 'new', or 'top'
        time_filter: For sort='top' — 'hour', 'day', 'week', 'month', 'year', 'all'.
                     Defaults to 'day' if not specified.
        min_score: Minimum post score (upvotes) to include. 0 = no filter.

    Returns:
        List of post dicts with standardized keys.
    """
    logger.info(
        "REDDIT_API_CALL | action=scrape_subreddit | subreddit=r/%s | sort=%s | limit=%d | max_age_hours=%d | time_filter=%s | min_score=%d",
        subreddit_name, sort, limit, max_age_hours, time_filter or "default", min_score,
    )
    start_time = time.time()

    subreddit_name = ensure_subreddit_bare(subreddit_name)

    reddit = get_reddit_client("scrape_subreddit")
    subreddit = reddit.subreddit(subreddit_name)

    # Age cutoff: 0 means no age filter (for repurpose mode)
    cutoff = None
    if max_age_hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    try:
        if sort == "hot":
            submissions = subreddit.hot(limit=limit)
        elif sort == "new":
            submissions = subreddit.new(limit=limit)
        elif sort == "top":
            effective_time_filter = time_filter or "day"
            submissions = subreddit.top(limit=limit, time_filter=effective_time_filter)
        else:
            submissions = subreddit.hot(limit=limit)

        posts = []
        skipped_stickied = 0
        skipped_old = 0
        skipped_locked = 0
        skipped_low_score = 0
        api_calls_estimate = 1  # Initial listing request

        for submission in submissions:
            # Skip stickied posts
            if submission.stickied:
                skipped_stickied += 1
                continue

            # Skip posts older than cutoff (if age filter is active)
            if cutoff is not None:
                created_utc = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)
                if created_utc < cutoff:
                    skipped_old += 1
                    continue

            # Skip locked posts (cannot comment on them)
            if submission.locked:
                skipped_locked += 1
                continue

            # Skip posts below minimum score threshold (for repurpose mode)
            if min_score > 0 and submission.score < min_score:
                skipped_low_score += 1
                continue

            post = _submission_to_dict(submission)
            api_calls_estimate += 1  # Each submission's comments = 1 API call
            posts.append(post)

        duration_ms = int((time.time() - start_time) * 1000)
        _log_rate_limit(reddit)

        logger.info(
            "REDDIT_API_RESULT | action=scrape_subreddit | subreddit=r/%s | "
            "posts_returned=%d | skipped_stickied=%d | skipped_old=%d | skipped_locked=%d | "
            "skipped_low_score=%d | est_api_calls=%d | duration_ms=%d",
            subreddit_name, len(posts), skipped_stickied, skipped_old, skipped_locked,
            skipped_low_score, api_calls_estimate, duration_ms,
        )
        return posts

    except TooManyRequests as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(
            "REDDIT_API_ERROR | action=scrape_subreddit | subreddit=r/%s | "
            "error=RATE_LIMITED | duration_ms=%d | details=%s",
            subreddit_name, duration_ms, str(e),
        )
        raise

    except (NotFound, Forbidden) as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(
            "REDDIT_API_ERROR | action=scrape_subreddit | subreddit=r/%s | "
            "error=%s | duration_ms=%d | details=%s",
            subreddit_name, type(e).__name__, duration_ms, str(e),
        )
        raise

    except (RequestException, ResponseException, ServerError) as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(
            "REDDIT_API_ERROR | action=scrape_subreddit | subreddit=r/%s | "
            "error=%s | duration_ms=%d | details=%s",
            subreddit_name, type(e).__name__, duration_ms, str(e),
        )
        raise

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.exception(
            "REDDIT_API_ERROR | action=scrape_subreddit | subreddit=r/%s | "
            "error=UNEXPECTED | duration_ms=%d",
            subreddit_name, duration_ms,
        )
        raise


def fetch_comments(submission_id: str, max_comments: int = 100) -> list[dict]:
    """Fetch and flatten comment tree for a submission.

    Args:
        submission_id: Reddit submission ID (without t3_ prefix)
        max_comments: Max comments to return

    Returns:
        Flat list of comment dicts with depth info.
    """
    logger.info(
        "REDDIT_API_CALL | action=fetch_comments | submission_id=%s | max_comments=%d",
        submission_id, max_comments,
    )
    start_time = time.time()

    reddit = get_reddit_client("fetch_comments")
    submission = reddit.submission(id=submission_id)

    # Replace "more comments" placeholders (limit to avoid too many API calls)
    replace_more_count = 3
    submission.comments.replace_more(limit=replace_more_count)

    comments = []
    _flatten_comments(submission.comments.list(), comments, max_comments)

    duration_ms = int((time.time() - start_time) * 1000)
    _log_rate_limit(reddit)

    logger.info(
        "REDDIT_API_RESULT | action=fetch_comments | submission_id=%s | "
        "comments_fetched=%d | replace_more_limit=%d | duration_ms=%d",
        submission_id, len(comments), replace_more_count, duration_ms,
    )
    return comments


def _flatten_comments(comment_list, result: list[dict], max_count: int) -> None:
    """Recursively flatten comment tree into a flat list."""
    for comment in comment_list:
        if len(result) >= max_count:
            break

        # Skip deleted/removed comments
        if not hasattr(comment, "body") or comment.body in ("[deleted]", "[removed]"):
            continue

        result.append({
            "id": comment.id,
            "author": str(comment.author) if comment.author else "[deleted]",
            "body": comment.body,
            "depth": comment.depth,
            "upvotes": comment.score,
            "created_utc": comment.created_utc,
        })


def _submission_to_dict(submission: Submission) -> dict:
    """Convert a PRAW Submission to a standardized dict."""
    # Fetch comments inline (light version — top-level only for scoring)
    submission.comments.replace_more(limit=0)
    comments = []
    for comment in submission.comments[:20]:  # Top 20 comments for context
        if not hasattr(comment, "body"):
            continue
        comments.append({
            "author": str(comment.author) if comment.author else "[deleted]",
            "body": comment.body,
            "depth": comment.depth,
            "upvotes": comment.score,
            "id": comment.id,
            "replies": _get_replies(comment, max_depth=3),
        })

    # Extract post image if present
    post_image = None
    if hasattr(submission, "preview") and submission.preview:
        try:
            images = submission.preview.get("images", [])
            if images:
                post_image = images[0]["source"]["url"]
        except (KeyError, IndexError):
            pass

    logger.debug(
        "REDDIT_DATA | action=submission_to_dict | id=%s | subreddit=r/%s | "
        "title=%s | score=%d | num_comments=%d | comments_loaded=%d",
        submission.id, submission.subreddit.display_name,
        submission.title[:80], submission.score, submission.num_comments, len(comments),
    )

    return {
        "reddit_native_id": submission.id,
        "subreddit": submission.subreddit.display_name,
        "post_title": submission.title,
        "post_body": submission.selftext or "",
        "comments_json": json.dumps(comments, ensure_ascii=False),
        "url": f"https://www.reddit.com{submission.permalink}",
        "author": str(submission.author) if submission.author else "[deleted]",
        "score": submission.score,
        "ups": submission.ups,
        "downs": submission.downs,
        "ups_downs_ratio": submission.upvote_ratio,
        "post_image": post_image,
        "created_utc": submission.created_utc,
        "num_comments": submission.num_comments,
        "is_locked": submission.locked,
    }


def _get_replies(comment, max_depth: int = 3, current_depth: int = 1) -> list[dict]:
    """Get nested replies up to max_depth."""
    if current_depth >= max_depth:
        return []

    replies = []
    for reply in comment.replies:
        if not hasattr(reply, "body") or reply.body in ("[deleted]", "[removed]"):
            continue
        replies.append({
            "author": str(reply.author) if reply.author else "[deleted]",
            "body": reply.body,
            "depth": reply.depth,
            "upvotes": reply.score,
            "id": reply.id,
            "replies": _get_replies(reply, max_depth, current_depth + 1),
        })

    return replies


def deduplicate_posts(posts: list[dict], existing_ids: set[str]) -> list[dict]:
    """Remove posts that already exist in the database.

    Args:
        posts: List of scraped post dicts
        existing_ids: Set of reddit_native_ids already in DB

    Returns:
        Only new posts not in existing_ids.
    """
    new_posts = []
    seen = set()

    for post in posts:
        native_id = post["reddit_native_id"]
        if native_id in existing_ids or native_id in seen:
            continue
        seen.add(native_id)
        new_posts.append(post)

    logger.info(
        "REDDIT_DEDUP | total_scraped=%d | already_in_db=%d | new_posts=%d",
        len(posts), len(posts) - len(new_posts), len(new_posts),
    )
    return new_posts


def check_thread_liveness(reddit_native_id: str) -> dict:
    """Check if a Reddit thread is still open for comments.

    Makes a lightweight PRAW call to fetch the submission and check its
    locked/removed/archived status. Use this before showing old threads
    in the review queue or before posting.

    Args:
        reddit_native_id: The Reddit submission ID (e.g. "1abc2de").

    Returns:
        Dict with keys:
            - is_locked: bool — thread is locked by mods
            - is_removed: bool — thread was removed
            - is_archived: bool — thread is archived (>6 months, auto-locked)
            - is_commentable: bool — True only if comments can still be posted
            - score: int — current score (useful for freshness)
            - num_comments: int — current comment count
    """
    logger.info(
        "REDDIT_API_CALL | action=check_thread_liveness | submission_id=%s",
        reddit_native_id,
    )
    start_time = time.time()

    try:
        reddit = get_reddit_client("check_thread_liveness")
        submission = reddit.submission(id=reddit_native_id)

        # Access attributes to trigger the API call
        is_locked = submission.locked
        is_removed = submission.removed_by_category is not None
        is_archived = submission.archived

        is_commentable = not (is_locked or is_removed or is_archived)

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(
            "REDDIT_API_RESULT | action=check_thread_liveness | submission_id=%s | "
            "locked=%s | removed=%s | archived=%s | commentable=%s | duration_ms=%d",
            reddit_native_id, is_locked, is_removed, is_archived,
            is_commentable, duration_ms,
        )

        return {
            "is_locked": is_locked,
            "is_removed": is_removed,
            "is_archived": is_archived,
            "is_commentable": is_commentable,
            "score": submission.score,
            "num_comments": submission.num_comments,
        }

    except (NotFound, Forbidden) as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.warning(
            "REDDIT_API_RESULT | action=check_thread_liveness | submission_id=%s | "
            "error=%s | duration_ms=%d — treating as non-commentable",
            reddit_native_id, type(e).__name__, duration_ms,
        )
        return {
            "is_locked": True,
            "is_removed": True,
            "is_archived": False,
            "is_commentable": False,
            "score": 0,
            "num_comments": 0,
        }

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(
            "REDDIT_API_ERROR | action=check_thread_liveness | submission_id=%s | "
            "error=%s | duration_ms=%d",
            reddit_native_id, type(e).__name__, duration_ms,
        )
        # On error, don't block the pipeline — assume commentable
        return {
            "is_locked": False,
            "is_removed": False,
            "is_archived": False,
            "is_commentable": True,
            "score": 0,
            "num_comments": 0,
        }
