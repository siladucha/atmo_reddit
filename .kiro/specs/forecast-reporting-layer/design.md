# Forecast & Reporting Layer v1 — Design

## System Architecture (High-Level)

```
┌─────────────────────────────────────────────────────────────────────┐
│                     DATA SOURCES (existing)                          │
├─────────────────────────────────────────────────────────────────────┤
│ GeoQueryResult     │ KarmaSnapshot    │ PerformanceMetric           │
│ GeoFrequencyMetric │ CommentDraft     │ EPGSlot                     │
│ SubredditRiskProfile│ ActivityEvent   │ ExecutionTask               │
│ GeoCompetitor      │ Avatar (health)  │ ClientSubredditAssignment   │
└────────────┬───────┴────────┬─────────┴───────────┬────────────────┘
             │                │                     │
     ┌───────▼───────┐ ┌─────▼──────┐ ┌────────────▼───────────┐
     │ LAYER 1       │ │ LAYER 2    │ │ LAYER 3                │
     │ Observed      │ │ Execution  │ │ Forecast               │
     │ Reality       │ │ Intent     │ │ Engine                 │
     │ Collector     │ │ Snapshot   │ │ (S-curve + Historical) │
     └───────┬───────┘ └─────┬──────┘ └────────────┬───────────┘
             │                │                     │
             └────────────────┼─────────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │ LAYER 4            │
                    │ Report Composer    │
                    │ (structured JSONB) │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │ LAYER 5            │
                    │ Business Impact    │
                    │ Calculator         │
                    └─────────┬──────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
     ┌────────▼──────┐ ┌─────▼─────┐ ┌───────▼──────┐
     │ Client Portal │ │ Demo HTML │ │ PDF Export   │
     │ (live)        │ │ (sales)   │ │ (future)     │
     └───────────────┘ └───────────┘ └──────────────┘
```

---

## Layer 1: Observed Reality Collector

### Metrics Registry

Each metric has: `source`, `validation_method`, `time_window`, `staleness_threshold`.

```python
@dataclass
class ObservedMetric:
    """Single observed data point with provenance."""
    metric_id: str              # e.g. "geo.brand_rate.perplexity"
    value: float
    measured_at: datetime
    time_window: str            # "batch" | "24h" | "7d" | "30d"
    validation: str             # "platform_confirmed" | "api_measured" | "system_counted"
    staleness_threshold_hours: int
    is_stale: bool              # computed: now - measured_at > staleness_threshold
    source_table: str           # for audit trail
    sample_size: int            # how many observations produced this value
    confidence: str             # "high" (n≥20) | "medium" (5≤n<20) | "low" (n<5)
```

### Metrics Catalog (v1)

| Metric ID | Source | Validation | Window | Stale After |
|-----------|--------|-----------|--------|-------------|
| `geo.brand_rate.overall` | GeoQueryResult | api_measured | per-batch | 7d |
| `geo.brand_rate.perplexity` | GeoQueryResult (provider=perplexity) | api_measured | per-batch | 7d |
| `geo.brand_rate.chatgpt` | GeoQueryResult (provider=openai) | api_measured | per-batch | 7d |
| `geo.brand_rate.claude` | GeoQueryResult (provider=anthropic) | api_measured | per-batch | 7d |
| `geo.competitor_rate.{name}` | GeoQueryResult.competitors_mentioned | api_measured | per-batch | 7d |
| `geo.category_rate.{category}` | GeoQueryResult JOIN GeoPrompt.category | api_measured | per-batch | 7d |
| `reddit.karma_avg_7d` | KarmaSnapshot (window=7d) | platform_confirmed | 7d rolling | 48h |
| `reddit.survival_rate_7d` | CommentDraft (posted, !is_deleted) | system_counted | 7d rolling | 48h |
| `reddit.removal_rate_7d` | CommentDraft (posted, is_deleted) | platform_confirmed | 7d rolling | 48h |
| `reddit.reply_depth_avg` | KarmaSnapshot.reply_count | platform_confirmed | 7d rolling | 48h |
| `execution.drafts_generated_7d` | CommentDraft (created_at) | system_counted | 7d | 24h |
| `execution.drafts_posted_7d` | CommentDraft (status=posted) | system_counted | 7d | 24h |
| `execution.posting_success_rate` | posted / (posted+failed) | system_counted | 7d | 24h |
| `execution.avg_karma_per_comment` | KarmaSnapshot (48h window avg) | platform_confirmed | 30d | 7d |
| `authority.high_intent_rate` | CommentDraft JOIN high-intent threads | system_counted | 30d | 7d |
| `authority.citation_count` | GeoQueryResult.reddit_urls_found | api_measured | per-batch | 7d |

