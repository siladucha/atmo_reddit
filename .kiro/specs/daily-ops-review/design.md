# Design Document

## Overview

The Daily Operations Review system provides a structured 60-90 minute daily review workflow at `/admin/daily-review`. It consumes data from existing platform models (ActivityEvent, AIUsageLog, KarmaSnapshot, PerformanceMetric, etc.) and optionally enhances analysis with budget-capped LLM calls (hard cap: $1/day, target: $0.30-0.50/day).

The architecture follows existing RAMP patterns: SQLAlchemy models, FastAPI route with HTMX partials, service layer for business logic. No new Celery tasks required — all analysis runs synchronously during the review session (data is already aggregated by existing Beat tasks).

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   /admin/daily-review                        │
│  ┌──────────┐  ┌──────────────────────────────────────────┐ │
│  │ Sidebar  │  │           Section Content                │ │
│  │ (6 steps │  │  (HTMX partials, lazy-loaded)            │ │
│  │ + timer) │  │                                          │ │
│  └──────────┘  └──────────────────────────────────────────┘ │
└───────────────────────────────┬─────────────────────────────┘
                                │ HTMX calls
                                ▼
┌─────────────────────────────────────────────────────────────┐
│              routes/daily_review.py                          │
│  start_session / get_section / save_input / complete        │
└───────────────────────────────┬─────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│            services/daily_review/                            │
│  ┌───────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │signal_collector│  │review_engine │  │  cost_governor  │  │
│  │ (SQL queries) │  │ (LLM + rules)│  │ (budget gate)   │  │
│  └───────┬───────┘  └──────┬───────┘  └────────┬────────┘  │
│          │                 │                    │            │
│          ▼                 ▼                    ▼            │
│  ┌──────────────────────────────────────────────────────┐   │
│  │          Existing Models (read-only)                  │   │
│  │  ActivityEvent, AIUsageLog, KarmaSnapshot,            │   │
│  │  PerformanceMetric, Avatar, Client, ScrapeLog,        │   │
│  │  PostingEvent, CommentDraft, HealthStatus             │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

**Key Design Decisions:**

1. **No new background tasks** — Signal collection is fast SQL (< 10s). LLM calls happen on-demand during section load.
2. **Graceful degradation** — Every section works without LLM (SQL-only fallback). LLM adds classification quality and narrative.
3. **Session caching** — Data snapshot is frozen at session start. Consistent view across all 6 sections.
4. **Existing data only** — No dependency on unbuilt Intelligence Layer or Operations Agent tables. Uses ActivityEvent, AIUsageLog, etc. directly.

## Components and Interfaces

## Data Models

#### DailyReviewSession

Stores the state of each review session.

```python
class DailyReviewSession(Base):
    __tablename__ = "daily_review_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_progress")
        # in_progress | completed | abandoned
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_date: Mapped[date] = mapped_column(Date, nullable=False)  # The date being reviewed

    # Section states: {"health": "completed", "changes": "pending", ...}
    section_states: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Section timestamps: {"health_started_at": "...", "health_completed_at": "...", ...}
    section_timestamps: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Cached aggregated data snapshot (frozen at session start for consistency)
    cached_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # User inputs per section (auto-saved on keystroke)
    user_inputs: Mapped[dict] = mapped_column(JSONB, default=dict)

    # LLM cost for this session
    session_llm_cost_usd: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=0)

    __table_args__ = (
        Index("ix_daily_review_sessions_date", "review_date"),
        Index("ix_daily_review_sessions_user_status", "user_id", "status"),
    )
```

#### IntelligenceReport

Immutable artifact produced when session completes.

