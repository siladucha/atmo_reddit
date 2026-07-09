# Requirements Document

## Introduction

Automated expiry mechanism for stale comment drafts in the RAMP system. Approved drafts that are never posted and pending drafts that are never reviewed accumulate indefinitely, creating operational noise and potential risk of posting contextually irrelevant content on threads that are no longer active. This feature introduces a Celery Beat scheduled task that automatically expires stale drafts, cascades status to associated EPG slots and execution tasks, emits activity events for transparency, and provides admin visibility into expired drafts.

## Glossary

- **Draft_Expiry_Service**: The service responsible for identifying and expiring stale CommentDraft records based on configurable age thresholds.
- **Stale_Draft**: A CommentDraft record whose age exceeds the configured threshold. For `approved` drafts, age is measured from `updated_at` (set when status transitions to approved). For `pending` drafts, age is measured from `created_at` (generation time).
- **EPG_Slot**: An EPGSlot record linked to a CommentDraft via `draft_id`, representing a planned publishing action in the daily avatar program.
- **Execution_Task**: An ExecutionTask record linked to an EPGSlot, representing a delivery action (email or extension) to an executor.
- **Expiry_Threshold**: A configurable duration (in hours) after which a draft in a given status is considered stale and eligible for automatic expiry.
- **Activity_Event**: An ActivityEvent record emitting structured metadata about system actions for operational transparency.
- **System_Setting**: A key-value configuration pair in the `system_settings` table, changeable at runtime without code deployment.
- **Execution_Window**: A 2-hour forward-looking window from current time. Drafts with an associated EPGSlot whose `scheduled_at` falls within this window are protected from expiry.

## Requirements

### Requirement 1: Automatic Expiry of Approved Drafts

**User Story:** As an operator, I want approved drafts older than a configurable threshold to be automatically expired, so that stale content is never posted to threads that are no longer contextually relevant.

#### Acceptance Criteria

1. WHEN the scheduled expiry task runs, THE Draft_Expiry_Service SHALL query all CommentDraft records with `status = 'approved'` and `updated_at` older than the configured `draft_expiry_approved_hours` system setting (default: 48 hours), returning a maximum of 500 records per execution.
2. THE Draft_Expiry_Service SHALL exclude any approved draft whose associated EPGSlot has `scheduled_at` within the next 2 hours from the current time (execution window protection).
3. WHEN a stale approved CommentDraft is identified, THE Draft_Expiry_Service SHALL transition the CommentDraft status from `'approved'` to `'expired'`.
4. THE Draft_Expiry_Service SHALL process drafts in batches of 50, committing each batch independently to avoid long-running database transactions.
5. IF no stale approved drafts exist, THEN THE Draft_Expiry_Service SHALL complete without error and log a summary indicating zero drafts expired.
6. IF a database error occurs while transitioning a batch, THEN THE Draft_Expiry_Service SHALL roll back only the failed batch, log the error, and continue processing remaining batches.

### Requirement 2: Automatic Expiry of Pending Drafts

**User Story:** As an operator, I want pending drafts older than a configurable threshold to be automatically expired, so that the review queue stays relevant and operators do not waste time reviewing stale content.

#### Acceptance Criteria

1. WHEN the scheduled expiry task runs, THE Draft_Expiry_Service SHALL query all CommentDraft records with `status = 'pending'` and `created_at` older than the configured `draft_expiry_pending_hours` system setting (default: 72 hours), returning a maximum of 500 records per execution.
2. WHEN a stale pending CommentDraft is identified, THE Draft_Expiry_Service SHALL transition the CommentDraft status from `'pending'` to `'expired'`.
3. THE Draft_Expiry_Service SHALL process pending drafts in batches of 50, committing each batch independently (same mechanism as Requirement 1).
4. IF no stale pending drafts exist, THEN THE Draft_Expiry_Service SHALL complete without error and log a summary indicating zero drafts expired.
5. IF a database error occurs while transitioning a batch, THEN THE Draft_Expiry_Service SHALL roll back only the failed batch, log the error, and continue processing remaining batches.

### Requirement 3: EPG Slot Status Cascade on Expiry

**User Story:** As an operator, I want the associated EPG slot to reflect the expired state when a draft is expired, so that the daily publishing program accurately represents the current plan.

#### Acceptance Criteria

