# QA Board UX Fixes — Bugfix Design

## Overview

Five UX/functional bugs affecting the Report Issue form (`/report-issue`) and QA Board (`/admin/qa-board`). The bugs range from unnecessary form validation (required "expected" field), missing visual hierarchy (environment badge), poor UX patterns (screenshot opens new tab), data loss (structured fields not stored/displayed), and missing input capability (no clipboard paste for screenshots). The fix approach is surgical — minimal changes to existing templates, routes, and services without architectural restructuring.

## Glossary

- **Bug_Condition (C)**: The set of user interactions that trigger incorrect behavior — form rejection on empty "expected" field, environment shown as plain text, screenshot opening in new tab, structured fields missing from display, clipboard paste not captured
- **Property (P)**: The desired behavior — optional field accepted, colored environment badge, modal lightbox, structured field display, clipboard paste with preview
- **Preservation**: Existing form submission flow, anti-bot protection, HTMX status updates, file picker upload, badge rendering for bug_id/risk_level/category/status
- **`report_issue_submit`**: The POST handler in `app/routes/engineering_memory.py` that validates and saves bug reports
- **`create_incident`**: The service function in `app/services/engineering_memory.py` that builds the BugReport record
- **`_build_problem_text`**: Helper that concatenates form fields into the `problem` text blob
- **QA Board**: The admin dashboard at `/admin/qa-board` rendered by `admin_qa_board.html`

## Bug Details

### Bug Condition

The bugs manifest across two user journeys: (1) reporters submitting the issue form, and (2) QA reviewers using the admin QA Board. Five independent conditions trigger incorrect behavior.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type UserInteraction
  OUTPUT: boolean
  
  RETURN (input.action == "submit_form" AND input.expected_field == "")
         OR (input.action == "view_qa_board" AND input.viewing == "environment_field")
         OR (input.action == "click_screenshot" AND input.target == "thumbnail")
         OR (input.action == "view_qa_board" AND input.viewing == "structured_fields")
         OR (input.action == "paste_clipboard" AND input.context == "report_form")
