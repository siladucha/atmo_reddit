# Requirements Document

## Introduction

The Reddit Marketing SaaS platform needs real-time visibility into Reddit API and LLM API health metrics directly on the admin System Health page. Currently the health page shows basic service connectivity (PostgreSQL, Redis, Celery, Reddit API, LLM) but provides no insight into API usage patterns, error rates, response times, or rate limit proximity. When the system is under load — scraping multiple subreddits, checking avatar statuses, generating comments — the admin has no way to see if Reddit API limits are being approached, if error rates are spiking, or if response times are degrading.

This feature adds an in-memory metrics collector that captures structured log events (REDDIT_API_CALL, REDDIT_API_RESULT, REDDIT_API_ERROR, LLM_CALL, LLM_RESULT) and aggregates them into time-windowed statistics. These metrics are surfaced as dashboard widgets on the existing System Health page with color-coded status indicators, and are available via an HTMX auto-refresh endpoint for near-real-time monitoring.

## Glossary

- **Metrics_Collector**: The in-memory service that intercepts structured log events and maintains rolling-window counters, histograms, and error tallies for Reddit API and LLM API calls.
- **Health_Dashboard**: The enhanced admin System Health page (`/admin/health`) that displays API metrics widgets alongside existing service status cards.
- **Rate_Limit_Gauge**: A visual widget showing the current Reddit API rate limit consumption as a percentage, with color-coded thresholds (green/yellow/red).
- **Time_Window**: A configurable rolling period (default 60 minutes) over which the Metrics_Collector aggregates call counts, error rates, and response time statistics.
- **Status_Indicator**: A color-coded signal (green = healthy, yellow = warning, red = critical) applied to each metric widget based on configurable thresholds.
- **Reddit_API_Metrics**: The aggregated statistics for Reddit API calls including call count, error count, error rate percentage, average response time, p95 response time, and rate limit state.
- **LLM_API_Metrics**: The aggregated statistics for LLM API calls including call count, error count, total cost, average latency, and per-model breakdown.
- **Scrape_Freshness**: Per-subreddit data showing when each subreddit was last scraped and whether the data is stale (older than 24 hours).
- **Admin_User**: A user with `is_superuser=True` who has access to the admin panel.

## Requirements

### Requirement 1: In-Memory Metrics Collection

**User Story:** As a system operator, I want API call metrics collected automatically from structured log events, so that usage statistics are available without additional instrumentation in every service function.

#### Acceptance Criteria

1. WHEN a log message matching the pattern `REDDIT_API_CALL` is emitted, THE Metrics_Collector SHALL record the timestamp, action, and target (subreddit or username).
2. WHEN a log message matching the pattern `REDDIT_API_RESULT` is emitted, THE Metrics_Collector SHALL record the response duration in milliseconds and the action outcome.
3. WHEN a log message matching the pattern `REDDIT_API_ERROR` is emitted, THE Metrics_Collector SHALL record the error type, duration, and action.
4. WHEN a log message matching the pattern `LLM_CALL` is emitted, THE Metrics_Collector SHALL record the model name, token counts, and timestamp.
5. WHEN a log message matching the pattern `LLM_RESULT` is emitted, THE Metrics_Collector SHALL record the cost, duration, and token usage.
6. THE Metrics_Collector SHALL discard events older than the configured Time_Window to bound memory usage.
7. THE Metrics_Collector SHALL be thread-safe, supporting concurrent writes from multiple Celery workers and reads from the admin HTTP handler.

### Requirement 2: Reddit API Rate Limit Tracking

**User Story:** As a system operator, I want to see the current Reddit API rate limit state on the dashboard, so that I can react before the quota is exhausted.

#### Acceptance Criteria

1. WHEN the `_log_rate_limit` function in `reddit.py` logs rate limit values, THE Metrics_Collector SHALL capture the remaining, used, and reset_timestamp values.
2. THE Metrics_Collector SHALL expose the most recent Rate_Limit_State via a synchronous read method.
3. WHILE no rate limit data has been captured since process startup, THE Metrics_Collector SHALL report the rate limit state as unknown.
4. WHEN the remaining requests drop below 20 out of 100, THE Metrics_Collector SHALL classify the rate limit status as warning.
5. WHEN the remaining requests drop below 5 out of 100, THE Metrics_Collector SHALL classify the rate limit status as critical.

