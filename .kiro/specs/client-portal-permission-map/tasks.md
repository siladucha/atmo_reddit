# Implementation Plan: Client Portal Permission Map

## Overview

Implement a centralized, runtime-editable permission matrix for client portal actions with three tiers (Self-Service, Approval Required, Admin-Only), a FastAPI permission guard dependency, and a generic ActionRequest approval workflow. Integrates with existing RBAC, rate limiting, audit logging, and notification systems.

## Tasks

- [x] 1. Database schema and core constants
  - [x] 1.1 Create the Default Permission Map module
    - Create `app/services/permission_map.py` with `PermissionTier` enum, `DEFAULT_PERMISSION_MAP` constant (19 self-service, 5 approval_required, 6 admin_only), and `get_effective_tier()` function
    - Ensure the constant is importable by both runtime code and migrations
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 1.3, 1.5_

  - [x] 1.2 Create the ActionRequest model
    - Create `app/models/action_request.py` with all fields: id, client_id, user_id, action_type, payload (JSONB), status, created_at, resolved_at, resolved_by, rejection_reason
    - Add indexes on (client_id, status) and (client_id, action_type, status)
    - Add relationships to Client, User (creator), User (resolver)
    - _Requirements: 4.1, 4.6_

  - [x] 1.3 Add permission_matrix JSONB column to Client model
    - Add `permission_matrix` mapped_column(JSONB, nullable=False, server_default="'{}'::jsonb") to `app/models/client.py`
    - _Requirements: 1.1_

  - [x] 1.4 Create Alembic migration perm01
    - Create `alembic/versions/perm01_permission_matrix_action_requests.py`
    - Add `permission_matrix` column to clients table
    - Create `action_requests` table with all columns and indexes
    - Backfill existing clients with DEFAULT_PERMISSION_MAP
    - Include downgrade function (drop table + column)
    - _Requirements: 1.1, 1.2, 4.1, 4.6_

  - [x]* 1.5 Write property tests for permission map and tier resolution
    - **Property 1: Permission matrix schema validity** — `get_effective_tier` always returns a valid tier string
    - **Property 3: Fallback resolution for missing/unknown keys** — missing keys fall back to default, unknown keys are ignored
    - **Validates: Requirements 1.3, 1.4, 1.5, 3.5**

- [x] 2. Permission Guard dependency
  - [x] 2.1 Implement the Permission Guard FastAPI dependency
    - Create `app/dependencies/permission_guard.py` with `require_permission(action_id)` factory function
    - Implement `PermissionRequiresApproval` exception class
    - Define `READ_ONLY_ACTIONS` frozenset for client_viewer logic
    - Implement pipeline: internal role bypass → viewer write denial → client matrix tier resolution → self-service allow / approval raise / admin-only deny
    - Implement `_resolve_client_id()` helper (path params or user.client_id)
    - Implement `_log_denial()` helper using existing `log_action` from audit
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 5.1, 5.2, 5.3, 8.2, 9.1_

  - [x]* 2.2 Write property tests for Permission Guard enforcement
    - **Property 4: Tier enforcement invariant** — guard produces correct outcome per tier for client_admin/client_manager
    - **Property 5: Viewer always denied writes** — client_viewer gets 403 regardless of tier
    - **Property 6: Client roles denied admin_only equally** — all client roles get 403 on admin_only, no escalation for client_admin
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 5.1, 5.2, 5.3, 5.4**

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. ActionRequest service and executors
  - [x] 4.1 Implement ActionRequest service
    - Create `app/services/action_request.py` with `create_action_request()`, `approve_action_request()`, `reject_action_request()`
    - Implement deduplication: check for existing pending with same client + action_type + matching payload
    - On create: audit log `action_request_created`
    - On approve: set status/resolved_at/resolved_by, call `_execute_action()`, audit log `action_request_resolved`, notify user (success)
    - On reject: set status/resolved_at/resolved_by/rejection_reason, audit log `action_request_resolved`, notify user (warning)
    - _Requirements: 4.2, 4.3, 4.4, 4.5, 7.5, 9.2, 9.3_

  - [x] 4.2 Implement Action Executors registry
    - Create `app/services/action_executors.py` with `ACTION_EXECUTORS` dict mapping action_type → handler function
    - Implement executors: `_execute_add_subreddit`, `_execute_remove_subreddit`, `_execute_request_avatar_freeze`, `_execute_request_avatar_unfreeze`, `_execute_change_brand_guardrails`
    - Each executor receives (db, client_id, user_id, payload) and performs the business logic
    - _Requirements: 4.3_

  - [x]* 4.3 Write property tests for ActionRequest lifecycle
    - **Property 7: ActionRequest deduplication** — duplicate pending request with same params returns None
    - **Property 8: Approval executes and transitions state** — approve sets approved status, records resolver, invokes executor
    - **Property 9: Rejection does not execute** — reject sets rejected status, records reason, does NOT invoke executor
    - **Validates: Requirements 4.3, 4.4, 4.5**

