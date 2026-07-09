# Implementation Plan: AI Cost Optimization

## Overview

Four-phase implementation ordered for maximum value delivery: model migration (immediate 25× cost reduction on editing/persona), GEO daily smoothing (eliminate spend spikes), budget health + unit economics services (visibility), and page redesign + JSON API (presentation + programmatic access).

## Tasks

- [ ] 1. Model Migration — Editing & Persona to Gemini Flash
  - [ ] 1.1 Add `llm_editing_model` and `llm_persona_model` to DEFAULT_SETTINGS
    - Add entries to `DEFAULT_SETTINGS` dict in `app/services/settings.py` with default value `gemini/gemini-2.5-flash`
    - _Requirements: 2.2, 3.1_

  - [ ] 1.2 Update `select_persona()` to use dedicated model setting
    - In `app/services/generation.py`, change `select_persona()` to read from `get_config("llm_persona_model")` instead of `get_config("llm_generation_model")`
    - _Requirements: 3.2, 3.4_

  - [ ] 1.3 Update `edit_comment()` to use dedicated model setting
    - In `app/services/generation.py`, change `edit_comment()` to read from `get_config("llm_editing_model")` instead of `get_config("llm_generation_model")`
    - _Requirements: 2.3, 2.5_

  - [ ]* 1.4 Write unit tests for model setting routing
    - Verify `select_persona` reads `llm_persona_model`, `edit_comment` reads `llm_editing_model`, and generation still reads `llm_generation_model`
    - _Requirements: 2.3, 3.2, 3.3_

- [ ] 2. Checkpoint — Verify model migration
  - Ensure persona and editing use Gemini Flash, generation still uses Claude Sonnet. Ask the user if questions arise.

- [ ] 3. GEO Daily Rotation Scheduler
  - [ ] 3.1 Add `last_executed_at` column to GeoPrompt model
    - Add `last_executed_at: Mapped[datetime | None]` to `app/models/geo_prompt.py`
    - Create Alembic migration `aico01_geo_prompt_last_executed.py` adding column + index
    - _Requirements: 1.6_

  - [ ] 3.2 Create `app/services/geo_scheduler.py` — daily rotation logic
    - Implement `select_daily_prompts(db, client_id)` using round-robin with freshness priority
    - Sort by `last_executed_at ASC` (NULL = highest priority), take `ceil(N / 7)` prompts
    - Prioritize prompts that failed in previous batch (failed_at > last_executed_at)
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 1.7_

  - [ ] 3.3 Create `run_geo_daily_rotation` Celery task
    - In `app/tasks/geo_monitoring.py`, add new task that iterates GEO-enabled clients, calls `select_daily_prompts()`, executes batch for selected subset, updates `last_executed_at` on success
    - Wrap existing `execute_geo_batch_for_prompts()` logic from `geo_query_runner.py`
    - _Requirements: 1.1, 1.4, 1.7_

  - [ ] 3.4 Update Beat schedule — replace Tue+Fri with daily
    - In `app/tasks/beat_app.py`, remove `geo-monitoring-scheduled` entry (Tue+Fri 09:30)
    - Add `geo-monitoring-daily-rotation` entry with `crontab(hour=9, minute=30)` daily
    - Register new task name in `app/tasks/worker.py`
    - _Requirements: 1.4_

  - [ ]* 3.5 Write property test for prompt rotation coverage
    - **Property 1: Prompt rotation guarantees 7-day coverage**
    - **Validates: Requirements 1.1**

  - [ ]* 3.6 Write property test for daily capacity ceiling
    - **Property 2: Daily execution respects capacity ceiling**
    - **Validates: Requirements 1.2, 1.3**

  - [ ]* 3.7 Write property test for failed prompt priority
    - **Property 3: Failed prompts receive priority in next rotation**
    - **Validates: Requirements 1.7**

- [ ] 4. Checkpoint — Verify GEO daily rotation
  - Ensure GEO runs daily selecting ~ceil(N/7) prompts per client, failed prompts get priority next day, `last_executed_at` updates correctly. Ask the user if questions arise.

- [ ] 5. Budget Health Service
  - [ ] 5.1 Add budget settings to DEFAULT_SETTINGS
    - Add `budget_anthropic` (default "50"), `budget_gemini` (default "300"), `budget_perplexity` (default "20"), `budget_openai` (default "50") to `app/services/settings.py`
    - _Requirements: 6.5_

  - [ ] 5.2 Create `app/services/budget_health.py`
    - Implement `ProviderBudgetHealth` dataclass (provider, display_name, spent_this_month, monthly_limit, pct_used, projected_month_end, state)
    - Implement `compute_budget_health(db)` querying `ai_usage_log` for current month, grouping by provider prefix from model field
    - Compute projected spend as `(spend_so_far / days_elapsed) * days_in_month`
    - Classify state: ≥90% projected = "danger", ≥70% = "warning", else "healthy"
    - Define `PROVIDER_PREFIXES` mapping (anthropic → ["anthropic/", "bedrock/anthropic"], gemini → ["gemini/"], etc.)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ]* 5.3 Write property test for budget health state classification
    - **Property 6: Budget health state correctly classified by projection threshold**
    - **Validates: Requirements 6.2, 6.3, 6.4**

