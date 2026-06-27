# Requirements Document

## Introduction

When an avatar's CQS (Contributor Quality Score) drops to "lowest", its EPG budget becomes 0 — no content tasks are generated and no emails reach the executor. This creates a deadlock: the system cannot recover because it never prompts the executor to perform a CQS check post. The avatar remains frozen/lowest indefinitely unless someone manually intervenes (Flaky_Finder_13 incident, June 24-26, 2026).

Additionally, even healthy avatars (CQS=low/moderate/high) need periodic CQS refresh posts. The existing `check_cqs_all_avatars` task reads the LAST post in r/WhatIsMyCQS within 30 days. If that post is older than 30 days, the system cannot determine current CQS. Without a mechanism to prompt executors, CQS data goes stale for all avatars.

This feature implements the "write" side of CQS monitoring — periodically sending CQS-check execution tasks to executors. For zero-budget avatars (CQS=lowest), this creates a self-healing recovery loop. For healthy avatars, this ensures CQS data remains fresh. The executor posts "What is my cqs?" in r/WhatIsMyCQS, and the existing `check_cqs_all_avatars` daily task (the "read" side) picks up the bot's reply.

## Glossary

- **CQS_Check_Task_Generator**: The service responsible for identifying avatars that need a CQS check execution task and creating those tasks
- **CQS_Check_Scheduler**: The Celery Beat task that periodically invokes the CQS_Check_Task_Generator
- **Execution_Task_Pipeline**: The existing system that creates ExecutionTask records, composes emails, and dispatches them to executors via the Beat dispatcher
- **Avatar**: A Reddit account managed by the system, with fields including cqs_level, cqs_checked_at, executor_email, executor_email_verified, is_frozen, warming_phase, health_status
- **Executor**: A human who logs into the avatar's Reddit account and performs actions (posting comments) on behalf of the system
- **CQS_Post**: A submission in r/WhatIsMyCQS with the text "What is my cqs?" that triggers a bot reply containing the avatar's CQS level
- **EPG_Budget**: The number of daily content tasks allocated to an avatar, derived from warming_phase and cqs_level (0 when cqs_level="lowest")
- **Quiet_Hours**: The period 23:00-07:00 Israel time (Asia/Jerusalem) during which no execution task emails are sent
- **CQS_Check_Interval**: The number of days between CQS check tasks for a given avatar (7 or 30 days depending on account age and CQS level)
- **Mature_Avatar**: An avatar with reddit_account_created 90 or more days ago
- **CQS_Stale_Threshold**: The maximum age (in days) of the last r/WhatIsMyCQS post before the system considers CQS data unreliable (30 days, matching CQS_POST_LOOKBACK_DAYS)

## Requirements

### Requirement 1: CQS Check Task Generation for Zero-Budget Avatars

**User Story:** As the system operator, I want avatars with zero EPG budget to automatically receive periodic CQS check tasks, so that the executor can post in r/WhatIsMyCQS and enable the system to detect CQS recovery without manual intervention.

#### Acceptance Criteria

1. WHEN an avatar has cqs_level="lowest" AND is_frozen=false AND has a verified executor_email AND no pending CQS check task exists, THE CQS_Check_Task_Generator SHALL create an ExecutionTask with task_type="cqs_check" for that avatar.
2. WHEN an avatar has EPG budget=0 due to frozen-recovery state (is_frozen=false, cqs_level="lowest", recently unfrozen) AND no pending CQS check task exists within the current CQS_Check_Interval, THE CQS_Check_Task_Generator SHALL create an ExecutionTask with task_type="cqs_check" for that avatar.
3. THE CQS_Check_Task_Generator SHALL set the CQS check task subreddit to "WhatIsMyCQS".
4. THE CQS_Check_Task_Generator SHALL set the CQS check task generated_text to "What is my cqs?".
5. THE CQS_Check_Task_Generator SHALL set the CQS check task thread_url to "https://reddit.com/r/WhatIsMyCQS/submit".

### Requirement 2: CQS Refresh for Healthy Avatars

**User Story:** As the system operator, I want healthy avatars (CQS above "lowest") to also receive periodic CQS check tasks, so that the system can read fresh CQS data and detect any degradation before it causes pipeline disruption.

#### Acceptance Criteria

