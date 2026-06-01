# Requirements Document

## Introduction

Automated proxy-based posting system for Reddit comments. Each avatar posts through its own dedicated residential proxy IP and fixed user-agent string. The system takes human-approved comment drafts (from the EPG pipeline) and posts them to Reddit automatically via PRAW with per-avatar credentials, proxy routing, and timing jitter. Human approval remains at the strategy/EPG level (approve/edit drafts), but the physical act of posting is fully automated — no manual copy-paste required.

The system supports two authentication modes via a Posting Adapter abstraction:
- **Password auth** (MVP, works now): Uses existing script-type Reddit app with avatar username + password. No new app creation required.
- **OAuth auth** (upgrade path): Uses web-type Reddit app with per-avatar refresh_token. Requires Reddit approval for new app creation.

Both modes share the same proxy routing, timing engine, safety gates, and audit trail. The auth mode is transparent to the rest of the system.

This feature builds on top of the EPG system (daily publishing program with scheduled slots). It automates the posting step for avatars configured in auto mode.

## Glossary

- **Posting_Service**: The backend service responsible for executing approved comment posts to Reddit via PRAW, using per-avatar proxy and credentials.
- **Posting_Adapter**: The abstraction layer that handles Reddit authentication. Two implementations: PasswordAuthAdapter (MVP, uses username+password via script app) and OAuthAdapter (upgrade path, uses per-avatar refresh_token via web app).
- **Proxy_Config**: The per-avatar proxy configuration consisting of a proxy URL (SOCKS5 or HTTP format) and a fixed user-agent string, stored on the Avatar model.
- **Reddit_App**: A registered Reddit application (script or web type) with client_id and client_secret. For OAuth mode: apps are scoped to a specific client or to the shared pool. For password auth mode: a single script app may serve all avatars.
- **Client_App**: A Reddit_App assigned to a specific client (`client_id` FK set). All avatars of that client post through their client's app(s). Provides full isolation — revocation of one client's app does not affect other clients. *(OAuth mode only)*
- **Shared_Pool_App**: A Reddit_App with `client_id = NULL`, used for farm avatars and avatars in warming phase that are not yet assigned to a client.
- **Posting_Event**: An audit record capturing every automated posting attempt — IP used, timestamp, HTTP response, Reddit comment ID, and outcome.
- **Kill_Switch**: A system-level or per-avatar toggle that immediately disables automated posting without affecting other pipeline operations.
- **Timing_Engine**: The component that determines when to execute a post, applying jitter (±30%) to the EPG-scheduled time while respecting minimum intervals and timezone constraints.
- **Avatar_Posting_Mode**: A per-avatar setting indicating whether the avatar uses automated posting (`auto`) or is disabled (`disabled`).
- **Fingerprint_Policy**: The set of rules ensuring posting behavior matches the avatar's declared timezone and activity patterns (posting hours, day-of-week distribution).
- **EPG_Slot**: An existing model representing a scheduled publishing action for an avatar on a given day, with status lifecycle: planned → generated → approved → posted.
- **App_Health_Check**: A periodic verification that a Reddit_App's credentials are still valid (not revoked by Reddit). Detects dead apps early and triggers avatar reassignment. *(OAuth mode only)*
- **CQS**: Contributor Quality Score — Reddit's hidden trust classification (lowest/low/moderate/high/highest). Checked by existing `services/cqs_checker.py` via Celery Beat task daily at 06:30. Stored on `avatar.cqs_level`. Phase 1 avatars with CQS "lowest" get reduced daily limit (1/day).

## Requirements

### Requirement 1: Reddit App Management

*(Full requirement applies to OAuth mode. For password auth MVP: a single script-type app record suffices for all avatars.)*

**User Story:** As a system operator, I want to register Reddit OAuth apps scoped to specific clients (or to a shared pool for farm avatars), so that blast radius is isolated per client and revocation of one app does not affect other clients.

#### Acceptance Criteria

