# Implementation Plan: Admin Panel & Client Onboarding

## Overview

This plan implements a comprehensive admin panel with dark theme, sidebar navigation, full CRUD for users/clients/personas/subreddits/keywords, a 7-step client onboarding wizard, Celery task monitoring, system health dashboard, AI cost tracking, audit logs, billing placeholder, and NeuroYoga seed data. The implementation builds incrementally: infrastructure first (route migration, auth dependency, base template), then service layer, then routes and templates, then the onboarding wizard, then seed data, and finally tests.

## Tasks

- [x] 1. Route migration and admin infrastructure
  - [x] 1.1 Move existing dashboard.py routes from `/admin` to `/api/admin` prefix
    - In `app/main.py`, change `app.include_router(dashboard.router, prefix="/admin", ...)` to `app.include_router(dashboard.router, prefix="/api/admin", ...)`
    - Update existing `tests/test_admin.py` to use `/api/admin/stats` and `/api/admin/ai-usage` paths
    - Verify all 60 existing tests still pass after the prefix change
    - _Requirements: 1.6 (preserve non-admin pages), Design §6 (route conflict resolution)_

  - [x] 1.2 Create `require_superuser` FastAPI dependency
    - Create `app/dependencies/__init__.py` and `app/dependencies/admin.py`
    - Implement `require_superuser(request, db)` that checks `request.state.user_id`, loads User from DB, verifies `is_active` and `is_superuser`
    - Return User object on success; raise `HTTPException(303)` redirect to `/login` if unauthenticated; raise `HTTPException(403)` if not superuser
    - _Requirements: 1.3, 1.4, 15.1, 15.2_

  - [x] 1.3 Create admin routes skeleton in `app/routes/admin.py`
    - Create `APIRouter(prefix="/admin")` with `Depends(require_superuser)` as router-level dependency
    - Register the router in `app/main.py` with `app.include_router(admin.router, tags=["admin-panel"])`
    - Add a minimal `GET /admin/` endpoint that returns a placeholder HTML response to verify wiring
    - _Requirements: 1.1, 1.2_

  - [ ]* 1.4 Write property test for superuser access control (Property 1)
    - **Property 1: Superuser access control on all admin routes**
    - Use `st.sampled_from(ADMIN_ROUTES)` to test that non-superuser gets 403 on every admin route
    - Create `tests/test_admin_properties.py` with Hypothesis, add `hypothesis` to dev dependencies in `pyproject.toml`
    - **Validates: Requirements 1.4, 15.1, 15.2**

- [x] 2. Checkpoint — Verify route migration and auth
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Admin base template and dark theme
  - [x] 3.1 Create `admin_base.html` with dark theme and sidebar navigation
    - Implement dark theme: Slate Night `#0F172A` background, Dark Steel `#1E293B` surfaces, indigo-600 primary, violet-600 AI accent, emerald-500 accent, amber-500 attention
    - Fixed left sidebar (240px) with icon + label links for all 12 navigation sections: Dashboard, Users, Clients, Avatars, Personas, Subreddits, Keywords, Tasks, System Health, AI Costs, Audit Logs, Billing
    - Active nav item highlighting using Jinja2 `{% block %}` or context variable
    - Load Inter font (UI text) and JetBrains Mono (technical data) from Google Fonts
    - Include HTMX and Tailwind CSS CDN
    - Main content area with header breadcrumbs
    - _Requirements: 1.1, 1.2, 1.5_

  - [x] 3.2 Add conditional "Admin" link to existing `base.html` top navigation
    - Update `_render` helper in `pages.py` to look up the current user's `is_superuser` flag and pass it to template context
    - Add an "Admin" link in `base.html` nav that is only visible when `is_superuser` is true
    - Ensure non-admin pages remain unchanged for non-superuser users
    - _Requirements: 1.6, 15.3, 15.4_

