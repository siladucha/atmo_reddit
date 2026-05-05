# Implementation Plan: Reddit Data Sync

## Overview

This plan implements a centralized, rate-limit-aware Reddit data synchronization system. The implementation proceeds bottom-up: core Redis-backed services first (RateLimitTracker, RateLimitQueue), then the SyncJobExecutor Celery task, then admin routes and HTMX templates, then integration with existing scraping tasks, and finally error handling and resilience. Property-based tests (Hypothesis) and unit tests are interleaved with implementation tasks to catch regressions early.

## Tasks

- [ ] 1. Extend system settings and add validation helpers
  - [ ] 1.1 Add new Reddit sync defaults to the settings service
    - Add `reddit_throttle_rate`, `reddit_batch_size`, `reddit_max_age_hours`, and `reddit_queue_state` to the `DEFAULTS` dict in `app/services/settings.py`
    - Values: `"60"`, `"10"`, `"24"`, `"active"` respectively, all non-secret, with descriptions matching the requirements
    - Verify `init_defaults` will create them on startup
    - _Requirements: 10.1, 10.2_

  - [ ] 1.2 Create settings validation module `app/services/sync_settings_validation.py`
    - Implement `validate_throttle_rate(value: int) -> bool` — returns True iff 1 <= value <= 100
    - Implement `validate_batch_size(value: int) -> bool` — returns True iff 1 <= value <= 50
    - Implement `validate_max_age_hours(value: int) -> bool` — returns True iff 1 <= value <= 168
    - Implement `validate_queue_state(value: str) -> bool` — returns True iff value in {"active", "paused", "draining"}
    - _Requirements: 7.6, 3.1_

  - [ ]* 1.3 Write property tests for settings validation (Property 10)
    - **Property 10: Settings validation ranges**
    - Test `validate_throttle_rate`, `validate_batch_size`, `validate_max_age_hours` with `st.integers(-1000, 1000)`
    - Verify boundary conditions: exactly at min/max should pass, one outside should fail
    - **Validates: Requirements 7.6**

  - [ ]* 1.4 Write property test for queue state validation (Property 5)
    - **Property 5: Queue state validation**
    - Test `validate_queue_state` with `st.text()` for arbitrary strings plus known valid states
    - Verify only "active", "paused", "draining" are accepted
    - **Validates: Requirements 3.1**

- [ ] 2. Implement RateLimitTracker service
  - [ ] 2.1 Create `app/services/rate_limit_tracker.py` with `RateLimitState` dataclass and `RateLimitTracker` class
    - Define `RateLimitState` dataclass with fields: `remaining_requests` (float), `used_requests` (int), `reset_timestamp` (float), `last_updated_at` (float), `total_requests_today` (int), `seconds_until_reset` (float, computed)
    - Add `is_low`, `is_warning`, and `color` properties to `RateLimitState`
    - Implement `RateLimitTracker.__init__(self, redis_client)` storing the Redis client
    - Use Redis key `ratelimit:reddit:state` with TTL of 120 seconds
    - Implement `update_from_headers(headers: dict)` — extract `X-Ratelimit-Remaining`, `X-Ratelimit-Used`, `X-Ratelimit-Reset` from headers dict, store as Redis hash, set TTL, increment `total_requests_today` daily counter
    - Implement `get_state() -> RateLimitState` — read Redis hash, compute `seconds_until_reset` as `max(0, reset_timestamp - time.time())`, return dataclass. If no data in Redis, return a default state with zeros
    - Implement `increment_daily_counter()` — increment `total_requests_today` with midnight UTC expiry
    - If headers dict does not contain `X-Ratelimit-*` keys, retain previously stored values without modification
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [ ]* 2.2 Write property test for rate limit state round-trip (Property 1)
    - **Property 1: Rate limit state round-trip**
    - Generate random valid headers with `st.floats(0, 100)` for remaining, `st.integers(0, 100)` for used, `st.floats(min_value=1)` for reset
    - Call `update_from_headers` then `get_state`, verify fields match input
    - Use fakeredis for Redis mock
    - **Validates: Requirements 1.1, 1.2**

  - [ ]* 2.3 Write property test for seconds_until_reset computation (Property 2)
    - **Property 2: seconds_until_reset computation**
    - Generate random `reset_timestamp` values, verify `seconds_until_reset == max(0, reset_timestamp - current_time)`
    - Test both past and future timestamps
    - **Validates: Requirements 1.3**

  - [ ]* 2.4 Write property test for missing headers preserve state (Property 3)
    - **Property 3: Missing headers preserve state**
    - Set initial state via `update_from_headers` with valid headers, then call `update_from_headers` with empty dict
    - Verify `remaining_requests`, `used_requests`, `reset_timestamp` are unchanged
    - **Validates: Requirements 1.4**

  - [ ]* 2.5 Write property test for rate limit color thresholds (Property 9)
    - **Property 9: Rate limit color thresholds**
    - Generate `remaining_requests` with `st.floats(min_value=0, max_value=100)`
    - Verify: >30 → "green", 10–30 → "amber", <10 → "red"
    - **Validates: Requirements 6.4, 6.5, 6.6**

