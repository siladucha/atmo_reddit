# Bugfix Requirements Document

## Introduction

This document addresses 42 UI/UX issues identified in a comprehensive QA audit of the RAMP admin panel. Issues range from critical data-loss risks and data contradictions to polish improvements. The fixes span multiple admin views: Avatars List, Avatar Detail, Review Queue, Audit Logs, and shared UI components. All issues are organized by severity to ensure critical problems are resolved first.

Platform: Python/FastAPI + Jinja2 + HTMX + Tailwind CSS. Templates in `app/templates/` with partials in `app/templates/partials/`. Admin panel uses dark theme (`admin_base.html`).

## Bug Analysis

### Current Behavior (Defect)

#### 🔴 CRITICAL

1.1 WHEN the user clicks "Delete All" in Audit Logs THEN the system immediately deletes all 1,787 log entries without any confirmation dialog or undo mechanism

1.2 WHEN the Avatars list view header displays stats THEN the system shows "16 active · 8 total" which is a mathematical contradiction (active count exceeds total count)

1.3 WHEN the avatar has 3 failed readiness checks (Credentials ✗, Proxy ✗, User-Agent ✗) THEN the system still renders the "Enable Auto-Posting" button as clickable/enabled

#### 🟠 HIGH

1.4 WHEN the Goals (30 Days) section renders on the avatar detail page THEN the system displays bare values "→ 80, → 3, → 85" with no labels explaining what each goal represents

1.5 WHEN an avatar's workflow phase has exceeded its expected duration (e.g. "Day 18/14") THEN the system displays this without a prominent visual warning on the Workflow or Overview tabs

1.6 WHEN displaying a username that is stored as "u/SergeiMarshak" THEN the system renders it as "u/u/SergeiMarshak" in both the header and breadcrumb by prepending an extra "u/" prefix

1.7 WHEN the avatar's strategy has not been approved THEN the system shows a passive "Strategy not approved" warning only on the Strategy tab, not on the Workflow tab which is the first tab users land on

1.8 WHEN an avatar is assigned hobby subreddits but its actual posting activity occurs in different subreddits THEN the system shows no clarification, alert, or explanation of the mismatch

1.9 WHEN the Avatars List View (Table + Grid) displays column headers for CQS, Health, Phase, Pool, AI Cost, Posting, Profile % THEN the system provides no tooltip/help icons to explain these abbreviations and metrics

1.10 WHEN the Review Queue displays ALERT badge, push:hard/low/medium tags, P1/P2 badges THEN the system provides no tooltip/help icons explaining what these terms mean

1.11 WHEN the user needs to filter by a specific subreddit (r/all) or user (u/all) THEN the system shows plain dropdown menus instead of searchable typeahead/combobox controls

1.12 WHEN the CQS Level dropdown displays on an avatar that has never been checked THEN the system defaults to "Highest" while simultaneously showing status "NOT CHECKED" — creating a contradictory state that could be saved to the database

#### 🟡 MEDIUM

1.13 WHEN the user clicks outside the Import/Export dropdown THEN the system does not close the dropdown menu

1.14 WHEN the same thread appears multiple times in the Review Queue (multiple drafts for same thread) THEN the system shows them as separate ungrouped entries with no visual indicator they belong to the same thread

1.15 WHEN three action icons appear next to the Approve button in Review Queue THEN the system renders them (X, pencil, arrows) without any labels or tooltips explaining their function

1.16 WHEN avatar rows in the table contain subreddit karma breakdowns of varying lengths THEN the system renders inconsistent row heights making the table visually unstable

1.17 WHEN the Posting column shows "Missing" for an avatar THEN the system provides no explanation of what specific data or configuration is missing

1.18 WHEN Health, AI Cost, or CQS columns have no data THEN the system displays raw "UNKNOWN" text or "—" dashes with no distinction between "not checked yet" and "check failed"

1.19 WHEN the Readiness checklist displays status symbols THEN the system uses three symbols (✗, ✓, ○) where the circle (○) meaning is unclear — it could mean "pending", "optional", or "not applicable"

1.20 WHEN the Health Scorecard displays sub-scores THEN the system shows raw numbers without maximum values or any explanation of how sub-scores combine into the overall health score

1.21 WHEN the Voice Profile section renders THEN the system displays technical metadata "DB type: TEXT (unlimited)" which is meaningless to end users

1.22 WHEN the Strategy footer renders THEN the system exposes technical metadata including LLM model name, token counts, and generation duration that has no operational value for users

1.23 WHEN the Karma bar chart renders with 3 bars THEN only 2 x-axis date labels are shown, and bars lack inline value labels

1.24 WHEN the 30d Delta indicator shows "0" THEN the bar chart simultaneously shows visible activity bars — creating a data contradiction

