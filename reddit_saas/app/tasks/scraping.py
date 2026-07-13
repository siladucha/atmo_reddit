"""Celery tasks for Reddit scraping.

TODO(pipeline-v2): Add scrape freshness gate (R8) — check min_scrape_interval_minutes
before each subreddit scrape. See Sprint 1, Task 1.2.
"""

from app.logging_config import get_logger
import time
import uuid
from datetime import datetime, timezone

from prawcore.exceptions import Forbidden, NotFound

from app.tasks.worker import celery_app
from app.database import SessionLocal
from app.models.client import Client
from app.models.scrape_log import ScrapeLog
from app.models.subreddit import ClientSubreddit, Subreddit
from app.models.thread import RedditThread
from app.services.audit import log_system_action
from app.services.reddit import scrape_subreddit, deduplicate_posts
from app.services.transparency import record_activity_event

logger = get_logger(__name__)


@celery_app.task(name="scrape_professional_subreddits")
def scrape_professional_subreddits(client_id: str):
    """Scrape all professional subreddits for a client."""
    db = SessionLocal()
    try:
        client = db.query(Client).filter(Client.id == client_id).first()
        if not client:
            logger.error(f"Client {client_id} not found")
            return
        if not client.is_active:
            logger.info(f"scrape_professional: client {client.client_name} is deactivated, skipping")
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

                # --- Freshness gate (R8): skip if scraped too recently ---
                from app.services.settings import get_setting_int
                min_interval = get_setting_int(db, "min_scrape_interval_minutes", 30)
                last_scraped = sub.last_scraped_at or subreddit_record.last_scraped_at
                if last_scraped is not None:
                    elapsed_minutes = (datetime.now(timezone.utc) - last_scraped).total_seconds() / 60
                    if elapsed_minutes < min_interval:
                        logger.info(
                            "scrape_professional: r/%s scraped %.1f min ago, skipping (threshold: %d)",
                            sub.subreddit_name, elapsed_minutes, min_interval,
                        )
                        continue

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
                        reddit_created_at=datetime.fromtimestamp(post["created_utc"], tz=timezone.utc) if post.get("created_utc") else None,
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

        # Fallback: Phase 0-1 avatars with no hobby subs get default starter subs
        if not hobby_sub_names and avatar.warming_phase <= 1:
            from app.services.sanitize import DEFAULT_PHASE1_HOBBY_SUBREDDITS
            hobby_sub_names = list(DEFAULT_PHASE1_HOBBY_SUBREDDITS)
            logger.info(
                f"scrape_hobby_subreddits: avatar {avatar.reddit_username} has no hobby subs, "
                f"using Phase 1 defaults: {hobby_sub_names}"
            )

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
                        "avatar_id": str(avatar.id),
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


