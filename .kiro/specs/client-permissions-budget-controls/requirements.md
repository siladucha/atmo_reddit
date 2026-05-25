# Requirements Document

## Introduction

This specification formalizes the client permissions and AI budget controls for the Reddit Marketing SaaS platform. It documents the existing RBAC permission system (6 roles with query scoping and data isolation), the plan-based resource limits (avatars, subreddits, actions per month), the global system kill switches, and the AI cost tracking infrastructure. It also defines the NOT YET BUILT components: the budget engine (smart daily limits per avatar) and plan action limits enforcement (max_comments_per_month).

The goal is to have a single authoritative spec that covers both what is implemented and what needs to be added to complete the client permissions and budget control layer before scaling to 10+ clients.

## Glossary

- **Platform**: The Reddit Marketing SaaS application (backend + admin panel + pipeline)
- **RBAC_System**: The Role-Based Access Control subsystem that enforces permission guards and query scoping
- **Permission_Guard**: A FastAPI dependency that validates the authenticated user's role before granting access to a route
- **Query_Scope**: The QueryScope class that automatically filters database queries by client_id based on the user's role
- **Kill_Switch**: A system setting (stored in DB) that globally enables or disables a pipeline stage
- **Budget_Engine**: The subsystem that enforces smart daily AI usage limits per avatar and per client (NOT YET BUILT)
- **Plan_Limiter**: The subsystem that enforces monthly action caps (comments, posts) based on the client's plan_type (NOT YET BUILT)
- **AIUsageLog**: The database model that records every LLM API call with cost, tokens, operation type, and client/avatar attribution
- **Client**: A tenant entity representing a paying customer with plan_type, max_avatars, and associated avatars/subreddits
- **Avatar**: A managed Reddit persona assigned to one or more clients
- **Plan_Type**: One of seed, starter, growth, scale — each with defined resource limits
- **Action**: A billable pipeline operation (comment generation, post generation, scoring call)
- **Daily_Budget**: The maximum AI spend (in USD) allowed per avatar per day, computed from the monthly plan allocation

## Requirements

### Requirement 1: Role-Based Permission Guards

**User Story:** As a platform operator, I want route-level permission enforcement based on user roles, so that each user can only access functionality appropriate to their role.

#### Acceptance Criteria

1. WHEN an unauthenticated request reaches a protected route, THE Permission_Guard SHALL return a 303 redirect to the login page
2. WHEN an inactive user attempts to access any route, THE Permission_Guard SHALL deny access with a 303 redirect to the login page
3. WHEN a client-scoped user attempts to access a route requiring platform admin privileges, THE Permission_Guard SHALL return a 403 Access Denied response
4. THE Permission_Guard SHALL support six distinct role levels: owner, partner, client_admin, client_manager, client_viewer, b2c_user
5. WHEN a user with the owner role accesses any route, THE Permission_Guard SHALL grant access regardless of the guard level applied
6. WHEN a user with the partner role accesses a route protected by require_platform_admin, THE Permission_Guard SHALL grant access
7. WHEN a client-scoped user accesses a route with require_client_access(client_id), THE Permission_Guard SHALL grant access only if the user's client_id matches the requested client_id

### Requirement 2: Query Scoping and Data Isolation

**User Story:** As a platform operator, I want automatic client data isolation at the query level, so that no client can ever see another client's data.

#### Acceptance Criteria

1. WHEN a client-scoped user queries a tenant-owned entity that has a client_id column, THE Query_Scope SHALL automatically filter results to only include records matching the user's client_id
2. WHEN an owner or partner queries a tenant-owned entity, THE Query_Scope SHALL return unfiltered results without applying any client_id filter
3. WHEN a background task (Celery worker) queries tenant-owned data, THE Query_Scope SHALL use system_context() which bypasses user-based scoping and returns unfiltered results
4. WHEN a client-scoped user queries avatars, THE Query_Scope SHALL include both owned avatars (client_id present in avatar.client_ids array) and actively rented avatars (rental records where is_active is true and expires_at is null or in the future)
5. WHEN a client-scoped user queries Reddit threads, THE Query_Scope SHALL include only threads that have a ThreadScore record matching the user's client_id
6. IF a client-scoped user has no client_id assigned and a query operation is attempted, THEN THE Query_Scope SHALL return an empty result set and log a security warning
7. IF a client-scoped user attempts a write operation targeting a different client_id, THEN THE Query_Scope SHALL raise a SecurityError and deny the operation
8. IF a query is executed without any user context and without system_context(), THEN THE Query_Scope SHALL fail closed by returning an empty result set
9. WHEN a client-scoped user queries a tenant-owned entity that has no client_id column and no special scoping rule, THE Query_Scope SHALL return an empty result set rather than exposing unscoped data

