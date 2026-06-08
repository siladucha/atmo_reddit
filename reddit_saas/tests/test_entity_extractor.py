"""Unit tests for Discovery Engine entity extractor service.

Tests cover:
- Happy path: valid entities extracted and stored
- Edge case: fewer than 3 entities → insufficient=True
- Edge case: malformed JSON from LLM → raises ValueError
- Edge case: empty entities list → raises ValueError
- Entities stored in DB
- Timeout handling
"""

import asyncio
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.discovery_entity import DiscoveryEntity
from app.services.discovery.entity_extractor import extract_entities


# --- Fixtures ---


@pytest.fixture
def mock_db():
    """Mock SQLAlchemy session for unit tests."""
    db = MagicMock()
    db.add = MagicMock()
    db.flush = MagicMock()
    db.commit = MagicMock()
    return db


@pytest.fixture
def session_id():
    return uuid.uuid4()


# --- Mock LLM Responses ---


def _make_llm_result(entities: list[dict]) -> dict:
    """Build a mock call_llm_json response with entity data."""
    return {
        "content": '{"entities": [...]}',
        "input_tokens": 500,
        "output_tokens": 200,
        "cost_usd": 0.0003,
        "duration_ms": 1200,
        "model": "gemini/gemini-2.5-flash-lite",
        "data": {"entities": entities},
    }


VALID_ENTITIES_5 = [
    {"name": "NeuroYoga App", "category": "product"},
    {"name": "Yoga Practitioners", "category": "audience"},
    {"name": "Meditation Fatigue", "category": "problem"},
    {"name": "Wellness Tech", "category": "industry"},
    {"name": "Headspace", "category": "competitor"},
]

VALID_ENTITIES_2 = [
    {"name": "SaaS Platform", "category": "product"},
    {"name": "Developers", "category": "audience"},
]

MALFORMED_DATA_NO_ENTITIES_KEY = {
    "content": '{"items": []}',
    "input_tokens": 100,
    "output_tokens": 50,
    "cost_usd": 0.0001,
    "duration_ms": 800,
    "model": "gemini/gemini-2.5-flash-lite",
    "data": {"items": []},  # wrong key — no "entities"
}

EMPTY_ENTITIES = {
    "content": '{"entities": []}',
    "input_tokens": 100,
    "output_tokens": 50,
    "cost_usd": 0.0001,
    "duration_ms": 800,
    "model": "gemini/gemini-2.5-flash-lite",
    "data": {"entities": []},
}


# --- Tests ---


@patch("app.services.discovery.session_manager.update_ai_cost")
@patch("app.services.discovery.entity_extractor.call_llm_json")
@patch("app.services.discovery.entity_extractor.log_ai_usage")
def test_extract_entities_happy_path(mock_log, mock_llm, mock_cost, mock_db, session_id):
    """5 valid entities returned across categories → stored in DB, insufficient=False."""
    mock_llm.return_value = _make_llm_result(VALID_ENTITIES_5)

    result = asyncio.run(extract_entities(
        client_brief="A" * 100,
        db=mock_db,
        session_id=session_id,
    ))

    assert result["count"] == 5
    assert result["insufficient"] is False
    assert len(result["entities"]) == 5
    # Verify entities are DiscoveryEntity instances
    for entity in result["entities"]:
        assert isinstance(entity, DiscoveryEntity)
    # Verify db.add was called for each entity
    assert mock_db.add.call_count == 5
    mock_db.flush.assert_called_once()
    mock_db.commit.assert_called_once()


@patch("app.services.discovery.session_manager.update_ai_cost")
@patch("app.services.discovery.entity_extractor.call_llm_json")
@patch("app.services.discovery.entity_extractor.log_ai_usage")
def test_extract_entities_insufficient(mock_log, mock_llm, mock_cost, mock_db, session_id):
    """Fewer than 3 entities → returns insufficient=True."""
    mock_llm.return_value = _make_llm_result(VALID_ENTITIES_2)

    result = asyncio.run(extract_entities(
        client_brief="B" * 100,
        db=mock_db,
        session_id=session_id,
    ))

    assert result["count"] == 2
    assert result["insufficient"] is True
    assert len(result["entities"]) == 2


@patch("app.services.discovery.entity_extractor.call_llm_json")
@patch("app.services.discovery.entity_extractor.log_ai_usage")
def test_extract_entities_malformed_json_no_key(mock_log, mock_llm, mock_db, session_id):
    """LLM returns JSON without 'entities' key → raises ValueError."""
    mock_llm.return_value = MALFORMED_DATA_NO_ENTITIES_KEY

    with pytest.raises(ValueError, match="no entities key"):
        asyncio.run(extract_entities(
            client_brief="C" * 100,
            db=mock_db,
            session_id=session_id,
        ))


@patch("app.services.discovery.entity_extractor.call_llm_json")
@patch("app.services.discovery.entity_extractor.log_ai_usage")
def test_extract_entities_empty_list(mock_log, mock_llm, mock_db, session_id):
    """LLM returns empty entities list → raises ValueError."""
    mock_llm.return_value = EMPTY_ENTITIES

    with pytest.raises(ValueError, match="empty entities list"):
        asyncio.run(extract_entities(
            client_brief="D" * 100,
            db=mock_db,
            session_id=session_id,
        ))


@patch("app.services.discovery.session_manager.update_ai_cost")
@patch("app.services.discovery.entity_extractor.call_llm_json")
@patch("app.services.discovery.entity_extractor.log_ai_usage")
def test_extract_entities_stored_in_db(mock_log, mock_llm, mock_cost, mock_db, session_id):
    """Entities are stored in DB with correct fields."""
    mock_llm.return_value = _make_llm_result(VALID_ENTITIES_5)

    result = asyncio.run(extract_entities(
        client_brief="E" * 100,
        db=mock_db,
        session_id=session_id,
    ))

    # Verify each entity has correct session_id and source
    for entity in result["entities"]:
        assert entity.session_id == session_id
        assert entity.source == "extracted"

    # Verify categories match input
    categories = {e.category for e in result["entities"]}
    assert "product" in categories
    assert "audience" in categories
    assert "problem" in categories
    assert "industry" in categories
    assert "competitor" in categories


@patch("app.services.discovery.entity_extractor.call_llm_json")
@patch("app.services.discovery.entity_extractor.log_ai_usage")
def test_extract_entities_timeout(mock_log, mock_llm, mock_db, session_id):
    """LLM call exceeds 30s timeout → raises TimeoutError."""

    def slow_llm(*args, **kwargs):
        import time
        time.sleep(60)
        return _make_llm_result(VALID_ENTITIES_5)

    mock_llm.side_effect = slow_llm

    # The extract_entities function has internal asyncio.wait_for(timeout=30.0)
    # We patch the timeout to 0.01 to make test fast
    with patch("app.services.discovery.entity_extractor.asyncio.wait_for", side_effect=asyncio.TimeoutError()):
        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            asyncio.run(extract_entities(
                client_brief="F" * 100,
                db=mock_db,
                session_id=session_id,
            ))
