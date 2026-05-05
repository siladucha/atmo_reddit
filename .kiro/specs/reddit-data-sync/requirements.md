# Requirements Document

## Introduction

This feature introduces a centralized, rate-limit-aware Reddit data synchronization system for the Reddit Marketing SaaS platform. The current implementation calls the Reddit API directly from individual Celery scraping tasks without centralized rate limit tracking, queue-based throttling, or admin visibility into API consumption. As data volumes grow across multiple clients and subreddits, the risk of hitting Reddit's OAuth rate limits (100 requests/minute per token) increases, potentially leading to temporary bans or degraded service.

This feature addresses four core needs: (1) a centralized rate-limiting queue that serializes all Reddit API calls through a single throttled gateway, (2) an admin-only "Community Data Refresh" button in the Settings section to trigger manual sync (regular users cannot trigger refreshes), (3) a real-time rate limit dashboard in the admin panel showing OAuth consumption status (remaining calls, used calls, reset time, queue depth), and (4) admin controls to manage sync behavior (pause/resume queue, adjust throttle rate, configure batch sizes).

## Glossary

- **Rate_Limit_Queue**: A Redis-backed queue that serializes all outbound Reddit API calls, enforcing a configurable maximum requests-per-minute ceiling to stay within Reddit's OAuth rate limits.
- **Rate_Limit_Tracker**: A Redis-stored data structure that records the current state of Reddit API rate limit consumption: remaining requests, used requests, reset timestamp, and last response headers from Reddit.
- **Sync_Job**: A Celery task that performs a community data refresh for one or more clients, broken into batched sub-tasks that are dispatched through the Rate_Limit_Queue.
- **Community_Data_Refresh**: The user-facing term for triggering a Reddit data synchronization. Used in the admin UI instead of "scraping" for legal compliance.
- **Admin_Settings_Page**: The existing admin settings page where system configuration is managed, extended with the new refresh trigger and rate limit controls.
- **Rate_Limit_Dashboard**: A section within the admin panel displaying real-time Reddit API rate limit status, queue depth, and sync job progress.
- **Throttle_Rate**: The configurable maximum number of Reddit API requests per minute, stored as a system setting. Default: 60 (conservative, below Reddit's 100/min limit).
- **Batch_Size**: The configurable number of subreddits to process per sync job iteration before yielding to the queue. Default: 10.
- **Queue_State**: The operational state of the Rate_Limit_Queue: "active" (processing requests), "paused" (holding requests until resumed), or "draining" (completing in-flight requests, accepting no new ones).
- **Sync_Status**: The status of a Sync_Job: "queued", "running", "completed", "failed", or "cancelled".
- **Incremental_Sync**: A synchronization strategy that only fetches data newer than the last successful sync timestamp for each subreddit, reducing API call volume.
- **Reddit_API_Headers**: The `X-Ratelimit-Remaining`, `X-Ratelimit-Used`, and `X-Ratelimit-Reset` headers returned by Reddit's API in every response.
- **Admin_User**: A user with `is_superuser=True` who has access to the admin panel and can trigger community data refreshes.
- **Regular_User**: A user with `is_superuser=False` who can view dashboards and review content but cannot trigger data refreshes.

## Requirements

### Requirement 1: Centralized Rate Limit Tracking

**User Story:** As an admin, I want the system to track Reddit API rate limit consumption in real time, so that I can monitor how close the system is to Reddit's limits and avoid bans.

#### Acceptance Criteria

1. WHEN a Reddit API response is received, THE Rate_Limit_Tracker SHALL extract and store the `X-Ratelimit-Remaining`, `X-Ratelimit-Used`, and `X-Ratelimit-Reset` values from the response headers in Redis.
2. THE Rate_Limit_Tracker SHALL store the following fields in Redis: remaining_requests (float), used_requests (integer), reset_timestamp (UTC epoch), last_updated_at (UTC epoch), and total_requests_today (integer counter).
3. WHEN the Rate_Limit_Tracker is queried, THE Rate_Limit_Tracker SHALL return the current rate limit state as a dictionary with all stored fields plus a computed seconds_until_reset value.
4. IF a Reddit API response does not contain rate limit headers, THEN THE Rate_Limit_Tracker SHALL retain the previously stored values without modification.
5. THE Rate_Limit_Tracker SHALL use a Redis key with a TTL of 120 seconds for the rate limit state, so that stale data expires automatically when no API calls are being made.

### Requirement 2: Rate-Limited Request Queue

**User Story:** As a developer, I want all Reddit API calls to pass through a centralized queue with throttling, so that the system never exceeds Reddit's rate limits regardless of how many concurrent tasks are running.

#### Acceptance Criteria

1. THE Rate_Limit_Queue SHALL use a Redis-based semaphore to limit concurrent Reddit API calls to one at a time, with a configurable minimum interval between calls derived from the Throttle_Rate setting.
2. WHEN a Celery task needs to make a Reddit API call, THE task SHALL acquire a slot from the Rate_Limit_Queue before proceeding, blocking until a slot is available or a timeout of 60 seconds is reached.
3. WHEN the Rate_Limit_Queue dispatches a request, THE Rate_Limit_Queue SHALL enforce a minimum delay of `60 / Throttle_Rate` seconds between consecutive API calls.
4. IF the Rate_Limit_Tracker shows remaining_requests below 10, THEN THE Rate_Limit_Queue SHALL increase the delay between calls to `seconds_until_reset / remaining_requests` seconds to spread remaining capacity evenly.
5. IF a task's queue wait exceeds the 60-second timeout, THEN THE Rate_Limit_Queue SHALL raise a QueueTimeoutError and the task SHALL log the timeout and retry with exponential backoff.
6. THE Rate_Limit_Queue SHALL expose a `queue_depth` method returning the number of tasks currently waiting for a slot.

### Requirement 3: Queue State Management

**User Story:** As an admin, I want to pause and resume the Reddit API queue, so that I can stop all Reddit calls immediately if I detect a problem or need to perform maintenance.

#### Acceptance Criteria

1. THE Rate_Limit_Queue SHALL support three Queue_States: "active", "paused", and "draining".
2. WHEN the Queue_State is set to "paused", THE Rate_Limit_Queue SHALL hold all pending requests without dispatching them, and new requests SHALL queue without being processed.
3. WHEN the Queue_State is changed from "paused" to "active", THE Rate_Limit_Queue SHALL resume processing queued requests in FIFO order.
4. WHEN the Queue_State is set to "draining", THE Rate_Limit_Queue SHALL complete all in-flight requests but accept no new requests, returning a QueueDrainingError for new submissions.
5. THE Rate_Limit_Queue SHALL persist the Queue_State in Redis so that it survives Celery worker restarts.
6. WHEN the Queue_State changes, THE Rate_Limit_Queue SHALL create an Activity_Event with event_type "system" recording the state transition and the admin who triggered it.

### Requirement 4: Admin-Only Community Data Refresh Trigger

**User Story:** As an admin, I want a "Community Data Refresh" button in the admin Settings section, so that I can manually trigger a full data sync when needed, while ensuring regular users cannot trigger refreshes.

#### Acceptance Criteria

1. THE Admin_Settings_Page SHALL display a "Community Data Refresh" section with a button labeled "Refresh Community Data" that triggers a Sync_Job for all active clients.
2. WHEN an Admin_User clicks the refresh button, THE system SHALL create a Sync_Job Celery task and return a confirmation message with the job ID.
3. WHEN an Admin_User clicks the refresh button, THE system SHALL create an Activity_Event with event_type "system" and a message "Community data refresh triggered by {admin_email}".
4. THE refresh button SHALL be disabled with a tooltip "Refresh already in progress" while a Sync_Job with Sync_Status "queued" or "running" exists.
5. THE refresh endpoint SHALL be protected by the `require_superuser` dependency, returning HTTP 403 for Regular_Users.
6. THE Admin_Settings_Page SHALL display the Sync_Status of the most recent Sync_Job (queued, running, completed, failed) with a timestamp.
7. WHEN an Admin_User triggers a refresh, THE system SHALL log an audit entry with action "trigger_community_refresh" containing the admin user ID and job ID.

### Requirement 5: Sync Job Execution with Batching and Incremental Sync

**User Story:** As an admin, I want the sync job to process subreddits in batches with incremental fetching, so that large data volumes are handled efficiently without overwhelming the Reddit API.

#### Acceptance Criteria

1. WHEN a Sync_Job starts, THE Sync_Job SHALL query all active ClientSubreddits across all active clients and partition them into batches of Batch_Size subreddits.
2. THE Sync_Job SHALL process each batch sequentially, dispatching individual subreddit scrape calls through the Rate_Limit_Queue.
3. WHEN scraping a subreddit, THE Sync_Job SHALL use Incremental_Sync: only fetch posts newer than the subreddit's `last_scraped_at` timestamp, falling back to the default `max_age_hours` if `last_scraped_at` is null.
4. WHEN a batch completes, THE Sync_Job SHALL update its progress metadata in Redis with: total_subreddits, completed_subreddits, total_new_posts, current_batch, and estimated_time_remaining.
5. IF a single subreddit scrape fails, THEN THE Sync_Job SHALL log the error, record a ScrapeLog with the error, and continue to the next subreddit without aborting the entire job.
6. WHEN the Sync_Job completes all batches, THE Sync_Job SHALL update its Sync_Status to "completed" and create an Activity_Event summarizing total subreddits processed, new posts found, and total duration.
7. IF the Sync_Job is cancelled by an admin, THEN THE Sync_Job SHALL stop processing new batches, set Sync_Status to "cancelled", and create an Activity_Event recording the cancellation.

### Requirement 6: Rate Limit Dashboard in Admin Panel

**User Story:** As an admin, I want to see the current Reddit API rate limit status in the admin panel, so that I can monitor API consumption and detect problems before they cause bans.

#### Acceptance Criteria

1. THE Rate_Limit_Dashboard SHALL be displayed as a section on the admin System Health page, showing: remaining_requests, used_requests, seconds_until_reset (as a countdown), total_requests_today, and Queue_State.
2. THE Rate_Limit_Dashboard SHALL display the current queue_depth (number of tasks waiting for a Rate_Limit_Queue slot).
3. THE Rate_Limit_Dashboard SHALL auto-refresh every 10 seconds via HTMX polling to show near-real-time data.
4. WHILE remaining_requests is above 30, THE Rate_Limit_Dashboard SHALL display the remaining count in green.
5. WHILE remaining_requests is between 10 and 30, THE Rate_Limit_Dashboard SHALL display the remaining count in amber.
6. WHILE remaining_requests is below 10, THE Rate_Limit_Dashboard SHALL display the remaining count in red with a warning icon.
7. IF the Rate_Limit_Tracker has no data (no API calls made recently), THEN THE Rate_Limit_Dashboard SHALL display "No recent API activity" with a neutral indicator.

### Requirement 7: Admin Controls for Sync Behavior

**User Story:** As an admin, I want to configure the throttle rate, batch size, and queue state from the admin panel, so that I can tune sync behavior without changing code or restarting services.

#### Acceptance Criteria

1. THE Admin_Settings_Page SHALL include the following configurable settings in a "Reddit API Configuration" section: Throttle_Rate (requests per minute, default 60, range 1–100), Batch_Size (subreddits per batch, default 10, range 1–50), and max_age_hours_default (default 24, range 1–168).
2. WHEN an admin updates a sync setting, THE system SHALL persist the new value via the existing SystemSetting key-value store and log an audit entry.
3. THE Admin_Settings_Page SHALL include "Pause Queue" and "Resume Queue" buttons that change the Queue_State.
4. WHEN the queue is paused, THE Admin_Settings_Page SHALL display the "Pause Queue" button as disabled and the "Resume Queue" button as enabled, and vice versa.
5. WHEN an admin changes the Throttle_Rate, THE Rate_Limit_Queue SHALL apply the new rate on the next request cycle without requiring a worker restart.
6. THE Admin_Settings_Page SHALL validate that Throttle_Rate is between 1 and 100 and Batch_Size is between 1 and 50, returning a validation error for out-of-range values.

### Requirement 8: Sync Job Progress Visibility

**User Story:** As an admin, I want to see the progress of a running sync job in real time, so that I know how far along the refresh is and when it will complete.

#### Acceptance Criteria

1. WHILE a Sync_Job has Sync_Status "running", THE Rate_Limit_Dashboard SHALL display a progress section showing: completed_subreddits / total_subreddits, total_new_posts found so far, current batch number, and estimated_time_remaining.
2. THE progress section SHALL auto-refresh every 5 seconds via HTMX polling while a job is running.
3. WHEN a Sync_Job transitions to "completed" or "failed", THE Rate_Limit_Dashboard SHALL display the final summary: total subreddits processed, total new posts, total duration, and error count.
4. THE Rate_Limit_Dashboard SHALL include a "Cancel Sync" button that is visible only while a Sync_Job has Sync_Status "running", allowing the admin to abort the job.
5. WHEN the admin clicks "Cancel Sync", THE system SHALL set a cancellation flag in Redis that the Sync_Job checks before processing each batch.

### Requirement 9: Integration with Existing Scraping Tasks

**User Story:** As a developer, I want the existing scheduled scraping tasks to use the new Rate_Limit_Queue, so that all Reddit API calls are throttled consistently whether triggered manually or by Celery Beat.

#### Acceptance Criteria

1. THE existing `scrape_professional_subreddits` task SHALL acquire a Rate_Limit_Queue slot before each Reddit API call.
2. THE existing `scrape_hobby_subreddits` task SHALL acquire a Rate_Limit_Queue slot before each Reddit API call.
3. THE existing `fetch_reddit_status` function in reddit_status.py SHALL acquire a Rate_Limit_Queue slot before calling the Reddit API.
4. WHEN a scheduled scraping task acquires a queue slot, THE Rate_Limit_Tracker SHALL be updated with the response headers from the resulting Reddit API call.
5. IF the Rate_Limit_Queue is paused, THEN scheduled scraping tasks SHALL wait for the queue to resume rather than bypassing the queue.

### Requirement 10: System Settings Extension

**User Story:** As a developer, I want the new sync configuration stored in the existing SystemSetting model, so that settings are managed consistently through the existing settings service.

#### Acceptance Criteria

1. THE settings service SHALL include the following new default settings: `reddit_throttle_rate` (value: "60", description: "Maximum Reddit API requests per minute"), `reddit_batch_size` (value: "10", description: "Subreddits per sync batch"), `reddit_max_age_hours` (value: "24", description: "Default max age in hours for fetched posts"), and `reddit_queue_state` (value: "active", description: "Reddit API queue state: active, paused, draining").
2. WHEN the application starts, THE settings service SHALL initialize the new default settings in the database if they do not already exist.
3. THE Rate_Limit_Queue SHALL read the Throttle_Rate and Queue_State from the settings service on each request cycle, allowing runtime changes without worker restarts.

### Requirement 11: Audit Trail and Activity Events

**User Story:** As an admin, I want all sync-related actions logged in the audit trail and activity feed, so that I have full visibility into who triggered what and when.

#### Acceptance Criteria

1. WHEN an admin triggers a Community Data Refresh, THE system SHALL create an AuditLog entry with action "trigger_community_refresh" and details containing the admin user ID, job ID, and timestamp.
2. WHEN an admin pauses or resumes the Rate_Limit_Queue, THE system SHALL create an AuditLog entry with action "queue_state_change" and details containing the previous state, new state, and admin user ID.
3. WHEN an admin changes the Throttle_Rate or Batch_Size, THE system SHALL create an AuditLog entry with action "sync_setting_change" and details containing the setting key, old value, new value, and admin user ID.
4. WHEN a Sync_Job starts, completes, fails, or is cancelled, THE system SHALL create an Activity_Event with event_type "sync" and a descriptive message including the job outcome and statistics.

### Requirement 12: Error Handling and Resilience

**User Story:** As a developer, I want the sync system to handle Reddit API errors gracefully, so that transient failures do not crash the entire sync pipeline or leave the system in an inconsistent state.

#### Acceptance Criteria

1. IF a Reddit API call returns HTTP 429 (Too Many Requests), THEN THE Rate_Limit_Queue SHALL pause all outbound requests for the duration specified in the `Retry-After` header or 60 seconds if the header is absent.
2. IF a Reddit API call returns HTTP 5xx, THEN THE Rate_Limit_Queue SHALL retry the request up to 3 times with exponential backoff (2s, 4s, 8s) before marking the request as failed.
3. IF the Redis connection is lost, THEN THE Rate_Limit_Queue SHALL fall back to a conservative in-memory rate limiter (30 requests/minute) and log a warning Activity_Event.
4. WHEN a Sync_Job encounters more than 10 consecutive subreddit failures, THE Sync_Job SHALL pause for 120 seconds before continuing, to allow transient issues to resolve.
5. IF the Rate_Limit_Tracker detects remaining_requests at 0, THEN THE Rate_Limit_Queue SHALL block all new requests until the reset_timestamp has passed.

### Requirement 13: Test Coverage

**User Story:** As a developer, I want comprehensive tests for the rate limiting, queue, and sync features, so that the system is reliable and regressions are caught early.

#### Acceptance Criteria

1. THE test suite SHALL include unit tests for the Rate_Limit_Tracker: storing and retrieving rate limit state, TTL expiration, and handling missing headers.
2. THE test suite SHALL include unit tests for the Rate_Limit_Queue: slot acquisition, throttle delay calculation, timeout behavior, pause/resume state transitions, and queue depth reporting.
3. THE test suite SHALL include unit tests for the Sync_Job: batch partitioning, incremental sync logic, progress tracking, error handling for individual subreddit failures, and cancellation.
4. THE test suite SHALL include integration tests for the admin refresh endpoint: superuser access, regular user rejection (HTTP 403), job creation, and duplicate job prevention.
5. THE test suite SHALL include tests for the Rate_Limit_Dashboard HTMX endpoint: correct rendering of rate limit data, color-coded thresholds, and "no data" state.
6. WHEN all new tests are run together with existing tests, THE test suite SHALL pass with zero failures.
