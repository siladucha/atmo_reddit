# Design Document: RAMP Operations Agent

## Overview

The RAMP Operations Agent is a three-layer autonomous monitoring and management system that watches, maintains, and optimizes the RAMP platform. The critical architectural lesson from the June 2026 17-day outage drives the design: **the observer must NOT live exclusively inside the observed system.**

### Design Rationale

The three-layer architecture separates concerns by failure domain:

- **Layer 1 (External Watchdog)**: Lives OUTSIDE Docker/Celery on the host OS. Survives container crashes, Celery death, and Docker daemon failures. Resolves tensions T-2026-06-28-004 and T-2026-06-28-007.
- **Layer 2 (Decision & Action Engine)**: Lives INSIDE Celery. Handles authority framework, action execution, and pipeline liveness checks. Resolves tension T-2026-06-28-006.
- **Layer 3 (Intelligence)**: Lives INSIDE Celery. Handles trends, economics, silent failures, briefings. Non-critical — system survives without it.

### Phasing Strategy

| Phase | Scope | Resolves |
|-------|-------|----------|
| Phase 1 | External watchdog + Telegram bot + pipeline liveness | T-004, T-006, T-007 |
| Phase 2 | Authority framework + autonomous actions | Req 12-15 |
| Phase 3 | Economic intelligence + silent failure detection | Req 10-11, 21 |
| Phase 4 | Briefings + weekly reports + scaling intelligence | Req 16-17, 20 |


## Architecture

### High-Level System Diagram

```mermaid
graph TB
    subgraph "Host OS (outside Docker)"
        L1[Layer 1: External Watchdog]
        CRON[systemd timer / cron]
        TG_BOT[Telegram Bot Process]
        UPTIMEROBOT[UptimeRobot Webhook]
    end

    subgraph "Docker Compose"
        subgraph "App Container"
            FASTAPI[FastAPI App]
            HEALTH_EP[/health endpoint]
            AGENT_EP[/admin/agent endpoints]
        end

        subgraph "Celery Workers"
            L2[Layer 2: Decision Engine]
            L3[Layer 3: Intelligence]
            AUTH[Authority Framework]
            EXEC[Action Executor]
            ALERT[Alert Engine]
            ECON[Economics Engine]
            BRIEF[Briefing Service]
        end

        subgraph "Data Layer"
            PG[(PostgreSQL)]
            REDIS[(Redis)]
        end
    end

    subgraph "External Services"
        TELEGRAM[Telegram API]
        UPTIME[UptimeRobot]
        LLM_API[LLM APIs]
    end

    CRON -->|every 30s| L1
    L1 -->|check| HEALTH_EP
    L1 -->|check| REDIS
    L1 -->|check| PG
    L1 -->|alert| TG_BOT
    L1 -->|restart| Docker

    UPTIMEROBOT -->|monitors| HEALTH_EP
    UPTIME -->|webhook on failure| TG_BOT

    TG_BOT <-->|commands + alerts| TELEGRAM
    TG_BOT -->|read| PG
    TG_BOT -->|read/write| REDIS

    L2 -->|execute| EXEC
    L2 -->|check authority| AUTH
    L2 -->|generate| ALERT
    L3 -->|analyze| ECON
    L3 -->|generate| BRIEF
    L3 -->|detect| ALERT

    ALERT -->|deliver| TG_BOT
    BRIEF -->|deliver| TG_BOT
    BRIEF -->|render| LLM_API

    EXEC -->|modify| PG
    EXEC -->|modify| REDIS
    L2 -->|read/write| PG
    L3 -->|read| PG
```


### Layer 1: External Watchdog (Phase 1)

**Deployment**: Standalone Python script + systemd timer on the DigitalOcean host, OUTSIDE Docker Compose. Also a long-running Telegram bot process managed by systemd.

**Design Decision**: Using systemd services (not Docker containers) because:
1. Survives Docker daemon restart/crash
2. Survives container OOM kills
3. Can restart Docker containers from outside
4. Minimal dependencies (Python + psycopg2 + redis-py + python-telegram-bot)

#### Watchdog Script (`/opt/ramp-watchdog/watchdog.py`)

Runs every 30 seconds via systemd timer. Checks:
1. Docker container health (all 4 services: app, db, redis, celery, celery-fast)
2. `/health` endpoint responds with 200 and valid JSON
3. Redis `ramp:heartbeat:last_at` is fresh (<3 min)
4. PostgreSQL accepts connections
5. Last scrape timestamp < 12 hours (if scraping enabled)
6. Last pipeline output < 24 hours (for active clients)

On failure: writes alert to Redis queue `ramp:watchdog:alerts`, Telegram bot picks up and delivers.

#### Telegram Bot Process (`/opt/ramp-watchdog/telegram_bot.py`)

Long-running systemd service. Responsibilities:
- Deliver alerts from Redis queue `ramp:watchdog:alerts`
- Deliver alerts from Layer 2/3 via Redis queue `ramp:agent:alerts`
- Handle interactive commands (`/status`, `/cost`, `/fleet`, `/approve`, `/reject`, `/silence`)
- Verify sender Telegram ID matches configured owner

#### UptimeRobot Integration

External monitoring (free tier, 5-minute checks):
- Monitors `https://gorampit.com/health`
- On failure: sends notification to configured Telegram chat
- Catches scenarios where even the host OS is unreachable


### Layer 2: Decision & Action Engine (Phase 2)

**Deployment**: Celery tasks on the existing worker infrastructure.

Components:
- **Metric Collector** (`agent_metric_collector` task, every 60s): Collects infrastructure/pipeline/avatar metrics, persists to `agent_metrics` table.
- **Alert Engine** (`agent_alert_evaluator` task, every 60s): Evaluates alert conditions across all tiers, handles cooldown/dedup/escalation.
- **Action Executor** (`agent_action_executor` task, every 60s): Checks recovery conditions, executes autonomous actions within authority bounds.
- **Pipeline Liveness Monitor** (`agent_pipeline_liveness` task, every 5 min): Checks each pipeline stage for zero-output conditions, flags stalled stages.
- **Authority Framework**: In-memory classification lookup + DB-persisted overrides. Validates every action before execution.

### Layer 3: Intelligence (Phase 3-4)

**Deployment**: Celery periodic tasks (lower frequency — hourly/daily/weekly).

