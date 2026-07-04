# Requirements Document

## Introduction

Formalize a Client Portal Permission Map that classifies all portal actions into three permission tiers: Self-Service (instant execution), Approval Required (generic request workflow), and Admin-Only (restricted to internal staff). The goal is to move at least 70% of portal actions to Self-Service, eliminating repetitive manual approvals while preserving risk-based gating. The permission matrix is stored as a centralized JSONB field on the Client model, ships with a hard-coded default, and is runtime-editable from the admin UI for per-client overrides.

## Glossary

- **Portal**: The client-facing section of RAMP accessed at `/clients/{client_id}/*`, scoped by RBAC roles (client_admin, client_manager, client_viewer).
- **Permission_Matrix**: A JSONB structure on the Client model that maps action identifiers to permission tiers for that client.
- **Self_Service_Tier**: Permission tier where the action executes immediately without human approval from internal staff.
- **Approval_Tier**: Permission tier where the action creates a pending ActionRequest that requires internal staff approval before execution.
- **Admin_Only_Tier**: Permission tier where the action is invisible and inaccessible to all client-scoped users; only internal roles (owner, partner) can perform it.
- **ActionRequest**: A generic approval workflow model (extends SubredditRequest pattern) tracking pending → approved → rejected lifecycle for any Approval_Tier action.
- **Default_Permission_Map**: A hard-coded Python constant defining the default permission tier for every portal action, applied to all clients unless overridden.
- **Permission_Guard**: A FastAPI dependency that checks the Permission_Matrix before allowing a portal action to proceed.
- **Client_Role**: One of three client-scoped RBAC roles — client_admin, client_manager, client_viewer — each with different capabilities within the permission system.

## Requirements

### Requirement 1: Permission Matrix Data Model

**User Story:** As a platform operator, I want each client to have a centralized permission configuration, so that I can control which actions are self-service, approval-required, or admin-only per client.

#### Acceptance Criteria

1. THE Client model SHALL store a `permission_matrix` field as a JSONB column with a NOT NULL constraint and a default value equal to the Default_Permission_Map.
2. WHEN a new Client record is created, THE System SHALL populate the `permission_matrix` field with the Default_Permission_Map without requiring manual configuration.
3. THE Permission_Matrix SHALL map each action identifier string to exactly one of three tier values: `self_service`, `approval_required`, or `admin_only`.
4. WHEN the Permission_Matrix contains an action identifier not present in the Default_Permission_Map, THE System SHALL ignore the unrecognized entry during permission evaluation.
5. WHEN the Permission_Matrix is missing an action identifier that exists in the Default_Permission_Map, THE Permission_Guard SHALL fall back to the default tier defined in the Default_Permission_Map for that action.

### Requirement 2: Default Permission Map

**User Story:** As a platform operator, I want a single hard-coded default that classifies every portal action into the correct tier, so that all clients start with a safe and autonomous baseline.

#### Acceptance Criteria

1. THE Default_Permission_Map SHALL classify at least 70% of all portal action identifiers as Self_Service_Tier.
2. THE Default_Permission_Map SHALL classify the following actions as Self_Service_Tier: add keyword, remove keyword, trigger pipeline, trigger EPG rebuild, trigger strategy generation, regenerate draft, approve draft, reject draft, edit draft, submit voice feedback, view avatars, view avatar detail, view report, view activity log, view settings, view subreddits, view keywords, view EPG schedule, mark draft as posted.
3. THE Default_Permission_Map SHALL classify the following actions as Approval_Tier: add subreddit, remove subreddit, request avatar freeze, request avatar unfreeze, change brand guardrails.
4. THE Default_Permission_Map SHALL classify the following actions as Admin_Only_Tier: deactivate client account, change plan type, assign avatar to client, remove avatar from client, modify auto-approve policy, toggle autopilot mode.
5. THE Default_Permission_Map SHALL be defined as a Python constant in a dedicated module so that it is importable by both runtime code and migrations.

### Requirement 3: Permission Guard Enforcement

**User Story:** As a client user, I want the system to enforce permission tiers transparently, so that I can execute self-service actions instantly and understand when an action requires approval.

#### Acceptance Criteria

1. WHEN a client-scoped user triggers a portal action classified as Self_Service_Tier in the applicable Permission_Matrix, THE Permission_Guard SHALL allow the action to proceed without delay or approval workflow.
2. WHEN a client-scoped user triggers a portal action classified as Approval_Tier in the applicable Permission_Matrix, THE Permission_Guard SHALL block immediate execution and create an ActionRequest record with status `pending`.
3. WHEN a client-scoped user triggers a portal action classified as Admin_Only_Tier in the applicable Permission_Matrix, THE Permission_Guard SHALL return HTTP 403 and not expose the action in the portal UI.
4. WHEN a client_viewer triggers any portal action that modifies state, THE Permission_Guard SHALL return HTTP 403 regardless of the permission tier, because client_viewer is read-only.
5. THE Permission_Guard SHALL resolve the effective permission tier by reading the client's `permission_matrix` field first, falling back to the Default_Permission_Map for any missing action identifiers.
6. THE Permission_Guard SHALL be implemented as a FastAPI dependency that accepts the action identifier as a parameter and can be composed with existing RBAC guards (verify_client_access_from_path).

### Requirement 4: ActionRequest Approval Workflow

**User Story:** As a client manager, I want approval-tier actions to follow a clear pending → approved/rejected lifecycle, so that I know the status of my requests and receive feedback.

