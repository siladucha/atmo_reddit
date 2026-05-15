# Implementation Plan: RBAC & Client Data Isolation

## Overview

Implement full Role-Based Access Control (RBAC) and client data isolation across the platform. This includes new database models (UserClientAssignment, AvatarRental), permission guard dependencies, automatic query scoping, LLM context isolation hardening, and a comprehensive permission matrix. The implementation follows a phased approach: schema first, then guards, then scoping, then route migration.

## Tasks

- [x] 1. Database models and migrations
  - [x] 1.1 Create UserClientAssignment SQLAlchemy model
    - Create `app/models/user_client_assignment.py`
    - Fields: id (UUID PK), user_id (FK users.id, CASCADE), client_id (FK clients.id, CASCADE), role (String(20)), is_active (Boolean, default True), created_at (DateTime)
    - UniqueConstraint on (user_id, client_id)
    - Indexes on user_id and client_id
    - Register model in `app/models/__init__.py`
    - _Requirements: 1.1, 1.6_

  - [x] 1.2 Create AvatarRental SQLAlchemy model
    - Create `app/models/avatar_rental.py`
    - Fields: id (UUID PK), avatar_id (FK avatars.id, CASCADE), client_id (FK clients.id, CASCADE), is_active (Boolean, default True), rented_at (DateTime), expires_at (DateTime nullable), price (Numeric(10,2) nullable)
    - UniqueConstraint on (avatar_id, client_id)
    - Indexes on client_id, avatar_id, and partial index for active rentals
    - Register model in `app/models/__init__.py`
    - _Requirements: 10.2_

  - [x] 1.3 Extend Client model with RBAC columns
    - Add to `app/models/client.py`: `max_avatars` (Integer, default 3), `plan_type` (String(20), default "starter"), `draft_approval_enabled` (Boolean, default False)
    - _Requirements: 10.3_

  - [x] 1.4 Extend Avatar model with farm columns
    - Add to `app/models/avatar.py`: `is_farm_avatar` (Boolean, default False), `rent_price` (Numeric(10,2), nullable)
    - _Requirements: 10.4_

  - [x] 1.5 Add `client_admin` to UserRole enum
    - Update `app/models/user_role.py` to include `client_admin = "client_admin"`
    - Add `client_admin` to relevant permission properties (`can_review`, `can_manage_avatars` for own company)
    - Add new properties: `can_manage_team` (client_admin only within own company), `is_client_scoped` (client_admin, client_manager, client_viewer, b2c_user)
    - _Requirements: 10.10_

  - [x] 1.6 Add index on users.role
    - Add `Index("ix_users_role", User.role)` to User model
    - _Requirements: 10.5_

  - [x] 1.7 Create Alembic migration for all schema changes
    - Generate migration with `alembic revision --autogenerate`
    - Include: user_client_assignments table, avatar_rentals table, client columns, avatar columns, users.role index
    - Verify migration runs forward and backward cleanly
    - Preserve all existing data (no destructive changes)
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.9_

  - [x] 1.8 Create seed data migration for existing users
    - Create a data migration that seeds UserClientAssignment records for existing users with non-null client_id and role in (client_manager, client_viewer)
    - Skip users with null client_id without error
    - Set is_active=True and copy role from user record
    - _Requirements: 10.7, 10.8_

- [x] 2. Checkpoint — Verify migrations run cleanly
  - Run `alembic upgrade head` and `alembic downgrade -1` to verify reversibility
  - Verify existing data is preserved

