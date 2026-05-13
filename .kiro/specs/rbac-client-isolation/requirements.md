# Requirements Document

## Introduction

This feature implements full Role-Based Access Control (RBAC) and client data isolation for the Reddit Marketing SaaS platform. The system currently relies on a single `client_id` FK on the User model and a `require_superuser` dependency for admin routes, with no granular permission enforcement at the middleware or query level. Before exposing the platform to external client managers and client viewers, the system must enforce strict role-based access at every layer (API, UI, database queries, LLM context assembly) and guarantee that tenant-owned data is never leaked across client boundaries.

The platform supports two client models:
- **B2B clients** — companies with teams (admin, managers, viewers) managing multiple avatars
- **B2C users** — individuals with exactly one personal avatar

Avatars can be **owned** by a client (created for them) or **rented** from the platform's pre-warmed avatar farm.

## Glossary

- **RBAC_System**: The role-based access control subsystem responsible for evaluating user permissions against requested resources and actions.
- **Query_Scoping_Layer**: The database query middleware that automatically filters all tenant-owned entity queries by the requesting user's authorized client set.
- **Permission_Guard**: A FastAPI dependency that validates the requesting user's role and client assignments before allowing access to a route handler.
- **User_Client_Assignment**: The many-to-many relationship table linking users to the clients they are authorized to manage.
- **Platform_Owner**: A user with the `owner` role — full system access including system settings, kill switches, infrastructure controls. (Max)
- **Business_Partner**: A user with the `partner` role — access to all clients, user management, AI cost analytics, audit logs. Cannot access system settings or kill switches. (Tzvi, Jenny)
- **Client_Admin**: A user with the `client_admin` role — administrator of a B2B company. Can manage their company's team (create/edit/deactivate client_manager and client_viewer users), manage avatars, approve drafts, and configure client-level settings.
- **Client_Team_Manager**: A user with the `client_manager` role — manager within a B2B company. Can manage avatars, review/approve/reject drafts, view activity. Cannot manage users or delete avatars.
- **Client_Viewer**: A user with the `client_viewer` role — read-only access to their own company's dashboard, drafts, avatars, and reports.
- **B2C_User**: A user with the `b2c_user` role — individual with exactly one personal avatar. Simplified UI, single-avatar limit enforced.
- **Tenant_Owned_Entity**: Any database record that belongs to a specific client (identified by a `client_id` column or indirect relationship through avatar `client_ids`).
- **LLM_Context_Builder**: The service responsible for assembling prompts for AI generation, including strategy documents, learning examples, correction patterns, and thread context.
- **Permission_Matrix**: A documented mapping of roles to allowed actions and resource scopes.
- **Avatar_Farm**: Platform-owned pre-warmed avatars that can be rented to B2B clients for a fee.
- **Avatar_Rental**: A record linking a farm avatar to a B2B client for a rental period, granting the client access to use that avatar.

## Requirements

### Requirement 1: User-to-Client Many-to-Many Relationship

**User Story:** As a platform administrator, I want to assign users to clients, so that B2B company teams can access their company's data and platform partners can manage multiple clients.

#### Acceptance Criteria

1. THE RBAC_System SHALL provide a `User_Client_Assignment` table with columns `user_id` (FK to users), `client_id` (FK to clients), `role` (String), `is_active` (Boolean), and `assigned_at` (timestamp).
2. WHEN a user with `can_manage_users` permission assigns a client to a `partner` user, THE RBAC_System SHALL create a User_Client_Assignment record linking that user to the client.
3. WHEN a user with `can_manage_users` permission removes a client assignment from a `partner` user, THE RBAC_System SHALL delete the corresponding User_Client_Assignment record.
4. THE RBAC_System SHALL use `User.client_id` FK for `client_admin`, `client_manager`, and `client_viewer` accounts (single-company scoping).
5. WHEN a `client_admin` or `client_manager` user queries their authorized clients, THE RBAC_System SHALL return only the client record matching their own `client_id`.
6. THE RBAC_System SHALL enforce a unique constraint on the (`user_id`, `client_id`) pair in User_Client_Assignment to prevent duplicate assignments.
7. IF a user with `can_manage_users` permission attempts to create a User_Client_Assignment for a non-existent user or a non-existent client, THEN THE RBAC_System SHALL reject the request with an error message indicating the reason for rejection.
8. IF a client is deactivated (is_active=false), THEN THE RBAC_System SHALL preserve existing User_Client_Assignment records but exclude the deactivated client from the results returned when the user queries their authorized clients.
9. WHEN a `partner` user queries their authorized clients, THE RBAC_System SHALL return ALL active clients (partners have platform-wide access).

