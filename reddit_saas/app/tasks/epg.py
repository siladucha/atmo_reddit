"""Celery tasks for EPG (Electronic Program Guide) — daily avatar publishing program.

Tasks:
- build_and_generate_epg_all_avatars: Daily (08:15) — plans EPG + generates comments for all avatars
- expire_stale_planned_slots: Daily cleanup for slots that remain "planned" past their date

Integration:
- Registered in app/tasks/worker.py
- Beat schedule: build_and_generate_epg_all_avatars at 08:15 (after AI pipeline scoring at 08:00)
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
                Avatar.warming_phase > 0,  # Exclude mentors
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

        for avatar in eligible:
            try:
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

        logger.info(
            "EPG daily run complete: planned=%d generated=%d skipped=%d errors=%d epg2=%s",
            results["planned"], results["generated"],
            results["skipped_avatars"], results["errors"], epg2_enabled,
        )
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
