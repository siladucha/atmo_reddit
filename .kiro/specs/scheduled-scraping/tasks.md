# Implementation Plan: Scheduled Scraping Queue

## Overview

Replace the batch-oriented Celery Beat crontab scraping with a continuous, priority-based scraping queue. Implementation follows the database-as-queue approach with Redis for ephemeral state (rate limiter, distributed locks, backoff). All configuration is hot-reloadable via `system_settings` without worker restarts.

## Tasks

- [x] 1. Register scraping settings defaults
  - [x] 1.1 Add new setting keys to `app/services/settings.py` DEFAULTS registry
    - Add `scrape_enabled` (value: `"true"`, group: `"scraping"`, desc: "Master on/off toggle for scrape queue")
    - Add `scrape_tick_interval_seconds` (value: `"60"`, group: `"scraping"`, desc: "Queue tick interval in seconds (30–300)")
    - Add `scrape_freshness_window_hours` (value: `"12"`, group: `"scraping"`, desc: "Freshness window in hours (1–168)")
    - Add `scrape_rate_limit_rpm` (value: `"30"`, group: `"scraping"`, desc: "Max Reddit API requests per minute (1–60)")
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.2, 3.3_

- [x] 2. Implement Rate Limiter service
  - [x] 2.1 Create `app/services/rate_limiter.py` with `ScrapeRateLimiter` class
    - Implement `__init__(self, redis_client)` storing the Redis connection
    - Implement `is_allowed(max_rpm: int) -> bool` using Redis sorted set sliding window (ZREMRANGEBYSCORE + ZCARD)
    - Implement `record_request() -> None` using ZADD with current timestamp
    - Implement `get_utilization(max_rpm: int) -> dict` returning `{"current_count": int, "max_rpm": int, "utilization_pct": float}`
    - Implement `activate_backoff(duration_seconds: int = 300) -> None` setting backoff key with TTL
    - Implement `is_in_backoff() -> bool` checking backoff key existence
    - Use `REDIS_KEY = "rate_limiter:scrape"` (sorted set), `BACKOFF_KEY = "rate_limiter:backoff"` (string with TTL), `WINDOW_SECONDS = 60`
    - When in backoff mode, `is_allowed()` uses `max_rpm // 2` as effective limit
    - _Requirements: 3.1, 3.4, 3.5, 8.5_

  - [ ]* 2.2 Write property test for rate limiter enforcement
    - **Property 5: Rate limiter enforcement**
    - **Validates: Requirements 3.1**

  - [ ]* 2.3 Write property test for backoff halving
    - **Property 11: Backoff halves effective rate limit**
    - **Validates: Requirements 8.5**

  - [ ]* 2.4 Write property test for rate limiter utilization
    - **Property 10: Rate limiter utilization**
    - **Validates: Requirements 6.7**

- [x] 3. Implement Distributed Lock service
  - [x] 3.1 Create `app/services/distributed_lock.py` with `ScrapeDistributedLock` class
    - Implement `__init__(self, redis_client)` storing the Redis connection
    - Implement `acquire(subreddit_name: str, ttl: int = 300) -> bool` using `SET key value NX EX ttl`
    - Value stored: worker hostname + timestamp for debugging
    - Implement `release(subreddit_name: str) -> None` using Lua script for atomic release (only release if value matches)
    - Implement `is_locked(subreddit_name: str) -> bool` checking key existence
    - Implement `get_all_locks() -> list[str]` using Redis SCAN with prefix `scrape_lock:`
    - Use `KEY_PREFIX = "scrape_lock:"`, `DEFAULT_TTL = 300`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ]* 3.2 Write unit tests for distributed lock
    - Test acquire returns True on first call, False on second
    - Test release allows re-acquisition
    - Test TTL expiry allows re-acquisition
    - Test Lua script atomicity (only owner can release)
    - Test `get_all_locks()` returns correct list
    - _Requirements: 4.1, 4.2, 4.4, 4.5_

