# Requirements Document

## Introduction

Production Readiness Audit is a mandatory Go/No-Go gate before RAMP deploys to production with paying clients. The audit systematically identifies hidden risks across data leakage, credit/usage integrity, rate limiting coverage, LLM response reliability, user flow completeness, specification coverage, and technical debt. The output is a unified risk report with a traffic-light dashboard (RED/YELLOW/GREEN) enabling an objective GO/NO-GO decision.

This is not a bugfix sprint — it is a structured reliability and security audit that produces actionable artifacts: integration maps, state diagrams, flow inventories, and a production dashboard.

## Glossary

- **Audit_Engine**: The system responsible for executing audit checks, collecting findings, and producing reports
- **Data_Path_Analyzer**: The component that traces data flow from external sources through processing to output
- **Credit_Integrity_Checker**: The component that verifies usage accounting state transitions and invariants
- **Rate_Limit_Auditor**: The component that verifies all operations route through the unified rate limit engine
- **LLM_Reliability_Monitor**: The component that tracks LLM task lifecycle states and detects lost responses
- **Flow_Completeness_Scanner**: The component that inventories all user/system flows and verifies terminal states
- **Spec_Coverage_Tracker**: The component that maps specifications to implementation and test coverage
- **Debt_Radar**: The component that scans codebase for reliability, performance, security, and product debt patterns
- **Production_Dashboard**: The admin UI screen displaying the unified RED/YELLOW/GREEN status of all audit findings
- **External_Integration**: Any connection to Reddit API, LLM providers (LiteLLM/Claude/Gemini), or third-party services
- **Bypass_Path**: Any code path that executes an operation without going through the expected control gate (rate limiter, permission check, safety gate)
- **Lost_Response**: An LLM task that was accepted but whose response is neither delivered nor recoverable
- **Flow_Inventory**: A complete catalog of all user and system flows with their terminal states documented
- **Blocker**: A finding with severity RED that prevents production deployment
- **Retention_Policy**: The configured data lifecycle period (90 days for scraped threads, indefinite for audit logs)
- **Idempotency_Key**: A unique identifier ensuring an operation executes exactly once even when retried

## Requirements

### Requirement 1: External Data Leakage Detection

**User Story:** As a platform operator, I want to trace all external data paths end-to-end, so that I can verify no sensitive data leaks beyond its intended boundary.

#### Acceptance Criteria

1. WHEN an audit is initiated, THE Data_Path_Analyzer SHALL trace every external integration path from source fetch through queue, processing, storage, LLM context, to output, covering at minimum: Reddit API (PRAW), LLM providers (LiteLLM/Gemini/Claude), Redis cache, PostgreSQL storage, proxy services, and SSE notification channels
2. THE Data_Path_Analyzer SHALL verify that raw API responses from Reddit are not stored with more than 500 characters of the original post body beyond the retention policy of 90 days, and that any records older than 90 days contain only derived metadata (scores, flags, IDs)
3. THE Data_Path_Analyzer SHALL verify that authentication tokens (Reddit OAuth, LLM API keys, proxy credentials) are not transmitted to any external service other than their intended provider, where intended providers are: Reddit OAuth tokens to reddit.com only, LLM API keys to their respective provider endpoints only, and proxy credentials to the configured proxy host only
4. THE Data_Path_Analyzer SHALL verify that no private user data (passwords, email addresses, IP addresses, OAuth refresh tokens) appears in application logs across all configured log outputs (stdout, file-based logs, and activity_events table free-text fields)
5. THE Data_Path_Analyzer SHALL verify that raw scraped content does not enter embedding vectors without sanitization, where sanitization requires at minimum: removal of usernames, removal of URLs, and stripping of Markdown formatting before vectorization
6. THE Data_Path_Analyzer SHALL verify that cached external data in Redis is purged according to the configured retention policy, and that no cache key containing external API response data has a TTL exceeding 24 hours or persists beyond the configured retention period
7. THE Data_Path_Analyzer SHALL verify that no internal database IDs (primary keys, foreign keys, or UUIDs used as row identifiers) are exposed in user-facing output or API responses to non-admin roles
8. THE Data_Path_Analyzer SHALL verify that LLM prompts do not contain credentials, internal database IDs, or data from other clients (context isolation check), by confirming each prompt includes data from at most one client_id
9. WHEN the trace is complete, THE Data_Path_Analyzer SHALL produce an integration map table with columns: Integration, Data_Read, Data_Stored, Retention_Period, Access_Roles, and Compliance_Status (PASS or FAIL with reason)
10. IF any criterion (2 through 8) detects a violation, THEN THE Data_Path_Analyzer SHALL flag the violation in the integration map with the specific criterion failed, the data path where the violation occurred, and a severity level (critical for credential exposure, high for cross-client leakage, medium for retention violations)
11. IF no retention policy is explicitly configured for a data category, THEN THE Data_Path_Analyzer SHALL apply the default retention limit of 90 days for scraped content and 24 hours for cached API responses

