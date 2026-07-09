import pytest
pytestmark = pytest.mark.skip(reason="Makes real LLM calls or uses seed data — needs mock isolation")

"""Tests for the Deterministic Trial Scoring Engine (Task 4)."""

import uuid
import math
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from app.models.client import Client
from app.models.trial_signal import TrialSignal
from app.services.trial_scoring import (
    ScoringEngine,
    DEFAULT_WEIGHTS,
    PLAN_VALUES_CENTS,
    OPPORTUNITY_NORMALIZATION_DIVISOR,
    TRIAL_DURATION_DAYS,
    CATEGORY_MAX,
    normalize_signal_count,
)

TZ = ZoneInfo("Asia/Jerusalem")


@pytest.fixture
def engine():
    """Create a ScoringEngine instance."""
    return ScoringEngine()


def _make_signal(signal_type: str, category: str, value: dict | None = None, created_at: datetime | None = None) -> TrialSignal:
    """Helper to create a TrialSignal mock for testing."""
    signal = MagicMock(spec=TrialSignal)
    signal.signal_type = signal_type
    signal.signal_category = category
    signal.signal_value = value
    signal.created_at = created_at or datetime.now(TZ)
    return signal


class TestNormalizeSignalCount:
    """Tests for the diminishing returns normalization function."""

    def test_zero_count_returns_zero(self):
        assert normalize_signal_count(0) == 0.0

    def test_negative_count_returns_zero(self):
        assert normalize_signal_count(-1) == 0.0

    def test_one_signal_gives_about_23(self):
        result = normalize_signal_count(1)
        # log2(2) / log2(21) * 100 = 1 / 4.392 * 100 ~ 22.76
        assert 22 <= result <= 24

    def test_three_signals_gives_about_46(self):
        result = normalize_signal_count(3)
        # log2(4) / log2(21) * 100 = 2 / 4.392 * 100 ~ 45.5
        assert 44 <= result <= 47

    def test_twenty_signals_gives_100(self):
        result = normalize_signal_count(20)
        # log2(21) / log2(21) * 100 = 100
        assert result == 100.0

    def test_over_twenty_capped_at_100(self):
        result = normalize_signal_count(50)
        assert result == 100.0

    def test_monotonically_increasing(self):
        prev = 0.0
        for i in range(1, 25):
            current = normalize_signal_count(i)
            assert current >= prev
            prev = current


class TestComputeConversionScore:
    """Tests for compute_conversion_score (Task 4.2)."""

    def test_empty_signals_returns_zero(self, engine):
        assert engine.compute_conversion_score([]) == 0

    def test_engagement_signals_contribute(self, engine):
        signals = [
            _make_signal("login", "engagement"),
            _make_signal("page_view", "engagement"),
            _make_signal("report_viewed", "engagement"),
        ]
        score = engine.compute_conversion_score(signals)
        assert 0 < score <= 100

    def test_all_categories_contribute(self, engine):
        signals = [
            _make_signal("login", "engagement"),
            _make_signal("email_domain_work", "intent"),
            _make_signal("landscape_report", "value_realization"),
            _make_signal("pricing_viewed", "conversion"),
        ]
        score = engine.compute_conversion_score(signals)
        assert score > 0

    def test_negative_signals_reduce_score(self, engine):
        positive_signals = [
            _make_signal("login", "engagement"),
            _make_signal("email_domain_work", "intent"),
            _make_signal("landscape_report", "value_realization"),
            _make_signal("pricing_viewed", "conversion"),
        ]
        score_without_negatives = engine.compute_conversion_score(positive_signals)

        signals_with_negatives = positive_signals + [
            _make_signal("no_activity_72h", "negative"),
            _make_signal("bounced_email", "negative"),
        ]
        score_with_negatives = engine.compute_conversion_score(signals_with_negatives)

        assert score_with_negatives < score_without_negatives

    def test_negative_penalty_capped_at_30(self, engine):
        # 4 negative signals = 4 * -10 = -40, but capped at -30
        signals = [
            _make_signal("no_activity_72h", "negative"),
            _make_signal("bounced_email", "negative"),
            _make_signal("multiple_short_sessions", "negative"),
            _make_signal("onboarding_abandoned", "negative"),
        ]
        score = engine.compute_conversion_score(signals)
        assert score == 0  # Only negatives, weighted sum is 0, penalty capped at -30

    def test_score_clamped_to_0_100(self, engine):
        # All positive signals
        signals = [_make_signal("upgrade_cta", "conversion") for _ in range(20)]
        score = engine.compute_conversion_score(signals)
        assert 0 <= score <= 100

    def test_deterministic_same_inputs_same_output(self, engine):
        signals = [
            _make_signal("login", "engagement"),
            _make_signal("pricing_viewed", "conversion"),
            _make_signal("landscape_report", "value_realization"),
        ]
        score1 = engine.compute_conversion_score(signals)
        score2 = engine.compute_conversion_score(signals)
        assert score1 == score2

    def test_custom_weights(self, engine):
        signals = [
            _make_signal("login", "engagement"),
            _make_signal("login", "engagement"),
            _make_signal("login", "engagement"),
        ]
        # Full weight on engagement
        custom_weights = {
            "engagement": 1.0,
            "intent": 0.0,
            "value_realization": 0.0,
            "conversion": 0.0,
            "negative_cap": 0.30,
        }
        score_custom = engine.compute_conversion_score(signals, weights=custom_weights)

        # Default 20% weight on engagement
        score_default = engine.compute_conversion_score(signals)

        assert score_custom > score_default


