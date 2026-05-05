# Requirements Document

## Introduction

This feature adds a new `/personas-page` to the Reddit Marketing SaaS platform. The page lists all Personas (voice profiles for content generation) with filtering, sorting, pagination, and grouping — mirroring the existing `/avatars-page` pattern. Because Personas are voice profiles (not Reddit accounts), they do not have their own Reddit credentials. However, each Persona belongs to a Client, and that Client's Avatars do have Reddit accounts. The page surfaces the Reddit status of associated Avatars for each Persona, with UI tooltips explaining what each check means and how to interpret results. A "Personas" link is added to the main navigation.

Key domain distinction: Personas define HOW an avatar speaks; Avatars define WHO posts on Reddit. Reddit checks (status, karma, shadowban) apply to Avatars. The Personas page shows these checks in the context of each Persona's Client, so users understand the health of the Reddit accounts that will use a given voice profile.

Persona count is unlimited per Client (no tier-based limit). Avatar count is limited by pricing tier (1/3/7/15), but that constraint is out of scope for this feature.

## Glossary

- **Personas_Page**: The server-rendered page at `/personas-page` that lists, filters, sorts, and paginates Persona records
- **Persona**: A voice profile record (model `Persona`) belonging to a Client, used for content generation. Fields: `id`, `client_id`, `persona_name`, `platform`, `voice_profile`, `is_active`, `created_at`
- **Avatar**: A Reddit account record (model `Avatar`) with `reddit_username`, Reddit status cache fields, and `client_ids` array
- **Client**: A business entity (model `Client`) that owns Personas and is referenced by Avatars via `client_ids`
- **Reddit_Status_Check**: The process of calling the Reddit API (via PRAW) to fetch an Avatar's account status (active, suspended, not_found, unknown, error), karma, and account age
- **Associated_Avatars**: The set of Avatars whose `client_ids` array contains the `client_id` of a given Persona
- **Filter_Bar**: The sticky toolbar at the top of the page providing search, client filter, status filter, sort, group, and view controls
- **Persona_Card**: A UI card component displaying a single Persona with its voice profile, associated Client, associated Avatars and their Reddit statuses
- **Persona_Row**: A UI table row component displaying a single Persona in table view
- **Tooltip**: A hover-activated UI element (using the existing `help-tip` CSS class) that explains what a Reddit check does and how to interpret its result
- **Personas_Query_Service**: The backend service module (`services/personas_query.py`) that handles search, filter, sort, group, and paginate logic for Personas
- **Navigation_Bar**: The top navigation bar defined in `base.html`

## Requirements

### Requirement 1: Personas Page Route

**User Story:** As a user, I want to access a dedicated Personas page at `/personas-page`, so that I can view and manage all voice profiles in one place.

#### Acceptance Criteria

1. WHEN a GET request is made to `/personas-page`, THE Personas_Page SHALL render the full page with the Personas list, Filter_Bar, and pagination
2. WHEN a GET request is made to `/personas-page` with an `HX-Request` header, THE Personas_Page SHALL return only the results partial (for HTMX inline updates)
3. THE Personas_Page SHALL scope visible Personas to the current user's Client when the user is not an admin
4. WHEN the user is an admin, THE Personas_Page SHALL display Personas across all Clients

### Requirement 2: Navigation Link

**User Story:** As a user, I want a "Personas" link in the main navigation bar, so that I can quickly navigate to the Personas page.

#### Acceptance Criteria

1. THE Navigation_Bar SHALL include a "Personas" link pointing to `/personas-page`, positioned after the "Avatars" link
2. WHILE the user is on the Personas_Page, THE Navigation_Bar SHALL highlight the "Personas" link with the active style (`font-semibold text-gray-900`)

### Requirement 3: Persona Listing with Filters

**User Story:** As a user, I want to search, filter, sort, and group Personas, so that I can find specific voice profiles efficiently.

#### Acceptance Criteria

