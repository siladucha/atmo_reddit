"""Tests for the S-Curve Visibility Forecaster.

Tests cover:
- Logistic S-curve computation
- 3 scenario generation (conservative/expected/optimistic)
- Per-engine projections with ENGINE_MULTIPLIERS
- Seeded noise reproducibility
- Clamping to [0, 100]
- Baseline extraction from observed metrics
- get_scenario_triple helper
- Platform risk discount applied to ceiling
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pytest

from app.services.forecast.visibility_forecaster import (
    DEFAULT_CEILING,
    DEFAULT_MIDPOINT,
    DEFAULT_STEEPNESS,
    ENGINE_MULTIPLIERS,
    NOISE_AMPLITUDE,
    ScenarioTriple,
    VisibilityForecast,
    VisibilityForecaster,
    _scurve,
    get_scenario_triple,
)


# ---------------------------------------------------------------------------
# Fixtures / Mocks
# ---------------------------------------------------------------------------


@dataclass
class MockObserved:
    metrics_json: list


@dataclass
class MockRisk:
    discount_factor: float


@dataclass
class MockIntent:
    pass


@pytest.fixture
def forecaster():
    return VisibilityForecaster()


@pytest.fixture
def observed_7_7():
    """Observed with 7.7% baseline (stored as 0.077 ratio)."""
    return MockObserved(
        metrics_json=[{"metric_id": "geo.brand_rate.overall", "value": 0.077}]
    )


@pytest.fixture
def risk_15():
    """15% risk discount."""
    return MockRisk(discount_factor=0.15)


@pytest.fixture
def risk_zero():
    """No risk discount."""
    return MockRisk(discount_factor=0.0)


@pytest.fixture
def intent():
    return MockIntent()


# ---------------------------------------------------------------------------
# Tests: _scurve helper function
# ---------------------------------------------------------------------------


class TestScurveFunction:
    def test_at_midpoint_equals_halfway(self):
        """At midpoint, value should be exactly halfway between baseline and ceiling."""
        baseline = 7.7
        ceiling = 40.0
        midpoint = 12
        steepness = 0.4

        result = _scurve(midpoint, baseline, ceiling, midpoint, steepness)
        expected = baseline + (ceiling - baseline) / 2.0
        assert abs(result - expected) < 1e-10

    def test_week_zero_close_to_baseline(self):
        """At week 0 with midpoint=12, value should be close to baseline."""
        result = _scurve(0, 7.7, 40.0, 12, 0.4)
        # exp(-0.4 * (0-12)) = exp(4.8) ≈ 121.5
        # value ≈ 7.7 + 32.3 / 122.5 ≈ 7.96
        assert result > 7.7
        assert result < 12.0

    def test_far_future_approaches_ceiling(self):
        """Far in the future, value should approach ceiling."""
        result = _scurve(100, 7.7, 40.0, 12, 0.4)
        assert abs(result - 40.0) < 0.01

    def test_negative_week_below_baseline_approach(self):
        """Negative weeks should approach baseline from below (but still above due to formula)."""
        result = _scurve(-10, 7.7, 40.0, 12, 0.4)
        # Very early, approaching baseline
        assert result >= 7.7
        assert result < 8.0

    def test_steepness_zero_flat(self):
        """With steepness=0, curve is flat at midpoint value (baseline + half range)."""
        result = _scurve(5, 10.0, 50.0, 12, 0.0)
        # exp(0) = 1, so value = 10 + 40/2 = 30
        expected = 10.0 + (50.0 - 10.0) / 2.0
        assert abs(result - expected) < 1e-10

    def test_overflow_protection_large_positive_exponent(self):
        """Large positive exponent shouldn't overflow."""
        result = _scurve(-1000, 5.0, 40.0, 12, 0.4)
        assert result == 5.0  # Returns baseline

    def test_overflow_protection_large_negative_exponent(self):
        """Large negative exponent shouldn't overflow."""
        result = _scurve(10000, 5.0, 40.0, 12, 0.4)
        assert result == 40.0  # Returns ceiling


# ---------------------------------------------------------------------------
# Tests: Scenario generation
# ---------------------------------------------------------------------------


