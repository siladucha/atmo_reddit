"""LLM Quality Monitor — detects model degradation under load.

Analyzes ai_usage_log quality_outcome fields to detect:
1. Success rate drops (empty responses, parse errors, timeouts)
2. Latency increases (avg and p95 duration_ms)
3. Fallback frequency spikes (model unavailable → using backup)
4. Per-operation quality drift (e.g. generation quality drops but scoring stays fine)

Produces LLMQualitySnapshot records and triggers alerts on degradation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func as sa_func, literal_column
from sqlalchemy.orm import Session

from app.models.ai_usage import AIUsageLog
from app.models.llm_quality_snapshot import LLMQualitySnapshot

logger = logging.getLogger(__name__)


# --- Configuration ---
# Minimum calls in a window to consider for analysis (avoid noise from low-volume operations)
MIN_CALLS_FOR_ANALYSIS = 5
# How far back to look for baseline (7 days)
BASELINE_DAYS = 7
# Degradation thresholds
SUCCESS_RATE_DROP_THRESHOLD = 10.0  # alert if success rate drops >10pp from baseline
LATENCY_SPIKE_THRESHOLD = 2.0  # alert if avg latency > 2x baseline
FALLBACK_RATE_THRESHOLD = 20.0  # alert if >20% of calls needed fallback
EMPTY_RATE_THRESHOLD = 15.0  # alert if >15% of responses are empty


@dataclass
class QualityMetrics:
    """Quality metrics for a model×operation pair within a time window."""

    model: str
    operation: str
    total_calls: int = 0
    success_count: int = 0
    empty_count: int = 0
    parse_error_count: int = 0
    timeout_count: int = 0
    error_count: int = 0
    fallback_count: int = 0
    avg_duration_ms: int = 0
    p95_duration_ms: int = 0
    avg_output_tokens: int = 0
    avg_cost_usd: float = 0.0
    success_rate: float = 100.0
    durations: list[int] = field(default_factory=list)


@dataclass
class DegradationSignal:
    """A detected degradation signal."""

    model: str
    operation: str
    signal_type: str  # success_rate_drop | latency_spike | high_fallback | high_empty
    current_value: float
    baseline_value: float
    threshold: float
    severity: str  # critical | high | medium
    message: str


def compute_quality_snapshot(
    db: Session,
    window_hours: int = 4,
) -> list[LLMQualitySnapshot]:
    """Compute quality metrics for the last N hours and compare against baseline.

    Returns list of LLMQualitySnapshot records (one per model×operation pair).
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=window_hours)
    baseline_start = now - timedelta(days=BASELINE_DAYS)

    # --- Current window metrics ---
    current_metrics = _collect_window_metrics(db, window_start, now)

    if not current_metrics:
        logger.info("LLM_QUALITY_CHECK | no calls in last %dh | skipping", window_hours)
        return []

    # --- Baseline metrics (7-day average per model×operation) ---
    baseline_metrics = _collect_baseline_metrics(db, baseline_start, window_start)

    # --- Compare and detect degradation ---
    snapshots = []
    for key, current in current_metrics.items():
        if current.total_calls < MIN_CALLS_FOR_ANALYSIS:
            continue

        baseline = baseline_metrics.get(key)
        baseline_success = float(baseline.success_rate) if baseline else 95.0
        baseline_duration = baseline.avg_duration_ms if baseline else current.avg_duration_ms

        # Detect degradation
        degradation_signals = []

        # 1. Success rate drop
        if baseline_success - current.success_rate > SUCCESS_RATE_DROP_THRESHOLD:
            degradation_signals.append({
                "type": "success_rate_drop",
                "current": round(current.success_rate, 1),
                "baseline": round(baseline_success, 1),
                "drop_pp": round(baseline_success - current.success_rate, 1),
            })

        # 2. Latency spike
        if baseline_duration and baseline_duration > 0:
            latency_ratio = current.avg_duration_ms / baseline_duration
            if latency_ratio > LATENCY_SPIKE_THRESHOLD:
                degradation_signals.append({
                    "type": "latency_spike",
                    "current_ms": current.avg_duration_ms,
                    "baseline_ms": baseline_duration,
                    "ratio": round(latency_ratio, 1),
                })

        # 3. High fallback rate
        fallback_rate = (current.fallback_count / current.total_calls * 100) if current.total_calls > 0 else 0
        if fallback_rate > FALLBACK_RATE_THRESHOLD:
            degradation_signals.append({
                "type": "high_fallback",
                "rate_pct": round(fallback_rate, 1),
                "fallback_count": current.fallback_count,
            })

        # 4. High empty response rate
        empty_rate = (current.empty_count / current.total_calls * 100) if current.total_calls > 0 else 0
        if empty_rate > EMPTY_RATE_THRESHOLD:
            degradation_signals.append({
                "type": "high_empty",
                "rate_pct": round(empty_rate, 1),
                "empty_count": current.empty_count,
            })

        snapshot = LLMQualitySnapshot(
            window_start=window_start,
            window_end=now,
            model=current.model,
            operation=current.operation,
            total_calls=current.total_calls,
            success_count=current.success_count,
            empty_count=current.empty_count,
            parse_error_count=current.parse_error_count,
            timeout_count=current.timeout_count,
            error_count=current.error_count,
            fallback_count=current.fallback_count,
            avg_duration_ms=current.avg_duration_ms,
            p95_duration_ms=current.p95_duration_ms,
            avg_output_tokens=current.avg_output_tokens,
            success_rate=Decimal(str(round(current.success_rate, 2))),
            avg_cost_usd=Decimal(str(round(current.avg_cost_usd, 6))),
            baseline_success_rate=Decimal(str(round(baseline_success, 2))),
            baseline_avg_duration_ms=baseline_duration,
            degradation_detected=len(degradation_signals) > 0,
            degradation_details=degradation_signals if degradation_signals else None,
        )
        snapshots.append(snapshot)

    return snapshots


