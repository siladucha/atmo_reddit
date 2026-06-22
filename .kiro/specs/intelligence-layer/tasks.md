# Implementation Plan: RAMP Intelligence Layer

## Overview

Implement the Intelligence Layer as an analytical subsystem that aggregates existing RAMP operational data, computes statistical baselines, detects anomalies, identifies trends, generates strategic observations, and produces actionable recommendations with a self-improving learning loop. Implementation uses Python 3.11+ / FastAPI / SQLAlchemy 2.0 / Celery + Redis / PostgreSQL 16.

## Tasks

- [ ] 1. Data models and Alembic migration
  - [ ] 1.1 Create SQLAlchemy models for Intelligence Layer tables
    - Create `app/models/intelligence/__init__.py` with all model imports
    - Create `app/models/intelligence/intelligence_event.py` with `IntelligenceEvent` model (UUID PK, client_id FK nullable, avatar_id FK nullable, event_category VARCHAR(50), event_type VARCHAR(100), payload JSONB, created_at TIMESTAMPTZ)
    - Create `app/models/intelligence/metric_baseline.py` with `MetricBaseline` model (UUID PK, entity_type VARCHAR(30), entity_id UUID nullable, metric_name VARCHAR(100), window_start DATE, window_end DATE, mean FLOAT, stddev FLOAT, trend_direction VARCHAR(20), trend_magnitude FLOAT, sample_count INTEGER, status VARCHAR(30) default "active", computed_at TIMESTAMPTZ)
    - Create `app/models/intelligence/intelligence_anomaly.py` with `IntelligenceAnomaly` model (UUID PK, entity_type VARCHAR(30), entity_id UUID, metric_name VARCHAR(100), observed_value FLOAT, expected_mean FLOAT, expected_stddev FLOAT, deviation_sigma FLOAT, severity VARCHAR(20), explanation TEXT, cluster_id UUID nullable, consecutive_count INTEGER default 1, detected_at TIMESTAMPTZ, resolved_at TIMESTAMPTZ nullable)
    - Create `app/models/intelligence/metric_trend.py` with `MetricTrend` model (UUID PK, entity_type VARCHAR(30), entity_id UUID, metric_name VARCHAR(100), window_days INTEGER, direction VARCHAR(20), magnitude FLOAT, acceleration FLOAT, confidence FLOAT, classification VARCHAR(20), consecutive_days INTEGER, threshold_warning JSONB nullable, computed_at TIMESTAMPTZ)
    - Create `app/models/intelligence/strategic_observation.py` with `StrategicObservation` model (UUID PK, client_id FK, observation_type VARCHAR(50), entity_scope JSONB, finding TEXT, supporting_data JSONB, confidence FLOAT, actionability_score FLOAT, generated_at TIMESTAMPTZ)
    - Create `app/models/intelligence/intelligence_recommendation.py` with `IntelligenceRecommendation` model (UUID PK, client_id FK, recommendation_type VARCHAR(50), target_entity_type VARCHAR(30), target_entity_id UUID, reasoning TEXT, confidence INTEGER CHECK 0-100, expected_impact JSONB, urgency VARCHAR(20), status VARCHAR(20) default "pending", source_anomaly_id FK nullable, source_trend_id FK nullable, source_observation_id FK nullable, decided_at TIMESTAMPTZ nullable, decided_by FK nullable, operator_notes TEXT nullable, created_at TIMESTAMPTZ, expires_at TIMESTAMPTZ nullable)
    - Create `app/models/intelligence/recommendation_outcome.py` with `RecommendationOutcome` model (UUID PK, recommendation_id FK UNIQUE, observation_start TIMESTAMPTZ, observation_end TIMESTAMPTZ, expected_metrics JSONB, actual_metrics JSONB, outcome_score FLOAT nullable, success BOOLEAN nullable, computed_at TIMESTAMPTZ nullable)
    - Create `app/models/intelligence/avatar_health_score.py` with `AvatarHealthScore` model (UUID PK, avatar_id FK, score_date DATE, health_index INTEGER CHECK 0-100, karma_component FLOAT, removal_component FLOAT, consistency_component FLOAT, compatibility_component FLOAT, age_component FLOAT, computed_at TIMESTAMPTZ, UNIQUE avatar_id+score_date)
    - Create `app/models/intelligence/intelligence_event_summary.py` with `IntelligenceEventSummary` model (UUID PK, summary_date DATE, client_id FK nullable, event_category VARCHAR(50), event_count INTEGER, avg_payload_values JSONB, created_at TIMESTAMPTZ, UNIQUE summary_date+client_id+event_category)
    - _Requirements: R1.5, R2.6, R3.6, R4, R5.6, R6.6, R7.5, R9.5, R12_

  - [ ] 1.2 Create Alembic migration for all Intelligence Layer tables
    - Single migration file: `intel_01_intelligence_layer_tables.py`
    - CREATE TABLE intelligence_events with indexes (category+created, client+created, avatar+created)
    - CREATE TABLE metric_baselines with unique index (entity_type, entity_id, metric_name, window_end)
    - CREATE TABLE intelligence_anomalies with indexes (entity+detected, severity, cluster_id)
    - CREATE TABLE metric_trends with unique index (entity_type, entity_id, metric_name, window_days)
    - CREATE TABLE strategic_observations with indexes (client+type, generated_at)
    - CREATE TABLE intelligence_recommendations with indexes (client+status, urgency, type+status)
    - CREATE TABLE recommendation_outcomes with unique index (recommendation_id)
    - CREATE TABLE avatar_health_scores with unique index (avatar_id, score_date) and index (health_index)
    - CREATE TABLE intelligence_event_summaries with unique index (summary_date, client_id, event_category)
    - Include downgrade operations (DROP ALL TABLEs)
    - _Requirements: R1.5, R2.6, R3.6, R5.6, R6.6, R7.5, R9.5, R12_

  - [ ] 1.3 Register new models in app model imports
    - Update `app/models/__init__.py` to import from `app/models/intelligence/`
    - Ensure all 9 models are discoverable by Alembic autogenerate
    - _Requirements: R1.5, R2.6, R3.6_

