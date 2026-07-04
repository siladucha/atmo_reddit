# Implementation Plan: Production Readiness Audit

## Overview

Implement an automated audit engine with 8 modular audit blocks, a PostgreSQL-backed findings store, an HTMX admin dashboard with traffic-light GO/NO-GO indicators, and a Markdown report generator. The system integrates as a new service layer, models, admin routes, Celery tasks, and templates into the existing RAMP platform.

## Tasks

- [x] 1. Database models and migration
  - [x] 1.1 Create audit models file with AuditRun, AuditFinding, and LLMTaskRecord
    - Create `app/models/audit_finding.py` with all three SQLAlchemy models
    - Include all columns, indexes, and check constraints as specified in design
    - AuditRun: id, status, triggered_by, started_at, completed_at, go_no_go, incident_probability, block_statuses (JSONB), report_path
    - AuditFinding: id, run_id (FK), block, title, severity, category, risk_description, owner, effort, risk_if_unresolved, decision, requirement_ref, data_path, eta, exemption_reason, exemption_granted_by (FK users.id), created_at, updated_at
    - LLMTaskRecord: id, celery_task_id (unique), client_id (FK), avatar_id (FK), operation, state, previous_state, attempt_count, max_attempts, partial_content, failure_history (JSONB), last_heartbeat_at, created_at, completed_at
    - Add composite indexes: ix_audit_findings_run_block, ix_audit_findings_severity, ix_llm_task_records_state, ix_llm_task_records_client_created
    - Add CheckConstraint ck_red_requires_exemption_or_fix
    - Register models in `app/models/__init__.py`
    - _Requirements: 2.1, 4.1, 9.2, 9.4, 9.10_

  - [x] 1.2 Create Alembic migration for audit tables
    - Generate migration with `alembic revision --autogenerate -m "add_audit_run_finding_llm_task_record"`
    - Verify migration creates audit_runs, audit_findings, llm_task_records tables
    - Verify all indexes and constraints are present
    - Include downgrade function
    - _Requirements: 8.6_

- [x] 2. Audit block base interface and shared types
  - [x] 2.1 Create AuditBlock ABC and enums in base.py
    - Create `app/services/audit/base.py` with:
    - Severity enum (red, yellow, green)
    - Decision enum (fix_before_release, defer_to_post_release, accept)
    - FixEffort enum (S, M, L, XL)
    - AuditBlockName enum (all 8 blocks)
    - BlockStatus enum (pending, running, completed, failed)
    - FindingInput dataclass with all fields from design
    - AuditBlock ABC with `name` property and `run()` async method
    - _Requirements: 7.5, 7.6, 9.2_

  - [ ]* 2.2 Write property tests for severity and decision enums
    - **Property 22: Debt severity assignment**
    - **Property 24: RED severity decision constraint**
    - **Validates: Requirements 7.5, 7.7, 9.10**

- [x] 3. AuditEngine orchestrator
  - [x] 3.1 Create AuditEngine orchestrator in `app/services/audit/__init__.py`
    - Implement `run_full_audit()`: creates AuditRun, dispatches all 8 blocks, persists findings, generates report
    - Implement `run_single_block()`: runs one block by name for re-checks
    - Implement `calculate_go_no_go()`: True if no unexempted RED findings
    - Implement `calculate_incident_probability()`: min(100, red_count * 15 + yellow_count * 5)
    - Handle concurrent audit lock (Redis distributed lock, TTL=30min, 409 on conflict)
    - Catch block exceptions — set block status to failed, continue others
    - Emit ActivityEvent on audit completion
    - _Requirements: 9.4, 9.8, 10.1, 10.2, 11.6_

  - [ ]* 3.2 Write property tests for GO/NO-GO and incident probability
    - **Property 27: GO/NO-GO calculation correctness**
    - **Property 28: Incident probability formula**
    - **Validates: Requirements 9.4, 9.8**

  - [ ]* 3.3 Write property test for RED violation event emission
    - **Property 33: RED violation event emission**
    - **Validates: Requirements 11.6**

