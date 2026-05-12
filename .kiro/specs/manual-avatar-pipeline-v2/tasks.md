# Implementation Plan: Manual Avatar Pipeline V2

## Overview

Refactor and extend the manual avatar pipeline to add budget visibility, cross-avatar deduplication, thread freshness filtering, scoring cost awareness, and pre-generation safety validation. The existing 4-step flow (Scrape → Score → Select Thread → Generate) is preserved, with each step gaining richer context and guardrails. Implementation creates 3 new service modules, 3 new templates, and updates the existing route handler and templates.

## Tasks

- [ ] 1. Create BudgetService with core computation logic
  - [ ] 1.1 Create `app/services/budget.py` with `BudgetSnapshot` dataclass and `compute_budget` function
    - Define `BudgetSnapshot` dataclass with all fields (total_today, max_total, professional_today, max_professional, hobby_today, max_hobby, minutes_until_next, last_comment_at, brand_ratio, max_brand_ratio, brand_ratio_exceeded, per_subreddit, max_per_subreddit, slots_remaining, can_generate, today_comments)
    - Implement `compute_budget(db, avatar)` that queries CommentDraft for today's activity, computes time gap, brand ratio (past 7 days), per-subreddit counts, and returns immutable snapshot
    - Use existing safety constants from `app/services/safety.py` (MAX_COMMENTS_PER_DAY=8, MAX_PROFESSIONAL_PER_DAY=5, MAX_HOBBY_PER_DAY=5, MIN_MINUTES_BETWEEN_COMMENTS=15, MAX_COMMENTS_PER_SUBREDDIT_DAY=2, MAX_BRAND_RATIO=0.3)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 9.1, 9.2, 9.3_

  - [ ]* 1.2 Write property tests for budget computation (Properties 1-4)
    - **Property 1: Budget computation correctness** — For any set of CommentDrafts with varying statuses and timestamps, verify total_today counts only {pending, approved, posted} from today, professional_today and hobby_today split correctly
    - **Validates: Requirements 1.1, 1.2, 1.3**
    - **Property 2: Time gap computation** — For any last comment timestamp T, verify minutes_until_next equals max(0, 15 - floor((now - T) / 60))
    - **Validates: Requirements 1.4, 7.3**
    - **Property 3: Brand ratio threshold detection** — For any avatar with N total and P professional comments in 7 days where N > 5, verify brand_ratio_exceeded is True iff P/N > 0.3
    - **Validates: Requirements 1.6**
    - **Property 4: Per-subreddit saturation detection** — For any avatar and subreddit S, verify per_subreddit[S] counts today's drafts targeting S, and subreddit_saturated is True iff count >= 2
    - **Validates: Requirements 1.7, 6.1**

  - [ ]* 1.3 Write property test for scrape freshness classification (Property 11)
    - **Property 11: Scrape freshness classification** — For any subreddit with last_scraped_at timestamp T, verify classified as "fresh" iff (now - T) < 30 minutes
    - **Validates: Requirements 8.2**

- [ ] 2. Create ThreadFilterService with filtering and annotation logic
  - [ ] 2.1 Create `app/services/thread_filter.py` with `FilteredThread`, `ThreadFilterResult` dataclasses and `filter_threads_for_avatar` function
    - Define `FilteredThread` dataclass (thread, score, age_display, age_hours, is_aging, subreddit_count_today, subreddit_saturated, can_generate)
    - Define `ThreadFilterResult` dataclass (threads, excluded_dedup_count, excluded_dedup_details, excluded_stale_count, phase, phase_label)
    - Implement `filter_threads_for_avatar(db, avatar, client, budget)` applying filters in order: phase restriction → freshness (>48h excluded) → cross-avatar dedup → self-dedup → locked exclusion → saturation annotation → sort
    - Implement `format_thread_age(scraped_at)` returning "Xm ago", "Xh ago", "Xd ago"
    - Implement `classify_thread_freshness(scraped_at)` returning (is_stale, is_aging) tuple
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3_

  - [ ]* 2.2 Write property tests for thread filtering (Properties 5-9)
    - **Property 5: Cross-avatar deduplication** — For any thread T and client C, if any avatar of C has a draft for T with status in {pending, approved, posted}, T must not appear in filtered list for other avatars of C
    - **Validates: Requirements 2.1**
    - **Property 6: Thread freshness filtering** — For any thread with scraped_at > 48h ago, it must be excluded; between 36-48h, it must be included with is_aging=True
    - **Validates: Requirements 3.1, 3.4**
    - **Property 7: Thread age formatting** — For any timestamp within 48h, format_thread_age returns string matching `\d+[mhd] ago` with correct numeric value
    - **Validates: Requirements 3.2**
    - **Property 8: Thread sort order invariant** — For any two threads with equal composite and alert scores, the newer thread (by scraped_at) appears first
    - **Validates: Requirements 3.3**
    - **Property 9: Phase-aware subreddit filtering** — For any avatar in phase P, all threads in filtered list respect phase subreddit restrictions (P1=hobby only, P2=hobby+business, P3=all)
    - **Validates: Requirements 5.1, 5.2, 5.3**

