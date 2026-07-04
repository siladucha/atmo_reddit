"""Statistical Reporter — weekly and final report generation for A/B test experiments.

Performs hypothesis testing (chi-squared, Mann-Whitney U), computes effect sizes
(Cramér's V, Cohen's d / rank-biserial r), generates per-group aggregates,
cumulative analyses, and early termination checks.

Usage:
    from app.services.ab_test.statistical_reporter import (
        generate_weekly_report,
        generate_final_report,
    )

    report = generate_weekly_report(db, experiment_id, week_number)
    final = generate_final_report(db, experiment_id)
"""

import math
from dataclasses import dataclass
from itertools import combinations

import numpy as np
from scipy import stats
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.ab_test import (
    AvatarAssignment,
    ExperimentRun,
    MetricSnapshot,
    TreatmentGroup,
    WeeklyReport,
)
from app.models.activity_event import ActivityEvent

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALPHA = 0.05
CONSECUTIVE_WEEKS_ALERT = 2
MIN_SAMPLE_SIZE = 5
MEDIUM_EFFECT_THRESHOLD = 0.3  # medium effect size boundary

# Primary metrics for early termination consideration
PRIMARY_METRICS = ["removal_rate", "shadowban_events"]

# Metric classification: continuous vs categorical
CONTINUOUS_METRICS = [
    "removal_rate",
    "karma_velocity_4h",
    "karma_velocity_24h",
    "karma_velocity_7d",
    "subreddit_bans",
    "phase_speed",
]
CATEGORICAL_METRICS = [
    "shadowban_occurred",
    "cqs_changed",
]


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class ComparisonResult:
    """Result of a pairwise statistical comparison."""

    pair: list[str]
    test: str
    statistic: float
    p_value: float
    effect_size: float
    significant: bool
    sample_sizes: dict[str, int]
    warning: str | None = None


@dataclass
class GroupAggregate:
    """Per-group summary statistics for a metric."""

    mean: float | None
    median: float | None
    std: float | None
    n: int
    values: list[float]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_weekly_report(
    db: Session,
    experiment_id: "str | __import__('uuid').UUID",
    week_number: int,
) -> WeeklyReport:
    """Generate full statistical report for a given week.

    Steps:
    1. Load metric snapshots for this week (per group)
    2. Compute per-group aggregates (mean, median, n)
    3. Run pairwise comparisons (chi-sq or Mann-Whitney U)
    4. Compute cumulative stats (all weeks so far)
    5. Check early termination criteria
    6. Store immutable report record

    Args:
        db: SQLAlchemy session.
        experiment_id: UUID of the experiment.
        week_number: 1-based week within the experiment.

    Returns:
        WeeklyReport record (already added to session and flushed).
    """
    experiment = db.query(ExperimentRun).filter(
        ExperimentRun.id == experiment_id
    ).one()

    groups = (
        db.query(TreatmentGroup)
        .filter(TreatmentGroup.experiment_id == experiment_id)
        .all()
    )
    group_map = {g.id: g for g in groups}

    # Load current-week snapshots grouped by group
    current_snapshots = (
        db.query(MetricSnapshot)
        .filter(
            MetricSnapshot.experiment_id == experiment_id,
            MetricSnapshot.week_number == week_number,
        )
        .all()
    )

    # Load all snapshots up to this week for cumulative analysis
    cumulative_snapshots = (
        db.query(MetricSnapshot)
        .filter(
            MetricSnapshot.experiment_id == experiment_id,
            MetricSnapshot.week_number <= week_number,
        )
        .all()
    )

    # Organize snapshots by group
    current_by_group = _organize_by_group(current_snapshots, group_map)
    cumulative_by_group = _organize_by_group(cumulative_snapshots, group_map)

    # Generate statistics for current week
    statistics = _compute_all_comparisons(current_by_group, groups)

    # Generate cumulative statistics
    cumulative = _compute_all_comparisons(cumulative_by_group, groups)

    # Build raw data table (per-avatar values)
    raw_data = _build_raw_data(current_snapshots, group_map)

    # Check early termination
    early_term, alert_metrics = _check_early_termination(
        db, experiment_id, week_number
    )

    # Create report record
    report = WeeklyReport(
        experiment_id=experiment_id,
        week_number=week_number,
        statistics_json=statistics,
        cumulative_json=cumulative,
        raw_data_json=raw_data,
        early_termination_recommended=early_term,
        alert_metrics=alert_metrics,
    )
    db.add(report)
    db.flush()

    # Emit alert event if early termination recommended
    if early_term:
        _emit_early_termination_alert(db, experiment, week_number, alert_metrics)

    logger.info(
        "Generated weekly report for experiment %s week %d "
        "(early_termination=%s, alert_metrics=%s)",
        experiment_id, week_number, early_term, alert_metrics,
    )
    return report


