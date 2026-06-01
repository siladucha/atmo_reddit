# Requirements Document

## Introduction

This feature hardens the Celery + Redis task pipeline against load spikes and failure scenarios identified during a resilience audit. It addresses 7 prioritized issues: a missing generic distributed lock class that breaks automated posting (P0), DB connection pool exhaustion during peak AI pipeline runs, missing dead letter queue for failed tasks, no catch-up mechanism for missed Celery Beat schedules, absence of an LLM circuit breaker during provider degradation, excessive memory consumption during scrape deduplication, and long session holds during AI generation tasks. The goal is to ensure the pipeline degrades gracefully under load rather than crashing or silently losing work.

## Glossary

- **Pipeline**: The Celery-based task processing system comprising scraping, scoring, generation, and posting stages
- **Worker**: A Celery worker process consuming tasks from Redis queues
- **Beat**: Celery Beat scheduler that dispatches periodic tasks on a cron-like schedule
- **DistributedLock**: A generic Redis-backed mutual exclusion primitive that accepts an arbitrary key and TTL, used by posting and other pipeline components to prevent concurrent operations
- **DLQ (Dead_Letter_Queue)**: A persistent store for tasks that have exhausted all retry attempts, enabling inspection and manual re-execution
- **Circuit_Breaker**: A fault-tolerance pattern that stops calling a failing service after consecutive failures, allowing recovery before resuming calls
- **Connection_Pool**: SQLAlchemy's pool of reusable PostgreSQL connections shared across worker threads
- **Pool_Timeout**: Maximum seconds a thread waits for a connection from the pool before raising TimeoutError
- **LLM_Provider**: External AI service (Anthropic, Google, OpenAI) called via LiteLLM for scoring and generation
- **LLM_Service**: The internal wrapper (`app/services/ai.py`) that calls LLM_Provider through LiteLLM with circuit breaker protection
- **Deduplication_Query**: The database query that filters already-scraped posts scoped to a specific subreddit
- **Catch_Up_Mechanism**: Logic that detects missed scheduled pipeline runs and triggers them retroactively
- **Peak_Window**: The 08:00 and 14:00 scheduled times when scoring + generation run for all clients simultaneously
- **Session_Hold_Time**: Duration a database session is held open during a task (3-5 minutes for LLM-calling tasks due to 60s timeout + retries)
- **Posting_Task**: The Celery task (`app/tasks/posting.py`) that acquires a per-avatar distributed lock and executes automated comment posting
- **SETNX**: Redis SET-if-Not-eXists command used for atomic lock acquisition
- **Lua_Release_Script**: A Redis Lua script that atomically checks lock ownership before deletion, ensuring only the lock holder can release

## Requirements

### Requirement 1: Generic Distributed Lock

**User Story:** As a platform operator, I want a generic distributed lock class available for all pipeline components, so that the posting system can acquire per-avatar locks without crashing.

#### Acceptance Criteria

1. THE distributed_lock module SHALL export a generic `DistributedLock` class that accepts a `key` string and `ttl` integer
2. THE DistributedLock SHALL use Redis SETNX with TTL for atomic lock acquisition
3. THE DistributedLock SHALL use a Lua_Release_Script for atomic release ensuring only the lock owner can release
4. WHEN `DistributedLock.acquire()` is called, THE DistributedLock SHALL return True if the lock was acquired, False if already held by another caller
5. THE `DistributedLock.release()` SHALL be safe to call multiple times without raising errors (idempotent)
6. WHEN the Posting_Task imports `from app.services.distributed_lock import DistributedLock`, THE import SHALL succeed without ImportError

### Requirement 2: DB Connection Pool Exhaustion Protection

**User Story:** As a platform operator, I want the database connection pool to handle peak load gracefully, so that tasks receive clear errors instead of hanging indefinitely when all connections are in use.

#### Acceptance Criteria

1. THE Connection_Pool SHALL be configured with a `pool_timeout` of 30 seconds
2. WHEN a task cannot acquire a database connection within the pool_timeout period, THE Pipeline SHALL raise a `ConnectionPoolExhausted` error with a descriptive message including current pool utilization
3. WHEN a `ConnectionPoolExhausted` error occurs in a retryable task, THE Worker SHALL retry the task with exponential backoff (60×2^attempt, max 3 retries)
4. WHEN a `ConnectionPoolExhausted` error occurs, THE Pipeline SHALL log a WARNING-level message containing the pool size, overflow count, and number of checked-out connections
5. THE Connection_Pool SHALL be configured with `max_overflow=20` to allow burst capacity of 40 total connections during peak windows
6. WHILE the connection pool utilization exceeds 80%, THE Pipeline SHALL emit a metric event to the activity log indicating pool pressure
7. THE pool pressure metric check SHALL execute at most once per 60 seconds to avoid excessive monitoring overhead
8. IF pool_pressure events have been emitted 3 or more times within 10 minutes, THEN THE Pipeline SHALL escalate the log level to ERROR

