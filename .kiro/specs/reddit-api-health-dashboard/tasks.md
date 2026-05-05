# Implementation Plan: Reddit API Health Dashboard

## Overview

Implement an in-memory metrics collector and database-backed aggregation layer to surface Reddit API and LLM API health metrics as auto-refreshing HTMX widgets on the existing System Health page. The implementation uses Python/FastAPI with thread-safe data structures, SQLAlchemy DB queries, Jinja2 partials, and Hypothesis for property-based testing.

## Tasks

- [x] 1. Implement MetricsCollector and MetricsLoggingHandler
  - [x] 1.1 Create `app/services/metrics_collector.py` with `RateLimitState` dataclass, `MetricsCollector` class, and `gauge_color` helper
    - Implement `RateLimitState` with `status` and `usage_pct` computed properties
    - Implement thread-safe `MetricsCollector` with `record_rate_limit()` and `get_rate_limit()` methods
    - Implement `gauge_color()` function mapping usage_pct to green/yellow/red/gray
    - Add `parse_rate_limit_message()` helper with regex parsing
    - _Requirements: 1.1, 1.6, 1.7, 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 1.2 Implement `MetricsLoggingHandler` logging handler
    - Create custom `logging.Handler` subclass that intercepts "Reddit rate limit status" log messages
    - Parse structured log format and feed data into `MetricsCollector`
    - Ensure `emit()` never raises exceptions (silent failure on parse errors)
    - Add singleton accessor `get_metrics_collector()` and `install_metrics_logging_handler()`
    - _Requirements: 2.1, 1.7_

  - [ ]* 1.3 Write property tests for rate limit parsing and classification
    - **Property 1: Rate limit log parsing round-trip**
    - **Property 2: Rate limit status classification**
    - **Property 3: Rate limit gauge color classification**
    - **Validates: Requirements 2.1, 2.3, 2.4, 2.5, 5.2, 5.3, 5.4, 5.6**

  - [ ]* 1.4 Write unit tests for MetricsCollector
    - Test fresh collector returns unknown state
    - Test record/read round-trip
    - Test thread safety smoke test
    - Test logging handler feeds collector correctly
    - Test handler ignores unrelated messages
    - _Requirements: 2.2, 2.3_

- [x] 2. Implement Health Metrics Service (DB aggregation)
  - [x] 2.1 Create `app/services/health_metrics.py` with `get_reddit_api_metrics()`
    - Query `scrape_log` table for entries within the time window
    - Compute total_calls, error_count, error_rate_pct, avg_response_ms, p95_response_ms, calls_per_minute
    - Classify errors by type (rate_limited, forbidden, timeout, other) using error message parsing
    - Determine widget status based on error_rate and latency thresholds
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [x] 2.2 Implement `get_llm_api_metrics()` function
    - Query `ai_usage_log` table for entries within the time window
    - Compute total_calls, total_cost_usd, avg_latency_ms, error_count
    - Break down by model (calls and cost per model)
    - Determine widget status based on latency and error thresholds
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 2.3 Implement `get_all_scrape_freshness()` function
    - Query `client_subreddits` for all active subreddits across all clients
    - Classify each as fresh, stale (>24h), or never_scraped (last_scraped_at is None)
    - Compute total_active, stale_count, never_scraped_count
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 2.4 Implement `get_metrics_snapshot()` for JSON API endpoint
    - Combine rate limit state from MetricsCollector with DB-aggregated metrics
    - Include `collected_at` ISO timestamp and `window_minutes` field
    - _Requirements: 10.1, 10.3, 10.4_

  - [ ]* 2.5 Write property tests for Reddit API metrics consistency
    - **Property 4: Reddit API metrics internal consistency**
    - **Property 5: Response time statistics ordering invariant**
    - **Property 6: Error breakdown sums to total**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**

  - [ ]* 2.6 Write property tests for LLM metrics and status classification
    - **Property 7: LLM per-model breakdown sums to totals**
    - **Property 8: Reddit API widget status classification**
    - **Property 9: LLM widget status classification**
    - **Validates: Requirements 4.1, 4.2, 4.5, 6.3, 6.4, 6.5, 7.3, 7.4**

  - [ ]* 2.7 Write unit tests for DB aggregation functions
    - Test empty window returns zero counts
    - Test aggregation with known data sets
    - Test old rows are excluded from window
    - Test latency warning threshold
    - Test LLM per-model breakdown
    - _Requirements: 3.1, 3.2, 4.1, 4.2_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement Route Endpoints
  - [x] 4.1 Add health widget endpoints to `app/routes/admin.py`
    - Add `GET /admin/health/widget/rate-limit` returning HTML partial
    - Add `GET /admin/health/widget/reddit-metrics` returning HTML partial
    - Add `GET /admin/health/widget/llm-metrics` returning HTML partial
    - Add `GET /admin/health/widget/scrape-freshness` returning HTML partial
    - All endpoints require superuser authentication
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

  - [x] 4.2 Add JSON metrics endpoint
    - Add `GET /admin/health/metrics` returning full JSON snapshot
    - Require superuser authentication
    - Include `collected_at` and `window_minutes` in response
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 4.3 Enhance existing `GET /admin/health` page handler
    - Pass rate limit context and initial widget data to template
    - Access MetricsCollector from `request.app.state.metrics_collector`
    - _Requirements: 5.1, 6.1, 7.1, 8.1_

  - [ ]* 4.4 Write integration tests for route endpoints
    - Test health page renders with all widget containers
    - Test each widget endpoint returns valid HTML
    - Test JSON endpoint returns correct structure
    - Test auth enforcement on all endpoints
    - _Requirements: 10.2, 11.5_

