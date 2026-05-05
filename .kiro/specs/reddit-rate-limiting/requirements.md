# Requirements Document

## Introduction

The Reddit Marketing SaaS platform currently creates a new PRAW Reddit client on every API call, losing rate limit state between requests. There is no centralized rate limiting, no visibility into Reddit API quota usage, and no intelligent backoff when limits are approached or exceeded. This feature introduces a centralized Reddit API rate-limiting system that manages a singleton client, tracks quota consumption, enforces configurable pacing per operation type, handles 429 responses with exponential backoff, and surfaces rate limit status in the admin health panel.

## Glossary

- **Rate_Limiter**: The centralized module responsible for tracking Reddit API quota usage, enforcing request pacing, and managing backoff logic across all Reddit API operations.
- **Reddit_Client_Manager**: The component that manages the lifecycle of the PRAW Reddit instance, ensuring a single shared instance persists across requests so that rate limit state is retained.
- **Rate_Limit_State**: A data structure holding the current values of requests remaining, requests used, and seconds until quota reset, as reported by Reddit API response headers (X-Ratelimit-Remaining, X-Ratelimit-Used, X-Ratelimit-Reset).
- **Operation_Type**: A classification of Reddit API calls by purpose. The two defined types are `scraping` (subreddit content fetching) and `status_check` (avatar account metadata lookups).
- **Backoff_Strategy**: The algorithm used to calculate wait times after a failed or rate-limited request. Uses exponential backoff with jitter.
- **Admin_Health_Panel**: The existing admin UI page at `/admin/health` that displays system service statuses and database statistics.
- **Settings**: The pydantic-settings configuration object (`app/config.py`) that holds all application configuration values loaded from environment variables.

## Requirements

### Requirement 1: Singleton Reddit Client

**User Story:** As a system operator, I want the Reddit API client to be created once and reused across all operations, so that rate limit state tracked by PRAW persists between requests.

#### Acceptance Criteria

1. THE Reddit_Client_Manager SHALL maintain a single PRAW Reddit instance that is reused across all callers within the same process.
2. WHEN `get_reddit_client()` is called multiple times within the same process, THE Reddit_Client_Manager SHALL return the same PRAW Reddit instance.
3. WHEN the Reddit API credentials in Settings change, THE Reddit_Client_Manager SHALL create a new PRAW Reddit instance with the updated credentials on the next call.
4. IF the singleton PRAW Reddit instance encounters an unrecoverable authentication error, THEN THE Reddit_Client_Manager SHALL discard the current instance and create a new one on the next call.

### Requirement 2: Rate Limit State Tracking

**User Story:** As a system operator, I want the system to continuously track Reddit API rate limit headers, so that I can understand current quota consumption and the system can make informed pacing decisions.

#### Acceptance Criteria

1. WHEN a Reddit API response is received, THE Rate_Limiter SHALL extract and store the values of X-Ratelimit-Remaining, X-Ratelimit-Used, and X-Ratelimit-Reset into the Rate_Limit_State.
2. THE Rate_Limiter SHALL make the current Rate_Limit_State available to other components via a synchronous read method.
3. WHEN no Reddit API call has been made yet in the current process, THE Rate_Limiter SHALL report the Rate_Limit_State as unknown rather than returning stale or default values.
4. WHEN the reset window elapses (based on X-Ratelimit-Reset), THE Rate_Limiter SHALL treat the Rate_Limit_State as unknown until the next API response updates the values.

### Requirement 3: Configurable Operation Pacing

**User Story:** As a system operator, I want to configure different minimum delays between Reddit API calls for scraping versus status checks, so that I can tune request pacing per operation type without code changes.

#### Acceptance Criteria

1. THE Settings SHALL include a `reddit_rate_limit_scrape_delay` configuration value with a default of 2.0 seconds.
2. THE Settings SHALL include a `reddit_rate_limit_status_delay` configuration value with a default of 2.0 seconds.
3. WHEN a Reddit API call of Operation_Type `scraping` completes, THE Rate_Limiter SHALL enforce a minimum delay of `reddit_rate_limit_scrape_delay` seconds before allowing the next `scraping` call.
4. WHEN a Reddit API call of Operation_Type `status_check` completes, THE Rate_Limiter SHALL enforce a minimum delay of `reddit_rate_limit_status_delay` seconds before allowing the next `status_check` call.
5. WHILE the Rate_Limit_State shows fewer than 10 requests remaining in the current window, THE Rate_Limiter SHALL double the configured delay for all Operation_Types until the quota resets.

### Requirement 4: Exponential Backoff on 429 Responses

**User Story:** As a system operator, I want the system to automatically retry Reddit API calls that receive a 429 TooManyRequests response using exponential backoff, so that transient rate limit hits are handled gracefully without manual intervention.