- [ ] 3. Create PreValidationService with structured error reporting
  - [ ] 3.1 Create `app/services/pre_validation.py` with `ValidationFailure`, `PreValidationResult` dataclasses and `pre_validate_generation` function
    - Define `ValidationFailure` dataclass (constraint, message, current_value, threshold, time_remaining)
    - Define `PreValidationResult` dataclass (allowed, failures)
    - Implement `pre_validate_generation(db, avatar, client, thread, budget)` checking: daily limit, time gap, subreddit limit, phase rules, brand ratio, avatar active/not frozen
    - Return ALL failures (not just first) for comprehensive feedback
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ]* 3.2 Write property test for pre-validation error specificity (Property 10)
    - **Property 10: Safety error message specificity** — For any failed pre-validation check, the ValidationFailure must contain non-empty constraint identifier, current_value, and threshold strings
    - **Validates: Requirements 7.2**

- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Refactor route handler to use new services
  - [ ] 5.1 Refactor `pipeline_panel` GET endpoint to use `compute_budget`
    - Replace inline budget queries with `compute_budget(db, avatar)` call
    - Pass full `BudgetSnapshot` to template context
    - Add subreddit freshness info (last_scraped_at per subreddit) to context
    - Add scoring cost estimate (unscored_count × $0.0003) to context
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 4.1, 4.2, 4.3, 8.1, 8.2, 8.4, 9.1, 9.2, 9.3_

  - [ ] 5.2 Refactor `pipeline_threads` GET endpoint to use `filter_threads_for_avatar`
    - Replace inline thread filtering with `filter_threads_for_avatar(db, avatar, client, budget)` call
    - Pass `ThreadFilterResult` to template (includes exclusion counts, phase label, annotated threads)
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.3_

  - [ ] 5.3 Refactor `pipeline_generate` POST endpoint to use `pre_validate_generation`
    - Add `compute_budget` + `pre_validate_generation` before generation
    - On validation failure, render structured error template with all failures
    - Add thread liveness check for threads > 12h old (using existing `check_and_filter_thread`)
    - Set `learning_metadata["source"] = "manual_pipeline"` on successful draft
    - Add HX-Trigger header for budget refresh after successful generation
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 10.2, 10.4, 11.1, 11.2, 11.3, 11.4_

  - [ ] 5.4 Add inline edit endpoint `POST /draft/{draft_id}/edit`
    - Accept `edited_text` form field
    - Save to `draft.edited_draft`, update `learning_metadata` with `inline_edit: True` and `edited_at` timestamp
    - Return updated draft partial
    - _Requirements: 10.1, 10.3_

  - [ ] 5.5 Add retry generation endpoint `POST /generate/{thread_id}/retry`
    - Skip pre-validation (safety already passed on first attempt)
    - Proceed directly to generation
    - Return draft partial or error with retry button
    - _Requirements: 10.5_

- [ ] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Create new HTMX templates
  - [ ] 7.1 Create `app/templates/partials/avatar_pipeline_budget.html`
    - Standalone budget partial for HTMX refresh after generation
    - Display all 7 budget metrics: total/max, professional/max, hobby/max, time until next, brand ratio, per-subreddit counts, slots remaining
    - Show prominent warning when zero slots remaining
    - Show brand ratio warning when exceeded
    - Use Tailwind dark theme consistent with existing admin partials
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

  - [ ] 7.2 Create `app/templates/partials/avatar_pipeline_validation_error.html`
    - Structured error display for pre-validation failures
    - Show each failure with constraint name, current value, threshold, and time remaining (if applicable)
    - Use warning/error color coding consistent with existing error partials
    - _Requirements: 7.2, 7.3, 7.4_

  - [ ] 7.3 Create `app/templates/partials/avatar_pipeline_activity.html`
    - Today's activity list showing comments with source (scheduler/manual), status, subreddit, and timestamp
    - Distinguish scheduler vs manual pipeline comments visually
    - Show most recent comment timestamp
    - _Requirements: 9.1, 9.2, 9.3_