- [ ] 3. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Implement RateLimitQueue service
  - [ ] 4.1 Create `app/services/rate_limit_queue.py` with exception classes and `RateLimitQueue` class
    - Define `QueueTimeoutError(Exception)` and `QueueDrainingError(Exception)`
    - Implement `RateLimitQueue.__init__(self, redis_client, tracker, settings_getter)` — store Redis client, RateLimitTracker instance, and a callable that returns current settings dict
    - Use Redis keys: `ratelimit:reddit:semaphore` (distributed lock, 30s TTL), `ratelimit:reddit:queue_state`, `ratelimit:reddit:last_call_ts`, `ratelimit:reddit:queue_depth`
    - Implement `acquire(timeout=60.0)` as a context manager:
      - Check queue state: if "draining" raise `QueueDrainingError`, if "paused" block/poll until resumed or timeout
      - Increment queue depth counter on entry, decrement on exit
      - Acquire Redis semaphore (max concurrency 1) with timeout, raise `QueueTimeoutError` if exceeded
      - Enforce minimum delay of `60 / throttle_rate` seconds since last call (read `last_call_ts` from Redis)
      - If tracker shows `remaining_requests < 10` and `remaining_requests > 0`, increase delay to `seconds_until_reset / remaining_requests`
      - If `remaining_requests == 0`, block until `reset_timestamp` passes
      - Update `last_call_ts` after delay, yield control to caller, release semaphore on exit
    - Implement `get_queue_state() -> str` — read from Redis, default "active"
    - Implement `set_queue_state(state: str)` — validate state, persist in Redis
    - Implement `queue_depth() -> int` — read atomic counter from Redis
    - Implement `_calculate_delay() -> float` — read throttle_rate from settings, check tracker state, return appropriate delay
    - Read `throttle_rate` and `queue_state` from settings on each request cycle (runtime changes without restart)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 10.3_

  - [ ]* 4.2 Write property test for throttle delay calculation (Property 4)
    - **Property 4: Throttle delay calculation**
    - Generate `throttle_rate` with `st.integers(1, 100)`, `remaining_requests` with `st.floats(0, 100)`, `seconds_until_reset` with `st.floats(0, 600)`
    - Verify: remaining >= 10 → delay == 60/rate; remaining < 10 and > 0 → delay == seconds_until_reset/remaining; remaining == 0 → delay >= seconds_until_reset
    - All delays must be non-negative
    - **Validates: Requirements 2.3, 2.4, 12.5**

  - [ ]* 4.3 Write property test for draining state rejects new requests (Property 6)
    - **Property 6: Draining state rejects new requests**
    - Set queue state to "draining", call `acquire()`, verify `QueueDrainingError` is raised
    - Verify queue depth counter is not modified
    - **Validates: Requirements 3.4**

  - [ ]* 4.4 Write unit tests for RateLimitQueue
    - Test timeout raises `QueueTimeoutError`
    - Test paused queue blocks `acquire()` calls
    - Test pause → resume processes queued requests
    - Test queue depth counter increments/decrements correctly
    - Test queue state persists across new RateLimitQueue instances
    - Test queue state change creates ActivityEvent (via mock)
    - _Requirements: 2.5, 3.2, 3.3, 3.5, 3.6, 13.2_

