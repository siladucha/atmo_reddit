"""Celery task: probe_subreddit_bans — weekly auto-unban check.

Probes all active per-subreddit bans to check if they've been lifted.
Uses unauthenticated PRAW client to verify comment visibility.

Schedule: Weekly (Sunday 03:45) — after karma tracking, before discovery.
"""

from celery import shared_task

from app.database import SessionLocal
from app.logging_config import get_logger

logger = get_logger(__name__)


@shared_task(name="probe_subreddit_bans")
def probe_subreddit_bans():
    """Probe all active subreddit bans to detect unbans.

    Returns dict with probe stats.
    """
    from app.services.subreddit_ban import get_bans_due_for_probe, probe_single_ban

    db = SessionLocal()
    try:
        bans = get_bans_due_for_probe(db)

        if not bans:
            logger.info("probe_subreddit_bans: no bans due for probing")
            return {"probed": 0, "lifted": 0, "still_banned": 0, "errors": 0}

        stats = {"probed": 0, "lifted": 0, "still_banned": 0, "errors": 0, "no_comments": 0}

        for ban in bans:
            try:
                result = probe_single_ban(db, ban)
                stats["probed"] += 1

                if result == "accessible":
                    stats["lifted"] += 1
                elif result == "still_banned":
                    stats["still_banned"] += 1
                elif result == "no_comments":
                    stats["no_comments"] += 1
                else:
                    stats["errors"] += 1

            except Exception as e:
                stats["errors"] += 1
                logger.error(
                    "probe_subreddit_bans: error probing ban %s: %s",
                    ban.id, str(e)[:200],
                )
                db.rollback()

        logger.info(
            "probe_subreddit_bans complete: probed=%d lifted=%d still_banned=%d errors=%d",
            stats["probed"], stats["lifted"], stats["still_banned"], stats["errors"],
        )
        return stats

    except Exception as e:
        logger.error("probe_subreddit_bans failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()