### Requirement 3: Dead Letter Queue for Failed Tasks

**User Story:** As a platform operator, I want failed tasks to be persisted after retry exhaustion, so that I can inspect failures, receive alerts, and manually re-run tasks without waiting for the next Beat cycle.

#### Acceptance Criteria

1. WHEN a Celery task exhausts all retry attempts, THE DLQ_Service SHALL persist the task metadata to a `dead_letter_tasks` database table including: task_name, task_args, task_kwargs, exception_message (max 1000 characters), exception_traceback (max 5000 characters), original_task_id, queue_name, failed_at timestamp, and retry_count
2. WHEN a task is persisted to the Dead_Letter_Queue, THE DLQ_Service SHALL record the failure in the activity_events table with event_type `dlq_entry` and include the task name and error summary
3. THE Dead_Letter_Queue SHALL provide a `retry_task(dlq_entry_id)` method that re-dispatches the original task with its original arguments and marks the DLQ entry as `retried`
4. IF `retry_task` is called on a DLQ entry whose status is not `pending`, THEN THE DLQ_Service SHALL raise ValueError
5. THE Dead_Letter_Queue SHALL provide a `discard_task(dlq_entry_id)` method that marks the entry as `discarded` without re-dispatching
6. WHEN more than 5 DLQ entries accumulate within a 10-minute window, THE DLQ_Service SHALL log an ERROR-level alert message containing the count and most common task_name
7. THE Dead_Letter_Queue table SHALL store entries with status enum: `pending`, `retried`, `discarded`
8. IF the DLQ persistence itself fails (database unavailable), THEN THE DLQ_Service SHALL log the full task details at ERROR level as a fallback to prevent silent loss
9. THE DLQ table SHALL retain entries for 30 days; a periodic cleanup task SHALL delete entries with status `retried` or `discarded` older than 30 days

### Requirement 4: Celery Beat Missed Schedule Catch-Up

**User Story:** As a platform operator, I want the AI pipeline to recover automatically if Beat was unavailable during a scheduled run, so that clients receive their daily scoring and generation even after transient outages.

#### Acceptance Criteria

1. WHEN the system heartbeat task detects that the time since the nearest past scheduled hour for `run_full_pipeline_all_clients` exceeds 2 hours, THE Catch_Up_Mechanism SHALL dispatch `run_full_pipeline_all_clients` with `triggered_by="catch_up"`
2. THE Catch_Up_Mechanism SHALL track the last successful execution timestamp of each catch-up-eligible task in Redis with key pattern `beat_catchup:{task_name}:last_success`
3. WHEN a catch-up dispatch occurs, THE Catch_Up_Mechanism SHALL log an INFO-level message indicating which scheduled run was missed and the delay duration
4. THE Catch_Up_Mechanism SHALL dispatch at most one catch-up per task per 4-hour window to prevent cascading duplicate runs
5. WHEN a catch-up task completes successfully, THE Catch_Up_Mechanism SHALL update the last_success timestamp in Redis
6. THE Catch_Up_Mechanism SHALL be configurable via system_settings key `beat_catchup_enabled` (default: true)
7. THE Catch_Up_Mechanism SHALL apply to the following tasks: `run_full_pipeline_all_clients`, `run_hobby_pipeline_all_avatars`
8. IF Redis is unavailable when reading or writing catch-up timestamps, THEN THE Catch_Up_Mechanism SHALL skip the catch-up check and log a WARNING without raising an exception
9. THE Redis keys used by the Catch_Up_Mechanism SHALL have a TTL of 48 hours

### Requirement 5: LLM Circuit Breaker

**User Story:** As a platform operator, I want the system to stop calling a degraded LLM provider after consecutive timeouts, so that workers are not blocked for extended periods and remaining tasks can be skipped or deferred.

#### Acceptance Criteria