def get_degradation_alerts(db: Session, hours: int = 4) -> list[DegradationSignal]:
    """Get active degradation signals from recent quality snapshots.

    Used by alert_aggregation.py to surface alerts on dashboard.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    degraded = (
        db.query(LLMQualitySnapshot)
        .filter(
            LLMQualitySnapshot.created_at >= cutoff,
            LLMQualitySnapshot.degradation_detected.is_(True),
        )
        .all()
    )

    signals = []
    for snap in degraded:
        if not snap.degradation_details:
            continue
        for detail in snap.degradation_details:
            sig_type = detail.get("type", "unknown")
            severity = _classify_severity(sig_type, detail)
            message = _format_degradation_message(snap.model, snap.operation, sig_type, detail)
            signals.append(DegradationSignal(
                model=snap.model,
                operation=snap.operation,
                signal_type=sig_type,
                current_value=detail.get("current", detail.get("current_ms", detail.get("rate_pct", 0))),
                baseline_value=detail.get("baseline", detail.get("baseline_ms", 0)),
                threshold=_get_threshold_for_type(sig_type),
                severity=severity,
                message=message,
            ))

    return signals


def get_quality_summary(db: Session, hours: int = 24) -> dict[str, Any]:
    """Get overall quality summary for the admin dashboard.

    Returns aggregated quality metrics across all models and operations.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    rows = (
        db.query(
            AIUsageLog.quality_outcome,
            sa_func.count(AIUsageLog.id).label("cnt"),
        )
        .filter(AIUsageLog.created_at >= cutoff)
        .group_by(AIUsageLog.quality_outcome)
        .all()
    )

    total = sum(r.cnt for r in rows)
    by_outcome = {r.quality_outcome or "unknown": r.cnt for r in rows}

    success = by_outcome.get("success", 0)
    success_rate = (success / total * 100) if total > 0 else 100.0

    # Per-model summary
    model_rows = (
        db.query(
            AIUsageLog.model,
            sa_func.count(AIUsageLog.id).label("total"),
            sa_func.sum(case((AIUsageLog.quality_outcome == "success", 1), else_=0)).label("success"),
            sa_func.avg(AIUsageLog.duration_ms).label("avg_duration"),
            sa_func.sum(case((AIUsageLog.quality_outcome == "empty", 1), else_=0)).label("empty"),
            sa_func.sum(case((AIUsageLog.quality_outcome == "parse_error", 1), else_=0)).label("parse_errors"),
            sa_func.sum(case((AIUsageLog.quality_outcome == "timeout", 1), else_=0)).label("timeouts"),
            sa_func.sum(case((AIUsageLog.quality_outcome == "fallback_used", 1), else_=0)).label("fallbacks"),
        )
        .filter(AIUsageLog.created_at >= cutoff)
        .group_by(AIUsageLog.model)
        .all()
    )

    models = []
    for r in model_rows:
        model_total = r.total or 0
        model_success = r.success or 0
        models.append({
            "model": r.model,
            "total": model_total,
            "success_rate": round((model_success / model_total * 100) if model_total > 0 else 100, 1),
            "avg_duration_ms": int(r.avg_duration or 0),
            "empty": r.empty or 0,
            "parse_errors": r.parse_errors or 0,
            "timeouts": r.timeouts or 0,
            "fallbacks": r.fallbacks or 0,
        })

    # Per-operation summary
    op_rows = (
        db.query(
            AIUsageLog.operation,
            sa_func.count(AIUsageLog.id).label("total"),
            sa_func.sum(case((AIUsageLog.quality_outcome == "success", 1), else_=0)).label("success"),
            sa_func.avg(AIUsageLog.duration_ms).label("avg_duration"),
        )
        .filter(AIUsageLog.created_at >= cutoff)
        .group_by(AIUsageLog.operation)
        .order_by(sa_func.count(AIUsageLog.id).desc())
        .all()
    )

    operations = []
    for r in op_rows:
        op_total = r.total or 0
        op_success = r.success or 0
        operations.append({
            "operation": r.operation,
            "total": op_total,
            "success_rate": round((op_success / op_total * 100) if op_total > 0 else 100, 1),
            "avg_duration_ms": int(r.avg_duration or 0),
        })

    # Recent degradation events
    recent_degradations = (
        db.query(LLMQualitySnapshot)
        .filter(
            LLMQualitySnapshot.degradation_detected.is_(True),
            LLMQualitySnapshot.created_at >= cutoff,
        )
        .order_by(LLMQualitySnapshot.created_at.desc())
        .limit(10)
        .all()
    )

    return {
        "period_hours": hours,
        "total_calls": total,
        "success_rate": round(success_rate, 1),
        "by_outcome": by_outcome,
        "models": sorted(models, key=lambda m: m["total"], reverse=True),
        "operations": operations,
        "degradation_events": len(recent_degradations),
        "recent_degradations": [
            {
                "model": d.model,
                "operation": d.operation,
                "success_rate": float(d.success_rate) if d.success_rate else None,
                "details": d.degradation_details,
                "at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in recent_degradations
        ],
    }


# --- Internal helpers ---


def _collect_window_metrics(
    db: Session,
    window_start: datetime,
    window_end: datetime,
) -> dict[tuple[str, str], QualityMetrics]:
    """Collect per-model×operation metrics for a time window."""
    rows = (
        db.query(
            AIUsageLog.model,
            AIUsageLog.operation,
            sa_func.count(AIUsageLog.id).label("total"),
            sa_func.sum(case((AIUsageLog.quality_outcome == "success", 1), else_=0)).label("success"),
            sa_func.sum(case((AIUsageLog.quality_outcome == "empty", 1), else_=0)).label("empty"),
            sa_func.sum(case((AIUsageLog.quality_outcome == "parse_error", 1), else_=0)).label("parse_error"),
            sa_func.sum(case((AIUsageLog.quality_outcome == "timeout", 1), else_=0)).label("timeout"),
            sa_func.sum(case((AIUsageLog.quality_outcome == "error", 1), else_=0)).label("error"),
            sa_func.sum(case((AIUsageLog.quality_outcome == "fallback_used", 1), else_=0)).label("fallback"),
            sa_func.avg(AIUsageLog.duration_ms).label("avg_duration"),
            sa_func.avg(AIUsageLog.output_tokens).label("avg_output"),
            sa_func.avg(AIUsageLog.cost_usd).label("avg_cost"),
        )
        .filter(
            AIUsageLog.created_at >= window_start,
            AIUsageLog.created_at < window_end,
        )
        .group_by(AIUsageLog.model, AIUsageLog.operation)
        .all()
    )

    metrics = {}
    for r in rows:
        total = r.total or 0
        success = r.success or 0
        key = (r.model, r.operation)
        metrics[key] = QualityMetrics(
            model=r.model,
            operation=r.operation,
            total_calls=total,
            success_count=success,
            empty_count=r.empty or 0,
            parse_error_count=r.parse_error or 0,
            timeout_count=r.timeout or 0,
            error_count=r.error or 0,
            fallback_count=r.fallback or 0,
            avg_duration_ms=int(r.avg_duration or 0),
            avg_output_tokens=int(r.avg_output or 0),
            avg_cost_usd=float(r.avg_cost or 0),
            success_rate=(success / total * 100) if total > 0 else 100.0,
        )

    # Compute p95 durations (separate query — percentile not in all SQLAlchemy builds)
    for key, m in metrics.items():
        durations = (
            db.query(AIUsageLog.duration_ms)
            .filter(
                AIUsageLog.created_at >= window_start,
                AIUsageLog.created_at < window_end,
                AIUsageLog.model == m.model,
                AIUsageLog.operation == m.operation,
                AIUsageLog.duration_ms.isnot(None),
            )
            .order_by(AIUsageLog.duration_ms)
            .all()
        )
        if durations:
            vals = [d[0] for d in durations if d[0] is not None]
            if vals:
                idx_95 = int(len(vals) * 0.95)
                m.p95_duration_ms = vals[min(idx_95, len(vals) - 1)]

    return metrics


def _collect_baseline_metrics(
    db: Session,
    baseline_start: datetime,
    baseline_end: datetime,
) -> dict[tuple[str, str], QualityMetrics]:
    """Collect baseline (7-day) metrics per model×operation."""
    rows = (
        db.query(
            AIUsageLog.model,
            AIUsageLog.operation,
            sa_func.count(AIUsageLog.id).label("total"),
            sa_func.sum(case((AIUsageLog.quality_outcome == "success", 1), else_=0)).label("success"),
            sa_func.avg(AIUsageLog.duration_ms).label("avg_duration"),
        )
        .filter(
            AIUsageLog.created_at >= baseline_start,
            AIUsageLog.created_at < baseline_end,
        )
        .group_by(AIUsageLog.model, AIUsageLog.operation)
        .all()
    )

    metrics = {}
    for r in rows:
        total = r.total or 0
        success = r.success or 0
        key = (r.model, r.operation)
        metrics[key] = QualityMetrics(
            model=r.model,
            operation=r.operation,
            total_calls=total,
            success_count=success,
            avg_duration_ms=int(r.avg_duration or 0),
            success_rate=(success / total * 100) if total > 0 else 95.0,
        )

    return metrics


def _classify_severity(sig_type: str, detail: dict) -> str:
    """Classify degradation severity."""
    if sig_type == "success_rate_drop":
        drop = detail.get("drop_pp", 0)
        if drop > 30:
            return "critical"
        elif drop > 15:
            return "high"
        return "medium"
    elif sig_type == "latency_spike":
        ratio = detail.get("ratio", 1)
        if ratio > 5:
            return "critical"
        elif ratio > 3:
            return "high"
        return "medium"
    elif sig_type == "high_fallback":
        rate = detail.get("rate_pct", 0)
        if rate > 50:
            return "critical"
        return "high"
    elif sig_type == "high_empty":
        rate = detail.get("rate_pct", 0)
        if rate > 40:
            return "critical"
        return "high"
    return "medium"


def _format_degradation_message(model: str, operation: str, sig_type: str, detail: dict) -> str:
    """Format a human-readable degradation message."""
    short_model = model.split("/")[-1] if "/" in model else model

    if sig_type == "success_rate_drop":
        return (
            f"{short_model}/{operation}: success rate dropped "
            f"{detail.get('baseline', '?')}% → {detail.get('current', '?')}% "
            f"(-{detail.get('drop_pp', '?')}pp)"
        )
    elif sig_type == "latency_spike":
        return (
            f"{short_model}/{operation}: latency {detail.get('ratio', '?')}x baseline "
            f"({detail.get('current_ms', '?')}ms vs {detail.get('baseline_ms', '?')}ms)"
        )
    elif sig_type == "high_fallback":
        return (
            f"{short_model}/{operation}: {detail.get('rate_pct', '?')}% calls needed fallback "
            f"({detail.get('fallback_count', '?')} calls)"
        )
    elif sig_type == "high_empty":
        return (
            f"{short_model}/{operation}: {detail.get('rate_pct', '?')}% empty responses "
            f"({detail.get('empty_count', '?')} calls)"
        )
    return f"{short_model}/{operation}: quality degradation ({sig_type})"


def _get_threshold_for_type(sig_type: str) -> float:
    """Get the threshold value for a given signal type."""
    return {
        "success_rate_drop": SUCCESS_RATE_DROP_THRESHOLD,
        "latency_spike": LATENCY_SPIKE_THRESHOLD,
        "high_fallback": FALLBACK_RATE_THRESHOLD,
        "high_empty": EMPTY_RATE_THRESHOLD,
    }.get(sig_type, 0)
