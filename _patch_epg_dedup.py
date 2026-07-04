"""Patch: replace dedup guard in portfolio_manager.py with smarter version."""
import re

filepath = "reddit_saas/app/services/portfolio_manager.py"

with open(filepath, "r") as f:
    content = f.read()

old = '''    # --- Dedup guard: skip if ANY slots already exist for today ---
    # Any existing slots (including skipped) mean EPG was already attempted today.
    # This prevents duplicate builds from the dual schedule (08:15 + 14:15).
    from sqlalchemy import func as _sa_func
    existing_slots_count = (
        db.query(_sa_func.count(EPGSlot.id))
        .filter(
            EPGSlot.avatar_id == avatar.id,
            EPGSlot.plan_date == plan_date,
        )
        .scalar() or 0
    )
    if existing_slots_count > 0:
        result.status = "already_planned"
        result.message = (
            f"EPG already built today: {existing_slots_count} slots exist. "
            f"Skipping duplicate build."
        )
        logger.info(
            "build_portfolio SKIPPED (dedup): avatar=%s plan_date=%s existing_slots=%d",
            avatar.reddit_username, plan_date, existing_slots_count,
        )
        return result'''

new = '''    # --- Dedup guard: prevent duplicate EPG builds per avatar per day ---
    # Rules:
    # 1. If any non-skipped slots exist (generated/approved/posted) -> skip (successful build exists)
    # 2. If only skipped slots exist -> allow ONE retry (afternoon rebuild after morning failure)
    # 3. Max 2 build attempts per day (counted by distinct created_at batches)
    from sqlalchemy import func as _sa_func

    _MAX_BUILD_ATTEMPTS_PER_DAY = 2

    existing_active_count = (
        db.query(_sa_func.count(EPGSlot.id))
        .filter(
            EPGSlot.avatar_id == avatar.id,
            EPGSlot.plan_date == plan_date,
            EPGSlot.status.notin_(["skipped"]),
        )
        .scalar() or 0
    )

    if existing_active_count > 0:
        # Successful build exists - no rebuild needed
        result.status = "already_planned"
        result.message = (
            f"EPG already built today: {existing_active_count} active slots exist. "
            f"Skipping duplicate build."
        )
        logger.info(
            "build_portfolio SKIPPED (dedup): avatar=%s plan_date=%s existing_slots=%d",
            avatar.reddit_username, plan_date, existing_active_count,
        )
        return result

    # Check build attempt count (all slots including skipped)
    build_attempts = (
        db.query(_sa_func.count(_sa_func.distinct(EPGSlot.created_at)))
        .filter(
            EPGSlot.avatar_id == avatar.id,
            EPGSlot.plan_date == plan_date,
        )
        .scalar() or 0
    )

    if build_attempts >= _MAX_BUILD_ATTEMPTS_PER_DAY:
        # Already attempted twice (morning + afternoon) - stop
        result.status = "already_planned"
        result.message = (
            f"EPG build attempted {build_attempts} times today (max {_MAX_BUILD_ATTEMPTS_PER_DAY}). "
            f"All previous slots skipped. No more retries."
        )
        logger.info(
            "build_portfolio SKIPPED (max attempts): avatar=%s plan_date=%s attempts=%d",
            avatar.reddit_username, plan_date, build_attempts,
        )
        return result

    # Allow rebuild: previous attempt(s) all failed (skipped), retry permitted
    if build_attempts > 0:
        logger.info(
            "build_portfolio RETRY: avatar=%s plan_date=%s previous_attempts=%d (all skipped)",
            avatar.reddit_username, plan_date, build_attempts,
        )'''

if old in content:
    content = content.replace(old, new)
    with open(filepath, "w") as f:
        f.write(content)
    print("OK: dedup guard patched")
else:
    print("ERROR: old text not found")