Components:
- **Economics Engine** (`agent_economics_daily` task, 02:00): Cost per client, margins, optimization suggestions.
- **Silent Failure Detector** (`agent_silent_failures` task, 03:00): Quality drift, phantom scraping, orphaned avatars.
- **Briefing Service** (`agent_daily_briefing` task, 08:30; `agent_weekly_report` task, Sunday 10:00): Generates and delivers reports.
- **Scaling Intelligence** (`agent_scaling_assessment` task, Monday 03:00): Capacity model and projections.
- **Trend Analyzer** (`agent_trend_analysis` task, Sunday 04:00): Weekly trend scores and fleet attrition analysis.


## Components and Interfaces

### Phase 1 Components

#### 1. External Watchdog (`/opt/ramp-watchdog/`)

```
/opt/ramp-watchdog/
├── watchdog.py          # Main check script (runs every 30s via systemd timer)
├── telegram_bot.py      # Long-running Telegram bot service
├── config.yaml          # Thresholds, Telegram chat ID, DB credentials
├── requirements.txt     # psycopg2-binary, redis, python-telegram-bot, pyyaml, httpx
└── install.sh           # Sets up systemd units + Python venv
```

**watchdog.py interface:**
```python
class WatchdogCheck:
    name: str
    status: Literal["healthy", "degraded", "critical"]
    message: str
    checked_at: datetime
    details: dict  # metric-specific payload

def run_all_checks(config: WatchdogConfig) -> list[WatchdogCheck]:
    """Execute all checks, return results. Never throws."""
    ...

def evaluate_and_alert(checks: list[WatchdogCheck], redis_client) -> None:
    """Push alerts to Redis queue if any check is critical/degraded."""
    ...
```

**telegram_bot.py interface:**
```python
class TelegramBotService:
    async def start(self) -> None: ...
    async def process_alert_queue(self) -> None:
        """Poll Redis queues, deliver messages."""
    async def handle_command(self, update: Update) -> None:
        """Route /status, /cost, /fleet, /approve, /reject, /silence."""
    def verify_sender(self, user_id: int) -> bool:
        """Check Telegram user ID against config."""
```


#### 2. Enhanced Health Endpoint

Extend existing `/health` endpoint to include agent-relevant signals:

```python
# GET /health — enhanced response
{
    "status": "healthy",  # healthy | degraded | critical
    "version": "0.3.0",
    "env": "production",
    "posting_disabled": true,
    "agent": {
        "health_score": 82,
        "last_heartbeat_at": "2026-07-01T12:00:30Z",
        "celery_workers_online": 2,
        "last_scrape_at": "2026-07-01T11:45:00Z",
        "last_pipeline_output_at": "2026-07-01T08:22:00Z",
        "pending_alerts": 1,
        "db_connections_used": 8,
        "redis_memory_mb": 45
    }
}
```

#### 3. Pipeline Liveness Monitor (inside Celery)

```python
class PipelineLivenessMonitor:
    """Detects zero-output pipeline stages (resolves T-2026-06-28-006)."""

    def check_stage_liveness(self, db: Session) -> list[StalledStage]:
        """For each pipeline stage, check if output is zero for > 2x cycle time."""
        ...

    def check_client_delivery(self, db: Session) -> list[ClientDeliveryGap]:
        """For each active client, check if 0 drafts for 48h."""
        ...

@dataclass
class StalledStage:
    stage: str  # scraping | scoring | generation | posting
    client_id: UUID | None  # None = system-wide
    last_output_at: datetime
    expected_cycle_hours: float
    hours_since_output: float
```


### Phase 2 Components

#### 4. Authority Framework

```python
class PermissionLevel(str, Enum):
    AUTONOMOUS = "autonomous"
    CONFIRMATION_REQUIRED = "confirmation_required"
    FORBIDDEN = "forbidden"

# Static classification (code-defined, DB-overridable)
AUTHORITY_MATRIX: dict[str, PermissionLevel] = {
    # Autonomous
    "restart_celery_worker": PermissionLevel.AUTONOMOUS,
    "freeze_avatar": PermissionLevel.AUTONOMOUS,
    "rotate_logs": PermissionLevel.AUTONOMOUS,
    "flush_redis_expired": PermissionLevel.AUTONOMOUS,
    "retry_failed_task": PermissionLevel.AUTONOMOUS,
    "adjust_worker_concurrency": PermissionLevel.AUTONOMOUS,
    "enforce_data_retention": PermissionLevel.AUTONOMOUS,
    "reprioritize_scrape_queue": PermissionLevel.AUTONOMOUS,
    "pause_avatar_proxy": PermissionLevel.AUTONOMOUS,
    "redistribute_drafts": PermissionLevel.AUTONOMOUS,
    # Confirmation required
    "deactivate_client": PermissionLevel.CONFIRMATION_REQUIRED,
    "unfreeze_avatar": PermissionLevel.CONFIRMATION_REQUIRED,
    "change_llm_model": PermissionLevel.CONFIRMATION_REQUIRED,
    "modify_posting_caps": PermissionLevel.CONFIRMATION_REQUIRED,
    "change_pipeline_schedule": PermissionLevel.CONFIRMATION_REQUIRED,
    "add_remove_subreddit": PermissionLevel.CONFIRMATION_REQUIRED,
    # Forbidden
    "delete_client_data": PermissionLevel.FORBIDDEN,
    "modify_billing": PermissionLevel.FORBIDDEN,
    "access_credentials": PermissionLevel.FORBIDDEN,
    "push_code": PermissionLevel.FORBIDDEN,
    "modify_infrastructure": PermissionLevel.FORBIDDEN,
    "create_delete_tables": PermissionLevel.FORBIDDEN,
}

class AuthorityFramework:
    def get_permission(self, action: str, db: Session) -> PermissionLevel:
        """Check DB overrides first, fall back to static matrix, default to CONFIRMATION_REQUIRED."""
        ...

    def execute_if_allowed(self, action: AgentAction, db: Session) -> ActionResult:
        """Validate permission, execute or escalate, audit log."""
        ...

    def propose_action(self, action: AgentAction, db: Session) -> AgentProposal:
        """Create proposal for confirmation_required action."""
        ...
```


#### 5. Action Executor

```python
class ActionExecutor:
    """Executes autonomous actions within authority bounds."""

    def restart_celery_worker(self) -> ActionResult: ...
    def freeze_avatar(self, avatar_id: UUID, reason: str) -> ActionResult: ...
    def flush_redis_expired(self) -> ActionResult: ...
    def rotate_logs(self) -> ActionResult: ...
    def adjust_concurrency(self, delta: int) -> ActionResult: ...
    def reprioritize_scrape_queue(self, subreddit_ids: list[UUID]) -> ActionResult: ...
    def redistribute_drafts(self, source_avatar: UUID, targets: list[UUID]) -> ActionResult: ...

    def execute(self, action: AgentAction) -> ActionResult:
        """Dispatch to handler, log result, handle rollback on failure."""
        ...

@dataclass
class ActionResult:
    action_name: str
    success: bool
    message: str
    rollback_plan: str | None
    execution_time_ms: int
    affected_entities: list[str]
```