- [ ] 2. Intelligence Event Collector service
  - [ ] 2.1 Create intel_collector.py service
    - Create `app/services/intelligence/__init__.py`
    - Create `app/services/intelligence/intel_collector.py`
    - Implement `record_pipeline_event(db, operation, avatar_id, client_id, duration_ms, input_count, output_count, status)` — creates IntelligenceEvent with event_category="pipeline"
    - Implement `record_review_event(db, draft_id, decision, avatar_id, client_id, latency_seconds, edit_distance)` — creates IntelligenceEvent with event_category="review"
    - Implement `record_karma_event(db, snapshot, approach)` — creates IntelligenceEvent with event_category="karma"
    - Implement `record_health_event(db, avatar_id, client_id, old_state, new_state, trigger, signals)` — creates IntelligenceEvent with event_category="health"
    - All functions: wrap in try/except, log failures, never raise to caller
    - _Requirements: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6_

  - [ ] 2.2 Integrate collector hooks into existing services
    - Hook into `app/services/transparency.py::record_activity_event()` — call `record_pipeline_event` for pipeline events
    - Hook into `app/routes/review.py` approve/reject/edit handlers — call `record_review_event`
    - Hook into `app/tasks/snapshot_outcomes.py` after karma snapshot — call `record_karma_event`
    - Hook into `app/services/karma_feedback.py` state change functions — call `record_health_event`
    - All hooks: non-blocking, failures logged but do not affect source workflow
    - _Requirements: R1.1, R1.2, R1.3, R1.4, R1.6_

