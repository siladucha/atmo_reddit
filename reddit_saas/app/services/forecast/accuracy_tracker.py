"""Forecast Accuracy Tracker — compares predictions to actuals.

Records predictions on report generation, evaluates accuracy when new GEO
batches arrive, and suggests confidence interval adjustments based on
historical performance.

Validates: Requirements R3.7, R3.8
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models.forecast_accuracy import ForecastAccuracyLog
from app.models.intelligence_report import ClientIntelligenceReport
from app.models.observed_snapshot import ObservedSnapshot

logger = logging.getLogger(__name__)

# Metrics we track predictions for
TRACKED_METRICS = [
    "geo.brand_rate.overall",
    "geo.brand_rate.perplexity",
    "geo.brand_rate.chatgpt",
    "geo.brand_rate.claude",
]

# Horizons in weeks
HORIZONS_WEEKS = [4, 12, 24]

# Scenario names that map to forecasted_json keys
SCENARIO_NAMES = ["conservative", "expected", "optimistic"]

# Horizon keys in forecasted_json
HORIZON_KEYS = {
    4: "visibility_4w",
    12: "visibility_12w",
    24: "visibility_24w",
}


def record_predictions(
    db: Session,
    report_id: uuid.UUID,
    client_id: uuid.UUID,
    forecasted_json: dict,
) -> list[ForecastAccuracyLog]:
    """Record forecast predictions as ForecastAccuracyLog entries.

    Called after report generation. Creates entries for each tracked metric
    at target dates (4w, 12w, 24w from now) with all 3 scenarios per metric.

    Args:
        db: SQLAlchemy session.
        report_id: UUID of the generated report.
        client_id: UUID of the client.
        forecasted_json: The forecasted_json from the report.

    Returns:
        List of created ForecastAccuracyLog entries.
    """
    if not forecasted_json:
        logger.debug("No forecasted_json provided, skipping prediction recording")
        return []

    now = datetime.now(timezone.utc)
    today = now.date()
    entries: list[ForecastAccuracyLog] = []

    for horizon_weeks in HORIZONS_WEEKS:
        target = today + timedelta(weeks=horizon_weeks)
        horizon_key = HORIZON_KEYS[horizon_weeks]
        horizon_data = forecasted_json.get(horizon_key)

        if not horizon_data or not isinstance(horizon_data, dict):
            continue

        # For each scenario, record predictions for tracked metrics
        for scenario in SCENARIO_NAMES:
            scenario_value = horizon_data.get(scenario)
            if scenario_value is None:
                continue

            # The overall visibility value applies to geo.brand_rate.overall
            _record_single_prediction(
                db=db,
                report_id=report_id,
                client_id=client_id,
                metric_id="geo.brand_rate.overall",
                predicted_at=now,
                target_date=target,
                scenario=scenario,
                predicted_value=scenario_value,
                entries=entries,
            )

        # Per-engine predictions at 12w from per_engine_12w
        if horizon_weeks == 12:
            per_engine = forecasted_json.get("per_engine_12w", {})
            for engine_name, engine_data in per_engine.items():
                if not isinstance(engine_data, dict):
                    continue
                metric_id = f"geo.brand_rate.{engine_name}"
                if metric_id not in TRACKED_METRICS:
                    continue

                for scenario, scenario_key in [
                    ("conservative", "c"),
                    ("expected", "e"),
                    ("optimistic", "o"),
                ]:
                    value = engine_data.get(scenario_key)
                    if value is None:
                        continue
                    _record_single_prediction(
                        db=db,
                        report_id=report_id,
                        client_id=client_id,
                        metric_id=metric_id,
                        predicted_at=now,
                        target_date=target,
                        scenario=scenario,
                        predicted_value=value,
                        entries=entries,
                    )

    if entries:
        db.flush()
        logger.info(
            "Recorded %d forecast predictions for client %s, report %s",
            len(entries),
            client_id,
            report_id,
        )

    return entries


def evaluate_accuracy(db: Session, client_id: uuid.UUID) -> int:
    """Evaluate forecast accuracy by comparing predictions to actuals.

    Called weekly when a new GEO batch arrives. Finds all ForecastAccuracyLog
    entries where actual_value IS NULL and target_date <= today. Fetches
    actual measured values from the latest ObservedSnapshot and fills in
    actual_value, error_pp, within_bounds, and measured_at.

    Args:
        db: SQLAlchemy session.
        client_id: UUID of the client.

    Returns:
        Number of predictions evaluated.
    """
    today = date.today()
    now = datetime.now(timezone.utc)

    # Find predictions that are due for evaluation
    pending_predictions = (
        db.query(ForecastAccuracyLog)
        .filter(
            ForecastAccuracyLog.client_id == client_id,
            ForecastAccuracyLog.actual_value.is_(None),
            ForecastAccuracyLog.target_date <= today,
        )
        .all()
    )

    if not pending_predictions:
        logger.debug("No pending predictions to evaluate for client %s", client_id)
        return 0

    # Get the latest ObservedSnapshot for this client
    latest_snapshot = (
        db.query(ObservedSnapshot)
        .filter(ObservedSnapshot.client_id == client_id)
        .order_by(ObservedSnapshot.collected_at.desc())
        .first()
    )

    if not latest_snapshot:
        logger.warning(
            "No ObservedSnapshot found for client %s, cannot evaluate predictions",
            client_id,
        )
        return 0

    # Build a metric_id → value lookup from the snapshot
    actual_values = _extract_actual_values(latest_snapshot)

    evaluated_count = 0

    for prediction in pending_predictions:
        metric_id = prediction.metric_id
        actual = actual_values.get(metric_id)

        if actual is None:
            # No matching metric in snapshot — skip
            continue

        # Compute error_pp = abs(actual - predicted)
        predicted = float(prediction.predicted_value)
        error = abs(actual - predicted)

        # Determine within_bounds by checking conservative/optimistic for same
        # (report_id, metric_id, target_date)
        within = _check_within_bounds(
            db=db,
            report_id=prediction.report_id,
            metric_id=metric_id,
            target_date=prediction.target_date,
            actual_value=actual,
        )

        # Update the prediction record
        prediction.actual_value = Decimal(str(round(actual, 2)))
        prediction.error_pp = Decimal(str(round(error, 2)))
        prediction.within_bounds = within
        prediction.measured_at = now

        evaluated_count += 1

    if evaluated_count > 0:
        db.flush()
        logger.info(
            "Evaluated %d predictions for client %s (%d pending, %d had actuals)",
            evaluated_count,
            client_id,
            len(pending_predictions),
            evaluated_count,
        )

    return evaluated_count


def get_accuracy_summary(db: Session, client_id: uuid.UUID) -> dict:
    """Return aggregate accuracy stats for a client.

    Returns:
        Dict with: total_predictions, measured_count, within_bounds_rate,
        avg_error_pp, worst_miss (metric + error).
    """
    # Total predictions
    total_predictions = (
        db.query(func.count(ForecastAccuracyLog.id))
        .filter(ForecastAccuracyLog.client_id == client_id)
        .scalar()
        or 0
    )

    # Measured (evaluated) predictions
    measured_count = (
        db.query(func.count(ForecastAccuracyLog.id))
        .filter(
            ForecastAccuracyLog.client_id == client_id,
            ForecastAccuracyLog.actual_value.isnot(None),
        )
        .scalar()
        or 0
    )

    if measured_count == 0:
        return {
            "total_predictions": total_predictions,
            "measured_count": 0,
            "within_bounds_rate": None,
            "avg_error_pp": None,
            "worst_miss": None,
        }

    # Within bounds rate
    within_bounds_count = (
        db.query(func.count(ForecastAccuracyLog.id))
        .filter(
            ForecastAccuracyLog.client_id == client_id,
            ForecastAccuracyLog.actual_value.isnot(None),
            ForecastAccuracyLog.within_bounds.is_(True),
        )
        .scalar()
        or 0
    )
    within_bounds_rate = round(within_bounds_count / measured_count, 4)

    # Average error_pp (only for "expected" scenario to avoid diluting with
    # conservative/optimistic extremes)
    avg_error = (
        db.query(func.avg(ForecastAccuracyLog.error_pp))
        .filter(
            ForecastAccuracyLog.client_id == client_id,
            ForecastAccuracyLog.actual_value.isnot(None),
            ForecastAccuracyLog.scenario == "expected",
        )
        .scalar()
    )
    avg_error_pp = round(float(avg_error), 2) if avg_error else None

    # Worst miss (highest error_pp for expected scenario)
    worst = (
        db.query(ForecastAccuracyLog)
        .filter(
            ForecastAccuracyLog.client_id == client_id,
            ForecastAccuracyLog.actual_value.isnot(None),
            ForecastAccuracyLog.scenario == "expected",
        )
        .order_by(ForecastAccuracyLog.error_pp.desc())
        .first()
    )
    worst_miss = None
    if worst and worst.error_pp:
        worst_miss = {
            "metric_id": worst.metric_id,
            "error_pp": float(worst.error_pp),
            "predicted": float(worst.predicted_value),
            "actual": float(worst.actual_value),
            "target_date": worst.target_date.isoformat(),
        }

    return {
        "total_predictions": total_predictions,
        "measured_count": measured_count,
        "within_bounds_rate": within_bounds_rate,
        "avg_error_pp": avg_error_pp,
        "worst_miss": worst_miss,
    }


def suggest_confidence_adjustment(db: Session, client_id: uuid.UUID) -> float:
    """Suggest whether to widen or narrow confidence intervals.

    Based on historical accuracy, returns a multiplier:
      - 1.0 = no change
      - >1.0 = widen intervals (e.g. 1.2 = widen 20%)
      - <1.0 = narrow intervals (e.g. 0.8 = narrow 20%)

    Logic:
      - If within_bounds_rate < 50%, model is overconfident → widen
      - If within_bounds_rate > 90%, model is too conservative → narrow
      - Otherwise, no change
      - Scale adjustment by how far from target (68% for 1σ)

    Args:
        db: SQLAlchemy session.
        client_id: UUID of the client.

    Returns:
        Float multiplier for confidence interval adjustment.
    """
    # Get evaluated predictions (all scenarios, to check within_bounds)
    measured_count = (
        db.query(func.count(ForecastAccuracyLog.id))
        .filter(
            ForecastAccuracyLog.client_id == client_id,
            ForecastAccuracyLog.actual_value.isnot(None),
            ForecastAccuracyLog.within_bounds.isnot(None),
        )
        .scalar()
        or 0
    )

    # Need at least 5 measurements to make a meaningful adjustment
    if measured_count < 5:
        return 1.0

    within_bounds_count = (
        db.query(func.count(ForecastAccuracyLog.id))
        .filter(
            ForecastAccuracyLog.client_id == client_id,
            ForecastAccuracyLog.actual_value.isnot(None),
            ForecastAccuracyLog.within_bounds.is_(True),
        )
        .scalar()
        or 0
    )

    within_rate = within_bounds_count / measured_count

    # Target: 68% of actuals should fall within conservative-optimistic bounds (1σ)
    target_rate = 0.68

    if within_rate < 0.50:
        # Model is overconfident — actual frequently outside bounds
        # Widen proportionally: if 30% within → widen 40%
        # Formula: 1.0 + (target_rate - within_rate) * scale_factor
        gap = target_rate - within_rate
        adjustment = 1.0 + min(gap * 2.0, 0.5)  # cap at 1.5 (50% wider)
        return round(adjustment, 2)

    elif within_rate > 0.90:
        # Model is too conservative — bounds are unnecessarily wide
        # Narrow proportionally: if 95% within → narrow 20%
        excess = within_rate - target_rate
        adjustment = 1.0 - min(excess * 0.8, 0.3)  # cap at 0.7 (30% narrower)
        return round(adjustment, 2)

    else:
        # Within acceptable range (50-90%), no adjustment needed
        return 1.0


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------


def _record_single_prediction(
    db: Session,
    report_id: uuid.UUID,
    client_id: uuid.UUID,
    metric_id: str,
    predicted_at: datetime,
    target_date: date,
    scenario: str,
    predicted_value: float,
    entries: list[ForecastAccuracyLog],
) -> None:
    """Create and add a single ForecastAccuracyLog entry.

    Handles deduplication: if an entry already exists for the same
    (report_id, metric_id, target_date, scenario), skip it.
    """
    # Check for existing entry to avoid duplicates
    existing = (
        db.query(ForecastAccuracyLog.id)
        .filter(
            ForecastAccuracyLog.report_id == report_id,
            ForecastAccuracyLog.metric_id == metric_id,
            ForecastAccuracyLog.target_date == target_date,
            ForecastAccuracyLog.scenario == scenario,
        )
        .first()
    )
    if existing:
        return

    entry = ForecastAccuracyLog(
        report_id=report_id,
        client_id=client_id,
        metric_id=metric_id,
        predicted_at=predicted_at,
        target_date=target_date,
        scenario=scenario,
        predicted_value=Decimal(str(round(predicted_value, 2))),
    )
    db.add(entry)
    entries.append(entry)


def _extract_actual_values(snapshot: ObservedSnapshot) -> dict[str, float]:
    """Extract metric values from an ObservedSnapshot.

    Returns a dict mapping metric_id → value (as percentage 0-100).
    Values stored as ratios (0.0-1.0) are converted to percentage.
    """
    values: dict[str, float] = {}
    metrics = snapshot.metrics_json

    if not metrics or not isinstance(metrics, list):
        return values

    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        metric_id = metric.get("metric_id")
        if metric_id not in TRACKED_METRICS:
            continue

        value = metric.get("value")
        if value is None:
            continue

        # Convert ratio (0-1) to percentage (0-100) if needed
        if isinstance(value, (int, float)):
            if value <= 1.0:
                values[metric_id] = value * 100.0
            else:
                values[metric_id] = float(value)

    return values


def _check_within_bounds(
    db: Session,
    report_id: uuid.UUID,
    metric_id: str,
    target_date: date,
    actual_value: float,
) -> bool:
    """Check if actual_value falls within conservative-optimistic range.

    Looks up the conservative and optimistic predictions for the same
    (report_id, metric_id, target_date) and checks:
        conservative_value <= actual_value <= optimistic_value

    If conservative or optimistic predictions are not found, returns False.
    """
    predictions = (
        db.query(ForecastAccuracyLog)
        .filter(
            ForecastAccuracyLog.report_id == report_id,
            ForecastAccuracyLog.metric_id == metric_id,
            ForecastAccuracyLog.target_date == target_date,
            ForecastAccuracyLog.scenario.in_(["conservative", "optimistic"]),
        )
        .all()
    )

    conservative_value = None
    optimistic_value = None

    for pred in predictions:
        if pred.scenario == "conservative":
            conservative_value = float(pred.predicted_value)
        elif pred.scenario == "optimistic":
            optimistic_value = float(pred.predicted_value)

    if conservative_value is None or optimistic_value is None:
        return False

    # Ensure bounds are ordered correctly (conservative can be lower or higher)
    lower = min(conservative_value, optimistic_value)
    upper = max(conservative_value, optimistic_value)

    return lower <= actual_value <= upper
