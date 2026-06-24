"""Strategy Handoff — full Discovery-to-Client-Strategy flow.

Orchestrates: generate strategy → save to client → import subreddits → create GEO prompts → mark session.
Single button click produces everything needed for pipeline to start generating content.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.activity_event import ActivityEvent
from app.models.client import Client
from app.models.discovery_session import DiscoverySession
from app.models.subreddit import ClientSubredditAssignment, Subreddit
from app.schemas.client_strategy import ClientStrategyOutput

logger = get_logger(__name__)


def prepare_handoff_context(session: DiscoverySession) -> dict:
    """Extract Discovery data summary for display in the UI.

    Used by the results page to show what will be handed off.
    """
    confirmed = [h for h in session.hypotheses if h.status == "confirmed"]
    reports = session.reports

    communities: list[dict] = []
    entry_points: list[str] = []

    if reports:
        latest_report = sorted(reports, key=lambda r: r.report_version, reverse=True)[0]
        content = latest_report.content or {}
        communities = content.get("communities", [])
        entry_points = content.get("entry_points", [])

    return {
        "session_id": str(session.id),
        "confirmed_count": len(confirmed),
        "communities_count": len(communities),
        "entry_points": entry_points[:5],
    }


def execute_handoff(session: DiscoverySession, db: Session) -> Client:
    """Execute the full Discovery -> Client Strategy handoff.

    Steps (atomic — rolls back on any failure):
    1. Resolve or create Client record
    2. Generate Client Strategy via Gemini Flash
    3. Save strategy_context to Client (versioned + history)
    4. Import subreddits with priority + engagement_approach
    5. Create GEO prompts from aeo_targets (if geo_monitoring_enabled)
    6. Mark session status as "handed_off"
    7. Log activity event

    Returns:
        Client record (for redirect to client detail page).

    Raises:
        ValueError: If strategy generation fails after retries.
    """
    # Step 1: Resolve/create client
    client = _resolve_or_create_client(session, db)

    # Step 2: Generate strategy
    from app.services.discovery.strategy_generator import generate_client_strategy
    strategy_output, result_meta = generate_client_strategy(session, db)

    # Step 3: Save to client with versioning
    _save_strategy_to_client(client, strategy_output, result_meta, session)

    # Step 4: Import subreddits with priority from strategy
    subs_imported = _import_subreddits_with_priority(client, strategy_output, db)

    # Step 5: Create GEO prompts (conditional)
    geo_created = 0
    if getattr(client, "geo_monitoring_enabled", False):
        geo_created = _create_geo_prompts(client, strategy_output, db)

    # Step 6: Mark session as handed off
    session.status = "handed_off"

    # Step 7: Activity event
    event = ActivityEvent(
        event_type="discovery_handoff",
        client_id=client.id,
        message=(
            f"Strategy handoff: v{client.strategy_version} generated, "
            f"{subs_imported} subreddits imported, {geo_created} GEO prompts created"
        ),
        event_metadata={
            "session_id": str(session.id),
            "client_id": str(client.id),
            "strategy_version": client.strategy_version,
            "subreddits_imported": subs_imported,
            "geo_prompts_created": geo_created,
            "model": result_meta.get("model", "unknown"),
            "cost_usd": result_meta.get("cost_usd", 0),
        },
    )
    db.add(event)
    db.flush()

    logger.info(
        "Handoff complete: session %s -> client %s (strategy v%d, %d subs, %d GEO)",
        session.id, client.id, client.strategy_version, subs_imported, geo_created,
    )

    return client


def _resolve_or_create_client(session: DiscoverySession, db: Session) -> Client:
    """Resolve existing client or create new one from Discovery data."""
    if session.client_id:
        client = db.query(Client).filter(Client.id == session.client_id).first()
        if not client:
            raise ValueError(f"Linked client {session.client_id} not found")
        return client

    # Create new Client from Discovery data
    name = session.prospect_name or "Discovery Prospect"

    # Extract industry from entities
    industry = None
    for entity in session.entities:
        if entity.category == "industry":
            industry = entity.name[:100]
            break

    client = Client(
        client_name=name,
        brand_name=name,
        company_profile=session.client_brief[:2000],
        industry=industry,
        is_active=True,
    )
    db.add(client)
    db.flush()

    session.client_id = client.id
    logger.info("Created client '%s' from Discovery session %s", name, session.id)
    return client


def _save_strategy_to_client(
    client: Client,
    strategy: ClientStrategyOutput,
    result_meta: dict,
    session: DiscoverySession,
) -> None:
    """Persist strategy with versioning and history rotation (max 3 previous)."""
    now = datetime.now(timezone.utc)
    strategy_dict = strategy.model_dump()

    # Attach metadata (not from LLM)
    strategy_dict["metadata"] = {
        "generated_at": now.isoformat(),
        "source_session_id": str(session.id),
        "model_used": result_meta.get("model", "unknown"),
        "generation_cost_usd": result_meta.get("cost_usd", 0),
        "prompt_version": "1.0",
    }

    # Rotate history (keep max 3 previous)
    if client.strategy_context:
        history = client.strategy_history or []
        history.insert(0, client.strategy_context)
        client.strategy_history = history[:3]

    # Set new strategy
    client.strategy_context = strategy_dict
    client.strategy_version = (client.strategy_version or 0) + 1
    client.strategy_generated_at = now
    client.strategy_source_session_id = session.id


def _import_subreddits_with_priority(
    client: Client,
    strategy: ClientStrategyOutput,
    db: Session,
) -> int:
    """Import subreddits from strategy with priority + engagement_approach (upsert)."""
    imported = 0
    for sp in strategy.subreddit_priorities[:10]:
        sub_name = sp.subreddit.replace("r/", "").strip()
        if not sub_name:
            continue

        # Find or create subreddit
        subreddit = (
            db.query(Subreddit)
            .filter(Subreddit.subreddit_name.ilike(sub_name))
            .first()
        )
        if not subreddit:
            subreddit = Subreddit(subreddit_name=sub_name, is_active=True)
            db.add(subreddit)
            db.flush()

        # Check for existing assignment (upsert)
        existing = (
            db.query(ClientSubredditAssignment)
            .filter(
                ClientSubredditAssignment.client_id == client.id,
                ClientSubredditAssignment.subreddit_id == subreddit.id,
            )
            .first()
        )

        if existing:
            existing.priority = sp.priority
            existing.engagement_approach = sp.engagement_approach
            existing.is_active = True
        else:
            assignment = ClientSubredditAssignment(
                client_id=client.id,
                subreddit_id=subreddit.id,
                type="professional",
                is_active=True,
                priority=sp.priority,
                engagement_approach=sp.engagement_approach,
            )
            db.add(assignment)

        imported += 1

    return imported


def _create_geo_prompts(
    client: Client,
    strategy: ClientStrategyOutput,
    db: Session,
) -> int:
    """Create GeoPrompt records from strategy aeo_targets (skip duplicates)."""
    from app.models.geo_prompt import GeoPrompt

    created = 0
    for target in strategy.aeo_targets:
        prompt_text = target.user_question

        # Skip if duplicate exists
        exists = (
            db.query(GeoPrompt)
            .filter(
                GeoPrompt.client_id == client.id,
                GeoPrompt.prompt_text == prompt_text,
            )
            .first()
        )
        if exists:
            continue

        geo_prompt = GeoPrompt(
            client_id=client.id,
            prompt_text=prompt_text,
            category="discovery_generated",
            is_active=True,
        )
        db.add(geo_prompt)
        created += 1

    return created
