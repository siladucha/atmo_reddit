# Implementation Plan

## Overview

Fix the Landscape Report zero-observability bug by introducing a `ReportGenerationJob` entity with full lifecycle tracking, `ReportJobEvent` audit logging, JSON schema validation, deduplication, and client-facing status display via HTMX polling.

## Task Dependency Graph

```json
{
  "waves": [
    {"tasks": ["1", "2"]},
    {"tasks": ["3.1"]},
    {"tasks": ["3.2"]},
    {"tasks": ["3.3"]},
    {"tasks": ["3.4", "3.5"]},
    {"tasks": ["3.6", "3.7"]},
    {"tasks": ["4"]}
  ]
}
```

## Tasks

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Report Generation Has Zero Observability
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate report generation creates no tracking entities
  - **Scoped PBT Approach**: For any valid client_id, calling `generate_landscape_report()` should result in a `ReportGenerationJob` entity and lifecycle events — but on unfixed code it won't
  - Test that `generate_landscape_report(db, client_id)` produces zero rows in `report_generation_jobs` table (confirms no job tracking exists)
  - Test that after generation, zero rows exist in `report_job_events` table (confirms no lifecycle events emitted)
  - Test that calling generation 3 times for same client creates 3 independent executions with no deduplication (confirms no dedup logic)
  - Test that when DB query fails mid-generation, no error record exists anywhere queryable (confirms silent failure)
  - Property assertion: for all report generation requests where client_id is valid, a job entity SHOULD exist with status in (completed, failed), events >= 2, and report_data or error_message populated
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (properties assert expected behavior that doesn't exist yet — confirms bug)
  - Document counterexamples: zero tracking rows, parallel uncoordinated executions, silent failures
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.5, 1.6_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Report Content and Route Behavior Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - Observe: `generate_landscape_report(db, client_id)` with threads+keywords returns dict with keys: `subreddits_monitored`, `threads_found`, `threads_relevant`, `competitor_mentions`, `high_intent_threads`, `brand_absent_threads`, `sample_drafts`, `share_of_voice`
  - Observe: client with no subreddits configured returns empty/minimal report without crash
  - Observe: client with subreddits but no threads in 7-day window returns graceful empty report
  - Observe: keyword matching (high/medium/low tiers) produces consistent results for given thread data
  - Observe: competitor extraction from `competitive_landscape` text produces consistent results
  - Write property-based test: for all non-bug-condition inputs (existing completed reports, other portal routes, client CRUD), the system behavior is identical
  - Write property-based test: for all valid client configurations (various keyword tiers, subreddit counts, thread volumes), `generate_landscape_report()` returns dict with all required keys and correct types
  - Write property-based test: thread query (7-day window, ordered by ups DESC, limit 200) produces same results regardless of tracking infrastructure
  - Verify tests pass on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 3. Fix for Landscape Report zero observability

  - [x] 3.1 Create ReportGenerationJob and ReportJobEvent models
    - Create `app/models/report_generation_job.py` with both SQLAlchemy models
    - `ReportGenerationJob`: id (UUID PK), client_id (FK clients.id CASCADE), onboarding_id (nullable UUID), status (String 30, default "pending"), started_at, completed_at, error_message (Text), error_step (String 100), tokens_input (Integer default 0), tokens_output (Integer default 0), ai_cost (Float default 0.0), report_data (JSONB nullable), triggered_by (String 50 default "portal"), created_at (server_default now), updated_at (onupdate now)
    - Add composite index `ix_report_gen_jobs_client_status` on (client_id, status)
    - Add index `ix_report_gen_jobs_created` on (created_at)
    - `ReportJobEvent`: id (UUID PK), job_id (FK report_generation_jobs.id CASCADE), event_type (String 50), metadata (JSONB nullable), created_at (server_default now)
    - Event types: REPORT_STARTED, STEP_COMPLETED, REPORT_COMPLETED, REPORT_FAILED, JSON_VALIDATION_FAILED, DEDUP_BLOCKED
    - Add index `ix_report_job_events_job_id` on (job_id)
    - Add index `ix_report_job_events_type_created` on (event_type, created_at)
    - Register models in `app/models/__init__.py`
    - _Bug_Condition: isBugCondition(input) — no job entity exists for generation_
    - _Expected_Behavior: job entity created with lifecycle tracking for every generation_
    - _Preservation: no changes to existing model imports or relationships_
    - _Requirements: 2.1, 2.5_

  - [x] 3.2 Create Alembic migration
    - Create `alembic/versions/lro01_report_generation_job.py`
    - Create `report_generation_jobs` table with all columns and indexes
    - Create `report_job_events` table with all columns and indexes
    - Verify migration applies cleanly: `alembic upgrade head`
    - Verify single head: `alembic heads`
    - _Requirements: 2.1, 2.5_

  - [x] 3.3 Refactor landscape report service with tracked generation
    - Modify `app/services/onboarding/landscape_report.py`
    - Add `get_or_create_report_job(db, client_id, triggered_by, onboarding_id)` — deduplication via `SELECT ... WHERE client_id AND status IN ('pending', 'processing') FOR UPDATE SKIP LOCKED`
    - Add `generate_landscape_report_tracked(db, client_id, triggered_by, onboarding_id)` — main entry: creates job, tracks steps, validates, emits events
    - Add `_emit_job_event(db, job_id, event_type, metadata)` — append event to audit log
    - Add `_validate_report_schema(report_data)` — validate required keys exist with correct types, returns (valid, error_msg)
    - Add `get_latest_report_for_client(db, client_id)` — most recent completed report_data or None
    - Add `get_job_status(db, client_id)` — current job status dict for HTMX polling
    - Wrap each generation step (fetch_subreddits, fetch_threads, analyze_threads) in try/except with error_step tracking
    - Emit STEP_COMPLETED events with duration_ms and counts at each step
    - On success: validate schema → store report_data in job → mark completed → emit REPORT_COMPLETED
    - On validation failure: mark job failed with error_step="validate_schema" → emit JSON_VALIDATION_FAILED
    - On any step failure: mark job failed with error_step and error_message → emit REPORT_FAILED
    - Preserve original `generate_landscape_report()` function signature for backward compatibility during transition
    - _Bug_Condition: no tracking, no validation, no dedup exists_
    - _Expected_Behavior: every generation tracked, validated, deduplicated_
    - _Preservation: report content logic (keyword matching, competitor detection, thread query) unchanged_
    - _Requirements: 2.1, 2.4, 2.5, 2.6, 3.1, 3.2_

  - [x] 3.4 Modify portal route for status-aware rendering
    - Modify `app/routes/portal.py` → `portal_landscape()` function
    - Replace synchronous `generate_landscape_report()` call with `get_job_status()` check
    - If completed job exists and is fresh (<1h): serve cached report_data from job
    - If no job or stale: call `generate_landscape_report_tracked()` to create new job
    - Add new endpoint `GET /clients/{id}/landscape/status` for HTMX polling (returns partial HTML with current status)
    - When job is pending/processing: render status page with HTMX poll (`hx-get` every 2s to status endpoint)
    - When job is completed: render landscape template with report data from job entity
    - When job is failed: render error state with retry button and error details
    - _Bug_Condition: portal calls generate synchronously with no status display_
    - _Expected_Behavior: portal shows generation status, serves cached results, displays errors_
    - _Preservation: `/clients/{id}/landscape` continues to render landscape template with report data_
    - _Requirements: 2.3, 2.6, 3.3_

  - [x] 3.5 Update landscape template for status-aware rendering
    - Modify `app/templates/client/landscape.html`
    - Add "Generating..." state with spinner when job is pending/processing (HTMX polling target)
    - Add error state display with retry button when job is failed (shows error_message)
    - Add HTMX attributes: `hx-get="/clients/{id}/landscape/status"`, `hx-trigger="every 2s"`, `hx-swap="outerHTML"`
    - Preserve existing report data rendering (same template structure for completed state)
    - _Bug_Condition: template shows blank/broken page on failure_
    - _Expected_Behavior: template shows appropriate status at each lifecycle stage_
    - _Preservation: report data rendering layout unchanged when completed_
    - _Requirements: 2.3, 3.3_

  - [x] 3.6 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Report Generation Creates Tracked Job
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior (job exists, events emitted, dedup works, errors recorded)
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed — generation now creates jobs, emits events, deduplicates, records errors)
    - _Requirements: 2.1, 2.4, 2.5, 2.6_

  - [x] 3.7 Verify preservation tests still pass
    - **Property 2: Preservation** - Report Content and Route Behavior Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm report content structure identical, keyword matching unchanged, competitor detection unchanged, thread query unchanged, empty/minimal reports still graceful
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 4. Checkpoint - Ensure all tests pass
  - Run full test suite: `pytest tests/ -x -q --timeout=30 --ignore=tests/test_geo_monitoring.py -k "not hypothesis"`
  - Run landscape report specific tests: `pytest tests/test_landscape_report_observability.py -v`
  - Verify imports: `python -c "from app.models.report_generation_job import ReportGenerationJob, ReportJobEvent"`
  - Verify migration: `alembic heads` shows single head
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Test file location: `tests/test_landscape_report_observability.py`
- New model file: `app/models/report_generation_job.py`
- Migration file: `alembic/versions/lro01_report_generation_job.py`
- Stale job threshold: completed jobs older than 24 hours trigger fresh generation (data refreshes daily via scraping)
- Migration is additive (CREATE TABLE only) — no data migration needed, backward compatible
- Existing `generate_landscape_report()` kept for backward compat; new code calls `generate_landscape_report_tracked()`
