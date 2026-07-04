"""Tests for ReportComposer._assemble_risks and related helpers.

Validates Task 9: Risk Section Assembly.
"""
import pytest

from app.services.forecast.report_composer import ReportComposer
from app.services.forecast.platform_risk import PlatformRiskAssessment


class MockSnapshot:
    """Mock ObservedSnapshot for testing without DB."""

    def __init__(self, metrics_json=None, data_gaps=None, source_availability=None):
        self.metrics_json = metrics_json or []
        self.data_gaps = data_gaps or []
        self.source_availability = source_availability or {}


@pytest.fixture
def composer():
    return ReportComposer()


@pytest.fixture
def low_risk():
    """PlatformRiskAssessment with low risk across the board."""
    return PlatformRiskAssessment(
        shadowban_probability=0.05,
        removal_rate_trend="stable",
        subreddit_risk_avg=30.0,
        avatar_health_score=0.9,
        account_age_factor=0.8,
        discount_factor=0.10,
    )


@pytest.fixture
def medium_risk():
    """PlatformRiskAssessment with medium risk."""
    return PlatformRiskAssessment(
        shadowban_probability=0.15,
        removal_rate_trend="stable",
        subreddit_risk_avg=50.0,
        avatar_health_score=0.7,
        account_age_factor=0.6,
        discount_factor=0.25,
    )


@pytest.fixture
def high_risk():
    """PlatformRiskAssessment with high risk."""
    return PlatformRiskAssessment(
        shadowban_probability=0.35,
        removal_rate_trend="degrading",
        subreddit_risk_avg=75.0,
        avatar_health_score=0.4,
        account_age_factor=0.3,
        discount_factor=0.45,
    )


@pytest.fixture
def snapshot_clean():
    """Snapshot with no stale metrics, no data gaps."""
    return MockSnapshot(
        metrics_json=[
            {
                "metric_id": "geo.brand_rate.overall",
                "value": 0.077,
                "is_stale": False,
                "measured_at": "2026-07-01T09:00:00+00:00",
                "staleness_threshold_hours": 168,
                "sample_size": 26,
            },
            {
                "metric_id": "reddit.survival_rate_7d",
                "value": 0.85,
                "is_stale": False,
                "measured_at": "2026-07-02T12:00:00+00:00",
                "staleness_threshold_hours": 48,
                "sample_size": 10,
            },
        ],
        data_gaps=[],
    )


@pytest.fixture
def snapshot_with_stale():
    """Snapshot with stale metrics and data gaps."""
    return MockSnapshot(
        metrics_json=[
            {
                "metric_id": "geo.brand_rate.overall",
                "value": 0.077,
                "is_stale": True,
                "measured_at": "2026-06-20T09:00:00+00:00",
                "staleness_threshold_hours": 168,
                "sample_size": 26,
            },
            {
                "metric_id": "reddit.survival_rate_7d",
                "value": 0.85,
                "is_stale": False,
                "measured_at": "2026-07-02T12:00:00+00:00",
                "staleness_threshold_hours": 48,
                "sample_size": 10,
            },
            {
                "metric_id": "execution.avg_karma_per_comment",
                "value": 3.5,
                "is_stale": True,
                "measured_at": "2026-06-15T08:00:00+00:00",
                "staleness_threshold_hours": 168,
                "sample_size": 5,
            },
        ],
        data_gaps=["ChatGPT engine not yet measured", "No GEO data for category: use_case"],
    )


# --- Test _assemble_risks output structure ---