### Collection Service

```python
# app/services/forecast/observed_reality.py

class ObservedRealityCollector:
    """Collects all ground-truth metrics for a client."""

    def collect(self, db: Session, client_id: UUID) -> ObservedSnapshot:
        """Returns immutable snapshot of all observed metrics."""
        return ObservedSnapshot(
            collected_at=now_utc(),
            client_id=client_id,
            metrics=self._collect_all(db, client_id),
            data_gaps=self._identify_gaps(db, client_id),
        )

    def _collect_geo_metrics(self, db, client_id) -> list[ObservedMetric]: ...
    def _collect_reddit_metrics(self, db, client_id) -> list[ObservedMetric]: ...
    def _collect_execution_metrics(self, db, client_id) -> list[ObservedMetric]: ...
```

---

## Layer 2: Execution Intent Snapshot

### What Constitutes "Intent"

Intent = system actions that are planned/scheduled but not yet measured as outcomes.

```python
@dataclass
class ExecutionIntent:
    """A planned action that has not yet produced a measured outcome."""
    intent_id: str              # e.g. "epg_slot:{uuid}"
    intent_type: str            # "comment_slot" | "geo_batch" | "phase_progression" | "strategy_update"
    status: str                 # "planned" | "approved" | "scheduled" | "executing" | "expired"
    target_date: datetime       # when it's supposed to happen
    validity_window_days: int   # how far ahead this intent is reliable (7/14/90)
    linked_task_id: UUID | None # FK to EPGSlot / ExecutionTask / etc.
    version: int                # plan version (increments on rebuild)
    created_at: datetime
```

### Intent Categories & Validity Windows

| Category | Source | Validity | Update Frequency |
|----------|--------|----------|-----------------|
| Daily EPG Slots | EPGSlot (status=planned/generated/approved) | 1 day | 2×/day (08:15, 14:15) |
| Pending Drafts | CommentDraft (status=pending/approved) | 3 days | Continuous |
| Scheduled GEO Batches | Celery Beat (Tue+Fri) | 7 days | Static schedule |
| Phase Roadmap | Avatar phase + promotion criteria | 90 days | Evaluated daily 06:00 |
| Strategy Plan | Client.strategy_context | 14 days | On demand |
| Subreddit Coverage | ClientSubredditAssignment (active) | 30 days | On change |

### Intent Versioning

```python
@dataclass
class IntentSnapshot:
    """Point-in-time view of all planned actions."""
    snapshot_version: int
    captured_at: datetime
    client_id: UUID
    daily_plan: list[ExecutionIntent]    # today's EPG
    weekly_plan: list[ExecutionIntent]   # next 7d scheduled
    phase_roadmap: PhaseProjection       # where each avatar is heading
    coverage_plan: list[SubredditCoverage]  # what subs are targeted

    def stale_intents(self) -> list[ExecutionIntent]:
        """Return intents past their validity window."""
        ...
```

### Linkage to Task System

```
Intent status lifecycle:
  planned → approved → scheduled → executing → [measured]
                                              ↗
                            expired (past deadline, never executed)
```

Critical rule: **An intent that reaches "measured" state exits Layer 2 and enters Layer 1.**
Until measured, it stays in Layer 2 and appears only in "Plan" section of reports.

---

## Layer 3: Forecasting Engine

### Model Architecture

The forecast engine computes: "Given observed baseline + planned execution + platform conditions, what is the expected outcome?"

```
Forecast = f(Observed Baseline, Execution Plan, Conversion Rates, Platform Risk)
```

### 3.1 Visibility Forecast (GEO/AEO Growth)

**Model:** Logistic S-curve with per-engine multipliers (already proven in demo).