```python
class IntelligenceReport(Base):
    __tablename__ = "intelligence_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("daily_review_sessions.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Structured data
    system_state: Mapped[str] = mapped_column(String(20), nullable=False)  # healthy | degraded | critical
    health_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    top_events: Mapped[list] = mapped_column(JSONB, nullable=False)       # top 3 changes
    top_anomalies: Mapped[list] = mapped_column(JSONB, nullable=False)    # top 3 anomalies
    top_risks: Mapped[list] = mapped_column(JSONB, nullable=False)        # next 24h risks
    forecast_table: Mapped[list] = mapped_column(JSONB, nullable=False)   # 7 domain forecasts
    decisions: Mapped[list] = mapped_column(JSONB, nullable=False)        # max 3 decisions
    overall_confidence: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-100

    # Narrative summary
    narrative_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    narrative_mode: Mapped[str] = mapped_column(String(20), default="llm")  # llm | template | offline

    # Forecast accuracy (filled next day when new session starts)
    forecast_accuracy: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Cost tracking
    total_llm_cost_usd: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=0)

    __table_args__ = (
        Index("ix_intelligence_reports_date", "report_date"),
    )
```

#### ReviewDecision

```python
class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("daily_review_sessions.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)

    decision_type: Mapped[str] = mapped_column(String(20), nullable=False)  # continue | investigate | change
    description: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str] = mapped_column(String(100), nullable=False)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    linked_observations: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Follow-up
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | done | deferred | cancelled
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    defer_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_review_decisions_status_date", "status", "report_date"),
    )
```

#### ReviewHypothesis

```python
class ReviewHypothesis(Base):
    __tablename__ = "review_hypotheses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("daily_review_sessions.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)

    observation: Mapped[str] = mapped_column(Text, nullable=False)
    possible_causes: Mapped[list] = mapped_column(JSONB, nullable=False)  # [{cause, probability}]
    recommended_action: Mapped[str] = mapped_column(String(30), nullable=False)
        # monitor | investigate | immediate_fix | defer
    linked_signals: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="open")  # open | confirmed | rejected | resolved
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_review_hypotheses_status", "status"),
    )
```

### Service Layer

#### services/daily_review/__init__.py

Package exports.

#### services/daily_review/signal_collector.py

Pure SQL aggregation — no LLM calls. Collects all operational signals.

```python
@dataclass
class HealthSignal:
    category: str           # uptime | errors | queue | latency | cost | usage | email | llm | reddit | manual | incidents
    metric_name: str        # e.g. "celery_failed_tasks_24h"
    current_value: float
    seven_day_avg: float
    delta_pct: float        # % change vs 7-day avg
    status: str             # better | worse | stable
    attention: bool         # > 1.5 stddev from baseline

@dataclass
class HealthSnapshot:
    signals: list[HealthSignal]
    overall_verdict: str    # healthy | degraded | critical
    verdict_evidence: list[str]
    collected_at: datetime
    data_gaps: list[str]

@dataclass
class ChangeSignal:
    category: str           # new_error | frequency_change | quality_degradation | user_behavior | external_api | unexpected_pattern
    signal: str             # description
    evidence: str           # supporting data
    impact: str             # avatar | client | platform
    confidence: str         # high | medium | low

@dataclass
class TrendItem:
    metric_name: str
    direction: str          # positive | negative | neutral
    magnitude_pct: float
    duration_days: int
    classification: str     # expected | unexpected | weak_signal
    extrapolation_7d: str | None

async def collect_health_snapshot(db: Session) -> HealthSnapshot: ...
async def collect_changes(db: Session, since: datetime) -> list[ChangeSignal]: ...
async def collect_trends(db: Session) -> list[TrendItem]: ...
```

#### services/daily_review/review_engine.py

LLM-enhanced analysis, gated by cost_governor.

```python
async def enhance_health_summary(snapshot: HealthSnapshot, budget: CostBudget) -> str | None: ...
async def classify_trends(trends: list[TrendItem], budget: CostBudget) -> list[TrendItem]: ...
async def generate_hypotheses(changes: list[ChangeSignal], trends: list[TrendItem], budget: CostBudget) -> list[dict]: ...
async def generate_forecasts(snapshot: HealthSnapshot, trends: list[TrendItem], budget: CostBudget) -> list[dict]: ...
async def generate_narrative(report_data: dict, budget: CostBudget) -> tuple[str, str]: ...
```

