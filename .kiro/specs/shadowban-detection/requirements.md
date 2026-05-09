# Requirements Document

## Introduction

Shadowban detection system for Reddit avatars. The system periodically checks whether each active avatar's content is visible to other users, detecting soft restrictions (reduced visibility), full shadowbans (invisible posts/comments), and suspensions. Early detection prevents wasting Claude Sonnet tokens (~$0.04/comment) on invisible comments and protects the pre-warmed avatar inventory ($199–$499 each).

The existing `reddit_status.py` service detects account-level suspension and existence but cannot detect shadowbans (where the account appears normal to the owner but content is invisible to others). This feature adds visibility-based detection using logged-out Reddit API checks.

## Glossary

- **Health_Checker**: The background service that performs periodic avatar health assessments by checking content visibility via the Reddit API
- **Avatar**: A pre-warmed Reddit account managed by the platform, represented by the `Avatar` model
- **Health_Status**: An enumeration of avatar states: ACTIVE, LIMITED, SHADOWBANNED, SUSPENDED, UNKNOWN
- **Visibility_Check**: A Reddit API call made from an unauthenticated session to verify whether an avatar's recent comments/posts are visible to other users
- **Pipeline**: The automated workflow (scrape → score → generate → review) that produces comment drafts
- **Operator**: The admin user who manages avatars and reviews generated content via the admin panel
- **Audit_Logger**: The existing audit logging infrastructure (`app/services/audit.py`) that records system and user actions

## Requirements

### Requirement 1: Avatar Health Status Model

**User Story:** As an operator, I want each avatar to have a clear health status, so that I can immediately identify which avatars are safe to use.

#### Acceptance Criteria

1. THE Avatar model SHALL store a `health_status` field with values: ACTIVE (Reddit account accessible and not restricted), LIMITED (Reddit account has reduced visibility or posting restrictions detected), SHADOWBANNED (Reddit shadowban detected), SUSPENDED (Reddit account suspended or banned), UNKNOWN (status has not yet been determined or cannot be determined)
2. THE Avatar model SHALL store a `health_status_changed_at` timestamp recording when the health status last transitioned to a different value
3. THE Avatar model SHALL store a `health_check_details` JSON field containing the raw results of the most recent health check, with a maximum stored payload size of 10 KB
4. THE Avatar model SHALL store a `consecutive_check_failures` integer tracking how many sequential health checks have returned an error or timed out without producing a status result
5. WHEN an Avatar record is created, THE Avatar model SHALL default `health_status` to UNKNOWN, `consecutive_check_failures` to 0, and `health_check_details` to null
6. WHEN a health check completes successfully with a determined status, THE Avatar model SHALL reset `consecutive_check_failures` to 0
7. IF `consecutive_check_failures` reaches `health_check_max_failures_before_unknown` (default: 5), THEN THE Avatar model SHALL set `health_status` to UNKNOWN

### Requirement 2: Shadowban Visibility Detection

**User Story:** As an operator, I want the system to detect shadowbans by checking comment visibility, so that I know when an avatar's content is invisible to others.

#### Acceptance Criteria

1. WHEN performing a visibility check, THE Health_Checker SHALL fetch up to `health_check_max_comments_to_sample` (default: 10) of the avatar's comments from the last `health_check_comment_lookback_days` (default: 7) days using an unauthenticated Reddit API session
2. IF the avatar has posted at least `health_check_min_comments` (default: 3) comments within the lookback period, THEN THE Health_Checker SHALL calculate the visibility ratio as the number of comments visible from the unauthenticated session divided by the total comments sampled
3. IF the avatar has posted fewer than `health_check_min_comments` comments within the lookback period, THEN THE Health_Checker SHALL skip classification and retain the avatar's previous health status
4. IF the visibility ratio equals 0 (zero comments visible), THEN THE Health_Checker SHALL classify the avatar as SHADOWBANNED
5. IF the visibility ratio is greater than 0 and less than `health_check_visibility_threshold` (default: 0.5), THEN THE Health_Checker SHALL classify the avatar as LIMITED
6. IF the visibility ratio is equal to or greater than `health_check_visibility_threshold`, THEN THE Health_Checker SHALL classify the avatar as ACTIVE
7. IF the Reddit API returns an error during a visibility check, THEN THE Health_Checker SHALL retain the avatar's previous health status and increment `consecutive_check_failures` by 1
8. IF `consecutive_check_failures` reaches `health_check_max_failures_before_limited` (default: 3), THEN THE Health_Checker SHALL classify the avatar as LIMITED and emit a warning-level activity event indicating repeated check failures

### Requirement 3: Profile Accessibility Check

**User Story:** As an operator, I want the system to verify avatar profile pages are accessible, so that suspended or deleted accounts are detected.

#### Acceptance Criteria

