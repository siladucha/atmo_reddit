# Implementation Plan: Pipeline Observability

## Overview

Implement the Pipeline Observability layer for the ThreddOps admin panel. This adds structured pipeline run tracking, step-level detail with timing/retries, system block health visualization, and automated data pruning. The implementation follows the existing project patterns: SQLAlchemy 2.0 models, service-layer logic, FastAPI routes with Jinja2+HTMX templates, and Hypothesis property-based tests.

## Tasks

- [ ] 1. Data models and migration
  - [ ] 1.1 Create PipelineRun and PipelineRunStep models
    - Create `app/models/pipeline_run.py` with `PipelineRun` model (id, pipeline_type, status, started_at, completed_at, trigger_source, operator_id, is_blocked, blocked_reason, error_message, steps_total, steps_completed)
    - Create `PipelineRunStep` model in same file (id, run_id FK with CASCADE, step_name, block_name, status, started_at, completed_at, duration_ms, max_retries, remaining_retries, last_error_message, metadata JSONB)
    - Add relationship between PipelineRun.steps and PipelineRunStep.run
    - Add composite indexes: (status, started_at), (pipeline_type, started_at) on runs; (run_id), (block_name, status, completed_at) on steps
    - _Requirements: 1.1, 2.1_

  - [ ] 1.2 Add new columns to ActivityEvent model
    - Add `operator_action_required: Mapped[bool]` (default False) to `app/models/activity_event.py`
    - Add `runbook_url: Mapped[str | None]` (Text, nullable) to `app/models/activity_event.py`
    - _Requirements: 6.1, 6.2_

  - [ ] 1.3 Register models in `app/models/__init__.py`
    - Import PipelineRun and PipelineRunStep
    - Add to `__all__` list
    - _Requirements: 1.1, 2.1_

  - [ ] 1.4 Create Alembic migration
    - Generate migration in `reddit_saas/alembic/versions/` for: `pipeline_runs` table, `pipeline_run_steps` table, two new columns on `activity_events`
    - Ensure CASCADE on foreign key from pipeline_run_steps.run_id → pipeline_runs.id
    - _Requirements: 1.1, 2.1, 6.1, 6.2_

