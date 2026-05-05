# Requirements Document

## Introduction

This feature extends the Reddit Marketing SaaS platform with a comprehensive admin panel and a structured client onboarding flow. The current system has minimal admin capabilities — only an AI cost dashboard (`/admin-page`) and a basic settings page (`/settings`) for API keys. The goal is to build a full system management interface covering user management, client CRUD with onboarding wizard, persona management, keyword management, subreddit configuration, Celery task monitoring, system health dashboard, audit logs, and billing placeholders. The first client to be onboarded through this flow is NeuroYoga (ATMO app).

The admin panel uses the existing tech stack: FastAPI + Jinja2/HTMX + Tailwind CSS, with server-side rendering and HTMX partials for interactivity. All existing 60 tests must continue to pass.

## Glossary

- **Admin_Panel**: The unified administration interface accessible at `/admin/*` routes, providing system management capabilities to authenticated superusers.
- **Onboarding_Wizard**: A multi-step guided flow within the Admin_Panel for setting up a new client from scratch, including profile creation, subreddit configuration, keyword setup, avatar assignment, persona creation, and pipeline configuration.
- **Client**: A business entity (brand) that uses the platform for Reddit marketing. Represented by the `clients` DB table.
- **Avatar**: A Reddit account identity used to post comments and posts. An avatar has a voice profile, tone principles, and can serve multiple clients. Represented by the `avatars` DB table.
- **Persona**: A client-specific voice profile that guides AI comment generation for a particular client. Represented by the `personas` DB table.
- **Subreddit**: A Reddit community monitored for a specific client. Represented by the `client_subreddits` DB table.
- **Keyword**: A scoring term with a priority level (HIGH, MEDIUM, LOW) used by the AI scoring pipeline to evaluate thread relevance for a client. Stored as JSONB in the `clients.keywords` column.
- **Pipeline**: The automated sequence of Celery tasks: scrape subreddits → score threads → select persona → generate comments → edit/quality check.
- **System_Health_Dashboard**: A panel within the Admin_Panel showing the operational status of Redis, PostgreSQL, Celery workers, and external API connections.
- **Audit_Log_Viewer**: A read-only interface for browsing the `audit_log` table, showing all user actions with filtering and pagination.
- **User**: An authenticated person who accesses the platform. Represented by the `users` DB table with `is_superuser` flag for admin access.
- **Test_Run**: A single-client pipeline execution triggered manually from the onboarding wizard to validate the client configuration before enabling scheduled runs.
- **Billing_Placeholder**: A reserved section in the Admin_Panel for future billing features, displaying current AI costs and budget settings without payment processing.

## Requirements

### Requirement 1: Admin Panel Navigation and Layout

**User Story:** As an admin, I want a unified admin panel with sidebar navigation, so that I can access all system management features from a single interface.

#### Acceptance Criteria

1. THE Admin_Panel SHALL provide a sidebar navigation menu with links to: Dashboard, Users, Clients, Avatars, Personas, Subreddits, Keywords, Tasks, System Health, AI Costs, Audit Logs, and Billing.
2. THE Admin_Panel SHALL render all pages using the existing Jinja2 + HTMX + Tailwind CSS stack with a shared `admin_base.html` layout template.
3. WHEN an unauthenticated user accesses any `/admin/*` route, THE Admin_Panel SHALL redirect the user to the `/login` page.
4. WHEN a non-superuser accesses any `/admin/*` route, THE Admin_Panel SHALL return an HTTP 403 response with an "Access Denied" message.
5. THE Admin_Panel SHALL highlight the currently active navigation item in the sidebar.
6. THE Admin_Panel SHALL preserve the existing top navigation bar from `base.html` for non-admin pages without modification.

### Requirement 2: User Management

**User Story:** As an admin, I want to manage platform users, so that I can control who has access to the system and assign roles.

#### Acceptance Criteria

