# Design Document: AI Cost Optimization

## Overview

This feature spans four independent subsystems that share the `/admin/ai-costs` page as their primary presentation layer and the `ai_usage_log` table as their data source:

1. **Cost Smoothing Scheduler** — Replaces Tue+Fri GEO batch with daily rotation
2. **Model Migration Service** — Decouples editing/persona model selection from generation
3. **Unit Economics Calculator** — Computes per-client cost breakdown for pricing
4. **AI Costs Dashboard Redesign** — Hierarchical layout with budget health, anomalies, and JSON API

All components integrate into the existing stack: FastAPI routes, SQLAlchemy models, Jinja2+HTMX templates, Celery tasks, and the centralized `call_llm()` + `log_ai_usage()` pipeline.

## Architecture

The system uses a layered approach:
- **Data Layer:** `ai_usage_log` table (existing) + `geo_prompts.last_executed_at` (new column)
- **Service Layer:** Four new services (geo_scheduler, budget_health, anomaly_detector, unit_economics) + modifications to generation.py
- **Presentation Layer:** Redesigned admin_ai_costs.html template + new JSON API endpoint
- **Scheduling Layer:** Modified Celery Beat schedule (daily GEO + daily economics computation)

All LLM interactions continue through the centralized `call_llm()` + `log_ai_usage()` pipeline. No new models or tables are needed — the feature leverages existing `ai_usage_log` data with new analytical services on top.

## Components and Interfaces

### 1. Cost Smoothing Scheduler

**Location:** `app/services/geo_scheduler.py` (new)

**Algorithm:** Round-robin with freshness priority.

```python
def select_daily_prompts(db: Session, client_id: UUID) -> list[GeoPrompt]:
    """Select prompts for today's GEO batch.
    
    Strategy:
    1. Get all active prompts for client
    2. Sort by last_executed_at ASC (oldest first, NULL = never run = highest priority)
    3. Take ceil(total / 7) prompts
    4. Prioritize prompts that failed in previous batch (failed_at > last_executed_at)
    """
    active_prompts = get_active_prompts(db, client_id)
    n = len(active_prompts)
    daily_target = math.ceil(n / 7)
    
    # Sort: failed prompts first, then by staleness
    prompts_sorted = sorted(active_prompts, key=lambda p: (
        0 if is_failed_priority(p) else 1,  # failed from yesterday first
        p.last_executed_at or datetime.min,   # oldest execution first
    ))
    
    return prompts_sorted[:daily_target]
```

**Data Model Change:** Add `last_executed_at` column to `geo_prompts` table.

```python
# Migration: aico01_geo_prompt_last_executed.py
# Add to GeoPrompt model:
last_executed_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True), nullable=True, index=True
)
```

**Beat Schedule Change** in `app/tasks/beat_app.py`:

```python
# REMOVE:
"geo-monitoring-scheduled": {
    "task": "run_geo_monitoring_all_clients",
    "schedule": crontab(hour=9, minute=30, day_of_week="tuesday,friday"),
},

# REPLACE WITH:
"geo-monitoring-daily-rotation": {
    "task": "run_geo_daily_rotation",
    "schedule": crontab(hour=9, minute=30),  # daily at 09:30
},
```

**New Celery Task:** `app/tasks/geo_monitoring.py`

```python
@celery_app.task(name="run_geo_daily_rotation")
def run_geo_daily_rotation():
    """Run daily GEO rotation for all enabled clients."""
    with get_db_session() as db:
        clients = get_geo_enabled_clients(db)
        for client in clients:
            prompts = select_daily_prompts(db, client.id)
            execute_geo_batch_for_prompts(db, client, prompts)
            # Update last_executed_at for successful prompts
            for p in prompts:
                if p.execution_succeeded:
                    p.last_executed_at = datetime.now(timezone.utc)
            db.commit()
```

**Integration with existing `geo_query_runner.py`:** The new task calls `execute_geo_batch_for_prompts()` which wraps the existing multi-provider execution logic from `run_geo_for_client()` but operates on a subset of prompts rather than all active prompts.

---

### 2. Model Migration Service