1.25 WHEN the page has multiple disconnected Save buttons and the user navigates away with unsaved changes THEN the system provides no warning about losing unsaved data

1.26 WHEN the user hovers over tooltip icons (ⓘ) THEN the system displays only "?" with no actual contextual information

1.27 WHEN the Live Pulse chart has no data to display THEN the system renders a blank/empty chart area with no message explaining the empty state

1.28 WHEN Pipeline Stats shows zero values THEN the system displays them in different colors with no legend or explanation of what the colors represent

1.29 WHEN subreddits display a "hob" tag THEN the system provides no tooltip or explanation that "hob" is an abbreviation for "hobby"

1.30 WHEN the admin uses Phase Override to change an avatar's phase THEN the system does not require a reason field — allowing significant phase changes without accountability

1.31 WHEN Entity IDs appear in Audit Logs THEN the system displays raw UUIDs with no clickable links to the referenced entities

1.32 WHEN the Details column in Audit Logs contains data THEN the system shows raw truncated JSON instead of a structured/formatted display

1.33 WHEN Audit Logs load THEN the view is dominated by one action type (scrape_completed) with no default filter to focus on more meaningful actions

1.34 WHEN 1,787 audit log entries exist THEN the system shows no visible pagination controls

#### 🟢 LOW / POLISH

1.35 WHEN large karma numbers are displayed (e.g. 6283184) THEN the system shows the raw unformatted number instead of a human-readable format like "6.3M"

1.36 WHEN Profile % shows a 0% red badge THEN the system provides no tooltip explaining what "Profile %" measures or why 0% is concerning

1.37 WHEN no filter is active in Review Queue and "Showing: 20" matches "Total Pending: 20" THEN the system redundantly displays both identical counts

1.38 WHEN Oldest Draft age is displayed THEN the system shows only hours (e.g. "692h") with no equivalent calendar date for context

1.39 WHEN "Freeze Avatar" buttons appear in two different locations on the avatar page THEN neither instance shows a confirmation dialog before executing the freeze action

1.40 WHEN the Strategy section shows "Questions for Client" THEN the terminology is confusing because these are questions the system needs answered to define the strategy, not questions directed at the client

1.41 WHEN the user hovers over certain elements THEN a "Post upvotes" tooltip appears unexpectedly without clear association to the hovered element

1.42 WHEN Version History displays multiple strategy versions THEN the system shows no diff or comparison between versions

### Expected Behavior (Correct)

#### 🔴 CRITICAL

2.1 WHEN the user clicks "Delete All" in Audit Logs THEN the system SHALL display a confirmation dialog stating the number of entries to be deleted and require explicit confirmation before proceeding, with an option to cancel

2.2 WHEN the Avatars list view header displays stats THEN the system SHALL show mathematically consistent counts (e.g. "16 active · 20 total" where active ≤ total), properly computing totals from the avatar queryset

2.3 WHEN the avatar has any failed readiness checks THEN the system SHALL disable the "Enable Auto-Posting" button and display a message indicating which checks must pass before auto-posting can be enabled

#### 🟠 HIGH

2.4 WHEN the Goals (30 Days) section renders THEN the system SHALL display descriptive labels for each goal value (e.g. "Karma → 80", "Posts → 3", "Health → 85%")

2.5 WHEN an avatar's workflow phase has exceeded its expected duration THEN the system SHALL display a prominent warning badge (e.g. "⚠️ OVERDUE by 4 days") visible on both the Workflow and Overview tabs

2.6 WHEN displaying a username stored as "u/SergeiMarshak" THEN the system SHALL render it as "u/SergeiMarshak" without prepending an additional "u/" prefix

2.7 WHEN the avatar's strategy has not been approved THEN the system SHALL surface a visible warning banner on the Workflow tab (the default landing tab) in addition to the Strategy tab

2.8 WHEN an avatar's assigned subreddits differ from its actual posting activity subreddits THEN the system SHALL display a mismatch indicator with a brief explanation (e.g. "Activity detected in 3 subreddits not in assignment list")

2.9 WHEN the Avatars List View displays abbreviated column headers THEN the system SHALL include tooltip/help icons (ⓘ) next to each header with a brief explanation of the metric (CQS = Comment Quality Score, etc.)

2.10 WHEN the Review Queue displays specialized badges and tags THEN the system SHALL include tooltip/help icons explaining each term (ALERT = requires immediate attention, P1 = highest priority, push:hard = aggressive engagement, etc.)

2.11 WHEN the user needs to filter by subreddit or user THEN the system SHALL provide searchable typeahead/combobox dropdowns that allow typing to filter the options list

2.12 WHEN the CQS Level dropdown displays for an avatar that has never been checked THEN the system SHALL default to an empty/placeholder state (e.g. "— Not Checked —") that cannot be confused with an actual CQS result

#### 🟡 MEDIUM