#### Acceptance Criteria

1. WHEN a Reddit API call receives a 429 TooManyRequests response, THE Rate_Limiter SHALL retry the call after an exponentially increasing delay.
2. THE Rate_Limiter SHALL use a base backoff delay of 5 seconds, doubling on each consecutive retry (5s, 10s, 20s, 40s).
3. THE Rate_Limiter SHALL add random jitter of up to 1 second to each backoff delay to prevent thundering herd effects.
4. THE Settings SHALL include a `reddit_rate_limit_max_retries` configuration value with a default of 3.
5. IF the number of consecutive retries for a single call exceeds `reddit_rate_limit_max_retries`, THEN THE Rate_Limiter SHALL raise the original TooManyRequests exception to the caller.
6. WHEN a retry succeeds after a 429 response, THE Rate_Limiter SHALL log the number of retries and total wait time at WARNING level.

### Requirement 5: Consistent Rate Limit Logging

**User Story:** As a system operator, I want rate limit information logged consistently across all Reddit API operations at INFO level, so that I can monitor quota usage in production logs without enabling DEBUG.

#### Acceptance Criteria

1. WHEN a Reddit API call completes, THE Rate_Limiter SHALL log the current Rate_Limit_State at INFO level, including requests remaining, requests used, and seconds until reset.
2. WHEN the Rate_Limit_State shows fewer than 20 requests remaining, THE Rate_Limiter SHALL log a warning at WARNING level indicating the quota is running low.
3. WHEN a 429 TooManyRequests response is received, THE Rate_Limiter SHALL log the event at WARNING level including the Operation_Type and the backoff delay before retry.
4. THE Rate_Limiter SHALL include the Operation_Type in all rate-limit-related log messages.
5. WHEN the Rate_Limit_State transitions from unknown to known (first API response after startup or reset), THE Rate_Limiter SHALL log the initial quota values at INFO level.

### Requirement 6: Admin Health Panel Rate Limit Visibility

**User Story:** As an admin user, I want to see the current Reddit API rate limit status on the admin health page, so that I can monitor quota usage and identify rate limiting issues without checking logs.

#### Acceptance Criteria

1. THE Admin_Health_Panel SHALL display a "Reddit API" card showing the current Rate_Limit_State (requests remaining, requests used, seconds until reset).
2. WHILE the Rate_Limit_State is unknown, THE Admin_Health_Panel SHALL display the Reddit API card with a "No data yet" indicator.
3. WHEN the Rate_Limit_State shows fewer than 10 requests remaining, THE Admin_Health_Panel SHALL display the Reddit API card with a warning status indicator.
4. WHEN the Rate_Limit_State shows 0 requests remaining, THE Admin_Health_Panel SHALL display the Reddit API card with a critical status indicator.
5. THE Admin_Health_Panel SHALL display the timestamp of the last Reddit API call that updated the Rate_Limit_State.

### Requirement 7: Health Endpoint Rate Limit Data

**User Story:** As a system operator, I want the `/health` endpoint to include Reddit API rate limit data, so that monitoring tools can track quota usage programmatically.

#### Acceptance Criteria

1. THE `/health` endpoint SHALL include a `reddit_rate_limit` object in the response containing the current Rate_Limit_State fields (remaining, used, reset_seconds).
2. WHILE the Rate_Limit_State is unknown, THE `/health` endpoint SHALL return `null` for the `reddit_rate_limit` object.
3. WHEN the Rate_Limit_State shows fewer than 10 requests remaining, THE `/health` endpoint SHALL include a `"status": "warning"` field in the `reddit_rate_limit` object.
4. WHEN the Rate_Limit_State shows 0 requests remaining, THE `/health` endpoint SHALL include a `"status": "critical"` field in the `reddit_rate_limit` object.

### Requirement 8: Integration with Existing Scraping Tasks

**User Story:** As a system operator, I want the scraping Celery tasks to use the centralized rate limiter for pacing instead of ad-hoc delays, so that all Reddit API calls are governed by a single rate limiting strategy.

#### Acceptance Criteria

1. WHEN `scrape_subreddit()` is called, THE Rate_Limiter SHALL enforce the configured scraping delay before the Reddit API call proceeds.
2. WHEN `check_all_reddit_statuses()` is called, THE Rate_Limiter SHALL enforce the configured status check delay between each avatar status lookup, replacing the hardcoded `delay_seconds` parameter.
3. WHEN `fetch_comments()` is called, THE Rate_Limiter SHALL enforce the configured scraping delay before the Reddit API call proceeds.
4. IF a 429 response occurs during a batch scraping or status check operation, THEN THE Rate_Limiter SHALL apply exponential backoff for the failed call without aborting the remaining items in the batch.
