"""Deterministic Trial Scoring Engine.

Pure-functional scoring: f(signals) -> scores.
No LLM calls, no external dependencies, no side effects.
Given the same signals, always produces the same score.

Subtasks implemented:
  4.1 ScoringEngine class
  4.2 compute_conversion_score — weighted sum with diminishing returns
  4.3 compute_opportunity_value — company size to plan tier mapping
  4.4 compute_priority_score — 45% conversion + 25% normalized_value + 30% urgency
  4.5 build_score_explanation — top 5 positive + top 5 negative signals
  4.6 determine_recommended_action — rule-based action selection
  4.7 build_signal_snapshot — serialize signals into reproducible JSONB
  4.8 Configurable weights via SystemSetting (key: trial_scoring_weights)
"""

import json
import logging
import math
from collections import defaultdict
from datetime import datetime

from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.settings import SystemSetting
from app.models.trial_signal import TrialSignal

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Jerusalem")

# --- Signal point values by category ---

ENGAGEMENT_POINTS: dict[str, int] = {
    "login": 5,
    "page_view": 2,
    "report_viewed": 8,
    "discovery_run": 10,
    "return_visit": 7,
}

INTENT_POINTS: dict[str, int] = {
    "email_domain_work": 15,
    "company_size_known": 10,
    "industry_known": 10,
}

VALUE_REALIZATION_POINTS: dict[str, int] = {
    "landscape_report": 20,
    "opportunity_report": 20,
    "high_intent_discovered": 15,
    "strategic_insights": 15,
    "competitor_mentions": 10,
}

CONVERSION_POINTS: dict[str, int] = {
    "pricing_viewed": 25,
    "upgrade_screen": 20,
    "upgrade_cta": 30,
    "support_contacted": 15,
    "email_replied": 10,
}

NEGATIVE_PENALTIES: dict[str, int] = {
    "no_activity_72h": -15,
    "bounced_email": -10,
    "multiple_short_sessions": -8,
    "viewed_pricing_without_upgrade": -12,
    "onboarding_abandoned": -20,
    "removed_keywords": -10,
    "export_without_return": -8,
    "report_open_no_scroll": -5,
}

# --- Default category weights (Task 4.8) ---

DEFAULT_WEIGHTS: dict[str, float] = {
    "engagement": 0.20,
    "intent": 0.25,
    "value_realization": 0.25,
    "conversion": 0.20,
    "negative_cap": 0.30,
}

# --- Company size to plan tier mapping (12-month contract value in cents) (Task 4.3) ---

PLAN_VALUES_CENTS: dict[str, int] = {
    "seed": 149 * 12 * 100,       # $149/mo x 12 = $1,788 = 178800 cents
    "starter": 399 * 12 * 100,    # $399/mo x 12 = $4,788 = 478800 cents
    "growth": 799 * 12 * 100,     # $799/mo x 12 = $9,588 = 958800 cents
    "scale": 1499 * 12 * 100,     # $1499/mo x 12 = $17,988 = 1798800 cents
}

# Normalization constant for priority score (Task 4.4):
# Normalized_Value = min(100, opportunity_value_cents / 50000)
OPPORTUNITY_NORMALIZATION_DIVISOR: int = 50000

# Trial duration for urgency calculation
TRIAL_DURATION_DAYS: int = 14

# Diminishing returns category max (log scale base) (Task 4.2)
CATEGORY_MAX: int = 20


def normalize_signal_count(count: float, category_max: int = CATEGORY_MAX) -> float:
    """Diminishing returns curve for signal counts.

    Uses log scale capped at 100:
        score = min(100, (log2(count + 1) / log2(category_max + 1)) * 100)

    Examples:
        1 signal  -> ~23
        3 signals -> ~46
        7 signals -> ~69
        15 signals -> ~92
        20+ signals -> 100 (cap)
    """
    if count <= 0:
        return 0.0
    return min(100.0, (math.log2(count + 1) / math.log2(category_max + 1)) * 100)


