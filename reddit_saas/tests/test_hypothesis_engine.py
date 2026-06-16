"""Unit tests for Discovery Engine hypothesis engine service.

Tests cover:
- Happy path: 5 valid hypotheses returned
- Dedup: prior statements excluded from output
- Retry logic: first call returns 2, retry returns 3 more → total 5
- Category validation: invalid category rejected
- Provenance JSONB stored correctly
- confidence_score = 50 for all new hypotheses
"""

import asyncio
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.discovery_entity import DiscoveryEntity
from app.models.discovery_hypothesis import DiscoveryHypothesis
from app.models.discovery_session import DiscoverySession
from app.services.discovery.hypothesis_engine import form_hypotheses


# --- Fixtures ---


@pytest.fixture
def mock_db():
    """Mock SQLAlchemy session."""
    db = MagicMock()
    db.add = MagicMock()
    db.flush = MagicMock()
    db.commit = MagicMock()
    return db


@pytest.fixture
def mock_session():
    """Mock DiscoverySession."""
    session = MagicMock(spec=DiscoverySession)
    session.id = uuid.uuid4()
    session.current_iteration = 1
    session.client_brief = "A wellness tech company building AI-powered yoga apps"
    return session


@pytest.fixture
def mock_entities():
    """Mock list of DiscoveryEntity objects."""
    entities = []
    data = [
        ("NeuroYoga App", "product"),
        ("Yoga Practitioners", "audience"),
        ("Meditation Fatigue", "problem"),
        ("Wellness Tech", "industry"),
        ("Headspace", "competitor"),
    ]
    for name, category in data:
        e = MagicMock(spec=DiscoveryEntity)
        e.id = uuid.uuid4()
        e.name = name
        e.category = category
        entities.append(e)
    return entities


# --- Mock LLM Responses ---


def _make_hypothesis_result(hypotheses: list[dict]) -> dict:
    """Build a mock call_llm_json response with hypothesis data."""
    return {
        "content": "{}",
        "input_tokens": 800,
        "output_tokens": 400,
        "cost_usd": 0.0005,
        "duration_ms": 2000,
        "model": "gemini/gemini-2.5-flash-lite",
        "data": {"hypotheses": hypotheses},
    }


VALID_HYPOTHESES_5 = [
    {
        "statement": "Yoga practitioners discuss app recommendations in r/yoga (50K+ subscribers) with 20+ posts/month",
        "category": "clients",
        "triggering_entities": ["NeuroYoga App", "Yoga Practitioners"],
        "reasoning": "Active audience seeking app recommendations",
    },
    {
        "statement": "Wellness tech companies find partnership signals in r/meditation (30K subscribers) with 15+ engagement",
        "category": "partners",
        "triggering_entities": ["Wellness Tech"],
        "reasoning": "Partnership discussions in adjacent communities",
    },
    {
        "statement": "Users provide feedback about meditation apps in r/mindfulness with 10+ comments per thread",
        "category": "feedback",
        "triggering_entities": ["Meditation Fatigue", "NeuroYoga App"],
        "reasoning": "Direct user sentiment about competing products",
    },
    {
        "statement": "Headspace alternatives are discussed weekly in r/meditation reaching 5K+ views",
        "category": "recognition",
        "triggering_entities": ["Headspace"],
        "reasoning": "Competitor brand discussions create positioning opportunities",
    },
    {
        "statement": "r/yogateachers (10K subscribers) discusses tech tools with average 12 upvotes per post",
        "category": "market_research",
        "triggering_entities": ["Yoga Practitioners", "Wellness Tech"],
        "reasoning": "Market intelligence from practitioner-focused communities",
    },
]

VALID_HYPOTHESES_2 = VALID_HYPOTHESES_5[:2]

VALID_HYPOTHESES_3_RETRY = [
    {
        "statement": "Hiring for wellness tech roles discussed in r/cscareerquestions with 20+ posts/month",
        "category": "hiring",
        "triggering_entities": ["Wellness Tech"],
        "reasoning": "Talent acquisition signal in tech communities",
    },
    {
        "statement": "Market research on meditation market trends in r/startups with 10+ engagement",
        "category": "market_research",
        "triggering_entities": ["Wellness Tech", "Meditation Fatigue"],
        "reasoning": "Industry trends discussed in startup communities",
    },
    {
        "statement": "User feedback on wellness apps in r/apps with 25+ posts/month",
        "category": "feedback",
        "triggering_entities": ["NeuroYoga App"],
        "reasoning": "App review community provides user sentiment data",
    },
]


# --- Tests ---


@patch("app.services.discovery.session_manager.update_ai_cost")
@patch("app.services.discovery.hypothesis_engine.call_llm_json")
@patch("app.services.discovery.hypothesis_engine.log_ai_usage")
def test_happy_path_5_hypotheses(mock_log, mock_llm, mock_cost, mock_db, mock_session, mock_entities):
    """5 valid hypotheses returned and stored."""
    mock_llm.return_value = _make_hypothesis_result(VALID_HYPOTHESES_5)

    result = asyncio.run(form_hypotheses(
        entities=mock_entities,
        session=mock_session,
        db=mock_db,
    ))

    assert len(result) == 5
    for h in result:
        assert isinstance(h, DiscoveryHypothesis)
    assert mock_db.add.call_count == 5
    mock_db.flush.assert_called()
    mock_db.commit.assert_called_once()


