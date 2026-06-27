"""Celery task: snapshot_comment_outcomes — time-series karma tracking.

Checks karma, reply_count, and deletion status for recently posted comments.
Creates KarmaSnapshot records at 4h, 24h, 48h windows after posting.

This is the foundation of the Feedback Layer:
- KarmaSnapshots enable engagement velocity measurement
- Reply counts prove "thread depth provoked" (Tier-2 signal)
- Deletion detection feeds into subreddit intelligence
- Karma curves feed EPG model correction and Discovery hypothesis validation

Schedule: Every 4 hours via Celery Beat.
"""

from datetime import datetime, timedelta, timezone

from celery import shared_task

from app.database import SessionLocal
from app.logging_config import get_logger

logger = get_logger(__name__)

# Check windows: how many hours after posting each snapshot should be taken
CHECK_WINDOWS = [
    ("4h", 3.5, 5.0),    # 4h window: eligible 3.5-5h after posting
    ("24h", 23.0, 26.0),  # 24h window: eligible 23-26h after posting
    ("48h", 47.0, 50.0),  # 48h window: eligible 47-50h after posting
    ("7d", 166.0, 170.0), # 7d window: eligible 166-170h after posting
]

# Max comments to process per task run (avoid long-running tasks)
MAX_COMMENTS_PER_RUN = 100

# Delay between Reddit API calls (seconds) — respect rate limits
API_CALL_DELAY_SECONDS = 2


@shared_task(name="snapshot_comment_outcomes")
def snapshot_comment_outcomes():
    """Periodic task: check karma outcomes for posted comments.

    Finds posted CommentDrafts eligible for each check window,
    fetches current karma/reply data from Reddit, and creates
    KarmaSnapshot records.

    Returns dict with processing stats.
    """
    from app.models.comment_draft import CommentDraft
    from app.models.karma_snapshot import KarmaSnapshot

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        stats = {
            "checked": 0,
            "snapshots_created": 0,
            "errors": 0,
            "skipped_already_checked": 0,
            "skipped_no_url": 0,
            "deletions_detected": 0,
        }

        for window_name, min_hours, max_hours in CHECK_WINDOWS:
            eligible = _find_eligible_comments(db, now, window_name, min_hours, max_hours)

            if not eligible:
                continue

            logger.info(
                "snapshot_comment_outcomes: window=%s eligible=%d",
                window_name, len(eligible),
            )

            for draft in eligible[:MAX_COMMENTS_PER_RUN - stats["checked"]]:
                if stats["checked"] >= MAX_COMMENTS_PER_RUN:
                    break

                try:
                    _check_and_snapshot(db, draft, window_name, now, stats)
                except Exception as e:
                    stats["errors"] += 1
                    logger.error(
                        "snapshot_comment_outcomes: error checking draft %s: %s",
                        draft.id, str(e)[:200],
                    )
                    db.rollback()

        logger.info(
            "snapshot_comment_outcomes complete: checked=%d snapshots=%d errors=%d deletions=%d",
            stats["checked"], stats["snapshots_created"], stats["errors"], stats["deletions_detected"],
        )
        return stats

    except Exception as e:
        logger.error("snapshot_comment_outcomes failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


def _find_eligible_comments(db, now: datetime, window_name: str, min_hours: float, max_hours: float):
    """Find posted comments eligible for a specific check window.

    A comment is eligible if:
    - status = 'posted'
    - posted_at is between min_hours and max_hours ago
    - No KarmaSnapshot exists for this comment at this window
    """
    from sqlalchemy import and_, not_, exists
    from app.models.comment_draft import CommentDraft
    from app.models.karma_snapshot import KarmaSnapshot

    window_start = now - timedelta(hours=max_hours)
    window_end = now - timedelta(hours=min_hours)

    # Subquery: already has snapshot for this window
    already_checked = (
        db.query(KarmaSnapshot.comment_draft_id)
        .filter(KarmaSnapshot.check_window == window_name)
        .subquery()
    )

    eligible = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.status == "posted",
            CommentDraft.posted_at.isnot(None),
            CommentDraft.posted_at >= window_start,
            CommentDraft.posted_at <= window_end,
            CommentDraft.reddit_comment_url.isnot(None),
            ~CommentDraft.id.in_(
                db.query(already_checked.c.comment_draft_id)
            ),
        )
        .order_by(CommentDraft.posted_at.asc())
        .limit(MAX_COMMENTS_PER_RUN)
        .all()
    )

    return eligible


