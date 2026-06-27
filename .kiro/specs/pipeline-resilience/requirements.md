# Requirements Document

## Introduction

RAMP runs ~30 automated Celery Beat tasks on a single DigitalOcean droplet (2 vCPU, 4 GB RAM) with Redis as broker, lock store, and rate limiter. The system operates autonomously 24/7 with no external monitoring or alerting. This feature addresses 10 identified operational gaps that block reliable autonomous operation: no unified emergency stop, no circuit breaker on health check cascading freezes, no provenance on auto-approved drafts, Celery Beat catch-up duplication after deploys, silent demotion/freeze events, no external health monitoring, no heartbeat watcher, no generic task deduplication, no structured error classification, and no feedback loop observability. The feature is organized into three priority tiers: P0 (blocks autonomous operation), P1 (observability), and P2 (operational quality).

## Glossary

- **Kill_Switch**: A Redis key or DB setting that, when set, causes all Celery tasks to abort early before performing work
- **Emergency_Kill**: The `ramp:kill:all` Redis key that, when present, halts all pipeline tasks system-wide within one task cycle
- **Freeze_Circuit_Breaker**: A safety mechanism that pauses health check batch processing when too many avatars are frozen in a single run, preventing cascade freezes from Reddit API instability
- **Provenance_Field**: The `approved_by` column on CommentDraft indicating who or what approved the draft (system, human, autopilot)
- **Beat_Catch_Up**: The behavior where Celery Beat fires overdue crontab tasks immediately after a container restart, causing duplicate pipeline runs
- **Task_Dedup_Decorator**: A reusable decorator that prevents the same task from executing more than once within a configured time window, using Redis keys
- **Error_Classification**: A structured categorization of errors into transient (retry-worthy), permanent (skip item), and critical (halt and alert) types
- **Heartbeat_Watcher**: A lightweight process that monitors the `ramp:heartbeat:last_at` Redis key and takes recovery action if the heartbeat is stale
- **Health_Endpoint**: An HTTP endpoint exposed by the application that returns system health status for external monitoring services
- **Operator_Alert**: A notification sent to the operator (via Telegram, email, or webhook) when a critical system event occurs
- **Feedback_Loop_Event**: An ActivityEvent record that captures the specific adjustments made by the feedback loop (subreddit priority changes, hypothesis confidence updates)
- **Worker**: A Celery worker process consuming tasks from Redis queues
- **Pipeline**: The Celery-based task processing system comprising scraping, scoring, generation, and posting stages

## Requirements

### Requirement 1: Emergency Kill Switch

**User Story:** As a platform operator, I want a single Redis key that immediately halts all pipeline tasks, so that I can stop the entire system in one action during an incident without needing to toggle multiple settings or restart containers.

#### Acceptance Criteria

1. WHEN the Redis key `ramp:kill:all` exists with any non-empty value, THE Pipeline SHALL abort every Celery task at the earliest safe point before performing any external API call, database mutation, or LLM invocation
2. THE Kill_Switch check SHALL execute within the first 5 lines of every Celery task function body, before acquiring locks or loading data
3. WHEN a task is aborted due to Emergency_Kill, THE Pipeline SHALL log a WARNING-level message containing the task name and the kill switch value (reason text)
4. WHEN a task is aborted due to Emergency_Kill, THE Pipeline SHALL return immediately without raising an exception or triggering Celery retry logic
5. THE Emergency_Kill key SHALL have no TTL by default, requiring explicit removal via `DEL ramp:kill:all` to resume operations
6. THE admin UI settings page SHALL provide a toggle to set or remove the `ramp:kill:all` key with an operator-supplied reason string as the value
7. IF Redis is unreachable when checking the kill switch, THEN THE Pipeline SHALL proceed with task execution (fail-open) and log a WARNING that the kill switch check failed. NOTE: This fail-open behavior applies ONLY to the kill switch check; other Redis failures (locks, rate limiter) are classified per Requirement 9.
8. THE kill switch check SHALL be implemented as a reusable utility function callable from any task with a single line of code
9. THE admin dashboard SHALL display a prominent red banner "⚠️ SYSTEM HALTED — reason: {value}" when the `ramp:kill:all` key is active
10. THE system SHALL support task-group-level kill switches via `ramp:kill:{group}` keys (groups: scraping, scoring, generation, posting, epg, email, health). The global `ramp:kill:all` takes precedence over group keys.