- [x] 5. Template context helper and portal UI integration
  - [x] 5.1 Implement permission context helper
    - Create `app/services/permission_context.py` with `get_permission_context(db, client_id, user_role)` returning `hidden_actions`, `approval_actions`, `pending_requests_count`
    - Classify all actions in DEFAULT_PERMISSION_MAP into hidden (admin_only) and approval (approval_required) sets
    - For client_viewer: hide all non-read actions
    - Count pending ActionRequests for the client
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 5.2 Inject permission context into portal routes
    - Modify `app/routes/portal.py` to call `get_permission_context()` and pass to all template contexts
    - Add `hidden_actions`, `approval_actions`, `pending_requests_count` to template rendering
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 5.3 Create "My Requests" portal page
    - Create `app/routes/portal_requests.py` with `GET /clients/{client_id}/requests`
    - Query ActionRequests for current client with status, timestamps, rejection_reason
    - Create `app/templates/client/requests.html` with table/list of requests, status badges, timestamps
    - Add sidebar navigation link with pending count badge
    - _Requirements: 7.3, 7.4_

- [x] 6. Replace existing role checks with Permission Guard
  - [x] 6.1 Integrate require_permission into portal_actions.py
    - Replace `_require_trigger_role` with `require_permission(action_id)` in `app/routes/portal_actions.py`
    - For approval-tier actions: catch `PermissionRequiresApproval`, call `create_action_request()`, return "Request submitted" HTMX response
    - For self-service tier: proceed with existing business logic
    - Map each existing route to its action_id: trigger_pipeline, trigger_epg_rebuild, trigger_strategy, regenerate_draft, add_keyword, remove_keyword, add_subreddit, remove_subreddit
    - _Requirements: 3.1, 3.2, 3.6, 8.1, 8.2_

  - [x] 6.2 Add permission-aware UI conditionals to portal templates
    - Wrap action buttons/forms with `{% if action_id not in hidden_actions %}` conditionals
    - Add "Requires Approval" badge for actions in `approval_actions` set
    - Update `client_base.html` to show pending requests count badge in sidebar
    - _Requirements: 7.1, 7.2, 7.3_

  - [x]* 6.3 Write property test for rate limit ordering
    - **Property 11: Permission guard executes before rate limit** — denied actions do not increment ClientActionLog
    - **Validates: Requirements 8.1, 8.2**

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Admin UI for permission management
  - [x] 8.1 Implement admin permissions page routes
    - Add `GET /admin/clients/{client_id}/permissions` to `app/routes/admin.py` — builds effective matrix with source indicators (override vs default)
    - Add `POST /admin/clients/{client_id}/permissions` — saves changed tiers to permission_matrix JSONB, uses `flag_modified(client, "permission_matrix")`, audit logs with old/new diff
    - Add `POST /admin/clients/{client_id}/permissions/reset/{action_id}` — removes single override
    - Add `POST /admin/clients/{client_id}/permissions/reset-all` — replaces matrix with DEFAULT_PERMISSION_MAP
    - Restrict to owner/partner with `require_platform_admin`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 9.4_

  - [x] 8.2 Create admin permissions template
    - Create `app/templates/admin_client_permissions.html` — dark theme, table of actions with tier selector (dropdown per row), source indicator (override badge), reset per-action button, reset-all button
    - Use HTMX for inline save (no full page reload)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 8.3 Implement admin ActionRequest management
    - Add `GET /admin/action-requests` route — list pending/resolved requests with filters (client, status, action_type)
    - Add `POST /admin/action-requests/{id}/approve` and `POST /admin/action-requests/{id}/reject` routes
    - Create `app/templates/admin_action_requests.html` — list page with approve/reject buttons, rejection reason modal
    - Add sidebar link in admin_base.html under Operations section
    - _Requirements: 4.3, 4.4_

  - [x]* 8.4 Write property test for audit trail completeness
    - **Property 12: Audit trail completeness** — every permission event (denial, creation, resolution, matrix update) produces a correct AuditLog entry
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4**

- [x] 9. Notification and wiring
  - [x] 9.1 Wire ActionRequest resolution notifications
    - Ensure `approve_action_request` and `reject_action_request` call `notify_client()` with correct user_id, type, title, body, and link to `/clients/{client_id}/requests`
    - _Requirements: 7.5_

  - [x] 9.2 Add admin sidebar link for client permissions
    - Add "Permissions" link under client detail in `admin_base.html` sidebar
    - Link to `/admin/clients/{client_id}/permissions`
    - _Requirements: 6.1_

  - [x]* 9.3 Write property test for notification delivery
    - **Property 10: Resolution notification delivery** — every resolved ActionRequest produces a Notification for the requesting user
    - **Validates: Requirements 7.5**

- [x] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The existing `SubredditRequest` model remains for backward compatibility; new subreddit add/remove flows route through ActionRequest
- Internal roles (owner, partner) bypass the permission matrix entirely — they already have full access via existing RBAC
- The `flag_modified` call on `permission_matrix` is critical for SQLAlchemy JSONB change detection

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["1.4", "1.5"] },
    { "id": 2, "tasks": ["2.1", "4.2"] },
    { "id": 3, "tasks": ["2.2", "4.1", "5.1"] },
    { "id": 4, "tasks": ["4.3", "5.2", "5.3"] },
    { "id": 5, "tasks": ["6.1", "6.2", "6.3"] },
    { "id": 6, "tasks": ["8.1", "8.3", "9.1", "9.2"] },
    { "id": 7, "tasks": ["8.2", "8.4", "9.3"] }
  ]
}
```