- [ ] 5. Implement SyncJobExecutor Celery task
  - [ ] 5.1 Create batch partitioning helper and incremental sync age computation
    - Create `app/services/sync_helpers.py` with:
    - `partition_batches(subreddits: list, batch_size: int) -> list[list]` — partition list into batches of `batch_size`, preserving order
    - `compute_max_age_hours(last_scraped_at: datetime | None, max_age_hours_default: int) -> int` — if `last_scraped_at` is not None, compute hours since then (rounded up, capped at default); if None, return default. Result is always a positive integer.
    - _Requirements: 5.1, 5.3_

  - [ ]* 5.2 Write property test for batch partitioning (Property 7)
    - **Property 7: Batch partitioning preserves all subreddits**
    - Generate lists with `st.lists(st.text(), max_size=200)` and `batch_size` with `st.integers(1, 50)`
    - Verify: correct number of batches, each batch <= batch_size, concatenation equals original, no duplicates across batches
    - **Validates: Requirements 5.1**

  - [ ]* 5.3 Write property test for incremental sync age computation (Property 8)
    - **Property 8: Incremental sync age computation**
    - Generate `last_scraped_at` with `st.datetimes()` and `max_age_hours_default` with `st.integers(1, 168)`
    - Verify: null → default, non-null → hours since (rounded up, capped), result always positive integer
    - **Validates: Requirements 5.3**

  - [ ] 5.4 Create `app/tasks/sync_job.py` with `community_data_refresh` Celery task
    - Register as `community_data_refresh` with `bind=True`
    - Accept `triggered_by` (admin email) and optional `job_id` parameters
    - On start: query all active `ClientSubreddit` records across all active clients, partition into batches using `partition_batches`
    - Store initial progress in Redis hash `sync_job:{job_id}:progress` with status "running", set `sync_job:active` pointer
    - Process each batch sequentially: for each subreddit, acquire a `RateLimitQueue` slot, call `scrape_subreddit` with computed `max_age_hours`, update tracker from response headers
    - After each subreddit: update progress in Redis (completed_subreddits, total_new_posts, current_batch, estimated_time_remaining)
    - On individual subreddit failure: log error, record `ScrapeLog` with error, continue to next subreddit
    - Before each batch: check cancellation flag at `sync_job:{job_id}:cancel`; if set, stop processing, set status to "cancelled", create ActivityEvent
    - On 10+ consecutive failures: pause for 120 seconds, log warning ActivityEvent, then resume
    - On completion: set status to "completed", create ActivityEvent with summary (total subreddits, new posts, duration, error count), clear `sync_job:active` pointer
    - On failure: set status to "failed", create ActivityEvent
    - Create AuditLog entry on start with action "trigger_community_refresh"
    - _Requirements: 4.2, 4.3, 4.7, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 11.1, 11.4, 12.4_

  - [ ]* 5.5 Write unit tests for SyncJobExecutor
    - Test single subreddit failure doesn't abort the job
    - Test job completion creates ActivityEvent with summary
    - Test cancellation flag stops processing and sets status to "cancelled"
    - Test 10+ consecutive failures trigger 120-second pause
    - Test duplicate refresh is rejected when active job exists
    - _Requirements: 5.5, 5.6, 5.7, 13.3_

- [ ] 6. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Implement admin routes for refresh, queue control, and dashboard
  - [ ] 7.1 Add Community Data Refresh endpoint to admin routes
    - Add `POST /admin/settings/refresh` endpoint to `app/routes/admin.py`
    - Protected by `require_superuser` dependency (returns 403 for regular users)
    - Check if an active sync job exists (read `sync_job:active` from Redis); if so, return "Refresh already in progress" with disabled state
    - Create `community_data_refresh` Celery task with admin email and generated job ID
    - Create AuditLog entry with action `trigger_community_refresh` containing admin user ID and job ID
    - Create ActivityEvent with event_type "system" and message "Community data refresh triggered by {admin_email}"
    - Return confirmation HTML partial with job ID
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.7, 11.1_

  - [ ] 7.2 Add queue state control endpoint
    - Add `POST /admin/settings/queue-state` endpoint accepting `state` form parameter
    - Validate state is one of "active", "paused", "draining" using `validate_queue_state`
    - Call `rate_limit_queue.set_queue_state(state)`
    - Create AuditLog entry with action `queue_state_change` containing previous state, new state, and admin user ID
    - Create ActivityEvent with event_type "system" recording the state transition
    - Return updated queue control HTML partial
    - _Requirements: 3.1, 3.6, 7.3, 7.4, 11.2_

  - [ ] 7.3 Add sync settings update endpoint
    - Add `POST /admin/settings/sync-config` endpoint accepting `throttle_rate`, `batch_size`, `max_age_hours` form parameters
    - Validate each value using the validation helpers from task 1.2
    - Persist via `set_setting` for each changed value
    - Create AuditLog entry with action `sync_setting_change` for each changed setting (old value, new value, admin user ID)
    - Return updated settings form HTML partial
    - _Requirements: 7.1, 7.2, 7.5, 7.6, 11.3_

  - [ ] 7.4 Add rate limit dashboard HTMX endpoint
    - Add `GET /admin/rate-limit-status` endpoint returning an HTML partial
    - Read current `RateLimitState` from tracker, queue depth from queue, queue state
    - Render `partials/rate_limit_status.html` with all fields: remaining_requests, used_requests, seconds_until_reset (countdown), total_requests_today, queue_state, queue_depth
    - Apply color coding: green (>30), amber (10–30), red (<10) with warning icon
    - If tracker has no data, display "No recent API activity" with neutral indicator
    - Include `hx-get` with `hx-trigger="every 10s"` for auto-refresh
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [ ] 7.5 Add sync progress HTMX endpoint
    - Add `GET /admin/sync-progress` endpoint returning an HTML partial
    - Read sync job progress from Redis hash `sync_job:{job_id}:progress`
    - While job is running: render progress bar with completed/total subreddits, new posts, current batch, estimated time remaining
    - Include `hx-get` with `hx-trigger="every 5s"` for auto-refresh while running
    - When completed/failed: render final summary with total subreddits, new posts, duration, error count
    - Include "Cancel Sync" button visible only when status is "running"
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [ ] 7.6 Add cancel sync endpoint
    - Add `POST /admin/sync-cancel` endpoint
    - Set cancellation flag in Redis at `sync_job:{job_id}:cancel` with TTL 3600s
    - Return updated progress partial showing cancellation pending
    - _Requirements: 8.5_

  - [ ] 7.7 Add most recent sync status display to settings page
    - Extend the admin settings page template to show the Sync_Status of the most recent Sync_Job with timestamp
    - Show "Refresh Community Data" button, disabled with tooltip when a job is queued/running
    - Add "Reddit API Configuration" section with throttle rate, batch size, max age hours inputs
    - Add "Pause Queue" / "Resume Queue" buttons reflecting current queue state
    - _Requirements: 4.1, 4.4, 4.6, 7.1, 7.3, 7.4_