### Requirement 2: Freeze Circuit Breaker

**User Story:** As a platform operator, I want the health check batch to pause automatically when too many avatars are frozen in a single run, so that a Reddit API outage does not cascade into mass freeze of the entire avatar fleet.

#### Acceptance Criteria

1. WHILE the health check batch is processing avatars, THE Freeze_Circuit_Breaker SHALL count the number of avatars that transition from `is_frozen=False` to `is_frozen=True` during the current batch run (only NEW freezes; avatars already frozen before the batch are not counted)
2. WHEN the freeze count within a single batch run exceeds a configurable threshold (default: 5), THE Freeze_Circuit_Breaker SHALL halt processing of remaining avatars in the batch
3. WHEN the Freeze_Circuit_Breaker triggers, THE Health_Checker SHALL log an ERROR-level message containing the freeze count, total batch size, and the usernames of the frozen avatars
4. WHEN the Freeze_Circuit_Breaker triggers, THE Health_Checker SHALL emit an Operator_Alert with severity "critical" containing the freeze count and a recommendation to investigate Reddit API stability
5. THE freeze threshold SHALL be configurable via the system setting `health_check_freeze_circuit_breaker_threshold` (default: 5, valid range: 2-20)
6. WHEN the Freeze_Circuit_Breaker triggers, THE Health_Checker SHALL record the event in the activity_events table with event_type `freeze_circuit_breaker_triggered` and include all frozen avatar usernames
7. THE Freeze_Circuit_Breaker counter SHALL reset to zero at the start of each new batch run (no persistence between runs)
8. WHEN the Freeze_Circuit_Breaker triggers, THE Health_Checker SHALL NOT automatically unfreeze any avatars — frozen avatars require manual operator investigation before unfreezing

### Requirement 3: Approved-By Provenance Field

**User Story:** As a platform operator, I want every approved draft to record who or what approved it, so that I can distinguish system-auto-approved drafts from human-reviewed drafts and audit autopilot behavior.

#### Acceptance Criteria

1. THE CommentDraft model SHALL have an `approved_by` field of type String (max 100 chars) that records the approval source
2. WHEN a draft is approved by the EPG auto-approve mechanism (avatar.auto_approve_drafts or client.autopilot_enabled), THE EPG_Executor SHALL set `approved_by` to "autopilot"
3. WHEN a draft is approved by a human user via the admin UI or client portal, THE Review_Service SHALL set `approved_by` to the user's email address or username
4. WHEN a draft is approved by any system process other than autopilot (batch approval, bulk operations), THE approving service SHALL set `approved_by` to "system:{process_name}"
5. THE `approved_by` field SHALL be nullable, with NULL indicating drafts approved before this feature was deployed (legacy data)
6. THE admin draft detail view SHALL display the `approved_by` value alongside the draft status
7. THE client portal review queue SHALL display the `approved_by` value for approved drafts
8. THE `approved_by` field SHALL be added via an Alembic migration that does not require downtime (nullable column addition)

### Requirement 4: Beat Catch-Up Prevention

**User Story:** As a platform operator, I want Celery Beat to not fire overdue crontab tasks after a container restart, so that deploys do not cause duplicate pipeline runs, extra LLM costs, and potential race conditions.

#### Acceptance Criteria

1. WHEN the Celery Beat container starts, THE entrypoint script SHALL delete the `celerybeat-schedule` file if it exists before launching the Beat process
2. THE Docker Compose configuration SHALL NOT mount a persistent volume for the celerybeat-schedule file (schedule state is ephemeral)
3. WHEN Beat starts with a clean schedule file, THE scheduler SHALL treat all crontab tasks as "not yet due" and wait for the next natural trigger time
4. THE entrypoint cleanup SHALL log an INFO-level message indicating whether a stale schedule file was found and deleted
5. IF the schedule file deletion fails (permission error), THEN THE entrypoint SHALL log an ERROR and continue startup rather than blocking the container

### Requirement 5: Demotion and Freeze Operator Alerts

**User Story:** As a platform operator, I want to be notified immediately when an avatar is demoted or frozen, so that I can investigate and intervene before client impact becomes noticeable.

#### Acceptance Criteria

