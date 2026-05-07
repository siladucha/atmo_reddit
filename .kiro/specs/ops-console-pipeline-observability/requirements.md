# Requirements Document

## Introduction

Pipeline Observability layer for the ThreddOps admin panel. This feature adds first-class tracking of pipeline executions (runs and steps), system block health visualization, and automated data retention — providing operators with clear visibility into what the pipeline did, is doing, and will do. This is an additive layer on top of the existing ops-dashboard spec, focused on the core concepts needed for a demo/test showcase: pipeline run lifecycle tracking, step-level detail with timing and retries, system block status, and data pruning.

## Glossary

- **Pipeline_Run**: A single execution of a pipeline (scrape, score, generate, review, hobby, health_check, phase_evaluation) tracked as a first-class entity with lifecycle status (queued → running → completed/failed/partial)
- **Pipeline_Run_Step**: An individual step within a Pipeline_Run, representing work performed by a specific system block (e.g., "fetch posts from r/yoga", "score thread #42")
- **System_Block**: A named subsystem component of the platform: scraper, scorer, generator, reviewer, reddit_api, llm_api, database, queue, cache, safety_checker, oauth_token_refresh
- **Block_Health**: The operational status of a System_Block: healthy, degraded, down, unknown
- **Pipeline_Status**: The lifecycle state of a Pipeline_Run: queued, running, completed, failed, partial
- **Step_Status**: The lifecycle state of a Pipeline_Run_Step: pending, running, completed, failed, skipped, retrying
- **Trigger_Source**: The origin that initiated a Pipeline_Run: schedule, manual, webhook, retry, dependent
- **Run_List_View**: The UI component displaying a paginated list of Pipeline_Runs with status, timing, and summary
- **Run_Detail_View**: The UI component displaying all steps within a single Pipeline_Run with timing, retries, and errors
- **Blocks_Panel**: The UI component displaying all System_Blocks with their current health status
- **Pruning_Task**: A scheduled background task that removes observability data older than the configured retention period
- **Observability_Service**: The service layer responsible for creating, updating, and querying Pipeline_Runs and Pipeline_Run_Steps

## Requirements

### Requirement 1: Pipeline Run Data Model

**User Story:** As a developer, I want pipeline executions stored as structured records with lifecycle tracking, so that the system can display run history and status to operators.

#### Acceptance Criteria

1. THE Observability_Service SHALL store each Pipeline_Run with fields: id (UUID), pipeline_type (string), status (Pipeline_Status enum), started_at (timestamp), completed_at (timestamp nullable), trigger_source (Trigger_Source enum), operator_id (UUID nullable), is_blocked (boolean), blocked_reason (text nullable), error_message (text nullable), steps_total (integer), steps_completed (integer)
2. WHEN a Pipeline_Run is created, THE Observability_Service SHALL set status to "queued" and started_at to the current UTC timestamp
3. WHEN a Pipeline_Run transitions from "queued" to "running", THE Observability_Service SHALL update the status field to "running"
4. WHEN all steps of a Pipeline_Run complete successfully, THE Observability_Service SHALL set status to "completed" and completed_at to the current UTC timestamp
5. WHEN any step of a Pipeline_Run fails and the run cannot continue, THE Observability_Service SHALL set status to "failed", completed_at to the current UTC timestamp, and error_message to the failure description
6. WHEN some steps of a Pipeline_Run complete and others fail but the run produces partial results, THE Observability_Service SHALL set status to "partial" and completed_at to the current UTC timestamp
7. THE Observability_Service SHALL update steps_completed each time a step transitions to "completed" status

### Requirement 2: Pipeline Run Step Data Model

**User Story:** As a developer, I want individual steps within a pipeline run tracked with timing and retry information, so that operators can identify exactly where failures occur.

#### Acceptance Criteria