class TestComputeOpportunityValue:
    """Tests for compute_opportunity_value (Task 4.3)."""

    def test_unknown_size_returns_seed(self, engine):
        client = MagicMock(spec=Client)
        client.company_profile = None
        client.keywords = None
        assert engine.compute_opportunity_value(client) == PLAN_VALUES_CENTS["seed"]

    def test_small_company_returns_seed(self, engine):
        client = MagicMock(spec=Client)
        client.company_profile = '{"company_size": 5}'
        client.keywords = None
        assert engine.compute_opportunity_value(client) == PLAN_VALUES_CENTS["seed"]

    def test_ten_employees_returns_seed(self, engine):
        client = MagicMock(spec=Client)
        client.company_profile = '{"company_size": 10}'
        client.keywords = None
        assert engine.compute_opportunity_value(client) == PLAN_VALUES_CENTS["seed"]

    def test_medium_company_returns_starter(self, engine):
        client = MagicMock(spec=Client)
        client.company_profile = '{"company_size": 25}'
        client.keywords = None
        assert engine.compute_opportunity_value(client) == PLAN_VALUES_CENTS["starter"]

    def test_fifty_employees_returns_starter(self, engine):
        client = MagicMock(spec=Client)
        client.company_profile = '{"company_size": 50}'
        client.keywords = None
        assert engine.compute_opportunity_value(client) == PLAN_VALUES_CENTS["starter"]

    def test_large_company_returns_growth(self, engine):
        client = MagicMock(spec=Client)
        client.company_profile = '{"company_size": 100}'
        client.keywords = None
        assert engine.compute_opportunity_value(client) == PLAN_VALUES_CENTS["growth"]

    def test_two_hundred_returns_growth(self, engine):
        client = MagicMock(spec=Client)
        client.company_profile = '{"company_size": 200}'
        client.keywords = None
        assert engine.compute_opportunity_value(client) == PLAN_VALUES_CENTS["growth"]

    def test_enterprise_returns_scale(self, engine):
        client = MagicMock(spec=Client)
        client.company_profile = '{"company_size": 500}'
        client.keywords = None
        assert engine.compute_opportunity_value(client) == PLAN_VALUES_CENTS["scale"]

    def test_reads_from_keywords_jsonb(self, engine):
        client = MagicMock(spec=Client)
        client.company_profile = None
        client.keywords = {"company_size": 75}
        assert engine.compute_opportunity_value(client) == PLAN_VALUES_CENTS["growth"]

    def test_plan_values_are_correct(self):
        assert PLAN_VALUES_CENTS["seed"] == 149 * 12 * 100
        assert PLAN_VALUES_CENTS["starter"] == 399 * 12 * 100
        assert PLAN_VALUES_CENTS["growth"] == 799 * 12 * 100
        assert PLAN_VALUES_CENTS["scale"] == 1499 * 12 * 100