### Requirement 2: Role-Based Permission Guards for API Routes

**User Story:** As a platform operator, I want every API endpoint to enforce role-based access, so that unauthorized users receive a 403 response instead of accessing restricted resources.

#### Acceptance Criteria

1. THE Permission_Guard SHALL verify the requesting user's role against the endpoint's required permission level before executing any route handler.
2. WHEN a client-scoped user (`client_admin`, `client_manager`, `client_viewer`, or `b2c_user`) requests an admin-panel endpoint (any route under `/admin/*`), THE Permission_Guard SHALL return HTTP 403 with body containing "Access Denied".
3. WHEN a `partner` user requests a system-settings endpoint (kill switches, infrastructure config), THE Permission_Guard SHALL return HTTP 403 with body containing "Access Denied".
4. WHEN an `owner` user requests any endpoint, THE Permission_Guard SHALL allow access regardless of the endpoint's required permission level.
5. WHEN a `client_admin`, `client_manager`, or `client_viewer` requests a resource belonging to a client_id different from their own `client_id`, THE Permission_Guard SHALL return HTTP 403 with body containing "Access Denied".
6. IF the requesting user has no valid authentication token or the token is expired, THEN THE Permission_Guard SHALL return HTTP 303 redirect with Location header set to "/login".
7. IF the requesting user's `is_active` field is False, THEN THE Permission_Guard SHALL return HTTP 303 redirect with Location header set to "/login".
8. THE Permission_Guard SHALL provide reusable FastAPI dependencies:
   - `require_owner` — only `owner` role
   - `require_partner` — only `partner` role
   - `require_platform_admin` — `owner` or `partner`
   - `require_client_admin` — `client_admin` (within own company)
   - `require_client_manager_or_above` — `client_admin` or `client_manager` (within own company)
   - `require_client_access(client_id)` — verifies requesting user is assigned to the specified client or has platform-wide access
   - `require_authenticated` — any active, authenticated user
9. THE Permission_Guard SHALL NOT introduce additional database queries beyond loading the user record (role is stored on the user, client_id is on the user).

### Requirement 3: Role-Based Permission Guards for UI Pages

**User Story:** As a platform operator, I want every UI page to enforce role-based access, so that users who navigate directly to a forbidden URL are blocked rather than seeing restricted content.

#### Acceptance Criteria

1. WHEN a user with role `client_admin`, `client_manager`, `client_viewer`, or `b2c_user` navigates to an admin panel URL (any `/admin/*` route), THE Permission_Guard SHALL return HTTP 403.
2. WHEN a user with role `partner` navigates to a system settings or kill switch page, THE Permission_Guard SHALL return HTTP 403.
3. WHEN a user with role `client_admin`, `client_manager`, `client_viewer`, or `b2c_user` navigates to a client hub URL belonging to a different client than their assigned `client_id`, THE Permission_Guard SHALL return HTTP 403.
4. THE RBAC_System SHALL enforce permissions at the server-side route level using FastAPI dependencies, not rely on UI element hiding alone.
5. WHEN a user with role `owner` navigates to any page, THE Permission_Guard SHALL allow access.
6. IF an unauthenticated user navigates to any protected page, THEN THE Permission_Guard SHALL redirect to the login page.
7. THE Permission_Guard SHALL return HTTP 403 with a generic "Access Denied" page that does not reveal the existence or nature of the protected resource.
8. WHEN a user with role `partner` navigates to any client's hub or admin panel (except system settings), THE Permission_Guard SHALL allow access.

