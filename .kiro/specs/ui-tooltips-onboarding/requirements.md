# Requirements Document

## Introduction

This feature adds guided onboarding flows and contextual walkthroughs to all UI screens of the Reddit Marketing SaaS platform. The goal is to prevent users from feeling overwhelmed when they first encounter a screen by providing step-by-step guided tours that highlight key elements, explain workflows, and progressively reveal complexity. This complements the existing info tooltips (element-level help) and the static guide page by providing interactive, screen-specific onboarding that adapts to the user's experience level.

## Glossary

- **Onboarding_Engine**: The client-side JavaScript module that manages tour state, step rendering, navigation, and progress persistence
- **Tour**: A sequence of ordered steps that guides the user through a specific screen's functionality, highlighting elements one at a time
- **Tour_Step**: A single step within a Tour, consisting of a highlighted target element, a popover with explanatory text, and navigation controls
- **Tour_Popover**: A floating card displayed next to the highlighted element containing a title, description, step counter, and navigation buttons
- **Highlight_Overlay**: A semi-transparent dark overlay that dims the entire page except the currently highlighted element, drawing focus to it
- **Tour_Registry**: A server-side data structure (Jinja2 context or JSON) that defines all available tours, their steps, and target selectors for each page
- **Progress_Store**: A client-side persistence layer (localStorage) that tracks which tours a user has completed or dismissed
- **Tour_Trigger**: A UI element (button or automatic prompt) that initiates a Tour on a given screen
- **Welcome_Modal**: A one-time modal shown to new users on their first login, offering to start the platform tour
- **Role_Context**: The current user's RBAC role, used to determine which tours and steps are relevant
- **Admin_Panel**: The dark-themed administrative interface (all `/admin/*` pages using `admin_base.html`)
- **Client_Panel**: The light-themed user-facing interface (dashboard, review, avatars, settings using `base.html`)

## Requirements

### Requirement 1: Onboarding Engine Core

**User Story:** As a developer, I want a lightweight onboarding engine built with vanilla JavaScript, so that guided tours work across all pages without adding framework dependencies.

#### Acceptance Criteria

1. THE Onboarding_Engine SHALL be implemented as a single JavaScript file (`static/js/onboarding.js`) with no external dependencies beyond what the platform already uses
2. THE Onboarding_Engine SHALL expose a global `RampTour` object with methods: `start(tourId)`, `next()`, `prev()`, `skip()`, `complete()`
3. THE Onboarding_Engine SHALL render Tour_Steps by positioning a Tour_Popover adjacent to the target element and applying a Highlight_Overlay to the rest of the page
4. THE Onboarding_Engine SHALL support step targets defined by CSS selectors (id, class, or data-attribute)
5. IF a target element for a Tour_Step does not exist in the DOM, THEN THE Onboarding_Engine SHALL skip that step and proceed to the next available step
6. THE Onboarding_Engine SHALL handle HTMX-swapped content by re-evaluating target selectors when a step becomes active
7. THE Onboarding_Engine SHALL be smaller than 8KB unminified to minimize page weight impact

### Requirement 2: Tour Step Rendering

**User Story:** As a user, I want each tour step to clearly highlight the relevant UI element with an explanatory card, so that I understand what each part of the screen does.

#### Acceptance Criteria

1. WHEN a Tour_Step is active, THE Onboarding_Engine SHALL display a Highlight_Overlay that dims the page with a semi-transparent background (`rgba(0,0,0,0.5)`) while keeping the target element fully visible and elevated above the overlay
2. WHEN a Tour_Step is active, THE Onboarding_Engine SHALL display a Tour_Popover containing: a title (bold, max 60 characters), a description (max 200 characters), a step counter ("Step 2 of 7"), and navigation buttons
3. THE Tour_Popover SHALL position itself automatically relative to the target element, choosing from top, bottom, left, or right based on available viewport space
4. THE Tour_Popover SHALL use styling consistent with the current theme — dark card (`bg-slate-800 border-slate-600 text-gray-200`) on Admin_Panel pages, light card (`bg-white border-gray-200 text-gray-800`) on Client_Panel pages
5. THE Highlight_Overlay SHALL smoothly scroll the target element into view if it is not currently visible in the viewport
6. THE Tour_Popover SHALL include a "Skip tour" link and a close (×) button to allow immediate dismissal at any step