1. THE system SHALL store Reddit app records in a `reddit_apps` table with fields: `id`, `client_id` (FK, nullable), `client_id_reddit` (Reddit's client_id string), `client_secret_encrypted`, `app_name`, `registered_under_username`, `redirect_uri`, `created_at`, `is_active`, `last_health_check_at`, `health_status`.
2. WHEN an admin creates a Reddit app record, THE system SHALL validate that `client_id_reddit` and `client_secret` are non-empty strings.
3. THE `reddit_apps.client_id` FK SHALL reference the `clients` table. WHEN `client_id` is NULL, the app belongs to the shared pool (farm/warming avatars).
4. WHEN an avatar is assigned to a Reddit app, THE Avatar model SHALL store the `reddit_app_id` foreign key referencing the assigned app.
5. THE system SHALL enforce that an avatar assigned to a client can ONLY be assigned to a Reddit app that belongs to the same client (or to the shared pool if the avatar has no client assignment).
6. WHEN an admin views the Reddit apps list, THE system SHALL display: app name, owning client (or "Shared Pool"), avatar count, health status, and last health check timestamp.
7. THE system SHALL emit a soft warning (log + admin notification) when a single Reddit app has more than 15 avatars assigned, recommending the operator create an additional app for that client.
8. THE system SHALL support unlimited Reddit app records (no hard cap on total apps).

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
3. THE Timing_Engine SHALL enforce a daily posting cap per avatar calculated as `min(phase_daily_limit, auto_posting_daily_cap)` where:
   - `phase_daily_limit` is the avatar's phase-based limit (Phase 0: 0, Phase 1: 3, Phase 2: 7, Phase 3: 18; CQS "lowest" in Phase 1: 1).
   - `auto_posting_daily_cap` is a configurable system setting (default: 8) that acts as a safety ceiling for automated posting regardless of phase.
4. THE system SHALL provide a system setting `auto_posting_daily_cap` (integer, default 8) in the `posting` settings group. Operators can increase it for proven avatars or decrease it for extra caution.
5. WHILE the calculated posting time falls outside the avatar's active hours (defined by the avatar's declared timezone), THE Timing_Engine SHALL defer the post to the next valid active window.
6. THE Timing_Engine SHALL define active hours as 08:00–23:00 in the avatar's declared timezone.
7. WHEN jitter is applied, THE Timing_Engine SHALL use a cryptographically secure random number generator to prevent predictable patterns.
8. WHEN the effective daily cap is reached, THE Timing_Engine SHALL mark remaining EPG_Slots for that day as `skipped` with reason `daily_cap_reached`.
9. THE EPG service SHALL use the effective daily cap (`min(phase_daily_limit, auto_posting_daily_cap)`) when generating slots, so that no LLM tokens are spent on drafts that will never be posted.

### Requirement 5: Safety Rules Enforcement

**User Story:** As a system operator, I want strict safety rules enforced on automated posting, so that avatar accounts are protected from detection and bans.

#### Acceptance Criteria

1. THE Posting_Service SHALL verify that the avatar's `proxy_url` resolves to an IP within the same /24 subnet as `last_posted_ip` before posting (subnet consistency check). This allows for normal IP rotation within the same residential proxy provider.
2. IF the resolved proxy IP is in a different /24 subnet from `last_posted_ip` and `last_posted_ip` is not null, THEN THE Posting_Service SHALL freeze the avatar with reason `ip_subnet_changed` and log a security alert.
3. THE Posting_Service SHALL delegate phase policy enforcement to the existing `PhasePolicy.check_comment_allowed()` service, which enforces:
   - Phase 0 (Mentor): excluded from automated posting entirely.
   - Phase 1: hobby comments only, in hobby subreddits only, no brand mentions, max 3/day (CQS "lowest": 1/day).
   - Phase 2: hobby + professional comments, in hobby + business subreddits, no explicit brand mentions, max 7/day.
   - Phase 3: all types, all subreddits, brand mentions allowed with ramp-up constraints (early: max 1 brand total, mid: ratio ≤10%, complete: ratio ≤30%), max 18/day.
   - THE Posting_Service SHALL NOT duplicate phase logic — PhasePolicy is the single source of truth.
