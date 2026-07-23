# Implementation Plan

## Overview

Bugfix implementation for 5 QA Board UX issues following the exploratory bugfix workflow: write tests BEFORE fix to confirm bugs exist, write preservation tests to capture baseline behavior, implement the fix, then verify all tests pass.

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": ["1", "2"] },
    { "wave": 2, "tasks": ["3.1", "3.2", "3.3", "3.4", "3.5"] },
    { "wave": 3, "tasks": ["3.6", "3.7"] },
    { "wave": 4, "tasks": ["4"] }
  ]
}
```

## Tasks

- [x] 1. Write bug condition exploration tests
  - **Property 1: Bug Condition** - QA Board UX Defects (Optional Field Rejection + Missing Structured Fields)
  - **CRITICAL**: These tests MUST FAIL on unfixed code — failure confirms the bugs exist
  - **DO NOT attempt to fix the tests or the code when they fail**
  - **NOTE**: These tests encode the expected behavior — they will validate the fix when they pass after implementation
  - **GOAL**: Surface counterexamples that demonstrate the 5 bugs exist in the current code
  - **Scoped PBT Approach**: Focus on the two server-testable bugs (Bug 1 + Bug 4) as concrete failing cases
  - **Test file**: `tests/test_engineering_memory_route.py` (extend existing)
  - **Test framework**: pytest + TestClient (matching existing patterns)
  - Test 1a: POST `/api/report-issue` with `what_happened`, `where`, `actual_result` filled, `expected=""`, valid anti-bot fields → assert 200 with NO error message (Bug 1 — currently FAILS because server rejects with "'Expected?' is required")
  - Test 1b: POST `/api/report-issue` with `where="https://app.example.com/settings"` + valid anti-bot fields → query DB → assert `source_url == "https://app.example.com/settings"` (Bug 4 — currently FAILS because source_url is never populated from form)
  - Test 1c: POST `/api/report-issue` with `email="reporter@test.com"` + valid anti-bot fields → query DB → assert `reporter_email == "reporter@test.com"` (Bug 4 — currently FAILS because reporter_email column doesn't exist yet)
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests FAIL (this is correct — proves the bugs exist)
  - Document counterexamples found (validation error for empty expected, NULL source_url, missing reporter_email)
  - Mark task complete when tests are written, run, and failures are documented
  - _Requirements: 1.1, 1.4_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Form Submission & Anti-Bot Behavior Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - **Test file**: `tests/test_engineering_memory_route.py` (extend existing)
  - **Test framework**: pytest + TestClient (matching existing patterns)
  - Observe: POST with all fields filled (including expected="It should work") + valid anti-bot → creates BugReport with expected text in problem blob on unfixed code
  - Observe: POST with honeypot `website="http://spam.bot"` → returns 200 success page (silent rejection) on unfixed code
  - Observe: POST with `human_check="wrong"` → returns 200 success page (silent rejection) on unfixed code
  - Observe: POST with `form_ts` < 3 seconds ago → returns 200 success page (silent rejection) on unfixed code
  - Observe: POST with empty `what_happened` → returns error "'What happened?' is required" on unfixed code
  - Observe: POST with empty `where` → returns error "'Where?' is required" on unfixed code
  - Observe: POST with empty `actual_result` → returns error "'Actual result?' is required" on unfixed code
  - Write tests asserting these observed behaviors:
    - Test 2a: Full form with `expected="Button should save"` → success + "Expected: Button should save" in problem blob
    - Test 2b: Honeypot filled → 200 success page (no error, silent accept for bots)
    - Test 2c: JS challenge wrong → 200 success page (silent accept for bots)
    - Test 2d: Timing too fast (<3s) → 200 success page (silent accept for bots)
    - Test 2e: Empty `what_happened` → error message returned
    - Test 2f: Empty `where` → error message returned
    - Test 2g: Empty `actual_result` → error message returned
  - Verify all tests PASS on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.5, 3.6, 3.7_

- [x] 3. Fix for QA Board UX bugs (5 bugs)

  - [x] 3.1 Bug 1: Make "What was expected?" field optional
    - In `app/templates/report_issue.html`: remove `required` attribute from "expected" textarea
    - In `app/templates/report_issue.html`: remove `aria-required="true"` from "expected" textarea
    - In `app/templates/report_issue.html`: replace red asterisk `<span class="text-red-500" aria-label="required">*</span>` with `<span class="text-gray-400 text-xs font-normal">(optional)</span>` on the expected label
    - In `app/routes/engineering_memory.py`: remove the line `if not expected.strip(): errors.append("'Expected?' is required")`
    - _Bug_Condition: isBugCondition(input) where input.action == "submit_form" AND input.expected_field == ""_
    - _Expected_Behavior: form accepts submission, creates BugReport, returns success page_
    - _Preservation: when expected IS filled, its value still included in problem text blob_
    - _Requirements: 2.1, 3.1, 3.7_

  - [x] 3.2 Bug 2: Add environment badge to QA Board header line
    - In `app/templates/admin_qa_board.html`: add environment badge in the header `div` (the `flex items-center gap-2 mb-1` row) after the status badge
    - Badge colors: `bg-red-900/50 text-red-300` for "prod", `bg-yellow-900/50 text-yellow-300` for "staging", `bg-slate-700 text-gray-300` for "dev"
    - Remove the plain `<span>{{ bug.environment }}</span>` from the footer metadata line
    - _Bug_Condition: isBugCondition(input) where input.action == "view_qa_board" AND input.viewing == "environment_field"_
    - _Expected_Behavior: environment shown as colored badge in header line_
    - _Preservation: existing badges for bug_id, risk_level, category, status unchanged_
    - _Requirements: 2.2, 3.3_

  - [x] 3.3 Bug 3: Replace screenshot new-tab link with modal lightbox
    - In `app/templates/admin_qa_board.html`: replace `<a href="{{ bug.screenshot_url }}" target="_blank">` with a clickable element that triggers a modal
    - Add hidden modal overlay div at page bottom: dark backdrop, centered full-size image, close button (×), click-outside-to-dismiss
    - Add vanilla JS: `openScreenshotModal(url)` to show modal, close on ×/backdrop click/Escape key
    - _Bug_Condition: isBugCondition(input) where input.action == "click_screenshot" AND input.target == "thumbnail"_
    - _Expected_Behavior: full-size image in modal overlay, no new tab_
    - _Preservation: thumbnail still rendered, mouse clicks on other elements still work_
    - _Requirements: 2.3, 3.4_

  - [x] 3.4 Bug 4: Store structured fields (source_url + reporter_email)
    - In `app/models/bug_report.py`: add `reporter_email: Mapped[str | None] = mapped_column(String(200), nullable=True)`
    - Create Alembic migration: `alembic revision --autogenerate -m "add_reporter_email_to_bug_reports"` → adds `reporter_email` column
    - In `app/routes/engineering_memory.py` `report_issue_submit`: add `"source_url": where` to the `form_data` dict
    - In `app/routes/engineering_memory.py` `report_issue_submit`: add `"reporter_email": email` to the `form_data` dict
    - In `app/services/engineering_memory.py` `create_incident`: set `reporter_email=form_data.get("reporter_email")` on the BugReport constructor
    - In `app/templates/admin_qa_board.html` expandable details: add row for source_url (as clickable link if present)
    - In `app/templates/admin_qa_board.html` expandable details: add row for reporter_email (if present)
    - _Bug_Condition: isBugCondition(input) where input.action == "view_qa_board" AND input.viewing == "structured_fields"_
    - _Expected_Behavior: source_url populated from "where" field, reporter_email stored separately and visible_
    - _Preservation: "where" value still appears in problem text blob (backward compatibility)_
    - _Requirements: 2.4, 3.1_

  - [x] 3.5 Bug 5: Add clipboard paste support for screenshot upload
    - In `app/templates/report_issue.html`: add paste event listener on `document` that captures `event.clipboardData.items` for image types
    - Convert pasted blob to File, set on the file input using DataTransfer API
    - Show preview thumbnail below file input with a "Remove" button
    - Ensure pasted file submits as `screenshot` field in the multipart form
    - Add visual hint text below file input: "or paste from clipboard (Ctrl+V / Cmd+V)"
    - _Bug_Condition: isBugCondition(input) where input.action == "paste_clipboard" AND input.context == "report_form"_
    - _Expected_Behavior: pasted image captured, preview shown, attached for submission_
    - _Preservation: traditional file picker still works_
    - _Requirements: 2.5, 3.5_

  - [x] 3.6 Verify bug condition exploration tests now pass
    - **Property 1: Expected Behavior** - QA Board UX Defects Fixed
    - **IMPORTANT**: Re-run the SAME tests from task 1 — do NOT write new tests
    - The tests from task 1 encode the expected behavior (optional field accepted, source_url stored, reporter_email stored)
    - When these tests pass, it confirms the expected behavior is satisfied
    - Run bug condition exploration tests from step 1
    - **EXPECTED OUTCOME**: Tests PASS (confirms all server-side bugs are fixed)
    - _Requirements: 2.1, 2.4_

  - [x] 3.7 Verify preservation tests still pass
    - **Property 2: Preservation** - Form Submission & Anti-Bot Behavior Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run preservation tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tests still pass after fix (anti-bot, required field validation for what_happened/where/actual_result, expected-when-filled included in problem text)

- [x] 4. Checkpoint - Ensure all tests pass
  - Run full test suite: `pytest tests/test_engineering_memory.py tests/test_engineering_memory_route.py -v`
  - Ensure all exploration tests (task 1) now PASS
  - Ensure all preservation tests (task 2) still PASS
  - Ensure existing tests in `test_engineering_memory.py` still PASS (service unit tests)
  - Verify no regressions in existing route tests
  - Ask the user if questions arise


## Notes

- Bugs 2, 3, and 5 are template/JS-only changes that cannot be fully tested via pytest (require browser). They are covered by manual QA verification.
- Bugs 1 and 4 have server-side components that are fully testable via endpoint tests.
- The Alembic migration (task 3.4) must be run locally before tests that check `reporter_email` column.
- All tests use `TestClient` (sync) matching existing patterns in `test_engineering_memory_route.py`.
- Anti-bot tests verify that bots receive fake "success" response (silent rejection pattern preserved).
