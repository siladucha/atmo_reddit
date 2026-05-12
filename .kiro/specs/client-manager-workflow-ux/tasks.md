# Implementation Plan: Client Manager Workflow UX

## Overview

This plan implements 10 interconnected improvements to the admin panel UX: sidebar restructuring with badges, enhanced Client Hub with tabs, batch operations, aging alerts, client filter, priority banner, action log widget, audit coverage expansion, and post-approval UX improvement. All changes use server-rendered Jinja2 + HTMX partials with no new database migrations.

## Tasks

- [ ] 1. Sidebar navigation restructuring and badge infrastructure
  - [ ] 1.1 Restructure sidebar groups in `app/templates/admin_base.html`
    - Reorganize links into four groups: "Daily Work", "Clients & Content", "Monitoring", "Settings"
    - Apply brighter text color (`text-gray-300`) and `border-l-2 border-indigo-500` accent to "Daily Work" group
    - Add badge container spans with `hx-get` and `hx-trigger="load, every 60s"` to "Review Queue" and "Scrape Queue" links
    - Ensure active link highlighting works across all groups
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [ ] 1.2 Implement badge count service functions in `app/services/operations_dashboard.py`
    - Add `get_pending_review_count(db)` — count CommentDraft + PostDraft with status="pending"
    - Add `get_stale_subreddit_count(db)` — count active subreddits where `last_scraped_at` > freshness window or NULL
    - Add `badge_color(count, red_threshold, amber_threshold=1)` pure function
    - _Requirements: 2.1, 2.2, 2.4, 2.5_

  - [ ] 1.3 Create badge partial endpoint and template
    - Add `GET /admin/partials/nav-badges` endpoint in `app/routes/admin.py`
    - Create `app/templates/partials/nav_badges.html` template with pill-shaped badges, min-width 20px, font-size ≥12px
    - Apply color logic: Review Queue red_threshold=10, Scrape Queue red_threshold=5
    - Hide badge when count is 0
    - _Requirements: 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

  - [ ]* 1.4 Write property tests for badge color function (Property 2)
    - **Property 2: Badge Color Determination**
    - Test that badge_color returns correct class for all count/threshold combinations
    - **Validates: Requirements 2.4, 2.5**

  - [ ]* 1.5 Write property tests for badge count accuracy (Property 1)
    - **Property 1: Badge Count Accuracy**
    - Test that pending count equals sum of pending CommentDraft + PostDraft records
    - Test that stale count equals subreddits with NULL or expired last_scraped_at
    - **Validates: Requirements 2.1, 2.2**

- [ ] 2. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 3. Enhanced Client Hub with tabbed interface
  - [ ] 3.1 Create Client Hub tabbed layout and overview tab
    - Refactor `GET /admin/clients/{id}` to render tabbed interface with Overview selected by default
    - Create `app/templates/admin_client_detail.html` with tab navigation using `hx-get` + `hx-target="#tab-content"`
    - Implement overview tab endpoint `GET /admin/clients/{id}/tab/overview` returning stats (subreddit_count, avatar_count, pending_reviews, threads_24h, comments_24h) and pipeline control buttons
    - Set `active_nav = "clients"` in template context
    - Return HTTP 404 for non-existent client_id
    - _Requirements: 3.1, 3.2, 3.9, 3.10_

  - [ ] 3.2 Implement pipeline trigger from Client Hub
    - Wire pipeline control buttons (Scrape, Score, Generate, Full Pipeline) to dispatch Celery tasks for the current client
    - Return confirmation indicator within 2 seconds
    - Add audit log entry for pipeline trigger (action="trigger_pipeline", entity_type="task")
    - Include `HX-Trigger: actionPerformed` header in response for action log refresh
    - _Requirements: 3.3, 9.3_

  - [ ] 3.3 Implement Subreddits tab with freshness indicators
    - Create endpoint `GET /admin/clients/{id}/tab/subreddits`
    - Create partial template listing subreddits with name, last_scraped_at, freshness color indicator, and "Scrape Now" button
    - Implement `freshness_color(last_scraped_at, now)` pure function (green ≤12h, amber 12-24h, red >24h or NULL)
    - _Requirements: 3.4_

  - [ ]* 3.4 Write property test for subreddit freshness color (Property 3)
    - **Property 3: Subreddit Freshness Color**
    - Test freshness_color returns correct color for all timestamp/now combinations
    - **Validates: Requirements 3.4**

  - [ ] 3.5 Implement Avatars, Review, and Reports tabs
    - Create endpoint `GET /admin/clients/{id}/tab/avatars` — list avatars with warming_phase, health_status, confidence score, link to detail page
    - Create endpoint `GET /admin/clients/{id}/tab/review` — pending drafts filtered to client with approve/reject/edit actions
    - Create endpoint `GET /admin/clients/{id}/tab/reports` — pipeline stats from transparency service
    - Create partial templates for each tab
    - _Requirements: 3.5, 3.6, 3.8_

  - [ ] 3.6 Implement Activity tab
    - Create endpoint `GET /admin/clients/{id}/tab/activity`
    - Query 20 most recent ActivityEvent records for client, ordered by created_at descending
    - Display event_type, description, and timestamp for each entry
    - _Requirements: 3.7, 3.8_

  - [ ]* 3.7 Write property test for activity events filtering and ordering (Property 4)
    - **Property 4: Activity Events Filtered and Ordered**
    - Test that results are filtered by client_id, ordered descending, limited to 20
    - **Validates: Requirements 3.7**

- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Batch operations for review queue
  - [ ] 5.1 Create batch operation endpoint and request schema
    - Define `BatchReviewRequest` Pydantic model with action (approve/reject) and ids (max 50 UUIDs)
    - Implement `POST /admin/review/batch` endpoint in `app/routes/admin.py`
    - Processing logic: query drafts by ID, transition pending ones, skip non-pending with reason, create audit + activity entries per draft, trigger learning capture
    - Return summary HTML partial with success count and skipped IDs
    - Add batch audit log entry (action="batch_approve"/"batch_reject")
    - _Requirements: 4.3, 4.4, 4.5, 4.8, 9.4_

  - [ ] 5.2 Implement batch operation frontend UI
    - Add checkboxes next to each pending draft in review queue template
    - Add "Select All on Page" checkbox in table header
    - Create floating action bar (fixed bottom, centered) with "Approve Selected", "Reject Selected" buttons and selection count
    - JavaScript: track selected IDs in Set, show/hide action bar based on count
    - Wire buttons to POST `/admin/review/batch` with HTMX, refresh draft list on completion
    - _Requirements: 4.1, 4.2, 4.6, 4.7_

  - [ ]* 5.3 Write property test for batch operation correctness (Property 5)
    - **Property 5: Batch Operation Correctness**
    - Test that pending drafts transition, non-pending are skipped, counts are accurate
    - **Validates: Requirements 4.3, 4.4, 4.5**

- [ ] 6. Aging alerts and review queue sort order
  - [ ] 6.1 Implement aging status and relative time functions
    - Add `aging_status(created_at, now)` pure function in service layer — returns None (<24h), amber warning (24-48h), red critical (≥48h)
    - Add `relative_time(created_at, now)` pure function — returns "{X}h ago" or "{X}d ago"
    - _Requirements: 5.1, 5.2, 5.5_

  - [ ] 6.2 Integrate aging alerts into review queue template
    - Render aging alert indicators (amber/red with label) next to pending drafts
    - Display relative timestamps for each draft
    - Change default sort order to oldest-first (ascending created_at)
    - Add "Thread Locked" badge for CommentDraft items where `draft.thread.is_locked == True`
    - Do NOT show "Thread Locked" badge for PostDraft items
    - _Requirements: 5.3, 5.4, 5.6, 5.7_

  - [ ]* 6.3 Write property tests for aging status (Property 6)
    - **Property 6: Aging Status Determination**
    - Test aging_status returns correct level/color/label for all timestamp differences
    - **Validates: Requirements 5.1, 5.2**

  - [ ]* 6.4 Write property test for relative timestamp formatting (Property 7)
    - **Property 7: Relative Timestamp Formatting**
    - Test relative_time returns correct format for all hour differences
    - **Validates: Requirements 5.5**

- [ ] 7. Client filter enhancement for review queue
  - [ ] 7.1 Implement HTMX client filter with URL push
    - Add `hx-get="/admin/review"` + `hx-push-url="true"` + `hx-target="#review-content"` to client select element
    - Add `hx-include` to preserve other filter values (status, sort, subreddit, avatar, age)
    - Wrap draft list + stats bar in `<div id="review-content">` target
    - Render empty state partial when filtered query returns 0 results
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ]* 7.2 Write property test for client filter correctness (Property 8)
    - **Property 8: Client Filter Correctness**
    - Test that filtered results only contain drafts matching the specified client_id
    - **Validates: Requirements 6.2**

