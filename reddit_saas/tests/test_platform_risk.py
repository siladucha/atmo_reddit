"""Tests for Platform Risk Assessment.

Tests cover:
- Avatar health score computation from survival rate
- Removal rate trend classification
- Shadowban probability derivation
- Composite discount factor calculation
- Discount capped at 0.6
- Graceful handling of missing/empty metrics
- Integration with VisibilityForecaster (discount_factor attribute)
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.forecast.platform_risk import (
    DEFAULT_ACCOUNT_AGE_FACTOR,
    DEFAULT_SHADOWBAN_LOW,
    DEFAULT_SUBREDDIT_RISK_AVG,
    MAX_DISCOUNT,
    REMOVAL_TREND_RISK,
    WEIGHTS,
    PlatformRiskAssessment,
    _classify_removal_trend,
    _compute_avatar_health_score,
    _compute_discount,
    _compute_shadowban_probability,
    _extract_metrics,
)


# ---------------------------------------------------------------------------
# Fixtures / Mocks
# ---------------------------------------------------------------------------


@dataclass
class MockObserved:
    metrics_json: list | None = None


@dataclass
class MockIntent:
    pass


@pytest.fixture
def intent():
    return MockIntent()


# ---------------------------------------------------------------------------
# Tests: _extract_metrics helper
# ---------------------------------------------------------------------------


class TestExtractMetrics:
    def test_extracts_known_metrics(self):
        observed = MockObserved(
            metrics_json=[
                {"metric_id": "reddit.survival_rate_7d", "value": 0.85},
                {"metric_id": "reddit.removal_rate_7d", "value": 0.10},
            ]
        )
        result = _extract_metrics(observed)
        assert result["reddit.survival_rate_7d"] == 0.85
        assert result["reddit.removal_rate_7d"] == 0.10

    def test_empty_list_returns_empty_dict(self):
        observed = MockObserved(metrics_json=[])
        assert _extract_metrics(observed) == {}

    def test_none_metrics_returns_empty_dict(self):
        observed = MockObserved(metrics_json=None)
        assert _extract_metrics(observed) == {}

    def test_no_attr_returns_empty_dict(self):
        class Bare:
            pass

        assert _extract_metrics(Bare()) == {}

    def test_skips_non_dict_entries(self):
        observed = MockObserved(metrics_json=["not_a_dict", 42, None])
        assert _extract_metrics(observed) == {}

    def test_skips_missing_value(self):
        observed = MockObserved(
            metrics_json=[{"metric_id": "foo", "value": None}]
        )
        assert _extract_metrics(observed) == {}

    def test_handles_integer_values(self):
        observed = MockObserved(
            metrics_json=[{"metric_id": "count", "value": 5}]
        )
        result = _extract_metrics(observed)
        assert result["count"] == 5.0


# ---------------------------------------------------------------------------
# Tests: Avatar health score computation
# ---------------------------------------------------------------------------


class TestAvatarHealthScore:
    def test_high_survival_rate_equals_one(self):
        """survival_rate >= 0.90 → score = 1.0"""
        assert _compute_avatar_health_score({"reddit.survival_rate_7d": 0.95}) == 1.0
        assert _compute_avatar_health_score({"reddit.survival_rate_7d": 0.90}) == 1.0

    def test_low_survival_rate_equals_0_3(self):
        """survival_rate <= 0.50 → score = 0.3"""
        assert _compute_avatar_health_score({"reddit.survival_rate_7d": 0.50}) == 0.3
        assert _compute_avatar_health_score({"reddit.survival_rate_7d": 0.30}) == 0.3
        assert _compute_avatar_health_score({"reddit.survival_rate_7d": 0.0}) == 0.3

    def test_midpoint_interpolation(self):
        """survival_rate = 0.70 → linear interpolation between (0.5,0.3) and (0.9,1.0)"""
        score = _compute_avatar_health_score({"reddit.survival_rate_7d": 0.70})
        # 0.3 + (0.70 - 0.50) * 1.75 = 0.3 + 0.35 = 0.65
        assert abs(score - 0.65) < 1e-10

    def test_missing_metric_defaults_to_0_7(self):
        """No survival_rate metric → moderate health (0.7)"""
        assert _compute_avatar_health_score({}) == 0.7

    def test_survival_one_equals_one(self):
        """Perfect survival → perfect health"""
        assert _compute_avatar_health_score({"reddit.survival_rate_7d": 1.0}) == 1.0


# ---------------------------------------------------------------------------
# Tests: Removal rate trend classification
# ---------------------------------------------------------------------------


class TestRemovalTrend:
    def test_improving(self):
        assert _classify_removal_trend(0.01) == "improving"
        assert _classify_removal_trend(0.04) == "improving"

    def test_stable(self):
        assert _classify_removal_trend(0.05) == "stable"
        assert _classify_removal_trend(0.10) == "stable"
        assert _classify_removal_trend(0.15) == "stable"

    def test_degrading(self):
        assert _classify_removal_trend(0.16) == "degrading"
        assert _classify_removal_trend(0.50) == "degrading"

    def test_none_defaults_to_stable(self):
        assert _classify_removal_trend(None) == "stable"

    def test_zero_is_improving(self):
        assert _classify_removal_trend(0.0) == "improving"

    def test_boundary_0_05_is_stable(self):
        """Exactly 0.05 should be stable (not improving)."""
        assert _classify_removal_trend(0.05) == "stable"

    def test_boundary_0_15_is_stable(self):
        """Exactly 0.15 should be stable (not degrading)."""
        assert _classify_removal_trend(0.15) == "stable"


# ---------------------------------------------------------------------------
# Tests: Shadowban probability
# ---------------------------------------------------------------------------


class TestShadowbanProbability:
    def test_low_removal_gives_default(self):
        assert _compute_shadowban_probability(0.05) == DEFAULT_SHADOWBAN_LOW
        assert _compute_shadowban_probability(0.10) == DEFAULT_SHADOWBAN_LOW
        assert _compute_shadowban_probability(0.20) == DEFAULT_SHADOWBAN_LOW

    def test_high_removal_increases_probability(self):
        prob = _compute_shadowban_probability(0.40)
        assert prob > DEFAULT_SHADOWBAN_LOW
        # 0.05 + (0.4 - 0.2) * 0.3125 = 0.05 + 0.0625 = 0.1125
        assert abs(prob - 0.1125) < 1e-10

    def test_none_returns_default(self):
        assert _compute_shadowban_probability(None) == DEFAULT_SHADOWBAN_LOW

    def test_capped_at_0_3(self):
        """Even with removal_rate = 1.0, prob should not exceed 0.30."""
        prob = _compute_shadowban_probability(1.0)
        assert prob == 0.30

    def test_at_threshold_boundary(self):
        """At exactly 0.2, should still be default low."""
        assert _compute_shadowban_probability(0.2) == DEFAULT_SHADOWBAN_LOW


# ---------------------------------------------------------------------------
# Tests: Composite discount calculation
# ---------------------------------------------------------------------------


class TestCompositeDiscount:
    def test_healthy_scenario_low_discount(self):
        """Healthy system should have low discount."""
        discount = _compute_discount(
            avatar_health_score=1.0,
            removal_rate_trend="improving",
            subreddit_risk_avg=20.0,
            account_age_factor=0.9,
            shadowban_probability=0.05,
        )
        # health_risk = 0, removal_risk = 0.05, sub_risk = 0.2, age_risk = 0.1, ban_risk = 0.05
        # 0.25*0 + 0.25*0.05 + 0.20*0.2 + 0.15*0.1 + 0.15*0.05
        # = 0 + 0.0125 + 0.04 + 0.015 + 0.0075 = 0.075
        assert abs(discount - 0.075) < 1e-10

    def test_risky_scenario_higher_discount(self):
        """Unhealthy system should have higher discount."""
        discount = _compute_discount(
            avatar_health_score=0.3,
            removal_rate_trend="degrading",
            subreddit_risk_avg=70.0,
            account_age_factor=0.4,
            shadowban_probability=0.25,
        )
        # health_risk = 0.7, removal_risk = 0.3, sub_risk = 0.7, age_risk = 0.6, ban_risk = 0.25
        # 0.25*0.7 + 0.25*0.3 + 0.20*0.7 + 0.15*0.6 + 0.15*0.25
        # = 0.175 + 0.075 + 0.14 + 0.09 + 0.0375 = 0.5175
        assert abs(discount - 0.5175) < 1e-10

    def test_max_discount_capped_at_0_6(self):
        """Even worst case should not exceed MAX_DISCOUNT (0.6)."""
        discount = _compute_discount(
            avatar_health_score=0.0,
            removal_rate_trend="degrading",
            subreddit_risk_avg=100.0,
            account_age_factor=0.0,
            shadowban_probability=1.0,
        )
        assert discount == MAX_DISCOUNT

    def test_all_perfect_discount_near_zero(self):
        """Perfect health + no risk = minimal discount."""
        discount = _compute_discount(
            avatar_health_score=1.0,
            removal_rate_trend="improving",
            subreddit_risk_avg=0.0,
            account_age_factor=1.0,
            shadowban_probability=0.0,
        )
        # health_risk=0, removal_risk=0.05, sub_risk=0, age_risk=0, ban_risk=0
        # 0.25*0 + 0.25*0.05 + 0.2*0 + 0.15*0 + 0.15*0 = 0.0125
        assert abs(discount - 0.0125) < 1e-10

    def test_weights_sum_to_one(self):
        """Verify weights are normalized."""
        assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-10


# ---------------------------------------------------------------------------
# Tests: PlatformRiskAssessment.compute (integration)
# ---------------------------------------------------------------------------


class TestPlatformRiskAssessmentCompute:
    def test_healthy_observed(self, intent):
        """High survival + low removal → low discount."""
        observed = MockObserved(
            metrics_json=[
                {"metric_id": "reddit.survival_rate_7d", "value": 0.95},
                {"metric_id": "reddit.removal_rate_7d", "value": 0.02},
            ]
        )
        risk = PlatformRiskAssessment.compute(observed, intent)
        assert risk.avatar_health_score == 1.0
        assert risk.removal_rate_trend == "improving"
        assert risk.shadowban_probability == DEFAULT_SHADOWBAN_LOW
        assert risk.discount_factor < 0.15

    def test_degraded_observed(self, intent):
        """Low survival + high removal → higher discount."""
        observed = MockObserved(
            metrics_json=[
                {"metric_id": "reddit.survival_rate_7d", "value": 0.55},
                {"metric_id": "reddit.removal_rate_7d", "value": 0.30},
            ]
        )
        risk = PlatformRiskAssessment.compute(observed, intent)
        assert risk.avatar_health_score < 0.5
        assert risk.removal_rate_trend == "degrading"
        assert risk.shadowban_probability > DEFAULT_SHADOWBAN_LOW
        assert risk.discount_factor > 0.2

    def test_no_metrics_uses_defaults(self, intent):
        """Empty metrics → sensible defaults, moderate discount."""
        observed = MockObserved(metrics_json=[])
        risk = PlatformRiskAssessment.compute(observed, intent)
        assert risk.avatar_health_score == 0.7
        assert risk.removal_rate_trend == "stable"
        assert risk.subreddit_risk_avg == DEFAULT_SUBREDDIT_RISK_AVG
        assert risk.account_age_factor == DEFAULT_ACCOUNT_AGE_FACTOR
        assert 0.1 < risk.discount_factor < 0.3

    def test_none_metrics_json(self, intent):
        observed = MockObserved(metrics_json=None)
        risk = PlatformRiskAssessment.compute(observed, intent)
        assert isinstance(risk, PlatformRiskAssessment)
        assert risk.discount_factor >= 0.0

    def test_no_metrics_json_attr(self, intent):
        """Object without metrics_json attribute."""

        class Bare:
            pass

        risk = PlatformRiskAssessment.compute(Bare(), intent)
        assert isinstance(risk, PlatformRiskAssessment)

    def test_intent_none_works(self):
        """intent=None should work (unused in v1)."""
        observed = MockObserved(metrics_json=[])
        risk = PlatformRiskAssessment.compute(observed, None)
        assert isinstance(risk, PlatformRiskAssessment)

    def test_discount_factor_range(self, intent):
        """discount_factor must always be in [0, 0.6]."""
        # Best case
        best = MockObserved(
            metrics_json=[
                {"metric_id": "reddit.survival_rate_7d", "value": 1.0},
                {"metric_id": "reddit.removal_rate_7d", "value": 0.0},
            ]
        )
        risk_best = PlatformRiskAssessment.compute(best, intent)
        assert 0.0 <= risk_best.discount_factor <= MAX_DISCOUNT

        # Worst case
        worst = MockObserved(
            metrics_json=[
                {"metric_id": "reddit.survival_rate_7d", "value": 0.0},
                {"metric_id": "reddit.removal_rate_7d", "value": 1.0},
            ]
        )
        risk_worst = PlatformRiskAssessment.compute(worst, intent)
        assert 0.0 <= risk_worst.discount_factor <= MAX_DISCOUNT

    def test_dataclass_fields_present(self, intent):
        """All expected fields are set."""
        observed = MockObserved(
            metrics_json=[
                {"metric_id": "reddit.survival_rate_7d", "value": 0.80},
                {"metric_id": "reddit.removal_rate_7d", "value": 0.08},
            ]
        )
        risk = PlatformRiskAssessment.compute(observed, intent)
        assert hasattr(risk, "shadowban_probability")
        assert hasattr(risk, "removal_rate_trend")
        assert hasattr(risk, "subreddit_risk_avg")
        assert hasattr(risk, "avatar_health_score")
        assert hasattr(risk, "account_age_factor")
        assert hasattr(risk, "discount_factor")

    def test_works_with_forecaster(self, intent):
        """Verify PlatformRiskAssessment integrates with VisibilityForecaster."""
        from app.services.forecast.visibility_forecaster import VisibilityForecaster

        observed = MockObserved(
            metrics_json=[
                {"metric_id": "geo.brand_rate.overall", "value": 0.077},
                {"metric_id": "reddit.survival_rate_7d", "value": 0.85},
                {"metric_id": "reddit.removal_rate_7d", "value": 0.10},
            ]
        )
        risk = PlatformRiskAssessment.compute(observed, intent)

        forecaster = VisibilityForecaster()
        forecast = forecaster.forecast(observed, intent, risk, seed_key="integration")

        assert forecast.risk_discount == risk.discount_factor
        assert forecast.baseline_rate == 7.7
        assert len(forecast.scenarios["expected"]) == 24
