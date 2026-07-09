# Emotional Profile Analysis Feedback — Bugfix Design

## Overview

When emotional profile analysis fails for a subreddit (PRAW errors, insufficient data, LLM errors, or schema validation failures), the `Subreddit.emotional_profile_error` field is set by the service — but the client portal's Community Tone section ignores this field entirely. The template only checks `{% if emotional_profile %}` and falls through to a generic "pending" message when the profile is absent, regardless of whether an error occurred.

The admin side has already been partially fixed (GET handler shows `emotional_profile_error`, POST handler validates subreddit existence before dispatching). This bugfix targets the remaining client portal gap: showing a user-friendly error state instead of the misleading "pending" message, and sanitizing raw error strings for client-facing display.

## Glossary

- **Bug_Condition (C)**: `subreddit.emotional_profile_error` is set (non-NULL, non-empty) AND the client portal Community Tone section is rendered
- **Property (P)**: When the bug condition holds, the UI SHALL display a user-friendly error message indicating analysis failed, with a sanitized reason
- **Preservation**: When `emotional_profile` data exists (success case) or when both `emotional_profile` and `emotional_profile_error` are NULL (never-analyzed case), existing behavior is unchanged
- **`analyze_subreddit_profile()`**: Service in `app/services/emotional_profile.py` that sets `emotional_profile_error` on failure and clears it on success
- **`portal_subreddit_risk_profile()`**: Route in `app/routes/portal_risk_profile.py` that renders the client risk profile page
- **`emotional_profile_error`**: Text field on the Subreddit model storing the last failure reason (raw Python exception string)

## Bug Details

### Bug Condition

The bug manifests when emotional profile analysis has previously failed for a subreddit AND a client portal user views the subreddit risk profile page. The route queries `emotional_profile` from the `subreddit_emotional_profiles` table (a separate raw SQL query), but never reads the `Subreddit.emotional_profile_error` field. The template then falls into the `{% else %}` branch showing "Community tone analysis pending" — which is factually incorrect (analysis was attempted and failed).

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type { subreddit: Subreddit, page: "client_risk_profile" }
  OUTPUT: boolean
  
  RETURN input.subreddit.emotional_profile_error IS NOT NULL
         AND input.subreddit.emotional_profile_error != ""
         AND input.subreddit.emotional_profile IS NULL
         AND input.page == "client_risk_profile"
