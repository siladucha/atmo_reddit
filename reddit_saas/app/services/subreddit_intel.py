"""Subreddit Intelligence Service — analytics and behavioral data per subreddit.

Provides data for the subreddit zoom-in detail page:
- Scrape history and freshness
- Thread activity and engagement metrics
- Avatar performance in this subreddit
- Top community contributors (leaders)
- Comment draft performance breakdown
"""

import uuid
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from sqlalchemy import func as sa_func, desc, and_, case
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.ai_usage import AIUsageLog
from app.models.comment_draft import CommentDraft
from app.models.scrape_log import ScrapeLog
from app.models.subreddit import Subreddit, ClientSubredditAssignment
from app.models.subreddit_karma import SubredditKarma
from app.models.thread import RedditThread
from app.models.client import Client


def get_subreddit_overview(db: Session, subreddit_name: str) -> dict:
    """Get high-level overview stats for a subreddit."""
    now = datetime.now(timezone.utc)

    subreddit = (
        db.query(Subreddit)
        .filter(sa_func.lower(Subreddit.subreddit_name) == subreddit_name.lower())
        .first()
    )
    if not subreddit:
        return {}

    # Total threads scraped
    total_threads = (
        db.query(sa_func.count(RedditThread.id))
        .filter(RedditThread.subreddit_id == subreddit.id)
        .scalar()
    ) or 0

    # Threads in last 7 days
    week_ago = now - timedelta(days=7)
    threads_7d = (
        db.query(sa_func.count(RedditThread.id))
        .filter(
            RedditThread.subreddit_id == subreddit.id,
            RedditThread.scraped_at >= week_ago,
        )
        .scalar()
    ) or 0

    # Total comments generated for threads in this subreddit
    total_comments = (
        db.query(sa_func.count(CommentDraft.id))
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .filter(RedditThread.subreddit_id == subreddit.id)
        .scalar()
    ) or 0

    # Comments by status
    status_counts = (
        db.query(CommentDraft.status, sa_func.count(CommentDraft.id))
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .filter(RedditThread.subreddit_id == subreddit.id)
        .group_by(CommentDraft.status)
        .all()
    )
    status_map = dict(status_counts)

    # Avg thread score
    avg_score = (
        db.query(sa_func.avg(RedditThread.score))
        .filter(RedditThread.subreddit_id == subreddit.id)
        .scalar()
    )

    # Client assignments
    assignments = (
        db.query(ClientSubredditAssignment)
        .join(Client, Client.id == ClientSubredditAssignment.client_id)
        .filter(ClientSubredditAssignment.subreddit_id == subreddit.id)
        .all()
    )

    return {
        "subreddit": subreddit,
        "total_threads": total_threads,
        "threads_7d": threads_7d,
        "total_comments": total_comments,
        "comments_pending": status_map.get("pending", 0),
        "comments_approved": status_map.get("approved", 0),
        "comments_posted": status_map.get("posted", 0),
        "comments_rejected": status_map.get("rejected", 0),
        "avg_thread_score": round(avg_score, 1) if avg_score else 0,
        "assignments": assignments,
    }


def get_scrape_history(db: Session, subreddit_name: str, limit: int = 20) -> list[dict]:
    """Get recent scrape logs for a subreddit."""
    logs = (
        db.query(ScrapeLog)
        .filter(sa_func.lower(ScrapeLog.subreddit_name) == subreddit_name.lower())
        .order_by(desc(ScrapeLog.scraped_at))
        .limit(limit)
        .all()
    )
    return [
        {
            "scraped_at": log.scraped_at,
            "posts_found": log.posts_found,
            "posts_new": log.posts_new,
            "duration_ms": log.duration_ms,
            "errors": log.errors,
        }
        for log in logs
    ]