- [ ] 8. Create HTMX templates for dashboard and progress
  - [ ] 8.1 Create `app/templates/partials/rate_limit_status.html`
    - Display rate limit gauges: remaining requests (color-coded), used requests, seconds until reset (countdown), total requests today
    - Display queue state badge and queue depth
    - Include `hx-get="/admin/rate-limit-status"` with `hx-trigger="every 10s"` and `hx-swap="outerHTML"`
    - "No recent API activity" state when tracker has no data
    - Use Tailwind CSS classes consistent with existing admin panel dark theme
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [ ] 8.2 Create `app/templates/partials/sync_progress.html`
    - Progress bar showing completed_subreddits / total_subreddits
    - Stats: new posts found, current batch, estimated time remaining
    - Include `hx-get="/admin/sync-progress"` with `hx-trigger="every 5s"` and `hx-swap="outerHTML"` while running
    - Final summary view for completed/failed jobs
    - "Cancel Sync" button with `hx-post="/admin/sync-cancel"` visible only when running
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [ ] 8.3 Extend `app/templates/admin_health.html` to include rate limit dashboard section
    - Add a "Reddit API Rate Limits" section that loads `partials/rate_limit_status.html` via HTMX
    - Add sync progress section that loads `partials/sync_progress.html` via HTMX
    - _Requirements: 6.1_

  - [ ] 8.4 Extend `app/templates/admin_settings.html` with refresh button and sync config controls
    - Add "Community Data Refresh" section with the refresh button and most recent job status
    - Add "Reddit API Configuration" section with throttle rate, batch size, max age hours form fields
    - Add queue control buttons (Pause/Resume) with proper enabled/disabled states
    - Wire all controls with HTMX for inline updates
    - _Requirements: 4.1, 4.4, 4.6, 7.1, 7.3, 7.4_

  - [ ]* 8.5 Write unit tests for dashboard rendering
    - Test rate limit status partial renders all fields correctly
    - Test "No recent API activity" shown when tracker has no data
    - Test progress section shown only when sync job is running
    - Test cancel button visible only when sync job is running
    - Test HTMX polling attributes present (10s for rate limit, 5s for progress)
    - _Requirements: 13.5_