1. WHEN an avatar's warming_phase decreases (demotion), THE Phase_Evaluator SHALL emit an Operator_Alert with severity "high" containing the avatar username, client name, previous phase, new phase, and trigger reason
2. WHEN an avatar is frozen for any reason, THE freezing service SHALL emit an Operator_Alert with severity "high" containing the avatar username, client name, freeze reason, and timestamp
3. WHEN an avatar's CQS level transitions to "lowest" resulting in zero EPG budget, THE CQS_Checker SHALL emit an Operator_Alert with severity "medium" containing the avatar username and recommendation to trigger CQS check task
4. THE Operator_Alert system SHALL support multiple delivery channels configurable via system settings: Telegram bot (webhook URL), email (to operator address), and Redis PubSub (for admin SSE)
5. WHEN Redis PubSub is configured as a channel but Redis is unreachable, THE alert system SHALL automatically fall back to email or Telegram channels without losing the alert
6. THE Operator_Alert SHALL be rate-limited to a maximum of 20 alerts per hour to prevent alert fatigue during mass events
7. WHEN the alert rate limit is exceeded, THE alert system SHALL send a single summary alert "N alerts suppressed in the last hour" and queue suppressed alerts for delivery in the next window
8. THE alert system SHALL deduplicate: if the same alert type + same entity fires more than 3 times within 1 hour, subsequent alerts SHALL be suppressed until the condition clears
9. THE alert delivery channel SHALL be configurable via system setting `operator_alert_channels` (JSON array, default: `["redis_pubsub"]`)

### Requirement 6: External Health Endpoint for Monitoring

**User Story:** As a platform operator, I want an external service to monitor the system health endpoint and alert me if the system goes down, so that I am notified of outages even when the internal heartbeat task itself has failed.

#### Acceptance Criteria

1. THE application SHALL expose a `/health/external` HTTP GET endpoint that returns a JSON response with fields: status ("healthy", "degraded", "critical"), version, uptime_seconds, last_heartbeat_age_seconds, worker_status, redis_status, and db_status
2. WHEN all components (Redis, DB, workers) are reachable and the last heartbeat is less than 5 minutes old, THE endpoint SHALL return status "healthy" with HTTP 200
3. WHEN any single component is unreachable or the heartbeat is older than 5 minutes, THE endpoint SHALL return status "degraded" with HTTP 200
4. WHEN two or more components are unreachable, THE endpoint SHALL return status "critical" with HTTP 503
5. THE `/health/external` endpoint SHALL NOT require authentication (public, for monitoring services)
6. THE `/health/external` endpoint SHALL respond within 3 seconds; IF any health check exceeds 2 seconds, THE endpoint SHALL skip that check and mark the component as "timeout"
7. THE endpoint response SHALL include a `checks` object with per-component timing in milliseconds for diagnostics

### Requirement 7: Heartbeat Watcher with Auto-Recovery

**User Story:** As a platform operator, I want an independent process to monitor the heartbeat and attempt worker recovery if the heartbeat goes stale, so that stuck workers are automatically restarted without manual intervention.

#### Acceptance Criteria

1. THE Heartbeat_Watcher SHALL run as a separate lightweight process (Docker container or supervisor subprocess) independent of the Celery worker
2. THE Heartbeat_Watcher SHALL check the `ramp:heartbeat:last_at` Redis key every 60 seconds
3. WHEN the heartbeat age exceeds 5 minutes (configurable via `heartbeat_stale_threshold_seconds`, default: 300), THE Heartbeat_Watcher SHALL emit an Operator_Alert with severity "critical" indicating workers may be unresponsive
4. WHEN the heartbeat age exceeds 5 minutes, THE Heartbeat_Watcher SHALL attempt recovery by executing `docker restart celery` and `docker restart celery-fast` via the Docker socket (mounted read-write at `/var/run/docker.sock`). Docker `restart: unless-stopped` policy ensures containers come back.
5. THE Heartbeat_Watcher SHALL wait at least 3 minutes between recovery attempts to allow the worker time to restart
6. IF Redis is unreachable from the Heartbeat_Watcher, THEN THE Heartbeat_Watcher SHALL emit an Operator_Alert indicating Redis connectivity failure and skip the recovery attempt
7. THE Heartbeat_Watcher SHALL log its own status every 5 minutes to stdout for container log visibility
8. THE Docker Compose configuration SHALL mount `/var/run/docker.sock` into the Heartbeat_Watcher container for container management access