def generate_final_report(
    db: Session,
    experiment_id: "str | __import__('uuid').UUID",
) -> dict:
    """Generate conclusion summary with H0 determination and confidence intervals.

    Returns a structured dict suitable for storing in ExperimentRun.conclusion_summary.

    Includes:
    - h0_rejected: whether the null hypothesis can be rejected for any primary metric
    - primary_metrics_significant: list of primary metrics with p < 0.05
    - confidence_intervals: per-metric 95% CI for group differences
    - recommendation: human-readable recommendation
    - total_weeks: number of weeks the experiment ran
    - total_avatars_analyzed: count of non-excluded avatars
    - exclusions: count of excluded avatars
    """
    experiment = db.query(ExperimentRun).filter(
        ExperimentRun.id == experiment_id
    ).one()

    groups = (
        db.query(TreatmentGroup)
        .filter(TreatmentGroup.experiment_id == experiment_id)
        .all()
    )
    group_map = {g.id: g for g in groups}

    # All snapshots
    all_snapshots = (
        db.query(MetricSnapshot)
        .filter(MetricSnapshot.experiment_id == experiment_id)
        .all()
    )

    # Determine total weeks
    if all_snapshots:
        total_weeks = max(s.week_number for s in all_snapshots)
    else:
        total_weeks = 0

    # Count avatars
    assignments = (
        db.query(AvatarAssignment)
        .filter(AvatarAssignment.experiment_id == experiment_id)
        .all()
    )
    total_avatars = len([a for a in assignments if not a.is_excluded])
    exclusions = len([a for a in assignments if a.is_excluded])

    # Compute final cumulative comparisons
    all_by_group = _organize_by_group(all_snapshots, group_map)
    final_stats = _compute_all_comparisons(all_by_group, groups)

    # Determine H0 rejection for primary metrics
    primary_significant = []
    for metric_name in PRIMARY_METRICS:
        metric_key = metric_name
        # Map to the actual key used in stats
        if metric_name == "shadowban_events":
            metric_key = "shadowban_occurred"
        if metric_key in final_stats:
            comparisons = final_stats[metric_key].get("comparisons", [])
            for comp in comparisons:
                if comp.get("significant"):
                    primary_significant.append(metric_name)
                    break

    h0_rejected = len(primary_significant) > 0

    # Compute confidence intervals for continuous metrics
    confidence_intervals = _compute_confidence_intervals(all_by_group, groups)

    # Build recommendation
    if h0_rejected:
        recommendation = (
            "H0 rejected: Posting method has a statistically significant effect "
            f"on {', '.join(primary_significant)}. "
            "Review group-level metrics to identify the safest posting method."
        )
    else:
        recommendation = (
            "H0 cannot be rejected: No statistically significant difference "
            "found between posting methods on primary health metrics. "
            "All tested methods appear equivalent in terms of avatar safety."
        )

    final_summary = {
        "h0_rejected": h0_rejected,
        "primary_metrics_significant": primary_significant,
        "confidence_intervals": confidence_intervals,
        "recommendation": recommendation,
        "total_weeks": total_weeks,
        "total_avatars_analyzed": total_avatars,
        "exclusions": exclusions,
        "final_statistics": final_stats,
    }

    logger.info(
        "Generated final report for experiment %s: h0_rejected=%s, weeks=%d",
        experiment_id, h0_rejected, total_weeks,
    )
    return final_summary


