# Implementation Plan: Trial Conversion Intelligence

## Overview

This plan implements the Trial Conversion Intelligence system — a deterministic scoring engine with AI interpretation layer for trial accounts. The system collects signals, computes scores without LLM involvement, and provides on-demand AI-generated sales intelligence to Owner/Partner users.

**Total tasks:** 16 (sequential with some parallelism possible after Task 1)
**Estimated effort:** 5-7 days
**Dependencies:** Existing Client model, trial_guard.py, ai.py (LiteLLM), admin_base.html, RBAC system

## Tasks

- [x] 1. Data Models & Alembic Migration
  - [x] 1.1 Create `app/models/trial_signal.py` — TrialSignal model (UUID pk, client_id FK, signal_type VARCHAR(50), signal_category VARCHAR(30), signal_value JSONB, created_at TIMESTAMPTZ). Indexes: (client_id, created_at), (client_id, signal_category)
  - [x] 1.2 Create `app/models/trial_score.py` — TrialScore model (UUID pk, client_id FK, conversion_score INT CHECK 0-100, priority_score INT CHECK 0-100, opportunity_value_cents INT CHECK >=0, recommended_action TEXT, score_explanation JSONB, signal_snapshot JSONB, lifecycle_state VARCHAR(20), scored_at TIMESTAMPTZ). Index: (client_id, scored_at DESC)
  - [x] 1.3 Create `app/models/trial_failure.py` — TrialFailure model (UUID pk, client_id FK UNIQUE, failure_category VARCHAR(30), ai_analysis TEXT nullable, ai_analysis_status VARCHAR(10) default "pending", reactivation_recommended BOOLEAN, win_back_window_days INT nullable, next_best_action TEXT nullable, reactivation_confidence FLOAT nullable, classified_at TIMESTAMPTZ)
  - [x] 1.4 Create `app/models/trial_sales_summary.py` — TrialSalesSummary model (UUID pk, client_id FK, score_id FK to trial_scores, sales_summary_version INT, content TEXT, cached_until TIMESTAMPTZ, generated_at TIMESTAMPTZ)
  - [x] 1.5 Create `app/models/trial_intelligence_event.py` — TrialIntelligenceEvent model (UUID pk, client_id FK, user_id FK, event_type VARCHAR(30), event_metadata JSONB nullable, created_at TIMESTAMPTZ). Index: (client_id, created_at DESC)
  - [x] 1.6 Create Alembic migration `add_trial_conversion_intelligence_tables` with all 5 tables, indexes, CHECK constraints
  - [x] 1.7 Register all models in `app/models/__init__.py`

- [x] 2. Signal Collector Service
  - [x] 2.1 Create `app/services/trial_signals.py` with SignalCollector class
  - [x] 2.2 Implement `record_signal(client_id, signal_type, signal_category, signal_value)` — checks plan_type="trial", stores with Asia/Jerusalem timestamp, 60s dedup window (same type+client)
  - [x] 2.3 Implement retry-once-on-db-error (2s delay), then discard without blocking caller
  - [x] 2.4 Implement daily cap (500 signals per client per day)
  - [x] 2.5 Implement `is_trial_client(client_id)` helper — returns False for non-trial clients (short-circuits signal recording)

- [x] 3. Negative Signal Detector
  - [x] 3.1 Create `app/services/trial_negative_signals.py` with NegativeSignalDetector class
  - [x] 3.2 Implement `detect_inactivity_72h(client_id)` — checks last signal timestamp > 72h ago
  - [x] 3.3 Implement `detect_multiple_short_sessions(client_id)` — 3+ sessions < 30s within 24h window
  - [x] 3.4 Implement `detect_pricing_without_upgrade(client_id)` — pricing_page_viewed signal exists, no return within 24h
  - [x] 3.5 Implement `detect_onboarding_abandoned(client_id)` — onboarding_started but not onboarding_completed within 48h
  - [x] 3.6 Implement `detect_removed_keywords(client_id)` — keyword removal event
  - [x] 3.7 Implement `detect_export_without_return(client_id)` — export signal followed by no activity for 48h
  - [x] 3.8 Implement `detect_report_no_scroll(client_id)` — report_opened with scroll_pct < 10%
  - [x] 3.9 Create Celery task `check_trial_negative_signals` (scheduled every 4h) for time-based negative detections