END FUNCTION
```

### Examples

- **Bug 1**: Reporter fills what_happened, where, actual_result but leaves "expected" empty → form rejects with "'Expected?' is required" error. Expected: submission succeeds.
- **Bug 2**: QA reviewer sees "prod" as tiny gray text in footer line of bug card → hard to spot critical production bugs. Expected: red badge in header line.
- **Bug 3**: QA reviewer clicks screenshot thumbnail → new tab opens with full image, losing QA Board context. Expected: modal overlay within page.
- **Bug 4**: Bug report stores "where" concatenated into `problem` text, email embedded in `reporter` string, `source_url` field never populated → QA reviewer cannot filter/sort by URL or see email separately. Expected: `source_url` populated from "where", email shown separately.
- **Bug 5**: Reporter copies screenshot, presses Cmd+V on form → nothing happens. Expected: image captured with preview shown.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Form submission with all fields filled (what_happened, where, actual_result) must continue to create BugReport and show success
- Anti-bot protection (honeypot + JS challenge + timing) must continue to reject bot submissions silently
- Existing badge display for bug_id, risk_level, category, and status must continue rendering with current colors
- HTMX inline status update (select + comment + update button) must continue working
- Traditional file picker for screenshot selection must continue working
- Platform_admin role requirement for QA Board access must continue being enforced
- When "expected" field IS filled, its value must still be included in the problem text blob
- The `where` field value must still appear in the problem text (for backward compatibility with existing reports)
- Mouse clicks on all existing QA Board elements must continue working

**Scope:**
All inputs unrelated to the 5 bug conditions should be completely unaffected. This includes:
- All other form fields (what_happened, where, actual_result, email)
- All admin panel navigation and routing
- All existing Celery tasks and background processing
- All other templates and pages

## Hypothesized Root Cause

Based on code review of the actual source files:

1. **Bug 1 — Required "expected" field**: 
   - Template has `required` attribute + `aria-required="true"` on the textarea
   - Label has red asterisk `<span class="text-red-500">*</span>`
   - Server-side validation in `report_issue_submit` has explicit check: `if not expected.strip(): errors.append("'Expected?' is required")`
   - Root cause: Over-specification during initial implementation — field was marked required at all 3 layers

2. **Bug 2 — Environment not prominent**:
   - In `admin_qa_board.html`, environment is rendered as `<span>{{ bug.environment }}</span>` inside the footer `div` with `text-xs text-gray-500`
   - Header line has badges for bug_id, risk_level, category, status — but NOT environment
   - Root cause: Environment was treated as metadata rather than a priority triage signal

3. **Bug 3 — Screenshot opens new tab**:
   - Template uses `<a href="{{ bug.screenshot_url }}" target="_blank">` wrapping the thumbnail
   - No modal/lightbox JavaScript exists in the template
   - Root cause: Simplest implementation chosen during initial build — no overlay was implemented

4. **Bug 4 — Structured fields not stored/displayed**:
   - `create_incident` passes `form_data.get("source_url")` but the route never sets `source_url` in form_data — it passes `where` separately
   - `_build_reporter` concatenates name + email + role into a single string
   - The model has `source_url` field (String(500)) but it's never populated from form submission
   - QA Board template doesn't display `source_url` or separate email
   - Root cause: Data mapping gap — form "where" field wasn't mapped to model's `source_url`; email stored only in concatenated `reporter` string

5. **Bug 5 — No clipboard paste**:
   - Template only has `<input type="file" id="screenshot" name="screenshot" accept="image/*">`
   - No JavaScript listener for paste events
   - Root cause: Feature was never implemented — only file picker was built

## Correctness Properties

Property 1: Bug Condition - Optional Expected Field Acceptance

_For any_ form submission where `what_happened`, `where`, and `actual_result` are non-empty but `expected` is empty, the fixed `report_issue_submit` handler SHALL accept the submission, create a BugReport record, and return the success confirmation page.

**Validates: Requirements 2.1**

Property 2: Bug Condition - Environment Badge Display

_For any_ bug report displayed on the QA Board, the environment value SHALL be rendered as a colored badge in the header line (same row as bug_id, risk_level, category, status) with colors: prod=red background, staging=yellow background, dev=gray background.

**Validates: Requirements 2.2**

Property 3: Bug Condition - Screenshot Modal Overlay

_For any_ click on a screenshot thumbnail in the QA Board, the system SHALL display the full-size image in a modal overlay within the page (with close button and click-outside-to-dismiss) WITHOUT opening a new tab or navigating away.

**Validates: Requirements 2.3**

Property 4: Bug Condition - Structured Field Storage and Display

_For any_ bug report created from the form, the `source_url` field on the BugReport model SHALL be populated from the form's "where" value, the reporter email SHALL be displayed separately in the QA Board details section, and the source_url SHALL be shown as a visible field on the QA Board.

**Validates: Requirements 2.4**

Property 5: Bug Condition - Clipboard Paste Screenshot

_For any_ clipboard paste event (Cmd+V / Ctrl+V) containing an image while the report-issue form is active, the system SHALL capture the pasted image, display a preview thumbnail, and attach it as the screenshot for form submission.

**Validates: Requirements 2.5**

Property 6: Preservation - Form Submission with All Fields

_For any_ form submission where all fields including `expected` are filled AND anti-bot checks pass, the fixed code SHALL produce the same result as the original code — creating a BugReport with the expected text included in the problem blob.

**Validates: Requirements 3.1, 3.5, 3.7**

Property 7: Preservation - Anti-Bot and Security

_For any_ form submission that fails honeypot, JS challenge, or timing checks, the fixed code SHALL produce the same silent rejection as the original code, preserving all anti-bot behavior.

**Validates: Requirements 3.2, 3.6**

Property 8: Preservation - QA Board Existing Functionality

_For any_ interaction with existing QA Board features (badge rendering, HTMX status updates, filtering), the fixed code SHALL produce exactly the same behavior as the original code.

**Validates: Requirements 3.3, 3.4**

## Fix Implementation

### Changes Required

**File**: `app/templates/report_issue.html`

**Changes for Bug 1 (optional expected field)**:
1. Remove `required` attribute from the "expected" textarea
2. Remove `aria-required="true"` from the "expected" textarea
3. Remove red asterisk `<span class="text-red-500" aria-label="required">*</span>` from the label
4. Add "(optional)" hint text like the email field has

**Changes for Bug 5 (clipboard paste)**:
1. Add a paste event listener on the document/form that captures image data from `event.clipboardData`
2. Create a `DataTransfer` / set the file input's files from the pasted blob
3. Show a preview thumbnail below the file input when paste succeeds
4. Ensure the pasted file is submitted as `screenshot` field in the multipart form

---

**File**: `app/routes/engineering_memory.py`

**Changes for Bug 1 (remove server-side validation)**:
1. Remove the line: `if not expected.strip(): errors.append("'Expected?' is required")`

**Changes for Bug 4 (structured field mapping)**:
1. In `form_data` dict construction, add `"source_url": where` to map the "where" field to `source_url`
2. Add `"email": email` explicitly to form_data (already present — but ensure service uses it)

---

**File**: `app/services/engineering_memory.py`

**Changes for Bug 4 (store source_url and email separately)**:
1. In `create_incident`, ensure `source_url` is set from `form_data.get("source_url")` (already coded but source_url was never in form_data — fixed by route change)
2. Add `reporter_email` field storage — the model needs a new column OR we store email in an existing unused field. Since `BugReport` doesn't have a dedicated `reporter_email` column, we'll store email in the existing data flow and extract it on display. Actually, looking at the model, `reporter` already contains the email. We'll add a helper property or pass email separately to the template context.

---

**File**: `app/models/bug_report.py`

**Changes for Bug 4**:
1. Add `reporter_email` column: `reporter_email: Mapped[str | None] = mapped_column(String(200), nullable=True)` — stores email separately for direct display

---

**File**: `app/templates/admin_qa_board.html`

**Changes for Bug 2 (environment badge)**:
1. Add environment badge in the header line (the `div` with `flex items-center gap-2 mb-1`) after the status badge
2. Use conditional colors: `bg-red-900/50 text-red-300` for prod, `bg-yellow-900/50 text-yellow-300` for staging, `bg-slate-700 text-gray-300` for dev
3. Remove the plain `<span>{{ bug.environment }}</span>` from the footer line

**Changes for Bug 3 (screenshot modal)**:
1. Replace `<a href="..." target="_blank">` wrapper with a clickable element that opens a modal
2. Add a modal overlay `<div>` (hidden by default) with the full-size image, close button, and click-outside-to-dismiss
3. Add minimal vanilla JS to show/hide the modal

**Changes for Bug 4 (display structured fields)**:
1. In the expandable details section, add a row for `source_url` (as a clickable link if it looks like a URL)
2. Add a row for reporter email (separate from the reporter name/role display)
3. Show source_url in the bug card metadata area

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bugs on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bugs BEFORE implementing the fix. Confirm or refute the root cause analysis.

**Test Plan**: Write endpoint tests that submit forms and render templates to observe the incorrect behavior on unfixed code.

**Test Cases**:
1. **Optional Expected Field Test**: POST to `/api/report-issue` with empty `expected` field, valid other fields → observe 200 with error message (will fail on unfixed code — returns validation error)
2. **Environment Badge Test**: GET `/admin/qa-board` with bugs in DB → parse HTML, check environment is NOT in header badge row (confirms current incorrect rendering)
3. **Screenshot Link Test**: GET `/admin/qa-board` with screenshot bug → parse HTML, confirm `target="_blank"` on screenshot link (confirms new-tab behavior)
4. **Source URL Storage Test**: POST `/api/report-issue` with `where="https://app.example.com/page"` → query DB, confirm `source_url` is NULL (demonstrates data loss on unfixed code)

**Expected Counterexamples**:
- Form submission with empty expected field returns error instead of success
- Environment displayed as plain text in footer instead of colored badge in header
- Screenshot thumbnail wrapped in `<a target="_blank">` instead of modal trigger
- `source_url` field is NULL after form submission despite "where" being filled

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := fixedHandler(input)
  ASSERT expectedBehavior(result)
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT originalHandler(input) = fixedHandler(input)
END FOR
```

