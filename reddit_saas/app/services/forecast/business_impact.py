"""Business Impact Calculator — Layer 5 of Forecast & Reporting.

Computes business-level metrics from observed data and forecasts:
- Category rank (client position among competitors)
- Gap closure rate (pp/week)
- Weeks to parity with leader
- ROI framing (cost per visibility point)
- Measurable vs inferred metric classification
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Plan pricing (monthly investment in USD)
PLAN_PRICES: dict[str, int] = {
    "trial": 0,
    "seed": 149,
    "starter": 399,
    "growth": 799,
    "scale": 1499,
}

# Fixed metric classifications
MEASURABLE_METRICS: list[str] = [
    "AI visibility rate",
    "Reddit karma",
    "survival rate",
    "comment volume",
]

INFERRED_METRICS: list[str] = [
    "traffic from AI search",
    "lead quality",
    "brand authority",
]

DEFAULT_DISCLAIMER: str = (
    "These projections assume continued Reddit content production "
    "at current volume, no major platform policy changes, and typical "
    "AI search citation behavior. Actual results may vary. "
    "Visibility ≠ traffic (correlation, not causation)."
)


@dataclass
class BusinessImpact:
    """Computed business impact metrics."""

    category_rank: int
    category_total: int
    projected_rank_12w: int
    gap_to_leader: dict[str, Any]
    investment_monthly: float
    projected_visibility_gain_pp: float
    cost_per_visibility_point: float | None
    measurable: list[str] = field(default_factory=lambda: list(MEASURABLE_METRICS))
    inferred: list[str] = field(default_factory=lambda: list(INFERRED_METRICS))
    disclaimer: str = DEFAULT_DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict suitable for JSONB storage."""
        return {
            "label": "💰 Business Impact",
            "category_rank": self.category_rank,
            "category_total": self.category_total,
            "projected_rank_12w": self.projected_rank_12w,
            "gap_to_leader": self.gap_to_leader,
            "investment_monthly": self.investment_monthly,
            "projected_visibility_gain_pp": self.projected_visibility_gain_pp,
            "cost_per_visibility_point": self.cost_per_visibility_point,
            "measurable": self.measurable,
            "inferred": self.inferred,
            "disclaimer": self.disclaimer,
        }


