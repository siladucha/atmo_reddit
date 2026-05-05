# Implementation Plan: Client Hub Navigation

## Overview

This plan transforms the monolithic client detail page into a tabbed Client Hub with 7 sections (Overview, Subreddits, Avatars, Personas, Threads, Review, Reports). Implementation proceeds bottom-up: core constants and helper functions first, then route handlers, then templates (hub shell → tab bar → tab partials), then navigation adaptation, and finally wiring and integration tests. Property-based tests (Hypothesis) are interleaved with implementation to catch regressions early.

## Tasks

- [ ] 1. Add core constants, helper functions, and extend `_render()`
  - [x] 1.1 Add `ALLOWED_TABS` constant and tab resolution helper to `pages.py`
    - Add `ALLOWED_TABS = ("overview", "subreddits", "avatars", "personas", "threads", "review", "reports")` as a module-level constant in `reddit_saas/app/routes/pages.py`
    - Implement `_resolve_tab(tab: str) -> str` pure function that returns `tab` if it is in `ALLOWED_TABS`, otherwise returns `"overview"`
    - _Requirements: 2.2, 2.3_

  - [x] 1.2 Add freshness indicator helper function
    - Implement `_freshness_color(last_scraped_at: datetime | None) -> str` pure function in `pages.py`
    - Returns `"green"` if scraped within 24 hours, `"yellow"` if within 72 hours, `"red"` if older or `None`
    - _Requirements: 4.2_

  - [x] 1.3 Add voice profile truncation helper function
    - Implement `_truncate_voice_profile(text: str | None, max_len: int = 200) -> str` pure function in `pages.py`
    - Returns the first `max_len` characters of the input string, or empty string if `None`
    - _Requirements: 6.2_

  - [x] 1.4 Extend `_render()` to inject `current_client_id`
    - In the `_render()` function, add `current_client_id` (string UUID or `None`) to the template context when the user is a Client_User with a `client_id`
    - This enables `base.html` to render client-specific navigation links
    - _Requirements: 11.1, 11.5_

  - [ ]* 1.5 Write property test for tab resolution (Property 1)
    - **Property 1: Tab resolution falls back to overview for invalid input**
    - Generate arbitrary strings with `st.text()`; verify `_resolve_tab` returns the input if it is in `ALLOWED_TABS`, otherwise returns `"overview"`
    - Also test all 7 valid tab names explicitly
    - **Validates: Requirements 2.2, 2.3**

  - [ ]* 1.6 Write property test for freshness indicator (Property 2)
    - **Property 2: Freshness indicator is determined by scrape recency**
    - Generate arbitrary datetimes with `st.datetimes()` and `st.none()`; verify color output matches the 24h/72h/older thresholds
    - **Validates: Requirements 4.2**

  - [ ]* 1.7 Write property test for voice profile truncation (Property 3)
    - **Property 3: Voice profile truncation preserves prefix**
    - Generate arbitrary strings with `st.text()`; verify output length ≤ 200 and output is a prefix of the original
    - **Validates: Requirements 6.2**

- [x] 2. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 3. Implement tab data loader functions
  - [x] 3.1 Implement `_tab_overview(client_id, db)` data loader
    - Query Client, count of active subreddits, count of assigned avatars, total threads count, engage-tagged threads count, pending comments count
    - Return a context dict with all metric values and the client's company profile fields
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 3.2 Implement `_tab_subreddits(client_id, db)` data loader
    - Query active `ClientSubreddit` records for the client
    - Compute freshness color for each subreddit using `_freshness_color()`
    - Return list of subreddits with name, type, `last_scraped_at`, and freshness color
    - _Requirements: 4.1, 4.2_

  - [x] 3.3 Implement `_tab_avatars(client_id, db, is_admin)` data loader
    - Query active avatars filtered by `client_ids` containing the client UUID
    - If `is_admin`, also query unassigned avatars (those without this client in `client_ids`)
    - Return client avatars list and unassigned avatars list (empty for non-admins)
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 3.4 Implement `_tab_personas(client_id, db)` data loader
    - Query `Persona` records for the client
    - Truncate voice profiles using `_truncate_voice_profile()`
    - Return list of personas with name, platform, active status, truncated voice profile, and full voice profile
    - _Requirements: 6.1, 6.2_

  - [x] 3.5 Implement `_tab_threads(client_id, db, tag)` data loader
    - Query `RedditThread` records for the client, optionally filtered by tag
    - Order by `created_at` descending, limit to 100
    - Return list of threads with title, subreddit, tag, composite score, and URL
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x] 3.6 Implement `_tab_review(client_id, db, status)` data loader
    - Query `CommentDraft` records filtered by client_id and status, limit 50
    - Join with `RedditThread` and `Avatar` to enrich each draft
    - Return enriched drafts list with thread title, avatar username, engagement mode, and AI draft text
    - _Requirements: 8.1, 8.4, 8.5_

  - [x] 3.7 Implement `_tab_reports(client_id, db)` data loader
    - Query comment draft counts grouped by status for the client
    - Query total AI cost (sum of `AIUsageLog.cost_usd`) for the client
    - Query thread counts grouped by tag for the client
    - Query count of active avatars assigned to the client
    - Return aggregated stats dict
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [ ]* 3.8 Write property test for thread tag filtering (Property 4)
    - **Property 4: Thread tag filter returns only matching threads**
    - Generate lists of thread-like dicts with random tags from `{"engage", "monitor", "skip"}` and a random filter; verify filtered results contain only matching tags
    - When filter is `None` or `"all"`, all threads are returned
    - **Validates: Requirements 7.2, 7.3**