#### services/daily_review/cost_governor.py

Budget enforcement.

```python
@dataclass
class CostBudget:
    daily_limit_usd: Decimal
    spent_today_usd: Decimal
    session_spent_usd: Decimal

    @property
    def remaining_usd(self) -> Decimal: ...
    @property
    def is_warning(self) -> bool: ...    # >= 80%
    @property
    def is_exhausted(self) -> bool: ...  # >= 100%

    def can_spend(self, estimated_cost: float) -> bool: ...
    def record_spend(self, db: Session, cost: Decimal, operation: str, model: str,
                     input_tokens: int, output_tokens: int, session_id: uuid.UUID) -> None: ...

def get_today_budget(db: Session) -> CostBudget: ...
def get_weekly_cost_summary(db: Session) -> dict: ...
```

### Route Layer

#### routes/daily_review.py

```python
router = APIRouter(prefix="/admin/daily-review", tags=["daily-review"])

@router.get("/")                                    # Main page: start or resume
@router.get("/history")                             # Historical reports (HTMX partial)
@router.post("/start")                              # Create new session
@router.get("/section/{name}")                      # Load section partial (lazy)
@router.post("/section/{name}/save")                # Auto-save user inputs
@router.post("/section/{name}/complete")            # Mark section done
@router.post("/complete")                           # Finalize → generate report
@router.post("/decisions")                          # Add decision
@router.patch("/decisions/{id}")                    # Update decision status
@router.get("/decisions/open")                      # Unresolved decisions partial
@router.post("/hypotheses")                         # Add hypothesis
@router.patch("/hypotheses/{id}")                   # Update hypothesis status
@router.get("/budget")                              # Budget indicator partial
```

All routes protected by `require_platform_admin` (owner/partner role only).

### Template Structure

```
templates/
├── admin_daily_review.html                         # Main page (extends admin_base.html)
└── partials/
    └── daily_review/
        ├── session_start.html                      # Landing: hours since last, forecast accuracy
        ├── sidebar.html                            # Section nav + timer + budget bar
        ├── section_health.html                     # Signals table + verdict badge
        ├── section_changes.html                    # Changes table (Signal/Evidence/Impact/Confidence)
        ├── section_trends.html                     # 3 tabs: expected/unexpected/weak
        ├── section_hypotheses.html                 # Hypothesis cards + history
        ├── section_forecast.html                   # Forecast table + override controls
        ├── section_decisions.html                  # Decision capture + open decisions list
        ├── budget_indicator.html                   # Cost budget bar with spend/remaining
        ├── report_card.html                        # Single report row in history
        └── quick_review.html                       # Collapsed "all clear" mode
```

### LLM Cost Budget Design

| Operation | Model | Input | Output | Cost | Frequency |
|-----------|-------|-------|--------|------|-----------|
| Health classification | Gemini 2.0 Flash | ~2K tok | ~200 tok | ~$0.01 | 1x/session |
| Change categorization | Gemini 2.0 Flash | ~3K tok | ~500 tok | ~$0.02 | 1x/session |
| Trend classification | Gemini 2.0 Flash | ~2K tok | ~400 tok | ~$0.02 | 1x/session |
| Hypothesis generation | Claude 3.5 Haiku | ~4K tok | ~800 tok | ~$0.08 | 1x/session |
| Forecast (7 domains) | Gemini 2.0 Flash | ~3K tok | ~600 tok | ~$0.02 | 1x/session |
| Narrative report | Claude 3.5 Haiku | ~3K tok | ~500 tok | ~$0.05 | 1x/session |
| **Total per session** | | | | **~$0.20** | |

**Budget strategy:**
- Target: $0.20-0.40/session normal day
- Buffer: $0.60 remaining for retries, extra analysis on incident days
- Hard cap: $1.00/day — system refuses LLM calls after exhaustion
- All operations batched: 7 forecasts in 1 prompt, all signals in 1 classification call