### Requirement 4: Automatic Query Scoping for Tenant-Owned Entities

**User Story:** As a security engineer, I want all database queries for tenant-owned data to be automatically scoped by the user's authorized client set, so that no code path can accidentally leak cross-client data.

#### Acceptance Criteria

1. THE Query_Scoping_Layer SHALL filter all read and write queries on Tenant_Owned_Entity tables by the requesting user's authorized client IDs.
2. WHEN a Platform_Owner or Business_Partner executes a query, THE Query_Scoping_Layer SHALL apply no client_id filter (full access).
3. WHEN a Client_Admin or Client_Team_Manager executes a query, THE Query_Scoping_Layer SHALL filter results to only their own `client_id`.
4. WHEN a Client_Viewer executes a query, THE Query_Scoping_Layer SHALL filter results to only their own `client_id`.
5. THE Query_Scoping_Layer SHALL scope the following entities: Client, Avatar (via `client_ids` JSONB array overlap), ClientSubreddit, ClientSubredditAssignment, CommentDraft, PostDraft, RedditThread, ThreadScore, ActivityEvent, EditRecord, CorrectionPattern, and StrategyDocument.
6. IF a query for a Tenant_Owned_Entity omits client scoping in development mode, THEN THE Query_Scoping_Layer SHALL raise a runtime error immediately.
7. IF a query for a Tenant_Owned_Entity omits client scoping in production mode, THEN THE Query_Scoping_Layer SHALL block the query from executing, return an empty result set, and log a security warning.
8. WHEN a background task or system process (Celery worker) executes a query without a user context, THE Query_Scoping_Layer SHALL require an explicit `system_context()` marker that bypasses user-based scoping and logs the caller in the audit trail.
9. IF a write operation (INSERT or UPDATE) targets a Tenant_Owned_Entity with a client_id not in the requesting user's authorized set, THEN THE Query_Scoping_Layer SHALL reject the operation and log a security warning.
10. THE Query_Scoping_Layer SHALL include avatar rentals: when a B2B client queries avatars, the layer SHALL return both (a) avatars owned by the client (via `Avatar.client_ids`) AND (b) avatars rented from the platform's farm (via `avatar_rentals` table where `client_id` matches and `is_active=true` and `expires_at > now`).

### Requirement 5: LLM Context Isolation

**User Story:** As a security engineer, I want the LLM context assembly to enforce client boundaries, so that no generated prompt ever contains strategy documents, learning examples, correction patterns, or activity data from another client.

#### Acceptance Criteria

1. THE LLM_Context_Builder SHALL require a non-null `client_id` parameter for every context assembly call, and IF the `client_id` is null or does not correspond to an existing client record, THEN THE LLM_Context_Builder SHALL raise a validation error and abort context assembly without invoking the LLM provider.
2. THE LLM_Context_Builder SHALL load StrategyDocument records only for avatars whose `client_ids` field contains the specified client_id.
3. THE LLM_Context_Builder SHALL load EditRecord and CorrectionPattern records only where the record's `client_id` matches the specified client_id and the associated avatar's `client_ids` field contains the specified client_id.
4. THE LLM_Context_Builder SHALL load few-shot examples only from CommentDraft records whose `client_id` matches the specified client_id.
5. IF the LLM_Context_Builder detects a context item with a client_id that does not match the target client_id, THEN THE LLM_Context_Builder SHALL exclude the item from the assembled prompt and log a warning at WARNING level or above that includes the mismatched client_id, the target client_id, and the record type.
6. THE LLM_Context_Builder SHALL include a runtime assertion verifying that every assembled context item belongs to the target client_id, and IF the assertion fails, THEN THE LLM_Context_Builder SHALL abort the prompt dispatch, raise an error, and log a security event at ERROR level that includes the target client_id and the offending record identifier.
7. THE LLM_Context_Builder SHALL, when processing requests for a B2B client, include StrategyDocument and CorrectionPattern from both (a) avatars owned by the client AND (b) avatars rented by the client (via active avatar_rentals records).

### Requirement 6: Platform Administrator Access Control