```python
@dataclass
class VisibilityForecast:
    """Projected brand visibility over time."""
    baseline_rate: float                # from Layer 1 (measured)
    target_weeks: int                   # projection horizon (default: 24)
    scenarios: dict[str, list[float]]   # {"conservative": [...], "expected": [...], "optimistic": [...]}
    per_engine: dict[str, list[float]]  # per-engine projections
    confidence_interval: float          # e.g. 0.68 (1σ) or 0.95 (2σ)
    assumptions: list[str]              # explicit list of what this forecast assumes
    risk_discount: float                # 0.0-1.0, reduces ceiling based on platform risk


class VisibilityForecaster:
    """S-curve projection with per-engine rates and risk discounting."""

    # Priors (updated as data accumulates)
    ENGINE_MULTIPLIERS = {
        "perplexity": 1.4,   # cites Reddit most aggressively
        "chatgpt": 1.0,      # web grounding, less Reddit-specific
        "claude": 0.65,      # newest web search, least Reddit-dependent
    }

    # S-curve parameters
    DEFAULT_CEILING = 40.0        # realistic max after 6mo active Reddit content
    DEFAULT_MIDPOINT = 12         # weeks to inflection
    DEFAULT_STEEPNESS = 0.4
    NOISE_AMPLITUDE = 2.5         # ±pp weekly noise

    def forecast(
        self,
        observed: ObservedSnapshot,
        intent: IntentSnapshot,
        platform_risk: PlatformRiskAssessment,
    ) -> VisibilityForecast:
        baseline = self._get_baseline(observed)
        ceiling = self._compute_ceiling(intent, platform_risk)
        scenarios = self._generate_scenarios(baseline, ceiling)
        return VisibilityForecast(
            baseline_rate=baseline,
            scenarios=scenarios,
            assumptions=self._document_assumptions(observed, intent),
            risk_discount=platform_risk.discount_factor,
            ...
        )

    def _generate_scenarios(self, baseline, ceiling) -> dict:
        return {
            "conservative": self._scurve(baseline, ceiling * 0.7, midpoint=14),
            "expected": self._scurve(baseline, ceiling, midpoint=12),
            "optimistic": self._scurve(baseline, ceiling * 1.2, midpoint=10),
        }
```

### 3.2 Reddit Engagement Forecast

**Model:** Linear regression on historical karma velocity + activity volume multiplier.

```python
@dataclass
class EngagementForecast:
    """Projected Reddit engagement metrics."""
    karma_projection_4w: dict[str, float]   # conservative/expected/optimistic
    survival_rate_projection: float          # expected based on 30d trend
    posting_volume_projection: int           # comments/week based on EPG budget
    high_intent_rate_projection: float       # based on strategy + subreddit mix


class EngagementForecaster:
    """Projects Reddit engagement based on historical response curves."""

    def forecast(
        self,
        observed: ObservedSnapshot,
        intent: IntentSnapshot,
    ) -> EngagementForecast:
        # Use historical karma velocity (karma per comment over time)
        karma_velocity = self._compute_karma_velocity(observed)
        # Planned volume from EPG budget
        planned_volume = self._sum_weekly_budget(intent)
        # Project karma growth = velocity × volume × survival_rate
        ...
```

### 3.3 Platform Risk Assessment

**Factors that discount projections:**

```python
@dataclass
class PlatformRiskAssessment:
    """Quantified platform risk that discounts forecasts."""
    shadowban_probability: float      # 0.0-1.0 per avatar, averaged
    removal_rate_trend: str           # "improving" | "stable" | "degrading"
    subreddit_risk_avg: float         # avg risk_score across active subs
    avatar_health_score: float        # % of avatars in healthy state
    account_age_factor: float         # young accounts = higher risk
    discount_factor: float            # composite: applied to forecast ceiling

    @classmethod
    def compute(cls, observed: ObservedSnapshot, intent: IntentSnapshot) -> Self:
        """Compute risk assessment from observed data."""
        ...
```

### 3.4 Forecast Accuracy Tracking

Every forecast is stored with a `forecast_id`. When actuals are measured, we compare:

```python
@dataclass
class ForecastAccuracy:
    """Comparison of predicted vs actual at each measurement point."""
    forecast_id: UUID
    metric_id: str
    predicted_at: datetime         # when forecast was made
    target_date: datetime          # what date the forecast was for
    predicted_value: float         # what we said would happen
    predicted_scenario: str        # which scenario this was from
    actual_value: float | None     # what actually happened (None if not yet measured)
    error_pp: float | None         # absolute error in percentage points
    within_bounds: bool | None     # was actual within conservative-optimistic range?
```

