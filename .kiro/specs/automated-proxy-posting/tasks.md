# Implementation Plan: Automated Proxy Posting

## Overview

Implement the automated proxy posting system that takes human-approved EPG comment drafts and posts them to Reddit via PRAW with per-avatar OAuth credentials, proxy routing, timing jitter, and comprehensive safety gates. The system integrates with existing Celery infrastructure, adds new models (RedditApp, PostingEvent), extends the Avatar model, and provides admin UI for management.

## Tasks

- [ ] 1. Database models and migrations
  - [ ] 1.1 Create RedditApp model and migration
    - Create `app/models/reddit_app.py` with fields: id, client_id, client_secret_encrypted, app_name, registered_under_username, redirect_uri, is_active, created_at
    - Add unique constraint on client_id
    - Register model in `app/models/__init__.py`
    - Create Alembic migration for `reddit_apps` table
    - _Requirements: 1.1, 1.2_

  - [ ] 1.2 Create PostingEvent model and migration
    - Create `app/models/posting_event.py` with fields: id, avatar_id, draft_id, epg_slot_id, posted_at, ip_used, proxy_url_hash, user_agent_used, reddit_comment_id, reddit_comment_url, response_status, response_body_excerpt, error_message, attempt_number, duration_ms, outcome
    - Add foreign keys to avatars, comment_drafts, epg_slots
    - Register model in `app/models/__init__.py`
    - Create Alembic migration for `posting_events` table
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [ ] 1.3 Extend Avatar model with proxy posting fields
    - Add fields to `app/models/avatar.py`: proxy_url_encrypted, user_agent_string, declared_timezone, posting_mode, reddit_app_id, refresh_token_encrypted, last_posted_at, last_posted_ip, last_posted_user_agent, consecutive_post_failures
    - Add ForeignKey to reddit_apps.id for reddit_app_id
    - Default posting_mode to "manual", declared_timezone to "America/New_York"
    - Create Alembic migration for avatar table alterations
    - _Requirements: 2.1, 2.2, 6.3, 7.1_

- [ ] 2. Checkpoint - Ensure migrations run cleanly
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 3. Encryption service
  - [ ] 3.1 Implement FieldEncryptor service
    - Create `app/services/encryption.py` with Fernet-based encrypt/decrypt methods
    - Source key from `FIELD_ENCRYPTION_KEY` environment variable
    - Add `FIELD_ENCRYPTION_KEY` to `app/config.py` Settings class
    - Add key generation instructions to `.env.example`
    - _Requirements: 2.1 (proxy_url storage), 1.1 (client_secret storage)_

  - [ ]* 3.2 Write property test for encryption round-trip
    - **Property 13: Encryption Round-Trip**
    - **Validates: Requirements 2.1, 1.1**

- [ ] 4. Safety gates and validation
  - [ ] 4.1 Implement posting safety gates
    - Create `app/services/posting_safety.py` with `check_posting_safety()` function
    - Implement SafetyResult dataclass (allowed: bool, reason: str)
    - Check order: global kill switch → posting_mode → is_frozen → health_status → phase policy → daily limit → proxy configured → user-agent configured → IP consistency → user-agent consistency
    - Query SystemSetting for `auto_posting_enabled`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 6.1, 6.2, 6.3, 6.4_

  - [ ]* 4.2 Write property test for kill switch and mode enforcement
    - **Property 8: Kill Switch and Mode Enforcement**
    - **Validates: Requirements 6.2, 6.4**

  - [ ]* 4.3 Write property test for safety gates refusing unhealthy avatars
    - **Property 9: Safety Gates Refuse Unhealthy Avatars**
    - **Validates: Requirements 5.6, 5.7**

  - [ ]* 4.4 Write property test for IP consistency enforcement
    - **Property 10: IP Consistency Enforcement**
    - **Validates: Requirements 5.1, 5.2**

  - [ ] 4.5 Implement proxy URL validation
    - Add `validate_proxy_url()` to `app/services/posting_safety.py`
    - Accept only URLs starting with `socks5://` or `http://` with valid host:port
    - Add credential redaction utility for logging
    - _Requirements: 10.2, 8.6_

  - [ ]* 4.6 Write property test for proxy URL validation
    - **Property 14: Proxy URL Validation**
    - **Validates: Requirements 10.2**

  - [ ]* 4.7 Write property test for missing configuration refuses posting
    - **Property 2: Missing Configuration Refuses Posting**
    - **Validates: Requirements 2.6, 2.7**

