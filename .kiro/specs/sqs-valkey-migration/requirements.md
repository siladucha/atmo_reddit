# Requirements Document

## Introduction

Migration of the RAMP platform task infrastructure from Celery+Redis to AWS SQS Standard + ElastiCache Serverless Valkey. The current system uses Celery as task queue (Redis as broker/backend) and Redis for distributed locks, rate limiting, and tick gating. The target architecture replaces Celery with direct SQS long-poll consumers (asyncio), replaces Redis broker with SQS Standard queues (with native DLQ), and replaces Redis cache/locks with Valkey Serverless (Redis-compatible protocol). The migration must preserve all existing pipeline functionality (scrape → score → generate → review), support local development without AWS (LocalStack for SQS, local Redis/Valkey for cache), and enable zero-downtime transition via parallel operation during cutover.

## Glossary

- **SQS_Producer**: The module responsible for sending task messages to AWS SQS queues with structured payloads
- **SQS_Consumer**: The asyncio-based long-poll loop that receives messages from SQS queues and dispatches them to task handlers
- **Task_Handler**: A function that executes the actual business logic for a task (scraping, scoring, generation, health check)
- **DLQ**: Dead Letter Queue — an SQS queue that automatically receives messages that fail processing after a configured number of retries (maxReceiveCount)
- **Visibility_Timeout**: The period during which a received SQS message is invisible to other consumers; if not deleted within this window, the message becomes visible again for retry
- **Valkey_Client**: The Redis-compatible client used to connect to ElastiCache Serverless Valkey for distributed locks, rate limiting, and short-lived task results
- **Scheduler**: The component that triggers periodic tasks by sending messages to SQS queues on a cron-like schedule (replaces Celery Beat)
- **Task_Message**: A JSON payload sent to SQS containing task_name, arguments, metadata (task_id, timestamp, retry_count)
- **LocalStack**: A local AWS emulator used for development and testing without real AWS credentials
- **Consumer_Loop**: The main asyncio event loop that polls multiple SQS queues concurrently with long polling (20s wait time)
- **Task_Registry**: A mapping of task_name strings to their corresponding Task_Handler functions
- **Backoff_Strategy**: The mechanism for increasing delays between retries when transient errors occur (e.g., Reddit 429)

## Requirements

### Requirement 1: SQS Message Producer

**User Story:** As a platform developer, I want a thin producer module that sends task messages to SQS queues, so that any part of the application (scheduler, API routes, orchestrator) can enqueue work without Celery dependencies.

#### Acceptance Criteria

1. THE SQS_Producer SHALL expose a function `send_task(queue_name, task_name, payload, **kwargs)` that sends a JSON Task_Message to the specified SQS queue
2. WHEN sending a task message, THE SQS_Producer SHALL include in the Task_Message: task_id (UUID), task_name, payload (dict), enqueued_at (ISO timestamp), and retry_count (default 0)
3. WHEN the SQS endpoint is unavailable, THE SQS_Producer SHALL raise a connection error with the queue name and original exception details
4. THE SQS_Producer SHALL support configurable SQS endpoint URL to allow switching between LocalStack (local) and real AWS (production)
5. WHEN a delay_seconds parameter is provided, THE SQS_Producer SHALL set the SQS DelaySeconds attribute on the message (range 0–900 seconds)
6. THE SQS_Producer SHALL use MessageGroupId and MessageDeduplicationId attributes only when targeting FIFO queues (not used in current Standard queue design)

### Requirement 2: SQS Message Consumer

**User Story:** As a platform developer, I want an asyncio-based consumer loop that polls SQS queues and dispatches messages to task handlers, so that background work executes reliably with automatic retry on failure.

#### Acceptance Criteria