- [x] 5. Implement Templates (widget partials + enhanced health page)
  - [x] 5.1 Create `partials/health_rate_limit.html` template
    - Display rate limit gauge with usage percentage
    - Show remaining, used, and seconds until reset values
    - Apply color-coded status indicator (green/yellow/red/gray)
    - Show "No data" with gray indicator when state is unknown
    - Add `hx-get` and `hx-trigger="every 30s"` for auto-refresh
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 9.1_

  - [x] 5.2 Create `partials/health_reddit_metrics.html` template
    - Display total calls, calls/min, error count, error rate percentage
    - Display average and p95 response times
    - Display error breakdown by type
    - Apply color-coded status indicator based on error rate and latency thresholds
    - Add `hx-get` and `hx-trigger="every 30s"` for auto-refresh
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 9.2_

  - [x] 5.3 Create `partials/health_llm_metrics.html` template
    - Display total calls, total cost USD, average latency
    - Display per-model breakdown of calls and costs
    - Apply color-coded status indicator based on latency and error thresholds
    - Add `hx-get` and `hx-trigger="every 60s"` for auto-refresh
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 9.3_

  - [x] 5.4 Create `partials/health_scrape_freshness.html` template
    - List all active subreddits with last scraped timestamp
    - Apply yellow indicator for stale (>24h) and red for never scraped
    - Display total active and stale counts
    - Add `hx-get` and `hx-trigger="every 120s"` for auto-refresh
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 9.4_

  - [x] 5.5 Enhance `admin_health.html` to include API Metrics section
    - Add a new section below existing service status cards
    - Include 4 widget containers with HTMX attributes for polling
    - Add error handling for failed HTMX refreshes (retain last content)
    - _Requirements: 5.1, 6.1, 7.1, 8.1, 9.5_

- [x] 6. Wire initialization in main.py
  - [x] 6.1 Initialize MetricsCollector and attach logging handler at app startup
    - Create singleton `MetricsCollector(window_minutes=60)`
    - Create `MetricsLoggingHandler` and attach to root logger
    - Store collector in `app.state.metrics_collector`
    - _Requirements: 1.7, 2.1_

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Property-based tests for scrape freshness
  - [ ]* 8.1 Write property test for scrape freshness classification
    - **Property 10: Scrape freshness classification and count consistency**
    - **Validates: Requirements 8.2, 8.3, 8.4**

- [x] 9. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (10 properties total)
- Unit tests validate specific examples and edge cases
- The implementation uses Python with FastAPI, SQLAlchemy, Jinja2, HTMX, and Hypothesis
- No database migrations needed — all new data structures are in-memory or use existing tables
- Celery worker metrics are aggregated from DB (scrape_log, ai_usage_log), not in-memory
