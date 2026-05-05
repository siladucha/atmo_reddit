# Implementation Plan: System Settings UI

## Overview

Migrate application configuration from `.env`/pydantic-settings into the database-backed `system_settings` table with an admin UI at `/admin/settings`. Implementation extends the existing `SystemSetting` model and `settings.py` service with a `group` column, in-memory cache, connection testing, audit logging, and a full HTMX-powered admin page.

## Tasks

- [x] 1. Extend the SystemSetting model with a `group` column
  - [x] 1.1 Add `group` column to `SystemSetting` in `app/models/settings.py`
    - Add `group: Mapped[str] = mapped_column(String(50), nullable=False, default="app")`
    - _Requirements: 1.4_
  - [x] 1.2 Create Alembic migration for the `group` column
    - Generate migration adding `group` column with default `"app"` to `system_settings` table
    - _Requirements: 1.4_

- [x] 2. Extend the Settings Service with cache, defaults registry, and audit logging
  - [x] 2.1 Expand the `DEFAULTS` registry with all settings and group assignments
    - Add entries for `redis_url`, `secret_key`, `access_token_expire_minutes`, `admin_email`, `admin_password`, `admin_name`, `app_env`, `app_host`, `app_port` with correct `group` and `secret` flags
    - Ensure groups are from the set: `database`, `redis`, `auth`, `reddit_api`, `llm`, `app`, `budget`
    - Mark `secret_key`, `admin_password`, `reddit_client_secret`, `llm_api_key` as `is_secret=True`
    - _Requirements: 1.1, 1.3, 1.4_
  - [x] 2.2 Implement in-memory cache (`_cache` dict) in `app/services/settings.py`
    - Add module-level `_cache: dict[str, str]` and `_cache_loaded: bool`
    - Modify `get_setting()` to check cache first, populate on miss
    - Add `invalidate_cache(key: str | None = None)` function
    - Add `reload_cache(db: Session)` function that clears and reloads all settings
    - _Requirements: 3.1, 3.2, 3.3_
  - [x] 2.3 Update `set_setting()` to accept `user_id` and create audit log entries
    - Add `user_id: uuid.UUID | None = None` parameter to `set_setting()`
    - Call `audit_service.log_action()` with `action="update"`, `entity_type="system_setting"`
    - Include setting key in details; redact value with `"[REDACTED]"` if `is_secret=True`
    - Invalidate cache for the updated key after write
    - _Requirements: 7.1, 7.2, 7.3, 3.2_
  - [x] 2.4 Update `init_defaults()` to persist `group` field for each setting
    - Write `group` from the DEFAULTS registry when creating new setting rows
    - Ensure existing rows are not overwritten (idempotency)
    - _Requirements: 1.2, 1.4_
  - [x] 2.5 Implement `test_reddit_connection(db)` and `test_llm_connection(db)` functions
    - Reddit: authenticate with PRAW using saved credentials, return `{"success": bool, "message": str}`
    - LLM: make a minimal LiteLLM API call using saved key and model, return `{"success": bool, "message": str}`
    - Truncate error messages to 100 characters max
    - _Requirements: 6.2, 6.3, 6.4, 6.6, 6.7, 6.8_
  - [x] 2.6 Implement `bulk_save_settings(db, updates: dict, user_id)` function
    - Accept a dict of key-value pairs, persist all, invalidate cache for each, audit log each change
    - _Requirements: 5.3_
  - [ ]* 2.7 Write property tests for settings service (cache and defaults)
    - **Property 1: init_defaults idempotency**
    - **Validates: Requirements 1.2**
  - [ ]* 2.8 Write property test for valid group labels
    - **Property 2: All settings have valid group labels**
    - **Validates: Requirements 1.4**
  - [ ]* 2.9 Write property test for database-first resolution
    - **Property 3: Database-first resolution for non-bootstrap keys**
    - **Validates: Requirements 2.3**

- [x] 3. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Implement cache property tests and service integration
  - [ ]* 4.1 Write property test for cache read-through
    - **Property 4: Cache read-through**
    - **Validates: Requirements 3.1**
  - [ ]* 4.2 Write property test for cache invalidation on write
    - **Property 5: Cache invalidation on write**
    - **Validates: Requirements 3.2**
  - [ ]* 4.3 Write property test for cache reload_all
    - **Property 6: Cache reload_all clears all entries**
    - **Validates: Requirements 3.3**
  - [ ]* 4.4 Write property test for audit log correctness
    - **Property 8: Audit log created with correct details on update**
    - **Validates: Requirements 7.1, 7.3**
  - [ ]* 4.5 Write property test for secret redaction in audit log
    - **Property 9: Secret values redacted in audit log**
    - **Validates: Requirements 7.2**
  - [ ]* 4.6 Write property test for connection test error truncation
    - **Property 10: Connection test error truncation**
    - **Validates: Requirements 6.4, 6.8**
  - [ ]* 4.7 Write property test for bulk save persistence
    - **Property 11: Bulk save persists all values**
    - **Validates: Requirements 5.3**