@patch("app.services.discovery.session_manager.update_ai_cost")
@patch("app.services.discovery.hypothesis_engine.call_llm_json")
@patch("app.services.discovery.hypothesis_engine.log_ai_usage")
def test_dedup_prior_statements(mock_log, mock_llm, mock_cost, mock_db, mock_session, mock_entities):
    """Prior hypothesis statements are excluded from output."""
    # Create prior hypotheses matching first 2 items
    prior = []
    for item in VALID_HYPOTHESES_5[:2]:
        h = MagicMock(spec=DiscoveryHypothesis)
        h.statement = item["statement"]
        h.status = "confirmed"
        h.confidence_score = 70
        prior.append(h)

    # LLM returns all 5 (including duplicates of prior)
    mock_llm.return_value = _make_hypothesis_result(VALID_HYPOTHESES_5)

    result = asyncio.run(form_hypotheses(
        entities=mock_entities,
        session=mock_session,
        prior_hypotheses=prior,
        db=mock_db,
    ))

    # Only 3 should be stored (the 2 duplicates are excluded)
    assert len(result) == 3
    result_statements = {h.statement for h in result}
    for prior_h in prior:
        assert prior_h.statement not in result_statements


@patch("app.services.discovery.session_manager.update_ai_cost")
@patch("app.services.discovery.hypothesis_engine.call_llm_json")
@patch("app.services.discovery.hypothesis_engine.log_ai_usage")
def test_retry_logic(mock_log, mock_llm, mock_cost, mock_db, mock_session, mock_entities):
    """First call returns 2 (<3), retry returns 3 more → total 5."""
    # First call returns only 2
    first_result = _make_hypothesis_result(VALID_HYPOTHESES_2)
    # Retry returns 3 more (different statements)
    retry_result = _make_hypothesis_result(VALID_HYPOTHESES_3_RETRY)

    mock_llm.side_effect = [first_result, retry_result]

    result = asyncio.run(form_hypotheses(
        entities=mock_entities,
        session=mock_session,
        db=mock_db,
    ))

    # Should have combined both batches (2 + 3 = 5)
    assert len(result) == 5
    # LLM was called twice (initial + retry)
    assert mock_llm.call_count == 2


@patch("app.services.discovery.session_manager.update_ai_cost")
@patch("app.services.discovery.hypothesis_engine.call_llm_json")
@patch("app.services.discovery.hypothesis_engine.log_ai_usage")
def test_invalid_category_rejected(mock_log, mock_llm, mock_cost, mock_db, mock_session, mock_entities):
    """Invalid category is filtered out during validation."""
    hypotheses_with_invalid = [
        {
            "statement": "Valid hypothesis about yoga with 20+ posts",
            "category": "clients",
            "triggering_entities": ["NeuroYoga App"],
            "reasoning": "Valid reasoning",
        },
        {
            "statement": "Invalid category hypothesis about social",
            "category": "social_media",  # Invalid category
            "triggering_entities": ["Wellness Tech"],
            "reasoning": "Invalid reasoning",
        },
        {
            "statement": "Another valid hypothesis about partners with 15 engagement",
            "category": "partners",
            "triggering_entities": ["Wellness Tech"],
            "reasoning": "Valid reasoning 2",
        },
        {
            "statement": "Third valid hypothesis about feedback in communities",
            "category": "feedback",
            "triggering_entities": ["Meditation Fatigue"],
            "reasoning": "Valid reasoning 3",
        },
    ]
    mock_llm.return_value = _make_hypothesis_result(hypotheses_with_invalid)

    result = asyncio.run(form_hypotheses(
        entities=mock_entities,
        session=mock_session,
        db=mock_db,
    ))

    # Only 3 valid (the "social_media" one is filtered out)
    assert len(result) == 3
    categories = {h.category for h in result}
    assert "social_media" not in categories


@patch("app.services.discovery.session_manager.update_ai_cost")
@patch("app.services.discovery.hypothesis_engine.call_llm_json")
@patch("app.services.discovery.hypothesis_engine.log_ai_usage")
def test_provenance_stored_correctly(mock_log, mock_llm, mock_cost, mock_db, mock_session, mock_entities):
    """Provenance JSONB includes triggering_entities, reasoning, and prompt_hash."""
    mock_llm.return_value = _make_hypothesis_result(VALID_HYPOTHESES_5)

    result = asyncio.run(form_hypotheses(
        entities=mock_entities,
        session=mock_session,
        db=mock_db,
    ))

    for h in result:
        provenance = h.provenance
        assert "triggering_entities" in provenance
        assert "reasoning" in provenance
        assert "llm_prompt_hash" in provenance
        assert isinstance(provenance["triggering_entities"], list)
        assert isinstance(provenance["reasoning"], str)
        assert len(provenance["reasoning"]) > 0


@patch("app.services.discovery.session_manager.update_ai_cost")
@patch("app.services.discovery.hypothesis_engine.call_llm_json")
@patch("app.services.discovery.hypothesis_engine.log_ai_usage")
def test_confidence_score_50_for_new(mock_log, mock_llm, mock_cost, mock_db, mock_session, mock_entities):
    """All new hypotheses get confidence_score = 50 (neutral)."""
    mock_llm.return_value = _make_hypothesis_result(VALID_HYPOTHESES_5)

    result = asyncio.run(form_hypotheses(
        entities=mock_entities,
        session=mock_session,
        db=mock_db,
    ))

    for h in result:
        assert h.confidence_score == 50
        assert h.confidence_delta == 0
