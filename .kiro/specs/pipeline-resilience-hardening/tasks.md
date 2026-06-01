# Implementation Plan: Pipeline Resilience Hardening

## Overview

This implementation hardens the Celery + Redis task pipeline against load spikes and failure scenarios. It addresses 6 prioritized issues: DB connection pool exhaustion, missing dead letter queue, no catch-up mechanism for missed Beat schedules, absence of an LLM circuit breaker, excessive memory during scrape deduplication, and long session holds during AI tasks. All changes are backward-compatible and deployed incrementally.

## Tasks

### Task Group 1: DB Connection Pool Hardening

- [ ] 1.1 Update `database.py` engine configuration: add `pool_timeout=30`, change `max_overflow` from 10 to 20
  - _Requirements: 1.1, 1.5_

- [ ] 1.2 Create `ConnectionPoolExhausted` exception class in `app/exceptions.py` with pool utilization details
  - _Requirements: 1.2_

- [ ] 1.3 Add SQLAlchemy pool event listener (`checkout` event) that logs WARNING when utilization exceeds 80%
  - _Requirements: 1.4, 1.6_

- [ ] 1.4 Add pool pressure activity event recording (emit to `activity_events` table when threshold crossed)
  - _Requirements: 1.6_

- [ ] 1.5 Wrap `sqlalchemy.exc.TimeoutError` in task error handlers to raise `ConnectionPoolExhausted` with context
  - _Requirements: 1.2, 1.3_

- [ ]* 1.6 Write unit tests for pool timeout behavior and pressure logging
  - _Requirements: 1.1, 1.2, 1.4_

### Task Group 2: Dead Letter Queue

- [ ] 2.1 Create `DeadLetterTask` SQLAlchemy model in `app/models/dead_letter_task.py`
  - _Requirements: 2.1, 2.6_

- [ ] 2.2 Create Alembic migration for `dead_letter_tasks` table
  - _Requirements: 2.1, 2.6_

- [ ] 2.3 Create `DLQService` class in `app/services/dlq.py` with `persist_failed_task`, `retry_task`, `discard_task` methods
  - _Requirements: 2.1, 2.3, 2.4_

- [ ] 2.4 Implement accumulation alert logic: log ERROR when >5 entries in 10-minute window
  - _Requirements: 2.5_

- [ ] 2.5 Implement fallback logging when DLQ persistence fails (full task details at ERROR level)
  - _Requirements: 2.7_

- [ ] 2.6 Register Celery `task_failure` signal handler to capture permanently failed tasks into DLQ
  - _Requirements: 2.1, 2.2_

- [ ]* 2.7 Write property-based test: DLQ persist/retry/discard lifecycle correctness
  - **Property 2: DLQ completeness**
  - **Property 3: DLQ idempotency**
  - **Validates: Requirements 2.1, 2.3, 2.7**

- [ ]* 2.8 Write unit tests for accumulation alert and fallback logging
  - _Requirements: 2.5, 2.7_

### Task Group 3: Celery Beat Catch-Up Mechanism

- [ ] 3.1 Create `BeatCatchupService` class in `app/services/beat_catchup.py` with schedule detection logic
  - _Requirements: 3.1, 3.2_

- [ ] 3.2 Implement `check_and_dispatch` method: detect overdue tasks based on expected schedule hours
  - _Requirements: 3.1, 3.3_

- [ ] 3.3 Implement `record_success` method: update Redis timestamp on successful task completion
  - _Requirements: 3.2, 3.5_

- [ ] 3.4 Add cooldown enforcement: max 1 catch-up dispatch per task per 4-hour window
  - _Requirements: 3.4_

- [ ] 3.5 Integrate catch-up check into existing `system_heartbeat` task
  - _Requirements: 3.1_

- [ ] 3.6 Add `beat_catchup_enabled` system setting (default: true)
  - _Requirements: 3.6_

- [ ] 3.7 Instrument `run_full_pipeline_all_clients` and `run_hobby_pipeline_all_avatars` to call `record_success` on completion
  - _Requirements: 3.5, 3.7_

- [ ]* 3.8 Write unit tests with mocked time for schedule detection and cooldown logic
  - _Requirements: 3.1, 3.4_

### Task Group 4: LLM Circuit Breaker

- [ ] 4.1 Create `CircuitBreaker` class in `app/services/circuit_breaker.py` with Redis-backed state machine
  - _Requirements: 4.1, 4.7_

- [ ] 4.2 Create `CircuitBreakerOpen` exception class with model name and remaining cooldown
  - _Requirements: 4.2_

- [ ] 4.3 Implement state transitions: closed→open (on threshold), open→half_open (on cooldown expiry), half_open→closed (on probe success), half_open→open (on probe failure)
  - _Requirements: 4.1, 4.3, 4.4, 4.5_