class TestScenarioGeneration:
    def test_three_scenarios_present(self, forecaster, observed_7_7, intent, risk_15):
        forecast = forecaster.forecast(observed_7_7, intent, risk_15, seed_key="test")
        assert "conservative" in forecast.scenarios
        assert "expected" in forecast.scenarios
        assert "optimistic" in forecast.scenarios

    def test_scenario_lengths_match_target_weeks(self, forecaster, observed_7_7, intent, risk_15):
        forecast = forecaster.forecast(
            observed_7_7, intent, risk_15, target_weeks=16, seed_key="t"
        )
        for scenario_name, values in forecast.scenarios.items():
            assert len(values) == 16, f"{scenario_name} length should be 16"

    def test_conservative_below_expected_below_optimistic_on_average(
        self, forecaster, observed_7_7, intent, risk_15
    ):
        """Over the full projection, average conservative < expected < optimistic."""
        forecast = forecaster.forecast(observed_7_7, intent, risk_15, seed_key="order-test")
        c_avg = sum(forecast.scenarios["conservative"]) / len(forecast.scenarios["conservative"])
        e_avg = sum(forecast.scenarios["expected"]) / len(forecast.scenarios["expected"])
        o_avg = sum(forecast.scenarios["optimistic"]) / len(forecast.scenarios["optimistic"])
        assert c_avg < e_avg < o_avg

    def test_all_values_clamped_0_100(self, forecaster, observed_7_7, intent, risk_15):
        """All scenario values must be in [0, 100]."""
        forecast = forecaster.forecast(observed_7_7, intent, risk_15, seed_key="clamp")
        for name, values in forecast.scenarios.items():
            for i, v in enumerate(values):
                assert 0.0 <= v <= 100.0, f"{name}[{i}] = {v} out of range"

    def test_scenario_params_conservative(self, forecaster, observed_7_7, intent, risk_zero):
        """Conservative uses ceiling×0.7 and midpoint+2."""
        # With zero risk, effective ceiling = DEFAULT_CEILING = 40
        # Conservative ceiling = 40 * 0.7 = 28, midpoint = 14
        # We verify by checking the curve doesn't reach as high
        forecast = forecaster.forecast(observed_7_7, intent, risk_zero, seed_key="params")
        # Conservative max (ignoring noise) should be around 28
        # Optimistic max should be around 48 (40*1.2)
        c_max_approx = max(forecast.scenarios["conservative"])
        o_max_approx = max(forecast.scenarios["optimistic"])
        # Conservative shouldn't go much above 28 + noise
        assert c_max_approx < 28 + NOISE_AMPLITUDE + 2  # some tolerance
        # Optimistic can go higher
        assert o_max_approx > c_max_approx


# ---------------------------------------------------------------------------
# Tests: Per-engine projections
# ---------------------------------------------------------------------------


class TestPerEngineProjections:
    def test_all_engines_present(self, forecaster, observed_7_7, intent, risk_15):
        forecast = forecaster.forecast(observed_7_7, intent, risk_15, seed_key="eng")
        for engine in ENGINE_MULTIPLIERS:
            assert engine in forecast.per_engine

    def test_engine_lengths_match_target_weeks(self, forecaster, observed_7_7, intent, risk_15):
        forecast = forecaster.forecast(
            observed_7_7, intent, risk_15, target_weeks=20, seed_key="len"
        )
        for engine, values in forecast.per_engine.items():
            assert len(values) == 20, f"{engine} length should be 20"

    def test_perplexity_highest_chatgpt_middle_claude_lowest(
        self, forecaster, observed_7_7, intent, risk_15
    ):
        """Perplexity (×1.4) > ChatGPT (×1.0) > Claude (×0.65) on average."""
        forecast = forecaster.forecast(observed_7_7, intent, risk_15, seed_key="eng-order")
        p_avg = sum(forecast.per_engine["perplexity"]) / len(forecast.per_engine["perplexity"])
        ch_avg = sum(forecast.per_engine["chatgpt"]) / len(forecast.per_engine["chatgpt"])
        cl_avg = sum(forecast.per_engine["claude"]) / len(forecast.per_engine["claude"])
        assert p_avg > ch_avg > cl_avg

    def test_per_engine_values_clamped(self, forecaster, observed_7_7, intent, risk_15):
        forecast = forecaster.forecast(observed_7_7, intent, risk_15, seed_key="eng-clamp")
        for engine, values in forecast.per_engine.items():
            for i, v in enumerate(values):
                assert 0.0 <= v <= 100.0, f"{engine}[{i}] = {v} out of range"