**Weekly job:** Compare last week's forecasts against this week's actuals.
Feeds back into model parameter adjustment (narrow/widen confidence, adjust multipliers).

---

## Layer 4: Report Composition

### Report Structure (JSONB Schema)

```python
@dataclass
class ClientIntelligenceReport:
    """Structured report separating all truth layers."""

    # Metadata
    report_id: UUID
    client_id: UUID
    generated_at: datetime
    report_period: str               # "2026-W27" (ISO week)
    report_version: int
    data_freshness: dict[str, str]   # {"geo": "2d ago", "karma": "4h ago", ...}

    # LAYER 1 — Observed (📍)
    observed: ObservedSection

    # LAYER 2 — Planned (📋)
    planned: PlannedSection

    # LAYER 3 — Forecasted (📈)
    forecasted: ForecastedSection

    # LAYER 4 — Risks (⚠️)
    risks: RiskSection

    # LAYER 5 — Business Impact (💰)
    business_impact: BusinessImpactSection


@dataclass
class ObservedSection:
    """📍 What actually happened (measured, validated)."""
    label: str = "📍 Observed Results"
    period: str                      # "Jun 23 – Jun 29, 2026"

    # Visibility
    brand_visibility_rate: float     # overall across engines
    per_engine_rates: dict[str, float]  # {"perplexity": 10.0, "claude": 0.0, ...}
    competitor_rates: dict[str, float]  # {"Tel Aviv Uni": 92.3, ...}
    category_rates: dict[str, float]    # {"academic": 10.0, "use_case": 0.0, ...}
    brand_mentions_count: int
    total_queries_measured: int
    engines_active: list[str]

    # Engagement (Reddit)
    comments_posted: int
    avg_karma_per_comment: float
    survival_rate: float             # % not deleted
    high_intent_participation_rate: float
    reply_depth_avg: float

    # Excerpts (proof — most powerful for sales)
    brand_excerpts: list[BrandExcerpt]  # actual AI response text where brand appeared

    # Data quality
    sample_sizes: dict[str, int]     # how many observations per metric
    staleness: dict[str, str]        # "geo: 2d" | "karma: 4h"


@dataclass
class BrandExcerpt:
    """Actual AI response excerpt where brand was mentioned."""
    engine: str                      # "perplexity" | "chatgpt" | "claude"
    query: str                       # the prompt that was asked
    excerpt: str                     # relevant portion of AI response (max 300 chars)
    date: str                        # when measured
    category: str                    # query category
```