- [ ] 4. Implement hub page and tab dispatch route handlers
  - [x] 4.1 Implement `client_hub()` route handler — GET `/clients/{client_id}`
    - Replace the existing `client_detail()` route with `client_hub()`
    - Accept `client_id: UUID` and `tab: str = "overview"` query parameter
    - Validate access: 404 if client not found, 403 if Client_User accessing another client
    - Resolve tab using `_resolve_tab(tab)`
    - Render `client_hub.html` with `client`, `active_tab`, and user context
    - _Requirements: 1.1, 1.5, 2.1, 2.2, 2.3, 12.1, 12.2, 12.4_

  - [x] 4.2 Implement `client_hub_tab()` route handler — GET `/clients/{client_id}/tab/{tab_name}`
    - Accept `client_id: UUID` and `tab_name: str` path parameter
    - Validate access: 404 if client not found, 403 if Client_User accessing another client
    - If `tab_name` not in `ALLOWED_TABS`, return 404
    - If non-HTMX request (no `HX-Request` header), redirect to `/clients/{client_id}?tab={tab_name}` with 303
    - Dispatch to the appropriate `_tab_*` data loader based on `tab_name`
    - For threads tab, accept optional `tag` query parameter
    - For review tab, accept optional `status` query parameter (default `"pending"`)
    - Render the corresponding `partials/client_hub_{tab_name}.html` template
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 12.1, 12.2, 12.4_

  - [ ]* 4.3 Write property test for invalid tab names return 404 (Property 7)
    - **Property 7: Invalid tab names return 404**
    - Generate arbitrary strings not in `ALLOWED_TABS` with `st.text().filter(lambda s: s not in ALLOWED_TABS)`
    - Verify GET `/clients/{client_id}/tab/{that_string}` returns HTTP 404
    - Use FastAPI `TestClient` with a test database fixture
    - **Validates: Requirements 10.4**

  - [ ]* 4.4 Write property test for access control (Property 8)
    - **Property 8: Access control enforces client isolation**
    - Generate combinations of user roles (admin, client_user) and client IDs
    - Verify: Admin_User gets 200 for any client, Client_User gets 200 for own client and 403 for others
    - Use FastAPI `TestClient` with test database fixtures
    - **Validates: Requirements 12.1, 12.2**

- [x] 5. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Create hub page and tab bar templates
  - [x] 6.1 Create `client_hub.html` template
    - Extends `base.html`
    - Renders client header: name, brand name, back link to dashboard (for admins)
    - Includes `partials/client_hub_tabs.html` with `active_tab` and `client.id`
    - Contains `<div id="tab-content">` with `hx-get="/clients/{{ client.id }}/tab/{{ active_tab }}"` and `hx-trigger="load"` to eagerly load the default tab
    - Includes HTMX script tag
    - _Requirements: 1.1, 1.5, 2.1, 13.1_

  - [x] 6.2 Create `partials/client_hub_tabs.html` tab bar partial
    - Renders horizontal tab bar with 7 tabs: Overview, Subreddits, Avatars, Personas, Threads, Review, Reports
    - Each tab is an `<a>` element with `hx-get`, `hx-target="#tab-content"`, `hx-swap="innerHTML"`, and `hx-push-url`
    - Active tab has distinct Tailwind styling (`border-b-2 border-blue-600 text-blue-600`)
    - Inactive tabs have `text-gray-500 hover:text-gray-700` styling
    - Uses `hx-push-url="/clients/{{ client_id }}?tab={{ tab_slug }}"` for URL state management
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 13.1_

