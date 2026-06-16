# Discovery Report Generation Fix — Bugfix Design

## Overview

The `research_progress` HTMX polling endpoint (`GET /admin/discovery/{session_id}/progress`) renders `discovery_results.html` when all background research completes, but omits `can_generate_report` and `is_max_iterations` from the template context. Since Jinja2 treats undefined variables as falsy, the "Generate Report" button never appears and the iteration controls malfunction. The fix adds the two missing context variables, computed identically to how `decide_hypotheses` already computes them.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug — the `research_progress` endpoint renders `discovery_results.html` (i.e., `all_done == True`) without the required template context variables
- **Property (P)**: The desired behavior — `can_generate_report` and `is_max_iterations` are present in the template context so the "Generate Report" button and iteration controls render correctly
- **Preservation**: The `decide_hypotheses` endpoint and `discovery_session_page` route must continue passing these variables as they currently do; the progress polling partial must continue rendering while research is in progress
- **`research_progress`**: The endpoint at `GET /admin/discovery/{session_id}/progress` in `reddit_saas/app/routes/discovery.py` that HTMX polls during background research
- **`SessionManager.can_generate_report(session)`**: Static method that returns `True` when at least one hypothesis is confirmed and research is done
- **`SessionManager.is_at_max_iterations(session)`**: Static method that returns `True` when `session.current_iteration >= MAX_ITERATIONS` (5)

## Bug Details

### Bug Condition

The bug manifests when the `research_progress` endpoint detects that all hypotheses have completed research (`all_done == True`) and transitions from the progress partial to the results partial. The `TemplateResponse` call for `discovery_results.html` omits `can_generate_report` and `is_max_iterations`, which the template uses to conditionally render the "Generate Report" button and "Next Iteration" controls.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type HTTPRequest to GET /admin/discovery/{session_id}/progress
  OUTPUT: boolean
  
  LET session = load_session(input.session_id)
  LET progress = session.session_metadata.get("research_progress", {})
  LET all_done = all(v == "complete" for v in progress.values()) AND len(progress) > 0
  
  RETURN all_done == True
END FUNCTION
```

### Examples

- **Normal completion**: Session has 3 hypotheses, all research tasks finish → `all_done = True` → endpoint renders `discovery_results.html` without `can_generate_report` → "Generate Report" button never appears even though 2 hypotheses are confirmed
- **Max iterations reached**: Session at iteration 5, research completes → endpoint renders results without `is_max_iterations = True` → "Next Iteration" button shows even though no further iterations are allowed
- **No confirmed hypotheses**: All hypotheses rejected after research → `can_generate_report = False` should suppress the button, but since the variable is absent (falsy), the button is suppressed for the wrong reason — works by accident but breaks if template logic inverts
- **Manual page refresh (NOT buggy)**: Operator refreshes the page → `discovery_session_page` route renders with all context variables → button appears correctly

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- The `decide_hypotheses` endpoint (`POST /{session_id}/decide`) must continue passing `can_generate_report` and `is_max_iterations` to `discovery_results.html` as it currently does
- The `discovery_session_page` route (`GET /{session_id}`) must continue passing these variables to `admin_discovery_session.html` as it currently does
- When research is still in progress (`all_done == False`), the progress endpoint must continue returning `discovery_research_progress.html` with the polling header
- The `generate_report` endpoint must continue validating `can_generate_report` server-side before proceeding

**Scope:**
All requests that do NOT hit the `all_done == True` branch of `research_progress` are completely unaffected. This includes:
- Progress polling while research is still running
- All other Discovery endpoints (create, entities, research trigger, stop, decide, report, export, handoff, abandon)
- Full page loads of the session page

## Hypothesized Root Cause

Based on the bug description and code review, the root cause is straightforward:

1. **Missing context variables in template render call**: The `research_progress` endpoint's `all_done` branch (lines ~590-599 of `discovery.py`) renders `partials/discovery_results.html` with only `session` and `hypotheses` in the context dict. The `can_generate_report` and `is_max_iterations` keys are absent.

2. **Copy-paste omission**: The `decide_hypotheses` endpoint (lines ~630-650) correctly passes all four context variables to the same template. The `research_progress` endpoint was likely written earlier or copied without the additional context keys.

3. **No error raised**: Jinja2's `UndefinedError` is not raised by default for undefined variables in conditionals (`{% if can_generate_report %}`). The undefined value evaluates to falsy, silently suppressing the button.

## Correctness Properties

Property 1: Bug Condition - Results Partial Context Variables Present

_For any_ HTTP request to `GET /admin/discovery/{session_id}/progress` where all research is complete (`all_done == True`), the fixed `research_progress` endpoint SHALL include `can_generate_report` (computed from `SessionManager.can_generate_report(session)`) and `is_max_iterations` (computed from `SessionManager.is_at_max_iterations(session)`) in the template context passed to `discovery_results.html`.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation - Non-Completion Polling Behavior

_For any_ HTTP request to `GET /admin/discovery/{session_id}/progress` where research is NOT complete (`all_done == False`), the fixed endpoint SHALL produce exactly the same response as the original endpoint — returning `discovery_research_progress.html` with `session`, `hypotheses`, and `progress` in the context.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `reddit_saas/app/routes/discovery.py`

**Function**: `research_progress` (the `GET /{session_id}/progress` endpoint)

**Specific Changes**:
1. **Add `can_generate_report` to the template context**: Compute `SessionManager.can_generate_report(session)` and include it in the context dict when rendering `discovery_results.html` in the `all_done` branch.

2. **Add `is_max_iterations` to the template context**: Compute `SessionManager.is_at_max_iterations(session)` and include it in the context dict when rendering `discovery_results.html` in the `all_done` branch.

3. **No other changes required**: The `SessionManager` class already has both methods implemented and tested. The template already uses these variables correctly (proven by the `decide_hypotheses` path working). Only the render call in `research_progress` needs updating.

**Before (buggy):**
```python
if all_done:
    return templates.TemplateResponse(
        request,
        "partials/discovery_results.html",
        {
            "session": session,
            "hypotheses": current_hypos,
        },
    )