- [x] 4. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Audit Block 1 — DataPathAnalyzer
  - [x] 5.1 Implement DataPathAnalyzer in `app/services/audit/data_path_analyzer.py`
    - Scan `app/services/` for external HTTP calls (httpx, PRAW, LiteLLM)
    - Query reddit_threads for records older than 90 days with body > 500 chars
    - Scan log configs and activity_events for PII patterns (emails, IPs, tokens)
    - Inspect Redis keys with TTL > 24h for external data patterns
    - Check route handlers for UUID exposure in non-admin contexts
    - Sample LLM prompt assembly code for multi-client data inclusion
    - Produce integration map table + findings
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11_

  - [ ]* 5.2 Write property tests for DataPathAnalyzer
    - **Property 1: Data retention violation detection**
    - **Property 2: PII detection in log entries**
    - **Property 3: Content sanitization removes prohibited patterns**
    - **Property 4: LLM prompt context isolation**
    - **Property 5: Violation severity classification**
    - **Validates: Requirements 1.2, 1.4, 1.5, 1.8, 1.10**

- [x] 6. Audit Block 2 — CreditIntegrityChecker
  - [x] 6.1 Implement CreditIntegrityChecker in `app/services/audit/credit_integrity.py`
    - Query Celery tasks that invoke LLM calls
    - Verify matching AIUsageLog entry within 5s of task completion
    - Detect duplicates: same (client_id, avatar_id, thread_id, operation) within 60s
    - Verify failed calls (output_tokens=0) have cost_usd=0
    - Identify orphaned executions (tasks without usage entry)
    - Count retry sequences, verify only successful attempt recorded
    - Produce reconciliation report + findings
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9_

  - [ ]* 6.2 Write property tests for CreditIntegrityChecker
    - **Property 6: Accounting sequence validity**
    - **Property 7: Duplicate usage detection within time window**
    - **Property 8: Task-to-usage reconciliation**
    - **Property 9: Failed calls produce zero cost**
    - **Property 10: Retry deduplication**
    - **Property 11: Task ID deduplication**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.6, 2.8**

- [x] 7. Audit Block 3 — RateLimitAuditor
  - [x] 7.1 Implement RateLimitAuditor in `app/services/audit/rate_limit_auditor.py`
    - Parse all files in `app/services/`, `app/tasks/`, `app/routes/` using AST
    - Identify external API call sites (PRAW, httpx, LiteLLM)
    - Check if `is_allowed()` or rate limiter invocation precedes each call in AST
    - Scan for local rate limiting patterns outside `rate_limiter.py`
    - Cross-reference with exemption registry (SystemSetting keys with `rate_limit_exemption:` prefix)
    - Produce coverage report table with one row per auditable path
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13_

  - [ ]* 7.2 Write property test for bypass path flagging
    - **Property 12: Bypass path flagging**
    - **Validates: Requirements 3.12**

- [x] 8. Audit Block 4 — LLMReliabilityMonitor
  - [x] 8.1 Implement LLMReliabilityMonitor in `app/services/audit/llm_reliability.py`
    - Query LLMTaskRecord for tasks in non-terminal states older than 5 min
    - Calculate Lost Response Rate over rolling 7 days
    - Verify state transition integrity (only valid transitions)
    - Check for duplicate completions (same task_id completed twice)
    - Verify all transitions have corresponding ActivityEvent
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11_

  - [ ]* 8.2 Write property tests for LLMReliabilityMonitor
    - **Property 13: LLM task state machine validity**
    - **Property 14: Task persistence ordering**
    - **Property 15: Timeout retry with exponential backoff**
    - **Property 16: Duplicate completion idempotence**
    - **Property 17: State transition observability**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.6, 4.9, 4.11**

- [ ] 9. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Audit Block 5 — FlowCompletenessScanner
  - [ ] 10.1 Implement FlowCompletenessScanner in `app/services/audit/flow_completeness.py`
    - Inventory user flows by scanning route handlers for multi-step patterns
    - Check templates for success indicators (confirmation messages, redirects)
    - Check for error recovery paths (try/except with user-facing responses)
    - Query activity_events for system flows, verify terminal status records
    - Cross-reference Celery Beat schedule with last successful ActivityEvent per flow
    - Produce Flow Inventory table + findings
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_

  - [ ]* 10.2 Write property tests for FlowCompletenessScanner
    - **Property 18: System flow observability invariant**
    - **Property 19: Stale flow detection**
    - **Validates: Requirements 5.5, 5.6, 5.7**

- [ ] 11. Audit Block 6 — SpecCoverageTracker
  - [ ] 11.1 Implement SpecCoverageTracker in `app/services/audit/spec_coverage.py`
    - List all directories under `.kiro/specs/` with `requirements.md`
    - Extract acceptance criteria from Markdown numbered lists
    - Search `app/services/`, `app/routes/`, `app/tasks/` for references matching spec feature name
    - Determine implementation level (not_read → tested) based on reference depth
    - Scan for orphan specs, dead features, hidden flags, unreachable templates
    - Produce coverage matrix + findings
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [ ]* 11.2 Write property tests for SpecCoverageTracker
    - **Property 20: Spec categorization correctness**
    - **Property 21: Spec risk level calculation**
    - **Validates: Requirements 6.1, 6.2**

