# Requirements Document

## Introduction

The Admin Avatar Detail page (`/admin/avatars/{id}`) currently exposes 12 separate tabs (Overview, Profile, Safety, Phase, Performance, Drafts, Billing, Analytics, Presence, Pipeline, Strategy, Actions). This over-segmentation increases cognitive load, hides critical signals behind navigation, and produces inconsistent lazy-loading behavior across the page. This spec consolidates the page into 7 tabs, unifies HTMX trigger semantics, removes duplicated controls, and fixes a likely lazy-load bug where partials re-fetch on every scroll.

The work is scoped to `reddit_saas/app/templates/admin_avatar_detail.html` and the route handlers in `reddit_saas/app/routes/admin.py` that serve its lazy-loaded partials. No new backend data is required — this is a presentation/IA refactor.

## Glossary

- **Avatar_Detail_Page**: The Jinja2 template at `admin_avatar_detail.html` rendered for `/admin/avatars/{id}`, used by ops to inspect a single avatar's state.
- **Tab_Group**: A logical cluster of related panels selected by a single button in the tab nav bar.
- **Panel**: A `<div data-avatar-detail-panel="…">` container that holds the content of a single Tab_Group; only one is visible at a time.
- **Lazy_Partial**: A child `<div>` inside a Panel that uses `hx-get` to fetch its content from a server endpoint asynchronously.
- **HTMX_Trigger_Policy**: The rule that determines when a Lazy_Partial issues its `hx-get` request (`load`, `revealed once`, etc.).
- **Critical_Signal**: Information that ops staff must see immediately to triage avatar problems — currently shadowban status, freeze state, CQS level, and warming-phase progress.
- **Header_Action**: A button rendered in the page header above the tabs (currently Refresh, Export, Back link).
- **Action_Tab**: The "Actions" Tab_Group containing destructive/admin-only operations (delete, reassign, manual phase override, etc.).

## Requirements

### Requirement 1: Tab Consolidation (12 → 7)

**User Story:** As an ops admin viewing an avatar, I want fewer top-level tabs, so that I can find related information without scanning 12 buttons.

#### Acceptance Criteria

1. THE Avatar_Detail_Page SHALL render exactly 7 tab buttons in the order: Overview, Profile & Safety, Performance, Billing, Content, Strategy, Actions.
2. THE Overview Tab_Group SHALL contain the existing Overview panels (Client Assignment, Confidence, Profile Completeness, Learned Patterns, Learning/Voice Adaptation) AND a **Today's Action card** (see Requirement 11) AND a summary card for Subreddit Presence coverage.
3. THE "Profile & Safety" Tab_Group SHALL contain the current Profile panel content followed by the current Safety panel content (Shadowban Status, CQS, Freeze Status), in that order.
4. THE Performance Tab_Group SHALL contain the current Performance panel content followed by the current Analytics panel content.
5. THE Content Tab_Group SHALL contain the current Drafts panel content followed by the current Pipeline panel content.
6. THE Billing, Strategy, and Actions Tab_Groups SHALL retain their current content unchanged.
7. THE Phase Tab_Group and Presence Tab_Group SHALL be removed as standalone tabs; their full content SHALL be reachable from the Overview summary cards via "View details" links that scroll-anchor to the same panel content rendered lower in the Overview tab.
8. IF a user navigates to the page with a legacy tab query parameter (`?tab=safety`, `?tab=phase`, `?tab=presence`, `?tab=drafts`, `?tab=analytics`, `?tab=pipeline`), THEN THE page SHALL redirect to the consolidated tab that now contains that content (e.g., `safety` → `profile-safety`, `phase` → `overview`, `presence` → `overview`, `drafts` → `content`, `analytics` → `performance`, `pipeline` → `content`).

### Requirement 2: Critical_Signal Visibility in Header

**User Story:** As an ops admin, I want shadowban, freeze, and CQS alerts visible regardless of which tab I am viewing, so that critical issues are not buried one click deep.

#### Acceptance Criteria

1. THE Avatar_Detail_Page header SHALL display a Critical_Signal badge row directly under the avatar name showing: shadowban state, freeze state, CQS level, and current warming phase number.
2. WHERE shadowban is detected, freeze is active, or CQS is "low"/"lowest", THE Critical_Signal badge SHALL render with red background colors (`bg-red-900/40`, `text-red-300`, `border-red-700`).
3. WHERE all signals are healthy, THE Critical_Signal badge row SHALL render with neutral/green colors.
4. THE Critical_Signal badge row SHALL be sticky-positioned alongside the existing tab bar so it remains visible during scroll, on the same `sticky top-0` band.
5. WHEN the user clicks any Critical_Signal badge, THE Avatar_Detail_Page SHALL switch to the relevant tab (shadowban/CQS/freeze → Profile & Safety; phase → Overview) and scroll-anchor to the relevant section.

### Requirement 3: Unified HTMX Trigger Policy

**User Story:** As a developer maintaining the page, I want one consistent rule for how lazy partials load, so that I can reason about network behavior and avoid accidental re-fetches.

#### Acceptance Criteria