END FUNCTION
```

### Examples

- User views r/sysadmin risk profile. Analysis failed with "Reddit API error: 403 Forbidden". Template shows "Community tone analysis pending" — should show error state with "Subreddit unreachable" message.
- User views r/tinycommunity risk profile. Analysis failed with "Insufficient data: only 3 qualifying comments". Template shows "Community tone analysis pending" — should show "Not enough community data to analyze tone."
- User views r/networking risk profile. Analysis failed with "LLM error: Rate limit exceeded on gemini/gemini-2.5-flash". Template shows "Community tone analysis pending" — should show "Analysis temporarily unavailable. Will retry automatically."
- User views r/biohackers risk profile where `emotional_profile` has valid data and `emotional_profile_error` is NULL. Template shows the full profile correctly — unchanged.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- When `emotional_profile` contains valid JSONB data, the full Community Tone display (formality, humor, expertise, negativity, dominant emotions, summary) continues rendering exactly as before
- When both `emotional_profile` is NULL and `emotional_profile_error` is NULL, the "pending" state with explanation text continues rendering as before
- The admin-side GET handler (`admin_get_emotional_profile_partial`) continues showing the raw error string and "Run Analysis" retry button as already implemented
- The admin-side POST handler continues validating subreddit existence and clearing `emotional_profile_error` before dispatching
- The Celery task `analyze_subreddit_emotional_profile` continues setting/clearing the error field as implemented
- Mouse clicks, page navigation, and all non-Community-Tone sections of the risk profile page remain unchanged

**Scope:**
All inputs that do NOT involve a subreddit with a non-NULL `emotional_profile_error` AND a NULL `emotional_profile` should be completely unaffected by this fix. This includes:
- Subreddits with successful profiles (profile exists, error is NULL)
- Subreddits never analyzed (both profile and error are NULL)
- Admin-side profile display (already fixed)
- Any page other than the client portal subreddit risk profile

## Hypothesized Root Cause

Based on the bug description and code analysis, the issues are:

1. **Route does not pass error to template**: `portal_subreddit_risk_profile()` in `portal_risk_profile.py` reads `emotional_profile` via a raw SQL query against `subreddit_emotional_profiles` table, but never reads `subreddit.emotional_profile_error` from the `Subreddit` model. The template context lacks any error variable.

2. **Template has no error branch**: `subreddit_risk_profile.html` has only two states: `{% if emotional_profile %}` (show data) and `{% else %}` (show "pending"). There is no intermediate state for "attempted but failed."

3. **Raw error strings not suitable for clients**: The error messages stored in `emotional_profile_error` are technical (e.g., "Reddit API error: 403 Forbidden", "LLM error: Rate limit exceeded..."). Client-facing pages need sanitized, human-friendly messages.

4. **Dual data source mismatch**: The `emotional_profile` data in the template comes from a separate table query (`subreddit_emotional_profiles`), while the error is on the `Subreddit` model itself. The route already has the `subreddit` object loaded but doesn't extract the error from it.

## Correctness Properties

Property 1: Bug Condition - Error State Displayed on Client Portal

_For any_ subreddit where `emotional_profile_error` is set (non-NULL and non-empty) AND `emotional_profile` is NULL, the client portal Community Tone section SHALL display a user-friendly error message indicating that analysis was attempted but failed, with a sanitized reason category (e.g., "subreddit unreachable", "not enough data", "analysis temporarily unavailable").

**Validates: Requirements 2.1, 2.3**

Property 2: Preservation - Successful Profile and Never-Analyzed States

_For any_ subreddit where `emotional_profile_error` is NULL (either because analysis succeeded or was never attempted), the client portal Community Tone section SHALL produce the same output as the original code — showing the full profile when data exists, or the "pending" message when no profile exists.

**Validates: Requirements 3.1, 3.2, 3.3**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `app/routes/portal_risk_profile.py`

**Function**: `portal_subreddit_risk_profile()`

**Specific Changes**:
1. **Read error from Subreddit model**: After loading the `subreddit` object (already done), extract `subreddit.emotional_profile_error` and pass it to the template context as `emotional_profile_error`.
2. **Add error sanitization helper**: Create a function `_sanitize_emotional_profile_error(raw_error: str) -> str` that maps technical error prefixes to user-friendly messages:
   - `"Reddit API error:"` → "This subreddit is currently unreachable for analysis."
   - `"Insufficient data:"` → "Not enough community activity to analyze tone yet."
   - `"LLM error:"` → "Tone analysis is temporarily unavailable. Will retry automatically."
   - `"Schema validation failed:"` → "Analysis produced unexpected results. Will retry automatically."
   - Default/unknown → "Tone analysis encountered an issue. Will retry on next weekly run."
3. **Pass sanitized error to template**: Add `"emotional_profile_error": sanitized_error` to the template context dict.

**File**: `app/templates/client/subreddit_risk_profile.html`

**Section**: Community Tone `{% else %}` block

**Specific Changes**:
4. **Add error state branch**: Between the `{% if emotional_profile %}` success block and the generic `{% else %}` pending block, insert `{% elif emotional_profile_error %}` that renders an error state UI with:
   - Warning icon (⚠️) instead of speech bubble (💬)
   - "Tone analysis unavailable" heading
   - The sanitized error message
   - "Analysis retries automatically each week" note
5. **Keep pending block as final fallback**: The existing `{% else %}` block remains unchanged for the never-analyzed state.

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Render the client portal risk profile page for subreddits that have `emotional_profile_error` set. Verify the template shows "pending" instead of an error state. Inspect the template context to confirm `emotional_profile_error` is absent.

**Test Cases**:
1. **PRAW Error Test**: Subreddit with `emotional_profile_error = "Reddit API error: 403 Forbidden"` — portal shows "pending" (will fail on unfixed code)
2. **Insufficient Data Test**: Subreddit with `emotional_profile_error = "Insufficient data: only 3 qualifying comments"` — portal shows "pending" (will fail on unfixed code)
3. **LLM Error Test**: Subreddit with `emotional_profile_error = "LLM error: Rate limit exceeded"` — portal shows "pending" (will fail on unfixed code)
4. **Schema Error Test**: Subreddit with `emotional_profile_error = "Schema validation failed: ..."` — portal shows "pending" (will fail on unfixed code)

**Expected Counterexamples**:
- Template context does not contain `emotional_profile_error` key
- Template falls through to `{% else %}` showing misleading "pending" state for all error cases
- Root cause: route never reads `subreddit.emotional_profile_error`

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL subreddit WHERE isBugCondition(subreddit) DO
  response := render_portal_risk_profile(subreddit)
  ASSERT "Tone analysis unavailable" IN response.html
  ASSERT sanitized_error_message IN response.html
  ASSERT "Community tone analysis pending" NOT IN response.html
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL subreddit WHERE NOT isBugCondition(subreddit) DO
  ASSERT render_portal_risk_profile_original(subreddit) = render_portal_risk_profile_fixed(subreddit)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for subreddits with valid profiles and never-analyzed subreddits, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Successful Profile Preservation**: Verify subreddits with valid `emotional_profile` data continue showing the full Community Tone display (formality, humor, expertise, etc.)
2. **Never-Analyzed Preservation**: Verify subreddits where both `emotional_profile` and `emotional_profile_error` are NULL continue showing the "pending" state
3. **Admin Error Display Preservation**: Verify the admin GET handler still shows raw error + "Run Analysis" button unchanged
4. **Admin POST Handler Preservation**: Verify dispatching analysis still clears error and returns status message

### Unit Tests

- Test `_sanitize_emotional_profile_error()` with each error prefix category
- Test template rendering with `emotional_profile_error` set (error state shown)
- Test template rendering with `emotional_profile` set (success state unchanged)
- Test template rendering with both NULL (pending state unchanged)
- Test edge case: both `emotional_profile` and `emotional_profile_error` set (success takes priority — profile data wins)

### Property-Based Tests

- Generate random error strings with various prefixes and verify sanitization always produces one of the known friendly messages
- Generate random emotional profile dicts and verify template rendering includes expected data fields
- Test that error sanitization never exposes raw Python exception details (no tracebacks, no file paths)

### Integration Tests

- Full request to portal risk profile endpoint with a subreddit that has `emotional_profile_error` set — verify HTTP 200 with error UI
- Full request with a subreddit that has valid `emotional_profile` — verify HTTP 200 with profile data
- Verify the weekly `refresh_subreddit_emotional_profiles` task correctly sets/clears error field (already tested by existing service tests)