1. THE Admin_Panel SHALL display a paginated list of all users showing email, full name, active status, superuser status, and creation date.
2. WHEN the admin submits the "Create User" form with a valid email and password, THE Admin_Panel SHALL create a new User record in the database.
3. WHEN the admin submits the "Create User" form with an email that already exists, THE Admin_Panel SHALL display an error message "Email already registered" without creating a duplicate.
4. WHEN the admin toggles the active status of a user, THE Admin_Panel SHALL update the `is_active` field of that User record.
5. WHEN the admin toggles the superuser status of a user, THE Admin_Panel SHALL update the `is_superuser` field of that User record.
6. THE Admin_Panel SHALL prevent the admin from deactivating their own user account.
7. WHEN the admin clicks "Delete" on a user, THE Admin_Panel SHALL soft-delete the user by setting `is_active` to false.

### Requirement 3: Client Management with Full CRUD

**User Story:** As an admin, I want full client management capabilities, so that I can create, view, edit, and deactivate clients.

#### Acceptance Criteria

1. THE Admin_Panel SHALL display a paginated list of all clients showing client name, brand name, active status, number of subreddits, number of avatars, and creation date.
2. WHEN the admin submits the "Create Client" form with a valid client name and brand name, THE Admin_Panel SHALL create a new Client record with all provided fields (company_profile, company_worldview, company_problem, competitive_landscape, brand_voice, icp_profiles).
3. WHEN the admin opens the client edit page, THE Admin_Panel SHALL pre-populate all form fields with the current client data.
4. WHEN the admin submits the client edit form, THE Admin_Panel SHALL update only the fields that were modified.
5. WHEN the admin deactivates a client, THE Admin_Panel SHALL set the `is_active` field to false and stop including that client in scheduled pipeline runs.
6. THE Admin_Panel SHALL display a client detail page showing all client fields, assigned avatars, configured subreddits, keywords summary, and personas.

### Requirement 4: Client Onboarding Wizard

**User Story:** As an admin, I want a step-by-step onboarding wizard, so that I can set up a new client completely from a single guided flow.

#### Acceptance Criteria

1. THE Onboarding_Wizard SHALL guide the admin through the following steps in order: (a) Client Profile, (b) Subreddit Configuration, (c) Keyword Setup, (d) Avatar Assignment, (e) Persona Creation, (f) Pipeline Configuration, (g) Test Run.
2. WHEN the admin completes step (a), THE Onboarding_Wizard SHALL create the Client record in the database and proceed to step (b).
3. WHEN the admin adds subreddits in step (b), THE Onboarding_Wizard SHALL create ClientSubreddit records linked to the new client.
4. WHEN the admin configures keywords in step (c), THE Onboarding_Wizard SHALL save the keywords as a structured JSONB object in the `clients.keywords` field with each keyword having a name and priority level (HIGH, MEDIUM, or LOW).
5. WHEN the admin assigns avatars in step (d), THE Onboarding_Wizard SHALL update the `client_ids` array on each selected Avatar to include the new client ID.
6. WHEN the admin creates personas in step (e), THE Onboarding_Wizard SHALL create Persona records linked to the new client with persona name and voice profile.
7. THE Onboarding_Wizard SHALL allow the admin to navigate back to any previous step without losing entered data.
8. WHEN the admin triggers a test run in step (g), THE Onboarding_Wizard SHALL dispatch the full pipeline (scrape → score → generate) as a Celery task chain for the new client and display the task status.

### Requirement 5: Persona Management

**User Story:** As an admin, I want to manage personas per client, so that I can define different voice profiles for AI-generated content.

#### Acceptance Criteria

1. THE Admin_Panel SHALL display a list of personas grouped by client, showing persona name, platform, active status, and creation date.
2. WHEN the admin submits the "Create Persona" form with a client, persona name, and voice profile, THE Admin_Panel SHALL create a new Persona record linked to the selected client.
3. WHEN the admin edits a persona, THE Admin_Panel SHALL allow modification of persona name, voice profile, and active status.
4. WHEN the admin deactivates a persona, THE Admin_Panel SHALL set the `is_active` field to false, excluding that persona from future AI pipeline runs.
5. THE Admin_Panel SHALL allow filtering personas by client.

### Requirement 6: Keyword Management

**User Story:** As an admin, I want a dedicated UI for managing client keywords with priority levels, so that I can fine-tune the AI scoring pipeline per client.

#### Acceptance Criteria