#### 6. Alert Engine

```python
class AlertEngine:
    """Evaluates alert conditions, manages cooldowns and escalation."""

    def evaluate_immediate_alerts(self, metrics: MetricSnapshot) -> list[Alert]: ...
    def evaluate_short_term_alerts(self, metrics: MetricSnapshot) -> list[Alert]: ...
    def evaluate_plannable_alerts(self, metrics: MetricSnapshot) -> list[Alert]: ...
    def evaluate_trend_alerts(self, weekly_data: WeeklyMetrics) -> list[Alert]: ...

    def should_suppress(self, alert: Alert, db: Session) -> bool:
        """Check cooldown period for duplicate suppression."""
        ...

    def escalate_if_needed(self, alert: Alert, db: Session) -> Alert:
        """Escalate severity if fired 3+ times in 24h without resolution."""
        ...

    def deliver(self, alert: Alert, db: Session) -> None:
        """Route to appropriate delivery channel (Telegram/email/dashboard)."""
        ...
```


### Phase 3-4 Components

#### 7. Economics Engine

```python
class EconomicsEngine:
    """Daily cost analysis and optimization suggestions."""

    def compute_cost_per_client(self, db: Session, date: date) -> dict[UUID, ClientCost]: ...
    def compute_cost_per_avatar(self, db: Session, date: date) -> dict[UUID, AvatarCost]: ...
    def compute_margins(self, db: Session, period: str) -> MarginReport: ...
    def identify_outliers(self, db: Session) -> list[CostOutlier]: ...
    def generate_optimization_suggestions(self, db: Session) -> list[OptimizationSuggestion]: ...
    def compute_breakeven(self, db: Session) -> dict[UUID, BreakevenPoint]: ...

@dataclass
class ClientCost:
    client_id: UUID
    date: date
    llm_scoring: Decimal
    llm_generation: Decimal
    llm_persona: Decimal
    llm_editing: Decimal
    proxy_fees: Decimal
    infrastructure_share: Decimal
    total: Decimal

@dataclass
class OptimizationSuggestion:
    suggestion_type: str
    affected_entity_id: UUID
    affected_entity_type: str
    description: str
    estimated_monthly_savings_usd: Decimal
    confidence: str  # high | medium | low
```

#### 8. Silent Failure Detector

```python
class SilentFailureDetector:
    """Detects problems that produce no errors but degrade quality."""

    def detect_quality_drift(self, db: Session) -> list[Finding]: ...
    def detect_phantom_scraping(self, db: Session) -> list[Finding]: ...
    def detect_scoring_inflation(self, db: Session) -> list[Finding]: ...
    def detect_stale_learning(self, db: Session) -> list[Finding]: ...
    def detect_orphaned_avatars(self, db: Session) -> list[Finding]: ...

    def run_all(self, db: Session) -> list[Finding]:
        """Execute all detectors, return findings."""
        ...

@dataclass
class Finding:
    finding_type: str
    entity_type: str  # client | avatar | subreddit
    entity_id: UUID
    description: str
    evidence: dict
    detected_at: datetime
```


#### 9. Briefing Service

```python
class BriefingService:
    """Generates daily and weekly reports."""

    def generate_daily_briefing(self, db: Session) -> DailyBriefing:
        """SQL-first data collection. LLM used only for 'recommendations' section if budget allows."""
        ...

    def generate_weekly_report(self, db: Session) -> WeeklyReport:
        """Full Markdown report with WoW comparisons, fleet status, economics."""
        ...

    def format_telegram_message(self, briefing: DailyBriefing) -> str:
        """Telegram-markdown formatted, max 500 words."""
        ...

    def deliver(self, message: str, channel: str) -> DeliveryResult:
        """Send via Telegram bot Redis queue. Retry 3x on failure."""
        ...
```

#### 10. Scaling Intelligence

```python
class ScalingIntelligence:
    """Capacity modeling and time-to-limit projections."""

    def compute_capacity_model(self, db: Session) -> CapacityModel: ...
    def project_time_to_limit(self, model: CapacityModel) -> dict[str, int]: ...
    def get_scaling_playbook(self, dimension: str) -> PlaybookEntry: ...

@dataclass
class CapacityModel:
    computed_at: datetime
    dimensions: dict[str, DimensionCapacity]

@dataclass
class DimensionCapacity:
    name: str  # cpu | memory | db_connections | reddit_api | llm_budget
    current_utilization_pct: float
    estimated_max_clients: int
    per_client_consumption: float
    days_to_90_pct: int | None
```


### Integration Points with Existing Code

| Existing Component | Integration Type | Details |
|-------------------|-----------------|---------|
| `signal_collector.py` | **Reuse + extend** | Layer 3 economics engine reuses signal collection patterns. Agent adds new metric categories. |
| `cost_governor.py` | **Share budget** | Agent ops share the existing $1/day budget. Agent heartbeat + alerts are free (no LLM). Only briefing/analysis uses budget. |
| `alert_aggregation.py` | **Supersede gradually** | Alert Engine replaces alert_aggregation for push delivery. Dashboard rendering coexists during transition. |
| `settings.py` | **Read** | Agent reads kill switches, thresholds, configuration from system_settings table. |
| `daily_review.py` | **Complement** | Agent provides automated daily signal. Daily Review remains the human-in-loop session for decisions. |
| `health_checker.py` | **Consume output** | Agent reads avatar health status. Does not duplicate health check logic. |
| Celery Beat | **Add tasks** | Agent adds 8-10 new periodic tasks to existing Beat schedule. |
| Redis | **Add keys** | Agent uses `ramp:agent:*` key prefix for all new Redis keys (heartbeat, locks, alert queues). |
| ActivityEvent model | **Write** | Agent emits activity events for all actions, findings, alerts. |
| AuditLog model | **Write** | Authority framework logs all decisions to existing audit log. |


## Data Models

### New Tables

#### `agent_metrics` — Time-series metric storage

```python
class AgentMetric(Base):
    __tablename__ = "agent_metrics"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    collected_at: Mapped[datetime] = mapped_column(index=True)
    category: Mapped[str]  # infrastructure | pipeline | avatar | economic
    metric_name: Mapped[str] = mapped_column(index=True)
    value: Mapped[float]
    unit: Mapped[str]  # percent | count | seconds | usd | bytes
    component: Mapped[str | None]  # postgres | redis | celery | scraping | etc.
    client_id: Mapped[UUID | None] = mapped_column(ForeignKey("clients.id"))
    avatar_id: Mapped[UUID | None] = mapped_column(ForeignKey("avatars.id"))
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_agent_metrics_cat_name_time", "category", "metric_name", "collected_at"),
    )
```