### Requirement 3: LLM Context Isolation

**User Story:** As a platform operator, I want runtime assertions during LLM context assembly, so that one client's data never leaks into another client's AI-generated content.

#### Acceptance Criteria

1. WHEN the generation service assembles context for a comment, THE Platform SHALL verify that the avatar is accessible by the target client — where accessible means the client's ID is present in the avatar's client_ids array OR an active, non-expired rental record exists linking the avatar to the client — before proceeding with generation
2. WHEN the persona selection service evaluates avatars for a client, THE Platform SHALL assert that each candidate avatar belongs to or is rented by the client, and exclude any avatar that fails the check from the candidate list
3. IF all candidate avatars fail the accessibility check during persona selection, THEN THE Platform SHALL raise an error, log a security warning identifying the client and the failed avatar usernames, and abort generation for that thread without producing any content
4. IF a single avatar fails the accessibility check during context assembly, THEN THE Platform SHALL log a security warning identifying the avatar and client, and skip that avatar without generating content
5. WHEN the generation service injects learning context (few-shot examples and correction patterns) into the LLM prompt, THE Platform SHALL assert that each learning record's client_id matches the target client_id, and discard any record that does not match
6. THE Platform SHALL verify avatar-client accessibility through both the client_ids array (ownership) and rental records where is_active is true and expires_at is either null or in the future

### Requirement 4: Global Kill Switches

**User Story:** As a platform owner, I want global kill switches for pipeline stages, so that I can immediately halt operations in an emergency.

#### Acceptance Criteria

1. THE Platform SHALL provide three independent kill switches: pipeline_enabled, generation_enabled, scrape_enabled, each accepting only the values "true" or "false"
2. WHEN pipeline_enabled is set to false, THE Platform SHALL skip all AI pipeline tasks (scoring and generation) for all clients, beginning with the next task that checks the switch value
3. WHEN generation_enabled is set to false, THE Platform SHALL skip comment generation while allowing scoring to continue
4. WHEN scrape_enabled is set to false, THE Platform SHALL skip all subreddit scraping tasks
5. WHEN a kill switch value is checked by a Celery worker, THE Platform SHALL read the value directly from the database (bypassing in-memory cache) to ensure the switch takes effect within one task cycle (at most 60 seconds from the moment the value is persisted)
6. THE Platform SHALL restrict kill switch modification to users with the owner role only
7. WHEN a kill switch value is changed, THE Platform SHALL record an audit log entry containing the setting key, new value, user identity, and timestamp
8. WHEN a task is skipped due to a kill switch being disabled, THE Platform SHALL log the skip event including the task name and the kill switch that caused it

### Requirement 5: Plan-Based Resource Limits (Existing)

**User Story:** As a platform operator, I want plan-based resource limits stored on the client model, so that each client's avatar allocation matches their subscription tier.

#### Acceptance Criteria

1. THE Client model SHALL store a plan_type field with allowed values: seed, starter, growth, scale
2. THE Client model SHALL store a max_avatars field representing the maximum number of avatars the client can use
3. WHEN a client on the seed plan is created, THE Platform SHALL set max_avatars to 1
4. WHEN a client on the starter plan is created, THE Platform SHALL set max_avatars to 3
5. WHEN a client on the growth plan is created, THE Platform SHALL set max_avatars to 7
6. WHEN a client on the scale plan is created, THE Platform SHALL set max_avatars to 15
7. WHEN an avatar assignment would exceed the client's max_avatars limit, THE Platform SHALL reject the assignment and return an error
8. WHEN a platform admin (owner or partner) assigns an avatar, THE Platform SHALL bypass the max_avatars limit check to allow manual overrides
9. THE Platform SHALL count only avatars where the client's ID is present in the avatar's client_ids array toward the max_avatars limit (rented avatars count separately)

### Requirement 6: Plan Action Limits Enforcement

**User Story:** As a platform operator, I want monthly action caps enforced per client based on their plan, so that clients cannot exceed their subscription allowance.

#### Acceptance Criteria