1. THE Admin_Panel SHALL display the keyword list for a selected client, showing each keyword's name and priority level (HIGH, MEDIUM, LOW).
2. WHEN the admin adds a keyword with a name and priority level, THE Admin_Panel SHALL append the keyword to the client's `keywords` JSONB field.
3. WHEN the admin removes a keyword, THE Admin_Panel SHALL remove that keyword entry from the client's `keywords` JSONB field.
4. WHEN the admin changes a keyword's priority level, THE Admin_Panel SHALL update the priority value in the client's `keywords` JSONB field.
5. THE Admin_Panel SHALL validate that keyword names are non-empty and that priority levels are one of HIGH, MEDIUM, or LOW.
6. THE Admin_Panel SHALL use HTMX partial updates for add, remove, and edit operations to avoid full page reloads.

### Requirement 7: Subreddit Management

**User Story:** As an admin, I want to manage subreddits per client, so that I can control which Reddit communities are monitored for each client.

#### Acceptance Criteria

1. THE Admin_Panel SHALL display the subreddit list for a selected client, showing subreddit name, type (professional or hobby), active status, and creation date.
2. WHEN the admin adds a subreddit with a name and type, THE Admin_Panel SHALL create a ClientSubreddit record linked to the selected client.
3. WHEN the admin adds a subreddit name that already exists for that client, THE Admin_Panel SHALL reactivate the existing record instead of creating a duplicate.
4. WHEN the admin removes a subreddit, THE Admin_Panel SHALL set the `is_active` field to false (soft delete).
5. WHEN the admin adds a subreddit, THE Admin_Panel SHALL validate that the subreddit name matches the pattern of a valid Reddit subreddit name (alphanumeric and underscores, 3-21 characters).

### Requirement 8: Celery Task Monitoring

**User Story:** As an admin, I want to monitor background tasks, so that I can see what the system is doing and troubleshoot issues.

#### Acceptance Criteria

1. THE Admin_Panel SHALL display a list of recent Celery task executions showing task name, status (pending, started, success, failure), client name, start time, and duration.
2. WHEN the admin clicks on a task entry, THE Admin_Panel SHALL display the task result or error traceback.
3. THE Admin_Panel SHALL provide buttons to manually trigger the following pipelines: full pipeline per client, hobby pipeline per avatar, and avatar health check.
4. WHEN the admin triggers a manual pipeline run, THE Admin_Panel SHALL dispatch the corresponding Celery task and display the queued task ID.
5. THE Admin_Panel SHALL auto-refresh the task list using HTMX polling at a 10-second interval.

### Requirement 9: System Health Dashboard

**User Story:** As an admin, I want a system health overview, so that I can quickly verify that all services are operational.

#### Acceptance Criteria

1. THE System_Health_Dashboard SHALL display the connection status of: PostgreSQL database, Redis cache, Celery workers, Reddit API, and LLM API.
2. WHEN a service connection check fails, THE System_Health_Dashboard SHALL display the service status as "Error" with a red indicator and a truncated error message.
3. WHEN all service connections succeed, THE System_Health_Dashboard SHALL display each service status as "Connected" with a green indicator.
4. THE System_Health_Dashboard SHALL display the count of active Celery workers and their hostnames.
5. THE System_Health_Dashboard SHALL display basic database statistics: total clients, total avatars, total threads, total comment drafts, and total pending reviews.

### Requirement 10: AI Cost Tracking (Enhanced)

**User Story:** As an admin, I want detailed AI cost tracking, so that I can monitor spending and stay within budget.

#### Acceptance Criteria

1. THE Admin_Panel SHALL display total AI cost, total API calls, total input tokens, and total output tokens as summary cards.
2. THE Admin_Panel SHALL display AI cost breakdown by client in a table.
3. THE Admin_Panel SHALL display AI cost breakdown by operation type (scoring, persona_select, generation, editing).
4. THE Admin_Panel SHALL display AI cost breakdown by model.
5. THE Admin_Panel SHALL display the current monthly budget setting and the percentage of budget consumed.
6. WHEN the monthly AI cost exceeds 80% of the configured budget, THE Admin_Panel SHALL display a warning indicator on the AI Costs page.

### Requirement 11: Audit Log Viewer