def _check_and_snapshot(db, draft, window_name: str, now: datetime, stats: dict):
    """Fetch current karma/replies for a comment and create snapshot.

    Uses PRAW to fetch the comment by its Reddit ID, reads score + reply count.
    Creates KarmaSnapshot record. Updates CommentDraft.last_karma_check_at.
    Detects deletion (comment removed/deleted on Reddit).
    """
    import time
    from app.models.karma_snapshot import KarmaSnapshot
    from app.services.reddit import get_reddit_client

    stats["checked"] += 1

    reddit_comment_url = draft.reddit_comment_url
    if not reddit_comment_url:
        stats["skipped_no_url"] += 1
        return

    # Extract comment ID from URL (format: .../comments/.../.../<comment_id>/)
    reddit_comment_id = _extract_comment_id(reddit_comment_url)
    if not reddit_comment_id:
        # Try from the field directly
        reddit_comment_id = getattr(draft, "reddit_comment_id", None)
        if not reddit_comment_id:
            stats["skipped_no_url"] += 1
            return

    # Fetch from Reddit API
    try:
        reddit = get_reddit_client(caller="snapshot_outcomes")
        comment = reddit.comment(id=reddit_comment_id)
        # Force fetch (lazy loading)
        comment._fetch()

        karma_value = comment.score
        reply_count = len(comment.replies) if hasattr(comment, "replies") else 0
        is_deleted = (
            comment.body in ("[removed]", "[deleted]")
            or comment.author is None
        )

    except Exception as e:
        error_str = str(e).lower()
        # If 404 or not found — comment was deleted/removed
        if "404" in error_str or "not found" in error_str:
            karma_value = draft.reddit_score or 0
            reply_count = 0
            is_deleted = True
        else:
            raise  # Re-raise transient errors for retry

    # Find previous snapshot for delta calculation
    previous = (
        db.query(KarmaSnapshot)
        .filter(KarmaSnapshot.comment_draft_id == draft.id)
        .order_by(KarmaSnapshot.checked_at.desc())
        .first()
    )

    karma_delta = None
    if previous is not None:
        karma_delta = karma_value - previous.karma_value

    # Determine subreddit from thread relationship
    subreddit = None
    if draft.thread and draft.thread.subreddit:
        subreddit = draft.thread.subreddit
    elif hasattr(draft, "thread") and draft.thread:
        subreddit = getattr(draft.thread, "subreddit_name", None) or getattr(draft.thread, "subreddit", None)

    # Create snapshot
    snapshot = KarmaSnapshot(
        comment_draft_id=draft.id,
        avatar_id=draft.avatar_id,
        karma_value=karma_value,
        reply_count=reply_count,
        is_deleted=is_deleted,
        check_window=window_name,
        checked_at=now,
        karma_delta=karma_delta,
        subreddit=subreddit,
    )
    db.add(snapshot)

    # Update draft's single-point score and last check time
    draft.reddit_score = karma_value
    draft.last_karma_check_at = now

    # Detect new deletion
    if is_deleted and not draft.is_deleted:
        draft.is_deleted = True
        draft.deleted_detected_at = now
        stats["deletions_detected"] += 1

        # Emit activity event for deletion
        _emit_deletion_event(db, draft, window_name)

        # Check if this triggers a per-subreddit ban detection
        if subreddit and draft.avatar_id:
            try:
                from app.services.subreddit_ban import check_for_subreddit_ban
                ban_created = check_for_subreddit_ban(
                    db, draft.avatar_id, subreddit, draft.id
                )
                if ban_created:
                    stats.setdefault("bans_detected", 0)
                    stats["bans_detected"] += 1
            except Exception as e:
                logger.warning(
                    "subreddit_ban check failed for draft %s: %s",
                    draft.id, str(e)[:100],
                )

    db.commit()
    stats["snapshots_created"] += 1

    # Rate limit: pause between API calls
    time.sleep(API_CALL_DELAY_SECONDS)


def _extract_comment_id(url: str) -> str | None:
    """Extract Reddit comment ID from a comment URL.

    URL format: https://www.reddit.com/r/{sub}/comments/{post_id}/{slug}/{comment_id}/
    Also handles: https://reddit.com/r/...
    """
    if not url:
        return None

    parts = url.rstrip("/").split("/")
    # Comment ID is typically the last path segment
    if len(parts) >= 2:
        # Check if it looks like a Reddit comment ID (alphanumeric, 5-10 chars)
        candidate = parts[-1]
        if candidate and len(candidate) <= 10 and candidate.isalnum():
            return candidate

    return None


def _emit_deletion_event(db, draft, window_name: str):
    """Emit an ActivityEvent when a comment deletion is detected."""
    from app.models.activity_event import ActivityEvent

    subreddit = ""
    if draft.thread:
        subreddit = getattr(draft.thread, "subreddit", "") or ""

    event = ActivityEvent(
        event_type="comment_deletion_detected",
        client_id=draft.client_id,
        message=(
            f"Comment by avatar in r/{subreddit} detected as deleted/removed "
            f"(window: {window_name})"
        ),
        event_metadata={
            "draft_id": str(draft.id),
            "avatar_id": str(draft.avatar_id),
            "subreddit": subreddit,
            "check_window": window_name,
            "reddit_comment_url": draft.reddit_comment_url,
        },
    )
    db.add(event)