- [x] 4. Deterministic Scoring Engine
  - [x] 4.1 Create `app/services/trial_scoring.py` with ScoringEngine class
  - [x] 4.2 Implement `compute_conversion_score(signals)` — weighted sum (Engagement 20%, Intent 25%, Value_Realization 25%, Conversion 20%, Negative penalty -10% to -30%), clamped 0-100
  - [x] 4.3 Implement `compute_opportunity_value(client)` — company size to plan tier mapping (1-10 emp → $149/mo, 11-50 → $399, 51-200 → $799, 201+ → $1499) × 12 months
  - [x] 4.4 Implement `compute_priority_score(conversion_score, opportunity_value, days_remaining)` — formula: 45% conversion + 25% normalized_value + 30% urgency, clamped 0-100
  - [x] 4.5 Implement `build_score_explanation(signals)` — returns top 5 positive + top 5 negative signals with numeric contribution values
  - [x] 4.6 Implement `determine_recommended_action(score, days_remaining, lifecycle_state, last_signal_at)` — select from: send_welcome_email, schedule_discovery_call, send_value_summary, send_upgrade_offer, send_reactivation_nudge
  - [x] 4.7 Implement `build_signal_snapshot(signals)` — serialize all signals into reproducible JSONB
  - [x] 4.8 Store configurable weights in SystemSetting (key: `trial_scoring_weights`, default JSON with category percentages)

- [x] 5. Lifecycle State Machine
  - [x] 5.1 Create `app/services/trial_lifecycle.py` with LifecycleFSM class
  - [x] 5.2 Define valid transitions map for 9 states (trial_started, onboarding_started, activated, engaged, high_intent, at_risk, expired, converted, reactivated)
  - [x] 5.3 Implement `evaluate_state(client_id, signals, current_state)` — evaluates transition rules, returns new state or same state
  - [x] 5.4 Implement all transition rules per design (trial_started→onboarding_started on wizard begin, activated→engaged on meaningful usage, etc.)
  - [x] 5.5 Emit ActivityEvent on every state transition (event_type="trial_lifecycle_change")

- [x] 6. Debounce Manager & Recompute Task
  - [x] 6.1 Create `app/services/trial_debounce.py` with DebounceManager class (Redis SET NX, 60s TTL)
  - [x] 6.2 Implement `should_recompute(client_id)` — returns True if no active key, False if debounced
  - [x] 6.3 Implement `clear(client_id)` — deletes debounce key after recompute completes
  - [x] 6.4 Create `app/tasks/trial_scoring.py` with Celery task `recompute_trial_score(client_id)` — loads signals, computes scores, evaluates lifecycle, stores TrialScore, emits events
  - [x] 6.5 Add Redis distributed lock per client_id (5s TTL) to prevent concurrent recomputes
  - [x] 6.6 Implement score change detection (>10 points → emit ActivityEvent + IntelligenceEvent)
  - [x] 6.7 Fallback: if Redis unavailable, always trigger recompute

- [ ] 7. Signal Collection Hooks (Route Integration)
  - [-] 7.1 Create `app/middleware/trial_signals.py` — lightweight middleware for trial user page view detection
  - [ ] 7.2 Add signal hooks to onboarding routes (onboarding_completed on wizard finish)
  - [ ] 7.3 Add signal hooks to portal routes (report_viewed, discovery_run, opportunity_reviewed)
  - [ ] 7.4 Add signal hooks to pricing/upgrade routes (pricing_page_viewed, upgrade_screen_opened, upgrade_cta_clicked)
  - [ ] 7.5 Add signal hooks to keyword management (removed_keywords on deletion)
  - [ ] 7.6 Add signal hooks to export and login routes
  - [ ] 7.7 After each signal recording, check debounce and dispatch recompute task if needed
  - [ ] 7.8 Ensure all hooks are fire-and-forget (never block the user request)