1. WHEN performing a health check, THE Health_Checker SHALL attempt to access the avatar's profile page via the Reddit API using an unauthenticated request context before performing any visibility check
2. WHEN the profile page returns a 404 (Not Found) response, THE Health_Checker SHALL classify the avatar as SUSPENDED and skip the visibility check for that avatar
3. WHEN the profile page returns a 403 (Forbidden) response, THE Health_Checker SHALL classify the avatar as SUSPENDED and skip the visibility check for that avatar
4. WHEN the profile page returns a 200 response and the account's `is_suspended` attribute is true, THE Health_Checker SHALL classify the avatar as SUSPENDED and skip the visibility check for that avatar
5. WHEN the profile page returns a 200 response and the account's `is_suspended` attribute is false, THE Health_Checker SHALL proceed to the visibility check for that avatar
6. IF the Reddit API returns a network error, timeout, or unexpected HTTP status code (not 200, 403, or 404) during the profile accessibility check, THEN THE Health_Checker SHALL retain the avatar's previous health status, increment `consecutive_check_failures`, and skip the visibility check for that avatar

### Requirement 4: Periodic Health Check Scheduling

**User Story:** As an operator, I want health checks to run automatically on a schedule, so that problematic accounts are detected without manual intervention.

#### Acceptance Criteria

1. THE Health_Checker SHALL run as a Celery periodic task on an interval defined by the `health_check_interval_hours` SystemSetting (default: 12 hours)
2. WHEN the periodic task fires, THE Health_Checker SHALL check all avatars where active is true and is_frozen is false, and whose last_health_check timestamp is older than the configured interval or null
3. WHEN the batch contains more than 10 avatars, THE Health_Checker SHALL space individual avatar checks by the delay defined in `health_check_rate_limit_delay_seconds` SystemSetting (default: 2 seconds)
4. WHILE processing a batch of avatars, IF one avatar's check fails due to an API or network error, THEN THE Health_Checker SHALL log the error, leave that avatar's cached status fields unchanged, and continue checking remaining avatars
5. WHEN a health check detects a change in an avatar's shadowban or suspension state, THE Health_Checker SHALL update the avatar's health_status field and write an audit log entry recording the previous and new state
6. THE Health_Checker SHALL log the total batch duration, number of avatars checked, number of errors, and count of status changes after each periodic run

### Requirement 5: Pipeline Integration

**User Story:** As an operator, I want the pipeline to skip unhealthy avatars automatically, so that tokens are not wasted on invisible comments.

#### Acceptance Criteria

1. WHILE an avatar's health_status is SHADOWBANNED, THE Pipeline SHALL exclude that avatar from the list of eligible avatars passed to persona selection during comment generation
2. WHILE an avatar's health_status is SUSPENDED, THE Pipeline SHALL exclude that avatar from the list of eligible avatars passed to persona selection during comment generation
3. WHILE an avatar's health_status is SHADOWBANNED or SUSPENDED, THE Pipeline SHALL exclude that avatar from the list of eligible avatars passed to hobby comment generation
4. WHEN a comment draft exists in "pending" status for an avatar whose health_status transitions to SHADOWBANNED or SUSPENDED, THE Pipeline SHALL set a warning flag on all pending drafts for that avatar within 60 seconds of the status change being persisted
5. WHEN the Pipeline excludes an avatar from persona selection due to unhealthy status, THE Pipeline SHALL log a warning-level message containing the avatar reddit_username and the current health_status value
6. IF all avatars assigned to a client are excluded due to unhealthy status, THEN THE Pipeline SHALL skip comment generation for that client and log a warning-level message indicating no eligible avatars remain for that client

### Requirement 6: Admin Panel Health Indicators

**User Story:** As an operator, I want to see avatar health status prominently in the admin panel, so that I can quickly identify and act on problematic accounts.

#### Acceptance Criteria

1. THE Admin_Panel SHALL display a health status badge next to each avatar in the avatar list view, color-coded as follows: ACTIVE = green, LIMITED = yellow, SHADOWBANNED = red, SUSPENDED = red, UNKNOWN = grey
2. THE Admin_Panel SHALL display a health summary widget on the operations dashboard showing counts per health_status category (ACTIVE, LIMITED, SHADOWBANNED, SUSPENDED, UNKNOWN)
3. WHEN an avatar's health_status is SHADOWBANNED or SUSPENDED, THE Admin_Panel SHALL display that avatar in a prominent "Attention Required" section at the top of the avatar list
4. IF no avatars have health_status SHADOWBANNED or SUSPENDED, THEN THE Admin_Panel SHALL hide the "Attention Required" section
5. THE Admin_Panel SHALL display the time elapsed since the last health check for each avatar, formatted as a relative duration (e.g., "2h ago", "3d ago"), or "Never checked" if no health check has been performed
6. WHEN the operator clicks the "Check Now" button for an avatar, THE Admin_Panel SHALL disable the button, display a loading indicator, and upon completion update the avatar's health status badge and elapsed time without a full page reload
7. IF the "Check Now" health check fails, THEN THE Admin_Panel SHALL display an error message indicating the check could not be completed and re-enable the button

