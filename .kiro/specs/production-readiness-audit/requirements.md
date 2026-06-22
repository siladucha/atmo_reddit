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

1. WHEN an audit is initiated, THE Data_Path_Analyzer SHALL trace every external integration path from source fetch through queue, processing, storage, LLM context, to output
2. THE Data_Path_Analyzer SHALL verify that raw API responses from Reddit are not stored in full beyond the retention policy of 90 days
3. THE Data_Path_Analyzer SHALL verify that authentication tokens (Reddit OAuth, LLM API keys, proxy credentials) are not transmitted to any external service other than their intended provider
4. THE Data_Path_Analyzer SHALL verify that no private user data (passwords, email addresses, IP addresses) appears in application logs
5. THE Data_Path_Analyzer SHALL verify that raw scraped content does not enter embedding vectors without sanitization
6. THE Data_Path_Analyzer SHALL verify that cached external data is purged according to the configured retention policy
7. THE Data_Path_Analyzer SHALL verify that no internal database IDs are exposed in user-facing output or API responses to non-admin roles
8. THE Data_Path_Analyzer SHALL verify that LLM prompts do not contain credentials, internal IDs, or data from other clients (context isolation check)
9. WHEN the trace is complete, THE Data_Path_Analyzer SHALL produce an integration map table with columns: Integration, Data_Read, Data_Stored, Retention_Period, Access_Roles

### Requirement 2: Credit and Usage Accounting Integrity

**User Story:** As a platform operator, I want to verify that credit/usage accounting is consistent across all state transitions, so that no operation is charged incorrectly or executed without accounting.

#### Acceptance Criteria

1. THE Credit_Integrity_Checker SHALL verify that the usage accounting path follows the sequence: Request, Reservation, Execution, Completion, Charge
2. THE Credit_Integrity_Checker SHALL verify that no single operation can be charged more than once for the same execution
3. THE Credit_Integrity_Checker SHALL verify that no operation executes and produces a result without recording a corresponding usage entry in AIUsageLog
4. THE Credit_Integrity_Checker SHALL verify that no charge is recorded when the operation did not produce a deliverable result
5. THE Credit_Integrity_Checker SHALL verify that cancelled or timed-out operations with prior reservations are compensated (reservation released)
6. WHEN a retry occurs after a transient failure, THE Credit_Integrity_Checker SHALL verify that the retry does not create a duplicate charge
7. WHEN a Celery worker restarts during task execution, THE Credit_Integrity_Checker SHALL verify that the in-progress operation is either completed or compensated
8. WHEN duplicate message delivery occurs, THE Credit_Integrity_Checker SHALL verify that the duplicate does not result in double execution
9. WHEN the audit is complete, THE Credit_Integrity_Checker SHALL produce a state transition diagram documenting all valid transitions and their accounting effects

### Requirement 3: Unified Rate Limit Coverage

**User Story:** As a platform operator, I want to confirm that all operations pass through a single rate-limiting engine, so that no operation can bypass resource controls.

#### Acceptance Criteria

1. THE Rate_Limit_Auditor SHALL verify that all Reddit API calls route through the unified rate limit engine
2. THE Rate_Limit_Auditor SHALL verify that all LLM API calls (scoring, generation, persona selection, editing) route through the unified rate limit engine
3. THE Rate_Limit_Auditor SHALL verify that all avatar execution operations (posting, commenting) route through the unified rate limit engine
4. THE Rate_Limit_Auditor SHALL verify that trial user operations are subject to rate limiting with trial-specific thresholds
5. THE Rate_Limit_Auditor SHALL verify that data import operations are subject to rate limiting
6. THE Rate_Limit_Auditor SHALL verify that background job operations (Celery tasks, Beat schedule) are subject to rate limiting
7. THE Rate_Limit_Auditor SHALL verify that admin tool operations are subject to rate limiting
8. THE Rate_Limit_Auditor SHALL verify that partner tool operations are subject to rate limiting
9. THE Rate_Limit_Auditor SHALL verify that internal automation paths (cron, migrations, recovery scripts) are either subject to rate limiting or explicitly documented as exempt with justification
10. THE Rate_Limit_Auditor SHALL verify that the rate limit engine follows the pattern: DENY when over limit, queue the request, retry on availability, execute when permitted
11. THE Rate_Limit_Auditor SHALL verify that no local rate limit implementation exists outside the unified engine
12. THE Rate_Limit_Auditor SHALL verify that no bypass path exists that skips the rate limit check without documented exemption
13. WHEN the audit is complete, THE Rate_Limit_Auditor SHALL produce a coverage report with columns: Endpoint, Rate_Limited, Limit_Source, Bypass_Possible, Owner

