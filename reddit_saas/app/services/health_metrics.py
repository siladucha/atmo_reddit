"""Health metrics aggregation for the admin System Health dashboard.

Reddit API metrics are aggregated from the ``scrape_log`` table. LLM API
metrics are aggregated from ``ai_usage_log``. Scrape freshness is computed
from ``client_subreddits.last_scraped_at`` across all active clients.

The in-memory ``MetricsCollector`` only contributes the most recent
PRAW rate-limit snapshot — multi-process aggregation lives in the DB.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.ai_usage import AIUsageLog
from app.models.client import Client
from app.models.scrape_log import ScrapeLog
from app.models.subreddit import ClientSubreddit
from app.services.metrics_collector import (
    MetricsCollector,
    RateLimitState,
    gauge_color,
)


REDDIT_ERROR_RATE_WARNING = 5.0
REDDIT_ERROR_RATE_CRITICAL = 20.0
REDDIT_LATENCY_WARNING_MS = 3000.0

LLM_LATENCY_WARNING_MS = 5000.0


# ---------------------------------------------------------------------------
# Reddit API metrics
# ---------------------------------------------------------------------------


def _classify_reddit_error(message: str | None) -> str:
    """Coarse-grained error type for the breakdown widget."""
    if not message:
        return "other"
    m = message.lower()
    if "ratelimited" in m or "rate_limited" in m or "429" in m or "toomanyrequests" in m:
        return "rate_limited"
    if "forbidden" in m or "403" in m:
        return "forbidden"
    if "timeout" in m or "timed out" in m:
        return "timeout"
    return "other"


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Return the ``pct``-th percentile (linear interpolation, 0 ≤ pct ≤ 100)."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    k = (len(sorted_values) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    weight = k - lo
    return float(sorted_values[lo]) * (1 - weight) + float(sorted_values[hi]) * weight


def _reddit_status(error_rate_pct: float, avg_response_ms: float) -> str:
    if error_rate_pct > REDDIT_ERROR_RATE_CRITICAL:
        return "critical"
    if error_rate_pct > REDDIT_ERROR_RATE_WARNING or avg_response_ms > REDDIT_LATENCY_WARNING_MS:
        return "warning"
    return "ok"


def get_reddit_api_metrics(db: Session, window_minutes: int = 60) -> dict[str, Any]:
    """Aggregate Reddit API metrics from the ``scrape_log`` table."""
    window_minutes = max(1, int(window_minutes))
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)

    rows = (
        db.query(ScrapeLog.duration_ms, ScrapeLog.errors)
        .filter(ScrapeLog.scraped_at >= cutoff)
        .all()
    )

    durations: list[int] = []
    error_messages: list[str] = []
    for row in rows:
        duration = row.duration_ms or 0
        durations.append(int(duration))
        if row.errors:
            error_messages.append(row.errors)

    total_calls = len(rows)
    error_count = len(error_messages)
    error_rate_pct = (error_count / total_calls * 100.0) if total_calls else 0.0
    calls_per_minute = total_calls / window_minutes if window_minutes else 0.0

    if durations:
        avg_response_ms = float(statistics.mean(durations))
        p95_response_ms = _percentile(sorted(durations), 95.0)
    else:
        avg_response_ms = 0.0
        p95_response_ms = 0.0

    errors_by_type = {"rate_limited": 0, "forbidden": 0, "timeout": 0, "other": 0}
    for msg in error_messages:
        errors_by_type[_classify_reddit_error(msg)] += 1

    return {
        "total_calls": total_calls,
        "error_count": error_count,
        "error_rate_pct": round(error_rate_pct, 2),
        "avg_response_ms": round(avg_response_ms, 2),
        "p95_response_ms": round(p95_response_ms, 2),
        "calls_per_minute": round(calls_per_minute, 2),
        "errors_by_type": errors_by_type,
        "status": _reddit_status(error_rate_pct, avg_response_ms),
        "window_minutes": window_minutes,
    }


# ---------------------------------------------------------------------------
# LLM API metrics
# ---------------------------------------------------------------------------


def _llm_status(avg_latency_ms: float, error_count: int) -> str:
    if error_count > 0 or avg_latency_ms > LLM_LATENCY_WARNING_MS:
        return "warning"
    return "ok"


def get_llm_api_metrics(db: Session, window_minutes: int = 60) -> dict[str, Any]:
    """Aggregate LLM API metrics from the ``ai_usage_log`` table."""
    window_minutes = max(1, int(window_minutes))
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)

    rows = (
        db.query(
            sa_func.count(AIUsageLog.id).label("total_calls"),
            sa_func.coalesce(sa_func.sum(AIUsageLog.cost_usd), 0).label("total_cost"),
            sa_func.coalesce(sa_func.avg(AIUsageLog.duration_ms), 0).label("avg_latency"),
        )
        .filter(AIUsageLog.created_at >= cutoff)
        .one()
    )

    total_calls = int(rows.total_calls or 0)
    total_cost = float(rows.total_cost or 0)
    avg_latency_ms = float(rows.avg_latency or 0)

    by_model_rows = (
        db.query(
            AIUsageLog.model,
            sa_func.count(AIUsageLog.id).label("calls"),
            sa_func.coalesce(sa_func.sum(AIUsageLog.cost_usd), 0).label("cost"),
        )
        .filter(AIUsageLog.created_at >= cutoff)
        .group_by(AIUsageLog.model)
        .all()
    )
    by_model = [
        {
            "model": row.model,
            "calls": int(row.calls or 0),
            "cost_usd": round(float(row.cost or 0), 6),
        }
        for row in by_model_rows
    ]
    by_model.sort(key=lambda m: m["calls"], reverse=True)

    # ai_usage_log doesn't currently store error rows; treat zero-token,
    # zero-cost entries as failed completions for visibility.
    error_count = (
        db.query(sa_func.count(AIUsageLog.id))
        .filter(
            AIUsageLog.created_at >= cutoff,
            AIUsageLog.input_tokens == 0,
            AIUsageLog.output_tokens == 0,
        )
        .scalar()
    ) or 0
    error_count = int(error_count)

    return {
        "total_calls": total_calls,
        "total_cost_usd": round(total_cost, 6),
        "avg_latency_ms": round(avg_latency_ms, 2),
        "error_count": error_count,
        "by_model": by_model,
        "status": _llm_status(avg_latency_ms, error_count),
        "window_minutes": window_minutes,
    }


# ---------------------------------------------------------------------------
# Scrape freshness across all active clients
# ---------------------------------------------------------------------------


def get_all_scrape_freshness(db: Session, stale_hours: int = 24) -> dict[str, Any]:
    """Aggregate per-subreddit scrape freshness across all active clients."""
    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(hours=stale_hours)

    rows = (
        db.query(ClientSubreddit, Client.client_name)
        .join(Client, ClientSubreddit.client_id == Client.id)
        .filter(
            ClientSubreddit.is_active.is_(True),
            Client.is_active.is_(True),
        )
        .order_by(Client.client_name, ClientSubreddit.subreddit_name)
        .all()
    )

    subreddits: list[dict[str, Any]] = []
    stale_count = 0
    never_scraped_count = 0
    for sub, client_name in rows:
        last_scraped = sub.last_scraped_at
        is_never_scraped = last_scraped is None
        is_stale = is_never_scraped or last_scraped < stale_threshold
        if is_stale:
            stale_count += 1
        if is_never_scraped:
            never_scraped_count += 1
        subreddits.append({
            "subreddit_name": sub.subreddit_name,
            "client_name": client_name,
            "client_id": str(sub.client_id),
            "subreddit_id": str(sub.id),
            "last_scraped_at": last_scraped,
            "is_stale": is_stale,
            "is_never_scraped": is_never_scraped,
        })

    return {
        "subreddits": subreddits,
        "total_active": len(subreddits),
        "stale_count": stale_count,
        "never_scraped_count": never_scraped_count,
        "stale_hours": stale_hours,
    }


# ---------------------------------------------------------------------------
# JSON snapshot for /admin/health/metrics
# ---------------------------------------------------------------------------


def _rate_limit_payload(state: RateLimitState) -> dict[str, Any]:
    payload = state.to_dict()
    payload["color"] = gauge_color(state.usage_pct)
    return payload


def get_metrics_snapshot(db: Session, collector: MetricsCollector) -> dict[str, Any]:
    """Combined JSON snapshot for the metrics API endpoint."""
    window_minutes = collector.get_window_minutes()
    rate_limit = collector.get_rate_limit()

    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "window_minutes": window_minutes,
        "rate_limit": _rate_limit_payload(rate_limit),
        "reddit_api": get_reddit_api_metrics(db, window_minutes=window_minutes),
        "llm_api": get_llm_api_metrics(db, window_minutes=window_minutes),
        "scrape_freshness": _serialize_freshness(get_all_scrape_freshness(db)),
    }


def _serialize_freshness(data: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe copy of scrape freshness output (datetimes → ISO strings)."""
    return {
        **{k: v for k, v in data.items() if k != "subreddits"},
        "subreddits": [
            {
                **sub,
                "last_scraped_at": (
                    sub["last_scraped_at"].isoformat()
                    if isinstance(sub["last_scraped_at"], datetime)
                    else None
                ),
            }
            for sub in data["subreddits"]
        ],
    }