- [ ] 5. Timing engine
  - [ ] 5.1 Implement timing engine service
    - Create `app/services/timing_engine.py`
    - Implement `calculate_jittered_time()` with ±30% jitter using `secrets.randbelow()`
    - Implement `get_next_valid_posting_time()` with min 45 min / max 90 min interval enforcement
    - Implement active hours clamping (08:00–23:00 in avatar timezone)
    - Implement daily post cap (max 8 per day)
    - Implement peak hour bias (12:00–14:00, 18:00–22:00 at 2x weight)
    - Use `zoneinfo.ZoneInfo` for timezone conversions
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 7.2, 7.3, 7.4, 7.5_

  - [ ]* 5.2 Write property test for timing engine output invariants
    - **Property 6: Timing Engine Output Invariants**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6**

  - [ ]* 5.3 Write property test for jitter bounds
    - **Property 7: Jitter Bounds**
    - **Validates: Requirements 4.1**

  - [ ]* 5.4 Write property test for no posting during sleep hours
    - **Property 17: No Posting During Sleep Hours**
    - **Validates: Requirements 7.4**

- [ ] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. PRAW client factory and posting service
  - [ ] 7.1 Implement PRAW client factory
    - Create `app/services/praw_factory.py`
    - Implement `create_avatar_reddit_client()` that builds authenticated PRAW client with proxy routing and custom user-agent
    - Decrypt proxy_url, refresh_token, client_secret via FieldEncryptor
    - Configure requests.Session with proxy and user-agent
    - Set connection timeouts (30s connect, 60s read)
    - _Requirements: 2.3, 2.4_

  - [ ]* 7.2 Write property test for PRAW client construction correctness
    - **Property 1: PRAW Client Construction Correctness**
    - **Validates: Requirements 2.3, 2.4**

  - [ ] 7.3 Implement proxy IP resolution
    - Add `resolve_proxy_ip()` to `app/services/praw_factory.py`
    - Use ipify.org as echo endpoint through the proxy session
    - Return IP string or None on failure
    - Implement timeout handling (10s default)
    - _Requirements: 5.1, 5.2_

  - [ ] 7.4 Implement core posting service
    - Create `app/services/posting.py` with `execute_post()` function
    - Load slot + avatar + draft + reddit_app from DB
    - Run safety gates via `check_posting_safety()`
    - Verify fingerprint consistency (IP + user-agent)
    - Build PRAW client via factory
    - Submit comment using `submission.reply()` or `comment.reply()` based on `location_depth`
    - On success: update draft (status=posted, posted_at, reddit_comment_url), update slot (status=posted), update avatar (last_posted_at, last_posted_ip, consecutive_post_failures=0)
    - Create PostingEvent audit record for every attempt
    - Store proxy_url_hash as SHA-256, ip_used as resolved IP only
    - Measure duration_ms for each attempt
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 9.2, 9.3, 9.4, 9.5_

  - [ ]* 7.5 Write property test for reply method selection by depth
    - **Property 5: Reply Method Selection by Depth**
    - **Validates: Requirements 3.2**

  - [ ]* 7.6 Write property test for successful post state transitions
    - **Property 4: Successful Post State Transitions**
    - **Validates: Requirements 3.3, 3.4, 3.5**

  - [ ]* 7.7 Write property test for audit event completeness and credential safety
    - **Property 12: Audit Event Completeness and Credential Safety**
    - **Validates: Requirements 9.2, 9.3, 9.4**

- [ ] 8. Error handling and avatar protection
  - [ ] 8.1 Implement error classification and freeze logic
    - Add error handling to `app/services/posting.py`
    - On 401/403: freeze avatar with reason `auth_error: {status_code}`, emit activity event, do NOT retry
    - On account suspended/banned: freeze avatar with reason `account_suspended`, emit activity event
    - On transient errors (timeout, 500, 502, 503): allow retry
    - On 429 rate limit: retry after Retry-After header value
    - Track consecutive_post_failures on avatar; freeze after 3 in 24h with reason `consecutive_failures`
    - On all retries exhausted: mark slot as `skipped` with reason `posting_failed_after_retries`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [ ]* 8.2 Write property test for auth error freezes avatar
    - **Property 11: Auth Error Freezes Avatar**
    - **Validates: Requirements 8.1, 8.2**

  - [ ]* 8.3 Write property test for consecutive failure freeze
    - **Property 15: Consecutive Failure Freeze**
    - **Validates: Requirements 8.5**