- [ ] 4.4 Integrate circuit breaker check into `call_llm()` in `app/services/ai.py` (check before call, record success/failure after)
  - _Requirements: 4.1, 4.2, 4.6_

- [ ] 4.5 Update `generate_comments` task to catch `CircuitBreakerOpen` and skip thread (continue loop)
  - _Requirements: 4.8_

- [ ] 4.6 Update `generate_hobby_comments` task to catch `CircuitBreakerOpen` and skip post (continue loop)
  - _Requirements: 4.8_

- [ ] 4.7 Add `circuit_breaker_threshold` and `circuit_breaker_cooldown_seconds` system settings
  - _Requirements: 4.9_

- [ ]* 4.8 Write property-based test: circuit breaker state machine transitions are always valid
  - **Property 1: Circuit breaker state machine validity**
  - **Validates: Requirements 4.1, 4.3, 4.4, 4.5**

- [ ]* 4.9 Write unit tests for Redis state persistence and cooldown timing
  - _Requirements: 4.1, 4.7_

### Task Group 5: Memory-Efficient Scrape Deduplication

- [ ] 5.1 Create Alembic migration adding composite index `ix_reddit_threads_subreddit_native_id` on `(subreddit_id, reddit_native_id)`
  - _Requirements: 5.5_

- [ ] 5.2 Create `get_new_post_ids()` helper function in `app/services/scrape_dedup.py` using subreddit-scoped SQL query with chunked IN clause
  - _Requirements: 5.1, 5.2, 5.4_

- [ ] 5.3 Refactor `scrape_subreddit_shared` in `app/tasks/scraping.py` to use new `get_new_post_ids()` instead of loading all IDs into memory
  - _Requirements: 5.4, 5.6_

- [ ] 5.4 Refactor `scrape_subreddit_shared` in `app/services/scrape_queue.py` to use new dedup helper
  - _Requirements: 5.4, 5.6_

- [ ] 5.5 Refactor `queue_ticker.py` deduplication to use new dedup helper
  - _Requirements: 5.4, 5.6_

- [ ] 5.6 Refactor `scrape_repurpose_all_subreddits` in `app/tasks/scraping.py` to use new dedup helper
  - _Requirements: 5.4, 5.6_

- [ ] 5.7 Refactor admin route manual scrape (`routes/admin.py`) to use new dedup helper
  - _Requirements: 5.4, 5.6_

- [ ]* 5.8 Write property-based test: deduplication correctness (no false positives/negatives vs naive set approach)
  - **Property 4: Deduplication correctness**
  - **Property 5: Deduplication memory bound**
  - **Validates: Requirements 5.1, 5.2, 5.4, 5.6**

- [ ]* 5.9 Write performance test: verify dedup completes within 500ms for 50k threads per subreddit
  - _Requirements: 5.3_

### Task Group 6: Session-Per-Operation Pattern for AI Tasks

- [ ] 6.1 Create `ThreadContext`, `ClientContext`, `AvatarContext` dataclasses in `app/schemas/task_context.py` for carrying data between session phases
  - _Requirements: 6.3_

- [ ] 6.2 Refactor `generate_comments` task to use session-per-operation: load phase → close session → LLM call → re-open session → save phase
  - _Requirements: 6.2, 6.3_

- [ ] 6.3 Add optimistic concurrency check after re-acquiring session: verify thread not locked, avatar not frozen, client still active
  - _Requirements: 6.4, 6.5_

- [ ] 6.4 Refactor `generate_hobby_comments` task to use session-per-operation pattern
  - _Requirements: 6.2, 6.3_

- [ ] 6.5 Refactor `score_threads` task to release session during LLM scoring calls
  - _Requirements: 6.2, 6.3_

- [ ]* 6.6 Write unit tests for optimistic concurrency check (entity deleted, entity status changed scenarios)
  - _Requirements: 6.4, 6.5_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Task Groups 1-4 can be developed in parallel (independent services)
- Task Group 5 touches multiple files but is isolated from AI task logic
- Task Group 6 depends on Task Group 1 (pool config) being in place first

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "2.1", "2.2", "4.1", "4.2", "5.1"] },
    { "id": 1, "tasks": ["1.3", "1.4", "1.5", "2.3", "3.1", "4.3", "4.7", "5.2", "6.1"] },
    { "id": 2, "tasks": ["1.6", "2.4", "2.5", "2.6", "3.2", "3.3", "3.4", "3.6", "4.4", "5.3", "5.4", "5.5"] },
    { "id": 3, "tasks": ["2.7", "2.8", "3.5", "3.7", "4.5", "4.6", "5.6", "5.7", "6.2"] },
    { "id": 4, "tasks": ["3.8", "4.8", "4.9", "5.8", "5.9", "6.3"] },
    { "id": 5, "tasks": ["6.4", "6.5"] },
    { "id": 6, "tasks": ["6.6"] }
  ]
}
```