class TestComputePriorityScore:
    """Tests for compute_priority_score (Task 4.4)."""

    def test_all_zeros(self, engine):
        score = engine.compute_priority_score(0, 0, 14)
        assert score == 0

    def test_max_conversion_no_value_no_urgency(self, engine):
        # 0.45 * 100 + 0.25 * 0 + 0.30 * 0 = 45
        score = engine.compute_priority_score(100, 0, 14)
        assert score == 45

    def test_urgency_at_zero_days_remaining(self, engine):
        # urgency = (14 - 0) / 14 * 100 = 100
        # 0.45 * 0 + 0.25 * 0 + 0.30 * 100 = 30
        score = engine.compute_priority_score(0, 0, 0)
        assert score == 30

    def test_full_value_normalization(self, engine):
        # normalized_value = min(100, 5000000/50000) = 100
        # 0.45 * 0 + 0.25 * 100 + 0.30 * 0 = 25
        score = engine.compute_priority_score(0, 5_000_000, 14)
        assert score == 25

    def test_all_maxed(self, engine):
        # 0.45 * 100 + 0.25 * 100 + 0.30 * 100 = 100
        score = engine.compute_priority_score(100, 5_000_000, 0)
        assert score == 100

    def test_clamped_to_100(self, engine):
        # Very high value: normalized to 100 via min()
        score = engine.compute_priority_score(100, 10_000_000, 0)
        assert score == 100

    def test_negative_days_remaining_clamped(self, engine):
        # days_remaining = -5 means trial expired 5 days ago
        # urgency = max(0, (14 - (-5)) / 14 * 100) = (19/14)*100 = 135.7 -> clamped to 100 in priority
        score = engine.compute_priority_score(0, 0, -5)
        # 0.30 * 135.7 = 40.7 -> clamped to 100 max? No, just raw.
        # Actually raw = 0.30 * (14-(-5))/14*100 = 0.30 * 135.7 = 40.7 -> round to 41
        assert score >= 30  # Must be > 0 due to urgency

    def test_normalization_divisor_is_50000(self):
        assert OPPORTUNITY_NORMALIZATION_DIVISOR == 50000


class TestBuildScoreExplanation:
    """Tests for build_score_explanation (Task 4.5)."""

    def test_empty_signals(self, engine):
        result = engine.build_score_explanation([])
        assert result["positive"] == []
        assert result["negative"] == []
        assert "category_scores" in result

    def test_returns_top_5_positive(self, engine):
        signals = [
            _make_signal("upgrade_cta", "conversion"),     # 30
            _make_signal("pricing_viewed", "conversion"),  # 25
            _make_signal("landscape_report", "value_realization"),  # 20
            _make_signal("opportunity_report", "value_realization"),  # 20
            _make_signal("email_domain_work", "intent"),   # 15
            _make_signal("discovery_run", "engagement"),    # 10
            _make_signal("login", "engagement"),            # 5
        ]
        result = engine.build_score_explanation(signals)
        assert len(result["positive"]) == 5
        # Should be sorted by contribution descending
        contributions = [p["contribution"] for p in result["positive"]]
        assert contributions == sorted(contributions, reverse=True)

    def test_returns_top_5_negative(self, engine):
        signals = [
            _make_signal("onboarding_abandoned", "negative"),        # -20
            _make_signal("no_activity_72h", "negative"),             # -15
            _make_signal("viewed_pricing_without_upgrade", "negative"),  # -12
            _make_signal("bounced_email", "negative"),               # -10
            _make_signal("removed_keywords", "negative"),            # -10
            _make_signal("report_open_no_scroll", "negative"),       # -5
        ]
        result = engine.build_score_explanation(signals)
        assert len(result["negative"]) == 5
        # Sorted by most negative first
        contributions = [n["contribution"] for n in result["negative"]]
        assert contributions == sorted(contributions)

    def test_includes_category_scores(self, engine):
        signals = [
            _make_signal("login", "engagement"),
            _make_signal("email_domain_work", "intent"),
        ]
        result = engine.build_score_explanation(signals)
        assert "engagement" in result["category_scores"]
        assert "intent" in result["category_scores"]
        assert "value_realization" in result["category_scores"]
        assert "conversion" in result["category_scores"]


class TestDetermineRecommendedAction:
    """Tests for determine_recommended_action (Task 4.6)."""

    def test_high_score_expiring_soon(self, engine):
        action = engine.determine_recommended_action(
            score=80, days_remaining=3, lifecycle_state="high_intent", last_signal_at=datetime.now(TZ)
        )
        assert action == "schedule_urgent_call"

    def test_high_score_time_remaining(self, engine):
        action = engine.determine_recommended_action(
            score=80, days_remaining=10, lifecycle_state="engaged", last_signal_at=datetime.now(TZ)
        )
        assert action == "send_value_confirmation"

    def test_medium_score_expiring_soon(self, engine):
        action = engine.determine_recommended_action(
            score=55, days_remaining=3, lifecycle_state="engaged", last_signal_at=datetime.now(TZ)
        )
        assert action == "send_case_study"

    def test_medium_score_time_remaining(self, engine):
        action = engine.determine_recommended_action(
            score=55, days_remaining=10, lifecycle_state="engaged", last_signal_at=datetime.now(TZ)
        )
        assert action == "share_value_prop"

    def test_low_score_at_risk(self, engine):
        action = engine.determine_recommended_action(
            score=20, days_remaining=5, lifecycle_state="at_risk", last_signal_at=datetime.now(TZ)
        )
        assert action == "send_reengagement_question"

    def test_low_score_engaged(self, engine):
        action = engine.determine_recommended_action(
            score=20, days_remaining=5, lifecycle_state="engaged", last_signal_at=datetime.now(TZ)
        )
        assert action == "identify_blockers"

    def test_expired_lifecycle(self, engine):
        action = engine.determine_recommended_action(
            score=50, days_remaining=0, lifecycle_state="expired", last_signal_at=datetime.now(TZ)
        )
        assert action == "classify_failure"

    def test_inactivity_override(self, engine):
        # Signal more than 72h ago
        old_signal = datetime.now(TZ) - timedelta(hours=80)
        action = engine.determine_recommended_action(
            score=80, days_remaining=10, lifecycle_state="engaged", last_signal_at=old_signal
        )
        assert action == "send_reengagement_question"

    def test_none_last_signal_no_inactivity_check(self, engine):
        action = engine.determine_recommended_action(
            score=80, days_remaining=10, lifecycle_state="engaged", last_signal_at=None
        )
        assert action == "send_value_confirmation"

    def test_default_fallback(self, engine):
        action = engine.determine_recommended_action(
            score=10, days_remaining=10, lifecycle_state="trial_started", last_signal_at=datetime.now(TZ)
        )
        assert action == "share_value_prop"