- [x] 4. Audit service and admin service layer
  - [x] 4.1 Create `app/services/audit.py` with `log_action` and `query_audit_logs`
    - `log_action(db, user_id, action, entity_type, entity_id, client_id, details)` → creates AuditLog entry
    - `query_audit_logs(db, page, per_page, user_id, client_id, action, date_from, date_to)` → returns paginated, filtered, descending-sorted audit entries
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 11.1, 11.2, 11.3, 11.4_

  - [ ]* 4.2 Write property test for audit log entries on mutations (Property 14)
    - **Property 14: Every admin mutation produces an audit log entry**
    - **Validates: Requirements 13.1, 13.2, 13.3, 13.4**

  - [ ]* 4.3 Write property test for audit log filtering (Property 15)
    - **Property 15: Audit log filtering returns only matching entries**
    - **Validates: Requirements 11.2**

  - [ ]* 4.4 Write property test for audit log sorting (Property 16)
    - **Property 16: Audit log sorting is descending by creation date**
    - **Validates: Requirements 11.3**

  - [x] 4.5 Create `app/services/admin.py` — user management functions
    - `list_users(db, page, per_page)` → paginated user list
    - `create_admin_user(db, email, password, full_name, is_superuser)` → creates User, checks duplicate email
    - `toggle_user_active(db, user_id, current_user_id)` → flips `is_active`, blocks self-deactivation
    - `toggle_user_superuser(db, user_id)` → flips `is_superuser`
    - All mutations call `audit.log_action()`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [ ]* 4.6 Write property test for user creation (Property 2)
    - **Property 2: User creation preserves data**
    - **Validates: Requirements 2.2**

  - [ ]* 4.7 Write property test for duplicate email rejection (Property 3)
    - **Property 3: Duplicate email rejection**
    - **Validates: Requirements 2.3**

  - [ ]* 4.8 Write property test for boolean toggle involution (Property 4)
    - **Property 4: Boolean field toggle is an involution**
    - **Validates: Requirements 2.4, 2.5**

  - [x] 4.9 Add client management functions to `app/services/admin.py`
    - `list_clients_paginated(db, page, per_page)` → paginated client list with subreddit/avatar counts
    - `create_client(db, **fields)` → creates Client record
    - `update_client(db, client_id, **fields)` → partial update, preserves unmodified fields
    - `deactivate_client(db, client_id)` → sets `is_active=False`
    - All mutations call `audit.log_action()`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [ ]* 4.10 Write property test for client creation (Property 5)
    - **Property 5: Client creation preserves all provided fields**
    - **Validates: Requirements 3.2**

  - [ ]* 4.11 Write property test for client partial update (Property 6)
    - **Property 6: Client partial update preserves unmodified fields**
    - **Validates: Requirements 3.4**

  - [x] 4.12 Add keyword management functions to `app/services/admin.py`
    - `get_client_keywords(db, client_id)` → flat list from JSONB
    - `add_keyword(db, client_id, name, priority)` → appends to JSONB
    - `remove_keyword(db, client_id, index)` → removes from JSONB
    - `update_keyword_priority(db, client_id, index, priority)` → moves keyword between priority lists
    - `validate_keyword(name, priority)` → validates non-empty name and valid priority
    - All mutations call `audit.log_action()`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ]* 4.13 Write property tests for keyword JSONB operations (Properties 7, 8, 9, 10)
    - **Property 7: Keyword addition to JSONB** — **Validates: Requirements 4.4, 6.2**
    - **Property 8: Keyword removal from JSONB** — **Validates: Requirements 6.3**
    - **Property 9: Keyword priority update** — **Validates: Requirements 6.4**
    - **Property 10: Keyword validation rejects invalid input** — **Validates: Requirements 6.5**

  - [x] 4.14 Add subreddit management functions to `app/services/admin.py`
    - `add_subreddit(db, client_id, name, type)` → creates or reactivates ClientSubreddit
    - `remove_subreddit(db, subreddit_id)` → soft-delete (is_active=False)
    - `validate_subreddit_name(name)` → regex `^[a-zA-Z0-9_]{3,21}$`
    - All mutations call `audit.log_action()`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ]* 4.15 Write property tests for subreddit operations (Properties 11, 12)
    - **Property 11: Subreddit name validation matches Reddit pattern** — **Validates: Requirements 7.5**
    - **Property 12: Subreddit reactivation instead of duplicate creation** — **Validates: Requirements 7.3**

  - [x] 4.16 Add persona management functions to `app/services/admin.py`
    - `list_personas(db, client_id=None)` → list with optional client filter
    - `create_persona(db, client_id, name, voice_profile)` → creates Persona
    - `update_persona(db, persona_id, **fields)` → partial update
    - `deactivate_persona(db, persona_id)` → sets `is_active=False`
    - All mutations call `audit.log_action()`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 4.17 Add avatar assignment function to `app/services/admin.py`
    - `assign_avatars_to_client(db, client_id, avatar_ids)` → adds client_id to each avatar's `client_ids` array (idempotent, no duplicates)
    - `unassign_avatar_from_client(db, client_id, avatar_id)` → removes client_id from avatar's `client_ids` array
    - _Requirements: 4.5_

  - [ ]* 4.18 Write property test for avatar assignment (Property 13)
    - **Property 13: Avatar assignment adds client ID to array (idempotent)**
    - **Validates: Requirements 4.5**

  - [x] 4.19 Add system health, AI costs, and task monitoring functions to `app/services/admin.py`
    - `check_system_health(db)` → checks PostgreSQL, Redis, Celery workers, Reddit API, LLM API
    - `get_db_statistics(db)` → counts of clients, avatars, threads, drafts, pending reviews
    - `get_ai_cost_summary(db)` → total cost, calls, tokens
    - `get_ai_costs_by_client(db)`, `get_ai_costs_by_operation(db)`, `get_ai_costs_by_model(db)` → breakdowns
    - `get_recent_tasks(celery_app)` → list of recent Celery tasks
    - `trigger_pipeline(celery_app, pipeline_type, entity_id)` → dispatches Celery task
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