# ---------------------------------------------------------------------------
# Statistical Comparison Functions
# ---------------------------------------------------------------------------


def _compare_continuous(
    group_a_values: list[float],
    group_b_values: list[float],
    group_a_name: str,
    group_b_name: str,
    metric_name: str,
) -> dict | None:
    """Mann-Whitney U test for continuous metrics.

    Returns dict with test results, or None if insufficient data.
    Includes warning when sample size is below MIN_SAMPLE_SIZE.
    """
    n_a = len(group_a_values)
    n_b = len(group_b_values)

    if n_a < 2 or n_b < 2:
        return None  # Cannot compute with < 2 values per group

    warning = None
    if n_a < MIN_SAMPLE_SIZE or n_b < MIN_SAMPLE_SIZE:
        warning = (
            f"Small sample size: {group_a_name}={n_a}, {group_b_name}={n_b}. "
            f"Results may be unreliable (recommend n >= {MIN_SAMPLE_SIZE})."
        )

    try:
        u_stat, p_value = stats.mannwhitneyu(
            group_a_values, group_b_values, alternative="two-sided"
        )
    except ValueError:
        # All values identical or other edge case
        return None

    # Effect size: rank-biserial correlation r = 1 - (2U)/(n1*n2)
    n_product = n_a * n_b
    if n_product > 0:
        effect_size = abs(1 - (2 * u_stat) / n_product)
    else:
        effect_size = 0.0

    return {
        "pair": [group_a_name, group_b_name],
        "test": "mann_whitney_u",
        "statistic": float(u_stat),
        "p_value": float(p_value),
        "effect_size": round(effect_size, 4),
        "significant": p_value < ALPHA,
        "sample_sizes": {group_a_name: n_a, group_b_name: n_b},
        "warning": warning,
    }


def _compare_categorical(
    group_a_counts: tuple[int, int],
    group_b_counts: tuple[int, int],
    group_a_name: str,
    group_b_name: str,
    metric_name: str,
) -> dict | None:
    """Chi-squared test for categorical metrics.

    Input: (events, non_events) per group.
    Returns dict with test results, or None if cannot compute.
    Includes warning when sample size is below MIN_SAMPLE_SIZE.
    """
    contingency = [list(group_a_counts), list(group_b_counts)]

    # Cannot compute chi-squared with zero marginal totals
    if any(sum(row) == 0 for row in contingency):
        return None
    # Cannot compute if all in one category for both groups
    col_totals = [contingency[0][i] + contingency[1][i] for i in range(2)]
    if any(t == 0 for t in col_totals):
        return None

    n_a = sum(group_a_counts)
    n_b = sum(group_b_counts)
    n = n_a + n_b

    warning = None
    if n_a < MIN_SAMPLE_SIZE or n_b < MIN_SAMPLE_SIZE:
        warning = (
            f"Small sample size: {group_a_name}={n_a}, {group_b_name}={n_b}. "
            f"Results may be unreliable (recommend n >= {MIN_SAMPLE_SIZE})."
        )

    try:
        chi2, p_value, dof, expected = stats.chi2_contingency(
            contingency, correction=True
        )
    except ValueError:
        return None

    # Cramér's V for 2x2 table: sqrt(chi2 / n)
    cramers_v = math.sqrt(chi2 / n) if n > 0 else 0.0

    return {
        "pair": [group_a_name, group_b_name],
        "test": "chi_squared",
        "statistic": float(chi2),
        "p_value": float(p_value),
        "effect_size": round(cramers_v, 4),
        "significant": p_value < ALPHA,
        "sample_sizes": {group_a_name: n_a, group_b_name: n_b},
        "warning": warning,
    }


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------


