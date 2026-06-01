# Implementation Plan: Quality Sentinel

## Overview

Implement the Quality Sentinel subsystem — a unified quality control system that tracks post-posting outcomes (karma, removals, replies), computes effectiveness scores for decision combinations, builds multi-level trends, alerts operators on degradation, and auto-adapts pipeline behavior. The system integrates with existing Celery/PostgreSQL infrastructure, adds 4 new models, 5 new services, Celery tasks, and an admin quality dashboard.

## Tasks

- [ ] 1. Database models and migrations
  - [ ] 1.1 Create OutcomeRecord model
    - Create `app/models/outcome_record.py` with fields: id, draft_id (FK unique), avatar_id (FK), client_id (FK), subreddit_id (FK), posted_at, karma_4h, karma_4h_checked_at, karma_24h, karma_24h_checked_at, karma_48h, karma_48h_checked_at, removal_detected, removal_detected_at, removal_type, reply_count, has_op_reply, comment_approach, strategy_pattern, timing_bucket, thread_score_at_selection, next_check_type, next_check_at, created_at
    - Add indexes: (next_check_type, next_check_at), (avatar_id, posted_at), (subreddit_id, posted_at), (client_id, posted_at)
    - Register model in `app/models/__init__.py`
    - _Requirements: 1.1, 2.1, 3.1, 4.1, 4.2_

  - [ ] 1.2 Create EffectivenessScore model
    - Create `app/models/effectiveness_score.py` with fields: id, combo_type, combo_key (unique), score, sample_count, positive_count, negative_count, removal_count, total_karma, avg_karma, last_outcome_at, updated_at, created_at
    - Add indexes: (combo_type), (combo_type, score)
    - Register model in `app/models/__init__.py`
    - _Requirements: 5.1, 5.3, 5.6_

  - [ ] 1.3 Create KPISnapshot model
    - Create `app/models/kpi_snapshot.py` with fields: id, observation_level, entity_id (nullable for system), snapshot_date, period_type, avg_karma, removal_rate, reply_rate, positive_outcome_rate, volume, trend_7d_karma, trend_30d_karma, trend_7d_removal, trend_30d_removal, created_at
    - Add unique constraint: (observation_level, entity_id, snapshot_date, period_type)
    - Add index: (observation_level, entity_id, snapshot_date)
    - Register model in `app/models/__init__.py`
    - _Requirements: 8.1, 8.2, 9.1_

  - [ ] 1.4 Create QualityAlert model
    - Create `app/models/quality_alert.py` with fields: id, alert_type, severity, observation_level, entity_id, entity_name, title, description, risk_score, is_acknowledged, acknowledged_at, acknowledged_by, created_at, expires_at
    - Add indexes: (is_acknowledged, created_at), (observation_level, entity_id, created_at)
    - Register model in `app/models/__init__.py`
    - _Requirements: 11.1, 11.2, 11.4, 11.5_

  - [ ] 1.5 Create Alembic migration
    - Create migration `qs01_quality_sentinel_tables` that creates all 4 tables with indexes and constraints
    - Seed system settings: quality_sentinel_enabled=true, auto_adaptation_enabled=false, outcome_check_batch_size=50, risk_score_warning_threshold=70, risk_score_critical_threshold=85, effectiveness_min_samples=5, outcome_retention_days=90, alert_retention_days=90
    - _Requirements: 18.1, 18.2, 18.3_

- [ ] 2. Checkpoint — Verify migrations run cleanly
  - Run `alembic upgrade head` and verify all tables created
  - Verify indexes exist with expected names
  - Verify system settings seeded correctly

