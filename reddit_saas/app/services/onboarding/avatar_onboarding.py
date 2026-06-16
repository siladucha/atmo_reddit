"""Avatar Onboarding Orchestrator — auto-triggers Discovery + Strategy + Pipeline on avatar assignment.

Sequence:
1. Check for existing Discovery session (24h idempotency)
2. Create Discovery session from client profile
3. Run entity extraction
4. Run hypothesis generation
5. Generate avatar strategy (with discovery context)
6. Trigger first pipeline run (scrape → score → generate)
7. Emit activity event

All steps are fault-tolerant: failure in one step logs error and continues.
"""

import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.discovery_session import DiscoverySession

logger = get_logger(__name__)


def trigger_avatar_onboarding(
    db: Session, avatar_id: uuid.UUID, client_id: uuid.UUID
) -> dict:
    """Orchestrate full post-allocation onboarding for a single avatar.

    Args:
        db: Database session.
        avatar_id: Avatar being onboarded.
        client_id: Client the avatar is assigned to.

    Returns:
        {"completed_steps": [...], "failed_steps": [...], "discovery_session_id": UUID|None}
    """
    completed = []
    failed = []
    discovery_session_id = None

    # Load avatar and client
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    client = db.query(Client).filter(Client.id == client_id).first()

    if not avatar or not client:
        logger.error("Avatar onboarding: avatar or client not found (avatar=%s, client=%s)", avatar_id, client_id)
        return {"completed_steps": [], "failed_steps": ["load_data"], "discovery_session_id": None}

    logger.info(
        "Avatar onboarding started: avatar=%s client=%s",
        avatar.reddit_username, client.client_name,
    )

    # --- Step 1: Check existing Discovery session (24h idempotency) ---
    try:
        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        existing_session = (
            db.query(DiscoverySession)
            .filter(
                DiscoverySession.client_id == client_id,
                DiscoverySession.created_at >= recent_cutoff,
            )
            .first()
        )
        if existing_session:
            discovery_session_id = existing_session.id
            logger.info("Reusing existing Discovery session %s (created < 24h ago)", existing_session.id)
            completed.append("discovery_reuse")
        else:
            completed.append("discovery_check")
    except Exception as e:
        logger.warning("Discovery check failed: %s", e)
        failed.append("discovery_check")

    # --- Step 2: Create Discovery session if needed ---
    if not discovery_session_id:
        try:
            from app.services.discovery.session_manager import create_session

            # Build brief from client profile
            brief_parts = [
                f"Company: {client.client_name} ({client.brand_name})",
                f"Profile: {client.company_profile or ''}",
                f"Problem: {client.company_problem or ''}",
                f"ICP: {client.icp_profiles or ''}",
                f"Competitive landscape: {client.competitive_landscape or ''}",
            ]
            brief = "\n".join(p for p in brief_parts if p.split(": ", 1)[-1].strip())

            # Ensure minimum brief length
            if len(brief) < 50:
                brief = f"Company: {client.client_name}. {client.company_profile or 'No profile available.'}"

            # Get an operator user_id (use the first owner/partner user as proxy)
            from app.models.user import User
            from app.models.user_role import UserRole
            operator = (
                db.query(User)
                .filter(User.role.in_(["owner", "partner"]))
                .first()
            )
            operator_id = operator.id if operator else avatar_id  # fallback

            session = create_session(
                operator_id=operator_id,
                client_brief=brief[:5000],
                prospect_name=None,
                client_id=client_id,
                db=db,
            )
            discovery_session_id = session.id
            db.commit()
            completed.append("discovery_create")
            logger.info("Created Discovery session %s for avatar onboarding", session.id)
        except Exception as e:
            logger.error("Discovery session creation failed: %s", e)
            failed.append("discovery_create")

    # --- Step 3: Entity extraction ---
    if discovery_session_id:
        try:
            import asyncio
            from app.services.discovery.entity_extractor import extract_entities

            brief = client.company_profile or f"{client.client_name}: {client.company_problem or ''}"
            if len(brief) < 50:
                brief = f"Company {client.client_name} in {client.industry or 'technology'} industry."

            # Run async entity extraction
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    extract_entities(brief[:5000], db, discovery_session_id)
                )
            finally:
                loop.close()

            completed.append(f"entity_extraction ({result.get('count', 0)} entities)")
        except Exception as e:
            logger.error("Entity extraction failed for session %s: %s", discovery_session_id, e)
            failed.append("entity_extraction")

    # --- Step 4: Strategy generation ---
    try:
        from app.tasks.strategy import generate_strategy_async

        # Dispatch as Celery task (non-blocking)
        generate_strategy_async.delay(str(avatar_id), str(client_id))
        completed.append("strategy_generation_dispatched")
    except Exception as e:
        logger.error("Strategy generation dispatch failed: %s", e)
        failed.append("strategy_generation")

    # --- Step 5: First pipeline run ---
    try:
        from app.tasks.ai_pipeline import score_threads, generate_comments
        from app.tasks.scraping import scrape_subreddit_shared
        from app.models.subreddit import Subreddit, ClientSubredditAssignment

        # Get client's subreddits
        assignments = (
            db.query(ClientSubredditAssignment)
            .join(Subreddit, Subreddit.id == ClientSubredditAssignment.subreddit_id)
            .filter(
                ClientSubredditAssignment.client_id == client_id,
                ClientSubredditAssignment.is_active.is_(True),
                Subreddit.is_active.is_(True),
            )
            .all()
        )

        if assignments:
            # Dispatch scrape tasks
            for a in assignments:
                scrape_subreddit_shared.delay(str(a.subreddit_id))

            # Chain score + generate after 60s delay (let scrapes finish)
            chain = (
                score_threads.si(str(client_id), triggered_by="avatar_onboarding")
                | generate_comments.si(str(client_id), triggered_by="avatar_onboarding")
            )
            chain.apply_async(countdown=60)
            completed.append(f"pipeline_dispatched ({len(assignments)} subreddits)")
        else:
            logger.warning("No subreddits assigned to client %s — skipping pipeline", client_id)
            failed.append("pipeline (no subreddits)")
    except Exception as e:
        logger.error("Pipeline dispatch failed: %s", e)
        failed.append("pipeline")

    # --- Step 6: Activity event ---
    try:
        from app.services.transparency import record_activity_event
        record_activity_event(
            db=db,
            client_id=str(client_id),
            event_type="avatar_onboarding_complete",
            description=f"Avatar {avatar.reddit_username} onboarding: {len(completed)} steps completed, {len(failed)} failed",
            details={
                "avatar_id": str(avatar_id),
                "avatar_username": avatar.reddit_username,
                "completed_steps": completed,
                "failed_steps": failed,
                "discovery_session_id": str(discovery_session_id) if discovery_session_id else None,
            },
        )
        db.commit()
    except Exception as e:
        logger.warning("Activity event logging failed: %s", e)

    logger.info(
        "Avatar onboarding complete: avatar=%s completed=%s failed=%s",
        avatar.reddit_username, completed, failed,
    )

    return {
        "completed_steps": completed,
        "failed_steps": failed,
        "discovery_session_id": str(discovery_session_id) if discovery_session_id else None,
    }