### Requirement 4: LLM Response Delivery Guarantee

**User Story:** As a platform operator, I want to guarantee that every accepted LLM task results in a response that is either delivered or recoverable, so that no generated content is silently lost.

#### Acceptance Criteria

1. THE LLM_Reliability_Monitor SHALL track every LLM task through states: CREATED, QUEUED, SENT, IN_PROGRESS, PARTIAL, COMPLETED, FAILED, RECOVERABLE, LOST
2. WHEN an LLM task is accepted, THE LLM_Reliability_Monitor SHALL persist the task record before sending to the provider
3. WHEN an LLM call times out (exceeds 60 times 2 to the power of attempt seconds), THE LLM_Reliability_Monitor SHALL transition the task to FAILED with the timeout reason and enable retry
4. WHEN a Celery worker crashes during LLM processing, THE LLM_Reliability_Monitor SHALL detect the orphaned task within 5 minutes via heartbeat absence and transition it to RECOVERABLE
5. WHEN a streaming response is interrupted, THE LLM_Reliability_Monitor SHALL persist any partial content received up to the interruption point
6. WHEN duplicate task completion is detected (same task ID completed twice), THE LLM_Reliability_Monitor SHALL discard the duplicate and retain the first completion
7. THE LLM_Reliability_Monitor SHALL maintain a Lost Response Rate metric below 0.01 percent measured over a rolling 7-day window
8. THE LLM_Reliability_Monitor SHALL provide a mechanism to resume or re-trigger generation for tasks in RECOVERABLE state
9. THE LLM_Reliability_Monitor SHALL emit an activity event for every state transition enabling full traceability
10. IF a task remains in SENT or IN_PROGRESS state for longer than 5 minutes without a heartbeat update, THEN THE LLM_Reliability_Monitor SHALL transition it to RECOVERABLE and trigger an orphan detection alert

### Requirement 5: User and System Flow Completeness

**User Story:** As a platform operator, I want to verify that every user and system flow reaches a defined terminal state, so that no user action results in a dead end or lost progress.

#### Acceptance Criteria

1. WHEN an audit is initiated, THE Flow_Completeness_Scanner SHALL inventory all user-facing flows: onboarding (6-step wizard), avatar creation, avatar onboarding, trial signup, client portal navigation, admin operations, partner workflow, and payment
2. FOR EACH identified user flow, THE Flow_Completeness_Scanner SHALL verify the existence of a success terminal screen
3. FOR EACH identified user flow, THE Flow_Completeness_Scanner SHALL verify the existence of an error recovery path that returns the user to a functional state
4. FOR EACH identified user flow, THE Flow_Completeness_Scanner SHALL verify that in-progress state is persisted so that page refresh or navigation away does not lose user input
5. THE Flow_Completeness_Scanner SHALL verify that each system flow (pipeline execution, EPG build, automated posting, health check, scraping, feedback loop, discovery, karma snapshot) emits an observable completion event
6. IF a system flow does not emit a completion event, THEN THE Flow_Completeness_Scanner SHALL classify the flow as broken with severity RED
7. IF a system flow has no proof of successful completion in the last 48 hours while scheduled to run, THEN THE Flow_Completeness_Scanner SHALL flag it as stale
8. WHEN the audit is complete, THE Flow_Completeness_Scanner SHALL produce a Flow Inventory with columns: Flow_Name, Type (user or system), Entry_Point, Steps_Count, Terminal_State, Error_Recovery, Progress_Persisted, Observable, Last_Successful_Run