- [ ] 3. Outcome Tracker service
  - [ ] 3.1 Create OutcomeTracker class
    - Create `app/services/outcome_tracker.py` with OutcomeTracker class
    - Implement `create_outcome_record(db, draft)` — extracts attribution context (comment_approach, strategy_pattern from draft/EPG/strategy), computes timing_bucket from posted_at, sets next_check_type='4h' and next_check_at=posted_at+4h
    - _Requirements: 1.1, 4.1, 4.2, 6.1_

  - [ ] 3.2 Implement pending checks query
    - Implement `get_pending_checks(db, batch_size=50)` — queries outcome_records WHERE next_check_at <= now() AND next_check_type != 'complete', ordered by priority (4h first, then 24h, then 48h), limited to batch_size
    - _Requirements: 1.4, 1.5_

  - [ ] 3.3 Implement karma check execution
    - Implement `execute_karma_check(db, record, reddit_client)` — fetches comment by reddit_comment_id, reads score, calls detect_removal(), counts replies on 24h/48h checks, updates appropriate karma field, advances next_check_type/next_check_at
    - _Requirements: 1.2, 2.1, 3.1, 3.2_

  - [ ] 3.4 Implement removal detection
    - Implement `detect_removal(comment)` — returns (is_removed, removal_type) based on comment.body content: '[removed]' → mod_removed, '[deleted]' → author_deleted, 404 → unknown
    - _Requirements: 2.2, 2.3, 2.4_

  - [ ] 3.5 Implement timing bucket computation
    - Implement `compute_timing_bucket(posted_at)` — converts datetime to 2-hour bucket string (e.g., hour 9 → "08-10", hour 14 → "14-16")
    - _Requirements: 4.2_

  - [ ] 3.6 Hook into posting service
    - In `app/services/posting.py`, after successful post (PostingEvent with outcome=success), call `outcome_tracker.create_outcome_record(db, draft)` to initialize tracking
    - _Requirements: 1.1_

- [ ] 4. Checkpoint — Verify outcome tracking works
  - Write unit test: create_outcome_record produces correct attribution and scheduling
  - Write unit test: detect_removal correctly classifies removal types
  - Write unit test: compute_timing_bucket returns valid bucket strings

- [ ] 5. Learning Engine service
  - [ ] 5.1 Create LearningEngine class
    - Create `app/services/learning_engine.py` with LearningEngine class and constants (KARMA_WEIGHT=1.0, REMOVAL_PENALTY=0.8, REPLY_BONUS=0.3, REJECTION_WEIGHT=0.5, STRATEGY_CHANGE_WEIGHT=0.3, MIN_SAMPLES=5)
    - _Requirements: 5.1, 14.2_

  - [ ] 5.2 Implement effectiveness score computation
    - Implement `compute_effectiveness_score(outcomes)` — sigmoid-normalized karma + removal penalty + reply bonus, clipped to [0.0, 1.0]
    - Implement sigmoid_normalize helper: karma -5→0.0, 0→0.3, 1→0.4, 5→0.6, 10→0.7, 50→0.95, 100+→1.0
    - _Requirements: 5.3_

  - [ ] 5.3 Implement effectiveness score updates
    - Implement `update_effectiveness_scores(db, outcome)` — generates combo keys (approach×sub, avatar×sub, timing×sub, strategy×client), upserts EffectivenessScore records with updated sample_count, positive_count, negative_count, removal_count, total_karma, avg_karma, and recomputed score
    - _Requirements: 5.2, 5.6, 6.1_

  - [ ] 5.4 Implement adaptation weights
    - Implement `get_adaptation_weights(db, combo_type, entity_id, subreddit_id)` — queries EffectivenessScore for matching combo_type, filters by min_samples threshold, returns dict of entity→score. Returns empty dict if auto_adaptation_enabled is False
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ] 5.5 Implement fallback logic
    - When combo_key has sample_count < MIN_SAMPLES, compute parent-level score (e.g., approach across all subreddits). If parent also insufficient, return no score
    - _Requirements: 5.4, 5.5, 17.5_

  - [ ] 5.6 Implement learning channel signals
    - Implement `record_rejection_signal(db, draft)` — negative signal (weight 0.5) for scoring/EPG decisions
    - Implement `record_strategy_change_signal(db, client_id, old_strategy)` — weak negative (weight 0.3)
    - Implement `record_epg_reassignment_signal(db, slot_id)` — weak negative (weight 0.3)
    - _Requirements: 13.1, 16.1, 16.2, 16.3_

- [ ] 6. Checkpoint — Verify learning engine
  - Write unit test: compute_effectiveness_score with known inputs produces expected scores
  - Write unit test: fallback returns parent-level score when n < 5
  - Write unit test: get_adaptation_weights returns empty when auto_adaptation_enabled=False