```python
@dataclass
class PlannedSection:
    """📋 What we plan to do (not yet outcomes)."""
    label: str = "📋 Current Execution Plan"

    # This week
    planned_comments_this_week: int
    avatars_active: int
    subreddits_targeted: list[str]
    phase_distribution: dict[str, int]  # {"Phase 1": 3, "Phase 2": 2, ...}

    # Next actions
    next_geo_batch: str              # "Tue Jul 8, 09:30"
    next_pipeline_run: str           # "Tomorrow 08:00"
    pending_drafts: int

    # Strategy
    engagement_approaches: list[str]  # what approaches are being used
    category_focus: list[str]        # which GEO categories we're targeting

    # Plan validity
    plan_version: int
    plan_generated_at: datetime
    plan_valid_until: datetime


@dataclass
class ForecastedSection:
    """📈 What we project will happen (model-based, with uncertainty)."""
    label: str = "📈 Forecasted Outcomes"

    # Visibility projection
    visibility_4w: ScenarioTriple    # 4-week visibility rate projection
    visibility_12w: ScenarioTriple   # 12-week visibility rate projection
    visibility_24w: ScenarioTriple   # 24-week (6 month) projection

    # Per-engine projections
    per_engine_12w: dict[str, ScenarioTriple]

    # Gap-to-leader
    leader_name: str                 # top competitor
    leader_rate: float               # their current rate
    gap_current_pp: float            # leader_rate - our_rate
    gap_projected_12w_pp: float      # projected gap in 12 weeks (expected scenario)
    weeks_to_parity: int | None      # when expected scenario reaches leader (None if never in 24w)

    # Engagement projection
    projected_karma_4w: ScenarioTriple
    projected_posting_volume_4w: int

    # Model metadata
    model_name: str                  # "logistic_scurve_v1"
    model_parameters: dict           # transparency: what params were used
    assumptions: list[str]           # explicit list
    last_accuracy_check: ForecastAccuracySummary | None


@dataclass
class ScenarioTriple:
    """Three scenarios with explicit labeling."""
    conservative: float              # -1σ or pessimistic
    expected: float                  # median/most likely
    optimistic: float                # +1σ or best case
    unit: str                        # "%" | "karma" | "comments"
    confidence_level: str            # "68%" (1σ) or "95%" (2σ)


@dataclass
class RiskSection:
    """⚠️ What could go wrong and what we're monitoring."""
    label: str = "⚠️ Risks & Sensitivities"

    platform_risk_level: str         # "low" | "medium" | "high"
    platform_risk_factors: list[RiskFactor]
    forecast_sensitivity: list[SensitivityItem]
    data_gaps: list[str]             # what we couldn't measure
    stale_data_warnings: list[str]   # which metrics are past staleness threshold


@dataclass
class RiskFactor:
    factor: str                      # "avatar_shadowban_risk"
    level: str                       # "low" | "medium" | "high"
    impact_on_forecast: str          # "reduces ceiling by 15%"
    mitigation: str                  # what system does about it


@dataclass
class SensitivityItem:
    assumption: str                  # "Reddit content → LLM citation lag is 6-8 weeks"
    if_wrong: str                    # "Visibility growth delayed by 4 weeks"
    how_we_detect: str               # "GEO batch at week 8 shows no improvement"
```

---

## Layer 5: Business Impact Calculator

### Success Definition (Per-Client)

```python
@dataclass
class ClientSuccessModel:
    """What 'success' means for this specific client."""
    client_id: UUID
    category: str                    # "higher_education" | "cybersecurity" | "saas" | ...
    starting_position: float         # baseline brand_rate at onboarding
    top_competitor_rate: float       # what the leader has
    success_thresholds: dict[str, float]  # {"minimal": 15, "good": 25, "excellent": 40}
    time_horizon_weeks: int          # client expectation (12/24/52)
    primary_kpi: str                 # "visibility_rate" | "lead_mentions" | "brand_citations"


@dataclass
class BusinessImpactSection:
    """💰 What the forecast means in business terms."""
    label: str = "💰 Business Impact"

    # Category dominance position
    category_rank: int               # "You are #7 out of 7 in your category"
    category_total: int
    projected_rank_12w: int          # "Projected to reach #5"

    # Gap analysis (the money slide)
    gap_to_leader: GapAnalysis
    gap_to_top3: GapAnalysis

    # ROI framing
    investment_monthly: float        # what client pays
    projected_visibility_gain_pp: float  # expected pp gain in next period
    cost_per_visibility_point: float  # $/pp (allows comparison)

    # What's measurable vs inferred
    measurable: list[str]            # ["AI visibility rate", "Reddit karma", "survival rate"]
    inferred: list[str]              # ["traffic from AI search", "lead quality", "brand authority"]
    disclaimer: str                  # explicit statement about inference limits


@dataclass
class GapAnalysis:
    """The 'show the gap' analysis Tzvi needs for sales."""
    target_name: str                 # "Tel Aviv University" or "Top 3 average"
    target_rate: float               # their current rate
    client_rate: float               # our current rate
    gap_pp: float                    # target - client
    projected_gap_12w: float         # expected gap in 12 weeks
    projected_gap_24w: float         # expected gap in 24 weeks
    closure_rate_pp_per_week: float  # how fast we're closing
    full_parity_weeks: int | None    # when we reach them (None = not in horizon)
```

### ROI Estimation Model

ROI is probabilistic, not deterministic. Never presented as a guarantee.

```
Visibility gain (pp) × Category search volume × CTR estimate = Estimated impressions
Estimated impressions × Conversion assumption = Potential leads

DISCLAIMER always attached:
"These projections assume continued Reddit content production at current volume,
no major platform policy changes, and typical AI search citation behavior.
Actual results may vary. Visibility ≠ traffic (correlation, not causation)."
```

---

## Data Schema — Storage Model

