"""Celery tasks for Subreddit Risk Profile weekly batch.

Three tasks scheduled on Sundays (Asia/Jerusalem):
- extract_subreddit_rules_batch: 05:00 — Extract rules for all active subreddits
- compute_moderation_profiles_batch: 05:15 — Compute moderation profiles from deletion data
- compute_risk_scores_batch: 05:30 — Compute risk scores and update high_risk flags

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7
"""

import time

from app.database import SessionLocal
from app.logging_config import get_logger
from app.services.distributed_lock import DistributedLock
from app.services.transparency import record_activity_event
from app.tasks.worker import celery_app

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants (from design doc)
# ---------------------------------------------------------------------------

LOCK_KEY = "risk_profile_batch"
LOCK_TTL_SECONDS = 1800  # 30 minutes

CIRCUIT_BREAKER_THRESHOLD = 0.50  # >50% failures triggers pause
CIRCUIT_BREAKER_PAUSE_SECONDS = 120  # 120s pause on circuit breaker

SUBREDDIT_DELAY_SECONDS = 3  # 3s delay between subreddits (Reddit API rate limits)


# ---------------------------------------------------------------------------
# Helper: acquire distributed lock (Req 7.6, 7.7)
# ---------------------------------------------------------------------------


def _acquire_batch_lock() -> DistributedLock | None:
    """Acquire the distributed lock for risk profile batch.

    Returns the lock instance if acquired, None otherwise.
    """
    lock = DistributedLock(key=LOCK_KEY, ttl=LOCK_TTL_SECONDS)
    if lock.acquire():
        logger.info("RISK_PROFILE_BATCH | lock acquired (key=%s, TTL=%ds)", LOCK_KEY, LOCK_TTL_SECONDS)
        return lock

    logger.warning("RISK_PROFILE_BATCH | lock NOT acquired — another batch is running")
    return None


# ---------------------------------------------------------------------------
# Task 1: extract_subreddit_rules_batch (Sunday 05:00) — Req 7.1, 7.2, 7.3, 7.5
# ---------------------------------------------------------------------------


@celery_app.task(name="extract_subreddit_rules_batch")
def extract_subreddit_rules_batch():
    """Sunday 05:00 — Extract rules for all active subreddits.

    Acquires distributed lock, then delegates to refresh_all_subreddit_rules
    which handles sequential processing (3s delay), circuit breaker (>50% failures),
    and activity event logging.

    Requirements:
    - 7.1: Schedule as Celery Beat on Sunday 05:00
    - 7.2: On failure, log and continue processing remaining subreddits
    - 7.3: Process sequentially with 3s delay (Reddit API rate limits)
    - 7.4: Emit activity event on completion
    - 7.5: Circuit breaker: >50% failures → pause 120s then resume
    - 7.6: Acquire distributed lock TTL=1800s
    - 7.7: If lock not acquired, log warning and abort
    """
    from app.services.rule_extractor import refresh_all_subreddit_rules

    logger.info("RISK_PROFILE_BATCH | task=extract_subreddit_rules_batch | status=start")

    # Req 7.6: Acquire distributed lock
    lock = _acquire_batch_lock()
    if lock is None:
        # Req 7.7: Log warning and abort
        db = SessionLocal()
        try:
            record_activity_event(
                db=db,
                event_type="risk_profile_batch",
                message="Rule extraction batch aborted — distributed lock not acquired (another instance running)",
                metadata={"phase": "extract_rules", "status": "lock_not_acquired"},
            )
        finally:
            db.close()
        return {"status": "aborted", "reason": "lock_not_acquired"}

    db = SessionLocal()
    try:
        # Delegates to service which handles Req 7.2, 7.3, 7.4, 7.5
        result = refresh_all_subreddit_rules(db)
        logger.info(
            "RISK_PROFILE_BATCH | task=extract_subreddit_rules_batch | status=complete | result=%s",
            result,
        )
        return result
    except Exception as e:
        logger.error(
            "RISK_PROFILE_BATCH | task=extract_subreddit_rules_batch | error=%s",
            str(e)[:200],
        )
        try:
            record_activity_event(
                db=db,
                event_type="risk_profile_batch",
                message=f"Rule extraction batch failed with fatal error: {str(e)[:150]}",
                metadata={"phase": "extract_rules", "status": "fatal_error", "error": str(e)[:200]},
            )
        except Exception:
            pass
        return {"status": "error", "error": str(e)[:200]}
    finally:
        db.close()
        lock.release()


