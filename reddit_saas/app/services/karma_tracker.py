"""Subreddit-specific karma tracking service.

Maintains per-avatar, per-subreddit karma snapshots. Karma is sourced from:

1. Internal comment performance — when a CommentDraft transitions to "posted"
   and a `reddit_score` is observed, the corresponding subreddit row is
   updated with the score delta.
2. Reddit API status check — when an avatar's recent comment history is
   fetched, the per-subreddit karma totals derived from those comments are
   reconciled with the snapshot table.

Reddit's public API does NOT expose a per-subreddit karma breakdown for an
arbitrary user, so the "karma sync" path falls back to summing scores from
the avatar's own posted comments (Req 3.2).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable

from prawcore.exceptions import Forbidden, NotFound, RequestException, ResponseException
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.activity_event import ActivityEvent
from app.models.avatar import Avatar
from app.models.comment_draft import CommentDraft
from app.models.subreddit_karma import SubredditKarma
from app.models.thread import RedditThread
from app.services.sanitize import clean_subreddit_list, ensure_username_bare

logger = logging.getLogger(__name__)


def _classify_subreddit(avatar: Avatar, subreddit_name: str) -> str:
    """Return "professional" | "hobby" | "unknown" for the given subreddit.

    Uses the avatar's hobby_subreddits / business_subreddits configuration as
    the source of truth. Both fields are JSONB and may contain plain strings
    or dicts (legacy Ori format); clean_subreddit_list normalizes both shapes.
    """
    sub_lower = (subreddit_name or "").lower()

    business = {s.lower() for s in clean_subreddit_list(avatar.business_subreddits)}
    if sub_lower in business:
        return "professional"

    hobby = {s.lower() for s in clean_subreddit_list(avatar.hobby_subreddits)}
    if sub_lower in hobby:
        return "hobby"

    return "unknown"


def _get_or_create_record(
    db: Session,
    avatar: Avatar,
    subreddit_name: str,
) -> tuple[SubredditKarma, bool]:
    """Return (record, created) — initializes a fresh snapshot when missing."""
    record = (
        db.query(SubredditKarma)
        .filter(
            SubredditKarma.avatar_id == avatar.id,
            sa_func.lower(SubredditKarma.subreddit_name) == subreddit_name.lower(),
        )
        .first()
    )
    if record is not None:
        return record, False

    record = SubredditKarma(
        avatar_id=avatar.id,
        subreddit_name=subreddit_name,
        comment_karma=0,
        post_karma=0,
        comment_count=0,
        previous_comment_karma=0,
        previous_post_karma=0,
        subreddit_type=_classify_subreddit(avatar, subreddit_name),
        last_updated_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.flush()
    return record, True


def _snapshot_previous(record: SubredditKarma) -> None:
    """Capture the current karma values as the previous snapshot (Req 11.1)."""
    record.previous_comment_karma = record.comment_karma or 0
    record.previous_post_karma = record.post_karma or 0


def record_comment_score(
    db: Session,
    avatar: Avatar,
    subreddit_name: str,
    new_score: int,
    *,
    previous_score: int | None = None,
    increment_count: bool = True,
) -> SubredditKarma:
    """Apply a comment-score event to the avatar's per-subreddit karma row.

    Args:
        avatar: The avatar that posted the comment.
        subreddit_name: The subreddit the comment was posted in.
        new_score: The current `reddit_score` value for the comment.
        previous_score: The previously recorded score, if known. When provided,
            the delta (new - previous) is applied; when None, `new_score` is
            applied as the delta (i.e. the score is being seen for the first
            time).
        increment_count: When True, increments comment_count by 1. Set False
            when reconciling an existing comment whose score changed.

    Returns:
        The mutated SubredditKarma record (already persisted in the session).
    """
    if not subreddit_name:
        raise ValueError("subreddit_name is required")

    record, _created = _get_or_create_record(db, avatar, subreddit_name)
    _snapshot_previous(record)

    if previous_score is None:
        delta = int(new_score or 0)
    else:
        delta = int(new_score or 0) - int(previous_score or 0)

    record.comment_karma = (record.comment_karma or 0) + delta
    if increment_count:
        record.comment_count = (record.comment_count or 0) + 1
    record.last_updated_at = datetime.now(timezone.utc)

    db.flush()
    return record


def sync_avatar_from_comment_history(
    db: Session,
    avatar: Avatar,
    *,
    log_event: bool = True,
) -> dict:
    """Recompute per-subreddit karma from this avatar's posted CommentDrafts.

    This is the "Reddit status check" path (Req 3). Reddit does not provide a
    per-subreddit breakdown for arbitrary users, so we derive the breakdown
    from the avatar's own posted comments. For each subreddit the avatar has
    posted in, we sum `reddit_score` across posted (non-deleted) comments and
    overwrite the snapshot with the result.

    Returns a summary dict: {"updated": N, "subreddits": [...]}.
    """
    rows = (
        db.query(
            RedditThread.subreddit.label("subreddit"),
            sa_func.count(CommentDraft.id).label("comment_count"),
            sa_func.coalesce(sa_func.sum(CommentDraft.reddit_score), 0).label("score_sum"),
        )
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.status == "posted",
            CommentDraft.is_deleted.is_(False),
        )
        .group_by(RedditThread.subreddit)
        .all()
    )

    now = datetime.now(timezone.utc)
    updated_subs: list[str] = []
    for row in rows:
        subreddit = row.subreddit
        if not subreddit:
            continue
        record, _created = _get_or_create_record(db, avatar, subreddit)
        _snapshot_previous(record)
        record.comment_karma = int(row.score_sum or 0)
        record.comment_count = int(row.comment_count or 0)
        # Refresh classification — avatar's hobby/business lists may change.
        record.subreddit_type = _classify_subreddit(avatar, subreddit)
        record.last_updated_at = now
        updated_subs.append(subreddit)

    if log_event and updated_subs:
        client_id = avatar.client_ids[0] if avatar.client_ids else None
        db.add(
            ActivityEvent(
                client_id=client_id,
                event_type="karma_sync",
                message=(
                    f"Synced subreddit karma for u/{avatar.reddit_username} "
                    f"({len(updated_subs)} subreddit(s))"
                ),
                event_metadata={
                    "avatar_id": str(avatar.id),
                    "subreddits": updated_subs,
                    "source": "comment_history",
                },
            )
        )

    db.flush()
    return {"updated": len(updated_subs), "subreddits": updated_subs}


def sync_avatar_from_reddit(
    db: Session,
    avatar: Avatar,
    *,
    fetch_recent_comments=None,
    log_event: bool = True,
) -> dict:
    """Best-effort fetch of per-subreddit karma from Reddit's public API.

    Reddit does not expose a per-subreddit karma breakdown for a user via
    PRAW, so this attempts to derive one from the user's recent comment
    history (`u/<name>/comments`). Each comment carries a score and a
    subreddit name; summing scores per subreddit gives a Reddit-sourced
    snapshot that we can reconcile with our internal numbers.

    On any API error we fall back to the internal-history sync (Req 3.2).

    Args:
        fetch_recent_comments: Optional injected callable that returns an
            iterable of objects exposing `subreddit.display_name` and `score`.
            Used by tests to avoid hitting the live API. When None, PRAW is
            used directly.
    """
    items: list[tuple[str, int]] = []
    error: str | None = None

    if fetch_recent_comments is None:
        try:
            from app.services.reddit import get_reddit_client

            start = time.time()
            reddit = get_reddit_client()
            redditor = reddit.redditor(ensure_username_bare(avatar.reddit_username))
            comments_iter = redditor.comments.new(limit=100)
            for c in comments_iter:
                sub = getattr(getattr(c, "subreddit", None), "display_name", None)
                if not sub:
                    continue
                items.append((sub, int(getattr(c, "score", 0) or 0)))
            logger.info(
                "REDDIT_API_RESULT | action=fetch_user_comments | username=u/%s | "
                "count=%d | duration_ms=%d",
                avatar.reddit_username,
                len(items),
                int((time.time() - start) * 1000),
            )
        except (NotFound, Forbidden) as exc:
            error = f"reddit_api_unavailable: {type(exc).__name__}"
        except (RequestException, ResponseException) as exc:
            error = f"reddit_api_error: {exc}"
        except Exception as exc:  # pragma: no cover — defensive
            error = f"unexpected_error: {exc}"
    else:
        try:
            for c in fetch_recent_comments(avatar):
                sub = getattr(getattr(c, "subreddit", None), "display_name", None)
                if not sub:
                    continue
                items.append((sub, int(getattr(c, "score", 0) or 0)))
        except Exception as exc:  # pragma: no cover — defensive
            error = f"unexpected_error: {exc}"

    if error:
        logger.info(
            "KARMA_SYNC | username=u/%s | source=reddit | result=fallback_internal | error=%s",
            avatar.reddit_username,
            error,
        )
        # Fallback per Req 3.2 — use internal comment performance only.
        return sync_avatar_from_comment_history(db, avatar, log_event=log_event)

    aggregated: dict[str, dict[str, int]] = defaultdict(lambda: {"karma": 0, "count": 0})
    for sub, score in items:
        aggregated[sub]["karma"] += score
        aggregated[sub]["count"] += 1

    # Merge in internal counts so subreddits we have posted in but Reddit did
    # not return (older than the 100-comment window) still show up.
    internal_rows = (
        db.query(
            RedditThread.subreddit.label("subreddit"),
            sa_func.count(CommentDraft.id).label("comment_count"),
        )
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.status == "posted",
        )
        .group_by(RedditThread.subreddit)
        .all()
    )
    for row in internal_rows:
        if row.subreddit and row.subreddit not in aggregated:
            aggregated[row.subreddit] = {"karma": 0, "count": int(row.comment_count or 0)}

    now = datetime.now(timezone.utc)
    updated_subs: list[str] = []
    for subreddit, totals in aggregated.items():
        record, _created = _get_or_create_record(db, avatar, subreddit)
        _snapshot_previous(record)
        record.comment_karma = int(totals["karma"])
        record.comment_count = max(int(totals["count"]), record.comment_count or 0)
        record.subreddit_type = _classify_subreddit(avatar, subreddit)
        record.last_updated_at = now
        updated_subs.append(subreddit)

    if log_event and updated_subs:
        client_id = avatar.client_ids[0] if avatar.client_ids else None
        db.add(
            ActivityEvent(
                client_id=client_id,
                event_type="karma_sync",
                message=(
                    f"Synced subreddit karma for u/{avatar.reddit_username} "
                    f"({len(updated_subs)} subreddit(s))"
                ),
                event_metadata={
                    "avatar_id": str(avatar.id),
                    "subreddits": updated_subs,
                    "source": "reddit_api",
                },
            )
        )

    db.flush()
    return {"updated": len(updated_subs), "subreddits": updated_subs}


# ---------------------------------------------------------------------------
# Read helpers — used by routes/templates.
# ---------------------------------------------------------------------------


def get_breakdown(db: Session, avatar: Avatar) -> list[SubredditKarma]:
    """Return all karma rows for an avatar, ordered by total karma desc."""
    rows = (
        db.query(SubredditKarma)
        .filter(SubredditKarma.avatar_id == avatar.id)
        .all()
    )
    return sorted(
        rows,
        key=lambda r: (
            -((r.comment_karma or 0) + (r.post_karma or 0)),
            (r.subreddit_name or "").lower(),
        ),
    )


def get_karma_in_subreddit(
    db: Session, avatar_id, subreddit_name: str
) -> SubredditKarma | None:
    """Return the karma row for a single avatar/subreddit pair, or None."""
    return (
        db.query(SubredditKarma)
        .filter(
            SubredditKarma.avatar_id == avatar_id,
            sa_func.lower(SubredditKarma.subreddit_name) == (subreddit_name or "").lower(),
        )
        .first()
    )


def diversity_count(db: Session, avatar_id) -> int:
    """Count of subreddits where the avatar has positive total karma."""
    return (
        db.query(sa_func.count(SubredditKarma.id))
        .filter(
            SubredditKarma.avatar_id == avatar_id,
            (SubredditKarma.comment_karma + SubredditKarma.post_karma) > 0,
        )
        .scalar()
    ) or 0


def professional_diversity_count(db: Session, avatar_id) -> int:
    """Count of *professional* subreddits where the avatar has positive karma."""
    return (
        db.query(sa_func.count(SubredditKarma.id))
        .filter(
            SubredditKarma.avatar_id == avatar_id,
            SubredditKarma.subreddit_type == "professional",
            (SubredditKarma.comment_karma + SubredditKarma.post_karma) > 0,
        )
        .scalar()
    ) or 0


def top_subreddits(
    db: Session, avatar_id, limit: int = 3
) -> list[SubredditKarma]:
    """Return the top-N subreddits for an avatar by total karma."""
    rows = get_breakdown(db, type("_A", (), {"id": avatar_id})())  # noqa
    return rows[:limit]


def top_subreddits_for_avatars(
    db: Session, avatar_ids: Iterable, limit: int = 3
) -> dict:
    """Batch fetch the top-N subreddits for many avatars.

    Returns: {avatar_id_str: [SubredditKarma, ...]}.
    """
    avatar_id_list = [a for a in avatar_ids if a is not None]
    if not avatar_id_list:
        return {}

    rows = (
        db.query(SubredditKarma)
        .filter(SubredditKarma.avatar_id.in_(avatar_id_list))
        .all()
    )
    grouped: dict = defaultdict(list)
    for r in rows:
        grouped[str(r.avatar_id)].append(r)
    for key, lst in grouped.items():
        lst.sort(
            key=lambda r: (
                -((r.comment_karma or 0) + (r.post_karma or 0)),
                (r.subreddit_name or "").lower(),
            )
        )
        grouped[key] = lst[:limit]
    return dict(grouped)