**Location:** Changes to `app/services/generation.py` and `app/services/settings.py`

**New DB Settings:**

```python
# In DEFAULT_SETTINGS (app/services/settings.py):
"llm_editing_model": "gemini/gemini-2.5-flash",
"llm_persona_model": "gemini/gemini-2.5-flash",
```

**Code Changes in `app/services/generation.py`:**

```python
# BEFORE (editing uses generation model):
model = get_config("llm_generation_model")

# AFTER (editing uses dedicated setting):
model = get_config("llm_editing_model")

# BEFORE (persona selection uses generation model):  
model = get_config("llm_generation_model")

# AFTER (persona uses dedicated setting):
model = get_config("llm_persona_model")
```

**Fallback Chain:** `gemini/gemini-2.5-flash` already has a fallback entry in `MODEL_FALLBACK_CHAIN`:
```python
"gemini/gemini-2.5-flash": ["gemini/gemini-2.5-flash-lite"],
```

**Cost Impact:** Editing moves from $15/1M output (Claude Sonnet) to $0.60/1M output (Gemini Flash) = 25× reduction. Persona selection same savings.

---

### 3. Unit Economics Calculator

**Location:** `app/services/unit_economics.py` (new)

**Data Model:**

```python
@dataclass
class UnitEconomics:
    """Per-client cost breakdown for pricing decisions."""
    client_name: str
    client_id: UUID
    avatar_count: int
    
    # Component costs (30-day rolling)
    pipeline_cost: float      # scoring + generation + editing + persona + hobby
    geo_share: float          # client_prompts / total_prompts * total_geo_cost
    infra_share: float        # fixed_monthly_infra / active_client_count
    
    # Derived metrics
    total_monthly: float      # pipeline + geo_share + infra_share
    per_avatar: float         # total / avatar_count
    per_draft: float          # total / drafts_generated_30d
    
    # Projections for 1/2/3 avatar configurations
    cost_1_avatar: float
    cost_2_avatar: float
    cost_3_avatar: float
```

**Computation Logic:**

```python
def compute_unit_economics(db: Session) -> list[UnitEconomics]:
    """Compute unit economics for all active clients.
    
    Uses rolling 30-day window from ai_usage_log.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    
    # 1. Pipeline cost per client (actual spend)
    pipeline_costs = (
        db.query(
            AIUsageLog.client_id,
            func.sum(AIUsageLog.cost_usd).label("cost")
        )
        .filter(AIUsageLog.created_at >= cutoff)
        .filter(AIUsageLog.operation.in_(PIPELINE_OPERATIONS))
        .group_by(AIUsageLog.client_id)
        .all()
    )
    
    # 2. GEO cost allocation (proportional by prompt count)
    total_geo_cost = get_total_geo_cost(db, cutoff)
    client_prompt_counts = get_client_prompt_counts(db)
    total_prompts = sum(client_prompt_counts.values())
    
    # 3. Infrastructure share (from system_settings)
    monthly_infra = float(get_setting(db, "monthly_infra_cost") or "25.0")
    active_clients = get_active_client_count(db)
    infra_per_client = monthly_infra / max(active_clients, 1)
    
    # 4. Per-avatar cost derivation
    # For N-avatar projections: scale pipeline cost linearly with avatar count
    # (scoring + generation scale per avatar; GEO and infra don't)
    ...
```

**Pipeline Operations Grouping:**

```python
PIPELINE_OPERATIONS = [
    "scoring", "scoring_batch",
    "generation", "editing", "persona_select",
    "hobby_comment_epg", "hobby_comment_pipeline", "hobby_comment_workflow",
    "post_topic", "post_brief", "post_generation",
]

GEO_OPERATIONS = ["geo_query"]
```

**Daily Update:** Celery task runs at 03:00 to refresh cached economics. Results stored in `system_settings` as JSON for fast page load (avoid recomputing on every page view).

```python
# beat_app.py entry:
"compute-unit-economics-daily": {
    "task": "compute_unit_economics_daily",
    "schedule": crontab(hour=3, minute=0),
},
```

---

### 4. AI Costs Dashboard Redesign