- [x] 3. Permission guards
  - [x] 3.1 Create `app/dependencies/permissions.py` with base `get_current_user` dependency
    - Load user from JWT (reuse logic from current `require_superuser`)
    - Return User object or raise 303 redirect to /login
    - Check `is_active` — redirect to /login if False
    - Support legacy `is_superuser` flag mapping to `owner` role
    - _Requirements: 2.6, 2.7_

  - [x] 3.2 Implement `require_authenticated` guard
    - Accept any active, authenticated user regardless of role
    - _Requirements: 2.8_

  - [x] 3.3 Implement `require_owner` guard
    - Accept only `owner` role
    - Raise 403 "Access Denied" for all other roles
    - _Requirements: 2.8, 6.1, 6.2_

  - [x] 3.4 Implement `require_platform_admin` guard
    - Accept `owner` or `partner` roles
    - Raise 403 "Access Denied" for all other roles
    - Legacy: also accept `is_superuser=True` for backward compatibility
    - _Requirements: 2.8, 6.6, 6.7_

  - [x] 3.5 Implement `require_client_admin` guard
    - Accept only `client_admin` role
    - Raise 403 "Access Denied" for all other roles
    - _Requirements: 2.8, 7.2_

  - [x] 3.6 Implement `require_client_manager_or_above` guard
    - Accept `client_admin` or `client_manager` roles
    - Raise 403 "Access Denied" for all other roles
    - _Requirements: 2.8, 7.1_

  - [x] 3.7 Implement `require_client_access(client_id)` factory guard
    - Accept owner/partner for any client_id
    - Accept client_admin/client_manager/client_viewer/b2c_user only if client_id matches user.client_id
    - Raise 403 "Access Denied" on mismatch
    - No additional DB queries (uses user.client_id from loaded user)
    - _Requirements: 2.5, 2.8, 7.11, 7.12_

  - [x] 3.8 Update `require_superuser` to delegate to `require_platform_admin`
    - Modify `app/dependencies/admin.py` to call `require_platform_admin` internally
    - Maintain backward compatibility — all existing routes continue to work
    - _Requirements: 2.9_

  - [x] 3.9 Write unit tests for all permission guards
    - Test each guard with all 6 roles (owner, partner, client_admin, client_manager, client_viewer, b2c_user)
    - Test inactive user → 303 redirect
    - Test missing token → 303 redirect
    - Test client_id mismatch → 403
    - Test owner bypasses all restrictions
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

- [x] 4. Checkpoint — Verify permission guards work
  - Run all permission guard tests
  - Verify existing admin routes still work with `require_superuser`

- [x] 5. Query scoping layer
  - [x] 5.1 Create `app/services/query_scope.py` with QueryScope class
    - Implement `__init__(user, system)` constructor
    - Implement `get_authorized_client_ids()` — returns None for owner/partner/system, list with single client_id for client-scoped users
    - Implement `assert_write_access(client_id)` — raises SecurityError if user cannot write to client_id
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 5.2 Implement `scope_query(query, model)` method
    - For owner/partner/system: return query unchanged
    - For client-scoped users: apply client_id filter based on model type
    - Handle Avatar special case (client_ids ARRAY overlap + avatar_rentals join)
    - Handle RedditThread special case (via ThreadScore.client_id)
    - Handle StrategyDocument special case (via Avatar.client_ids)
    - For missing user context: raise RuntimeError (dev) or return empty + log WARNING (prod)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.10_

  - [x] 5.3 Implement `system_context()` function
    - Create a QueryScope with system=True
    - Log the caller (using inspect.stack or explicit caller parameter)
    - For use in Celery workers and background tasks
    - _Requirements: 4.8_

  - [x] 5.4 Implement `get_query_scope(user)` convenience function
    - Create a QueryScope from an authenticated user
    - Shorthand for `QueryScope(user=user)`
    - _Requirements: 4.1_

  - [x] 5.5 Write property-based tests for query scoping
    - **Property 2: Client-scoped users only see their own data**
    - **Property 3: Owner/partner see all data**
    - **Property 4: System context sees all data**
    - **Property 5: Write operations to wrong client_id are rejected**
    - Test with random users, random records, random client_ids
    - Test file: `tests/test_query_scoping_props.py`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.8, 4.9_

  - [x] 5.6 Write unit tests for avatar scoping (owned + rented)
    - Test: owned avatar visible to client
    - Test: rented avatar (active, not expired) visible to client
    - Test: rented avatar (expired) NOT visible to client
    - Test: rented avatar (is_active=false) NOT visible to client
    - Test: avatar not owned and not rented NOT visible to client
    - Test file: `tests/test_avatar_scoping.py`
    - _Requirements: 4.10, 7.5, 7.9_

- [x] 6. Checkpoint — Verify query scoping works
  - Run all query scoping tests
  - Verify no regressions in existing functionality

