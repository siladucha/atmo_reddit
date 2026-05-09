# Implementation Plan: Avatar Daily Timeline

## Overview

Implement a "Timeline" tab on the avatar detail page that displays a full day-by-day history of avatar activity from creation to today. The implementation follows the existing HTMX lazy-loading pattern with a dedicated service layer, server-side pagination (60 days/page), and property-based tests for correctness validation.

## Tasks

- [ ] 1. Create timeline service with data models and core logic
  - [ ] 1.1 Create `app/services/avatar_timeline.py` with dataclasses and aggregation logic
    - Define `DayEntry`, `PhaseEvent`, `TimelineSummary`, `PaginationMeta`, `TimelineResult` dataclasses
    - Implement `get_avatar_timeline(db, avatar_id, avatar_username, avatar_created_at, page, per_page)` function
    - Calculate full date range: `max(avatar_created_at, today - 3650 days)` to today
    - Implement reverse-chronological page slicing (page 1 = most recent 60 days)
    - Run CommentDraft aggregation query (avatar_id, status="posted", grouped by UTC date)
    - Run HobbySubreddit aggregation query (avatar_username, status="posted", non-NULL created_at, grouped by UTC date)
    - Run PostDraft aggregation query (avatar_id, status="posted", grouped by UTC date)
    - Run ActivityEvent query for phase events (phase_promotion, auto_downgrade, phase_override)
    - Merge query results into DayEntry objects, filling gaps with zero-value entries
    - Compute summary statistics (totals across full timeline, avatar age, current phase)
    - Handle edge cases: invalid page clamping, NULL reddit_score as 0, 10-year cap
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.1, 2.2, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 6.1, 6.2, 6.3_

  - [ ]* 1.2 Write property test: Day Coverage Completeness (Property 1)
    - **Property 1: Day Coverage Completeness**
    - Generate random avatar creation dates (1 to 3650 days ago) and verify exactly one DayEntry per calendar day with no gaps or duplicates
    - **Validates: Requirements 1.1, 1.7, 1.8**

  - [ ]* 1.3 Write property test: Activity Aggregation Correctness (Property 2)
    - **Property 2: Activity Aggregation Correctness**
    - Generate random CommentDraft, HobbySubreddit, PostDraft records and verify day counts/karma match records whose timestamps fall within each UTC day
    - **Validates: Requirements 1.2, 1.3, 1.4, 1.5, 1.6, 6.1, 6.2, 6.3**

  - [ ]* 1.4 Write property test: Phase Event Extraction (Property 3)
    - **Property 3: Phase Event Extraction**
    - Generate random ActivityEvent records and verify only matching phase events are returned with correct fields, ordered by created_at ascending
    - **Validates: Requirements 2.1, 2.2, 2.4, 2.5**

  - [ ]* 1.5 Write property test: Summary Totals Consistency (Property 4)
    - **Property 4: Summary Totals Consistency**
    - Verify summary totals equal the sum across all day entries in the full timeline (not just current page)
    - **Validates: Requirements 3.3, 3.4, 3.5**

  - [ ]* 1.6 Write property test: Reverse Chronological Ordering (Property 5)
    - **Property 5: Reverse Chronological Ordering**
    - Verify entries list is sorted in strictly descending date order for any generated timeline
    - **Validates: Requirements 4.2**

  - [ ]* 1.7 Write property test: Pagination Correctness (Property 6)
    - **Property 6: Pagination Correctness**
    - For any total days N and per_page=60, verify total_pages=ceil(N/60), has_next/has_previous flags, and page entry counts
    - **Validates: Requirements 4.5**

  - [ ]* 1.8 Write property test: Avatar Age Calculation (Property 7)
    - **Property 7: Avatar Age Calculation**
    - For any avatar created_at and current date, verify avatar_age_days equals (today - created_at.date()).days
    - **Validates: Requirements 3.1**

- [ ] 2. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 3. Add route handler and integrate with admin page
  - [ ] 3.1 Add timeline-partial route to `app/routes/admin.py`
    - Implement `GET /admin/avatars/{avatar_id}/timeline-partial` endpoint
    - Accept `page` query parameter (default 1)
    - Use `require_superuser` dependency for auth
    - Fetch avatar from DB, return 404 if not found
    - Call `get_avatar_timeline()` with avatar data
    - Render and return `partials/avatar_timeline.html` template
    - Handle database errors gracefully (return error template with retry button)
    - _Requirements: 5.1, 5.3, 5.4_

  - [ ] 3.2 Add "Timeline" tab button and panel to `app/templates/admin_avatar_detail.html`
    - Insert tab button after "Performance" tab with `data-avatar-detail-tab="timeline"`
    - Add tab panel with `data-avatar-detail-panel="timeline"` containing HTMX lazy-load div
    - Use `hx-get="/admin/avatars/{{ avatar.id }}/timeline-partial"` with `hx-trigger="intersect once"`
    - Add `hx-request='{"timeout": 5000}'` for 5-second timeout
    - Include loading spinner as default content before HTMX swap
    - _Requirements: 4.1, 5.1, 5.2_

- [ ] 4. Create timeline partial template
  - [ ] 4.1 Create `app/templates/partials/avatar_timeline.html`
    - Render summary header: avatar age, current phase, phase_changed_at, lifetime totals (comments, hobby comments, posts, karma)
    - Render day-entry table with fixed-width columns: date (YYYY-MM-DD), professional comments, hobby comments, posts, karma total
    - Apply lighter background to active day rows (has_activity = true)
    - Render phase event icons (promotion ⬆, downgrade ⬇, override ↔) adjacent to day rows with reason text when available
    - Implement pagination controls (previous/next) using HTMX `hx-get` with page parameter, targeting `#timeline-panel-content`
    - Handle empty state: display "No timeline data available yet" message
    - Handle error state: display error message with retry button
    - Use Tailwind CSS classes consistent with existing admin dark theme
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.2, 4.3, 4.4, 4.5, 4.6, 2.3, 2.4, 2.5, 5.3, 5.4, 5.5_

- [ ] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Write unit and integration tests
  - [ ]* 6.1 Write unit tests for timeline service in `tests/test_avatar_timeline.py`
    - Test empty avatar (created today, no records) → 1 day entry with zeros
    - Test single day activity (3 comments, 2 hobby, 1 post) → correct counts
    - Test NULL karma handling → treated as 0
    - Test 10-year cap (avatar created 15 years ago) → only 3650 days returned
    - Test phase event rendering (with/without reasons)
    - Test pagination boundary (60 days → 1 page, 61 days → 2 pages)
    - Test HobbySubreddit NULL created_at → excluded from count
    - Test multiple phase events same day → all returned on correct day
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.1, 2.2, 6.3_

  - [ ]* 6.2 Write integration tests in `tests/test_avatar_timeline_integration.py`
    - Test route returns 200 with valid avatar
    - Test route returns 404 with non-existent avatar ID
    - Test pagination navigation (page=2 returns correct slice)
    - _Requirements: 5.1, 4.5_

- [ ] 7. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The design specifies Python (FastAPI + SQLAlchemy) — all code uses Python 3.11+
- No new database migrations are needed; the feature reads from existing tables only
- The existing `karma_history.py` service provides a reference pattern for the new timeline service

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8"] },
    { "id": 2, "tasks": ["3.1", "3.2"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["6.1", "6.2"] }
  ]
}
```