- [x] 4. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement Queue Ticker task
  - [x] 5.1 Create `app/tasks/queue_ticker.py` with `queue_tick` Celery task
    - Register task with `@celery_app.task(name="queue_tick")`
    - Implement tick-interval gating: store last run timestamp in Redis (`queue_tick:last_run`), skip if not enough time elapsed per `scrape_tick_interval_seconds` setting
    - Read `scrape_enabled` from DB — if `"false"`, log "paused" and return `{"status": "paused"}`
    - Call `rate_limiter.is_allowed(max_rpm)` — if False, log "rate limited" and return `{"status": "rate_limited"}`
    - Query next stale subreddit using SQLAlchemy (ORDER BY last_scraped_at ASC NULLS FIRST, subreddit_name ASC, LIMIT 5)
    - If no candidates, return `{"status": "all_fresh"}`
    - Try to acquire distributed lock for top candidate — if fails, try next (up to 3 attempts)
    - Call `rate_limiter.record_request()`
    - Dispatch `scrape_single_subreddit.delay(subreddit_name, client_id)`
    - Return `{"status": "dispatched", "subreddit": subreddit_name}`
    - Wrap entire body in try/except for `redis.ConnectionError` and `sqlalchemy.exc.OperationalError` — skip tick gracefully
    - _Requirements: 1.4, 1.5, 1.6, 1.7, 2.7, 3.4, 3.6, 4.3, 8.1, 8.2_

  - [x] 5.2 Implement `scrape_single_subreddit` Celery task in `app/tasks/queue_ticker.py`
    - Register with `@celery_app.task(name="scrape_single_subreddit", bind=True, max_retries=0)`
    - Record start ActivityEvent (`event_type="scrape"`, message with subreddit + client name)
    - Call existing `scrape_subreddit()` from `app/services/reddit.py`
    - Deduplicate posts using existing `deduplicate_posts()`
    - Save new RedditThread records
    - Update `client_subreddits.last_scraped_at` to current UTC timestamp
    - Record ScrapeLog entry
    - Record completion ActivityEvent with metadata: subreddit_name, posts_found, posts_new, duration_ms
    - On HTTP 429 (TooManyRequests): call `rate_limiter.activate_backoff()`, record system ActivityEvent, do NOT update last_scraped_at
    - Use try/finally to guarantee `lock.release(subreddit_name)` and `db.close()`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 8.4, 8.5_

  - [x] 5.3 Register `queue_tick` in Celery Beat schedule in `app/tasks/worker.py`
    - Add `"scrape-queue-tick"` entry with `"task": "queue_tick"` and `"schedule": 60.0`
    - _Requirements: 2.1, 2.2_

  - [ ]* 5.4 Write unit tests for queue ticker
    - Test ticker paused: `scrape_enabled=false` → returns `{"status": "paused"}`
    - Test ticker rate limited: rate limiter returns False → returns `{"status": "rate_limited"}`
    - Test ticker all fresh: no stale subreddits → returns `{"status": "all_fresh"}`
    - Test lock fallback: first candidate locked → selects second candidate
    - Test Redis down: ConnectionError → graceful skip with `{"status": "error"}`
    - Test DB down: OperationalError → graceful skip with `{"status": "error"}`
    - _Requirements: 1.4, 1.6, 3.4, 4.3, 8.1, 8.2_

  - [ ]* 5.5 Write property test for queue filtering and depth
    - **Property 1: Queue filtering and depth**
    - **Validates: Requirements 1.1, 6.1**

  - [ ]* 5.6 Write property test for staleness score computation
    - **Property 2: Staleness score computation**
    - **Validates: Requirements 1.2, 1.3**

  - [ ]* 5.7 Write property test for queue ordering
    - **Property 3: Queue ordering and waiting list completeness**
    - **Validates: Requirements 1.4, 1.5, 1.7, 6.4**