### Requirement 6: Specification Coverage Mapping

**User Story:** As a platform operator, I want to map all specifications to their implementation and test status, so that I can identify orphan specs, untested features, and hidden feature flags.

#### Acceptance Criteria

1. THE Spec_Coverage_Tracker SHALL collect all specifications from the .kiro/specs/ directory and categorize each as: not_read, read, partially_implemented, implemented, tested, or outdated
2. FOR EACH specification, THE Spec_Coverage_Tracker SHALL record: specification name, status, implementation percentage, test coverage percentage, owner, and risk level
3. THE Spec_Coverage_Tracker SHALL identify orphan specifications (specs with no corresponding implementation code)
4. THE Spec_Coverage_Tracker SHALL identify dead features (implemented code with no corresponding active specification or route registration)
5. THE Spec_Coverage_Tracker SHALL identify hidden feature flags (SystemSetting entries that gate unreleased or incomplete functionality)
6. THE Spec_Coverage_Tracker SHALL identify unreachable UI (templates or partials not linked from any navigation path or route)
7. WHEN the audit is complete, THE Spec_Coverage_Tracker SHALL produce a coverage matrix with columns: Specification, Status, Implemented_Percent, Tested_Percent, Owner, Risk

### Requirement 7: Technical Debt Radar

**User Story:** As a platform operator, I want a systematic scan of technical debt across reliability, performance, security, and product dimensions, so that I can prioritize remediation before production.

#### Acceptance Criteria

1. THE Debt_Radar SHALL scan for reliability debt: missing retry logic on external calls, missing idempotency keys on state-mutating operations, missing observability (no activity events emitted), and missing alert thresholds for scheduled tasks
2. THE Debt_Radar SHALL scan for performance debt: database queries without appropriate indexes, N+1 query patterns in list endpoints, unbounded query results (missing pagination or LIMIT), and Celery queue depth growth without backpressure
3. THE Debt_Radar SHALL scan for security debt: authentication bypass paths (endpoints missing require_superuser or RBAC guards), permission leakage between client scopes, secrets in source code or non-encrypted configuration, and missing input validation on user-facing endpoints
4. THE Debt_Radar SHALL scan for product debt: incomplete user scenarios (flows without terminal states), missing user-facing error explanations, and UX dead ends (links or buttons leading to 404 or empty states)
5. FOR EACH identified debt item, THE Debt_Radar SHALL assign a severity: RED (production blocker), YELLOW (acceptable for initial launch with fix timeline), or GREEN (acceptable indefinitely)
6. FOR EACH identified debt item, THE Debt_Radar SHALL record: issue description, category (reliability, performance, security, product), severity, owner, estimated fix effort, risk if unresolved, and decision (fix_before_release, defer_to_post_release, accept)

### Requirement 8: Bypass Path Detection

**User Story:** As a platform operator, I want to identify all unexpected bypass paths in the system, so that operations cannot circumvent safety gates or rate limits through non-standard channels.

#### Acceptance Criteria

1. THE Audit_Engine SHALL identify all cron-triggered operations (Celery Beat tasks) and verify they pass through the same safety gates as user-triggered equivalents
2. THE Audit_Engine SHALL identify all debug endpoints and verify they are disabled or access-restricted (require_superuser) in production configuration
3. THE Audit_Engine SHALL identify all internal import scripts (seed.py, migration data scripts) and verify they respect data validation rules
4. THE Audit_Engine SHALL identify all manual admin actions and verify each produces an audit log entry
5. THE Audit_Engine SHALL identify all feature flags (SystemSetting entries) and verify each has a documented owner and intended lifecycle
6. THE Audit_Engine SHALL identify all Alembic migration scripts that modify existing data (UPDATE/DELETE) and verify they are idempotent and reversible
7. THE Audit_Engine SHALL identify all batch job operations and verify they respect the same posting safety gates as individual posting operations
8. THE Audit_Engine SHALL identify all recovery scripts and verify they do not create orphaned records or inconsistent state
9. WHEN a bypass path is identified without a documented exemption, THE Audit_Engine SHALL classify it as a potential leak with severity RED

