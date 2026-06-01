# Design Document: Quality Sentinel

## Overview

Quality Sentinel is a unified quality control subsystem that closes the feedback loop between posting outcomes and pipeline decisions. It tracks karma, removals, and replies after posting; computes effectiveness scores for decision combinations; builds multi-level trends; alerts operators on degradation; and auto-adapts system behavior.

## Architecture

The system consists of three subsystems integrated into the existing Celery + PostgreSQL infrastructure:

**Data flow:**
```
Posted Comment → Outcome Tracker (Celery, every 4h)
  → Reddit API (karma check) → Outcome Record (PostgreSQL)
  → Learning Engine (on 48h snapshot) → Effectiveness Scores (upsert)
  → Trend Calculator (daily 03:00) → KPI Snapshots + Trends
  → Alert Engine (after trends) → Risk Scores + Alerts
  → Dashboard (pre-computed, /admin/quality)
```

Integration points with existing system:
- **CommentDraft** (status=posted) triggers outcome tracking
- **Celery Beat** schedules karma checks, trend computation, alert evaluation
- **Redis** provides distributed locks for batch processing
- **PostingEvent** provides posting timestamp and metadata
- **EPG slots** provide timing and selection context for attribution

---

## Components and Interfaces

### 1. Outcome Record Model (`models/outcome_record.py`)

Stores post-posting outcome data linked to the original draft.

```python
class OutcomeRecord(Base):
    __tablename__ = "outcome_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    draft_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("comment_drafts.id"), unique=True, nullable=False)
    avatar_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    subreddit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("subreddits.id"), nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Karma snapshots
    karma_4h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    karma_4h_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    karma_24h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    karma_24h_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    karma_48h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    karma_48h_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

```python
    # Removal detection
    removal_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    removal_detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removal_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # mod_removed | author_deleted | unknown

    # Reply detection
    reply_count: Mapped[int] = mapped_column(Integer, default=0)
    has_op_reply: Mapped[bool] = mapped_column(Boolean, default=False)

    # Attribution context (denormalized for query performance)
    comment_approach: Mapped[str | None] = mapped_column(String(50), nullable=True)
    strategy_pattern: Mapped[str | None] = mapped_column(String(100), nullable=True)
    timing_bucket: Mapped[str | None] = mapped_column(String(20), nullable=True)  # e.g., "08-10", "10-12"
    thread_score_at_selection: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Scheduling state
    next_check_type: Mapped[str | None] = mapped_column(String(10), nullable=True)  # 4h | 24h | 48h | complete
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

**Indexes:**
```python
__table_args__ = (
    Index("ix_outcome_records_next_check", "next_check_type", "next_check_at"),
    Index("ix_outcome_records_avatar_posted", "avatar_id", "posted_at"),
    Index("ix_outcome_records_subreddit_posted", "subreddit_id", "posted_at"),
    Index("ix_outcome_records_client_posted", "client_id", "posted_at"),
)
```

### 2. Effectiveness Score Model (`models/effectiveness_score.py`)

Stores computed effectiveness for decision combinations. Updated in-place (upsert).

```python
class EffectivenessScore(Base):
    __tablename__ = "effectiveness_scores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    combo_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # combo_type values: approach_x_subreddit, avatar_x_subreddit, timing_x_subreddit, strategy_x_client
    combo_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    # combo_key format: "{combo_type}:{entity1_id}:{entity2_id}"

    score: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0 - 1.0
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    positive_count: Mapped[int] = mapped_column(Integer, default=0)  # karma > 0
    negative_count: Mapped[int] = mapped_column(Integer, default=0)  # karma < 0
    removal_count: Mapped[int] = mapped_column(Integer, default=0)
    total_karma: Mapped[int] = mapped_column(Integer, default=0)
    avg_karma: Mapped[float] = mapped_column(Float, default=0.0)

    last_outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_effectiveness_combo_type", "combo_type"),
        Index("ix_effectiveness_score_value", "combo_type", "score"),
    )
```