1. THE Observability_Service SHALL store each Pipeline_Run_Step with fields: id (UUID), run_id (UUID foreign key to pipeline_runs), step_name (string), block_name (string referencing a System_Block), status (Step_Status enum), started_at (timestamp nullable), completed_at (timestamp nullable), duration_ms (integer nullable), max_retries (integer default 3), remaining_retries (integer), last_error_message (text nullable), metadata (JSONB nullable)
2. WHEN a Pipeline_Run_Step is created, THE Observability_Service SHALL set status to "pending" and remaining_retries to max_retries
3. WHEN a Pipeline_Run_Step begins execution, THE Observability_Service SHALL set status to "running" and started_at to the current UTC timestamp
4. WHEN a Pipeline_Run_Step completes successfully, THE Observability_Service SHALL set status to "completed", completed_at to the current UTC timestamp, and duration_ms to the elapsed milliseconds since started_at
5. WHEN a Pipeline_Run_Step fails and remaining_retries is greater than 0, THE Observability_Service SHALL set status to "retrying", decrement remaining_retries by 1, and store the error in last_error_message
6. WHEN a Pipeline_Run_Step fails and remaining_retries equals 0, THE Observability_Service SHALL set status to "failed" and store the error in last_error_message
7. WHEN a Pipeline_Run_Step is not applicable to the current run, THE Observability_Service SHALL set status to "skipped"

### Requirement 3: Pipeline Runs List View

**User Story:** As an operator, I want to see a list of recent pipeline runs with their status and timing, so that I can quickly assess pipeline health and identify failures.

#### Acceptance Criteria

1. THE Run_List_View SHALL display pipeline runs in reverse chronological order with columns: pipeline_type, status (with color-coded badge), trigger_source, started_at, duration (computed from started_at and completed_at), steps progress (steps_completed / steps_total)
2. THE Run_List_View SHALL paginate results with 20 runs per page
3. THE Run_List_View SHALL support filtering by: pipeline_type, status, trigger_source, and date range
4. WHEN a Pipeline_Run has status "failed" or "partial", THE Run_List_View SHALL display the error_message in a truncated tooltip
5. WHEN a Pipeline_Run has status "running", THE Run_List_View SHALL display an animated progress indicator
6. THE Run_List_View SHALL be accessible at the route `/admin/ops/pipeline-runs`
7. THE Run_List_View SHALL auto-refresh every 30 seconds using HTMX polling

### Requirement 4: Pipeline Run Detail View

**User Story:** As an operator, I want to drill into a specific pipeline run and see all its steps with timing and error details, so that I can diagnose exactly where and why a failure occurred.

#### Acceptance Criteria

1. THE Run_Detail_View SHALL display the Pipeline_Run header with: pipeline_type, status badge, trigger_source, started_at, completed_at, total duration, operator_id (if manual trigger), error_message (if failed)
2. THE Run_Detail_View SHALL display all Pipeline_Run_Steps for the selected run in execution order with columns: step_name, block_name, status badge, started_at, duration_ms, remaining_retries, last_error_message
3. WHEN a step has status "failed" or "retrying", THE Run_Detail_View SHALL highlight that step row with a red or amber background
4. WHEN a step has metadata, THE Run_Detail_View SHALL display the metadata as an expandable JSON section
5. THE Run_Detail_View SHALL be accessible at the route `/admin/ops/pipeline-runs/{run_id}`
6. WHEN a Pipeline_Run has is_blocked set to true, THE Run_Detail_View SHALL display a prominent blocked banner with the blocked_reason

### Requirement 5: System Blocks Health Panel

**User Story:** As an operator, I want to see the health status of all system subsystems at a glance, so that I can identify which components are degraded or down.

#### Acceptance Criteria