- [ ] 7. Trend Calculator service
  - [ ] 7.1 Create TrendCalculator class
    - Create `app/services/trend_calculator.py` with TrendCalculator class and TREND_THRESHOLDS dict
    - Add numpy to project dependencies in pyproject.toml
    - _Requirements: 8.1, 9.1_

  - [ ] 7.2 Implement daily snapshot collection
    - Implement `collect_daily_snapshots(db, snapshot_date)` — queries outcome_records for the date, aggregates avg_karma, removal_rate, reply_rate, positive_outcome_rate, volume at system/client/subreddit/avatar levels, creates KPISnapshot records
    - _Requirements: 8.1, 8.2, 8.3_

  - [ ] 7.3 Implement trend computation
    - Implement `compute_trends(db, snapshot_date)` — for each entity at each level, fetches last 7 and 30 daily snapshots, computes linear regression slope via numpy.polyfit(degree=1), updates trend fields on latest snapshot
    - Implement `_linear_regression_slope(values)` — numpy polyfit, returns slope
    - Enforce minimum data points: 5 for 7d, 14 for 30d
    - _Requirements: 9.1, 9.2_

  - [ ] 7.4 Implement trend classification
    - Implement `classify_trend(slope, kpi_name)` — returns 'improving'/'stable'/'degrading' based on per-KPI thresholds
    - _Requirements: 9.3, 9.4_

  - [ ] 7.5 Implement retention cleanup
    - Implement `cleanup_old_snapshots(db)` — aggregates daily snapshots older than 1 year into monthly summaries, deletes raw daily records
    - _Requirements: 8.4, 8.5_

- [ ] 8. Alert Engine service
  - [ ] 8.1 Create AlertEngine class
    - Create `app/services/alert_engine.py` with AlertEngine class, RISK_WEIGHTS, thresholds, and retention constants
    - _Requirements: 10.1, 10.2_

  - [ ] 8.2 Implement risk score computation
    - Implement `compute_entity_risk_score(db, observation_level, entity_id)` — weighted sum of removal_rate_trend (0.35), karma_trend inverted (0.30), volume_drop (0.20), consecutive_failures (0.15), each normalized to 0-100
    - Implement `compute_risk_scores(db)` — iterates all active avatars, clients, and system level
    - _Requirements: 10.1, 10.2, 10.5_

  - [ ] 8.3 Implement alert evaluation
    - Implement `evaluate_alerts(db, risk_scores)` — detects threshold crossings (70=warning, 85=critical), respects 24h deduplication window, creates QualityAlert records
    - _Requirements: 11.1, 11.2, 11.5_

  - [ ] 8.4 Implement correlation alert detection
    - Implement `detect_correlation_alerts(db)` — finds 3+ avatars with degrading karma trend in same subreddit within 7 days, creates Correlation_Alert
    - _Requirements: 11.3_

  - [ ] 8.5 Implement alert cleanup
    - Implement `cleanup_expired_alerts(db)` — deletes alerts older than 90 days
    - _Requirements: 11.4_

- [ ] 9. Decision Quality service
  - [ ] 9.1 Create DecisionQualityService
    - Create `app/services/decision_quality.py` with DecisionQualityService class
    - Implement `strategy_quality(db, window_days=30)` — avg karma trend for strategy-attributed outcomes
    - Implement `scoring_precision(db, window_days=30)` — % of engage threads with positive outcome
    - Implement `epg_quality(db, window_days=30)` — karma of selected threads vs average
    - Implement `generation_quality(db, window_days=30)` — composite of edit rate, rejection rate, karma
    - Implement `posting_success(db, window_days=30)` — failure rate + timing effectiveness
    - Implement `compute_all_node_qualities(db)` — aggregates all metrics into dashboard dict
    - _Requirements: 6.2, 12.2_