**User Story:** As a platform owner, I want platform administrators to have appropriate access levels, so that operations run smoothly while maintaining separation between system-level and business-level controls.

#### Acceptance Criteria

1. WHEN a user with `owner` role accesses any resource, THE RBAC_System SHALL allow the request without any restriction (full system access).
2. WHEN a user with `owner` role accesses system settings, kill switches, or infrastructure controls, THE RBAC_System SHALL allow the request.
3. WHEN a user with `partner` role accesses any client's data, THE RBAC_System SHALL return the requested data without filtering by client_id (platform-wide client access).
4. WHEN a user with `partner` role accesses user management, THE RBAC_System SHALL allow creating, deactivating, and role-assigning operations for any user.
5. WHEN a user with `partner` role accesses AI cost analytics or audit logs, THE RBAC_System SHALL return records across all clients without client-scoping filters.
6. THE RBAC_System SHALL map the `owner` UserRole value to full platform access (all resources including system settings, kill switches, and infrastructure controls).
7. THE RBAC_System SHALL map the `partner` UserRole value to administrative access for all clients, user management, AI cost analytics, and audit logs, but SHALL exclude access to system settings and kill switches.
8. IF a user with `owner` or `partner` role has `is_active` set to false, THEN THE RBAC_System SHALL deny all requests and redirect to the login page.
9. WHEN a user with `partner` role attempts to access system settings or kill switches, THE RBAC_System SHALL return HTTP 403 with body containing "Access Denied".

### Requirement 7: B2B Client Access Control

**User Story:** As a B2B client administrator or manager, I want to access only my company's avatars and data, so that I cannot see other clients' confidential information.

#### Acceptance Criteria

1. WHEN a `client_admin` or `client_manager` accesses the platform, THE RBAC_System SHALL scope all queries to their own `client_id`.
2. WHEN a `client_admin` accesses user management, THE RBAC_System SHALL allow creating, editing, and deactivating `client_manager` and `client_viewer` users within their own company ONLY.
3. WHEN a `client_admin` attempts to create a user with role `client_admin`, THE RBAC_System SHALL deny the request (only platform owner/partner can create client_admin users).
4. WHEN a `client_manager` accesses user management, THE RBAC_System SHALL deny access (only client_admin can manage users within the company).
5. WHEN a `client_admin` or `client_manager` accesses avatars, THE RBAC_System SHALL display both (a) avatars owned by their company AND (b) avatars rented from the platform's farm (active rentals only).
6. WHEN a `client_admin` creates a new avatar, THE RBAC_System SHALL check the company's `max_avatars` limit; IF the limit is reached, THEN return error "Maximum avatars reached for your plan".
7. WHEN a `client_manager` attempts to delete an avatar, THE RBAC_System SHALL deny access (only client_admin can delete avatars).
8. WHEN a `client_admin` or `client_manager` generates a comment or triggers pipeline actions, THE RBAC_System SHALL allow selecting any avatar from (owned + rented).
9. WHEN a client's rental of a farm avatar expires (`expires_at < now` or `is_active=false`), THE RBAC_System SHALL hide that avatar from the client's avatar list on the next request.
10. THE RBAC_System SHALL deny `client_admin` and `client_manager` access to: system settings, kill switches, platform-wide analytics, other clients' data, and admin panel pages.
11. WHEN a `client_admin` or `client_manager` approves or rejects a draft, THE RBAC_System SHALL verify the draft belongs to their own client before allowing the action; IF the draft belongs to a different client, THEN return HTTP 403.
12. IF a `client_admin` or `client_manager` constructs a direct URL or API request referencing a client_id that does not match their own, THEN THE RBAC_System SHALL deny the request and return HTTP 403.
13. WHEN a client is deactivated, THE RBAC_System SHALL deny all subsequent access attempts by that client's users on the next request without requiring re-authentication.

### Requirement 8: Client Viewer and B2C User Access Control

**User Story:** As a client viewer or B2C user, I want to see only my own data with appropriate restrictions, so that I have a focused view without exposure to other clients or system internals.

#### Acceptance Criteria