4. WHEN the daily post count for an avatar reaches the effective daily cap (`min(phase_daily_limit, auto_posting_daily_cap)`), THE Posting_Service SHALL skip remaining scheduled posts for that day and mark EPG_Slots as `skipped` with reason `daily_cap_reached`.
5. THE Posting_Service SHALL check the avatar's `is_frozen` status before every posting attempt and refuse to post for frozen avatars.
6. THE Posting_Service SHALL check the avatar's `health_status` before every posting attempt and refuse to post for avatars with status `shadowbanned` or `suspended`.

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
5. IF an avatar accumulates 3 consecutive posting failures within 24 hours (meaning 3 different EPG_Slot posting attempts that all failed after exhausting retries, with no successful post in between), THEN THE Posting_Service SHALL freeze the avatar with reason `consecutive_failures` and emit an activity event.
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
3. WHEN an admin views the avatar detail page, THE system SHALL display the auth status: for OAuth mode — connection status and a button to initiate the OAuth flow; for password auth mode — a masked password field with "Set/Update Password" action.
4. WHEN an admin views the posting logs section, THE system SHALL display the 50 most recent Posting_Events for that avatar, sorted by `posted_at` descending.
5. WHEN an admin views the posting logs, THE system SHALL show: timestamp, subreddit, thread title (truncated), status (success/failure), duration, and a link to the Reddit comment.
6. WHEN an admin toggles an avatar's `posting_mode`, THE system SHALL update the value immediately and log an audit event.
7. THE system SHALL provide a global posting dashboard at `/admin/posting` showing: total posts today, success rate, active avatars count, and the global kill switch toggle.

### Requirement 11: OAuth Scaling Strategy

*(Applies only when OAuth mode is enabled. Not required for password auth MVP.)*

**User Story:** As a system operator, I want to scale posting capacity by leveraging per-avatar OAuth tokens with independent rate limits, so that the system can support hundreds of avatars without hitting Reddit API constraints.

#### Acceptance Criteria

1. WHEN an avatar completes the OAuth authorization flow, THE system SHALL store a per-avatar `refresh_token` that grants an independent 60 req/min rate limit for that avatar's token.
2. THE system SHALL use per-avatar OAuth tokens for all posting operations. Each avatar authenticates independently through its assigned Reddit app, and each token has its own 60 req/min rate limit.
3. WHEN the Posting_Service posts on behalf of an avatar, THE Posting_Service SHALL use the avatar's own refresh_token (not a shared app token) for all Reddit API calls.
4. THE system SHALL track per-avatar API usage (calls/min, calls/day) to detect avatars approaching their individual rate limits.
5. IF a single Reddit app is revoked or banned by Reddit, THEN only avatars assigned to that app SHALL be affected; avatars on other apps SHALL continue operating normally.
6. THE system SHALL support reassigning an avatar from one Reddit app to another without losing the avatar's refresh_token or posting history.
7. THE system SHALL enforce that a single Reddit web app can authorize unlimited avatars (Reddit does not limit OAuth grants per app), but SHALL distribute client avatars across client-scoped apps for blast radius isolation.
8. WHEN a client has more than 15 active posting avatars on a single app, THE system SHALL log a recommendation to create an additional app for that client.

### Requirement 12: Celery Task Scheduling Integration

**User Story:** As a system operator, I want the posting service to run as Celery tasks triggered by the EPG schedule, so that posting integrates with the existing task infrastructure.

#### Acceptance Criteria

1. THE system SHALL register a Celery Beat task `execute_pending_posts` that runs every 5 minutes to check for EPG_Slots due for posting.
2. WHEN `execute_pending_posts` finds approved EPG_Slots with `scheduled_at` in the past (accounting for jitter), THE system SHALL dispatch individual `post_comment` Celery tasks for each slot.
3. THE `post_comment` Celery task SHALL accept `epg_slot_id` as its parameter and execute the full posting flow (proxy setup, PRAW client creation, comment submission, audit logging).
4. THE `post_comment` task SHALL use Celery's `bind=True` with `max_retries=3` and `default_retry_delay=60` for transient failures.
5. THE system SHALL use a Redis distributed lock per avatar to prevent concurrent posting attempts for the same avatar.
6. WHEN multiple EPG_Slots for the same avatar are due simultaneously, THE system SHALL process them sequentially with the minimum interval enforced between each.