### 3. KPI Snapshot Model (`models/kpi_snapshot.py`)

Stores daily KPI measurements at all observation levels.

```python
class KPISnapshot(Base):
    __tablename__ = "kpi_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    observation_level: Mapped[str] = mapped_column(String(20), nullable=False)  # system | client | subreddit | avatar
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # NULL for system level
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_type: Mapped[str] = mapped_column(String(10), default="daily")  # daily | monthly

    # KPI values
    avg_karma: Mapped[float | None] = mapped_column(Float, nullable=True)
    removal_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0.0 - 1.0
    reply_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0.0 - 1.0
    positive_outcome_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # karma > 0
    volume: Mapped[int] = mapped_column(Integer, default=0)  # number of posts

    # Computed trends (updated by trend calculator)
    trend_7d_karma: Mapped[float | None] = mapped_column(Float, nullable=True)  # slope
    trend_30d_karma: Mapped[float | None] = mapped_column(Float, nullable=True)
    trend_7d_removal: Mapped[float | None] = mapped_column(Float, nullable=True)
    trend_30d_removal: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("observation_level", "entity_id", "snapshot_date", "period_type", name="uq_kpi_snapshot"),
        Index("ix_kpi_level_entity_date", "observation_level", "entity_id", "snapshot_date"),
    )
```

### 4. Quality Alert Model (`models/quality_alert.py`)

Stores operator alerts with deduplication and acknowledgment.

```python
class QualityAlert(Base):
    __tablename__ = "quality_alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # alert_type values: risk_warning, risk_critical, correlation_subreddit_hostile,
    #                     high_rejection_rate, high_removal_rate
    severity: Mapped[str] = mapped_column(String(20), nullable=False)  # warning | critical
    observation_level: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    entity_name: Mapped[str | None] = mapped_column(String(200), nullable=True)  # denormalized for display

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    is_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 90 days from creation

    __table_args__ = (
        Index("ix_alerts_unacknowledged", "is_acknowledged", "created_at"),
        Index("ix_alerts_entity", "observation_level", "entity_id", "created_at"),
    )
```

### 5. Outcome Tracker Service (`services/outcome_tracker.py`)

Core service for collecting karma, detecting removals, and detecting replies.

```python
class OutcomeTracker:
    """Tracks post-posting outcomes via Reddit API checks."""

    def create_outcome_record(self, db: Session, draft: CommentDraft) -> OutcomeRecord:
        """Create an outcome record when a draft transitions to 'posted'.

        Extracts attribution context from the draft, EPG slot, and active strategy.
        Schedules first check at posted_at + 4 hours.
        """

    def get_pending_checks(self, db: Session, batch_size: int = 50) -> list[OutcomeRecord]:
        """Get outcome records due for their next check.

        Ordered by priority: 4h > 24h > 48h.
        Limited to batch_size per execution.
        """

    def execute_karma_check(self, db: Session, record: OutcomeRecord, reddit_client) -> None:
        """Execute a single karma check for an outcome record.

        1. Fetch comment via reddit_comment_id
        2. Read current score (karma)
        3. Check visibility (removal detection)
        4. Count replies (on 24h/48h checks)
        5. Update the appropriate snapshot field
        6. Schedule next check or mark as complete
        """

    def detect_removal(self, comment) -> tuple[bool, str]:
        """Determine if a comment has been removed.

        Returns (is_removed, removal_type).
        removal_type: 'mod_removed' | 'author_deleted' | 'unknown'

        Detection logic:
        - comment.body == '[removed]' → mod_removed
        - comment.body == '[deleted]' → author_deleted
        - comment not found (404) → unknown
        """

    def compute_timing_bucket(self, posted_at: datetime) -> str:
        """Convert posting time to a 2-hour bucket string.

        e.g., 09:30 → '08-10', 14:15 → '14-16'
        """
```

