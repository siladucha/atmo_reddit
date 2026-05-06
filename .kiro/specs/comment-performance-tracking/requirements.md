# Requirements Document

## Introduction

Comment Performance Tracking enables the system to monitor the real-world performance of posted comments on Reddit. After a CommentDraft transitions to "posted" status, the system periodically fetches performance metrics (score, replies, visibility status) via PRAW and stores time-series snapshots. This data feeds into avatar warming phase evaluation, engagement effectiveness analysis, client reporting, and early warning detection for removed or heavily downvoted comments.

## Glossary

- **Performance_Tracker**: The service responsible for fetching and storing comment performance data from Reddit via PRAW.
- **Performance_Snapshot**: A point-in-time record of a comment's metrics (score, reply count, visibility status) stored for historical analysis.
- **Comment_Score**: The Reddit score (upvotes minus downvotes) of a posted comment at the time of measurement.
- **Reply_Count**: The number of direct replies to a posted comment at the time of measurement.
- **Visibility_Status**: Whether a comment is still visible on Reddit — one of: visible, removed, deleted.
- **Tracking_Window**: The period during which a posted comment is actively monitored (from posted_at until the comment reaches a configurable age threshold).
- **Snapshot_Interval**: The configurable time between consecutive performance checks for a single comment.
- **Alert_Threshold**: Configurable score value below which the system triggers a downvote warning.
- **Phase_Evaluator**: The existing service that evaluates avatar warming phase promotion/demotion eligibility.
- **Activity_Event**: An existing model used for pipeline transparency and audit trail logging.

## Requirements

### Requirement 1: Periodic Comment Performance Fetching

**User Story:** As a system operator, I want the system to automatically fetch performance metrics for posted comments, so that I have up-to-date data without manual intervention.

#### Acceptance Criteria

1. WHEN a CommentDraft status transitions to "posted", THE Performance_Tracker SHALL mark the comment as eligible for tracking.
2. WHILE a posted comment is within the Tracking_Window, THE Performance_Tracker SHALL fetch its current Comment_Score, Reply_Count, and Visibility_Status from Reddit via PRAW at each Snapshot_Interval.
3. WHEN the Tracking_Window expires for a comment, THE Performance_Tracker SHALL stop actively tracking that comment.
4. THE Performance_Tracker SHALL execute as a Celery periodic task that processes all comments currently within their Tracking_Window.
5. IF the Reddit API returns a rate limit error during performance fetching, THEN THE Performance_Tracker SHALL retry with exponential backoff and log the rate limit event.
6. IF the Reddit API returns a 404 or "not found" for a comment, THEN THE Performance_Tracker SHALL mark the comment Visibility_Status as "deleted" and record the detection timestamp.

### Requirement 2: Performance Snapshot Storage

**User Story:** As a system operator, I want historical performance data stored over time, so that I can analyze comment growth trajectories rather than only seeing the latest values.

#### Acceptance Criteria

1. WHEN the Performance_Tracker fetches metrics for a comment, THE Performance_Tracker SHALL create a new Performance_Snapshot record with the comment ID, timestamp, Comment_Score, Reply_Count, and Visibility_Status.
2. THE Performance_Snapshot SHALL preserve all historical records for a comment, enabling time-series analysis of score and reply growth.
3. WHEN a Performance_Snapshot is created, THE Performance_Tracker SHALL also update the CommentDraft.reddit_score field with the latest Comment_Score value.
4. WHEN a Performance_Snapshot indicates Visibility_Status is "removed" or "deleted", THE Performance_Tracker SHALL update CommentDraft.is_deleted to true and set CommentDraft.deleted_detected_at to the current timestamp.

### Requirement 3: Configurable Tracking Parameters

**User Story:** As a system operator, I want to configure tracking frequency and duration, so that I can balance API usage against data freshness.

#### Acceptance Criteria

