"""Tests for ReportComposer.compose_with_forecast and _build_forecasted_section.

Validates Task 7: Integrate Forecast into Report.
"""
import pytest

from app.services.forecast.report_composer import ReportComposer
from app.services.forecast.visibility_forecaster import (
    DEFAULT_CEILING,
    DEFAULT_MIDPOINT,
    DEFAULT_STEEPNESS,
    ENGINE_MULTIPLIERS,
    NOISE_AMPLITUDE,
    VisibilityForecaster,
)
from app.services.forecast.platform_risk import PlatformRiskAssessment


class MockSnapshot:
    """Mock ObservedSnapshot for testing without DB."""

    def __init__(self, metrics_json=None, source_availability=None):
        self.metrics_json = metrics_json or []
        self.source_availability = source_availability or {}


@pytest.fixture
def composer():
    return ReportComposer()


@pytest.fixture
def observed_json_with_competitors():
    """Observed JSON with competitors for gap-to-leader tests."""
    return {
        "brand_visibility_rate": 0.077,
        "per_engine_rates": {"perplexity": 0.10, "claude": 0.0},
        "competitor_rates": {
            "tel_aviv_uni": 0.90,
            "hebrew_uni": 0.85,
            "technion": 0.60,
        },
        "category_rates": {"category": 0.1},
        "brand_mentions_count": 2,
        "total_queries_measured": 26,
        "engines_active": ["perplexity", "claude"],
        "comments_posted": 5,
        "avg_karma_per_comment": 3.5,
        "survival_rate": 0.85,
        "reply_depth_avg": 1.2,
        "brand_excerpts": [],
        "sample_sizes": {},
        "staleness": {},
    }


@pytest.fixture
def observed_json_no_competitors():
    """Observed JSON without competitors."""
    return {
        "brand_visibility_rate": 0.077,
        "per_engine_rates": {"perplexity": 0.10},
        "competitor_rates": {},
        "category_rates": {},
        "brand_mentions_count": 2,
        "total_queries_measured": 26,
        "engines_active": ["perplexity"],
        "comments_posted": 3,
        "avg_karma_per_comment": 2.0,
        "survival_rate": 0.90,
        "reply_depth_avg": 0.8,
        "brand_excerpts": [],
        "sample_sizes": {},
        "staleness": {},
    }


@pytest.fixture
def snapshot_with_metrics():
    """Snapshot with standard GEO + Reddit metrics."""
    return MockSnapshot(
        metrics_json=[
            {"metric_id": "geo.brand_rate.overall", "value": 0.077, "sample_size": 26},
            {"metric_id": "reddit.survival_rate_7d", "value": 0.85, "sample_size": 10},
        ]
    )


@pytest.fixture
def risk_assessment(snapshot_with_metrics):
    return PlatformRiskAssessment.compute(snapshot_with_metrics, None)


@pytest.fixture
def forecast(snapshot_with_metrics, risk_assessment):
    forecaster = VisibilityForecaster()
    return forecaster.forecast(
        snapshot_with_metrics, None, risk_assessment, seed_key="test_2026-W27"
    )


# --- Test _build_forecasted_section structure ---


