# Implementation Plan: Thread Ingestion Filtering

## Overview

Implement a deterministic, zero-cost post content filter (`app/services/post_filter.py`) that evaluates raw PRAW Submission objects against text-quality rules inside `scrape_subreddit()`. The filter rejects media-only posts, deleted content, link posts, URL-heavy text, and short posts before the expensive `_submission_to_dict()` call. Integration includes structured logging with per-reason skip counts and error resilience.

## Tasks

- [x] 1. Create post_filter module with core types and evaluate function
  - [x] 1.1 Create `app/services/post_filter.py` with SkipReason enum, FilterResult dataclass, and constants
    - Define `SkipReason(str, Enum)` with values: non_self_post, deleted_or_removed, empty_selftext, too_short, media_post, mostly_urls
    - Define `FilterResult` frozen dataclass with `passed: bool`, `reason: SkipReason | None`, `skipped` property, and factory methods `pass_result()` / `skip(reason)`
    - Define constants: `MIN_SELF_TEXT_LENGTH = 120`, `URL_RATIO_THRESHOLD = 0.50`
    - Define `_MEDIA_HINTS: frozenset[str]` and precompiled `_URL_PATTERN` regex
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 3.1, 3.2, 4.1, 4.2, 5.1–5.8, 6.1–6.3, 7.1, 9.1_

  - [x] 1.2 Implement `evaluate()` function with all six filter rules in order
    - Rule 1: `is_self` gate — `getattr(submission, "is_self", None)`, reject if False or None
    - Rule 2: Deleted/removed — check selftext in `("[deleted]", "[removed]")`
    - Rule 3: Empty selftext — check None or `selftext.strip() == ""`
    - Rule 4: Minimum length — `len(selftext.strip()) < MIN_SELF_TEXT_LENGTH`
    - Rule 5: Media detection — call `_check_media(submission, selftext)`
    - Rule 6: URL-dominated — call `_is_mostly_urls(stripped_text)`
    - Return `FilterResult.pass_result()` if all rules pass
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 3.1, 3.2, 4.1, 4.2, 5.1–5.8, 6.1–6.3, 7.1, 9.1, 9.2, 9.3_

  - [x] 1.3 Implement `_check_media()` helper with all 7 media conditions
    - Check post_hint in `_MEDIA_HINTS` (image, hosted:video, rich:video)
    - Check post_hint == "link" with empty selftext
    - Check `is_gallery is True`
    - Check `media is not None` with empty selftext
    - Check `secure_media is not None` with empty selftext
    - Return `FilterResult.skip(SkipReason.media_post)` on first match, None otherwise
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_

  - [x] 1.4 Implement `_is_mostly_urls()` helper
    - Count total non-whitespace characters (replace spaces, tabs, newlines, carriage returns)
    - Find all URL matches using `_URL_PATTERN` (https?://\S+)
    - Sum URL character lengths, compare ratio against `URL_RATIO_THRESHOLD`
    - Return True if ratio > 0.50
    - _Requirements: 6.1, 6.2, 6.3_

- [x] 2. Integrate post_filter into scrape_subreddit
  - [x] 2.1 Modify `scrape_subreddit()` in `app/services/reddit.py` to call `evaluate()`
    - Import `evaluate` from `app.services.post_filter`
    - Add `skip_counts: dict[str, int] = {}` and `skipped_filter_error: int = 0` before the loop
    - After existing stickied/age/locked/score checks, wrap `evaluate(submission)` in try/except
    - On `FilterResult.skipped`: increment `skip_counts[reason.value]`, log INFO with submission_id/subreddit/title/reason, continue
    - On exception: log WARNING with submission_id/subreddit/error, increment `skipped_filter_error`, continue
    - On `FilterResult.passed`: proceed to `_submission_to_dict(submission)` as before
    - _Requirements: 10.1, 10.3, 8.1, 8.2_

  - [x] 2.2 Add summary log line at end of `scrape_subreddit()`
    - After the loop, emit a single INFO log: `POST_FILTER_SUMMARY | subreddit=r/{name} | filtered_{reason}={count} | ...`
    - Only include reasons with count > 0
    - Include `filter_errors={skipped_filter_error}` if > 0
    - Add `skipped_filter_error` to the existing REDDIT_API_RESULT log line
    - _Requirements: 10.2_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Write unit tests for post_filter
  - [x] 4.1 Create `tests/test_post_filter.py` with example-based unit tests
    - Create `FakeSubmission` dataclass for duck-typing PRAW Submission
    - Test `is_self=False` → skip non_self_post
    - Test `is_self=None` → skip non_self_post
    - Test selftext `[deleted]` → skip deleted_or_removed
    - Test selftext `[removed]` → skip deleted_or_removed
    - Test selftext empty string → skip empty_selftext
    - Test selftext None → skip empty_selftext
    - Test selftext whitespace-only → skip empty_selftext
    - Test selftext 119 chars → skip too_short
    - Test selftext exactly 120 chars → passes length check
    - Test each media hint (image, hosted:video, rich:video) → skip media_post
    - Test post_hint "link" with empty selftext → skip media_post
    - Test is_gallery=True → skip media_post
    - Test media not None with empty selftext → skip media_post
    - Test secure_media not None with empty selftext → skip media_post
    - Test URL ratio at boundary (50.1% → skip, 49.9% → pass)
    - Test happy path: self-post with 200+ chars, no media, low URL ratio → pass
    - Test evaluation order: submission failing multiple rules returns earliest reason
    - _Requirements: 1.1, 1.3, 2.1, 2.2, 3.1, 3.2, 4.1, 4.2, 5.1–5.7, 6.1, 7.1, 9.1–9.3_

  - [ ]* 4.2 Write property test: Non-self posts are always rejected
    - **Property 1: Non-self posts are always rejected**
    - **Validates: Requirements 1.1, 1.3**
    - Generate submissions with `is_self` in (False, None), randomize all other fields
    - Assert `evaluate()` returns `passed=False, reason=SkipReason.non_self_post`

  - [ ]* 4.3 Write property test: Whitespace-only and None selftext rejected as empty
    - **Property 2: Whitespace-only and None selftext is rejected as empty**
    - **Validates: Requirements 3.1, 3.2**
    - Generate self-post submissions with selftext either None or whitespace-only strings
    - Assert `evaluate()` returns `passed=False, reason=SkipReason.empty_selftext`

  - [ ]* 4.4 Write property test: Short text below threshold rejected
    - **Property 3: Short text below threshold is rejected**
    - **Validates: Requirements 4.1**
    - Generate self-post submissions with non-sentinel selftext where `len(selftext.strip())` in [1, 119]
    - Assert `evaluate()` returns `passed=False, reason=SkipReason.too_short`

  - [ ]* 4.5 Write property test: URL-dominated text rejected
    - **Property 4: URL-dominated text is rejected**
    - **Validates: Requirements 6.1, 6.2, 6.3**
    - Generate self-post submissions with selftext >= 120 stripped chars, no media hints, URL ratio > 50%
    - Assert `evaluate()` returns `passed=False, reason=SkipReason.mostly_urls`

  - [ ]* 4.6 Write property test: Valid submissions pass all rules
    - **Property 5: Valid submissions pass all rules**
    - **Validates: Requirements 7.1**
    - Generate submissions where `is_self=True`, selftext not sentinel, length >= 120, no media, URL ratio <= 50%
    - Assert `evaluate()` returns `passed=True, reason=None`

  - [ ]* 4.7 Write property test: Evaluation order determines SkipReason
    - **Property 6: Evaluation order — earliest failing rule determines SkipReason**
    - **Validates: Requirements 9.1, 9.2, 9.3**
    - Generate submissions that fail multiple rules simultaneously
    - Assert returned SkipReason matches the earliest-ordered failing rule

- [ ] 5. Write integration tests for scrape_subreddit filter integration
  - [ ]* 5.1 Create `tests/test_scraping_filter_integration.py`
    - Mock PRAW subreddit listing to return controlled Submission objects
    - Test that `evaluate()` is called for each non-stickied/non-locked submission
    - Test that skipped submissions produce INFO log with correct key=value pairs
    - Test summary log line with per-reason counts
    - Test error resilience: mock `evaluate` to raise for one submission, verify scraping continues and WARNING logged
    - Test pass-through: submissions that pass filter appear in output with correct post_body
    - _Requirements: 8.1, 8.2, 10.1, 10.2, 10.3_

- [x] 6. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The filter operates on raw PRAW Submission objects before `_submission_to_dict()` to avoid unnecessary comment fetching
- Error handling in integration uses try/except with WARNING log and continue — never interrupts the scrape

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4"] },
    { "id": 2, "tasks": ["2.1"] },
    { "id": 3, "tasks": ["2.2"] },
    { "id": 4, "tasks": ["4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7"] },
    { "id": 5, "tasks": ["5.1"] }
  ]
}
```