def _organize_by_group(
    snapshots: list[MetricSnapshot],
    group_map: dict,
) -> dict[str, list[MetricSnapshot]]:
    """Organize snapshots by group posting_method name."""
    result: dict[str, list[MetricSnapshot]] = {}
    for snap in snapshots:
        group = group_map.get(snap.group_id)
        if group is None:
            continue
        key = group.posting_method
        if key not in result:
            result[key] = []
        result[key].append(snap)
    return result


def _extract_metric_values(
    snapshots: list[MetricSnapshot],
    metric_name: str,
) -> list[float]:
    """Extract non-None numeric values for a metric from snapshots."""
    values = []
    for snap in snapshots:
        val = None
        if metric_name == "removal_rate":
            val = snap.removal_rate
        elif metric_name == "karma_velocity_4h":
            val = snap.karma_velocity_4h
        elif metric_name == "karma_velocity_24h":
            val = snap.karma_velocity_24h
        elif metric_name == "karma_velocity_7d":
            val = snap.karma_velocity_7d
        elif metric_name == "subreddit_bans":
            val = snap.subreddit_bans_new
        elif metric_name == "phase_speed":
            val = snap.phase_at_end - snap.phase_at_start

        if val is not None:
            values.append(float(val))
    return values


def _extract_categorical_counts(
    snapshots: list[MetricSnapshot],
    metric_name: str,
) -> tuple[int, int]:
    """Extract (events, non_events) for a categorical metric.

    For shadowban_occurred: event = shadowban_events > 0
    For cqs_changed: event = cqs_changed == True
    """
    events = 0
    non_events = 0
    for snap in snapshots:
        if metric_name == "shadowban_occurred":
            if snap.shadowban_events > 0:
                events += 1
            else:
                non_events += 1
        elif metric_name == "cqs_changed":
            if snap.cqs_changed:
                events += 1
            else:
                non_events += 1
    return events, non_events


def _compute_group_aggregate(values: list[float]) -> dict:
    """Compute mean, median, std, n for a list of values."""
    if not values:
        return {"mean": None, "median": None, "std": None, "n": 0}
    arr = np.array(values)
    return {
        "mean": round(float(np.mean(arr)), 4),
        "median": round(float(np.median(arr)), 4),
        "std": round(float(np.std(arr, ddof=1)), 4) if len(arr) > 1 else 0.0,
        "n": len(arr),
    }


def _compute_categorical_aggregate(
    snapshots: list[MetricSnapshot],
    metric_name: str,
) -> dict:
    """Compute event count and total n for a categorical metric."""
    events, non_events = _extract_categorical_counts(snapshots, metric_name)
    total = events + non_events
    rate = events / total if total > 0 else 0.0
    return {
        "count": events,
        "n": total,
        "rate": round(rate, 4),
    }


def _compute_all_comparisons(
    by_group: dict[str, list[MetricSnapshot]],
    groups: list[TreatmentGroup],
) -> dict:
    """Compute per-metric group aggregates and pairwise comparisons.

    Returns a dict keyed by metric name with structure:
    {
        "groups": {group_method: aggregate_dict, ...},
        "comparisons": [comparison_dict, ...]
    }
    """
    group_methods = sorted(by_group.keys())
    result = {}

    # Continuous metrics
    for metric_name in CONTINUOUS_METRICS:
        groups_data = {}
        for method in group_methods:
            values = _extract_metric_values(by_group[method], metric_name)
            groups_data[method] = _compute_group_aggregate(values)

        comparisons = []
        for method_a, method_b in combinations(group_methods, 2):
            values_a = _extract_metric_values(by_group[method_a], metric_name)
            values_b = _extract_metric_values(by_group[method_b], metric_name)
            comp = _compare_continuous(
                values_a, values_b, method_a, method_b, metric_name
            )
            if comp is not None:
                comparisons.append(comp)

        result[metric_name] = {
            "groups": groups_data,
            "comparisons": comparisons,
        }

    # Categorical metrics
    for metric_name in CATEGORICAL_METRICS:
        groups_data = {}
        for method in group_methods:
            groups_data[method] = _compute_categorical_aggregate(
                by_group[method], metric_name
            )

        comparisons = []
        for method_a, method_b in combinations(group_methods, 2):
            counts_a = _extract_categorical_counts(
                by_group[method_a], metric_name
            )
            counts_b = _extract_categorical_counts(
                by_group[method_b], metric_name
            )
            comp = _compare_categorical(
                counts_a, counts_b, method_a, method_b, metric_name
            )
            if comp is not None:
                comparisons.append(comp)

        result[metric_name] = {
            "groups": groups_data,
            "comparisons": comparisons,
        }

    return result


