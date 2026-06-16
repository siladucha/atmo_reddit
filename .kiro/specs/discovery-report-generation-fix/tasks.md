# Implementation Plan

## Overview

Fix the `research_progress` endpoint to include `can_generate_report` and `is_max_iterations` in the template context when rendering `discovery_results.html` after all research completes. Uses the bug condition methodology: explore the bug with property tests, verify preservation of non-buggy behavior, implement the fix, then validate.

## Tasks

- [ ] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Missing Context Variables in Research Progress Completion
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: Scope the property to the concrete failing case: any session where `research_progress` has all values == "complete" and at least one confirmed hypothesis
  - Bug Condition: `isBugCondition(input)` returns True when all values in `session.session_metadata["research_progress"]` are "complete" AND `len(progress) > 0`
  - Test that `GET /admin/discovery/{session_id}/progress` when `all_done == True` includes `can_generate_report` and `is_max_iterations` in the template context
  - Generate random sessions with all-complete research progress (varying hypothesis counts, iteration numbers 1-5, mix of confirmed/rejected hypotheses)
  - Assert that the rendered response contains the "Generate Report" button markup when at least one hypothesis is confirmed
  - Assert that when `current_iteration >= 5`, the response does NOT show "Next Iteration" controls
  - Run test on UNFIXED code - expect FAILURE (this confirms the bug exists)
  - **EXPECTED OUTCOME**: Test FAILS because `can_generate_report` is not in the template context, so the "Generate Report" button never renders
  - Document counterexamples found (e.g., "Session with 3 confirmed hypotheses, all research complete, but response HTML lacks Generate Report button")
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 2.1, 2.2, 2.3_

- [ ] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Non-Completion Polling Behavior Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - Observe: when `research_progress` has at least one non-"complete" value, `GET /{session_id}/progress` returns `discovery_research_progress.html` partial with `session`, `hypotheses`, and `progress` in context
  - Observe: when `research_progress` is empty (`{}`), endpoint returns `discovery_research_progress.html` partial
  - Observe: `decide_hypotheses` endpoint (`POST /{session_id}/decide`) already passes `can_generate_report` and `is_max_iterations` to `discovery_results.html`
  - Write property-based test: for all session states where NOT all research is complete (random mixes of "queued", "researching", "complete" with at least one non-"complete"), the endpoint returns the progress partial template with correct context keys (`session`, `hypotheses`, `progress`)
  - Write property-based test: for empty progress dicts, endpoint returns progress partial
  - Write unit test: `decide_hypotheses` still passes `can_generate_report` and `is_max_iterations` after fix (regression check)
  - Verify all preservation tests PASS on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [ ] 3. Fix for missing template context variables in research_progress endpoint

  - [ ] 3.1 Implement the fix
    - In `reddit_saas/app/routes/discovery.py`, locate the `research_progress` endpoint's `if all_done:` branch (~line 590)
    - Add `"can_generate_report": SessionManager.can_generate_report(session)` to the template context dict
    - Add `"is_max_iterations": SessionManager.is_at_max_iterations(session)` to the template context dict
    - No other files require changes — `SessionManager` methods already exist and are imported
    - _Bug_Condition: isBugCondition(input) where all values in session.session_metadata["research_progress"] are "complete" and len(progress) > 0_
    - _Expected_Behavior: Template context includes can_generate_report (from SessionManager.can_generate_report) and is_max_iterations (from SessionManager.is_at_max_iterations) so the "Generate Report" button and iteration controls render correctly_
    - _Preservation: Non-all_done branch unchanged; decide_hypotheses unchanged; discovery_session_page unchanged_
    - _Requirements: 1.1, 1.2, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4_

  - [ ] 3.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Missing Context Variables in Research Progress Completion
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior (can_generate_report and is_max_iterations present in context)
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed — template context now includes both variables)
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-Completion Polling Behavior Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions — non-completion polling and decide_hypotheses paths unchanged)
    - Confirm all tests still pass after fix (no regressions)

- [ ] 4. Checkpoint - Ensure all tests pass
  - Run full test suite to verify no unintended side effects
  - Ensure Property 1 (bug condition) now PASSES with the fix applied
  - Ensure Property 2 (preservation) still PASSES after the fix
  - Ensure existing Discovery Engine tests (if any) still pass
  - Ask the user if questions arise

## Task Dependency Graph

```json
{
  "waves": [
    ["1", "2"],
    ["3.1"],
    ["3.2", "3.3"],
    ["4"]
  ]
}
```

## Notes

- The fix is a 2-line addition to the template context dict in `research_progress` endpoint
- `SessionManager.can_generate_report()` and `SessionManager.is_at_max_iterations()` are already imported and used by `decide_hypotheses` and `discovery_session_page`
- Property-based tests should use Hypothesis library (already in project dependencies) to generate random session states
- Test file location: `tests/test_discovery_progress_bugfix.py`
