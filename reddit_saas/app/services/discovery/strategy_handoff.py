"""Strategy Handoff — bridges Discovery findings into Strategy generation.

Transforms validated Discovery data into actionable context for the Strategy Engine.
Handles three scenarios:
1. Prospect → creates Client record from Discovery data
2. Existing client → enriches existing record
3. Strategy regeneration trigger → when environment changes invalidate current strategy

Stateless service — callable from UI handoff button or automated strategy review.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.activity_event import ActivityEvent
from app.models.client import Client
from app.models.discovery_session import DiscoverySession
from app.models.subreddit import ClientSubredditAssignment, Subreddit

logger = logging.getLogger(__name__)


def prepare_handoff_context(session: DiscoverySession) -> dict:
    """Extract Discovery data for injection into strategy generation prompt.

    This dict is passed as discovery_context to StrategyEngine.generate_strategy().
    The strategy prompt uses it to ground recommendations in validated data.

    Includes:
    - All confirmed hypotheses (statement + confidence score)
    - Recommended communities (subreddit name + relevance score + suggested engagement approach)
    - Entry points from the report
    - Competitive landscape from the report

    Args:
        session: Completed Discovery session with confirmed hypotheses and report.

    Returns:
        Dict with structured Discovery context for strategy prompt.
    """
    confirmed = [h for h in session.hypotheses if h.status == "confirmed"]
    reports = session.reports

    # Extract structured data from the latest report
    communities: list[dict] = []
    entry_points: list[str] = []
    competitive_landscape: str = ""

    if reports:
        latest_report = sorted(reports, key=lambda r: r.report_version, reverse=True)[0]
        content = latest_report.content or {}
        communities = content.get("communities", [])
        entry_points = content.get("entry_points", [])
        competitive_landscape = content.get("competitive_landscape", "")

    context = {
        "session_id": str(session.id),
        "client_brief": session.client_brief[:2000],
        "confirmed_hypotheses": [
            {
                "statement": h.statement,
                "confidence_score": h.confidence_score,
            }
            for h in confirmed
        ],
        "recommended_communities": [
            {
                "subreddit_name": c.get("name", ""),
                "relevance_score": c.get("relevance", 0),
                "suggested_engagement_approach": c.get("approach", ""),
            }
            for c in communities[:10]
        ],
        "entry_points": entry_points,
        "competitive_landscape": competitive_landscape[:2000],
    }

    return context


def execute_handoff(session: DiscoverySession, db: Session) -> dict:
    """Execute the Discovery → Strategy handoff.

    If session.client_id is NULL: creates a new Client record from session data.
    If linked to existing client: uses existing record.
    Pre-populates subreddit suggestions from Discovery findings.
    Logs 'discovery_handoff' ActivityEvent.

    Does NOT trigger strategy generation — only prepares context and creates
    the client. Strategy generation is triggered separately.

    Args:
        session: Completed Discovery session.
        db: Database session.

    Returns:
        Dict with handoff results including session_id and client_id
        for the strategy generator to use.
    """
    client_created = False
    client: Client | None = None

    if session.client_id:
        # Existing client — use as-is
        client = db.query(Client).filter(Client.id == session.client_id).first()
        if not client:
            raise ValueError(f"Linked client {session.client_id} not found")
    else:
        # Create new Client from Discovery data
        client = _create_client_from_discovery(session, db)
        session.client_id = client.id
        client_created = True

    # Pre-populate subreddit suggestions from report
    subreddits_imported = _import_subreddit_suggestions(session, client, db)

    # Count confirmed hypotheses
    confirmed_count = len([h for h in session.hypotheses if h.status == "confirmed"])

    # Log activity event
    event = ActivityEvent(
        event_type="discovery_handoff",
        client_id=client.id,
        message=(
            f"Discovery handoff: {confirmed_count} confirmed hypotheses, "
            f"{subreddits_imported} subreddits suggested"
        ),
        event_metadata={
            "session_id": str(session.id),
            "client_id": str(client.id),
            "confirmed_hypotheses": confirmed_count,
            "recommended_subreddits": subreddits_imported,
            "client_created": client_created,
        },
    )
    db.add(event)
    db.flush()

    logger.info(
        f"Discovery handoff complete: session {session.id} → client {client.id} "
        f"({confirmed_count} hypotheses, {subreddits_imported} subreddits, "
        f"new_client={client_created})"
    )

    return {
        "session_id": str(session.id),
        "client_id": str(client.id),
        "client_created": client_created,
        "confirmed_hypotheses_count": confirmed_count,
        "recommended_subreddits_count": subreddits_imported,
    }


def _create_client_from_discovery(session: DiscoverySession, db: Session) -> Client:
    """Create a new Client record populated from Discovery session data.

    Uses prospect_name as brand_name/client_name. Uses the client brief as
    a starting point for the company_profile.
    """
    # Extract competitive landscape from report
    competitive_landscape = ""
    if session.reports:
        latest = sorted(session.reports, key=lambda r: r.report_version, reverse=True)[0]
        competitive_landscape = (latest.content or {}).get("competitive_landscape", "")

    # Extract industry from entities
    industry = None
    for entity in session.entities:
        if entity.category == "industry":
            industry = entity.name[:100]
            break

    # Use prospect_name for both client_name and brand_name
    name = session.prospect_name or "Discovery Prospect"

    client = Client(
        client_name=name,
        brand_name=name,
        company_profile=session.client_brief[:2000],
        competitive_landscape=competitive_landscape[:2000] if competitive_landscape else None,
        industry=industry,
        is_active=True,
    )
    db.add(client)
    db.flush()  # Get ID assigned

    logger.info(f"Created client '{client.client_name}' from Discovery session {session.id}")
    return client


def _import_subreddit_suggestions(
    session: DiscoverySession, client: Client, db: Session
) -> int:
    """Pre-populate subreddit assignments from Discovery report communities.

    Creates ClientSubredditAssignment records for recommended communities.
    Skips subreddits already assigned to this client.

    Returns:
        Count of subreddits imported.
    """
    if not session.reports:
        return 0

    latest_report = sorted(session.reports, key=lambda r: r.report_version, reverse=True)[0]
    communities = (latest_report.content or {}).get("communities", [])

    if not communities:
        return 0

    # Get existing assignments to avoid duplicates
    existing = (
        db.query(ClientSubredditAssignment)
        .filter(
            ClientSubredditAssignment.client_id == client.id,
            ClientSubredditAssignment.is_active == True,
        )
        .all()
    )
    existing_sub_ids = {a.subreddit_id for a in existing}

    imported_count = 0
    for community in communities[:10]:
        sub_name = community.get("name", "").replace("r/", "").strip()
        if not sub_name:
            continue

        # Find or create subreddit in registry
        subreddit = (
            db.query(Subreddit)
            .filter(Subreddit.subreddit_name.ilike(sub_name))
            .first()
        )

        if not subreddit:
            subreddit = Subreddit(subreddit_name=sub_name, is_active=True)
            db.add(subreddit)
            db.flush()

        # Skip if already assigned
        if subreddit.id in existing_sub_ids:
            continue

        # Create assignment (type: professional for Discovery-recommended subs)
        assignment = ClientSubredditAssignment(
            client_id=client.id,
            subreddit_id=subreddit.id,
            type="professional",
            is_active=True,
        )
        db.add(assignment)
        existing_sub_ids.add(subreddit.id)
        imported_count += 1

    return imported_count
