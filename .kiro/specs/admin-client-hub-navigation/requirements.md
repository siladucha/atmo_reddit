# Requirements Document

## Introduction

The Admin Client Hub Navigation feature transforms the existing admin client detail page (`/admin/clients/{id}`) into a comprehensive client-centric hub with tabbed navigation. Currently, the admin panel uses flat navigation where Avatars, Subreddits, Keywords, and Threads are separate top-level pages. This feature consolidates all client-related data into a single hub page with tabs, adds breadcrumb navigation for context, and introduces reporting/analytics functionality within the client context.

## Glossary

- **Admin_Client_Hub**: The enhanced admin client detail page at `/admin/clients/{id}` that serves as a centralized hub for all client-related operations, using tabbed navigation to organize content sections.
- **Tab_Navigation**: A horizontal navigation bar within the Admin_Client_Hub that allows switching between content sections (Overview, Avatars, Subreddits, Keywords, Threads, Reports) without full page reloads.
- **Breadcrumb_Bar**: A hierarchical navigation element displayed in the page header showing the current location path (e.g., Admin > Clients > ClientName > Tab) with clickable links for navigation back.
- **Tab_Partial**: An HTMX-loaded HTML fragment representing the content of a single tab, fetched asynchronously when the tab is activated.
- **Client_Report**: An analytics section within the Admin_Client_Hub that displays performance metrics, pipeline statistics, and activity summaries for a specific client.
- **Active_Tab**: The currently selected tab in the Tab_Navigation, visually highlighted and with its content displayed in the main content area.

## Requirements

### Requirement 1: Tabbed Hub Navigation

**User Story:** As an admin, I want to see all client-related data (avatars, subreddits, keywords, threads, reports) organized in tabs on the client detail page, so that I can manage everything for a client from one place without navigating to separate pages.

#### Acceptance Criteria

1. WHEN an admin navigates to `/admin/clients/{id}`, THE Admin_Client_Hub SHALL display a Tab_Navigation bar with the following tabs: Overview, Avatars, Subreddits, Keywords, Threads, Reports.
2. WHEN an admin clicks a tab in the Tab_Navigation, THE Admin_Client_Hub SHALL load the corresponding Tab_Partial via HTMX without a full page reload.
3. THE Admin_Client_Hub SHALL highlight the Active_Tab in the Tab_Navigation with a distinct visual style (indigo background with white text).
4. WHEN the Admin_Client_Hub loads initially, THE Admin_Client_Hub SHALL display the Overview tab as the Active_Tab by default.
5. WHEN an admin navigates to `/admin/clients/{id}?tab={tab_name}`, THE Admin_Client_Hub SHALL display the specified tab as the Active_Tab.
6. THE Admin_Client_Hub SHALL update the browser URL to reflect the Active_Tab without triggering a full page reload.

### Requirement 2: Tab Content — Overview

**User Story:** As an admin, I want the Overview tab to show a summary of the client's configuration and quick stats, so that I can get a high-level picture at a glance.

#### Acceptance Criteria

1. WHEN the Overview tab is active, THE Admin_Client_Hub SHALL display the client edit form (client name, brand name, company profile, worldview, problem, competitive landscape, brand voice, ICP profiles).
2. WHEN the Overview tab is active, THE Admin_Client_Hub SHALL display summary cards showing counts of keywords, subreddits, and avatars assigned to the client.
3. WHEN the Overview tab is active, THE Admin_Client_Hub SHALL display action buttons for Transparency, Onboarding Wizard, and Deactivate.

### Requirement 3: Tab Content — Avatars

**User Story:** As an admin, I want to see and manage all avatars assigned to a specific client within the client hub, so that I do not need to navigate to the global avatars page and filter manually.

#### Acceptance Criteria

1. WHEN the Avatars tab is active, THE Admin_Client_Hub SHALL display a table of all avatars assigned to the client, showing status, username, Reddit status, warming phase, karma, and health.
2. WHEN the Avatars tab is active, THE Admin_Client_Hub SHALL provide Pause/Activate toggle actions for each avatar inline.
3. WHEN the Avatars tab is active, THE Admin_Client_Hub SHALL provide a Check Reddit Status action for each avatar inline.

### Requirement 4: Tab Content — Subreddits

**User Story:** As an admin, I want to see and manage all subreddits assigned to a specific client within the client hub, so that I can add, remove, or toggle subreddits in context.

#### Acceptance Criteria

