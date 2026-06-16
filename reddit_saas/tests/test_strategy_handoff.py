"""Unit tests for Discovery Engine strategy handoff service.

Tests cover:
- prepare_handoff_context extracts confirmed hypotheses
- execute_handoff creates Client when client_id is None
- execute_handoff uses existing client when client_id set
- Subreddit suggestions imported from report
- ActivityEvent logged with correct metadata
- No duplicate subreddit assignments
"""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.models.activity_event import ActivityEvent
from app.models.client import Client
from app.models.discovery_entity import DiscoveryEntity
from app.models.discovery_hypothesis import DiscoveryHypothesis
from app.models.discovery_session import DiscoverySession
from app.models.subreddit import ClientSubredditAssignment, Subreddit
from app.models.visibility_report import VisibilityReport
from app.services.discovery.strategy_handoff import (
    execute_handoff,
    prepare_handoff_context,
)


# --- Fixtures ---


@pytest.fixture
def discovery_session(db: Session, superuser):
    """Create a completed Discovery session with hypotheses and report."""
    session = DiscoverySession(
        operator_user_id=superuser.id,
        client_brief="A wellness tech company building AI-powered yoga apps for stressed professionals " * 2,
        prospect_name="NeuroYoga Corp",
        status="completed",
        current_iteration=2,
    )
    db.add(session)
    db.flush()

    # Add entities
    entity = DiscoveryEntity(
        session_id=session.id,
        name="Yoga App",
        category="product",
        source="extracted",
    )
    db.add(entity)

    # Add confirmed hypotheses
    h1 = DiscoveryHypothesis(
        session_id=session.id,
        iteration_number=1,
        statement="Yoga practitioners discuss app recommendations with 20+ posts/month",
        category="clients",
        confidence_score=75,
        status="confirmed",
    )
    h2 = DiscoveryHypothesis(
        session_id=session.id,
        iteration_number=1,
        statement="Wellness partners seek integration in r/meditation",
        category="partners",
        confidence_score=60,
        status="confirmed",
    )
    h3 = DiscoveryHypothesis(
        session_id=session.id,
        iteration_number=1,
        statement="No hiring signal found for this niche",
        category="hiring",
        confidence_score=30,
        status="rejected",
        rejection_reason="Not relevant for this client",
    )
    db.add_all([h1, h2, h3])

    # Add report
    report = VisibilityReport(
        session_id=session.id,
        content={
            "executive_summary": "Summary text",
            "demand_assessment": "Strong demand",
            "communities": [
                {"name": "r/yoga", "subscribers": 50000, "daily_posts": 20, "relevance": 85, "approach": "helpful expert"},
                {"name": "r/meditation", "subscribers": 30000, "daily_posts": 15, "relevance": 70, "approach": "community member"},
            ],
            "discussion_activity": "Active discussions",
            "entry_points": ["Weekly recommendation threads", "App comparison megathreads"],
            "competitive_landscape": "Headspace and Calm dominate brand mentions",
            "visibility_outcomes": [{"type": "clients", "probability": "high", "reasoning": "Active audience"}],
            "risks_and_limitations": "Limited presence in non-English subreddits",
        },
        report_version=1,
    )
    db.add(report)
    db.flush()

    return session


# --- Tests ---


def test_prepare_handoff_context_extracts_confirmed(db: Session, discovery_session):
    """prepare_handoff_context returns only confirmed hypotheses."""
    context = prepare_handoff_context(discovery_session)

    assert "confirmed_hypotheses" in context
    assert len(context["confirmed_hypotheses"]) == 2  # Only confirmed, not rejected

    # Verify structure
    for h in context["confirmed_hypotheses"]:
        assert "statement" in h
        assert "confidence_score" in h
        assert h["confidence_score"] > 0

    # Verify communities extracted from report
    assert "recommended_communities" in context
    assert len(context["recommended_communities"]) == 2
    assert context["recommended_communities"][0]["subreddit_name"] == "r/yoga"

    # Verify entry points
    assert "entry_points" in context
    assert len(context["entry_points"]) == 2

    # Verify competitive landscape
    assert "competitive_landscape" in context
    assert "Headspace" in context["competitive_landscape"]


def test_execute_handoff_creates_client_when_no_client_id(db: Session, discovery_session):
    """When client_id is None, execute_handoff creates a new Client."""
    assert discovery_session.client_id is None

    result = execute_handoff(discovery_session, db)
    db.flush()

    assert result["client_created"] is True
    assert result["client_id"] is not None

    # Verify client record was created
    client = db.query(Client).filter(Client.id == uuid.UUID(result["client_id"])).first()
    assert client is not None
    assert client.client_name == "NeuroYoga Corp"
    assert client.is_active is True

    # Verify session now linked to client
    assert discovery_session.client_id == client.id


