"""Orchestrator tasks — run pipelines for all active clients/avatars.

Called by Celery Beat on schedule.
"""

import logging

from app.tasks.worker import celery_app
from app.database import SessionLocal
from app.models.client import Client
from app.models.avatar import Avatar
from app.services.audit import log_system_action

logger = logging.getLogger(__name__)


@celery_app.task(name="run_full_pipeline_all_clients")
def run_full_pipeline_all_clients():
    """Run score → generate comments → generate posts for all active clients.

    Scraping is handled separately by the queue_tick task (continuous,
    priority-based). This task only processes already-scraped threads.
    """
    from app.tasks.ai_pipeline import score_threads, generate_comments, generate_posts

    db = SessionLocal()
    try:
        clients = db.query(Client).filter(Client.is_active.is_(True)).all()
        logger.info(f"Running AI pipeline (score+generate) for {len(clients)} active clients")

        try:
            log_system_action(
                db,
                action="pipeline_run_started",
                entity_type="pipeline",
                details={"client_count": len(clients)},
            )
        except Exception as e:
            logger.error(f"Failed to log pipeline_run_started audit entry: {e}")

        for client in clients:
            cid = str(client.id)
            try:
                # Chain: score → generate comments → generate posts
                chain = (
                    score_threads.si(cid, triggered_by="orchestrator")
                    | generate_comments.si(cid, triggered_by="orchestrator")
                    | generate_posts.si(cid, triggered_by="orchestrator")
                )
                chain.apply_async()
                logger.info(f"AI pipeline queued for {client.client_name}")
            except Exception as e:
                logger.error(f"Failed to queue AI pipeline for {client.client_name}: {e}")

        try:
            log_system_action(
                db,
                action="pipeline_run_completed",
                entity_type="pipeline",
                details={
                    "client_count": len(clients),
                    "clients_queued": [c.client_name for c in clients],
                },
            )
        except Exception as e:
            logger.error(f"Failed to log pipeline_run_completed audit entry: {e}")

    finally:
        db.close()


@celery_app.task(name="run_hobby_pipeline_all_avatars")
def run_hobby_pipeline_all_avatars():
    """Run hobby scrape + comment generation for all active avatars."""
    from app.tasks.scraping import scrape_hobby_subreddits
    from app.tasks.ai_pipeline import generate_hobby_comments

    db = SessionLocal()
    try:
        avatars = (
            db.query(Avatar)
            .filter(
                Avatar.active.is_(True),
                Avatar.is_shadowbanned.is_(False),
                Avatar.is_frozen.is_(False),
                Avatar.health_status.notin_(("shadowbanned", "suspended")),
                Avatar.warming_phase != 0,  # Mentor — excluded from pipelines
            )
            .all()
        )
        logger.info(f"Running hobby pipeline for {len(avatars)} active non-shadowbanned avatars")

        for avatar in avatars:
            aid = str(avatar.id)
            try:
                chain = (
                    scrape_hobby_subreddits.si(aid)
                    | generate_hobby_comments.si(aid, triggered_by="orchestrator")
                )
                chain.apply_async()
                logger.info(f"Hobby pipeline queued for {avatar.reddit_username}")
            except Exception as e:
                logger.error(f"Failed to queue hobby pipeline for {avatar.reddit_username}: {e}")

        try:
            log_system_action(
                db,
                action="hobby_pipeline_run",
                entity_type="pipeline",
                details={"avatar_count": len(avatars)},
            )
        except Exception as e:
            logger.error(f"Failed to log hobby_pipeline_run audit entry: {e}")

    finally:
        db.close()


@celery_app.task(name="check_all_avatars_health")
def check_all_avatars_health():
    """Check health of all active avatars — shadowban detection, karma update."""
    db = SessionLocal()
    try:
        from app.services.safety import get_avatar_health, quarantine_avatar
        from datetime import datetime, timezone

        avatars = db.query(Avatar).filter(Avatar.active.is_(True)).all()
        logger.info(f"Health check for {len(avatars)} avatars")

        for avatar in avatars:
            try:
                health = get_avatar_health(db, avatar)

                # Auto-quarantine if brand ratio too high
                if not health["brand_ratio_ok"]:
                    logger.warning(f"Avatar {avatar.reddit_username} brand ratio too high: {health['brand_ratio']}")
                    # Don't quarantine, just log — human decides

                avatar.last_health_check = datetime.now(timezone.utc)
                db.commit()
            except Exception as e:
                logger.error(f"Health check failed for avatar {avatar.reddit_username}: {e}")
                db.rollback()
                continue

        logger.info("Health check complete")

    except Exception as e:
        logger.error(f"Health check task failed: {e}")
    finally:
        db.close()


@celery_app.task(name="check_avatar_shadowban_status")
def check_avatar_shadowban_status():
    """Check Reddit account status for all active avatars — shadowban/suspension detection.

    Runs BEFORE the AI pipeline (scheduled 30 min before scoring) so that
    shadowbanned avatars are flagged and excluded from expensive LLM calls.

    Cost savings: each shadowbanned avatar skipped saves ~$0.06/thread
    (persona selection $0.02 + generation $0.04) × 15 threads/day = ~$0.90/day per avatar.

    Uses reddit_status.py which:
    - Calls Reddit API to check account existence/suspension
    - Updates avatar.is_shadowbanned + avatar.reddit_status
    - Writes audit log on state change
    - Syncs subreddit karma via karma_tracker
    """
    db = SessionLocal()
    try:
        from app.services.reddit_status import check_all_reddit_statuses
        from datetime import datetime, timezone, timedelta

        # Only check avatars that haven't been checked in the last 6 hours
        # (avoids redundant API calls if task runs more frequently)
        stale_threshold = datetime.now(timezone.utc) - timedelta(hours=6)

        avatars = (
            db.query(Avatar)
            .filter(
                Avatar.active.is_(True),
                Avatar.is_frozen.is_(False),
            )
            .filter(
                (Avatar.reddit_status_checked_at.is_(None))
                | (Avatar.reddit_status_checked_at < stale_threshold)
            )
            .all()
        )

        if not avatars:
            logger.info("check_avatar_shadowban_status: all avatars recently checked, skipping")
            return {"checked": 0, "skipped_fresh": True}

        logger.info(
            f"check_avatar_shadowban_status: checking {len(avatars)} avatars "
            f"(stale_threshold={stale_threshold.isoformat()})"
        )

        results = check_all_reddit_statuses(db, avatars, delay_seconds=2.0)

        # Summary
        suspended = [r for r in results if r["status"] == "suspended"]
        if suspended:
            logger.warning(
                "SHADOWBAN_DETECTED | count=%d | usernames=%s",
                len(suspended),
                [r["username"] for r in suspended],
            )

        return {
            "checked": len(results),
            "active": sum(1 for r in results if r["status"] == "active"),
            "suspended": len(suspended),
            "not_found": sum(1 for r in results if r["status"] == "not_found"),
            "errors": sum(1 for r in results if r["status"] == "error"),
        }

    except Exception as e:
        logger.error(f"check_avatar_shadowban_status failed: {e}")
        return {"error": str(e)}
    finally:
        db.close()