1. WHEN a `client_viewer` accesses the platform, THE RBAC_System SHALL scope all data queries to the user's own `client_id`, applying the Query_Scoping_Layer filter to every Tenant_Owned_Entity request.
2. THE RBAC_System SHALL allow `client_viewer` read-only access to: client dashboard, avatar list (own client only), draft list (own client only), activity feed (own client only), subreddit list (own client only), reports (own client only), and client settings (view only, no modification).
3. THE RBAC_System SHALL deny `client_viewer` access to: other clients' data, global logs, system settings, user management, platform-wide analytics, admin panel pages, kill switches, and pipeline triggers.
4. WHEN a `client_viewer` attempts to access a resource with a different client_id, THE RBAC_System SHALL return HTTP 403 with a response body indicating access denied.
5. WHERE draft approval is enabled for the client (via a boolean `draft_approval_enabled` flag on the Client record), THE RBAC_System SHALL allow `client_viewer` to approve, reject, or edit generated drafts belonging to their own client.
6. IF draft approval is not enabled for the client, THEN THE RBAC_System SHALL allow `client_viewer` read-only access to the draft list but SHALL deny approve, reject, and edit actions.
7. IF a `client_viewer` account has no `client_id` assigned (null value), THEN THE RBAC_System SHALL deny access to all client-scoped resources and return HTTP 403.
8. WHEN a `b2c_user` accesses the platform, THE RBAC_System SHALL scope all queries to their single personal avatar and its associated data only.
9. WHEN a `b2c_user` attempts to create a second avatar, THE RBAC_System SHALL return HTTP 403 with error "B2C users can have only one avatar".
10. WHEN a `b2c_user` upgrades to B2B (plan change), THE RBAC_System SHALL create a client record, convert the personal avatar to the first company avatar, and allow creating up to (`max_avatars` - 1) additional avatars.

### Requirement 9: Cross-Client Data Isolation Tests

**User Story:** As a quality engineer, I want automated tests proving that client data isolation is enforced, so that regressions are caught before deployment.

#### Acceptance Criteria

1. WHEN a user with role `client_manager` scoped to Client_A requests Client_B's CommentDraft records via API, THEN THE RBAC_System SHALL return an empty result set or HTTP 403 response containing zero records belonging to Client_B.
2. WHEN a user with role `client_manager` scoped to Client_A requests Client_B's RedditThread records via API, THEN THE RBAC_System SHALL return an empty result set or HTTP 403 response containing zero records belonging to Client_B.
3. WHEN a user with role `client_manager` scoped to Client_A requests Client_B's Avatar records via API, THEN THE RBAC_System SHALL return an empty result set or HTTP 403 response containing zero records belonging to Client_B.
4. WHEN a user with role `client_manager` scoped to Client_A requests Client_B's ActivityEvent records via API, THEN THE RBAC_System SHALL return an empty result set or HTTP 403 response containing zero records belonging to Client_B.
5. WHEN a user with role `client_admin` requests data for a client not matching their own `client_id` via API, THEN THE RBAC_System SHALL return an empty result set or HTTP 403 response containing zero records from the other client.
6. THE RBAC_System SHALL include tests that invoke the LLM context assembly (select_persona and generate_comment) for Client_A and assert that the assembled prompt contains no RedditThread content, Avatar voice profiles, or CorrectionPattern data belonging to any other client.
7. WHEN a user with role `owner` requests any client's CommentDraft, RedditThread, Avatar, or ActivityEvent records via API, THEN THE RBAC_System SHALL return the requested records regardless of client ownership.
8. THE RBAC_System SHALL include at least one isolation test per resource type (CommentDraft, RedditThread, Avatar, ActivityEvent) for the `client_viewer` role, verifying the same denial behavior as `client_manager` when accessing another client's data.
9. IF a context isolation assertion fails at runtime (avatar does not belong to the requesting client), THEN THE RBAC_System SHALL raise an error and abort the operation without returning or processing cross-client data.
10. THE RBAC_System SHALL include tests verifying that a B2B client can access both owned AND rented farm avatars (via active avatar_rentals records).
11. THE RBAC_System SHALL include tests verifying that a `b2c_user` cannot create more than one avatar.