# ---------------------------------------------------------------------------
# Tests: Noise and reproducibility
# ---------------------------------------------------------------------------


class TestNoiseReproducibility:
    def test_same_seed_same_output(self, forecaster, observed_7_7, intent, risk_15):
        """Same seed_key must produce identical results."""
        f1 = forecaster.forecast(observed_7_7, intent, risk_15, seed_key="repro")
        f2 = forecaster.forecast(observed_7_7, intent, risk_15, seed_key="repro")
        assert f1.scenarios == f2.scenarios
        assert f1.per_engine == f2.per_engine

    def test_different_seed_different_output(self, forecaster, observed_7_7, intent, risk_15):
        """Different seed_key should produce different noise pattern."""
        f1 = forecaster.forecast(observed_7_7, intent, risk_15, seed_key="seed-a")
        f2 = forecaster.forecast(observed_7_7, intent, risk_15, seed_key="seed-b")
        assert f1.scenarios != f2.scenarios

    def test_noise_bounded(self, forecaster, observed_7_7, intent, risk_zero):
        """Noise shouldn't push values far beyond the pure S-curve ± NOISE_AMPLITUDE."""
        forecast = forecaster.forecast(observed_7_7, intent, risk_zero, seed_key="noise-bound")
        # At week 12 (midpoint), expected value = baseline + (ceiling-baseline)/2
        # = 7.7 + 32.3/2 = 23.85
        # With ±2.5 noise, should be roughly 21.35 to 26.35
        week_12_val = forecast.scenarios["expected"][12]
        assert 21.0 <= week_12_val <= 27.0


# ---------------------------------------------------------------------------
# Tests: Baseline extraction
# ---------------------------------------------------------------------------


class TestBaselineExtraction:
    def test_extracts_from_metrics_json(self, forecaster, intent, risk_zero):
        observed = MockObserved(
            metrics_json=[{"metric_id": "geo.brand_rate.overall", "value": 0.25}]
        )
        forecast = forecaster.forecast(observed, intent, risk_zero, seed_key="b")
        assert forecast.baseline_rate == 25.0

    def test_missing_metric_returns_zero(self, forecaster, intent, risk_zero):
        observed = MockObserved(
            metrics_json=[{"metric_id": "reddit.karma_avg_7d", "value": 5.0}]
        )
        forecast = forecaster.forecast(observed, intent, risk_zero, seed_key="b")
        assert forecast.baseline_rate == 0.0

    def test_empty_metrics_returns_zero(self, forecaster, intent, risk_zero):
        observed = MockObserved(metrics_json=[])
        forecast = forecaster.forecast(observed, intent, risk_zero, seed_key="b")
        assert forecast.baseline_rate == 0.0

    def test_none_metrics_returns_zero(self, forecaster, intent, risk_zero):
        observed = MockObserved(metrics_json=None)
        forecast = forecaster.forecast(observed, intent, risk_zero, seed_key="b")
        assert forecast.baseline_rate == 0.0

    def test_value_already_percentage(self, forecaster, intent, risk_zero):
        """If value > 1.0, treat as already a percentage."""
        observed = MockObserved(
            metrics_json=[{"metric_id": "geo.brand_rate.overall", "value": 15.5}]
        )
        forecast = forecaster.forecast(observed, intent, risk_zero, seed_key="b")
        assert forecast.baseline_rate == 15.5


# ---------------------------------------------------------------------------
# Tests: Platform risk discount
# ---------------------------------------------------------------------------