1. THE SQS_Consumer SHALL poll configured SQS queues using long polling with a WaitTimeSeconds of 20 seconds
2. WHEN a message is received, THE SQS_Consumer SHALL deserialize the Task_Message JSON and dispatch to the Task_Handler registered for that task_name
3. WHEN a Task_Handler completes successfully, THE SQS_Consumer SHALL delete the message from the SQS queue
4. IF a Task_Handler raises an exception, THEN THE SQS_Consumer SHALL leave the message in the queue (do not delete) so that SQS visibility timeout triggers automatic retry
5. THE SQS_Consumer SHALL process messages from multiple queues concurrently using asyncio tasks (one polling coroutine per queue)
6. WHEN the consumer starts, THE SQS_Consumer SHALL log the list of queues being polled and the configured visibility timeouts
7. IF the SQS endpoint is unreachable, THEN THE SQS_Consumer SHALL retry connection with exponential backoff (starting at 1 second, max 60 seconds) and log each retry attempt
8. THE SQS_Consumer SHALL support graceful shutdown: stop polling, wait for in-flight task handlers to complete (up to 30 seconds), then exit

### Requirement 3: SQS Queue Configuration

**User Story:** As a platform operator, I want dedicated SQS queues per task type with appropriate visibility timeouts and DLQ routing, so that failures are isolated and automatically captured for investigation.

#### Acceptance Criteria

1. THE SQS_Producer SHALL support sending to these queues: `ramp-scrape` (scraping tasks), `ramp-ai` (scoring and generation tasks), `ramp-health` (heartbeat and phase evaluation), and `ramp-dlq` (dead letter)
2. WHEN a message in `ramp-scrape` exceeds 3 receive attempts without successful deletion, THE queue SHALL route it to `ramp-dlq`
3. WHEN a message in `ramp-ai` exceeds 3 receive attempts without successful deletion, THE queue SHALL route it to `ramp-dlq`
4. WHEN a message in `ramp-health` exceeds 5 receive attempts without successful deletion, THE queue SHALL route it to `ramp-dlq`
5. THE `ramp-scrape` queue SHALL have a visibility timeout of 300 seconds (5 minutes) to accommodate Reddit API latency
6. THE `ramp-ai` queue SHALL have a visibility timeout of 600 seconds (10 minutes) to accommodate LLM API latency
7. THE `ramp-health` queue SHALL have a visibility timeout of 60 seconds
8. THE SQS queues SHALL retain messages for 14 days (maximum SQS retention period)

### Requirement 4: Valkey Client Integration

**User Story:** As a platform developer, I want to replace the Redis connection with a Valkey-compatible client, so that distributed locks, rate limiting, and task results work identically on ElastiCache Serverless Valkey without code changes to lock/rate-limiter logic.

#### Acceptance Criteria

1. THE Valkey_Client SHALL connect using the same Redis protocol (RESP) and support all commands currently used: SET, GET, DEL, SETNX, EXPIRE, ZADD, ZCARD, ZREMRANGEBYSCORE, PING, INFO, and Lua scripting (EVAL)
2. WHEN the environment variable `VALKEY_URL` is set, THE Valkey_Client SHALL use it as the connection endpoint; otherwise it SHALL fall back to `REDIS_URL` for backward compatibility
3. THE Valkey_Client SHALL work with the existing `ScrapeDistributedLock` class without modifications to lock acquire/release logic
4. THE Valkey_Client SHALL work with the existing `ScrapeRateLimiter` class without modifications to rate limiting logic
5. IF the Valkey endpoint is unreachable, THEN THE Valkey_Client SHALL raise a connection error that existing error handling in queue_ticker and ai_pipeline can catch
6. THE Valkey_Client SHALL support TLS connections for production ElastiCache Serverless endpoints (TLS required by AWS)

### Requirement 5: Task Result Storage in Valkey

**User Story:** As a platform developer, I want short-lived task results stored in Valkey with TTL, so that the orchestrator can check task completion status without polling SQS or the database.

#### Acceptance Criteria

1. WHEN a Task_Handler completes successfully, THE SQS_Consumer SHALL store the result in Valkey under key `task_result:{task_id}` with a TTL of 300 seconds (5 minutes)
2. WHEN a Task_Handler fails, THE SQS_Consumer SHALL store the error details in Valkey under key `task_result:{task_id}` with status "failed" and a TTL of 300 seconds
3. THE task result value SHALL be a JSON object containing: task_id, task_name, status ("success" or "failed"), result (handler return value or error message), and completed_at (ISO timestamp)
4. WHEN a caller queries a task result that has expired (TTL elapsed), THE Valkey_Client SHALL return None indicating the result is no longer available