1. THE Plan_Limiter SHALL enforce the following monthly comment limits: seed=30, starter=60, growth=150, scale=400
2. WHEN the generation pipeline attempts to create a comment draft for a client, THE Plan_Limiter SHALL query the count of comment drafts with status "pending", "approved", or "posted" created within the current calendar month (Asia/Jerusalem timezone) for that client and compare it against the plan limit
3. IF a client's current month comment count equals or exceeds their plan's monthly comment limit, THEN THE Plan_Limiter SHALL skip generation for that client and log an activity event with reason "plan_limit_reached"
4. THE Plan_Limiter SHALL count only comment drafts with status "pending", "approved", or "posted" toward the monthly limit (rejected drafts do not count)
5. THE Plan_Limiter SHALL determine the current month boundary using the Asia/Jerusalem timezone, such that the action count resets to zero at midnight on the first day of each calendar month in that timezone
6. THE Platform SHALL expose the current action count and remaining allowance on the admin client detail page, showing the numeric count used and the numeric count remaining for the current month
7. WHEN a client's current month comment count first reaches or exceeds 80% of their monthly limit, THE Platform SHALL log a single warning activity event "plan_limit_approaching" per calendar month (no duplicate warnings within the same month)
8. IF multiple comment drafts are being generated for a client within the same pipeline batch and the limit is reached mid-batch, THEN THE Plan_Limiter SHALL skip generation for remaining drafts in that batch and log a single "plan_limit_reached" activity event

### Requirement 7: AI Cost Tracking

**User Story:** As a platform operator, I want every LLM API call logged with cost attribution, so that I can monitor AI spend per client and per avatar.

#### Acceptance Criteria

1. WHEN an LLM API call completes successfully, THE Platform SHALL create an AIUsageLog record with: client_id, avatar_id, operation type, model name, input_tokens, output_tokens, cost_usd (precision to 6 decimal places), and duration_ms
2. THE AIUsageLog SHALL support the following operation types: scoring, persona_select, generation, editing, hobby_comment, post_draft
3. THE Platform SHALL index AIUsageLog by (client_id, created_at) for efficient per-client cost queries
4. THE Platform SHALL index AIUsageLog by operation type for aggregate cost analysis
5. WHEN an LLM call is triggered by a background task, THE AIUsageLog SHALL record the triggered_by field as "scheduler" or "orchestrator"
6. WHEN an LLM call is triggered manually, THE AIUsageLog SHALL record the triggered_by field as "manual", "api", or "test_run"
7. IF an LLM API call fails or times out, THEN THE Platform SHALL still create an AIUsageLog record with duration_ms reflecting elapsed time, input_tokens set to the tokens sent, output_tokens set to 0, and cost_usd set to 0.000000
8. WHEN an LLM call is not attributable to a specific client or avatar (system-level operation), THE AIUsageLog SHALL record client_id and avatar_id as null while still capturing operation type, model, tokens, cost, and duration

### Requirement 8: Budget Engine — Smart Daily Limits

**User Story:** As a platform operator, I want smart daily AI budget limits per avatar, so that monthly spend is distributed evenly and no single avatar consumes the entire budget in one day.

#### Acceptance Criteria

1. THE Budget_Engine SHALL compute a daily budget per avatar as: (client monthly AI budget / days in current calendar month) / number of active non-frozen avatars with warming_phase > 0 assigned to the client
2. WHEN the AI pipeline processes an avatar, THE Budget_Engine SHALL check the avatar's cumulative AI spend for the current day by summing cost_usd from AIUsageLog where avatar_id matches and created_at falls within the current calendar day in the Asia/Jerusalem timezone
3. IF an avatar's daily spend exceeds the computed daily budget multiplied by 1.2 (configurable overage tolerance stored as the system setting budget_overage_tolerance_pct with default value 20), THEN THE Budget_Engine SHALL skip further AI operations (scoring, generation, persona_select, editing) for that avatar until the next calendar day in Asia/Jerusalem timezone and log an activity event with reason "daily_budget_exceeded"
4. WHEN a client has a per-client monthly_ai_budget_usd value configured on the Client model, THE Budget_Engine SHALL use that value as the monthly budget for daily limit computation
5. WHEN a client has no explicit monthly_ai_budget_usd configured (null or 0), THE Budget_Engine SHALL compute the client's monthly budget as: global monthly_budget_usd system setting / number of active clients (equal split)
6. IF a client has zero active non-frozen avatars with warming_phase > 0, THEN THE Budget_Engine SHALL skip daily budget computation for that client and log an activity event with reason "no_eligible_avatars_for_budget"
7. THE Platform SHALL expose daily budget utilization (current day spend in USD, computed daily limit in USD, and percentage used) on the admin avatar detail page
8. WHEN an avatar's daily budget is exhausted, THE Budget_Engine SHALL still allow health checks, karma tracking, and presence scanning (non-LLM operations) to proceed without budget restriction

