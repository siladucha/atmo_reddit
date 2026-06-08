"""System Topology Timeline service.

Computes node states, timeline aggregation, and forecast points
for the 9 pipeline nodes displayed on the Admin Dashboard.
"""

from __future__ import annotations

from app.logging_config import get_logger
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import text, func, and_, case, literal_column
from sqlalchemy.orm import Session

from app.models.activity_event import ActivityEvent
from app.models.ai_usage import AIUsageLog
from app.models.comment_draft import CommentDraft
from app.models.scrape_log import ScrapeLog

logger = get_logger(__name__)


class NodeState(str, Enum):
    """Operational state of a pipeline node."""

    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    STALE = "stale"


@dataclass
class HourBucket:
    """Aggregated event counts for a single hour slot."""

    hour: int  # 0-23
    event_count: int
    error_count: int


@dataclass
class NodeStatus:
    """Complete status snapshot for a single pipeline node."""

    node_id: str
    label: str
    state: NodeState
    last_run_at: datetime | None
    last_duration_ms: int | None
    last_error: str | None
    forecast_point: str | None  # ISO 8601 timestamp or descriptive label
    forecast_relative: str | None  # "in 45 min", "overdue", etc.
    is_overdue: bool
    timeline: list[HourBucket] = field(default_factory=list)  # 24 items


@dataclass
class TopologyData:
    """Full topology snapshot returned by the service."""

    nodes: list[NodeStatus]
    current_hour: int
    generated_at: datetime


# Static schedule configuration for forecast calculations.
# Maps node_id to schedule type and parameters.
SCHEDULE_CONFIG: dict[str, dict] = {
    "scrape": {"type": "interval", "seconds": 60},
    "score": {"type": "cron", "hours": [8, 14], "minutes": 0},
    "generate": {"type": "cron", "hours": [8, 14], "minutes": 0, "offset_minutes": 15},
    "review": {"type": "human", "label": "human-driven"},
    "reddit_api": {"type": "interval", "seconds": 60},
    "llm_api": {"type": "cron", "hours": [8, 14], "minutes": 0},
    "database": {"type": "always", "label": "always available"},
    "queue": {"type": "interval", "seconds": 60},
    "safety": {"type": "event", "label": "event-driven"},
}


NODE_LABELS = {
    "scrape": "Scraping",
    "score": "Scoring",
    "generate": "Generation",
    "review": "Review Queue",
    "reddit_api": "Reddit API",
    "llm_api": "LLM API",
    "database": "Database",
    "queue": "Task Queue",
    "safety": "Safety",
}


def get_topology_data(db: Session) -> TopologyData:
    """Main entry point. Computes all topology data in batched queries.

    Orchestrates calls to compute_node_states, aggregate_timeline, and
    calculate_forecasts, then assembles a complete TopologyData snapshot
    for all 9 pipeline nodes.
    """
    now = datetime.now(timezone.utc)

    # --- Compute node states (with graceful degradation) ---
    try:
        states = compute_node_states(db)
    except Exception:
        logger.exception("topology.compute_node_states_failed")
        states = {node_id: NodeState.ERROR for node_id in NODE_LABELS}

    # --- Aggregate timeline (with graceful degradation) ---
    try:
        timeline = aggregate_timeline(db)
    except Exception:
        logger.exception("topology.aggregate_timeline_failed")
        timeline = {
            node_id: [HourBucket(hour=h, event_count=0, error_count=0) for h in range(24)]
            for node_id in NODE_LABELS
        }

    # --- Calculate forecasts (with graceful degradation) ---
    try:
        forecasts = calculate_forecasts(db)
    except Exception:
        logger.exception("topology.calculate_forecasts_failed")
        forecasts = {node_id: (None, None, False) for node_id in NODE_LABELS}

    # --- Batch query: last_run_at and last_duration_ms per node ---
    last_run_info = _query_last_run_info(db, now)

    # --- Batch query: last_error per node ---
    last_errors = _query_last_errors(db, now)

    # --- Assemble NodeStatus list for all 9 nodes ---
    nodes: list[NodeStatus] = []
    for node_id, label in NODE_LABELS.items():
        forecast_point, forecast_relative, is_overdue = forecasts.get(
            node_id, (None, None, False)
        )
        run_at, duration_ms = last_run_info.get(node_id, (None, None))

        nodes.append(
            NodeStatus(
                node_id=node_id,
                label=label,
                state=states.get(node_id, NodeState.IDLE),
                last_run_at=run_at,
                last_duration_ms=duration_ms,
                last_error=last_errors.get(node_id),
                forecast_point=forecast_point,
                forecast_relative=forecast_relative,
                is_overdue=is_overdue,
                timeline=timeline.get(
                    node_id,
                    [HourBucket(hour=h, event_count=0, error_count=0) for h in range(24)],
                ),
            )
        )

    return TopologyData(
        nodes=nodes,
        current_hour=now.hour,
        generated_at=now,
    )