### Requirement 6: Periodic Task Scheduler

**User Story:** As a platform operator, I want a scheduler that sends task messages to SQS on configured intervals, so that periodic pipelines (scraping, AI pipeline, health checks) run without Celery Beat.

#### Acceptance Criteria

1. THE Scheduler SHALL support cron-style scheduling (hour, minute, day_of_week) and interval-based scheduling (every N seconds)
2. THE Scheduler SHALL replicate the current Celery Beat schedule: `run_full_pipeline_all_clients` at 08:00 and 14:00 UTC, `run_hobby_pipeline_all_avatars` at 10:00 UTC, `check_all_avatars_health` every 12 hours at :30, `queue_tick` every 60 seconds, `evaluate_all_avatar_phases` at 06:00 UTC, `track_karma_all_avatars` every 4 hours at :15, and `system_heartbeat` every 60 seconds
3. WHEN a scheduled time arrives, THE Scheduler SHALL send the corresponding task message to the appropriate SQS queue via SQS_Producer
4. THE Scheduler SHALL persist its last-run timestamps so that it does not re-fire tasks after a restart within the same schedule window
5. IF the Scheduler process restarts, THEN THE Scheduler SHALL check last-run timestamps and skip any schedules that already fired within their current period
6. THE Scheduler SHALL run as a lightweight asyncio loop within the same process as the SQS_Consumer (no separate container required)

### Requirement 7: Task Handler Registry and Dispatch

**User Story:** As a platform developer, I want a registry that maps task names to handler functions, so that the consumer can dispatch messages to the correct business logic without hardcoded if/else chains.

#### Acceptance Criteria

1. THE Task_Registry SHALL map these task names to their handlers: `scrape_subreddit_shared`, `scrape_professional_subreddits`, `scrape_hobby_subreddits`, `score_threads`, `generate_comments`, `generate_hobby_comments`, `generate_posts`, `run_full_pipeline_all_clients`, `run_hobby_pipeline_all_avatars`, `check_all_avatars_health`, `evaluate_all_avatar_phases`, `track_karma_all_avatars`, `system_heartbeat`, `queue_tick`
2. WHEN a Task_Message arrives with a task_name not in the Task_Registry, THE SQS_Consumer SHALL log an error with the unknown task_name and delete the message (do not retry unknown tasks)
3. THE Task_Registry SHALL allow registering new handlers at application startup without modifying the consumer loop code
4. WHEN dispatching a task, THE SQS_Consumer SHALL pass the Task_Message payload dict as keyword arguments to the Task_Handler

### Requirement 8: Pipeline Orchestration via SQS

**User Story:** As a platform developer, I want the orchestrator to chain pipeline steps by sending sequential SQS messages, so that the scrape → score → generate pipeline executes in order without Celery chain primitives.

#### Acceptance Criteria

1. WHEN `run_full_pipeline_all_clients` executes, THE orchestrator SHALL query active clients and for each client send a `score_threads` message to `ramp-ai` queue followed by a `generate_comments` message to `ramp-ai` queue with a delay (DelaySeconds) sufficient for scoring to complete
2. WHEN `run_hobby_pipeline_all_avatars` executes, THE orchestrator SHALL query active avatars and for each avatar send a `scrape_hobby_subreddits` message to `ramp-scrape` queue followed by a `generate_hobby_comments` message to `ramp-ai` queue with appropriate delay
3. IF a pipeline step fails (task result status is "failed"), THEN THE orchestrator SHALL not enqueue subsequent steps for that client or avatar
4. THE orchestrator SHALL use SQS DelaySeconds (0–900 seconds) to sequence dependent tasks within a pipeline run

### Requirement 9: Local Development Support

**User Story:** As a platform developer, I want to run the full SQS+Valkey architecture locally without AWS credentials, so that I can debug all pipelines before deploying to production.

#### Acceptance Criteria