- [ ] 8. Sales Summary Generator
  - [ ] 8.1 Create `app/services/trial_summary.py` with SalesSummaryGenerator class
  - [ ] 8.2 Implement `generate_summary(client_id, score_id)` — builds prompt from score snapshot, calls Claude Sonnet via LiteLLM, returns 5-section briefing
  - [ ] 8.3 Implement cache logic: check TrialSalesSummary for matching score_id → return cached if match
  - [ ] 8.4 Implement cache invalidation: regenerate when score_id differs, increment version
  - [ ] 8.5 Enforce 15s timeout, return error on failure (do NOT cache failed results)
  - [ ] 8.6 Handle insufficient data (<3 signals): return structured "insufficient data" response
  - [ ] 8.7 Handle missing onboarding data: generate from signals, note gap in "problems" section

- [ ] 9. Outreach Generator
  - [ ] 9.1 Create `app/services/trial_outreach.py` with OutreachGenerator class
  - [ ] 9.2 Implement `generate_outreach(client_id, score_id)` — produces 4 drafts (email, LinkedIn, followup, call notes)
  - [ ] 9.3 Implement tone selection by Conversion_Score (>70 urgency, 40-70 curiosity, <40 soft re-engagement)
  - [ ] 9.4 Enforce character limits (email 2000, LinkedIn 300, followup 1000, call notes 1500)
  - [ ] 9.5 Enforce 20s timeout, return error with retry option on failure
  - [ ] 9.6 Implement `log_copy_event(client_id, user_id, draft_type)` — creates copied_outreach IntelligenceEvent
  - [ ] 9.7 NO auto-send capability — text-only output with copy-to-clipboard UI

- [ ] 10. Failure Analyzer
  - [ ] 10.1 Create `app/services/trial_failure.py` with FailureAnalyzer class
  - [ ] 10.2 Implement `classify_failure(client_id)` — deterministic rules in priority order (no_engagement, product_confusion, wrong_icp, no_value_discovered, no_urgency, budget_issue, unknown)
  - [ ] 10.3 Implement free-email-domain detection (gmail, yahoo, hotmail, outlook, protonmail)
  - [ ] 10.4 Implement `generate_reactivation_intel(client_id, failure)` — LLM call for win_back_window_days, next_best_action, confidence
  - [ ] 10.5 Handle LLM timeout (30s): store classification with ai_analysis_status="failed"
  - [ ] 10.6 Create Celery task `classify_expired_trials` (daily at 02:00) — finds newly expired trials, classifies each

- [ ] 11. Intelligence Event Logger
  - [ ] 11.1 Create `app/services/trial_events.py` with IntelligenceEventLogger class and IntelligenceEventType StrEnum
  - [ ] 11.2 Implement `log_event(client_id, user_id, event_type, metadata)` — stores TrialIntelligenceEvent record
  - [ ] 11.3 Implement `get_events(client_id, limit=20)` — returns recent events for detail view
  - [ ] 11.4 Integrate auto-logging into SalesSummaryGenerator, OutreachGenerator, and ScoringEngine

- [ ] 12. RBAC & Access Control
  - [ ] 12.1 Create `app/dependencies/trial_intelligence.py` with `require_owner_or_partner` FastAPI dependency
  - [ ] 12.2 Verify user.role in {"owner", "partner"}, raise HTTPException(403) otherwise
  - [ ] 12.3 Log denied access attempts to AuditLog (action="access_denied", entity_type="trial_intelligence")
  - [ ] 12.4 Ensure trial intelligence data excluded from portal query_scope