- [ ] 12. Audit Block 7 — DebtRadar
  - [ ] 12.1 Implement DebtRadar in `app/services/audit/debt_radar.py`
    - Scan for reliability debt: missing retry, missing idempotency, missing ActivityEvent, missing alert thresholds
    - Scan for performance debt: missing indexes, N+1 patterns, unbounded queries, queue backpressure
    - Scan for security debt: missing auth guards, permission leakage, secrets in source, missing validation
    - Scan for product debt: incomplete scenarios, missing error messages, UX dead ends
    - Assign severity per design criteria (RED/YELLOW/GREEN)
    - Record all required fields per finding
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

  - [ ]* 12.2 Write property tests for DebtRadar
    - **Property 22: Debt severity assignment**
    - **Property 23: Debt item field completeness**
    - **Validates: Requirements 7.5, 7.6**

- [ ] 13. Audit Block 8 — BypassDetector
  - [ ] 13.1 Implement BypassDetector in `app/services/audit/bypass_detector.py`
    - Identify Celery Beat tasks that modify CommentDraft/PostDraft/PostingEvent
    - Verify each invokes all 9 posting safety gates from `posting_safety.py`
    - Scan routes for missing `require_superuser`/`require_platform_admin` dependencies
    - Check `_*.py` scripts in project root for direct DB writes without Pydantic validation
    - Verify admin CRUD routes produce AuditLog entries
    - Check feature flags for valid description + boolean value
    - Scan Alembic scripts for UPDATE/DELETE without downgrade functions
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10_

  - [ ]* 13.2 Write property tests for BypassDetector
    - **Property 25: Feature flag validity invariant**
    - **Property 26: Bypass without exemption is RED**
    - **Validates: Requirements 8.5, 8.9**

- [ ] 14. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 15. Observability rules enforcement
  - [ ] 15.1 Implement observability rules in `app/services/audit/observability_rules.py`
    - Verify Celery tasks emit at least one observability signal (ActivityEvent, log, metric)
    - Verify API request handlers emit at least one observability signal
    - Verify terminal outcome records within 300s timeout
    - Verify Celery Beat tasks emit signals within 2× scheduled interval
    - Verify CUD operations produce AuditLog entries
    - Emit ActivityEvent with type `audit_violation_detected` for RED violations
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [ ]* 15.2 Write property tests for observability rules
    - **Property 30: CUD operation audit trail**
    - **Property 31: Observability enforcement — no silent execution**
    - **Property 32: Terminal outcome timeout**
    - **Validates: Requirements 11.1, 11.2, 8.4, 11.5**

- [ ] 16. Report generator
  - [ ] 16.1 Implement ReportGenerator in `app/services/audit/report_generator.py`
    - Generate Markdown report with sections:
    - Executive Summary (GO/NO-GO + rationale)
    - Production Blockers (RED findings)
    - Required Fixes Before Release (decision=fix_before_release)
    - Deferred to Post-Release (decision=defer_to_post_release)
    - Incident Probability Estimate
    - Flow Inventory Table
    - Integration Map Table
    - Rate Limit Coverage Table
    - State Transition Diagram (Mermaid)
    - Bypass Path Inventory
    - Partial Audit Warning (if any block failed)
    - Save to project root as `AUDIT_REPORT_{date}.md`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 10.10, 10.11, 10.12_

  - [ ]* 16.2 Write unit tests for report generator
    - Test report structure and section ordering
    - Test GO vs NO-GO report variations
    - Test partial audit warning inclusion
    - _Requirements: 10.1, 10.2, 10.12_

- [ ] 17. Admin routes and dashboard
  - [ ] 17.1 Create admin routes in `app/routes/admin_audit.py`
    - `GET /admin/production-readiness` — main dashboard page
    - `POST /admin/production-readiness/run` — trigger full audit
    - `POST /admin/production-readiness/run/{block_name}` — trigger single block
    - `GET /admin/production-readiness/findings` — HTMX partial: findings table (filterable by severity, block)
    - `GET /admin/production-readiness/summary` — HTMX partial: summary header
    - `PUT /admin/production-readiness/findings/{id}` — update finding (decision, severity, owner, ETA)
    - `POST /admin/production-readiness/findings/{id}/accept` — accept RED finding (requires exemption)
    - `GET /admin/production-readiness/report/{run_id}` — download generated report
    - All routes use `require_superuser` dependency
    - Register router in `app/main.py`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.10_

  - [ ]* 17.2 Write property test for RED acceptance validation
    - **Property 29: RED acceptance validation**
    - **Validates: Requirements 9.10**

