"""Unit tests for Discovery Engine session manager service.

Tests cover:
- create_session with valid data
- create_session rejects brief <50 chars
- create_session rejects brief >5000 chars
- abandon_session only works from "in_progress" status
- advance_iteration rejects when at max (5)
- advance_iteration rejects when undecided hypotheses remain
- list_sessions pagination
- list_sessions status filter
- update_ai_cost atomic increment
"""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.models.discovery_hypothesis import DiscoveryHypothesis
from app.models.discovery_session import DiscoverySession
from app.services.discovery.session_manager import (
    abandon_session,
    advance_iteration,
    create_session,
    list_sessions,
    update_ai_cost,
)


# --- Tests ---


def test_create_session_valid(db: Session, superuser):
    """Create session with valid data succeeds."""
    brief = "A" * 100  # 100 chars, above 50 min
    session = create_session(
        operator_id=superuser.id,
        client_brief=brief,
        prospect_name="Test Prospect",
        client_id=None,
        db=db,
    )

    assert session.id is not None
    assert session.status == "in_progress"
    assert session.current_iteration == 1
    assert session.client_brief == brief
    assert session.prospect_name == "Test Prospect"
    assert session.operator_user_id == superuser.id
    assert session.client_id is None
    assert session.total_ai_cost_usd == 0


def test_create_session_rejects_short_brief(db: Session, superuser):
    """Brief < 50 chars raises ValueError."""
    with pytest.raises(ValueError, match="at least 50 characters"):
        create_session(
            operator_id=superuser.id,
            client_brief="Too short",
            prospect_name=None,
            client_id=None,
            db=db,
        )


def test_create_session_rejects_long_brief(db: Session, superuser):
    """Brief > 5000 chars raises ValueError."""
    long_brief = "X" * 5001
    with pytest.raises(ValueError, match="at most 5000 characters"):
        create_session(
            operator_id=superuser.id,
            client_brief=long_brief,
            prospect_name=None,
            client_id=None,
            db=db,
        )


def test_abandon_session_from_in_progress(db: Session, superuser):
    """Abandoning an in_progress session succeeds."""
    session = create_session(
        operator_id=superuser.id,
        client_brief="A" * 100,
        prospect_name=None,
        client_id=None,
        db=db,
    )
    db.flush()

    result = abandon_session(session_id=session.id, reason="Not a good fit", db=db)

    assert result.status == "abandoned"
    assert result.abandon_reason == "Not a good fit"


def test_abandon_session_rejects_non_in_progress(db: Session, superuser):
    """Cannot abandon a session that is not 'in_progress'."""
    session = create_session(
        operator_id=superuser.id,
        client_brief="B" * 100,
        prospect_name=None,
        client_id=None,
        db=db,
    )
    db.flush()

    # First abandon
    abandon_session(session_id=session.id, reason="First abandon", db=db)
    db.flush()

    # Trying to abandon again should fail
    with pytest.raises(ValueError, match="Only 'in_progress' sessions can be abandoned"):
        abandon_session(session_id=session.id, reason="Second attempt", db=db)


def test_advance_iteration_rejects_at_max(db: Session, superuser):
    """Cannot advance beyond max 5 iterations."""
    session = create_session(
        operator_id=superuser.id,
        client_brief="C" * 100,
        prospect_name=None,
        client_id=None,
        db=db,
    )
    db.flush()

    # Set iteration to 5 directly
    session.current_iteration = 5
    db.flush()

    with pytest.raises(ValueError, match="Cannot advance beyond 5 iterations"):
        advance_iteration(session_id=session.id, db=db)


def test_advance_iteration_rejects_undecided_hypotheses(db: Session, superuser):
    """Cannot advance when hypotheses are still 'proposed'."""
    session = create_session(
        operator_id=superuser.id,
        client_brief="D" * 100,
        prospect_name=None,
        client_id=None,
        db=db,
    )
    db.flush()

    # Add a proposed hypothesis in current iteration
    hypothesis = DiscoveryHypothesis(
        session_id=session.id,
        iteration_number=1,
        statement="Test hypothesis about yoga with 20+ posts",
        category="clients",
        status="proposed",
    )
    db.add(hypothesis)
    db.flush()

    with pytest.raises(ValueError, match="still have status 'proposed'"):
        advance_iteration(session_id=session.id, db=db)