### Requirement 13: Client-Scoped App Isolation and App Health Monitoring

*(Applies only when OAuth mode is enabled with multiple apps. For password auth MVP: all avatars share one script app — no isolation needed.)*

**User Story:** As a system operator, I want Reddit apps isolated per client with automatic health monitoring, so that a revoked app affects only one client and the system detects dead apps before posting failures cascade.

#### Acceptance Criteria

1. THE system SHALL enforce that each paying client has at least one dedicated Reddit app assigned (`reddit_apps.client_id = client.id`).
2. THE system SHALL enforce that avatars belonging to client A CANNOT be assigned to a Reddit app belonging to client B. Avatars may only use apps scoped to their own client or apps in the shared pool (if the avatar is unassigned/farm).
3. WHEN a new client is onboarded, THE admin UI SHALL prompt the operator to register a Reddit app for that client before enabling automated posting for the client's avatars.
4. THE system SHALL run a periodic App_Health_Check (Celery Beat task, every 60 minutes) that verifies each active Reddit app's credentials by making a lightweight authenticated API call (`GET /api/v1/me` via any avatar's token on that app).
5. IF the App_Health_Check receives a 401 or 403 response for an app, THE system SHALL mark the app's `health_status` as `revoked`, freeze all avatars assigned to that app with reason `app_revoked: {app_name}`, and emit an activity event with severity `critical`.
6. IF the App_Health_Check detects 2 or more avatars on the same app receiving auth errors within a 1-hour window, THE system SHALL proactively mark the app as `suspect` and alert the operator (even if the health check itself hasn't run yet).
7. WHEN an app is marked as `revoked`, THE admin UI SHALL display a prominent alert on the client's page with instructions: "Reddit app revoked. Create a new app, register it, and reconnect avatars via OAuth."
8. THE system SHALL support reassigning avatars from a revoked app to a new app of the same client. The reassignment SHALL require a new OAuth authorization flow for each affected avatar (refresh tokens are app-specific).
9. THE `reddit_apps` table SHALL include `health_status` field with values: `healthy`, `suspect`, `revoked`, `unknown` (default: `unknown`).
10. THE system SHALL log all App_Health_Check results as activity events for audit trail.
11. Farm avatars (not assigned to any client) SHALL only be assigned to shared pool apps (`reddit_apps.client_id IS NULL`). WHEN a farm avatar is rented to a client, the avatar SHALL be reassigned to one of the client's apps (requiring re-OAuth).
12. THE system SHALL pre-provision 2-3 shared pool apps at system setup for farm/warming avatars, with no hard limit on avatars per shared pool app (soft warning at 50+).

### Requirement 14: Client Onboarding for Automated Posting

**User Story:** As a system operator, I want a clear onboarding checklist for enabling automated posting for a new client, so that all prerequisites are met before the first automated post goes out.

#### Acceptance Criteria

1. THE system SHALL define the following onboarding prerequisites before automated posting can be enabled for a client's avatars:
   - a) Client record exists with `is_active = true`.
   - b) At least one Reddit app registered and assigned to the client (`reddit_apps.client_id = client.id`, `health_status != 'revoked'`).
   - c) At least one avatar assigned to the client with `posting_mode = 'auto'`.
   - d) Each auto-mode avatar has: `proxy_url_encrypted` set, `user_agent_string` set, credentials configured (either `reddit_password_encrypted` for password auth OR `refresh_token_encrypted` + `reddit_app_id` for OAuth), and assigned to a Reddit app.
   - e) Each auto-mode avatar has completed at least one successful test post (verified via PostingEvent with `outcome = 'success'`).
   - f) Global kill switch `auto_posting_enabled` is `true`.

2. THE admin UI SHALL display a "Posting Readiness" checklist on the client detail page showing the status of each prerequisite (a–f) with green/red indicators.

3. WHEN any prerequisite is not met, THE system SHALL display a clear action item explaining what the operator needs to do (e.g., "Register a Reddit app for this client", "Complete OAuth for avatar X", "Run a test post for avatar Y").