#### `agent_alerts` — Alert lifecycle tracking

```python
class AgentAlert(Base):
    __tablename__ = "agent_alerts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    alert_type: Mapped[str] = mapped_column(index=True)  # machine-readable identifier
    severity: Mapped[str]  # critical | high | medium | low
    time_horizon: Mapped[str]  # immediate | short_term | plannable | trend
    title: Mapped[str]
    message: Mapped[str]
    affected_entity_type: Mapped[str | None]  # client | avatar | subreddit | system
    affected_entity_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(default="open")  # open | acknowledged | resolved | false_positive | expired
    triggered_at: Mapped[datetime] = mapped_column(index=True)
    acknowledged_at: Mapped[datetime | None]
    resolved_at: Mapped[datetime | None]
    escalation_count: Mapped[int] = mapped_column(default=0)
    original_severity: Mapped[str]
    cooldown_until: Mapped[datetime | None]
    delivery_status: Mapped[str] = mapped_column(default="pending")  # pending | delivered | failed
    delivery_channel: Mapped[str | None]  # telegram | email | dashboard
    payload_json: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_agent_alerts_type_entity", "alert_type", "affected_entity_id"),
        Index("ix_agent_alerts_status", "status", "triggered_at"),
    )
```


#### `agent_actions` — Autonomous action log

```python
class AgentAction(Base):
    __tablename__ = "agent_actions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    action_name: Mapped[str] = mapped_column(index=True)
    permission_level: Mapped[str]  # autonomous | confirmation_required | forbidden
    status: Mapped[str]  # executed | proposed | approved | rejected | expired | blocked | failed
    trigger_condition: Mapped[str]  # what caused this action
    affected_entity_type: Mapped[str | None]
    affected_entity_id: Mapped[UUID | None]
    rationale: Mapped[str | None]  # 1-3 sentence explanation
    expected_impact: Mapped[str | None]  # what will change
    rollback_plan: Mapped[str | None]
    outcome: Mapped[str | None]  # success description or error message
    proposed_at: Mapped[datetime] = mapped_column(default=func.now())
    decided_at: Mapped[datetime | None]  # when approved/rejected
    executed_at: Mapped[datetime | None]
    decided_by: Mapped[str | None]  # "agent" or user email
    expires_at: Mapped[datetime | None]  # 8h after proposal for confirmation_required
    execution_time_ms: Mapped[int | None]
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_agent_actions_status_time", "status", "proposed_at"),
    )
```

#### `agent_proposals` — Pending confirmation-required actions

```python
class AgentProposal(Base):
    __tablename__ = "agent_proposals"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    action_id: Mapped[UUID] = mapped_column(ForeignKey("agent_actions.id"))
    action_name: Mapped[str]
    description: Mapped[str]
    rationale: Mapped[str]
    expected_impact: Mapped[str]
    risk_level: Mapped[str]  # low | medium | high
    recommended_deadline: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    expires_at: Mapped[datetime]  # created_at + 8h
    re_escalated_at: Mapped[datetime | None]  # +4h reminder
    status: Mapped[str] = mapped_column(default="pending")  # pending | approved | rejected | expired
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None]

    action: Mapped["AgentAction"] = relationship()
```


#### `agent_heartbeats` — Agent self-monitoring

```python
class AgentHeartbeat(Base):
    __tablename__ = "agent_heartbeats"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    recorded_at: Mapped[datetime] = mapped_column(index=True, default=func.now())
    overall_status: Mapped[str]  # HEALTHY | DEGRADED | ERROR
    execution_time_ms: Mapped[int]
    memory_rss_mb: Mapped[float]
    cpu_time_ms: Mapped[float]
    db_connected: Mapped[bool]
    redis_connected: Mapped[bool]
    task_queue_connected: Mapped[bool]
    metrics_collection_ok: Mapped[bool]
    alert_delivery_ok: Mapped[bool]
    details_json: Mapped[dict | None] = mapped_column(JSONB)
```

#### `agent_economic_snapshots` — Daily economic data

```python
class AgentEconomicSnapshot(Base):
    __tablename__ = "agent_economic_snapshots"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    snapshot_date: Mapped[date] = mapped_column(unique=True, index=True)
    total_llm_cost: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    total_infrastructure_cost: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    total_proxy_cost: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    total_revenue: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    gross_margin_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    per_client_breakdown_json: Mapped[dict] = mapped_column(JSONB)  # {client_id: ClientCost}
    per_avatar_breakdown_json: Mapped[dict] = mapped_column(JSONB)  # {avatar_id: AvatarCost}
    optimization_suggestions_json: Mapped[list | None] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(default=func.now())
```

#### `agent_weekly_reports` — Stored weekly reports

```python
class AgentWeeklyReport(Base):
    __tablename__ = "agent_weekly_reports"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    report_week_start: Mapped[date] = mapped_column(index=True)  # Monday of reporting week
    report_markdown: Mapped[str]  # Full Markdown content
    metrics_json: Mapped[dict] = mapped_column(JSONB)  # Structured WoW comparisons
    fleet_status_json: Mapped[dict] = mapped_column(JSONB)
    economic_projections_json: Mapped[dict] = mapped_column(JSONB)
    scaling_assessment_json: Mapped[dict | None] = mapped_column(JSONB)
    recommendations_json: Mapped[list | None] = mapped_column(JSONB)
    generated_at: Mapped[datetime] = mapped_column(default=func.now())
    delivered_at: Mapped[datetime | None]
```


#### `agent_config` — Runtime configuration overrides

```python
class AgentConfig(Base):
    __tablename__ = "agent_config"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(unique=True, index=True)
    value: Mapped[str]
    value_type: Mapped[str]  # int | float | bool | str | json
    description: Mapped[str | None]
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
```

### Redis Key Schema

All agent keys use `ramp:agent:` prefix for namespace isolation.

| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `ramp:agent:heartbeat` | STRING (ISO datetime) | 300s | Last heartbeat timestamp |
| `ramp:agent:health_score` | STRING (int) | 120s | Current composite health score |
| `ramp:agent:alerts` | LIST | — | Alert delivery queue (LPUSH/RPOP) |
| `ramp:watchdog:alerts` | LIST | — | Watchdog alert queue (LPUSH/RPOP) |
| `ramp:agent:silence_until` | STRING (ISO datetime) | auto | Alert suppression end time |
| `ramp:agent:metrics:{category}:{name}` | STRING (JSON) | 120s | Latest metric value cache |
| `ramp:agent:cooldown:{alert_type}:{entity_id}` | STRING | variable | Alert dedup cooldown |
| `ramp:agent:lock:{action_name}` | STRING | 60s | Action execution lock |
| `ramp:agent:concurrency_level` | STRING (int) | — | Current worker concurrency |
| `ramp:agent:telegram:last_delivery` | STRING (ISO datetime) | — | Telegram connectivity tracking |


### Metric Retention Strategy

| Granularity | Retention | Storage |
|-------------|-----------|---------|
| Raw samples (60s intervals) | 24 hours | `agent_metrics` table |
| 5-minute aggregates | 7 days | `agent_metrics` (aggregated rows, `metadata_json.aggregated=true`) |
| Daily summaries | 90 days | `agent_economic_snapshots` + `agent_metrics` daily rows |
| Weekly reports | Indefinite | `agent_weekly_reports` |

Aggregation runs daily at 01:00 — rolls raw samples (>24h) into 5-min averages, deletes raw.
Weekly cleanup at Sunday 02:00 — rolls 5-min aggregates (>7d) into daily summaries, deletes 5-min.

### New API Endpoints

```
# Agent Dashboard
GET  /admin/agent                          — Agent overview page
GET  /admin/agent/health-map               — Component health map
GET  /admin/agent/alerts                   — Alert history (7-day)
GET  /admin/agent/actions                  — Action log (7-day)
GET  /admin/agent/economics                — Cost charts + margin
GET  /admin/agent/reports                  — Weekly reports archive
GET  /admin/agent/config                   — Configuration editor
POST /admin/agent/config                   — Save configuration

# Agent Widget API (HTMX partials)
GET  /admin/agent/widget/health-score      — Health score badge (polled every 60s)
GET  /admin/agent/widget/alerts-count      — Active alert count
GET  /admin/agent/widget/actions-recent    — Last 5 actions
GET  /admin/agent/widget/cost-today        — Today's cost vs budget

# Proposal Actions
POST /admin/agent/proposals/{id}/approve   — Approve confirmation_required
POST /admin/agent/proposals/{id}/reject    — Reject confirmation_required

# Agent Self-Diagnostic
GET  /api/agent/diagnostic                 — Self-diagnostic endpoint (JSON)

# Telegram Bot Webhook (if using webhook mode)
POST /api/agent/telegram/webhook           — Telegram update webhook
```


### Telegram Bot Design

**Library**: `python-telegram-bot` v21+ (async, Manifest V3 compatible)

**Deployment**: Standalone systemd service on host OS (not inside Docker), using long-polling mode (not webhook) to avoid needing public HTTPS endpoint for the bot.

**Command Set**:

| Command | Response | Authority |
|---------|----------|-----------|
| `/status` | Health score, system state, worker count, last scrape time | Read-only |
| `/cost` | Today's LLM spend + infra spend, budget remaining | Read-only |
| `/fleet` | Per-client: active avatars, frozen avatars, unhealthy count | Read-only |
| `/approve {id}` | Executes proposed action, returns result | Write (auth required) |
| `/reject {id}` | Rejects proposed action, records decision | Write (auth required) |
| `/silence {duration}` | Suppresses non-critical alerts for duration | Write (auth required) |
| `/alerts` | List open alerts (last 5, severity-ordered) | Read-only |
| `/help` | Command reference | Read-only |

**Authentication**: Telegram user_id checked against `agent_config[telegram_owner_id]`. All commands from non-matching IDs are silently dropped (no information disclosure).

**Message Format** (daily briefing example):
```
🟢 RAMP Daily — Jul 1, 2026

Health: 85/100
Clients: 5 active | Avatars: 18 active
Posts (24h): 12 | Errors: 0
LLM cost: $1.23 | Rev/Cost: 4.2x

🤖 Actions taken:
• Rotated logs (disk was 82%)
• Retried failed EPG build for Hot-Thought2408
• Froze NotSoDelgado88 (3 consecutive failures)

📋 Pending (1):
• Unfreeze connor_lloyd — /approve abc123

All systems nominal. ✅
```


### External Watchdog Design

#### Systemd Units

```ini
# /etc/systemd/system/ramp-watchdog.timer
[Unit]
Description=RAMP Watchdog Timer

[Timer]
OnBootSec=30
OnUnitActiveSec=30

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/ramp-watchdog.service
[Unit]
Description=RAMP Watchdog Check
After=network.target

[Service]
Type=oneshot
ExecStart=/opt/ramp-watchdog/venv/bin/python /opt/ramp-watchdog/watchdog.py
TimeoutSec=25
User=root

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/ramp-telegram-bot.service
[Unit]
Description=RAMP Telegram Bot
After=network.target

[Service]
Type=simple
ExecStart=/opt/ramp-watchdog/venv/bin/python /opt/ramp-watchdog/telegram_bot.py
Restart=always
RestartSec=10
User=root
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

#### Watchdog Check Chain

```python
CHECKS = [
    DockerHealthCheck(),      # docker ps, check all containers "healthy"
    HealthEndpointCheck(),    # GET http://localhost/health, expect 200 + valid JSON
    RedisHeartbeatCheck(),    # GET ramp:heartbeat:last_at, age < 180s
    PostgresConnCheck(),      # SELECT 1 via psycopg2
    PipelineOutputCheck(),    # last_scraped_at < 12h (if scrape_enabled)
    DiskSpaceCheck(),         # df /, alert if > 90%
]
```

#### Auto-Recovery Actions (Watchdog-Level)

The watchdog can perform limited recovery before alerting:

1. **Container restart**: If a container is unhealthy, run `docker compose restart {service}`. Alert only if restart fails or container unhealthy again within 5 min.
2. **Docker daemon restart**: If Docker daemon is unresponsive, run `systemctl restart docker`. Alert immediately regardless of outcome.
3. **Escalation**: If recovery fails or critical condition persists > 5 min, push alert to Telegram.


### Health Score Computation

```python
def compute_health_score(metrics: MetricSnapshot) -> int:
    """Weighted composite score 0-100.

    Infrastructure (40%):
      - CPU utilization (inverted): 100 - cpu_pct
      - Memory utilization (inverted): 100 - mem_pct
      - Disk utilization (inverted): 100 - disk_pct
      - DB connection pool headroom: (max - used) / max * 100
      - Redis memory headroom: (max - used) / max * 100
      - Container health: all_healthy ? 100 : 0
      - Worker responsiveness: all_heartbeat_fresh ? 100 : 0

    Pipeline (35%):
      - Scrape freshness: pct_subreddits_fresh
      - Scoring throughput: scored_24h > 0 ? 100 : 0
      - Generation throughput: generated_24h > 0 ? 100 : 0
      - Posting success rate: success_rate_24h * 100
      - Review queue health: depth < 50 ? 100 : max(0, 100 - (depth - 50) * 2)

    Avatar Fleet (25%):
      - Active ratio: active / total * 100
      - Frozen ratio (inverted): (1 - frozen/total) * 100
      - Health distribution: (active_health / total) * 100
      - Phase progression: weighted by phase (higher = better)
    """
    ...