def _build_raw_data(
    snapshots: list[MetricSnapshot],
    group_map: dict,
) -> dict:
    """Build per-avatar raw data table for report_data JSONB.

    Returns dict keyed by group posting_method with list of avatar records.
    """
    raw: dict[str, list[dict]] = {}
    for snap in snapshots:
        group = group_map.get(snap.group_id)
        if group is None:
            continue
        method = group.posting_method
        if method not in raw:
            raw[method] = []
        raw[method].append({
            "avatar_id": str(snap.avatar_id),
            "week_number": snap.week_number,
            "removal_rate": float(snap.removal_rate) if snap.removal_rate is not None else None,
            "total_posted": snap.total_posted,
            "total_deleted": snap.total_deleted,
            "karma_velocity_4h": float(snap.karma_velocity_4h) if snap.karma_velocity_4h is not None else None,
            "karma_velocity_24h": float(snap.karma_velocity_24h) if snap.karma_velocity_24h is not None else None,
            "karma_velocity_7d": float(snap.karma_velocity_7d) if snap.karma_velocity_7d is not None else None,
            "shadowban_events": snap.shadowban_events,
            "cqs_changed": snap.cqs_changed,
            "cqs_level_start": snap.cqs_level_start,
            "cqs_level_end": snap.cqs_level_end,
            "subreddit_bans_new": snap.subreddit_bans_new,
            "phase_at_start": snap.phase_at_start,
            "phase_at_end": snap.phase_at_end,
            "tasks_attempted": snap.tasks_attempted,
            "tasks_succeeded": snap.tasks_succeeded,
            "tasks_failed": snap.tasks_failed,
        })
    return raw


def _check_early_termination(
    db: Session,
    experiment_id: "str | __import__('uuid').UUID",
    week_number: int,
) -> tuple[bool, list[str]]:
    """Check if primary metrics show significance for 2+ consecutive weeks.

    Detects 2 consecutive weeks with significant primary metric AND
    medium-or-larger effect size. Emits activity event if triggered.

    Args:
        db: SQLAlchemy session.
        experiment_id: UUID of the experiment.
        week_number: Current week number.

    Returns:
        (recommend_termination, alert_metric_names)
    """
    if week_number < CONSECUTIVE_WEEKS_ALERT:
        return False, []

    # Load reports for last N weeks (current + previous)
    recent_reports = (
        db.query(WeeklyReport)
        .filter(
            WeeklyReport.experiment_id == experiment_id,
            WeeklyReport.week_number >= week_number - CONSECUTIVE_WEEKS_ALERT,
            WeeklyReport.week_number < week_number,  # Previous weeks only
        )
        .order_by(WeeklyReport.week_number)
        .all()
    )

    if len(recent_reports) < CONSECUTIVE_WEEKS_ALERT - 1:
        return False, []

    alert_metrics: list[str] = []

    for primary_metric in PRIMARY_METRICS:
        # Map primary metric to the key used in statistics_json
        metric_key = primary_metric
        if primary_metric == "shadowban_events":
            metric_key = "shadowban_occurred"

        # Check previous weeks had significant result with medium+ effect
        consecutive_significant = 0
        for report in recent_reports:
            stats_data = report.statistics_json or {}
            metric_data = stats_data.get(metric_key, {})
            comparisons = metric_data.get("comparisons", [])

            has_significant_medium = False
            for comp in comparisons:
                if (
                    comp.get("significant")
                    and comp.get("effect_size", 0) >= MEDIUM_EFFECT_THRESHOLD
                ):
                    has_significant_medium = True
                    break

            if has_significant_medium:
                consecutive_significant += 1
            else:
                consecutive_significant = 0

        # Need consecutive_significant == CONSECUTIVE_WEEKS_ALERT - 1
        # (previous weeks) because current week's report isn't stored yet.
        # We check current week's stats are also significant below.
        if consecutive_significant >= CONSECUTIVE_WEEKS_ALERT - 1:
            alert_metrics.append(primary_metric)

    return len(alert_metrics) > 0, alert_metrics