### New Table: `client_intelligence_reports`

```sql
CREATE TABLE client_intelligence_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    report_period VARCHAR(10) NOT NULL,       -- "2026-W27"
    report_version INT NOT NULL DEFAULT 1,

    -- Structured layers (each independently queryable)
    observed_json JSONB NOT NULL,             -- Layer 1
    planned_json JSONB NOT NULL,              -- Layer 2
    forecasted_json JSONB NOT NULL,           -- Layer 3
    risks_json JSONB NOT NULL,               -- Layer 4
    business_impact_json JSONB NOT NULL,      -- Layer 5

    -- Metadata
    model_version VARCHAR(20) NOT NULL,       -- "scurve_v1"
    data_freshness_json JSONB NOT NULL,       -- age of each source
    generation_cost_usd NUMERIC(8,4) DEFAULT 0,

    -- Lifecycle
    status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | published | superseded
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,

    CONSTRAINT uq_report_client_period_version UNIQUE (client_id, report_period, report_version)
);

CREATE INDEX ix_cir_client_period ON client_intelligence_reports(client_id, report_period);
```

### New Table: `forecast_accuracy_log`

```sql
CREATE TABLE forecast_accuracy_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id UUID NOT NULL REFERENCES client_intelligence_reports(id) ON DELETE CASCADE,
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    metric_id VARCHAR(100) NOT NULL,          -- "geo.brand_rate.perplexity"
    predicted_at TIMESTAMPTZ NOT NULL,
    target_date DATE NOT NULL,
    scenario VARCHAR(20) NOT NULL,            -- "conservative" | "expected" | "optimistic"
    predicted_value NUMERIC(8,2) NOT NULL,
    actual_value NUMERIC(8,2),               -- NULL until measured
    error_pp NUMERIC(8,2),                   -- computed when actual arrives
    within_bounds BOOLEAN,                   -- was actual within conservative-optimistic?
    measured_at TIMESTAMPTZ,

    CONSTRAINT uq_accuracy_report_metric_target UNIQUE (report_id, metric_id, target_date, scenario)
);

CREATE INDEX ix_fal_client_metric ON forecast_accuracy_log(client_id, metric_id);
```

### New Table: `observed_snapshots`

```sql
CREATE TABLE observed_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metrics_json JSONB NOT NULL,              -- array of ObservedMetric
    data_gaps JSONB NOT NULL DEFAULT '[]',
    source_availability JSONB NOT NULL DEFAULT '{}',

    CONSTRAINT uq_observed_client_date UNIQUE (client_id, (collected_at::date))
);

CREATE INDEX ix_obs_client_collected ON observed_snapshots(client_id, collected_at);
```

---

## Report Template — Client-Facing (Weekly)

### Visual Structure

