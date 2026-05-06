# Requirements Document

## Introduction

This feature adds inline informational tooltip icons (ℹ️) throughout the Reddit Marketing SaaS admin panel. Each tooltip provides contextual help explaining what a UI element is and how it works. The goal is to reduce the learning curve for new operators and provide quick reference for experienced users without leaving the current page. This complements the existing `page_guide.html` collapsible block by offering element-level micro-help.

## Glossary

- **Tooltip_Component**: A reusable Jinja2 partial that renders an info icon with an associated popup text bubble
- **Info_Icon**: A small circular icon (ℹ️ style) rendered inline next to a UI element, indicating that contextual help is available
- **Tooltip_Popup**: A floating text container that appears when the user interacts with the Info_Icon, displaying explanatory text
- **Admin_Panel**: The dark-themed administrative interface of the Reddit Marketing SaaS platform (all `/admin/*` pages)
- **HTMX_Content**: HTML fragments loaded dynamically via HTMX into the page after initial render
- **Trigger_Interaction**: The user action that causes a Tooltip_Popup to appear — hover on desktop, tap on mobile

## Requirements

### Requirement 1: Reusable Tooltip Partial

**User Story:** As a developer, I want a single reusable Jinja2 partial for info tooltips, so that I can add contextual help to any UI element with minimal code duplication.

#### Acceptance Criteria

1. THE Tooltip_Component SHALL render as a Jinja2 include partial located at `templates/partials/info_tooltip.html`
2. THE Tooltip_Component SHALL accept a `tooltip_text` parameter containing the help message to display
3. THE Tooltip_Component SHALL accept an optional `position` parameter to control Tooltip_Popup placement with a default value of "top"
4. THE Tooltip_Component SHALL render an Info_Icon using an inline SVG circle-i icon consistent with the existing page_guide.html icon style
5. THE Tooltip_Component SHALL be usable via a single Jinja2 include statement with set variables (e.g., `{% set tooltip_text = "..." %}{% include "partials/info_tooltip.html" %}`)

### Requirement 2: Tooltip Visual Design

**User Story:** As an admin user, I want tooltips to be visually consistent with the dark theme, so that they feel like a native part of the interface.

#### Acceptance Criteria

1. THE Info_Icon SHALL render as a 16×16 pixel SVG with `text-gray-500` color in its default state
2. WHEN the user hovers over the Info_Icon, THE Info_Icon SHALL change color to `text-indigo-400`
3. THE Tooltip_Popup SHALL use a dark background (`bg-slate-800`), light text (`text-gray-200`), a subtle border (`border-slate-600`), and rounded corners (`rounded-lg`)
4. THE Tooltip_Popup SHALL have a maximum width of 280 pixels to prevent overly wide popups
5. THE Tooltip_Popup SHALL display a small directional arrow (caret) pointing toward the Info_Icon
6. THE Tooltip_Popup SHALL use `text-sm` (14px) font size for readability
7. THE Tooltip_Popup SHALL appear with a fade-in transition of 150ms duration

### Requirement 3: Desktop Interaction

**User Story:** As a desktop user, I want tooltips to appear on hover, so that I can quickly glance at help text without clicking.

#### Acceptance Criteria

1. WHEN the user hovers over the Info_Icon on a desktop device, THE Tooltip_Component SHALL display the Tooltip_Popup after a 200ms delay
2. WHEN the user moves the cursor away from both the Info_Icon and the Tooltip_Popup, THE Tooltip_Component SHALL hide the Tooltip_Popup after a 150ms delay
3. WHILE the cursor is over the Tooltip_Popup, THE Tooltip_Component SHALL keep the Tooltip_Popup visible so the user can read longer text
4. THE Tooltip_Component SHALL implement hover behavior using pure CSS (no JavaScript required for basic show/hide)

### Requirement 4: Mobile Interaction

**User Story:** As a mobile user, I want tooltips to appear on tap and dismiss easily, so that I can access help on touch devices.

#### Acceptance Criteria

1. WHEN the user taps the Info_Icon on a touch device, THE Tooltip_Component SHALL toggle the Tooltip_Popup visibility
2. WHEN the user taps anywhere outside the Tooltip_Popup, THE Tooltip_Component SHALL hide the Tooltip_Popup
3. WHEN the user taps a different Info_Icon while a Tooltip_Popup is already visible, THE Tooltip_Component SHALL close the previously open Tooltip_Popup and open the new one
4. THE Tooltip_Component SHALL use a JavaScript event listener for touch interaction that does not conflict with HTMX event handling

### Requirement 5: HTMX Compatibility

**User Story:** As a developer, I want tooltips to work on dynamically loaded content, so that HTMX-swapped fragments also have working tooltips.

#### Acceptance Criteria

1. THE Tooltip_Component SHALL function correctly on content loaded via HTMX swaps without requiring manual re-initialization
2. THE Tooltip_Component SHALL use event delegation on the document body for mobile tap-to-dismiss behavior
3. IF a Tooltip_Popup is visible inside a container that gets replaced by an HTMX swap, THEN THE Tooltip_Component SHALL not leave orphaned popup elements in the DOM

### Requirement 6: Accessibility

**User Story:** As a user relying on assistive technology, I want tooltips to be accessible, so that I can understand UI elements using a screen reader or keyboard.

#### Acceptance Criteria

1. THE Info_Icon SHALL include an `aria-label` attribute with the value "More information"
2. THE Info_Icon SHALL be focusable via keyboard using `tabindex="0"`
3. WHEN the Info_Icon receives keyboard focus, THE Tooltip_Component SHALL display the Tooltip_Popup
4. WHEN the Info_Icon loses keyboard focus, THE Tooltip_Component SHALL hide the Tooltip_Popup
5. THE Tooltip_Popup SHALL have `role="tooltip"` and be linked to the Info_Icon via `aria-describedby`
6. WHEN the user presses the Escape key while a Tooltip_Popup is visible, THE Tooltip_Component SHALL hide the Tooltip_Popup

