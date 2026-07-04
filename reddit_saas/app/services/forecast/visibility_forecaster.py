"""Visibility Forecaster — Layer 3 S-Curve Engine.

Implements a logistic S-curve projection for AI search visibility growth,
with per-engine multipliers, three scenarios (conservative/expected/optimistic),
and seeded noise for reproducible reports.

S-curve formula:
    rate(week) = baseline + (ceiling - baseline) / (1 + exp(-steepness * (week - midpoint)))

Per-engine:
    Each engine gets its own projection: engine_ceiling = overall_ceiling × engine_multiplier

Noise:
    Seeded random (hash of client_id + report_period) for reproducibility.
    ±2.5pp uniform random noise added per week, clamped to [0, 100].

Validates: Requirements R3.1, R3.2, R3.3, R3.5, R3.9
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Output Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class VisibilityForecast:
    """Projected brand visibility over time."""

    baseline_rate: float
    target_weeks: int  # default 24
    scenarios: dict[str, list[float]]  # {"conservative": [...], "expected": [...], "optimistic": [...]}
    per_engine: dict[str, list[float]]  # per-engine projections (expected scenario)
    confidence_interval: float  # 0.68 (1σ)
    assumptions: list[str]
    risk_discount: float  # from platform risk assessment


@dataclass
class ScenarioTriple:
    """Three scenarios for a specific week."""

    conservative: float
    expected: float
    optimistic: float
    unit: str = "%"
    confidence_level: str = "68%"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENGINE_MULTIPLIERS: dict[str, float] = {
    "perplexity": 1.4,  # cites Reddit most aggressively
    "chatgpt": 1.0,  # web grounding, less Reddit-specific
    "claude": 0.65,  # newest web search, least Reddit-dependent
}

DEFAULT_CEILING = 40.0  # realistic max after 6mo active Reddit content
DEFAULT_MIDPOINT = 12  # weeks to inflection
DEFAULT_STEEPNESS = 0.4
NOISE_AMPLITUDE = 2.5  # ±pp weekly noise
DEFAULT_TARGET_WEEKS = 24
CONFIDENCE_INTERVAL = 0.68  # 1σ


# ---------------------------------------------------------------------------
# Core S-Curve Function
# ---------------------------------------------------------------------------


def _scurve(
    week: int,
    baseline: float,
    ceiling: float,
    midpoint: float,
    steepness: float,
) -> float:
    """Compute a single S-curve value at a given week.

    Args:
        week: The week number (0-indexed).
        baseline: Starting rate (%).
        ceiling: Maximum achievable rate (%).
        midpoint: Week at inflection point.
        steepness: Growth rate parameter.

    Returns:
        Projected rate at the given week (not clamped — caller handles clamping).
    """
    exponent = -steepness * (week - midpoint)
    # Guard against overflow in exp()
    if exponent > 500:
        return baseline
    if exponent < -500:
        return ceiling
    return baseline + (ceiling - baseline) / (1.0 + math.exp(exponent))


# ---------------------------------------------------------------------------
# Helper: ScenarioTriple extraction
# ---------------------------------------------------------------------------


def get_scenario_triple(scenarios: dict[str, list[float]], week: int) -> ScenarioTriple:
    """Extract scenario values at a specific week index.

    Args:
        scenarios: Dict with keys "conservative", "expected", "optimistic",
                   each containing a list of weekly values.
        week: Week index (0-based). Clamped to valid range.

    Returns:
        ScenarioTriple with the values at the given week.
    """
    # Clamp week to valid range
    max_week = min(
        len(scenarios.get("conservative", [])),
        len(scenarios.get("expected", [])),
        len(scenarios.get("optimistic", [])),
    ) - 1
    if max_week < 0:
        return ScenarioTriple(conservative=0.0, expected=0.0, optimistic=0.0)
    week = max(0, min(week, max_week))

    return ScenarioTriple(
        conservative=scenarios["conservative"][week],
        expected=scenarios["expected"][week],
        optimistic=scenarios["optimistic"][week],
    )


# ---------------------------------------------------------------------------
# Main Forecaster
# ---------------------------------------------------------------------------


class VisibilityForecaster:
    """S-curve projection with per-engine rates and risk discounting.

    Usage:
        forecaster = VisibilityForecaster()
        forecast = forecaster.forecast(observed, intent, platform_risk)
    """

    def forecast(
        self,
        observed: Any,
        intent: Any,
        platform_risk: Any,
        *,
        target_weeks: int = DEFAULT_TARGET_WEEKS,
        seed_key: str = "",
    ) -> VisibilityForecast:
        """Generate a visibility forecast from observed data and platform risk.

        Args:
            observed: Object with `metrics_json` (list of metric dicts).
                      Used to extract baseline brand rate.
            intent: Object (unused in v1, placeholder for future intent integration).
            platform_risk: Object with `discount_factor` (float 0.0-1.0).
                           Applied to reduce the ceiling.
            target_weeks: Number of weeks to project (default 24).
            seed_key: Seed string for reproducible noise (e.g., client_id + report_period).
                      If empty, noise is still seeded but deterministically from "default".

        Returns:
            VisibilityForecast with scenarios, per-engine projections, and metadata.
        """
        # 1. Extract baseline from observed metrics
        baseline = self._get_baseline(observed)

        # 2. Compute effective ceiling with platform risk discount
        discount_factor = getattr(platform_risk, "discount_factor", 0.0)
        effective_ceiling = DEFAULT_CEILING * (1.0 - discount_factor)

        # 3. Create seeded RNG for reproducibility
        rng = self._make_rng(seed_key)

        # 4. Generate 3 scenarios as lists of weekly rates
        scenarios = self._generate_scenarios(
            baseline=baseline,
            ceiling=effective_ceiling,
            target_weeks=target_weeks,
            rng=rng,
        )

        # 5. Generate per-engine projections (expected scenario params + engine multiplier)
        per_engine = self._generate_per_engine(
            baseline=baseline,
            ceiling=effective_ceiling,
            target_weeks=target_weeks,
            rng=rng,
        )

        # 6. Document assumptions
        assumptions = self._document_assumptions(
            baseline=baseline,
            ceiling=effective_ceiling,
            discount_factor=discount_factor,
        )

        return VisibilityForecast(
            baseline_rate=round(baseline, 2),
            target_weeks=target_weeks,
            scenarios=scenarios,
            per_engine=per_engine,
            confidence_interval=CONFIDENCE_INTERVAL,
            assumptions=assumptions,
            risk_discount=round(discount_factor, 4),
        )

    # ------------------------------------------------------------------
    # Private: Baseline Extraction
    # ------------------------------------------------------------------

    def _get_baseline(self, observed: Any) -> float:
        """Extract baseline brand rate from observed metrics.

        Looks for "geo.brand_rate.overall" in metrics_json.
        Falls back to 0.0 if not found.
        """
        metrics_json = getattr(observed, "metrics_json", None)
        if not metrics_json or not isinstance(metrics_json, list):
            return 0.0

        for metric in metrics_json:
            if isinstance(metric, dict) and metric.get("metric_id") == "geo.brand_rate.overall":
                value = metric.get("value", 0.0)
                # Value is stored as a ratio (0.0-1.0), convert to percentage
                if isinstance(value, (int, float)):
                    # If value is <= 1.0, assume it's a ratio and convert to %
                    if value <= 1.0:
                        return value * 100.0
                    return float(value)
                return 0.0

        return 0.0

    # ------------------------------------------------------------------
    # Private: RNG Seed
    # ------------------------------------------------------------------

    def _make_rng(self, seed_key: str) -> random.Random:
        """Create a seeded Random instance for reproducible noise.

        Seed = hash of seed_key (typically client_id + report_period).
        """
        if not seed_key:
            seed_key = "default"
        seed_int = int(hashlib.sha256(seed_key.encode()).hexdigest()[:8], 16)
        return random.Random(seed_int)

    # ------------------------------------------------------------------
    # Private: Scenario Generation
    # ------------------------------------------------------------------

    def _generate_scenarios(
        self,
        baseline: float,
        ceiling: float,
        target_weeks: int,
        rng: random.Random,
    ) -> dict[str, list[float]]:
        """Generate 3 scenarios as lists of weekly rates with noise.

        Conservative: ceiling × 0.7, midpoint + 2
        Expected: ceiling, midpoint (default)
        Optimistic: ceiling × 1.2, midpoint - 2
        """
        scenario_params = {
            "conservative": {
                "ceiling": ceiling * 0.7,
                "midpoint": DEFAULT_MIDPOINT + 2,
            },
            "expected": {
                "ceiling": ceiling,
                "midpoint": DEFAULT_MIDPOINT,
            },
            "optimistic": {
                "ceiling": ceiling * 1.2,
                "midpoint": DEFAULT_MIDPOINT - 2,
            },
        }

        scenarios: dict[str, list[float]] = {}

        for scenario_name, params in scenario_params.items():
            weekly_rates: list[float] = []
            for week in range(target_weeks):
                raw_rate = _scurve(
                    week=week,
                    baseline=baseline,
                    ceiling=params["ceiling"],
                    midpoint=params["midpoint"],
                    steepness=DEFAULT_STEEPNESS,
                )
                # Add seeded noise
                noise = rng.uniform(-NOISE_AMPLITUDE, NOISE_AMPLITUDE)
                noisy_rate = raw_rate + noise
                # Clamp to [0, 100]
                clamped = max(0.0, min(100.0, noisy_rate))
                weekly_rates.append(round(clamped, 2))

            scenarios[scenario_name] = weekly_rates

        return scenarios

    # ------------------------------------------------------------------
    # Private: Per-Engine Projections
    # ------------------------------------------------------------------

    def _generate_per_engine(
        self,
        baseline: float,
        ceiling: float,
        target_weeks: int,
        rng: random.Random,
    ) -> dict[str, list[float]]:
        """Generate per-engine projections using ENGINE_MULTIPLIERS.

        Each engine uses the expected scenario parameters (default midpoint/steepness)
        with its own ceiling: engine_ceiling = overall_ceiling × engine_multiplier.
        """
        per_engine: dict[str, list[float]] = {}

        for engine_name, multiplier in ENGINE_MULTIPLIERS.items():
            engine_ceiling = ceiling * multiplier
            weekly_rates: list[float] = []

            for week in range(target_weeks):
                raw_rate = _scurve(
                    week=week,
                    baseline=baseline,
                    ceiling=engine_ceiling,
                    midpoint=DEFAULT_MIDPOINT,
                    steepness=DEFAULT_STEEPNESS,
                )
                # Add seeded noise per engine
                noise = rng.uniform(-NOISE_AMPLITUDE, NOISE_AMPLITUDE)
                noisy_rate = raw_rate + noise
                # Clamp to [0, 100]
                clamped = max(0.0, min(100.0, noisy_rate))
                weekly_rates.append(round(clamped, 2))

            per_engine[engine_name] = weekly_rates

        return per_engine

    # ------------------------------------------------------------------
    # Private: Assumptions Documentation
    # ------------------------------------------------------------------

    def _document_assumptions(
        self,
        baseline: float,
        ceiling: float,
        discount_factor: float,
    ) -> list[str]:
        """Generate explicit list of assumptions for this forecast."""
        assumptions = [
            f"Baseline brand visibility rate: {baseline:.1f}%",
            f"Maximum achievable ceiling (post-risk discount): {ceiling:.1f}%",
            f"Platform risk discount applied: {discount_factor*100:.1f}%",
            f"Inflection point at week {DEFAULT_MIDPOINT} (expected scenario)",
            f"Growth steepness parameter: {DEFAULT_STEEPNESS}",
            "Assumes continued Reddit content production at current volume",
            "Assumes no major platform policy changes affecting AI citation",
            "Per-engine multipliers: Perplexity ×1.4, ChatGPT ×1.0, Claude ×0.65",
            "Noise: ±2.5pp uniform random per week (seeded for reproducibility)",
        ]

        if discount_factor > 0:
            original_ceiling = DEFAULT_CEILING
            assumptions.append(
                f"Original ceiling {original_ceiling:.1f}% reduced to {ceiling:.1f}% due to platform risk"
            )

        return assumptions