```
┌─────────────────────────────────────────────────────────────┐
│ HEADER: Client Name · Period · Data Freshness Indicator      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ ┌─ HERO CARD ─────────────────────────────────────────────┐ │
│ │  📍 7.7% (Measured)  →  📈 ~38% (Projected, 6 mo)      │ │
│ │  +30pp projected growth · ±8pp confidence               │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ┌─ 📍 OBSERVED RESULTS ──────────────────────────────────┐ │
│ │  Brand visibility: X% (N queries, M engines)            │ │
│ │  Per-engine: Perplexity X% · ChatGPT Y% · Claude Z%    │ │
│ │  Comments posted: N · Avg karma: X · Survival: Y%      │ │
│ │  High-intent threads: X%                                │ │
│ │                                                         │ │
│ │  🏆 Category Position:                                  │ │
│ │  ┌────────────────────────────────────────────────┐     │ │
│ │  │ Competitor A  ████████████████████████████ 92%  │     │ │
│ │  │ Competitor B  ██████████████████████████   85%  │     │ │
│ │  │ Competitor C  ████████████████             61%  │     │ │
│ │  │ You           ██                            8%  │     │ │
│ │  └────────────────────────────────────────────────┘     │ │
│ │                                                         │ │
│ │  💬 AI Response Excerpts (where brand cited)            │ │
│ │  "Ono offers programs for English speakers..."          │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ┌─ 📋 EXECUTION PLAN (this week) ────────────────────────┐ │
│ │  Avatars active: 5 · Target subs: 8                     │ │
│ │  Planned comments: 35-50 this week                      │ │
│ │  Category focus: use_case (0% → gap), comparison (0%)   │ │
│ │  Next GEO measurement: Tue Jul 8                        │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ┌─ 📈 FORECAST ──────────────────────────────────────────┐ │
│ │  Visibility in 4 weeks: 12-18% (expected: 15%)          │ │
│ │  Visibility in 12 weeks: 22-35% (expected: 28%)         │ │
│ │  Gap to leader: 84pp today → ~64pp in 12 weeks          │ │
│ │                                                         │ │
│ │  [Trend chart: solid=measured, dashed=projected]         │ │
│ │                                                         │ │
│ │  Model: S-curve · Confidence: 68%                       │ │
│ │  Assumes: continued posting volume, no platform changes  │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ┌─ ⚠️ RISKS & SENSITIVITIES ─────────────────────────────┐ │
│ │  Platform risk: LOW (all avatars healthy)                │ │
│ │  If posting volume drops 50% → forecast delayed 4 weeks  │ │
│ │  If Reddit policy changes → re-baseline needed           │ │
│ │  Data gaps: ChatGPT not yet measured                     │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ┌─ 💰 BUSINESS IMPACT ───────────────────────────────────┐ │
│ │  Category rank: #7/7 → projected #5/7 (12 weeks)        │ │
│ │  Gap closure rate: ~1.5pp/week expected                  │ │
│ │  ROI framing: $X/mo → Y pp visibility growth             │ │
│ │  ⚡ Measurable: visibility rate, karma, survival         │ │
│ │  🔮 Inferred: traffic, leads (correlation, not causal)  │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ FOOTER: Generated by RAMP · Methodology · Confidence notes  │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Risks & Failure Modes

### 1. Self-Reinforcing Bias (Most Critical)

**Risk:** System only measures visibility for queries WE chose. If we pick queries where we're likely to appear, we overestimate true visibility.

**Mitigation:**
- Category distribution requirement: queries must cover ≥5 categories including ones where brand is NOT present
- Competitor queries: include queries where competitors dominate (shows honest gap)
- External validation: monthly manual spot-check of queries NOT in our set
- "Blind spot" metric: % of categories with 0% visibility (healthy system should have some)

### 2. Projection Treated as Reality (Layer Conflation)

**Risk:** Over time, projected numbers get internalized as "what we'll deliver" rather than "what might happen."

**Mitigation:**
- Structural separation (JSONB layers) makes conflation machine-detectable
- Every projected number ALWAYS accompanied by range (never a point estimate)
- Forecast accuracy tracking: if predictions consistently miss, confidence intervals widen
- UI: projected values always dashed/italic, measured always solid/bold

### 3. Small Sample Size Overconfidence

**Risk:** With 20-30 queries per batch, 1 mention swing = 3-5pp change. System may report "visibility improved!" when it's just noise.

**Mitigation:**
- `confidence` field based on sample size: n<5 = "low", 5≤n<20 = "medium", n≥20 = "high"
- Minimum 3 batches before reporting "trend" (avoid reading noise as signal)
- Statistical significance test before claiming "improvement" (binomial test, p<0.1)

### 4. Reddit Content → LLM Citation Lag Unknown

**Risk:** We don't know how long it takes from "Reddit post upvoted" to "LLM cites it." Could be 2 weeks or 6 months.

**Mitigation:**
- `assumptions` field explicitly states assumed lag
- Track first-citation-after-post delay for each detected brand mention
- Over time, narrow the estimate with empirical data
- Conservative scenario uses longer lag; optimistic uses shorter

### 5. Platform Risk Not Quantifiable

**Risk:** Reddit shadowban/policy change probability is fundamentally unknowable.

**Mitigation:**
- `discount_factor` is a tunable parameter, not a precise calculation
- Historical incident rate (from ops logs) provides empirical base rate
- When incidents occur, discount factor increases (forecasts become more conservative)
- Report explicitly lists platform risks as "cannot be eliminated, only managed"

### 6. Stale Data Presented as Fresh

**Risk:** GEO batch is 6 days old but report shows it as current visibility.

**Mitigation:**
- Every metric has `staleness_threshold_hours`
- Stale metrics flagged with ⚠️ in report
- Report header shows "Data Freshness" for each source
- If ALL key sources are stale (>threshold), report generation is blocked with warning

---

## What Additional Data Improves Prediction Accuracy

### Immediate (can collect now, not yet used for forecasting):

1. **Citation-to-post attribution** — when GEO detects brand mention, which Reddit post was cited? Track `reddit_urls_found` → match to our `comment_drafts`. Enables: "this specific comment led to this citation."

2. **Time-to-citation delay** — time between comment posted and first GEO brand detection. Enables: calibrating the lag assumption in S-curve model.

3. **Karma velocity vs citation probability** — do higher-karma comments get cited more? Threshold detection: "comments with karma>10 are 3x more likely to be cited."

4. **Category-specific growth rates** — different categories may have different S-curves. "Academic programs" might grow faster than "career outcomes" because there's less competition.

### Medium-term (requires new instrumentation):

5. **Google Search Console data** — if client shares GSC access, we can correlate visibility growth with organic traffic changes. Bridges the "visibility → traffic" inference gap.

6. **Perplexity referral tracking** — track if Perplexity citations drive actual clicks (requires client site analytics).

7. **Competitor activity monitoring** — are competitors also increasing Reddit presence? If yes, our growth may be offset. Requires: scraping competitor mentions over time.

### Long-term (research-grade):

8. **A/B testing on content approaches** — which content archetype (comparison, first-hand, listicle) drives more citations? Requires: enough volume to measure per-approach.

9. **Cross-engine correlation** — does Perplexity citing lead to ChatGPT citing later? Sequential influence mapping.

10. **Causal inference** — natural experiments: when posting pauses (shadowban, vacation), does visibility drop? Lag measurement via interrupted time series.

---

## Implementation Phases

| Phase | Scope | Effort | Deliverable |
|-------|-------|--------|-------------|
| **1** | ObservedRealityCollector + Report JSONB model + basic report template | 3-4 days | Weekly report with measured data (no projection) |
| **2** | VisibilityForecaster (S-curve) + scenario generation + report integration | 2-3 days | Report with 📍+📈 sections, demo-style |
| **3** | ForecastAccuracy tracking + IntentSnapshot + full 5-layer report | 3-4 days | Complete intelligence report |
| **4** | Client portal integration (HTMX) + automated weekly generation (Beat task) | 2-3 days | Live portal page + scheduled reports |
| **5** | Business Impact calculator + gap-to-leader + ROI framing | 1-2 days | Full business case in report |

**Total: ~12-16 days.**

---

## Relationship to Existing Systems

| Existing Component | How Forecast Layer Uses It |
|-------------------|--------------------------|
| `geo_query_runner.py` | Source of GEO observation data (Layer 1) |
| `GeoQueryResult` | Raw brand_mentioned + competitors_mentioned |
| `GeoFrequencyMetric` | Pre-aggregated per-prompt rates |
| `KarmaSnapshot` | Outcome measurement (karma, deletion) |
| `PerformanceMetric` | Daily avatar metrics |
| `signal_collector.py` | Health/cost signals (ops-internal, not client-facing) |
| `client_report.py` | Legacy Markdown report (superseded by this system) |
| `demo/share-of-voice.html` | Visual reference for report template |
| `client/visibility.html` | Current portal page (will be upgraded) |
| `EPGSlot` / `ExecutionTask` | Source of intent data (Layer 2) |
| `SubredditRiskProfile` | Platform risk input (Layer 3) |

---

## Anti-Patterns (What This System Must NOT Do)

1. **Never present forecast as fact.** "You will reach 38%" is forbidden. "Projected to reach ~38% (±8pp)" is correct.

2. **Never hide data gaps.** If ChatGPT isn't measured yet, say so explicitly. Don't extrapolate from Perplexity to "overall visibility" without stating the assumption.

3. **Never show only optimistic scenario.** All three scenarios always visible. If only one fits the UI, show "expected" with bounds.

4. **Never count planned actions as outcomes.** "We plan to post 50 comments" ≠ "50 comments posted." Plan is plan. Result is result.

5. **Never suppress declining metrics.** If visibility dropped or karma decreased, show it honestly. Trust is built on transparency, not on cherry-picking good news.

6. **Never update historical observed data.** Once measured, the number is frozen. New measurements are new data points, not corrections to old ones.