- [ ] 10. Celery tasks and scheduling
  - [ ] 10.1 Create quality sentinel tasks
    - Create `app/tasks/quality_sentinel.py` with task definitions
    - Implement `check_outcomes_batch` — gets pending checks (batch 50), processes via Reddit API, handles errors with retry/backoff, triggers effectiveness update on 48h completion
    - Implement `compute_daily_trends` — calls collect_daily_snapshots + compute_trends, chains evaluate_risk_scores
    - Implement `evaluate_risk_scores` — calls compute_risk_scores + evaluate_alerts + detect_correlation_alerts + cleanup
    - Implement `cleanup_outcome_records` — deletes completed records older than 90 days (verifies aggregation first)
    - _Requirements: 1.3, 1.5, 1.6, 17.1, 17.2, 17.4, 19.1, 19.2, 19.3_

  - [ ] 10.2 Register tasks and Beat schedule
    - Register tasks in `app/tasks/worker.py`
    - Add Celery Beat entries: check_outcomes_batch every 4h, compute_daily_trends at 03:00, cleanup_outcome_records Sunday 04:00
    - _Requirements: 19.1, 19.2, 19.4, 19.5_

- [ ] 11. Checkpoint — Verify tasks run
  - Test check_outcomes_batch with mocked Reddit API
  - Test compute_daily_trends produces correct snapshots
  - Test evaluate_risk_scores creates alerts on threshold crossing

- [ ] 12. Learning channel hooks
  - [ ] 12.1 Hook rejection signal
    - In `app/routes/review.py` and `app/routes/pages.py`, after draft rejection, call `learning_engine.record_rejection_signal(db, draft)`
    - _Requirements: 13.1, 13.2_

  - [ ] 12.2 Hook strategy change signal
    - In strategy engine service, after active strategy changes, call `learning_engine.record_strategy_change_signal(db, client_id, old_strategy)`
    - _Requirements: 16.1_

  - [ ] 12.3 Hook EPG reassignment signal
    - In EPG routes, after manual slot reassignment, call `learning_engine.record_epg_reassignment_signal(db, slot_id)`
    - _Requirements: 16.2_

  - [ ] 12.4 Hook outcome completion
    - In outcome_tracker, after 48h snapshot recorded, call `learning_engine.update_effectiveness_scores(db, outcome)`
    - _Requirements: 5.2, 14.1_

- [ ] 13. Auto-adaptation integration
  - [ ] 13.1 EPG service integration
    - In `app/services/epg.py` thread selection, query effectiveness weights via get_adaptation_weights and bias toward high-score subreddit×approach combos (score > 0.6)
    - Gate behind auto_adaptation_enabled setting
    - _Requirements: 7.1_

  - [ ] 13.2 Approach diversity integration
    - In `app/services/approach_diversity.py`, query effectiveness weights and reduce probability of approaches with score < 0.3 for target subreddit
    - Gate behind auto_adaptation_enabled setting
    - _Requirements: 7.2_

  - [ ] 13.3 Timing engine integration
    - In `app/services/timing_engine.py`, query effectiveness weights and bias toward timing buckets with score > 0.5 for target subreddit
    - Gate behind auto_adaptation_enabled setting
    - _Requirements: 7.3_

- [ ] 14. Quality Dashboard UI
  - [ ] 14.1 Create dashboard route and main page
    - Create `app/routes/quality_dashboard.py` with router (prefix=/admin/quality)
    - Implement GET / — main dashboard page
    - Implement GET /drilldown/{level}/{entity_id} — entity drill-down
    - Implement POST /alerts/{alert_id}/acknowledge — acknowledge alert
    - Implement GET /alerts/badge — HTMX partial for header badge
    - Register router in `app/main.py`
    - _Requirements: 12.1, 12.3, 12.5_

  - [ ] 14.2 Create dashboard template
    - Create `app/templates/admin_quality.html` extending admin_base.html
    - Sections: system risk score gauge, decision quality bars, sparkline trends, top 5 risks, recent learnings, alert list
    - All data loaded from pre-computed scores (not real-time aggregation)
    - _Requirements: 12.2, 12.4_

  - [ ] 14.3 Create HTMX partials
    - Create `app/templates/partials/quality_risk_score.html` — risk score gauge
    - Create `app/templates/partials/quality_decision_bars.html` — per-node quality bars
    - Create `app/templates/partials/quality_sparklines.html` — 7d trend sparklines
    - Create `app/templates/partials/quality_top_risks.html` — top 5 at-risk entities
    - Create `app/templates/partials/quality_alerts.html` — alert list with acknowledge
    - _Requirements: 12.2_

  - [ ] 14.4 Create drill-down template
    - Create `app/templates/admin_quality_drilldown.html` — entity detail with KPI history, effectiveness scores, trend charts, related alerts
    - _Requirements: 12.3_

  - [ ] 14.5 Add navigation and alert badge
    - Add "Quality" link to admin navigation sidebar in `admin_base.html`
    - Add alert badge to header (HTMX lazy-load from /admin/quality/alerts/badge)
    - _Requirements: 11.6, 12.1_