#### 4.1 Budget Health Indicator

**Location:** `app/services/budget_health.py` (new)

```python
@dataclass
class ProviderBudgetHealth:
    """Budget health status for a single provider."""
    provider: str           # anthropic, gemini, perplexity, openai
    display_name: str       # "Anthropic", "Google/Gemini", etc.
    spent_this_month: float
    monthly_limit: float
    pct_used: float         # spent / limit * 100
    projected_month_end: float  # (spent / days_elapsed) * days_in_month
    state: str              # "healthy" | "warning" | "danger"


def compute_budget_health(db: Session) -> list[ProviderBudgetHealth]:
    """Compute budget health for all providers.
    
    Reads limits from system_settings:
      budget_anthropic, budget_gemini, budget_perplexity, budget_openai
    
    Reads spend from ai_usage_log filtered to current month,
    grouped by provider prefix extracted from model field.
    """
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    days_elapsed = max((now - month_start).days, 1)
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    
    # Query spend per provider prefix
    provider_spend = get_spend_by_provider(db, month_start)
    
    results = []
    for provider, config in PROVIDER_CONFIGS.items():
        limit = float(get_setting(db, f"budget_{provider}") or config.default_limit)
        spent = provider_spend.get(provider, 0.0)
        projected = (spent / days_elapsed) * days_in_month
        pct = (projected / limit * 100) if limit > 0 else 0
        
        if pct >= 90:
            state = "danger"
        elif pct >= 70:
            state = "warning"
        else:
            state = "healthy"
        
        results.append(ProviderBudgetHealth(
            provider=provider,
            display_name=config.display_name,
            spent_this_month=spent,
            monthly_limit=limit,
            pct_used=pct,
            projected_month_end=projected,
            state=state,
        ))
    return results
```

**Provider-to-model mapping:**

```python
PROVIDER_PREFIXES = {
    "anthropic": ["anthropic/", "bedrock/anthropic"],
    "gemini": ["gemini/"],
    "perplexity": ["perplexity/"],
    "openai": ["openai/"],
}
```

#### 4.2 Anomaly Detector

**Location:** `app/services/anomaly_detector.py` (new)

```python
@dataclass
class CostAnomaly:
    """A detected cost spike day."""
    date: date
    total_cost: float
    rolling_avg: float       # 7-day avg EXCLUDING this day
    ratio: float             # total_cost / rolling_avg
    top_operation: str       # highest-cost operation that day
    top_provider: str        # highest-cost provider that day


def detect_anomalies(db: Session, lookback_days: int = 30) -> list[CostAnomaly]:
    """Detect anomaly days in the cost timeline.
    
    Algorithm:
    1. Get daily costs for last N days
    2. For each day, compute 7-day rolling average (excluding current day)
    3. If day_cost > 3 * rolling_avg → flag as anomaly
    4. Attribute anomaly to top operation and provider
    """
    daily_costs = get_daily_cost_series(db, lookback_days)
    anomalies = []
    
    for i, (day, cost) in enumerate(daily_costs):
        # Get previous 7 days (excluding current)
        window_start = max(0, i - 7)
        window = [c for j, (_, c) in enumerate(daily_costs[window_start:i]) 
                  if j != i]
        
        if len(window) < 3:  # need at least 3 days for meaningful average
            continue
        
        avg = sum(window) / len(window)
        if avg > 0 and cost > 3 * avg:
            top_op, top_provider = get_top_contributors(db, day)
            anomalies.append(CostAnomaly(
                date=day,
                total_cost=cost,
                rolling_avg=avg,
                ratio=cost / avg,
                top_operation=top_op,
                top_provider=top_provider,
            ))
    
    return anomalies
```

#### 4.3 Hierarchical Page Layout

**Template:** `app/templates/admin_ai_costs.html` (rewrite)

