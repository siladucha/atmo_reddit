# Requirements Document

## Introduction

Automated proxy-based posting system for Reddit comments. Each avatar posts through its own dedicated residential proxy IP and fixed user-agent string. The system takes human-approved comment drafts (from the EPG pipeline) and posts them to Reddit automatically via PRAW with per-avatar OAuth credentials, proxy routing, and timing jitter. Human approval remains at the strategy/EPG level (approve/edit drafts), but the physical act of posting is fully automated — no manual copy-paste required.

This feature builds on top of the existing OAuth Avatar Auth spec (per-avatar OAuth tokens) and the EPG system (daily publishing program with scheduled slots). It automates the posting step for avatars configured in auto mode.

## Glossary

- **Posting_Service**: The backend service responsible for executing approved comment posts to Reddit via PRAW, using per-avatar proxy and OAuth credentials.
- **Proxy_Config**: The per-avatar proxy configuration consisting of a proxy URL (SOCKS5 or HTTP format) and a fixed user-agent string, stored on the Avatar model.
- **Reddit_App**: A registered Reddit OAuth "web" application with client_id and client_secret. Multiple apps are used for diversification (3-5 apps across 5-7 avatars).
- **Posting_Event**: An audit record capturing every automated posting attempt — IP used, timestamp, HTTP response, Reddit comment ID, and outcome.
- **Kill_Switch**: A system-level or per-avatar toggle that immediately disables automated posting without affecting other pipeline operations.
- **Timing_Engine**: The component that determines when to execute a post, applying jitter (±30%) to the EPG-scheduled time while respecting minimum intervals and timezone constraints.
- **Avatar_Posting_Mode**: A per-avatar setting indicating whether the avatar uses automated posting (`auto`) or is disabled (`disabled`).
- **Fingerprint_Policy**: The set of rules ensuring posting behavior matches the avatar's declared timezone and activity patterns (posting hours, day-of-week distribution).
- **EPG_Slot**: An existing model representing a scheduled publishing action for an avatar on a given day, with status lifecycle: planned → generated → approved → posted.

## Requirements

### Requirement 1: Reddit App Management

**User Story:** As a system operator, I want to register multiple Reddit OAuth apps and distribute avatars across them, so that posting activity is diversified across multiple app identities.

#### Acceptance Criteria

1. THE system SHALL store Reddit app records in a `reddit_apps` table with fields: `id`, `client_id`, `client_secret`, `app_name`, `registered_under_username`, `redirect_uri`, `created_at`, `is_active`.
2. WHEN an admin creates a Reddit app record, THE system SHALL validate that `client_id` and `client_secret` are non-empty strings.
3. THE system SHALL support 3 to 5 active Reddit app records simultaneously.
4. WHEN an avatar is assigned to a Reddit app, THE Avatar model SHALL store the `reddit_app_id` foreign key referencing the assigned app.
5. THE system SHALL enforce a maximum of 3 avatars per Reddit app to maintain diversification.
6. WHEN an admin views the Reddit apps list, THE system SHALL display the count of avatars assigned to each app.

### Requirement 2: Per-Avatar Proxy Configuration

**User Story:** As a system operator, I want to assign a dedicated residential proxy to each avatar, so that each avatar posts from a unique IP address that never changes.

#### Acceptance Criteria

1. THE Avatar model SHALL include a `proxy_url` field storing the proxy connection string in format `socks5://user:pass@ip:port` or `http://user:pass@ip:port`.
2. THE Avatar model SHALL include a `user_agent_string` field storing the fixed browser user-agent for that avatar.
3. WHEN the Posting_Service creates a PRAW client for an avatar, THE Posting_Service SHALL configure the HTTP session to route all traffic through the avatar's `proxy_url`.
4. WHEN the Posting_Service creates a PRAW client for an avatar, THE Posting_Service SHALL set the request user-agent header to the avatar's `user_agent_string`.
5. THE system SHALL enforce that no two active avatars share the same `proxy_url` value.
6. IF an avatar's `proxy_url` is empty or null, THEN THE Posting_Service SHALL refuse to post for that avatar and log a configuration error.
7. IF an avatar's `user_agent_string` is empty or null, THEN THE Posting_Service SHALL refuse to post for that avatar and log a configuration error.

### Requirement 3: Automated Comment Posting Execution

**User Story:** As a system operator, I want approved comment drafts to be posted to Reddit automatically at the scheduled time, so that no manual copy-paste is required.

#### Acceptance Criteria