1. WHEN a Mature_Avatar has cqs_level above "lowest" AND the last CQS check task (task_type="cqs_check") was created more than 30 days ago (or never), THE CQS_Check_Task_Generator SHALL create an ExecutionTask with task_type="cqs_check" for that avatar.
2. WHEN an avatar has reddit_account_created within the last 90 days AND cqs_level above "lowest" AND the last CQS check task was created more than 7 days ago (or never), THE CQS_Check_Task_Generator SHALL create an ExecutionTask with task_type="cqs_check" for that avatar.
3. THE CQS_Check_Task_Generator SHALL apply the same exclusion rules (frozen, shadowbanned, suspended, inactive, no verified executor email) to healthy avatar CQS refresh as to zero-budget avatar checks.

### Requirement 3: Frequency-Based Scheduling Rules

**User Story:** As the system operator, I want the CQS check frequency to adapt based on account age and CQS level, so that newer or more restricted accounts are checked more frequently while established accounts are checked less often.

#### Acceptance Criteria

1. WHEN an avatar has reddit_account_created within the last 90 days, THE CQS_Check_Task_Generator SHALL use a CQS_Check_Interval of 7 days for that avatar.
2. WHEN an avatar has cqs_level="lowest", THE CQS_Check_Task_Generator SHALL use a CQS_Check_Interval of 7 days for that avatar regardless of account age.
3. WHEN an avatar has reddit_account_created 90 or more days ago AND cqs_level is above "lowest", THE CQS_Check_Task_Generator SHALL use a CQS_Check_Interval of 30 days for that avatar.
4. THE CQS_Check_Task_Generator SHALL determine the last CQS check task date from the most recent ExecutionTask with task_type="cqs_check" for that avatar (using created_at timestamp).

### Requirement 4: Exclusion Rules

**User Story:** As the system operator, I want CQS check tasks to be suppressed for accounts that cannot benefit from them, so that executors do not receive tasks for dead or permanently compromised accounts.

#### Acceptance Criteria

1. WHILE an avatar has is_frozen=true, THE CQS_Check_Task_Generator SHALL NOT create a CQS check task for that avatar.
2. WHILE an avatar has health_status="shadowbanned", THE CQS_Check_Task_Generator SHALL NOT create a CQS check task for that avatar.
3. WHILE an avatar has health_status="suspended", THE CQS_Check_Task_Generator SHALL NOT create a CQS check task for that avatar.
4. WHILE an avatar has active=false, THE CQS_Check_Task_Generator SHALL NOT create a CQS check task for that avatar.
5. IF an avatar has no executor_email OR executor_email_verified=false, THEN THE CQS_Check_Task_Generator SHALL skip that avatar and log a warning.

### Requirement 5: Anti-Spam Protection

**User Story:** As the system operator, I want the system to prevent sending duplicate or excessive CQS check tasks, so that executors are not overwhelmed and the system does not spam.

#### Acceptance Criteria

1. THE CQS_Check_Task_Generator SHALL NOT create a new CQS check task if a pending (status in generated, emailed, accepted) CQS check task already exists for that avatar.
2. THE CQS_Check_Task_Generator SHALL enforce a maximum of one active CQS check task per avatar at any time.
3. THE CQS_Check_Task_Generator SHALL respect the CQS_Check_Interval — if a CQS check task (any terminal status) was created within the interval period, no new task is generated.

### Requirement 6: Quiet Hours Enforcement

**User Story:** As the system operator, I want CQS check task emails to respect quiet hours, so that executors do not receive work emails during nighttime hours.

#### Acceptance Criteria

1. WHILE the current time is between 23:00 and 07:00 Israel time (Asia/Jerusalem), THE CQS_Check_Scheduler SHALL defer task creation to the next run after quiet hours end.
2. THE CQS_Check_Scheduler SHALL log a message indicating deferral due to quiet hours when skipping a run.

### Requirement 7: CQS Check Email Composition

**User Story:** As an executor, I want the CQS check email to contain clear step-by-step instructions, so that I can complete the task without confusion or additional guidance.

#### Acceptance Criteria

1. THE Execution_Task_Pipeline SHALL compose CQS check emails with a subject line following the format: "[RAMP] CQS Check — u/{avatar_username} — {task_code}".
2. THE Execution_Task_Pipeline SHALL include in the CQS check email body: the avatar username to log in as, the target subreddit (r/WhatIsMyCQS), the exact text to post ("What is my cqs?"), and a note that this is a routine account health check.
3. THE Execution_Task_Pipeline SHALL include the standard action link in the CQS check email for the executor to confirm task completion.
4. THE Execution_Task_Pipeline SHALL set the deadline for CQS check tasks to 48 hours from task creation (longer than standard content tasks because CQS checks are non-time-sensitive).