### Requirement 3: Reddit API Metrics Aggregation

**User Story:** As a system operator, I want aggregated Reddit API statistics (calls per minute, error rate, response times), so that I can identify performance degradation and error spikes at a glance.

#### Acceptance Criteria

1. THE Metrics_Collector SHALL compute the total number of Reddit API calls within the current Time_Window.
2. THE Metrics_Collector SHALL compute the number of Reddit API errors within the current Time_Window.
3. THE Metrics_Collector SHALL compute the error rate as a percentage (errors divided by total calls multiplied by 100).
4. THE Metrics_Collector SHALL compute the average response time in milliseconds for Reddit API calls within the current Time_Window.
5. THE Metrics_Collector SHALL compute the 95th percentile (p95) response time in milliseconds for Reddit API calls within the current Time_Window.
6. THE Metrics_Collector SHALL compute the calls-per-minute rate based on the total calls divided by the elapsed minutes in the Time_Window.
7. THE Metrics_Collector SHALL break down error counts by error type (429 TooManyRequests, 403 Forbidden, timeout, other).

### Requirement 4: LLM API Metrics Aggregation

**User Story:** As a system operator, I want aggregated LLM API statistics (call count, cost, latency), so that I can monitor AI spending and detect LLM service issues.

#### Acceptance Criteria

1. THE Metrics_Collector SHALL compute the total number of LLM API calls within the current Time_Window.
2. THE Metrics_Collector SHALL compute the total cost in USD for LLM API calls within the current Time_Window.
3. THE Metrics_Collector SHALL compute the average latency in milliseconds for LLM API calls within the current Time_Window.
4. THE Metrics_Collector SHALL compute the number of LLM API errors within the current Time_Window.
5. THE Metrics_Collector SHALL break down LLM call counts and costs by model name.

### Requirement 5: Health Dashboard Rate Limit Widget

**User Story:** As an admin user, I want a visual rate limit gauge on the System Health page, so that I can instantly see how close the system is to the Reddit API quota limit.

#### Acceptance Criteria

1. THE Health_Dashboard SHALL display a Rate_Limit_Gauge widget showing the percentage of Reddit API quota consumed (used out of 100).
2. WHEN the quota consumed is below 60 percent, THE Rate_Limit_Gauge SHALL display a green Status_Indicator.
3. WHEN the quota consumed is between 60 and 80 percent, THE Rate_Limit_Gauge SHALL display a yellow Status_Indicator.
4. WHEN the quota consumed exceeds 80 percent, THE Rate_Limit_Gauge SHALL display a red Status_Indicator.
5. THE Rate_Limit_Gauge SHALL display the numeric values of requests remaining, requests used, and seconds until reset.
6. WHILE the rate limit state is unknown, THE Rate_Limit_Gauge SHALL display a "No data" indicator with a gray Status_Indicator.

### Requirement 6: Health Dashboard Reddit API Metrics Widget

**User Story:** As an admin user, I want to see Reddit API call statistics on the System Health page, so that I can monitor API usage patterns and error rates.

#### Acceptance Criteria

1. THE Health_Dashboard SHALL display a Reddit API metrics widget showing total calls, calls per minute, error count, and error rate percentage for the current Time_Window.
2. THE Health_Dashboard SHALL display average and p95 response times in the Reddit API metrics widget.
3. WHEN the error rate exceeds 5 percent, THE Reddit API metrics widget SHALL display a yellow Status_Indicator.
4. WHEN the error rate exceeds 20 percent, THE Reddit API metrics widget SHALL display a red Status_Indicator.
5. WHEN the average response time exceeds 3000 milliseconds, THE Reddit API metrics widget SHALL display a yellow Status_Indicator.
6. THE Reddit API metrics widget SHALL display a breakdown of errors by type (429, 403, timeout, other).

