# Implementation Plan

## Overview

This task list implements fixes for 42 UI/UX defects identified in the RAMP admin panel QA audit. Tasks are ordered by the bugfix exploration workflow: (1) write tests to confirm bugs exist, (2) write preservation tests, (3) implement fixes starting with shared components, (4) verify all tests pass. Shared components (modal, tooltip, dropdown, filter) are built first since multiple views depend on them.

## Task Dependency Graph

```json
{
  "waves": [
    {"tasks": ["1", "2"]},
    {"tasks": ["3"]},
    {"tasks": ["4"]},
    {"tasks": ["5", "6", "7", "8", "9"]},
    {"tasks": ["10"]},
    {"tasks": ["11"]}
  ]
}
```

## Tasks

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** — Admin UI Rendering Defects
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bugs exist
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bugs exist across all 12 bug categories
  - **Scoped PBT Approach**: Test the following concrete failing cases:
    - Template rendering: `render_username("u/SergeiMarshak")` produces `"u/u/SergeiMarshak"` (double prefix)
    - Data consistency: avatars list endpoint returns `active_count > total_count`
    - CQS default: avatar with `cqs_level=None` renders dropdown defaulting to "Highest"
    - Conditional UI: avatar with failed readiness checks renders auto-posting button as enabled
    - Karma formatting: raw number `6283184` displayed without abbreviation
    - Phase Override: POST to phase override endpoint with empty reason returns 200 (not 422)
    - Confirmation gates: "Delete All" button in audit logs has no modal (uses basic `confirm()`)
  - Test file: `tests/test_admin_ui_bug_conditions.py`
  - Use `pytest` + `hypothesis` for property-based generation of avatar states and render contexts
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct — it proves the bugs exist)
  - Document counterexamples found to understand root causes
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 2.1, 2.2, 2.3, 2.6, 2.12, 2.30, 2.35_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** — Existing Admin Panel Functionality Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - **Observe behavior on UNFIXED code for non-buggy inputs:**
    - Observe: HTMX partial swaps for avatar tabs return 200 with correct `Content-Type`
    - Observe: Admin CRUD operations (create/edit avatar, client, user) succeed and return expected responses
    - Observe: Pipeline controls (freeze/unfreeze, kill switches) function correctly
    - Observe: Role-based rendering (`is_avatar_manager` checks) produces correct HTML output
    - Observe: Pagination mechanics in audit logs preserve page/sort state via URL params
    - Observe: Username rendering for usernames NOT starting with "u/" produces correct output
    - Observe: CQS dropdown with actual set value (e.g., "medium") displays that value correctly
    - Observe: Auto-posting button enabled when ALL readiness checks pass
  - Test file: `tests/test_admin_ui_preservation.py`
  - Write property-based tests: for all non-bug-condition admin interactions, response matches original behavior
  - Verify test passes on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14, 3.15, 3.16, 3.17, 3.18, 3.19, 3.20, 3.21, 3.22, 3.23, 3.24, 3.25, 3.26, 3.27, 3.28, 3.29, 3.30, 3.31, 3.32, 3.33, 3.34_