- [x] 5. Checkpoint — Verify service layer
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Admin routes and templates — core pages
  - [x] 6.1 Implement admin dashboard route and template
    - `GET /admin/` → renders `admin_dashboard.html` with system stats cards (clients, avatars, pending reviews, AI cost, active tasks)
    - Create `admin_dashboard.html` extending `admin_base.html`
    - _Requirements: 1.1_

  - [x] 6.2 Implement user management routes and template
    - `GET /admin/users` → paginated user list
    - `POST /admin/users` → create user form submission
    - `POST /admin/users/{id}/toggle-active` → HTMX toggle
    - `POST /admin/users/{id}/toggle-superuser` → HTMX toggle
    - `POST /admin/users/{id}/delete` → soft-delete
    - Create `admin_users.html` with table, create form, and HTMX partials (`admin_user_row.html`)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 6.3 Implement client management routes and templates
    - `GET /admin/clients` → paginated client list with counts
    - `GET /admin/clients/new` → create client form
    - `POST /admin/clients/new` → create client submission
    - `GET /admin/clients/{id}` → client detail page with all fields, avatars, subreddits, keywords, personas
    - `POST /admin/clients/{id}` → update client
    - `POST /admin/clients/{id}/deactivate` → deactivate client
    - Create `admin_clients.html`, `admin_client_new.html`, `admin_client_detail.html`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 6.4 Implement persona management routes and template
    - `GET /admin/personas` → persona list grouped by client, with client filter
    - `POST /admin/personas` → create persona
    - `POST /admin/personas/{id}` → update persona
    - `POST /admin/personas/{id}/deactivate` → deactivate persona
    - Create `admin_personas.html`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 6.5 Implement keyword management routes and template
    - `GET /admin/keywords/{client_id}` → keyword list for client
    - `POST /admin/keywords/{client_id}/add` → add keyword (HTMX partial)
    - `POST /admin/keywords/{client_id}/{index}/remove` → remove keyword (HTMX partial)
    - `POST /admin/keywords/{client_id}/{index}/update` → update priority (HTMX partial)
    - Create `admin_keywords.html` and `partials/admin_keyword_row.html`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 6.6 Implement subreddit management routes and template
    - `GET /admin/subreddits/{client_id}` → subreddit list for client
    - `POST /admin/subreddits/{client_id}/add` → add subreddit (HTMX partial)
    - `POST /admin/subreddits/{client_id}/{id}/remove` → soft-delete (HTMX partial)
    - Create `admin_subreddits.html` and `partials/admin_subreddit_row.html`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 6.7 Implement Celery task monitoring routes and template
    - `GET /admin/tasks` → task list with HTMX polling (10s interval)
    - `POST /admin/tasks/trigger/{pipeline_type}/{entity_id}` → trigger pipeline
    - Create `admin_tasks.html` and `partials/admin_task_list.html`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 6.8 Implement system health dashboard route and template
    - `GET /admin/health` → service statuses, worker info, DB statistics
    - Create `admin_health.html`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 6.9 Implement AI cost tracking routes and template
    - `GET /admin/ai-costs` → summary cards, breakdowns by client/operation/model, budget warning
    - Create `admin_ai_costs.html`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [x] 6.10 Implement audit log viewer route and template
    - `GET /admin/audit-logs` → paginated, filterable, read-only audit log list
    - Create `admin_audit_logs.html`
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [x] 6.11 Implement billing placeholder route and template
    - `GET /admin/billing` → current AI cost, budget, AWS credits, "Coming Soon" notice, link to settings
    - Create `admin_billing.html`
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