1. WHEN the environment variable `AWS_ENDPOINT_URL` is set (e.g., `http://localhost:4566`), THE SQS_Producer and SQS_Consumer SHALL use LocalStack as the SQS endpoint
2. WHEN running locally, THE Valkey_Client SHALL connect to a local Redis or Valkey instance (default: `redis://localhost:6379/0`)
3. THE project SHALL include a docker-compose configuration that starts LocalStack (SQS emulation) and Redis/Valkey alongside the application
4. WHEN running locally with LocalStack, THE SQS_Producer SHALL auto-create queues if they do not exist (queues are ephemeral in LocalStack)
5. THE local development setup SHALL require only `docker compose up` to start all infrastructure dependencies
6. WHEN running in local mode, THE system SHALL function identically to production mode (same code paths, same message formats, same handler dispatch)

### Requirement 10: Celery Removal and Cleanup

**User Story:** As a platform developer, I want to remove all Celery dependencies after migration is complete, so that the codebase has no dead code and dependencies are minimal.

#### Acceptance Criteria

1. WHEN migration is complete, THE codebase SHALL not import or reference celery, celery.schedules, or celery_app
2. WHEN migration is complete, THE `pyproject.toml` SHALL not list celery or redis (as broker) in dependencies
3. THE task handler functions (score_threads, generate_comments, scrape_subreddit_shared, etc.) SHALL retain their business logic unchanged — only the decorator and dispatch mechanism changes
4. WHEN migration is complete, THE `docker-compose.yml` SHALL not include celery worker or celery beat service definitions
5. THE migration SHALL be performed incrementally: new SQS system runs in parallel with Celery during transition, with a feature flag (`use_sqs_tasks`) controlling which system dispatches tasks

### Requirement 11: Existing Test Compatibility

**User Story:** As a platform developer, I want all 93 existing tests to continue passing after migration, so that no regressions are introduced during the infrastructure change.

#### Acceptance Criteria

1. THE test suite SHALL pass with SQS mocked (using moto library or equivalent) without requiring LocalStack running
2. WHEN tests import task handler functions, THE handlers SHALL be callable directly as regular Python functions (no Celery task wrapper required)
3. THE test configuration SHALL provide a mock SQS client that captures sent messages for assertion without network calls
4. IF a test currently patches `celery_app.task` or uses `task.delay()`, THEN THE test SHALL be updated to use the new SQS_Producer mock interface
5. THE migration SHALL not reduce test coverage below the current level (93 tests passing)

### Requirement 12: Observability and Monitoring

**User Story:** As a platform operator, I want CloudWatch metrics and structured logging for the SQS+Valkey system, so that I can monitor queue health, detect failures, and set up alerts without custom instrumentation.

#### Acceptance Criteria

1. THE SQS_Consumer SHALL log each message received, dispatched, completed, and failed with structured fields: task_id, task_name, queue_name, duration_ms, status
2. WHEN a message is routed to DLQ (exceeds maxReceiveCount), THE system SHALL be detectable via CloudWatch metric `ApproximateNumberOfMessagesVisible` on `ramp-dlq`
3. THE SQS_Consumer SHALL emit timing metrics for task execution: time from enqueue to start (queue latency) and time from start to completion (execution duration)
4. WHEN the Valkey connection fails, THE system SHALL log the failure with connection details and continue attempting reconnection
5. THE Scheduler SHALL log each scheduled task dispatch with: task_name, queue_name, scheduled_time, actual_dispatch_time

### Requirement 13: Message Serialization Format

**User Story:** As a platform developer, I want a well-defined message serialization format, so that producers and consumers agree on payload structure and the format can evolve without breaking compatibility.

#### Acceptance Criteria

1. THE Task_Message SHALL be serialized as JSON with this schema: `{"task_id": "uuid", "task_name": "string", "payload": {}, "enqueued_at": "iso_timestamp", "retry_count": 0, "version": "1"}`
2. THE SQS_Consumer SHALL validate incoming messages against the expected schema and reject malformed messages (delete without processing, log error)
3. THE Task_Message SHALL include a `version` field to support future schema evolution
4. FOR ALL valid Task_Messages, serializing the payload to JSON and deserializing back SHALL produce an equivalent payload (round-trip property)
5. WHEN the payload contains datetime objects, THE SQS_Producer SHALL serialize them as ISO 8601 strings

