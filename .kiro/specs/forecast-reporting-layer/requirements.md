# Forecast & Reporting Layer v1 — Requirements

## Problem Statement

RAMP produces client reports that mix observed reality, execution intent, and implicit projection without clear separation. This creates three risks:

1. **Credibility risk** — clients can't distinguish "what happened" from "what we hope will happen"
2. **Self-deception risk** — system treats planned actions as equivalent to outcomes
3. **Sales risk** — Tzvi can't show prospects the gap between current state and projected state with proper confidence labels

Цви consistently говорит: клиент хочет видеть кто доминирует в его категории, где он относительно них, и куда мы можем его привести. Это три разных типа истины, и отчёт должен их чётко разделять.

## Business Context

The demo report (`/demo/share-of-voice.html`) already demonstrates the visual pattern:
- 📍 "Measured" (real batch data)
- 📈 "Projected" (S-curve model)
- Competitor benchmark (market position)

This needs to be formalized into a reproducible, machine-verifiable architecture.

## Layers (5)

### Layer 1: Observed Reality (Truth Layer)
What metrics are ground truth and how they're validated.

### Layer 2: Execution Intent (Planned Actions)
How upcoming system actions are represented and versioned.

### Layer 3: Forecasting (Counterfactual Simulation)
"If we execute planned actions under current conditions, expected outcome is X."

### Layer 4: Report Composition (Client-Facing Output)
Structured report that separates all layers with explicit labels.

### Layer 5: Business Impact
How forecasts map to business value (visibility, leads, ROI).

---

## Requirements

### R1: Observed Reality Layer

| ID | Requirement |
|----|-------------|
| R1.1 | System maintains a validated metrics registry classifying each metric as "observed truth" with validation method and time window |
| R1.2 | Reddit engagement metrics (karma, reply_count, survival_rate, removal_rate) are classified as "platform-validated" with 48h validation window |
| R1.3 | AI visibility signals (brand_mentioned rate per engine per batch) are classified as "measurement" with per-batch validation |
| R1.4 | Execution success metrics (drafts_generated, drafts_posted, drafts_deleted) are classified as "system-verified" with 24h window |
| R1.5 | Each metric has an explicit staleness threshold (e.g. GEO data >7d = stale, karma >48h = stale) |
| R1.6 | Competitor presence metrics are classified as "comparative-measurement" — same instrument measures both us and competitors |

### R2: Execution Intent Layer

| ID | Requirement |
|----|-------------|
| R2.1 | All planned actions (EPG slots, pending drafts, scheduled batches) are represented as intent with status tracking |
| R2.2 | Intent has a validity window (max 7d forward for EPG, 14d for strategy, 90d for phase roadmap) |
| R2.3 | Intent is versioned — when EPG rebuilds, old plan is archived, new plan has version+1 |
| R2.4 | Intent explicitly links to task system states: approved → scheduled → executed → measured |
| R2.5 | Intent NEVER appears in the "Results" section of any report. It appears in "Plan" section only. |
| R2.6 | Stale intent (past deadline, not executed) is auto-marked as "expired" and excluded from forecasts |

### R3: Forecasting Layer

| ID | Requirement |
|----|-------------|
| R3.1 | Forecasts are computed from: (observed baseline) + (planned actions × historical conversion rates) + (platform risk discount) |
| R3.2 | Each forecast includes uncertainty bounds (confidence interval or min/expected/max scenarios) |
| R3.3 | System supports at minimum 3 scenarios: conservative (−1σ), expected (median), optimistic (+1σ) |
| R3.4 | Planned actions are NEVER treated as outcomes in forecast computation |
| R3.5 | Platform risk (shadowban probability, subreddit removal rate, Reddit policy changes) is included as discount factor |
| R3.6 | Historical response curves (karma velocity over time, visibility growth lag) are used for projection |
| R3.7 | Forecast accuracy is tracked: actual vs predicted at each measurement point |
| R3.8 | Forecasts degrade gracefully: less data = wider confidence intervals, not more confident claims |
| R3.9 | Per-engine growth rates are separate (Perplexity ×1.4, ChatGPT ×1.0, Claude ×0.65 as initial priors) |

### R4: Report Composition Layer

| ID | Requirement |
|----|-------------|
| R4.1 | Every report section has an explicit label: 📍Observed / 📋Planned / 📈Forecasted / ⚠️Risk |
| R4.2 | No section conflates observation with prediction — they are structurally separate |
| R4.3 | Each data point in the report links to its source layer (truth, intent, or forecast) |
| R4.4 | Report is machine-verifiable: JSONB structure allows programmatic extraction of each layer |
| R4.5 | Client-facing report uses visual markers (solid line = measured, dashed line = projected) already established in demo |
| R4.6 | Report includes "Data Freshness" indicator showing age of each data source |
| R4.7 | Report is generated per-client, per-period (weekly cadence) |

### R5: Business Impact Layer

| ID | Requirement |
|----|-------------|
| R5.1 | Forecast maps to business value dimensions: visibility score, estimated impressions, brand association strength |
| R5.2 | "Success" is defined per-client based on their category and starting position |
| R5.3 | ROI is estimated probabilistically: "At expected scenario, $X investment yields Y% visibility growth" |
| R5.4 | Business impact explicitly states what is measurable vs what is inferred |
| R5.5 | Category dominance view: client's position relative to top-5 competitors (from GEO batch data) |
| R5.6 | Gap-to-leader metric: "You are at 7.7%, leader is at 92%. Projected gap closure: X pp in Y weeks" |

---

## Non-Requirements (Explicit Exclusions)

- This is NOT a real-time dashboard (weekly cadence is sufficient)
- This does NOT replace the daily ops review (that's internal, this is client-facing)
- This does NOT require LLM generation for v1 (structured templates with data injection)
- This does NOT promise traffic/lead conversion (visibility → traffic is correlation, not causal)

---

## Acceptance Criteria

1. A client report produced by this system clearly separates measured from projected
2. An engineer reading the report JSON can programmatically verify no confusion between layers
3. Tzvi can show a prospect: "Here's where you are (measured), here's your competitor (measured), here's where you'll be (projected with confidence)"
4. When a forecast is wrong, the system can identify which assumption failed
5. The report never says "your visibility IS 38%" for a projected value — it says "projected to reach ~38% (±8pp)"
