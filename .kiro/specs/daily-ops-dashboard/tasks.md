# Implementation Plan: Daily Operations Dashboard

## Overview

The Daily Operations Dashboard consolidates client pipeline status, manual triggers, review queue counts, scrape freshness, run history, schedule visibility, and avatar health into a single-page admin view at `/admin/`. The implementation uses a shell + HTMX partials architecture with server-side rendering.

**Current state:** The service layer (`services/operations_dashboard.py`), route endpoints (`routes/admin.py`), and all templates (`admin_dashboard.html` + 6 partials) are already implemented and passing basic unit/integration tests. The remaining work focuses on property-based testing to validate correctness properties defined in the design, plus any refinements identified during testing.

## Tasks

- [ ] 1. Validate existing implementation against requirements
  - [ ] 1.1 Verify service layer functions match design return shapes
    - Confirm `get_top_metrics`, `get_client_status_cards`, `get_scrape_freshness_grouped`, `get_run_history`, `get_avatar_health_summary`, `get_schedule_display` all return the documented TypedDict shapes
    - Verify `list_active_clients` returns only active clients sorted by name
    - _Requirements: 1.1, 1.2, 3.1, 4.1, 5.1, 6.1, 7.1_
  - [ ] 1.2 Verify route endpoints return correct HTTP responses and HTMX attributes
    - Confirm all GET partials return HTML fragments (not full pages)
    - Confirm POST trigger endpoints return toast partials with correct status codes (200 success, 400 bad action, 500 error)
    - Verify `admin_dashboard.html` includes `hx-trigger="load, every 60s"` on client cards container
    - _Requirements: 1.4, 2.1, 2.2, 2.5, 2.6, 8.4, 8.5_
  - [ ] 1.3 Verify template layout matches design specification
    - Confirm top metrics bar shows pending reviews, total clients, total avatars, next run time
    - Confirm two-column layout: client cards (2/3 width left), side panels (1/3 right)
    - Confirm Run All controls section with all four action buttons
    - Confirm Run History section below with client filter dropdown
    - _Requirements: 8.1, 8.2, 8.3_

- [ ] 2. Checkpoint - Verify existing tests pass
  - Ensure all tests in `tests/test_operations_dashboard.py` pass, ask the user if questions arise.

- [ ] 3. Write property-based tests for service layer correctness
  - [ ] 3.1 Set up property test file structure
    - Create `tests/test_operations_dashboard_properties.py`
    - Set up Hypothesis strategies for generating Client, RedditThread, CommentDraft, ClientSubreddit, ActivityEvent, and Avatar model instances
    - Configure `@settings(max_examples=100)` for all property tests
    - _Requirements: 1.1, 1.2, 3.1, 4.1, 5.1, 6.1, 7.1_
  - [ ]* 3.2 Write property test: Client status cards reflect active clients with correct 24h counts
    - **Property 1: Client status cards reflect active clients with correct 24h counts**
    - Generate arbitrary sets of active/inactive clients with varying RedditThread and CommentDraft records across time boundaries
    - Assert: one card per active client, `threads_24h` matches threads in last 24h, `scored_24h` matches threads with non-None tag in last 24h, `generated_24h` matches drafts in last 24h, `pending` matches drafts with status "pending", `is_idle` is True iff all 24h counts are 0
    - **Validates: Requirements 1.1, 1.2, 1.3**
  - [ ]* 3.3 Write property test: Pending reviews count equals total pending drafts
    - **Property 2: Pending reviews count equals total pending drafts**
    - Generate arbitrary CommentDraft records with varying statuses across multiple clients
    - Assert: `get_top_metrics(db)["pending_reviews"]` equals count of drafts where `status == "pending"`
    - **Validates: Requirements 3.1, 3.2**
  - [ ]* 3.4 Write property test: Scrape freshness staleness classification
    - **Property 3: Scrape freshness staleness classification**
    - Generate active subreddits with varying `last_scraped_at` timestamps (including None)
    - Assert: `is_stale == True` iff `last_scraped_at` is None or older than 24h; `is_never == True` iff `last_scraped_at` is None
    - **Validates: Requirements 4.1, 4.2, 4.3**
  - [ ]* 3.5 Write property test: Scrape freshness sorting invariant
    - **Property 4: Scrape freshness sorting invariant**
    - For each client group returned, assert all stale subreddits appear before all fresh subreddits
    - **Validates: Requirements 4.4**
  - [ ]* 3.6 Write property test: Run history filters to pipeline event types only
    - **Property 5: Run history filters to pipeline event types only**
    - Generate ActivityEvent records with varying `event_type` values including non-pipeline types
    - Assert: returned events only have `event_type` in ("scrape", "score", "generate")
    - **Validates: Requirements 5.1, 5.2**
  - [ ]* 3.7 Write property test: Run history ordering and limit
    - **Property 6: Run history ordering and limit**
    - Generate pipeline ActivityEvent records with varying timestamps
    - Assert: at most `limit` entries returned, ordered by `created_at` descending
    - **Validates: Requirements 5.3, 5.4**
  - [ ]* 3.8 Write property test: Schedule display correctness
    - **Property 7: Schedule display correctness**
    - Generate arbitrary `now` datetime values
    - Assert: exactly one entry per configured schedule, all `next_at >= now`, exactly one `is_next == True` with minimum `next_at`
    - **Validates: Requirements 6.1, 6.2, 6.3**
  - [ ]* 3.9 Write property test: Avatar health aggregation correctness
    - **Property 8: Avatar health aggregation correctness**
    - Generate active avatars with varying `reddit_status` and `warming_phase` values
    - Assert: `status_counts` match actual counts per status, `phase_counts` match counts per phase, `total_active` equals sum of status counts, `eligible_for_promotion` matches avatars with phase < 3 and stale/null evaluation date
    - **Validates: Requirements 7.1, 7.3, 7.4**
  - [ ]* 3.10 Write property test: Human delta formatting produces valid output
    - **Property 9: Human delta formatting produces valid output**
    - Generate non-negative timedeltas
    - Assert: result is non-empty, contains at least one digit (or is "now"), uses only units s/m/h/d, is monotonically non-decreasing as input increases
    - **Validates: Requirements 5.3, 6.2**

- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass (both existing unit/integration tests and new property-based tests), ask the user if questions arise.

- [ ] 5. Address any gaps identified during validation
  - [ ] 5.1 Fix any service layer discrepancies found in task 1.1
    - Apply corrections to `services/operations_dashboard.py` if return shapes or logic don't match design
    - _Requirements: 1.1, 1.2, 3.1, 4.1, 5.1, 6.1, 7.1_
  - [ ] 5.2 Fix any template or route issues found in tasks 1.2–1.3
    - Apply corrections to templates or route handlers if HTMX attributes, layout, or response codes don't match requirements
    - _Requirements: 2.5, 2.6, 8.4, 8.5_

- [ ] 6. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- The service layer, routes, and templates are already implemented — this plan focuses on validation and property-based testing
- Each property test validates specific correctness properties from the design document
- Property tests use Hypothesis (already in the project) with `@settings(max_examples=100)`
- Test file: `tests/test_operations_dashboard_properties.py`
- Existing tests: `tests/test_operations_dashboard.py` (unit + integration, already passing)
