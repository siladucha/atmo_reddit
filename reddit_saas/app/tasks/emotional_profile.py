"""Celery tasks for Subreddit Emotional Profile.

- refresh_subreddit_emotional_profiles: Weekly refresh (Sunday 04:30)
- analyze_subreddit_emotional_profile: On-demand single subreddit analysis
- recompute_all_compatibility: After profile refresh, update compatibility scores
"""

import time

from app.database import SessionLocal
from app.logging_config import get_logger
from app.tasks.worker import celery_app

logger = get_logger(__name__)


@celery_app.task(name="analyze_subreddit_emotional_profile", bind=True, max_retries=1)
def analyze_subreddit_emotional_profile(self, subreddit_name: str):
    """On-demand: analyze a single subreddit's emotional profile.

    Dispatched from admin UI "Run Analysis" / "Refresh Profile" button.
    """
    from app.services.emotional_profile import analyze_subreddit_profile

    db = SessionLocal()
    try:
        result = analyze_subreddit_profile(db, subreddit_name)
        if "error" in result:
            logger.warning(
                "EP_TASK | sub=r/%s | error=%s", subreddit_name, result["error"]
            )
        else:
            logger.info(
                "EP_TASK | sub=r/%s | confidence=%s | done",
                subreddit_name, result.get("confidence"),
            )
        return result
    except Exception as e:
        logger.error("EP_TASK | sub=r/%s | exception=%s", subreddit_name, str(e)[:200])
        raise self.retry(exc=e, countdown=30)
    finally:
        db.close()


@celery_app.task(name="refresh_subreddit_emotional_profiles")
def refresh_subreddit_emotional_profiles():
    """Weekly task: refresh emotional profiles for all active subreddits.

    Schedule: Sunday 04:30 (Israel time, low-traffic).
    Sequential processing with 5s delay between subreddits.
    """
    from sqlalchemy import exists, and_

    from app.models.subreddit import ClientSubredditAssignment, Subreddit
    from app.services.emotional_profile import analyze_subreddit_profile

    db = SessionLocal()
    try:
        # Get all subreddits with at least one active assignment
        subreddits = (
            db.query(Subreddit)
            .filter(
                Subreddit.is_active == True,
                exists().where(
                    and_(
                        ClientSubredditAssignment.subreddit_id == Subreddit.id,
                        ClientSubredditAssignment.is_active == True,
                    )
                ),
            )
            .all()
        )

        stats = {"refreshed": 0, "skipped": 0, "failed": 0, "pauses": 0}
        consecutive_errors = 0

        for subreddit in subreddits:
            # Circuit breaker: 5 pauses → abandon
            if stats["pauses"] >= 5:
                logger.error("EP_REFRESH | abandoning after 5 pauses")
                break

            try:
                result = analyze_subreddit_profile(db, subreddit.subreddit_name)
                if "error" in result:
                    stats["failed"] += 1
                    consecutive_errors += 1
                else:
                    stats["refreshed"] += 1
                    consecutive_errors = 0
            except Exception as e:
                stats["failed"] += 1
                consecutive_errors += 1
                logger.warning(
                    "EP_REFRESH | sub=r/%s | error=%s",
                    subreddit.subreddit_name, str(e)[:100],
                )

            # 3 consecutive errors → pause 60s
            if consecutive_errors >= 3:
                stats["pauses"] += 1
                consecutive_errors = 0
                logger.warning("EP_REFRESH | pausing 60s after 3 errors")
                time.sleep(60)

            # Rate limit delay between subreddits
            time.sleep(5)

        # After all profiles refreshed, recompute compatibility
        if stats["refreshed"] > 0:
            recompute_all_compatibility.delay()

        # Log completion
        from app.models.activity_event import ActivityEvent
        event = ActivityEvent(
            event_type="emotional_profile_refresh_completed",
            message=(
                f"Emotional profile refresh: {stats['refreshed']} refreshed, "
                f"{stats['skipped']} skipped, {stats['failed']} failed"
            ),
            event_metadata=stats,
        )
        db.add(event)
        db.commit()

        logger.info("EP_REFRESH | complete | stats=%s", stats)
        return stats

    except Exception as e:
        logger.error("EP_REFRESH | fatal error=%s", str(e)[:200])
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()


@celery_app.task(name="recompute_all_compatibility")
def recompute_all_compatibility():
    """Recompute compatibility scores for all active avatar-subreddit pairs.

    Called after profile refresh to ensure scores reflect updated profiles.
    """
    from app.models.avatar import Avatar
    from app.services.emotional_profile import compute_all_compatibility_for_avatar

    db = SessionLocal()
    try:
        # Get all active, non-frozen avatars with voice profiles
        avatars = (
            db.query(Avatar)
            .filter(
                Avatar.active == True,
                Avatar.is_frozen == False,
                Avatar.voice_profile_md.isnot(None),
            )
            .all()
        )

        stats = {"avatars_processed": 0, "scores_computed": 0}

        for avatar in avatars:
            try:
                results = compute_all_compatibility_for_avatar(db, avatar)
                stats["avatars_processed"] += 1
                stats["scores_computed"] += len(results)
            except Exception as e:
                logger.warning(
                    "EP_COMPAT_ALL | avatar=%s | error=%s",
                    avatar.reddit_username, str(e)[:100],
                )

            time.sleep(1)  # Gentle rate limiting on LLM calls

        logger.info("EP_COMPAT_ALL | complete | stats=%s", stats)
        return stats

    except Exception as e:
        logger.error("EP_COMPAT_ALL | fatal error=%s", str(e)[:200])
        return {"error": str(e)}
    finally:
        db.close()