### Requirement 9: Client Deactivation Cascade

**User Story:** As a platform operator, I want client deactivation to immediately halt all pipeline activity for that client, so that deactivated clients consume no resources.

#### Acceptance Criteria

1. WHEN a client's is_active field is set to false, THE Platform SHALL skip all pipeline tasks (scraping, scoring, generation, post generation, hobby pipeline) for that client's subreddits and avatars on the next task execution cycle, logging a skip message for each skipped task
2. WHEN a client-scoped user (client_admin, client_manager, client_viewer, or b2c_user) belonging to a deactivated client attempts to access any protected route, THE Permission_Guard SHALL return a 403 Access Denied response on every request — not only at login
3. WHEN a client is deactivated, THE Platform SHALL log an audit event recording the action "deactivate", entity_type "client", the client_id, and the acting user's identity
4. WHEN a deactivated client is reactivated, THE Platform SHALL resume pipeline processing on the next scheduled run without requiring manual intervention, using the preserved avatar assignments and subreddit assignments
5. WHILE a client is deactivated, THE Platform SHALL preserve all avatar assignments, subreddit assignments, and pending drafts so that reactivation restores the client to its prior operational state
6. WHILE a client is deactivated, THE Platform SHALL continue to allow owner and partner users to view and manage the deactivated client's data through admin routes

### Requirement 10: Draft Approval Control

**User Story:** As a platform operator, I want configurable draft approval requirements per client, so that B2C users can optionally bypass the review queue.

#### Acceptance Criteria

1. THE Client model SHALL store a draft_approval_enabled boolean field (default: false)
2. WHILE draft_approval_enabled is true for a client, THE Platform SHALL require a user with owner, partner, client_admin, or client_manager role to explicitly set a draft's status to "approved" before it can proceed to posting
3. WHEN the generation service creates a comment draft or post draft for a client with draft_approval_enabled set to false, THE Platform SHALL set the draft status to "approved" immediately upon creation (bypassing the "pending" state)
4. WHEN a draft is auto-approved due to draft_approval_enabled being false, THE Platform SHALL log an activity event with action "draft_auto_approved" including the draft_id and client_id
5. IF auto-approval fails due to a system error during draft creation, THEN THE Platform SHALL fall back to creating the draft with status "pending" and log a warning activity event with reason "auto_approve_failed"
6. THE Platform SHALL restrict modification of draft_approval_enabled to users with owner, partner, or client_admin roles
7. WHEN a client's draft_approval_enabled setting is changed, THE Platform SHALL log an audit event recording the previous value, new value, and the acting user's identity

### Requirement 11: AI Budget Alerting

**User Story:** As a platform operator, I want alerts when AI spend approaches configured limits, so that I can take action before budgets are exhausted.

#### Acceptance Criteria

1. WHEN an AIUsageLog record is created and the total monthly AI spend across all clients reaches or exceeds 80% of the global monthly_budget_usd setting, THE Platform SHALL log a warning activity event "global_budget_approaching" with metadata containing current_spend_usd, budget_usd, and percentage
2. WHEN an AIUsageLog record is created and the total monthly AI spend exceeds the global monthly_budget_usd setting, THE Platform SHALL log a critical activity event "global_budget_exceeded" with metadata containing current_spend_usd, budget_usd, and percentage
3. IF the global monthly_budget_usd is set to 0, THEN THE Platform SHALL treat the budget as unlimited and skip all budget threshold checks
4. THE Platform SHALL compute monthly AI spend by summing cost_usd from AIUsageLog records where created_at falls within the current calendar month in the Asia/Jerusalem timezone
5. THE Platform SHALL log each threshold alert ("global_budget_approaching" and "global_budget_exceeded") at most once per calendar month; subsequent spend increases within the same month SHALL NOT produce duplicate events
6. WHEN the "global_budget_exceeded" event is logged, THE Platform SHALL continue pipeline operations without halting (alerting is informational only and does not block AI operations)