1. WHEN a CommentDraft is expired by the Draft_Expiry_Service, THE Draft_Expiry_Service SHALL query the EPGSlot record where `draft_id` matches the expired draft's ID.
2. WHEN an associated EPGSlot is found with status in (`'generated'`, `'approved'`), THE Draft_Expiry_Service SHALL transition the EPGSlot status to `'expired'` and set `skip_reason` to `'draft_stale_expired'` within the same database transaction as the CommentDraft status change.
3. IF the associated EPGSlot has a terminal status (`'posted'`, `'skipped'`, `'expired'`), THEN THE Draft_Expiry_Service SHALL leave the EPGSlot unchanged.
4. IF no EPGSlot is associated with the expired draft, THEN THE Draft_Expiry_Service SHALL proceed without error.

### Requirement 4: Execution Task Cancellation on Expiry

**User Story:** As an operator, I want associated execution tasks to be cancelled when a draft expires, so that executors do not receive emails or extension tasks for content that will never be posted.

#### Acceptance Criteria

1. WHEN an EPGSlot is transitioned to `'expired'` by the Draft_Expiry_Service, THE Draft_Expiry_Service SHALL query all ExecutionTask records where `epg_slot_id` matches the expired slot's ID.
2. WHEN an associated ExecutionTask is found with status in (`'generated'`, `'emailed'`, `'accepted'`), THE Draft_Expiry_Service SHALL transition the ExecutionTask status to `'cancelled'` and set `cancel_reason` to `'draft_stale_expired'` within the same database transaction.
3. IF the associated ExecutionTask has a terminal status (`'submitted'`, `'verified'`, `'expired'`, `'cancelled'`), THEN THE Draft_Expiry_Service SHALL leave the ExecutionTask unchanged.
4. IF no ExecutionTask is associated with the expired EPGSlot, THEN THE Draft_Expiry_Service SHALL proceed without error.
5. WHEN an ExecutionTask with `task_lifecycle_status = 'ASSIGNED'` (leased by extension) is cancelled, THE Draft_Expiry_Service SHALL set `task_lifecycle_status` to `'CANCELLED'` so the extension stops attempting execution on next poll.

### Requirement 5: Activity Event Emission

**User Story:** As an operator, I want activity events emitted when drafts are expired, so that I have full transparency into automated system actions through the existing Activity Feed.

#### Acceptance Criteria

1. WHEN one or more drafts are expired for a given client in a single task run, THE Draft_Expiry_Service SHALL emit exactly one ActivityEvent per affected client with `event_type = 'system'`, a human-readable summary message, and structured metadata.
2. THE ActivityEvent metadata SHALL include: `action` (`'stale_draft_expiry'`), `drafts_expired_count` (integer), `approved_expired_count` (integer), `pending_expired_count` (integer), `tasks_cancelled_count` (integer), and `avatar_ids` (list of distinct UUID strings for avatars whose drafts were expired).
3. THE ActivityEvent `client_id` SHALL be set to the UUID of the client associated with the expired drafts, enabling client-scoped filtering in the Activity Feed.
4. IF the call to `record_activity_event` raises an exception during event emission, THEN THE Draft_Expiry_Service SHALL log the error and continue without reverting draft expiry operations already committed.
5. THE summary message SHALL follow the pattern `"Expired {drafts_expired_count} stale draft(s) for {avatar_count} avatar(s)"` where `avatar_count` is the number of distinct avatars affected for that client.

### Requirement 6: Celery Beat Scheduled Task

**User Story:** As an operator, I want the draft expiry process to run automatically on a regular schedule, so that stale drafts are cleaned up without manual intervention.

#### Acceptance Criteria

1. THE Celery Beat schedule SHALL include a task named `'expire_stale_drafts'` that runs every 60 minutes.
2. THE `expire_stale_drafts` task SHALL be registered in `app/tasks/worker.py` by adding its containing module to the `include` list and defining its schedule entry in the `beat_schedule` dict.
3. WHEN the task executes, THE Draft_Expiry_Service SHALL acquire a distributed lock using `DistributedLock(key="expire_stale_drafts_lock", ttl=1800)` to prevent concurrent runs.
4. IF the distributed lock cannot be acquired, THEN THE task SHALL skip execution and log a warning indicating that a previous run is still in progress.
5. THE task SHALL read the `draft_expiry_enabled` setting once at the start of execution. If `'false'`, it SHALL release the lock, log that expiry is disabled, and return immediately.

### Requirement 7: Configurable Thresholds via System Settings

**User Story:** As an operator, I want to configure expiry thresholds without a code deployment, so that I can adjust the policy based on operational needs.

