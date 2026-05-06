# Requirements Document

## Introduction

Consolidate two separate settings pages — `/admin/settings` (admin panel, dark theme) and `/settings` (user-facing, light theme) — into a single unified settings page at `/admin/settings`. In the current agency model, the user (Max) is both the system admin and the client manager, so the split between "admin" and "user" settings is unnecessary and confusing. The unified page retains the full functionality of the admin settings page (grouped tabs, inline editing, connection tests, bulk save) and absorbs any unique functionality from the user-facing page. The old `/settings` route is removed or redirected.

## Glossary

- **Unified_Settings_Page**: The single consolidated settings page at `/admin/settings` that replaces both the former admin settings page and the user-facing settings page.
- **Settings_Service**: The backend service (`app/services/settings.py`) responsible for reading, writing, and caching system settings from the `system_settings` database table.
- **System_Setting**: A single key-value record in the `system_settings` table, with metadata fields `is_secret`, `description`, `group`, and `updated_at`.
- **Setting_Group**: A logical category used to organize settings in the UI (e.g., Database, Redis, Auth, Reddit API, LLM, App, Scraping, Budget).
- **Admin_User**: A user with `is_superuser=True` who has access to the admin panel.
- **Connection_Status_Panel**: A visual summary showing the connection state of external services (Reddit API, LLM, Database, Redis).
- **Legacy_Settings_Route**: The old user-facing settings route at `/settings` that will be removed or redirected after consolidation.

## Requirements

### Requirement 1: Remove User-Facing Settings Page

**User Story:** As the system owner, I want the separate `/settings` page removed, so that there is only one place to manage all system settings.

#### Acceptance Criteria

1. WHEN a user navigates to `/settings`, THE application SHALL redirect to `/admin/settings` with HTTP 303 status.
2. WHEN a user navigates to `/settings-save`, THE application SHALL redirect to `/admin/settings` with HTTP 303 status.
3. THE `settings.html` template (light theme) SHALL be removed from the templates directory after the redirect is in place.
4. THE Unified_Settings_Page SHALL retain all setting groups previously visible on the user-facing page: Reddit API, LLM, Budget, and Notifications (alert_email).

### Requirement 2: Add Connection Status Panel to Unified Page

**User Story:** As the system owner, I want to see a quick overview of external service connection statuses on the settings page, so that I can immediately identify configuration problems.

#### Acceptance Criteria

1. THE Unified_Settings_Page SHALL display a Connection_Status_Panel at the top of the page, above the settings tabs.
2. THE Connection_Status_Panel SHALL show status indicators for: Reddit API, LLM, Database, and Redis.
3. WHEN a service is configured and reachable, THE Connection_Status_Panel SHALL display a green indicator with the label "Connected" or "Configured".
4. WHEN a service is not configured, THE Connection_Status_Panel SHALL display a gray indicator with the label "Not configured".
5. IF a service connection check returns an error, THEN THE Connection_Status_Panel SHALL display a red indicator with the label "Error".

### Requirement 3: Add Scraping Group to Settings Tabs

**User Story:** As the system owner, I want scraping-related settings visible in the unified settings page, so that I can configure scrape queue parameters from the same place as other settings.

#### Acceptance Criteria

1. THE Unified_Settings_Page SHALL include a "Scraping" tab in the tab navigation, positioned after the "App" tab and before the "Budget" tab.
2. THE Scraping tab SHALL display settings with group "scraping": `scrape_enabled`, `scrape_tick_interval_seconds`, `scrape_freshness_window_hours`, `scrape_rate_limit_rpm`.
3. THE Scraping tab SHALL follow the same inline-edit pattern as other setting groups on the page.

### Requirement 4: Unified Page Retains Full Admin Functionality

**User Story:** As the system owner, I want the unified settings page to keep all existing admin settings features, so that no functionality is lost during consolidation.

#### Acceptance Criteria

1. THE Unified_Settings_Page SHALL display settings organized into tabs by Setting_Group: Database, Redis, Auth, Reddit API, LLM, App, Scraping, Budget.
2. THE Unified_Settings_Page SHALL support inline editing of individual settings via HTMX without full page reload.
3. THE Unified_Settings_Page SHALL support bulk save of all modified settings via a "Save All Changes" button.
4. THE Unified_Settings_Page SHALL display "Test Connection" buttons for Reddit API and LLM groups.
5. WHEN a setting has `is_secret=True`, THE Unified_Settings_Page SHALL mask the value with a reveal toggle.
6. THE Unified_Settings_Page SHALL display `database_url` as a read-only informational row in the Database group.
7. THE Unified_Settings_Page SHALL extend `admin_base.html` and use the dark theme styling.

### Requirement 5: Navigation Updates

**User Story:** As the system owner, I want the navigation to reflect the single settings page, so that I can find settings without confusion.

#### Acceptance Criteria

1. THE `admin_base.html` sidebar SHALL retain the "System Settings" link pointing to `/admin/settings`.
2. THE `base.html` navigation (light theme) SHALL remove the "Settings" link that previously pointed to `/settings`.
3. WHEN the user is on any page using `base.html`, THE navigation SHALL include a link to `/admin/settings` labeled "Settings" if the user is an Admin_User.

### Requirement 6: Preserve Audit Logging

**User Story:** As the system owner, I want all settings changes to continue being recorded in the audit log, so that I maintain a history of configuration changes.

#### Acceptance Criteria

1. WHEN a setting is updated through the Unified_Settings_Page, THE Settings_Service SHALL create an audit log entry with `action="update"`, `entity_type="system_setting"`, and details containing the setting key and new value.
2. WHEN the updated setting is a secret, THE audit log entry SHALL record `"[REDACTED]"` instead of the actual value.
3. THE audit log entry SHALL include the `user_id` of the Admin_User who performed the change.

### Requirement 7: Clean Up Dead Code

**User Story:** As a developer, I want unused settings-related code removed, so that the codebase stays clean and maintainable.

#### Acceptance Criteria

1. THE `settings_page` GET handler in `pages.py` SHALL be replaced with a redirect to `/admin/settings`.
2. THE `settings_save` POST handler in `pages.py` SHALL be removed.
3. THE `settings_save_async` POST handler in `pages.py` SHALL be removed.
4. THE `settings.html` template file SHALL be deleted.
5. THE `check_connections` function in Settings_Service SHALL remain available since the Connection_Status_Panel uses it.