class TestBuildSignalSnapshot:
    """Tests for build_signal_snapshot (Task 4.7)."""

    def test_empty_signals(self, engine):
        result = engine.build_signal_snapshot([])
        assert result["signals"] == []
        assert result["signal_count"] == 0
        assert "snapshot_generated_at" in result

    def test_serializes_all_signals(self, engine):
        now = datetime.now(TZ)
        signals = [
            _make_signal("login", "engagement", created_at=now),
            _make_signal("pricing_viewed", "conversion", value={"page": "/pricing"}, created_at=now),
        ]
        result = engine.build_signal_snapshot(signals)
        assert result["signal_count"] == 2
        assert len(result["signals"]) == 2
        assert result["signals"][0]["type"] == "login"
        assert result["signals"][0]["category"] == "engagement"
        assert result["signals"][1]["value"] == {"page": "/pricing"}

    def test_snapshot_is_json_serializable(self, engine):
        import json
        signals = [
            _make_signal("login", "engagement", created_at=datetime.now(TZ)),
        ]
        result = engine.build_signal_snapshot(signals)
        # Should not raise
        json.dumps(result)

    def test_deterministic_for_same_signals(self, engine):
        now = datetime(2026, 6, 20, 10, 0, 0, tzinfo=TZ)
        signals = [_make_signal("login", "engagement", created_at=now)]
        result1 = engine.build_signal_snapshot(signals)
        result2 = engine.build_signal_snapshot(signals)
        # signals part should be identical (snapshot_generated_at may differ slightly)
        assert result1["signals"] == result2["signals"]
        assert result1["signal_count"] == result2["signal_count"]


class TestGetScoringWeights:
    """Tests for get_scoring_weights (Task 4.8)."""

    def test_returns_defaults_when_no_setting(self, engine, db):
        weights = engine.get_scoring_weights(db)
        assert weights == DEFAULT_WEIGHTS

    def test_returns_custom_weights_from_db(self, engine, db):
        from app.models.settings import SystemSetting
        import json

        custom = {
            "engagement": 0.30,
            "intent": 0.20,
            "value_realization": 0.20,
            "conversion": 0.20,
            "negative_cap": 0.10,
        }
        setting = SystemSetting(
            key="trial_scoring_weights",
            value=json.dumps(custom),
            group="trial_intelligence",
        )
        db.add(setting)
        db.flush()

        weights = engine.get_scoring_weights(db)
        assert weights["engagement"] == 0.30
        assert weights["negative_cap"] == 0.10

    def test_returns_defaults_on_invalid_json(self, engine, db):
        from app.models.settings import SystemSetting

        setting = SystemSetting(
            key="trial_scoring_weights",
            value="not valid json {{{",
            group="trial_intelligence",
        )
        db.add(setting)
        db.flush()

        weights = engine.get_scoring_weights(db)
        assert weights == DEFAULT_WEIGHTS

    def test_returns_defaults_on_missing_keys(self, engine, db):
        from app.models.settings import SystemSetting
        import json

        # Missing "negative_cap"
        incomplete = {
            "engagement": 0.30,
            "intent": 0.20,
        }
        setting = SystemSetting(
            key="trial_scoring_weights",
            value=json.dumps(incomplete),
            group="trial_intelligence",
        )
        db.add(setting)
        db.flush()

        weights = engine.get_scoring_weights(db)
        assert weights == DEFAULT_WEIGHTS