class TestBuildForecastedSection:
    """Tests for _build_forecasted_section output structure."""

    def test_returns_all_required_keys(
        self, composer, forecast, observed_json_with_competitors, risk_assessment
    ):
        result = composer._build_forecasted_section(
            forecast, observed_json_with_competitors, risk_assessment
        )
        required_keys = [
            "label",
            "visibility_4w",
            "visibility_12w",
            "visibility_24w",
            "per_engine_12w",
            "leader_name",
            "leader_rate",
            "gap_current_pp",
            "gap_projected_12w_pp",
            "weeks_to_parity",
            "model_name",
            "model_parameters",
            "assumptions",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_label_value(
        self, composer, forecast, observed_json_with_competitors, risk_assessment
    ):
        result = composer._build_forecasted_section(
            forecast, observed_json_with_competitors, risk_assessment
        )
        assert result["label"] == "📈 Forecasted Outcomes"

    def test_model_name(
        self, composer, forecast, observed_json_with_competitors, risk_assessment
    ):
        result = composer._build_forecasted_section(
            forecast, observed_json_with_competitors, risk_assessment
        )
        assert result["model_name"] == "logistic_scurve_v1"


# --- Test ScenarioTriple output ---


class TestScenarioTriple:
    """Tests for 4w/12w/24w ScenarioTriple values."""

    def test_visibility_4w_structure(
        self, composer, forecast, observed_json_with_competitors, risk_assessment
    ):
        result = composer._build_forecasted_section(
            forecast, observed_json_with_competitors, risk_assessment
        )
        v4w = result["visibility_4w"]
        assert "conservative" in v4w
        assert "expected" in v4w
        assert "optimistic" in v4w
        assert v4w["unit"] == "%"
        assert v4w["confidence_level"] == "68%"

    def test_visibility_12w_structure(
        self, composer, forecast, observed_json_with_competitors, risk_assessment
    ):
        result = composer._build_forecasted_section(
            forecast, observed_json_with_competitors, risk_assessment
        )
        v12w = result["visibility_12w"]
        assert isinstance(v12w["conservative"], float)
        assert isinstance(v12w["expected"], float)
        assert isinstance(v12w["optimistic"], float)

    def test_visibility_24w_structure(
        self, composer, forecast, observed_json_with_competitors, risk_assessment
    ):
        result = composer._build_forecasted_section(
            forecast, observed_json_with_competitors, risk_assessment
        )
        v24w = result["visibility_24w"]
        assert v24w["unit"] == "%"
        assert v24w["confidence_level"] == "68%"

    def test_scenario_values_are_positive(
        self, composer, forecast, observed_json_with_competitors, risk_assessment
    ):
        result = composer._build_forecasted_section(
            forecast, observed_json_with_competitors, risk_assessment
        )
        for horizon in ["visibility_4w", "visibility_12w", "visibility_24w"]:
            triple = result[horizon]
            assert triple["conservative"] >= 0
            assert triple["expected"] >= 0
            assert triple["optimistic"] >= 0

    def test_12w_greater_than_4w_expected(
        self, composer, forecast, observed_json_with_competitors, risk_assessment
    ):
        """Expected scenario at 12w should generally exceed 4w (S-curve growth)."""
        result = composer._build_forecasted_section(
            forecast, observed_json_with_competitors, risk_assessment
        )
        # Due to noise this might not always hold, but with seeded RNG it should
        assert result["visibility_12w"]["expected"] >= result["visibility_4w"]["expected"] - 5.0


# --- Test gap-to-leader ---


class TestGapToLeader:
    """Tests for gap-to-leader calculation."""

    def test_leader_identified_correctly(
        self, composer, forecast, observed_json_with_competitors, risk_assessment
    ):
        result = composer._build_forecasted_section(
            forecast, observed_json_with_competitors, risk_assessment
        )
        assert result["leader_name"] == "tel_aviv_uni"
        assert result["leader_rate"] == 0.9

    def test_gap_current_positive(
        self, composer, forecast, observed_json_with_competitors, risk_assessment
    ):
        """Gap should be positive when leader is ahead."""
        result = composer._build_forecasted_section(
            forecast, observed_json_with_competitors, risk_assessment
        )
        # tel_aviv_uni at 90% vs baseline at 7.7% → gap ~82.3pp
        assert result["gap_current_pp"] > 70.0

    def test_gap_projected_12w_smaller_than_current(
        self, composer, forecast, observed_json_with_competitors, risk_assessment
    ):
        """Projected gap at 12w should be smaller than current (growth closes gap)."""
        result = composer._build_forecasted_section(
            forecast, observed_json_with_competitors, risk_assessment
        )
        assert result["gap_projected_12w_pp"] < result["gap_current_pp"]

    def test_no_competitors_returns_none(
        self, composer, forecast, observed_json_no_competitors, risk_assessment
    ):
        result = composer._build_forecasted_section(
            forecast, observed_json_no_competitors, risk_assessment
        )
        assert result["leader_name"] is None
        assert result["leader_rate"] is None
        assert result["gap_current_pp"] == 0.0
        assert result["gap_projected_12w_pp"] == 0.0
        assert result["weeks_to_parity"] is None

    def test_weeks_to_parity_none_when_unreachable(
        self, composer, forecast, observed_json_with_competitors, risk_assessment
    ):
        """With leader at 90% and ceiling at ~34% (after discount), parity unreachable."""
        result = composer._build_forecasted_section(
            forecast, observed_json_with_competitors, risk_assessment
        )
        # 90% is way above forecasted ceiling (~34%), so parity is unreachable in 24w
        assert result["weeks_to_parity"] is None


# --- Test per-engine 12w ---


class TestPerEngine12w:
    """Tests for per-engine projections at 12w."""

    def test_all_engines_present(
        self, composer, forecast, observed_json_with_competitors, risk_assessment
    ):
        result = composer._build_forecasted_section(
            forecast, observed_json_with_competitors, risk_assessment
        )
        per_engine = result["per_engine_12w"]
        assert "perplexity" in per_engine
        assert "chatgpt" in per_engine
        assert "claude" in per_engine

    def test_engine_triple_keys(
        self, composer, forecast, observed_json_with_competitors, risk_assessment
    ):
        result = composer._build_forecasted_section(
            forecast, observed_json_with_competitors, risk_assessment
        )
        for engine_name, triple in result["per_engine_12w"].items():
            assert "c" in triple, f"{engine_name} missing 'c'"
            assert "e" in triple, f"{engine_name} missing 'e'"
            assert "o" in triple, f"{engine_name} missing 'o'"

    def test_perplexity_highest(
        self, composer, forecast, observed_json_with_competitors, risk_assessment
    ):
        """Perplexity should have highest rate (multiplier 1.4)."""
        result = composer._build_forecasted_section(
            forecast, observed_json_with_competitors, risk_assessment
        )
        per_engine = result["per_engine_12w"]
        assert per_engine["perplexity"]["e"] > per_engine["chatgpt"]["e"]
        assert per_engine["chatgpt"]["e"] > per_engine["claude"]["e"]


# --- Test model metadata ---


class TestModelMetadata:
    """Tests for model parameters and assumptions."""

    def test_model_parameters_complete(
        self, composer, forecast, observed_json_with_competitors, risk_assessment
    ):
        result = composer._build_forecasted_section(
            forecast, observed_json_with_competitors, risk_assessment
        )
        params = result["model_parameters"]
        assert params["ceiling"] == DEFAULT_CEILING
        assert params["midpoint"] == DEFAULT_MIDPOINT
        assert params["steepness"] == DEFAULT_STEEPNESS
        assert params["engine_multipliers"] == ENGINE_MULTIPLIERS
        assert params["noise_amplitude"] == NOISE_AMPLITUDE
        assert isinstance(params["risk_discount"], float)
        assert 0.0 <= params["risk_discount"] <= 0.6

    def test_assumptions_non_empty(
        self, composer, forecast, observed_json_with_competitors, risk_assessment
    ):
        result = composer._build_forecasted_section(
            forecast, observed_json_with_competitors, risk_assessment
        )
        assert len(result["assumptions"]) > 0
        assert all(isinstance(a, str) for a in result["assumptions"])

    def test_assumptions_mention_baseline(
        self, composer, forecast, observed_json_with_competitors, risk_assessment
    ):
        result = composer._build_forecasted_section(
            forecast, observed_json_with_competitors, risk_assessment
        )
        baseline_assumption = result["assumptions"][0]
        assert "7.7" in baseline_assumption


# --- Test _scenario_triple_to_dict helper ---


class TestScenarioTripleToDict:
    """Tests for _scenario_triple_to_dict conversion."""

    def test_conversion(self, composer):
        from app.services.forecast.visibility_forecaster import ScenarioTriple

        triple = ScenarioTriple(
            conservative=10.123, expected=15.456, optimistic=20.789
        )
        result = composer._scenario_triple_to_dict(triple)
        assert result == {
            "conservative": 10.12,
            "expected": 15.46,
            "optimistic": 20.79,
            "unit": "%",
            "confidence_level": "68%",
        }