1. WHEN an EPG_Slot reaches status `approved` and its `scheduled_at` time arrives (with jitter applied), THE Posting_Service SHALL submit the comment text to the target Reddit thread using the avatar's authenticated PRAW client.
2. WHEN the Posting_Service submits a comment, THE Posting_Service SHALL use PRAW's `submission.reply()` or `comment.reply()` method depending on the draft's `location_depth` value.
3. WHEN a comment is posted successfully, THE Posting_Service SHALL update the CommentDraft status to `posted`, set `posted_at` to the current timestamp, and store the `reddit_comment_url`.
4. WHEN a comment is posted successfully, THE Posting_Service SHALL update the corresponding EPG_Slot status to `posted` and set `posted_at`.
5. WHEN a comment is posted successfully, THE Posting_Service SHALL record the avatar's `last_posted_at` timestamp on the Avatar model.
6. THE Posting_Service SHALL execute posting as a Celery task with retry logic: max 3 retries with exponential backoff (60s × 2^attempt) for transient network errors.

### Requirement 4: Timing Engine with Jitter

**User Story:** As a system operator, I want posting times to include random jitter around the scheduled time, so that posting patterns appear natural and non-automated.

#### Acceptance Criteria

1. WHEN the Timing_Engine calculates the actual posting time for an EPG_Slot, THE Timing_Engine SHALL apply a random offset of ±30% of the interval between consecutive slots.
2. THE Timing_Engine SHALL enforce a minimum interval of 45 minutes between consecutive posts from the same avatar.
3. THE Timing_Engine SHALL enforce a maximum interval of 90 minutes as the upper bound for minimum spacing between posts.
4. THE Timing_Engine SHALL enforce a maximum of 8 comments per day per avatar.
5. WHILE the calculated posting time falls outside the avatar's active hours (defined by the avatar's declared timezone), THE Timing_Engine SHALL defer the post to the next valid active window.
6. THE Timing_Engine SHALL define active hours as 08:00–23:00 in the avatar's declared timezone.
7. WHEN jitter is applied, THE Timing_Engine SHALL use a cryptographically secure random number generator to prevent predictable patterns.

### Requirement 5: Safety Rules Enforcement

**User Story:** As a system operator, I want strict safety rules enforced on automated posting, so that avatar accounts are protected from detection and bans.

#### Acceptance Criteria

1. THE Posting_Service SHALL verify that the avatar's `proxy_url` resolves to the same IP as `last_posted_ip` before posting (IP consistency check).
2. IF the resolved proxy IP differs from `last_posted_ip` and `last_posted_ip` is not null, THEN THE Posting_Service SHALL freeze the avatar and log a security alert.
3. THE Posting_Service SHALL verify that the avatar's `user_agent_string` has not changed since the last successful post.
4. THE Posting_Service SHALL respect the avatar's warming phase policy: Phase 1 avatars post hobby comments only, Phase 3 avatars may post brand-related comments.
5. WHEN the daily post count for an avatar reaches the configured maximum (default 8), THE Posting_Service SHALL skip remaining scheduled posts for that day and mark EPG_Slots as `skipped` with reason `daily_limit_reached`.
6. THE Posting_Service SHALL check the avatar's `is_frozen` status before every posting attempt and refuse to post for frozen avatars.
7. THE Posting_Service SHALL check the avatar's `health_status` before every posting attempt and refuse to post for avatars with status `shadowbanned` or `suspended`.

### Requirement 6: Kill Switch Controls

**User Story:** As a system operator, I want global and per-avatar kill switches for automated posting, so that I can immediately halt all automated posting in an emergency.

#### Acceptance Criteria

1. THE system SHALL provide a global system setting `auto_posting_enabled` (boolean, default `true`) that controls whether any automated posting occurs.
2. WHILE `auto_posting_enabled` is `false`, THE Posting_Service SHALL skip all posting tasks and log a message indicating the global kill switch is active.
3. THE Avatar model SHALL include a `posting_mode` field with values: `auto`, `disabled`.
4. WHILE an avatar's `posting_mode` is `disabled`, THE Posting_Service SHALL skip automated posting for that avatar.
5. WHEN an admin toggles the global kill switch, THE system SHALL take effect within 60 seconds for all pending posting tasks.
6. WHEN an admin changes an avatar's `posting_mode`, THE system SHALL take effect immediately for the next posting attempt.

### Requirement 7: Fingerprint Consistency

**User Story:** As a system operator, I want posting times to match each avatar's declared timezone and behavioral patterns, so that the posting fingerprint appears consistent with a real user.

#### Acceptance Criteria

1. THE Avatar model SHALL include a `declared_timezone` field storing the avatar's timezone (e.g., `America/New_York`, `Europe/London`).
2. WHEN the Timing_Engine schedules posts, THE Timing_Engine SHALL convert all scheduling to the avatar's `declared_timezone` before applying active-hours constraints.
3. THE Timing_Engine SHALL distribute posts across the active window with a bias toward peak hours (12:00–14:00 and 18:00–22:00 local time) to mimic natural usage.
4. THE Timing_Engine SHALL avoid posting between 00:00–07:00 in the avatar's declared timezone.
5. WHEN an avatar's `declared_timezone` is not set, THE Timing_Engine SHALL default to `America/New_York`.