### Requirement 7: Health Dashboard LLM API Metrics Widget

**User Story:** As an admin user, I want to see LLM API statistics on the System Health page, so that I can monitor AI costs and detect latency issues.

#### Acceptance Criteria

1. THE Health_Dashboard SHALL display an LLM API metrics widget showing total calls, total cost in USD, and average latency for the current Time_Window.
2. THE Health_Dashboard SHALL display a per-model breakdown of call counts and costs in the LLM API metrics widget.
3. WHEN the average LLM latency exceeds 5000 milliseconds, THE LLM API metrics widget SHALL display a yellow Status_Indicator.
4. WHEN the LLM error count exceeds 0 within the Time_Window, THE LLM API metrics widget SHALL display a yellow Status_Indicator.

### Requirement 8: Health Dashboard Scrape Freshness Widget

**User Story:** As an admin user, I want to see per-subreddit scrape freshness on the System Health page, so that I can identify subreddits that have not been scraped recently.

#### Acceptance Criteria

1. THE Health_Dashboard SHALL display a scrape freshness widget listing all active subreddits across all clients with their last scraped timestamp.
2. WHEN a subreddit has not been scraped within the last 24 hours, THE scrape freshness widget SHALL display that subreddit with a yellow Status_Indicator.
3. WHEN a subreddit has never been scraped, THE scrape freshness widget SHALL display that subreddit with a red Status_Indicator.
4. THE scrape freshness widget SHALL display the total number of active subreddits and the count of stale subreddits.

### Requirement 9: HTMX Auto-Refresh for Dashboard Widgets

**User Story:** As an admin user, I want the dashboard metrics to refresh automatically without a full page reload, so that I can monitor the system in near-real-time.

#### Acceptance Criteria

1. THE Health_Dashboard SHALL use HTMX polling to refresh the Rate_Limit_Gauge widget every 30 seconds.
2. THE Health_Dashboard SHALL use HTMX polling to refresh the Reddit API metrics widget every 30 seconds.
3. THE Health_Dashboard SHALL use HTMX polling to refresh the LLM API metrics widget every 60 seconds.
4. THE Health_Dashboard SHALL use HTMX polling to refresh the scrape freshness widget every 120 seconds.
5. WHEN an HTMX refresh request fails, THE Health_Dashboard SHALL retain the last successfully loaded content and display a subtle connection error indicator.

### Requirement 10: Metrics API Endpoint

**User Story:** As a system operator, I want a JSON API endpoint that returns current API metrics, so that external monitoring tools can consume the data programmatically.

#### Acceptance Criteria

1. THE system SHALL expose a `GET /admin/health/metrics` endpoint that returns a JSON object containing Reddit_API_Metrics, LLM_API_Metrics, and rate limit state.
2. THE `/admin/health/metrics` endpoint SHALL require Admin_User authentication (superuser only).
3. THE JSON response SHALL include a `collected_at` ISO 8601 timestamp indicating when the metrics snapshot was taken.
4. THE JSON response SHALL include a `window_minutes` field indicating the Time_Window duration used for aggregation.

### Requirement 11: HTMX Partial Endpoints for Dashboard Widgets

**User Story:** As a system operator, I want dedicated HTMX partial endpoints for each dashboard widget, so that individual widgets can refresh independently without reloading the entire page.

#### Acceptance Criteria

1. THE system SHALL expose a `GET /admin/health/widget/rate-limit` endpoint that returns the Rate_Limit_Gauge HTML partial.
2. THE system SHALL expose a `GET /admin/health/widget/reddit-metrics` endpoint that returns the Reddit API metrics HTML partial.
3. THE system SHALL expose a `GET /admin/health/widget/llm-metrics` endpoint that returns the LLM API metrics HTML partial.
4. THE system SHALL expose a `GET /admin/health/widget/scrape-freshness` endpoint that returns the scrape freshness HTML partial.
5. WHEN any widget endpoint is called, THE system SHALL require Admin_User authentication (superuser only).