```

### Metric Collection Points

Layer 2 metric collector gathers from:

| Source | Metrics | Method |
|--------|---------|--------|
| Docker API (via socket) | Container status, CPU, memory, restart count | `docker stats --no-stream` parsed |
| PostgreSQL | Connections active, pool usage, longest query, table sizes | `pg_stat_activity` + `pg_stat_user_tables` |
| Redis | Memory used, connected clients, eviction rate, keyspace hits | `INFO` command |
| Celery | Worker count, active tasks, reserved, queue depth | `celery inspect active/reserved/stats` |
| Disk | Usage per mount | `shutil.disk_usage()` |
| System | CPU%, memory%, load average | `psutil` |
| Pipeline (SQL) | Scrape freshness, scoring/generation/posting counts | Existing queries from signal_collector |
| Avatars (SQL) | Frozen count, health distribution, phase breakdown | Existing queries |
| LLM (SQL) | Today's spend, error count, latency | `AIUsageLog` queries |


### Alert Condition Matrix

#### Immediate (deliver within 60s)

| Condition | Alert Type | Detection |
|-----------|-----------|-----------|
| Heartbeat missing 3 intervals (180s) | `pipeline_stopped` | Redis key age check |
| PostgreSQL 3 consecutive connection failures | `database_down` | Connection test in metric collector |
| Redis 3 consecutive connection failures | `cache_down` | Connection test in metric collector |
| Avatar Reddit suspension detected | `avatar_suspended` | Health checker output |
| Disk > 95% | `disk_full` | psutil check |
| 3+ posting failures across 2+ avatars in 10 min | `systemic_posting_failure` | PostingEvent query |

#### Short-Term (deliver within 1h)

| Condition | Alert Type | Detection |
|-----------|-----------|-----------|
| Single avatar 3 consecutive posting failures | `avatar_posting_failure` | PostingEvent query |
| LLM error rate > 10% over 30 min | `llm_degradation` | AIUsageLog query |
| Reddit 429 > 5 times in 15 min | `reddit_rate_limit` | ActivityEvent query |
| Celery queue > 100 pending | `task_backlog` | Celery inspect |
| Single task running > 10 min | `stuck_task` | Celery inspect |
| Scheduled pipeline missed by 15 min | `pipeline_missed` | Beat schedule vs ActivityEvent |

#### Plannable (include in daily briefing)

| Condition | Alert Type | Detection |
|-----------|-----------|-----------|
| Daily LLM cost > 150% of 7-day avg | `cost_spike` | AIUsageLog query |
| Client engagement < 3% over 3 days | `engagement_declining` | Thread/draft ratio |
| Backup overdue > 48h | `backup_overdue` | System check |
| 3+ avatars frozen in one day | `elevated_freeze_rate` | Avatar query |
| SSL cert < 14 days to expiry | `cert_renewal` | SSL check |
| DB storage grew > 10% this week | `storage_growth` | pg_database_size |

#### Trend (include in weekly report)

| Condition | Alert Type | Detection |
|-----------|-----------|-----------|
| Approval rate dropped > 10pp (7d vs 21d) | `quality_declining` | CommentDraft query |
| Cost per client up > 20% MoM | `unit_economics_deteriorating` | Economic snapshot |
| Avg karma growth rate down > 30% | `authority_growth_slowing` | KarmaSnapshot query |
| Frozen-to-active ratio up 5pp for 3 weeks | `fleet_attrition` | Avatar historical query |


### Alert Deduplication & Escalation

```python
COOLDOWN_PERIODS = {
    "immediate": timedelta(minutes=30),
    "short_term": timedelta(minutes=30),
    "plannable": timedelta(hours=24),
    "trend": timedelta(days=7),
}