- [x] 5. Refactor Config Loader for database-first resolution
  - [x] 5.1 Reduce `Settings` class in `app/config.py` to bootstrap-only values
    - Keep only `database_url` and `redis_url` in the pydantic `Settings` class
    - Remove all other fields (they now come from DB)
    - _Requirements: 9.1, 9.2_
  - [x] 5.2 Add `get_config(key, db=None)` function to `app/config.py`
    - For bootstrap keys (`database_url`, `redis_url`), return from env/Settings
    - For all other keys, delegate to `settings_service.get_setting(db, key)`
    - Handle the case where `db` is None by creating a session
    - _Requirements: 2.1, 2.2, 2.3, 2.4_
  - [x] 5.3 Update existing modules that import from `config.Settings` to use `get_config()` or `settings_service.get_setting()`
    - Identify and update callers of `get_settings().reddit_client_id`, `get_settings().litellm_api_key`, etc.
    - Ensure `get_settings()` still works for `database_url` and `redis_url`
    - _Requirements: 2.3, 2.4_

- [x] 6. Checkpoint — Ensure all tests pass after config refactor
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Create admin settings route endpoints
  - [x] 7.1 Add `GET /admin/settings` endpoint in `app/routes/admin.py`
    - Require `require_superuser` dependency
    - Fetch all settings via `get_all_settings(db)`, group by `group` field
    - Render `admin_system_settings.html` template with grouped settings
    - Include `DATABASE_URL` as a read-only informational row
    - _Requirements: 4.1, 4.2, 4.3, 9.4_
  - [x] 7.2 Add `POST /admin/settings/{key}` endpoint for individual setting save
    - Accept `value` from form, call `set_setting(db, key, value, user_id)`
    - Return HTMX partial with success indicator
    - Trigger cache invalidation
    - _Requirements: 5.2, 5.4, 3.4_
  - [x] 7.3 Add `POST /admin/settings/bulk-save` endpoint
    - Accept multiple key-value pairs from form, call `bulk_save_settings()`
    - Return HTMX partial with success state
    - _Requirements: 5.3_
  - [x] 7.4 Add `POST /admin/settings/test/reddit` endpoint
    - Call `test_reddit_connection(db)`, return HTMX partial with result indicator
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.9_
  - [x] 7.5 Add `POST /admin/settings/test/llm` endpoint
    - Call `test_llm_connection(db)`, return HTMX partial with result indicator
    - _Requirements: 6.5, 6.6, 6.7, 6.8, 6.9_

- [x] 8. Create the admin settings page template
  - [x] 8.1 Create `app/templates/admin_system_settings.html`
    - Extend `admin_base.html`, use dark theme classes (`bg-slate-night`, `bg-dark-steel`, `border-slate-700`, `text-gray-300`)
    - Add page heading "System Settings" and breadcrumb "Admin > System Settings"
    - Render settings grouped by `group` in visually separated cards
    - For each setting: display key label, current value (masked if secret with reveal toggle), description, updated_at
    - Add inline edit button → input field + save button using HTMX `hx-post`
    - Add bulk save button
    - Add "Test Connection" buttons in `reddit_api` and `llm` group cards
    - Show `DATABASE_URL` as read-only with explanatory note
    - Use Tailwind CSS classes from CDN
    - _Requirements: 4.1, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.4, 5.5, 5.6, 6.1, 6.5, 6.9, 9.3, 9.4, 10.1, 10.2, 10.3, 10.4, 10.5_
  - [ ]* 8.2 Write property test for secret masking in rendered output
    - **Property 7: Secret values masked in rendered output**
    - **Validates: Requirements 4.4**

- [x] 9. Update admin sidebar navigation
  - [x] 9.1 Add "System Settings" link to `app/templates/admin_base.html` sidebar
    - Place after "Audit Logs" and before "Billing"
    - Use `active_nav == "settings"` for active state highlighting
    - _Requirements: 8.1, 8.2, 8.3_

- [x] 10. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Integration tests for settings routes
  - [ ]* 11.1 Write integration tests for settings page access control
    - Test GET `/admin/settings` returns 200 for superuser, 403 for non-superuser
    - Test settings page contains grouped sections
    - _Requirements: 4.1, 4.2_
  - [ ]* 11.2 Write integration tests for save and connection test endpoints
    - Test POST save updates DB and invalidates cache
    - Test connection test endpoints return correct HTMX partials
    - Mock external services (PRAW, LiteLLM) for connection tests
    - _Requirements: 5.2, 5.3, 6.2, 6.6_

- [x] 12. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (11 properties total)
- Unit/integration tests validate specific examples and edge cases
- The existing `check_connections()` function in `settings.py` will be superseded by the new `test_reddit_connection()` and `test_llm_connection()` functions
- Cache is in-process dict (no Redis dependency) since the app runs single-process uvicorn
