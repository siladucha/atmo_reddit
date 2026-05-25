# Requirements Document

## Introduction

Transform the existing Client Hub (`/clients/{client_id}`) from a light-themed tab-based admin tool into a polished, dark-themed client-facing portal. The redesign follows the RAMP UX Developer Spec v3, implementing a sidebar navigation layout, design token system, redesigned review queue with optimistic updates, and a streamlined home screen. The backend is already built — this is primarily a frontend/template and API response layer change. Client users see the new portal; admin users continue using the existing admin panel unchanged.

The implementation is phased: P0 (dark theme, sidebar, review queue, home screen, design tokens, safety blocks, API allowlist), P1 (onboarding wizard, avatars screen, momentum feed, system banners, filter bar, settings, empty states), P2 (insights, batch approve, mobile layout, upsell — deferred to v2).

## Glossary

- **Client_Portal**: The client-facing web application at `/clients/{client_id}`, accessible to users with roles client_admin, client_manager, or client_viewer
- **Design_Token_System**: CSS custom properties on `:root` defining colors, typography, spacing, and interaction standards per the UX spec
- **Sidebar_Navigation**: Fixed 240px left sidebar replacing the current horizontal tab bar, containing nav items with icon + label + optional badge
- **Review_Queue**: The screen where clients approve, edit, skip, or regenerate AI-generated comment drafts before posting
- **Home_Screen**: The overview/dashboard screen showing headline metrics, pending approvals CTA, and momentum events
- **Optimistic_Update**: UI pattern where the interface updates immediately on user action, reverting only if the server returns an error
- **Safety_Block**: A hard block preventing approval of a draft that violates phase-based brand mention rules
- **API_Allowlist**: A server-side response schema filter that explicitly includes only permitted fields in client-facing API responses, never exposing sensitive data
- **Toast_Notification**: A transient message appearing bottom-right, auto-dismissing after 4 seconds, stacked max 3
- **Skeleton_Loading**: A placeholder UI with pulsing opacity (0.4–0.7, 1.2s interval) shown while content loads, replacing spinners
- **Phase_Badge**: A colored pill indicating an avatar's warming phase (Phase 1 grey, Phase 2 orange, Phase 3 green)
- **Momentum_Event**: A notable system event (breakout comment, shadowban alert) displayed in the home screen feed
- **System_Banner**: A full-width notification bar at the top of the content area for critical alerts (shadowban, inactivity)
- **Filter_Bar**: An inline chip row on the review queue for filtering drafts by avatar and subreddit
- **Empty_State**: A branded placeholder shown when a screen has no data, with contextual copy and guidance
- **Onboarding_Wizard**: A simplified multi-step form for new client setup (company profile, ICP, keywords, subreddits, brand guardrails)
- **Brand_Guardrail**: Content rules that prevent brand mentions in Phase 1/2 avatars and block competitor attack language

## Requirements

### Requirement 1: Design Token System

**User Story:** As a developer, I want all UI values defined as CSS custom properties, so that the dark theme is consistent and maintainable without hardcoded hex values in templates.

#### Acceptance Criteria