### Requirement 2: Credit and Usage Accounting Integrity

**User Story:** As a platform operator, I want to verify that credit/usage accounting is consistent across all state transitions, so that no operation is charged incorrectly or executed without accounting.

#### Acceptance Criteria

1. THE Credit_Integrity_Checker SHALL verify that each AI operation follows the accounting sequence: Task Dispatched, Execution Started, LLM Call Completed, AIUsageLog Entry Recorded, with no step skipped or reordered
2. THE Credit_Integrity_Checker SHALL verify that no single operation (identified by the combination of client_id, avatar_id, thread_id, and operation type) is recorded more than once in AIUsageLog for the same execution window of 60 seconds
3. THE Credit_Integrity_Checker SHALL verify that every Celery task that invokes an LLM call and returns a successful result has a corresponding AIUsageLog entry with matching client_id, avatar_id, operation, and created_at within 5 seconds of task completion
4. IF an LLM call returns an error or produces zero output_tokens, THEN THE Credit_Integrity_Checker SHALL verify that no AIUsageLog entry is recorded with cost_usd greater than 0 for that failed call
5. IF a Celery task is revoked or times out after an LLM call has been dispatched but before AIUsageLog is written, THEN THE Credit_Integrity_Checker SHALL flag the orphaned execution as an unreconciled usage gap requiring manual review
6. WHEN a retry occurs after a transient LLM failure (HTTP 429, 500, or timeout), THE Credit_Integrity_Checker SHALL verify that only the successful attempt is recorded in AIUsageLog and that failed retry attempts with zero tokens are not counted toward client cost totals
7. WHEN a Celery worker restarts during task execution, THE Credit_Integrity_Checker SHALL verify that the in-progress operation either completes with a single AIUsageLog entry or is flagged as an unreconciled gap within the next scheduled audit run
8. WHEN duplicate Celery message delivery occurs (same task_id dispatched more than once), THE Credit_Integrity_Checker SHALL verify that at most one AIUsageLog entry exists per unique task execution, using the Celery task_id as the deduplication key
9. WHEN the audit is complete, THE Credit_Integrity_Checker SHALL produce a reconciliation report listing: total operations executed, total AIUsageLog entries, count of duplicates detected, count of missing entries, count of orphaned executions, and a per-client cost variance summary

### Requirement 3: Unified Rate Limit Coverage

**User Story:** As a platform operator, I want to confirm that all operations pass through a single rate-limiting engine, so that no operation can bypass resource controls.

#### Acceptance Criteria

