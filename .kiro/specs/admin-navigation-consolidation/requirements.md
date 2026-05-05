# Requirements Document

## Introduction

Consolidation of the admin panel navigation and elimination of duplicate dashboards in the Reddit Marketing SaaS platform. Currently the system has two parallel UI layers: a user-facing light-theme interface (`base.html`) and an admin dark-theme interface (`admin_base.html`). Both contain overlapping functionality — dashboards, client management, avatar management, thread views, and review queues — creating confusion and maintenance burden. This feature unifies all management into a single, well-structured admin navigation with logical grouping and clear hierarchy.

## Glossary

- **Admin_Panel**: The dark-themed superuser management interface at `/admin/*` using `admin_base.html`
- **User_Pages**: The light-themed interface at root paths (`/`, `/review`, `/avatars-page`, `/threads/*`) using `base.html`
- **Client_Hub**: The tabbed client detail page at `/clients/{id}` with overview, subreddits, avatars, threads, review, and reports tabs
- **Navigation_Sidebar**: The fixed left sidebar in `admin_base.html` containing all admin navigation links
- **Navigation_Group**: A visually separated section of related navigation items within the Navigation_Sidebar
- **Active_Indicator**: The visual highlight (indigo background) showing which navigation item is currently active
- **Breadcrumb**: The path indicator in the admin header showing the current location hierarchy
- **HTMX_Partial**: A server-rendered HTML fragment loaded asynchronously via HTMX for inline updates

## Requirements

### Requirement 1: Eliminate Duplicate Dashboard

**User Story:** As an admin, I want a single unified dashboard, so that I do not see the same metrics in two different places and always know where to find system overview information.

#### Acceptance Criteria

1. WHEN an authenticated superuser navigates to `/`, THE Admin_Panel SHALL redirect the superuser to `/admin/`
2. WHEN an authenticated non-superuser (client user) navigates to `/`, THE User_Pages SHALL display the Client_Hub for the user's assigned client
3. THE Admin_Panel dashboard at `/admin/` SHALL display all metrics currently shown on both the user-facing dashboard (`/`) and the admin dashboard, including: total clients, total avatars, pending reviews, AI cost, total threads, total comment drafts, and the activity feed
4. WHEN the duplicate user-facing dashboard route is removed, THE Admin_Panel SHALL preserve all quick-action links (review pending comments, manage avatars) within the admin dashboard

### Requirement 2: Consolidate Navigation into Logical Groups

**User Story:** As an admin, I want navigation items organized into logical groups with clear labels, so that I can quickly find the management section I need.

#### Acceptance Criteria

1. THE Navigation_Sidebar SHALL organize items into the following Navigation_Groups: "Operations" (Dashboard, Review Queue, Scrape Queue, Tasks), "Content" (Clients, Avatars, Subreddits, Keywords), "Monitoring" (System Health, AI Costs, Audit Logs), and "Settings" (System Settings, Billing, Dry Run)
2. WHEN a Navigation_Group is rendered, THE Navigation_Sidebar SHALL display a group label above the group's items in uppercase small text with muted color
3. THE Navigation_Sidebar SHALL display a visual divider between each Navigation_Group
4. THE Navigation_Sidebar SHALL maintain the current Active_Indicator style (indigo background) for the selected item

### Requirement 3: Integrate Threads Management into Admin Panel

**User Story:** As an admin, I want to view and manage threads directly from the admin panel, so that I do not need to switch to the user-facing interface for thread operations.

#### Acceptance Criteria

1. WHEN an admin navigates to `/admin/threads`, THE Admin_Panel SHALL display a threads list page with client filter, tag filter, and the same data columns as the current `/threads/{client_id}` page
2. THE Admin_Panel threads page SHALL use the dark theme (`admin_base.html`) and match the visual style of other admin pages
3. WHEN a client filter is selected, THE Admin_Panel threads page SHALL show only threads belonging to that client
4. WHEN a tag filter is selected, THE Admin_Panel threads page SHALL show only threads with the matching tag (engage, monitor, skip)

### Requirement 4: Integrate Review Queue into Admin Panel

**User Story:** As an admin, I want the review queue accessible directly from the admin panel navigation, so that I can approve and reject comment drafts without leaving the admin interface.

#### Acceptance Criteria