class TestAssembleRisksStructure:
    """Tests for _assemble_risks output dict structure."""

    def test_returns_all_required_keys(self, composer, low_risk, snapshot_clean):
        result = composer._assemble_risks(low_risk, snapshot_clean)
        required_keys = [
            "label",
            "platform_risk_level",
            "platform_risk_factors",
            "forecast_sensitivity",
            "data_gaps",
            "stale_data_warnings",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_label_value(self, composer, low_risk, snapshot_clean):
        result = composer._assemble_risks(low_risk, snapshot_clean)
        assert result["label"] == "⚠️ Risks & Sensitivities"


# --- Test platform_risk_level thresholds ---


class TestPlatformRiskLevel:
    """Tests for platform_risk_level derivation from discount_factor."""

    def test_low_risk_level(self, composer, low_risk, snapshot_clean):
        """discount_factor < 0.15 → 'low'"""
        result = composer._assemble_risks(low_risk, snapshot_clean)
        assert result["platform_risk_level"] == "low"

    def test_medium_risk_level(self, composer, medium_risk, snapshot_clean):
        """0.15 <= discount_factor < 0.35 → 'medium'"""
        result = composer._assemble_risks(medium_risk, snapshot_clean)
        assert result["platform_risk_level"] == "medium"

    def test_high_risk_level(self, composer, high_risk, snapshot_clean):
        """discount_factor >= 0.35 → 'high'"""
        result = composer._assemble_risks(high_risk, snapshot_clean)
        assert result["platform_risk_level"] == "high"

    def test_boundary_015_is_medium(self, composer, snapshot_clean):
        """Exactly 0.15 should be medium."""
        risk = PlatformRiskAssessment(
            shadowban_probability=0.05,
            removal_rate_trend="stable",
            subreddit_risk_avg=30.0,
            avatar_health_score=0.9,
            account_age_factor=0.8,
            discount_factor=0.15,
        )
        result = composer._assemble_risks(risk, snapshot_clean)
        assert result["platform_risk_level"] == "medium"

    def test_boundary_035_is_high(self, composer, snapshot_clean):
        """Exactly 0.35 should be high."""
        risk = PlatformRiskAssessment(
            shadowban_probability=0.05,
            removal_rate_trend="stable",
            subreddit_risk_avg=30.0,
            avatar_health_score=0.9,
            account_age_factor=0.8,
            discount_factor=0.35,
        )
        result = composer._assemble_risks(risk, snapshot_clean)
        assert result["platform_risk_level"] == "high"


# --- Test platform_risk_factors ---


class TestPlatformRiskFactors:
    """Tests for platform_risk_factors list."""

    def test_four_factors_generated(self, composer, low_risk, snapshot_clean):
        result = composer._assemble_risks(low_risk, snapshot_clean)
        assert len(result["platform_risk_factors"]) == 4

    def test_factor_names(self, composer, low_risk, snapshot_clean):
        result = composer._assemble_risks(low_risk, snapshot_clean)
        factor_names = [f["factor"] for f in result["platform_risk_factors"]]
        assert "avatar_shadowban_risk" in factor_names
        assert "content_removal_trend" in factor_names
        assert "subreddit_moderation_risk" in factor_names
        assert "account_maturity_risk" in factor_names

    def test_factor_structure(self, composer, low_risk, snapshot_clean):
        result = composer._assemble_risks(low_risk, snapshot_clean)
        for factor in result["platform_risk_factors"]:
            assert "factor" in factor
            assert "level" in factor
            assert "impact_on_forecast" in factor
            assert "mitigation" in factor

    def test_low_shadowban_level(self, composer, low_risk, snapshot_clean):
        """shadowban_probability=0.05 → level='low'"""
        result = composer._assemble_risks(low_risk, snapshot_clean)
        sb_factor = next(
            f for f in result["platform_risk_factors"]
            if f["factor"] == "avatar_shadowban_risk"
        )
        assert sb_factor["level"] == "low"

    def test_high_shadowban_level(self, composer, high_risk, snapshot_clean):
        """shadowban_probability=0.35 → level='high'"""
        result = composer._assemble_risks(high_risk, snapshot_clean)
        sb_factor = next(
            f for f in result["platform_risk_factors"]
            if f["factor"] == "avatar_shadowban_risk"
        )
        assert sb_factor["level"] == "high"

    def test_degrading_removal_trend(self, composer, high_risk, snapshot_clean):
        """removal_rate_trend='degrading' → content_removal_trend level='high'"""
        result = composer._assemble_risks(high_risk, snapshot_clean)
        removal_factor = next(
            f for f in result["platform_risk_factors"]
            if f["factor"] == "content_removal_trend"
        )
        assert removal_factor["level"] == "high"

    def test_stable_removal_trend(self, composer, low_risk, snapshot_clean):
        """removal_rate_trend='stable' → content_removal_trend level='stable'"""
        result = composer._assemble_risks(low_risk, snapshot_clean)
        removal_factor = next(
            f for f in result["platform_risk_factors"]
            if f["factor"] == "content_removal_trend"
        )
        assert removal_factor["level"] == "stable"

    def test_mitigation_strings_non_empty(self, composer, low_risk, snapshot_clean):
        result = composer._assemble_risks(low_risk, snapshot_clean)
        for factor in result["platform_risk_factors"]:
            assert len(factor["mitigation"]) > 0


# --- Test forecast_sensitivity ---


class TestForecastSensitivity:
    """Tests for static sensitivity items."""

    def test_four_sensitivity_items(self, composer, low_risk, snapshot_clean):
        result = composer._assemble_risks(low_risk, snapshot_clean)
        assert len(result["forecast_sensitivity"]) == 4

    def test_sensitivity_item_structure(self, composer, low_risk, snapshot_clean):
        result = composer._assemble_risks(low_risk, snapshot_clean)
        for item in result["forecast_sensitivity"]:
            assert "assumption" in item
            assert "if_wrong" in item
            assert "how_we_detect" in item

    def test_sensitivity_content_sample(self, composer, low_risk, snapshot_clean):
        result = composer._assemble_risks(low_risk, snapshot_clean)
        assumptions = [item["assumption"] for item in result["forecast_sensitivity"]]
        assert any("citation lag" in a for a in assumptions)
        assert any("posting volume" in a for a in assumptions)
        assert any("policy changes" in a for a in assumptions)
        assert any("growth rates" in a for a in assumptions)


# --- Test data_gaps ---


class TestDataGaps:
    """Tests for data_gaps listing."""

    def test_empty_when_no_gaps(self, composer, low_risk, snapshot_clean):
        result = composer._assemble_risks(low_risk, snapshot_clean)
        assert result["data_gaps"] == []

    def test_includes_gaps_from_snapshot(self, composer, low_risk, snapshot_with_stale):
        result = composer._assemble_risks(low_risk, snapshot_with_stale)
        assert len(result["data_gaps"]) == 2
        assert "ChatGPT engine not yet measured" in result["data_gaps"]
        assert "No GEO data for category: use_case" in result["data_gaps"]


# --- Test stale_data_warnings ---


class TestStaleDataWarnings:
    """Tests for stale data warning extraction."""

    def test_empty_when_no_stale(self, composer, low_risk, snapshot_clean):
        result = composer._assemble_risks(low_risk, snapshot_clean)
        assert result["stale_data_warnings"] == []

    def test_stale_metrics_generate_warnings(self, composer, low_risk, snapshot_with_stale):
        result = composer._assemble_risks(low_risk, snapshot_with_stale)
        warnings = result["stale_data_warnings"]
        assert len(warnings) == 2
        # Check that stale metric IDs are mentioned
        assert any("geo.brand_rate.overall" in w for w in warnings)
        assert any("execution.avg_karma_per_comment" in w for w in warnings)

    def test_stale_warning_includes_timestamp(self, composer, low_risk, snapshot_with_stale):
        result = composer._assemble_risks(low_risk, snapshot_with_stale)
        warnings = result["stale_data_warnings"]
        # Warnings should mention the measured_at time
        assert any("2026-06-20" in w for w in warnings)

    def test_stale_warning_includes_threshold(self, composer, low_risk, snapshot_with_stale):
        result = composer._assemble_risks(low_risk, snapshot_with_stale)
        warnings = result["stale_data_warnings"]
        # Warnings should mention the threshold
        assert any("168h" in w for w in warnings)

    def test_handles_empty_metrics_json(self, composer, low_risk):
        snapshot = MockSnapshot(metrics_json=[], data_gaps=[])
        result = composer._assemble_risks(low_risk, snapshot)
        assert result["stale_data_warnings"] == []

    def test_handles_none_metrics_json(self, composer, low_risk):
        snapshot = MockSnapshot(metrics_json=None, data_gaps=[])
        result = composer._assemble_risks(low_risk, snapshot)
        assert result["stale_data_warnings"] == []