- [x] 6. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement Queue Dashboard service
  - [x] 7.1 Create `app/services/scrape_queue.py` with dashboard data functions
    - Implement `get_queue_status(db, redis_client, freshness_hours: int) -> dict` returning total queue depth, stale count, processing speed, ETA, rate limiter utilization, scrape_enabled state
    - Implement `get_waiting_list(db, redis_client, freshness_hours: int) -> list[dict]` returning sorted list with subreddit_name, client_name, last_scraped_at, staleness_score, is_locked flag
    - Implement `get_processing_speed(db, window_minutes: int = 5) -> float` counting scrape ActivityEvents in last N minutes divided by N
    - Implement `get_stale_count(db, freshness_hours: int) -> int` counting subreddits past freshness window
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.9_

  - [ ]* 7.2 Write property test for stale subreddit count
    - **Property 7: Stale subreddit count**
    - **Validates: Requirements 6.2**

  - [ ]* 7.3 Write property test for processing speed calculation
    - **Property 8: Processing speed calculation**
    - **Validates: Requirements 6.3**

  - [ ]* 7.4 Write property test for ETA calculation
    - **Property 9: ETA calculation**
    - **Validates: Requirements 6.6**

  - [ ]* 7.5 Write property test for scrape completion event metadata
    - **Property 6: Scrape completion event metadata**
    - **Validates: Requirements 5.3**

- [x] 8. Implement Queue Dashboard routes and templates
  - [x] 8.1 Add queue dashboard routes to `app/routes/admin.py`
    - `GET /admin/scrape-queue` — full dashboard page
    - `GET /admin/scrape-queue/status` — HTMX partial for stats cards (auto-refresh target)
    - `GET /admin/scrape-queue/waiting-list` — HTMX partial for waiting subreddits table
    - `POST /admin/scrape-queue/toggle` — toggle `scrape_enabled` setting
    - `POST /admin/scrape-queue/settings` — update tick interval, freshness window, rate limit with validation (reject out-of-range values with descriptive error)
    - All routes require `require_superuser` dependency
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 7.1, 7.2, 7.3, 7.4, 2.8, 2.9, 3.7_

  - [x] 8.2 Create `app/templates/admin_scrape_queue.html` dashboard template
    - Stats cards: total queue depth, stale count, processing speed (req/min), ETA to empty, rate limiter utilization %
    - Prominent scrape_enabled toggle with visual state (green/red)
    - Warning banner when scraping is paused
    - "All subreddits are fresh" message when queue is empty
    - Settings form: tick interval, freshness window, rate limit (with validation feedback)
    - Waiting list table: subreddit name, client name, last_scraped_at, staleness score, lock indicator
    - Currently processing indicator (subreddits with active locks)
    - HTMX polling every 30 seconds on status and waiting-list partials
    - Use `admin_base.html` dark theme, set `active_nav: "scrape-queue"`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 7.3, 7.4_

  - [x] 8.3 Create HTMX partial templates
    - `app/templates/partials/scrape_queue_status.html` — stats cards partial
    - `app/templates/partials/scrape_queue_waiting_list.html` — waiting list table partial
    - _Requirements: 6.8_

  - [ ]* 8.4 Write property test for settings range validation
    - **Property 4: Settings range validation**
    - **Validates: Requirements 2.8, 2.9, 3.7**

- [x] 9. Wire navigation and finalize integration
  - [x] 9.1 Add "Scrape Queue" link to admin navigation in `app/templates/admin_base.html`
    - Add nav item pointing to `/admin/scrape-queue`
    - Highlight when `active_nav == "scrape-queue"`
    - _Requirements: 6.1_

  - [x] 9.2 Add `conftest.py` fixtures for scrape queue tests
    - Add `fake_redis` fixture using `fakeredis.FakeRedis()`
    - Add `rate_limiter(fake_redis)` fixture returning `ScrapeRateLimiter` instance
    - Add `distributed_lock(fake_redis)` fixture returning `ScrapeDistributedLock` instance
    - Place in `reddit_saas/tests/conftest.py`
    - _Requirements: (testing infrastructure)_

- [x] 10. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (11 properties total)
- Unit tests validate specific scenarios and edge cases
- All Redis operations use `fakeredis` in tests — no real Redis required for CI
- No database schema changes needed — all queue state derived from existing tables
- The existing `scrape_professional_subreddits` task remains for backward compatibility but will no longer be triggered by Celery Beat once the queue ticker is active
