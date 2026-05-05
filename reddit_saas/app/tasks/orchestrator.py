"""Orchestrator tasks — run pipelines for all active clients/avatars.

Called by Celery Beat on schedule.
"""

import logging

from app.tasks.worker import celery_app
from app.database import SessionLocal
from app.models.client import Client
from app.models.avatar import Avatar

logger = logging.getLogger(__name__)


@celery_app.task(name="run_full_pipeline_all_clients")
def run_full_pipeline_all_clients():
    """Run score → generate for all active clients.

    Scraping is handled separately by the queue_tick task (continuous,
    priority-based). This task only processes already-scraped threads.
    """
    from app.tasks.ai_pipeline import score_threads, generate_comments

    db = SessionLocal()
    try:
        clients = db.query(Client).filter(Client.is_active.is_(True)).all()
        logger.info(f"Running AI pipeline (score+generate) for {len(clients)} active clients")

        for client in clients:
            cid = str(client.id)
            try:
                # Chain: score → generate (scraping removed — handled by queue_tick)
                chain = (
                    score_threads.si(cid)
                    | generate_comments.si(cid)
                )
                chain.apply_async()
                logger.info(f"AI pipeline queued for {client.client_name}")
            except Exception as e:
                logger.error(f"Failed to queue AI pipeline for {client.client_name}: {e}")

    finally:
        db.close()


@celery_app.task(name="run_hobby_pipeline_all_avatars")
def run_hobby_pipeline_all_avatars():
    """Run hobby scrape + comment generation for all active avatars."""
    from app.tasks.scraping import scrape_hobby_subreddits
    from app.tasks.ai_pipeline import generate_hobby_comments

    db = SessionLocal()
    try:
        avatars = db.query(Avatar).filter(Avatar.active.is_(True)).all()
        logger.info(f"Running hobby pipeline for {len(avatars)} active avatars")

        for avatar in avatars:
            aid = str(avatar.id)
            try:
                chain = (
                    scrape_hobby_subreddits.si(aid)
                    | generate_hobby_comments.si(aid)
                )
                chain.apply_async()
                logger.info(f"Hobby pipeline queued for {avatar.reddit_username}")
            except Exception as e:
                logger.error(f"Failed to queue hobby pipeline for {avatar.reddit_username}: {e}")

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
            health = get_avatar_health(db, avatar)

            # Auto-quarantine if brand ratio too high
            if not health["brand_ratio_ok"]:
                logger.warning(f"Avatar {avatar.reddit_username} brand ratio too high: {health['brand_ratio']}")
                # Don't quarantine, just log — human decides

            avatar.last_health_check = datetime.now(timezone.utc)
            db.commit()

        logger.info("Health check complete")

    finally:
        db.close()
