# Requirements Document

## Introduction

The client detail page at `/clients/{id}` currently displays all client information (profile, subreddits, pipeline controls, avatars) on a single monolithic page. As the number of managed entities grows (personas, threads, reports, review queue), this layout becomes unwieldy.

This feature reorganizes the client detail page into a **Client Hub** with tabbed second-level navigation. Each tab loads its content as an HTMX partial (no full page reload), consistent with the existing Jinja2 + HTMX + Tailwind stack. Additionally, the global navigation bar in `base.html` adapts for client-bound users, showing client-specific menu items instead of the global navigation.

## Glossary

- **Client_Hub**: The reorganized client detail page at `/clients/{id}` that serves as a central navigation point with tabbed sections for all client-related data.
- **Tab_Bar**: The horizontal second-level navigation component rendered below the page header, containing clickable tab items that load content via HTMX.
- **Tab_Partial**: A Jinja2 template fragment returned by the server for a specific tab, loaded into the content area via an HTMX GET request without a full page reload.
- **Active_Tab**: The currently selected tab in the Tab_Bar, visually distinguished and whose content is displayed in the content area.
- **Overview_Tab**: The default tab showing client metrics, pipeline status, pipeline controls, and recent activity summary.
- **Subreddits_Tab**: The tab displaying the client's monitored subreddits with freshness indicators and inline add/remove functionality.
- **Avatars_Tab**: The tab displaying avatars assigned to the client, their statuses, and assignment controls.
- **Personas_Tab**: The tab displaying the client's personas with voice profile summaries.
- **Threads_Tab**: The tab displaying found Reddit threads for the client with tag filters (engage/monitor/skip).
- **Review_Tab**: The tab displaying the review queue filtered to the current client only.
- **Reports_Tab**: The tab displaying client-specific statistics: comments per period, engagement metrics, and AI costs.
- **Client_User**: A non-superuser User whose `client_id` field is set, binding them to a specific Client.
- **Admin_User**: A User with `is_superuser = True` who can access all clients and the admin panel.
- **Client_Nav**: The adapted navigation bar shown to Client_Users, replacing global navigation items with client-specific hub links.

## Requirements

### Requirement 1: Tab Bar Rendering

**User Story:** As a user viewing a client's page, I want to see a horizontal tab bar with all available sections, so that I can navigate between different aspects of the client without leaving the page.

#### Acceptance Criteria

1. WHEN a user navigates to `/clients/{client_id}`, THE Client_Hub SHALL render a Tab_Bar containing the following tabs in order: Overview, Subreddits, Avatars, Personas, Threads, Review, Reports.
2. THE Tab_Bar SHALL visually distinguish the Active_Tab from inactive tabs using a different background color and/or border style.
3. WHEN a user clicks a tab in the Tab_Bar, THE Tab_Bar SHALL issue an HTMX GET request to the corresponding tab partial endpoint and display the returned content in the content area below the Tab_Bar.
4. WHEN a user clicks a tab in the Tab_Bar, THE Tab_Bar SHALL update the Active_Tab visual state to reflect the newly selected tab without a full page reload.
5. THE Client_Hub SHALL display the client name and brand name in a header above the Tab_Bar.

### Requirement 2: Default Tab Selection

**User Story:** As a user arriving at the client hub, I want to see the Overview tab loaded by default, so that I immediately get a summary of the client's status.

#### Acceptance Criteria

1. WHEN a user navigates to `/clients/{client_id}` without specifying a tab, THE Client_Hub SHALL load the Overview_Tab content by default.
2. WHEN a user navigates to `/clients/{client_id}?tab={tab_name}`, THE Client_Hub SHALL load the specified tab content and mark it as the Active_Tab.
3. IF an invalid tab name is provided in the `tab` query parameter, THEN THE Client_Hub SHALL fall back to loading the Overview_Tab.

### Requirement 3: Overview Tab Content