1. THE Rate_Limit_Auditor SHALL verify that all Reddit API calls route through the unified rate limit engine by confirming each call invokes the engine's is_allowed() check before execution and record_request() after execution
2. THE Rate_Limit_Auditor SHALL verify that all LLM API calls (scoring, generation, persona selection, editing) route through the unified rate limit engine by confirming each call invokes the engine's permit check before dispatching the request
3. THE Rate_Limit_Auditor SHALL verify that all avatar execution operations (posting, commenting) route through the unified rate limit engine by confirming each operation invokes the engine's permit check before PRAW execution
4. THE Rate_Limit_Auditor SHALL verify that trial user operations are subject to rate limiting with trial-specific thresholds, where each trial-tier threshold is defined as a named configuration entry in the rate limit engine with a numeric requests-per-window value
5. THE Rate_Limit_Auditor SHALL verify that data import operations are subject to rate limiting by confirming they invoke the unified engine's permit check before processing
6. THE Rate_Limit_Auditor SHALL verify that background job operations (Celery tasks, Beat schedule) are subject to rate limiting by confirming each task invokes the unified engine's permit check before executing its external API call
7. THE Rate_Limit_Auditor SHALL verify that admin tool operations are subject to rate limiting by confirming they invoke the unified engine's permit check before executing resource-consuming actions
8. THE Rate_Limit_Auditor SHALL verify that partner tool operations are subject to rate limiting by confirming they invoke the unified engine's permit check before executing resource-consuming actions
9. THE Rate_Limit_Auditor SHALL verify that internal automation paths (cron, migrations, recovery scripts) are either subject to rate limiting through the unified engine or explicitly documented as exempt in a maintained exemption registry that includes: path identifier, justification, and approver
10. IF the rate limit engine denies a request because the caller exceeds its configured threshold, THEN THE Rate_Limit_Auditor SHALL verify that the engine queues the request and retries up to a maximum of 3 attempts with exponential backoff (minimum 1 second between retries), and executes the request when capacity is available within a maximum queue duration of 60 seconds before returning a rejection
11. THE Rate_Limit_Auditor SHALL verify that no local rate limit implementation (defined as any code that tracks request counts, applies delays, or denies access based on frequency outside the unified engine module) exists outside the unified engine
12. IF a code path invokes an external API or resource-consuming operation without calling the unified rate limit engine, THEN THE Rate_Limit_Auditor SHALL flag it as a bypass unless it appears in the documented exemption registry
13. WHEN the audit is complete, THE Rate_Limit_Auditor SHALL produce a coverage report listing every endpoint and background task, with columns: Endpoint, Rate_Limited (boolean), Limit_Source (unified engine reference or exemption registry entry), Bypass_Possible (boolean), Owner (team or service name), and containing one row per auditable path with zero rows omitted

### Requirement 4: LLM Response Delivery Guarantee

**User Story:** As a platform operator, I want to guarantee that every accepted LLM task results in a response that is either delivered or recoverable, so that no generated content is silently lost.

#### Acceptance Criteria

1. THE LLM_Reliability_Monitor SHALL track every LLM task through states: CREATED, QUEUED, SENT, IN_PROGRESS, PARTIAL, COMPLETED, FAILED, RECOVERABLE, LOST
2. WHEN an LLM task is accepted, THE LLM_Reliability_Monitor SHALL persist the task record with client_id, avatar_id, operation type, and creation timestamp before sending to the provider
3. WHEN an LLM call times out (exceeds 60 seconds per attempt), THE LLM_Reliability_Monitor SHALL transition the task to FAILED with the timeout reason and retry up to a maximum of 3 attempts with exponential backoff (60 times 2 to the power of attempt seconds between retries)
4. WHEN a Celery worker crashes during LLM processing, THE LLM_Reliability_Monitor SHALL detect the orphaned task within 5 minutes via heartbeat absence and transition it to RECOVERABLE
5. WHEN an LLM provider returns a partial response before a connection is terminated, THE LLM_Reliability_Monitor SHALL persist any content received up to the disconnection point and transition the task to PARTIAL
6. WHEN duplicate task completion is detected (same task ID completed twice), THE LLM_Reliability_Monitor SHALL discard the duplicate, retain the first completion, and log the duplicate occurrence as an activity event
7. THE LLM_Reliability_Monitor SHALL maintain a Lost Response Rate metric below 0.01 percent measured over a rolling 7-day window
8. WHEN a task transitions to RECOVERABLE state, THE LLM_Reliability_Monitor SHALL automatically re-enqueue the task for retry within 60 seconds, up to the maximum of 3 total attempts across all recovery cycles
9. THE LLM_Reliability_Monitor SHALL emit an ActivityEvent for every state transition including the previous state, new state, transition reason, and timestamp
10. IF a task remains in SENT or IN_PROGRESS state for longer than 5 minutes without a heartbeat update, THEN THE LLM_Reliability_Monitor SHALL transition it to RECOVERABLE and emit an orphan detection alert as an ActivityEvent
11. IF a task has exhausted all retry attempts (3 total) and remains undelivered, THEN THE LLM_Reliability_Monitor SHALL transition it to LOST and emit an alert-level ActivityEvent containing the task ID, operation type, client_id, and failure history