- [x] 7. Checkpoint — Verify core admin pages
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Onboarding wizard
  - [x] 8.1 Implement wizard step routes in `app/routes/admin.py`
    - `GET /admin/clients/{id}/onboard/step/{n}` → renders wizard step n (1-7)
    - `POST /admin/clients/{id}/onboard/step/{n}` → processes step n, returns next step via HTMX `hx-swap="outerHTML"`
    - Each step loads current state from DB (back navigation preserves data)
    - _Requirements: 4.1, 4.7_

  - [x] 8.2 Create wizard step templates (steps 1-3)
    - `admin_onboard_step1.html` — Client Profile form (client_name, brand_name, company_profile, company_worldview, company_problem, competitive_landscape, brand_voice, icp_profiles)
    - `admin_onboard_step2.html` — Subreddit Configuration (add/remove subreddits with type selection, HTMX inline operations)
    - `admin_onboard_step3.html` — Keyword Setup (add keywords with priority, HTMX inline operations)
    - _Requirements: 4.2, 4.3, 4.4_

  - [x] 8.3 Create wizard step templates (steps 4-7)
    - `admin_onboard_step4.html` — Avatar Assignment (checkbox list of available avatars)
    - `admin_onboard_step5.html` — Persona Creation (create one or more personas with name and voice profile)
    - `admin_onboard_step6.html` — Pipeline Configuration (review summary, toggle pipeline settings)
    - `admin_onboard_step7.html` — Test Run (trigger pipeline, display task status with HTMX polling)
    - _Requirements: 4.5, 4.6, 4.8_

- [x] 9. NeuroYoga seed data
  - [x] 9.1 Add `seed_neuroyoga()` function to `app/seed.py`
    - Create NeuroYoga client with client_name "NeuroYoga", brand_name "ATMO", and all profile fields populated
    - Create ClientSubreddit records for meditation, breathing, yoga, TCM, stress management, wellness tech, biohacking communities
    - Create keywords JSONB with HIGH (breathing exercises, acupressure, stress relief), MEDIUM (TCM, meditation app, HRV biofeedback), LOW (wellness tech, mindfulness)
    - Create at least one Persona for NeuroYoga with wellness-appropriate voice profile
    - Make function idempotent — check for existing "NeuroYoga" client before creating
    - Call `seed_neuroyoga()` from the main `seed()` function
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_

  - [ ]* 9.2 Write property test for seed idempotency (Property 17)
    - **Property 17: Seed script idempotency**
    - Run `seed_neuroyoga()` N times (1-5), verify record counts are identical after each run
    - **Validates: Requirements 14.5**