### Requirement 8: Task Deduplication Decorator

**User Story:** As a platform operator, I want a generic decorator that prevents duplicate task execution within a time window, so that Beat catch-up bursts and accidental double-triggers do not cause duplicate pipeline runs for any task.

#### Acceptance Criteria

1. THE Task_Dedup_Decorator SHALL accept a `cooldown_seconds` parameter specifying the minimum interval between executions of the same task
2. WHEN a decorated task is invoked and a Redis key `task_dedup:{task_name}` exists with a timestamp less than `cooldown_seconds` ago, THE decorator SHALL skip execution and return immediately without raising an error
3. WHEN a decorated task executes successfully, THE decorator SHALL set the Redis key `task_dedup:{task_name}` with the current timestamp and TTL equal to `cooldown_seconds`
4. THE decorator SHALL use the task name and optionally task arguments as the dedup key, allowing the same task with different arguments to execute concurrently
5. WHEN a task is skipped due to deduplication, THE decorator SHALL log an INFO-level message containing the task name, the age of the existing dedup key, and the configured cooldown
6. IF Redis is unreachable when checking the dedup key, THEN THE decorator SHALL allow the task to proceed (fail-open) and log a WARNING
7. THE decorator SHALL be applicable to any Celery task via `@task_dedup(cooldown_seconds=N)` syntax

### Requirement 9: Structured Error Classification

**User Story:** As a platform operator, I want errors to be classified into transient, permanent, and critical categories with appropriate handling for each, so that transient errors are retried, permanent errors skip the affected item, and critical errors halt processing and alert the operator.

#### Acceptance Criteria

1. THE error classification system SHALL categorize exceptions into three types: transient (network timeouts, rate limits, temporary API errors), permanent (invalid data, missing required fields, deleted entities), and critical (authentication failures, Redis unavailable, configuration errors)
2. WHEN a transient error occurs in a batch task, THE Pipeline SHALL skip the affected item, increment an error counter, and continue processing remaining items in the batch
3. WHEN a permanent error occurs, THE Pipeline SHALL skip the affected item, log it at WARNING level with full context (item ID, error type, message), and continue processing
4. WHEN a critical error occurs, THE Pipeline SHALL halt the current task, log at ERROR level, and emit an Operator_Alert with severity "critical"
5. THE error classification SHALL be implemented as a utility module exporting a `classify_error(exception)` function that returns an enum value (TRANSIENT, PERMANENT, CRITICAL)
6. THE `classify_error` function SHALL classify `redis.ConnectionError` and `redis.TimeoutError` as CRITICAL
7. THE `classify_error` function SHALL classify `httpx.TimeoutException`, `httpx.ConnectError`, and LLM provider timeout errors as TRANSIENT
8. THE `classify_error` function SHALL classify `sqlalchemy.exc.IntegrityError` with UNIQUE violation as PERMANENT (expected dedup behavior). Other IntegrityError subtypes SHALL be classified as CRITICAL.
9. THE `classify_error` function SHALL classify generic `ValueError` as PERMANENT
10. THE distributed_lock module SHALL wrap all Redis calls in try/except, classify errors using the error classification system, and handle them according to their type (CRITICAL errors propagate, TRANSIENT errors return False from acquire)
11. ALL Redis operations across the codebase SHALL use a timeout parameter (default 5 seconds) to prevent indefinite hangs on Redis partial failures

### Requirement 10: Feedback Loop Observability

**User Story:** As a platform operator, I want full visibility into what the feedback loop changes on each run, so that I can detect drift, understand allocation changes, and audit the system's self-modification behavior.

#### Acceptance Criteria

1. WHEN the feedback loop adjusts subreddit priority for any avatar, THE Feedback_Service SHALL emit an ActivityEvent with event_type `feedback_adjustment` containing: avatar_id, subreddit_name, previous_priority, new_priority, adjustment_reason, and the outcome data that triggered the adjustment
2. WHEN the feedback loop updates hypothesis confidence, THE Feedback_Service SHALL emit an ActivityEvent with event_type `feedback_hypothesis_update` containing: hypothesis_id, previous_confidence, new_confidence, supporting_outcomes_count, and contradicting_outcomes_count
3. WHEN the feedback loop run completes, THE Feedback_Service SHALL emit a summary ActivityEvent with event_type `feedback_loop_summary` containing: total_adjustments_count, avatars_affected, subreddits_affected, hypotheses_updated, run_duration_ms, and a direction indicator (net_positive, net_negative, mixed)
4. THE admin Activity Feed SHALL display feedback loop events with dedicated formatting showing before/after values and direction arrows
5. THE feedback loop summary event SHALL be visible in the admin dashboard as a recent system event
6. WHEN the cumulative absolute priority adjustment in a single run exceeds 30% of total allocation for any avatar, THE Feedback_Service SHALL log a WARNING and emit an Operator_Alert indicating potential drift