def get_avatar_performance(db: Session, subreddit_name: str) -> list[dict]:
    """Get per-avatar performance metrics in this subreddit.

    Returns avatars sorted by total karma earned, with comment counts,
    avg karma per comment, and removal stats.
    """
    # Get karma data from SubredditKarma
    karma_rows = (
        db.query(SubredditKarma)
        .join(Avatar, Avatar.id == SubredditKarma.avatar_id)
        .filter(
            sa_func.lower(SubredditKarma.subreddit_name) == subreddit_name.lower(),
            Avatar.active.is_(True),
        )
        .all()
    )

    # Get subreddit record for thread lookup
    subreddit = (
        db.query(Subreddit)
        .filter(sa_func.lower(Subreddit.subreddit_name) == subreddit_name.lower())
        .first()
    )

    # Get comment stats per avatar in this subreddit
    comment_stats = {}
    if subreddit:
        stats = (
            db.query(
                CommentDraft.avatar_id,
                sa_func.count(CommentDraft.id).label("total_comments"),
                sa_func.count(
                    case((CommentDraft.status == "posted", CommentDraft.id))
                ).label("posted_count"),
                sa_func.count(
                    case((CommentDraft.is_deleted.is_(True), CommentDraft.id))
                ).label("removed_count"),
                sa_func.avg(CommentDraft.reddit_score).label("avg_score"),
            )
            .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
            .filter(RedditThread.subreddit_id == subreddit.id)
            .group_by(CommentDraft.avatar_id)
            .all()
        )
        for row in stats:
            comment_stats[row.avatar_id] = {
                "total_comments": row.total_comments,
                "posted_count": row.posted_count,
                "removed_count": row.removed_count,
                "avg_score": round(float(row.avg_score), 1) if row.avg_score else None,
            }

    results = []
    for karma in karma_rows:
        avatar = karma.avatar
        cs = comment_stats.get(karma.avatar_id, {})
        posted = cs.get("posted_count", 0)
        removed = cs.get("removed_count", 0)
        removal_rate = (removed / posted * 100) if posted > 0 else 0

        results.append({
            "avatar_id": karma.avatar_id,
            "reddit_username": avatar.reddit_username,
            "warming_phase": avatar.warming_phase,
            "is_frozen": avatar.is_frozen,
            "comment_karma": karma.comment_karma,
            "post_karma": karma.post_karma,
            "total_karma": karma.total_karma,
            "karma_delta": karma.total_delta,
            "comment_count": karma.comment_count,
            "total_drafts": cs.get("total_comments", 0),
            "posted_count": posted,
            "removed_count": removed,
            "removal_rate": round(removal_rate, 1),
            "avg_reddit_score": cs.get("avg_score"),
            "subreddit_type": karma.subreddit_type,
            "last_updated_at": karma.last_updated_at,
        })

    # Sort by total karma descending
    results.sort(key=lambda x: x["total_karma"], reverse=True)
    return results


def get_top_community_users(db: Session, subreddit_name: str, limit: int = 15) -> list[dict]:
    """Get top community contributors with spam/bot detection heuristics.

    Analyzes thread authors to identify:
    - Real influencers (high avg score, moderate post frequency)
    - Suspected spammers/bots (high frequency, low engagement)
    - Promo accounts (patterns in username or posting behavior)

    All detection is programmatic — no AI budget spent.
    """
    subreddit = (
        db.query(Subreddit)
        .filter(sa_func.lower(Subreddit.subreddit_name) == subreddit_name.lower())
        .first()
    )
    if not subreddit:
        return []

    # Get our avatar usernames to exclude them
    avatar_usernames = {
        row[0].lower()
        for row in db.query(Avatar.reddit_username).all()
    }

    # Aggregate thread authors with engagement metrics
    author_stats = (
        db.query(
            RedditThread.author,
            sa_func.count(RedditThread.id).label("post_count"),
            sa_func.avg(RedditThread.score).label("avg_score"),
            sa_func.max(RedditThread.score).label("max_score"),
            sa_func.sum(RedditThread.score).label("total_score"),
            sa_func.max(RedditThread.scraped_at).label("last_seen"),
            sa_func.min(RedditThread.scraped_at).label("first_seen"),
        )
        .filter(
            RedditThread.subreddit_id == subreddit.id,
            RedditThread.author.isnot(None),
            RedditThread.author != "[deleted]",
            RedditThread.author != "AutoModerator",
        )
        .group_by(RedditThread.author)
        .having(sa_func.count(RedditThread.id) >= 2)  # at least 2 posts to analyze
        .order_by(desc("total_score"))
        .limit(50)  # fetch more to filter
        .all()
    )

    results = []
    for row in author_stats:
        if row.author and row.author.lower() in avatar_usernames:
            continue
        if len(results) >= limit:
            break

        post_count = row.post_count
        avg_score = float(row.avg_score) if row.avg_score else 0
        max_score = row.max_score or 0
        total_score = row.total_score or 0

        # --- Spam/Bot Detection Heuristics (no AI) ---
        signals = []
        classification = "real"  # real | suspected_spam | suspected_bot | promo

        # 1. High frequency + low engagement = spam/bot
        if post_count >= 10 and avg_score < 2:
            signals.append("high_freq_low_engagement")
            classification = "suspected_spam"

        # 2. Very high frequency (>20 posts) with mediocre scores
        if post_count >= 20 and avg_score < 5:
            signals.append("volume_poster")
            classification = "suspected_bot"

        # 3. Username patterns common in bots/promo
        username_lower = (row.author or "").lower()
        bot_patterns = ["bot", "_bot", "auto", "news", "feed", "daily", "update", "official"]
        if any(p in username_lower for p in bot_patterns):
            signals.append("bot_username_pattern")
            if classification == "real":
                classification = "suspected_bot"

        # 4. Promo account patterns
        promo_patterns = ["pr_", "marketing", "brand", "team", "hq", "media"]
        if any(p in username_lower for p in promo_patterns):
            signals.append("promo_username_pattern")
            classification = "promo"

        # 5. All posts have score 1 (no engagement at all)
        if avg_score <= 1.0 and post_count >= 5:
            signals.append("zero_engagement")
            classification = "suspected_spam"

        # 6. High engagement = real influencer
        if avg_score >= 10 and post_count >= 3:
            signals.append("high_engagement")
            classification = "real"

        # 7. Has viral posts (max_score > 50) = real
        if max_score >= 50:
            signals.append("viral_posts")
            classification = "real"

        # Calculate days active
        days_active = 0
        if row.first_seen and row.last_seen:
            days_active = max(1, (row.last_seen - row.first_seen).days)

        # Posts per day (frequency indicator)
        posts_per_day = post_count / max(days_active, 1)

        results.append({
            "username": row.author,
            "post_count": post_count,
            "avg_score": round(avg_score, 1),
            "max_score": max_score,
            "total_score": total_score,
            "last_seen": row.last_seen,
            "first_seen": row.first_seen,
            "days_active": days_active,
            "posts_per_day": round(posts_per_day, 2),
            "classification": classification,
            "signals": signals,
        })

    # Sort: real users first (by total_score), then suspected (by post_count)
    results.sort(key=lambda x: (
        0 if x["classification"] == "real" else 1,
        -x["total_score"],
    ))

    return results