### 6. Learning Engine Service (`services/learning_engine.py`)

Computes effectiveness scores and provides adaptation weights.

```python
class LearningEngine:
    """Computes effectiveness scores and provides adaptation weights."""

    KARMA_WEIGHT = 1.0
    REMOVAL_PENALTY = 0.8
    REPLY_BONUS = 0.3
    REJECTION_WEIGHT = 0.5
    STRATEGY_CHANGE_WEIGHT = 0.3
    MIN_SAMPLES = 5

    def compute_effectiveness_score(self, outcomes: list[OutcomeRecord]) -> float:
        """Compute normalized effectiveness score (0.0 - 1.0) from outcomes.

        Formula:
        raw_score = (
            sum(normalize_karma(o.karma_48h or o.karma_24h or o.karma_4h))
            - REMOVAL_PENALTY * removal_count
            + REPLY_BONUS * sum(o.reply_count)
        ) / sample_count

        Normalized to 0.0-1.0 via sigmoid-like scaling.
        """

    def update_effectiveness_scores(self, db: Session, outcome: OutcomeRecord) -> None:
        """Recompute all effectiveness scores affected by a new outcome.

        Generates combo keys:
        - approach_x_subreddit:{approach}:{subreddit_id}
        - avatar_x_subreddit:{avatar_id}:{subreddit_id}
        - timing_x_subreddit:{timing_bucket}:{subreddit_id}
        - strategy_x_client:{strategy_pattern}:{client_id}

        For each combo key: upsert EffectivenessScore with updated stats.
        """

    def get_adaptation_weights(
        self, db: Session, combo_type: str, entity_id: str, subreddit_id: uuid.UUID
    ) -> dict[str, float]:
        """Get effectiveness weights for pipeline adaptation.

        Returns dict mapping entity values to their effectiveness scores.
        Only returns scores where sample_count >= MIN_SAMPLES.
        Returns empty dict if auto_adaptation_enabled is False.
        """

    def record_rejection_signal(self, db: Session, draft: CommentDraft) -> None:
        """Record a draft rejection as a negative signal.

        Updates effectiveness scores for the thread's subreddit and
        the avatar that was assigned.
        """

    def record_strategy_change_signal(self, db: Session, client_id: uuid.UUID, old_strategy: str) -> None:
        """Record a strategy change as a weak negative signal for the old strategy."""

    def record_epg_reassignment_signal(self, db: Session, slot_id: uuid.UUID) -> None:
        """Record an EPG slot reassignment as a weak negative signal."""
```

### 7. Trend Calculator Service (`services/trend_calculator.py`)

Computes daily KPI snapshots and linear regression trends.

```python
import numpy as np
from datetime import date, timedelta

class TrendCalculator:
    """Computes KPI snapshots and trend slopes at all observation levels."""

    TREND_THRESHOLDS = {
        "karma": 0.5,      # slope threshold for improving/degrading
        "removal": 0.02,   # 2% change per day
        "reply": 0.01,     # 1% change per day
    }

    def collect_daily_snapshots(self, db: Session, snapshot_date: date) -> int:
        """Collect KPI snapshots for all entities at all levels.

        Levels: system, client, subreddit, avatar.
        Queries outcome_records for the given date range.
        Returns count of snapshots created.
        """

    def compute_trends(self, db: Session, snapshot_date: date) -> None:
        """Compute 7d and 30d linear regression slopes for all KPIs.

        Uses numpy polyfit (degree=1) on the last N daily snapshots.
        Requires minimum 5 points for 7d, 14 points for 30d.
        Updates trend fields on the latest KPI snapshot.
        """

    def _linear_regression_slope(self, values: list[float]) -> float:
        """Compute slope of linear regression through values.

        Uses numpy.polyfit with degree 1.
        Returns slope (change per day).
        """
        if len(values) < 2:
            return 0.0
        x = np.arange(len(values), dtype=float)
        coeffs = np.polyfit(x, values, 1)
        return float(coeffs[0])

    def classify_trend(self, slope: float, kpi_name: str) -> str:
        """Classify trend as 'improving', 'stable', or 'degrading'.

        Uses per-KPI thresholds from TREND_THRESHOLDS.
        """
        threshold = self.TREND_THRESHOLDS.get(kpi_name, 0.5)
        if slope > threshold:
            return "improving"
        elif slope < -threshold:
            return "degrading"
        return "stable"

    def cleanup_old_snapshots(self, db: Session) -> int:
        """Aggregate daily snapshots older than 1 year into monthly summaries.

        Returns count of daily records deleted after aggregation.
        """
```

