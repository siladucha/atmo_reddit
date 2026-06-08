"""Unit tests for Discovery Engine confidence scorer service.

Tests cover:
- Strong signal: 3 subreddits with ≥20 posts and ≥10 engagement → score > 50, positive delta
- Weak signal: all subreddits with <5 posts → score < 50, negative delta
- No signal (topic_absent): no broader results → score = 15, no_signal.cause = "topic_absent"
- No signal (search_too_narrow): broader results found → score = 15, no_signal.cause = "search_too_narrow"
- Mixed signals: some strong + some weak → score between 20-80
- Cap at +30 and -30 (never goes above 80 or below 20 from adjustments alone)
- confidence_reasoning text is generated
"""

import uuid
from unittest.mock import MagicMock

import pytest

from app.services.discovery.confidence_scorer import score_hypothesis


# --- Fixtures ---


@pytest.fixture
def mock_hypothesis():
    """Create a mock hypothesis for scoring."""
    h = MagicMock()
    h.id = uuid.uuid4()
    h.statement = "Target audience actively discusses yoga apps in wellness subreddits"
    h.category = "clients"
    h.confidence_score = 50
    return h


# --- Tests ---


def test_strong_signal_score_above_50(mock_hypothesis):
    """3 subreddits with ≥20 posts AND ≥10 avg engagement → score > 50, positive delta."""
    signals = {
        "subreddits": [
            {"name": "r/yoga", "subscribers": 50000, "posts_30d": 25, "avg_engagement": 15, "relevance_score": 80},
            {"name": "r/meditation", "subscribers": 30000, "posts_30d": 30, "avg_engagement": 12, "relevance_score": 70},
            {"name": "r/wellness", "subscribers": 20000, "posts_30d": 22, "avg_engagement": 11, "relevance_score": 65},
        ],
        "total_posts_found": 77,
        "avg_engagement_overall": 12.7,
    }

    result = score_hypothesis(mock_hypothesis, signals)

    assert result["confidence_score"] > 50
    assert result["confidence_delta"] > 0
    assert result["no_signal"] is None


def test_weak_signal_score_below_50(mock_hypothesis):
    """All subreddits with <5 posts → score < 50, negative delta."""
    signals = {
        "subreddits": [
            {"name": "r/niche1", "subscribers": 500, "posts_30d": 2, "avg_engagement": 1, "relevance_score": 30},
            {"name": "r/niche2", "subscribers": 300, "posts_30d": 1, "avg_engagement": 2, "relevance_score": 25},
            {"name": "r/niche3", "subscribers": 200, "posts_30d": 3, "avg_engagement": 1, "relevance_score": 20},
        ],
        "total_posts_found": 6,
        "avg_engagement_overall": 1.3,
    }

    result = score_hypothesis(mock_hypothesis, signals)

    assert result["confidence_score"] < 50
    assert result["confidence_delta"] < 0
    assert result["no_signal"] is None


def test_no_signal_topic_absent(mock_hypothesis):
    """No broader results → score = 15, no_signal.cause = 'topic_absent'."""
    signals = {
        "subreddits": [],
        "total_posts_found": 2,
        "avg_engagement_overall": 0,
        "broader_search": {"posts_found": 3, "terms_used": ["broad term"]},
    }

    result = score_hypothesis(mock_hypothesis, signals)

    assert result["confidence_score"] == 15
    assert result["no_signal"] is not None
    assert result["no_signal"]["cause"] == "topic_absent"
    assert len(result["no_signal"]["suggestions"]) <= 3


def test_no_signal_search_too_narrow(mock_hypothesis):
    """Broader results found (≥10) but primary <5 → score = 15, cause = 'search_too_narrow'."""
    signals = {
        "subreddits": [
            {"name": "r/tiny", "subscribers": 100, "posts_30d": 1, "avg_engagement": 0, "relevance_score": 10},
        ],
        "total_posts_found": 3,
        "avg_engagement_overall": 0,
        "broader_search": {"posts_found": 15, "terms_used": ["broader term", "adjacent topic"]},
    }

    result = score_hypothesis(mock_hypothesis, signals)

    assert result["confidence_score"] == 15
    assert result["no_signal"] is not None
    assert result["no_signal"]["cause"] == "search_too_narrow"
    assert len(result["no_signal"]["suggestions"]) <= 3


def test_mixed_signals_score_between_20_80(mock_hypothesis):
    """Some strong + some weak subreddits → score between 20 and 80."""
    signals = {
        "subreddits": [
            {"name": "r/strong1", "subscribers": 40000, "posts_30d": 25, "avg_engagement": 15, "relevance_score": 80},
            {"name": "r/weak1", "subscribers": 500, "posts_30d": 2, "avg_engagement": 1, "relevance_score": 20},
            {"name": "r/weak2", "subscribers": 300, "posts_30d": 3, "avg_engagement": 2, "relevance_score": 25},
        ],
        "total_posts_found": 30,
        "avg_engagement_overall": 6.0,
    }

    result = score_hypothesis(mock_hypothesis, signals)

    assert 20 <= result["confidence_score"] <= 80
    assert result["no_signal"] is None


def test_cap_at_plus_30(mock_hypothesis):
    """5 strong subreddits → bonus capped at +30 (score never exceeds 80 from bonus alone)."""
    signals = {
        "subreddits": [
            {"name": f"r/strong{i}", "subscribers": 50000, "posts_30d": 30, "avg_engagement": 20, "relevance_score": 90}
            for i in range(5)
        ],
        "total_posts_found": 150,
        "avg_engagement_overall": 20.0,
    }

    result = score_hypothesis(mock_hypothesis, signals)

    # Base 50 + cap 30 = max 80 (no weak subs to subtract)
    assert result["confidence_score"] <= 80
    assert result["confidence_delta"] <= 30


def test_cap_at_minus_30(mock_hypothesis):
    """5 weak subreddits → penalty capped at -30 (score never below 20 from penalty alone)."""
    signals = {
        "subreddits": [
            {"name": f"r/weak{i}", "subscribers": 100, "posts_30d": 1, "avg_engagement": 0, "relevance_score": 5}
            for i in range(5)
        ],
        "total_posts_found": 5,
        "avg_engagement_overall": 0.2,
    }

    result = score_hypothesis(mock_hypothesis, signals)

    # Base 50 - cap 30 = min 20 (no strong subs to add)
    assert result["confidence_score"] >= 20
    assert result["confidence_delta"] >= -30


def test_confidence_reasoning_generated(mock_hypothesis):
    """confidence_reasoning text is always a non-empty string."""
    signals = {
        "subreddits": [
            {"name": "r/test", "subscribers": 10000, "posts_30d": 15, "avg_engagement": 8, "relevance_score": 60},
        ],
        "total_posts_found": 15,
        "avg_engagement_overall": 8.0,
    }

    result = score_hypothesis(mock_hypothesis, signals)

    assert "confidence_reasoning" in result
    assert isinstance(result["confidence_reasoning"], str)
    assert len(result["confidence_reasoning"]) > 10