1. THE Blocks_Panel SHALL display all 11 System_Blocks: scraper, scorer, generator, reviewer, reddit_api, llm_api, database, queue, cache, safety_checker, oauth_token_refresh
2. THE Blocks_Panel SHALL display each block with: block name, current Block_Health status (healthy/degraded/down/unknown), and a color-coded indicator (green/yellow/red/gray)
3. WHEN a System_Block has processed a Pipeline_Run_Step within the last 10 minutes with status "completed", THE Blocks_Panel SHALL set that block's health to "healthy"
4. WHEN a System_Block has more than 3 failed steps in the last 30 minutes, THE Blocks_Panel SHALL set that block's health to "degraded"
5. WHEN a System_Block has more than 10 consecutive failed steps, THE Blocks_Panel SHALL set that block's health to "down"
6. WHEN a System_Block has no Pipeline_Run_Steps in the last 60 minutes, THE Blocks_Panel SHALL set that block's health to "unknown"
7. THE Blocks_Panel SHALL be accessible at the route `/admin/ops/system-blocks` and also embedded as a summary widget on the pipeline runs list page
8. THE Blocks_Panel SHALL auto-refresh every 60 seconds using HTMX polling

### Requirement 6: Activity Events Enhancement

**User Story:** As a developer, I want activity events to indicate when operator action is required and link to relevant documentation, so that the system can surface actionable alerts.

#### Acceptance Criteria

1. THE Observability_Service SHALL store an operator_action_required boolean field on each ActivityEvent record, defaulting to false
2. THE Observability_Service SHALL store a runbook_url text field on each ActivityEvent record, defaulting to null
3. WHEN an activity event is created with operator_action_required set to true, THE Run_List_View SHALL display an "action needed" badge on the corresponding pipeline run
4. WHEN an activity event has a non-null runbook_url, THE Run_Detail_View SHALL display the runbook link as a clickable reference next to the error message

### Requirement 7: Data Retention and Pruning

**User Story:** As a developer, I want observability data automatically pruned after a retention period, so that the database does not grow unbounded and query performance remains acceptable.

#### Acceptance Criteria

1. THE Pruning_Task SHALL delete pipeline_runs records older than 90 days, cascading to their associated pipeline_run_steps
2. THE Pruning_Task SHALL delete activity_events records older than 30 days, except records where event_type equals "critical_error" which SHALL be retained for 365 days
3. THE Pruning_Task SHALL execute once daily at 03:00 UTC
4. THE Pruning_Task SHALL log the count of deleted records as an activity event with event_type "system_maintenance"
5. IF the Pruning_Task encounters a database error during deletion, THEN THE Pruning_Task SHALL log the error and retry once after a 5-minute delay
6. THE Pruning_Task SHALL process deletions in batches of 1000 records to avoid long-running transactions

### Requirement 8: Observability Write Performance

**User Story:** As a developer, I want observability writes to be non-blocking, so that pipeline execution latency is not impacted by recording observability data.

#### Acceptance Criteria

1. THE Observability_Service SHALL perform all Pipeline_Run and Pipeline_Run_Step write operations asynchronously, without blocking the calling pipeline task
2. THE Observability_Service SHALL use a dedicated database session for observability writes, separate from the pipeline's transactional session
3. IF an observability write fails, THEN THE Observability_Service SHALL log the failure and continue pipeline execution without raising an exception to the caller
4. THE Observability_Service SHALL complete observability write operations within 100 milliseconds under normal database load

### Requirement 9: Pipeline Run Creation from Pipeline Tasks

**User Story:** As a developer, I want pipeline tasks to automatically create and update Pipeline_Run records, so that every execution is tracked without manual instrumentation in each task.

#### Acceptance Criteria

1. WHEN a pipeline task (scrape, score, generate, review, hobby, health_check, phase_evaluation) begins execution, THE Observability_Service SHALL create a new Pipeline_Run record with the appropriate pipeline_type and trigger_source
2. WHEN a pipeline task creates sub-operations (e.g., scoring individual threads), THE Observability_Service SHALL create a Pipeline_Run_Step for each sub-operation with the corresponding block_name
3. WHEN a pipeline task completes, THE Observability_Service SHALL update the Pipeline_Run status to "completed" or "failed" based on the outcome
4. WHEN a pipeline task is triggered manually by an operator, THE Observability_Service SHALL record the operator_id on the Pipeline_Run
5. THE Observability_Service SHALL provide a context manager or decorator pattern that pipeline tasks use to automatically track run lifecycle without modifying core task logic