### Requirement 5: User and System Flow Completeness

**User Story:** As a platform operator, I want to verify that every user and system flow reaches a defined terminal state, so that no user action results in a dead end or lost progress.

#### Acceptance Criteria

1. WHEN an audit is initiated, THE Flow_Completeness_Scanner SHALL inventory all user-facing flows: onboarding (6-step wizard), avatar creation, avatar onboarding, trial signup, client portal navigation, admin operations, partner workflow, and payment
2. WHEN the Flow_Completeness_Scanner processes a user flow, THE Flow_Completeness_Scanner SHALL verify that the flow contains at least one terminal screen displaying an explicit success indication (a confirmation message, a summary of completed action, or a redirect to the relevant dashboard)
3. WHEN the Flow_Completeness_Scanner processes a user flow, THE Flow_Completeness_Scanner SHALL verify that each error state within the flow provides a recovery path that returns the user to the last valid step or to the flow entry point without requiring the user to re-enter previously submitted data
4. WHEN the Flow_Completeness_Scanner processes a user flow, THE Flow_Completeness_Scanner SHALL verify that in-progress state is persisted to the server (database or session store) so that a full page refresh does not discard user input entered in prior completed steps
5. THE Flow_Completeness_Scanner SHALL verify that each system flow (pipeline execution, EPG build, automated posting, health check, scraping, feedback loop, discovery, karma snapshot) writes an ActivityEvent record with a terminal status of "completed" or "failed" upon finishing execution
6. IF a system flow does not have a corresponding ActivityEvent record with terminal status, THEN THE Flow_Completeness_Scanner SHALL classify the flow as broken with severity RED
7. IF a system flow has no ActivityEvent record with status "completed" within the last 48 hours while that flow is scheduled to run according to the Celery Beat schedule, THEN THE Flow_Completeness_Scanner SHALL flag it as stale
8. WHEN the audit is complete, THE Flow_Completeness_Scanner SHALL produce a Flow Inventory with columns: Flow_Name, Type (user or system), Entry_Point, Steps_Count, Terminal_State, Error_Recovery, Progress_Persisted, Observable, Last_Successful_Run

### Requirement 6: Specification Coverage Mapping

**User Story:** As a platform operator, I want to map all specifications to their implementation and test status, so that I can identify orphan specs, untested features, and hidden feature flags.

#### Acceptance Criteria