class TestPlatformRiskDiscount:
    def test_zero_discount_full_ceiling(self, forecaster, observed_7_7, intent, risk_zero):
        forecast = forecaster.forecast(observed_7_7, intent, risk_zero, seed_key="r")
        assert forecast.risk_discount == 0.0
        # Expected scenario avg should be higher than with discount
        e_avg = sum(forecast.scenarios["expected"]) / 24
        assert e_avg > 15.0  # with full 40% ceiling

    def test_high_discount_reduces_ceiling(self, forecaster, observed_7_7, intent):
        high_risk = MockRisk(discount_factor=0.5)
        forecast = forecaster.forecast(observed_7_7, intent, high_risk, seed_key="r")
        assert forecast.risk_discount == 0.5
        # Effective ceiling = 40 * 0.5 = 20
        # Expected average should be lower
        e_avg = sum(forecast.scenarios["expected"]) / 24
        assert e_avg < 18.0  # ceiling is only 20

    def test_full_discount_collapses_ceiling(self, forecaster, observed_7_7, intent):
        """100% risk discount means ceiling = baseline (no growth)."""
        full_risk = MockRisk(discount_factor=1.0)
        forecast = forecaster.forecast(observed_7_7, intent, full_risk, seed_key="r")
        # Ceiling = 40 * 0 = 0, so S-curve goes to 0
        # But baseline is 7.7%, so the formula gives baseline + (0-baseline)/...
        # which means values drift toward 0 (not 7.7)
        # All values should be low
        e_max = max(forecast.scenarios["expected"])
        assert e_max < 12.0  # can't grow much with zero ceiling


# ---------------------------------------------------------------------------
# Tests: get_scenario_triple
# ---------------------------------------------------------------------------


class TestGetScenarioTriple:
    def test_extracts_correct_week(self):
        scenarios = {
            "conservative": [1.0, 2.0, 3.0],
            "expected": [4.0, 5.0, 6.0],
            "optimistic": [7.0, 8.0, 9.0],
        }
        triple = get_scenario_triple(scenarios, 1)
        assert triple.conservative == 2.0
        assert triple.expected == 5.0
        assert triple.optimistic == 8.0
        assert triple.unit == "%"
        assert triple.confidence_level == "68%"

    def test_week_clamped_to_max(self):
        scenarios = {
            "conservative": [1.0, 2.0],
            "expected": [3.0, 4.0],
            "optimistic": [5.0, 6.0],
        }
        triple = get_scenario_triple(scenarios, 99)
        # Clamped to week 1 (last index)
        assert triple.conservative == 2.0
        assert triple.expected == 4.0
        assert triple.optimistic == 6.0

    def test_week_zero(self):
        scenarios = {
            "conservative": [10.0, 20.0],
            "expected": [15.0, 25.0],
            "optimistic": [20.0, 30.0],
        }
        triple = get_scenario_triple(scenarios, 0)
        assert triple.conservative == 10.0
        assert triple.expected == 15.0
        assert triple.optimistic == 20.0

    def test_empty_scenarios(self):
        scenarios = {"conservative": [], "expected": [], "optimistic": []}
        triple = get_scenario_triple(scenarios, 0)
        assert triple.conservative == 0.0
        assert triple.expected == 0.0
        assert triple.optimistic == 0.0


# ---------------------------------------------------------------------------
# Tests: VisibilityForecast dataclass structure
# ---------------------------------------------------------------------------


class TestForecastStructure:
    def test_output_type(self, forecaster, observed_7_7, intent, risk_15):
        forecast = forecaster.forecast(observed_7_7, intent, risk_15, seed_key="s")
        assert isinstance(forecast, VisibilityForecast)

    def test_assumptions_non_empty(self, forecaster, observed_7_7, intent, risk_15):
        forecast = forecaster.forecast(observed_7_7, intent, risk_15, seed_key="s")
        assert len(forecast.assumptions) > 0
        assert any("baseline" in a.lower() for a in forecast.assumptions)
        assert any("ceiling" in a.lower() for a in forecast.assumptions)

    def test_default_target_weeks_24(self, forecaster, observed_7_7, intent, risk_15):
        forecast = forecaster.forecast(observed_7_7, intent, risk_15, seed_key="s")
        assert forecast.target_weeks == 24

    def test_custom_target_weeks(self, forecaster, observed_7_7, intent, risk_15):
        forecast = forecaster.forecast(
            observed_7_7, intent, risk_15, target_weeks=12, seed_key="s"
        )
        assert forecast.target_weeks == 12
        assert len(forecast.scenarios["expected"]) == 12

    def test_confidence_interval_068(self, forecaster, observed_7_7, intent, risk_15):
        forecast = forecaster.forecast(observed_7_7, intent, risk_15, seed_key="s")
        assert forecast.confidence_interval == 0.68