### Requirement 3: Tour Navigation

**User Story:** As a user, I want to navigate forward, backward, or skip the tour at any point, so that I control the pace of learning.

#### Acceptance Criteria

1. THE Tour_Popover SHALL display a "Next" button that advances to the next Tour_Step
2. THE Tour_Popover SHALL display a "Back" button on all steps except the first step
3. WHEN the user reaches the final Tour_Step, THE Tour_Popover SHALL display a "Done" button instead of "Next"
4. WHEN the user clicks "Done", THE Onboarding_Engine SHALL mark the Tour as completed in the Progress_Store
5. WHEN the user clicks "Skip tour" or the close button, THE Onboarding_Engine SHALL mark the Tour as dismissed in the Progress_Store and remove the overlay
6. WHEN the user presses the Escape key during an active Tour, THE Onboarding_Engine SHALL dismiss the Tour
7. WHEN the user clicks the Highlight_Overlay (outside the target element and popover), THE Onboarding_Engine SHALL dismiss the Tour

### Requirement 4: Progress Persistence

**User Story:** As a user, I want the system to remember which tours I have completed, so that I am not shown the same onboarding repeatedly.

#### Acceptance Criteria

1. THE Progress_Store SHALL persist tour completion and dismissal state in the browser's localStorage under the key `ramp_onboarding_{user_id}`
2. WHEN a user has completed or dismissed a Tour, THE Onboarding_Engine SHALL not auto-trigger that Tour again on subsequent page visits
3. THE Progress_Store SHALL store a JSON object mapping tour IDs to their status (`completed`, `dismissed`) and a timestamp
4. WHEN localStorage is unavailable or cleared, THE Onboarding_Engine SHALL treat all tours as not yet seen and allow re-triggering

### Requirement 5: Tour Trigger Mechanisms

**User Story:** As a user, I want tours to start automatically on my first visit to a screen and be re-accessible via a help button, so that I get guidance when needed without being forced into it repeatedly.

#### Acceptance Criteria