def _query_last_run_info(
    db: Session, now: datetime
) -> dict[str, tuple[datetime | None, int | None]]:
    """Query latest activity timestamp and duration for each node in batch.

    Returns dict mapping node_id to (last_run_at, last_duration_ms).
    """
    result: dict[str, tuple[datetime | None, int | None]] = {}

    # --- Scraping: from scrape_log ---
    scrape_latest = (
        db.query(ScrapeLog.scraped_at, ScrapeLog.duration_ms)
        .order_by(ScrapeLog.scraped_at.desc())
        .first()
    )
    if scrape_latest:
        result["scrape"] = (scrape_latest.scraped_at, scrape_latest.duration_ms)

    # --- Score, Generate, Heartbeat (queue), Safety: from activity_events ---
    event_type_to_node = {
        "score": "score",
        "generate": "generate",
        "heartbeat": "queue",
        "safety": "safety",
    }

    # Use a subquery approach: get latest event per type
    for event_type, node_id in event_type_to_node.items():
        latest_event = (
            db.query(ActivityEvent.created_at)
            .filter(ActivityEvent.event_type == event_type)
            .order_by(ActivityEvent.created_at.desc())
            .first()
        )
        if latest_event:
            # ActivityEvent doesn't have duration_ms, so None
            result[node_id] = (latest_event.created_at, None)

    # --- LLM API: from ai_usage_log ---
    llm_latest = (
        db.query(AIUsageLog.created_at, AIUsageLog.duration_ms)
        .order_by(AIUsageLog.created_at.desc())
        .first()
    )
    if llm_latest:
        result["llm_api"] = (llm_latest.created_at, llm_latest.duration_ms)

    # --- Reddit API: derived from scrape_log (same as scraping) ---
    if scrape_latest:
        result["reddit_api"] = (scrape_latest.scraped_at, scrape_latest.duration_ms)

    # --- Review Queue: from comment_drafts (latest created_at) ---
    latest_draft = (
        db.query(func.max(CommentDraft.created_at)).scalar()
    )
    if latest_draft:
        result["review"] = (latest_draft, None)

    # --- Database: always now (it's always running) ---
    result["database"] = (now, None)

    return result