def test_advance_iteration_succeeds_after_decisions(db: Session, superuser):
    """Can advance when all hypotheses are decided."""
    session = create_session(
        operator_id=superuser.id,
        client_brief="E" * 100,
        prospect_name=None,
        client_id=None,
        db=db,
    )
    db.flush()

    # Add decided hypotheses
    h1 = DiscoveryHypothesis(
        session_id=session.id,
        iteration_number=1,
        statement="Confirmed hypothesis",
        category="clients",
        status="confirmed",
    )
    h2 = DiscoveryHypothesis(
        session_id=session.id,
        iteration_number=1,
        statement="Rejected hypothesis",
        category="partners",
        status="rejected",
        rejection_reason="Not relevant enough",
    )
    db.add_all([h1, h2])
    db.flush()

    result = advance_iteration(session_id=session.id, db=db)

    assert result.current_iteration == 2


def test_list_sessions_pagination(db: Session, superuser):
    """Pagination returns correct page and total."""
    # Create 3 sessions
    for i in range(3):
        create_session(
            operator_id=superuser.id,
            client_brief=f"Session {i} brief " + "x" * 50,
            prospect_name=f"Prospect {i}",
            client_id=None,
            db=db,
        )
    db.flush()

    # Request page 1 with per_page=2
    result = list_sessions(db=db, page=1, per_page=2)

    assert len(result["items"]) == 2
    assert result["total"] >= 3
    assert result["page"] == 1
    assert result["per_page"] == 2
    assert result["pages"] >= 2


def test_list_sessions_status_filter(db: Session, superuser):
    """Status filter only returns matching sessions."""
    # Create an in_progress session
    s1 = create_session(
        operator_id=superuser.id,
        client_brief="Active session " + "a" * 50,
        prospect_name=None,
        client_id=None,
        db=db,
    )
    # Create and abandon a session
    s2 = create_session(
        operator_id=superuser.id,
        client_brief="Abandoned session " + "b" * 50,
        prospect_name=None,
        client_id=None,
        db=db,
    )
    db.flush()
    abandon_session(session_id=s2.id, reason="Testing filter", db=db)
    db.flush()

    # Filter by "abandoned"
    result = list_sessions(db=db, status_filter="abandoned")

    # All returned items should be abandoned
    for item in result["items"]:
        assert item.status == "abandoned"

    # Filter by "in_progress"
    result_active = list_sessions(db=db, status_filter="in_progress")
    for item in result_active["items"]:
        assert item.status == "in_progress"


def test_update_ai_cost_atomic_increment(db: Session, superuser):
    """update_ai_cost atomically increments total_ai_cost_usd."""
    session = create_session(
        operator_id=superuser.id,
        client_brief="G" * 100,
        prospect_name=None,
        client_id=None,
        db=db,
    )
    db.flush()

    # Increment twice
    update_ai_cost(session_id=session.id, cost_delta=0.05, db=db)
    update_ai_cost(session_id=session.id, cost_delta=0.03, db=db)
    db.flush()

    # Refresh to see the updated value
    db.refresh(session)
    assert float(session.total_ai_cost_usd) == pytest.approx(0.08, abs=0.001)


def test_update_ai_cost_rejects_zero_or_negative(db: Session, superuser):
    """update_ai_cost rejects non-positive cost_delta."""
    session = create_session(
        operator_id=superuser.id,
        client_brief="H" * 100,
        prospect_name=None,
        client_id=None,
        db=db,
    )
    db.flush()

    with pytest.raises(ValueError, match="must be positive"):
        update_ai_cost(session_id=session.id, cost_delta=0, db=db)

    with pytest.raises(ValueError, match="must be positive"):
        update_ai_cost(session_id=session.id, cost_delta=-0.01, db=db)