def test_execute_handoff_uses_existing_client(db: Session, superuser):
    """When client_id is set, uses existing client without creating new one."""
    # Create an existing client
    client = Client(
        client_name="Existing Client",
        brand_name="Existing Brand",
        is_active=True,
    )
    db.add(client)
    db.flush()

    # Create session linked to existing client
    session = DiscoverySession(
        operator_user_id=superuser.id,
        client_brief="B" * 100,
        prospect_name=None,
        client_id=client.id,
        status="completed",
        current_iteration=1,
    )
    db.add(session)
    db.flush()

    # Add a confirmed hypothesis
    h = DiscoveryHypothesis(
        session_id=session.id,
        iteration_number=1,
        statement="Test hypothesis",
        category="clients",
        confidence_score=70,
        status="confirmed",
    )
    db.add(h)

    # Add minimal report
    report = VisibilityReport(
        session_id=session.id,
        content={"communities": [], "entry_points": [], "competitive_landscape": ""},
        report_version=1,
    )
    db.add(report)
    db.flush()

    result = execute_handoff(session, db)
    db.flush()

    assert result["client_created"] is False
    assert result["client_id"] == str(client.id)

    # No new client was created
    clients = db.query(Client).filter(Client.client_name == "Existing Client").all()
    assert len(clients) == 1


def test_subreddit_suggestions_imported(db: Session, discovery_session):
    """Subreddits from report are imported as ClientSubredditAssignment."""
    result = execute_handoff(discovery_session, db)
    db.flush()

    client_id = uuid.UUID(result["client_id"])

    # Check subreddit assignments were created
    assignments = (
        db.query(ClientSubredditAssignment)
        .filter(ClientSubredditAssignment.client_id == client_id)
        .all()
    )

    assert len(assignments) >= 1
    assert result["recommended_subreddits_count"] >= 1

    # Check subreddit records exist
    subreddit_names = []
    for a in assignments:
        sub = db.query(Subreddit).filter(Subreddit.id == a.subreddit_id).first()
        if sub:
            subreddit_names.append(sub.subreddit_name)

    # At least one of yoga/meditation should be imported
    assert any(name in ["yoga", "meditation"] for name in subreddit_names)


def test_activity_event_logged(db: Session, discovery_session):
    """ActivityEvent is logged with correct event_type and metadata."""
    result = execute_handoff(discovery_session, db)
    db.flush()

    # Find the activity event
    event = (
        db.query(ActivityEvent)
        .filter(ActivityEvent.event_type == "discovery_handoff")
        .order_by(ActivityEvent.created_at.desc())
        .first()
    )

    assert event is not None
    assert event.client_id == uuid.UUID(result["client_id"])
    assert "discovery_handoff" == event.event_type

    # Verify metadata
    metadata = event.event_metadata
    assert metadata["session_id"] == str(discovery_session.id)
    assert metadata["confirmed_hypotheses"] == 2
    assert "recommended_subreddits" in metadata
    assert "client_created" in metadata


def test_no_duplicate_subreddit_assignments(db: Session, superuser):
    """Importing subreddits skips already-assigned subreddits."""
    # Create client with existing subreddit assignment
    client = Client(
        client_name="Client With Subs",
        brand_name="Brand",
        is_active=True,
    )
    db.add(client)
    db.flush()

    # Create the subreddit and assign it (use unique name to avoid collision with real DB data)
    from sqlalchemy import func as sa_func
    subreddit = db.query(Subreddit).filter(sa_func.lower(Subreddit.subreddit_name) == "yoga").first()
    if not subreddit:
        subreddit = Subreddit(subreddit_name="yoga", is_active=True)
        db.add(subreddit)
        db.flush()

    existing_assignment = ClientSubredditAssignment(
        client_id=client.id,
        subreddit_id=subreddit.id,
        type="professional",
        is_active=True,
    )
    db.add(existing_assignment)
    db.flush()

    # Create session linked to this client
    session = DiscoverySession(
        operator_user_id=superuser.id,
        client_brief="C" * 100,
        client_id=client.id,
        status="completed",
        current_iteration=1,
    )
    db.add(session)
    db.flush()

    h = DiscoveryHypothesis(
        session_id=session.id,
        iteration_number=1,
        statement="Valid hypothesis",
        category="clients",
        confidence_score=70,
        status="confirmed",
    )
    db.add(h)

    # Report recommends "yoga" (already assigned) and "meditation" (new)
    report = VisibilityReport(
        session_id=session.id,
        content={
            "communities": [
                {"name": "r/yoga", "subscribers": 50000, "daily_posts": 20, "relevance": 85, "approach": "expert"},
                {"name": "r/meditation", "subscribers": 30000, "daily_posts": 15, "relevance": 70, "approach": "member"},
            ],
            "entry_points": [],
            "competitive_landscape": "",
        },
        report_version=1,
    )
    db.add(report)
    db.flush()

    result = execute_handoff(session, db)
    db.flush()

    # Count total assignments for this client
    all_assignments = (
        db.query(ClientSubredditAssignment)
        .filter(ClientSubredditAssignment.client_id == client.id)
        .all()
    )

    # Should have exactly 2: original "yoga" + new "meditation" (no duplicate yoga)
    assert len(all_assignments) == 2
    # The yoga subreddit should NOT be duplicated
    yoga_assignments = [
        a for a in all_assignments
        if a.subreddit_id == subreddit.id
    ]
    assert len(yoga_assignments) == 1