1. THE Design_Token_System SHALL define CSS custom properties on `:root` for all color tokens specified in the UX spec (--color-bg: #0D0D1A, --color-surface: #1A1A2E, --color-surface-alt: #1E1E32, --color-border: #2E2E4A, --color-orange: #FF6B35, --color-orange-light: #FF8C5A, --color-white: #FFFFFF, --color-muted: #AAAAAA, --color-red: #E53935, --color-amber: #F59E0B, --color-green: #22C55E, --color-phase1: #6B7280, --color-phase2: #FF6B35, --color-phase3: #22C55E)
2. THE Design_Token_System SHALL define CSS custom properties for typography scale (--text-display: 48px/700, --text-h1: 28px/700, --text-h2: 20px/600, --text-h3: 16px/600, --text-body: 14px/400, --text-small: 12px/400, --text-micro: 10px/500 uppercase)
3. THE Design_Token_System SHALL define spacing based on an 8px base unit, with all spacing values as multiples of 8px
4. THE Design_Token_System SHALL define border-radius tokens (8px for cards, 4px for inputs/chips, 999px for pills/badges)
5. THE Design_Token_System SHALL define interaction tokens (150ms ease-out transitions, 2px solid orange focus ring with 2px offset, card shadow 0 2px 12px rgba(0,0,0,0.4))
6. THE Design_Token_System SHALL be scoped so that admin panel pages using `admin_base.html` remain unaffected by the new client portal tokens

### Requirement 2: Dark Theme Application

**User Story:** As a client user, I want the portal to use a dark theme with the RAMP design language, so that the product feels polished and professional.

#### Acceptance Criteria

1. THE Client_Portal SHALL use a new base template (`client_base.html`) that applies the dark theme tokens and is separate from the existing `base.html` (light, non-admin) and `admin_base.html` (dark, admin)
2. THE Client_Portal SHALL render page backgrounds using --color-bg (#0D0D1A)
3. THE Client_Portal SHALL render card and surface elements using --color-surface (#1A1A2E) and --color-surface-alt (#1E1E32)
4. THE Client_Portal SHALL render primary text in --color-white (#FFFFFF) and secondary text in --color-muted (#AAAAAA)
5. THE Client_Portal SHALL render all interactive accent elements (CTAs, active states, badges) using --color-orange (#FF6B35)
6. WHEN a user focuses an interactive element using keyboard navigation, THE Client_Portal SHALL display a 2px solid orange focus ring with 2px offset (WCAG 2.1 AA compliant)
7. THE Client_Portal SHALL never use raw hex values in component templates — all colors referenced via CSS custom property tokens

### Requirement 3: Sidebar Navigation

**User Story:** As a client user, I want a fixed sidebar with clear navigation items, so that I can quickly access all portal sections without losing context.

#### Acceptance Criteria

1. THE Sidebar_Navigation SHALL be a fixed left panel, 240px wide, full viewport height, with background --color-surface
2. THE Sidebar_Navigation SHALL contain navigation items: Home (BarChart2 icon), Review Queue (Inbox icon), Avatars (Users icon), Settings (Settings icon)
3. WHEN a navigation item is active, THE Sidebar_Navigation SHALL highlight it with a 3px solid --color-orange left border and --color-surface-alt background
4. THE Sidebar_Navigation SHALL display an orange pill badge on the Review Queue item showing the count of pending drafts
5. WHEN the pending draft count exceeds 10, THE Sidebar_Navigation SHALL render the Review Queue badge in --color-red instead of --color-orange
6. THE Sidebar_Navigation SHALL display a red dot badge on the Avatars item when any avatar assigned to the client is shadowbanned
7. THE Sidebar_Navigation SHALL display the client company name (truncated to 20 characters with ellipsis) in a bottom-pinned footer section
8. THE Sidebar_Navigation SHALL offset the main content area by 240px from the left edge
9. WHEN a navigation item is clicked, THE Client_Portal SHALL load the corresponding screen content via HTMX without a full page reload

### Requirement 4: Home Screen

**User Story:** As a client user, I want to see key metrics and pending actions at a glance, so that I understand my campaign status immediately upon login.

#### Acceptance Criteria

1. THE Home_Screen SHALL display 3 headline metric cards in a horizontal row: "Comments Posted" (count in selected period), "Total Upvotes Earned" (sum in selected period), "Subreddits Active In" (count of active subreddits)
2. THE Home_Screen SHALL render metric numbers using --text-display (48px/700) in --color-white, with labels in --text-small using --color-muted
3. THE Home_Screen SHALL display a Pending Approvals CTA that scales visual weight based on queue depth: 0 items shows a grey pill "Queue empty"; 1–4 items shows an amber pill with count; 5+ items shows an orange banner "X drafts waiting. Review now →"
4. WHEN the Pending Approvals CTA is clicked, THE Client_Portal SHALL navigate to the Review Queue screen
5. THE Home_Screen SHALL display a Momentum Events feed showing breakout comments (🔥 icon, "[Avatar] earned N upvotes in r/[sub]") and shadowban alerts (🚨 icon, "[Avatar] has been paused")
6. WHEN a momentum event "View thread" link is clicked, THE Client_Portal SHALL open the Reddit thread URL in a new browser tab
7. THE Home_Screen SHALL never display avatar reddit_username, proxy_ip, raw karma score, AI cost, or confidence score values

### Requirement 5: Review Queue Redesign

**User Story:** As a client user, I want to quickly review, edit, and approve AI-generated comment drafts, so that I can maintain content quality while keeping my campaign active.

#### Acceptance Criteria

1. THE Review_Queue SHALL display a page header with title "Review Queue" and subtitle "[N] drafts waiting for your approval"
2. THE Review_Queue SHALL display each draft as a card with: avatar name + phase badge (header left), subreddit pill + relative timestamp (header right), thread title in bold, first 120 characters of thread body in --color-muted, and the full comment draft text on a --color-surface-alt background
3. THE Review_Queue SHALL display 3 action buttons per card in fixed order: Approve (green fill), Edit (orange outline), Skip (ghost style), each with minimum 44px height
4. WHEN the client clicks Approve, THE Review_Queue SHALL immediately remove the card from the UI (optimistic update) and display a green Toast_Notification "Approved"
5. IF the server returns an error after an optimistic approve, THEN THE Review_Queue SHALL restore the card to its original position and display a red Toast_Notification with the error message
6. WHEN the client clicks Edit, THE Review_Queue SHALL transform the comment draft block into an editable text area with an orange border highlight and cursor, displaying "Save & Approve" (green) and "Cancel" buttons below
7. WHEN the client clicks "Save & Approve" after editing, THE Review_Queue SHALL capture the edit diff as a training signal, remove the card optimistically, and display a green Toast_Notification "Got it — we'll remember this for future drafts"
8. WHEN the client clicks Skip, THE Review_Queue SHALL remove the card from the visible queue with a fade animation (optimistic update) and move the draft to a "skipped" state
9. THE Review_Queue SHALL implement Skeleton_Loading (pulsing opacity 0.4–0.7, 1.2s CSS animation) while draft cards are being fetched, with no spinner elements
10. THE Review_Queue SHALL never display avatar reddit_username, proxy_ip, raw karma score, AI generation cost, or confidence score in any card element

### Requirement 6: Safety Blocks (Brand Mention Protection)

**User Story:** As a client user, I want the system to prevent premature brand mentions, so that avatar credibility is not compromised during early warming phases.

#### Acceptance Criteria

1. WHEN a comment draft contains the client brand name AND the avatar is in Phase 1 or Phase 2, THE Review_Queue SHALL display a red banner at the top of the card: "Brand mention blocked — [Avatar] is still building credibility in r/[sub]. Brand mentions unlock at Phase 3."
2. WHILE a safety block is active on a draft card, THE Review_Queue SHALL disable the Approve button and require the client to edit the draft to remove the brand mention before approval
3. WHEN the client edits a blocked draft to remove the brand mention, THE Review_Queue SHALL remove the safety block banner and re-enable the Approve button
4. THE Client_Portal SHALL enforce safety blocks server-side — the approve API endpoint SHALL reject any draft that triggers a brand mention block regardless of client-side state

### Requirement 7: API Response Allowlist

**User Story:** As a platform operator, I want sensitive internal data never exposed to client-facing endpoints, so that operational security is maintained regardless of frontend implementation.

#### Acceptance Criteria

1. THE API_Allowlist SHALL ensure that client-facing API responses never include: reddit_username, proxy_ip, browser_profile_id, raw_karma_score, ai_cost, confidence_score, survival_rate, or phase_eligibility_calculation fields
2. THE API_Allowlist SHALL be implemented as a server-side response schema (Pydantic model) applied to all client-facing endpoints, using an explicit include list rather than a denylist
3. WHEN a client-facing endpoint is called, THE API_Allowlist SHALL filter the response before serialization — sensitive fields SHALL never be present in the HTTP response body
4. THE API_Allowlist SHALL apply identically in development, staging, and production environments with no environment-conditional logic

### Requirement 8: Toast Notification System

**User Story:** As a client user, I want brief feedback messages after my actions, so that I know whether my approvals and edits succeeded without disrupting my workflow.

#### Acceptance Criteria

1. THE Toast_Notification system SHALL display notifications in the bottom-right corner of the viewport
2. THE Toast_Notification system SHALL stack a maximum of 3 notifications simultaneously, with newest at the bottom
3. THE Toast_Notification system SHALL auto-dismiss each notification after 4 seconds
4. THE Toast_Notification system SHALL use --color-green background for success messages, --color-amber for warnings, and --color-red for errors
5. THE Toast_Notification system SHALL animate notifications in with a slide-from-right transition (150ms ease-out)

### Requirement 9: Skeleton Loading States

**User Story:** As a client user, I want smooth loading indicators instead of spinners, so that the interface feels fast and polished during data fetches.

#### Acceptance Criteria

1. WHEN content is loading, THE Client_Portal SHALL display skeleton placeholder elements matching the shape and layout of the expected content
2. THE Client_Portal SHALL animate skeleton elements with an opacity pulse between 0.4 and 0.7 at a 1.2-second interval using CSS animation
3. THE Client_Portal SHALL never display a spinner element (circular loading indicator) anywhere in the client portal

### Requirement 10: Filter Bar (Review Queue)

**User Story:** As a client user, I want to filter the review queue by avatar and subreddit, so that I can focus on specific segments of my campaign.

#### Acceptance Criteria

1. THE Filter_Bar SHALL appear directly below the Review Queue subtitle as an inline chip row
2. THE Filter_Bar SHALL provide filter chips for: Avatar (one chip per avatar assigned to the client) and Subreddit (one chip per subreddit the client monitors)
3. WHEN a filter chip is selected, THE Review_Queue SHALL reload its content via HTMX showing only drafts matching the selected filters
4. THE Filter_Bar SHALL display active filters as removable chips (with × icon) and provide a "Clear all" text link at the right end
5. THE Filter_Bar SHALL persist filter state in URL query parameters so that page refreshes maintain the active filters

### Requirement 11: Avatars Screen

**User Story:** As a client user, I want to see my avatars with their status and activity, so that I understand which personas are active and how they are performing.

#### Acceptance Criteria

1. THE Client_Portal SHALL display avatars in a card grid layout (3 columns desktop, 2 tablet, 1 mobile)
2. THE Client_Portal SHALL render each avatar card with: avatar name, one-sentence professional bio, phase badge (Phase 1 grey, Phase 2 orange, Phase 3 green), and "last active" timestamp
3. WHEN an avatar has not been active for more than 7 days, THE Client_Portal SHALL display the "last active" text in --color-amber
4. WHEN an avatar is shadowbanned, THE Client_Portal SHALL display a full-width red "PAUSED" banner at the top of the avatar card
5. THE Client_Portal SHALL never display reddit_username, raw karma score, proxy IP, AI cost, confidence score, or browser profile ID on avatar cards
6. WHEN no avatars are assigned to the client, THE Client_Portal SHALL display an Empty_State with copy: "Your avatars are being configured. Check back in 24–48 hours."

### Requirement 12: System Banners

**User Story:** As a client user, I want to be alerted about critical issues affecting my campaign, so that I can take action or understand why activity has paused.

#### Acceptance Criteria

1. WHEN any avatar assigned to the client is shadowbanned, THE Client_Portal SHALL display a red full-width banner at the top of the content area: "[Avatar] has been paused. We are investigating — no action needed from you."
2. WHEN the client has not approved any drafts in 7+ days, THE Client_Portal SHALL display an amber full-width banner: "Your drafts are waiting. Unapproved content delays avatar progress."
3. THE Client_Portal SHALL display only one banner at a time, prioritized by severity (red over amber)
4. WHILE a shadowban banner is active, THE Client_Portal SHALL not allow the banner to be dismissed (persists until resolved)
5. WHEN an inactivity banner is displayed, THE Client_Portal SHALL allow the client to dismiss it with a 24-hour snooze

### Requirement 13: Settings Screen

**User Story:** As a client user, I want to manage my keywords, subreddits, and brand guardrails, so that I can refine my campaign targeting without contacting support.

#### Acceptance Criteria

1. THE Client_Portal SHALL provide a Settings screen with sections: Keywords, Subreddits, and Brand Guardrails
2. THE Client_Portal SHALL allow client_admin and client_manager roles to add, remove, and update keyword priority (high/medium/low) via inline HTMX interactions
3. THE Client_Portal SHALL allow client_admin and client_manager roles to add and remove subreddits via inline HTMX interactions
4. THE Client_Portal SHALL display brand guardrails (terms the brand must never be associated with) as editable tag inputs
5. THE Client_Portal SHALL enforce RBAC — client_viewer role SHALL have read-only access to the Settings screen with all edit controls hidden

### Requirement 14: Empty States

**User Story:** As a client user, I want helpful guidance when a screen has no data, so that I understand what to expect and when to check back.

#### Acceptance Criteria

1. WHEN the Review Queue has no pending drafts, THE Client_Portal SHALL display: "Nothing to review right now. Your avatars are active — new drafts appear here as opportunities are found." with a timestamp "Last draft appeared: [X hours/days] ago"
2. WHEN the Avatars screen has no avatars assigned, THE Client_Portal SHALL display: "Your avatars are being configured. Check back in 24–48 hours."
3. WHEN the Home Screen has no momentum events, THE Client_Portal SHALL display: "No activity yet. Your avatars are warming up — momentum events will appear here as they engage."
4. THE Client_Portal SHALL render all empty states using --color-muted text on --color-surface background, centered within the content area

### Requirement 15: Simplified Onboarding Wizard

**User Story:** As a new client user, I want a guided setup flow to configure my campaign, so that the system has enough context to generate relevant content for my brand.

#### Acceptance Criteria

1. WHEN a client user logs in for the first time and the client has no keywords AND no subreddits configured, THE Client_Portal SHALL display the Onboarding_Wizard as a full-screen takeover (no sidebar visible)
2. THE Onboarding_Wizard SHALL present steps as form fields (no web scraping, no AI auto-fill): Company Profile (name, description, value proposition), ICP Definition (job titles, frustrations, industry), Keywords (tag input with priority), Subreddits (selection from suggested list), Brand Guardrails (terms to avoid)
3. THE Onboarding_Wizard SHALL display a progress bar at the top (4px height, orange fill) with step label "Step N of 5"
4. THE Onboarding_Wizard SHALL validate that all required fields are completed before allowing progression to the next step
5. WHEN the wizard is completed, THE Client_Portal SHALL save all configuration data and redirect to the Home Screen with a green Toast_Notification "Setup complete. Your avatars will be active in 24–48 hours."
6. THE Onboarding_Wizard SHALL allow navigation back to previous steps with all fields pre-filled

### Requirement 16: Backward Compatibility

**User Story:** As a platform operator, I want the admin panel to remain unchanged, so that internal operations are not disrupted by the client portal redesign.

#### Acceptance Criteria

1. THE Client_Portal redesign SHALL not modify any templates extending `admin_base.html`
2. THE Client_Portal redesign SHALL not modify any routes under the `/admin/` path prefix
3. THE Client_Portal redesign SHALL maintain all existing API endpoints used by the admin panel without breaking changes
4. WHEN an admin-level user (owner, partner) navigates to `/clients/{client_id}`, THE Client_Portal SHALL render the new dark-themed portal (admins can preview what clients see)
