"""Signal Collector — pure SQL aggregation for Daily Ops Review.

Collects all operational signals from existing tables.
No LLM calls. No interpretation. Just data.

Output: ReviewSnapshot (immutable, stored in DB).

Guidelines compliance:
- Snapshot First: all data frozen at collection time
- SQL + Rules before LLM: this module is 100% SQL
- Cache for session: snapshot is the cache
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func as sa_func, desc
from sqlalchemy.orm import Session

from app.models.activity_event import ActivityEvent
from app.models.ai_usage import AIUsageLog
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.posting_event import PostingEvent
from app.models.scrape_log import ScrapeLog
from app.models.subreddit import Subreddit, ClientSubredditAssignment

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class HealthSignal:
    """A single operational signal with current value and baseline comparison."""

    category: str  # uptime | errors | queue | latency | cost | posting | scraping | avatars
    metric_name: str  # e.g. "celery_failed_tasks_24h"
    current_value: float
    seven_day_avg: float
    seven_day_stddev: float
    delta_pct: float  # % change vs 7-day avg
    status: str  # better | worse | stable
    attention: bool  # > 1.5 stddev from baseline


@dataclass
class ChangeSignal:
    """A detected change in system behavior (not just an event)."""

    category: str  # new_error | frequency_change | quality_degradation | posting_anomaly | scrape_anomaly
    signal: str  # human-readable description
    evidence: str  # supporting data points
    impact: str  # avatar | client | platform
    confidence: str  # high | medium | low


@dataclass
class HealthSnapshot:
    """Complete point-in-time health collection."""

    signals: list[HealthSignal]
    changes: list[ChangeSignal]
    overall_verdict: str  # healthy | degraded | critical
    verdict_evidence: list[str]
    collected_at: str  # ISO format
    data_gaps: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CostSnapshot:
    """AI cost breakdown for the review period."""

    total_24h_usd: float
    total_7d_usd: float
    by_operation: dict[str, float]  # operation -> cost
    by_model: dict[str, float]  # model -> cost
    daily_avg_7d: float


@dataclass
class SignalCollection:
    """Full collection result ready to be stored as ReviewSnapshot."""

    health: HealthSnapshot
    cost: CostSnapshot
    trends: dict[str, Any]  # simplified trends for Phase 1
    forecast_inputs: dict[str, Any]  # raw data for future forecast use
    source_availability: dict[str, bool]  # which sources had data


# ---------------------------------------------------------------------------
# Collection functions
# ---------------------------------------------------------------------------


def collect_snapshot(db: Session) -> SignalCollection:
    """Collect all signals and return a complete SignalCollection.

    This is the main entry point. Called once at session start.
    All data is frozen — no live queries after this.
    """
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)
    since_7d = now - timedelta(days=7)

    data_gaps: list[str] = []

    # Collect each category
    signals: list[HealthSignal] = []
    changes: list[ChangeSignal] = []

    # --- Worker / Uptime ---
    try:
        worker_signals = _collect_worker_signals(db, now, since_24h, since_7d)
        signals.extend(worker_signals)
    except Exception as e:
        logger.warning(f"Failed to collect worker signals: {e}")
        data_gaps.append("worker_uptime")

    # --- Errors ---
    try:
        error_signals, error_changes = _collect_error_signals(db, now, since_24h, since_7d)
        signals.extend(error_signals)
        changes.extend(error_changes)
    except Exception as e:
        logger.warning(f"Failed to collect error signals: {e}")
        data_gaps.append("errors")

    # --- Queue ---
    try:
        queue_signals = _collect_queue_signals(db, now)
        signals.extend(queue_signals)
    except Exception as e:
        logger.warning(f"Failed to collect queue signals: {e}")
        data_gaps.append("queue")

    # --- Posting ---
    try:
        posting_signals, posting_changes = _collect_posting_signals(db, now, since_24h, since_7d)
        signals.extend(posting_signals)
        changes.extend(posting_changes)
    except Exception as e:
        logger.warning(f"Failed to collect posting signals: {e}")
        data_gaps.append("posting")

    # --- Scraping ---
    try:
        scrape_signals, scrape_changes = _collect_scrape_signals(db, now, since_24h, since_7d)
        signals.extend(scrape_signals)
        changes.extend(scrape_changes)
    except Exception as e:
        logger.warning(f"Failed to collect scrape signals: {e}")
        data_gaps.append("scraping")

    # --- Avatars ---
    try:
        avatar_signals = _collect_avatar_signals(db, now)
        signals.extend(avatar_signals)
    except Exception as e:
        logger.warning(f"Failed to collect avatar signals: {e}")
        data_gaps.append("avatars")

    # --- Cost ---
    try:
        cost = _collect_cost_snapshot(db, now, since_24h, since_7d)
    except Exception as e:
        logger.warning(f"Failed to collect cost snapshot: {e}")
        data_gaps.append("cost")
        cost = CostSnapshot(
            total_24h_usd=0, total_7d_usd=0, by_operation={},
            by_model={}, daily_avg_7d=0,
        )

    # --- Compute verdict ---
    verdict, verdict_evidence = _compute_verdict(signals, data_gaps)

    health = HealthSnapshot(
        signals=signals,
        changes=changes,
        overall_verdict=verdict,
        verdict_evidence=verdict_evidence,
        collected_at=now.isoformat(),
        data_gaps=data_gaps,
    )

    # Source availability
    source_availability = {
        "activity_events": "errors" not in data_gaps,
        "ai_usage_log": "cost" not in data_gaps,
        "posting_events": "posting" not in data_gaps,
        "scrape_log": "scraping" not in data_gaps,
        "avatars": "avatars" not in data_gaps,
    }

    return SignalCollection(
        health=health,
        cost=cost,
        trends={},  # Phase 2
        forecast_inputs={},  # Phase 2
        source_availability=source_availability,
    )


# ---------------------------------------------------------------------------
# Internal collectors
# ---------------------------------------------------------------------------


def _collect_worker_signals(
    db: Session, now: datetime, since_24h: datetime, since_7d: datetime
) -> list[HealthSignal]:
    """Check worker heartbeat freshness."""
    last_heartbeat = (
        db.query(ActivityEvent.created_at)
        .filter(
            ActivityEvent.event_type == "system",
            ActivityEvent.message.ilike("%heartbeat%"),
        )
        .order_by(desc(ActivityEvent.created_at))
        .first()
    )

    if not last_heartbeat or not last_heartbeat.created_at:
        worker_age_sec = 9999.0
    else:
        worker_age_sec = (now - last_heartbeat.created_at).total_seconds()

    worker_online = 1.0 if worker_age_sec < 120 else 0.0

    return [
        HealthSignal(
            category="uptime",
            metric_name="worker_online",
            current_value=worker_online,
            seven_day_avg=1.0,  # expected always online
            seven_day_stddev=0.0,
            delta_pct=0.0 if worker_online == 1.0 else -100.0,
            status="stable" if worker_online == 1.0 else "worse",
            attention=worker_online == 0.0,
        ),
    ]


def _collect_error_signals(
    db: Session, now: datetime, since_24h: datetime, since_7d: datetime
) -> tuple[list[HealthSignal], list[ChangeSignal]]:
    """Count errors in activity events and detect frequency changes."""
    # Errors in last 24h
    errors_24h = (
        db.query(sa_func.count(ActivityEvent.id))
        .filter(
            ActivityEvent.created_at >= since_24h,
            ActivityEvent.event_type.in_(["error", "task_failure", "pipeline_error"]),
        )
        .scalar()
    ) or 0

    # Daily error counts for last 7 days
    daily_errors = []
    for i in range(1, 8):
        day_start = now - timedelta(days=i)
        day_end = now - timedelta(days=i - 1)
        count = (
            db.query(sa_func.count(ActivityEvent.id))
            .filter(
                ActivityEvent.created_at >= day_start,
                ActivityEvent.created_at < day_end,
                ActivityEvent.event_type.in_(["error", "task_failure", "pipeline_error"]),
            )
            .scalar()
        ) or 0
        daily_errors.append(count)

    avg_7d = statistics.mean(daily_errors) if daily_errors else 0
    stddev_7d = statistics.stdev(daily_errors) if len(daily_errors) >= 2 else 0

    delta_pct = ((errors_24h - avg_7d) / avg_7d * 100) if avg_7d > 0 else 0
    attention = abs(errors_24h - avg_7d) > 1.5 * stddev_7d if stddev_7d > 0 else errors_24h > avg_7d * 2

    signals = [
        HealthSignal(
            category="errors",
            metric_name="errors_24h",
            current_value=float(errors_24h),
            seven_day_avg=round(avg_7d, 1),
            seven_day_stddev=round(stddev_7d, 1),
            delta_pct=round(delta_pct, 1),
            status="worse" if delta_pct > 20 else ("better" if delta_pct < -20 else "stable"),
            attention=attention,
        ),
    ]

    # Detect changes: new error types or frequency spikes
    changes: list[ChangeSignal] = []

    if errors_24h > avg_7d * 2 and errors_24h > 5:
        changes.append(ChangeSignal(
            category="frequency_change",
            signal=f"Error rate doubled: {errors_24h} vs avg {avg_7d:.0f}",
            evidence=f"24h: {errors_24h}, 7d avg: {avg_7d:.1f}, stddev: {stddev_7d:.1f}",
            impact="platform",
            confidence="high",
        ))

    return signals, changes


def _collect_queue_signals(db: Session, now: datetime) -> list[HealthSignal]:
    """Check pending draft queue depth."""
    pending = (
        db.query(sa_func.count(CommentDraft.id))
        .filter(CommentDraft.status == "pending")
        .scalar()
    ) or 0

    return [
        HealthSignal(
            category="queue",
            metric_name="pending_drafts",
            current_value=float(pending),
            seven_day_avg=25.0,  # reasonable default estimate
            seven_day_stddev=15.0,
            delta_pct=0.0,
            status="worse" if pending > 50 else "stable",
            attention=pending > 50,
        ),
    ]


def _collect_posting_signals(
    db: Session, now: datetime, since_24h: datetime, since_7d: datetime
) -> tuple[list[HealthSignal], list[ChangeSignal]]:
    """Posting success rate and anomaly detection."""
    # 24h posting stats
    posts_attempted = (
        db.query(sa_func.count(PostingEvent.id))
        .filter(PostingEvent.posted_at >= since_24h)
        .scalar()
    ) or 0

    posts_success = (
        db.query(sa_func.count(PostingEvent.id))
        .filter(
            PostingEvent.posted_at >= since_24h,
            PostingEvent.outcome == "success",
        )
        .scalar()
    ) or 0

    posts_failed = posts_attempted - posts_success
    success_rate = (posts_success / posts_attempted * 100) if posts_attempted > 0 else 100.0

    # 7-day daily success rates
    daily_rates = []
    for i in range(1, 8):
        day_start = now - timedelta(days=i)
        day_end = now - timedelta(days=i - 1)
        attempted = (
            db.query(sa_func.count(PostingEvent.id))
            .filter(PostingEvent.posted_at >= day_start, PostingEvent.posted_at < day_end)
            .scalar()
        ) or 0
        succeeded = (
            db.query(sa_func.count(PostingEvent.id))
            .filter(
                PostingEvent.posted_at >= day_start,
                PostingEvent.posted_at < day_end,
                PostingEvent.outcome == "success",
            )
            .scalar()
        ) or 0
        rate = (succeeded / attempted * 100) if attempted > 0 else 100.0
        daily_rates.append(rate)

    avg_rate = statistics.mean(daily_rates) if daily_rates else 100.0
    stddev_rate = statistics.stdev(daily_rates) if len(daily_rates) >= 2 else 0.0

    signals = [
        HealthSignal(
            category="posting",
            metric_name="posting_success_rate_24h",
            current_value=round(success_rate, 1),
            seven_day_avg=round(avg_rate, 1),
            seven_day_stddev=round(stddev_rate, 1),
            delta_pct=round(success_rate - avg_rate, 1),
            status="worse" if success_rate < avg_rate - 10 else "stable",
            attention=success_rate < 80,
        ),
        HealthSignal(
            category="posting",
            metric_name="posts_attempted_24h",
            current_value=float(posts_attempted),
            seven_day_avg=0.0,
            seven_day_stddev=0.0,
            delta_pct=0.0,
            status="stable",
            attention=False,
        ),
    ]

    changes: list[ChangeSignal] = []
    if posts_failed >= 3 and success_rate < 70:
        changes.append(ChangeSignal(
            category="posting_anomaly",
            signal=f"Posting failure spike: {posts_failed} failures ({success_rate:.0f}% success)",
            evidence=f"Attempted: {posts_attempted}, Failed: {posts_failed}, 7d avg rate: {avg_rate:.0f}%",
            impact="platform",
            confidence="high",
        ))

    return signals, changes


def _collect_scrape_signals(
    db: Session, now: datetime, since_24h: datetime, since_7d: datetime
) -> tuple[list[HealthSignal], list[ChangeSignal]]:
    """Scraping freshness and throughput."""
    # Count stale subreddits (>12h since last scrape)
    stale_threshold = now - timedelta(hours=12)

    stale_count = (
        db.query(sa_func.count(Subreddit.id))
        .join(ClientSubredditAssignment, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .join(Client, Client.id == ClientSubredditAssignment.client_id)
        .filter(
            Subreddit.is_active.is_(True),
            ClientSubredditAssignment.is_active.is_(True),
            Client.is_active.is_(True),
            sa_func.coalesce(
                Subreddit.last_scraped_at,
                datetime(2020, 1, 1, tzinfo=timezone.utc),
            ) < stale_threshold,
        )
        .scalar()
    ) or 0

    total_active = (
        db.query(sa_func.count(Subreddit.id))
        .join(ClientSubredditAssignment, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .filter(
            Subreddit.is_active.is_(True),
            ClientSubredditAssignment.is_active.is_(True),
        )
        .scalar()
    ) or 1

    freshness_pct = ((total_active - stale_count) / total_active * 100)

    signals = [
        HealthSignal(
            category="scraping",
            metric_name="scrape_freshness_pct",
            current_value=round(freshness_pct, 1),
            seven_day_avg=95.0,
            seven_day_stddev=5.0,
            delta_pct=round(freshness_pct - 95.0, 1),
            status="worse" if freshness_pct < 80 else "stable",
            attention=freshness_pct < 80,
        ),
        HealthSignal(
            category="scraping",
            metric_name="stale_subreddits",
            current_value=float(stale_count),
            seven_day_avg=0.0,
            seven_day_stddev=0.0,
            delta_pct=0.0,
            status="worse" if stale_count > 3 else "stable",
            attention=stale_count > 3,
        ),
    ]

    changes: list[ChangeSignal] = []
    if stale_count > 5:
        changes.append(ChangeSignal(
            category="scrape_anomaly",
            signal=f"{stale_count} subreddits stale (>12h without scrape)",
            evidence=f"Total active: {total_active}, Stale: {stale_count}, Freshness: {freshness_pct:.0f}%",
            impact="platform",
            confidence="high",
        ))

    return signals, changes


def _collect_avatar_signals(db: Session, now: datetime) -> list[HealthSignal]:
    """Avatar fleet health metrics."""
    total_active = (
        db.query(sa_func.count(Avatar.id))
        .filter(Avatar.active.is_(True))
        .scalar()
    ) or 0

    frozen_count = (
        db.query(sa_func.count(Avatar.id))
        .filter(Avatar.active.is_(True), Avatar.is_frozen.is_(True))
        .scalar()
    ) or 0

    frozen_pct = (frozen_count / total_active * 100) if total_active > 0 else 0

    return [
        HealthSignal(
            category="avatars",
            metric_name="total_active_avatars",
            current_value=float(total_active),
            seven_day_avg=float(total_active),
            seven_day_stddev=0.0,
            delta_pct=0.0,
            status="stable",
            attention=False,
        ),
        HealthSignal(
            category="avatars",
            metric_name="frozen_avatars",
            current_value=float(frozen_count),
            seven_day_avg=0.0,
            seven_day_stddev=0.0,
            delta_pct=0.0,
            status="worse" if frozen_count > 0 else "stable",
            attention=frozen_count >= 3,
        ),
        HealthSignal(
            category="avatars",
            metric_name="frozen_pct",
            current_value=round(frozen_pct, 1),
            seven_day_avg=0.0,
            seven_day_stddev=0.0,
            delta_pct=0.0,
            status="worse" if frozen_pct > 20 else "stable",
            attention=frozen_pct > 20,
        ),
    ]


def _collect_cost_snapshot(
    db: Session, now: datetime, since_24h: datetime, since_7d: datetime
) -> CostSnapshot:
    """AI cost aggregation."""
    # 24h total
    total_24h = (
        db.query(sa_func.sum(AIUsageLog.cost_usd))
        .filter(AIUsageLog.created_at >= since_24h)
        .scalar()
    ) or Decimal("0")

    # 7d total
    total_7d = (
        db.query(sa_func.sum(AIUsageLog.cost_usd))
        .filter(AIUsageLog.created_at >= since_7d)
        .scalar()
    ) or Decimal("0")

    # By operation (24h)
    op_rows = (
        db.query(
            AIUsageLog.operation,
            sa_func.sum(AIUsageLog.cost_usd).label("cost"),
        )
        .filter(AIUsageLog.created_at >= since_24h)
        .group_by(AIUsageLog.operation)
        .all()
    )
    by_operation = {row.operation: float(row.cost or 0) for row in op_rows}

    # By model (24h)
    model_rows = (
        db.query(
            AIUsageLog.model,
            sa_func.sum(AIUsageLog.cost_usd).label("cost"),
        )
        .filter(AIUsageLog.created_at >= since_24h)
        .group_by(AIUsageLog.model)
        .all()
    )
    by_model = {row.model: float(row.cost or 0) for row in model_rows}

    daily_avg = float(total_7d) / 7.0 if total_7d else 0.0

    return CostSnapshot(
        total_24h_usd=float(total_24h),
        total_7d_usd=float(total_7d),
        by_operation=by_operation,
        by_model=by_model,
        daily_avg_7d=round(daily_avg, 4),
    )


# ---------------------------------------------------------------------------
# Verdict computation
# ---------------------------------------------------------------------------


def _compute_verdict(
    signals: list[HealthSignal], data_gaps: list[str]
) -> tuple[str, list[str]]:
    """Compute overall verdict: healthy | degraded | critical.

    Rules:
    - critical: worker offline OR any signal > 3 stddev worse
    - degraded: any attention flag OR data gaps
    - healthy: everything normal
    """
    evidence: list[str] = []

    # Critical checks
    for s in signals:
        if s.metric_name == "worker_online" and s.current_value == 0:
            evidence.append("Worker offline")
            return "critical", evidence

    # Check for severe deviations (> 3 stddev)
    for s in signals:
        if s.seven_day_stddev > 0:
            deviation = abs(s.current_value - s.seven_day_avg) / s.seven_day_stddev
            if deviation > 3 and s.status == "worse":
                evidence.append(f"{s.metric_name}: {s.current_value} (3σ+ deviation)")
                return "critical", evidence

    # Degraded checks
    attention_signals = [s for s in signals if s.attention]
    if attention_signals:
        for s in attention_signals:
            evidence.append(f"{s.metric_name}: {s.current_value} (attention)")
        return "degraded", evidence

    if data_gaps:
        evidence.append(f"Data gaps: {', '.join(data_gaps)}")
        return "degraded", evidence

    evidence.append("All signals within normal range")
    return "healthy", evidence


# ---------------------------------------------------------------------------
# Snapshot creation (stores to DB)
# ---------------------------------------------------------------------------


def create_review_snapshot(db: Session) -> "ReviewSnapshot":
    """Collect all signals and persist as immutable ReviewSnapshot.

    Returns the created snapshot (attached to session).
    """
    from app.models.review_snapshot import ReviewSnapshot

    collection = collect_snapshot(db)

    snapshot = ReviewSnapshot(
        health_snapshot_json=collection.health.to_dict(),
        signals_json={"signals": [asdict(s) for s in collection.health.signals]},
        trends_json=collection.trends,
        cost_json=asdict(collection.cost),
        forecast_inputs_json=collection.forecast_inputs,
        source_availability_json=collection.source_availability,
    )

    db.add(snapshot)
    db.flush()  # Get ID without committing

    return snapshot