### Requirement 10: Database Migration and Seed Data

**User Story:** As a developer, I want Alembic migrations that create the necessary tables and columns for RBAC and avatar rentals, so that the system can be deployed with access control active from the start.

#### Acceptance Criteria

1. THE RBAC_System SHALL provide an Alembic migration creating the `user_client_assignments` table with columns `id` (UUID PK), `user_id` (FK to `users.id`), `client_id` (FK to `clients.id`), `role` (String), `is_active` (Boolean), and `created_at` (DateTime), with a unique constraint on (`user_id`, `client_id`) and indexes on `user_id` and `client_id`.
2. THE RBAC_System SHALL provide an Alembic migration creating the `avatar_rentals` table with columns `id` (UUID PK), `avatar_id` (FK to `avatars.id`), `client_id` (FK to `clients.id`), `is_active` (Boolean), `rented_at` (DateTime), `expires_at` (DateTime nullable), and `price` (Numeric nullable), with a unique constraint on (`avatar_id`, `client_id`) and indexes on `client_id` and `avatar_id`.
3. THE RBAC_System SHALL provide an Alembic migration adding columns to the `clients` table: `max_avatars` (Integer, default 3), `plan_type` (String, default "starter"), and `draft_approval_enabled` (Boolean, default false).
4. THE RBAC_System SHALL provide an Alembic migration adding columns to the `avatars` table: `is_farm_avatar` (Boolean, default false) and `rent_price` (Numeric nullable).
5. THE RBAC_System SHALL provide an Alembic migration adding an index on `users.role` for efficient role-based queries.
6. WHEN the migration runs on an existing database, THE RBAC_System SHALL preserve all existing user records, their current `client_id` values, and their `role` column values without modification.
7. WHEN the migration seed step executes, THE RBAC_System SHALL create one `user_client_assignments` record for each existing user whose `role` is `client_manager` and whose `client_id` is not NULL, copying the `client_id` value into the assignment record with `is_active` set to true.
8. IF a user has `role` equal to `client_manager` but `client_id` is NULL, THEN THE RBAC_System SHALL skip that user during seed data creation without raising an error.
9. IF a migration fails, THEN THE RBAC_System SHALL support full rollback via `alembic downgrade` that drops the new tables and columns, restoring the schema to its pre-migration state.
10. THE RBAC_System SHALL update the `UserRole` enum to include `client_admin` as a new role value, with a migration that adds it to the allowed values.

### Requirement 11: Permission Matrix Documentation

**User Story:** As a developer or auditor, I want a clear permission matrix documenting which roles can access which resources and actions, so that access rules are transparent and auditable.

#### Acceptance Criteria

1. THE RBAC_System SHALL include a permission matrix document listing all roles (`owner`, `partner`, `client_admin`, `client_manager`, `client_viewer`, `b2c_user`) against all resource categories in a structured tabular format.
2. THE Permission_Matrix SHALL specify allowed actions (read, create, update, delete, approve, reject, trigger) per role per resource, marking each combination as "allowed", "denied", or "scoped" with the applicable scope noted.
3. THE Permission_Matrix SHALL document scope restrictions per role: "all clients" for `owner` and `partner`; "own company only" for `client_admin`, `client_manager`, and `client_viewer`; "own avatar only" for `b2c_user`.
4. THE Permission_Matrix SHALL cover: client data, avatars (owned + rented), subreddits, threads, drafts, activity events, system settings, user management, AI cost analytics, audit logs, kill switches, pipeline triggers, and avatar farm/rentals.
5. WHEN a new endpoint or resource is added, THE Permission_Matrix SHALL be updated in the same pull request that introduces the endpoint, before the change is merged.
6. THE Permission_Matrix SHALL include a revision date and a change summary entry for each update so that auditors can identify what changed and when.
7. IF a role-resource combination is not explicitly listed in the Permission_Matrix, THEN THE RBAC_System SHALL deny access to that combination by default (deny-by-default principle).