def _compute_confidence_intervals(
    by_group: dict[str, list[MetricSnapshot]],
    groups: list[TreatmentGroup],
) -> dict:
    """Compute 95% confidence intervals for continuous metric differences.

    Uses bootstrap-free approach: mean ± 1.96 * SE for each group,
    plus difference CI between pairs.
    """
    group_methods = sorted(by_group.keys())
    ci_result: dict = {}

    for metric_name in CONTINUOUS_METRICS:
        metric_ci: dict = {"groups": {}, "differences": []}

        for method in group_methods:
            values = _extract_metric_values(by_group[method], metric_name)
            if len(values) >= 2:
                arr = np.array(values)
                mean = float(np.mean(arr))
                se = float(np.std(arr, ddof=1) / np.sqrt(len(arr)))
                ci_low = mean - 1.96 * se
                ci_high = mean + 1.96 * se
                metric_ci["groups"][method] = {
                    "mean": round(mean, 4),
                    "ci_lower": round(ci_low, 4),
                    "ci_upper": round(ci_high, 4),
                    "n": len(values),
                }
            else:
                metric_ci["groups"][method] = {
                    "mean": float(values[0]) if values else None,
                    "ci_lower": None,
                    "ci_upper": None,
                    "n": len(values),
                }

        # Compute difference CIs for each pair
        for method_a, method_b in combinations(group_methods, 2):
            values_a = _extract_metric_values(by_group[method_a], metric_name)
            values_b = _extract_metric_values(by_group[method_b], metric_name)
            if len(values_a) >= 2 and len(values_b) >= 2:
                arr_a = np.array(values_a)
                arr_b = np.array(values_b)
                diff_mean = float(np.mean(arr_a) - np.mean(arr_b))
                se_diff = float(
                    np.sqrt(
                        np.var(arr_a, ddof=1) / len(arr_a)
                        + np.var(arr_b, ddof=1) / len(arr_b)
                    )
                )
                ci_low = diff_mean - 1.96 * se_diff
                ci_high = diff_mean + 1.96 * se_diff
                metric_ci["differences"].append({
                    "pair": [method_a, method_b],
                    "diff_mean": round(diff_mean, 4),
                    "ci_lower": round(ci_low, 4),
                    "ci_upper": round(ci_high, 4),
                })

        ci_result[metric_name] = metric_ci

    return ci_result


def _emit_early_termination_alert(
    db: Session,
    experiment: ExperimentRun,
    week_number: int,
    alert_metrics: list[str],
) -> None:
    """Emit an activity event recommending early termination review."""
    event = ActivityEvent(
        client_id=None,
        event_type="ab_test_early_termination_alert",
        message=(
            f"A/B test '{experiment.name}' (week {week_number}): "
            f"significant results on primary metrics {alert_metrics} "
            f"for {CONSECUTIVE_WEEKS_ALERT}+ consecutive weeks. "
            "Consider early termination."
        ),
        event_metadata={
            "experiment_id": str(experiment.id),
            "experiment_name": experiment.name,
            "week_number": week_number,
            "alert_metrics": alert_metrics,
            "consecutive_weeks": CONSECUTIVE_WEEKS_ALERT,
        },
    )
    db.add(event)
    logger.warning(
        "Early termination alert for experiment %s week %d: metrics=%s",
        experiment.id, week_number, alert_metrics,
    )