- [ ] 3. Metric Baseline Engine
  - [ ] 3.1 Create intel_baseline.py service
    - Create `app/services/intelligence/intel_baseline.py`
    - Implement `compute_baselines_for_entity(db, entity_type, entity_id)` — queries 30 days of intelligence_events, computes weighted mean/stddev with exponential decay (lambda=0.1), determines trend via linear regression
    - Implement `compute_all_baselines(db)` — iterates all active avatars, clients, and platform-wide; calls compute_baselines_for_entity for each
    - Implement `get_baseline(db, entity_type, entity_id, metric_name)` — retrieves most recent baseline for given entity+metric
    - Handle insufficient_data: if sample_count < 7, set status="insufficient_data"
    - Tracked metrics: karma_per_comment, removal_rate, approval_rate, engagement_velocity, posting_frequency, subreddit_response_rate, review_latency
    - _Requirements: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6_

  - [ ] 3.2 Write property tests for baseline computation
    - Property: weighted mean with uniform weights equals arithmetic mean
    - Property: stddev is always non-negative
    - Property: exponential decay weights sum to approximately 1 when normalized
    - Property: trend_direction is "stable" when all values are identical
    - Property: insufficient_data status when sample_count < 7
    - _Validates: R2.1, R2.2, R2.3, R2.4_

- [ ] 4. Anomaly Detection Engine
  - [ ] 4.1 Create intel_anomaly.py service
    - Create `app/services/intelligence/intel_anomaly.py`
    - Implement `detect_anomalies(db)` — for each entity+metric with active baseline, compute current value, check z-score, create anomaly if |z| > 2
    - Implement `check_metric_for_anomaly(db, entity_type, entity_id, metric_name, current_value)` — single metric check against baseline
    - Implement `cluster_anomalies(db, new_anomalies)` — group anomalies for same entity within 24h window, assign shared cluster_id
    - Implement `escalate_persistent_anomalies(db)` — find unresolved anomalies with 3+ consecutive occurrences, bump severity (warning→critical)
    - Implement `resolve_anomaly(db, anomaly_id)` — set resolved_at=now
    - Generate explanation text: include metric name, observed value, expected range (mean ± 2*stddev), and potential cause mapping
    - _Requirements: R3.1, R3.2, R3.3, R3.4, R3.5, R3.6_

  - [ ] 4.2 Write property tests for anomaly detection
    - Property: value within 2σ of mean never produces anomaly
    - Property: value beyond 3σ always produces critical severity
    - Property: severity classification is deterministic (same inputs → same output)
    - Property: cluster_id groups anomalies for same entity within 24h
    - _Validates: R3.1, R3.4, R3.5_

- [ ] 5. Trend Analysis Engine
  - [ ] 5.1 Create intel_trends.py service
    - Create `app/services/intelligence/intel_trends.py`
    - Implement `analyze_trends(db)` — compute 7d and 30d trend vectors for all entities+metrics
    - Implement `compute_trend_vector(values, window_days)` — returns direction, magnitude, acceleration, confidence, classification
    - Classification logic: 5+ consecutive same-direction → "emerging"; 14+ days → "established"; otherwise "none"
    - Implement `check_threshold_intersection(db, trend)` — extrapolate trend line, check known thresholds (karma_drop=-2, removal_rate=0.30, frequency=8)
    - Generate threshold_warning JSON: {threshold_name, current_value, threshold_value, estimated_days_to_breach}
    - _Requirements: R4.1, R4.2, R4.3, R4.4, R4.5_

  - [ ] 5.2 Write property tests for trend analysis
    - Property: monotonically increasing sequence → direction is "improving" for positive metrics
    - Property: constant sequence → direction is "stable" and magnitude is 0
    - Property: classification is "emerging" only when consecutive_days >= 5
    - Property: magnitude is invariant to uniform scaling of values (percentage-based)
    - _Validates: R4.1, R4.2, R4.3, R4.4_