- [x] 3. Shared Components — Confirmation Modal, Tooltip System, Searchable Dropdown

  - [x] 3.1 Create shared confirmation modal partial
    - Create `app/templates/partials/confirm_modal.html`
    - Accept parameters: `modal_id`, `title`, `message`, `confirm_text`, `cancel_text`, `action_url`, `method`
    - Dark theme styled (bg-slate-800, border-slate-700, text-white)
    - HTMX `hx-post` or form submission on confirm button
    - Close on cancel click, Escape key, and backdrop click
    - Accessible: `role="dialog"`, `aria-modal="true"`, focus trap
    - _Bug_Condition: isBugCondition(input) where input.action == "delete_all" AND NOT confirmation_shown_
    - _Expected_Behavior: confirmation modal displayed with entry count before destructive action executes_
    - _Preservation: Existing confirm() dialogs replaced, actual delete/freeze functionality unchanged_
    - _Requirements: 2.1, 2.39_

  - [x] 3.2 Create shared tooltip macro/partial
    - Create `app/templates/partials/tooltip.html` as Jinja2 macro
    - Macro signature: `{% macro tooltip(text, icon="ⓘ") %}`
    - Renders consistent icon with `title` attribute and styled hover popup
    - Dark theme compatible (bg-slate-700 tooltip background)
    - Accessible: `aria-label` on trigger, tooltip content readable by screen readers
    - _Bug_Condition: isBugCondition(input) where column_header.has_abbreviation AND NOT tooltip_exists_
    - _Expected_Behavior: meaningful tooltip text displayed on hover for all abbreviated headers_
    - _Preservation: Existing tooltip content in Review Queue preserved unchanged_
    - _Requirements: 2.9, 2.10, 2.15, 2.26, 2.29, 2.36_

  - [x] 3.3 Create searchable dropdown component
    - Create `app/static/js/searchable-dropdown.js`
    - Vanilla JS combobox (Alpine.js compatible if Alpine already loaded, else standalone)
    - Features: text input with dropdown list, filters on keyup, keyboard nav (arrow keys + Enter + Escape)
    - Progressive enhancement: works as plain `<select>` if JS disabled
    - Dark theme styling (bg-slate-800 dropdown, border-slate-600 input)
    - Accessible: `role="combobox"`, `aria-expanded`, `aria-activedescendant`
    - _Bug_Condition: isBugCondition(input) where filter_dropdown.options.length > 20 AND NOT searchable_
    - _Expected_Behavior: typing filters the options list; keyboard navigation supported_
    - _Preservation: Plain dropdowns elsewhere in UI continue to function as-is_
    - _Requirements: 2.11_

  - [x] 3.4 Create `humanize_number` Jinja2 filter
    - Register in `app/main.py` template environment setup
    - Logic: `< 1000` → as-is, `1000–999999` → "1.2K", `1000000+` → "6.3M"
    - Always round to 1 decimal place, strip trailing ".0" (e.g., "2K" not "2.0K")
    - Template usage: `{{ value | humanize_number }}` with `title="{{ value }}"` for full number on hover
    - Unit test: `tests/test_humanize_number.py` covering edge cases (0, 999, 1000, 1500, 999999, 1000000, -500)
    - _Bug_Condition: isBugCondition(input) where karma_value > 1000 AND display == raw_number_
    - _Expected_Behavior: abbreviated form displayed with full number on hover_
    - _Preservation: Numbers < 1000 displayed as-is_
    - _Requirements: 2.35_

  - [x] 3.5 Create unsaved changes detection script
    - Add to `app/templates/admin_base.html` (shared across all admin pages)
    - Track dirty state via `input`/`change` events on forms with `data-track-changes` attribute
    - `beforeunload` event listener warns when tracked fields have been modified
    - Skip warning for HTMX requests (check `htmx` in event or `HX-Request` header)
    - Minimal footprint: ~30 lines of vanilla JS
    - _Bug_Condition: isBugCondition(input) where has_unsaved_changes AND navigating_away AND NOT beforeunload_warning_
    - _Expected_Behavior: browser confirmation dialog shown when navigating away from dirty form_
    - _Preservation: Navigation without form changes proceeds without dialog_
    - _Requirements: 2.25_