**User Story:** As a user, I want the Overview tab to show key client metrics and pipeline controls, so that I can quickly assess the client's current state and trigger pipeline actions.

#### Acceptance Criteria

1. THE Overview_Tab SHALL display the client's company profile information (worldview, problem, competitive landscape) in a collapsible section.
2. THE Overview_Tab SHALL display summary metric cards: total subreddits count, total avatars count, total threads count, threads tagged "engage" count, and pending comments count.
3. THE Overview_Tab SHALL display pipeline control buttons (Scrape, Score, Generate, Full Pipeline) that trigger pipeline actions via HTMX POST requests.
4. THE Overview_Tab SHALL display a pipeline status area that shows feedback after a pipeline action is triggered.

### Requirement 4: Subreddits Tab Content

**User Story:** As a user, I want to manage the client's monitored subreddits in a dedicated tab, so that I can add, view, and assess subreddit freshness without clutter.

#### Acceptance Criteria

1. THE Subreddits_Tab SHALL display a list of all active subreddits for the client, showing subreddit name and type (professional/hobby).
2. THE Subreddits_Tab SHALL display a freshness indicator for each subreddit based on the `last_scraped_at` timestamp: green for scraped within 24 hours, yellow for scraped within 72 hours, red for older or never scraped.
3. THE Subreddits_Tab SHALL provide an inline form to add a new subreddit with name and type fields, submitting via HTMX POST.
4. WHEN a new subreddit is added successfully, THE Subreddits_Tab SHALL update the subreddit list without a full page reload.

### Requirement 5: Avatars Tab Content

**User Story:** As a user, I want to see all avatars assigned to this client and manage assignments, so that I can control which Reddit accounts operate for this client.

#### Acceptance Criteria

1. THE Avatars_Tab SHALL display all avatars assigned to the client, showing reddit username, karma (comment and post), and shadowban status.
2. THE Avatars_Tab SHALL display the Reddit status of each avatar (active, suspended, shadowbanned, unknown) with a color-coded indicator.
3. WHERE the current user is an Admin_User, THE Avatars_Tab SHALL display a list of unassigned avatars with an "Assign" button for each.
4. WHEN an Admin_User clicks the "Assign" button for an unassigned avatar, THE Avatars_Tab SHALL assign the avatar to the client via HTMX POST and update the displayed lists without a full page reload.

### Requirement 6: Personas Tab Content

**User Story:** As a user, I want to view the client's personas and their voice profiles, so that I can understand the content strategy for this client.

#### Acceptance Criteria

1. THE Personas_Tab SHALL display all personas belonging to the client, showing persona name, platform, and active status.
2. THE Personas_Tab SHALL display a truncated voice profile summary for each persona (first 200 characters).
3. WHEN a user clicks on a persona card, THE Personas_Tab SHALL expand to show the full voice profile text.

### Requirement 7: Threads Tab Content

**User Story:** As a user, I want to browse and filter the client's Reddit threads within the hub, so that I can review thread scoring and engagement decisions without navigating away.

#### Acceptance Criteria

1. THE Threads_Tab SHALL display the most recent threads for the client (up to 100), showing post title, subreddit, tag (engage/monitor/skip), and composite score.
2. THE Threads_Tab SHALL provide tag filter buttons (All, Engage, Monitor, Skip) that filter the displayed threads via HTMX GET requests.
3. WHEN a tag filter is selected, THE Threads_Tab SHALL update the thread list to show only threads matching the selected tag, without a full page reload.
4. THE Threads_Tab SHALL display each thread's Reddit URL as a clickable external link.

### Requirement 8: Review Tab Content

**User Story:** As a user, I want to review AI-generated comment drafts for this specific client within the hub, so that I do not need to navigate to the global review page and filter manually.

#### Acceptance Criteria