- [ ] 8. Priority banner on dashboard
  - [ ] 8.1 Implement priority items service function
    - Add `get_priority_items(db)` in `app/services/operations_dashboard.py`
    - Query: (1) shadowbanned/suspended active avatars, (2) pipeline failures last 24h (ActivityEvent with error in metadata), (3) stale subreddits >24h, (4) drafts pending >24h
    - Return sorted list by fixed priority order with count, type, and link params
    - _Requirements: 7.1, 7.2_

  - [ ] 8.2 Create priority banner endpoint and template
    - Add `GET /admin/partials/priority-banner` endpoint in `app/routes/admin.py`
    - Create `app/templates/partials/priority_banner.html` — horizontal bar with colored pills, each linking to relevant page with pre-applied filters
    - Show "All clear — no urgent items" green message when no items
    - Add `hx-trigger="load, every 60s"` to banner container on dashboard
    - Retain last content on fetch failure with subtle error indicator
    - _Requirements: 7.3, 7.4, 7.5, 7.6_

  - [ ]* 8.3 Write property test for priority banner ordering (Property 9)
    - **Property 9: Priority Banner Ordering and Structure**
    - Test that items are sorted by fixed priority order and each has count > 0 with link
    - **Validates: Requirements 7.1, 7.2, 7.5**

- [ ] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Action log widget for Client Hub
  - [ ] 10.1 Implement action log widget endpoint and template
    - Add `GET /admin/clients/{id}/action-log` endpoint in `app/routes/admin.py`
    - Query 20 most recent AuditLog entries for client_id, ordered by created_at descending
    - Join User table for user names, display "System" for NULL user_id
    - Format timestamps: relative if <24h, absolute if older
    - Extract summary from details JSONB; fallback to "{action} {entity_type}" when NULL/empty
    - Create `app/templates/partials/client_action_log.html` template
    - Add `hx-trigger="actionPerformed from:body"` for auto-refresh
    - Include "View All" link to `/admin/audit-logs?client_id={id}`
    - Show empty state when no entries exist
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [ ]* 10.2 Write property test for action log widget query (Property 10)
    - **Property 10: Action Log Widget Query Correctness**
    - Test that results are filtered by client_id, ordered descending, limited to 20, with correct display fields
    - **Validates: Requirements 8.1, 8.2, 8.3**

- [ ] 11. Audit log coverage expansion
  - [ ] 11.1 Add audit logging to backup, deletion, and pipeline triggers
    - Add `audit_service.log_action()` call to backup trigger handler (action="trigger_backup", entity_type="system")
    - Add `audit_service.log_action()` call BEFORE audit log deletion (action="delete_audit_logs", entity_type="audit_log", details with count + filters)
    - Add `audit_service.log_action()` call to pipeline trigger handlers from dashboard/Client Hub (action="trigger_pipeline", entity_type="task", details with pipeline_type + target_entity_id)
    - Ensure user_id is always set from authenticated operator
    - _Requirements: 9.1, 9.2, 9.3, 9.5_

  - [ ]* 11.2 Write property test for operator audit entries (Property 11)
    - **Property 11: Operator Audit Entries Include User ID**
    - Test that all operator-initiated audit entries have non-NULL user_id matching authenticated user
    - **Validates: Requirements 9.5**

- [ ] 12. Post-approval UX improvement
  - [ ] 12.1 Modify approve response and implement mark-as-posted flow
    - Change approve response to return inline "✓ Approved" confirmation element (no "Mark as Posted" form)
    - Enhance "Approved" status tab to show approved-but-not-posted drafts with thread title, subreddit, avatar username, and "Mark as Posted" button
    - Implement inline form expansion via HTMX with URL input field
    - Create `POST /admin/review/mark-posted/{draft_id}` endpoint
    - Implement `validate_reddit_url(url)` function — accept URLs starting with "https://www.reddit.com/" or "https://reddit.com/", max 2048 chars, non-empty
    - On valid URL: transition to "posted", store URL, return "Posted" confirmation
    - On invalid URL: return inline validation error, do not transition status
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [ ]* 12.2 Write property test for Reddit URL validation (Property 12)
    - **Property 12: Reddit URL Validation**
    - Test validate_reddit_url accepts valid Reddit URLs and rejects all others
    - **Validates: Requirements 10.4, 10.5, 10.6**

- [ ] 13. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties using Hypothesis (minimum 100 iterations each)
- Unit tests validate specific examples and edge cases
- No database migrations required — all features use existing models
- All new UI is server-rendered Jinja2 + HTMX (consistent with existing stack)
- Badge/banner polling uses `hx-trigger="every 60s"` for near-real-time updates

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "6.1"] },
    { "id": 2, "tasks": ["1.4", "1.5", "3.1", "6.3", "6.4"] },
    { "id": 3, "tasks": ["3.2", "3.3", "3.5", "3.6", "6.2", "7.1", "8.1"] },
    { "id": 4, "tasks": ["3.4", "3.7", "5.1", "7.2", "8.2"] },
    { "id": 5, "tasks": ["5.2", "5.3", "8.3", "10.1", "11.1"] },
    { "id": 6, "tasks": ["10.2", "11.2", "12.1"] },
    { "id": 7, "tasks": ["12.2"] }
  ]
}
```