### Requirement 7: Audit Logging for Status Changes

**User Story:** As an operator, I want all health status changes to be logged, so that I can track the history of avatar health and investigate patterns.

#### Acceptance Criteria

1. WHEN an avatar's health_status changes from one value to another, THE Audit_Logger SHALL create an audit log entry with action "health_status_changed", entity_type "avatar", entity_id set to the avatar's id, and details containing the previous status, new status, the avatar's reddit_username, and the detection method used
2. WHEN a periodic health check batch completes processing all active avatars, THE Audit_Logger SHALL create an audit log entry with action "health_check_batch_completed", entity_type "avatar", and details containing the total number of avatars checked, the number of status changes detected, and the number of errors encountered
3. WHEN a manual health check is triggered by an operator for a specific avatar, THE Audit_Logger SHALL create an audit log entry with the operator's user_id, action "health_check_manual", entity_type "avatar", and entity_id set to the avatar's id
4. THE Audit_Logger SHALL record the detection method in the audit details for each status change, using one of the following values: "profile_check" (PRAW account metadata lookup), "visibility_check" (comment visibility verification), or "api_error" (status inferred from Reddit API error response such as 403 Forbidden or 404 Not Found)
5. IF the Audit_Logger fails to persist an audit log entry during a health check, THEN THE System SHALL log the failure to the application log with the avatar's reddit_username and the error details, and SHALL NOT interrupt the health check operation

### Requirement 8: Configurable Parameters via Admin Settings

**User Story:** As an operator, I want all health check parameters to be configurable through the admin settings panel, so that I can tune detection behavior without code changes.

#### Acceptance Criteria

1. THE System SHALL store the following health check parameters as SystemSetting records (key-value in the database), manageable via the existing admin Settings page:
   - `health_check_interval_hours` (default: 12) — how often the periodic task runs
   - `health_check_min_comments` (default: 3) — minimum recent comments required for visibility classification
   - `health_check_visibility_threshold` (default: 0.5) — ratio above which avatar is classified ACTIVE
   - `health_check_rate_limit_delay_seconds` (default: 2) — delay between individual avatar checks
   - `health_check_max_failures_before_unknown` (default: 5) — consecutive failures before status becomes UNKNOWN
   - `health_check_max_failures_before_limited` (default: 3) — consecutive failures before emitting LIMITED warning
   - `health_check_comment_lookback_days` (default: 7) — how far back to look for avatar comments
   - `health_check_max_comments_to_sample` (default: 10) — max comments to fetch per avatar
2. WHEN the Health_Checker reads a parameter, THE System SHALL fetch the current value from the SystemSetting table at runtime (not cached across task runs)
3. THE Admin_Panel SHALL display all health check parameters in a dedicated "Health Check" section on the Settings page with input fields, current values, and descriptions
4. WHEN an operator updates a health check parameter, THE System SHALL validate the new value against allowed ranges (e.g., interval_hours >= 1, visibility_threshold between 0.0 and 1.0) and reject invalid values with an error message
5. WHEN a health check parameter is not found in the database, THE System SHALL use the hardcoded default value listed above

### Requirement 9: Warming Phase Exclusion

**User Story:** As an operator, I want shadowbanned avatars excluded from all warming phases, so that warming activities are not wasted on compromised accounts.

#### Acceptance Criteria

1. WHILE an avatar's health_status is SHADOWBANNED, THE Pipeline SHALL exclude that avatar from Phase 1 warming activities (hobby commenting) by skipping it during hobby comment generation task execution
2. WHILE an avatar's health_status is SUSPENDED, THE Pipeline SHALL exclude that avatar from Phase 1 warming activities (hobby commenting) by skipping it during hobby comment generation task execution
3. WHILE an avatar's health_status is SHADOWBANNED or SUSPENDED, THE Pipeline SHALL exclude that avatar from Phase 2 activities (content seeding) and Phase 3 activities (brand integration) by filtering it out of the client avatar list during comment and post generation tasks
4. WHEN an avatar's health_status transitions to SHADOWBANNED or SUSPENDED (detected via periodic health check), THE Pipeline SHALL set that avatar's is_frozen to true, freeze_reason to the detected health_status value, and frozen_at to the current UTC timestamp
5. IF the Pipeline attempts to include a frozen avatar in any warming phase activity, THEN THE Pipeline SHALL skip that avatar and log an informational message indicating the avatar username and freeze status