- [ ] 6. Avatar Health Index
  - [ ] 6.1 Create intel_health_index.py service
    - Create `app/services/intelligence/intel_health_index.py`
    - Implement `compute_health_index(db, avatar)` — compute 5 components, apply weights (25/25/15/20/15), clamp to [0, 100]
    - karma_component: avg karma per comment in last 14d, normalized to [0, 100] against platform average
    - removal_component: (1 - removal_rate_14d) * 100
    - consistency_component: (1 - coefficient_of_variation_of_daily_posts) * 100, clamped [0, 100]
    - compatibility_component: weighted avg of per-subreddit karma / platform avg, normalized [0, 100]
    - age_component: min(100, (account_age_days / 365) * 50 + (total_karma / 1000) * 30 + phase * 20)
    - Implement `compute_all_health_indices(db)` — iterate active unfrozen avatars
    - _Requirements: R9.1, R9.5_

  - [ ] 6.2 Write property tests for health index
    - Property: health_index is always in [0, 100] for any combination of component values
    - Property: all components contribute exactly their weight percentage (sum of weights = 100)
    - Property: higher karma and lower removal rate always produce higher health_index
    - _Validates: R9.1_

- [ ] 7. Recommendation Engine
  - [ ] 7.1 Create intel_recommendations.py service
    - Create `app/services/intelligence/intel_recommendations.py`
    - Implement `generate_recommendations(db)` — evaluate anomalies, trends, health indices; generate recommendations with type, reasoning, confidence, urgency
    - Implement recommendation type mapping: critical anomaly (removal_rate) → reduce_activity; trend (declining karma approaching threshold) → change_strategy; health < 40 → reduce_activity; health < 20 → reduce_activity (critical urgency)
    - Implement `act_on_recommendation(db, recommendation_id, user_id, decision, notes)` — update status, decided_at, decided_by, operator_notes
    - Implement `expire_stale_recommendations(db)` — expire pending recommendations older than 14 days
    - Implement cap enforcement: check pending count per client, if >= 10 only insert if urgency > lowest existing
    - _Requirements: R6.1, R6.2, R6.3, R6.4, R6.5, R6.6_

  - [ ] 7.2 Write property tests for recommendation engine
    - Property: pending recommendations per client never exceed 10
    - Property: every recommendation has non-empty reasoning field
    - Property: confidence is always in [0, 100]
    - Property: urgency ordering is maintained (critical > high > medium > low)
    - _Validates: R6.1, R6.3, R6.4_

- [ ] 8. Learning Loop
  - [ ] 8.1 Create intel_learning.py service
    - Create `app/services/intelligence/intel_learning.py`
    - Implement `start_outcome_tracking(db, recommendation_id)` — create RecommendationOutcome with observation_start=now, observation_end=now+7days, expected_metrics from recommendation.expected_impact
    - Implement `close_observation_windows(db)` — find outcomes past observation_end without computed_at, query actual metrics, compute outcome_score, set success
    - Implement `compute_recommendation_accuracy(db, recommendation_type, window_days=30)` — percentage of successful outcomes in window
    - Implement `adjust_confidence_multipliers(db)` — if accuracy < 50% for a type, flag and reduce multiplier by 20%
    - _Requirements: R7.1, R7.2, R7.3, R7.4, R7.5_

  - [ ] 8.2 Write property tests for learning loop
    - Property: accepted recommendation always creates exactly one outcome record
    - Property: observation_end equals observation_start + 7 days
    - Property: accuracy is always in [0.0, 1.0] range
    - Property: confidence multiplier decreases by 20% when accuracy drops below 50%
    - _Validates: R7.1, R7.2, R7.3, R7.4_

- [ ] 9. Strategic Observations (LLM-assisted)
  - [ ] 9.1 Create intel_strategy.py service
    - Create `app/services/intelligence/intel_strategy.py`
    - Implement `generate_weekly_observations(db)` — orchestrates all observation types for each active client
    - Implement `compare_subreddit_performance(db, client_id)` — query karma/removal/engagement per subreddit, produce ranked comparison finding
    - Implement `analyze_approach_effectiveness(db, client_id)` — query karma by engagement approach (from draft metadata), identify best/worst approaches per subreddit
    - Implement `analyze_avatar_subreddit_fit(db, client_id)` — correlate avatar performance with subreddit, identify best avatar-subreddit pairings
    - Implement `correlate_competitor_presence(db, client_id)` — if GEO data exists, correlate competitor mentions with client performance in same subs
    - Implement `rank_pain_points(db, client_id)` — aggregate opportunity scores by topic/pain-point, rank by engagement quality
    - Use Gemini Flash for synthesis: input structured metrics JSON, output natural language finding
    - _Requirements: R5.1, R5.2, R5.3, R5.4, R5.5, R5.6_