```
┌─────────────────────────────────────────────────────────────────┐
│ HERO SECTION                                                     │
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌──────────┐  │
│ │Period $ │ │Daily Avg│ │Projected│ │API Calls│ │  Tokens  │  │
│ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └──────────┘  │
│                                                                   │
│ Budget Health Cards (per provider: Anthropic | Gemini | etc.)    │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐             │
│ │ Anthropic    │ │ Gemini       │ │ Perplexity   │             │
│ │ $12/$50 24%  │ │ $3/$300 1%   │ │ $2/∞         │             │
│ │ ████░░░░ OK │ │ █░░░░░░░ OK │ │ ░░░░░░░░ OK  │             │
│ └──────────────┘ └──────────────┘ └──────────────┘             │
│                                                                   │
│ Unit Economics ($/client/month for 1/2/3 avatars)               │
├─────────────────────────────────────────────────────────────────┤
│ STAGE BREAKDOWN (stacked bar chart — always visible)             │
│ [Discovery|Scoring|Content|Hobby|Posts|GEO|Other]                │
│ Click segment → filters detail below                             │
├─────────────────────────────────────────────────────────────────┤
│ PROVIDER DETAIL (burn rate cards per provider)                   │
│ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐       │
│ │ Anthropic      │ │ Gemini         │ │ Perplexity     │       │
│ │ $X spent       │ │ $Y spent       │ │ $Z spent       │       │
│ │ $D/day avg     │ │ $D/day avg     │ │ $D/day avg     │       │
│ │ ▲12% vs prev  │ │ ▼5% vs prev   │ │ →0% vs prev   │       │
│ └────────────────┘ └────────────────┘ └────────────────┘       │
├─────────────────────────────────────────────────────────────────┤
│ DRILL-DOWN SECTIONS (collapsed <details> by default)             │
│ ▶ Cost Timeline (daily chart + anomaly highlights)               │
│ ▶ By Operation                                                   │
│ ▶ By Client                                                      │
│ ▶ By Model                                                       │
│ ▶ By Avatar                                                      │
│ ▶ Recent Calls                                                   │
└─────────────────────────────────────────────────────────────────┘
```

**Anomaly highlighting:** In the cost timeline chart (Chart.js), anomaly days get a red point marker and tooltip showing ratio + top contributor. The timeline data includes an `anomalies` array that Chart.js uses for conditional styling.

**Stacked bar interaction:** HTMX `hx-get` on click sends `?stage=Content` parameter. Detail tables reload filtered to that stage's operations.

#### 4.4 RAMP Agent JSON API

**Location:** `app/routes/admin.py` (new endpoint)

```python
@router.get("/api/admin/ai-costs", response_class=JSONResponse)
def api_ai_costs(
    request: Request,
    current_user: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
    period: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """JSON API for RAMP Operations Agent consumption.
    
    Returns structured cost intelligence:
    - Budget health per provider
    - Anomaly detection results
    - Unit economics
    - Period summary
    """
    days = _parse_period(period, date_from, date_to)
    
    return {
        "total_month": summary.total_cost,
        "daily_avg": summary.daily_avg,
        "projected_month": summary.monthly_projection,
        "per_provider": [
            {
                "name": h.provider,
                "spent": h.spent_this_month,
                "limit": h.monthly_limit,
                "pct": h.pct_used,
            }
            for h in budget_health
        ],
        "anomalies": [
            {
                "date": a.date.isoformat(),
                "cost": a.total_cost,
                "avg": a.rolling_avg,
                "ratio": a.ratio,
                "top_operation": a.top_operation,
            }
            for a in anomalies
        ],
        "unit_economics": {
            "per_client_1av": economics.cost_1_avatar,
            "per_client_2av": economics.cost_2_avatar,
            "per_client_3av": economics.cost_3_avatar,
            "per_avatar": economics.per_avatar,
            "per_draft": economics.per_draft,
        },
    }
```

**Authentication:** Uses `require_business_admin` which accepts `owner` and `partner` roles — same access level as the AI Costs HTML page.

---

## Data Models

### New Columns

| Table | Column | Type | Purpose |
|-------|--------|------|---------|
| `geo_prompts` | `last_executed_at` | `DateTime(tz)` | Track prompt freshness for rotation |

### New System Settings