- [x] 10. Checkpoint — Verify wizard and seed data
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Unit tests for admin routes and templates
  - [x] 11.1 Add test fixtures to `tests/conftest.py`
    - Add `superuser` fixture (creates user with `is_superuser=True`)
    - Add `regular_user` fixture (creates non-superuser user)
    - Add `admin_client` fixture (TestClient authenticated as superuser)
    - _Requirements: 15.1, 15.2_

  - [x] 11.2 Write unit tests for admin access control and navigation
    - `test_unauthenticated_redirect` — unauthenticated request to `/admin/` redirects to `/login`
    - `test_non_superuser_403` — non-superuser gets 403 on `/admin/`
    - `test_admin_dashboard_renders` — superuser gets 200 with stats cards
    - `test_admin_sidebar_links` — all 12 navigation links present in sidebar HTML
    - `test_admin_active_nav_highlight` — current page nav item has active CSS class
    - `test_non_admin_pages_accessible` — dashboard, review, avatars-page work for non-superusers
    - `test_admin_link_visibility` — admin link visible only to superusers in `base.html` nav
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.6, 15.3, 15.4_

  - [x] 11.3 Write unit tests for user management
    - `test_user_list_pagination` — user list shows correct page of results
    - `test_user_create_success` — create user with valid data succeeds
    - `test_user_create_duplicate_email` — duplicate email shows error message
    - `test_self_deactivation_blocked` — admin cannot deactivate own account
    - _Requirements: 2.1, 2.2, 2.3, 2.6_

  - [x] 11.4 Write unit tests for client management
    - `test_client_list_shows_counts` — client list shows subreddit and avatar counts
    - `test_client_create_success` — create client with all fields succeeds
    - `test_client_edit_prepopulates` — edit form shows current client data
    - `test_client_deactivate` — deactivate sets `is_active=False`
    - _Requirements: 3.1, 3.2, 3.3, 3.5_

  - [x] 11.5 Write unit tests for keyword, subreddit, and persona management
    - `test_keyword_add_remove` — add and remove keywords from JSONB
    - `test_keyword_invalid_name` — empty keyword name rejected
    - `test_keyword_invalid_priority` — invalid priority rejected
    - `test_subreddit_add_success` — valid subreddit name accepted
    - `test_subreddit_invalid_name` — invalid subreddit name rejected
    - `test_subreddit_reactivation` — re-adding deactivated subreddit reactivates
    - `test_persona_list_grouped` — personas grouped by client
    - `test_persona_filter_by_client` — filter returns only matching personas
    - _Requirements: 5.1, 5.5, 6.2, 6.3, 6.5, 7.2, 7.3, 7.5_

  - [x] 11.6 Write unit tests for onboarding wizard
    - `test_onboarding_wizard_step_order` — wizard steps render in correct order
    - `test_onboarding_back_navigation` — back button preserves data
    - `test_onboarding_test_run` — test run dispatches Celery task (mocked)
    - _Requirements: 4.1, 4.7, 4.8_

  - [x] 11.7 Write unit tests for health, AI costs, audit logs, billing, and seed
    - `test_health_page_renders` — health page shows all service statuses
    - `test_ai_costs_summary` — AI costs page shows correct totals
    - `test_ai_costs_by_operation` — breakdown by operation type correct
    - `test_ai_costs_budget_warning` — warning shown when cost > 80% budget
    - `test_audit_log_list` — audit log page shows entries
    - `test_audit_log_filter` — filtering returns correct entries
    - `test_audit_log_readonly` — no mutation endpoints for audit logs
    - `test_billing_placeholder` — billing page shows "Coming Soon"
    - `test_seed_neuroyoga` — seed creates NeuroYoga with all data
    - `test_seed_idempotent` — running seed twice doesn't duplicate
    - _Requirements: 9.1, 10.1, 10.3, 10.6, 11.1, 11.2, 11.4, 12.3, 14.1, 14.5_

- [x] 12. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests (17 properties) validate universal correctness properties using Hypothesis
- Unit tests validate specific examples and edge cases
- The existing 60 tests must continue to pass throughout implementation
- All admin templates use `admin_base.html` (dark theme); non-admin pages keep `base.html` (light theme) unchanged