- [ ] 8. Update existing HTMX templates
  - [ ] 8.1 Update `app/templates/partials/avatar_pipeline_panel.html`
    - Add Budget Dashboard section at top (include `avatar_pipeline_budget.html`)
    - Add scrape freshness indicators per subreddit (last scraped time, "fresh" badge)
    - Disable Scrape button when all subreddits are fresh with "All subreddits are fresh" message
    - Add scoring cost estimate next to Score button
    - Disable Score button when unscored_count == 0 with "Nothing to score" message
    - Add `hx-get` for budget partial refresh
    - _Requirements: 4.1, 4.2, 4.3, 8.1, 8.2, 8.4_

  - [ ] 8.2 Update `app/templates/partials/avatar_pipeline_threads.html`
    - Add thread age display (human-readable format from `age_display`)
    - Add aging indicator (⚠️ badge) for threads 36-48h old
    - Add subreddit saturation badges (count/max per subreddit)
    - Disable Generate button for saturated subreddits
    - Add dedup exclusion count display ("X threads excluded — other avatars have drafts")
    - Add dedup detail tooltip showing which avatar has the draft
    - Add phase restriction label above thread list
    - _Requirements: 2.2, 2.3, 3.2, 3.4, 5.5, 6.1, 6.2, 6.3_

  - [ ] 8.3 Update `app/templates/partials/avatar_pipeline_draft.html`
    - Add inline edit textarea with save button (hx-post to edit endpoint)
    - Add retry button on generation error (hx-post to retry endpoint)
    - Add HX-Trigger to refresh budget section after draft display
    - _Requirements: 10.1, 10.3, 10.4, 10.5_

- [ ] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Write integration and unit tests
  - [ ]* 10.1 Write unit tests for BudgetService
    - Test budget computation with various draft states (empty, at limit, mixed statuses)
    - Test time gap calculation edge cases (no previous comment, exactly 15 min ago, just under)
    - Test brand ratio with edge cases (N <= 5 skips check, exactly 30%, over 30%)
    - Test per-subreddit counting accuracy
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 1.7_

  - [ ]* 10.2 Write unit tests for ThreadFilterService
    - Test phase filtering (phase 1 hobby only, phase 2 hobby+business, phase 3 all)
    - Test cross-avatar dedup with multiple avatars same client
    - Test freshness exclusion at boundary (exactly 48h)
    - Test sort order with equal scores
    - _Requirements: 2.1, 3.1, 5.1, 5.2, 5.3_

  - [ ]* 10.3 Write unit tests for PreValidationService
    - Test all constraint checks individually
    - Test multiple simultaneous failures returned
    - Test all fields populated on each failure type
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ]* 10.4 Write integration tests for refactored route endpoints
    - Test full generate flow with mocked LLM (verify draft created with source=manual_pipeline)
    - Test liveness check integration (mock Reddit API, verify locked thread handling)
    - Test inline edit persistence (verify edited_draft and learning_metadata saved)
    - Test retry endpoint skips pre-validation
    - Test HTMX budget refresh trigger header present after generation
    - _Requirements: 10.2, 10.3, 10.5, 11.1, 11.2, 11.3_

  - [ ]* 10.5 Write property test for draft persistence (Property 12)
    - **Property 12: Draft persistence correctness** — For any successful generation via manual pipeline, verify draft has status="pending" and learning_metadata contains source="manual_pipeline"; for inline edits, verify edited_draft equals submitted text and learning_metadata contains inline_edit=True
    - **Validates: Requirements 10.2, 10.3**

- [ ] 11. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties (12 properties from design)
- Unit tests validate specific examples and edge cases
- No database migrations needed — uses existing `learning_metadata` JSONB field on CommentDraft
- Existing services (`safety.py`, `thread_liveness.py`, `generation.py`) are consumed, not modified
- All new templates use Tailwind dark theme consistent with existing admin panel

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "3.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.1", "3.2"] },
    { "id": 2, "tasks": ["2.2", "5.1", "5.2", "5.3"] },
    { "id": 3, "tasks": ["5.4", "5.5", "7.1", "7.2", "7.3"] },
    { "id": 4, "tasks": ["8.1", "8.2", "8.3"] },
    { "id": 5, "tasks": ["10.1", "10.2", "10.3"] },
    { "id": 6, "tasks": ["10.4", "10.5"] }
  ]
}
```