**Testing Approach**: Example-based tests are most appropriate here because:
- The input domain is bounded (form fields, template contexts)
- Preservation is about specific existing flows (anti-bot, HTMX updates)
- Template rendering is deterministic given the same context

**Test Plan**: Observe behavior on UNFIXED code for normal form submissions and QA Board rendering, then write tests that verify these behaviors continue after the fix.

**Test Cases**:
1. **Full Form Submission Preservation**: Submit form with ALL fields filled (including expected) → verify BugReport created with expected text in problem blob
2. **Anti-Bot Preservation**: Submit form with honeypot filled → verify silent acceptance (no error shown to bot)
3. **HTMX Status Update Preservation**: POST to `/admin/qa-board/{bug_id}/status` → verify HTML response with updated status
4. **File Picker Preservation**: Submit form with file upload via traditional input → verify screenshot saved and URL stored
5. **Existing Badges Preservation**: GET `/admin/qa-board` → verify bug_id, risk_level, category, status badges still render correctly

### Unit Tests

- Test `report_issue_submit` accepts empty `expected` field without error
- Test `report_issue_submit` still rejects empty `what_happened`, `where`, `actual_result`
- Test `create_incident` stores `source_url` from form_data
- Test `create_incident` stores `reporter_email` from form_data
- Test `_build_problem_text` still includes `expected` when provided
- Test `_build_problem_text` gracefully handles empty `expected`

### Property-Based Tests

Not recommended for this bugfix — the input domain is well-bounded and the bugs are deterministic UI/validation issues. Example-based tests provide sufficient coverage.

### Integration Tests

- Test full form submission flow (GET form → fill → POST → verify success page + DB record)
- Test QA Board rendering with multiple bugs of different environments (verify badge colors)
- Test screenshot modal interaction (would require browser testing — document as manual QA)
- Test clipboard paste (requires browser testing — document as manual QA)