- [ ] 18. Dashboard templates
  - [ ] 18.1 Create dashboard templates
    - Create `app/templates/admin_production_readiness.html` (extends `admin_base.html`)
    - Layout: summary header (GO/NO-GO, incident probability, severity counts), filter buttons, block sections with findings
    - Dark theme with traffic-light colors (RED: bg-red-900/30, YELLOW: bg-yellow-900/30, GREEN: bg-green-900/30)
    - "Run Audit" button with loading indicator
    - Create `app/templates/partials/audit_findings_table.html` — filterable findings list with decision dropdowns
    - Create `app/templates/partials/audit_summary_header.html` — GO/NO-GO badge, counts, incident probability
    - Create `app/templates/partials/audit_block_status.html` — per-block status card
    - HTMX interactions: filter triggers hx-get, decision dropdown triggers hx-put, accept button opens modal
    - Summary header auto-refreshes via `hx-trigger="every 5s"` during active run
    - _Requirements: 9.1, 9.2, 9.5, 9.6, 9.7, 9.8, 9.9_

- [ ] 19. Celery task integration
  - [ ] 19.1 Create Celery audit task in `app/tasks/audit.py`
    - `run_audit_task`: Celery task with bind=True, max_retries=1, countdown=60
    - Accepts optional `block_name` parameter for single-block runs
    - Instantiates all 8 block runners and AuditEngine
    - Executes audit via AuditEngine.run_full_audit() or run_single_block()
    - Handles task failure with retry
    - Register task in Celery worker configuration
    - _Requirements: 10.1_

- [ ] 20. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 21. Integration wiring and test setup
  - [ ] 21.1 Wire all components together and create test infrastructure
    - Create `tests/test_audit/__init__.py`
    - Create `tests/test_audit/test_engine.py` — orchestrator integration tests (concurrent lock, block failure isolation, full audit run)
    - Create `tests/test_audit/test_properties.py` — all 33 property-based tests using Hypothesis
    - Configure Hypothesis settings (min 100 examples per test)
    - Create test fixtures: mock codebase directory, test DB records, Redis test keys
    - Wire admin audit routes into sidebar navigation in `admin_base.html`
    - Add "Production Readiness" link to admin sidebar
    - _Requirements: 9.1, 9.4, 9.8_

  - [ ]* 21.2 Write remaining integration tests
    - Create `tests/test_audit/test_data_path_analyzer.py`
    - Create `tests/test_audit/test_credit_integrity.py`
    - Create `tests/test_audit/test_rate_limit_auditor.py`
    - Create `tests/test_audit/test_llm_reliability.py`
    - Create `tests/test_audit/test_flow_completeness.py`
    - Create `tests/test_audit/test_spec_coverage.py`
    - Create `tests/test_audit/test_debt_radar.py`
    - Create `tests/test_audit/test_bypass_detector.py`
    - Create `tests/test_audit/test_report_generator.py`
    - Create `tests/test_audit/test_dashboard.py`
    - _Requirements: 1.1–11.6_

- [ ] 22. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design (33 total)
- Unit/integration tests validate specific block logic and end-to-end flows
- The design specifies Python 3.11+, FastAPI, SQLAlchemy 2.0, Celery+Redis, PostgreSQL 16, Jinja2+HTMX, Tailwind CSS
- All admin routes use `require_superuser` dependency (existing pattern)
- Dashboard uses dark theme via `admin_base.html` (existing pattern)
- Hypothesis library is used for property-based tests (already configured in project)
- Static analysis blocks use Python AST module for code scanning
- Only one audit run can be active at a time (Redis distributed lock)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2", "2.2", "3.1"] },
    { "id": 2, "tasks": ["3.2", "3.3", "5.1", "6.1", "7.1", "8.1"] },
    { "id": 3, "tasks": ["5.2", "6.2", "7.2", "8.2", "10.1", "11.1", "12.1", "13.1"] },
    { "id": 4, "tasks": ["10.2", "11.2", "12.2", "13.2", "15.1"] },
    { "id": 5, "tasks": ["15.2", "16.1", "17.1"] },
    { "id": 6, "tasks": ["16.2", "17.2", "18.1", "19.1"] },
    { "id": 7, "tasks": ["21.1"] },
    { "id": 8, "tasks": ["21.2"] }
  ]
}
```
