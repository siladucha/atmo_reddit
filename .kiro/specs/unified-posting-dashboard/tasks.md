# Implementation Plan: Unified Posting Dashboard

## Overview

Implement a unified posting dashboard at `/admin/posting-dashboard` that consolidates EPG status and posting audit logs across all avatars into a single operational view. The implementation uses a new route module with 4 endpoints, HTMX lazy-loaded partials, cursor-based pagination, and server-side filtering — all gated by `require_platform_admin` RBAC.

## Tasks

- [x] 1. Database migration and indexes
  - [x] 1.1 Create Alembic migration for posting_events indexes
    - Add index `ix_posting_events_posted_at` on `posting_events(posted_at DESC)`
    - Add composite index `ix_posting_events_avatar_posted` on `posting_events(avatar_id, posted_at DESC)`
    - Verify existing `ix_epg_slots_avatar_date` covers EPG queries (no new EPG index needed)
    - _Requirements: 8.2, 8.3_

- [x] 2. Route module and service layer
  - [x] 2.1 Create `app/routes/posting_dashboard.py` with router and page shell endpoint
    - Define `router = APIRouter(prefix="/admin/posting-dashboard", tags=["posting-dashboard"])`
    - Implement `GET /admin/posting-dashboard` — renders `admin_posting_dashboard.html` page shell
    - Use `Depends(require_platform_admin)` for RBAC
    - Register router in `app/main.py` (import + `app.include_router`)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

  - [x] 2.2 Implement stats endpoint (`GET /admin/posting-dashboard/stats`)
    - Query EPG slots for today (Asia/Jerusalem) — COUNT DISTINCT avatar_id, COUNT total, COUNT posted
    - Query posting_events for today — COUNT success, COUNT failure
    - Compute success_rate_pct (handle division by zero → 0%)
    - Return HTMX partial `partials/posting_dashboard_stats.html`
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 2.3 Implement EPG panel endpoint (`GET /admin/posting-dashboard/epg-panel`)
    - Accept query params: `plan_date` (default today Asia/Jerusalem), `status_filter` (default "all"), `avatar_search` (default "")
    - Query epg_slots JOIN avatars LEFT JOIN comment_drafts, filtered by plan_date + status_filter + avatar_search
    - Group results by avatar in Python (defaultdict)
    - Compute EPG summary (per-status counts) from filtered results
    - Batch-load approval attribution from audit_logs (single query with `entity_id IN (...)`)
    - Return HTMX partial `partials/posting_dashboard_epg_panel.html`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 3.1, 3.2, 3.3, 3.4, 6.1, 6.2, 6.3_

  - [x] 2.4 Implement posting log endpoint (`GET /admin/posting-dashboard/posting-log`)
    - Accept query params: `outcome_filter` (default "all"), `avatar_search` (default ""), `date_from`, `date_to`, `cursor` (ISO timestamp)
    - Query posting_events JOIN avatars LEFT JOIN epg_slots, filtered by outcome + avatar + date range + cursor
    - Use cursor-based pagination: `WHERE posted_at < cursor ORDER BY posted_at DESC LIMIT 51` (fetch 51, return 50, detect has_more)
    - Format all datetimes in Asia/Jerusalem timezone
    - Return HTMX partial `partials/posting_dashboard_posting_log.html`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3, 5.4, 8.3_

  - [ ]* 2.5 Write property tests for pure filtering and grouping functions
    - **Property 2: Date Filter Correctness** — for any set of EPG slots spanning multiple dates and any selected date, only slots matching plan_date are returned
    - **Property 3: Avatar Grouping Integrity** — every slot within a group belongs to the stated avatar, no slot appears in more than one group
    - **Property 4: Status Summary Accuracy** — sum of per-status counts equals total slots, each count matches actual records
    - **Property 5: Status Filter Correctness** — filtered result contains only slots matching filter (or all if "all")
    - **Property 6: Avatar Substring Filter Correctness** — filtered result contains only records with matching username (case-insensitive)
    - **Validates: Requirements 2.1, 2.2, 2.9, 2.10, 3.1, 3.2, 3.3, 5.3**

  - [ ]* 2.6 Write property tests for pagination and stats functions
    - **Property 7: Posting Log Ordering and Cursor Pagination** — returned page has events strictly older than cursor, in descending order, limited to 50, next cursor equals last item's posted_at
    - **Property 8: Outcome Filter Correctness** — filtered result contains only events matching outcome filter
    - **Property 9: Date Range Filter Correctness** — filtered result contains only events within the specified range
    - **Property 10: Statistics Aggregation Correctness** — computed stats match expected counts and success_rate formula
    - **Property 11: Timezone Display Consistency** — formatting produces Asia/Jerusalem equivalent of UTC input
    - **Validates: Requirements 4.1, 4.7, 5.1, 5.2, 5.4, 6.2, 7.1, 7.2, 8.3**