- [x] 4. Data Computation & Backend Fixes

  - [x] 4.1 Fix active/total avatar count computation
    - File: `app/routes/admin.py` (avatars list endpoint)
    - Fix `total_count` to query ALL avatars in scope (not just filtered/active subset)
    - Ensure `active_count ≤ total_count` invariant always holds
    - Both counts must derive from the same base queryset with appropriate filters
    - _Bug_Condition: isBugCondition(input) where active_count > total_count_
    - _Expected_Behavior: mathematically consistent counts (active ≤ total)_
    - _Preservation: Correct querysets continue to show accurate counts_
    - _Requirements: 2.2_

  - [x] 4.2 Fix 30d Delta data consistency
    - File: `app/routes/admin.py` or `app/templates/admin_avatar_detail.html`
    - Ensure delta indicator value and bar chart data use same queryset and time window
    - Pass consistent data source to both the delta number and chart rendering
    - _Bug_Condition: isBugCondition(input) where delta == 0 AND chart shows activity bars_
    - _Expected_Behavior: delta value and chart bars reflect same underlying data_
    - _Preservation: When data is consistent, both render correctly_
    - _Requirements: 2.24_

  - [x] 4.3 Add Phase Override reason validation (backend)
    - File: `app/routes/admin.py` (phase override endpoint)
    - Add `reason` form field (required, non-empty after strip)
    - Return 422 with error message if reason is empty/missing
    - Store reason in audit log details JSON
    - _Bug_Condition: isBugCondition(input) where phase_override.submitted AND NOT reason_provided_
    - _Expected_Behavior: 422 returned for empty reason; reason stored in audit log_
    - _Preservation: Phase override with valid reason continues to work_
    - _Requirements: 2.30_

  - [x] 4.4 Add Review Queue thread grouping (backend)
    - File: `app/routes/admin.py` (review endpoint)
    - Group drafts by `thread_id` before passing to template
    - Pass grouped structure: `[{thread: ..., drafts: [...], count: N}, ...]`
    - Single-draft threads remain as individual items (no grouping indicator)
    - _Bug_Condition: isBugCondition(input) where multiple drafts for same thread shown as disconnected_
    - _Expected_Behavior: grouped structure with "N drafts for this thread" indicator_
    - _Preservation: Single drafts per thread displayed as individual items without grouping_
    - _Requirements: 2.14_

  - [x] 4.5 Add audit log default filter logic
    - File: `app/routes/admin.py` (audit logs endpoint)
    - Add `exclude_automated` query parameter (default `true`)
    - When enabled, filter out high-frequency automated actions (e.g., `scrape_completed`, `karma_tracked`)
    - Provide "Show All" / "Hide Automated" toggle that sets the parameter
    - _Bug_Condition: isBugCondition(input) where view dominated by scrape_completed entries_
    - _Expected_Behavior: automated actions hidden by default; toggle available_
    - _Preservation: Manual custom filters still respected_
    - _Requirements: 2.33_

- [x] 5. Template Fixes — Avatar Detail View

  - [x] 5.1 Fix double username prefix
    - File: `app/templates/admin_avatar_detail.html` + breadcrumb partial
    - Change `u/{{ avatar.reddit_username }}` to conditional:
      `{% if avatar.reddit_username.startswith('u/') %}{{ avatar.reddit_username }}{% else %}u/{{ avatar.reddit_username }}{% endif %}`
    - Apply in both header and breadcrumb locations
    - _Bug_Condition: isBugCondition(input) where username.startswith("u/") AND rendered.startswith("u/u/")_
    - _Expected_Behavior: "u/SergeiMarshak" rendered (no double prefix)_
    - _Preservation: Usernames not starting with "u/" continue to get prefix added_
    - _Requirements: 2.6_

  - [x] 5.2 Fix CQS dropdown default for unchecked avatars
    - File: `app/templates/admin_avatar_detail.html`
    - If `avatar.cqs_level is none` or status is "NOT_CHECKED", default to placeholder "— Not Checked —"
    - Add disabled placeholder `<option>` at top when condition met
    - _Bug_Condition: isBugCondition(input) where cqs_never_checked AND cqs_dropdown.default == "Highest"_
    - _Expected_Behavior: placeholder "— Not Checked —" shown as default_
    - _Preservation: CQS Level manually set by admin displays correctly_
    - _Requirements: 2.12_

  - [x] 5.3 Disable auto-posting button when readiness checks fail
    - File: `app/templates/admin_avatar_detail.html`
    - Wrap button in `{% if readiness_all_pass %}...{% else %}disabled{% endif %}`
    - Disabled state: `opacity-50 cursor-not-allowed` + `disabled` attribute
    - Add message below: "N checks must pass before enabling auto-posting"
    - _Bug_Condition: isBugCondition(input) where failed_checks > 0 AND autopost_button.enabled_
    - _Expected_Behavior: button disabled with explanation when checks fail_
    - _Preservation: Button enabled and functional when all checks pass_
    - _Requirements: 2.3_

  - [x] 5.4 Add Goals section labels
    - File: `app/templates/admin_avatar_detail.html`
    - Change bare "→ 80, → 3, → 85" to "Karma → 80", "Posts → 3", "Health → 85%"
    - _Requirements: 2.4_

  - [x] 5.5 Add Phase overdue warning badge
    - File: `app/templates/admin_avatar_detail.html`
    - Add `{% if phase_days > phase_expected %}` → "⚠️ OVERDUE by N days" badge
    - Visible on both Workflow and Overview tabs
    - _Requirements: 2.5_

  - [x] 5.6 Remove DB metadata from Voice Profile
    - File: `app/templates/admin_avatar_detail.html`
    - Remove "DB type: TEXT (unlimited)" line from Voice Profile rendering
    - _Requirements: 2.21_

  - [x] 5.7 Collapse Strategy technical metadata
    - File: `app/templates/admin_avatar_detail.html`
    - Wrap LLM model name, token counts, generation duration in `<details>` tag
    - Summary text: "Technical Details" (collapsed by default)
    - _Requirements: 2.22_

  - [x] 5.8 Add Phase Override reason field (frontend)
    - File: `app/templates/admin_avatar_detail.html`
    - Add required `<textarea>` for reason in Phase Override form
    - Disable submit button until reason has content (JS or `required` attribute)
    - _Requirements: 2.30_

  - [x] 5.9 Health sub-scores display improvement
    - Show as "7/10" format with brief explanation of how sub-scores combine
    - _Requirements: 2.20_

  - [x] 5.10 Karma chart x-axis labels and inline values
    - Ensure all bars have x-axis date labels and inline value labels on each bar
    - _Requirements: 2.23_

  - [x] 5.11 Surface strategy warning on Workflow tab
    - Add "Strategy not approved" banner on Workflow tab (default landing tab)
    - _Requirements: 2.7_

  - [x] 5.12 Add subreddit mismatch indicator
    - Show "Activity detected in N subreddits not in assignment list" when mismatch exists
    - _Requirements: 2.8_

  - [x] 5.13 Readiness symbols clarification
    - Replace ○ with explicit "Pending" text label
    - _Requirements: 2.19_

  - [x] 5.14 Posting "Missing" explanation
    - Change "Missing" to "Missing: {specific items}" (e.g., "Missing: proxy, credentials")
    - _Requirements: 2.17_

  - [x] 5.15 Health/AI Cost/CQS state distinction
    - Distinguish "Not Checked" vs "Error" vs "N/A" with distinct badge styles
    - _Requirements: 2.18_

  - [x] 5.16 Oldest Draft date format
    - Show "29 days (May 5, 2026)" format instead of just "692h"
    - _Requirements: 2.38_

  - [x] 5.17 Strategy questions label rename
    - Change "Questions for Client" to "Questions to Define Strategy"
    - _Requirements: 2.40_

  - [x] 5.18 Version History diff view
    - Add visual diff (highlight changed lines) between strategy versions
    - _Requirements: 2.42_