- [ ] 9. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Integrate existing scraping tasks with RateLimitQueue
  - [ ] 10.1 Create a Redis client factory and queue singleton module `app/services/redis_client.py`
    - Provide `get_redis_client()` function that returns a Redis connection from the app's Redis URL
    - Provide `get_rate_limit_queue()` function that returns a configured `RateLimitQueue` singleton
    - Provide `get_rate_limit_tracker()` function that returns a configured `RateLimitTracker` singleton
    - _Requirements: 2.1, 10.3_

  - [ ] 10.2 Modify `scrape_professional_subreddits` in `app/tasks/scraping.py` to use RateLimitQueue
    - Import `get_rate_limit_queue` and `get_rate_limit_tracker`
    - Wrap each `scrape_subreddit` call inside `with rate_limit_queue.acquire():` context manager
    - After each scrape call, update the tracker with response headers from PRAW
    - If queue is paused, the task will block until resumed (or timeout)
    - _Requirements: 9.1, 9.4, 9.5_

  - [ ] 10.3 Modify `scrape_hobby_subreddits` in `app/tasks/scraping.py` to use RateLimitQueue
    - Same pattern as 10.2: wrap `scrape_subreddit` calls with `rate_limit_queue.acquire()`
    - Update tracker with response headers after each call
    - _Requirements: 9.2, 9.4, 9.5_

  - [ ] 10.4 Modify `fetch_reddit_status` in `app/services/reddit_status.py` to use RateLimitQueue
    - Wrap the Reddit API call with `rate_limit_queue.acquire()`
    - Update tracker with response headers after the call
    - _Requirements: 9.3, 9.4_

  - [ ] 10.5 Update `app/services/reddit.py` to expose response headers after PRAW calls
    - Add a mechanism to extract `X-Ratelimit-*` headers from PRAW's internal HTTP response after each API call
    - Return or make accessible the headers dict so callers can pass them to the tracker
    - _Requirements: 1.1, 9.4_

  - [ ]* 10.6 Write integration tests for existing task integration
    - Test `scrape_professional_subreddits` acquires queue slot before each API call (mock)
    - Test `scrape_hobby_subreddits` acquires queue slot before each API call (mock)
    - Test `fetch_reddit_status` acquires queue slot before calling Reddit API (mock)
    - Test paused queue blocks scheduled scraping tasks
    - _Requirements: 13.4_

- [ ] 11. Implement error handling and resilience
  - [ ] 11.1 Add HTTP 429 handling to RateLimitQueue
    - When a Reddit API call returns HTTP 429, pause all outbound requests for the `Retry-After` header duration (default 60 seconds if absent)
    - Log a warning ActivityEvent
    - _Requirements: 12.1_

  - [ ]* 11.2 Write property test for 429 pause duration (Property 11)
    - **Property 11: 429 pause duration**
    - Generate `Retry-After` values with `st.one_of(st.none(), st.text(), st.integers(1, 600))`
    - Verify: valid positive number → use it; absent/empty/invalid → 60 seconds; result always positive
    - **Validates: Requirements 12.1**

  - [ ] 11.3 Add HTTP 5xx retry logic to RateLimitQueue
    - Retry up to 3 times with exponential backoff (2s, 4s, 8s) before marking as failed
    - _Requirements: 12.2_

  - [ ] 11.4 Implement Redis fallback with in-memory rate limiter
    - Create `InMemoryRateLimiter` dataclass in `app/services/rate_limit_queue.py`
    - Conservative 30 requests/minute token bucket
    - Switch to fallback when Redis connection is lost, log warning ActivityEvent
    - Periodically attempt Redis reconnection
    - _Requirements: 12.3_

  - [ ] 11.5 Add remaining_requests == 0 blocking to RateLimitQueue
    - When tracker detects `remaining_requests` at 0, block all new requests until `reset_timestamp` has passed
    - _Requirements: 12.5_

  - [ ]* 11.6 Write integration tests for error handling
    - Test HTTP 429 pauses queue for Retry-After duration
    - Test HTTP 5xx retries 3 times with exponential backoff
    - Test Redis connection loss triggers in-memory fallback
    - _Requirements: 13.2_

- [ ] 12. Implement admin endpoint tests
  - [ ]* 12.1 Write tests for admin refresh endpoint
    - Test `POST /admin/settings/refresh` requires superuser (403 for regular users)
    - Test refresh creates Celery task and returns job ID
    - Test refresh creates AuditLog with "trigger_community_refresh"
    - Test duplicate refresh rejected when job already running
    - _Requirements: 4.5, 13.4_

  - [ ]* 12.2 Write tests for queue state and settings endpoints
    - Test queue state change creates AuditLog with "queue_state_change"
    - Test settings change creates AuditLog with "sync_setting_change"
    - Test validation rejects out-of-range throttle rate and batch size
    - _Requirements: 11.2, 11.3, 13.4_

- [ ] 13. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate the 11 universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- All new state is stored in Redis (no new DB migrations needed)
- The implementation uses fakeredis for Redis mocking in tests
