"""Celery tasks for Reddit scraping."""

import logging
import time
import uuid
from datetime import datetime, timezone

from app.tasks.worker import celery_app
from app.database import SessionLocal
from app.models.client import Client
from app.models.scrape_log import ScrapeLog
from app.models.subreddit import ClientSubreddit, Subreddit
from app.models.thread import RedditThread
from app.services.reddit import scrape_subreddit, deduplicate_posts
from app.services.transparency import record_activity_event

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
        client_uuid = uuid.UUID(client_id)
        for sub in subreddits:
            try:
                # Resolve subreddit_id from shared registry
                subreddit_record = (
                    db.query(Subreddit)
                    .filter(Subreddit.subreddit_name.ilike(sub.subreddit_name))
                    .first()
                )
                if not subreddit_record:
                    subreddit_record = Subreddit(subreddit_name=sub.subreddit_name, is_active=True)
                    db.add(subreddit_record)
                    db.flush()
                subreddit_id = subreddit_record.id

                start = time.time()
                posts = scrape_subreddit(sub.subreddit_name, limit=50, max_age_hours=24)
                new_posts = deduplicate_posts(posts, existing_ids)
                end = time.time()
                duration_ms = int((end - start) * 1000)

                for post in new_posts:
                    thread = RedditThread(
                        client_id=client_id,
                        subreddit_id=subreddit_id,
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
                        is_locked=post.get("is_locked", False),
                        scraped_at=datetime.now(timezone.utc),
                    )
                    db.add(thread)
                    existing_ids.add(post["reddit_native_id"])

                db.commit()
                total_new += len(new_posts)
                logger.info(f"r/{sub.subreddit_name}: {len(new_posts)} new posts")

                # Record transparency data (never crash the pipeline)
                try:
                    scrape_log = ScrapeLog(
                        client_id=client_uuid,
                        subreddit_name=sub.subreddit_name,
                        posts_found=len(posts),
                        posts_new=len(new_posts),
                        duration_ms=duration_ms,
                        errors=None,
                    )
                    db.add(scrape_log)
                    sub.last_scraped_at = datetime.now(timezone.utc)
                    db.commit()

                    message = f"Scraped {len(posts)} posts from r/{sub.subreddit_name} ({len(new_posts)} new)"
                    metadata = {
                        "subreddit_name": sub.subreddit_name,
                        "posts_found": len(posts),
                        "posts_new": len(new_posts),
                        "duration_ms": duration_ms,
                    }
                    record_activity_event(db, "scrape", message, client_uuid, metadata)
                except Exception as te:
                    logger.warning(f"Failed to record transparency for r/{sub.subreddit_name}: {te}")

            except Exception as e:
                logger.error(f"Failed to scrape r/{sub.subreddit_name}: {e}")
                # Record error transparency data (never crash the pipeline).
                # Stamp last_scraped_at so admin UI reflects the attempt; the error
                # itself is preserved in scrape_log.errors and activity_events.
                try:
                    db.rollback()
                    sub.last_scraped_at = datetime.now(timezone.utc)
                    error_log = ScrapeLog(
                        client_id=client_uuid,
                        subreddit_name=sub.subreddit_name,
                        posts_found=0,
                        posts_new=0,
                        duration_ms=0,
                        errors=str(e),
                    )
                    db.add(error_log)
                    db.commit()

                    record_activity_event(
                        db,
                        "system",
                        f"Scrape failed for r/{sub.subreddit_name}: {e}",
                        client_uuid,
                        {"subreddit_name": sub.subreddit_name, "error": str(e)},
                    )
                except Exception as te:
                    logger.warning(f"Failed to record error transparency for r/{sub.subreddit_name}: {te}")
                    db.rollback()
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
        from app.services.settings import is_scrape_enabled
        if not is_scrape_enabled(db):
            logger.info("scrape_hobby_subreddits: scrape_enabled=false, skipping")
            return 0

        from app.models.avatar import Avatar
        from app.models.hobby import HobbySubreddit

        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if not avatar:
            logger.error(f"Avatar {avatar_id} not found")
            return 0
        if avatar.is_frozen:
            logger.info(f"scrape_hobby_subreddits: avatar {avatar.reddit_username} is frozen, skipping")
            return 0

        hobby_subs_raw = avatar.hobby_subreddits or []
        if isinstance(hobby_subs_raw, str):
            hobby_subs_raw = [s.strip() for s in hobby_subs_raw.split(",")]

        # Normalize: handle both list of strings and list of dicts (Ori format)
        hobby_sub_names = []
        for item in hobby_subs_raw:
            if isinstance(item, dict):
                name = item.get("subreddit") or item.get("name") or item.get("display_name") or ""
            else:
                name = str(item)
            name = name.strip().replace("r/", "")
            if name:
                hobby_sub_names.append(name)

        total_new = 0
        for sub_name in hobby_sub_names:
            if not sub_name:
                continue

            try:
                start = time.time()
                posts = scrape_subreddit(sub_name, limit=20, max_age_hours=24, sort="hot")

                total_new_for_sub = 0
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
                    total_new_for_sub += 1

                db.commit()
                total_new += total_new_for_sub
                end = time.time()
                duration_ms = int((end - start) * 1000)

                # Record activity event (no ScrapeLog — hobby scrapes have no client_id)
                try:
                    message = f"Scraped hobby r/{sub_name}: {total_new_for_sub} new posts for {avatar.reddit_username}"
                    metadata = {
                        "subreddit_name": sub_name,
                        "posts_new": total_new_for_sub,
                        "duration_ms": duration_ms,
                        "avatar_username": avatar.reddit_username,
                    }
                    record_activity_event(db, "scrape", message, client_id=None, metadata=metadata)
                except Exception as te:
                    logger.warning(f"Failed to record transparency for hobby r/{sub_name}: {te}")

            except Exception as e:
                logger.error(f"Failed to scrape hobby r/{sub_name}: {e}")
                # Record error activity event (never crash the pipeline)
                try:
                    record_activity_event(
                        db,
                        "system",
                        f"Hobby scrape failed for r/{sub_name}: {e}",
                        client_id=None,
                        metadata={"subreddit_name": sub_name, "error": str(e), "avatar_username": avatar.reddit_username},
                    )
                except Exception as te:
                    logger.warning(f"Failed to record error transparency for hobby r/{sub_name}: {te}")
                continue

        logger.info(f"Hobby scraping for {avatar.reddit_username}: {total_new} new posts")
        return total_new

    finally:
        db.close()