1. THE Review_Tab SHALL display pending comment drafts filtered to the current client only, showing thread title, avatar username, engagement mode, and AI draft text.
2. THE Review_Tab SHALL provide Approve and Reject action buttons for each pending draft, submitting via HTMX POST.
3. WHEN a draft is approved or rejected, THE Review_Tab SHALL update the draft's visual state inline without a full page reload.
4. THE Review_Tab SHALL provide status filter tabs (Pending, Approved, Posted, Rejected) that filter the displayed drafts via HTMX GET requests.
5. THE Review_Tab SHALL display up to 50 drafts per status filter.

### Requirement 9: Reports Tab Content

**User Story:** As a user, I want to see engagement statistics and AI cost data for this client, so that I can assess the ROI and operational costs.

#### Acceptance Criteria

1. THE Reports_Tab SHALL display the total number of comment drafts grouped by status (pending, approved, rejected, posted) for the client.
2. THE Reports_Tab SHALL display the total AI cost (USD) incurred for the client.
3. THE Reports_Tab SHALL display the count of threads by tag (engage, monitor, skip) for the client.
4. THE Reports_Tab SHALL display the total number of active avatars assigned to the client.

### Requirement 10: Tab Partial Endpoints

**User Story:** As a developer, I want each tab to have a dedicated partial endpoint, so that HTMX can load tab content independently and the architecture remains clean.

#### Acceptance Criteria

1. THE Server SHALL expose GET endpoints at `/clients/{client_id}/tab/{tab_name}` for each tab (overview, subreddits, avatars, personas, threads, review, reports).
2. WHEN an HTMX request is received at a tab endpoint, THE Server SHALL return only the Tab_Partial HTML fragment (not a full page).
3. WHEN a non-HTMX request is received at a tab endpoint, THE Server SHALL redirect to `/clients/{client_id}?tab={tab_name}` to render the full page with the correct tab selected.
4. IF a non-existent tab name is requested, THEN THE Server SHALL return an HTTP 404 response.

### Requirement 11: Client-Bound Navigation Adaptation

**User Story:** As a client-bound user, I want the navigation bar to show links relevant to my client hub, so that I can quickly access my client's sections without seeing irrelevant global links.

#### Acceptance Criteria

1. WHILE a Client_User is authenticated, THE Navigation Bar SHALL display client hub tab links (Overview, Subreddits, Avatars, Personas, Threads, Review, Reports) pointing to `/clients/{client_id}/tab/{tab_name}`.
2. WHILE a Client_User is authenticated, THE Navigation Bar SHALL hide the global "Dashboard" link that lists all clients.
3. WHILE a Client_User is authenticated, THE Navigation Bar SHALL hide the global "Avatars" and "Personas" links that show cross-client views.
4. WHILE an Admin_User is authenticated, THE Navigation Bar SHALL continue to display the existing global navigation links unchanged.
5. THE Navigation Bar SHALL display the client name next to the role badge for Client_Users.

### Requirement 12: Access Control for Client Hub Tabs

**User Story:** As a system operator, I want to ensure that client-bound users can only access their own client's hub, so that data isolation is maintained.

#### Acceptance Criteria

1. WHEN a Client_User requests a tab for a client that does not match the Client_User's `client_id`, THE Server SHALL return an HTTP 403 response.
2. WHEN an Admin_User requests a tab for any client, THE Server SHALL return the requested tab content.
3. IF an unauthenticated request is made to a tab endpoint, THEN THE Server SHALL redirect to the login page.
4. WHEN a request is made for a non-existent client, THE Server SHALL return an HTTP 404 response.

### Requirement 13: URL State and Browser History

**User Story:** As a user, I want the browser URL to reflect the currently active tab, so that I can bookmark or share a link to a specific tab.

#### Acceptance Criteria

1. WHEN a user clicks a tab, THE Client_Hub SHALL update the browser URL to `/clients/{client_id}?tab={tab_name}` using HTMX `hx-push-url`.
2. WHEN a user navigates using the browser back/forward buttons, THE Client_Hub SHALL load the tab indicated by the URL's `tab` query parameter.
