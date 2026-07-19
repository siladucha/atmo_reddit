"""Celery task: Daily Subreddit Intelligence Refresh.

Runs daily at 07:00 (before EPG build at 08:15). Ensures every subreddit
that will be used in today's generation has fresh emotional profile + rules.

Two-pass approach:
1. Check which subs are stale (emotional analyzed_at > threshold OR risk next_check_at passed)
2. Refresh stale subs: rules extraction + emotional profile + risk score recompute

Cost: ~$0.003/sub (Gemini Flash). Typically 5-15 subs/day.
Time: ~5-8 min for 15 subs (3s delay between Reddit API calls).

Notifications: Telegram + admin bell if critical sub cannot be refreshed.
Audit: ActivityEvent for every run + per-sub results.
AI Cost: log_ai_usage for every LLM call (already in sub-services).
"""

import time
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.logging_config import get_logger
from app.services.distributed_lock import DistributedLock
from app.tasks.worker import celery_app

logger = get_logger(__name__)

LOCK_KEY = "subreddit_intelligence_daily"
LOCK_TTL = 1800  # 30 min

# Freshness thresholds
EMOTIONAL_STALE_DAYS = 7  # re-analyze emotional if older than 7 days
SUBREDDIT_DELAY_SECONDS = 3  # Reddit API rate limit