def _query_last_errors(db: Session, now: datetime) -> dict[str, str | None]:
    """Query the latest error message for each node.

    Returns dict mapping node_id to last error string (or None if no recent errors).
    """
    result: dict[str, str | None] = {}
    error_window = timedelta(hours=24)
    cutoff = now - error_window

    # --- Scraping / Reddit API: from scrape_log.errors ---
    scrape_error = (
        db.query(ScrapeLog.errors)
        .filter(
            ScrapeLog.scraped_at >= cutoff,
            ScrapeLog.errors.isnot(None),
        )
        .order_by(ScrapeLog.scraped_at.desc())
        .first()
    )
    if scrape_error:
        result["scrape"] = scrape_error.errors
        result["reddit_api"] = scrape_error.errors

    # --- Score, Generate, Safety: from activity_events with error in metadata ---
    for event_type, node_id in [
        ("score", "score"),
        ("generate", "generate"),
        ("safety", "safety"),
    ]:
        error_event = (
            db.query(ActivityEvent.message)
            .filter(
                ActivityEvent.event_type == event_type,
                ActivityEvent.created_at >= cutoff,
                ActivityEvent.event_metadata.has_key("error"),
            )
            .order_by(ActivityEvent.created_at.desc())
            .first()
        )
        if error_event:
            result[node_id] = error_event.message

    # --- LLM API: from ai_usage_log with zero tokens (error indicator) ---
    llm_error = (
        db.query(AIUsageLog.operation)
        .filter(
            AIUsageLog.created_at >= cutoff,
            AIUsageLog.cost_usd == 0,
            AIUsageLog.input_tokens == 0,
            AIUsageLog.output_tokens == 0,
        )
        .order_by(AIUsageLog.created_at.desc())
        .first()
    )
    if llm_error:
        result["llm_api"] = f"LLM API error in operation: {llm_error.operation}"

    # --- Task Queue: from activity_events heartbeat with error ---
    heartbeat_error = (
        db.query(ActivityEvent.message)
        .filter(
            ActivityEvent.event_type == "heartbeat",
            ActivityEvent.created_at >= cutoff,
            ActivityEvent.event_metadata.has_key("error"),
        )
        .order_by(ActivityEvent.created_at.desc())
        .first()
    )
    if heartbeat_error:
        result["queue"] = heartbeat_error.message

    # --- Database: no persistent error source (checked live in compute_node_states) ---
    # --- Review Queue: no error concept (just pending count) ---

    return result