- [x] 6. Template Fixes — Avatars List View

  - [x] 6.1 Apply tooltips to all column headers
    - Add tooltip macro calls for: CQS, Health, Phase, Pool, AI Cost, Posting, Profile %
    - Import tooltip macro from `partials/tooltip.html`
    - Tooltip content: CQS="Comment Quality Score", Health="Shadowban/suspension detection score", etc.
    - _Requirements: 2.9_

  - [x] 6.2 Apply `humanize_number` filter to karma displays
    - Replace raw karma numbers with `{{ karma | humanize_number }}` + `title="{{ karma }}"`
    - _Requirements: 2.35_

  - [x] 6.3 Consistent row heights for karma breakdowns
    - Add `max-h-20 overflow-y-auto` to subreddit karma breakdown cells
    - _Requirements: 2.16_

  - [x] 6.4 Profile % tooltip
    - Add tooltip to 0% red badge: "Percentage of Reddit profile fields completed"
    - _Requirements: 2.36_

  - [x] 6.5 Apply searchable dropdown to subreddit filter
    - Replace `r/all` plain `<select>` with searchable combobox component
    - _Requirements: 2.11_

- [x] 7. Template Fixes — Review Queue

  - [x] 7.1 Apply thread grouping template
    - Render grouped drafts from backend (task 4.4)
    - Multi-draft threads: show "N drafts for this thread" indicator with indented sub-items
    - Single drafts: render as individual items (unchanged)
    - _Requirements: 2.14_

  - [x] 7.2 Add tooltips to badges and action icons
    - ALERT badge → "Requires immediate attention"
    - push:hard → "Aggressive engagement strategy"
    - P1/P2 → "Priority 1 (highest) / Priority 2"
    - Action icons: ✗ → "Reject", ✎ → "Edit", ↕ → "Change Status"
    - _Requirements: 2.10, 2.15_

  - [x] 7.3 Apply searchable dropdown to avatar/subreddit filters
    - Replace `u/all` and `r/all` plain dropdowns with searchable combobox
    - _Requirements: 2.11_

  - [x] 7.4 Hide redundant "Showing" stat
    - When no filter active and Showing == Total Pending, hide "Showing: N"
    - _Requirements: 2.37_

  - [x] 7.5 "hob" tag tooltip
    - Add tooltip to "hob" tags: "Hobby subreddit"
    - _Requirements: 2.29_

