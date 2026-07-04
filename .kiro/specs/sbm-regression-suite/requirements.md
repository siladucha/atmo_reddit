# Requirements Document

## Introduction

SBM Regression Test Suite — a dedicated integration-level test suite that validates all 10 System Behavior Model (SBM) properties (P1–P10) against a real PostgreSQL database. The suite provides a single `pytest` target (`tests/sbm/`) that serves as a pre-deploy gate and regression safety net. Each test documents which SBM property it validates, what a violation means, and is designed to catch the class of regressions that occurred in production (June 2026 incidents: CQS deadlock P2/P9, EPG dedup P1, quiet hours violation P8). External dependencies (Reddit API, LLM providers) are replaced with mocks/fakes to ensure deterministic, fast execution.

## Glossary

- **SBM_Suite**: The collection of integration test files in `tests/sbm/` that validate all 10 System Behavior Model properties
- **SBM_Property**: One of the 10 system-level invariants (P1–P10) defined in `.kiro/steering/system_behavior_model.md`
- **Test_Runner**: The pytest framework executing SBM_Suite tests with Hypothesis support for property-based testing
- **Test_DB**: A local PostgreSQL 16 database used by the SBM_Suite with SAVEPOINT-based transaction isolation per test (auto-rollback via conftest.py)
- **Critical_Path_Target**: A pytest marker (`@pytest.mark.sbm_critical`) identifying the fast subset of SBM_Suite tests that run as a pre-deploy gate
- **Mock_Reddit**: A fake implementation of PRAW Reddit client that returns configurable responses without network calls
- **Mock_LLM**: A fake implementation of LiteLLM calls that returns deterministic outputs without API calls
- **Violation_Docstring**: A structured docstring in each SBM test documenting the property ID, statement, and what a failure means operationally
- **Regression_Scenario**: A test case modeled after a real production incident that triggered an SBM property violation

## Requirements

### Requirement 1: Suite Structure and Organization

**User Story:** As a developer, I want a dedicated test directory for SBM property tests with clear organization, so that I can quickly find and run property-specific regression tests.

#### Acceptance Criteria

1. THE SBM_Suite SHALL reside in a dedicated `tests/sbm/` directory with one test file per SBM_Property (10 files: `test_p1_monotonic_progress.py` through `test_p10_graceful_degradation.py`)
2. THE SBM_Suite SHALL include a shared `conftest.py` in `tests/sbm/` that reuses the existing SAVEPOINT pattern from `tests/conftest.py` and provides SBM-specific fixtures (mock clients, avatars, pipelines)
3. THE SBM_Suite SHALL register a pytest marker `sbm_critical` for tests included in the Critical_Path_Target
4. THE SBM_Suite SHALL register a pytest marker `sbm` for all SBM property tests to enable `pytest -m sbm` execution

### Requirement 2: SBM Property Documentation in Tests

**User Story:** As a developer, I want each test to clearly document which SBM property it validates and what a failure means, so that test failures map directly to operational risk.

#### Acceptance Criteria

1. THE Test_Runner SHALL enforce that every test function in SBM_Suite has a Violation_Docstring containing the property ID (P1–P10), the property statement, and a violation impact description
2. WHEN a test fails, THE Test_Runner SHALL include the property ID and violation description in the pytest output via a custom failure hook
3. THE SBM_Suite SHALL include a module-level docstring in each test file referencing the SBM property statement and enforcement category (runtime/scheduled/manual)

### Requirement 3: P1 — Monotonic Progress Validation

**User Story:** As a developer, I want to verify that active clients with healthy avatars produce drafts within the expected window, so that pipeline stalls are caught before deployment.

#### Acceptance Criteria

1. WHEN an active client has at least one healthy (not frozen, not shadowbanned, not suspended) avatar, THE SBM_Suite SHALL verify that the pipeline code path from scoring through generation produces at least one CommentDraft record
2. IF a client has all avatars frozen or shadowbanned, THEN THE SBM_Suite SHALL verify that no drafts are generated for that client (correct behavior, not a violation)
3. WHEN the pipeline runs for an active client, THE SBM_Suite SHALL verify that the generate_comments task does not silently skip all threads without logging an activity event
4. THE SBM_Suite SHALL include a Regression_Scenario modeling the "paying client with 0 posts in 7d" alert condition by verifying the alert_aggregation SQL query returns the expected clients

### Requirement 4: P2 — Recovery Reachability Validation

**User Story:** As a developer, I want to verify that frozen and shadowbanned avatars are not excluded from diagnostic tasks, so that deadlocks like the June 27 CQS incident are prevented.

#### Acceptance Criteria

1. WHEN an avatar has `is_frozen=True`, THE SBM_Suite SHALL verify that `run_cqs_check_batch()` includes the avatar in its query results
2. WHEN an avatar has `health_status='shadowbanned'`, THE SBM_Suite SHALL verify that `generate_cqs_check_tasks()` creates an ExecutionTask for that avatar
3. THE SBM_Suite SHALL include a Regression_Scenario reproducing the June 27 CQS deadlock: a frozen avatar with improved CQS must be detectable by the batch checker
4. WHEN an avatar is in any non-suspended state, THE SBM_Suite SHALL verify that at least one diagnostic task path (CQS check OR health check) is reachable for that avatar