1. THE Avatar_Detail_Page SHALL apply the HTMX_Trigger_Policy: `hx-trigger="load"` for partials inside the Overview Tab_Group (loaded on initial page render), and `hx-trigger="revealed once"` for partials inside all other Tab_Groups (loaded when the user first activates the tab).
2. THE Avatar_Detail_Page SHALL NOT use `hx-trigger="revealed"` (without `once`) on any element; existing instances at lines 812, 823, 1297, 1312, 1322, 1334 SHALL be changed to `revealed once`.
3. WHEN a user manually refreshes a panel via a per-partial refresh button, THE corresponding `hx-get` SHALL re-fire and replace content via `hx-swap="innerHTML"`; this is the only sanctioned re-fetch path.
4. THE tab activation script SHALL fire a custom event `avatarDetail:tab-activated` carrying the tab id, so HTMX-loaded partials inside revealed tabs can self-initialize JS widgets (charts, etc.) on first activation.

### Requirement 4: Header Action Deduplication

**User Story:** As an ops admin, I want each action to live in exactly one place, so that I do not waste time deciding which button to click.

#### Acceptance Criteria

1. THE Avatar_Detail_Page header SHALL contain exactly these Header_Actions: a back link to the avatar list, a single "Refresh page" button, and an avatar status toggle (active/inactive).
2. THE Export action SHALL exist only inside the Action_Tab; THE header SHALL NOT contain an Export button.
3. THE "Refresh All" / "Refresh page" duplication SHALL be resolved by keeping only the page-reload anchor that already exists in the header (lines 119-127); any additional refresh-all controls in panels SHALL be removed.
4. WHERE a panel has a panel-specific refresh button (e.g., shadowban "Check Health"), THAT button SHALL remain because it triggers a distinct backend operation, not just a re-fetch.

### Requirement 5: Mobile Breadcrumbs

**User Story:** As an ops admin on a phone, I want short breadcrumbs and accessible tabs, so that the page is usable below 768px width.

#### Acceptance Criteria

1. WHERE the viewport width is below 640px, THE breadcrumbs SHALL truncate the middle segments and show only "← Avatars / {username}" with the avatar name truncated to 24 characters via CSS `text-overflow: ellipsis`.
2. WHERE the viewport width is below 768px, THE tab bar SHALL allow horizontal scroll (`overflow-x-auto`) and SHALL NOT wrap to multiple lines.
3. THE active tab button SHALL remain visible on tab-bar scroll: when a tab is activated programmatically, THE Avatar_Detail_Page SHALL call `scrollIntoView({block: 'nearest', inline: 'center'})` on the active button.

### Requirement 6: Karma Chart Density Toggle

**User Story:** As an ops admin reviewing avatar karma, I want to choose between daily and weekly granularity, so that I can see both day-level anomalies and overall trends without scrolling 30 columns by default.

#### Acceptance Criteria

1. THE karma chart in the Performance Tab_Group SHALL default to a weekly-aggregate view (4–6 bars covering the last 30 days).
2. THE karma chart SHALL include a "Daily / Weekly" toggle control above the bars.
3. WHEN the user selects "Daily", THE chart SHALL re-render with the existing 30-column daily resolution.
4. THE selected granularity SHALL persist in `localStorage` under the key `avatarDetail:karmaGranularity` and SHALL be restored on subsequent visits.

### Requirement 7: Collapsible Comment Lists

**User Story:** As an ops admin reviewing drafts, I want long comment lists collapsed by default with a summary, so that I am not forced to scroll past 19 cards to reach the pipeline section.

#### Acceptance Criteria

1. WHERE the Content Tab_Group renders more than 5 professional or hobby comments, THE list SHALL be wrapped in a `<details>` element collapsed by default.
2. THE `<summary>` of the collapsed list SHALL display: comment type ("Professional" / "Hobby"), total count, and status breakdown (e.g., "19 — 12 approved, 7 pending").
3. WHERE the total is 5 or fewer, THE list SHALL render expanded without a `<details>` wrapper.
4. THE first card in each list SHALL remain visible above the `<details>` collapse boundary as a preview.

### Requirement 8: Tab State Persistence

**User Story:** As an ops admin returning to an avatar I was just looking at, I want the last tab I was on to be remembered, so that I do not lose context after navigating away.

#### Acceptance Criteria

1. WHEN the user activates a tab, THE Avatar_Detail_Page SHALL update the URL hash (`#tab=profile-safety`) without reloading the page.
2. WHEN the page loads with a `#tab=…` hash, THE Avatar_Detail_Page SHALL activate that tab in place of Overview.
3. WHEN the page loads without a hash, THE Avatar_Detail_Page SHALL default to the Overview tab.
4. THE tab state SHALL NOT be persisted in `localStorage` — the hash is the sole source of truth, so different browser tabs viewing different avatars do not interfere.

### Requirement 9: Backward Compatibility for Bookmarks

**User Story:** As an ops admin with bookmarks pointing to specific avatar tabs, I want those bookmarks to keep working after the refactor, so that I do not lose saved workflows.