1. THE Filter_Bar SHALL provide a text search field that filters Personas by `persona_name` (case-insensitive partial match)
2. THE Filter_Bar SHALL provide a Client dropdown filter (visible to admins and users with access to multiple Clients)
3. THE Filter_Bar SHALL provide a status filter with options: All, Active, Inactive
4. THE Filter_Bar SHALL provide sort options: Name A→Z, Name Z→A, Newest first, Oldest first
5. THE Filter_Bar SHALL provide a group toggle: Group by Client, Flat list
6. THE Filter_Bar SHALL provide a view toggle: Grid, Table
7. WHEN any filter or sort control changes, THE Personas_Page SHALL update results via HTMX without a full page reload
8. WHEN filters are active, THE Filter_Bar SHALL display a "Reset" link that clears all filters
9. THE Filter_Bar SHALL push the current filter state to the browser URL so that filtered views are shareable and reload-safe

### Requirement 4: Persona Card Display

**User Story:** As a user, I want each Persona card to show the voice profile details and its associated Avatars with Reddit statuses, so that I understand the health of accounts using this voice.

#### Acceptance Criteria

1. THE Persona_Card SHALL display the Persona name, platform, active/inactive status, and creation date
2. THE Persona_Card SHALL display the owning Client name as a link to the Client detail page
3. THE Persona_Card SHALL display the voice profile text in a collapsible section (collapsed by default)
4. THE Persona_Card SHALL list all Associated_Avatars with each Avatar's `reddit_username`, Reddit status badge (active/suspended/not_found/unknown), and comment karma
5. WHEN a Persona has zero Associated_Avatars, THE Persona_Card SHALL display a message: "No avatars assigned to this client"
6. THE Persona_Card SHALL display a Tooltip next to the Associated_Avatars section header explaining: "These are Reddit accounts belonging to the same client as this persona. Their Reddit status shows whether the account is active, suspended, or not found on Reddit."

### Requirement 5: Reddit Status Display with Tooltips

**User Story:** As a user, I want to see Reddit status information for avatars associated with each persona, with clear explanations of what each status means, so that I can understand the results without guessing.

#### Acceptance Criteria

1. THE Persona_Card SHALL display a Tooltip next to each Reddit status badge explaining the status meaning:
   - Active: "This Reddit account exists and is in good standing. It can post and comment normally."
   - Suspended: "This Reddit account has been suspended by Reddit. It cannot post or comment until the suspension is lifted."
   - Not Found: "This Reddit username was not found on Reddit. The account may have been deleted or the username may be incorrect."
   - Unknown: "The Reddit status has not been checked yet, or the last check encountered an error."
2. THE Persona_Card SHALL display a Tooltip next to the karma value explaining: "Comment karma is the total upvotes minus downvotes on all comments. Higher karma indicates a more established account."
3. WHEN an Avatar's Reddit status check is older than 24 hours, THE Persona_Card SHALL display a "stale" indicator with a Tooltip: "The last Reddit check was more than 24 hours ago. Click 'Check Status' on the Avatars page to refresh."

### Requirement 6: Reddit Status Check for Associated Avatars

**User Story:** As a user, I want to trigger Reddit status checks for all avatars associated with a persona's client directly from the Personas page, so that I can verify account health without switching pages.

#### Acceptance Criteria

1. THE Persona_Card SHALL include a "Check Avatars" button that triggers Reddit_Status_Check for all Associated_Avatars of that Persona's Client
2. WHEN the "Check Avatars" button is clicked, THE Personas_Page SHALL call the Reddit API for each Associated_Avatar with a 2-second delay between calls (when more than 10 avatars)
3. WHEN the Reddit_Status_Check completes, THE Persona_Card SHALL update the Associated_Avatars section via HTMX to reflect the new statuses
4. WHILE the Reddit_Status_Check is in progress, THE Persona_Card SHALL display a loading indicator (⏳) on the "Check Avatars" button
5. IF a Reddit_Status_Check fails for an individual Avatar, THEN THE Persona_Card SHALL display the error status for that Avatar and continue checking remaining Avatars
6. THE "Check Avatars" button SHALL include a Tooltip: "Checks the Reddit account status for all avatars belonging to this persona's client. Each account is checked via the Reddit API with a short delay to avoid rate limiting."

### Requirement 7: Bulk Reddit Status Check

**User Story:** As a user, I want to check Reddit status for all avatars associated with the currently visible personas at once, so that I can quickly verify account health across multiple personas.