1. WHEN an admin navigates to `/admin/review`, THE Admin_Panel SHALL display the review queue with the same functionality as the current `/review` page (status filter, client filter, approve/reject/edit actions)
2. THE Admin_Panel review page SHALL use the dark theme (`admin_base.html`) and support HTMX inline actions for approve, reject, and edit operations
3. WHEN a comment draft is approved or rejected via the admin review page, THE Admin_Panel SHALL update the draft status and display confirmation inline without full page reload

### Requirement 5: Unify Avatar Management

**User Story:** As an admin, I want a single avatar management page in the admin panel that combines the functionality of both the admin avatars list and the user-facing avatars page, so that all avatar operations are in one place.

#### Acceptance Criteria

1. THE Admin_Panel avatars page at `/admin/avatars` SHALL include the filtering, sorting, grouping, and grid/table view toggle currently available on the `/avatars-page` route
2. THE Admin_Panel avatars page SHALL include admin-only actions: toggle active, phase override, and client assignment
3. WHEN the unified avatars page is rendered, THE Admin_Panel SHALL display avatar health indicators, phase information, and warming progress alongside the avatar list
4. THE Admin_Panel avatars page SHALL support the same HTMX-based Reddit status check currently available on `/avatars-page`

### Requirement 6: Add Global Keywords Page

**User Story:** As an admin, I want a global keywords management page that shows keywords across all clients, so that I can manage keyword strategy from a single view without navigating into each client separately.

#### Acceptance Criteria

1. WHEN an admin navigates to `/admin/keywords`, THE Admin_Panel SHALL display a page listing all keywords grouped by client
2. THE Admin_Panel keywords page SHALL allow adding, removing, and updating keyword priority for any client from the global view
3. WHEN a keyword is modified on the global page, THE Admin_Panel SHALL display the updated keyword list for that client without full page reload

### Requirement 7: Preserve Client Hub for Non-Admin Users

**User Story:** As a client user, I want to keep my dedicated client hub interface, so that I only see information relevant to my account without admin complexity.

#### Acceptance Criteria

1. WHILE a non-superuser is authenticated, THE User_Pages SHALL display the Client_Hub with tabs (overview, subreddits, avatars, threads, review, reports) for the user's assigned client
2. WHILE a non-superuser is authenticated, THE User_Pages SHALL hide all admin-only navigation items (System Health, AI Costs, Audit Logs, System Settings, Billing, Tasks, Scrape Queue)
3. IF a non-superuser attempts to access any `/admin/*` route, THEN THE Admin_Panel SHALL return HTTP 403 Forbidden

### Requirement 8: Update Breadcrumb Navigation

**User Story:** As an admin, I want breadcrumbs that reflect the navigation hierarchy, so that I always know where I am and can navigate back to parent sections.

#### Acceptance Criteria

1. WHEN an admin is on a detail page (client detail, avatar detail, keyword page for a client), THE Admin_Panel SHALL display a breadcrumb showing the full path (e.g., "Admin / Content / Clients / ClientName")
2. WHEN an admin clicks a breadcrumb segment, THE Admin_Panel SHALL navigate to that level of the hierarchy
3. THE Admin_Panel breadcrumb SHALL update to reflect the current Navigation_Group and page title on every page

### Requirement 9: Remove Deprecated User-Facing Admin Routes

**User Story:** As a developer, I want deprecated routes removed, so that the codebase has a single source of truth for each management function and no dead code.

#### Acceptance Criteria

1. WHEN the consolidation is complete, THE Admin_Panel SHALL serve all management functionality previously split between `/admin/*` routes and user-facing routes (`/`, `/review`, `/avatars-page`, `/threads/{client_id}`)
2. WHEN a superuser accesses a deprecated user-facing route (`/review`, `/avatars-page`, `/threads/{client_id}`), THE System SHALL redirect to the corresponding admin panel page
3. THE System SHALL preserve all existing HTMX partial endpoints and API routes (`/review-api/*`, `/avatars-api/*`, `/clients-api/*`) to avoid breaking programmatic integrations

### Requirement 10: Responsive Sidebar Behavior

**User Story:** As an admin using a smaller screen, I want the sidebar to collapse gracefully, so that I can still access navigation without losing content area.

#### Acceptance Criteria

1. WHILE the viewport width is below 1024px, THE Navigation_Sidebar SHALL collapse to show only icons (without text labels)
2. WHEN the admin hovers over the collapsed Navigation_Sidebar, THE Navigation_Sidebar SHALL expand to show full labels as a temporary overlay
3. WHILE the viewport width is below 768px, THE Navigation_Sidebar SHALL be hidden by default and accessible via a hamburger menu button in the header