### Requirement 9: Production Dashboard

**User Story:** As a platform operator, I want a single admin screen showing the readiness status of all audit findings, so that I can make an informed GO/NO-GO decision.

#### Acceptance Criteria

1. THE Production_Dashboard SHALL display a single unified view accessible at /admin/production-readiness with traffic-light indicators: RED (blocker), YELLOW (temporarily acceptable), GREEN (ready)
2. THE Production_Dashboard SHALL display for each finding: Issue title, Severity, Owner, ETA for resolution, Risk description, and Decision (fix/defer/accept)
3. THE Production_Dashboard SHALL aggregate findings from all audit blocks: Data Leakage, Credit Integrity, Rate Limit Coverage, LLM Reliability, Flow Completeness, Spec Coverage, Technical Debt, Bypass Detection
4. THE Production_Dashboard SHALL calculate an overall GO/NO-GO recommendation: any RED finding that is not resolved or exempted results in NO-GO
5. THE Production_Dashboard SHALL display a summary header: total RED count, total YELLOW count, total GREEN count, overall status
6. THE Production_Dashboard SHALL provide filtering by severity level and by audit block
7. WHEN a finding severity is updated or a fix is verified, THE Production_Dashboard SHALL reflect the change via HTMX partial update without full page refresh
8. THE Production_Dashboard SHALL display a first-week incident probability estimate based on the count and severity distribution of unresolved findings

### Requirement 10: Audit Report Generation

**User Story:** As a platform operator, I want the audit to produce a unified report document, so that I can share the production readiness status with stakeholders.

#### Acceptance Criteria

1. WHEN all audit blocks have completed, THE Audit_Engine SHALL generate a unified risk report as a Markdown document
2. THE Audit_Engine SHALL include in the report: an executive summary with overall GO/NO-GO decision and supporting rationale
3. THE Audit_Engine SHALL include in the report: a list of all production blockers (RED items) with owner and ETA
4. THE Audit_Engine SHALL include in the report: a list of required fixes before release
5. THE Audit_Engine SHALL include in the report: a list of items explicitly deferred to post-release with risk acceptance justification
6. THE Audit_Engine SHALL include in the report: a first-week incident probability estimate
7. THE Audit_Engine SHALL include in the report: the status of each critical flow from the Flow Inventory
8. THE Audit_Engine SHALL include in the report: the integration map table from the Data Leakage audit
9. THE Audit_Engine SHALL include in the report: the rate limit coverage report table
10. THE Audit_Engine SHALL include in the report: the state transition diagram (as text or Mermaid) from the Credit Integrity audit
11. THE Audit_Engine SHALL include in the report: the bypass path inventory with exemption status

### Requirement 11: Observability Rule Enforcement

**User Story:** As a platform operator, I want to enforce strict observability rules so that production systems have guaranteed visibility into all operations.

#### Acceptance Criteria

1. THE Audit_Engine SHALL apply the rule: IF a flow does not emit observable events (ActivityEvent records, structured log entries, or metrics), THEN THE Audit_Engine SHALL classify the flow as broken with severity RED
2. THE Audit_Engine SHALL apply the rule: IF a flow has no proof of completion (no terminal state event, no status column update, no completion log), THEN THE Audit_Engine SHALL classify the flow as incomplete with severity RED
3. THE Audit_Engine SHALL apply the rule: IF a rate limit bypass path exists without documented exemption, THEN THE Audit_Engine SHALL classify it as a leak with severity RED
4. THE Audit_Engine SHALL verify that every Celery Beat scheduled task emits at least one ActivityEvent or structured log entry per execution cycle
5. THE Audit_Engine SHALL verify that every API endpoint that creates, updates, or deletes a resource produces an AuditLog entry