@celery_app.task(name="scrape_subreddit_shared", bind=True, max_retries=0)
def scrape_subreddit_shared(self, subreddit_id: str) -> dict:
    """Scrape a single subreddit. Subreddit-centric — no client_id.

    1. Load Subreddit record
    2. Scrape posts from Reddit
    3. Deduplicate globally by reddit_native_id across entire reddit_threads table
    4. Insert new RedditThread records with subreddit_id (no client_id)
    5. Update Subreddit.last_scraped_at
    6. Record ScrapeLog with subreddit_id (nullable client_id)

    Args:
        subreddit_id: UUID string of the Subreddit record.

    Returns:
        Status dict with scrape results.
    """
    db = SessionLocal()
    start_time = time.time()
    subreddit_uuid = uuid.UUID(subreddit_id)

    try:
        # Load Subreddit record
        sub_record = db.query(Subreddit).filter(Subreddit.id == subreddit_uuid).first()
        if not sub_record:
            logger.error(f"scrape_subreddit_shared: Subreddit {subreddit_id} not found")
            return {"status": "error", "reason": "subreddit_not_found"}

        subreddit_name = sub_record.subreddit_name

        # Record start event
        record_activity_event(
            db,
            "scrape",
            f"Starting shared scrape of r/{subreddit_name}",
            client_id=None,
            metadata={"subreddit_name": subreddit_name, "subreddit_id": subreddit_id, "phase": "start"},
        )

        # Scrape posts from Reddit
        posts = scrape_subreddit(subreddit_name, limit=50, max_age_hours=24)

        # Deduplicate globally by reddit_native_id across entire reddit_threads table
        existing_ids = set(
            row[0]
            for row in db.query(RedditThread.reddit_native_id).all()
        )
        new_posts = deduplicate_posts(posts, existing_ids)

        # Insert new RedditThread records with subreddit_id (no client_id)
        for post in new_posts:
            thread = RedditThread(
                subreddit_id=subreddit_uuid,
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
                is_locked=post.get("is_locked", False),
                scraped_at=datetime.now(timezone.utc),
            )
            db.add(thread)

        db.commit()

        # Update Subreddit.last_scraped_at
        sub_record.last_scraped_at = datetime.now(timezone.utc)

        # Record ScrapeLog with subreddit_id (nullable client_id)
        duration_ms = int((time.time() - start_time) * 1000)
        scrape_log = ScrapeLog(
            subreddit_id=subreddit_uuid,
            client_id=None,
            subreddit_name=subreddit_name,
            posts_found=len(posts),
            posts_new=len(new_posts),
            duration_ms=duration_ms,
            errors=None,
        )
        db.add(scrape_log)
        db.commit()

        # Record completion event
        message = f"Scraped r/{subreddit_name}: {len(posts)} found, {len(new_posts)} new ({duration_ms}ms)"
        metadata = {
            "subreddit_name": subreddit_name,
            "subreddit_id": subreddit_id,
            "posts_found": len(posts),
            "posts_new": len(new_posts),
            "duration_ms": duration_ms,
        }
        record_activity_event(db, "scrape", message, client_id=None, metadata=metadata)

        logger.info("scrape_subreddit_shared: %s", message)
        return {
            "status": "success",
            "subreddit": subreddit_name,
            "subreddit_id": subreddit_id,
            "posts_found": len(posts),
            "posts_new": len(new_posts),
            "duration_ms": duration_ms,
        }

    except Exception as e:
        error_str = str(e)

        # Update last_scraped_at even on failure so admin UI reflects the attempt
        try:
            db.rollback()
            sub_record = db.query(Subreddit).filter(Subreddit.id == subreddit_uuid).first()
            if sub_record:
                sub_record.last_scraped_at = datetime.now(timezone.utc)
                subreddit_name = sub_record.subreddit_name
            else:
                subreddit_name = "unknown"

            duration_ms = int((time.time() - start_time) * 1000)
            db.add(ScrapeLog(
                subreddit_id=subreddit_uuid,
                client_id=None,
                subreddit_name=subreddit_name,
                posts_found=0,
                posts_new=0,
                duration_ms=duration_ms,
                errors=error_str[:500],
            ))
            db.commit()
        except Exception as inner:
            logger.warning("scrape_subreddit_shared: failed to record error scrape_log: %s", inner)
            db.rollback()

        record_activity_event(
            db,
            "system",
            f"Shared scrape failed for r/{subreddit_name}: {error_str[:200]}",
            client_id=None,
            metadata={"subreddit_id": subreddit_id, "error": error_str[:500]},
        )
        logger.error("scrape_subreddit_shared: Failed for subreddit %s: %s", subreddit_id, e)
        return {"status": "error", "subreddit_id": subreddit_id, "error": error_str[:200]}

    finally:
        db.close()