- [ ] 10. Query Service and API
  - [ ] 10.1 Create intel_query.py service
    - Create `app/services/intelligence/intel_query.py`
    - Implement `get_anomalies(db, entity_type, entity_id, severity, time_range, limit, after_id)` with cursor-based pagination
    - Implement `get_trends(db, entity_type, entity_id, metric_name, limit)` with filtering
    - Implement `get_recommendations(db, client_id, entity_type, entity_id, status, limit, after_id)` with cursor pagination
    - Implement `get_health_index(db, avatar_id)` — latest score
    - Implement `get_health_history(db, avatar_id, days)` — time series
    - Implement `get_strategic_observations(db, client_id, observation_type, limit)`
    - Implement `get_dashboard_summary(db, client_id)` — aggregated counts and key metrics
    - _Requirements: R10.1, R10.4_

  - [ ] 10.2 Create Intelligence API routes
    - Create `app/routes/intelligence.py`
    - GET `/api/intelligence/anomalies` — paginated anomaly list with filters (entity_type, severity, time range)
    - GET `/api/intelligence/trends` — paginated trend list with filters
    - GET `/api/intelligence/recommendations` — paginated recommendations with filters (status, urgency)
    - GET `/api/intelligence/health/{avatar_id}` — avatar health index + 30d history
    - GET `/api/intelligence/observations` — paginated strategic observations
    - GET `/api/intelligence/summary` — dashboard summary (counts, key metrics)
    - All endpoints: RBAC via query_scope (client users see only their data), 403 on unauthorized entity access
    - Register router in `app/main.py`
    - _Requirements: R10.2, R10.3, R10.4, R10.5_

- [ ] 11. Celery Tasks
  - [ ] 11.1 Create intelligence Celery tasks
    - Create `app/tasks/intelligence.py`
    - Task `compute_intelligence_baselines` — calls `intel_baseline.compute_all_baselines(db)`
    - Task `detect_intelligence_anomalies` — calls `intel_anomaly.detect_anomalies(db)` + `cluster_anomalies` + `escalate_persistent_anomalies`
    - Task `analyze_intelligence_trends` — calls `intel_trends.analyze_trends(db)`
    - Task `generate_strategic_observations` — calls `intel_strategy.generate_weekly_observations(db)`
    - Task `process_intelligence_learning` — calls `intel_learning.close_observation_windows(db)` + `adjust_confidence_multipliers`
    - Task `compute_avatar_health_indices` — calls `intel_health_index.compute_all_health_indices(db)`, then generates recommendations for health < 40 and < 20
    - Task `archive_intelligence_data` — purge events > 90d (after computing summaries), purge resolved anomalies > 90d, purge baselines > 365d
    - All tasks: retry with exponential backoff (max 3), emit ActivityEvent on failure
    - _Requirements: R11.1, R11.2, R11.3, R11.4, R11.5, R11.6, R12.1, R12.2, R12.3, R12.5, R12.6_

  - [ ] 11.2 Register intelligence tasks in Celery Beat schedule
    - Add to worker.py beat_schedule: compute_intelligence_baselines at 03:00
    - Add: detect_intelligence_anomalies every 4h at :50 (03:50, 07:50, 11:50, 15:50, 19:50, 23:50)
    - Add: analyze_intelligence_trends at 03:30
    - Add: generate_strategic_observations crontab(day_of_week=1, hour=4, minute=0)
    - Add: process_intelligence_learning at 04:00
    - Add: compute_avatar_health_indices at 04:30
    - Add: archive_intelligence_data crontab(day_of_week=0, hour=2, minute=0)
    - _Requirements: R11.1, R11.2, R11.3, R11.4, R11.5, R12.6_