# ---------------------------------------------------------------------------
# Task 2: compute_moderation_profiles_batch (Sunday 05:15) — Req 7.1, 7.2, 7.4
# ---------------------------------------------------------------------------


@celery_app.task(name="compute_moderation_profiles_batch")
def compute_moderation_profiles_batch():
    """Sunday 05:15 — Compute moderation profiles from deletion data.

    Also computes daily stats for each subreddit.
    Updates SubredditRiskProfile.moderation_profile and confidence_level.

    Requirements:
    - 7.1: Schedule as Celery Beat on Sunday 05:15
    - 7.2: On failure, log and continue remaining subreddits
    - 7.4: Emit activity event on completion
    - 7.6: Acquire distributed lock TTL=1800s
    - 7.7: If lock not acquired, log warning and abort
    """
    from datetime import datetime, timezone

    from sqlalchemy import exists, and_

    from app.models.subreddit import ClientSubredditAssignment, Subreddit
    from app.models.subreddit_risk_profile import SubredditRiskProfile
    from app.services.moderation_profiler import (
        compute_daily_stats,
        compute_moderation_profile,
    )

    logger.info("RISK_PROFILE_BATCH | task=compute_moderation_profiles_batch | status=start")

    # Req 7.6: Acquire distributed lock
    lock = _acquire_batch_lock()
    if lock is None:
        # Req 7.7: Log warning and abort
        db = SessionLocal()
        try:
            record_activity_event(
                db=db,
                event_type="risk_profile_batch",
                message="Moderation profile batch aborted — distributed lock not acquired",
                metadata={"phase": "moderation_profiles", "status": "lock_not_acquired"},
            )
        finally:
            db.close()
        return {"status": "aborted", "reason": "lock_not_acquired"}

    db = SessionLocal()
    start_time = time.time()
    stats = {"processed": 0, "success": 0, "failures": 0}

    try:
        # Get all subreddits with active assignments (same query as rule_extractor)
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

        logger.info(
            "RISK_PROFILE_BATCH | task=compute_moderation_profiles_batch | subreddits=%d",
            len(subreddits),
        )

        for subreddit in subreddits:
            subreddit_name = subreddit.subreddit_name
            stats["processed"] += 1

            try:
                # Compute moderation profile
                profile_data = compute_moderation_profile(db, subreddit_name)

                # Get or create risk profile
                risk_profile = (
                    db.query(SubredditRiskProfile)
                    .filter(SubredditRiskProfile.subreddit_id == subreddit.id)
                    .first()
                )
                if not risk_profile:
                    risk_profile = SubredditRiskProfile(subreddit_id=subreddit.id)
                    db.add(risk_profile)
                    db.flush()

                # Update profile fields
                risk_profile.moderation_profile = {
                    "removal_rate": profile_data.removal_rate,
                    "aggressiveness": profile_data.aggressiveness,
                    "patterns": profile_data.patterns,
                    "total_posted": profile_data.total_posted,
                    "total_deleted": profile_data.total_deleted,
                }
                risk_profile.dangerous_hours = profile_data.dangerous_hours
                risk_profile.confidence_level = profile_data.confidence_level
                risk_profile.last_profile_computed_at = datetime.now(timezone.utc)

                db.commit()

                # Compute daily stats
                compute_daily_stats(db, subreddit_name)

                stats["success"] += 1

            except Exception as e:
                # Req 7.2: Log and continue
                db.rollback()
                stats["failures"] += 1
                logger.warning(
                    "RISK_PROFILE_BATCH | task=compute_moderation_profiles_batch | "
                    "subreddit=r/%s | error=%s",
                    subreddit_name,
                    str(e)[:200],
                )

        duration_seconds = int(time.time() - start_time)
        stats["duration_seconds"] = duration_seconds

        # Req 7.4: Emit activity event on completion
        record_activity_event(
            db=db,
            event_type="risk_profile_batch",
            message=(
                f"Moderation profile batch complete: {stats['success']}/{stats['processed']} succeeded, "
                f"{stats['failures']} failed, duration {duration_seconds}s"
            ),
            metadata={**stats, "phase": "moderation_profiles"},
        )

        logger.info(
            "RISK_PROFILE_BATCH | task=compute_moderation_profiles_batch | status=complete | stats=%s",
            stats,
        )
        return stats

    except Exception as e:
        logger.error(
            "RISK_PROFILE_BATCH | task=compute_moderation_profiles_batch | fatal_error=%s",
            str(e)[:200],
        )
        db.rollback()
        try:
            record_activity_event(
                db=db,
                event_type="risk_profile_batch",
                message=f"Moderation profile batch failed with fatal error: {str(e)[:150]}",
                metadata={"phase": "moderation_profiles", "status": "fatal_error", "error": str(e)[:200]},
            )
        except Exception:
            pass
        return {"status": "error", "error": str(e)[:200]}
    finally:
        db.close()
        lock.release()


