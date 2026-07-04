# Forecast & Reporting Layer v1 — Tasks

## Phase 1: Observed Reality Collector + Report Model (3-4 days)

### Task 1: Database Migration
- [x] Create migration `frl01`: `client_intelligence_reports`, `forecast_accuracy_log`, `observed_snapshots` tables
- [x] Add indexes per design schema
- [x] Unique constraints on (client_id, report_period, report_version)

### Task 2: Models
- [x] Create `app/models/intelligence_report.py` — ClientIntelligenceReport model
- [x] Create `app/models/forecast_accuracy.py` — ForecastAccuracyLog model
- [x] Create `app/models/observed_snapshot.py` — ObservedSnapshot model
- [x] Register in `app/models/__init__.py`

### Task 3: Observed Reality Collector Service
- [x] Create `app/services/forecast/observed_reality.py`
- [x] Implement `ObservedRealityCollector.collect(db, client_id)` → `ObservedSnapshot`
- [x] `_collect_geo_metrics()` — query GeoQueryResult for latest batch, compute per-engine rates
- [x] `_collect_reddit_metrics()` — karma avg, survival rate, reply depth from KarmaSnapshot
- [x] `_collect_execution_metrics()` — drafts generated/posted/deleted from CommentDraft
- [x] `_collect_competitor_metrics()` — competitor rates from GeoQueryResult.competitors_mentioned
- [x] `_collect_category_metrics()` — per-category rates via GeoPrompt.category JOIN
- [x] `_identify_gaps()` — what sources are missing or stale
- [x] `_extract_brand_excerpts()` — find actual AI response text where brand_mentioned=true

### Task 4: Basic Report Composer (Layer 1 only)
- [x] Create `app/services/forecast/report_composer.py`
- [x] `compose_observed_report(db, client_id)` → stores ClientIntelligenceReport (observed_json only)
- [x] Populate data_freshness_json from source timestamps
- [x] Status = 'draft' on creation

---

## Phase 2: Visibility Forecaster + Scenarios (2-3 days)

### Task 5: S-Curve Forecast Engine
- [x] Create `app/services/forecast/visibility_forecaster.py`
- [x] Implement logistic S-curve with per-engine multipliers
- [x] `forecast(observed, intent, platform_risk)` → `VisibilityForecast`
- [x] 3 scenarios: conservative (ceiling×0.7, midpoint+2), expected, optimistic (ceiling×1.2, midpoint-2)
- [x] Per-engine projections using ENGINE_MULTIPLIERS
- [x] Noise generation (seeded for reproducibility per report)

### Task 6: Platform Risk Assessment
- [x] Create `app/services/forecast/platform_risk.py`
- [x] `PlatformRiskAssessment.compute(observed, intent)` → discount_factor
- [x] Factors: avatar_health_score, removal_rate_trend, subreddit_risk_avg, account_age
- [x] Composite discount applied to forecast ceiling

### Task 7: Integrate Forecast into Report
- [x] Update `report_composer.py` to populate `forecasted_json`
- [x] Add ScenarioTriple for 4w/12w/24w horizons
- [x] Add gap-to-leader calculation (from competitor metrics)
- [x] Add model metadata (name, parameters, assumptions list)

---

## Phase 3: Intent Snapshot + Full Report + Accuracy (3-4 days)

### Task 8: Intent Snapshot Collector
- [x] Create `app/services/forecast/intent_snapshot.py`
- [x] `collect_intent(db, client_id)` → `IntentSnapshot`
- [x] Collect from: EPGSlot (today/tomorrow), CommentDraft (pending/approved), Beat schedule
- [x] Phase roadmap from Avatar phase + promotion criteria
- [x] Subreddit coverage from ClientSubredditAssignment

### Task 9: Risk Section Assembly
- [x] Add `_assemble_risks()` to report_composer
- [x] Platform risk factors with impact-on-forecast statements
- [x] Sensitivity items (what happens if assumptions are wrong)
- [x] Data gap listing + stale data warnings
- [x] Output as `risks_json`

