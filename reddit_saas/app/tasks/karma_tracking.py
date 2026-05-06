"""Celery tasks for karma tracking — monitors all avatar activity effects on Reddit.

Tracks:
- Comment karma (reddit_score) for posted CommentDrafts
- Post karma (reddit_score, upvote_ratio, num_comments) for posted PostDrafts
- Per-subreddit karma breakdown updates
- Overall avatar karma sync
- Deletion/removal detection
- Karma-based phase demotion triggers

Schedule:
- Runs every 4 hours via Celery Beat
- Checks posted items from the last 7 days (configurable)
- Rate-limited: 2s delay between Reddit API calls per avatar
"""

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from app.tasks.worker import celery_app
from app.database import SessionLocal
from app.models.avatar import Avatar
from app.models.comment_draft import CommentDraft
from app.models.post_draft import PostDraft
from app.models.thread import RedditThread
from app.services.transparency import record_activity_event

logger = logging.getLogger(__name__)

# How far back to check karma for posted items
KARMA_CHECK_WINDOW_DAYS = 7
# Minimum time between karma checks for the same item (avoid hammering API)
MIN_RECHECK_INTERVAL_HOURS = 4
# Delay between Reddit API calls (rate limiting)
API_CALL_DELAY_SECONDS = 2


@celery_app.task(name="track_karma_all_avatars")
def track_karma_all_avatars():
    """Track karma for all active avatars — posts and comments.

    For each avatar:
    1. Fetch recent submissions from Reddit → update PostDraft.reddit_score
    2. Fetch recent comments from Reddit → update CommentDraft.reddit_score
    3. Update per-subreddit karma breakdown
    4. Update avatar total karma
    5. Detect deletions/removals
    6. Evaluate karma-based phase demotion
    """
    db = SessionLocal()
    try:
        avatars = (
            db.query(Avatar)
            .filter(Avatar.active.is_(True), Avatar.is_shadowbanned.is_(False))
            .all()
        )
        logger.info(f"Karma tracking: processing {len(avatars)} active avatars")

        total_stats = {
            "avatars_processed": 0,
            "comments_updated": 0,
            "posts_updated": 0,
            "deletions_detected": 0,
            "demotions_triggered": 0,
            "errors": 0,
        }

        for i, avatar in enumerate(avatars):
            if i > 0:
                time.sleep(API_CALL_DELAY_SECONDS)

            try:
                stats = _track_single_avatar(db, avatar)
                total_stats["avatars_processed"] += 1
                total_stats["comments_updated"] += stats.get("comments_updated", 0)
                total_stats["posts_updated"] += stats.get("posts_updated", 0)
                total_stats["deletions_detected"] += stats.get("deletions_detected", 0)
                total_stats["demotions_triggered"] += stats.get("demotions_triggered", 0)
            except Exception as e:
                total_stats["errors"] += 1
                logger.error(f"Karma tracking failed for u/{avatar.reddit_username}: {e}")
                db.rollback()
                continue

        # Record summary activity event
        try:
            message = (
                f"Karma tracking complete: {total_stats['avatars_processed']} avatars, "
                f"{total_stats['comments_updated']} comments updated, "
                f"{total_stats['posts_updated']} posts updated, "
                f"{total_stats['deletions_detected']} deletions detected"
            )
            record_activity_event(db, "karma_tracking", message, client_id=None, metadata=total_stats)
        except Exception:
            logger.warning("Failed to record karma tracking summary event")

        logger.info(f"Karma tracking complete: {total_stats}")
        return total_stats

    finally:
        db.close()