### Requirement 7: Positioning and Overflow

**User Story:** As a user, I want tooltips to always be fully visible on screen, so that text is never cut off by page edges.

#### Acceptance Criteria

1. THE Tooltip_Component SHALL support four position values: "top", "bottom", "left", "right"
2. THE Tooltip_Popup SHALL use CSS absolute positioning relative to the Info_Icon wrapper
3. IF the Tooltip_Popup would overflow the viewport boundary, THEN THE Tooltip_Component SHALL remain visible by using a `z-index` of at least 50 to appear above other UI elements
4. THE Tooltip_Popup SHALL not cause horizontal scrollbars on the page

### Requirement 8: Dashboard Page Tooltips

**User Story:** As an admin user viewing the Dashboard, I want info icons next to key metrics and panels, so that I understand what each number and section represents.

#### Acceptance Criteria

1. THE Admin_Panel SHALL display an Info_Icon next to the "Pending Reviews" metric card label explaining that it shows the count of AI-generated comment drafts awaiting human approval
2. THE Admin_Panel SHALL display an Info_Icon next to the "Active Clients" metric card label explaining that it shows the number of clients with `is_active` enabled
3. THE Admin_Panel SHALL display an Info_Icon next to the "Active Avatars" metric card label explaining that it shows the total Reddit accounts currently assigned to active clients
4. THE Admin_Panel SHALL display an Info_Icon next to the "Next Scheduled Run" metric card label explaining that it shows the countdown to the next Celery pipeline execution
5. THE Admin_Panel SHALL display an Info_Icon next to the "Run All" controls section explaining that these buttons trigger pipeline stages for every active client simultaneously
6. THE Admin_Panel SHALL display an Info_Icon next to the "Scrape Freshness" panel header explaining that it shows how recently each subreddit was scraped
7. THE Admin_Panel SHALL display an Info_Icon next to the "Avatar Health" panel header explaining that it shows karma levels and account status for all avatars
8. THE Admin_Panel SHALL display an Info_Icon next to the "Schedule" panel header explaining that it shows upcoming scheduled pipeline runs

### Requirement 9: Clients Page Tooltips

**User Story:** As an admin user viewing the Clients page, I want info icons next to table headers and actions, so that I understand the data model.

#### Acceptance Criteria

1. THE Admin_Panel SHALL display an Info_Icon next to the "Client Name" column header explaining that it is the internal identifier for the business using the platform
2. THE Admin_Panel SHALL display an Info_Icon next to the "Brand" column header explaining that it is the public-facing brand name used in content generation context
3. THE Admin_Panel SHALL display an Info_Icon next to the "Active" column header explaining that inactive clients are excluded from all pipeline runs
4. THE Admin_Panel SHALL display an Info_Icon next to the "Subreddits" column header explaining that it shows the count of monitored Reddit communities for this client
5. THE Admin_Panel SHALL display an Info_Icon next to the "Avatars" column header explaining that it shows the count of Reddit accounts assigned to post on behalf of this client
6. THE Admin_Panel SHALL display an Info_Icon next to the "+ New Client" button explaining that it opens a blank client creation form
7. THE Admin_Panel SHALL display an Info_Icon next to the "Onboard" action link explaining that it launches the 7-step onboarding wizard for the client

### Requirement 10: Review Queue Page Tooltips

**User Story:** As an admin user reviewing comment drafts, I want info icons explaining the review workflow and scoring, so that I can make informed approval decisions.

#### Acceptance Criteria

1. THE Admin_Panel SHALL display an Info_Icon next to the "Status" filter bar explaining the draft lifecycle: pending → approved → posted, or pending → rejected
2. THE Admin_Panel SHALL display an Info_Icon next to the "score" badge on comment cards explaining that it is the composite relevance score (higher means more strategic value)
3. THE Admin_Panel SHALL display an Info_Icon next to the "engagement mode" label explaining the difference between engagement modes (e.g., helpful, authority, casual)
4. THE Admin_Panel SHALL display an Info_Icon next to the "Approve" button explaining that approval marks the draft as ready for manual posting to Reddit
5. THE Admin_Panel SHALL display an Info_Icon next to the "Reject" button explaining that rejection removes the draft from the posting queue permanently

### Requirement 11: System Settings Page Tooltips

**User Story:** As an admin user configuring system settings, I want info icons next to each setting, so that I understand what each configuration key controls.

#### Acceptance Criteria

1. THE Admin_Panel SHALL display an Info_Icon next to each setting key name explaining what the setting controls
2. THE Admin_Panel SHALL display an Info_Icon next to the "secret" badge explaining that secret values are masked and require explicit reveal
3. THE Admin_Panel SHALL display an Info_Icon next to the "read-only" badge explaining that read-only settings are managed by the system and cannot be edited manually
4. THE Admin_Panel SHALL display an Info_Icon next to "Test Connection" buttons explaining that they verify connectivity to the configured external service

### Requirement 12: Global Tooltip Script Inclusion

**User Story:** As a developer, I want tooltip JavaScript loaded once in the base template, so that all pages automatically support tooltip interactions.

#### Acceptance Criteria

1. THE Admin_Panel SHALL include the tooltip JavaScript in `admin_base.html` so it is available on every admin page
2. THE Tooltip_Component SHALL require no per-page JavaScript initialization
3. THE Tooltip_Component SHALL use less than 2KB of combined CSS and JavaScript (unminified) to minimize page weight impact
