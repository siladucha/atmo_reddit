---
inclusion: fileMatch
fileMatchPattern: "**/daily_review/**,**/daily-ops-review/**"
---

# Engineering Guidelines — Daily Operations Review (RAMP)

## Objective

Build the Daily Operations Review as a lightweight operational ritual layer on top of existing RAMP systems. This feature is not an autonomous decision-maker and not a replacement for dashboards. Its purpose is to help operators spend 60-90 minutes per day understanding:

1. What happened in the last 24 hours?
2. Why did it happen?
3. What does it mean for the next 24 hours?
4. What should change?

Success is measured by reducing operational surprise, not maximizing analysis sophistication.

## Core Principles

### 1. Snapshot First (Non-Negotiable)

The review must operate against a frozen dataset. At session start:
- Collect all required metrics
- Store immutable snapshot
- Attach snapshot to session
- Never query live metrics inside sections

Reason: Two people opening the same review later must see identical inputs.

### 2. Separate Collection from Interpretation

Do not mix: data collection, anomaly detection, presentation, decisions, report generation.

Preferred architecture:
```
DailyReviewSession
    → ReviewSnapshotService
        → ReviewAnalysisEngine
            → DecisionTracker
                → IntelligenceReportGenerator
```
Each layer should be independently testable.

### 3. Keep Review Stateless Between Sections

Sections must not depend on UI navigation order. Each section receives:
- snapshot
- session_inputs
- cached_analysis

Never depend on frontend state.

### 4. Prefer SQL + Rules Before LLM

Default execution order:
```
SQL aggregation → deterministic scoring → statistical detection → templates → optional LLM enrichment
```

LLM is enhancement only. System must remain usable with zero LLM budget.

### 5. Cache Everything for Session Lifetime

Create one cache scope: `review_session_cache`. Cache:
- health calculations
- anomaly classification
- forecasts
- summaries
- hypothesis generation

Rule: Same inputs → same outputs → no recomputation.

## Data Model

- **DailyReviewSession**: id, status, started_at, completed_at, snapshot_id, current_section, total_duration_sec, owner_id, cost_used_usd
- **ReviewSnapshot**: id, created_at, health_snapshot_json, signals_json, trends_json, cost_json, forecast_inputs_json, source_availability_json (IMMUTABLE)
- **ReviewDecision**: id, review_id, type, owner, deadline, status, linked_entities
- **IntelligenceReport**: report_raw (structured immutable JSON) + report_summary (narrative). Never regenerate report_raw.

## Implementation Priorities

### Phase 1 — Usable Review (Ship First)
Build: session lifecycle, snapshot collection, health section, change section, decisions, report generation.
Skip: forecasting, hypothesis generation, LLM summaries, historical calibration.
Target: usable within 2 weeks.

### Phase 2 — Analytical Layer
Add: trend classification, weak signals, forecast generation, forecast accuracy.
Target: after operators complete at least 10 reviews.

### Phase 3 — Intelligence Layer
Add: hypothesis workflows, recommendation ranking, narrative summaries, learning loops.
Only after stable operational usage.

## Cost Rules

- Daily Operations budget: default = $1/day, target = $0.30-0.50/day
- Budget allocation: 40% review, 40% monitoring, 20% reserve
- When exhausted: disable LLM, continue review, show degraded mode
- Never block operators

## Decision Rules

- Maximum: 3 decisions per review
- Allowed types: observe, investigate, execute, block
- Every decision must answer: "What changes tomorrow?"
- If nothing changes → decision should not exist

## UX Rules

- Quick Review must be default (healthy sections collapse automatically)
- Autosave ≤ 2 seconds
- Restore session on reload
- Keyboard friendly, no modal chains
- Do not make users scroll endlessly

## Anti-Patterns (Do Not Build)

- Autonomous operations
- Agent self-modification
- Recursive analysis
- Live dashboards inside review
- Endless recommendations
- Per-widget LLM calls
- Background recomputation

Review exists to focus attention.

## Definition of Done

Feature is complete when:
- Operator can finish review in <90 min
- Session can resume safely
- Report is reproducible
- Cost stays below budget
- At least one decision is produced
- Next day forecast can be compared to reality