### Requirement 8: Error Handling and Avatar Protection

**User Story:** As a system operator, I want the system to automatically freeze avatars on authentication errors or bans, so that compromised accounts are protected from further damage.

#### Acceptance Criteria

1. IF the Reddit API returns a 401 (Unauthorized) or 403 (Forbidden) response during posting, THEN THE Posting_Service SHALL freeze the avatar with reason `auth_error: {status_code}` and emit an activity event.
2. IF the Reddit API returns a response indicating the account is suspended or banned, THEN THE Posting_Service SHALL freeze the avatar with reason `account_suspended` and emit an activity event.
3. IF a posting attempt fails with a transient error (network timeout, 500, 502, 503), THEN THE Posting_Service SHALL retry up to 3 times with exponential backoff.
4. IF all retry attempts fail for a single post, THEN THE Posting_Service SHALL mark the EPG_Slot as `skipped` with reason `posting_failed_after_retries` and move to the next scheduled post.
5. IF an avatar accumulates 3 consecutive posting failures within 24 hours, THEN THE Posting_Service SHALL freeze the avatar with reason `consecutive_failures` and emit an activity event.
6. WHEN a proxy connection fails (timeout or refused), THE Posting_Service SHALL log the proxy error with the avatar's `proxy_url` (credentials redacted) and retry.

### Requirement 9: Audit Trail

**User Story:** As a system operator, I want every automated posting attempt logged with full context, so that I can investigate issues and demonstrate compliance.

#### Acceptance Criteria

1. THE system SHALL create a `posting_events` table with fields: `id`, `avatar_id`, `draft_id`, `epg_slot_id`, `posted_at`, `ip_used`, `proxy_url_hash`, `user_agent_used`, `reddit_comment_id`, `reddit_comment_url`, `response_status`, `response_body_excerpt`, `error_message`, `attempt_number`, `duration_ms`.
2. WHEN a posting attempt is made (success or failure), THE Posting_Service SHALL create a Posting_Event record with all available context.
3. THE Posting_Event SHALL store the `ip_used` field as the resolved IP address of the proxy (not the proxy credentials).
4. THE Posting_Event SHALL store a SHA-256 hash of the proxy URL in `proxy_url_hash` for correlation without exposing credentials.
5. WHEN a posting attempt succeeds, THE Posting_Event SHALL store the `reddit_comment_id` and full `reddit_comment_url` returned by Reddit.
6. THE system SHALL retain Posting_Event records for a minimum of 180 days.

### Requirement 10: Admin UI for Proxy Posting Management

**User Story:** As an admin, I want a UI to configure proxies, connect Reddit OAuth, view posting logs, and toggle automated posting per avatar, so that I can manage the posting infrastructure.

#### Acceptance Criteria

1. WHEN an admin views the avatar detail page, THE system SHALL display the proxy configuration section showing `proxy_url` (credentials masked), `user_agent_string`, `posting_mode`, and `last_posted_at`.
2. WHEN an admin edits an avatar's proxy configuration, THE system SHALL validate the proxy URL format (must start with `socks5://` or `http://`).
3. WHEN an admin views the avatar detail page, THE system SHALL display the Reddit OAuth connection status and a button to initiate the OAuth flow.
4. WHEN an admin views the posting logs section, THE system SHALL display the 50 most recent Posting_Events for that avatar, sorted by `posted_at` descending.
5. WHEN an admin views the posting logs, THE system SHALL show: timestamp, subreddit, thread title (truncated), status (success/failure), duration, and a link to the Reddit comment.
6. WHEN an admin toggles an avatar's `posting_mode`, THE system SHALL update the value immediately and log an audit event.
7. THE system SHALL provide a global posting dashboard at `/admin/posting` showing: total posts today, success rate, active avatars count, and the global kill switch toggle.

### Requirement 11: Celery Task Scheduling Integration

**User Story:** As a system operator, I want the posting service to run as Celery tasks triggered by the EPG schedule, so that posting integrates with the existing task infrastructure.

#### Acceptance Criteria

1. THE system SHALL register a Celery Beat task `execute_pending_posts` that runs every 5 minutes to check for EPG_Slots due for posting.
2. WHEN `execute_pending_posts` finds approved EPG_Slots with `scheduled_at` in the past (accounting for jitter), THE system SHALL dispatch individual `post_comment` Celery tasks for each slot.
3. THE `post_comment` Celery task SHALL accept `epg_slot_id` as its parameter and execute the full posting flow (proxy setup, PRAW client creation, comment submission, audit logging).
4. THE `post_comment` task SHALL use Celery's `bind=True` with `max_retries=3` and `default_retry_delay=60` for transient failures.
5. THE system SHALL use a Redis distributed lock per avatar to prevent concurrent posting attempts for the same avatar.
6. WHEN multiple EPG_Slots for the same avatar are due simultaneously, THE system SHALL process them sequentially with the minimum interval enforced between each.