def _track_single_avatar(db, avatar: Avatar) -> dict:
    """Track karma for a single avatar. Returns stats dict."""
    from app.services.reddit import get_reddit_client
    from app.services.karma_feedback import update_comment_score, evaluate_and_demote_if_needed
    from app.services import karma_tracker
    from prawcore.exceptions import NotFound, Forbidden, RequestException

    stats = {
        "comments_updated": 0,
        "posts_updated": 0,
        "deletions_detected": 0,
        "demotions_triggered": 0,
    }

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=KARMA_CHECK_WINDOW_DAYS)
    recheck_cutoff = now - timedelta(hours=MIN_RECHECK_INTERVAL_HOURS)

    try:
        reddit = get_reddit_client()
        redditor = reddit.redditor(avatar.reddit_username)

        # Check if account is accessible
        if getattr(redditor, "is_suspended", False):
            logger.warning(f"u/{avatar.reddit_username} is suspended — skipping karma tracking")
            avatar.reddit_status = "suspended"
            db.commit()
            return stats

    except (NotFound, Forbidden) as e:
        logger.warning(f"u/{avatar.reddit_username} not accessible: {e}")
        return stats
    except (RequestException, Exception) as e:
        logger.error(f"Reddit API error for u/{avatar.reddit_username}: {e}")
        return stats

    # --- Track POSTS ---
    stats["posts_updated"] = _track_avatar_posts(db, avatar, redditor, now, window_start, recheck_cutoff)

    time.sleep(1)  # Brief pause between submissions and comments API calls

    # --- Track COMMENTS ---
    stats["comments_updated"], stats["deletions_detected"] = _track_avatar_comments(
        db, avatar, redditor, now, window_start, recheck_cutoff
    )

    # --- Update per-subreddit karma from Reddit ---
    try:
        karma_tracker.sync_avatar_from_comment_history(db, avatar, log_event=True)
    except Exception as e:
        logger.warning(f"Subreddit karma sync failed for u/{avatar.reddit_username}: {e}")

    # --- Update avatar total karma from Reddit ---
    try:
        avatar.reddit_karma_comment = int(getattr(redditor, "comment_karma", 0) or 0)
        avatar.reddit_karma_post = int(getattr(redditor, "link_karma", 0) or 0)
        avatar.reddit_status = "active"
        avatar.reddit_status_checked_at = now
        db.commit()
    except Exception as e:
        logger.warning(f"Avatar karma update failed for u/{avatar.reddit_username}: {e}")
        db.rollback()

    # --- Evaluate karma-based demotion ---
    try:
        result = evaluate_and_demote_if_needed(db, avatar)
        if result.get("demoted"):
            stats["demotions_triggered"] = 1
            logger.info(
                f"u/{avatar.reddit_username} demoted to Phase {result.get('new_phase')} "
                f"(avg_score={result.get('avg_score')})"
            )
    except Exception as e:
        logger.warning(f"Demotion evaluation failed for u/{avatar.reddit_username}: {e}")

    return stats


def _track_avatar_posts(db, avatar: Avatar, redditor, now, window_start, recheck_cutoff) -> int:
    """Fetch recent posts from Reddit and update PostDraft records.

    Returns number of posts updated.
    """
    # Get our posted PostDrafts that need karma checking
    our_posts = (
        db.query(PostDraft)
        .filter(
            PostDraft.avatar_id == avatar.id,
            PostDraft.status == "posted",
            PostDraft.posted_at >= window_start,
        )
        .filter(
            # Only recheck if never checked or check is stale
            (PostDraft.last_karma_check_at.is_(None))
            | (PostDraft.last_karma_check_at < recheck_cutoff)
        )
        .all()
    )

    if not our_posts:
        return 0

    # Fetch recent submissions from Reddit
    try:
        reddit_posts = {}
        for submission in redditor.submissions.new(limit=25):
            created = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)
            if created < window_start:
                break
            reddit_posts[submission.id] = submission
            # Also index by title for matching (PostDraft may not have reddit_native_id)
            reddit_posts[f"title:{submission.title.lower().strip()[:100]}"] = submission
    except Exception as e:
        logger.warning(f"Failed to fetch submissions for u/{avatar.reddit_username}: {e}")
        return 0

    updated = 0
    for post_draft in our_posts:
        submission = None

        # Match by reddit_native_id first
        if post_draft.reddit_native_id:
            submission = reddit_posts.get(post_draft.reddit_native_id)

        # Fallback: match by title
        if not submission:
            title_key = f"title:{(post_draft.edited_title or post_draft.ai_title or '').lower().strip()[:100]}"
            submission = reddit_posts.get(title_key)

        if submission:
            previous_score = post_draft.reddit_score
            post_draft.reddit_native_id = submission.id
            post_draft.reddit_score = submission.score
            post_draft.reddit_upvote_ratio = submission.upvote_ratio
            post_draft.reddit_num_comments = submission.num_comments
            post_draft.last_karma_check_at = now

            # Detect removal
            if submission.removed_by_category and not post_draft.is_deleted:
                post_draft.is_deleted = True
                post_draft.deleted_detected_at = now
                logger.warning(
                    f"Post removed: u/{avatar.reddit_username} in r/{post_draft.subreddit} "
                    f"(score={submission.score}, reason={submission.removed_by_category})"
                )

            # Update per-subreddit post karma
            try:
                from app.services.karma_tracker import _get_or_create_record, _snapshot_previous
                record, _ = _get_or_create_record(db, avatar, post_draft.subreddit)
                _snapshot_previous(record)
                # Accumulate post karma delta
                delta = (submission.score or 0) - (previous_score or 0)
                record.post_karma = (record.post_karma or 0) + delta
                record.last_updated_at = now
            except Exception as e:
                logger.warning(f"Post karma tracker update failed: {e}")

            updated += 1
        else:
            # Post not found on Reddit — might be deleted or too old
            post_draft.last_karma_check_at = now

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.warning(f"Failed to commit post karma updates for u/{avatar.reddit_username}")
        return 0

    if updated > 0:
        logger.info(f"u/{avatar.reddit_username}: updated karma for {updated} posts")

    return updated


