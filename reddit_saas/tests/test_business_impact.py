"""Tests for BusinessImpactCalculator — Layer 5 of Forecast & Reporting.

Covers:
- Category rank computation (client position among competitors)
- Gap closure rate (pp/week based on trend)
- Weeks-to-parity estimation
- ROI framing (investment/month ÷ projected gain = cost per point)
- Measurable vs inferred distinction
- Full compute() integration
"""
from __future__ import annotations

import pytest

from app.services.forecast.business_impact import (
    DEFAULT_DISCLAIMER,
    INFERRED_METRICS,
    MEASURABLE_METRICS,
    PLAN_PRICES,
    BusinessImpact,
    BusinessImpactCalculator,
)


@pytest.fixture
def calculator() -> BusinessImpactCalculator:
    return BusinessImpactCalculator()


# ---------------------------------------------------------------------------
# Category Rank Computation
# ---------------------------------------------------------------------------


class TestCategoryRank:
    """Category rank = client position among competitors (1-indexed)."""

    def test_client_last_when_lowest_rate(self, calculator: BusinessImpactCalculator):
        """Client with lowest rate should be ranked last."""
        competitors = {"CompA": 0.90, "CompB": 0.60, "CompC": 0.45}
        rank, total = calculator.compute_category_rank(competitors, client_rate=0.08)
        assert rank == 4
        assert total == 4

    def test_client_first_when_highest_rate(self, calculator: BusinessImpactCalculator):
        """Client with highest rate should be ranked #1."""
        competitors = {"CompA": 0.20, "CompB": 0.15}
        rank, total = calculator.compute_category_rank(competitors, client_rate=0.50)
        assert rank == 1
        assert total == 3

    def test_client_middle_position(self, calculator: BusinessImpactCalculator):
        """Client ranked in the middle of the pack."""
        competitors = {"CompA": 0.90, "CompB": 0.30}
        rank, total = calculator.compute_category_rank(competitors, client_rate=0.50)
        assert rank == 2
        assert total == 3

    def test_no_competitors(self, calculator: BusinessImpactCalculator):
        """With no competitors, client is #1 of 1."""
        rank, total = calculator.compute_category_rank({}, client_rate=0.10)
        assert rank == 1
        assert total == 1

    def test_tied_rates(self, calculator: BusinessImpactCalculator):
        """Tied rates — stable sort should place them deterministically."""
        competitors = {"CompA": 0.50, "CompB": 0.50}
        rank, total = calculator.compute_category_rank(competitors, client_rate=0.50)
        # All tied at 0.50, client appended last. Python sort is stable,
        # so original order preserved: CompA, CompB, __client__ all at 0.50
        # Rank should be 3 (or whichever position stable sort puts __client__)
        assert total == 3
        assert 1 <= rank <= 3


# ---------------------------------------------------------------------------
# Gap Closure Rate
# ---------------------------------------------------------------------------


class TestGapClosureRate:
    """Gap closure = (current_gap - projected_gap) / 12 weeks."""

    def test_closing_gap(self, calculator: BusinessImpactCalculator):
        """Client is closing the gap → positive rate."""
        # Current gap: 50pp, projected gap at 12w: 30pp
        # Closed 20pp over 12 weeks = ~1.67 pp/week
        rate = calculator.compute_gap_closure_rate(50.0, 30.0)
        assert rate == pytest.approx(1.67, abs=0.01)

    def test_widening_gap(self, calculator: BusinessImpactCalculator):
        """Client is falling behind → return 0.0."""
        rate = calculator.compute_gap_closure_rate(30.0, 40.0)
        assert rate == 0.0

    def test_no_change(self, calculator: BusinessImpactCalculator):
        """Gap unchanged → return 0.0."""
        rate = calculator.compute_gap_closure_rate(50.0, 50.0)
        assert rate == 0.0

    def test_full_closure(self, calculator: BusinessImpactCalculator):
        """Full parity at 12w → rate = current_gap / 12."""
        rate = calculator.compute_gap_closure_rate(24.0, 0.0)
        assert rate == 2.0

    def test_zero_starting_gap(self, calculator: BusinessImpactCalculator):
        """Already at parity → rate 0.0."""
        rate = calculator.compute_gap_closure_rate(0.0, 0.0)
        assert rate == 0.0


# ---------------------------------------------------------------------------
# Weeks to Parity
# ---------------------------------------------------------------------------