### Requirement 5: P3 — Cost Proportionality Validation

**User Story:** As a developer, I want to verify that budget controls prevent unbounded LLM cost accumulation, so that retry loops and failed generations are capped.

#### Acceptance Criteria

1. THE SBM_Suite SHALL verify that `cost_governor.py` enforces the daily cap by rejecting calls when the cumulative cost exceeds the configured threshold
2. WHEN Smart Scoring runs for an avatar, THE SBM_Suite SHALL verify that the number of threads scored does not exceed `remaining_budget × 3` (HARD_CAP=15)
3. WHEN `cqs_level='lowest'`, THE SBM_Suite SHALL verify that `AttentionBudget.from_avatar()` returns `max_comments=0` (zero EPG slots, zero LLM calls for that avatar)
4. THE SBM_Suite SHALL verify that the Smart Scoring budget formula correctly reduces scoring calls proportionally to already-consumed daily budget

### Requirement 6: P4 — Safety Monotonicity Validation

**User Story:** As a developer, I want to verify that phase-based content restrictions are strictly enforced with no bypass path, so that brand safety is guaranteed.

#### Acceptance Criteria

1. WHEN an avatar has `warming_phase=1`, THE SBM_Suite SHALL verify that `check_avatar_can_post()` blocks any comment containing brand mentions
2. WHEN an avatar has `warming_phase=1`, THE SBM_Suite SHALL verify that professional comment generation is blocked (only hobby pipeline produces output)
3. THE SBM_Suite SHALL use Hypothesis to generate random phase values (0–3) and verify that restrictions for phase N are a superset of restrictions for phase N+1 (monotonicity property)
4. WHEN an avatar has `warming_phase=0`, THE SBM_Suite SHALL verify that posting_safety gate 5 (Phase 0 exclusion) blocks automated posting

### Requirement 7: P5 — Human Gate Integrity Validation

**User Story:** As a developer, I want to verify that the generate-to-post pipeline always has a human decision point, so that autonomous posting never occurs without consent.

#### Acceptance Criteria

1. THE SBM_Suite SHALL verify that a CommentDraft transitions from `pending` to `posted` only after passing through `approved` status (no direct pending→posted path exists in code)
2. WHEN `POSTING_DISABLED=true`, THE SBM_Suite SHALL verify that `execute_pending_posts` posts zero comments regardless of approved slots
3. THE SBM_Suite SHALL verify that an EPG slot with `status='planned'` or `status='generated'` cannot be dispatched by `execute_pending_posts` (only `approved` slots are posted)
4. WHEN `auto_approve_drafts=false` on an avatar, THE SBM_Suite SHALL verify that generated EPG slots remain in `generated` status (no auto-transition to `approved`)

### Requirement 8: P6 — Feedback Closure Validation

**User Story:** As a developer, I want to verify that all posted comments eventually receive karma snapshots, so that the learning loop is never silently broken.

#### Acceptance Criteria

1. WHEN a CommentDraft has `status='posted'` and `posted_at` older than 4 hours, THE SBM_Suite SHALL verify that `snapshot_comment_outcomes` includes the draft in its processing query
2. THE SBM_Suite SHALL verify the feedback closure SQL query (comments posted >48h with no karma snapshots) correctly identifies orphaned comments
3. WHEN `snapshot_comment_outcomes` processes a comment, THE SBM_Suite SHALL verify that a KarmaSnapshot record is created with the correct `check_window` value
4. THE SBM_Suite SHALL include a Regression_Scenario where a posted draft with no `reddit_comment_url` is correctly excluded from snapshot processing (not a false violation)

### Requirement 9: P7 — Isolation Guarantee Validation

**User Story:** As a developer, I want to verify that client data isolation is enforced at every query boundary, so that cross-client data leaks are impossible.

#### Acceptance Criteria

1. THE SBM_Suite SHALL use Hypothesis to generate random pairs of clients and verify that queries scoped to client A never return data owned by client B
2. THE SBM_Suite SHALL verify that `query_scope.py` scoping functions include `client_id` filter on all entity queries (CommentDraft, RedditThread, Avatar, EPGSlot)
3. WHEN an avatar is assigned to client A, THE SBM_Suite SHALL verify that `generate_comment()` context assembly includes only client A's keywords, strategy, and subreddits
4. THE SBM_Suite SHALL verify that the Portal route handlers return 403 when a client_admin attempts to access another client's resources

### Requirement 10: P8 — Temporal Consistency Validation

**User Story:** As a developer, I want to verify that dispatches respect time windows and quiet hours, so that executors never receive emails at inappropriate times.

#### Acceptance Criteria