# ---------------------------------------------------------------------------
# Task 3: compute_risk_scores_batch (Sunday 05:30) — Req 7.1, 7.4
# ---------------------------------------------------------------------------


@celery_app.task(name="compute_risk_scores_batch")
def compute_risk_scores_batch():
    """Sunday 05:30 — Compute risk scores and update high_risk flags.

    Emits risk_score_spike events when delta > 15.

    Requirements:
    - 7.1: Schedule as Celery Beat on Sunday 05:30
    - 7.4: Emit activity event on completion
    - 7.6: Acquire distributed lock TTL=1800s
    - 7.7: If lock not acquired, log warning and abort
    """
    from app.services.risk_scorer import refresh_all_risk_scores

    logger.info("RISK_PROFILE_BATCH | task=compute_risk_scores_batch | status=start")

    # Req 7.6: Acquire distributed lock
    lock = _acquire_batch_lock()
    if lock is None:
        # Req 7.7: Log warning and abort
        db = SessionLocal()
        try:
            record_activity_event(
                db=db,
                event_type="risk_profile_batch",
                message="Risk score batch aborted — distributed lock not acquired",
                metadata={"phase": "risk_scores", "status": "lock_not_acquired"},
            )
        finally:
            db.close()
        return {"status": "aborted", "reason": "lock_not_acquired"}

    db = SessionLocal()
    start_time = time.time()

    try:
        # refresh_all_risk_scores handles:
        # - Computing scores for all profiles
        # - Appending to history (FIFO 12 weeks)
        # - Emitting risk_score_spike events (Req 4.3)
        # - Setting/clearing is_high_risk (Req 4.6, 4.8)
        result = refresh_all_risk_scores(db)

        duration_seconds = int(time.time() - start_time)
        result["duration_seconds"] = duration_seconds

        # Req 7.4: Emit activity event on completion
        record_activity_event(
            db=db,
            event_type="risk_profile_batch",
            message=(
                f"Risk score batch complete: {result.get('processed', 0)} processed, "
                f"{result.get('spikes', 0)} spikes detected, "
                f"{result.get('high_risk_set', 0)} set high_risk, "
                f"{result.get('high_risk_cleared', 0)} cleared high_risk, "
                f"duration {duration_seconds}s"
            ),
            metadata={**result, "phase": "risk_scores"},
        )

        logger.info(
            "RISK_PROFILE_BATCH | task=compute_risk_scores_batch | status=complete | result=%s",
            result,
        )
        return result

    except Exception as e:
        logger.error(
            "RISK_PROFILE_BATCH | task=compute_risk_scores_batch | fatal_error=%s",
            str(e)[:200],
        )
        db.rollback()
        try:
            record_activity_event(
                db=db,
                event_type="risk_profile_batch",
                message=f"Risk score batch failed with fatal error: {str(e)[:150]}",
                metadata={"phase": "risk_scores", "status": "fatal_error", "error": str(e)[:200]},
            )
        except Exception:
            pass
        return {"status": "error", "error": str(e)[:200]}
    finally:
        db.close()
        lock.release()
