#!/usr/bin/env python3
"""
Post & Comment Karma Checker — проверяет карму постов/комментариев аватаров на Reddit.

Запуск:
    cd reddit_saas && python -m scripts.check_post_karma
    cd reddit_saas && python -m scripts.check_post_karma --username Hot-Thought2408
    cd reddit_saas && python -m scripts.check_post_karma --username Hot-Thought2408 --limit 5
    cd reddit_saas && python -m scripts.check_post_karma --all-avatars

Что делает:
    1. Подключается к Reddit API через PRAW
    2. Получает последние посты/комментарии указанного пользователя
    3. Показывает карму (score), upvote ratio, количество комментариев
    4. Обновляет reddit_score в БД для наших post_drafts/comment_drafts (если найдены)

Почему карма может быть неизвестна:
    - PostDraft модель не имеет поля reddit_score (в отличие от CommentDraft)
    - Нет автоматического трекинга кармы постов после публикации
    - reddit_status.py проверяет только общую карму аватара, не конкретных постов
"""

import argparse
import sys
import os
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import praw
from prawcore.exceptions import NotFound, Forbidden, RequestException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import get_settings, get_config
from app.models.avatar import Avatar
from app.models.post_draft import PostDraft
from app.models.comment_draft import CommentDraft
from app.models.thread import RedditThread


def get_reddit_client() -> praw.Reddit:
    """Create a read-only Reddit client from app config."""
    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as db:
        client_id = get_config("reddit_client_id", db)
        client_secret = get_config("reddit_client_secret", db)
        user_agent = get_config("reddit_user_agent", db)

    if not client_id or not client_secret:
        # Fallback to env vars
        client_id = os.getenv("REDDIT_CLIENT_ID", client_id or "")
        client_secret = os.getenv("REDDIT_CLIENT_SECRET", client_secret or "")
        user_agent = os.getenv("REDDIT_USER_AGENT", user_agent or "RAMP/1.0")

    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
    )


def check_user_posts(username: str, limit: int = 10, verbose: bool = True) -> list[dict]:
    """Fetch recent posts by a Reddit user and return their karma info.

    Args:
        username: Reddit username (without u/ prefix)
        limit: Max posts to fetch
        verbose: Print results to stdout

    Returns:
        List of post dicts with karma info
    """
    reddit = get_reddit_client()

    if verbose:
        print(f"\n{'='*70}")
        print(f"  📊 Post Karma Check: u/{username}")
        print(f"  📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}")

    try:
        redditor = reddit.redditor(username)
        # Check if user exists / is suspended
        if getattr(redditor, "is_suspended", False):
            if verbose:
                print(f"  ❌ u/{username} is SUSPENDED")
            return []

        # General karma
        comment_karma = getattr(redditor, "comment_karma", 0)
        link_karma = getattr(redditor, "link_karma", 0)
        if verbose:
            print(f"\n  👤 Account Overview:")
            print(f"     Comment Karma: {comment_karma}")
            print(f"     Post Karma:    {link_karma}")
            print(f"     Total:         {comment_karma + link_karma}")

    except NotFound:
        if verbose:
            print(f"  ❌ u/{username} not found")
        return []
    except Forbidden:
        if verbose:
            print(f"  ❌ u/{username} — access forbidden (possibly shadowbanned)")
        return []

    # Fetch recent posts (submissions)
    posts = []
    if verbose:
        print(f"\n  📝 Recent Posts (limit={limit}):")
        print(f"  {'─'*66}")

    try:
        for submission in redditor.submissions.new(limit=limit):
            post_info = {
                "id": submission.id,
                "subreddit": submission.subreddit.display_name,
                "title": submission.title[:80],
                "score": submission.score,
                "upvote_ratio": submission.upvote_ratio,
                "num_comments": submission.num_comments,
                "url": f"https://reddit.com{submission.permalink}",
                "created_utc": datetime.fromtimestamp(submission.created_utc, tz=timezone.utc),
                "is_removed": submission.removed_by_category is not None,
                "over_18": submission.over_18,
            }
            posts.append(post_info)

            if verbose:
                age = datetime.now(timezone.utc) - post_info["created_utc"]
                age_str = f"{age.days}d" if age.days > 0 else f"{age.seconds // 3600}h"
                removed_flag = " 🚫 REMOVED" if post_info["is_removed"] else ""
                print(
                    f"  {'⬆' if post_info['score'] > 0 else '⬇'} "
                    f"Score: {post_info['score']:>4} | "
                    f"Ratio: {post_info['upvote_ratio']:.0%} | "
                    f"Comments: {post_info['num_comments']:>3} | "
                    f"Age: {age_str:>4} | "
                    f"r/{post_info['subreddit']}"
                    f"{removed_flag}"
                )
                print(f"    └─ {post_info['title']}")
                print(f"       {post_info['url']}")
                print()

    except Exception as e:
        if verbose:
            print(f"  ⚠️  Error fetching posts: {e}")

    # Fetch recent comments
    comments = []
    if verbose:
        print(f"\n  💬 Recent Comments (limit={limit}):")
        print(f"  {'─'*66}")

    try:
        for comment in redditor.comments.new(limit=limit):
            comment_info = {
                "id": comment.id,
                "subreddit": comment.subreddit.display_name,
                "body": comment.body[:100],
                "score": comment.score,
                "created_utc": datetime.fromtimestamp(comment.created_utc, tz=timezone.utc),
                "is_removed": comment.body in ("[removed]", "[deleted]"),
                "parent_title": getattr(comment, "link_title", "")[:60],
            }
            comments.append(comment_info)

            if verbose:
                age = datetime.now(timezone.utc) - comment_info["created_utc"]
                age_str = f"{age.days}d" if age.days > 0 else f"{age.seconds // 3600}h"
                removed_flag = " 🚫 REMOVED" if comment_info["is_removed"] else ""
                print(
                    f"  {'⬆' if comment_info['score'] > 0 else '⬇'} "
                    f"Score: {comment_info['score']:>4} | "
                    f"Age: {age_str:>4} | "
                    f"r/{comment_info['subreddit']}"
                    f"{removed_flag}"
                )
                print(f"    └─ Re: {comment_info['parent_title']}")
                print(f"       {comment_info['body'][:80]}...")
                print()

    except Exception as e:
        if verbose:
            print(f"  ⚠️  Error fetching comments: {e}")

    if verbose:
        print(f"  {'='*66}")
        print(f"  Summary: {len(posts)} posts, {len(comments)} comments")
        total_post_karma = sum(p["score"] for p in posts)
        total_comment_karma = sum(c["score"] for c in comments)
        print(f"  Post karma (visible): {total_post_karma}")
        print(f"  Comment karma (visible): {total_comment_karma}")

    return posts


