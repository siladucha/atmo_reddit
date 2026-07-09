# Implementation Plan

## Overview

Fix the client portal Community Tone section to display user-friendly error messages when emotional profile analysis fails, instead of showing the misleading "pending" state. The admin side is already partially fixed. This spec targets `app/routes/portal_risk_profile.py` and `app/templates/client/subreddit_risk_profile.html`.

## Tasks

- [ ] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Client Portal Shows "Pending" When Error Exists
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: For any subreddit where `emotional_profile_error` is non-NULL/non-empty AND `emotional_profile` is NULL, the rendered client portal Community Tone section should contain a user-friendly error message (not "pending")
  - Test setup: create a subreddit with `emotional_profile_error` set to various error strings (PRAW error, insufficient data, LLM error, schema validation) and `emotional_profile` = NULL
  - Render the portal risk profile page via test client
  - Assert response contains "Tone analysis unavailable" or equivalent error state heading
  - Assert response does NOT contain "Community tone analysis pending" when error exists
  - Assert response contains a sanitized user-friendly message (not raw Python exception)
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (template has no error branch, always shows "pending" for missing profile)
  - Document counterexamples: template context lacks `emotional_profile_error` key, route never reads error from Subreddit model
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.3, 2.1, 2.3_

- [ ] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Successful Profile and Never-Analyzed States Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - Observe on UNFIXED code: subreddit with valid `emotional_profile` JSONB renders full Community Tone display (formality, humor, expertise, dominant emotions, summary)
  - Observe on UNFIXED code: subreddit with both `emotional_profile` NULL and `emotional_profile_error` NULL renders "Community tone analysis pending" state
  - Observe on UNFIXED code: subreddit with valid `emotional_profile` AND `emotional_profile_error` set still renders the full profile (success takes priority)
  - Write property-based test: for all subreddits where `emotional_profile_error` is NULL (success case or never-analyzed case), the rendered output matches the original code behavior
  - Generate random valid emotional profile dicts and verify template rendering includes expected fields
  - Verify the admin-side GET handler (`admin_get_emotional_profile_partial`) still shows raw error + "Run Analysis" button (unchanged)
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3_

- [ ] 3. Fix for client portal emotional profile error display

  - [ ] 3.1 Add error sanitization helper to portal_risk_profile.py
    - Create function `_sanitize_emotional_profile_error(raw_error: str) -> str` in `app/routes/portal_risk_profile.py`
    - Map error prefixes to user-friendly messages:
      - `"Reddit API error:"` → "This subreddit is currently unreachable for analysis."
      - `"Insufficient data:"` → "Not enough community activity to analyze tone yet."
      - `"LLM error:"` → "Tone analysis is temporarily unavailable. Will retry automatically."
      - `"Schema validation failed:"` → "Analysis produced unexpected results. Will retry automatically."
      - Default/unknown → "Tone analysis encountered an issue. Will retry on next weekly run."
    - Ensure no raw Python exception details, tracebacks, or file paths are ever exposed
    - _Bug_Condition: isBugCondition(input) where input.subreddit.emotional_profile_error IS NOT NULL AND input.subreddit.emotional_profile IS NULL AND input.page == "client_risk_profile"_
    - _Expected_Behavior: sanitized user-friendly message displayed instead of generic "pending"_
    - _Preservation: When emotional_profile_error is NULL, behavior unchanged_
    - _Requirements: 2.1, 2.3_

  - [ ] 3.2 Pass sanitized error to template context in portal_risk_profile.py
    - In `portal_subreddit_risk_profile()` route handler, read `subreddit.emotional_profile_error` from the already-loaded subreddit object
    - If error exists, call `_sanitize_emotional_profile_error()` on it
    - Add `"emotional_profile_error": sanitized_error` to the template context dict passed to `subreddit_risk_profile.html`
    - If no error, pass `"emotional_profile_error": None`
    - _Bug_Condition: route currently never reads subreddit.emotional_profile_error — template context lacks error variable_
    - _Expected_Behavior: template context always includes emotional_profile_error (None or sanitized string)_
    - _Preservation: All other template context variables unchanged_
    - _Requirements: 2.1, 2.3_

  - [ ] 3.3 Add error state branch to subreddit_risk_profile.html template
    - In `app/templates/client/subreddit_risk_profile.html`, locate the Community Tone section
    - Between `{% if emotional_profile %}` (success block) and `{% else %}` (pending block), insert `{% elif emotional_profile_error %}`
    - Error state UI: warning icon (⚠️), heading "Tone analysis unavailable", the sanitized error message, note "Analysis retries automatically each week"
    - Keep the existing `{% else %}` block unchanged as final fallback for never-analyzed state
    - _Bug_Condition: template currently has only two states (profile exists OR pending) — no error branch_
    - _Expected_Behavior: three-state template: success → error → pending_
    - _Preservation: success block and pending block unchanged_
    - _Requirements: 2.1, 2.3, 3.1, 3.2_

  - [ ] 3.4 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Error State Displayed on Client Portal
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior (error state shown instead of "pending")
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed — error state now rendered)
    - _Requirements: 2.1, 2.3_

  - [ ] 3.5 Verify preservation tests still pass
    - **Property 2: Preservation** - Successful Profile and Never-Analyzed States Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions — success and pending states unchanged)
    - Confirm all tests still pass after fix (no regressions)

- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Admin-side fix is ALREADY applied in `app/routes/admin.py` (GET handler shows error, POST handler validates) — do not modify
- No new models or migrations required — `emotional_profile_error` field already exists on Subreddit model
- Two main files to change: `app/routes/portal_risk_profile.py` and `app/templates/client/subreddit_risk_profile.html`
- Error sanitization prevents leaking raw Python exceptions (tracebacks, file paths, internal model names) to client-facing pages
- The `emotional_profile` data comes from a separate raw SQL query (subreddit_emotional_profiles table), while `emotional_profile_error` is on the Subreddit model — route already has the subreddit object loaded
- Edge case: if both `emotional_profile` and `emotional_profile_error` are set, profile data wins (success takes priority over stale error)

## Task Dependency Graph

```json
{
  "waves": [
    ["1", "2"],
    ["3.1"],
    ["3.2"],
    ["3.3"],
    ["3.4", "3.5"],
    ["4"]
  ]
}
```