- [ ] 7. Create tab content partial templates
  - [x] 7.1 Create `partials/client_hub_overview.html`
    - Metric cards grid: subreddits count, avatars count, threads count, engage count, pending comments count
    - Collapsible company profile section (worldview, problem, competitive landscape)
    - Pipeline control buttons (Scrape, Score, Generate, Full Pipeline) with `hx-post` to existing pipeline endpoints
    - Pipeline status area `<div id="pipeline-status">`
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 7.2 Create `partials/client_hub_subreddits.html`
    - List of subreddits with name, type, and freshness dot (green/yellow/red based on `last_scraped_at`)
    - Inline add form with subreddit name and type fields, submitting via `hx-post` to existing subreddit endpoint
    - Empty state message when no subreddits exist
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 7.3 Create `partials/client_hub_avatars.html`
    - Avatar cards showing reddit username, karma (comment/post), reddit status badge (color-coded), shadowban warning
    - Unassigned avatars section (visible only for admins) with "Assign" buttons using `hx-post`
    - Empty state message when no avatars assigned
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 7.4 Create `partials/client_hub_personas.html`
    - Persona cards showing name, platform, active status badge, truncated voice profile (200 chars)
    - Click-to-expand for full voice profile text (using Tailwind `hidden`/`block` toggle or HTMX)
    - Empty state message when no personas exist
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 7.5 Create `partials/client_hub_threads.html`
    - Tag filter buttons (All, Engage, Monitor, Skip) using `hx-get` to reload the threads tab with `tag` parameter
    - Thread list showing title, subreddit, tag badge, composite score, and external Reddit URL link
    - Limit display to 100 threads
    - Empty state message when no threads found
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x] 7.6 Create `partials/client_hub_review.html`
    - Status filter tabs (Pending, Approved, Posted, Rejected) using `hx-get` to reload with `status` parameter
    - Draft cards showing thread title, avatar username, engagement mode, AI draft text
    - Approve and Reject buttons using `hx-post` to existing review endpoints
    - Limit display to 50 drafts
    - Empty state message when no drafts found
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 7.7 Create `partials/client_hub_reports.html`
    - Stats cards: comment drafts by status (pending, approved, rejected, posted)
    - Thread counts by tag (engage, monitor, skip)
    - Total AI cost (USD) for the client
    - Active avatars count
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [ ] 8. Adapt navigation bar for client-bound users
  - [x] 8.1 Modify `base.html` navigation for Client_Users
    - Add conditional block: if `current_user_role == 'Client'` and `current_client_id`, render client hub tab links (Overview, Subreddits, Avatars, Personas, Threads, Review, Reports) pointing to `/clients/{{ current_client_id }}?tab={tab_name}`
    - Hide global Dashboard, Avatars, and Personas links for Client_Users
    - Keep existing global navigation unchanged for Admin_Users
    - Display client name next to the role badge for Client_Users
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

- [x] 9. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Integration tests for HTMX dispatch and access control
  - [ ]* 10.1 Write integration tests for HTMX vs non-HTMX dispatch (Properties 5 & 6)
    - **Property 5: HTMX tab requests return partial HTML fragments**
    - **Property 6: Non-HTMX tab requests redirect to the hub page**
    - For each of the 7 valid tabs: verify HTMX request returns HTML fragment (no `<html>` or `<body>` tags), non-HTMX request returns 303 redirect to `/clients/{id}?tab={name}`
    - Use FastAPI `TestClient` with test database fixtures
    - **Validates: Requirements 10.2, 10.3**

  - [ ]* 10.2 Write integration tests for hub page and tab content
    - Test hub page returns 200 with default overview tab
    - Test hub page returns 200 with each valid tab via `?tab=` parameter
    - Test overview tab partial returns metric values
    - Test subreddits tab partial returns subreddit list
    - Test avatars tab partial includes unassigned section for admin, excludes for client user
    - Test personas tab partial returns persona fields
    - Test threads tab partial respects 100 limit
    - Test review tab partial filters by client_id and respects 50 limit
    - Test reports tab partial returns all stat categories
    - Test non-existent client returns 404
    - Test unauthenticated request redirects to login
    - **Validates: Requirements 2.1, 3.1–3.4, 4.1, 5.1–5.3, 6.1, 7.1, 8.1, 8.5, 9.1–9.4, 12.3, 12.4**

  - [ ]* 10.3 Write integration tests for navigation adaptation
    - Test nav bar shows hub links for client user (contains `/clients/{id}?tab=` links)
    - Test nav bar shows global links for admin user (contains `/`, `/review`, `/avatars-page`)
    - Test `current_client_id` is injected in template context for client users
    - Test nav bar hides Dashboard, Avatars, Personas links for client users
    - **Validates: Requirements 11.1, 11.2, 11.3, 11.4**

  - [ ]* 10.4 Write integration test for URL state management
    - Test that tab bar links include `hx-push-url` attribute with correct URL pattern
    - Test that hub page content area has `hx-trigger="load"` for eager tab loading
    - **Validates: Requirements 13.1, 13.2**

- [x] 11. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate 6 of the 8 correctness properties from the design (Properties 1–4, 7, 8) using Hypothesis PBT
- Properties 5 and 6 (HTMX vs non-HTMX dispatch) are covered as example-based integration tests since the tab set is small and fixed
- Unit tests validate specific examples and edge cases
- No new database models or migrations are required — the feature reads from existing models
- All test files go in `reddit_saas/tests/test_client_hub_navigation.py`