- [ ] 13. Trial Dashboard Routes
  - [ ] 13.1 Create `app/routes/trial_intelligence.py` with FastAPI router (prefix `/admin/trial-intelligence`)
  - [ ] 13.2 Implement `GET /admin/trial-intelligence` — main dashboard page (active trials sorted by Priority_Score)
  - [ ] 13.3 Implement `GET /admin/trial-intelligence/expired` — expired trials tab with failure analysis
  - [ ] 13.4 Implement `GET /admin/trial-intelligence/funnel` — funnel visualization HTMX partial
  - [ ] 13.5 Implement `GET /admin/trial-intelligence/{client_id}` — trial detail view
  - [ ] 13.6 Implement `POST /admin/trial-intelligence/{client_id}/summary` — generate/cache sales summary
  - [ ] 13.7 Implement `POST /admin/trial-intelligence/{client_id}/outreach` — generate outreach drafts
  - [ ] 13.8 Implement `POST /admin/trial-intelligence/{client_id}/mark-contacted` + `schedule-followup` + `copy-outreach` — action endpoints
  - [ ] 13.9 Support query params: sort_by, filter_activity, filter_state, days_min, days_max
  - [ ] 13.10 Apply `require_owner_or_partner` to all routes, register router in `app/main.py`

- [ ] 14. Dashboard Templates (Jinja2 + HTMX)
  - [ ] 14.1 Create `app/templates/admin_trial_intelligence.html` — main dashboard (extends admin_base.html dark theme) with tabs: Active, Expired, Funnel
  - [ ] 14.2 Create `app/templates/partials/trial_table.html` — sortable table (client name, domain, signup, days remaining, lifecycle state, activity, scores, action)
  - [ ] 14.3 Create `app/templates/partials/trial_funnel.html` — state funnel visualization (counts per lifecycle state)
  - [ ] 14.4 Create `app/templates/partials/trial_summary_row.html` — summary stats (total, avg score, pipeline $, funnel distribution)
  - [ ] 14.5 Create `app/templates/admin_trial_detail.html` — detail view with signal timeline, score history, explanation, action buttons
  - [ ] 14.6 Create `app/templates/partials/trial_explanation.html` — expandable score explanation (top 5 positive + negative)
  - [ ] 14.7 Create `app/templates/partials/trial_summary_result.html` — generated sales summary display
  - [ ] 14.8 Create `app/templates/partials/trial_outreach_result.html` — 4 outreach drafts with copy buttons
  - [ ] 14.9 Create `app/templates/partials/trial_events_feed.html` — recent intelligence events feed
  - [ ] 14.10 Create `app/templates/admin_trial_expired.html` — expired trials with categories, AI analysis, reactivation intel
  - [ ] 14.11 Add "Trial Intelligence" link in admin_base.html sidebar (visible only to Owner/Partner roles)

- [ ] 15. Celery Beat Schedule Integration
  - [ ] 15.1 Add `check_trial_negative_signals` to Beat schedule (every 4h at :30)
  - [ ] 15.2 Add `classify_expired_trials` to Beat schedule (daily at 02:00)
  - [ ] 15.3 Add `cleanup_old_trial_data` to Beat schedule (weekly Sunday 05:00) — deletes signals/scores/failures > 180 days past trial expiry
  - [ ] 15.4 Register tasks in worker config

- [ ] 16. Integration Testing & Verification
  - [ ] 16.1 Test signal → debounce → score → dashboard end-to-end flow
  - [ ] 16.2 Test RBAC: verify HTTP 403 for all non-owner/partner roles
  - [ ] 16.3 Test lifecycle transitions: walk all 9 states with appropriate signals
  - [ ] 16.4 Test negative signals: verify score decreases when negatives added
  - [ ] 16.5 Test LLM cache: generate summary → same score_id → cached returned
  - [ ] 16.6 Test failure classification: expired trial with known pattern → correct category
  - [ ] 16.7 Test debounce: 10 rapid signals → only 1 recompute dispatched
  - [ ] 16.8 Test determinism: same signal snapshot → identical scores on repeated computation


## Notes

- Tasks 2-5 and 8-12 can be developed in parallel after Task 1 completes
- Tasks 13-14 depend on services being available (Tasks 2-12)
- Task 15 wires up scheduled execution
- Task 16 validates the full system end-to-end
- LLM costs per trial: ~$0.04 per summary + ~$0.06 per outreach + ~$0.02 per failure analysis = ~$0.12 per trial lifetime
- All scoring is deterministic — no LLM in the scoring loop