| Key | Default | Purpose |
|-----|---------|---------|
| `llm_editing_model` | `gemini/gemini-2.5-flash` | Dedicated editing model |
| `llm_persona_model` | `gemini/gemini-2.5-flash` | Dedicated persona model |
| `budget_anthropic` | `50` | Monthly Anthropic budget ($) |
| `budget_gemini` | `300` | Monthly Gemini budget ($) |
| `budget_perplexity` | `20` | Monthly Perplexity budget ($) |
| `budget_openai` | `50` | Monthly OpenAI budget ($) |
| `monthly_infra_cost` | `25` | Monthly infra cost for unit economics |
| `unit_economics_cache` | `{}` | Cached unit economics JSON |

### Migration: `aico01`

```python
"""AI Cost Optimization — schema changes."""

def upgrade():
    # Add last_executed_at to geo_prompts
    op.add_column("geo_prompts", sa.Column(
        "last_executed_at", sa.DateTime(timezone=True), nullable=True
    ))
    op.create_index("ix_geo_prompts_last_executed", "geo_prompts", ["last_executed_at"])
```

---

## Error Handling

### GEO Daily Rotation Failures

- **Provider timeout:** Mark prompt as failed (don't update `last_executed_at`). Prioritize in next day's batch.
- **All providers fail for a prompt:** Log `geo_rotation_prompt_failed` activity event. Prompt bubbles to top priority next day.
- **Task-level failure:** If the entire Celery task crashes, the distributed lock releases (TTL=1800s). Next daily run retries. No prompts marked as executed (DB transaction rolled back).
- **Partial batch failure:** Successful prompts get `last_executed_at` updated; failed ones don't. This naturally prioritizes them next day.

### Model Migration Failures

- **Gemini Flash unavailable:** Standard `MODEL_FALLBACK_CHAIN` routes `gemini/gemini-2.5-flash` → `gemini/gemini-2.5-flash-lite`. If that also fails, `call_llm()` raises `litellm.exceptions.ServiceUnavailableError`.
- **Quality regression:** If Gemini Flash editing produces lower quality, admin changes `llm_editing_model` back to Claude in DB settings — no deploy needed.

### Budget Health Edge Cases

- **No spend data for current month (day 1):** `days_elapsed = 1`, projection = `day1_spend * days_in_month`. May be volatile — UI shows "Insufficient data" note for first 3 days of month.
- **Budget setting missing:** Default to a generous limit ($300) to avoid false danger states.
- **Provider not used this month:** Show $0 spent, 0% used, "healthy" state.

### Anomaly Detection Edge Cases

- **First 7 days of data:** Not enough history for rolling average. Skip anomaly detection for first 7 days.
- **Zero-cost days in window:** Include in average (legitimate signal that spend dropped).
- **Single massive spike:** Correctly detected since rolling_avg stays low from previous normal days.

---

## Integration Points

### Existing Services Modified

| File | Change |
|------|--------|
| `app/services/generation.py` | Read `llm_editing_model` and `llm_persona_model` from DB settings instead of `llm_generation_model` |
| `app/services/settings.py` | Add new default settings to `DEFAULT_SETTINGS` |
| `app/services/admin.py` | Add `get_ai_costs_by_provider()` function for per-provider grouping |
| `app/services/ai.py` | Ensure `gemini/gemini-2.5-flash` exists in `MODEL_COSTS` (already present) |
| `app/tasks/beat_app.py` | Replace Tue+Fri GEO schedule with daily + add unit economics task |
| `app/tasks/geo_monitoring.py` | Add `run_geo_daily_rotation` task alongside existing `run_geo_monitoring_all_clients` |
| `app/routes/admin.py` | Extend `admin_ai_costs` route context + add JSON API endpoint |
| `app/templates/admin_ai_costs.html` | Full redesign to hierarchical layout |
| `app/models/geo_prompt.py` | Add `last_executed_at` column |

### New Services

| File | Purpose |
|------|---------|
| `app/services/geo_scheduler.py` | Daily rotation prompt selection logic |
| `app/services/budget_health.py` | Per-provider budget status computation |
| `app/services/anomaly_detector.py` | Cost spike detection algorithm |
| `app/services/unit_economics.py` | Per-client cost breakdown calculation |

---

## Performance Considerations

- **Unit Economics computation** runs daily (03:00) and caches results in `system_settings`. Page load reads cached JSON — no heavy query on every page view.
- **Anomaly detection** runs on page load but operates on pre-aggregated daily totals (max 90 rows for 90-day lookback). Sub-100ms.
- **Budget health** queries current month data grouped by model prefix. Single query, indexed on `created_at`. Sub-50ms.
- **GEO daily rotation** executes ~6 prompts per client per day (vs ~40 on batch days). Each prompt takes ~5-40s depending on provider. Total daily execution: ~2-4 minutes per client (spread over time, not burst).

---

## Testing Strategy

**Unit tests** cover:
- `geo_scheduler.py` — specific examples of prompt selection with known dates and failure states
- `budget_health.py` — edge cases (day 1 of month, missing settings, zero spend)
- `anomaly_detector.py` — known time series with expected anomaly outputs
- `unit_economics.py` — calculation correctness with fixed test data
- Model migration — verify `get_config()` calls use correct setting keys

**Property-based tests** cover:
- Scheduler rotation coverage (Property 1-3)
- Budget health state classification (Property 6)
- Anomaly detection algorithm (Property 7)
- Unit economics decomposition (Properties 4-5)
- API response schema (Property 8)

**Integration tests** cover:
- GEO daily rotation task end-to-end with mocked providers
- JSON API endpoint authentication and response shape
- Beat schedule verification (daily entry replaces Tue+Fri)

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Prompt rotation guarantees 7-day coverage

*For any* set of N active GEO prompts belonging to a client, running the Cost_Smoothing_Scheduler for 7 consecutive days SHALL result in every prompt being selected for execution at least once.

**Validates: Requirements 1.1**

### Property 2: Daily execution respects capacity ceiling

*For any* client with N active GEO prompts, on any given day the Cost_Smoothing_Scheduler SHALL select at most `ceil(N / 7) + 1` prompts for execution.

**Validates: Requirements 1.2, 1.3**

### Property 3: Failed prompts receive priority in next rotation

*For any* set of prompts where a subset failed execution on day D, running the scheduler on day D+1 SHALL select all failed prompts from day D before selecting any prompt that succeeded on day D (up to the daily capacity ceiling).

**Validates: Requirements 1.7**

### Property 4: Unit economics components sum to total

*For any* client with cost data in the 30-day window, the Unit_Economics_Calculator output SHALL satisfy: `pipeline_cost + geo_share + infra_share = total_monthly` (within floating-point tolerance of ±$0.01).

**Validates: Requirements 5.1**

### Property 5: GEO cost allocated proportionally by prompt count

*For any* distribution of active prompts across clients, the GEO share allocated to client C SHALL equal `(prompts_of_C / total_prompts) * total_geo_cost` (within ±$0.01 tolerance).

**Validates: Requirements 5.6**

### Property 6: Budget health state correctly classified by projection threshold

*For any* provider with a configured monthly limit L, current month spend S, and days_elapsed D in a month of M total days: the projected spend P = (S / D) * M SHALL determine the health state as follows: if P >= 0.9 * L then "danger"; else if P >= 0.7 * L then "warning"; else "healthy".

**Validates: Requirements 6.2, 6.3, 6.4**

### Property 7: Anomaly detection flags days exceeding 3× rolling average

*For any* daily cost time series of length ≥ 8 days, a day with cost C is flagged as an anomaly if and only if C > 3 × mean(costs of the preceding 7 days, excluding day itself). Days with fewer than 3 preceding data points are never flagged.

**Validates: Requirements 8.1, 8.3**

### Property 8: Agent API response contains all required fields

*For any* authenticated request to `/api/admin/ai-costs` with valid period parameters, the JSON response SHALL contain all required top-level keys: `total_month` (number), `daily_avg` (number), `projected_month` (number), `per_provider` (array), `anomalies` (array), `unit_economics` (object with keys `per_client_1av`, `per_client_2av`, `per_client_3av`, `per_avatar`, `per_draft`).

**Validates: Requirements 10.2**
