"""Celery tasks for Reddit scraping."""

import logging
from datetime import datetime, timezone

from app.tasks.worker import celery_app
from app.database import SessionLocal
from app.models.client import Client
from app.models.subreddit import ClientSubreddit
from app.models.thread import RedditThread
from app.services.reddit import scrape_subreddit, deduplicate_posts

logger = logging.getLogger(__name__)


@celery_app.task(name="scrape_professional_subreddits")
def scrape_professional_subreddits(client_id: str):
    """Scrape all professional subreddits for a client."""
    db = SessionLocal()
    try:
        client = db.query(Client).filter(Client.id == client_id).first()
        if not client:
            logger.error(f"Client {client_id} not found")
            return

        subreddits = (
            db.query(ClientSubreddit)
            .filter(
                ClientSubreddit.client_id == client_id,
                ClientSubreddit.type == "professional",
                ClientSubreddit.is_active.is_(True),
            )
            .all()
        )

        # Get existing thread IDs for dedup
        existing_ids = set(
            row[0]
            for row in db.query(RedditThread.reddit_native_id)
            .filter(RedditThread.client_id == client_id)
            .all()
        )

        total_new = 0
        for sub in subreddits:
            try:
                posts = scrape_subreddit(sub.subreddit_name, limit=50, max_age_hours=24)
                new_posts = deduplicate_posts(posts, existing_ids)

                for post in new_posts:
                    thread = RedditThread(
                        client_id=client_id,
                        type="professional",
                        reddit_native_id=post["reddit_native_id"],
                        subreddit=post["subreddit"],
                        post_title=post["post_title"],
                        post_body=post["post_body"],
                        comments_json=post["comments_json"],
                        url=post["url"],
                        author=post["author"],
                        score=post["score"],
                        ups=post["ups"],
                        downs=post["downs"],
                        scraped_at=datetime.now(timezone.utc),
                    )
                    db.add(thread)
                    existing_ids.add(post["reddit_native_id"])

                db.commit()
                total_new += len(new_posts)
                logger.info(f"r/{sub.subreddit_name}: {len(new_posts)} new posts")

            except Exception as e:
                logger.error(f"Failed to scrape r/{sub.subreddit_name}: {e}")
                continue

        logger.info(f"Scraping complete for {client.client_name}: {total_new} new posts total")
        return total_new

    finally:
        db.close()


@celery_app.task(name="scrape_hobby_subreddits")
def scrape_hobby_subreddits(avatar_id: str):
    """Scrape hobby subreddits for an avatar."""
    db = SessionLocal()
    try:
        from app.models.avatar import Avatar
        from app.models.hobby import HobbySubreddit

        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if not avatar:
            logger.error(f"Avatar {avatar_id} not found")
            return

        hobby_subs = avatar.hobby_subreddits or []
        if isinstance(hobby_subs, str):
            hobby_subs = [s.strip() for s in hobby_subs.split(",")]

        total_new = 0
        for sub_name in hobby_subs:
            sub_name = sub_name.strip().replace("r/", "")
            if not sub_name:
                continue

            try:
                posts = scrape_subreddit(sub_name, limit=20, max_age_hours=24, sort="hot")

                for post in posts:
                    # Check if already exists
                    exists = (
                        db.query(HobbySubreddit)
                        .filter(HobbySubreddit.post_id == post["reddit_native_id"])
                        .first()
                    )
                    if exists:
                        continue

                    hobby = HobbySubreddit(
                        subreddit=post["subreddit"],
                        post_id=post["reddit_native_id"],
                        post_title=post["post_title"],
                        post_body=post["post_body"],
                        comments=post["comments_json"],
                        url=post["url"],
                        author=post["author"],
                        avatar_username=avatar.reddit_username,
                        post_ups=post["ups"],
                        post_downs=post["downs"],
                        status="new",
                    )
                    db.add(hobby)
                    total_new += 1

                db.commit()

            except Exception as e:
                logger.error(f"Failed to scrape hobby r/{sub_name}: {e}")
                continue

        logger.info(f"Hobby scraping for {avatar.reddit_username}: {total_new} new posts")
        return total_new

    finally:
        db.close()