def get_recent_threads(
    db: Session, subreddit_name: str, limit: int = 20, days: int = 7
) -> list[dict]:
    """Get recent threads from this subreddit with engagement data."""
    subreddit = (
        db.query(Subreddit)
        .filter(sa_func.lower(Subreddit.subreddit_name) == subreddit_name.lower())
        .first()
    )
    if not subreddit:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    threads = (
        db.query(RedditThread)
        .filter(
            RedditThread.subreddit_id == subreddit.id,
            RedditThread.scraped_at >= cutoff,
        )
        .order_by(desc(RedditThread.scraped_at))
        .limit(limit)
        .all()
    )

    # Get comment counts per thread
    thread_ids = [t.id for t in threads]
    comment_counts = {}
    if thread_ids:
        counts = (
            db.query(
                CommentDraft.thread_id,
                sa_func.count(CommentDraft.id).label("count"),
            )
            .filter(CommentDraft.thread_id.in_(thread_ids))
            .group_by(CommentDraft.thread_id)
            .all()
        )
        comment_counts = {row.thread_id: row.count for row in counts}

    results = []
    for thread in threads:
        results.append({
            "id": thread.id,
            "post_title": thread.post_title,
            "author": thread.author,
            "score": thread.score,
            "url": thread.url,
            "tag": thread.tag,
            "alert": thread.alert,
            "scraped_at": thread.scraped_at,
            "comment_drafts_count": comment_counts.get(thread.id, 0),
        })

    return results