#### Acceptance Criteria

1. THE Filter_Bar SHALL include a "Check visible" button that triggers Reddit_Status_Check for all Associated_Avatars of all currently visible Personas
2. WHEN the "Check visible" button is clicked, THE Personas_Page SHALL deduplicate Avatars (an Avatar may be associated with multiple Personas of the same Client) before checking
3. WHEN the bulk check completes, THE Personas_Page SHALL refresh the results partial via HTMX to reflect updated statuses
4. THE "Check visible" button SHALL include a Tooltip: "Checks Reddit status for all avatars associated with the personas currently shown. Avatars shared across personas are checked only once. This may take a while if many accounts need checking."

### Requirement 8: Personas Query Service

**User Story:** As a developer, I want a dedicated query service for the Personas page, so that the route handler stays thin and the query logic is testable and reusable.

#### Acceptance Criteria

1. THE Personas_Query_Service SHALL provide a `list_personas_page` function that accepts filter, sort, group, pagination parameters and a viewer_client_id for scoping
2. THE Personas_Query_Service SHALL batch-fetch related Clients and Associated_Avatars in no more than 3 database queries (Personas + Clients + Avatars) to avoid N+1 query problems
3. THE Personas_Query_Service SHALL return a data structure containing: paginated Persona items, total counts, filter state, grouped results (when grouping is active), and associated Avatar data per Persona
4. WHEN grouping by Client is active, THE Personas_Query_Service SHALL return all matching Personas without pagination, grouped by Client
5. WHEN flat list mode is active, THE Personas_Query_Service SHALL paginate results (24 per page in grid view, 50 per page in table view)

### Requirement 9: Persona Table View

**User Story:** As a user, I want to view Personas in a table format, so that I can see more personas at once with key data in columns.

#### Acceptance Criteria

1. WHEN table view is selected, THE Personas_Page SHALL render Personas as rows in a table with columns: Name, Client, Platform, Status (active/inactive), Associated Avatars count, Reddit Health summary, Created date
2. THE Persona_Row SHALL display the Reddit Health summary as a compact badge showing counts: "N active / M total avatars" with color coding (green if all active, orange if some suspended, red if majority suspended)
3. THE Persona_Row SHALL include a "Check Avatars" button identical in behavior to the Persona_Card button

### Requirement 10: Grouped View by Client

**User Story:** As a user, I want to see Personas grouped by Client, so that I can understand which voice profiles belong to each business.

#### Acceptance Criteria

1. WHEN group-by-client is active, THE Personas_Page SHALL display Personas in collapsible groups, one per Client
2. THE client group header SHALL display the Client name, brand name (if different), count of Personas in the group, and a summary of Associated_Avatars Reddit statuses across the group
3. THE client group header SHALL include a "Check All Client Avatars" button that triggers Reddit_Status_Check for all Avatars belonging to that Client
4. WHEN a Client has no Personas matching the current filters, THE Personas_Page SHALL omit that Client group from the results

### Requirement 11: Empty States

**User Story:** As a user, I want clear messaging when there are no personas to display, so that I understand why the page is empty and what to do next.

#### Acceptance Criteria

1. WHEN no Personas exist in the system (for the current user's scope), THE Personas_Page SHALL display an empty state with the message "No personas yet" and a suggestion to create personas via the admin panel
2. WHEN Personas exist but none match the current filters, THE Personas_Page SHALL display a "No matches" message with a "Clear filters" link

### Requirement 12: Stats Summary Bar

**User Story:** As a user, I want to see a summary of persona and avatar health statistics at the top of the page, so that I get an at-a-glance overview.

#### Acceptance Criteria

1. THE Personas_Page SHALL display a stats summary below the page title showing: total Personas count, active Personas count, inactive Personas count
2. THE Personas_Page SHALL display Associated_Avatars aggregate stats: total avatars across all visible Personas' Clients, count by Reddit status (active, suspended, not_found, stale)
3. THE stats summary SHALL include Tooltips explaining each metric:
   - Total Personas: "Total number of voice profiles in your scope"
   - Active/Inactive: "Whether the persona is enabled for content generation"
   - Avatar stats: "Reddit account health for avatars belonging to the same clients as your personas"