1. WHEN 3 consecutive LLM calls to the same model fail with timeout or connection errors within a 5-minute window, THE Circuit_Breaker SHALL open and reject subsequent calls to that model for a configurable cooldown period (default: 120 seconds); any successful call resets the failure counter to zero, and the 5-minute window expires old failures if no calls occur during that period
2. WHILE the Circuit_Breaker is open for a model, THE LLM_Service SHALL raise a `CircuitBreakerOpen` error immediately without making the network call, including the remaining cooldown seconds in the error message
3. WHEN the cooldown period expires, THE Circuit_Breaker SHALL transition to half-open state and allow one probe call through
4. WHEN a probe call in half-open state succeeds, THE Circuit_Breaker SHALL close and resume normal operation
5. IF a probe call in half-open state fails, THEN THE Circuit_Breaker SHALL re-open with the same cooldown period
6. WHEN the Circuit_Breaker opens, THE LLM_Service SHALL log a WARNING-level message containing the model name, failure count, and cooldown duration
7. THE Circuit_Breaker SHALL track state per model identifier in Redis with key pattern `circuit_breaker:{model}:state`
8. WHEN a `CircuitBreakerOpen` error is raised during comment generation, THE Pipeline SHALL skip the current thread and continue processing remaining threads rather than retrying the entire task
9. THE Circuit_Breaker failure threshold and cooldown period SHALL be configurable via system_settings keys `circuit_breaker_threshold` (valid range: 1-10, default: 3) and `circuit_breaker_cooldown_seconds` (valid range: 30-600, default: 120)
10. WHEN the Circuit_Breaker transitions from open to closed (recovery), THE LLM_Service SHALL log an INFO-level message indicating the model has recovered
11. THE Redis keys used by the Circuit_Breaker SHALL have a TTL of 10 minutes

### Requirement 6: Memory-Efficient Scrape Deduplication

**User Story:** As a platform operator, I want scrape deduplication to use bounded memory regardless of total thread count, so that the system remains stable at scale (100+ clients, millions of stored threads).

#### Acceptance Criteria

1. THE Deduplication_Query SHALL use a subreddit-scoped SQL query with `EXISTS` subquery or `NOT IN` clause rather than loading all `reddit_native_id` values into Python memory
2. WHEN deduplicating scraped posts, THE Pipeline SHALL query only `reddit_native_id` values belonging to the subreddit being scraped, not the entire `reddit_threads` table
3. THE Deduplication_Query SHALL complete within 500ms for subreddits with up to 50,000 stored threads
4. WHEN the `scrape_subreddit_shared` function processes scraped posts, THE Pipeline SHALL filter duplicates using a subreddit-scoped SQL query that returns only new `reddit_native_id` values not present in the database for that subreddit; batches SHALL contain at most 50 items (current scrape limit)
5. THE `reddit_threads` table SHALL have a composite index on `(subreddit_id, reddit_native_id)` to support efficient deduplication lookups
6. FOR ALL deduplication operations, the Python process memory increase SHALL remain below 1 MB regardless of total thread count in the database
7. IF a dedup query exceeds 2 seconds, THE Pipeline SHALL log a WARNING containing the subreddit_name, duration in milliseconds, and stored thread count for that subreddit

### Requirement 7: Session-Per-Operation for AI Tasks

**User Story:** As a platform operator, I want AI pipeline tasks to release database connections during long LLM calls, so that individual task failures do not cascade into worker starvation and the connection pool remains available for other tasks.

#### Acceptance Criteria

1. WHEN a scoring or generation task encounters a database connection timeout, THE Pipeline SHALL release any held resources and retry with exponential backoff
2. WHEN a database connection timeout occurs during an LLM call (session held open waiting for LLM response), THE Pipeline SHALL close the database session before the LLM call and re-acquire it after the response returns
3. THE Pipeline SHALL implement a session-per-operation pattern for LLM-calling tasks: acquire session → load data → close session → call LLM → acquire session → save results; this applies per-thread in the generation loop (load thread+avatar+client data → close → all LLM calls for that thread → reopen → save)
4. WHEN the session-per-operation pattern is used, THE Pipeline SHALL verify that loaded entity IDs are still valid when re-acquiring the session (optimistic concurrency check)
5. IF an entity is no longer valid after re-acquiring the session (deleted or status changed), THEN THE Pipeline SHALL skip that entity and log an INFO-level message
6. WHEN the session is closed before an LLM call, THE Pipeline SHALL ensure no lazy-loaded attributes are accessed after closure by loading all required fields into plain Python variables or dataclasses before closing the session
7. THE session-per-operation pattern SHALL apply to the following functions: `generate_comment`, `edit_comment`, `select_persona`