@celery_app.task(name="refresh_subreddit_intelligence_daily")
def refresh_subreddit_intelligence_daily():
    """Daily 07:00 — refresh stale subreddit intelligence before EPG generation.

    Checks all active subreddits used by active avatars. For each stale sub:
    1. Extract rules (if risk profile next_check_at passed)
    2. Analyze emotional profile (if analyzed_at > 7 days)
    3. Recompute risk scores

    Sends Telegram alert if any sub fails refresh and is high-risk or heavily used.
    """
    lock = DistributedLock(key=LOCK_KEY, ttl=LOCK_TTL)
    if not lock.acquire():
        logger.info("SUBREDDIT_INTEL | lock not acquired — another run in progress")
        return {"status": "skipped", "reason": "lock_not_acquired"}

    db = SessionLocal()
    start_time = time.time()

    try:
        from sqlalchemy import or_, exists, and_, func as sqlfunc

        from app.models.subreddit import ClientSubredditAssignment, Subreddit
        from app.models.subreddit_risk_profile import SubredditRiskProfile
        from app.services.emotional_profile import analyze_subreddit_profile
        from app.services.moderation_profiler import compute_moderation_profile, compute_daily_stats
        from app.services.ops_notifications import notify_ops
        from app.services.risk_scorer import refresh_all_risk_scores
        from app.services.rule_extractor import extract_rules_for_subreddit
        from app.services.transparency import record_activity_event

        now = datetime.now(timezone.utc)
        emotional_threshold = now - timedelta(days=EMOTIONAL_STALE_DAYS)

        # Get all active subreddits with at least one active assignment
        active_sub_ids = (
            db.query(ClientSubredditAssignment.subreddit_id)
            .filter(ClientSubredditAssignment.is_active.is_(True))
            .distinct()
            .subquery()
        )

        all_active_subs = (
            db.query(Subreddit)
            .filter(
                Subreddit.id.in_(active_sub_ids),
                Subreddit.is_active.is_(True),
            )
            .all()
        )

        # Determine which subs need refresh
        subs_needing_emotional = []
        subs_needing_rules = []

        for sub in all_active_subs:
            # Emotional profile stale?
            if (
                sub.emotional_profile_analyzed_at is None
                or sub.emotional_profile_analyzed_at < emotional_threshold
            ):
                subs_needing_emotional.append(sub)

            # Risk profile rules stale? (check next_check_at)
            risk_profile = (
                db.query(SubredditRiskProfile)
                .filter(SubredditRiskProfile.subreddit_id == sub.id)
                .first()
            )
            if risk_profile is None:
                # No profile at all → needs creation + analysis
                subs_needing_rules.append(sub)
            elif risk_profile.next_check_at is None or risk_profile.next_check_at <= now:
                subs_needing_rules.append(sub)

        # Deduplicate: process each sub once
        subs_to_process = set()
        for s in subs_needing_emotional:
            subs_to_process.add(s.id)
        for s in subs_needing_rules:
            subs_to_process.add(s.id)

        total_stale = len(subs_to_process)

        if total_stale == 0:
            logger.info("SUBREDDIT_INTEL | all subs fresh — nothing to do")
            record_activity_event(
                db=db,
                event_type="subreddit_intelligence_daily",
                message="All subreddits have fresh intelligence — no refresh needed",
                metadata={"total_active": len(all_active_subs), "stale": 0},
            )
            db.commit()
            return {
                "status": "ok",
                "total_active": len(all_active_subs),
                "stale": 0,
                "refreshed": 0,
            }

        logger.info(
            "SUBREDDIT_INTEL | total_active=%d | stale=%d (emotional=%d, rules=%d) | starting refresh",
            len(all_active_subs),
            total_stale,
            len(subs_needing_emotional),
            len(subs_needing_rules),
        )

        # Process stale subs
        stats = {
            "total_active": len(all_active_subs),
            "stale": total_stale,
            "emotional_refreshed": 0,
            "rules_refreshed": 0,
            "errors": 0,
            "failed_subs": [],
        }

        emotional_ids = {s.id for s in subs_needing_emotional}
        rules_ids = {s.id for s in subs_needing_rules}

        # Build a map of subs to process
        subs_map = {s.id: s for s in all_active_subs}

        for sub_id in subs_to_process:
            sub = subs_map.get(sub_id)
            if not sub:
                continue

            sub_name = sub.subreddit_name

            # --- Rules refresh ---
            if sub_id in rules_ids:
                try:
                    extract_rules_for_subreddit(db, sub_name)
                    # Compute moderation profile
                    profile_data = compute_moderation_profile(db, sub_name)
                    risk_profile = (
                        db.query(SubredditRiskProfile)
                        .filter(SubredditRiskProfile.subreddit_id == sub.id)
                        .first()
                    )
                    if risk_profile:
                        risk_profile.moderation_profile = {
                            "removal_rate": profile_data.removal_rate,
                            "aggressiveness": profile_data.aggressiveness,
                            "patterns": profile_data.patterns,
                            "total_posted": profile_data.total_posted,
                            "total_deleted": profile_data.total_deleted,
                        }
                        risk_profile.dangerous_hours = profile_data.dangerous_hours
                        risk_profile.confidence_level = profile_data.confidence_level
                        risk_profile.last_profile_computed_at = now
                    db.commit()
                    compute_daily_stats(db, sub_name)
                    stats["rules_refreshed"] += 1
                except Exception as e:
                    db.rollback()
                    stats["errors"] += 1
                    stats["failed_subs"].append(sub_name)
                    logger.warning(
                        "SUBREDDIT_INTEL | rules refresh failed | sub=r/%s | error=%s",
                        sub_name, str(e)[:150],
                    )

            # --- Emotional profile refresh ---
            if sub_id in emotional_ids:
                try:
                    result = analyze_subreddit_profile(db, sub_name)
                    if "error" not in result:
                        stats["emotional_refreshed"] += 1
                    else:
                        stats["errors"] += 1
                        if sub_name not in stats["failed_subs"]:
                            stats["failed_subs"].append(sub_name)
                        logger.warning(
                            "SUBREDDIT_INTEL | emotional refresh failed | sub=r/%s | error=%s",
                            sub_name, result["error"][:150],
                        )
                except Exception as e:
                    db.rollback()
                    stats["errors"] += 1
                    if sub_name not in stats["failed_subs"]:
                        stats["failed_subs"].append(sub_name)
                    logger.warning(
                        "SUBREDDIT_INTEL | emotional refresh exception | sub=r/%s | error=%s",
                        sub_name, str(e)[:150],
                    )

            # Rate limit between subs
            time.sleep(SUBREDDIT_DELAY_SECONDS)

        # Recompute all risk scores (fast, no API calls)
        try:
            score_result = refresh_all_risk_scores(db)
            stats["scores_recomputed"] = score_result.get("updated", 0)
        except Exception as e:
            logger.warning("SUBREDDIT_INTEL | risk score recompute failed: %s", str(e)[:100])

        duration_seconds = int(time.time() - start_time)
        stats["duration_seconds"] = duration_seconds

        # Record audit event
        record_activity_event(
            db=db,
            event_type="subreddit_intelligence_daily",
            message=(
                f"Daily intelligence refresh: {stats['emotional_refreshed']} emotional, "
                f"{stats['rules_refreshed']} rules refreshed out of {total_stale} stale. "
                f"{stats['errors']} errors. Duration {duration_seconds}s."
            ),
            metadata=stats,
        )
        db.commit()

        # Notify ops if there are failures on high-use subs
        if stats["failed_subs"]:
            notify_ops(
                level="warning",
                title=f"Subreddit Intelligence: {len(stats['failed_subs'])} subs failed refresh",
                body=(
                    f"Failed: {', '.join(stats['failed_subs'][:5])}\n"
                    f"These subs may have stale profiles during today's EPG generation.\n"
                    f"Refreshed: {stats['emotional_refreshed']} emotional + {stats['rules_refreshed']} rules."
                ),
                category="subreddit_intelligence",
            )

        logger.info(
            "SUBREDDIT_INTEL | complete | %s",
            " | ".join(f"{k}={v}" for k, v in stats.items() if k != "failed_subs"),
        )

        return stats

    except Exception as e:
        logger.error("SUBREDDIT_INTEL | fatal error: %s", str(e)[:200])
        db.rollback()
        return {"status": "error", "error": str(e)[:200]}
    finally:
        db.close()
        lock.release()


def extract_rules_for_subreddit(db, sub_name: str):
    """Wrapper that calls rule_extractor and persists results."""
    from app.models.subreddit import Subreddit
    from app.models.subreddit_risk_profile import SubredditRiskProfile
    from app.services.rule_extractor import extract_subreddit_rules, _ExtractionFailure

    subreddit = (
        db.query(Subreddit)
        .filter(Subreddit.subreddit_name == sub_name)
        .first()
    )
    if not subreddit:
        return

    # Ensure risk profile exists
    profile = (
        db.query(SubredditRiskProfile)
        .filter(SubredditRiskProfile.subreddit_id == subreddit.id)
        .first()
    )
    if not profile:
        profile = SubredditRiskProfile(subreddit_id=subreddit.id)
        db.add(profile)
        db.flush()

    result = extract_subreddit_rules(sub_name, db=db)

    if result is None:
        profile.extraction_status = "no_content"
    elif isinstance(result, _ExtractionFailure):
        profile.extraction_status = "extraction_failed"
    else:
        profile.extracted_rules = [r.model_dump() for r in result.rules]
        profile.extraction_status = "success"
        profile.last_rule_extraction_at = datetime.now(timezone.utc)

    db.commit()
