"""Platform Risk Assessment — Layer 3 Risk Discounting.

Quantifies platform-level risk factors that discount forecast ceilings.
Uses observed metrics (survival rate, removal rate) plus defaults for
factors not yet directly measurable from metrics_json.

Composite discount formula:
    health_risk = 1.0 - avatar_health_score
    removal_risk = {"improving": 0.05, "stable": 0.1, "degrading": 0.3}[trend]
    sub_risk = subreddit_risk_avg / 100.0
    age_risk = 1.0 - account_age_factor
    ban_risk = shadowban_probability

    weights = health=0.25, removal=0.25, sub=0.2, age=0.15, ban=0.15
    composite = weighted_sum(...)
    discount_factor = min(0.6, composite)  # never discount > 60%

Validates: Requirements R3.4, R3.5
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Self


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Removal rate trend thresholds
REMOVAL_IMPROVING_THRESHOLD = 0.05
REMOVAL_DEGRADING_THRESHOLD = 0.15

# Risk weights for composite calculation
WEIGHTS = {
    "health": 0.25,
    "removal": 0.25,
    "sub": 0.20,
    "age": 0.15,
    "ban": 0.15,
}

# Removal trend to risk value mapping
REMOVAL_TREND_RISK = {
    "improving": 0.05,
    "stable": 0.10,
    "degrading": 0.30,
}

# Maximum discount (never discount more than 60% of ceiling)
MAX_DISCOUNT = 0.6

# Defaults for factors not yet derivable from observed metrics
DEFAULT_SUBREDDIT_RISK_AVG = 30.0  # low-moderate, enhanced when intent provides data
DEFAULT_ACCOUNT_AGE_FACTOR = 0.8  # moderate maturity
DEFAULT_SHADOWBAN_LOW = 0.05  # default low probability
DEFAULT_SHADOWBAN_HIGH_REMOVAL_THRESHOLD = 0.2  # if removal > this, higher ban prob


# ---------------------------------------------------------------------------
# Output Dataclass
# ---------------------------------------------------------------------------


@dataclass
class PlatformRiskAssessment:
    """Quantified platform risk that discounts forecasts."""

    shadowban_probability: float  # 0.0-1.0 per avatar, averaged
    removal_rate_trend: str  # "improving" | "stable" | "degrading"
    subreddit_risk_avg: float  # avg risk_score across active subs
    avatar_health_score: float  # % of avatars in healthy state (0.0-1.0)
    account_age_factor: float  # young accounts = higher risk (0.0-1.0)
    discount_factor: float  # composite: applied to forecast ceiling (0.0-0.6)

    @classmethod
    def compute(cls, observed: Any, intent: Any) -> Self:
        """Compute risk assessment from observed data.

        Args:
            observed: Object with `metrics_json` (list of metric dicts).
                      Expected metrics:
                        - "reddit.survival_rate_7d" → avatar_health_score
                        - "reddit.removal_rate_7d" → removal_rate_trend + shadowban_probability
            intent: Object (unused in v1, placeholder for future enhancement
                    when subreddit data and avatar details are available).

        Returns:
            Fully populated PlatformRiskAssessment instance.
        """
        metrics = _extract_metrics(observed)

        # 1. Avatar health score from survival rate
        avatar_health_score = _compute_avatar_health_score(metrics)

        # 2. Removal rate trend classification
        removal_rate = _get_removal_rate(metrics)
        removal_rate_trend = _classify_removal_trend(removal_rate)

        # 3. Subreddit risk average (default for v1)
        subreddit_risk_avg = DEFAULT_SUBREDDIT_RISK_AVG

        # 4. Account age factor (default for v1)
        account_age_factor = DEFAULT_ACCOUNT_AGE_FACTOR

        # 5. Shadowban probability from removal rate
        shadowban_probability = _compute_shadowban_probability(removal_rate)

        # 6. Composite discount
        discount_factor = _compute_discount(
            avatar_health_score=avatar_health_score,
            removal_rate_trend=removal_rate_trend,
            subreddit_risk_avg=subreddit_risk_avg,
            account_age_factor=account_age_factor,
            shadowban_probability=shadowban_probability,
        )

        return cls(
            shadowban_probability=round(shadowban_probability, 4),
            removal_rate_trend=removal_rate_trend,
            subreddit_risk_avg=round(subreddit_risk_avg, 2),
            avatar_health_score=round(avatar_health_score, 4),
            account_age_factor=round(account_age_factor, 4),
            discount_factor=round(discount_factor, 4),
        )


# ---------------------------------------------------------------------------
# Private Helpers
# ---------------------------------------------------------------------------


def _extract_metrics(observed: Any) -> dict[str, float]:
    """Extract relevant metrics from observed.metrics_json into a flat dict.

    Looks for metric_id keys and extracts their float values.
    """
    metrics_json = getattr(observed, "metrics_json", None)
    if not metrics_json or not isinstance(metrics_json, list):
        return {}

    result: dict[str, float] = {}
    for metric in metrics_json:
        if isinstance(metric, dict):
            metric_id = metric.get("metric_id", "")
            value = metric.get("value")
            if metric_id and isinstance(value, (int, float)):
                result[metric_id] = float(value)
    return result


def _compute_avatar_health_score(metrics: dict[str, float]) -> float:
    """Compute avatar health score from survival rate.

    survival_rate > 0.90 → score = 1.0 (healthy)
    survival_rate < 0.50 → score = 0.3
    Linear interpolation between 0.50-0.90.
    """
    survival_rate = metrics.get("reddit.survival_rate_7d")

    if survival_rate is None:
        # No data available — assume moderate health
        return 0.7

    # Clamp survival rate to [0, 1]
    survival_rate = max(0.0, min(1.0, survival_rate))

    if survival_rate >= 0.90:
        return 1.0
    elif survival_rate <= 0.50:
        return 0.3
    else:
        # Linear interpolation between (0.50, 0.3) and (0.90, 1.0)
        # slope = (1.0 - 0.3) / (0.90 - 0.50) = 0.7 / 0.4 = 1.75
        return 0.3 + (survival_rate - 0.50) * (0.7 / 0.4)


def _get_removal_rate(metrics: dict[str, float]) -> float | None:
    """Get removal rate from metrics, or None if not available."""
    return metrics.get("reddit.removal_rate_7d")


def _classify_removal_trend(removal_rate: float | None) -> str:
    """Classify removal rate into trend category.

    < 0.05 → "improving"
    0.05-0.15 → "stable"
    > 0.15 → "degrading"

    None → "stable" (default when no data)
    """
    if removal_rate is None:
        return "stable"

    if removal_rate < REMOVAL_IMPROVING_THRESHOLD:
        return "improving"
    elif removal_rate > REMOVAL_DEGRADING_THRESHOLD:
        return "degrading"
    else:
        return "stable"


def _compute_shadowban_probability(removal_rate: float | None) -> float:
    """Derive shadowban probability from removal rate.

    If removal > 0.2 → higher probability (linear scale to 0.3).
    Default low: 0.05.
    """
    if removal_rate is None:
        return DEFAULT_SHADOWBAN_LOW

    if removal_rate <= DEFAULT_SHADOWBAN_HIGH_REMOVAL_THRESHOLD:
        return DEFAULT_SHADOWBAN_LOW
    else:
        # Linear scale: 0.2 → 0.05, 1.0 → 0.30
        # slope = (0.30 - 0.05) / (1.0 - 0.2) = 0.25 / 0.8 = 0.3125
        prob = DEFAULT_SHADOWBAN_LOW + (removal_rate - DEFAULT_SHADOWBAN_HIGH_REMOVAL_THRESHOLD) * 0.3125
        return min(0.30, prob)


def _compute_discount(
    avatar_health_score: float,
    removal_rate_trend: str,
    subreddit_risk_avg: float,
    account_age_factor: float,
    shadowban_probability: float,
) -> float:
    """Compute composite discount factor from all risk indicators.

    Each factor contributes to the discount (higher = riskier, range [0, 1]).
    Total discount is a weighted average clamped to [0, 0.6].
    """
    health_risk = 1.0 - avatar_health_score
    removal_risk = REMOVAL_TREND_RISK.get(removal_rate_trend, 0.10)
    sub_risk = subreddit_risk_avg / 100.0
    age_risk = 1.0 - account_age_factor
    ban_risk = shadowban_probability

    composite = (
        WEIGHTS["health"] * health_risk
        + WEIGHTS["removal"] * removal_risk
        + WEIGHTS["sub"] * sub_risk
        + WEIGHTS["age"] * age_risk
        + WEIGHTS["ban"] * ban_risk
    )

    # Clamp to [0, MAX_DISCOUNT] — never discount more than 60% of ceiling
    return max(0.0, min(MAX_DISCOUNT, composite))