### 8. Alert Engine Service (`services/alert_engine.py`)

Computes risk scores and generates operator alerts.

```python
class AlertEngine:
    """Computes composite risk scores and generates alerts."""

    RISK_WEIGHTS = {
        "removal_rate_trend": 0.35,
        "karma_trend": 0.30,
        "volume_drop": 0.20,
        "consecutive_failures": 0.15,
    }
    WARNING_THRESHOLD = 70
    CRITICAL_THRESHOLD = 85
    DEDUP_WINDOW_HOURS = 24
    ALERT_RETENTION_DAYS = 90

    def compute_risk_scores(self, db: Session) -> dict[str, list]:
        """Compute composite risk scores for all entities.

        Processes: all active avatars, all active clients, system-level.
        Returns dict with lists of (entity_id, score, level) tuples.
        """

    def compute_entity_risk_score(
        self, db: Session, observation_level: str, entity_id: uuid.UUID | None
    ) -> float:
        """Compute risk score (0-100) for a single entity.

        Factors:
        - removal_rate_trend: 7d slope of removal rate (weight 0.35)
        - karma_trend: 7d slope of avg karma, inverted (weight 0.30)
        - volume_drop: % decrease in volume vs 30d avg (weight 0.20)
        - consecutive_failures: posting failures in last 7d (weight 0.15)

        Each factor normalized to 0-100, then weighted sum.
        """

    def evaluate_alerts(self, db: Session, risk_scores: dict) -> list[QualityAlert]:
        """Generate alerts based on risk score transitions.

        Creates alerts when:
        - Score crosses 70 (warning)
        - Score crosses 85 (critical)
        Respects 24h deduplication window.
        """

    def detect_correlation_alerts(self, db: Session) -> list[QualityAlert]:
        """Detect cross-entity patterns.

        Pattern: 3+ avatars with degrading karma in same subreddit within 7 days.
        Creates correlation alert: "subreddit may have become hostile"
        """

    def cleanup_expired_alerts(self, db: Session) -> int:
        """Delete alerts older than 90 days. Returns count deleted."""
```

### 9. Decision Quality Service (`services/decision_quality.py`)

Computes per-pipeline-node quality metrics for the dashboard.

```python
class DecisionQualityService:
    """Computes quality metrics for each pipeline decision node."""

    def compute_all_node_qualities(self, db: Session, window_days: int = 30) -> dict:
        """Compute quality metrics for all pipeline nodes.

        Returns dict with keys: strategy, scoring, epg, generation, posting.
        Each value is a dict with: score (0-1), trend, sample_count.
        """

    def strategy_quality(self, db: Session, window_days: int = 30) -> float:
        """Avg karma trend for comments following each strategy pattern.

        Score = normalized avg karma across all strategy-attributed outcomes.
        """

    def scoring_precision(self, db: Session, window_days: int = 30) -> float:
        """% of 'engage' threads that got positive outcome (karma > 0).

        Score = positive_outcomes / total_outcomes for scored threads.
        """

    def epg_quality(self, db: Session, window_days: int = 30) -> float:
        """Karma of selected threads vs. average thread karma.

        Score = avg_karma_selected / avg_karma_all (capped at 1.0).
        """

    def generation_quality(self, db: Session, window_days: int = 30) -> float:
        """Composite: (1 - edit_rate) * 0.3 + (1 - rejection_rate) * 0.3 + karma_score * 0.4.

        Combines pre-posting quality (edits, rejections) with post-posting outcome.
        """

    def posting_success(self, db: Session, window_days: int = 30) -> float:
        """(1 - failure_rate) * 0.5 + timing_effectiveness * 0.5.

        timing_effectiveness = avg effectiveness score for timing buckets used.
        """
```