2.13 WHEN the user clicks outside the Import/Export dropdown THEN the system SHALL close the dropdown menu

2.14 WHEN multiple drafts for the same thread appear in the Review Queue THEN the system SHALL visually group them (e.g. with an indented sub-list or a "2 drafts for this thread" indicator)

2.15 WHEN action icons appear next to the Approve button THEN the system SHALL display tooltips on hover explaining each icon's function (X = Reject, Pencil = Edit, Arrows = Reassign/Move)

2.16 WHEN avatar rows display subreddit karma breakdowns THEN the system SHALL enforce consistent row heights (e.g. via fixed height with overflow scroll/truncation, or collapsible sections)

2.17 WHEN the Posting column shows "Missing" THEN the system SHALL specify what is missing (e.g. "Missing: proxy, credentials" or "Missing: user-agent")

2.18 WHEN Health, AI Cost, or CQS columns have no data THEN the system SHALL distinguish between states: "Not Checked" (never evaluated) vs "Error" (check failed) vs "N/A" (not applicable), using distinct visual indicators

2.19 WHEN the Readiness checklist displays status symbols THEN the system SHALL use clearly labeled indicators: ✓ = "Pass", ✗ = "Fail", and replace ○ with an explicit label such as "Pending" or "Not Configured"

2.20 WHEN the Health Scorecard displays sub-scores THEN the system SHALL show them with maximum values (e.g. "7/10") and include a brief explanation or formula showing how they combine

2.21 WHEN the Voice Profile section renders THEN the system SHALL NOT display internal database metadata ("DB type: TEXT (unlimited)") — only user-relevant content should be shown

2.22 WHEN the Strategy footer renders THEN the system SHALL hide or collapse technical metadata (model name, token counts, duration) behind an expandable "Technical Details" section, hidden by default

2.23 WHEN the Karma bar chart renders THEN the system SHALL display x-axis labels for all bars and show inline value labels on each bar

2.24 WHEN the 30d Delta indicator value and the bar chart data are computed THEN the system SHALL ensure they use the same data source and time window so values are consistent

2.25 WHEN the user navigates away from a page with unsaved changes THEN the system SHALL display a browser confirmation dialog warning about unsaved changes

2.26 WHEN the user hovers over tooltip icons (ⓘ) THEN the system SHALL display meaningful contextual help text explaining the associated metric or field

2.27 WHEN the Live Pulse chart has no data THEN the system SHALL display an empty state message (e.g. "No activity recorded yet" or "Waiting for pipeline data...")

2.28 WHEN Pipeline Stats shows zero values in different colors THEN the system SHALL include a legend explaining what each color represents

2.29 WHEN subreddits display a "hob" tag THEN the system SHALL show a tooltip on hover reading "Hobby subreddit" or use the full word "hobby" instead of the abbreviation

2.30 WHEN the admin uses Phase Override THEN the system SHALL require a reason field (text input) that is stored in the audit log before the phase change is executed

2.31 WHEN Entity IDs appear in Audit Logs THEN the system SHALL render them as clickable links that navigate to the relevant entity detail page (avatar, client, user, etc.)

2.32 WHEN the Details column in Audit Logs contains JSON data THEN the system SHALL display it in a formatted, structured view (key-value pairs, collapsible sections) rather than raw truncated JSON

2.33 WHEN Audit Logs load THEN the system SHALL apply a default filter that excludes high-frequency automated actions (e.g. scrape_completed) or provide a "Hide Automated" toggle that is enabled by default

2.34 WHEN audit log entries exceed a page size THEN the system SHALL display visible pagination controls (page numbers, next/prev buttons) with a configurable page size

#### 🟢 LOW / POLISH

2.35 WHEN karma numbers exceed 1,000 THEN the system SHALL format them in a human-readable abbreviated form (1.2K, 6.3M, etc.) with the full number available on hover

2.36 WHEN Profile % shows a 0% red badge THEN the system SHALL include a tooltip explaining what Profile % measures (e.g. "Percentage of Reddit profile fields completed") and why a low value matters

2.37 WHEN no filter is active in Review Queue and "Showing" count equals "Total Pending" THEN the system SHALL hide the redundant "Showing: N" stat or display it only when a filter reduces the visible count

2.38 WHEN Oldest Draft age is displayed THEN the system SHALL show both the relative time (e.g. "29 days") and the calendar date (e.g. "May 5, 2026") for full context

2.39 WHEN the user clicks "Freeze Avatar" in any location THEN the system SHALL display a confirmation dialog explaining the consequences of freezing before executing the action

2.40 WHEN the Strategy section labels the questions area THEN the system SHALL use clearer terminology such as "Questions to Define Strategy" or "Strategy Input Questions" instead of "Questions for Client"

2.41 WHEN tooltips appear on hover THEN the system SHALL ensure each tooltip is correctly anchored to its trigger element and does not appear on unrelated elements unexpectedly