def get_engagement_timeline(db: Session, subreddit_name: str, days: int = 14) -> list[dict]:
    """Get daily engagement metrics for timeline visualization.

    Returns per-day: threads_scraped, comments_generated, comments_posted.
    """
    subreddit = (
        db.query(Subreddit)
        .filter(sa_func.lower(Subreddit.subreddit_name) == subreddit_name.lower())
        .first()
    )
    if not subreddit:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Threads per day
    threads_per_day = (
        db.query(
            sa_func.date_trunc("day", RedditThread.scraped_at).label("day"),
            sa_func.count(RedditThread.id).label("count"),
        )
        .filter(
            RedditThread.subreddit_id == subreddit.id,
            RedditThread.scraped_at >= cutoff,
        )
        .group_by("day")
        .all()
    )

    # Comments per day (generated)
    comments_per_day = (
        db.query(
            sa_func.date_trunc("day", CommentDraft.created_at).label("day"),
            sa_func.count(CommentDraft.id).label("count"),
        )
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .filter(
            RedditThread.subreddit_id == subreddit.id,
            CommentDraft.created_at >= cutoff,
        )
        .group_by("day")
        .all()
    )

    # Posted per day
    posted_per_day = (
        db.query(
            sa_func.date_trunc("day", CommentDraft.posted_at).label("day"),
            sa_func.count(CommentDraft.id).label("count"),
        )
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .filter(
            RedditThread.subreddit_id == subreddit.id,
            CommentDraft.posted_at.isnot(None),
            CommentDraft.posted_at >= cutoff,
        )
        .group_by("day")
        .all()
    )

    # Merge into timeline
    threads_map = {row.day.date(): row.count for row in threads_per_day}
    comments_map = {row.day.date(): row.count for row in comments_per_day}
    posted_map = {row.day.date(): row.count for row in posted_per_day}

    timeline = []
    for i in range(days):
        day = (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).date()
        timeline.append({
            "date": day,
            "threads": threads_map.get(day, 0),
            "comments_generated": comments_map.get(day, 0),
            "comments_posted": posted_map.get(day, 0),
        })

    return timeline


def get_ai_costs(db: Session, subreddit_name: str, limit: int = 20) -> dict:
    """Get AI usage and cost metrics for a subreddit."""
    base_filters = [sa_func.lower(AIUsageLog.subreddit_name) == subreddit_name.lower()]

    summary_row = (
        db.query(
            sa_func.count(AIUsageLog.id).label("calls"),
            sa_func.coalesce(sa_func.sum(AIUsageLog.cost_usd), 0).label("cost"),
            sa_func.coalesce(sa_func.sum(AIUsageLog.input_tokens), 0).label("input_tokens"),
            sa_func.coalesce(sa_func.sum(AIUsageLog.output_tokens), 0).label("output_tokens"),
            sa_func.coalesce(sa_func.avg(AIUsageLog.duration_ms), 0).label("avg_duration_ms"),
        )
        .filter(*base_filters)
        .one()
    )

    by_operation = (
        db.query(
            AIUsageLog.operation,
            sa_func.count(AIUsageLog.id).label("calls"),
            sa_func.coalesce(sa_func.sum(AIUsageLog.cost_usd), 0).label("cost"),
            sa_func.coalesce(sa_func.sum(AIUsageLog.input_tokens), 0).label("input_tokens"),
            sa_func.coalesce(sa_func.sum(AIUsageLog.output_tokens), 0).label("output_tokens"),
        )
        .filter(*base_filters)
        .group_by(AIUsageLog.operation)
        .order_by(desc("cost"))
        .all()
    )

    by_model = (
        db.query(
            AIUsageLog.model,
            sa_func.count(AIUsageLog.id).label("calls"),
            sa_func.coalesce(sa_func.sum(AIUsageLog.cost_usd), 0).label("cost"),
            sa_func.coalesce(sa_func.sum(AIUsageLog.input_tokens), 0).label("input_tokens"),
            sa_func.coalesce(sa_func.sum(AIUsageLog.output_tokens), 0).label("output_tokens"),
        )
        .filter(*base_filters)
        .group_by(AIUsageLog.model)
        .order_by(desc("cost"))
        .all()
    )

    recent_calls = (
        db.query(AIUsageLog)
        .filter(*base_filters)
        .order_by(desc(AIUsageLog.created_at))
        .limit(limit)
        .all()
    )

    return {
        "summary": {
            "calls": int(summary_row.calls or 0),
            "cost": float(summary_row.cost or 0),
            "input_tokens": int(summary_row.input_tokens or 0),
            "output_tokens": int(summary_row.output_tokens or 0),
            "avg_duration_ms": int(summary_row.avg_duration_ms or 0),
        },
        "by_operation": [
            {
                "operation": row.operation,
                "calls": int(row.calls or 0),
                "cost": float(row.cost or 0),
                "input_tokens": int(row.input_tokens or 0),
                "output_tokens": int(row.output_tokens or 0),
            }
            for row in by_operation
        ],
        "by_model": [
            {
                "model": row.model,
                "calls": int(row.calls or 0),
                "cost": float(row.cost or 0),
                "input_tokens": int(row.input_tokens or 0),
                "output_tokens": int(row.output_tokens or 0),
            }
            for row in by_model
        ],
        "recent_calls": recent_calls,
    }