**User Story:** As an admin, I want to browse audit logs, so that I can track all user actions in the system for accountability.

#### Acceptance Criteria

1. THE Audit_Log_Viewer SHALL display a paginated list of audit log entries showing timestamp, user email, action, entity type, entity ID, and client name.
2. THE Audit_Log_Viewer SHALL support filtering by user, client, action type, and date range.
3. THE Audit_Log_Viewer SHALL sort entries by creation date in descending order (newest first).
4. THE Audit_Log_Viewer SHALL be read-only with no edit or delete capabilities.

### Requirement 12: Billing Placeholder

**User Story:** As an admin, I want a billing section in the admin panel, so that the interface is ready for future payment processing integration.

#### Acceptance Criteria

1. THE Billing_Placeholder SHALL display the current monthly AI cost and the configured monthly budget.
2. THE Billing_Placeholder SHALL display the AWS credits remaining value from system settings.
3. THE Billing_Placeholder SHALL display a "Coming Soon" notice for payment processing features.
4. THE Billing_Placeholder SHALL provide a link to the system settings page for editing budget values.

### Requirement 13: Admin Panel Audit Logging

**User Story:** As an admin, I want all admin actions to be logged, so that there is a complete audit trail of system changes.

#### Acceptance Criteria

1. WHEN the admin creates, updates, or deactivates a client, THE Admin_Panel SHALL write an entry to the `audit_log` table with the action, entity type "client", entity ID, and the admin's user ID.
2. WHEN the admin creates, updates, or deactivates a user, THE Admin_Panel SHALL write an entry to the `audit_log` table with the action, entity type "user", entity ID, and the admin's user ID.
3. WHEN the admin creates, updates, or deactivates a persona, THE Admin_Panel SHALL write an entry to the `audit_log` table with the action, entity type "persona", entity ID, and the admin's user ID.
4. WHEN the admin modifies keywords or subreddits for a client, THE Admin_Panel SHALL write an entry to the `audit_log` table with the action, entity type, client ID, and the admin's user ID.
5. WHEN the admin triggers a manual pipeline run, THE Admin_Panel SHALL write an entry to the `audit_log` table with the action "trigger_pipeline", the client or avatar ID, and the admin's user ID.

### Requirement 14: NeuroYoga Client Seed Data

**User Story:** As an admin, I want seed data for the NeuroYoga (ATMO) client, so that I can quickly set up the first client for testing and demonstration.

#### Acceptance Criteria

1. THE Seed_Script SHALL create a Client record for NeuroYoga with: client_name "NeuroYoga", brand_name "ATMO", and populated company_profile, company_worldview, company_problem, competitive_landscape, brand_voice, and icp_profiles fields based on the ATMO product description.
2. THE Seed_Script SHALL create ClientSubreddit records for NeuroYoga covering relevant communities: meditation, breathing, yoga, TCM, stress management, wellness technology, and biohacking subreddits.
3. THE Seed_Script SHALL create keyword entries for NeuroYoga with appropriate priority levels covering: breathing exercises (HIGH), acupressure (HIGH), stress relief (HIGH), TCM (MEDIUM), meditation app (MEDIUM), HRV biofeedback (MEDIUM), wellness tech (LOW), and mindfulness (LOW).
4. THE Seed_Script SHALL create at least one Persona record for NeuroYoga with a voice profile appropriate for wellness and breathing communities.
5. THE Seed_Script SHALL be idempotent — running the script multiple times shall not create duplicate records.

### Requirement 15: Superuser Access Control

**User Story:** As a system owner, I want admin panel access restricted to superusers, so that regular users cannot modify system configuration.

#### Acceptance Criteria

1. THE Admin_Panel SHALL check the `is_superuser` flag on the authenticated User before rendering any admin page.
2. WHEN a request to any `/admin/*` route comes from a user where `is_superuser` is false, THE Admin_Panel SHALL return an HTTP 403 response.
3. THE Admin_Panel navigation links SHALL only be visible in the top navigation bar to users where `is_superuser` is true.
4. THE existing non-admin pages (dashboard, review, threads, avatars-page) SHALL remain accessible to all authenticated users without requiring superuser status.