### 10. Celery Tasks (`tasks/quality_sentinel.py`)

```python
from app.tasks.worker import celery_app

@celery_app.task(name="check_outcomes_batch")
def check_outcomes_batch():
    """Periodic task (every 4h): process pending karma checks in batch.

    1. Get up to 50 pending outcome records (ordered by priority)
    2. For each: execute karma check via Reddit API
    3. On 48h completion: trigger effectiveness score update
    4. Respects Reddit API rate limit (pause if >50 req/min)
    """

@celery_app.task(name="compute_daily_trends")
def compute_daily_trends():
    """Daily task (03:00): collect KPI snapshots and compute trends.

    1. Collect daily snapshots at all 4 observation levels
    2. Compute 7d and 30d linear regression slopes
    3. Chain: evaluate_risk_scores.delay()
    """

@celery_app.task(name="evaluate_risk_scores")
def evaluate_risk_scores():
    """Chained after compute_daily_trends: compute risk scores and alerts.

    1. Compute composite risk scores for all entities
    2. Evaluate alert conditions (threshold crossings)
    3. Detect correlation alerts (cross-entity patterns)
    4. Cleanup expired alerts (>90 days)
    """

@celery_app.task(name="cleanup_outcome_records")
def cleanup_outcome_records():
    """Weekly task: delete outcome records older than 90 days.

    Only deletes records that have been fully processed (next_check_type='complete')
    and whose data has been aggregated into effectiveness scores.
    """
```

### Celery Beat Schedule Additions

```python
"check-outcomes-batch": {
    "task": "check_outcomes_batch",
    "schedule": crontab(minute=0, hour="*/4"),  # Every 4 hours
},
"compute-daily-trends": {
    "task": "compute_daily_trends",
    "schedule": crontab(minute=0, hour=3),  # 03:00 daily
},
"cleanup-outcome-records": {
    "task": "cleanup_outcome_records",
    "schedule": crontab(minute=0, hour=4, day_of_week=0),  # Sunday 04:00
},
```

### 11. Dashboard Route (`routes/quality_dashboard.py`)

```python
from fastapi import APIRouter, Depends, Request
from app.dependencies.admin import require_superuser

router = APIRouter(prefix="/admin/quality", tags=["quality"])

@router.get("")
async def quality_dashboard(request: Request, db=Depends(get_db), user=Depends(require_superuser)):
    """Main quality dashboard page.

    Renders pre-computed data:
    - System risk score
    - Per-node decision quality bars
    - 7d sparkline trends
    - Top 5 at-risk entities
    - Recent effectiveness score changes
    - Unacknowledged alert count
    """

@router.get("/drilldown/{level}/{entity_id}")
async def quality_drilldown(level: str, entity_id: str, request: Request, db=Depends(get_db)):
    """Drill-down view for a specific entity.

    Shows: entity risk score, KPI history, effectiveness scores,
    trend charts, related alerts.
    """

@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, db=Depends(get_db), user=Depends(require_superuser)):
    """Mark an alert as acknowledged."""

@router.get("/alerts/badge")
async def alert_badge(db=Depends(get_db)):
    """HTMX partial: unacknowledged alert count for header badge."""
```

---

## Data Models

### New Tables