4. THE system SHALL provide a "Test Post" action per avatar that:
   - Picks the oldest approved EPG_Slot (or creates a test slot if none exist).
   - Executes the full posting flow (proxy, OAuth, safety gates, PRAW submission).
   - Reports success/failure with full diagnostics (IP used, response, duration).
   - Does NOT count toward daily cap or posting statistics.

5. THE onboarding flow for automated posting SHALL follow this sequence:

   **Password auth mode (MVP):**
   - Step 1: Operator registers the existing script app in admin UI (if not already registered).
   - Step 2: Operator configures each avatar: proxy_url, user_agent_string, declared_timezone.
   - Step 3: Operator provides Reddit password for the avatar (stored encrypted, AES-256).
   - Step 4: Operator runs "Test Post" per avatar to verify end-to-end connectivity.
   - Step 5: Operator sets avatar `posting_mode = 'auto'` to enable automated posting.

   **OAuth mode (when approved):**
   - Step 1: Operator creates Reddit web app on reddit.com/prefs/apps (manual, ~2 min).
   - Step 2: Operator registers the app in admin UI (client_id_reddit + client_secret + assign to client).
   - Step 3: Operator configures each avatar: proxy_url, user_agent_string, declared_timezone.
   - Step 4: Operator initiates OAuth flow per avatar (redirect → Reddit authorize → callback → refresh_token stored).
   - Step 5: Operator runs "Test Post" per avatar to verify end-to-end connectivity.
   - Step 6: Operator sets avatar `posting_mode = 'auto'` to enable automated posting.

6. THE system SHALL block setting `posting_mode = 'auto'` for an avatar unless prerequisites (d) are met (proxy, user-agent, and either password or OAuth credentials configured). THE system SHALL display a validation error listing missing fields.

7. WHEN a farm avatar is rented to a client, THE system SHALL guide the operator through re-assignment:
   - Reassign avatar to client's Reddit app (requires re-OAuth since tokens are app-specific).
   - Verify proxy is still valid (test connection).
   - Run test post under new app.
   - Only then allow `posting_mode = 'auto'`.

8. THE admin UI SHALL provide a global "Posting Onboarding Status" view at `/admin/posting/onboarding` showing all clients with their readiness percentage and blocking issues.

### Requirement 15: Password Auth Credential Management

**User Story:** As a system operator, I want to securely store and manage Reddit passwords for avatars using password auth mode, so that credentials are protected and easily updatable when needed.

#### Acceptance Criteria

1. THE Avatar model SHALL include a `reddit_password_encrypted` field storing the avatar's Reddit password encrypted with Fernet (AES-128-CBC) using the system's `FIELD_ENCRYPTION_KEY`.
2. THE system SHALL NEVER log, display, or expose Reddit passwords in plaintext. Admin UI SHALL show only "●●●●●●●● (set)" or "Not configured".
3. WHEN the Posting_Service detects an authentication failure (401) for a password-auth avatar, THE system SHALL freeze the avatar with reason `password_auth_failed` and display "Update Password" action in admin UI.
4. THE admin UI SHALL provide a "Set/Update Password" form on the avatar detail page (masked input field, encrypted on save).
5. WHEN an avatar's password is updated, THE system SHALL reset `consecutive_post_failures` to 0 and unfreeze the avatar if it was frozen with reason `password_auth_failed`.
6. THE system SHALL support both auth modes simultaneously: some avatars on password auth, others on OAuth. The PRAW factory selects the mode based on which credentials are present (refresh_token takes priority over password if both exist).

### Requirement 16: Auth Mode Switching

**User Story:** As a system operator, I want to switch an avatar between password auth and OAuth mode, so that I can upgrade avatars to OAuth when approval is obtained without disrupting service.

#### Acceptance Criteria

1. WHEN an avatar is switched from password auth to OAuth mode (refresh_token is set), THE system SHALL continue to retain the stored password as fallback but use OAuth for all posting operations.
2. WHEN an avatar is switched from OAuth to password auth (refresh_token cleared), THE system SHALL require a valid `reddit_password_encrypted` before allowing `posting_mode = 'auto'`.
3. THE admin UI SHALL display the current auth mode for each avatar: "Password Auth" or "OAuth" with a visual indicator.
4. THE system SHALL log an audit event when an avatar's auth mode changes.