ESCALATION_RULES = {
    # If same alert fires 3+ times in 24h without resolution → escalate one level
    "short_term": "immediate",
    "plannable": "short_term",
    # Immediate cannot escalate further — add "escalation_ceiling_reached" annotation
}
```

### SBM Property Protection

The agent actively monitors and protects all 10 SBM properties:

| Property | Agent Responsibility | Detection Mechanism |
|----------|---------------------|-------------------|
| P1: Monotonic Progress | Alert when client has 0 output for 48h | Pipeline liveness monitor |
| P2: Recovery Reachability | Alert on avatar frozen > 30d without phase transition | Silent failure detector |
| P3: Cost Proportionality | Alert on cost/slot > $0.20, daily pipeline ceiling | Economics engine |
| P4: Safety Monotonicity | No agent action bypasses phase gates | Authority framework (forbidden) |
| P5: Human Gate Integrity | No agent action auto-approves content | Authority framework (forbidden) |
| P6: Feedback Closure | Alert when posted comments lack karma snapshots | Silent failure detector |
| P7: Isolation Guarantee | No agent action crosses client boundaries | Authority framework invariant |
| P8: Temporal Consistency | Alert on quiet-hours violations | Alert engine |
| P9: Diagnostic Independence | Agent checks never skip frozen/banned avatars | Code design invariant |
| P10: Graceful Degradation | External watchdog survives internal failures | Architecture (Layer 1) |


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*


### Property 1: Health Score Bounded and Weighted

*For any* valid MetricSnapshot containing infrastructure metrics (0-100 per component), pipeline metrics (0-100 per stage), and avatar fleet metrics (0-100 per indicator), the computed Health_Score SHALL always be in the range [0, 100], AND the contribution of infrastructure metrics shall be exactly 40% of the total, pipeline metrics exactly 35%, and avatar fleet metrics exactly 25%.

**Validates: Requirements 1.4**

### Property 2: Component Health State Transitions

*For any* sequence of health check results (pass/fail) for a component, the component SHALL be marked "degraded" if and only if the last 2 consecutive results are failures, AND SHALL be restored to "healthy" if and only if the last 3 consecutive results are successes after being in "degraded" state.

**Validates: Requirements 1.5, 1.6**

### Property 3: Diagnostic Report Completeness

*For any* MetricSnapshot that produces a Health_Score below 70, the generated diagnostic report SHALL list every metric that is below its normal range, and for each such metric SHALL include the current value, the normal range, and the weighted impact on the overall Health_Score.

**Validates: Requirements 1.8**

### Property 4: Metric Fallback with Timeout

*For any* metric source that becomes unavailable at time T, the Health_Score computation SHALL use the last known value for that source for any computation occurring in the interval (T, T+5min], AND SHALL assign a score of 0 for that source for any computation occurring after T+5min.

**Validates: Requirements 1.9**

### Property 5: Alert Deduplication Respects Cooldown

*For any* sequence of alert firings with the same alert_type and affected_entity_id, if an alert was delivered at time T, then all subsequent firings of the same alert within the cooldown period (T + cooldown_duration) SHALL be suppressed and not delivered.

**Validates: Requirements 5.6, 6.7, 7.8, 8.8**


### Property 6: Alert Escalation on Repeated Firing

*For any* alert that fires 3 or more times within a 24-hour window without being resolved, the alert's severity SHALL be escalated one level (short_term → immediate, plannable → short_term), UNLESS the alert is already at "immediate" severity in which case it SHALL NOT escalate further but SHALL receive an "escalation_ceiling_reached" annotation.

**Validates: Requirements 5.8, 5.9**

### Property 7: Authority Classification with Default

*For any* action name, the authority framework SHALL return exactly one of (autonomous, confirmation_required, forbidden). For any action name NOT explicitly listed in the authority matrix, the framework SHALL return "confirmation_required".

**Validates: Requirements 15.1, 15.2, 15.3, 15.4, 15.10**

### Property 8: Forbidden Actions Always Blocked

*For any* action classified as "forbidden" in the authority framework, regardless of the trigger condition or context, the action executor SHALL block execution, log a blocked attempt in the audit log, and return an error indicating the action is forbidden.

**Validates: Requirements 15.5**

### Property 9: Audit Trail Completeness

*For any* agent action (autonomous execution, proposal, approval, rejection, or blocked attempt), an audit log entry SHALL exist containing: timestamp, action name, permission level, affected entity identifier, actor identity, and outcome.

**Validates: Requirements 15.7**

### Property 10: Telegram Command Authentication

*For any* Telegram message received by the bot, if the sender's user_id does not match the configured Platform Owner Telegram ID, the bot SHALL not execute the command, SHALL not return any system information, and SHALL not acknowledge receipt.

**Validates: Requirements 18.7**

### Property 11: Silent Failure Detection Accuracy

*For any* dataset where an avatar has received no pipeline activity (scoring, generation, or posting events) for more than 7 days, AND the avatar is not frozen AND its warming_phase is not 0, the silent failure detector SHALL flag that avatar as an "orphaned avatar" finding.

**Validates: Requirements 21.5**


## Error Handling

### Layer 1 (External Watchdog) — Must Never Crash

| Failure | Handling | Fallback |
|---------|----------|----------|
| Cannot connect to Docker socket | Log warning, report container status "unknown" | Alert via Telegram |
| Cannot reach /health endpoint | Attempt Docker restart of app container | Alert if restart fails |
| Cannot connect to Redis | Check if Redis container is running, restart if needed | Alert directly (bypass Redis queue — use Telegram API directly) |
| Cannot connect to PostgreSQL | Check if DB container is running, restart if needed | Alert directly |
| Telegram API unreachable | Queue alerts in local file (`/opt/ramp-watchdog/pending_alerts.json`) | Retry on next cycle |
| Watchdog script timeout (>25s) | systemd kills process, next timer cycle re-runs | systemd journal logs timeout |
| Python crash in watchdog | systemd logs exit code, next timer cycle re-runs fresh | No state lost (stateless checks) |
| Telegram bot process crash | systemd `Restart=always` with 10s backoff | Auto-restart, alerts queue in Redis |

**Key invariant**: Watchdog script is stateless. Every run is independent. Crash = no data loss.

### Layer 2 (Celery Tasks) — Retry with Degradation

| Failure | Handling | Fallback |
|---------|----------|----------|
| Metric collection timeout (single source) | Skip that source, use last-known (5 min), then score 0 | Log gap in health snapshot |
| Alert delivery failure (Telegram) | Retry 3x with 30s backoff, then email fallback | Log failed delivery |
| Action execution failure | Log failure, mark action as "failed" | If autonomous and fails 2x: escalate to Platform Owner |
| Database connection lost | Task retries with Celery standard retry (3x, exponential) | If all retries fail: agent heartbeat shows DEGRADED |
| Redis unavailable | Tasks fail gracefully (no lock = skip action) | Agent enters DEGRADED state |
| Agent budget exhausted | LLM-dependent operations (briefing analysis) skip | SQL-only fallback for all reporting |

### Layer 3 (Intelligence) — Best Effort

| Failure | Handling | Fallback |
|---------|----------|----------|
| Economics computation fails | Log error, mark day as "partial" | Previous day's data shown on dashboard |
| LLM call for recommendations fails | Skip recommendations section | Template-only briefing |
| Weekly report generation fails | Log error, retry once after 1 hour | Deliver partial report or skip |
| Trend analysis insufficient data | Skip trend, log "insufficient data" | Note in weekly report |

### Cascading Failure Prevention

1. **Agent never blocks pipeline**: All agent tasks run at low Celery priority. Pipeline tasks (scoring, generation) always take precedence.
2. **Agent budget isolation**: Agent LLM calls use the existing `cost_governor.py` ($1/day cap). Agent never consumes pipeline LLM budget.
3. **Agent action rollback**: Every autonomous action has a rollback plan logged. If action fails, rollback is attempted once.
4. **Watchdog independence**: Layer 1 has zero dependency on Layer 2/3. If Celery dies, watchdog still detects and alerts.


## Testing Strategy

### Dual Testing Approach

**Unit Tests (pytest)**: Specific examples, edge cases, integration points.
**Property Tests (hypothesis)**: Universal properties across all inputs.

Both are complementary — unit tests catch specific bugs, property tests verify general correctness.

### Property-Based Testing Configuration

- **Library**: Hypothesis (Python)
- **Minimum iterations**: 100 per property test
- **Tag format**: `# Feature: ramp-operations-agent, Property {N}: {text}`

### Property Tests

