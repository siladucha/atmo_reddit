"""Karma feedback service — tracks posted comment performance on Reddit.

Checks reddit_score for posted comments, detects significant karma drops,
and triggers avatar phase demotion when karma consistently drops below
threshold.

Demotion trigger: if average reddit_score across recent posted comments
drops below KARMA_DROP_THRESHOLD (negative karma), the avatar is demoted
by one phase.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.comment_draft import CommentDraft
from app.models.thread import RedditThread
from app.services.transparency import record_activity_event

logger = logging.getLogger(__name__)

# If average score of recent posted comments drops below this, trigger demotion
KARMA_DROP_THRESHOLD = -2
# Minimum number of scored comments needed to evaluate karma drop
MIN_SCORED_COMMENTS = 3
# Window in days to look back for karma evaluation
KARMA_EVAL_WINDOW_DAYS = 14


def update_comment_score(
    db: Session,
    comment_id: UUID,
    new_score: int,
) -> CommentDraft | None:
    """Update reddit_score on a posted comment and reconcile karma tracking.

    Args:
        db: Database session.
        comment_id: The comment draft ID.
        new_score: The observed Reddit score (upvotes - downvotes).

    Returns:
        The updated CommentDraft, or None if not found / not posted.
    """
    comment = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if not comment:
        return None
    if comment.status != "posted":
        return None

    previous_score = comment.reddit_score
    comment.reddit_score = new_score
    db.flush()

    # Update per-subreddit karma tracking
    try:
        from app.services import karma_tracker

        avatar = comment.avatar
        thread = comment.thread
        if avatar and thread and thread.subreddit:
            karma_tracker.record_comment_score(
                db,
                avatar=avatar,
                subreddit_name=thread.subreddit,
                new_score=new_score,
                previous_score=previous_score,
                increment_count=False,  # Already counted when marked as posted
            )
    except Exception:
        logger.warning(
            "Karma tracker update failed for comment %s", comment_id, exc_info=True
        )

    db.commit()
    return comment


def check_karma_drop_demotion(
    db: Session,
    avatar: Avatar,
) -> tuple[bool, float]:
    """Check if avatar's recent karma warrants phase demotion.

    Evaluates average reddit_score of posted comments in the evaluation window.
    If avg score < KARMA_DROP_THRESHOLD and there are enough scored comments,
    returns (True, avg_score).

    Args:
        db: Database session.
        avatar: The avatar to evaluate.

    Returns:
        (should_demote: bool, avg_score: float)
    """
    if avatar.warming_phase <= 1:
        return (False, 0.0)

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=KARMA_EVAL_WINDOW_DAYS)

    # Get scored posted comments in window
    scored_comments = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.status == "posted",
            CommentDraft.reddit_score.isnot(None),
            CommentDraft.posted_at >= window_start,
        )
        .all()
    )

    if len(scored_comments) < MIN_SCORED_COMMENTS:
        return (False, 0.0)

    avg_score = sum(c.reddit_score for c in scored_comments) / len(scored_comments)

    if avg_score < KARMA_DROP_THRESHOLD:
        return (True, avg_score)

    return (False, avg_score)


def evaluate_and_demote_if_needed(
    db: Session,
    avatar: Avatar,
) -> dict:
    """Evaluate karma drop and execute demotion if triggered.

    Returns a summary dict with evaluation results.
    """
    should_demote, avg_score = check_karma_drop_demotion(db, avatar)

    result = {
        "avatar_id": str(avatar.id),
        "avatar_username": avatar.reddit_username,
        "current_phase": avatar.warming_phase,
        "avg_score": round(avg_score, 2),
        "should_demote": should_demote,
        "demoted": False,
    }

    if not should_demote:
        return result

    # Execute demotion
    try:
        from app.services.phase import PhaseTransitionManager
        from app.services.phase_lock import PhaseTransitionLock
        from app.config import get_settings
        import redis

        redis_client = redis.from_url(get_settings().redis_url)
        lock = PhaseTransitionLock(redis_client)
        manager = PhaseTransitionManager(lock)

        target_phase = max(1, avatar.warming_phase - 1)
        trigger_reason = f"karma_drop (avg_score={avg_score:.2f})"

        demoted = manager.demote(db, avatar, target_phase, trigger_reason)
        result["demoted"] = demoted
        result["new_phase"] = target_phase if demoted else avatar.warming_phase

        if demoted:
            logger.info(
                "Avatar %s demoted to Phase %d due to karma drop (avg=%.2f)",
                avatar.reddit_username,
                target_phase,
                avg_score,
            )
    except Exception:
        logger.warning(
            "Karma-drop demotion failed for avatar %s",
            avatar.reddit_username,
            exc_info=True,
        )

    return result


def get_avatar_karma_summary(
    db: Session,
    avatar_id: UUID,
    window_days: int = KARMA_EVAL_WINDOW_DAYS,
) -> dict:
    """Get karma performance summary for an avatar's posted comments.

    Returns:
        Dict with total_posted, scored_count, avg_score, negative_count,
        positive_count, and at_risk flag.
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=window_days)

    posted_comments = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
            CommentDraft.posted_at >= window_start,
        )
        .all()
    )

    total_posted = len(posted_comments)
    scored = [c for c in posted_comments if c.reddit_score is not None]
    scored_count = len(scored)

    if scored_count == 0:
        return {
            "total_posted": total_posted,
            "scored_count": 0,
            "avg_score": None,
            "negative_count": 0,
            "positive_count": 0,
            "at_risk": False,
        }

    avg_score = sum(c.reddit_score for c in scored) / scored_count
    negative_count = sum(1 for c in scored if c.reddit_score < 0)
    positive_count = sum(1 for c in scored if c.reddit_score > 0)

    at_risk = (
        scored_count >= MIN_SCORED_COMMENTS and avg_score < KARMA_DROP_THRESHOLD
    )

    return {
        "total_posted": total_posted,
        "scored_count": scored_count,
        "avg_score": round(avg_score, 2),
        "negative_count": negative_count,
        "positive_count": positive_count,
        "at_risk": at_risk,
    }