class BusinessImpactCalculator:
    """Computes business impact metrics from observed and forecasted data.

    Extracts and formalizes the logic previously inline in
    ReportComposer._build_business_impact_section().
    """

    def compute(
        self,
        observed_json: dict[str, Any],
        forecasted_json: dict[str, Any],
        plan_type: str = "starter",
    ) -> BusinessImpact:
        """Compute all business impact metrics.

        Args:
            observed_json: Observed section with brand_visibility_rate and
                competitor_rates (rates as ratios 0-1).
            forecasted_json: Forecasted section with visibility projections
                (percentages 0-100) and optional weeks_to_parity.
            plan_type: Client's subscription plan type for ROI calculation.

        Returns:
            BusinessImpact dataclass with all computed metrics.
        """
        competitor_rates = observed_json.get("competitor_rates", {})
        client_rate = observed_json.get("brand_visibility_rate", 0.0)

        # Category rank (current)
        category_rank, category_total = self.compute_category_rank(
            competitor_rates, client_rate
        )

        # Projected rate at 12w (extract from forecasted_json, in %)
        visibility_12w = forecasted_json.get("visibility_12w", {})
        projected_12w_pct = 0.0
        if isinstance(visibility_12w, dict):
            projected_12w_pct = visibility_12w.get("expected", 0.0)
        projected_12w_ratio = projected_12w_pct / 100.0 if projected_12w_pct else 0.0

        # Projected rank at 12w
        projected_rank_12w, _ = self.compute_category_rank(
            competitor_rates, projected_12w_ratio
        )

        # Gap to leader
        gap_to_leader = self._compute_gap_to_leader(
            competitor_rates, client_rate, projected_12w_ratio, forecasted_json
        )

        # ROI framing
        baseline_pct = client_rate * 100.0
        visibility_24w = forecasted_json.get("visibility_24w", {})
        expected_24w_pct = 0.0
        if isinstance(visibility_24w, dict):
            expected_24w_pct = visibility_24w.get("expected", 0.0)
        projected_gain_pp = round(max(0.0, expected_24w_pct - baseline_pct), 2)

        investment_monthly, cost_per_point = self.compute_roi(
            plan_type, projected_gain_pp
        )

        return BusinessImpact(
            category_rank=category_rank,
            category_total=category_total,
            projected_rank_12w=projected_rank_12w,
            gap_to_leader=gap_to_leader,
            investment_monthly=investment_monthly,
            projected_visibility_gain_pp=projected_gain_pp,
            cost_per_visibility_point=cost_per_point,
        )

    def compute_category_rank(
        self, competitor_rates: dict[str, float], client_rate: float
    ) -> tuple[int, int]:
        """Compute client's position among all entities (1-indexed).

        Sorts all entities (competitors + client) by rate descending.
        Returns (rank, total_entities).

        Args:
            competitor_rates: Dict mapping competitor names to their rates
                (as ratios 0-1).
            client_rate: Client's rate (as ratio 0-1).

        Returns:
            Tuple of (rank, total) where rank is 1-indexed position.
        """
        all_entities: list[tuple[str, float]] = []
        for name, rate in competitor_rates.items():
            all_entities.append((name, rate))
        all_entities.append(("__client__", client_rate))

        # Sort descending by rate
        all_entities.sort(key=lambda x: x[1], reverse=True)

        # Find client's position (1-indexed)
        category_rank = 1
        for i, (name, _rate) in enumerate(all_entities):
            if name == "__client__":
                category_rank = i + 1
                break

        return category_rank, len(all_entities)

    def compute_gap_closure_rate(
        self, gap_current_pp: float, gap_projected_12w_pp: float
    ) -> float:
        """Compute gap closure rate in percentage points per week.

        closure_rate = (current_gap - projected_gap) / 12 weeks.
        If negative or zero (client falling behind), returns 0.0.

        Args:
            gap_current_pp: Current gap to leader in percentage points.
            gap_projected_12w_pp: Projected gap at 12 weeks in pp.

        Returns:
            Closure rate in pp/week (0.0 if gap is widening).
        """
        gap_closed = gap_current_pp - gap_projected_12w_pp
        if gap_closed <= 0:
            return 0.0
        return round(gap_closed / 12.0, 2)

    def compute_weeks_to_parity(
        self,
        forecasted_json: dict[str, Any],
        gap_current_pp: float | None = None,
        closure_rate_pp_per_week: float | None = None,
    ) -> int | None:
        """Estimate weeks until client reaches the leader.

        Uses forecasted_json["weeks_to_parity"] if present.
        Otherwise computes: gap_current_pp / closure_rate_pp_per_week.
        Returns None if unreachable (closure_rate <= 0).

        Args:
            forecasted_json: Forecasted section that may contain
                weeks_to_parity directly.
            gap_current_pp: Current gap in pp (for manual computation).
            closure_rate_pp_per_week: Closure rate from compute_gap_closure_rate.

        Returns:
            Estimated weeks to reach leader, or None if unreachable.
        """
        # Prefer explicit value from forecaster
        explicit = forecasted_json.get("weeks_to_parity")
        if explicit is not None:
            return int(explicit)

        # Compute from gap and closure rate
        if (
            gap_current_pp is not None
            and closure_rate_pp_per_week is not None
            and closure_rate_pp_per_week > 0
        ):
            weeks = gap_current_pp / closure_rate_pp_per_week
            return int(round(weeks))

        return None

    def compute_roi(
        self, plan_type: str, projected_gain_pp: float
    ) -> tuple[float, float | None]:
        """Compute ROI framing metrics.

        Args:
            plan_type: Client's subscription plan type.
            projected_gain_pp: Projected visibility gain in percentage points
                over the forecast horizon.

        Returns:
            Tuple of (investment_monthly, cost_per_point).
            cost_per_point is None if projected_gain_pp <= 0.
        """
        investment_monthly = float(PLAN_PRICES.get(plan_type, 0))
        cost_per_point: float | None = None

        if projected_gain_pp > 0 and investment_monthly > 0:
            cost_per_point = round(investment_monthly / projected_gain_pp, 2)

        return investment_monthly, cost_per_point

    def _compute_gap_to_leader(
        self,
        competitor_rates: dict[str, float],
        client_rate: float,
        projected_12w_ratio: float,
        forecasted_json: dict[str, Any],
    ) -> dict[str, Any]:
        """Compute detailed gap-to-leader metrics.

        All rates are stored as ratios (0-1). Gaps are computed in
        percentage-points (pp) for readability.

        Args:
            competitor_rates: {name: rate_ratio} from observed_json.
            client_rate: Client's brand_visibility_rate (ratio 0-1).
            projected_12w_ratio: Projected client rate at 12w (ratio 0-1).
            forecasted_json: Full forecasted section for weeks_to_parity.

        Returns:
            Dict with gap-to-leader details.
        """
        if not competitor_rates:
            return {
                "target_name": None,
                "target_rate": 0.0,
                "client_rate": round(client_rate, 4),
                "gap_pp": 0.0,
                "projected_gap_12w": 0.0,
                "closure_rate_pp_per_week": 0.0,
                "full_parity_weeks": None,
            }

        # Leader = highest-rate competitor
        leader_name = max(competitor_rates, key=competitor_rates.get)  # type: ignore[arg-type]
        leader_rate = competitor_rates[leader_name]

        # Current gap in pp
        gap_pp = round((leader_rate - client_rate) * 100.0, 2)

        # Projected gap at 12w in pp
        projected_gap_12w = round(
            (leader_rate - projected_12w_ratio) * 100.0, 2
        )

        # Closure rate
        closure_rate = self.compute_gap_closure_rate(gap_pp, projected_gap_12w)

        # Full parity weeks
        full_parity_weeks = self.compute_weeks_to_parity(
            forecasted_json,
            gap_current_pp=gap_pp,
            closure_rate_pp_per_week=closure_rate,
        )

        return {
            "target_name": leader_name,
            "target_rate": round(leader_rate, 4),
            "client_rate": round(client_rate, 4),
            "gap_pp": gap_pp,
            "projected_gap_12w": projected_gap_12w,
            "closure_rate_pp_per_week": closure_rate,
            "full_parity_weeks": full_parity_weeks,
        }