def compute_node_states(db: Session) -> dict[str, NodeState]:
    """Compute current state for all 9 pipeline nodes.

    Uses batched queries where possible to minimize database round-trips.
    Each node's state is determined by staleness thresholds, error rates,
    or specific conditions as defined in the requirements.
    """
    now = datetime.now(timezone.utc)
    states: dict[str, NodeState] = {}

    # --- Thresholds ---
    scrape_staleness = timedelta(hours=6)
    score_staleness = timedelta(hours=2)
    generate_staleness = timedelta(hours=4)
    heartbeat_staleness = timedelta(minutes=5)
    error_window = timedelta(minutes=15)
    reddit_api_error_threshold = 0.05  # 5%
    llm_api_error_threshold = 0.10  # 10%
    review_pending_threshold = 50
    review_age_threshold = timedelta(hours=24)
    safety_window = timedelta(hours=1)

    # --- Batch query: latest activity_events by type ---
    # Fetch latest timestamps for score, generate, heartbeat, safety in one query
    event_types_needed = ["score", "generate", "heartbeat", "safety"]
    latest_events = (
        db.query(
            ActivityEvent.event_type,
            func.max(ActivityEvent.created_at).label("latest"),
        )
        .filter(ActivityEvent.event_type.in_(event_types_needed))
        .group_by(ActivityEvent.event_type)
        .all()
    )
    latest_by_type: dict[str, datetime] = {
        row.event_type: row.latest for row in latest_events
    }

    # --- 1. Scraping node: stale if no scrape_log entries within 6h ---
    latest_scrape = (
        db.query(func.max(ScrapeLog.scraped_at)).scalar()
    )
    if latest_scrape is None or (now - latest_scrape) > scrape_staleness:
        states["scrape"] = NodeState.STALE
    else:
        states["scrape"] = NodeState.IDLE

    # --- 2. Scoring node: stale if no score events within 2h after last scrape ---
    latest_score = latest_by_type.get("score")
    # Scoring staleness is relative to last scrape completion
    score_deadline = (
        (latest_scrape + score_staleness) if latest_scrape else None
    )
    if latest_score is None and latest_scrape is not None and now > (latest_scrape + score_staleness):
        states["score"] = NodeState.STALE
    elif latest_score is not None and score_deadline is not None and latest_score < latest_scrape and now > score_deadline:
        # Last score was before last scrape and deadline has passed
        states["score"] = NodeState.STALE
    elif latest_score is None and latest_scrape is None:
        states["score"] = NodeState.IDLE
    else:
        states["score"] = NodeState.IDLE

    # --- 3. Generation node: stale if no generate events within 4h after last scoring ---
    latest_generate = latest_by_type.get("generate")
    if latest_score is not None:
        generate_deadline = latest_score + generate_staleness
        if latest_generate is None and now > generate_deadline:
            states["generate"] = NodeState.STALE
        elif latest_generate is not None and latest_generate < latest_score and now > generate_deadline:
            states["generate"] = NodeState.STALE
        else:
            states["generate"] = NodeState.IDLE
    else:
        # No scoring events at all — generation can't be stale without scoring
        states["generate"] = NodeState.IDLE

    # --- 4. Review Queue: warning if >50 pending OR oldest pending >24h ---
    review_stats = (
        db.query(
            func.count(CommentDraft.id).label("pending_count"),
            func.min(CommentDraft.created_at).label("oldest_pending"),
        )
        .filter(CommentDraft.status == "pending")
        .one()
    )
    pending_count = review_stats.pending_count or 0
    oldest_pending = review_stats.oldest_pending

    if pending_count > review_pending_threshold:
        states["review"] = NodeState.WARNING
    elif oldest_pending is not None and (now - oldest_pending) > review_age_threshold:
        states["review"] = NodeState.WARNING
    else:
        states["review"] = NodeState.IDLE

    # --- 5. Reddit API: error rate >5% in last 15 min ---
    # Count activity_events with event_type containing scrape-related errors
    # and scrape_log entries with errors in the last 15 min
    error_window_start = now - error_window

    # Count total scrape_log entries in window
    reddit_total = (
        db.query(func.count(ScrapeLog.id))
        .filter(ScrapeLog.scraped_at >= error_window_start)
        .scalar()
    ) or 0

    # Count scrape_log entries with errors in window
    reddit_errors = (
        db.query(func.count(ScrapeLog.id))
        .filter(
            and_(
                ScrapeLog.scraped_at >= error_window_start,
                ScrapeLog.errors.isnot(None),
            )
        )
        .scalar()
    ) or 0

    if reddit_total > 0 and (reddit_errors / reddit_total) > reddit_api_error_threshold:
        states["reddit_api"] = NodeState.ERROR
    else:
        states["reddit_api"] = NodeState.IDLE

    # --- 6. LLM API: error rate >10% in last 15 min ---
    # Errors indicated by zero tokens (cost_usd=0, input_tokens=0, output_tokens=0)
    llm_total = (
        db.query(func.count(AIUsageLog.id))
        .filter(AIUsageLog.created_at >= error_window_start)
        .scalar()
    ) or 0

    llm_errors = (
        db.query(func.count(AIUsageLog.id))
        .filter(
            and_(
                AIUsageLog.created_at >= error_window_start,
                AIUsageLog.cost_usd == 0,
                AIUsageLog.input_tokens == 0,
                AIUsageLog.output_tokens == 0,
            )
        )
        .scalar()
    ) or 0

    if llm_total > 0 and (llm_errors / llm_total) > llm_api_error_threshold:
        states["llm_api"] = NodeState.ERROR
    else:
        states["llm_api"] = NodeState.IDLE

    # --- 7. Database: health check via SELECT 1 ---
    try:
        db.execute(text("SELECT 1"))
        states["database"] = NodeState.IDLE
    except Exception:
        logger.error("topology.db_health_failed")
        states["database"] = NodeState.ERROR

    # --- 8. Task Queue: no heartbeat within 5 min ---
    latest_heartbeat = latest_by_type.get("heartbeat")
    if latest_heartbeat is None or (now - latest_heartbeat) > heartbeat_staleness:
        states["queue"] = NodeState.STALE
    else:
        states["queue"] = NodeState.IDLE

    # --- 9. Safety: any safety events in last 1h → warning ---
    latest_safety = latest_by_type.get("safety")
    if latest_safety is not None and (now - latest_safety) <= safety_window:
        states["safety"] = NodeState.WARNING
    else:
        states["safety"] = NodeState.IDLE

    return states