- [x] 3. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Templates
  - [x] 4.1 Create page shell template `admin_posting_dashboard.html`
    - Extend `admin_base.html`, set title "Posting Dashboard"
    - Add three `div` containers with `hx-get` triggers for lazy-loading stats, EPG panel, and posting log
    - Stats container: `hx-trigger="load, every 60s"` for auto-refresh
    - EPG and posting log containers: `hx-trigger="load"`
    - Include skeleton loader placeholders for each panel
    - Set `active_nav = 'posting-dashboard'` for sidebar highlight
    - _Requirements: 7.3, 8.4_

  - [x] 4.2 Create stats partial `partials/posting_dashboard_stats.html`
    - Render summary cards: avatars with EPG, total slots, posts completed, failures, success rate %
    - Use dark theme card styling consistent with existing admin partials (bg-slate-800, rounded-xl, etc.)
    - _Requirements: 7.1, 7.2_

  - [x] 4.3 Create EPG panel partial `partials/posting_dashboard_epg_panel.html`
    - Render date picker input, status filter pills (all/planned/generated/approved/posted/skipped), avatar search input
    - Filters use `hx-get` targeting `#epg-panel-content` with appropriate `hx-include`
    - Avatar search: `hx-trigger="keyup changed delay:300ms"`
    - Render summary bar with per-status counts
    - Render grouped table: avatar username header → slot rows (slot_type, subreddit, title truncated 60 chars, scheduled_at, status badge, approver)
    - Status badges color-coded: gray/blue/yellow/green/red
    - Empty state: "No EPG slots for this date"
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 3.1, 3.2, 3.3, 3.4, 6.1, 6.2, 6.3_

  - [x] 4.4 Create posting log partial `partials/posting_dashboard_posting_log.html`
    - Render outcome filter pills, avatar search input, date range inputs (date_from, date_to)
    - Filters use `hx-get` targeting `#posting-log-content`
    - Render table rows: avatar username, outcome badge (green/red/gray), posted_at, duration_ms, subreddit, reddit_comment_url (clickable, opens new tab)
    - Error message visible on hover (title attribute) for failures
    - "Load More" button at bottom: `hx-get` with cursor param, `hx-swap="afterend"` to append rows
    - Hide "Load More" when no more results (has_more=False)
    - Empty state: "No posting events recorded"
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3, 5.4_

  - [ ]* 4.5 Write unit tests for template rendering and edge cases
    - Test status badge color mapping (5 status → 5 colors)
    - Test outcome badge color mapping (3 outcomes → 3 colors)
    - Test thread title truncation at boundary (59, 60, 61 chars)
    - Test empty state rendering for both panels
    - Test "Load More" visibility logic (has_more true/false)
    - _Requirements: 2.3, 2.4, 2.5, 2.6, 2.7, 4.3, 4.4, 4.5, 4.6_

- [x] 5. Sidebar navigation integration
  - [x] 5.1 Add "Posting Dashboard" navigation item to `admin_base.html` sidebar
    - Add link in the Operations section (visible to owner, partner, avatar_manager)
    - Use condition: `{% if is_owner or is_partner or is_avatar_mgr %}`
    - Highlight active state: `{% if active_nav == 'posting-dashboard' %}bg-indigo-600 text-white{% else %}...{% endif %}`
    - Place after "Activity" link and before "Users" link in the Operations section
    - Use appropriate SVG icon (chart/calendar style)
    - _Requirements: 9.1, 9.2, 9.3_

- [x] 6. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Integration tests and RBAC verification
  - [ ]* 7.1 Write integration tests for RBAC access control
    - **Property 1: RBAC Access Control** — endpoint returns 200 for owner/partner/avatar_manager, 403 for client_admin/client_manager/client_viewer/qa/b2c_user, redirect for unauthenticated
    - Test all 4 endpoints enforce `require_platform_admin`
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**

  - [ ]* 7.2 Write integration tests for endpoint responses
    - Seed test data: 3 avatars × 5 EPG slots each + 20 posting events
    - Test stats endpoint returns correct aggregates
    - Test EPG panel filters by date, status, avatar_search
    - Test posting log filters by outcome, avatar, date_range
    - Test cursor pagination (first page no cursor, load more with cursor, last page no Load More)
    - Test HTMX partial responses (check HX-Request header handling)
    - _Requirements: 8.1, 8.4_

- [x] 8. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The route module is standalone (`posting_dashboard.py`) to avoid bloating `admin.py` (7900+ lines)
- All datetime display uses `zoneinfo.ZoneInfo("Asia/Jerusalem")` for timezone conversion
- Approval attribution uses batch query on `audit_logs` table to avoid N+1

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4"] },
    { "id": 3, "tasks": ["2.5", "2.6", "4.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "4.4"] },
    { "id": 5, "tasks": ["4.5", "5.1"] },
    { "id": 6, "tasks": ["7.1", "7.2"] }
  ]
}
```