```

**After (fixed):**
```python
if all_done:
    return templates.TemplateResponse(
        request,
        "partials/discovery_results.html",
        {
            "session": session,
            "hypotheses": current_hypos,
            "can_generate_report": SessionManager.can_generate_report(session),
            "is_max_iterations": SessionManager.is_at_max_iterations(session),
        },
    )
```

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write a test that creates a Discovery session, sets `session_metadata.research_progress` to all-complete, then calls `GET /{session_id}/progress`. Assert that the response HTML contains the "Generate Report" button markup. Run on UNFIXED code to observe failure.

**Test Cases**:
1. **All research complete, 1+ confirmed hypothesis**: Call progress endpoint → expect "Generate Report" button in response HTML (will fail on unfixed code because `can_generate_report` is undefined/falsy)
2. **All research complete, at max iterations**: Call progress endpoint → expect "Next Iteration" button NOT in response HTML (will fail on unfixed code because `is_max_iterations` is undefined/falsy, so template may show the button)
3. **All research complete, no confirmed hypotheses**: Call progress endpoint → expect NO "Generate Report" button (passes by accident on unfixed code but for wrong reason)

**Expected Counterexamples**:
- Response HTML from the progress endpoint does not contain the "Generate Report" button when it should
- Possible cause: `can_generate_report` not in template context → Jinja2 treats as falsy → `{% if can_generate_report %}` block skipped

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL session WHERE all_research_complete(session) DO
  response := GET /admin/discovery/{session.id}/progress
  context := extract_template_context(response)
  ASSERT "can_generate_report" IN context
  ASSERT "is_max_iterations" IN context
  ASSERT context["can_generate_report"] == SessionManager.can_generate_report(session)
  ASSERT context["is_max_iterations"] == SessionManager.is_at_max_iterations(session)
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL session WHERE NOT all_research_complete(session) DO
  ASSERT research_progress_original(session) == research_progress_fixed(session)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many session/progress configurations automatically
- It catches edge cases like empty progress dicts, partial completions, single-hypothesis sessions
- It provides strong guarantees that the in-progress polling path is unchanged

**Test Plan**: Observe behavior on UNFIXED code for sessions where research is still in progress (various combinations of queued/researching/complete statuses), then write property-based tests to verify the fixed code returns identical responses.

**Test Cases**:
1. **In-progress preservation**: Generate random session states where at least one hypothesis is not complete → verify response is `discovery_research_progress.html` with same context
2. **Empty progress preservation**: Session with empty `research_progress` dict → verify same behavior (returns progress partial)
3. **Decide endpoint preservation**: Verify `decide_hypotheses` still passes `can_generate_report` and `is_max_iterations` after fix (no regression)
4. **Session page preservation**: Verify `discovery_session_page` still passes all context variables after fix

### Unit Tests

- Test `research_progress` with `all_done = True` and confirmed hypotheses → assert `can_generate_report` is in rendered context
- Test `research_progress` with `all_done = True` and max iterations → assert `is_max_iterations` is True in context
- Test `research_progress` with `all_done = False` → assert response uses `discovery_research_progress.html` template
- Test `research_progress` with empty progress → assert response uses progress template

### Property-Based Tests

- Generate random `research_progress` dicts (mix of "complete", "queued", "researching" values) and verify: if all values are "complete" then response includes both context vars; otherwise response is the progress partial
- Generate random session states (varying iteration counts 1-5, varying hypothesis statuses) and verify `can_generate_report` and `is_max_iterations` match their respective `SessionManager` method outputs
- Generate random non-all-done progress states and verify response is identical between original and fixed code paths

### Integration Tests

- Full flow: create session → extract entities → form hypotheses → trigger research → simulate Celery completion (set all progress to "complete") → poll progress → verify "Generate Report" button appears in HTML
- Full flow with max iterations: set `current_iteration = 5` → complete research → poll progress → verify "Next Iteration" is suppressed
- Compare HTMX polling path vs manual page refresh → both should show identical button states