#### Acceptance Criteria

1. THE ActionRequest model SHALL store: id, client_id, user_id, action_type, payload (JSONB), status (pending/approved/rejected), created_at, resolved_at, resolved_by, rejection_reason.
2. WHEN an ActionRequest is created, THE System SHALL record the requesting user's id, the action_type identifier, and any action-specific parameters in the payload field.
3. WHEN an internal user (owner or partner) approves an ActionRequest, THE System SHALL set status to `approved`, record resolved_at and resolved_by, and execute the originally requested action.
4. WHEN an internal user (owner or partner) rejects an ActionRequest, THE System SHALL set status to `rejected`, record resolved_at, resolved_by, and rejection_reason, and not execute the action.
5. WHILE an ActionRequest with status `pending` exists for a given client and action_type with identical payload, THE System SHALL prevent creation of a duplicate ActionRequest for the same parameters.
6. THE ActionRequest model SHALL have an index on (client_id, status) for efficient querying of pending requests per client.

### Requirement 5: Role-Based Tier Interaction

**User Story:** As a platform operator, I want each client role to interact with permission tiers according to its capabilities, so that read-only users cannot trigger actions and managers cannot perform admin-only operations.

#### Acceptance Criteria

1. WHILE a user has the client_viewer role, THE Permission_Guard SHALL deny all write actions regardless of the permission tier, restricting the user to read-only portal views.
2. WHILE a user has the client_manager role, THE Permission_Guard SHALL allow Self_Service_Tier and Approval_Tier actions but deny Admin_Only_Tier actions.
3. WHILE a user has the client_admin role, THE Permission_Guard SHALL allow Self_Service_Tier and Approval_Tier actions but deny Admin_Only_Tier actions.
4. WHEN a client_admin triggers an Approval_Tier action, THE System SHALL create an ActionRequest identical to when a client_manager triggers the same action, with no privilege escalation for client_admin.

### Requirement 6: Admin UI for Permission Matrix Override

**User Story:** As a platform operator, I want to view and edit a client's permission matrix from the admin panel, so that I can customize tier assignments per client without code changes.

#### Acceptance Criteria

1. THE Admin Panel SHALL provide a page at `/admin/clients/{client_id}/permissions` displaying the effective Permission_Matrix for a client.
2. WHEN an operator views the permissions page, THE System SHALL show each action identifier with its current tier and indicate whether the tier comes from the client override or the default.
3. WHEN an operator changes an action's tier on the permissions page and saves, THE System SHALL update the client's `permission_matrix` JSONB field with the new tier value.
4. THE permissions page SHALL provide a "Reset to Default" control per action that removes the client-specific override for that action, reverting it to the Default_Permission_Map tier.
5. THE permissions page SHALL provide a "Reset All to Default" control that replaces the entire `permission_matrix` with the Default_Permission_Map.
6. THE permissions page SHALL be accessible only to users with owner or partner roles.

### Requirement 7: Portal UI Tier Awareness

**User Story:** As a client user, I want the portal UI to reflect my permission capabilities, so that I see which actions I can perform instantly, which require approval, and which are unavailable.

#### Acceptance Criteria

1. WHEN rendering a portal page, THE System SHALL hide UI controls for actions classified as Admin_Only_Tier in the applicable Permission_Matrix for the current client.
2. WHEN rendering a portal page, THE System SHALL annotate UI controls for Approval_Tier actions with a visual indicator (badge or label) communicating that the action will create a request rather than execute immediately.
3. WHEN a client-scoped user has pending ActionRequests, THE Portal SHALL display a count of pending requests in the sidebar navigation.
4. THE Portal SHALL provide a "My Requests" page listing all ActionRequests for the current client with their status (pending, approved, rejected) and timestamps.
5. WHEN an ActionRequest is resolved (approved or rejected), THE System SHALL create a Notification for the requesting user with the outcome.

### Requirement 8: Rate Limiting Integration

**User Story:** As a platform operator, I want Self-Service tier actions to remain subject to existing rate limits, so that moving actions to self-service does not remove operational safety controls.

#### Acceptance Criteria

1. WHEN a Self_Service_Tier action is subject to an existing rate limit (via ClientActionLog), THE System SHALL enforce the rate limit independently of the permission tier check.
2. THE Permission_Guard SHALL execute before the rate limit check in the request processing pipeline, so that denied actions do not consume rate limit quota.
3. IF a Self_Service_Tier action exceeds its rate limit, THEN THE System SHALL return HTTP 429 with a retry-after indicator, consistent with existing portal action behavior.

### Requirement 9: Audit Trail

**User Story:** As a platform operator, I want all permission-related events logged, so that I can trace who did what and review tier enforcement history.

#### Acceptance Criteria

1. WHEN the Permission_Guard denies an action, THE System SHALL log an AuditLog entry with action `permission_denied`, the user_id, client_id, action_type, and the reason (admin_only or viewer_restricted).
2. WHEN an ActionRequest is created, THE System SHALL log an AuditLog entry with action `action_request_created` and the action_type.
3. WHEN an ActionRequest is approved or rejected, THE System SHALL log an AuditLog entry with action `action_request_resolved`, the resolver's user_id, and the outcome.
4. WHEN an operator modifies a client's Permission_Matrix via the admin UI, THE System SHALL log an AuditLog entry with action `permission_matrix_updated`, the operator's user_id, and the changed action identifiers with old and new tier values.