2.42 WHEN Version History displays multiple strategy versions THEN the system SHALL provide a visual diff or side-by-side comparison showing what changed between versions

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the user confirms deletion in the Audit Logs confirmation dialog THEN the system SHALL CONTINUE TO delete all entries as it does today (the deletion functionality itself remains unchanged)

3.2 WHEN avatars are displayed in list view with correct data THEN the system SHALL CONTINUE TO show accurate active/total counts for normally-functioning querysets

3.3 WHEN all readiness checks pass (✓ for Credentials, Proxy, User-Agent) THEN the system SHALL CONTINUE TO render "Enable Auto-Posting" as clickable and functional

3.4 WHEN avatar detail pages render non-goal metrics and sections THEN the system SHALL CONTINUE TO display all existing avatar information without layout disruption

3.5 WHEN an avatar's phase is within expected duration THEN the system SHALL CONTINUE TO display the phase progress normally without warning indicators

3.6 WHEN displaying usernames that do not start with "u/" THEN the system SHALL CONTINUE TO render them as-is without any prefix modification

3.7 WHEN the strategy is approved THEN the system SHALL CONTINUE TO show normal status indicators without warning banners

3.8 WHEN assigned subreddits match actual activity THEN the system SHALL CONTINUE TO display them normally without mismatch indicators

3.9 WHEN existing table columns render without tooltip icons THEN the system SHALL CONTINUE TO function correctly for sorting, filtering, and data display

3.10 WHEN the Review Queue renders approved/rejected drafts THEN the system SHALL CONTINUE TO process them through the existing status workflow

3.11 WHEN the user selects a value from non-searchable dropdowns elsewhere in the UI THEN the system SHALL CONTINUE TO function as plain dropdowns where typeahead is not needed

3.12 WHEN CQS Level is manually set by an admin for a checked avatar THEN the system SHALL CONTINUE TO save and display the selected value correctly

3.13 WHEN the Import/Export dropdown is opened by clicking the trigger button THEN the system SHALL CONTINUE TO open and close via the trigger button click

3.14 WHEN single drafts appear in the Review Queue (one draft per thread) THEN the system SHALL CONTINUE TO display them as individual items without grouping

3.15 WHEN the Approve button is clicked THEN the system SHALL CONTINUE TO approve the draft and trigger the existing post-approval workflow

3.16 WHEN avatars with uniform subreddit counts are displayed THEN the system SHALL CONTINUE TO render table rows at their natural height

3.17 WHEN all posting configuration is complete THEN the system SHALL CONTINUE TO show "Active" or configured status in the Posting column

3.18 WHEN Health/AI Cost/CQS have actual checked values THEN the system SHALL CONTINUE TO display those values as they appear today

3.19 WHEN readiness checks show ✓ (pass) or ✗ (fail) THEN the system SHALL CONTINUE TO render those symbols with their current meaning

3.20 WHEN the overall Health score is displayed THEN the system SHALL CONTINUE TO calculate and render it correctly

3.21 WHEN non-technical Voice Profile content renders (the actual voice text) THEN the system SHALL CONTINUE TO display it as-is

3.22 WHEN users explicitly expand technical details THEN the system SHALL CONTINUE TO show full metadata (model, tokens, duration)

3.23 WHEN karma charts have complete data (all bars with corresponding dates) THEN the system SHALL CONTINUE TO render them correctly

3.24 WHEN 30d Delta and bar chart data are consistent THEN the system SHALL CONTINUE TO display both without modification

3.25 WHEN the user navigates away from pages without form changes THEN the system SHALL CONTINUE TO navigate without any confirmation dialogs

3.26 WHEN existing tooltips display correct content THEN the system SHALL CONTINUE TO show their current text without modification

3.27 WHEN the Live Pulse chart has data to display THEN the system SHALL CONTINUE TO render the chart visualization normally

3.28 WHEN Pipeline Stats shows non-zero values THEN the system SHALL CONTINUE TO display them with their current styling

3.29 WHEN subreddits display other tags (e.g. "pro", "target") THEN the system SHALL CONTINUE TO render them as-is

3.30 WHEN Phase Override is executed with a reason provided THEN the system SHALL CONTINUE TO apply the phase change and log it to the audit trail

3.31 WHEN entity links in Audit Logs point to valid entities THEN the system SHALL CONTINUE TO navigate to the correct detail pages

3.32 WHEN Audit Log entries have short, simple details THEN the system SHALL CONTINUE TO display them inline without requiring expansion

3.33 WHEN users manually apply custom filters to Audit Logs THEN the system SHALL CONTINUE TO respect those filter selections

3.34 WHEN paginated audit logs are browsed THEN the system SHALL CONTINUE TO load entries in chronological order with correct sorting