def _track_avatar_comments(db, avatar: Avatar, redditor, now, window_start, recheck_cutoff):
    """Fetch recent comments from Reddit and update CommentDraft records.

    Returns (comments_updated, deletions_detected).
    """
    from app.services.karma_feedback import update_comment_score

    # Get our posted CommentDrafts that need karma checking
    our_comments = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.status == "posted",
            CommentDraft.posted_at >= window_start,
        )
        .filter(
            (CommentDraft.last_karma_check_at.is_(None))
            | (CommentDraft.last_karma_check_at < recheck_cutoff)
        )
        .all()
    )

    if not our_comments:
        return 0, 0

    # Fetch recent comments from Reddit
    try:
        reddit_comments = {}
        for comment in redditor.comments.new(limit=100):
            created = datetime.fromtimestamp(comment.created_utc, tz=timezone.utc)
            if created < window_start:
                break
            reddit_comments[comment.id] = comment
            # Index by body prefix for matching (CommentDraft doesn't store reddit comment ID)
            body_key = (comment.body or "").strip()[:80].lower()
            if body_key:
                reddit_comments[f"body:{body_key}"] = comment
    except Exception as e:
        logger.warning(f"Failed to fetch comments for u/{avatar.reddit_username}: {e}")
        return 0, 0

    updated = 0
    deletions = 0

    for comment_draft in our_comments:
        reddit_comment = None

        # Match by body text (edited_draft or ai_draft)
        draft_text = (comment_draft.edited_draft or comment_draft.ai_draft or "").strip()[:80].lower()
        if draft_text:
            reddit_comment = reddit_comments.get(f"body:{draft_text}")

        if reddit_comment:
            new_score = reddit_comment.score
            previous_score = comment_draft.reddit_score

            # Use the karma_feedback service to update (handles subreddit karma too)
            if previous_score != new_score:
                update_comment_score(db, comment_draft.id, new_score)
                updated += 1

            comment_draft.last_karma_check_at = now

            # Detect deletion
            if reddit_comment.body in ("[removed]", "[deleted]") and not comment_draft.is_deleted:
                comment_draft.is_deleted = True
                comment_draft.deleted_detected_at = now
                deletions += 1
                logger.warning(
                    f"Comment removed: u/{avatar.reddit_username} in "
                    f"r/{comment_draft.thread.subreddit if comment_draft.thread else '?'} "
                    f"(score={new_score})"
                )
        else:
            # Comment not found — could be deleted or outside the 100-comment window
            comment_draft.last_karma_check_at = now

            # If comment was posted recently but not found, likely deleted
            if comment_draft.posted_at and (now - comment_draft.posted_at) < timedelta(days=2):
                if not comment_draft.is_deleted:
                    comment_draft.is_deleted = True
                    comment_draft.deleted_detected_at = now
                    deletions += 1
                    logger.warning(
                        f"Comment likely removed (not found): u/{avatar.reddit_username}, "
                        f"posted {comment_draft.posted_at}"
                    )

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.warning(f"Failed to commit comment karma updates for u/{avatar.reddit_username}")
        return 0, 0

    if updated > 0 or deletions > 0:
        logger.info(
            f"u/{avatar.reddit_username}: {updated} comments updated, {deletions} deletions detected"
        )

    return updated, deletions


@celery_app.task(name="track_karma_single_avatar")
def track_karma_single_avatar(avatar_id: str):
    """Track karma for a single avatar — for manual triggering or targeted checks."""
    db = SessionLocal()
    try:
        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if not avatar:
            logger.error(f"Avatar {avatar_id} not found")
            return {"error": "avatar_not_found"}

        stats = _track_single_avatar(db, avatar)

        # Record activity event
        client_id = avatar.client_ids[0] if avatar.client_ids else None
        try:
            message = (
                f"Karma tracked for u/{avatar.reddit_username}: "
                f"{stats['posts_updated']} posts, {stats['comments_updated']} comments"
            )
            record_activity_event(
                db, "karma_tracking", message,
                client_id=uuid.UUID(client_id) if client_id else None,
                metadata={"avatar_id": str(avatar.id), **stats},
            )
        except Exception:
            pass

        return stats

    finally:
        db.close()