- [ ] 2. ObservabilityService — write API
  - [ ] 2.1 Implement non-blocking write infrastructure
    - Create `app/services/observability.py`
    - Implement dedicated session factory (separate from pipeline's transactional session)
    - Implement fire-and-forget background thread dispatch for write operations
    - Implement try/except wrapper that logs failures without propagating exceptions
    - _Requirements: 8.1, 8.2, 8.3_

  - [ ] 2.2 Implement write methods
    - `create_run(pipeline_type, trigger_source, operator_id, steps_total) -> UUID` — creates PipelineRun with status="queued", returns run_id immediately
    - `update_run_status(run_id, status, error_message, steps_completed)` — updates run fields
    - `create_step(run_id, step_name, block_name, max_retries, metadata) -> UUID` — creates PipelineRunStep with status="pending", remaining_retries=max_retries
    - `update_step_status(step_id, status, error_message, duration_ms)` — updates step, decrements remaining_retries on retry
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [ ]* 2.3 Write property tests for creation defaults (Property 1)
    - **Property 1: Creation defaults are correctly applied**
    - For any valid pipeline_type and trigger_source, creating a PipelineRun results in status="queued" and started_at ≈ now. For any valid max_retries, creating a PipelineRunStep results in status="pending" and remaining_retries=max_retries.
    - **Validates: Requirements 1.2, 2.2**

  - [ ]* 2.4 Write property tests for retry counter (Property 3)
    - **Property 3: Retry counter decrements correctly**
    - For any PipelineRunStep with remaining_retries > 0, failure decrements by 1 and sets status="retrying". When remaining_retries=0, failure sets status="failed".
    - **Validates: Requirements 2.5, 2.6**

  - [ ]* 2.5 Write property test for write failure isolation (Property 9)
    - **Property 9: Write failure isolation**
    - For any observability write that encounters a DB error, the error is logged but not propagated to the caller.
    - **Validates: Requirements 8.1, 8.3**

- [ ] 3. ObservabilityService — read API
  - [ ] 3.1 Implement read methods
    - `get_runs(db, pipeline_type, status, trigger_source, date_from, date_to, page, page_size) -> (list[PipelineRun], int)` — paginated, filtered, ordered by started_at DESC
    - `get_run_detail(db, run_id) -> PipelineRun | None` — single run with steps eagerly loaded
    - `get_run_steps(db, run_id) -> list[PipelineRunStep]` — steps ordered by started_at (nulls last)
    - _Requirements: 3.1, 3.2, 3.3, 4.1, 4.2_

  - [ ] 3.2 Implement block health computation
    - `compute_block_health(db) -> list[BlockHealthStatus]` — compute health for all 11 system blocks
    - Define `BlockHealthStatus` dataclass (block_name, label, health, last_step_at, recent_failures, consecutive_failures)
    - Implement priority rules: down (>10 consecutive failures) > degraded (>3 failures in 30 min) > healthy (completed step in 10 min) > unknown (no steps in 60 min)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [ ]* 3.3 Write property test for block health computation (Property 6)
    - **Property 6: Block health computation follows priority rules**
    - For any system block and any set of recent steps, health is computed according to priority: down > degraded > healthy > unknown.
    - **Validates: Requirements 5.3, 5.4, 5.5, 5.6**

  - [ ]* 3.4 Write property test for list query correctness (Property 7)
    - **Property 7: List query returns correct, ordered, paginated results**
    - For any set of PipelineRuns and any filter combination, returned runs match filters, are ordered by started_at DESC, and count ≤ page_size.
    - **Validates: Requirements 3.1, 3.2, 3.3**

- [ ] 4. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. PipelineRunContext — context manager
  - [ ] 5.1 Implement PipelineRunContext
    - Add `PipelineRunContext` class to `app/services/observability.py`
    - `__enter__`: create run with status "queued", then update to "running"
    - `__exit__`: set status to "completed" (no exception) or "failed" (exception), set completed_at, store error_message from exception
    - `add_step(step_name, block_name, max_retries) -> StepHandle` — returns a handle with `.complete()` and `.fail(error)` methods
    - StepHandle.complete(): sets status="completed", computes duration_ms
    - StepHandle.fail(error): handles retry logic (decrement or fail)
    - _Requirements: 9.1, 9.2, 9.3, 9.5_

  - [ ]* 5.2 Write property test for context manager lifecycle (Property 5)
    - **Property 5: Context manager lifecycle round-trip**
    - For any pipeline_type and trigger_source, entering creates a run (queued→running). Normal exit → "completed". Exception exit → "failed" with error_message. Both set completed_at.
    - **Validates: Requirements 9.1, 9.3, 9.5**

  - [ ]* 5.3 Write property test for step timing consistency (Property 2)
    - **Property 2: Step completion timing is consistent**
    - For any step that transitions running→completed, duration_ms equals (completed_at - started_at) in milliseconds within 10ms tolerance.
    - **Validates: Requirements 2.4**

- [ ] 6. Routes and templates — Pipeline Runs List
  - [ ] 6.1 Create ops router and list route
    - Create `app/routes/ops.py` with APIRouter(prefix="/admin/ops")
    - Implement `GET /pipeline-runs` — full page with filters (pipeline_type, status, trigger_source) and pagination
    - Implement `GET /partials/pipeline-runs-table` — HTMX partial for auto-refresh (hx-trigger="every 30s")
    - Use `require_superuser` dependency
    - Mount router in `app/main.py`
    - _Requirements: 3.1, 3.2, 3.3, 3.6, 3.7_

  - [ ] 6.2 Create pipeline runs list template
    - Create `app/templates/admin_pipeline_runs.html` extending `admin_base.html`
    - Table with columns: pipeline_type, status (color badge), trigger_source, started_at, duration, steps progress
    - Filter controls (dropdowns for pipeline_type, status, trigger_source)
    - Pagination controls (20 per page)
    - Color-coded status badges: green=completed, red=failed, yellow=partial, blue=running, gray=queued
    - Animated progress indicator for running status
    - Truncated error tooltip for failed/partial runs
    - Embedded system blocks summary widget
    - HTMX polling on table body (every 30s)
    - Dark admin theme (Tailwind CSS)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.7, 5.7_

  - [ ] 6.3 Create pipeline runs table partial
    - Create `app/templates/partials/pipeline_runs_table.html` — table body only for HTMX swap
    - _Requirements: 3.7_

- [ ] 7. Routes and templates — Pipeline Run Detail
  - [ ] 7.1 Create run detail route
    - Implement `GET /pipeline-runs/{run_id}` — full page with run header and steps table
    - Return 404 if run_id not found
    - Use `require_superuser` dependency
    - _Requirements: 4.1, 4.2, 4.5_

  - [ ] 7.2 Create run detail template
    - Create `app/templates/admin_pipeline_run_detail.html` extending `admin_base.html`
    - Run header: pipeline_type, status badge, trigger_source, started_at, completed_at, total duration, operator_id, error_message
    - Blocked banner (prominent, shown when is_blocked=True with blocked_reason)
    - Steps table: step_name, block_name, status badge, started_at, duration_ms, remaining_retries, last_error_message
    - Red/amber row highlighting for failed/retrying steps
    - Expandable JSON section for step metadata
    - Runbook link display when activity event has runbook_url
    - Dark admin theme (Tailwind CSS)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 6.4_

- [ ] 8. Routes and templates — System Blocks Panel
  - [ ] 8.1 Create system blocks route
    - Implement `GET /system-blocks` — full page with 11-block health grid
    - Implement `GET /partials/system-blocks-grid` — HTMX partial for auto-refresh (hx-trigger="every 60s")
    - Use `require_superuser` dependency
    - _Requirements: 5.7, 5.8_

  - [ ] 8.2 Create system blocks templates
    - Create `app/templates/admin_system_blocks.html` extending `admin_base.html`
    - Grid layout showing all 11 blocks: scraper, scorer, generator, reviewer, reddit_api, llm_api, database, queue, cache, safety_checker, oauth_token_refresh
    - Each block card: name, health status, color indicator (green/yellow/red/gray)
    - HTMX polling on grid (every 60s)
    - Dark admin theme (Tailwind CSS)
    - _Requirements: 5.1, 5.2, 5.7, 5.8_

  - [ ] 8.3 Create system blocks grid partial
    - Create `app/templates/partials/system_blocks_grid.html` — grid only for HTMX swap
    - _Requirements: 5.8_

- [ ] 9. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Pruning task
  - [ ] 10.1 Implement pruning task
    - Create `app/tasks/pruning.py`
    - Delete pipeline_runs older than 90 days (CASCADE deletes steps)
    - Delete activity_events older than 30 days (except event_type="critical_error" retained 365 days)
    - Process deletions in batches of 1000 records
    - Log deleted counts as activity event with event_type="system_maintenance"
    - On DB error: log and retry once after 5-minute delay
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [ ]* 10.2 Write property test for data retention (Property 8)
    - **Property 8: Data retention preserves only records within retention period**
    - After pruning: no pipeline_run older than 90 days remains, no activity_event older than 30 days remains (except critical_error at 365 days). Records within retention are preserved.
    - **Validates: Requirements 7.1, 7.2**

- [ ] 11. Run status aggregation logic
  - [ ] 11.1 Implement run status from step outcomes (Property 4 logic)
    - Add helper method to ObservabilityService that computes final run status from step outcomes
    - All steps completed → run "completed", steps_completed = N
    - Any step failed and run cannot continue → run "failed"
    - Mixed results → run "partial"
    - Wire into PipelineRunContext exit logic
    - _Requirements: 1.4, 1.5, 1.6, 1.7_

  - [ ]* 11.2 Write property test for run status aggregation (Property 4)
    - **Property 4: Run status reflects aggregate step outcomes**
    - For any run with N steps: all completed → "completed" with steps_completed=N. Any failed → "failed". steps_completed always equals count of completed steps.
    - **Validates: Requirements 1.4, 1.5, 1.7**

- [ ] 12. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The implementation uses Python (FastAPI + SQLAlchemy 2.0 + Jinja2/HTMX) matching the existing project stack
- All admin routes use `require_superuser` dependency
- Templates extend `admin_base.html` (dark theme)
- Observability writes are non-blocking (background thread + dedicated session)
