"""Karma history service — 30-day karma trend for an avatar.

Aggregates reddit_score from posted comments and posts by day and subreddit,
providing a timeline view of karma accumulation.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.models.comment_draft import CommentDraft
from app.models.avatar_profile_snapshot import AvatarProfileSnapshot
from app.models.post_draft import PostDraft
from app.models.thread import RedditThread


@dataclass
class DayKarma:
    """Karma earned on a single day."""
    date: str  # YYYY-MM-DD
    comment_karma: int
    post_karma: int
    comments_posted: int
    posts_posted: int
    reddit_comment_karma: int | None = None
    reddit_post_karma: int | None = None
    reddit_total_karma: int | None = None
    snapshot_at: datetime | None = None

    @property
    def total(self) -> int:
        return self.comment_karma + self.post_karma


@dataclass
class SubredditKarmaHistory:
    """Karma earned in a specific subreddit over the period."""
    subreddit: str
    total_karma: int
    comment_count: int
    avg_score: float
    best_score: int
    worst_score: int


@dataclass
class KarmaHistory:
    """Full 30-day karma history for an avatar."""
    avatar_id: str
    days: list[DayKarma]
    by_subreddit: list[SubredditKarmaHistory]
    total_karma: int
    total_comments: int
    total_posts: int
    avg_daily_karma: float
    trend: str  # "up", "down", "flat"
    reddit_total_karma: int  # current total from avatar model
    snapshot_count: int = 0
    latest_snapshot_at: datetime | None = None
    latest_snapshot_total_karma: int | None = None
    snapshot_delta_karma: int | None = None


def get_karma_history(
    db: Session,
    avatar_id: uuid.UUID,
    days: int = 30,
) -> KarmaHistory:
    """Build karma history for an avatar over the last N days."""
    from app.models.avatar import Avatar

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return KarmaHistory(
            avatar_id=str(avatar_id), days=[], by_subreddit=[],
            total_karma=0, total_comments=0, total_posts=0,
            avg_daily_karma=0.0, trend="flat", reddit_total_karma=0,
        )

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # --- Comment karma by day ---
    comment_rows = (
        db.query(
            func.date(CommentDraft.posted_at).label("day"),
            func.coalesce(func.sum(CommentDraft.reddit_score), 0).label("karma"),
            func.count(CommentDraft.id).label("count"),
        )
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
            CommentDraft.posted_at >= cutoff,
        )
        .group_by(func.date(CommentDraft.posted_at))
        .all()
    )
    comment_by_day = {str(row.day): {"karma": int(row.karma), "count": int(row.count)} for row in comment_rows}

    # --- Post karma by day ---
    post_rows = (
        db.query(
            func.date(PostDraft.posted_at).label("day"),
            func.coalesce(func.sum(PostDraft.reddit_score), 0).label("karma"),
            func.count(PostDraft.id).label("count"),
        )
        .filter(
            PostDraft.avatar_id == avatar_id,
            PostDraft.status == "posted",
            PostDraft.posted_at >= cutoff,
        )
        .group_by(func.date(PostDraft.posted_at))
        .all()
    )
    post_by_day = {str(row.day): {"karma": int(row.karma), "count": int(row.count)} for row in post_rows}

    # --- Reddit profile snapshots by day ---
    #
    # These are account-level karma snapshots fetched from Reddit. They are
    # separate from internal "posted" records, so they keep the Performance tab
    # useful even before the system has posted comments/posts for the avatar.
    snapshot_rows = (
        db.query(AvatarProfileSnapshot)
        .filter(
            AvatarProfileSnapshot.avatar_id == avatar_id,
            AvatarProfileSnapshot.fetched_at >= cutoff,
            AvatarProfileSnapshot.error.is_(None),
        )
        .order_by(AvatarProfileSnapshot.fetched_at.asc())
        .all()
    )
    snapshot_by_day: dict[str, AvatarProfileSnapshot] = {}
    for snapshot in snapshot_rows:
        if not snapshot.fetched_at:
            continue
        snapshot_by_day[str(snapshot.fetched_at.date())] = snapshot

    # --- Build daily timeline ---
    today = datetime.now(timezone.utc).date()
    day_list: list[DayKarma] = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        ds = str(d)
        c = comment_by_day.get(ds, {"karma": 0, "count": 0})
        p = post_by_day.get(ds, {"karma": 0, "count": 0})
        snapshot = snapshot_by_day.get(ds)
        day_list.append(DayKarma(
            date=ds,
            comment_karma=c["karma"],
            post_karma=p["karma"],
            comments_posted=c["count"],
            posts_posted=p["count"],
            reddit_comment_karma=snapshot.comment_karma if snapshot else None,
            reddit_post_karma=snapshot.post_karma if snapshot else None,
            reddit_total_karma=snapshot.total_karma if snapshot else None,
            snapshot_at=snapshot.fetched_at if snapshot else None,
        ))

    # --- By subreddit ---
    sub_rows = (
        db.query(
            RedditThread.subreddit.label("subreddit"),
            func.coalesce(func.sum(CommentDraft.reddit_score), 0).label("total_karma"),
            func.count(CommentDraft.id).label("comment_count"),
            func.coalesce(func.avg(CommentDraft.reddit_score), 0).label("avg_score"),
            func.coalesce(func.max(CommentDraft.reddit_score), 0).label("best"),
            func.coalesce(func.min(CommentDraft.reddit_score), 0).label("worst"),
        )
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
            CommentDraft.posted_at >= cutoff,
            CommentDraft.reddit_score.isnot(None),
        )
        .group_by(RedditThread.subreddit)
        .order_by(func.sum(CommentDraft.reddit_score).desc())
        .all()
    )

    by_subreddit = [
        SubredditKarmaHistory(
            subreddit=row.subreddit or "unknown",
            total_karma=int(row.total_karma),
            comment_count=int(row.comment_count),
            avg_score=round(float(row.avg_score), 1),
            best_score=int(row.best),
            worst_score=int(row.worst),
        )
        for row in sub_rows
    ]

    # --- Totals ---
    total_karma = sum(d.total for d in day_list)
    total_comments = sum(d.comments_posted for d in day_list)
    total_posts = sum(d.posts_posted for d in day_list)
    avg_daily = total_karma / days if days > 0 else 0.0

    # --- Trend (compare first half vs second half) ---
    mid = days // 2
    first_half = sum(d.total for d in day_list[:mid])
    second_half = sum(d.total for d in day_list[mid:])
    if second_half > first_half + 2:
        trend = "up"
    elif first_half > second_half + 2:
        trend = "down"
    else:
        trend = "flat"

    reddit_total = (avatar.reddit_karma_comment or 0) + (avatar.reddit_karma_post or 0)
    latest_snapshot = snapshot_rows[-1] if snapshot_rows else None
    first_snapshot = snapshot_rows[0] if snapshot_rows else None
    snapshot_delta = None
    if latest_snapshot and first_snapshot and len(snapshot_rows) > 1:
        snapshot_delta = int(latest_snapshot.total_karma or 0) - int(first_snapshot.total_karma or 0)

    return KarmaHistory(
        avatar_id=str(avatar_id),
        days=day_list,
        by_subreddit=by_subreddit,
        total_karma=total_karma,
        total_comments=total_comments,
        total_posts=total_posts,
        avg_daily_karma=round(avg_daily, 1),
        trend=trend,
        reddit_total_karma=reddit_total,
        snapshot_count=len(snapshot_rows),
        latest_snapshot_at=latest_snapshot.fetched_at if latest_snapshot else None,
        latest_snapshot_total_karma=latest_snapshot.total_karma if latest_snapshot else None,
        snapshot_delta_karma=snapshot_delta,
    )