class TestWeeksToParity:
    """Weeks until client reaches leader rate."""

    def test_explicit_from_forecast(self, calculator: BusinessImpactCalculator):
        """Uses forecasted_json['weeks_to_parity'] when present."""
        forecasted = {"weeks_to_parity": 18}
        result = calculator.compute_weeks_to_parity(forecasted)
        assert result == 18

    def test_computed_from_gap_and_rate(self, calculator: BusinessImpactCalculator):
        """Computes from gap / closure_rate when explicit not available."""
        forecasted: dict = {}
        # Gap 30pp, closing at 2pp/week → 15 weeks
        result = calculator.compute_weeks_to_parity(
            forecasted, gap_current_pp=30.0, closure_rate_pp_per_week=2.0
        )
        assert result == 15

    def test_unreachable_zero_closure(self, calculator: BusinessImpactCalculator):
        """Returns None when closure rate is zero."""
        forecasted: dict = {}
        result = calculator.compute_weeks_to_parity(
            forecasted, gap_current_pp=30.0, closure_rate_pp_per_week=0.0
        )
        assert result is None

    def test_unreachable_no_data(self, calculator: BusinessImpactCalculator):
        """Returns None when no data available."""
        result = calculator.compute_weeks_to_parity({})
        assert result is None

    def test_explicit_overrides_computed(self, calculator: BusinessImpactCalculator):
        """Explicit value takes precedence even when gap/rate available."""
        forecasted = {"weeks_to_parity": 10}
        result = calculator.compute_weeks_to_parity(
            forecasted, gap_current_pp=100.0, closure_rate_pp_per_week=1.0
        )
        # Should return 10 (explicit), not 100 (computed)
        assert result == 10


# ---------------------------------------------------------------------------
# ROI Framing
# ---------------------------------------------------------------------------


class TestROI:
    """ROI = investment_monthly / projected_gain_pp."""

    def test_starter_plan_with_gain(self, calculator: BusinessImpactCalculator):
        """Standard ROI calculation for starter plan."""
        investment, cost_per_point = calculator.compute_roi("starter", 30.0)
        assert investment == 399.0
        assert cost_per_point == pytest.approx(13.30, abs=0.01)

    def test_growth_plan_with_gain(self, calculator: BusinessImpactCalculator):
        """Growth plan ROI."""
        investment, cost_per_point = calculator.compute_roi("growth", 20.0)
        assert investment == 799.0
        assert cost_per_point == pytest.approx(39.95, abs=0.01)

    def test_zero_gain_returns_none(self, calculator: BusinessImpactCalculator):
        """No projected gain → cost_per_point is None."""
        investment, cost_per_point = calculator.compute_roi("starter", 0.0)
        assert investment == 399.0
        assert cost_per_point is None

    def test_trial_plan_zero_investment(self, calculator: BusinessImpactCalculator):
        """Trial plan has $0 investment → cost_per_point is None."""
        investment, cost_per_point = calculator.compute_roi("trial", 30.0)
        assert investment == 0.0
        assert cost_per_point is None

    def test_unknown_plan_defaults_to_zero(self, calculator: BusinessImpactCalculator):
        """Unknown plan type → $0 investment."""
        investment, cost_per_point = calculator.compute_roi("enterprise", 30.0)
        assert investment == 0.0
        assert cost_per_point is None

    def test_scale_plan(self, calculator: BusinessImpactCalculator):
        """Scale plan ROI calculation."""
        investment, cost_per_point = calculator.compute_roi("scale", 50.0)
        assert investment == 1499.0
        assert cost_per_point == pytest.approx(29.98, abs=0.01)


# ---------------------------------------------------------------------------
# Measurable vs Inferred
# ---------------------------------------------------------------------------


class TestMeasurableInferred:
    """Fixed metric classification lists."""

    def test_measurable_contains_expected(self):
        """Measurable list has the required items."""
        assert "AI visibility rate" in MEASURABLE_METRICS
        assert "Reddit karma" in MEASURABLE_METRICS
        assert "survival rate" in MEASURABLE_METRICS
        assert "comment volume" in MEASURABLE_METRICS

    def test_inferred_contains_expected(self):
        """Inferred list has the required items."""
        assert "traffic from AI search" in INFERRED_METRICS
        assert "lead quality" in INFERRED_METRICS
        assert "brand authority" in INFERRED_METRICS

    def test_no_overlap(self):
        """Measurable and inferred should not overlap."""
        overlap = set(MEASURABLE_METRICS) & set(INFERRED_METRICS)
        assert len(overlap) == 0

    def test_disclaimer_present(self):
        """Disclaimer string is non-empty and mentions key caveats."""
        assert len(DEFAULT_DISCLAIMER) > 50
        assert "correlation" in DEFAULT_DISCLAIMER.lower()