1. WHEN a user visits a page for the first time (no Progress_Store entry for that page's Tour), THE Onboarding_Engine SHALL automatically start the Tour after a 1-second delay
2. THE Client_Panel and Admin_Panel SHALL display a persistent "?" help button in the bottom-right corner of every page that has an associated Tour
3. WHEN the user clicks the "?" help button, THE Onboarding_Engine SHALL start the page's Tour regardless of previous completion status
4. THE "?" help button SHALL use a fixed position, circular design (40×40px), and match the current theme colors
5. WHEN a Tour is currently active, THE "?" help button SHALL be hidden to avoid visual conflict

### Requirement 6: Welcome Modal for New Users

**User Story:** As a new user logging in for the first time, I want a welcome modal that introduces the platform and offers to start a guided tour, so that I have a clear starting point.

#### Acceptance Criteria

1. WHEN a user logs in and has no entries in the Progress_Store, THE Client_Panel SHALL display a Welcome_Modal on the dashboard page
2. THE Welcome_Modal SHALL contain: a welcome heading, a brief platform description (2-3 sentences), a "Start Tour" button, and a "Skip, I'll explore on my own" link
3. WHEN the user clicks "Start Tour", THE Onboarding_Engine SHALL close the Welcome_Modal and begin the Dashboard Tour
4. WHEN the user clicks "Skip", THE Onboarding_Engine SHALL close the Welcome_Modal and record `welcome_dismissed` in the Progress_Store
5. THE Welcome_Modal SHALL use a centered overlay design with a max-width of 480px and theme-appropriate styling

### Requirement 7: Role-Based Tour Content

**User Story:** As a platform with multiple user roles, I want tours to show only relevant steps for each role, so that users are not confused by features they cannot access.

#### Acceptance Criteria

1. THE Tour_Registry SHALL support a `roles` field on each Tour_Step specifying which RBAC roles should see that step
2. WHEN a Tour_Step has a `roles` field, THE Onboarding_Engine SHALL skip that step for users whose role is not in the list
3. THE Onboarding_Engine SHALL receive the current user's role via a data attribute on the body element (`data-user-role`)
4. WHERE a Tour has no role-restricted steps, THE Onboarding_Engine SHALL show all steps to all users

### Requirement 8: Dashboard Tour (Client Panel)

**User Story:** As a client_admin or client_manager user, I want a guided tour of the dashboard, so that I understand the key metrics and actions available to me.

#### Acceptance Criteria

1. THE Dashboard Tour SHALL highlight the stats cards section explaining that these show the current state of the user's Reddit marketing operations
2. THE Dashboard Tour SHALL highlight the clients list explaining that each client represents a brand being marketed on Reddit
3. THE Dashboard Tour SHALL highlight the "Pending Review" metric explaining that these are AI-generated comments waiting for human approval
4. THE Dashboard Tour SHALL highlight the "+ New Client" button explaining how to add a new brand to manage
5. THE Dashboard Tour SHALL highlight the quick links section explaining shortcuts to review queue and avatar management
6. THE Dashboard Tour SHALL highlight the "How does this work?" guide link explaining that a full step-by-step guide is available

### Requirement 9: Review Queue Tour (Client Panel)

**User Story:** As a user responsible for reviewing comments, I want a guided tour of the review queue, so that I understand the approval workflow and available actions.

#### Acceptance Criteria

1. THE Review_Queue Tour SHALL highlight the status filter bar explaining how to filter drafts by status (pending, approved, rejected, posted)
2. THE Review_Queue Tour SHALL highlight a comment card explaining the anatomy of a draft: thread title, subreddit, avatar, score, and generated text
3. THE Review_Queue Tour SHALL highlight the approve button explaining that approval marks the comment as ready for posting
4. THE Review_Queue Tour SHALL highlight the reject button explaining that rejection permanently removes the draft from the queue
5. THE Review_Queue Tour SHALL highlight the edit area explaining that users can modify the AI-generated text before approving
6. THE Review_Queue Tour SHALL highlight the "Open on Reddit" link explaining that users can view the original thread for context

### Requirement 10: Admin Dashboard Tour

**User Story:** As an owner or partner user, I want a guided tour of the admin dashboard, so that I understand the system health panels and pipeline controls.

#### Acceptance Criteria

1. THE Admin_Dashboard Tour SHALL highlight the metric cards row explaining the key system indicators (pending reviews, active clients, active avatars, next run)
2. THE Admin_Dashboard Tour SHALL highlight the "Run All" controls explaining that these trigger pipeline stages across all clients simultaneously
3. THE Admin_Dashboard Tour SHALL highlight the System Topology panel explaining that it shows real-time health of all pipeline nodes
4. THE Admin_Dashboard Tour SHALL highlight the Activity Feed explaining that it shows recent pipeline events with timestamps
5. THE Admin_Dashboard Tour SHALL highlight the Scrape Freshness panel explaining how to identify stale subreddits
6. THE Admin_Dashboard Tour SHALL highlight the Schedule panel explaining the automated pipeline run schedule

### Requirement 11: Client Detail Tour (Admin Panel)

**User Story:** As an admin user viewing a client's detail page, I want a guided tour explaining the client configuration and pipeline controls, so that I can manage clients effectively.

#### Acceptance Criteria

1. THE Client_Detail Tour SHALL highlight the client info section explaining the client name, brand, and worldview fields
2. THE Client_Detail Tour SHALL highlight the subreddits section explaining how to add and categorize subreddits (professional vs hobby)
3. THE Client_Detail Tour SHALL highlight the keywords section explaining how keywords drive AI scoring relevance
4. THE Client_Detail Tour SHALL highlight the avatars assignment section explaining how avatars are linked to clients
5. THE Client_Detail Tour SHALL highlight the pipeline buttons explaining the scrape → score → generate workflow
6. THE Client_Detail Tour SHALL highlight the transparency link explaining where to find detailed pipeline activity logs

### Requirement 12: Avatar Detail Tour (Admin Panel)

**User Story:** As an admin user viewing an avatar's detail page, I want a guided tour explaining warming phases, health status, and pipeline stats, so that I understand the avatar lifecycle.

#### Acceptance Criteria

1. THE Avatar_Detail Tour SHALL highlight the status badges explaining active/inactive and Reddit account status
2. THE Avatar_Detail Tour SHALL highlight the warming phase section explaining the 3-phase progression system (credibility → seeding → brand integration)
3. THE Avatar_Detail Tour SHALL highlight the phase progress bars explaining what metrics drive promotion
4. THE Avatar_Detail Tour SHALL highlight the pipeline stats section explaining hobby vs professional comment counts
5. THE Avatar_Detail Tour SHALL highlight the health/presence tabs explaining how to monitor avatar reputation
6. THE Avatar_Detail Tour SHALL highlight the phase override section explaining that admins can manually adjust phases

### Requirement 13: Onboarding Wizard Context Tour (Admin Panel)

**User Story:** As an admin user starting the 7-step onboarding wizard for a new client, I want a brief introductory tour explaining the wizard flow, so that I know what to expect before filling in forms.

#### Acceptance Criteria

1. WHEN the user opens the onboarding wizard (Step 1) for the first time, THE Onboarding_Engine SHALL offer a brief 3-step introductory tour
2. THE Wizard_Intro Tour SHALL explain that the wizard has 7 steps: client profile → subreddits → keywords → avatars → personas → pipeline config → test run
3. THE Wizard_Intro Tour SHALL highlight the progress indicator explaining how to track completion
4. THE Wizard_Intro Tour SHALL explain that all steps can be revisited and edited after initial completion

### Requirement 14: Theme Compatibility

**User Story:** As a developer, I want the onboarding engine to automatically adapt its styling to the current page theme, so that tours look native on both light and dark themed pages.

#### Acceptance Criteria

1. THE Onboarding_Engine SHALL detect the current theme by checking for the presence of `admin_base.html` layout indicators (a `data-theme="dark"` attribute on the body element)
2. WHILE on a dark-themed page, THE Tour_Popover SHALL use dark styling: `bg-slate-800`, `text-gray-200`, `border-slate-600`, buttons with `bg-indigo-600`
3. WHILE on a light-themed page, THE Tour_Popover SHALL use light styling: `bg-white`, `text-gray-800`, `border-gray-200`, buttons with `bg-blue-600`
4. THE Highlight_Overlay SHALL use `rgba(0,0,0,0.5)` on dark themes and `rgba(0,0,0,0.4)` on light themes

### Requirement 15: Accessibility

**User Story:** As a user relying on assistive technology or keyboard navigation, I want onboarding tours to be fully accessible, so that I can follow the guided experience without a mouse.

#### Acceptance Criteria

1. WHEN a Tour is active, THE Tour_Popover SHALL receive keyboard focus and trap focus within the popover (Next, Back, Skip, Close buttons)
2. THE Tour_Popover SHALL have `role="dialog"` and `aria-modal="true"` attributes
3. THE Tour_Popover SHALL have an `aria-label` describing the current step (e.g., "Tour step 2 of 7: Review Queue")
4. WHEN the user presses Tab, THE Onboarding_Engine SHALL cycle focus between the navigation buttons within the Tour_Popover
5. WHEN the user presses Escape, THE Onboarding_Engine SHALL dismiss the Tour and return focus to the element that was focused before the Tour started
6. THE Highlight_Overlay SHALL have `aria-hidden="true"` to prevent screen readers from reading background content during the tour

### Requirement 16: Tour Definition Format

**User Story:** As a developer, I want tours defined in a simple JSON-like structure within Jinja2 templates, so that adding new tours or modifying steps requires no JavaScript changes.

#### Acceptance Criteria

1. THE Tour_Registry SHALL be defined as a JSON object embedded in a `<script type="application/json" id="page-tour-data">` tag within each page template
2. WHEN a page template includes tour data, THE Onboarding_Engine SHALL parse it on page load and register the tour
3. THE Tour definition format SHALL include: `tourId` (string), `title` (string), `steps` (array of step objects)
4. Each Tour_Step object SHALL include: `target` (CSS selector), `title` (string), `description` (string), and optionally `position` (top/bottom/left/right) and `roles` (array of role strings)
5. THE Onboarding_Engine SHALL validate tour data on parse and log a console warning for malformed definitions without crashing

### Requirement 17: Re-trigger and Reset

**User Story:** As a user, I want to be able to replay any tour or reset all onboarding progress, so that I can refresh my memory or show the platform to a colleague.

#### Acceptance Criteria

1. THE Client_Panel settings page SHALL include a "Reset Onboarding" button that clears all Progress_Store data for the current user
2. WHEN the user clicks "Reset Onboarding", THE Onboarding_Engine SHALL clear localStorage entries and confirm the reset with a brief notification
3. THE "?" help button on each page SHALL allow replaying the tour regardless of completion status
4. THE Admin_Panel settings page SHALL include a "Reset Onboarding" option in the user preferences section