- [ ] 12. Intelligence Dashboard (Admin UI)
  - [ ] 12.1 Create intelligence dashboard page and partials
    - Create `app/templates/admin_intelligence.html` — main dashboard extending admin_base.html with tab layout (Anomalies | Trends | Observations | Recommendations | Health | Learning)
    - Create `app/templates/partials/intelligence_anomalies.html` — anomaly list with severity badges, entity links, explanation, filter controls (client, severity, time range)
    - Create `app/templates/partials/intelligence_trends.html` — trend summary cards with direction arrows, magnitude, classification badges, threshold warnings highlighted
    - Create `app/templates/partials/intelligence_observations.html` — observation cards with finding text, confidence, actionability, supporting data expandable
    - Create `app/templates/partials/intelligence_recommendations.html` — recommendation list with urgency badges, type icons, action buttons (accept/reject/defer)
    - Create `app/templates/partials/intelligence_recommendation_detail.html` — full detail view with reasoning, supporting data, related anomalies/trends, decision form
    - Create `app/templates/partials/intelligence_health.html` — avatar health grid with score badges, color coding (green > 60, yellow 40-60, red < 40), link to avatar detail
    - Create `app/templates/partials/intelligence_learning.html` — accuracy stats per recommendation type, bar chart, confidence multiplier table
    - _Requirements: R8.1, R8.2, R8.3, R8.4, R8.5, R8.6_

  - [ ] 12.2 Create intelligence admin routes
    - Add intelligence routes to `app/routes/intelligence.py` (or separate `app/routes/admin_intelligence.py`)
    - GET `/admin/intelligence` — render main dashboard page (requires platform_admin)
    - GET `/admin/intelligence/anomalies` — HTMX partial with query params (client_id, severity, days)
    - GET `/admin/intelligence/trends` — HTMX partial
    - GET `/admin/intelligence/observations` — HTMX partial with client filter
    - GET `/admin/intelligence/recommendations` — HTMX partial with status/urgency filters
    - GET `/admin/intelligence/recommendations/{id}` — HTMX partial recommendation detail
    - POST `/admin/intelligence/recommendations/{id}/decide` — form handler for accept/reject/defer + trigger outcome tracking on accept
    - GET `/admin/intelligence/health` — HTMX partial avatar health overview
    - GET `/admin/intelligence/learning` — HTMX partial learning loop stats
    - Add navigation link to admin_base.html sidebar
    - _Requirements: R8.1, R8.2, R8.3, R8.4, R8.5, R8.6_

- [ ] 13. Data Retention and Archival
  - [ ] 13.1 Implement archival logic in intelligence tasks
    - In `archive_intelligence_data` task: compute daily summaries for events older than 90 days (group by date+client+category, count events, avg numeric payload values)
    - Insert summaries into intelligence_event_summaries table
    - Delete intelligence_events older than 90 days (batch delete, 1000 per batch to avoid lock contention)
    - Delete resolved intelligence_anomalies older than 90 days
    - Delete metric_baselines with window_end older than 365 days
    - Delete metric_trends with computed_at older than 180 days
    - Keep recommendations and outcomes indefinitely (learning loop integrity)
    - Log archival stats as ActivityEvent
    - _Requirements: R12.1, R12.2, R12.3, R12.4, R12.5, R12.6_

- [ ] 14. Integration and End-to-End Testing
  - [ ] 14.1 Write integration tests for the full intelligence pipeline
    - Test: pipeline event → baseline computation → anomaly detection → recommendation generation
    - Test: recommendation accept → outcome tracking → observation window close → accuracy update
    - Test: health index computation triggers recommendation when score < 40
    - Test: archival preserves summary data while removing raw events
    - Test: RBAC enforcement on API endpoints (client users cannot see other clients' data)
    - Test: cap enforcement (11th recommendation for same client triggers expire of lowest priority)
    - _Validates: R1-R12 end-to-end_
