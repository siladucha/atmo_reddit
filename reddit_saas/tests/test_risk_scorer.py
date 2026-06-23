"""Unit tests for the risk_scorer service.

Tests cover:
- compute_risk_score() with weighted formula
- Individual sub-score computations
- refresh_all_risk_scores() batch behavior (history, spike, high_risk flags)
- Edge cases: insufficient data, empty history, boundary scores
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from app.models.subreddit_risk_profile import SubredditRiskProfile
from app.services.risk_scorer import (
    AGGRESSIVENESS_MAP,
    HIGH_RISK_THRESHOLD,
    INSUFFICIENT_DATA_SCORE,
    RISK_SCORE_HISTORY_WEEKS,
    SPIKE_THRESHOLD,
    WEIGHT_AGGRESSIVENESS,
    WEIGHT_REMOVAL_RATE,
    WEIGHT_RULE_STRICTNESS,
    WEIGHT_TREND_DIRECTION,
    _compute_aggressiveness_score,
    _compute_removal_rate_score,
    _compute_rule_strictness_score,
    _compute_trend_direction_score,
    compute_risk_score,
    refresh_all_risk_scores,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    *,
    removal_rate: float = 0.0,
    aggressiveness: str = "low",
    extracted_rules: list | None = None,
    risk_score_history: list | None = None,
    confidence_level: str = "medium",
    risk_score: int = 50,
) -> SubredditRiskProfile:
    """Create a SubredditRiskProfile instance for testing (not persisted)."""
    profile = SubredditRiskProfile(
        id=uuid.uuid4(),
        subreddit_id=uuid.uuid4(),
        risk_score=risk_score,
        risk_score_history=risk_score_history or [],
        extracted_rules=extracted_rules or [],
        moderation_profile={
            "removal_rate": removal_rate,
            "aggressiveness": aggressiveness,
        },
        confidence_level=confidence_level,
    )
    return profile


# ---------------------------------------------------------------------------
# Tests: _compute_removal_rate_score
# ---------------------------------------------------------------------------


class TestRemovalRateScore:
    """Tests for _compute_removal_rate_score."""

    def test_zero_removal(self):
        profile = _make_profile(removal_rate=0.0)
        assert _compute_removal_rate_score(profile) == 0.0

    def test_full_removal(self):
        profile = _make_profile(removal_rate=1.0)
        assert _compute_removal_rate_score(profile) == 100.0

    def test_half_removal(self):
        profile = _make_profile(removal_rate=0.5)
        assert _compute_removal_rate_score(profile) == 50.0

    def test_linear_mapping(self):
        profile = _make_profile(removal_rate=0.32)
        assert abs(_compute_removal_rate_score(profile) - 32.0) < 0.01

    def test_clamps_above_one(self):
        """Values above 1.0 should clamp to 100."""
        profile = _make_profile(removal_rate=1.5)
        assert _compute_removal_rate_score(profile) == 100.0

    def test_clamps_below_zero(self):
        """Negative values should clamp to 0."""
        profile = _make_profile(removal_rate=-0.1)
        assert _compute_removal_rate_score(profile) == 0.0

    def test_missing_moderation_profile(self):
        """If moderation_profile is None/empty, default to 0."""
        profile = _make_profile()
        profile.moderation_profile = None
        assert _compute_removal_rate_score(profile) == 0.0


# ---------------------------------------------------------------------------
# Tests: _compute_aggressiveness_score
# ---------------------------------------------------------------------------


class TestAggressivenessScore:
    """Tests for _compute_aggressiveness_score."""

    def test_low(self):
        profile = _make_profile(aggressiveness="low")
        assert _compute_aggressiveness_score(profile) == 10.0

    def test_medium(self):
        profile = _make_profile(aggressiveness="medium")
        assert _compute_aggressiveness_score(profile) == 40.0

    def test_high(self):
        profile = _make_profile(aggressiveness="high")
        assert _compute_aggressiveness_score(profile) == 70.0

    def test_extreme(self):
        profile = _make_profile(aggressiveness="extreme")
        assert _compute_aggressiveness_score(profile) == 100.0

    def test_unknown_defaults_to_low(self):
        """Unknown aggressiveness level defaults to 10 (low)."""
        profile = _make_profile(aggressiveness="unknown_level")
        assert _compute_aggressiveness_score(profile) == 10.0

    def test_missing_aggressiveness_key(self):
        """If aggressiveness key is missing, default to low."""
        profile = _make_profile()
        profile.moderation_profile = {"removal_rate": 0.1}
        assert _compute_aggressiveness_score(profile) == 10.0


# ---------------------------------------------------------------------------
# Tests: _compute_rule_strictness_score
# ---------------------------------------------------------------------------


class TestRuleStrictnessScore:
    """Tests for _compute_rule_strictness_score."""

    def test_zero_rules(self):
        profile = _make_profile(extracted_rules=[])
        assert _compute_rule_strictness_score(profile) == 0.0

    def test_one_rule(self):
        profile = _make_profile(extracted_rules=[{"category": "min_karma"}])
        assert _compute_rule_strictness_score(profile) == 12.0

    def test_five_rules(self):
        rules = [{"category": "rule"} for _ in range(5)]
        profile = _make_profile(extracted_rules=rules)
        assert _compute_rule_strictness_score(profile) == 60.0

    def test_caps_at_100(self):
        """More than 8 rules should cap at 100 (9 * 12 = 108 → 100)."""
        rules = [{"category": "rule"} for _ in range(9)]
        profile = _make_profile(extracted_rules=rules)
        assert _compute_rule_strictness_score(profile) == 100.0

    def test_exactly_at_cap(self):
        """8 rules: 8 * 12 = 96 (just under cap)."""
        rules = [{"category": "rule"} for _ in range(8)]
        profile = _make_profile(extracted_rules=rules)
        assert _compute_rule_strictness_score(profile) == 96.0

    def test_none_rules(self):
        """If extracted_rules is None, treat as empty."""
        profile = _make_profile()
        profile.extracted_rules = None
        assert _compute_rule_strictness_score(profile) == 0.0


# ---------------------------------------------------------------------------
# Tests: _compute_trend_direction_score
# ---------------------------------------------------------------------------


class TestTrendDirectionScore:
    """Tests for _compute_trend_direction_score."""

    def test_no_history_returns_neutral(self):
        profile = _make_profile(risk_score_history=[])
        assert _compute_trend_direction_score(profile) == 50.0

    def test_one_entry_returns_neutral(self):
        profile = _make_profile(risk_score_history=[{"week": "2026-W20", "score": 40}])
        assert _compute_trend_direction_score(profile) == 50.0

    def test_flat_trend_returns_neutral(self):
        """Same score each week → slope = 0 → result = 50."""
        history = [{"week": f"2026-W{20+i}", "score": 50} for i in range(4)]
        profile = _make_profile(risk_score_history=history)
        assert _compute_trend_direction_score(profile) == 50.0

    def test_increasing_trend(self):
        """Increasing scores → positive slope → result > 50."""
        history = [
            {"week": "2026-W20", "score": 30},
            {"week": "2026-W21", "score": 40},
            {"week": "2026-W22", "score": 50},
            {"week": "2026-W23", "score": 60},
        ]
        profile = _make_profile(risk_score_history=history)
        result = _compute_trend_direction_score(profile)
        assert result > 50.0

    def test_decreasing_trend(self):
        """Decreasing scores → negative slope → result < 50."""
        history = [
            {"week": "2026-W20", "score": 80},
            {"week": "2026-W21", "score": 70},
            {"week": "2026-W22", "score": 60},
            {"week": "2026-W23", "score": 50},
        ]
        profile = _make_profile(risk_score_history=history)
        result = _compute_trend_direction_score(profile)
        assert result < 50.0

    def test_uses_last_four_weeks_only(self):
        """With 6 weeks of history, only the last 4 should be used."""
        history = [
            {"week": "2026-W18", "score": 90},
            {"week": "2026-W19", "score": 80},
            # Last 4:
            {"week": "2026-W20", "score": 30},
            {"week": "2026-W21", "score": 40},
            {"week": "2026-W22", "score": 50},
            {"week": "2026-W23", "score": 60},
        ]
        profile = _make_profile(risk_score_history=history)
        result = _compute_trend_direction_score(profile)
        # Should reflect increasing trend from 30→60, ignoring early 90→80
        assert result > 50.0

    def test_result_clamped_to_range(self):
        """Even extreme slopes should stay in 0-100."""
        history = [
            {"week": "2026-W20", "score": 0},
            {"week": "2026-W21", "score": 100},
        ]
        profile = _make_profile(risk_score_history=history)
        result = _compute_trend_direction_score(profile)
        assert 0.0 <= result <= 100.0


# ---------------------------------------------------------------------------
# Tests: compute_risk_score (composite)
# ---------------------------------------------------------------------------


class TestComputeRiskScore:
    """Tests for compute_risk_score (full weighted computation)."""

    def test_insufficient_data_returns_50(self):
        """Req 4.7: insufficient data → always 50."""
        profile = _make_profile(
            confidence_level="insufficient_data",
            removal_rate=0.9,
            aggressiveness="extreme",
        )
        assert compute_risk_score(profile) == INSUFFICIENT_DATA_SCORE

    def test_all_zeros_minimal_risk(self):
        """Zero removal, low aggressiveness, no rules, neutral trend → low score."""
        profile = _make_profile(
            removal_rate=0.0,
            aggressiveness="low",
            extracted_rules=[],
            confidence_level="high",
        )
        # Expected: 0*0.4 + 10*0.25 + 0*0.2 + 50*0.15 = 0 + 2.5 + 0 + 7.5 = 10
        assert compute_risk_score(profile) == 10

    def test_maximum_risk(self):
        """All sub-scores at max → 100."""
        history = [
            {"week": "2026-W20", "score": 0},
            {"week": "2026-W21", "score": 25},
            {"week": "2026-W22", "score": 50},
            {"week": "2026-W23", "score": 75},
        ]
        profile = _make_profile(
            removal_rate=1.0,
            aggressiveness="extreme",
            extracted_rules=[{"cat": "r"} for _ in range(10)],  # 10*12=120→100
            risk_score_history=history,
            confidence_level="high",
        )
        result = compute_risk_score(profile)
        # removal: 100*0.4=40, aggr: 100*0.25=25, rules: 100*0.2=20, trend: >50*0.15
        assert result >= 85  # Should be close to max

    def test_medium_profile(self):
        """Medium-risk profile produces score in middle range."""
        profile = _make_profile(
            removal_rate=0.25,
            aggressiveness="medium",
            extracted_rules=[{"cat": "r"} for _ in range(3)],  # 3*12=36
            confidence_level="medium",
        )
        result = compute_risk_score(profile)
        # removal: 25*0.4=10, aggr: 40*0.25=10, rules: 36*0.2=7.2, trend: 50*0.15=7.5
        # Total ≈ 34.7 → 35
        assert 30 <= result <= 40

    def test_result_always_integer(self):
        """Result should always be an integer."""
        profile = _make_profile(
            removal_rate=0.33,
            aggressiveness="high",
            extracted_rules=[{"cat": "r"}],
            confidence_level="high",
        )
        result = compute_risk_score(profile)
        assert isinstance(result, int)

    def test_result_in_valid_range(self):
        """Result should always be 0-100."""
        profile = _make_profile(
            removal_rate=0.99,
            aggressiveness="extreme",
            extracted_rules=[{"cat": "r"} for _ in range(20)],
            confidence_level="high",
        )
        result = compute_risk_score(profile)
        assert 0 <= result <= 100


# ---------------------------------------------------------------------------
# Tests: refresh_all_risk_scores (integration with DB)
# ---------------------------------------------------------------------------


class TestRefreshAllRiskScores:
    """Tests for refresh_all_risk_scores using real DB session."""

    def test_empty_db_returns_zero_stats(self, db):
        """No profiles → all stats zero."""
        stats = refresh_all_risk_scores(db)
        assert stats["processed"] == 0
        assert stats["updated"] == 0
        assert stats["spikes"] == 0

    def test_computes_score_and_appends_history(self, db):
        """Score is computed and appended to history."""
        from app.models.subreddit import Subreddit

        subreddit = Subreddit(subreddit_name="testsub_scorer1", is_active=True)
        db.add(subreddit)
        db.flush()

        profile = SubredditRiskProfile(
            subreddit_id=subreddit.id,
            risk_score=30,
            risk_score_history=[],
            moderation_profile={"removal_rate": 0.25, "aggressiveness": "medium"},
            extracted_rules=[{"category": "min_karma"}],
            confidence_level="medium",
        )
        db.add(profile)
        db.flush()

        stats = refresh_all_risk_scores(db)

        assert stats["processed"] == 1
        assert stats["updated"] == 1

        # History should have 1 entry
        db.refresh(profile)
        assert len(profile.risk_score_history) == 1
        assert profile.risk_score_history[0]["score"] == profile.risk_score

    def test_history_capped_at_12_weeks(self, db):
        """History should not exceed 12 entries (FIFO eviction)."""
        from app.models.subreddit import Subreddit

        subreddit = Subreddit(subreddit_name="testsub_scorer2", is_active=True)
        db.add(subreddit)
        db.flush()

        # Pre-fill with 12 entries
        existing_history = [
            {"week": f"2026-W{i:02d}", "score": 40 + i} for i in range(12)
        ]
        profile = SubredditRiskProfile(
            subreddit_id=subreddit.id,
            risk_score=50,
            risk_score_history=existing_history,
            moderation_profile={"removal_rate": 0.2, "aggressiveness": "low"},
            extracted_rules=[],
            confidence_level="medium",
        )
        db.add(profile)
        db.flush()

        refresh_all_risk_scores(db)

        db.refresh(profile)
        # Should still be exactly 12 (oldest evicted, new one added)
        assert len(profile.risk_score_history) == RISK_SCORE_HISTORY_WEEKS

    def test_spike_detection_emits_event(self, db):
        """Score increase > 15 emits risk_score_spike event."""
        from app.models.subreddit import Subreddit
        from app.models.activity_event import ActivityEvent

        subreddit = Subreddit(subreddit_name="testsub_scorer3", is_active=True)
        db.add(subreddit)
        db.flush()

        # Current score is 20, new score will be much higher due to extreme config
        profile = SubredditRiskProfile(
            subreddit_id=subreddit.id,
            risk_score=20,  # Previous score
            risk_score_history=[],
            moderation_profile={"removal_rate": 0.8, "aggressiveness": "extreme"},
            extracted_rules=[{"cat": "r"} for _ in range(5)],
            confidence_level="high",
        )
        db.add(profile)
        db.flush()

        stats = refresh_all_risk_scores(db)

        # The new score should be significantly higher than 20
        db.refresh(profile)
        assert profile.risk_score > 20 + SPIKE_THRESHOLD

        # Spike should be detected
        assert stats["spikes"] == 1

        # Activity event should exist
        spike_event = (
            db.query(ActivityEvent)
            .filter(ActivityEvent.event_type == "risk_score_spike")
            .first()
        )
        assert spike_event is not None
        assert "testsub_scorer3" in spike_event.message

    def test_sets_high_risk_flag(self, db):
        """Score > 80 sets is_high_risk on subreddit (Req 4.6)."""
        from app.models.subreddit import Subreddit

        subreddit = Subreddit(
            subreddit_name="testsub_scorer4", is_active=True, is_high_risk=False
        )
        db.add(subreddit)
        db.flush()

        profile = SubredditRiskProfile(
            subreddit_id=subreddit.id,
            risk_score=50,
            risk_score_history=[],
            moderation_profile={"removal_rate": 0.95, "aggressiveness": "extreme"},
            extracted_rules=[{"cat": "r"} for _ in range(10)],
            confidence_level="high",
        )
        db.add(profile)
        db.flush()

        stats = refresh_all_risk_scores(db)

        db.refresh(subreddit)
        db.refresh(profile)

        # Score should exceed 80
        assert profile.risk_score > HIGH_RISK_THRESHOLD
        assert subreddit.is_high_risk is True
        assert stats["high_risk_set"] == 1

    def test_clears_high_risk_flag(self, db):
        """Score <= 80 clears is_high_risk on subreddit (Req 4.8)."""
        from app.models.subreddit import Subreddit

        subreddit = Subreddit(
            subreddit_name="testsub_scorer5", is_active=True, is_high_risk=True
        )
        db.add(subreddit)
        db.flush()

        # Low risk profile — score will be well under 80
        profile = SubredditRiskProfile(
            subreddit_id=subreddit.id,
            risk_score=85,  # Currently marked high risk
            risk_score_history=[],
            moderation_profile={"removal_rate": 0.05, "aggressiveness": "low"},
            extracted_rules=[],
            confidence_level="medium",
        )
        db.add(profile)
        db.flush()

        stats = refresh_all_risk_scores(db)

        db.refresh(subreddit)
        db.refresh(profile)

        # Score should be low (well under 80)
        assert profile.risk_score <= HIGH_RISK_THRESHOLD
        assert subreddit.is_high_risk is False
        assert stats["high_risk_cleared"] == 1

    def test_insufficient_data_assigns_50(self, db):
        """Req 4.7: insufficient data profiles get score 50."""
        from app.models.subreddit import Subreddit

        subreddit = Subreddit(subreddit_name="testsub_scorer6", is_active=True)
        db.add(subreddit)
        db.flush()

        profile = SubredditRiskProfile(
            subreddit_id=subreddit.id,
            risk_score=30,
            risk_score_history=[],
            moderation_profile={"removal_rate": 0.9, "aggressiveness": "extreme"},
            extracted_rules=[{"cat": "r"} for _ in range(10)],
            confidence_level="insufficient_data",
        )
        db.add(profile)
        db.flush()

        refresh_all_risk_scores(db)

        db.refresh(profile)
        assert profile.risk_score == INSUFFICIENT_DATA_SCORE
        assert profile.risk_score == 50
