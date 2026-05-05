# Requirements Document

## Introduction

Migrate all application settings from the `.env` file into the database (`system_settings` table) and expose them through an admin panel UI at `/admin/settings`. After migration, only `DATABASE_URL` remains in `.env` (and `REDIS_URL` as a bootstrap fallback). All other configuration — Redis, auth, Reddit API credentials, LLM keys, and app config — is managed from the database via the admin UI. Settings changes take effect without app restart.

## Glossary

- **Settings_Service**: The backend service (`app/services/settings.py`) responsible for reading, writing, and caching system settings from the `system_settings` database table.
- **Settings_Page**: The admin UI page at `/admin/settings` that displays and allows editing of all system settings.
- **Config_Loader**: The application configuration layer (`app/config.py`) that resolves setting values, reading from the database with `.env` fallback for bootstrap settings.
- **System_Setting**: A single key-value record in the `system_settings` table, with metadata fields `is_secret`, `description`, `group`, and `updated_at`.
- **Setting_Group**: A logical category used to organize settings in the UI (e.g., Database, Redis, Auth, Reddit API, LLM, App, Budget/Billing).
- **Bootstrap_Setting**: A setting that must be available before the database connection is established (`DATABASE_URL`, `REDIS_URL`). These remain in `.env` as the primary or fallback source.
- **Secret_Setting**: A setting marked `is_secret=True` whose value is masked in the UI and excluded from non-privileged API responses.
- **Settings_Cache**: An in-memory cache layer within the Settings_Service that avoids repeated database queries for frequently accessed settings.
- **Audit_Log**: The existing audit logging system (`app/services/audit.py`) that records admin actions with user identity, entity type, and details.
- **Admin_User**: A user with `is_superuser=True` who has access to the admin panel.

## Requirements

### Requirement 1: Expand Default Settings Registry

**User Story:** As an admin, I want all application settings that were previously in `.env` to be registered in the database defaults, so that every configurable value is manageable from a single place.

#### Acceptance Criteria

1. THE Settings_Service SHALL include default entries for all settings currently defined in `.env`: `redis_url`, `secret_key`, `access_token_expire_minutes`, `admin_email`, `admin_password`, `admin_name`, `app_env`, `app_host`, `app_port`.
2. WHEN the application starts, THE Settings_Service SHALL call `init_defaults` to ensure all default settings exist in the `system_settings` table without overwriting previously saved values.
3. THE Settings_Service SHALL mark `secret_key`, `admin_password`, `reddit_client_secret`, and `llm_api_key` as secret settings (`is_secret=True`).
4. THE Settings_Service SHALL assign each default setting a `group` label from the set: `database`, `redis`, `auth`, `reddit_api`, `llm`, `app`, `budget`.

### Requirement 2: Database-First Configuration Loading

**User Story:** As a developer, I want the application to read settings from the database instead of `.env`, so that configuration changes made in the admin UI take effect without redeployment.

#### Acceptance Criteria

1. THE Config_Loader SHALL read `DATABASE_URL` exclusively from the `.env` file or environment variables.
2. THE Config_Loader SHALL read `REDIS_URL` from the `.env` file or environment variables as a bootstrap fallback, since Celery requires it before the database is available.
3. WHEN a non-bootstrap setting is requested, THE Config_Loader SHALL query the Settings_Service for the database value first, falling back to the `.env` value only if no database record exists.
4. THE Config_Loader SHALL provide a `get_setting(key)` function that other modules use to retrieve individual settings at runtime instead of accessing a static `Settings` object.

### Requirement 3: Settings Cache with Invalidation

**User Story:** As a developer, I want settings to be cached in memory so that frequent reads do not hit the database on every request, while still reflecting changes promptly.

#### Acceptance Criteria

1. THE Settings_Cache SHALL store setting values in memory after the first database read.
2. WHEN a setting is updated via the Settings_Service `set_setting` function, THE Settings_Cache SHALL invalidate the cached entry for that key immediately.
3. THE Settings_Cache SHALL support a `reload_all` operation that clears the entire cache and re-reads all settings from the database.
4. WHEN the admin saves settings through the Settings_Page, THE Settings_Page SHALL trigger cache invalidation so that new values take effect without app restart.

### Requirement 4: Admin Settings Page — Display

**User Story:** As an admin, I want to see all system settings organized by group on a dedicated admin page, so that I can quickly find and review any configuration value.

#### Acceptance Criteria

1. THE Settings_Page SHALL be accessible at the URL path `/admin/settings`.
2. THE Settings_Page SHALL require the `require_superuser` dependency, restricting access to Admin_User accounts only.
3. THE Settings_Page SHALL display settings organized into collapsible or visually separated sections by Setting_Group: Database, Redis, Auth, Reddit API, LLM, App, Budget/Billing.
4. WHEN a setting has `is_secret=True`, THE Settings_Page SHALL display the value as `•••••` with a reveal toggle button that shows the actual value on click.
5. THE Settings_Page SHALL display the `description` field for each setting as helper text.
6. THE Settings_Page SHALL display the `updated_at` timestamp for each setting that has been modified.
7. THE Settings_Page SHALL extend the `admin_base.html` template and follow the existing dark theme styling.

