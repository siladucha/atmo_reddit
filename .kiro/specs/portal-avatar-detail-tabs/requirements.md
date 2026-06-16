# Requirements Document

## Introduction

Reorganize the client portal avatar detail page (`/clients/{client_id}/avatars/{avatar_id}`) from a single long scrollable page into a tab-based navigation layout. The header and info block remain always visible at the top, while the remaining content sections are distributed across tabs for improved UX and faster navigation.

## Glossary

- **Tab_Navigation**: A horizontal row of clickable tab labels that switches visible content panels without a full page reload
- **Tab_Panel**: The content area displayed when a corresponding tab is active; only one panel is visible at a time
- **Avatar_Detail_Page**: The client portal page at `/clients/{client_id}/avatars/{avatar_id}` showing avatar personality, subreddits, and recent activity
- **Portal_Client**: A user with client_admin, client_manager, or client_viewer role accessing the client portal

## Requirements

### Requirement 1: Persistent Header Section

**User Story:** As a Portal_Client, I want the avatar header and info block to always be visible regardless of which tab is active, so that I always have context about which avatar I am viewing.

#### Acceptance Criteria

1. THE Avatar_Detail_Page SHALL display the avatar header (avatar initial, name, phase badge, karma total, frozen/inactive status indicator) above the Tab_Navigation in the DOM layout, remaining visible regardless of which tab is active
2. THE Avatar_Detail_Page SHALL display the info block (explanation text describing the avatar personality profile's purpose) between the header and the Tab_Navigation in the DOM layout, remaining visible regardless of which tab is active
3. THE Avatar_Detail_Page SHALL display the back link ("← Back to Avatars") above the header, linking to the client's avatar list page (`/clients/{client_id}/avatars`)
4. WHILE the page content exceeds the viewport height, THE Avatar_Detail_Page SHALL keep the header, info block, and back link in their static DOM positions (scrolling with the page) without sticky or fixed positioning

### Requirement 2: Tab Navigation Component

**User Story:** As a Portal_Client, I want a horizontal tab bar below the info block, so that I can quickly switch between different sections of avatar information.

#### Acceptance Criteria

1. THE Tab_Navigation SHALL display the following tabs in order: "Voice & Personality", "Territory", "Activity"
2. THE Tab_Navigation SHALL visually distinguish the currently active tab from inactive tabs such that the active tab has a different background color or a visible bottom border not present on inactive tabs
3. WHEN a Portal_Client clicks a tab label, THE Tab_Navigation SHALL switch the visible Tab_Panel to the selected tab content without a full page reload, hiding all other Tab_Panel sections
4. WHEN the Avatar_Detail_Page loads without a URL hash fragment matching a valid tab identifier, THE Tab_Navigation SHALL activate the "Voice & Personality" tab as the default
5. THE Tab_Navigation SHALL use appropriate ARIA roles (tablist, tab, tabpanel) and set `aria-selected="true"` on the active tab so that assistive technologies can identify the selected tab

### Requirement 3: Voice & Personality Tab Content

**User Story:** As a Portal_Client, I want voice profile and personality sections grouped in one tab, so that I can review the avatar's writing style in a single view.

#### Acceptance Criteria

1. WHEN the "Voice & Personality" tab is active, THE Tab_Panel SHALL display the following sections in order: Voice Profile, Tone Principles, Speech Patterns, Core Belief, Expertise Areas, Boundaries, Vocabulary
2. THE Tab_Panel SHALL render Voice Profile as a full-width card spanning both grid columns, and render Tone Principles, Speech Patterns, Core Belief, Expertise Areas, Boundaries, and Vocabulary as half-width cards in a two-column grid, each displaying its content in a pre-formatted text block with word-wrap enabled
3. IF a section's corresponding data field is null, an empty string, or contains only whitespace characters, THEN THE Tab_Panel SHALL hide that section entirely from the tab content
4. IF all seven sections have no data, THEN THE Tab_Panel SHALL display an empty-state message indicating that no voice or personality information has been configured for this avatar

### Requirement 4: Territory Tab Content

**User Story:** As a Portal_Client, I want to see the avatar's subreddit assignments in a dedicated tab, so that I can quickly review where the avatar operates.

#### Acceptance Criteria

1. WHEN the "Territory" tab is active, THE Tab_Panel SHALL display the Subreddit Territory section with business subreddits grouped separately from hobby subreddits, each group preceded by a category label ("Business" and "Hobby")
2. THE Tab_Panel SHALL render each subreddit as a pill-styled link (opening reddit.com/r/{name} in a new browser tab) using blue background for business subreddits and purple background for hobby subreddits, consistent with existing pill styling
3. WHEN no subreddits are assigned (both business_subreddits and hobby_subreddits arrays are empty), THE Tab_Panel SHALL display an empty state message indicating no subreddits are configured for this avatar

### Requirement 5: Activity Tab Content

**User Story:** As a Portal_Client, I want to see the avatar's recent comment activity in a dedicated tab, so that I can check engagement history without scrolling through personality content.

#### Acceptance Criteria

1. WHEN the "Activity" tab is active, THE Tab_Panel SHALL display the Recent Activity section listing up to 20 comment drafts created within the last 30 days, sorted by creation date descending (newest first)
2. THE Tab_Panel SHALL display each activity item with: subreddit name as a link to the Reddit subreddit, thread title truncated to 60 characters, comment text preview truncated to 120 characters, status badge (pending, approved, rejected, or posted), reddit score (displayed only when status is "posted" and a score value exists), and a relative timestamp indicating when the draft was created
3. WHEN no activity exists for the past 30 days, THE Tab_Panel SHALL display an empty state message indicating no recent activity
4. IF a comment draft is associated with a hobby post rather than a professional thread, THEN THE Tab_Panel SHALL resolve the subreddit name and thread title from the hobby post record

### Requirement 6: Client-Side Tab Switching

**User Story:** As a Portal_Client, I want instant tab switching without network requests, so that navigation between sections feels responsive.

#### Acceptance Criteria

1. THE Avatar_Detail_Page SHALL implement tab switching using vanilla JavaScript (show/hide panels via CSS class toggling) without HTMX requests or full page reloads
2. WHEN a tab is clicked, THE Avatar_Detail_Page SHALL toggle the active CSS class on all tab labels and show/hide the corresponding Tab_Panel within 16ms (single animation frame)
3. THE Avatar_Detail_Page SHALL render all Tab_Panel content into the DOM on initial page load so that switching requires no deferred fetching
4. WHEN the page loads with a tab identifier in the URL fragment (e.g., #voice), THE Avatar_Detail_Page SHALL activate the corresponding tab instead of the default first tab
5. IF a tab identifier in the URL fragment does not match any existing Tab_Panel, THEN THE Avatar_Detail_Page SHALL activate the default first tab
6. WHEN a tab is activated, THE Avatar_Detail_Page SHALL update the URL fragment to reflect the active tab name without triggering a page reload

### Requirement 7: URL Fragment Persistence

**User Story:** As a Portal_Client, I want the active tab reflected in the URL, so that I can share a link to a specific tab or return to it after a page refresh.

#### Acceptance Criteria

1. WHEN a Portal_Client switches tabs, THE Avatar_Detail_Page SHALL update the URL hash fragment to the active tab's identifier using the exact mapping: "Voice & Personality" -> `#voice`, "Territory" -> `#territory`, "Activity" -> `#activity`
2. WHEN a Portal_Client switches tabs, THE Avatar_Detail_Page SHALL update the URL hash using `history.replaceState` so that tab switches do not create new browser history entries
3. WHEN the page loads with a hash fragment matching a valid tab identifier (`#voice`, `#territory`, or `#activity`), THE Avatar_Detail_Page SHALL activate the corresponding tab instead of the default
4. WHEN the browser `hashchange` event fires (e.g., via back/forward navigation from an external page), THE Avatar_Detail_Page SHALL activate the tab matching the new hash fragment
5. IF the URL contains a hash fragment that does not match any valid tab identifier or contains no hash fragment, THEN THE Avatar_Detail_Page SHALL activate the "Voice & Personality" tab and replace the URL hash with `#voice`

### Requirement 8: Responsive Tab Layout

**User Story:** As a Portal_Client, I want the tabs to work well on different screen sizes, so that I can use the page on both desktop and tablet.

#### Acceptance Criteria

1. WHILE the viewport width is greater than 640px, THE Tab_Navigation SHALL display all tab labels in a single horizontal row without scrolling or wrapping
2. WHILE the viewport width is 640px or less, THE Tab_Navigation SHALL display tab labels in a horizontally scrollable container that does not wrap to multiple lines, and SHALL display a visible scroll indicator (fade or shadow) on the edge where additional tabs are available off-screen
3. THE Tab_Navigation SHALL display each tab label as a touch target with a minimum height of 44px and minimum width of 44px on all viewport sizes
4. WHILE any tab is selected, THE Tab_Navigation SHALL display the active tab indicator (border and text color differentiation) identically on both desktop and tablet viewport sizes
5. THE Tab_Panel content SHALL preserve its responsive column layout within each tab, rendering content in a multi-column grid on viewports wider than 640px and a single-column stack on viewports of 640px or less