class ScoringEngine:
    """Deterministic scoring engine. Pure function of signals -> scores.

    Task 4.1: Core class providing all scoring computations.

    Determinism guarantee: given the same signal_snapshot, this engine
    ALWAYS produces identical scores. No randomness, no external state, no LLM.
    """

    def compute_conversion_score(self, signals: list[TrialSignal], weights: dict[str, float] | None = None) -> int:
        """Compute the conversion score from trial signals.

        Task 4.2: Weighted sum with diminishing returns.

        Algorithm:
        1. Group signals by category
        2. Compute category sub-scores using diminishing returns (log scale)
        3. Apply weights: Engagement 20%, Intent 25%, Value_Realization 25%, Conversion 20%
        4. Subtract negative penalty: -10 per negative signal, capped at -30 total
        5. Clamp result to 0-100

        Args:
            signals: List of TrialSignal objects for the client
            weights: Optional weight overrides (from SystemSetting)

        Returns:
            Integer score 0-100
        """
        if not signals:
            return 0

        w = weights or DEFAULT_WEIGHTS

        grouped = self._group_by_category(signals)

        # Compute category sub-scores using diminishing returns
        engagement_score = self._compute_category_subscore(
            grouped.get("engagement", []), ENGAGEMENT_POINTS
        )
        intent_score = self._compute_intent_subscore(grouped.get("intent", []))
        value_score = self._compute_category_subscore(
            grouped.get("value_realization", []), VALUE_REALIZATION_POINTS
        )
        conversion_score = self._compute_category_subscore(
            grouped.get("conversion", []), CONVERSION_POINTS
        )

        # Compute negative penalty: -10 per signal, max total -30
        negative_signals = grouped.get("negative", [])
        negative_penalty = self._compute_negative_penalty(negative_signals, w.get("negative_cap", 0.30))

        # Weighted sum of positive categories
        weighted_sum = (
            w.get("engagement", 0.20) * engagement_score
            + w.get("intent", 0.25) * intent_score
            + w.get("value_realization", 0.25) * value_score
            + w.get("conversion", 0.20) * conversion_score
        )

        # Apply negative penalty (already capped)
        raw_score = weighted_sum + negative_penalty

        return max(0, min(100, int(round(raw_score))))

    def compute_opportunity_value(self, client: Client) -> int:
        """Compute opportunity value in cents based on company size.

        Task 4.3: Company size to plan tier mapping x 12 months.

        Mapping:
            1-10 employees -> $149/mo (Seed)    = 178,800 cents/yr
            11-50 employees -> $399/mo (Starter) = 478,800 cents/yr
            51-200 employees -> $799/mo (Growth) = 958,800 cents/yr
            201+ employees -> $1,499/mo (Scale)  = 1,798,800 cents/yr
            Unknown -> defaults to Seed tier

        Returns:
            Annual contract value in cents.
        """
        company_size = self._get_company_size(client)

        if company_size is None:
            return PLAN_VALUES_CENTS["seed"]
        elif company_size <= 10:
            return PLAN_VALUES_CENTS["seed"]
        elif company_size <= 50:
            return PLAN_VALUES_CENTS["starter"]
        elif company_size <= 200:
            return PLAN_VALUES_CENTS["growth"]
        else:
            return PLAN_VALUES_CENTS["scale"]

    def compute_priority_score(
        self,
        conversion_score: int,
        opportunity_value_cents: int,
        days_remaining: int,
    ) -> int:
        """Compute priority score combining conversion, value, and urgency.

        Task 4.4: Formula:
            Priority_Score = 0.45 x Conversion_Score
                           + 0.25 x Normalized_Value
                           + 0.30 x Urgency

        Where:
            Normalized_Value = min(100, opportunity_value_cents / 50000)
            Urgency = max(0, (14 - days_remaining) / 14 x 100)

        Returns:
            Priority score clamped to 0-100.
        """
        normalized_value = min(100.0, opportunity_value_cents / OPPORTUNITY_NORMALIZATION_DIVISOR)
        urgency_score = max(0.0, (TRIAL_DURATION_DAYS - days_remaining) / TRIAL_DURATION_DAYS * 100)

        raw = (
            0.45 * conversion_score
            + 0.25 * normalized_value
            + 0.30 * urgency_score
        )

        return max(0, min(100, int(round(raw))))

    def build_score_explanation(self, signals: list[TrialSignal]) -> dict:
        """Build explanation showing top contributing and penalizing signals.

        Task 4.5: Returns top 5 positive + top 5 negative signals with
        numeric contribution values.

        Returns:
            {
                "positive": [{"signal_type": str, "category": str, "contribution": int}],
                "negative": [{"signal_type": str, "category": str, "contribution": int}],
                "category_scores": {"engagement": int, "intent": int, ...}
            }
        """
        positive_contributions: list[dict] = []
        negative_contributions: list[dict] = []

        for signal in signals:
            category = signal.signal_category
            signal_type = signal.signal_type
            contribution = self._get_signal_contribution(signal_type, category)

            if contribution > 0:
                positive_contributions.append({
                    "signal_type": signal_type,
                    "category": category,
                    "contribution": contribution,
                })
            elif contribution < 0:
                negative_contributions.append({
                    "signal_type": signal_type,
                    "category": category,
                    "contribution": contribution,
                })

        # Sort by contribution descending for positive, ascending for negative
        positive_contributions.sort(key=lambda x: x["contribution"], reverse=True)
        negative_contributions.sort(key=lambda x: x["contribution"])

        # Compute category scores for additional context
        grouped = self._group_by_category(signals)
        category_scores = {
            "engagement": self._compute_category_subscore(
                grouped.get("engagement", []), ENGAGEMENT_POINTS
            ),
            "intent": self._compute_intent_subscore(grouped.get("intent", [])),
            "value_realization": self._compute_category_subscore(
                grouped.get("value_realization", []), VALUE_REALIZATION_POINTS
            ),
            "conversion": self._compute_category_subscore(
                grouped.get("conversion", []), CONVERSION_POINTS
            ),
        }

        return {
            "positive": positive_contributions[:5],
            "negative": negative_contributions[:5],
            "category_scores": category_scores,
        }

    def determine_recommended_action(
        self,
        score: int,
        days_remaining: int,
        lifecycle_state: str,
        last_signal_at: datetime | None,
    ) -> str:
        """Determine the recommended next action based on current state.

        Task 4.6: Rule-based action selection.

        Decision rules (checked in order):
            1. score > 70 + days_remaining < 5 -> "schedule_urgent_call"
            2. score > 70 + days_remaining >= 5 -> "send_value_confirmation"
            3. score 40-70 + days_remaining < 5 -> "send_case_study"
            4. score 40-70 + days_remaining >= 5 -> "share_value_prop"
            5. score < 40 + lifecycle_state == "at_risk" -> "send_reengagement_question"
            6. score < 40 + lifecycle_state in (engaged, activated) -> "identify_blockers"
            7. lifecycle_state == "expired" -> "classify_failure"

        Inactivity override:
            If last_signal_at is set and (now - last_signal_at) > 72h -> "send_reengagement_question"

        Returns:
            One of: schedule_urgent_call, send_value_confirmation, send_case_study,
                    share_value_prop, send_reengagement_question, identify_blockers,
                    classify_failure
        """
        now = datetime.now(tz=TZ)

        # Inactivity override: if no signal in 72h
        if last_signal_at is not None:
            if last_signal_at.tzinfo is None:
                last_signal_at = last_signal_at.replace(tzinfo=TZ)
            hours_since_last = (now - last_signal_at).total_seconds() / 3600
            if hours_since_last > 72:
                return "send_reengagement_question"

        # Terminal state
        if lifecycle_state == "expired":
            return "classify_failure"

        # Rule 1: High score + expiring soon
        if score > 70 and days_remaining < 5:
            return "schedule_urgent_call"

        # Rule 2: High score + time remaining
        if score > 70:
            return "send_value_confirmation"

        # Rule 3: Medium score + expiring soon
        if 40 <= score <= 70 and days_remaining < 5:
            return "send_case_study"

        # Rule 4: Medium score + time remaining
        if 40 <= score <= 70:
            return "share_value_prop"

        # Rule 5: Low score + at_risk
        if score < 40 and lifecycle_state == "at_risk":
            return "send_reengagement_question"

        # Rule 6: Low score + engaged/activated
        if score < 40 and lifecycle_state in ("engaged", "activated"):
            return "identify_blockers"

        # Default fallback for other states (trial_started, onboarding_started, etc.)
        return "share_value_prop"

    def build_signal_snapshot(self, signals: list[TrialSignal]) -> dict:
        """Serialize all signals into a reproducible JSONB structure.

        Task 4.7: Complete signal state for deterministic score reproduction.

        Returns:
            {
                "signals": [...],
                "signal_count": int,
                "snapshot_generated_at": str (ISO format)
            }
        """
        now = datetime.now(tz=TZ)
        return {
            "signals": [
                {
                    "type": s.signal_type,
                    "category": s.signal_category,
                    "value": s.signal_value,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                }
                for s in signals
            ],
            "signal_count": len(signals),
            "snapshot_generated_at": now.isoformat(),
        }

    def get_scoring_weights(self, db: Session) -> dict[str, float]:
        """Read scoring weights from SystemSetting.

        Task 4.8: Reads key "trial_scoring_weights" from system settings.
        Returns DEFAULT_WEIGHTS if not configured or invalid.

        Expected JSON format in SystemSetting value:
            {
                "engagement": 0.20,
                "intent": 0.25,
                "value_realization": 0.25,
                "conversion": 0.20,
                "negative_cap": 0.30
            }
        """
        setting = db.query(SystemSetting).filter(
            SystemSetting.key == "trial_scoring_weights"
        ).first()

        if setting and setting.value:
            try:
                weights = json.loads(setting.value)
                if isinstance(weights, dict) and all(
                    k in weights for k in DEFAULT_WEIGHTS
                ):
                    return {k: float(v) for k, v in weights.items()}
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.warning("Invalid trial_scoring_weights in SystemSetting, using defaults")

        return DEFAULT_WEIGHTS.copy()

    # --- Private helpers ---

    def _group_by_category(self, signals: list[TrialSignal]) -> dict[str, list[TrialSignal]]:
        """Group signals by their signal_category."""
        grouped: dict[str, list[TrialSignal]] = defaultdict(list)
        for signal in signals:
            grouped[signal.signal_category].append(signal)
        return grouped

    def _compute_category_subscore(
        self, signals: list[TrialSignal], points_map: dict[str, int]
    ) -> int:
        """Compute a category sub-score using diminishing returns (log scale).

        Uses normalize_signal_count for the count of weighted signals,
        ensuring diminishing returns as more signals accumulate.

        The effective count is the sum of points divided by average point value,
        giving a normalized signal equivalent count.
        """
        if not signals:
            return 0

        total_points = 0
        for signal in signals:
            points = points_map.get(signal.signal_type, 2)
            total_points += points

        # Use log-scale normalization on effective signal count
        avg_points = sum(points_map.values()) / max(len(points_map), 1) if points_map else 5
        effective_count = total_points / max(avg_points, 1)

        return int(round(normalize_signal_count(effective_count, CATEGORY_MAX)))

    def _compute_intent_subscore(self, signals: list[TrialSignal]) -> int:
        """Compute intent sub-score with special handling for repeated signals.

        Points: email_domain_work=15, company_size_known=10, industry_known=10.
        Special: subreddits_configured=5 per signal (max 20 total),
                 keywords_configured=3 per signal (max 15 total).

        Uses diminishing returns on effective signal count.
        """
        if not signals:
            return 0

        total_points = 0
        subreddit_count = 0
        keyword_count = 0

        for signal in signals:
            if signal.signal_type == "subreddits_configured":
                subreddit_count += 1
            elif signal.signal_type == "keywords_configured":
                keyword_count += 1
            else:
                points = INTENT_POINTS.get(signal.signal_type, 0)
                total_points += points

        total_points += min(subreddit_count * 5, 20)
        total_points += min(keyword_count * 3, 15)

        # Use log-scale normalization
        avg_points = 10  # Average intent signal value
        effective_count = total_points / avg_points

        return int(round(normalize_signal_count(effective_count, CATEGORY_MAX)))

    def _compute_negative_penalty(self, signals: list[TrialSignal], negative_cap: float = 0.30) -> float:
        """Compute negative penalty.

        Each negative signal applies -10 penalty, capped at -(negative_cap * 100) total.
        Default cap: -30 (i.e., 30% of 100).

        Args:
            signals: Negative category signals
            negative_cap: Maximum penalty as a fraction (0.30 = -30 points)

        Returns:
            Negative float (penalty), e.g. -20.0
        """
        if not signals:
            return 0.0

        max_penalty = -(negative_cap * 100)
        penalty = -(len(signals) * 10)

        return max(penalty, max_penalty)

    def _get_signal_contribution(self, signal_type: str, category: str) -> int:
        """Get the point contribution for a single signal."""
        if category == "engagement":
            return ENGAGEMENT_POINTS.get(signal_type, 2)
        elif category == "intent":
            if signal_type == "subreddits_configured":
                return 5
            elif signal_type == "keywords_configured":
                return 3
            return INTENT_POINTS.get(signal_type, 0)
        elif category == "value_realization":
            return VALUE_REALIZATION_POINTS.get(signal_type, 0)
        elif category == "conversion":
            return CONVERSION_POINTS.get(signal_type, 0)
        elif category == "negative":
            return NEGATIVE_PENALTIES.get(signal_type, -5)
        return 0

    def _get_company_size(self, client: Client) -> int | None:
        """Extract company size from client metadata.

        Looks for company_size in:
        1. company_profile field (JSON string with "company_size" or "employees" key)
        2. keywords JSONB (with "company_size" key)

        Returns None if unknown.
        """
        if client.company_profile:
            try:
                profile_data = json.loads(client.company_profile)
                if isinstance(profile_data, dict):
                    size = profile_data.get("company_size") or profile_data.get("employees")
                    if size is not None:
                        return int(size)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        if client.keywords and isinstance(client.keywords, dict):
            size = client.keywords.get("company_size")
            if size is not None:
                try:
                    return int(size)
                except (TypeError, ValueError):
                    pass

        return None