#### Acceptance Criteria

1. THE System_Setting `'draft_expiry_approved_hours'` SHALL control the age threshold for approved draft expiry with a default value of `48`.
2. THE System_Setting `'draft_expiry_pending_hours'` SHALL control the age threshold for pending draft expiry with a default value of `72`.
3. THE System_Setting `'draft_expiry_enabled'` SHALL act as a kill switch for the entire expiry mechanism with a default value of `'true'`.
4. WHEN `draft_expiry_enabled` is set to `'false'`, THE Draft_Expiry_Service SHALL skip all expiry processing and log that it was disabled.
5. THE settings SHALL be registered in the `DEFAULT_SETTINGS` dict in `app/services/settings.py` with group `'pipeline'`.

### Requirement 8: Admin Visibility of Expired Drafts

**User Story:** As an operator, I want expired drafts to be visually distinguishable from manually rejected drafts in the admin UI, so that I can understand the reason for each draft's terminal state.

#### Acceptance Criteria

1. THE CommentDraft model SHALL support the status value `'expired'` in addition to the existing statuses (`pending`, `approved`, `rejected`, `posted`), stored in the existing VARCHAR `status` column without requiring a database migration.
2. WHEN displaying drafts in the admin review queue and client portal review page, THE system SHALL render expired drafts with an amber/orange badge (`bg-amber-100 text-amber-800` in light theme, `bg-amber-900/50 text-amber-300` in dark theme) labeled "Expired" that is visually distinct from the red "Rejected" badge.
3. THE admin review queue filter dropdown SHALL include `'expired'` as a filterable status option, appearing after `'rejected'` in the dropdown list.
4. WHEN an expired draft is displayed, THE system SHALL show the expiry reason including the stale age in hours at the time of expiry (stored in metadata, not computed at display time).
5. IF a draft's status is `'expired'`, THEN THE system SHALL treat it as a terminal state — the draft SHALL NOT appear in approval queues, SHALL NOT be eligible for posting, and SHALL NOT count toward the avatar's daily budget.

### Requirement 9: Operational Metrics and Logging

**User Story:** As an operator, I want structured logging and metrics from the expiry process, so that I can monitor its operation and detect anomalies.

#### Acceptance Criteria

1. WHEN the expiry task completes, THE Draft_Expiry_Service SHALL log at INFO level a single summary containing: total drafts expired, approved drafts expired count, pending drafts expired count, execution tasks cancelled count, per-client expiry counts, and execution duration in milliseconds.
2. IF the number of expired drafts in a single run exceeds 50, THEN THE Draft_Expiry_Service SHALL emit a WARNING-level log that includes the actual expired count and the threshold value of 50.
3. THE Draft_Expiry_Service SHALL log each individual draft expiry at DEBUG level with: draft ID, avatar ID, client ID, original status, and age in whole hours.
4. WHEN the expiry task completes with zero drafts expired, THE Draft_Expiry_Service SHALL log at INFO level a summary indicating zero drafts expired and the execution duration in milliseconds.

## Design Notes

### Timestamp Strategy

- **Approved drafts**: Use `updated_at` as the age reference. This field is updated when a draft transitions to `approved` (either manually or via auto-approve). This correctly handles the case where a draft was generated hours before approval — the 48h clock starts at approval time, not generation time.
- **Pending drafts**: Use `created_at` as the age reference. Pending drafts have never been reviewed, so their generation time is the appropriate staleness indicator.

### Execution Window Protection

Drafts with an associated EPGSlot scheduled within the next 2 hours are protected from expiry. This prevents the race condition where the expiry task runs at 14:15, finds a 49h-old approved draft, and expires it — while the extension or email dispatch is about to execute it at 14:30. The 2-hour window ensures any draft that is actively in the execution pipeline is left alone.

### 500-Record Safety Cap

The 500-record maximum per execution is a safety cap, not a pagination mechanism. If more than 500 stale drafts exist (e.g., first-time enablement with months of backlog), the system clears them over multiple hourly runs (500/hour = 2-3 hours for a typical backlog). This prevents a single task from running too long and hitting the lock TTL.

### Status Transition Atomicity

Each batch (50 records) is committed in a single transaction that includes: draft status → expired, EPGSlot status → expired (if applicable), ExecutionTask status → cancelled (if applicable). This ensures no orphaned state. If any part of the batch fails, the entire batch rolls back and is retried on the next hourly run.