def sync_post_karma_to_db(username: str, posts: list[dict]):
    """Match fetched posts against our PostDraft records and log findings.

    Since PostDraft doesn't have reddit_score field, this just reports
    what we find. In the future, we should add reddit_score to PostDraft.
    """
    settings = get_settings()
    engine = create_engine(settings.database_url)

    with Session(engine) as db:
        avatar = db.query(Avatar).filter(Avatar.reddit_username == username).first()
        if not avatar:
            print(f"\n  ⚠️  Avatar u/{username} not found in database")
            return

        print(f"\n  🔗 DB Sync for u/{username} (avatar_id={str(avatar.id)[:8]}...):")

        # Check PostDrafts
        our_posts = (
            db.query(PostDraft)
            .filter(PostDraft.avatar_id == avatar.id, PostDraft.status == "posted")
            .all()
        )
        print(f"     PostDrafts with status='posted': {len(our_posts)}")

        # Check CommentDrafts
        our_comments = (
            db.query(CommentDraft)
            .filter(CommentDraft.avatar_id == avatar.id, CommentDraft.status == "posted")
            .all()
        )
        print(f"     CommentDrafts with status='posted': {len(our_comments)}")

        # For comments, try to match and update reddit_score
        updated = 0
        for cd in our_comments:
            if cd.reddit_score is None:
                print(f"     ⚠️  CommentDraft {str(cd.id)[:8]} has NO reddit_score tracked")

        # Note: PostDraft model lacks reddit_score field entirely
        if our_posts:
            print(f"\n     ℹ️  PostDraft model does NOT have reddit_score field.")
            print(f"     ℹ️  This is why karma is unknown for posts.")
            print(f"     ℹ️  Consider adding reddit_score, reddit_url, upvote_ratio to PostDraft model.")


def check_all_avatars(limit: int = 5):
    """Check karma for all active avatars in the database."""
    settings = get_settings()
    engine = create_engine(settings.database_url)

    with Session(engine) as db:
        avatars = db.query(Avatar).filter(Avatar.active.is_(True)).all()

    print(f"\n  Found {len(avatars)} active avatars")
    print(f"  {'='*70}")

    for i, avatar in enumerate(avatars):
        if i > 0:
            time.sleep(2)  # Rate limit between users
        posts = check_user_posts(avatar.reddit_username, limit=limit)
        sync_post_karma_to_db(avatar.reddit_username, posts)


def main():
    parser = argparse.ArgumentParser(
        description="Check Reddit post/comment karma for avatars"
    )
    parser.add_argument(
        "--username", "-u",
        help="Reddit username to check (without u/ prefix)",
    )
    parser.add_argument(
        "--all-avatars", "-a",
        action="store_true",
        help="Check all active avatars in the database",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=10,
        help="Max posts/comments to fetch per user (default: 10)",
    )
    parser.add_argument(
        "--sync-db",
        action="store_true",
        help="Also check and report DB sync status",
    )

    args = parser.parse_args()

    if not args.username and not args.all_avatars:
        parser.error("Specify --username or --all-avatars")

    if args.all_avatars:
        check_all_avatars(limit=args.limit)
    else:
        posts = check_user_posts(args.username, limit=args.limit)
        if args.sync_db:
            sync_post_karma_to_db(args.username, posts)


if __name__ == "__main__":
    main()