@celery_app.task(name="scrape_hobby_all_avatars")
def scrape_hobby_all_avatars():
    """Discovery: scrape hobby subreddits for all eligible avatars.

    Pure data supply — no generation, no budget decisions.
    Populates HobbySubreddit table so EPG has an opportunity pool to evaluate.
    """
    db = SessionLocal()
    try:
        from app.models.avatar import Avatar
        from app.services.settings import is_scrape_enabled

        if not is_scrape_enabled(db):
            logger.info("scrape_hobby_all_avatars: scrape_enabled=false, skipping")
            return {"status": "skipped", "reason": "scrape_disabled"}

        avatars = (
            db.query(Avatar)
            .filter(
                Avatar.active.is_(True),
                Avatar.is_frozen.is_(False),
                Avatar.warming_phase >= 0,  # Phase 0 (Incubation) included — needs hobby posts for 1/day budget
                Avatar.health_status.notin_(("shadowbanned", "suspended")),
            )
            .all()
        )

        logger.info("Hobby discovery scrape: %d eligible avatars", len(avatars))
        total_new = 0
        errors = 0

        for avatar in avatars:
            try:
                count = scrape_hobby_subreddits(str(avatar.id))
                total_new += (count or 0)
            except Exception as e:
                logger.error("Hobby scrape failed for %s: %s", avatar.reddit_username, str(e)[:100])
                errors += 1

        logger.info("Hobby discovery complete: %d new posts, %d errors", total_new, errors)
        return {"scraped_avatars": len(avatars), "new_posts": total_new, "errors": errors}

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

        # --- Freshness gate (R8): skip if scraped too recently ---
        from app.services.settings import get_setting_int
        min_interval = get_setting_int(db, "min_scrape_interval_minutes", 30)

        if sub_record.last_scraped_at is not None:
            elapsed_minutes = (datetime.now(timezone.utc) - sub_record.last_scraped_at).total_seconds() / 60
            if elapsed_minutes < min_interval:
                logger.info(
                    "scrape_subreddit_shared: r/%s scraped %.1f min ago (threshold: %d min), skipping",
                    subreddit_name, elapsed_minutes, min_interval,
                )
                record_activity_event(
                    db,
                    "scrape_too_fresh",
                    f"Skipped r/{subreddit_name}: scraped {int(elapsed_minutes)} min ago (min interval: {min_interval} min)",
                    client_id=None,
                    metadata={
                        "subreddit_name": subreddit_name,
                        "subreddit_id": subreddit_id,
                        "elapsed_minutes": round(elapsed_minutes, 1),
                        "threshold_minutes": min_interval,
                        "last_scraped_at": sub_record.last_scraped_at.isoformat(),
                    },
                )
                return {
                    "status": "skipped",
                    "reason": "scrape_too_fresh",
                    "subreddit": subreddit_name,
                    "elapsed_minutes": round(elapsed_minutes, 1),
                    "threshold_minutes": min_interval,
                }

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
                reddit_created_at=datetime.fromtimestamp(post["created_utc"], tz=timezone.utc) if post.get("created_utc") else None,
            )
            db.add(thread)

        db.commit()

        # Update Subreddit.last_scraped_at + reset failure counter on success
        sub_record.last_scraped_at = datetime.now(timezone.utc)
        if sub_record.consecutive_failures > 0:
            sub_record.consecutive_failures = 0

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

        # Audit log for admin audit logs page
        try:
            log_system_action(
                db,
                action="scrape_completed",
                entity_type="subreddit",
                entity_id=subreddit_uuid,
                details={
                    "subreddit_name": subreddit_name,
                    "posts_found": len(posts),
                    "posts_new": len(new_posts),
                    "duration_ms": duration_ms,
                },
            )
        except Exception as audit_err:
            logger.warning("scrape_subreddit_shared: failed to write audit log: %s", audit_err)

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

        # Classify error: permanent (403/404) vs transient
        is_permanent = isinstance(e, (Forbidden, NotFound))
        if is_permanent:
            if isinstance(e, Forbidden):
                disable_reason = f"Subreddit returned 403 Forbidden (private, quarantined, or banned): {error_str[:150]}"
            else:
                disable_reason = f"Subreddit returned 404 Not Found (deleted or never existed): {error_str[:150]}"

        # Update last_scraped_at even on failure so admin UI reflects the attempt
        try:
            db.rollback()
            sub_record = db.query(Subreddit).filter(Subreddit.id == subreddit_uuid).first()
            if sub_record:
                sub_record.last_scraped_at = datetime.now(timezone.utc)
                subreddit_name = sub_record.subreddit_name

                if is_permanent:
                    # Immediate disable — no point retrying private/deleted subreddits
                    sub_record.is_active = False
                    sub_record.consecutive_failures = (sub_record.consecutive_failures or 0) + 1
                    sub_record.disabled_reason = disable_reason
                    sub_record.disabled_at = datetime.now(timezone.utc)
                    logger.warning(
                        "scrape_subreddit_shared: IMMEDIATE DISABLE r/%s — %s",
                        subreddit_name, disable_reason[:100],
                    )
                else:
                    # --- Consecutive failure tracking + auto-disable ---
                    sub_record.consecutive_failures = (sub_record.consecutive_failures or 0) + 1
                    from app.services.settings import get_setting_int
                    max_failures = get_setting_int(db, "scrape_max_consecutive_failures", 5)

                    if sub_record.consecutive_failures >= max_failures:
                        sub_record.is_active = False
                        sub_record.disabled_reason = f"Auto-disabled after {sub_record.consecutive_failures} consecutive failures. Last error: {error_str[:200]}"
                        sub_record.disabled_at = datetime.now(timezone.utc)
                        logger.warning(
                            "scrape_subreddit_shared: AUTO-DISABLED r/%s after %d consecutive failures (error: %s)",
                            subreddit_name, sub_record.consecutive_failures, error_str[:100],
                        )
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

        # Emit activity event — include failure count and auto-disable status
        was_disabled = False
        try:
            sub_check = db.query(Subreddit).filter(Subreddit.id == subreddit_uuid).first()
            failure_count = sub_check.consecutive_failures if sub_check else 0
            was_disabled = sub_check and not sub_check.is_active and sub_check.disabled_reason
        except Exception:
            failure_count = 0

        event_type = "scrape_auto_disabled" if was_disabled else "scrape_failed"
        event_msg = (
            f"Auto-disabled r/{subreddit_name} after {failure_count} consecutive failures: {error_str[:150]}"
            if was_disabled
            else f"Shared scrape failed for r/{subreddit_name} (failure #{failure_count}): {error_str[:150]}"
        )
        record_activity_event(
            db,
            event_type,
            event_msg,
            client_id=None,
            metadata={
                "subreddit_id": subreddit_id,
                "subreddit_name": subreddit_name,
                "error": error_str[:500],
                "consecutive_failures": failure_count,
                "auto_disabled": was_disabled,
                "permanent_error": is_permanent,
            },
        )

        # Audit log for admin audit logs page
        try:
            log_system_action(
                db,
                action="scrape_failed",
                entity_type="subreddit",
                entity_id=subreddit_uuid,
                details={
                    "subreddit_name": subreddit_name,
                    "error": error_str[:500],
                },
            )
        except Exception as audit_err:
            logger.warning("scrape_subreddit_shared: failed to write failure audit log: %s", audit_err)

        logger.error("scrape_subreddit_shared: Failed for subreddit %s: %s", subreddit_id, e)
        return {"status": "error", "subreddit_id": subreddit_id, "error": error_str[:200]}

    finally:
        db.close()