### Fallback Strategy (Offline Mode)

When budget exhausted, each section degrades gracefully:

| Section | LLM Mode | Offline Mode |
|---------|----------|--------------|
| Health Snapshot | AI verdict + summary | Raw signals table, rule-based verdict |
| Changes | AI categorization | Frequency-delta grouping (SQL only) |
| Trends | AI classification | Direction + magnitude only |
| Hypotheses | AI suggestions | Empty template, manual-only |
| Forecast | AI predictions | "Stable" default, anomaly notes only |
| Narrative | Prose summary | Template: "Date: X. State: Y. Decisions: N." |

## Error Handling

1. **SQL query timeout** — Each signal_collector query has 5s timeout. On timeout, that signal category shows "data unavailable" and is excluded from health score.
2. **LLM API failure** — Automatic fallback to offline mode for that operation. Cost not charged for failed calls. Error logged.
3. **Session data loss** — user_inputs JSONB is auto-saved per keystroke via HTMX POST. Browser crash loses max 2s of typing.
4. **Budget race condition** — cost_governor uses SELECT FOR UPDATE on daily accumulator to prevent overspend in concurrent sessions (unlikely but handled).
5. **Stale cache** — cached_snapshot is frozen at session start. If session lasts 3+ hours, user sees banner "data may be stale, consider restarting".

## Correctness Properties

### Property 1: Budget Invariant
`SUM(ai_usage_log.cost_usd WHERE operation LIKE 'agent_%' AND date = today) <= agent_daily_budget_usd`. Enforced at every LLM call via `can_spend()` check BEFORE the API call.

### Property 2: Session Completeness
A session cannot be marked "completed" until all 6 section_states are "completed". UI enforces sequential progression.

### Property 3: Report Immutability
IntelligenceReport has no UPDATE endpoints. Amendments create linked records.

### Property 4: Decision Limit
Maximum 3 decisions per session enforced at route level (returns 422 on 4th attempt).

### Property 5: Forecast Uniqueness
Only one IntelligenceReport per report_date (UNIQUE constraint). Cannot generate two reports for same day.

## Testing Strategy

1. **Unit tests** — signal_collector functions tested with fixture DB data (known events → expected signals)
2. **Cost governor tests** — verify budget enforcement, boundary conditions ($0.99 remaining + $0.02 call → blocked)
3. **Integration tests** — full session lifecycle: start → fill sections → complete → verify report generated
4. **Offline mode test** — set budget to $0.00, verify all sections render with template fallback
5. **Auto-save test** — simulate keystroke → verify user_inputs JSONB updated
6. **Forecast accuracy test** — create yesterday's report with known forecast → verify evaluation logic

## Alembic Migration

Single migration `dor01_daily_ops_review_tables`:

```sql
CREATE TABLE daily_review_sessions (...);
CREATE TABLE intelligence_reports (...);
CREATE TABLE review_decisions (...);
CREATE TABLE review_hypotheses (...);
-- Indexes as defined in models
```

## Dependencies on Existing Systems

| System | Data Consumed | Access |
|--------|--------------|--------|
| ActivityEvent | Event counts, types, frequencies (24h) | SQL read |
| AIUsageLog | Cost totals, failure rates + write agent_ops records | SQL read/write |
| KarmaSnapshot | Karma outcomes, deletions (48h) | SQL read |
| PerformanceMetric | Daily avatar aggregates | SQL read |
| ScrapeLog | Scrape success/timing | SQL read |
| PostingEvent | Posting success/failure | SQL read |
| Avatar | Frozen count, phase, health | SQL read |
| Client | Active count, plan types | SQL read |
| CommentDraft | Generation/approval rates | SQL read |
| SystemSetting | Kill switches, budget config | SQL read |
| HealthStatus | Shadowban/suspension events | SQL read |

No dependency on unbuilt tables (Intelligence Layer, Operations Agent). This feature works with current codebase.