1. WHEN the Subreddits tab is active, THE Admin_Client_Hub SHALL display a table of all subreddits assigned to the client, showing subreddit name, type (professional/hobby), active status, and last scraped timestamp.
2. WHEN the Subreddits tab is active, THE Admin_Client_Hub SHALL provide a form to add a new subreddit to the client.
3. WHEN the Subreddits tab is active, THE Admin_Client_Hub SHALL provide Pause/Resume toggle actions for each subreddit inline.
4. WHEN the Subreddits tab is active, THE Admin_Client_Hub SHALL provide a Remove action for each subreddit inline.

### Requirement 5: Tab Content — Keywords

**User Story:** As an admin, I want to manage keywords for a specific client within the client hub, so that I can add and remove keywords without leaving the client context.

#### Acceptance Criteria

1. WHEN the Keywords tab is active, THE Admin_Client_Hub SHALL display all keywords for the client grouped by priority (HIGH, MEDIUM, LOW).
2. WHEN the Keywords tab is active, THE Admin_Client_Hub SHALL provide a form to add a new keyword with a priority selector.
3. WHEN the Keywords tab is active, THE Admin_Client_Hub SHALL provide a Remove action for each keyword inline.
4. WHEN a keyword is added or removed, THE Admin_Client_Hub SHALL update the keywords list via HTMX without a full page reload.

### Requirement 6: Tab Content — Threads

**User Story:** As an admin, I want to see all threads scraped for a specific client within the client hub, so that I can review thread quality and engagement decisions in context.

#### Acceptance Criteria

1. WHEN the Threads tab is active, THE Admin_Client_Hub SHALL display a list of the most recent threads (up to 100) for the client, showing title, subreddit, tag (engage/monitor/skip), score, and creation date.
2. WHEN the Threads tab is active, THE Admin_Client_Hub SHALL provide a filter by tag (engage, monitor, skip, all).
3. WHEN a tag filter is selected, THE Admin_Client_Hub SHALL reload the threads list via HTMX showing only threads matching the selected tag.

### Requirement 7: Tab Content — Reports

**User Story:** As an admin, I want to see performance analytics for a specific client within the client hub, so that I can assess campaign effectiveness and identify issues.

#### Acceptance Criteria

1. WHEN the Reports tab is active, THE Admin_Client_Hub SHALL display pipeline statistics: total threads scraped, threads tagged as engage, comments generated, comments approved, and comments posted for the client.
2. WHEN the Reports tab is active, THE Admin_Client_Hub SHALL display a scrape freshness summary showing each subreddit's last scrape time and a color-coded freshness indicator (green: <24h, yellow: <72h, red: >72h or never).
3. WHEN the Reports tab is active, THE Admin_Client_Hub SHALL display the most recent activity events (up to 50) for the client in a timeline format.
4. WHEN the Reports tab is active, THE Admin_Client_Hub SHALL display AI cost summary for the client (total tokens used, estimated cost) if AI usage data is available.

### Requirement 8: Breadcrumb Navigation

**User Story:** As an admin, I want breadcrumbs that show my current location within the client hub, so that I can navigate back to the clients list or other sections easily.

#### Acceptance Criteria

1. WHEN an admin is on the Admin_Client_Hub page, THE Breadcrumb_Bar SHALL display the path: Admin > Clients > {Client Name}.
2. WHEN an admin activates a tab other than Overview, THE Breadcrumb_Bar SHALL display the path: Admin > Clients > {Client Name} > {Tab Name}.
3. WHEN an admin clicks "Clients" in the Breadcrumb_Bar, THE Breadcrumb_Bar SHALL navigate to `/admin/clients`.
4. THE Breadcrumb_Bar SHALL use the existing admin header breadcrumb area defined in admin_base.html.

### Requirement 9: HTMX Tab Loading Endpoint

**User Story:** As a developer, I want a dedicated endpoint for loading tab content via HTMX, so that tab switching is fast and does not require full page reloads.

#### Acceptance Criteria

1. THE Admin_Client_Hub SHALL expose an endpoint at `/admin/clients/{id}/tab/{tab_name}` that returns the Tab_Partial HTML for the specified tab.
2. WHEN a non-HTMX request is made to `/admin/clients/{id}/tab/{tab_name}`, THE Admin_Client_Hub SHALL redirect to `/admin/clients/{id}?tab={tab_name}`.
3. IF an invalid tab name is provided, THEN THE Admin_Client_Hub SHALL return HTTP 404.
4. IF the client ID does not exist, THEN THE Admin_Client_Hub SHALL return HTTP 404.
5. THE Admin_Client_Hub SHALL require superuser authentication for all tab endpoints.
