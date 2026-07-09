"""Risk Scorer service — dynamic risk score computation per subreddit.

Computes a weighted risk score (0-100) from four sub-scores:
- Removal Rate (40%): linear 0-100 from removal_rate
- Aggressiveness (25%): low=10, medium=40, high=70, extreme=100
- Rule Strictness (20%): min(rule_count * 12, 100)
- Trend Direction (15%): slope of last 4 weeks, mapped to 0-100

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.subreddit_risk_profile import SubredditRiskProfile
from app.services.transparency import record_activity_event

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RISK_SCORE_HISTORY_WEEKS = 12

# Weights (Req 4.2)
WEIGHT_REMOVAL_RATE = 0.40
WEIGHT_AGGRESSIVENESS = 0.25
WEIGHT_RULE_STRICTNESS = 0.20
WEIGHT_TREND_DIRECTION = 0.15

# Aggressiveness mapping (Req 4.2)
AGGRESSIVENESS_MAP: dict[str, int] = {
    "low": 10,
    "medium": 40,
    "high": 70,
    "extreme": 100,
}

# Spike threshold (Req 4.3)
SPIKE_THRESHOLD = 15

# High risk threshold (Req 4.6, 4.8)
HIGH_RISK_THRESHOLD = 80

# Default score for insufficient data (Req 4.7)
INSUFFICIENT_DATA_SCORE = 50

# Min posts for confidence (Req 4.7)
MIN_POSTS_FOR_CONFIDENCE = 5

# ---------------------------------------------------------------------------
# Adaptive refresh intervals (days)
# ---------------------------------------------------------------------------
# Determined by risk score + moderation aggressiveness after each analysis.
# Higher risk / more aggressive → more frequent checks (rules change often).
# Low risk / stable → infrequent checks (saves LLM cost).

REFRESH_INTERVAL_HIGH_RISK = 3        # risk > 70 or extreme aggressiveness
REFRESH_INTERVAL_MEDIUM_HIGH = 7      # risk 51-70 or high aggressiveness
REFRESH_INTERVAL_MEDIUM = 14          # risk 31-50 or medium aggressiveness
REFRESH_INTERVAL_LOW = 21             # risk 11-30, stable
REFRESH_INTERVAL_VERY_LOW = 30        # risk 0-10, very stable
REFRESH_INTERVAL_FIRST_CHECK = 7      # first ever analysis → recheck in 7 days
REFRESH_INTERVAL_SPIKE = 3            # spike detected → urgent recheck


# ---------------------------------------------------------------------------
# Sub-score computations
# ---------------------------------------------------------------------------


def _compute_removal_rate_score(profile: SubredditRiskProfile) -> float:
    """Removal Rate sub-score: linear 0-100 from removal_rate (Req 4.2).

    removal_rate is stored as 0.0-1.0 in moderation_profile JSONB.
    Maps linearly: 0% removal = 0, 100% removal = 100.
    """
    moderation_profile = profile.moderation_profile or {}
    removal_rate = moderation_profile.get("removal_rate", 0.0)

    # Clamp to valid range
    removal_rate = max(0.0, min(1.0, float(removal_rate)))

    return removal_rate * 100.0


def _compute_aggressiveness_score(profile: SubredditRiskProfile) -> float:
    """Aggressiveness sub-score: mapped from level (Req 4.2).

    low=10, medium=40, high=70, extreme=100.
    """
    moderation_profile = profile.moderation_profile or {}
    aggressiveness = moderation_profile.get("aggressiveness", "low")

    return float(AGGRESSIVENESS_MAP.get(aggressiveness, 10))


def _compute_rule_strictness_score(profile: SubredditRiskProfile) -> float:
    """Rule Strictness sub-score: min(rule_count * 12, 100) (Req 4.2)."""
    extracted_rules = profile.extracted_rules or []
    rule_count = len(extracted_rules)

    return float(min(rule_count * 12, 100))


def _compute_trend_direction_score(profile: SubredditRiskProfile) -> float:
    """Trend Direction sub-score: slope of last 4 weeks mapped to 0-100 (Req 4.2).

    Positive slope = higher risk.
    Uses linear regression slope over the last 4 data points in history.
    If fewer than 2 data points, returns 50 (neutral).
    """
    history = profile.risk_score_history or []

    # Need at least 2 data points for a slope
    if len(history) < 2:
        return 50.0

    # Take last 4 weeks (or fewer if not enough data)
    recent = history[-4:]
    scores = [entry.get("score", 50) for entry in recent]

    n = len(scores)
    if n < 2:
        return 50.0

    # Simple linear regression slope: sum((x - x_mean)(y - y_mean)) / sum((x - x_mean)^2)
    x_values = list(range(n))
    x_mean = sum(x_values) / n
    y_mean = sum(scores) / n

    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, scores))
    denominator = sum((x - x_mean) ** 2 for x in x_values)

    if denominator == 0:
        return 50.0

    slope = numerator / denominator

    # Map slope to 0-100: slope of -25 maps to 0, slope of +25 maps to 100
    # Neutral (0 slope) = 50
    mapped = 50.0 + (slope * 2.0)

    # Clamp to 0-100
    return max(0.0, min(100.0, mapped))


# ---------------------------------------------------------------------------
# Adaptive refresh interval computation
# ---------------------------------------------------------------------------


def _compute_next_check_at(
    risk_score: int,
    profile: SubredditRiskProfile,
    spiked: bool = False,
) -> datetime:
    """Determine when this subreddit should be re-analyzed next.

    Logic:
    - Spike detected → 3 days (urgent recheck)
    - risk > 70 or extreme aggressiveness → 3 days
    - risk 51-70 or high aggressiveness → 7 days
    - risk 31-50 → 14 days
    - risk 11-30 → 21 days
    - risk 0-10 → 30 days
    - First analysis (history ≤ 1 entry) → 7 days

    Cost impact: Gemini Flash ~$0.003/sub. At 50 subs with avg 14-day interval
    ≈ 107 calls/month ≈ $0.32/month. Very cheap.
    """
    now = datetime.now(timezone.utc)

    # Spike = urgent
    if spiked:
        return now + timedelta(days=REFRESH_INTERVAL_SPIKE)

    # First analysis
    history = profile.risk_score_history or []
    if len(history) <= 1:
        return now + timedelta(days=REFRESH_INTERVAL_FIRST_CHECK)

    # Aggressiveness factor
    moderation_profile = profile.moderation_profile or {}
    aggressiveness = moderation_profile.get("aggressiveness", "low")

    # Use the more aggressive of risk-score-based or aggressiveness-based interval
    if risk_score > 70 or aggressiveness == "extreme":
        days = REFRESH_INTERVAL_HIGH_RISK
    elif risk_score > 50 or aggressiveness == "high":
        days = REFRESH_INTERVAL_MEDIUM_HIGH
    elif risk_score > 30:
        days = REFRESH_INTERVAL_MEDIUM
    elif risk_score > 10:
        days = REFRESH_INTERVAL_LOW
    else:
        days = REFRESH_INTERVAL_VERY_LOW

    return now + timedelta(days=days)


# ---------------------------------------------------------------------------
# Core function: compute_risk_score (Req 4.1, 4.2)
# ---------------------------------------------------------------------------


def compute_risk_score(profile: SubredditRiskProfile) -> int:
    """Compute weighted risk score (0-100) for a subreddit profile.

    Weights:
    - Removal Rate (40%): linear 0-100 from removal_rate
    - Aggressiveness (25%): low=10, medium=40, high=70, extreme=100
    - Rule Strictness (20%): min(rule_count * 12, 100)
    - Trend Direction (15%): slope of last 4 weeks, mapped to 0-100

    Returns:
        Integer risk score clamped to 0-100.
    """
    # Req 4.7: insufficient data → assign 50
    if profile.confidence_level == "insufficient_data":
        return INSUFFICIENT_DATA_SCORE

    removal_score = _compute_removal_rate_score(profile)
    aggressiveness_score = _compute_aggressiveness_score(profile)
    rule_strictness_score = _compute_rule_strictness_score(profile)
    trend_score = _compute_trend_direction_score(profile)

    weighted_score = (
        removal_score * WEIGHT_REMOVAL_RATE
        + aggressiveness_score * WEIGHT_AGGRESSIVENESS
        + rule_strictness_score * WEIGHT_RULE_STRICTNESS
        + trend_score * WEIGHT_TREND_DIRECTION
    )

    # Clamp to 0-100 and round
    result = int(round(max(0.0, min(100.0, weighted_score))))

    return result


# ---------------------------------------------------------------------------
# Batch function: refresh_all_risk_scores (Req 4.3, 4.4, 4.5, 4.6, 4.7, 4.8)
# ---------------------------------------------------------------------------


def refresh_all_risk_scores(db: Session) -> dict:
    """Batch: compute risk scores for all profiles.

    Steps for each profile:
    1. Compute risk score using weighted formula
    2. Append new score to risk_score_history (cap 12 weeks FIFO)
    3. Detect spike (>15 point increase) and emit event (Req 4.3)
    4. Set/clear is_high_risk flag on Subreddit (Req 4.6, 4.8)

    Returns:
        Summary dict with processed, updated, spikes, high_risk_set,
        high_risk_cleared counts.
    """
    from app.models.subreddit import Subreddit

    logger.info("RISK_SCORER | action=refresh_all | status=start")

    profiles = db.query(SubredditRiskProfile).all()

    stats = {
        "processed": 0,
        "updated": 0,
        "spikes": 0,
        "high_risk_set": 0,
        "high_risk_cleared": 0,
        "insufficient_data": 0,
    }

    now = datetime.now(timezone.utc)
    # ISO week label for history entry
    week_label = now.strftime("%G-W%V")

    for profile in profiles:
        stats["processed"] += 1

        previous_score = profile.risk_score
        new_score = compute_risk_score(profile)

        # Track insufficient data (Req 4.7)
        if profile.confidence_level == "insufficient_data":
            stats["insufficient_data"] += 1

        # Update risk_score
        profile.risk_score = new_score

        # Append to history (Req 4.4): cap at 12 weeks FIFO
        history = list(profile.risk_score_history or [])
        history.append({"week": week_label, "score": new_score})

        # FIFO eviction: keep only last 12 entries
        if len(history) > RISK_SCORE_HISTORY_WEEKS:
            history = history[-RISK_SCORE_HISTORY_WEEKS:]

        profile.risk_score_history = history

        # Detect spike (Req 4.3): increase > 15 points
        delta = new_score - previous_score
        if delta > SPIKE_THRESHOLD:
            stats["spikes"] += 1

            # Load subreddit name for event message
            subreddit = db.query(Subreddit).filter(
                Subreddit.id == profile.subreddit_id
            ).first()
            subreddit_name = subreddit.subreddit_name if subreddit else "unknown"

            record_activity_event(
                db,
                event_type="risk_score_spike",
                message=(
                    f"Risk score spike for r/{subreddit_name}: "
                    f"{previous_score} → {new_score} (Δ{delta})"
                ),
                metadata={
                    "subreddit_name": subreddit_name,
                    "previous_score": previous_score,
                    "new_score": new_score,
                    "delta": delta,
                },
            )

        # Set/clear is_high_risk (Req 4.6, 4.8)
        subreddit = db.query(Subreddit).filter(
            Subreddit.id == profile.subreddit_id
        ).first()

        if subreddit:
            if new_score > HIGH_RISK_THRESHOLD and not subreddit.is_high_risk:
                # Req 4.6: score exceeds 80 → set high_risk
                subreddit.is_high_risk = True
                stats["high_risk_set"] += 1
                logger.info(
                    "RISK_SCORER | action=set_high_risk | subreddit=r/%s | score=%d",
                    subreddit.subreddit_name,
                    new_score,
                )
            elif new_score <= HIGH_RISK_THRESHOLD and subreddit.is_high_risk:
                # Req 4.8: score drops to 80 or below AND currently flagged → clear
                subreddit.is_high_risk = False
                stats["high_risk_cleared"] += 1
                logger.info(
                    "RISK_SCORER | action=clear_high_risk | subreddit=r/%s | score=%d",
                    subreddit.subreddit_name,
                    new_score,
                )

        # Adaptive refresh: schedule next check based on score + aggressiveness
        profile.next_check_at = _compute_next_check_at(
            new_score, profile, spiked=(delta > SPIKE_THRESHOLD)
        )

        stats["updated"] += 1

    db.commit()

    logger.info(
        "RISK_SCORER | action=refresh_all | status=done | "
        "processed=%d | updated=%d | spikes=%d | "
        "high_risk_set=%d | high_risk_cleared=%d | insufficient_data=%d",
        stats["processed"],
        stats["updated"],
        stats["spikes"],
        stats["high_risk_set"],
        stats["high_risk_cleared"],
        stats["insufficient_data"],
    )

    return stats