### Requirement 8: Integration with Existing Dispatch Pipeline

**User Story:** As the system operator, I want CQS check tasks to flow through the existing execution task dispatch pipeline, so that delivery, anti-spam, expiry, and SLA tracking work identically to content tasks.

#### Acceptance Criteria

1. THE CQS_Check_Task_Generator SHALL create ExecutionTask records with status="generated" that are dispatched by the existing `dispatch_due_email_tasks` Beat task.
2. THE Execution_Task_Pipeline SHALL recognize task_type="cqs_check" and use the CQS-specific email template when composing the email.
3. WHEN a CQS check task passes its deadline without executor confirmation, THE Execution_Task_Pipeline SHALL expire it using the same `expire_overdue_execution_tasks` mechanism as content tasks.
4. THE CQS_Check_Task_Generator SHALL set scheduled_at to the next available time after quiet hours (07:00 Israel time if created during quiet hours, or current time + 5 minutes otherwise) so that `dispatch_due_email_tasks` picks it up in its next window.

### Requirement 9: Self-Healing Loop Completion

**User Story:** As the system operator, I want the CQS check mechanism to complete the self-healing recovery loop, so that avatars automatically resume normal operations when Reddit lifts CQS restrictions.

#### Acceptance Criteria

1. WHEN the existing `check_cqs_all_avatars` task detects that an avatar's cqs_level has improved from "lowest" to "low" or above, THE system SHALL restore EPG budget to the phase-appropriate value (handled by existing AttentionBudget logic).
2. WHEN an avatar's cqs_level improves above "lowest" and EPG budget becomes greater than 0, THE CQS_Check_Task_Generator SHALL revert to the 30-day CQS_Check_Interval for that avatar (standard refresh cadence instead of recovery cadence).
3. THE CQS_Check_Task_Generator SHALL cancel any pending CQS check task when the avatar becomes frozen, shadowbanned, or suspended (cleanup on state change).

### Requirement 10: Celery Beat Scheduling

**User Story:** As the system operator, I want the CQS check task generation to run on a reliable schedule, so that eligible avatars are processed daily without manual intervention.

#### Acceptance Criteria

1. THE CQS_Check_Scheduler SHALL run as a Celery Beat periodic task once daily at 07:00 Israel time (Asia/Jerusalem).
2. THE CQS_Check_Scheduler SHALL process all eligible avatars in a single batch run.
3. THE CQS_Check_Scheduler SHALL log a summary after each run including: avatars checked, tasks created, avatars skipped (with reasons), and run duration.
4. IF the CQS_Check_Scheduler encounters an error for one avatar, THEN THE CQS_Check_Scheduler SHALL continue processing remaining avatars and include the error count in the summary.

### Requirement 11: EPG Slot Independence

**User Story:** As the system operator, I want CQS check tasks to be created independently of the EPG slot pipeline, so that they can exist without a linked EPG slot or comment draft.

#### Acceptance Criteria

1. THE CQS_Check_Task_Generator SHALL create ExecutionTask records with epg_slot_id=NULL for CQS check tasks.
2. THE CQS_Check_Task_Generator SHALL create ExecutionTask records with draft_id=NULL for CQS check tasks.
3. THE CQS_Check_Task_Generator SHALL create ExecutionTask records with thread_id=NULL for CQS check tasks.
4. THE Execution_Task_Pipeline SHALL handle CQS check tasks with NULL epg_slot_id without errors in dispatch, expiry, and verification flows.
5. THE system SHALL require a database migration to make epg_slot_id nullable on the execution_tasks table (currently NOT NULL with UNIQUE constraint) and to drop the UNIQUE constraint so that multiple tasks can have epg_slot_id=NULL.

### Requirement 12: System Setting Control

**User Story:** As the system operator, I want a kill switch for CQS check task generation, so that the feature can be disabled without a code deployment.

#### Acceptance Criteria

1. THE CQS_Check_Scheduler SHALL check the system setting "cqs_check_tasks_enabled" before processing avatars.
2. IF "cqs_check_tasks_enabled" is not set to "true", THEN THE CQS_Check_Scheduler SHALL skip execution and log a message indicating the feature is disabled.
3. THE system SHALL default "cqs_check_tasks_enabled" to "true" when not configured.