### Requirement 5: Admin Settings Page — Editing

**User Story:** As an admin, I want to edit settings inline or via a form on the settings page, so that I can update configuration values without accessing the server.

#### Acceptance Criteria

1. WHEN an admin clicks an edit control on a setting, THE Settings_Page SHALL present an editable input field pre-filled with the current value.
2. THE Settings_Page SHALL support saving an individual setting via an HTMX request without a full page reload.
3. THE Settings_Page SHALL support a bulk save action that persists all modified settings in a single operation.
4. WHEN a setting is saved successfully, THE Settings_Page SHALL display a success indicator next to the saved setting.
5. IF a setting value fails validation, THEN THE Settings_Page SHALL display an error message next to the affected field and retain the entered value.
6. THE Settings_Page SHALL use HTMX partial responses for inline editing interactions, consistent with the existing admin panel patterns.

### Requirement 6: Connection Test Buttons

**User Story:** As an admin, I want to test external service connections from the settings page, so that I can verify credentials are correct before relying on them.

#### Acceptance Criteria

1. THE Settings_Page SHALL display a "Test Connection" button in the Reddit API settings group.
2. WHEN the admin clicks the Reddit API test button, THE Settings_Service SHALL attempt to authenticate with the Reddit API using the currently saved `reddit_client_id`, `reddit_client_secret`, and `reddit_user_agent` values.
3. WHEN the Reddit API connection test succeeds, THE Settings_Page SHALL display a green success indicator with the message "Connected".
4. IF the Reddit API connection test fails, THEN THE Settings_Page SHALL display a red error indicator with a truncated error description.
5. THE Settings_Page SHALL display a "Test Connection" button in the LLM settings group.
6. WHEN the admin clicks the LLM test button, THE Settings_Service SHALL attempt a minimal API call to the configured LLM provider using the saved `llm_api_key` and `llm_scoring_model` values.
7. WHEN the LLM connection test succeeds, THE Settings_Page SHALL display a green success indicator.
8. IF the LLM connection test fails, THEN THE Settings_Page SHALL display a red error indicator with a truncated error description.
9. THE Settings_Page SHALL execute connection tests via HTMX requests and display results inline without a full page reload.

### Requirement 7: Audit Logging for Settings Changes

**User Story:** As an admin, I want all settings changes to be recorded in the audit log, so that I can track who changed what and when.

#### Acceptance Criteria

1. WHEN an admin updates a setting, THE Settings_Service SHALL create an Audit_Log entry with `action="update"`, `entity_type="system_setting"`, and `details` containing the setting key and the new value.
2. WHEN the updated setting is a Secret_Setting, THE Audit_Log entry SHALL record the key name but SHALL replace the value in `details` with `"[REDACTED]"` instead of the actual secret value.
3. THE Audit_Log entry SHALL include the `user_id` of the Admin_User who performed the change.

### Requirement 8: Admin Sidebar Navigation

**User Story:** As an admin, I want a navigation link to the settings page in the admin sidebar, so that I can access it from any admin page.

#### Acceptance Criteria

1. THE `admin_base.html` sidebar SHALL include a "System Settings" navigation link pointing to `/admin/settings`.
2. THE navigation link SHALL be placed in the system section of the sidebar, after the "Audit Logs" link and before the "Billing" link.
3. WHEN the admin is on the Settings_Page, THE sidebar link SHALL be highlighted with the active state style, consistent with other admin navigation links.

### Requirement 9: Bootstrap Settings Handling

**User Story:** As a developer, I want `DATABASE_URL` and `REDIS_URL` to remain available from `.env` so that the application can start and connect to infrastructure before the database is accessible.

#### Acceptance Criteria

1. THE Config_Loader SHALL resolve `DATABASE_URL` from environment variables or `.env` only, without querying the database.
2. THE Config_Loader SHALL resolve `REDIS_URL` from environment variables or `.env` for Celery worker bootstrap, since the Celery worker initializes before a database session is available.
3. WHEN the database is accessible, THE Settings_Page SHALL display `redis_url` as an editable setting so that the admin can update it for non-bootstrap consumers that read it at request time.
4. THE Settings_Page SHALL display a read-only informational row for `DATABASE_URL` with a note explaining it can only be changed in the `.env` file.

### Requirement 10: Settings Page Template

**User Story:** As a developer, I want the settings page template to follow existing admin conventions, so that the UI is consistent and maintainable.

#### Acceptance Criteria

1. THE Settings_Page template SHALL be named `admin_system_settings.html` and located in the `app/templates/` directory.
2. THE template SHALL extend `admin_base.html` and use the existing dark theme color scheme (`bg-slate-night`, `bg-dark-steel`, `border-slate-700`, `text-gray-300`).
3. THE template SHALL use Tailwind CSS classes loaded from the CDN, consistent with other admin templates.
4. THE template SHALL use HTMX attributes for all interactive operations (save, test connection, reveal secret).
5. THE template SHALL include a page heading "System Settings" and breadcrumb navigation reading "Admin > System Settings".