1. WHEN the audit is triggered, THE Spec_Coverage_Tracker SHALL collect all specification directories from .kiro/specs/ that contain a requirements.md file and categorize each as one of: not_read (no matching service or route file references the spec name), read (referenced in code comments or docs but no functional implementation), partially_implemented (at least one but not all acceptance criteria have corresponding code paths), implemented (all acceptance criteria have corresponding code paths), tested (all acceptance criteria have corresponding test assertions), or outdated (spec references models, routes, or services that have been renamed or deleted)
2. FOR EACH specification, THE Spec_Coverage_Tracker SHALL record: specification name (directory name under .kiro/specs/), status (one of the 6 categories from criterion 1), implementation percentage (number of acceptance criteria with corresponding code paths divided by total acceptance criteria, expressed as 0-100), test coverage percentage (number of acceptance criteria with corresponding test assertions divided by total acceptance criteria, expressed as 0-100), owner (the service file or route file most responsible for the spec's implementation, or "unassigned" if none found), and risk level (high if implementation percentage is below 30 and spec is referenced by an active route, medium if implementation percentage is between 30 and 79, low if 80 or above)
3. THE Spec_Coverage_Tracker SHALL identify orphan specifications defined as spec directories where no Python file under app/services/, app/routes/, or app/tasks/ contains an import, function, or class name that matches the spec's primary feature name
4. THE Spec_Coverage_Tracker SHALL identify dead features defined as Python modules under app/services/ or app/routes/ that are not imported by any other module and are not referenced by any specification directory name or any route registration in app/main.py
5. IF a SystemSetting entry exists whose key is not referenced in any active route handler or Celery task as a runtime gate, THEN THE Spec_Coverage_Tracker SHALL flag it as a hidden feature flag and include its key name, current value, and the list of code locations (if any) that reference it
6. THE Spec_Coverage_Tracker SHALL identify unreachable UI defined as template files under app/templates/ that are not referenced by any render_template or TemplateResponse call in app/routes/ and are not included via Jinja2 include or extends directives from a referenced template
7. WHEN all specifications have been categorized and all orphan, dead feature, hidden flag, and unreachable UI scans are complete, THE Spec_Coverage_Tracker SHALL produce a coverage matrix with columns: Specification (directory name), Status (one of the 6 categories), Implemented_Percent (integer 0-100), Tested_Percent (integer 0-100), Owner (file path or "unassigned"), Risk (high/medium/low), and a summary section listing total counts per status category and total counts of orphans, dead features, hidden flags, and unreachable templates

### Requirement 7: Technical Debt Radar

**User Story:** As a platform operator, I want a systematic scan of technical debt across reliability, performance, security, and product dimensions, so that I can prioritize remediation before production.

#### Acceptance Criteria

1. THE Debt_Radar SHALL scan for reliability debt: missing retry logic on external calls (HTTP, PRAW, LLM API), missing idempotency keys on state-mutating operations, missing observability (operations that change state without emitting an ActivityEvent), and scheduled Celery tasks without a corresponding alert threshold for late or failed execution
2. THE Debt_Radar SHALL scan for performance debt: database queries on columns used in WHERE, JOIN, or ORDER BY clauses that lack a corresponding index, N+1 query patterns in list endpoints (a loop issuing one query per item instead of a batch query), query results returned without LIMIT or pagination when the result set may exceed 100 rows, and Celery queue depth growth without backpressure (no mechanism to pause or slow producers when queue exceeds 1000 pending messages)
3. THE Debt_Radar SHALL scan for security debt: authentication bypass paths (endpoints missing require_superuser, require_platform_admin, or RBAC guards from dependencies/permissions.py), permission leakage between client scopes (queries missing client_id filtering), secrets in source code or non-encrypted configuration (API keys, passwords, tokens outside Fernet-encrypted fields or environment variables), and missing input validation on user-facing endpoints (route handlers accepting string or numeric input without Pydantic schema or length/range constraints)
4. THE Debt_Radar SHALL scan for product debt: incomplete user scenarios (flows that lack at least one of: success confirmation, error recovery path, or explicit exit action), missing user-facing error explanations (error responses that do not include a human-readable message indicating the failure reason), and UX dead ends (links or buttons whose target returns HTTP 404 or renders an empty state without guidance)
5. WHEN a debt item is identified, THE Debt_Radar SHALL assign a severity based on these criteria: RED if the item can cause data loss, security breach, or complete workflow failure in production; YELLOW if the item degrades user experience or operational efficiency but does not block core workflows, with a required remediation deadline of no more than 30 calendar days post-launch; or GREEN if the item has no user-visible impact and no security or data-integrity risk
6. WHEN a debt item is identified, THE Debt_Radar SHALL record: issue description (maximum 200 characters), category (reliability, performance, security, product), severity (RED, YELLOW, GREEN), owner (the team member responsible for the module containing the debt), estimated fix effort (S: 1-4 hours, M: 4-16 hours, L: 16-40 hours, XL: 40+ hours), risk if unresolved (specific consequence statement, maximum 200 characters), and decision (fix_before_release, defer_to_post_release, accept)
7. IF a debt item is classified as RED severity, THEN THE Debt_Radar SHALL require a decision of fix_before_release and SHALL NOT permit the decisions defer_to_post_release or accept for that item

### Requirement 8: Bypass Path Detection

**User Story:** As a platform operator, I want to identify all unexpected bypass paths in the system, so that operations cannot circumvent safety gates or rate limits through non-standard channels.

#### Acceptance Criteria

1. THE Audit_Engine SHALL identify all cron-triggered operations (Celery Beat tasks) that create or modify CommentDraft, PostDraft, or PostingEvent records and verify each operation passes through the same 9 posting safety gates (kill switch, posting_mode, frozen, health_status, phase exclusion, daily cap, proxy configured, user-agent configured, subnet consistency) as user-triggered equivalents
2. THE Audit_Engine SHALL identify all debug endpoints (routes not protected by require_superuser or require_platform_admin dependency) and verify they are either removed or protected by require_superuser in production configuration
3. THE Audit_Engine SHALL identify all internal import scripts (seed.py, migration data scripts, any Python file in the project root matching _*.py) and verify they invoke the same Pydantic schema validation as the corresponding API routes before writing to the database
4. THE Audit_Engine SHALL identify all manual admin actions (create, update, delete operations on Client, Avatar, User, SystemSetting entities via admin routes) and verify each produces an AuditLog entry containing user_id, action, entity_type, entity_id, and created_at
5. THE Audit_Engine SHALL identify all feature flags (SystemSetting entries where group equals app and key contains enabled or disabled) and verify each has a non-empty description field identifying the owning team and a value of either true or false
6. THE Audit_Engine SHALL identify all Alembic migration scripts containing UPDATE or DELETE SQL statements against existing data and verify each script includes a corresponding downgrade function that reverses the data modification
7. THE Audit_Engine SHALL identify all batch job operations (Celery tasks that process more than one record per invocation) that create or approve drafts and verify they invoke the same 9 posting safety gates per record as individual posting operations
8. IF a recovery script or migration creates a record that references a non-existent foreign key (client_id, avatar_id, or user_id not present in the referenced table), THEN THE Audit_Engine SHALL flag it as an orphaned record with severity RED
9. WHEN a bypass path is identified without a corresponding entry in the SystemSetting table with key pattern bypass_exemption:{path_identifier} and a non-empty description, THE Audit_Engine SHALL classify it as a potential leak with severity RED
10. THE Audit_Engine SHALL produce an audit report listing each identified bypass path with its classification (compliant, exempted, or RED leak), the specific gate or rule it was verified against, and a timestamp of the last verification within the previous 24 hours

### Requirement 9: Production Dashboard

**User Story:** As a platform operator, I want a single admin screen showing the readiness status of all audit findings, so that I can make an informed GO/NO-GO decision.

#### Acceptance Criteria

1. THE Production_Dashboard SHALL display a single unified view accessible at /admin/production-readiness with traffic-light indicators: RED (blocker that must fix before launch), YELLOW (known risk with documented mitigation accepted by an owner or partner role), GREEN (resolved or no action needed)
2. THE Production_Dashboard SHALL display for each finding: Issue title (maximum 120 characters), Severity (RED/YELLOW/GREEN), Owner (assigned user), ETA for resolution (date in YYYY-MM-DD format or N/A if accepted), Risk description (maximum 500 characters), and Decision (fix/defer/accept)
3. THE Production_Dashboard SHALL aggregate findings from all audit blocks: Data Leakage, Credit Integrity, Rate Limit Coverage, LLM Reliability, Flow Completeness, Spec Coverage, Technical Debt, Bypass Detection
4. THE Production_Dashboard SHALL calculate an overall GO/NO-GO recommendation: any RED finding whose Decision is not set to accept with an exemption_reason and exemption_granted_by (owner or partner role) results in NO-GO; otherwise GO
5. THE Production_Dashboard SHALL display a summary header: total RED count, total YELLOW count, total GREEN count, overall status (GO or NO-GO)
6. THE Production_Dashboard SHALL provide filtering by severity level and by audit block, retaining the selected filter state in the URL query parameters
7. WHEN a finding severity is updated or a fix is verified, THE Production_Dashboard SHALL reflect the change via HTMX partial update without full page refresh within 2 seconds of the server-side change being persisted
8. THE Production_Dashboard SHALL display a first-week incident probability estimate as a percentage (0-100%) calculated from: (count of RED findings times 15) + (count of YELLOW findings times 5), capped at 100%
9. IF no findings exist for any audit block, THEN THE Production_Dashboard SHALL display that block with a GREEN indicator and the label "No findings"
10. IF the operator sets a RED finding Decision to accept, THEN THE Production_Dashboard SHALL require an exemption_reason (minimum 10 characters) and record the exemption_granted_by user before updating the GO/NO-GO calculation

### Requirement 10: Audit Report Generation

**User Story:** As a platform operator, I want the audit to produce a unified report document, so that I can share the production readiness status with stakeholders.

#### Acceptance Criteria

1. WHEN all audit blocks have completed (all 8 blocks report a terminal status of completed or failed), THE Audit_Engine SHALL generate a unified risk report as a Markdown document saved to the project root as AUDIT_REPORT_{date}.md
2. THE Audit_Engine SHALL include in the report: an executive summary section containing the overall GO/NO-GO decision derived from the Production Dashboard calculation (GO if zero unexempted RED findings, NO-GO otherwise) and a supporting rationale paragraph listing the count of findings per severity
3. THE Audit_Engine SHALL include in the report: a Production Blockers section listing all RED findings with columns: Issue, Owner, ETA, and Risk
4. THE Audit_Engine SHALL include in the report: a Required Fixes Before Release section listing all items with decision = fix_before_release
5. THE Audit_Engine SHALL include in the report: a Deferred to Post-Release section listing all items with decision = defer_to_post_release, each with its risk acceptance justification
6. THE Audit_Engine SHALL include in the report: a first-week incident probability estimate as a percentage calculated using the same formula as the Production Dashboard (RED times 15 + YELLOW times 5, capped at 100%)
7. THE Audit_Engine SHALL include in the report: the Flow Inventory table from the Flow Completeness audit
8. THE Audit_Engine SHALL include in the report: the integration map table from the Data Leakage audit
9. THE Audit_Engine SHALL include in the report: the rate limit coverage report table from the Rate Limit audit
10. THE Audit_Engine SHALL include in the report: the state transition diagram (as Mermaid syntax) from the Credit Integrity audit
11. THE Audit_Engine SHALL include in the report: the bypass path inventory with classification and exemption status
12. IF any audit block has status failed (unable to complete), THEN THE Audit_Engine SHALL include a Partial Audit Warning section at the top of the report identifying which blocks failed and why

### Requirement 11: Observability Rule Enforcement

**User Story:** As a platform operator, I want to enforce strict observability rules so that production systems have guaranteed visibility into all operations.

#### Acceptance Criteria

1. IF a Celery task or API request handler completes execution without emitting at least one ActivityEvent record, structured log entry (Python logging at INFO level or above with task/request context), or metric increment, THEN THE Audit_Engine SHALL classify that execution as broken with severity RED
2. IF a Celery task or API request handler does not produce a terminal outcome record (an ActivityEvent with event_type containing complete, failed, or skipped, OR a status column update on the target entity, OR a structured log entry at INFO level indicating final disposition) within 300 seconds of invocation, THEN THE Audit_Engine SHALL classify the execution as incomplete with severity RED
3. IF a rate limit bypass path exists without a corresponding entry in the system_settings table with key prefix rate_limit_exemption:, THEN THE Audit_Engine SHALL classify it as a leak with severity RED
4. THE Audit_Engine SHALL verify that every Celery Beat scheduled task emits at least one ActivityEvent or structured log entry per scheduled execution cycle, checked within a grace window of 2 times the task's configured interval
5. THE Audit_Engine SHALL verify that every API endpoint that creates, updates, or deletes a database-persisted entity (any SQLAlchemy model exposed via routes) produces an AuditLog entry containing at minimum: action, entity_type, entity_id, and user_id (or null for system-initiated)
6. WHEN THE Audit_Engine classifies any execution as severity RED, THE Audit_Engine SHALL emit an ActivityEvent with event_type audit_violation_detected and metadata containing the violation category, affected task or endpoint name, and timestamp of detection