@celery_app.task(name="scrape_repurpose_all_subreddits")
def scrape_repurpose_all_subreddits() -> dict:
    """Scrape evergreen top posts (high upvotes, 1-3 years old) from all active subreddits.

    Repurpose mode: finds high-engagement threads that still receive organic
    traffic via Google/Reddit search. These are ideal for late comments that
    get visibility without competing with fresh content.

    Runs weekly (low frequency). Uses sort=top, time_filter=year, min_score threshold.
    Skips locked threads. Deduplicates globally.

    Returns:
        Status dict with total results across all subreddits.
    """
    db = SessionLocal()
    try:
        from app.services.settings import is_scrape_enabled, get_setting_int
        if not is_scrape_enabled(db):
            logger.info("scrape_repurpose: scrape_enabled=false, skipping")
            return {"status": "paused"}

        # Configuration
        min_score = get_setting_int(db, "repurpose_min_score", 50)
        limit_per_sub = get_setting_int(db, "repurpose_limit_per_sub", 25)

        # Get all active subreddits (from client assignments)
        from app.models.subreddit import Subreddit, ClientSubredditAssignment
        active_subs = (
            db.query(Subreddit)
            .join(ClientSubredditAssignment, ClientSubredditAssignment.subreddit_id == Subreddit.id)
            .join(Client, Client.id == ClientSubredditAssignment.client_id)
            .filter(
                Subreddit.is_active.is_(True),
                ClientSubredditAssignment.is_active.is_(True),
                Client.is_active.is_(True),
            )
            .distinct()
            .all()
        )

        if not active_subs:
            logger.info("scrape_repurpose: no active subreddits found")
            return {"status": "no_subreddits"}

        # Global dedup set
        existing_ids = set(
            row[0]
            for row in db.query(RedditThread.reddit_native_id).all()
        )

        total_found = 0
        total_new = 0
        subs_processed = 0
        errors = []

        for sub in active_subs:
            try:
                start = time.time()
                posts = scrape_subreddit(
                    sub.subreddit_name,
                    limit=limit_per_sub,
                    max_age_hours=0,  # No age filter — we want old posts
                    sort="top",
                    time_filter="year",
                    min_score=min_score,
                )

                new_posts = deduplicate_posts(posts, existing_ids)

                for post in new_posts:
                    thread = RedditThread(
                        subreddit_id=sub.id,
                        type="repurpose",
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
                        reddit_created_at=datetime.fromtimestamp(post["created_utc"], tz=timezone.utc) if post.get("created_utc") else None,
                    )
                    db.add(thread)
                    existing_ids.add(post["reddit_native_id"])

                db.commit()

                duration_ms = int((time.time() - start) * 1000)
                total_found += len(posts)
                total_new += len(new_posts)
                subs_processed += 1

                # Record scrape log
                scrape_log = ScrapeLog(
                    subreddit_id=sub.id,
                    client_id=None,
                    subreddit_name=sub.subreddit_name,
                    posts_found=len(posts),
                    posts_new=len(new_posts),
                    duration_ms=duration_ms,
                    errors=None,
                )
                db.add(scrape_log)
                db.commit()

                if new_posts:
                    logger.info(
                        "scrape_repurpose: r/%s — %d found, %d new (min_score=%d, top/year)",
                        sub.subreddit_name, len(posts), len(new_posts), min_score,
                    )

            except Exception as e:
                logger.error("scrape_repurpose: failed for r/%s: %s", sub.subreddit_name, e)
                errors.append({"subreddit": sub.subreddit_name, "error": str(e)[:200]})
                db.rollback()
                continue

        # Record activity event
        try:
            message = (
                f"Repurpose scrape complete: {subs_processed} subs, "
                f"{total_found} found, {total_new} new (min_score={min_score})"
            )
            metadata = {
                "subs_processed": subs_processed,
                "total_found": total_found,
                "total_new": total_new,
                "min_score": min_score,
                "time_filter": "year",
                "errors": len(errors),
            }
            record_activity_event(db, "scrape", message, client_id=None, metadata=metadata)
        except Exception:
            pass

        # Audit log
        try:
            log_system_action(
                db,
                action="repurpose_scrape_completed",
                entity_type="system",
                details={
                    "subs_processed": subs_processed,
                    "total_found": total_found,
                    "total_new": total_new,
                    "min_score": min_score,
                    "errors": errors[:5],
                },
            )
        except Exception:
            pass

        logger.info(
            "scrape_repurpose: DONE — %d subs, %d found, %d new, %d errors",
            subs_processed, total_found, total_new, len(errors),
        )
        return {
            "status": "success",
            "subs_processed": subs_processed,
            "total_found": total_found,
            "total_new": total_new,
            "errors": len(errors),
        }

    finally:
        db.close()