| Table | Purpose | Est. Size (10 clients) |
|-------|---------|----------------------|
| `outcome_records` | Post-posting karma/removal/reply data | ~22 KB/day |
| `effectiveness_scores` | Decision combo scores (upsert) | ~2.5 MB total |
| `kpi_snapshots` | Daily/monthly KPI measurements | ~5 KB/day |
| `quality_alerts` | Operator alerts with dedup | ~1 KB/day |

### Modified Tables

| Table | Change | Purpose |
|-------|--------|---------|
| `system_settings` | New keys: `auto_adaptation_enabled`, `quality_sentinel_enabled` | Feature gates |

---

## Effectiveness Score Formula

```python
def compute_effectiveness_score(outcomes: list[OutcomeRecord]) -> float:
    """
    For each outcome, compute a raw contribution:
      karma_contribution = sigmoid_normalize(karma_48h or karma_24h or karma_4h)
      removal_penalty = -REMOVAL_PENALTY if removal_detected else 0
      reply_bonus = min(reply_count * 0.1, REPLY_BONUS)

    Raw score = mean(karma_contribution + removal_penalty + reply_bonus)
    Final score = clip(raw_score, 0.0, 1.0)

    sigmoid_normalize maps karma to 0-1:
      - karma <= -5: 0.0
      - karma = 0: 0.3
      - karma = 1: 0.4
      - karma = 5: 0.6
      - karma = 10: 0.7
      - karma = 50+: 0.95
      - karma = 100+: 1.0
    """
```

---

## Auto-Adaptation Integration Points

### EPG Service Integration

```python
# In services/epg.py — thread selection
def select_threads_for_avatar(db, avatar, candidate_threads):
    engine = LearningEngine()
    weights = engine.get_adaptation_weights(
        db, "approach_x_subreddit", avatar_id=str(avatar.id), subreddit_id=None
    )
    # Apply weights to candidate scoring (multiply thread score by effectiveness weight)
    # Threads in high-effectiveness subreddits get boosted
```

### Approach Diversity Integration

```python
# In services/approach_diversity.py — approach selection
def select_approach(db, avatar, subreddit_id):
    engine = LearningEngine()
    weights = engine.get_adaptation_weights(
        db, "approach_x_subreddit", entity_id="*", subreddit_id=subreddit_id
    )
    # Reduce probability of approaches with score < 0.3
    # Boost probability of approaches with score > 0.6
```

### Timing Engine Integration

```python
# In services/timing_engine.py — slot assignment
def assign_timing_slot(db, avatar, subreddit_id):
    engine = LearningEngine()
    weights = engine.get_adaptation_weights(
        db, "timing_x_subreddit", entity_id="*", subreddit_id=subreddit_id
    )
    # Bias toward timing buckets with score > 0.5
    # Reduce weight of timing buckets with score < 0.3
```

---

## Error Handling

### Outcome Check Failures

| Error | Action | Impact |
|-------|--------|--------|
| Reddit API 429 (rate limit) | Backoff, prioritize 4h checks | Delayed snapshots |
| Reddit API 404 (comment gone) | Mark as removal_type='unknown' | Normal flow |
| Reddit API 500/503 | Retry 3x with backoff, skip on failure | Missing snapshot |
| Network timeout | Retry 3x, skip on failure | Missing snapshot |
| DB connection error | Skip entire batch, retry next cycle | Delayed processing |

### Graceful Degradation