- [x] 8. Template Fixes — Audit Logs

  - [x] 8.1 Replace basic confirm() with confirmation modal
    - Replace `onsubmit="return confirm(...)"` on "Delete All" with shared modal (task 3.1)
    - Modal message: "Are you sure you want to delete all N log entries? This cannot be undone."
    - _Requirements: 2.1_

  - [x] 8.2 Render entity IDs as clickable links
    - Change raw UUIDs to `<a href="/admin/{entity_type}s/{entity_id}">` links
    - Handle entity types: avatar, client, user, thread
    - _Requirements: 2.31_

  - [x] 8.3 Structured JSON display for details column
    - Replace raw truncated JSON with formatted key-value rendering
    - Use `<details>` with collapsed expandable content for long entries
    - Short entries (< 3 keys): display inline without expansion
    - _Requirements: 2.32_

  - [x] 8.4 Add "Hide Automated" toggle (default on)
    - Toggle control in filter bar, synced with backend `exclude_automated` param (task 4.5)
    - URL parameter preserved on page navigation
    - _Requirements: 2.33_

  - [x] 8.5 Ensure pagination controls are always visible
    - Verify `pagination.total_pages > 1` renders page numbers + next/prev buttons
    - Fix any conditional that might hide pagination when entries exist
    - _Requirements: 2.34_

- [x] 9. Template Fixes — Empty States, Charts, Polish

  - [x] 9.1 Live Pulse empty state
    - When no data: display "No activity recorded yet — waiting for pipeline data"
    - _Requirements: 2.27_

  - [x] 9.2 Pipeline Stats color legend
    - Add legend below stats explaining what each color represents
    - _Requirements: 2.28_

  - [x] 9.3 Freeze Avatar confirmation modal
    - Apply shared confirmation modal to both "Freeze Avatar" button locations
    - Message: "Freezing this avatar will stop all automated posting and pipeline activity. Continue?"
    - _Requirements: 2.39_

  - [x] 9.4 Import/Export dropdown close on outside click
    - Add document `click` event listener to close Import/Export dropdown when clicking outside
    - _Requirements: 2.13_

  - [x] 9.5 Fix orphan tooltips
    - Audit tooltip anchoring; fix "Post upvotes" tooltip appearing on unrelated elements
    - Ensure each `title` attribute is on the correct trigger element
    - _Requirements: 2.41_

  - [x] 9.6 Add `data-track-changes` to forms with Save buttons
    - Add attribute to forms in avatar detail, client detail, and settings pages
    - Connects to unsaved changes detection script (task 3.5)
    - _Requirements: 2.25_

- [x] 10. Fix verification and validation

  - [x] 10.1 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** — Admin UI Rendering Defects Fixed
    - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bugs are fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.6, 2.12, 2.30, 2.35_

  - [x] 10.2 Verify preservation tests still pass
    - **Property 2: Preservation** — Existing Admin Panel Functionality Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tests still pass after fix (no regressions)

- [x] 11. Checkpoint — Ensure all tests pass
  - Run full test suite: `pytest tests/ -v`
  - Verify no regressions in existing admin panel tests
  - Verify both property-based test files pass (bug condition + preservation)
  - Verify `humanize_number` unit tests pass
  - Ask the user if questions arise

## Notes

- Platform: Python/FastAPI + Jinja2 + HTMX + Tailwind CSS
- Templates: `app/templates/` with partials in `app/templates/partials/`
- Admin panel uses dark theme (`admin_base.html`)
- Test framework: pytest + hypothesis for property-based tests
- Shared components (task 3) must be completed before consumer tasks (5-9)
- Backend fixes (task 4) must be completed before templates that depend on them
- Tasks 1 and 2 run on UNFIXED code and must be written first