#### Acceptance Criteria

1. WHEN a user opens a URL with a legacy hash (`#tab=safety`, `#tab=phase`, etc.), THE Avatar_Detail_Page SHALL detect the legacy id, rewrite it to the consolidated id (per Requirement 1.8 mapping), and update the address bar without a server round-trip.
2. THE legacy-id mapping SHALL also handle the `?tab=` query-parameter form for cases where ops used non-hash bookmarks.

### Requirement 10: No Regression in Existing Functionality

**User Story:** As an ops admin, I want every piece of information currently visible to remain reachable after the refactor, so that the consolidation reduces clicks but never removes data.

#### Acceptance Criteria

1. THE refactored Avatar_Detail_Page SHALL render every Lazy_Partial that the current page renders, with the same `hx-get` endpoint URL and the same final DOM structure once loaded.
2. THE refactor SHALL NOT change any route handler in `reddit_saas/app/routes/admin.py`; only the parent template's tab/panel organization changes.
3. WHERE a panel's contents are moved to a different tab, THE move SHALL be a re-parenting of the same DOM subtree, not a rewrite of the panel's internals.
4. THE existing JavaScript tab-switching logic at lines 1431-1460 SHALL be updated to handle 7 panels instead of 12, but its event dispatch contract SHALL remain compatible with any other code that listens for tab changes.

### Requirement 11: Today's Action Card (Overview)

**User Story:** As an ops marketer opening an avatar detail page, I want one card at the top that tells me what this avatar should do today, so that I can act without piecing together phase rules, daily quotas, and health blockers from separate panels.

#### Acceptance Criteria

1. THE Overview Tab_Group SHALL render a "Today's Action" card immediately below the Client Assignment card, before all other content.
2. THE Today's Action card SHALL display three signals: (a) an imperative action sentence, (b) a daily-quota status pill, (c) a nearest-promotion-gate progress bar.
3. WHERE the avatar has an active health blocker (shadowbanned, frozen, or CQS=lowest), THE imperative action SHALL be a "Blocked: …" message that overrides any phase-derived recommendation.
4. WHERE the avatar is at Phase 0 (Mentor), THE card SHALL render the single line "Mentor — no pipeline action expected today" and SHALL omit signals (b) and (c).
5. WHERE the avatar is at Phase 3, THE nearest-promotion-gate signal SHALL be omitted and replaced with "Phase 3 — fully integrated".
6. WHERE the daily quota for the relevant counter is already met, THE imperative action SHALL read "Quota met (X/Y) — wait until 00:00 UTC".
7. WHERE the avatar's phase-progress gates are all met (`health.phase_eligible_for_next` is true), THE imperative action SHALL read "Eligible for promotion to Phase {n+1} — review evidence".
8. THE card SHALL include a "View phase details" link that scroll-anchors to the full Phase Progress section rendered lower in the Overview panel.
9. THE imperative action text SHALL be computed server-side by a helper `avatar_today_recommendation(avatar, health)` and passed into the template; THE template SHALL NOT contain phase-logic conditionals beyond rendering the precomputed string.

### Requirement 12: Phase Status Coloring

**User Story:** As an ops marketer scanning the avatar header, I want the phase badge to encode whether the avatar is progressing normally, stalled, or blocked, so that I can spot abnormal avatars without inspecting every one.

#### Acceptance Criteria

1. THE phase badge in the Critical_Signal header SHALL render the phase number with a neutral (blue) base color and append a status suffix whose color encodes urgency.
2. THE status suffix colors SHALL follow this table:
   - **Green** — phase days-in-phase within expected duration AND no health blocker
   - **Neutral blue** — phase days-in-phase within first half of expected duration (early-warming state, no action needed)
   - **Amber** — phase days-in-phase exceeds 1.5× expected duration AND not eligible for promotion
   - **Red** — health blocker present (shadowban, freeze, CQS=lowest) overrides all other states
3. THE expected-duration values SHALL be: Phase 1 = 14 days, Phase 2 = 30 days, Phase 3 = no expected duration (always green if no blocker).
4. THE phase status suffix SHALL be one of: "On track", "Day {n}/{expected}", "Stalled {n}d", "Blocked", or "Eligible for promotion".
5. THE Phase 0 (Mentor) badge SHALL render in purple with no status suffix (matches existing convention).
6. THE phase-status color rule SHALL be implemented in the same server-side helper as Requirement 11, returning both the imperative action AND the badge state, so the two stay in sync.

## Out of Scope

- **Global search bar in the admin header.** Belongs to a separate spec covering `admin_base.html`, not the avatar detail page.
- **Sticky quick-action header with Message/Sync/Report buttons.** "Message to Reddit" is not a system capability per `CLAUDE.md §5` (posting is manual); a generic "Sync" or "Report" button would need its own backend design first.
- **Swipe gestures between tabs on mobile.** Not blocked by anything in this refactor, but adds a JS dependency on touch handling that warrants its own UX validation.
- **Backend endpoint consolidation.** Several partials could in theory be merged at the route level for fewer network round-trips; that is a separate performance spec.