def aggregate_timeline(db: Session, hours: int = 24) -> dict[str, list[HourBucket]]:
    """Single SQL query aggregating events per node per hour.

    Executes:
    - One query on activity_events covering score, generate, heartbeat, safety
    - Supplementary query on scrape_log for Scraping node
    - Supplementary query on ai_usage_log for LLM API node
    - Supplementary query on comment_drafts for Review Queue node
    - Reddit API derived from scrape_log errors

    Returns exactly 24 HourBuckets per node, filling missing hours with zeros.
    Logs a performance warning if total query time exceeds 100ms.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    # All node_ids that need timelines
    all_node_ids = [
        "scrape", "score", "generate", "review",
        "reddit_api", "llm_api", "database", "queue", "safety",
    ]

    # Initialize result with empty buckets for all nodes
    result: dict[str, list[HourBucket]] = {}
    for node_id in all_node_ids:
        result[node_id] = [HourBucket(hour=h, event_count=0, error_count=0) for h in range(24)]

    # Map event_type to node_id for activity_events
    event_type_to_node = {
        "score": "score",
        "generate": "generate",
        "heartbeat": "queue",
        "safety": "safety",
    }

    start_time = time.perf_counter()

    # --- Query 1: activity_events (single query for all event types) ---
    # Uses ix_activity_events_type_created index
    hour_trunc = func.date_trunc("hour", func.timezone("UTC", ActivityEvent.created_at))
    hour_extract = func.extract("hour", hour_trunc)
    activity_rows = (
        db.query(
            ActivityEvent.event_type,
            hour_extract.label("bucket_hour"),
            func.count().label("event_count"),
            func.count(
                case(
                    (ActivityEvent.event_metadata.has_key("error"), literal_column("1")),
                    else_=None,
                )
            ).label("error_count"),
        )
        .filter(
            ActivityEvent.event_type.in_(list(event_type_to_node.keys())),
            ActivityEvent.created_at >= cutoff,
        )
        .group_by(ActivityEvent.event_type, hour_trunc)
        .all()
    )

    for row in activity_rows:
        node_id = event_type_to_node.get(row.event_type)
        if node_id is None:
            continue
        bucket_hour = int(row.bucket_hour)
        result[node_id][bucket_hour] = HourBucket(
            hour=bucket_hour,
            event_count=row.event_count,
            error_count=row.error_count,
        )

    # --- Query 2: scrape_log for Scraping node ---
    scrape_hour_trunc = func.date_trunc("hour", func.timezone("UTC", ScrapeLog.scraped_at))
    scrape_hour_extract = func.extract("hour", scrape_hour_trunc)
    scrape_rows = (
        db.query(
            scrape_hour_extract.label("bucket_hour"),
            func.count().label("event_count"),
            func.count(
                case(
                    (ScrapeLog.errors.isnot(None), literal_column("1")),
                    else_=None,
                )
            ).label("error_count"),
        )
        .filter(ScrapeLog.scraped_at >= cutoff)
        .group_by(scrape_hour_trunc)
        .all()
    )

    for row in scrape_rows:
        bucket_hour = int(row.bucket_hour)
        result["scrape"][bucket_hour] = HourBucket(
            hour=bucket_hour,
            event_count=row.event_count,
            error_count=row.error_count,
        )

    # --- Query 3: scrape_log errors for Reddit API node ---
    # Reddit API timeline counts error entries from scrape_log
    reddit_api_rows = (
        db.query(
            scrape_hour_extract.label("bucket_hour"),
            func.count().label("event_count"),
            func.count(
                case(
                    (ScrapeLog.errors.isnot(None), literal_column("1")),
                    else_=None,
                )
            ).label("error_count"),
        )
        .filter(ScrapeLog.scraped_at >= cutoff)
        .group_by(scrape_hour_trunc)
        .all()
    )

    for row in reddit_api_rows:
        bucket_hour = int(row.bucket_hour)
        result["reddit_api"][bucket_hour] = HourBucket(
            hour=bucket_hour,
            event_count=row.event_count,
            error_count=row.error_count,
        )

    # --- Query 4: ai_usage_log for LLM API node ---
    ai_hour_trunc = func.date_trunc("hour", func.timezone("UTC", AIUsageLog.created_at))
    ai_hour_extract = func.extract("hour", ai_hour_trunc)
    ai_rows = (
        db.query(
            ai_hour_extract.label("bucket_hour"),
            func.count().label("event_count"),
            func.count(
                case(
                    (
                        and_(
                            AIUsageLog.cost_usd == 0,
                            AIUsageLog.input_tokens == 0,
                            AIUsageLog.output_tokens == 0,
                        ),
                        literal_column("1"),
                    ),
                    else_=None,
                )
            ).label("error_count"),
        )
        .filter(AIUsageLog.created_at >= cutoff)
        .group_by(ai_hour_trunc)
        .all()
    )

    for row in ai_rows:
        bucket_hour = int(row.bucket_hour)
        result["llm_api"][bucket_hour] = HourBucket(
            hour=bucket_hour,
            event_count=row.event_count,
            error_count=row.error_count,
        )

    # --- Query 5: comment_drafts for Review Queue node ---
    drafts_hour_trunc = func.date_trunc("hour", func.timezone("UTC", CommentDraft.created_at))
    drafts_hour_extract = func.extract("hour", drafts_hour_trunc)
    drafts_rows = (
        db.query(
            drafts_hour_extract.label("bucket_hour"),
            func.count().label("event_count"),
        )
        .filter(CommentDraft.created_at >= cutoff)
        .group_by(drafts_hour_trunc)
        .all()
    )

    for row in drafts_rows:
        bucket_hour = int(row.bucket_hour)
        result["review"][bucket_hour] = HourBucket(
            hour=bucket_hour,
            event_count=row.event_count,
            error_count=0,
        )

    # --- Database node: always 24 zero buckets (already initialized) ---

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    if elapsed_ms > 100:
        logger.warning("topology.slow_query duration_ms=%d", int(elapsed_ms))

    return result


def _next_cron_occurrence(now: datetime, hours: list[int], minutes: int = 0, offset_minutes: int = 0) -> datetime:
    """Find next occurrence of any of the specified hours:minutes in UTC.

    Adds offset_minutes for generation node.
    Must be strictly in the future (forecast > now).
    """
    candidates: list[datetime] = []
    for h in hours:
        # Try today
        candidate = now.replace(hour=h, minute=minutes, second=0, microsecond=0)
        candidate = candidate + timedelta(minutes=offset_minutes)
        if candidate > now:
            candidates.append(candidate)
        # Try tomorrow
        candidate_tomorrow = (now + timedelta(days=1)).replace(
            hour=h, minute=minutes, second=0, microsecond=0
        )
        candidate_tomorrow = candidate_tomorrow + timedelta(minutes=offset_minutes)
        candidates.append(candidate_tomorrow)

    return min(candidates)


def _format_relative_time(delta: timedelta) -> str:
    """Convert a timedelta to a human-readable relative time string.

    Positive delta → "in X min", "in Xh", "in Xh Y min"
    Negative delta → "overdue"
    """
    total_seconds = delta.total_seconds()
    if total_seconds < 0:
        return "overdue"

    total_minutes = int(total_seconds // 60)
    if total_minutes == 0:
        return "in <1 min"

    hours = total_minutes // 60
    mins = total_minutes % 60

    if hours == 0:
        return f"in {mins} min"
    elif mins == 0:
        return f"in {hours}h"
    else:
        return f"in {hours}h {mins} min"


def calculate_forecasts(db: Session) -> dict[str, tuple[str | None, str | None, bool]]:
    """Calculate next expected execution for each node.

    Returns:
        Dict mapping node_id to (forecast_point, forecast_relative, is_overdue).
        - forecast_point: ISO 8601 timestamp or descriptive label
        - forecast_relative: human-readable relative time or None
        - is_overdue: True if forecast is in the past
    """
    from app.models.subreddit import Subreddit, ClientSubredditAssignment
    from app.models.client import Client

    now = datetime.now(timezone.utc)
    forecasts: dict[str, tuple[str | None, str | None, bool]] = {}

    # --- Scraping: earliest subreddit due based on last_scraped_at + default 6h ---
    DEFAULT_SCRAPE_INTERVAL_HOURS = 6

    # Find the earliest subreddit due for scraping
    earliest_due = (
        db.query(Subreddit.last_scraped_at)
        .join(ClientSubredditAssignment, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .join(Client, Client.id == ClientSubredditAssignment.client_id)
        .filter(
            Subreddit.is_active.is_(True),
            ClientSubredditAssignment.is_active.is_(True),
            Client.is_active.is_(True),
            Subreddit.last_scraped_at.isnot(None),
        )
        .order_by(Subreddit.last_scraped_at.asc())
        .first()
    )

    if earliest_due and earliest_due.last_scraped_at:
        scrape_forecast = earliest_due.last_scraped_at + timedelta(hours=DEFAULT_SCRAPE_INTERVAL_HOURS)
        is_overdue = scrape_forecast <= now
        delta = scrape_forecast - now
        relative = _format_relative_time(delta) if not is_overdue else "overdue"
        forecasts["scrape"] = (scrape_forecast.isoformat(), relative, is_overdue)
    else:
        # No subreddits with last_scraped_at — next tick in 60s
        scrape_forecast = now + timedelta(seconds=60)
        forecasts["scrape"] = (scrape_forecast.isoformat(), "in 1 min", False)

    # --- Scoring: next occurrence of 08:00 or 14:00 UTC ---
    score_config = SCHEDULE_CONFIG["score"]
    score_forecast = _next_cron_occurrence(now, score_config["hours"], score_config["minutes"])
    score_delta = score_forecast - now
    forecasts["score"] = (score_forecast.isoformat(), _format_relative_time(score_delta), False)

    # --- Generation: next AI pipeline run + 15 min offset ---
    gen_config = SCHEDULE_CONFIG["generate"]
    gen_forecast = _next_cron_occurrence(
        now, gen_config["hours"], gen_config["minutes"], gen_config["offset_minutes"]
    )
    gen_delta = gen_forecast - now
    forecasts["generate"] = (gen_forecast.isoformat(), _format_relative_time(gen_delta), False)

    # --- Review Queue: human-driven label ---
    forecasts["review"] = ("human-driven", None, False)

    # --- Reddit API: next scheduled occurrence (same as scoring — 08:00 or 14:00 UTC) ---
    reddit_api_config = SCHEDULE_CONFIG["reddit_api"]
    # reddit_api is interval-based (60s) — use queue_tick logic
    # But per task description: "Reddit API / LLM API: next scheduled occurrence (same as scoring)"
    reddit_forecast = _next_cron_occurrence(now, [8, 14], 0)
    reddit_delta = reddit_forecast - now
    forecasts["reddit_api"] = (reddit_forecast.isoformat(), _format_relative_time(reddit_delta), False)

    # --- LLM API: next scheduled occurrence (same as scoring — 08:00 or 14:00 UTC) ---
    llm_config = SCHEDULE_CONFIG["llm_api"]
    llm_forecast = _next_cron_occurrence(now, llm_config["hours"], llm_config["minutes"])
    llm_delta = llm_forecast - now
    forecasts["llm_api"] = (llm_forecast.isoformat(), _format_relative_time(llm_delta), False)

    # --- Database: always available label ---
    forecasts["database"] = ("always available", None, False)

    # --- Task Queue: last heartbeat + 60s interval ---
    latest_heartbeat = (
        db.query(func.max(ActivityEvent.created_at))
        .filter(ActivityEvent.event_type == "heartbeat")
        .scalar()
    )

    if latest_heartbeat:
        queue_forecast = latest_heartbeat + timedelta(seconds=60)
        is_overdue = queue_forecast <= now
        delta = queue_forecast - now
        relative = _format_relative_time(delta) if not is_overdue else "overdue"
        forecasts["queue"] = (queue_forecast.isoformat(), relative, is_overdue)
    else:
        # No heartbeat recorded — next expected in 60s
        queue_forecast = now + timedelta(seconds=60)
        forecasts["queue"] = (queue_forecast.isoformat(), "in 1 min", False)

    # --- Safety: event-driven label ---
    forecasts["safety"] = ("event-driven", None, False)

    return forecasts