- Missing karma_4h: use karma_24h for effectiveness computation
- Missing karma_24h: use karma_48h
- Missing all snapshots: exclude from effectiveness computation (don't penalize)
- Trend computation with gaps: linear regression handles missing points naturally
- Insufficient data (n < 5): fall back to parent level, never return 0

---

## Reddit API Usage

### Karma Check API Calls

```
Per check: 1 API call (GET /api/info with comment fullname)
Per outcome: 3 checks max (4h + 24h + 48h)
Per day at 10 clients: 150 posts × 3 = 450 calls/day
Rate: 450 / 24h = ~19 calls/hour (well within 60/min limit)
```

### Batch Processing Strategy

```
check_outcomes_batch runs every 4 hours (6 times/day)
Each run processes up to 50 pending checks
At 10 clients: ~75 checks per run (450/6)
Duration per run: ~75 × 2s = 150s (2.5 minutes)
```

### Priority Queue

When approaching rate limits, prioritize:
1. 4h checks (freshest signal, most actionable)
2. 24h checks (reply detection window)
3. 48h checks (final snapshot, can be delayed)

---

## Testing Strategy

### Property-Based Tests (Hypothesis)

- **Effectiveness score bounds**: For any set of outcomes, computed score is always in [0.0, 1.0]
- **Effectiveness score monotonicity**: Adding a positive outcome never decreases the score; adding a removal never increases it
- **Timing bucket computation**: For any valid datetime, compute_timing_bucket returns a valid bucket string matching pattern "HH-HH"
- **Risk score bounds**: For any entity state, risk score is always in [0, 100]
- **Trend classification consistency**: For any slope value, classify_trend returns exactly one of 'improving', 'stable', 'degrading'
- **Alert deduplication**: For any sequence of risk score evaluations, no duplicate alerts are created within 24h for the same entity+condition
- **Fallback behavior**: When sample_count < MIN_SAMPLES, get_adaptation_weights returns empty dict (no bias applied)
- **Outcome record completeness**: For any posted draft with valid attribution data, create_outcome_record produces a record with all required fields populated

### Unit Tests (pytest)

- Outcome tracker: mock Reddit API, verify karma/removal/reply extraction
- Learning engine: verify score computation with known inputs
- Trend calculator: verify linear regression with known data series
- Alert engine: verify threshold crossing detection
- Decision quality: verify per-node metric computation
- Retention cleanup: verify only completed records are deleted

### Integration Tests

- Full outcome lifecycle: post → 4h check → 24h check → 48h check → effectiveness update
- Alert flow: degrading trend → risk score crosses threshold → alert created → badge shows
- Adaptation flow: effectiveness scores computed → EPG uses weights → selection biased

---

## Correctness Properties

### Property 1: Effectiveness Score Bounds

For any non-empty list of OutcomeRecords, compute_effectiveness_score SHALL return a value in the closed interval [0.0, 1.0].

**Validates: Requirements 5.3**

### Property 2: Effectiveness Score Monotonicity — Positive Outcomes

For any set of outcomes S, if a new outcome with karma > 0 and no removal is added to produce S', then compute_effectiveness_score(S') >= compute_effectiveness_score(S) (score never decreases when adding a positive outcome).

**Validates: Requirements 5.3, 14.3**

### Property 3: Effectiveness Score Monotonicity — Removals

For any set of outcomes S, if a new outcome with removal_detected=True is added to produce S', then compute_effectiveness_score(S') <= compute_effectiveness_score(S) (score never increases when adding a removal).

**Validates: Requirements 5.3, 15.2**

### Property 4: Timing Bucket Computation Correctness

For any valid datetime d, compute_timing_bucket(d) SHALL return a string matching the pattern "HH-HH" where the first HH is an even hour and the second HH = first HH + 2, and d.hour falls within [first_HH, second_HH).

**Validates: Requirements 4.2**

### Property 5: Risk Score Bounds

For any combination of trend values and failure counts, compute_entity_risk_score SHALL return a value in the closed interval [0, 100].

**Validates: Requirements 10.1**

### Property 6: Trend Classification Exhaustiveness

For any float slope value and any valid kpi_name, classify_trend SHALL return exactly one of 'improving', 'stable', or 'degrading'.

**Validates: Requirements 9.3**

### Property 7: Alert Deduplication

For any entity E and condition C, if an alert for (E, C) was created at time T, then evaluate_alerts SHALL NOT create another alert for (E, C) at any time T' where T' - T < 24 hours.

**Validates: Requirements 11.5**