| Property | Module Under Test | Generator Strategy |
|----------|-------------------|-------------------|
| 1: Health score bounded | `health_score.py` | Random MetricSnapshot with values 0-100 per component |
| 2: State transitions | `component_health.py` | Random sequences of pass/fail check results |
| 3: Diagnostic completeness | `diagnostic.py` | Random MetricSnapshot where score < 70 |
| 4: Metric fallback | `health_score.py` | Random metric histories with timestamp gaps |
| 5: Alert dedup | `alert_engine.py` | Random alert sequences with timestamps |
| 6: Alert escalation | `alert_engine.py` | Random alert histories with resolution status |
| 7: Authority classification | `authority_framework.py` | Random action names (known + unknown) |
| 8: Forbidden blocking | `action_executor.py` | Random forbidden action attempts |
| 9: Audit completeness | `authority_framework.py` | Random action sequences |
| 10: Telegram auth | `telegram_bot.py` | Random user IDs |
| 11: Silent failure detection | `silent_failure_detector.py` | Random avatar datasets with activity gaps |

### Unit Tests

| Area | Test Focus |
|------|-----------|
| Watchdog checks | Each check returns correct status for mocked scenarios |
| Telegram bot commands | Each command produces correct response format |
| Alert conditions | Each alert type triggers on correct threshold (specific examples) |
| Action executor | Each recovery action succeeds/fails correctly with mocked dependencies |
| Economics engine | Cost calculations match expected values for known datasets |
| Briefing format | Telegram message respects 500-word limit, correct markdown |
| Pipeline liveness | Stalled detection for each pipeline stage with known data |
| Config validation | Invalid thresholds rejected, valid ones accepted |

### Integration Tests

| Area | Test Focus |
|------|-----------|
| Metric collection → agent_metrics table | End-to-end collection and storage |
| Alert trigger → Telegram delivery | Full alert lifecycle with mocked Telegram API |
| Proposal → Approve → Execute | Full confirmation_required workflow |
| Health endpoint → watchdog detection | Unhealthy endpoint triggers watchdog alert |
| Daily briefing generation | Full briefing with real (test) database data |

### Test Infrastructure

- **Mocks**: Telegram API, Docker socket, psutil (for system metrics)
- **Fixtures**: Pre-populated `agent_metrics` tables for time-series tests, known alert histories
- **Test database**: Separate test PostgreSQL with seeded metric and alert data
- **Redis**: Real Redis instance (test database 1) for integration tests


## Appendix: Celery Beat Schedule Additions

| Time | Task | Layer | Purpose |
|------|------|-------|---------|
| every 60s | `agent_heartbeat` | L2 | Self-monitoring + dependency checks |
| every 60s | `agent_metric_collector` | L2 | Collect all metrics → agent_metrics |
| every 60s | `agent_alert_evaluator` | L2 | Evaluate immediate + short-term alert conditions |
| every 5 min | `agent_pipeline_liveness` | L2 | Check pipeline stage output freshness |
| every 60 min | `agent_plannable_alerts` | L2 | Evaluate plannable alert conditions |
| 01:00 | `agent_metric_aggregation` | L3 | Roll raw metrics into 5-min aggregates |
| 02:00 | `agent_economics_daily` | L3 | Cost per client, margins, suggestions |
| 03:00 | `agent_silent_failures` | L3 | Silent failure detection |
| Mon 03:00 | `agent_scaling_assessment` | L3 | Capacity model recomputation |
| 08:30 | `agent_daily_briefing` | L3 | Generate + deliver daily briefing |
| Sun 04:00 | `agent_trend_analysis` | L3 | Weekly trend scores |
| Sun 10:00 | `agent_weekly_report` | L3 | Generate + store weekly report |

## Appendix: File Structure (New Code)

```
reddit_saas/app/
├── services/
│   └── agent/
│       ├── __init__.py
│       ├── health_score.py          # Health score computation
│       ├── component_health.py      # Component state machine (degraded/healthy)
│       ├── metric_collector.py      # Metric collection from all sources
│       ├── alert_engine.py          # Alert evaluation, dedup, escalation, delivery
│       ├── alert_conditions.py      # Alert condition definitions (all tiers)
│       ├── action_executor.py       # Autonomous action handlers
│       ├── authority_framework.py   # Permission classification + enforcement
│       ├── pipeline_liveness.py     # Pipeline stage liveness detection
│       ├── economics_engine.py      # Cost analysis + optimization suggestions
│       ├── silent_failure_detector.py # Silent failure detection
│       ├── briefing_service.py      # Daily/weekly report generation
│       ├── scaling_intelligence.py  # Capacity model + projections
│       ├── telegram_delivery.py     # Message formatting + Redis queue push
│       └── diagnostic.py           # Diagnostic report generation
├── models/
│   ├── agent_metric.py
│   ├── agent_alert.py
│   ├── agent_action.py
│   ├── agent_proposal.py
│   ├── agent_heartbeat.py
│   ├── agent_economic_snapshot.py
│   ├── agent_weekly_report.py
│   └── agent_config.py
├── tasks/
│   └── agent.py                    # All agent Celery tasks
├── routes/
│   └── admin_agent.py              # /admin/agent/* routes
└── templates/
    ├── admin_agent.html            # Agent dashboard
    ├── admin_agent_health_map.html # Health map view
    └── partials/
        └── agent/                  # HTMX partials for agent widgets
            ├── health_score.html
            ├── alerts_count.html
            ├── actions_recent.html
            ├── cost_today.html
            └── proposal_card.html

/opt/ramp-watchdog/                 # External watchdog (host OS)
├── watchdog.py
├── telegram_bot.py
├── config.yaml
├── requirements.txt
└── install.sh
```

## Appendix: Migration Plan

### Database Migration (`agent01`)

Creates all 7 new tables:
- `agent_metrics`
- `agent_alerts`
- `agent_actions`
- `agent_proposals`
- `agent_heartbeats`
- `agent_economic_snapshots`
- `agent_weekly_reports`
- `agent_config`

Indexes optimized for time-range queries (most queries filter by `collected_at` or `triggered_at`).

### Deployment Order

1. **Phase 1a**: Deploy watchdog to host OS (zero risk — independent of app)
2. **Phase 1b**: Deploy Telegram bot to host OS (zero risk — read-only initially)
3. **Phase 1c**: Deploy enhanced `/health` endpoint (low risk — additive)
4. **Phase 1d**: Deploy pipeline liveness monitor (low risk — alert only)
5. **Phase 2a**: Deploy authority framework + action executor (medium risk — actions are reversible)
6. **Phase 2b**: Deploy alert engine (medium risk — notification only)
7. **Phase 3**: Deploy economics + silent failure detection (low risk — analysis only)
8. **Phase 4**: Deploy briefings + weekly reports + scaling (low risk — reporting only)

Each phase is independently deployable and provides value without requiring subsequent phases.
