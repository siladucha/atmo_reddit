"""Avatar Onboarding Service — creates avatars from Discovery/Strategy context.

Bridges the gap between Discovery → Strategy → Avatar creation.
Instead of manually filling in avatar fields, this service:
1. Takes a Discovery session's recommended communities
2. Takes a client's strategy context
3. Pre-configures the avatar with correct hobby/business subreddits
4. Links the avatar to the client
5. Logs the creation with full provenance

This enables the flow:
  Client Onboarding → Discovery → Strategy → "Create Avatar" button → 
  Avatar appears with correct config, ready for EPG.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.activity_event import ActivityEvent
from app.models.audit import AuditLog
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.discovery_session import DiscoverySession
from app.models.strategy_document import StrategyDocument

logger = get_logger(__name__)


def create_avatar_from_context(
    db: Session,
    reddit_username: str,
    client_id: uuid.UUID,
    discovery_session_id: uuid.UUID | None = None,
    hobby_subreddits: list[str] | None = None,
    voice_profile_md: str = "",
    hill_i_die_on: str = "",
    helpful_mode_topics: str = "",
    operator_user_id: uuid.UUID | None = None,
) -> Avatar:
    """Create a new avatar pre-configured from Discovery and Strategy context.

    Auto-populates:
    - hobby_subreddits from provided list or Discovery communities
    - business_subreddits from Discovery's recommended communities
    - client_ids linkage
    - warming_phase = 1 (always starts in credibility building)
    - Generates initial strategy document

    Args:
        db: Database session
        reddit_username: Reddit account username
        client_id: Client to assign the avatar to
        discovery_session_id: Optional Discovery session for context
        hobby_subreddits: Explicit hobby subs (if not provided, inferred from Discovery)
        voice_profile_md: Voice profile markdown
        hill_i_die_on: Avatar's core positioning
        helpful_mode_topics: Topics for helpful engagement
        operator_user_id: Who created this (for audit)

    Returns:
        Created Avatar with strategy generated
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise ValueError(f"Client {client_id} not found")

    # --- Extract context from Discovery ---
    business_subs = []
    discovery_context = None

    if discovery_session_id:
        session = db.query(DiscoverySession).filter(
            DiscoverySession.id == discovery_session_id
        ).first()

        if session and session.reports:
            from app.services.discovery.strategy_handoff import prepare_handoff_context
            discovery_context = prepare_handoff_context(session)

            # Extract recommended communities as business subreddits
            for comm in discovery_context.get("recommended_communities", []):
                sub_name = comm.get("subreddit_name", "").replace("r/", "").strip()
                if sub_name:
                    business_subs.append({"subreddit": sub_name, "source": "discovery"})

    # --- Default hobby subs if not provided ---
    if not hobby_subreddits:
        # Use 3 generic popular subreddits for credibility building
        hobby_subreddits = ["todayilearned", "AskReddit", "technology"]

    # --- Create Avatar ---
    avatar = Avatar(
        id=uuid.uuid4(),
        reddit_username=reddit_username,
        active=True,
        warming_phase=1,  # Always start in Phase 1
        client_ids=[str(client_id)],
        hobby_subreddits=hobby_subreddits,
        business_subreddits=business_subs if business_subs else None,
        voice_profile_md=voice_profile_md or None,
        hill_i_die_on=hill_i_die_on or None,
        helpful_mode_topics=helpful_mode_topics or None,
        health_status="unknown",
        posting_mode="disabled",  # Start disabled until configured
    )
    db.add(avatar)
    db.flush()

    # --- Generate initial strategy ---
    try:
        from app.services.strategy_engine import StrategyEngine
        engine = StrategyEngine()
        strategy = engine.generate_fallback_strategy(db, avatar, client)
        logger.info(f"Initial strategy v{strategy.version} generated for {reddit_username}")
    except Exception as e:
        logger.warning(f"Failed to generate initial strategy for {reddit_username}: {e}")
        # Non-critical — avatar still created

    # --- Log activity ---
    event = ActivityEvent(
        event_type="avatar_onboarded",
        client_id=client_id,
        message=(
            f"Avatar @{reddit_username} created for {client.client_name} "
            f"(hobby: {hobby_subreddits[:3]}, business: {[s.get('subreddit','') for s in business_subs[:3]]})"
        ),
        event_metadata={
            "avatar_id": str(avatar.id),
            "reddit_username": reddit_username,
            "client_id": str(client_id),
            "discovery_session_id": str(discovery_session_id) if discovery_session_id else None,
            "hobby_subreddits": hobby_subreddits,
            "business_subreddits": [s.get("subreddit", "") for s in business_subs],
            "phase": 1,
            "source": "avatar_onboarding_flow",
        },
    )
    db.add(event)

    # Audit log
    audit = AuditLog(
        user_id=operator_user_id,
        client_id=client_id,
        action="avatar_created_from_context",
        entity_type="avatar",
        entity_id=avatar.id,
        details={
            "reddit_username": reddit_username,
            "hobby_subreddits": hobby_subreddits,
            "business_subreddits_count": len(business_subs),
            "discovery_linked": discovery_session_id is not None,
        },
    )
    db.add(audit)

    db.commit()
    db.refresh(avatar)

    logger.info(
        f"Avatar onboarded: @{reddit_username} → {client.client_name} "
        f"(hobby={len(hobby_subreddits)}, biz={len(business_subs)})"
    )

    return avatar