1. THE Performance_Tracker SHALL read the Tracking_Window duration from SystemSettings with key "perf_tracking_window_days" and a default of 7 days.
2. THE Performance_Tracker SHALL read the Snapshot_Interval from SystemSettings with key "perf_snapshot_interval_hours" and a default of 6 hours.
3. THE Performance_Tracker SHALL read the Alert_Threshold from SystemSettings with key "perf_alert_score_threshold" and a default of -2.
4. WHEN a SystemSetting value is updated, THE Performance_Tracker SHALL use the new value on the next execution cycle without requiring a restart.

### Requirement 4: Early Warning Alerts

**User Story:** As a system operator, I want to be alerted when a comment is removed or heavily downvoted, so that I can take corrective action quickly.

#### Acceptance Criteria

1. WHEN a Performance_Snapshot shows Comment_Score below the Alert_Threshold, THE Performance_Tracker SHALL create an ActivityEvent with event_type "comment_alert" and a message describing the downvote warning.
2. WHEN a Performance_Snapshot shows Visibility_Status changed from "visible" to "removed" or "deleted", THE Performance_Tracker SHALL create an ActivityEvent with event_type "comment_alert" and a message describing the removal detection.
3. THE Performance_Tracker SHALL include the avatar_id, comment_id, subreddit, and current score in the ActivityEvent metadata.
4. THE Performance_Tracker SHALL emit at most one alert per comment per alert condition to avoid duplicate notifications.

### Requirement 5: Phase Evaluation Integration

**User Story:** As a system operator, I want comment performance data to feed into avatar warming phase evaluation, so that phase promotion decisions reflect actual Reddit engagement quality.

#### Acceptance Criteria

1. THE Phase_Evaluator SHALL use Performance_Snapshot data when computing average comment score (compute_avg_comment_score) for phase promotion eligibility.
2. THE Phase_Evaluator SHALL use Performance_Snapshot data when computing comment survival rate (compute_comment_survival_rate) for phase promotion and demotion checks.
3. WHEN the Performance_Tracker detects a comment removal, THE Phase_Evaluator SHALL reflect the updated is_deleted status in subsequent survival rate calculations.

### Requirement 6: Effectiveness Analysis Data

**User Story:** As a system operator, I want to query performance data grouped by engagement_mode and comment_approach, so that I can identify which strategies produce the best results.

#### Acceptance Criteria

1. THE Performance_Snapshot SHALL store the avatar_id and client_id alongside the comment reference, enabling filtering by avatar and client.
2. THE Performance_Tracker SHALL expose a service function that returns aggregated performance metrics (average score, average reply count, removal rate) grouped by engagement_mode for a given client and time window.
3. THE Performance_Tracker SHALL expose a service function that returns aggregated performance metrics grouped by comment_approach for a given client and time window.

### Requirement 7: Reddit API Comment Fetching

**User Story:** As a system operator, I want the system to fetch individual comment data from Reddit, so that performance tracking has a reliable data source.

#### Acceptance Criteria

1. THE Performance_Tracker SHALL fetch comment data using the Reddit comment ID via PRAW's comment endpoint.
2. WHEN fetching a comment, THE Performance_Tracker SHALL extract: score, number of direct replies, and whether the comment body is "[removed]" or "[deleted]".
3. IF the PRAW client raises a Forbidden or NotFound exception for a comment, THEN THE Performance_Tracker SHALL treat the comment as removed and update Visibility_Status accordingly.
4. THE Performance_Tracker SHALL log all Reddit API calls for comment fetching with the same structured logging format used by the existing scraping service.

### Requirement 8: Batch Processing Efficiency

**User Story:** As a system operator, I want performance tracking to handle multiple comments efficiently, so that it does not overwhelm the Reddit API or slow down other pipeline tasks.

#### Acceptance Criteria

1. THE Performance_Tracker SHALL process comments in batches, inserting a configurable delay between individual Reddit API calls to respect rate limits.
2. THE Performance_Tracker SHALL skip comments whose last Performance_Snapshot was created less than Snapshot_Interval ago.
3. WHILE processing a batch, THE Performance_Tracker SHALL commit Performance_Snapshot records after each successful comment fetch rather than waiting for the entire batch to complete.
4. THE Performance_Tracker SHALL log a summary at the end of each batch run including: total comments checked, snapshots created, alerts triggered, and errors encountered.
