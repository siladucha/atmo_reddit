# Implementation Plan

## Overview
A/B testing framework to scientifically validate whether the posting method (old.reddit textarea, manual email-instructed, new.reddit chrome.debugger) affects Reddit's trust score for avatar accounts. The experiment assigns avatars to treatment groups, enforces control variables, and produces weekly statistical reports over an 8-week period.

## Tasks

- [x] 1. Database Models & Migration
  Create SQLAlchemy models for the A/B test framework and Alembic migration. Add `posting_strategy` column to `execution_tasks`.
  - [x] 1.1. Create `app/models/ab_test.py` with 6 models: ExperimentRun, TreatmentGroup, AvatarAssignment, MetricSnapshot, WeeklyReport, ControlViolation
  - [x] 1.2. Create Alembic migration `alembic/versions/ab01_ab_test_framework.py` creating 6 tables + adding `posting_strategy` to execution_tasks
  - [x] 1.3. Update `app/models/__init__.py` to import new models (if __init__ exists with model imports)
  - [x] 1.4. Verify all UNIQUE constraints: (experiment_id, posting_method) on groups, (experiment_id, avatar_id) on assignments, (experiment_id, avatar_id, week_number) on snapshots, (experiment_id, week_number) on reports
  - [x] 1.5. Verify migration applies cleanly (`alembic upgrade head`)

- [x] 2. Experiment Manager Service
  Core service for experiment lifecycle management: create, configure, assign avatars, state transitions.
  - [x] 2.1. Create `app/services/ab_test/__init__.py`
  - [x] 2.2. Create `app/services/ab_test/experiment_manager.py` with create_experiment(), add_treatment_group(), assign_avatar(), start_experiment(), pause_experiment(), resume_experiment(), conclude_experiment(), abort_experiment(), exclude_avatar(), get_active_experiment_for_avatar(), is_avatar_in_experiment()
  - [x] 2.3. Validate eligibility checks (CQS ≠ lowest, account_age within ±2 weeks of group median)
  - [x] 2.4. Emit ActivityEvent on every state transition

- [x] 3. Control Variable Enforcer
  Service that hooks into the EPG pipeline to enforce equal conditions across groups.
  - [x] 3.1. Create `app/services/ab_test/control_enforcer.py` with get_experiment_budget(), get_allowed_risk_range(), get_forced_content_type(), get_forced_generation_model(), validate_and_log_violation()
  - [x] 3.2. Modify `app/services/portfolio_manager.py` to call get_experiment_budget() to override AttentionBudget when avatar in experiment
  - [x] 3.3. Modify `app/services/opportunity_engine.py` to call get_allowed_risk_range() to filter subreddits by risk score
  - [x] 3.4. Modify `app/tasks/ai_pipeline.py` to call get_forced_content_type() and get_forced_generation_model()
  - [x] 3.5. Ensure conditional activation: only when ab_test_enabled=true AND avatar is in active experiment; early return for non-experiment avatars

- [x] 4. Posting Method Router
  Override delivery channel and posting strategy for experiment avatars. Integrates with task creation flow.
  - [x] 4.1. Create `app/services/ab_test/posting_router.py` with get_posting_method() returning correct config for each treatment group
  - [x] 4.2. Modify `app/services/execution_tasks.py` in create_execution_task() to check PostingRouter before using avatar's delivery_channel; set posting_strategy field
  - [x] 4.3. Modify `app/services/extension_dispatcher.py` to include posting_strategy in task payload returned by get_pending_tasks_for_node()
  - [x] 4.4. Modify `app/routes/extension_api.py` to include posting_strategy in task response JSON
  - [x] 4.5. Ensure paused experiment reverts to normal delivery_channel and failed extension tasks do NOT fall back to email

- [x] 5. Extension Scheduler Routing
  Modify extension scheduler to route tasks to the correct executor module based on posting_strategy field.
  - [x] 5.1. Modify `ramp_extension/background/scheduler.js` to add strategy-based executor selection in _executeDueTask()
  - [x] 5.2. Ensure tasks with posting_strategy=old_reddit execute via executeTaskOldReddit()
  - [x] 5.3. Ensure tasks with posting_strategy=new_reddit_debugger (or null/undefined) execute via executeTask() (chrome.debugger)
  - [x] 5.4. Include posting_strategy used in execution result report to backend
  - [x] 5.5. Verify backward compatibility for tasks without posting_strategy field

- [x] 6. Metric Collector
  Service that collects all health metrics per avatar per week from existing database tables.
  - [x] 6.1. Create `app/services/ab_test/metric_collector.py` with collect_week_metrics() and individual metric collectors
  - [x] 6.2. Implement _collect_removal_rate() querying comment_drafts WHERE status=posted AND posted_at in week window
  - [x] 6.3. Implement _collect_karma_velocity() averaging karma_snapshots for 4h/24h/7d windows
  - [x] 6.4. Implement _collect_shadowban_events(), _collect_cqs_changes(), _collect_subreddit_bans(), _collect_phase_speed(), _collect_account_warnings()
  - [x] 6.5. Store all snapshots as immutable MetricSnapshot records; handle avatars excluded mid-week