- [ ] 6. Anomaly Detection Service
  - [ ] 6.1 Create `app/services/anomaly_detector.py`
    - Implement `CostAnomaly` dataclass (date, total_cost, rolling_avg, ratio, top_operation, top_provider)
    - Implement `detect_anomalies(db, lookback_days=30)` — get daily costs, compute 7-day rolling average excluding current day, flag days where cost > 3× avg
    - Skip anomaly detection for days with < 3 preceding data points
    - Attribute anomaly to top contributing operation and provider
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [ ]* 6.2 Write property test for anomaly detection algorithm
    - **Property 7: Anomaly detection flags days exceeding 3× rolling average**
    - **Validates: Requirements 8.1, 8.3**

- [ ] 7. Unit Economics Calculator
  - [ ] 7.1 Create `app/services/unit_economics.py`
    - Implement `UnitEconomics` dataclass with fields: client_name, client_id, avatar_count, pipeline_cost, geo_share, infra_share, total_monthly, per_avatar, per_draft, cost_1_avatar, cost_2_avatar, cost_3_avatar
    - Implement `compute_unit_economics(db)` using 30-day rolling window from `ai_usage_log`
    - Compute pipeline costs per client grouped by operation
    - Compute GEO share proportionally by client prompt count / total prompts
    - Compute infra share from `monthly_infra_cost` setting / active client count
    - Project costs for 1/2/3 avatar configurations (scale pipeline linearly, keep GEO+infra fixed)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.6_

  - [ ] 7.2 Add `monthly_infra_cost` and `unit_economics_cache` to DEFAULT_SETTINGS
    - Add `monthly_infra_cost` (default "25") and `unit_economics_cache` (default "{}") to settings
    - _Requirements: 5.1_

  - [ ] 7.3 Create daily Celery task for unit economics computation
    - Add `compute_unit_economics_daily` task in `app/tasks/` that computes and caches results in `system_settings` as JSON
    - Add Beat schedule entry at 03:00 daily in `beat_app.py`
    - _Requirements: 5.5_

  - [ ]* 7.4 Write property tests for unit economics
    - **Property 4: Unit economics components sum to total**
    - **Property 5: GEO cost allocated proportionally by prompt count**
    - **Validates: Requirements 5.1, 5.6**

- [ ] 8. Checkpoint — Verify services
  - Ensure budget health computes correctly per provider, anomaly detection flags spike days, unit economics sums correctly. Ask the user if questions arise.

- [ ] 9. AI Costs Page Redesign
  - [ ] 9.1 Update admin route to provide new context data
    - In `app/routes/admin.py` → `admin_ai_costs()`, add calls to `compute_budget_health()`, `detect_anomalies()`, read cached unit economics from settings
    - Add per-provider spend grouping via new `get_ai_costs_by_provider()` helper in `app/services/admin.py`
    - _Requirements: 6.1, 7.3, 8.2, 9.1_

  - [ ] 9.2 Rewrite `app/templates/admin_ai_costs.html` — hierarchical layout
    - Hero section: period total, daily avg, projection, API calls, tokens + budget health cards per provider
    - Unit economics table showing $/month for 1/2/3 avatars, $/avatar, $/draft
    - Stage breakdown: stacked bar chart by pipeline stage (Chart.js)
    - Provider detail: per-provider burn rate cards with trend vs previous period
    - Drill-down sections in collapsed `<details>`: cost timeline (with anomaly highlights), by operation, by client, by model, by avatar, recent calls
    - Retain existing date picker (7d/30d/90d/All + custom range) and client filter
    - _Requirements: 7.1, 7.2, 7.3, 9.1, 9.2, 9.3, 9.4, 9.5_

  - [ ] 9.3 Add anomaly highlighting to cost timeline chart
    - In Chart.js timeline data, include anomalies array; render anomaly days with red point markers and tooltip showing ratio + top contributor
    - _Requirements: 8.2_

  - [ ] 9.4 Add HTMX stage-filter interaction
    - Clicking a stage segment in stacked bar sends `hx-get` with `?stage=Content` parameter, detail tables reload filtered to that stage's operations
    - _Requirements: 7.2_

- [ ] 10. RAMP Agent JSON API
  - [ ] 10.1 Create `/api/admin/ai-costs` JSON endpoint
    - In `app/routes/admin.py`, add new GET endpoint returning JSON with: `total_month`, `daily_avg`, `projected_month`, `per_provider` array, `anomalies` array, `unit_economics` object
    - Require `owner` or `partner` role authentication via `require_business_admin`
    - Accept optional query params: `period` (7d/30d/90d/all), `date_from`, `date_to`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [ ]* 10.2 Write property test for API response schema
    - **Property 8: Agent API response contains all required fields**
    - **Validates: Requirements 10.2**

- [ ] 11. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Implementation order optimized for value: model migration delivers immediate 25× cost reduction, GEO smoothing eliminates daily spikes, services provide data infrastructure, page redesign presents it all

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "3.1", "5.1"] },
    { "id": 2, "tasks": ["1.4", "3.2", "5.2", "7.2"] },
    { "id": 3, "tasks": ["3.3", "5.3", "6.1", "7.1"] },
    { "id": 4, "tasks": ["3.4", "3.5", "3.6", "3.7", "6.2", "7.3"] },
    { "id": 5, "tasks": ["7.4", "9.1"] },
    { "id": 6, "tasks": ["9.2", "9.3", "9.4", "10.1"] },
    { "id": 7, "tasks": ["10.2"] }
  ]
}
```