- [ ] 15. System settings
  - [ ] 15.1 Add quality settings to settings service
    - Add quality group settings: quality_sentinel_enabled, auto_adaptation_enabled, outcome_check_batch_size, risk_score_warning_threshold, risk_score_critical_threshold, effectiveness_min_samples, outcome_retention_days, alert_retention_days
    - Add validators for quality group
    - Add quality settings section to admin system settings page
    - _Requirements: 7.5, 17.1_

- [ ] 16. Property-based tests
  - [ ] 16.1 Effectiveness score properties
    - Test: score always in [0.0, 1.0] for any valid outcomes (Property 1)
    - Test: adding positive outcome never decreases score (Property 2)
    - Test: adding removal never increases score (Property 3)
    - _Validates: Properties 1, 2, 3_

  - [ ] 16.2 Timing and risk score properties
    - Test: timing bucket returns valid "HH-HH" pattern for any datetime (Property 4)
    - Test: risk score always in [0, 100] for any inputs (Property 5)
    - Test: classify_trend returns exactly one valid classification (Property 6)
    - Test: risk weight sum equals 1.0 (Property 13)
    - _Validates: Properties 4, 5, 6, 13_

  - [ ] 16.3 Alert and threshold properties
    - Test: alert deduplication prevents duplicates within 24h (Property 7)
    - Test: min sample threshold returns empty weights when n < 5 (Property 8)
    - Test: auto-adaptation gate returns empty when disabled (Property 15)
    - Test: correlation alert fires when 3+ avatars degrade in same sub (Property 14)
    - _Validates: Properties 7, 8, 14, 15_

  - [ ] 16.4 Data integrity properties
    - Test: outcome record attribution completeness for valid inputs (Property 9)
    - Test: karma snapshot scheduling produces correct 4h→24h→48h→complete sequence (Property 10)
    - Test: retention cleanup never deletes incomplete records (Property 11)
    - Test: linear regression requires minimum data points (Property 12)
    - Test: effectiveness score fallback to parent level (Property 16)
    - _Validates: Properties 9, 10, 11, 12, 16_

- [ ] 17. Unit and integration tests
  - [ ] 17.1 Unit tests
    - Test OutcomeTracker: mock Reddit API, verify karma extraction, removal detection, reply counting
    - Test LearningEngine: verify score computation with known inputs, verify fallback
    - Test TrendCalculator: verify linear regression with known data, verify classification
    - Test AlertEngine: verify threshold crossing, deduplication, correlation detection
    - Test DecisionQualityService: verify per-node metrics with known data
    - Test retention cleanup: verify only completed records deleted

  - [ ] 17.2 Integration tests
    - Test full outcome lifecycle: post → 4h → 24h → 48h → effectiveness update
    - Test alert flow: degrading trend → risk score → alert → badge
    - Test adaptation flow: scores computed → EPG uses weights → selection biased

## Notes

- Phase 1 (before 10 clients): Outcome Tracking + basic trends + alerts (Task Groups 1-11, 14-17)
- Phase 2 (10 clients): Effectiveness scores + auto-adaptation (Task Groups 12-13)
- The auto_adaptation_enabled setting defaults to false — adaptation is opt-in after sufficient data accumulates
- numpy is the only new dependency (for linear regression)
- All Reddit API calls for karma checks use the existing shared PRAW client (not per-avatar proxied clients)
- Storage impact is minimal: ~22 KB/day at 10 clients for outcome records, ~2.5 MB total for effectiveness scores

## Task Dependency Graph

```json
{
  "waves": [
    {"tasks": ["1"]},
    {"tasks": ["2", "15"]},
    {"tasks": ["3", "5", "7", "8", "9"]},
    {"tasks": ["4", "6", "10", "12", "13"]},
    {"tasks": ["11", "14", "16", "17"]}
  ]
}
```