### Property 8: Minimum Sample Threshold

For any combo_key with sample_count < MIN_SAMPLES (5), get_adaptation_weights SHALL return an empty dict (no bias), ensuring the system does not adapt based on insufficient data.

**Validates: Requirements 5.4, 7.4**

### Property 9: Outcome Record Attribution Completeness

For any posted CommentDraft with a valid EPG slot and active strategy, create_outcome_record SHALL produce an OutcomeRecord where all attribution fields (comment_approach, strategy_pattern, timing_bucket) are non-null.

**Validates: Requirements 4.2, 6.1**

### Property 10: Karma Snapshot Scheduling Correctness

For any OutcomeRecord created at time T, the scheduled check times SHALL be: next_check_at = T + 4h (type='4h'), then T + 24h (type='24h'), then T + 48h (type='48h'), then next_check_type='complete'.

**Validates: Requirements 1.1**

### Property 11: Retention Cleanup Safety

For any OutcomeRecord with next_check_type != 'complete', cleanup_outcome_records SHALL NOT delete that record regardless of its age.

**Validates: Requirements 4.4**

### Property 12: Linear Regression Minimum Data Points

For any KPI with fewer than 5 daily snapshots, compute_trends SHALL NOT compute a 7d trend. For any KPI with fewer than 14 daily snapshots, compute_trends SHALL NOT compute a 30d trend.

**Validates: Requirements 9.2**

### Property 13: Risk Score Weight Sum

The sum of all RISK_WEIGHTS values SHALL equal 1.0, ensuring the composite risk score is properly normalized.

**Validates: Requirements 10.2**

### Property 14: Correlation Alert Detection

For any subreddit S, if 3 or more distinct avatars have trend_7d_karma classified as 'degrading' within the same 7-day window, detect_correlation_alerts SHALL produce a Correlation_Alert for subreddit S.

**Validates: Requirements 11.3**

### Property 15: Auto-Adaptation Gate

WHILE auto_adaptation_enabled system setting is False, get_adaptation_weights SHALL return empty dict for all combo types, ensuring no pipeline behavior is modified.

**Validates: Requirements 7.5**

### Property 16: Effectiveness Score Fallback

For any combo_key where sample_count < MIN_SAMPLES, the Learning_Engine SHALL attempt to compute a score at the parent level (e.g., approach across all subreddits). If the parent level also has insufficient data, it SHALL return no score rather than 0.

**Validates: Requirements 5.4, 5.5, 17.5**

**Validates: Requirements 5.5, 17.5**

---

## System Settings

| Key | Default | Group | Description |
|-----|---------|-------|-------------|
| `quality_sentinel_enabled` | `true` | quality | Master kill switch for all QS tasks |
| `auto_adaptation_enabled` | `false` | quality | Gates auto-adaptation behavior |
| `outcome_check_batch_size` | `50` | quality | Max checks per batch execution |
| `risk_score_warning_threshold` | `70` | quality | Risk score warning level |
| `risk_score_critical_threshold` | `85` | quality | Risk score critical level |
| `effectiveness_min_samples` | `5` | quality | Min outcomes before publishing score |
| `outcome_retention_days` | `90` | quality | Days to retain raw outcome records |
| `alert_retention_days` | `90` | quality | Days to retain alert records |

---

## Migration Plan

### Alembic Migration: `qs01_quality_sentinel_tables`

Creates:
- `outcome_records` table with all indexes
- `effectiveness_scores` table with unique constraint on combo_key
- `kpi_snapshots` table with unique constraint and indexes
- `quality_alerts` table with indexes
- System settings seed (quality group)

### Data Backfill

For existing posted comments (before Quality Sentinel activation):
- No backfill of karma snapshots (cannot retroactively check Reddit)
- Effectiveness scores start from zero (cold start)
- KPI snapshots start from activation date
- Historical data from existing `SubredditKarma` model can seed initial trends