- [ ] 9. Celery tasks integration
  - [ ] 9.1 Implement posting Celery tasks
    - Create `app/tasks/posting.py`
    - Implement `execute_pending_posts` periodic task: query EPG slots with status='approved' and scheduled_at <= now(), dispatch individual `post_comment` tasks
    - Implement `post_comment` task with bind=True, max_retries=3, default_retry_delay=60
    - Acquire Redis distributed lock per avatar (key: `posting_lock:{avatar_id}`, TTL=300s)
    - If lock held: retry after 60s
    - Exponential backoff on retry: 60s × 2^attempt
    - Check minimum interval (45 min since last_posted_at) before dispatching
    - Register tasks in `app/tasks/worker.py`
    - _Requirements: 3.6, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [ ] 9.2 Add Celery Beat schedule entry
    - Add `execute-pending-posts` to Beat schedule in `app/tasks/worker.py` with 300s interval
    - _Requirements: 11.1_

  - [ ] 9.3 Add `auto_posting_enabled` system setting
    - Add default SystemSetting record for `auto_posting_enabled` (default: true) in seed data or migration
    - Ensure the setting is queryable by the safety gates
    - _Requirements: 6.1, 6.2, 6.5_

- [ ] 10. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Reddit app management and constraints
  - [ ] 11.1 Implement Reddit app admin CRUD
    - Add routes to `app/routes/admin.py` for listing, creating, editing Reddit apps
    - Validate client_id and client_secret non-empty on creation
    - Display avatar count per app in list view
    - Encrypt client_secret before storage
    - _Requirements: 1.2, 1.3, 1.6_

  - [ ] 11.2 Implement max avatars per Reddit app constraint
    - Add validation in avatar assignment logic: reject if app already has 3 active avatars
    - Add validation in admin UI when assigning avatar to app
    - _Requirements: 1.4, 1.5_

  - [ ]* 11.3 Write property test for max avatars per Reddit app
    - **Property 16: Max Avatars Per Reddit App**
    - **Validates: Requirements 1.5**

  - [ ]* 11.4 Write property test for proxy URL uniqueness among active avatars
    - **Property 3: Proxy URL Uniqueness Among Active Avatars**
    - **Validates: Requirements 2.5**

- [ ] 12. Admin UI for proxy posting management
  - [ ] 12.1 Implement avatar detail proxy section
    - Add proxy configuration section to avatar detail page template
    - Display: proxy_url (masked credentials), user_agent_string, posting_mode toggle, last_posted_at + IP, Reddit OAuth status, consecutive failures count
    - Add edit form for proxy_url (with format validation), user_agent_string, declared_timezone
    - Add posting_mode toggle (auto/manual/disabled) with immediate effect
    - _Requirements: 10.1, 10.2, 10.3, 10.6_

  - [ ] 12.2 Implement posting logs section on avatar detail
    - Add posting events tab/section to avatar detail page
    - Display 50 most recent PostingEvents sorted by posted_at desc
    - Show: timestamp, subreddit, thread title (truncated), outcome (success/failure/skipped), duration_ms, link to Reddit comment
    - Use HTMX partial for lazy loading
    - _Requirements: 10.4, 10.5_

  - [ ] 12.3 Implement global posting dashboard at /admin/posting
    - Create `app/templates/admin_posting_dashboard.html`
    - Display: total posts today, success rate (24h), active auto-posting avatars count
    - Add global kill switch toggle (auto_posting_enabled)
    - Add recent posting events table (last 50 across all avatars)
    - Add per-avatar posting summary (posts today, last post time, status)
    - Add route in `app/routes/admin.py`
    - _Requirements: 10.7, 6.1, 6.5_

- [ ] 13. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The encryption key (`FIELD_ENCRYPTION_KEY`) must be generated and added to `.env` before running the posting service
- The system integrates with existing Celery Beat, Redis locks, and SystemSetting infrastructure
- Admin UI follows existing patterns: dark theme (`admin_base.html`), HTMX partials, `require_superuser` dependency

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["3.1"] },
    { "id": 2, "tasks": ["3.2", "4.1", "4.5", "5.1"] },
    { "id": 3, "tasks": ["4.2", "4.3", "4.4", "4.6", "4.7", "5.2", "5.3", "5.4"] },
    { "id": 4, "tasks": ["7.1", "7.3"] },
    { "id": 5, "tasks": ["7.2", "7.4"] },
    { "id": 6, "tasks": ["7.5", "7.6", "7.7", "8.1"] },
    { "id": 7, "tasks": ["8.2", "8.3", "9.1", "9.2", "9.3"] },
    { "id": 8, "tasks": ["11.1", "11.2"] },
    { "id": 9, "tasks": ["11.3", "11.4", "12.1", "12.2", "12.3"] }
  ]
}
```