### Requirement 11: Worker Memory Protection

**User Story:** As a platform operator, I want Celery workers to automatically recycle after processing a set number of tasks, so that memory leaks do not degrade performance or crash the worker over multi-day uptime periods.

#### Acceptance Criteria

1. THE Celery worker configuration SHALL set `worker_max_tasks_per_child` to a configurable value (default: 200)
2. WHEN a worker child process has completed `worker_max_tasks_per_child` tasks, THE Worker SHALL terminate the child process and spawn a fresh one
3. THE `worker_max_tasks_per_child` value SHALL be configurable via the environment variable `CELERY_MAX_TASKS_PER_CHILD`
4. THE worker restart due to max tasks SHALL be logged at INFO level with the process PID and task count

### Requirement 12: Redis Health Check Task

**User Story:** As a platform operator, I want a periodic task that verifies Redis connectivity and basic operations, so that Redis degradation is detected proactively before it causes task failures.

#### Acceptance Criteria

1. THE system SHALL include a Celery task `check_redis_health` that executes a PING, a SET/GET round-trip, and measures latency
2. THE `check_redis_health` task SHALL run every 5 minutes via Celery Beat
3. WHEN the Redis PING fails or latency exceeds 100ms, THE task SHALL emit an Operator_Alert with severity "high" containing the error or latency value
4. WHEN the Redis SET/GET round-trip returns inconsistent data, THE task SHALL emit an Operator_Alert with severity "critical"
5. THE task SHALL record results in the existing heartbeat Redis structure for dashboard visibility
6. IF the Redis health check task itself cannot connect to Redis (broker failure), THE failure SHALL be visible via the external health endpoint's `redis_status` field

### Requirement 13: Log Persistence Strategy

**User Story:** As a platform operator, I want container logs to be persisted to disk with rotation, so that logs survive container restarts and are available for post-incident investigation.

#### Acceptance Criteria

1. THE Docker Compose configuration SHALL configure the `json-file` logging driver for all service containers with `max-size: 50m` and `max-file: 5`
2. WHEN a container restarts, THE previous container's logs SHALL remain accessible via `docker compose logs` (retained by the logging driver, not destroyed)
3. THE total disk usage for logs per container SHALL not exceed 250 MB (5 files x 50 MB)
4. THE logging configuration SHALL apply to all containers: app, celery, celery-fast, celery-beat, redis, and db

---

## Design Notes (Non-Normative)

### Defense-in-Depth: Req 4 + Req 8

Requirement 4 (Beat Catch-Up Prevention) is the primary defense — deleting the schedule file ensures Beat doesn't fire overdue tasks. Requirement 8 (Task Dedup Decorator) is the secondary guard — even if Beat somehow double-fires (race condition, manual trigger), the decorator prevents duplicate execution. They are complementary, not redundant.

### Known Limitation: Req 12 (Redis Health Check)

The Redis health check task runs via Celery, which uses Redis as broker. If Redis is completely down, the task cannot execute. This circular dependency is intentional — the External Health Endpoint (Req 6) covers this scenario from outside the Celery worker.

### Recovery Philosophy

This spec focuses on DETECTION and HALTING, not automated RECOVERY. When circuit breakers trigger or kill switches activate, the system stops and alerts. Recovery (unfreezing avatars, resuming pipeline) requires human investigation and explicit action. Automated recovery is deferred until the system has proven reliable detection for at least 30 days.

### Relationship to Browser Extension

The Browser Extension (separate spec) adds a parallel execution channel. The resilience layer here covers the backend pipeline. Extension-specific resilience (offline handling, task timeout) is in the extension spec. The Operator_Alert system (Req 5) will also be consumed by the extension dispatcher for extension-offline fallback notifications.
