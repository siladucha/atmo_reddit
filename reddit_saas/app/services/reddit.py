"""Reddit API service using PRAW.

Handles subreddit scraping, comment tree flattening, and deduplication.
"""

import json
import logging
from datetime import datetime, timezone, timedelta

import praw
from praw.models import Submission

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def get_reddit_client() -> praw.Reddit:
    """Create a read-only Reddit client."""
    return praw.Reddit(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        user_agent=settings.reddit_user_agent,
    )


def scrape_subreddit(
    subreddit_name: str,
    limit: int = 50,
    max_age_hours: int = 24,
    sort: str = "hot",
) -> list[dict]:
    """Scrape posts from a subreddit.

    Args:
        subreddit_name: Name without r/ prefix (e.g. 'cybersecurity')
        limit: Max posts to fetch
        max_age_hours: Only return posts newer than this
        sort: 'hot', 'new', or 'top'

    Returns:
        List of post dicts with standardized keys.
    """
    reddit = get_reddit_client()
    subreddit = reddit.subreddit(subreddit_name)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    if sort == "hot":
        submissions = subreddit.hot(limit=limit)
    elif sort == "new":
        submissions = subreddit.new(limit=limit)
    elif sort == "top":
        submissions = subreddit.top(limit=limit, time_filter="day")
    else:
        submissions = subreddit.hot(limit=limit)

    posts = []
    for submission in submissions:
        # Skip stickied posts
        if submission.stickied:
            continue

        # Skip posts older than cutoff
        created_utc = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)
        if created_utc < cutoff:
            continue

        post = _submission_to_dict(submission)
        posts.append(post)

    logger.info(f"Scraped {len(posts)} posts from r/{subreddit_name} ({sort}, last {max_age_hours}h)")
    return posts


def fetch_comments(submission_id: str, max_comments: int = 100) -> list[dict]:
    """Fetch and flatten comment tree for a submission.

    Args:
        submission_id: Reddit submission ID (without t3_ prefix)
        max_comments: Max comments to return

    Returns:
        Flat list of comment dicts with depth info.
    """
    reddit = get_reddit_client()
    submission = reddit.submission(id=submission_id)

    # Replace "more comments" placeholders (limit to avoid too many API calls)
    submission.comments.replace_more(limit=3)

    comments = []
    _flatten_comments(submission.comments.list(), comments, max_comments)

    logger.info(f"Fetched {len(comments)} comments for submission {submission_id}")
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

    logger.info(f"Dedup: {len(posts)} → {len(new_posts)} new posts")
    return new_posts