def update_post_score(
    db: Session,
    post_id: UUID,
    new_score: int,
    upvote_ratio: float | None = None,
    num_comments: int | None = None,
) -> "PostDraft | None":
    """Update reddit_score on a posted PostDraft and reconcile karma tracking.

    Args:
        db: Database session.
        post_id: The post draft ID.
        new_score: The observed Reddit score (upvotes - downvotes).
        upvote_ratio: The upvote ratio (0.0 to 1.0).
        num_comments: Number of comments on the post.

    Returns:
        The updated PostDraft, or None if not found / not posted.
    """
    from app.models.post_draft import PostDraft

    post = db.query(PostDraft).filter(PostDraft.id == post_id).first()
    if not post:
        return None
    if post.status != "posted":
        return None

    previous_score = post.reddit_score
    post.reddit_score = new_score
    if upvote_ratio is not None:
        post.reddit_upvote_ratio = upvote_ratio
    if num_comments is not None:
        post.reddit_num_comments = num_comments
    post.last_karma_check_at = datetime.now(timezone.utc)
    db.flush()

    # Update per-subreddit post karma tracking
    try:
        from app.services import karma_tracker
        from app.models.avatar import Avatar

        avatar = db.query(Avatar).filter(Avatar.id == post.avatar_id).first()
        if avatar and post.subreddit:
            record, _ = karma_tracker._get_or_create_record(db, avatar, post.subreddit)
            karma_tracker._snapshot_previous(record)
            delta = (new_score or 0) - (previous_score or 0)
            record.post_karma = (record.post_karma or 0) + delta
            record.last_updated_at = datetime.now(timezone.utc)
    except Exception:
        logger.warning(
            "Post karma tracker update failed for post %s", post_id, exc_info=True
        )

    db.commit()
    return post


def get_avatar_full_karma_summary(
    db: Session,
    avatar_id: UUID,
    window_days: int = KARMA_EVAL_WINDOW_DAYS,
) -> dict:
    """Get full karma performance summary for an avatar — both posts and comments.

    Returns:
        Dict with comments and posts sections, plus combined metrics.
    """
    from app.models.post_draft import PostDraft

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=window_days)

    # Comments
    posted_comments = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
            CommentDraft.posted_at >= window_start,
        )
        .all()
    )
    scored_comments = [c for c in posted_comments if c.reddit_score is not None]
    deleted_comments = [c for c in posted_comments if c.is_deleted]

    # Posts
    posted_posts = (
        db.query(PostDraft)
        .filter(
            PostDraft.avatar_id == avatar_id,
            PostDraft.status == "posted",
            PostDraft.posted_at >= window_start,
        )
        .all()
    )
    scored_posts = [p for p in posted_posts if p.reddit_score is not None]
    deleted_posts = [p for p in posted_posts if p.is_deleted]

    # Comment stats
    comment_avg = (
        sum(c.reddit_score for c in scored_comments) / len(scored_comments)
        if scored_comments else None
    )

    # Post stats
    post_avg = (
        sum(p.reddit_score for p in scored_posts) / len(scored_posts)
        if scored_posts else None
    )

    # Combined karma
    all_scores = [c.reddit_score for c in scored_comments] + [p.reddit_score for p in scored_posts]
    combined_avg = sum(all_scores) / len(all_scores) if all_scores else None

    return {
        "window_days": window_days,
        "comments": {
            "total_posted": len(posted_comments),
            "scored": len(scored_comments),
            "avg_score": round(comment_avg, 2) if comment_avg is not None else None,
            "total_karma": sum(c.reddit_score for c in scored_comments) if scored_comments else 0,
            "deleted": len(deleted_comments),
            "negative_count": sum(1 for c in scored_comments if c.reddit_score < 0),
            "positive_count": sum(1 for c in scored_comments if c.reddit_score > 0),
        },
        "posts": {
            "total_posted": len(posted_posts),
            "scored": len(scored_posts),
            "avg_score": round(post_avg, 2) if post_avg is not None else None,
            "total_karma": sum(p.reddit_score for p in scored_posts) if scored_posts else 0,
            "deleted": len(deleted_posts),
            "avg_upvote_ratio": (
                round(sum(p.reddit_upvote_ratio for p in scored_posts if p.reddit_upvote_ratio) / len(scored_posts), 2)
                if scored_posts else None
            ),
            "total_comments_received": sum(p.reddit_num_comments or 0 for p in scored_posts),
        },
        "combined": {
            "total_actions": len(posted_comments) + len(posted_posts),
            "total_scored": len(all_scores),
            "avg_score": round(combined_avg, 2) if combined_avg is not None else None,
            "total_karma": sum(all_scores) if all_scores else 0,
            "total_deleted": len(deleted_comments) + len(deleted_posts),
            "survival_rate": (
                round((1 - (len(deleted_comments) + len(deleted_posts)) / (len(posted_comments) + len(posted_posts))) * 100, 1)
                if (posted_comments or posted_posts) else None
            ),
            "at_risk": (
                len(all_scores) >= MIN_SCORED_COMMENTS
                and combined_avg is not None
                and combined_avg < KARMA_DROP_THRESHOLD
            ),
        },
    }