### Task 10: Forecast Accuracy Tracking
- [x] Create `app/services/forecast/accuracy_tracker.py`
- [x] On report generation: write ForecastAccuracyLog entries for each projected metric
- [x] Weekly task: compare predictions to actuals (when new GEO batch arrives)
- [x] Compute error_pp, within_bounds for each past prediction
- [x] Feed results into model parameter adjustment (widen/narrow confidence)

### Task 11: Full 5-Layer Report Composition
- [x] Update `compose_full_report(db, client_id)` to populate all 5 JSONB fields
- [x] Add `business_impact_json` (category rank, gap closure, ROI framing)
- [x] ClientSuccessModel derivation from client.plan_type + competitive position
- [x] Report version management (supersede old drafts)

---

## Phase 4: Portal Integration + Automation (2-3 days)

### Task 12: Client Portal Template
- [x] Create `app/templates/client/intelligence_report.html`
- [x] 5 visual sections matching design template (📍/📋/📈/⚠️/💰)
- [x] Solid vs dashed visual distinction (measured vs projected)
- [x] Trend chart with Chart.js (embedded, no CDN for portal)
- [x] Competitor bar chart
- [x] Responsive layout

### Task 13: Portal Route
- [x] Add route `/clients/{id}/report/weekly` → renders latest published report
- [x] Add route `/clients/{id}/report/history` → list of past reports
- [x] RBAC: client_viewer+ can view, client_admin+ can trigger regeneration
- [x] HTMX lazy-load for chart sections

### Task 14: Weekly Automated Generation
- [x] Create `app/tasks/intelligence_report.py`
- [x] `generate_weekly_reports_all_clients` Celery task
- [x] Beat schedule: Monday 08:00 (after weekend pipeline, before Tue GEO batch)
- [x] Only generates for clients with geo_monitoring_enabled + ≥1 completed batch
- [x] Publishes report + optionally sends notification to client

### Task 15: Admin UI
- [x] Add report overview to admin client detail page
- [x] Manual trigger: "Generate Report Now" button
- [x] View raw JSONB for debugging
- [x] Forecast accuracy dashboard (hit/miss rates over time)

---

## Phase 5: Business Impact + Polish (1-2 days)

### Task 16: Business Impact Calculator
- [x] Create `app/services/forecast/business_impact.py`
- [x] Category rank computation (client position among competitors)
- [x] Gap closure rate (pp/week based on trend)
- [x] Weeks-to-parity estimation (when expected scenario reaches leader)
- [x] ROI framing (investment/month ÷ projected gain = cost per point)
- [x] Measurable vs inferred distinction

### Task 17: Demo Report Dynamic Generation
- [x] Refactor `demo/share-of-voice.html` to be generated from report JSONB
- [x] Or: create `/demo/report/{client_id}` route that renders demo-style from real data
- [x] noindex, no auth (for sales calls only, URL shared manually)

---

## Dependencies

| Task | Depends On | Blocks |
|------|-----------|--------|
| T1 (migration) | None | T2, T3 |
| T2 (models) | T1 | T3, T4 |
| T3 (collector) | T2 | T4, T5 |
| T4 (basic report) | T3 | T7 |
| T5 (forecaster) | T3 | T7 |
| T6 (risk) | T3 | T7 |
| T7 (integrate) | T4, T5, T6 | T11 |
| T8 (intent) | T2 | T11 |
| T9 (risks) | T6, T8 | T11 |
| T10 (accuracy) | T2, T7 | T15 |
| T11 (full report) | T7, T8, T9 | T12 |
| T12 (template) | T11 | T13 |
| T13 (route) | T12 | T14 |
| T14 (automation) | T13 | None |
| T15 (admin) | T10, T13 | None |
| T16 (business) | T11 | T17 |
| T17 (demo) | T16 | None |
