# Requirements Document

## Introduction

The Extension Grace Period feature introduces a configurable soft deadline for overdue EPG slots in the browser extension. Currently, when an executor opens the extension after the task deadline (scheduled_at + window_hours), the task is already expired and unavailable. This feature allows overdue tasks to remain executable for an additional grace period (default 3 hours beyond the original deadline) provided that safety conditions are met: the thread is still alive, the subreddit is not in dangerous hours, and the avatar has not exceeded its daily posting budget.

## Glossary

- **Extension_API**: The browser extension backend API (`/api/extension/tasks`) that returns available tasks to the executor's Chrome extension.
- **Grace_Period_Engine**: The service component responsible for evaluating whether an overdue task qualifies for grace period execution based on elapsed time and safety conditions.
- **Expire_Task_Service**: The service function (`expire_overdue_tasks`) that transitions active tasks past their deadline to "expired" status.
- **Safety_Condition_Evaluator**: The component that checks thread liveness, dangerous hours, and daily budget constraints before allowing a grace period task to be executed.
- **ExecutionTask**: The database model representing a single actionable item delivered to an executor via email or extension.
- **Grace_Period_Window**: The configurable time window (default 3 hours) added to the original deadline during which a task remains executable if safety conditions pass.
- **Original_Deadline**: The computed deadline for a task (`scheduled_at + window_hours`), currently defaulting to `scheduled_at + 2h`.
- **Grace_Deadline**: The extended deadline computed as `original_deadline + grace_period_hours`.

## Requirements

### Requirement 1: Grace Period System Setting

**User Story:** As a system operator, I want to configure the grace period duration via a system setting, so that I can adjust the leniency window without code changes.

#### Acceptance Criteria

1. THE Extension_API SHALL read the grace period duration from the system setting `epg_grace_period_hours`.
2. WHEN the system setting `epg_grace_period_hours` is not configured, THE Grace_Period_Engine SHALL use a default value of 3 hours.
3. WHEN the system setting `epg_grace_period_hours` is set to 0, THE Grace_Period_Engine SHALL disable grace period functionality entirely and all tasks past their original deadline SHALL be treated as expired.

### Requirement 2: Grace Period Task Eligibility in Extension

**User Story:** As an executor, I want tasks that are past their original deadline but within the grace period to appear in my extension, so that I can still execute them if conditions allow.

#### Acceptance Criteria

1. WHEN an executor requests tasks via the Extension_API AND a task has passed its original deadline but the current time is less than the grace deadline, THE Extension_API SHALL include the task in the response if all safety conditions pass.
2. WHEN an executor requests tasks via the Extension_API AND a task has passed its grace deadline, THE Extension_API SHALL exclude the task from the response.
3. WHEN a task is within the grace period window, THE Extension_API SHALL mark the task response payload with an `is_grace_period` flag set to true.
4. WHEN a task is within its original deadline window, THE Extension_API SHALL mark the task response payload with an `is_grace_period` flag set to false.

### Requirement 3: Safety Condition Evaluation for Grace Period Tasks

**User Story:** As a system operator, I want grace period tasks to undergo safety checks before being offered to the executor, so that overdue tasks are only available when it is safe to post.

#### Acceptance Criteria

1. WHEN a task is within the grace period window, THE Safety_Condition_Evaluator SHALL verify that the thread associated with the task is still alive (not locked, removed, or archived).
2. WHEN a task is within the grace period window, THE Safety_Condition_Evaluator SHALL verify that the current hour is not within the dangerous hours for the task's target subreddit.
3. WHEN a task is within the grace period window, THE Safety_Condition_Evaluator SHALL verify that the avatar has not exceeded its effective daily posting cap.
4. IF any safety condition fails for a grace period task, THEN THE Extension_API SHALL exclude the task from the response and not offer it to the executor.
5. WHEN all three safety conditions pass for a grace period task, THE Extension_API SHALL include the task in the response with the `is_grace_period` flag set to true.

### Requirement 4: Expire Task Service Grace Period Awareness

**User Story:** As a system operator, I want the expire task service to respect the grace period, so that tasks eligible for grace period execution are not prematurely expired.

#### Acceptance Criteria

1. WHEN the Expire_Task_Service evaluates a task for expiration, THE Expire_Task_Service SHALL compute the grace deadline as `original_deadline + epg_grace_period_hours`.
2. WHEN a task's grace deadline has not yet passed, THE Expire_Task_Service SHALL NOT transition the task to "expired" status.
3. WHEN a task's grace deadline has passed, THE Expire_Task_Service SHALL transition the task to "expired" status regardless of safety conditions.
4. WHEN `epg_grace_period_hours` is set to 0, THE Expire_Task_Service SHALL expire tasks immediately after the original deadline passes (current behavior preserved).

### Requirement 5: Grace Period Visual Distinction in Extension Response

**User Story:** As an executor, I want to see which tasks are overdue but still available, so that I can prioritize them and understand they have limited remaining time.

#### Acceptance Criteria

1. WHEN a task is within the grace period window, THE Extension_API SHALL include a `grace_period_remaining_minutes` field in the task response indicating the number of minutes remaining before the grace deadline.
2. WHEN a task is within the grace period window, THE Extension_API SHALL include a `grace_deadline` field in the task response containing the ISO 8601 timestamp of the grace deadline.
3. THE Extension_API SHALL order grace period tasks after on-time tasks but before diagnostic tasks in the response list.

### Requirement 6: Grace Period Task Execution Lifecycle

**User Story:** As a system operator, I want grace period task execution to follow the same lifecycle as regular tasks, so that no special handling is needed after the executor begins working on a task.

#### Acceptance Criteria

1. WHEN an executor accepts a grace period task via the extension, THE ExecutionTask SHALL transition to the standard lifecycle states (ASSIGNED → EXECUTING → REPORTED) without additional grace period checks.
2. WHEN a grace period task is assigned to an execution node, THE Extension_API SHALL NOT re-evaluate safety conditions for subsequent polling cycles until the task lease expires.
3. IF a grace period task's lease expires before completion, THEN THE Grace_Period_Engine SHALL re-evaluate safety conditions before making the task available again.
