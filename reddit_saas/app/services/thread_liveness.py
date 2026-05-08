"""Thread liveness service.

Handles detection and management of locked/removed/archived Reddit threads.
Prevents wasting LLM resources on threads that can no longer receive comments.
"""

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.models.thread import RedditThread
from app.models.comment_draft import CommentDraft
from app.services.reddit import check_thread_liveness

logger = logging.getLogger(__name__)

# Threads older than this threshold get a liveness check before generation
STALE_THREAD_HOURS = 12


def refresh_thread_locked_status(db: Session, thread: RedditThread) -> bool:
    """Check Reddit API and update thread's is_locked status.

    Args:
        db: Database session.
        thread: The thread to check.

    Returns:
        True if thread is commentable, False if locked/removed/archived.
    """
    result = check_thread_liveness(thread.reddit_native_id)

    if not result["is_commentable"]:
        if not thread.is_locked:
            thread.is_locked = True
            thread.locked_detected_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(
                "Thread %s marked as locked (locked=%s, removed=%s, archived=%s)",
                thread.reddit_native_id,
                result["is_locked"],
                result["is_removed"],
                result["is_archived"],
            )
        return False

    # Thread is still open — if it was previously marked locked, unmark it
    if thread.is_locked:
        thread.is_locked = False
        thread.locked_detected_at = None
        db.commit()
        logger.info(
            "Thread %s unmarked as locked (was false positive or unlocked by mods)",
            thread.reddit_native_id,
        )

    return True


def is_thread_stale(thread: RedditThread) -> bool:
    """Check if a thread is old enough to warrant a liveness check.

    Args:
        thread: The thread to evaluate.

    Returns:
        True if thread was scraped more than STALE_THREAD_HOURS ago.
    """
    if not thread.scraped_at:
        return True
    age = datetime.now(timezone.utc) - thread.scraped_at
    return age > timedelta(hours=STALE_THREAD_HOURS)


def check_and_filter_thread(db: Session, thread: RedditThread) -> bool:
    """Combined check: if thread is already locked, skip. If stale, verify liveness.

    Use this before generating a comment for a thread.

    Args:
        db: Database session.
        thread: The thread to check.

    Returns:
        True if thread is safe to generate for, False if should be skipped.
    """
    # Already known to be locked
    if thread.is_locked:
        return False

    # Fresh thread — no need to re-check
    if not is_thread_stale(thread):
        return True

    # Stale thread — verify with Reddit API
    return refresh_thread_locked_status(db, thread)


def expire_drafts_for_locked_threads(db: Session, client_id=None) -> int:
    """Find pending drafts for locked threads and auto-reject them.

    This prevents operators from wasting time reviewing comments that
    cannot be posted.

    Args:
        db: Database session.
        client_id: Optional — limit to a specific client.

    Returns:
        Number of drafts expired.
    """
    query = (
        db.query(CommentDraft)
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .filter(
            CommentDraft.status == "pending",
            RedditThread.is_locked.is_(True),
        )
    )
    if client_id:
        query = query.filter(CommentDraft.client_id == client_id)

    drafts = query.all()

    for draft in drafts:
        draft.status = "rejected"

    if drafts:
        db.commit()
        logger.info(
            "Expired %d pending drafts for locked threads (client=%s)",
            len(drafts),
            client_id or "all",
        )

    return len(drafts)


def bulk_refresh_locked_status(db: Session, max_threads: int = 50) -> dict:
    """Refresh locked status for threads with pending drafts that are stale.

    Prioritizes threads that have pending drafts (resource conservation).
    Called periodically by the scheduler.

    Args:
        db: Database session.
        max_threads: Maximum threads to check per run (rate limit protection).

    Returns:
        Dict with counts: checked, newly_locked, still_open.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_THREAD_HOURS)

    # Find threads with pending drafts that were scraped before the cutoff
    threads = (
        db.query(RedditThread)
        .join(CommentDraft, CommentDraft.thread_id == RedditThread.id)
        .filter(
            CommentDraft.status == "pending",
            RedditThread.is_locked.is_(False),
            RedditThread.scraped_at < cutoff,
        )
        .distinct()
        .limit(max_threads)
        .all()
    )

    checked = 0
    newly_locked = 0
    still_open = 0

    for thread in threads:
        is_open = refresh_thread_locked_status(db, thread)
        checked += 1
        if is_open:
            still_open += 1
        else:
            newly_locked += 1

    # Auto-expire drafts for any newly locked threads
    if newly_locked > 0:
        expired = expire_drafts_for_locked_threads(db)
        logger.info("Bulk refresh: expired %d drafts after finding %d locked threads", expired, newly_locked)

    result = {
        "checked": checked,
        "newly_locked": newly_locked,
        "still_open": still_open,
    }
    logger.info("bulk_refresh_locked_status: %s", result)
    return result