- [x] 7. Statistical Reporter
  Generate weekly reports with statistical comparisons between treatment groups.
  - [x] 7.1. Create `app/services/ab_test/statistical_reporter.py` with generate_weekly_report() and generate_final_report()
  - [x] 7.2. Implement chi-squared test for categorical metrics and Mann-Whitney U test for continuous metrics
  - [x] 7.3. Calculate effect size (Cohen's d for continuous, Cramér's V for categorical)
  - [x] 7.4. Implement cumulative analysis (all weeks pooled) alongside current-week-only
  - [x] 7.5. Implement _check_early_termination() detecting 2 consecutive weeks with significant primary metric + medium effect size
  - [x] 7.6. Handle small sample sizes gracefully (warn when n < 5 per group)

- [x] 8. Celery Tasks
  Scheduled tasks for automated metric collection and experiment lifecycle monitoring.
  - [x] 8.1. Create `app/tasks/ab_test.py` with collect_weekly_ab_metrics (Monday 02:30 IST) and check_experiment_durations (daily 07:00 IST) tasks
  - [x] 8.2. Modify `app/tasks/worker.py` to add Beat schedule entries for both new tasks
  - [x] 8.3. Guard tasks by ab_test_enabled setting; handle multiple concurrent experiments

- [x] 9. Phase Evaluation Block
  Prevent phase promotions/demotions for avatars in active experiments.
  - [x] 9.1. Modify `app/services/phase.py` in evaluate_avatar_phase() to skip evaluation if avatar in active (not paused) experiment
  - [x] 9.2. Emit activity event ab_phase_eval_blocked with avatar_id and experiment_id
  - [x] 9.3. Ensure phase evaluation resumes normally when experiment concludes or avatar excluded

- [x] 10. Admin Routes
  FastAPI routes for the A/B test admin UI.
  - [x] 10.1. Create `app/routes/admin_ab_test.py` with all routes requiring owner access
  - [x] 10.2. Implement GET /admin/ab-tests (list), GET /admin/ab-tests/new (form), POST /admin/ab-tests (create)
  - [x] 10.3. Implement GET /admin/ab-tests/{id} (detail), POST .../groups, POST .../assign, POST .../start, POST .../pause, POST .../resume, POST .../conclude, POST .../abort
  - [x] 10.4. Implement GET /admin/ab-tests/{id}/report/{week} and GET /admin/ab-tests/{id}/metrics (HTMX partials)
  - [x] 10.5. Modify `app/main.py` to include new router and `app/templates/admin_base.html` to add sidebar link

- [x] 11. Admin Templates
  Jinja2 templates for the A/B test admin pages.
  - [x] 11.1. Create `app/templates/admin_ab_tests.html` (list page with dark admin theme)
  - [x] 11.2. Create `app/templates/admin_ab_test_detail.html` (detail page with tabs: Groups, Assignments, Metrics, Reports)
  - [x] 11.3. Create `app/templates/partials/ab_test_groups.html` and `app/templates/partials/ab_test_assignments.html`
  - [x] 11.4. Create `app/templates/partials/ab_test_metrics.html` (Chart.js line charts per metric type)
  - [x] 11.5. Create `app/templates/partials/ab_test_report.html` (weekly report with stats table + significance markers)
  - [x] 11.6. Add status badges (draft=gray, active=green, paused=yellow, concluded=blue, aborted=red) and action buttons with confirmation dialogs

- [ ] 12. Integration Testing & Deploy @optional
  Verify end-to-end flow locally, fix integration issues, deploy to staging.
  - [~] 12.1. Test: create experiment → add 2 groups → assign 5+ avatars each → start (all transitions work)
  - [~] 12.2. Test: control enforcer overrides budget, task creation uses correct posting_strategy, extension receives posting_strategy
  - [~] 12.3. Test: weekly metric collection and statistical report generation
  - [~] 12.4. Test: phase evaluation skipped for experiment avatars; pausing restores normal behavior
  - [~] 12.5. Verify no regression for non-experiment avatars; migration applies cleanly on staging

## Task Dependency Graph

```
1 --> 2
2 --> 3
2 --> 4
2 --> 6
2 --> 9
4 --> 5
6 --> 7
6 --> 8
7 --> 8
3 --> 10
4 --> 10
6 --> 10
7 --> 10
10 --> 11
1 --> 12
2 --> 12
3 --> 12
4 --> 12
5 --> 12
6 --> 12
7 --> 12
8 --> 12
9 --> 12
10 --> 12
11 --> 12
```

## Notes

- **Critical path:** Task 1 → Task 2 → (Tasks 3, 4, 6 in parallel) → Tasks 7, 8 → Tasks 10, 11 → Task 12
- **Total estimated effort:** 25-35 hours (~3-4 days focused)
- Task 12 is marked optional as it's integration testing that may require manual verification
- All models use UUID primary keys and proper CHECK constraints for status enums
- Statistical tests require scipy (already in project dependencies)
- Extension scheduler changes are in JavaScript (ramp_extension/)
