"""Subreddit presence service.

Pure aggregation logic and data access for the Avatar Subreddit Presence Map.
Handles grouping Reddit comments by subreddit, computing per-subreddit metrics,
staleness detection for presence data freshness, and scanning avatar presence
via PRAW.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.avatar_subreddit_presence import AvatarSubredditPresence

logger = logging.getLogger(__name__)

# Threshold for considering presence data stale (7 days)
PRESENCE_STALE_DAYS = 7


def aggregate_comments_by_subreddit(comments: list[dict]) -> list[dict]:
    """Group raw Reddit comments by subreddit and compute per-subreddit metrics.

    Pure function — no side effects, no DB access.

    Args:
        comments: List of comment dicts, each containing:
            - subreddit (str): Name of the subreddit (no r/ prefix)
            - score (int): Karma score of the comment
            - created_utc (float): Unix timestamp of comment creation

    Returns:
        List of dicts, one per unique subreddit, each containing:
            - subreddit_name (str): Subreddit name
            - comment_count (int): Number of comments in that subreddit
            - total_karma (int): Sum of karma scores
            - last_activity_at (datetime): Timezone-aware UTC datetime of the
              most recent comment in that subreddit
    """
    if not comments:
        return []

    subreddit_map: dict[str, dict] = {}

    for comment in comments:
        sub = comment["subreddit"]
        score = comment["score"]
        created_utc = comment["created_utc"]

        if sub not in subreddit_map:
            subreddit_map[sub] = {
                "subreddit_name": sub,
                "comment_count": 0,
                "total_karma": 0,
                "last_activity_at": datetime.fromtimestamp(created_utc, tz=timezone.utc),
            }

        entry = subreddit_map[sub]
        entry["comment_count"] += 1
        entry["total_karma"] += score

        comment_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
        if comment_dt > entry["last_activity_at"]:
            entry["last_activity_at"] = comment_dt

    return list(subreddit_map.values())


def is_presence_stale(last_scanned_at: datetime | None) -> bool:
    """Determine if presence data is stale and should be refreshed.

    Pure function — compares the given timestamp against the current time.

    Args:
        last_scanned_at: When presence was last scanned, or None if never scanned.
            Must be timezone-aware (UTC) if provided.

    Returns:
        True if presence data is stale (None or older than 7 days), False otherwise.
    """
    if last_scanned_at is None:
        return True

    threshold = datetime.now(timezone.utc) - timedelta(days=PRESENCE_STALE_DAYS)
    return last_scanned_at < threshold


# Valid sort keys for get_avatar_presence
VALID_SORT_KEYS = ("comment_count", "avg_karma", "last_activity_at")


def get_avatar_presence(
    db: Session,
    avatar_id: uuid.UUID,
    sort_by: str = "comment_count",
) -> list[AvatarSubredditPresence]:
    """Query presence records for an avatar, sorted by the specified field.

    Args:
        db: SQLAlchemy session.
        avatar_id: UUID of the avatar to query presence for.
        sort_by: Sort key — one of "comment_count" (default), "avg_karma",
            or "last_activity_at". Records are returned in descending order.

    Returns:
        List of AvatarSubredditPresence records sorted descending by the
        chosen key. For "avg_karma", the value is computed as
        total_karma / comment_count (0.0 when comment_count is 0).
    """
    if sort_by not in VALID_SORT_KEYS:
        sort_by = "comment_count"

    records = (
        db.query(AvatarSubredditPresence)
        .filter(AvatarSubredditPresence.avatar_id == avatar_id)
        .all()
    )

    if sort_by == "avg_karma":
        records.sort(
            key=lambda r: (
                r.total_karma / r.comment_count if r.comment_count > 0 else 0.0
            ),
            reverse=True,
        )
    elif sort_by == "last_activity_at":
        # None values sort last (treated as oldest)
        records.sort(
            key=lambda r: r.last_activity_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
    else:
        # Default: comment_count descending
        records.sort(key=lambda r: r.comment_count, reverse=True)

    return records


def scan_avatar_presence(db: Session, avatar_id: uuid.UUID) -> list[AvatarSubredditPresence]:
    """Fetch avatar's recent comments from Reddit, aggregate by subreddit, upsert presence records.

    Connects to Reddit via PRAW, fetches the avatar's last 100 comments,
    aggregates them by subreddit using `aggregate_comments_by_subreddit`,
    and upserts the results into the `avatar_subreddit_presence` table.

    On success, updates the avatar's `presence_last_scanned_at` to now and
    `presence_scan_status` to "completed".

    On error (PRAW exception), sets `presence_scan_status` to "failed" and
    preserves any existing presence data. The exception is re-raised.

    Args:
        db: SQLAlchemy session.
        avatar_id: UUID of the avatar to scan.

    Returns:
        List of upserted AvatarSubredditPresence records.

    Raises:
        Exception: Re-raises any PRAW or unexpected exception after marking
            the avatar's scan status as "failed".
    """
    from app.services.reddit import get_reddit_client

    # Load the avatar
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if avatar is None:
        raise ValueError(f"Avatar not found: {avatar_id}")

    try:
        # Fetch recent comments via PRAW
        reddit = get_reddit_client()
        redditor = reddit.redditor(avatar.reddit_username)

        logger.info(
            "PRESENCE_SCAN | action=fetch_comments | avatar_id=%s | username=%s",
            avatar_id, avatar.reddit_username,
        )

        raw_comments = []
        for comment in redditor.comments.new(limit=100):
            raw_comments.append({
                "subreddit": comment.subreddit.display_name,
                "score": comment.score,
                "created_utc": comment.created_utc,
            })

        logger.info(
            "PRESENCE_SCAN | action=comments_fetched | avatar_id=%s | count=%d",
            avatar_id, len(raw_comments),
        )

        # Aggregate by subreddit
        aggregated = aggregate_comments_by_subreddit(raw_comments)

        # Upsert presence records
        upserted_records: list[AvatarSubredditPresence] = []

        for entry in aggregated:
            # Check if a record already exists for this avatar + subreddit
            existing = (
                db.query(AvatarSubredditPresence)
                .filter(
                    AvatarSubredditPresence.avatar_id == avatar_id,
                    AvatarSubredditPresence.subreddit_name == entry["subreddit_name"],
                )
                .first()
            )

            if existing:
                # Update existing record
                existing.comment_count = entry["comment_count"]
                existing.total_karma = entry["total_karma"]
                existing.last_activity_at = entry["last_activity_at"]
                upserted_records.append(existing)
            else:
                # Insert new record
                new_record = AvatarSubredditPresence(
                    avatar_id=avatar_id,
                    subreddit_name=entry["subreddit_name"],
                    comment_count=entry["comment_count"],
                    total_karma=entry["total_karma"],
                    last_activity_at=entry["last_activity_at"],
                )
                db.add(new_record)
                upserted_records.append(new_record)

        # Update avatar scan metadata
        avatar.presence_last_scanned_at = datetime.now(timezone.utc)
        avatar.presence_scan_status = "completed"

        db.commit()

        logger.info(
            "PRESENCE_SCAN | action=completed | avatar_id=%s | subreddits=%d",
            avatar_id, len(upserted_records),
        )

        return upserted_records

    except Exception as e:
        # Roll back any partial changes from this attempt
        db.rollback()

        # Set status to "failed" — preserve existing presence data
        avatar_for_status = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if avatar_for_status:
            avatar_for_status.presence_scan_status = "failed"
            db.commit()

        logger.error(
            "PRESENCE_SCAN | action=failed | avatar_id=%s | error=%s | details=%s",
            avatar_id, type(e).__name__, str(e),
        )

        raise
