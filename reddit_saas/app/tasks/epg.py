"""Celery tasks for EPG (Electronic Program Guide) — daily avatar publishing program.

Tasks:
- build_and_generate_epg_all_avatars: Daily (08:15) — plans EPG + generates comments for all avatars (full daily budget)
- epg_topup_underfilled_avatars: Daily (14:15) — fills remaining budget for avatars that got fewer slots in morning
- expire_stale_planned_slots: Daily cleanup for slots that remain "planned" past their date

Integration:
- Registered in app/tasks/worker.py
- Beat schedule: build_and_generate_epg_all_avatars at 08:15, epg_topup at 14:15
- Depends on: app/services/epg.py (build_daily_epg) + app/services/epg_executor.py (generate_all_planned_slots)
"""

from app.logging_config import get_logger
import uuid
from datetime import date, datetime, timezone

from celery import shared_task

from app.database import SessionLocal

logger = get_logger(__name__)


@shared_task(name="build_and_generate_epg_all_avatars")
def build_and_generate_epg_all_avatars():
    """Build daily EPG plans and generate comments for all eligible avatars.

    Flow per avatar:
    1. Check epg2_enabled flag:
       - If enabled: build_portfolio() — multi-stage investment decision engine
       - If disabled: build_daily_epg() — legacy thread selection
    2. generate_all_planned_slots() — calls LLM to generate comments for each slot
    3. Auto-approve if client has autopilot_enabled

    Skips avatars that are frozen, inactive, mentor (phase 0), or shadowbanned.
    Respects pipeline_enabled kill switch.
    """
    from app.models.avatar import Avatar
    from app.models.client import Client
    from app.services.epg import build_daily_epg
    from app.services.epg_executor import generate_all_planned_slots
    from app.services.portfolio_manager import build_portfolio
    from app.services.settings import get_setting

    db = SessionLocal()
    try:
        # Check pipeline kill switch
        pipeline_enabled = get_setting(db, "pipeline_enabled")
        if pipeline_enabled in ("false", "False", "0"):
            logger.info("build_and_generate_epg_all_avatars: pipeline_enabled=false, skipping")
            return {"status": "skipped", "reason": "pipeline_disabled"}

        # Check EPG 2.0 feature flag
        epg2_enabled = get_setting(db, "epg2_enabled").lower() in ("true", "1")
        if epg2_enabled:
            logger.info("EPG 2.0 (Attention Portfolio Manager) enabled")
        else:
            logger.info("EPG 2.0 disabled, using legacy build_daily_epg")

        # Get all active avatars
        avatars = (
            db.query(Avatar)
            .filter(
                Avatar.active.is_(True),
                Avatar.is_frozen.is_(False),
                Avatar.pool != "mentor",  # Mentors excluded (pool-based)
            )
            .all()
        )

        # Filter out unhealthy
        eligible = [
            a for a in avatars
            if a.health_status not in ("shadowbanned", "suspended")
        ]

        logger.info(
            "EPG daily run: %d eligible avatars (of %d active), epg2=%s",
            len(eligible), len(avatars), epg2_enabled,
        )

        results = {
            "planned": 0,
            "generated": 0,
            "skipped_avatars": 0,
            "errors": 0,
            "epg2_enabled": epg2_enabled,
        }

        # Track this pipeline run for observability
        try:
            from app.services.pipeline_tracker import start_pipeline_run, complete_pipeline_run, fail_pipeline_run
            pipeline_run = start_pipeline_run(
                db, "epg_build",
                trigger_source="scheduler",
                meta={"epg2_enabled": epg2_enabled, "eligible_avatars": len(eligible)},
            )
        except Exception:
            pipeline_run = None

        for avatar in eligible:
            try:
                # Acquire per-avatar distributed lock to prevent race conditions
                # between morning (08:15) and afternoon (14:15) EPG runs
                from app.services.distributed_lock import DistributedLock
                from app.services.ai import reset_task_call_counter
                epg_lock = DistributedLock(
                    key=f"epg_build_lock:{avatar.id}",
                    ttl=600,  # 10 min TTL — generous for LLM generation
                )
                if not epg_lock.acquire():
                    logger.info(
                        "EPG: avatar=%s skipped (lock held — concurrent build in progress)",
                        avatar.reddit_username,
                    )
                    results["skipped_avatars"] += 1
                    continue

                try:
                    # R-AI-007: reset per-task call counter per avatar to prevent
                    # accumulation across avatars in this orchestrator task
                    reset_task_call_counter()
                    # Resolve client
                    client = None
                    if avatar.client_ids:
                        client = (
                            db.query(Client)
                            .filter(Client.id == uuid.UUID(avatar.client_ids[0]))
                            .first()
                        )

                    # Skip if client is inactive
                    if client and not client.is_active:
                        results["skipped_avatars"] += 1
                        continue

                    # Skip expired trial clients (prevent AI resource waste)
                    if client:
                        from app.services.trial_guard import is_trial_expired
                        if is_trial_expired(client):
                            results["skipped_avatars"] += 1
                            continue

                    # Step 1: Build plan — EPG 2.0 or legacy depending on feature flag
                    if epg2_enabled:
                        epg = build_portfolio(db, avatar, client)
                    else:
                        epg = build_daily_epg(db, avatar, client)

                    if epg.status in ("frozen", "excluded", "budget_exhausted"):
                        results["skipped_avatars"] += 1
                        continue

                    planned_count = len(epg.hobby_slots) + len(epg.business_slots)
                    results["planned"] += planned_count

                    # Step 2: Generate comments for planned slots
                    generated = generate_all_planned_slots(db, avatar.id)
                    results["generated"] += generated

                    if generated > 0:
                        logger.info(
                            "EPG: avatar=%s generated=%d/%d planned (epg2=%s)",
                            avatar.reddit_username, generated, planned_count, epg2_enabled,
                        )
                finally:
                    epg_lock.release()

            except Exception as e:
                logger.error(
                    "EPG failed for avatar %s: %s",
                    avatar.reddit_username, str(e)[:200],
                    exc_info=True,
                )
                results["errors"] += 1
                # Continue with other avatars
                continue

        # Log summary to audit
        try:
            from app.services.audit import log_system_action
            log_system_action(
                db=db,
                action="epg_daily_run",
                entity_type="system",
                details={
                    "eligible_avatars": len(eligible),
                    "planned_slots": results["planned"],
                    "generated_slots": results["generated"],
                    "skipped_avatars": results["skipped_avatars"],
                    "errors": results["errors"],
                    "plan_date": str(date.today()),
                    "epg2_enabled": epg2_enabled,
                },
            )
        except Exception:
            pass

        # Complete pipeline run tracking
        if pipeline_run:
            try:
                complete_pipeline_run(
                    db, pipeline_run,
                    succeeded=results["generated"],
                    failed=results["errors"],
                    skipped=results["skipped_avatars"],
                )
                db.commit()
            except Exception:
                pass

        logger.info(
            "EPG daily run complete: planned=%d generated=%d skipped=%d errors=%d epg2=%s",
            results["planned"], results["generated"],
            results["skipped_avatars"], results["errors"], epg2_enabled,
        )

        # Notify clients with pending drafts (if autopilot=off)
        if results["generated"] > 0:
            try:
                from app.services.client_email_notifications import notify_pending_drafts
                # Find unique client_ids that got new drafts
                notified_clients = set()
                for avatar in eligible:
                    if avatar.client_ids:
                        for cid in avatar.client_ids:
                            if cid and cid not in notified_clients:
                                notified_clients.add(cid)
                                notify_pending_drafts(db, cid)
            except Exception as e:
                logger.warning("Failed to send pending drafts notifications: %s", e)

        return results

    except Exception as e:
        logger.error("build_and_generate_epg_all_avatars failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


@shared_task(name="expire_stale_planned_slots")
def expire_stale_planned_slots():
    """Mark planned slots from past dates as 'skipped' (expired).

    Runs daily at 23:00. Any slot still 'planned' from yesterday or earlier
    means generation failed or was never attempted — mark as expired for clarity.
    """
    from app.models.epg_slot import EPGSlot

    db = SessionLocal()
    try:
        today = date.today()

        expired_count = (
            db.query(EPGSlot)
            .filter(
                EPGSlot.status == "planned",
                EPGSlot.plan_date < today,
            )
            .update(
                {"status": "skipped", "skip_reason": "expired_past_date"},
                synchronize_session="fetch",
            )
        )
        db.commit()

        if expired_count > 0:
            logger.info("Expired %d stale planned EPG slots", expired_count)

        return {"expired": expired_count}

    except Exception as e:
        logger.error("expire_stale_planned_slots failed: %s", e, exc_info=True)
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()


@shared_task(name="epg_topup_underfilled_avatars")
def epg_topup_underfilled_avatars():
    """Afternoon top-up: fill remaining budget for avatars that got fewer slots than their daily limit.

    Runs at 14:15 (after afternoon scrape at 14:00 brings fresh threads).
    Only creates NEW slots for the unfilled portion of the budget — never duplicates
    or replaces existing slots.

    Example: Phase 2 avatar has budget=9 (7 comments + 2 posts). Morning run created 5
    (2 skipped due to no opportunities). Afternoon: fresh threads available → create up to 4 more.

    Skipped morning slots do NOT free up budget — they represent burned opportunities.
    Only the gap between successfully created slots and the daily budget is filled.
    """
    from app.models.avatar import Avatar
    from app.models.client import Client
    from app.models.epg_slot import EPGSlot
    from app.services.epg_executor import generate_all_planned_slots
    from app.services.portfolio_manager import build_portfolio, AttentionBudget
    from app.services.settings import get_setting
    from sqlalchemy import func as sa_func

    db = SessionLocal()
    try:
        # Check pipeline kill switch
        pipeline_enabled = get_setting(db, "pipeline_enabled")
        if pipeline_enabled in ("false", "False", "0"):
            logger.info("epg_topup: pipeline_enabled=false, skipping")
            return {"status": "skipped", "reason": "pipeline_disabled"}

        epg2_enabled = get_setting(db, "epg2_enabled").lower() in ("true", "1")
        today = date.today()

        # Get all active avatars
        avatars = (
            db.query(Avatar)
            .filter(
                Avatar.active.is_(True),
                Avatar.is_frozen.is_(False),
                Avatar.pool != "mentor",
            )
            .all()
        )

        eligible = [
            a for a in avatars
            if a.health_status not in ("shadowbanned", "suspended")
        ]

        results = {"topped_up": 0, "generated": 0, "skipped": 0, "errors": 0}

        for avatar in eligible:
            try:
                # Calculate full daily budget for this avatar
                budget = AttentionBudget.from_avatar(avatar)
                daily_limit = budget.max_total_actions

                if daily_limit <= 0:
                    results["skipped"] += 1
                    continue

                # Count total budget used today (EPG comment slots + PostDrafts)
                from app.services.epg_executor import get_budget_used_today
                total_used_today = get_budget_used_today(db, avatar.id, today)

                remaining = daily_limit - total_used_today

                if remaining <= 0:
                    # Budget fully filled from morning run
                    results["skipped"] += 1
                    continue

                # Guard: check total slot count (ALL statuses including skipped).
                # If we already created >= daily_limit slots and they all failed generation,
                # creating more won't help — the issue is generation, not opportunity supply.
                total_slots_all_statuses = (
                    db.query(sa_func.count(EPGSlot.id))
                    .filter(
                        EPGSlot.avatar_id == avatar.id,
                        EPGSlot.plan_date == today,
                    )
                    .scalar() or 0
                )

                if total_slots_all_statuses >= daily_limit:
                    logger.info(
                        "epg_topup: avatar=%s has %d total slots today (budget=%d), "
                        "successful=%d. Skipping — generation issues, not supply.",
                        avatar.reddit_username, total_slots_all_statuses,
                        daily_limit, total_used_today,
                    )
                    results["skipped"] += 1
                    continue

                # This avatar has unfilled budget — run portfolio build for the gap
                logger.info(
                    "epg_topup: avatar=%s used=%d/%d, filling %d more",
                    avatar.reddit_username, total_used_today, daily_limit, remaining,
                )

                from app.services.distributed_lock import DistributedLock
                from app.services.ai import reset_task_call_counter

                epg_lock = DistributedLock(
                    key=f"epg_build_lock:{avatar.id}",
                    ttl=600,
                )
                if not epg_lock.acquire():
                    results["skipped"] += 1
                    continue

                try:
                    reset_task_call_counter()

                    client = None
                    if avatar.client_ids:
                        client = (
                            db.query(Client)
                            .filter(Client.id == uuid.UUID(avatar.client_ids[0]))
                            .first()
                        )

                    if client and not client.is_active:
                        results["skipped"] += 1
                        continue

                    if client:
                        from app.services.trial_guard import is_trial_expired
                        if is_trial_expired(client):
                            results["skipped"] += 1
                            continue

                    # Build portfolio — dedup guard in build_portfolio will see existing
                    # active slots and block. We need to temporarily override.
                    # Instead, call build_portfolio which will be blocked by dedup.
                    # Solution: we use the topup-aware path.
                    if epg2_enabled:
                        epg = build_portfolio(db, avatar, client, topup_remaining=remaining)
                    else:
                        # Legacy path: no topup support, skip
                        results["skipped"] += 1
                        continue

                    if epg.status in ("frozen", "excluded", "budget_exhausted", "already_planned"):
                        results["skipped"] += 1
                        continue

                    planned_count = len(epg.hobby_slots) + len(epg.business_slots)
                    results["topped_up"] += planned_count

                    # Generate comments for new planned slots
                    generated = generate_all_planned_slots(db, avatar.id)
                    results["generated"] += generated

                    if generated > 0:
                        logger.info(
                            "epg_topup: avatar=%s topped_up=%d generated=%d",
                            avatar.reddit_username, planned_count, generated,
                        )
                finally:
                    epg_lock.release()

            except Exception as e:
                logger.error(
                    "epg_topup failed for avatar %s: %s",
                    avatar.reddit_username, str(e)[:200],
                    exc_info=True,
                )
                results["errors"] += 1
                continue

        logger.info(
            "epg_topup complete: topped_up=%d generated=%d skipped=%d errors=%d",
            results["topped_up"], results["generated"],
            results["skipped"], results["errors"],
        )
        return results

    except Exception as e:
        logger.error("epg_topup_underfilled_avatars failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


@shared_task(name="ensure_daily_epg_minimum")
def ensure_daily_epg_minimum():
    """Enforcement: guarantee every active avatar has ≥1 EPG slot today.

    Runs at 09:00 (45 min after morning EPG build at 08:15).
    For each avatar with 0 generated/approved/posted slots today:
    1. Trigger hobby scrape (fresh content supply)
    2. Attempt build_portfolio with topup_remaining=budget
    3. If still 0 — emit activity event + alert (operator must investigate)

    This is NOT a retry of the morning run — it's an enforcement mechanism.
    If the morning run succeeded (avatar has slots), this task does nothing.
    If the morning run produced zero-day, this gives it a second chance with
    fresh scraped content, then alerts if still impossible.

    The invariant being enforced:
        ∀ active avatar with budget > 0: EPG_slots_today ≥ 1

    Gated by: pipeline_enabled, epg2_enabled.
    """
    from app.models.avatar import Avatar
    from app.models.client import Client
    from app.models.epg_slot import EPGSlot
    from app.services.epg_executor import generate_all_planned_slots
    from app.services.portfolio_manager import build_portfolio, AttentionBudget
    from app.services.settings import get_setting
    from sqlalchemy import func as sa_func

    db = SessionLocal()
    try:
        # Gate checks
        pipeline_enabled = get_setting(db, "pipeline_enabled")
        if pipeline_enabled in ("false", "False", "0"):
            logger.info("ensure_daily_epg_minimum: pipeline_enabled=false, skipping")
            return {"status": "skipped", "reason": "pipeline_disabled"}

        epg2_enabled = get_setting(db, "epg2_enabled").lower() in ("true", "1")
        if not epg2_enabled:
            logger.info("ensure_daily_epg_minimum: epg2 disabled, skipping (legacy EPG has no guarantee)")
            return {"status": "skipped", "reason": "epg2_disabled"}

        today = date.today()

        # Get all avatars that SHOULD have EPG today
        avatars = (
            db.query(Avatar)
            .filter(
                Avatar.active.is_(True),
                Avatar.is_frozen.is_(False),
                Avatar.pool != "mentor",
                Avatar.health_status.notin_(("shadowbanned", "suspended")),
            )
            .all()
        )

        # Find avatars with zero active slots today
        starving_avatars = []
        for avatar in avatars:
            budget = AttentionBudget.from_avatar(avatar)
            if budget.max_total_actions <= 0:
                continue  # CQS=lowest or mentor — legitimately 0 budget

            # Use unified budget counter (EPG slots + PostDrafts)
            from app.services.epg_executor import get_budget_used_today
            total_used = get_budget_used_today(db, avatar.id, today)

            if total_used > 0:
                continue  # Has successful slots — not starving

            # Check if slots were already attempted but all failed generation.
            # If total slots (any status) >= budget, the problem is generation,
            # not lack of opportunity. Don't create more — won't help.
            total_slots_any_status = (
                db.query(sa_func.count(EPGSlot.id))
                .filter(
                    EPGSlot.avatar_id == avatar.id,
                    EPGSlot.plan_date == today,
                )
                .scalar() or 0
            )

            if total_slots_any_status >= budget.max_total_actions:
                logger.info(
                    "ensure_daily_epg_minimum: avatar=%s has %d slots (all failed), "
                    "budget=%d. Generation issue — not retrying.",
                    avatar.reddit_username, total_slots_any_status,
                    budget.max_total_actions,
                )
                continue  # Already attempted enough — generation is broken

            starving_avatars.append(avatar)

        if not starving_avatars:
            logger.info("ensure_daily_epg_minimum: all %d avatars have EPG slots today ✓", len(avatars))
            return {"status": "ok", "all_covered": len(avatars)}

        logger.warning(
            "ensure_daily_epg_minimum: %d/%d avatars have 0 slots today — attempting recovery",
            len(starving_avatars), len(avatars),
        )

        results = {"recovered": 0, "still_starving": 0, "errors": 0}

        for avatar in starving_avatars:
            try:
                from app.services.distributed_lock import DistributedLock
                from app.services.ai import reset_task_call_counter

                # Step 1: Force hobby scrape for this avatar (fresh supply)
                try:
                    from app.tasks.scraping import scrape_hobby_subreddits
                    scrape_hobby_subreddits(str(avatar.id))
                    # Refresh session to see new hobby posts
                    db.expire_all()
                except Exception as scrape_err:
                    logger.warning(
                        "ensure_daily_epg_minimum: scrape failed for %s: %s",
                        avatar.reddit_username, str(scrape_err)[:100],
                    )

                # Step 2: Attempt EPG build (uses topup path to bypass dedup guard)
                epg_lock = DistributedLock(
                    key=f"epg_build_lock:{avatar.id}",
                    ttl=600,
                )
                if not epg_lock.acquire():
                    logger.info(
                        "ensure_daily_epg_minimum: avatar=%s lock held, skip",
                        avatar.reddit_username,
                    )
                    results["still_starving"] += 1
                    continue

                try:
                    reset_task_call_counter()

                    client = None
                    if avatar.client_ids:
                        client = (
                            db.query(Client)
                            .filter(Client.id == uuid.UUID(avatar.client_ids[0]))
                            .first()
                        )

                    if client and not client.is_active:
                        results["still_starving"] += 1
                        continue

                    if client:
                        from app.services.trial_guard import is_trial_expired
                        if is_trial_expired(client):
                            results["still_starving"] += 1
                            continue

                    budget = AttentionBudget.from_avatar(avatar, client)

                    # Subtract already-used budget (slots generated earlier today)
                    from app.services.epg_executor import get_budget_used_today as _get_used
                    already_used = _get_used(db, avatar.id, today)
                    topup_amount = max(0, budget.max_total_actions - already_used)

                    if topup_amount <= 0:
                        # Budget was filled between our check and this point (race)
                        results["still_starving"] += 1
                        continue

                    epg = build_portfolio(db, avatar, client, topup_remaining=topup_amount)

                    if epg.status in ("frozen", "excluded", "budget_exhausted"):
                        results["still_starving"] += 1
                        continue

                    planned_count = len(epg.hobby_slots) + len(epg.business_slots)

                    if planned_count > 0:
                        # Generate comments for new slots
                        generated = generate_all_planned_slots(db, avatar.id)
                        if generated > 0:
                            results["recovered"] += 1
                            logger.info(
                                "ensure_daily_epg_minimum: RECOVERED avatar=%s generated=%d",
                                avatar.reddit_username, generated,
                            )
                        else:
                            results["still_starving"] += 1
                    else:
                        results["still_starving"] += 1
                finally:
                    epg_lock.release()

            except Exception as e:
                logger.error(
                    "ensure_daily_epg_minimum: failed for %s: %s",
                    avatar.reddit_username, str(e)[:200],
                    exc_info=True,
                )
                results["errors"] += 1

        # Step 3: Alert for avatars still without EPG after recovery attempt
        if results["still_starving"] > 0:
            logger.warning(
                "🔴 ensure_daily_epg_minimum: %d avatars STILL have 0 EPG slots after recovery attempt",
                results["still_starving"],
            )
            # Emit activity event for operator visibility
            try:
                from app.services.transparency import record_activity_event
                starving_names = [
                    a.reddit_username for a in starving_avatars
                    if a.reddit_username  # just in case
                ][:10]  # cap at 10 for log readability
                record_activity_event(
                    db,
                    event_type="system",
                    message=(
                        f"⚠️ EPG daily minimum NOT met: {results['still_starving']} avatars "
                        f"have 0 slots today after recovery. Investigate: {', '.join(starving_names)}"
                    ),
                    client_id=None,
                    metadata={
                        "starving_count": results["still_starving"],
                        "recovered_count": results["recovered"],
                        "avatars": starving_names,
                    },
                )
                db.commit()
            except Exception:
                pass

        logger.info(
            "ensure_daily_epg_minimum complete: recovered=%d still_starving=%d errors=%d",
            results["recovered"], results["still_starving"], results["errors"],
        )
        return results

    except Exception as e:
        logger.error("ensure_daily_epg_minimum failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()