- [x] 7. LLM context isolation hardening
  - [x] 7.1 Create `_avatar_accessible_by_client` helper function
    - Check ownership via `client_ids` ARRAY
    - Check rental via `avatar_rentals` table (active + not expired)
    - Return boolean
    - Place in `app/services/generation.py` or a shared `app/services/isolation.py`
    - _Requirements: 5.7_

  - [x] 7.2 Strengthen `generate_comment` context isolation
    - Add validation: client_id must not be null (raise ValueError)
    - Replace direct `client_ids` assertion with `_avatar_accessible_by_client` (supports rentals)
    - Add final assertion: verify every context item (strategy, learning examples, patterns) belongs to target client_id
    - On assertion failure: abort, log ERROR with client_id + offending record ID
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 7.3 Strengthen `select_persona` context isolation
    - Replace direct `client_ids` assertion with `_avatar_accessible_by_client` (supports rentals)
    - Log WARNING if any candidate avatar fails the check (exclude from candidates, don't abort)
    - _Requirements: 5.1, 5.6_

  - [x] 7.4 Scope learning service queries to client_id
    - Verify `select_few_shot_examples` filters by client_id (already does — confirm)
    - Verify `get_correction_patterns` filters by client_id (already does — confirm)
    - Add explicit assertion after loading: all returned records have matching client_id
    - _Requirements: 5.3, 5.4_

  - [x] 7.5 Scope strategy loading to client's avatars
    - Verify `get_approved_strategy` only loads strategies for avatars accessible by the client
    - Add client_id parameter to strategy loading if not already present
    - _Requirements: 5.2, 5.7_

  - [x] 7.6 Write property-based tests for LLM context isolation
    - **Property 6: Every item in assembled context belongs to target client_id**
    - Create multi-client test data, invoke context assembly for one client, assert no cross-contamination
    - Test file: `tests/test_llm_isolation_props.py`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 9.6_

- [x] 8. Checkpoint — Verify LLM isolation
  - Run all LLM isolation tests
  - Verify generation pipeline still works end-to-end

- [x] 9. B2B client access control
  - [x] 9.1 Implement max_avatars enforcement
    - In avatar creation endpoint: check `client.max_avatars` vs current avatar count
    - Return error "Maximum avatars reached for your plan" if limit exceeded
    - Owner/partner can override (no limit check for platform admins)
    - _Requirements: 7.6_

  - [x] 9.2 Implement client_admin team management scope
    - client_admin can create/edit/deactivate client_manager and client_viewer users within own company
    - client_admin CANNOT create another client_admin (only owner/partner can)
    - client_manager CANNOT manage users at all
    - Enforce via permission check in user management endpoints
    - _Requirements: 7.2, 7.3, 7.4_

  - [x] 9.3 Implement client deactivation cascade
    - When client.is_active set to False: deny all subsequent access by client's users
    - Check client.is_active in `get_current_user` dependency (after loading user, load client if client-scoped)
    - Return 403 "Access Denied" if client is inactive
    - _Requirements: 7.13, 1.8_

  - [x] 9.4 Write tests for B2B access control
    - Test max_avatars enforcement
    - Test client_admin team management scope
    - Test client deactivation cascade
    - Test draft approval scoped to own client
    - Test file: `tests/test_b2b_access_control.py`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.6, 7.11, 7.13_

- [x] 10. B2C and client_viewer access control
  - [x] 10.1 Implement B2C single avatar limit
    - In avatar creation: if user.role == b2c_user, check if they already have an avatar
    - Return 403 "B2C users can have only one avatar" if limit exceeded
    - _Requirements: 8.9_

  - [x] 10.2 Implement client_viewer conditional draft approval
    - Check `client.draft_approval_enabled` flag
    - If True: allow client_viewer to approve/reject/edit drafts (own client only)
    - If False: client_viewer gets read-only access to draft list
    - _Requirements: 8.5, 8.6_

  - [x] 10.3 Implement B2C to B2B upgrade path
    - Create client record for the user
    - Convert personal avatar to first company avatar (add client_id to avatar.client_ids)
    - Set user.role to client_admin, user.client_id to new client.id
    - Allow creating up to (max_avatars - 1) additional avatars
    - _Requirements: 8.10_

  - [x] 10.4 Write tests for B2C and viewer access control
    - Test B2C single avatar limit
    - Test client_viewer read-only access
    - Test client_viewer conditional draft approval (enabled vs disabled)
    - Test B2C upgrade to B2B
    - Test file: `tests/test_b2c_viewer_access.py`
    - _Requirements: 8.1, 8.2, 8.3, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10_

- [x] 11. Checkpoint — Verify all access control
  - Run all access control tests
  - Verify no regressions

- [x] 12. Cross-client isolation tests
  - [x] 12.1 Write cross-client isolation tests for API endpoints
    - Create Client_A and Client_B with users
    - Test: client_manager of A cannot access B's CommentDrafts
    - Test: client_manager of A cannot access B's RedditThreads
    - Test: client_manager of A cannot access B's Avatars
    - Test: client_manager of A cannot access B's ActivityEvents
    - Test: client_admin of A cannot access B's data
    - Test: client_viewer of A cannot access B's data
    - Test: owner CAN access both A and B data
    - Test file: `tests/test_cross_client_isolation.py`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.7, 9.8_

  - [x] 12.2 Write LLM context isolation integration test
    - Create two clients with avatars, strategies, edit records, correction patterns
    - Invoke context assembly for Client_A
    - Assert: no Client_B data in assembled prompt
    - Test file: `tests/test_cross_client_isolation.py`
    - _Requirements: 9.6_

  - [x] 12.3 Write avatar rental isolation tests
    - Test: B2B client can access owned + rented farm avatars
    - Test: B2B client cannot access another client's rented avatars
    - Test: expired rental hides avatar
    - Test file: `tests/test_cross_client_isolation.py`
    - _Requirements: 9.10_

  - [x] 12.4 Write B2C avatar limit test
    - Test: b2c_user cannot create more than one avatar
    - Test file: `tests/test_cross_client_isolation.py`
    - _Requirements: 9.11_

  - [x] 12.5 Write runtime assertion failure test
    - Test: if avatar doesn't belong to client, operation aborts with error
    - Test: no cross-client data returned or processed
    - Test file: `tests/test_cross_client_isolation.py`
    - _Requirements: 9.9_

- [x] 13. Checkpoint — Verify all isolation tests pass
  - Run full test suite
  - Verify no regressions in existing functionality

- [x] 14. Admin route migration
  - [x] 14.1 Split admin routes by permission level
    - System settings / kill switches: change from `require_superuser` to `require_owner`
    - User management: keep `require_platform_admin`
    - Client CRUD: keep `require_platform_admin`
    - All other admin routes: keep `require_platform_admin` (no change)
    - _Requirements: 2.2, 2.3, 3.2, 6.2, 6.9_

  - [x] 14.2 Add client_id validation to admin endpoints that accept client_id parameter
    - For partner users: allow any client_id
    - For owner users: allow any client_id
    - Add `require_client_access` guard where client_id is in URL path
    - _Requirements: 2.5, 3.3_

  - [x] 14.3 Update auth middleware for role-based redirects
    - After JWT validation, attach full user role info to request.state
    - Add `request.state.user_role` for use by templates (nav rendering)
    - _Requirements: 3.4_

- [x] 15. Permission matrix documentation
  - [x] 15.1 Create `docs/permission_matrix.md`
    - List all 6 roles in columns
    - List all resource categories in rows
    - Mark each combination as "allowed", "denied", or "scoped (own company)"
    - Cover: client data, avatars (owned + rented), subreddits, threads, drafts, activity events, system settings, user management, AI cost analytics, audit logs, kill switches, pipeline triggers, avatar farm/rentals
    - Include revision date and change summary
    - State deny-by-default principle
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7_

- [x] 16. Final checkpoint — Full test suite
  - Run complete test suite
  - Verify all permission guards, query scoping, LLM isolation, and cross-client tests pass
  - Verify existing admin panel functionality is preserved
  - Verify migration is reversible

## Notes

- The implementation is phased to ensure zero downtime and backward compatibility
- `require_superuser` continues to work throughout (delegates to `require_platform_admin`)
- Client-facing routes (`/hub/*`) and B2C routes (`/my/*`) are defined in the design but NOT implemented in this spec — they will be a separate feature spec after RBAC infrastructure is in place
- The `qa` role (Jenny) is preserved as-is — it maps to cross-client reviewer access, which is handled by the existing `can_view_all_clients` property
- All property-based tests use Hypothesis (already configured in project)
- Background tasks (Celery workers) must use `system_context()` — this is enforced by the fail-closed behavior of the query scoping layer

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "1.4", "1.5", "1.6"] },
    { "id": 1, "tasks": ["1.7", "1.8"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "3.4", "3.5", "3.6", "3.7"] },
    { "id": 4, "tasks": ["3.8", "3.9"] },
    { "id": 5, "tasks": ["5.1"] },
    { "id": 6, "tasks": ["5.2", "5.3", "5.4"] },
    { "id": 7, "tasks": ["5.5", "5.6"] },
    { "id": 8, "tasks": ["7.1"] },
    { "id": 9, "tasks": ["7.2", "7.3", "7.4", "7.5"] },
    { "id": 10, "tasks": ["7.6"] },
    { "id": 11, "tasks": ["9.1", "9.2", "9.3", "10.1", "10.2", "10.3"] },
    { "id": 12, "tasks": ["9.4", "10.4"] },
    { "id": 13, "tasks": ["12.1", "12.2", "12.3", "12.4", "12.5"] },
    { "id": 14, "tasks": ["14.1", "14.2", "14.3"] },
    { "id": 15, "tasks": ["15.1"] }
  ]
}
```