1. WHEN current time is within quiet hours (23:00–07:00 Israel time), THE SBM_Suite SHALL verify that `dispatch_due_email_tasks` dispatches zero tasks
2. THE SBM_Suite SHALL use Hypothesis to generate random scheduled_at timestamps and verify that dispatch only occurs when `scheduled_at` falls within [now-5min, now+30min]
3. THE SBM_Suite SHALL include a Regression_Scenario modeling the June 25 Flaky_Finder_13 incident: an avatar with `declared_timezone='America/New_York'` must not generate dispatch at executor's nighttime (Israel 02:00)
4. WHEN timing_engine generates slot times, THE SBM_Suite SHALL verify that all generated times fall within active hours (08:00–23:00 configured timezone)

### Requirement 11: P9 — Diagnostic Independence Validation

**User Story:** As a developer, I want to verify that diagnostic systems never filter out avatars based on the condition they are diagnosing, so that the "patient too sick to examine" anti-pattern is prevented.

#### Acceptance Criteria

1. WHEN an avatar has `is_frozen=True` AND `health_status='shadowbanned'`, THE SBM_Suite SHALL verify that `run_cqs_check_batch()` query results include this avatar
2. WHEN an avatar has `cqs_level='lowest'`, THE SBM_Suite SHALL verify that `generate_cqs_check_tasks()` produces a task for that avatar (the very condition being diagnosed does not block the diagnostic)
3. THE SBM_Suite SHALL include a Regression_Scenario modeling the June 27 CQS deadlock: create a frozen shadowbanned avatar, run all diagnostic batch queries, and verify the avatar appears in at least one diagnostic path
4. THE SBM_Suite SHALL verify that `health_check_all_avatars` batch query does not exclude avatars with `is_frozen=True` from health signal collection

### Requirement 12: P10 — Graceful Degradation Validation

**User Story:** As a developer, I want to verify that disabling one component does not cascade failures to others, so that single points of failure are eliminated.

#### Acceptance Criteria

1. WHEN `pipeline_enabled=false`, THE SBM_Suite SHALL verify that scraping, health checks, karma tracking, and CQS tasks continue to execute independently
2. WHEN `generation_enabled=false`, THE SBM_Suite SHALL verify that scoring still runs and tags threads (pipeline produces scores but no drafts)
3. WHEN `scrape_enabled=false`, THE SBM_Suite SHALL verify that the generation pipeline processes existing scored threads without error (uses stale data gracefully)
4. THE SBM_Suite SHALL verify that each kill switch (`pipeline_enabled`, `generation_enabled`, `scrape_enabled`, `auto_posting_enabled`, `email_tasks_enabled`) independently controls only its intended scope without raising exceptions in other subsystems

### Requirement 13: Pre-Deploy Critical Path Gate

**User Story:** As a developer, I want a fast subset of SBM tests that runs before every deployment, so that critical regressions are caught in under 20 seconds.

#### Acceptance Criteria

1. THE Critical_Path_Target SHALL complete execution within 20 seconds on local PostgreSQL (no network calls)
2. THE Critical_Path_Target SHALL include at least one test per SBM property that has runtime enforcement (P4, P5, P7) and one test for each previously-violated property (P1, P2, P8, P9)
3. WHEN the Critical_Path_Target is invoked via `pytest -m sbm_critical`, THE Test_Runner SHALL execute only the marked fast subset
4. IF any Critical_Path_Target test fails, THEN THE Test_Runner SHALL exit with non-zero status and print a summary of violated SBM properties

### Requirement 14: External Dependency Isolation

**User Story:** As a developer, I want SBM tests to run without Reddit API or LLM providers, so that tests are deterministic and fast.

#### Acceptance Criteria

1. THE SBM_Suite SHALL use Mock_Reddit (fake PRAW client) for all tests requiring Reddit API interaction (health checks, CQS probes, karma snapshots)
2. THE SBM_Suite SHALL use Mock_LLM (fake LiteLLM responses) for all tests requiring LLM calls (scoring, generation, strategy)
3. THE SBM_Suite SHALL use fakeredis for all Redis-dependent operations (distributed locks, rate limiting, heartbeat)
4. THE SBM_Suite SHALL use the real Test_DB (PostgreSQL with SAVEPOINT pattern) for all database operations — no database mocking

### Requirement 15: Regression Scenario Coverage

**User Story:** As a developer, I want test cases modeled after real production incidents, so that known failure modes are permanently prevented from recurring.

#### Acceptance Criteria

1. THE SBM_Suite SHALL include a Regression_Scenario for the June 27 CQS deadlock (P2/P9): frozen avatar excluded from all diagnostic paths, creating undetectable recovery
2. THE SBM_Suite SHALL include a Regression_Scenario for the June 24-25 EPG dedup failure (P1): multiple EPG build runs creating duplicate slots beyond budget
3. THE SBM_Suite SHALL include a Regression_Scenario for the June 25 quiet hours violation (P8): email dispatch at executor's 02:00 due to persona timezone mismatch
4. WHEN a new production incident occurs and is traced to an SBM property violation, THE SBM_Suite SHALL be extended with a corresponding Regression_Scenario (documented convention in `tests/sbm/README.md`)