# ---------------------------------------------------------------------------
# Full compute() Integration
# ---------------------------------------------------------------------------


class TestComputeIntegration:
    """End-to-end compute() tests."""

    def test_full_computation(self, calculator: BusinessImpactCalculator):
        """Realistic scenario: Ono Academic College baseline data."""
        observed = {
            "brand_visibility_rate": 0.077,  # 7.7%
            "competitor_rates": {
                "Tel Aviv University": 0.923,
                "Hebrew University": 0.85,
                "Technion": 0.60,
                "Bar-Ilan University": 0.55,
                "Ben-Gurion University": 0.50,
                "Reichman University": 0.45,
            },
        }
        forecasted = {
            "visibility_12w": {"conservative": 18.0, "expected": 28.0, "optimistic": 35.0},
            "visibility_24w": {"conservative": 28.0, "expected": 38.0, "optimistic": 45.0},
        }
        result = calculator.compute(observed, forecasted, plan_type="starter")

        # Client should be last (7.7% < all competitors)
        assert result.category_rank == 7
        assert result.category_total == 7

        # Projected rank at 12w (28% expected → above Reichman 45%? No, 28%/100=0.28 ratio)
        # 0.28 < all competitors (lowest is Reichman at 0.45)
        assert result.projected_rank_12w == 7

        # Gap to leader: Tel Aviv Uni at 92.3%
        assert result.gap_to_leader["target_name"] == "Tel Aviv University"
        assert result.gap_to_leader["gap_pp"] == pytest.approx(84.6, abs=0.1)

        # ROI
        assert result.investment_monthly == 399.0
        # Gain: 38.0% - 7.7% = 30.3pp
        assert result.projected_visibility_gain_pp == pytest.approx(30.3, abs=0.1)
        assert result.cost_per_visibility_point is not None
        assert result.cost_per_visibility_point == pytest.approx(
            399.0 / 30.3, abs=0.1
        )

        # Measurable/inferred
        assert len(result.measurable) == 4
        assert len(result.inferred) == 3
        assert result.disclaimer == DEFAULT_DISCLAIMER

    def test_no_competitors(self, calculator: BusinessImpactCalculator):
        """Edge case: no competitor data."""
        observed = {"brand_visibility_rate": 0.10, "competitor_rates": {}}
        forecasted = {
            "visibility_12w": {"expected": 20.0},
            "visibility_24w": {"expected": 30.0},
        }
        result = calculator.compute(observed, forecasted, plan_type="growth")

        assert result.category_rank == 1
        assert result.category_total == 1
        assert result.gap_to_leader["target_name"] is None
        assert result.gap_to_leader["gap_pp"] == 0.0

    def test_zero_baseline(self, calculator: BusinessImpactCalculator):
        """Edge case: client starts at 0% visibility."""
        observed = {
            "brand_visibility_rate": 0.0,
            "competitor_rates": {"Leader": 0.80},
        }
        forecasted = {
            "visibility_12w": {"expected": 15.0},
            "visibility_24w": {"expected": 25.0},
        }
        result = calculator.compute(observed, forecasted, plan_type="seed")

        assert result.category_rank == 2
        assert result.gap_to_leader["gap_pp"] == 80.0
        assert result.projected_visibility_gain_pp == 25.0
        assert result.investment_monthly == 149.0

    def test_to_dict_serialization(self, calculator: BusinessImpactCalculator):
        """BusinessImpact.to_dict() produces valid JSONB-ready dict."""
        observed = {
            "brand_visibility_rate": 0.10,
            "competitor_rates": {"CompA": 0.50},
        }
        forecasted = {
            "visibility_12w": {"expected": 20.0},
            "visibility_24w": {"expected": 30.0},
        }
        result = calculator.compute(observed, forecasted, plan_type="starter")
        d = result.to_dict()

        assert d["label"] == "💰 Business Impact"
        assert isinstance(d["category_rank"], int)
        assert isinstance(d["gap_to_leader"], dict)
        assert isinstance(d["measurable"], list)
        assert isinstance(d["inferred"], list)
        assert "disclaimer" in d
