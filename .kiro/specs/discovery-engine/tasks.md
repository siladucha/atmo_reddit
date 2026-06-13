# Implementation Plan: Discovery Engine

## Overview

Implementation of the Discovery Engine — a pre-engagement layer that analyzes client business context, forms hypotheses about Reddit ecosystem relevance, researches Reddit for evidence, and produces a Visibility Report as a sales artifact. Covers data models, core services (entity extraction, hypothesis formation, confidence scoring, Reddit research), report generation, strategy handoff, admin UI with HTMX flow, cost tracking, and tests.

## Tasks

- [x] 1. Create Discovery Models
  - [x] 1.1. Create `app/models/discovery_session.py` — DiscoverySession model (UUID PK, client_id FK nullable, operator_user_id FK, client_brief, prospect_name, status enum, current_iteration, timestamps, abandon_reason, session_metadata JSONB, total_ai_cost_usd)
  - [x] 1.2. Create `app/models/discovery_entity.py` — DiscoveryEntity model (UUID PK, session_id FK CASCADE, name, category enum, source enum, created_at)
  - [x] 1.3. Create `app/models/discovery_hypothesis.py` — DiscoveryHypothesis model (UUID PK, session_id FK CASCADE, iteration_number, statement, category enum, confidence_score, confidence_delta, status enum, classification, provenance JSONB, reddit_signals JSONB, rejection_reason, timestamps)
  - [x] 1.4. Create `app/models/visibility_report.py` — VisibilityReport model (UUID PK, session_id FK CASCADE, content JSONB, generated_at, operator_notes, report_version, model_used, generation_cost_usd)
  - [x] 1.5. Register all models in `app/models/__init__.py`
- [x] 2. Alembic Migration
  - [x] 2.1. Create migration: `discovery_sessions` table with indexes on client_id and operator_user_id
  - [x] 2.2. Create migration: `discovery_entities` table with index on session_id
  - [x] 2.3. Create migration: `discovery_hypotheses` table with unique constraint (session_id, iteration_number, statement) and composite index (session_id, status)
  - [x] 2.4. Create migration: `visibility_reports` table with index on session_id
  - [x] 2.5. Add `discovery_session_id` nullable UUID FK column to `strategy_documents` table
  - [x] 2.6. Verify migration runs cleanly up and down
- [x] 3. Pydantic Schemas
  - [x] 3.1. Create `app/schemas/discovery.py` with EntityExtractionOutput, HypothesisFormationOutput, RedditSignalOutput, VisibilityReportContent, SessionCreateRequest, and HypothesisDecision validation schemas
- [x] 4. Entity Extractor Service
  - [x] 4.1. Create `app/services/discovery/__init__.py`
  - [x] 4.2. Create `app/services/discovery/entity_extractor.py` with `extract_entities(client_brief, db, session_id)` that calls Gemini Flash via `call_llm_json()`, builds extraction prompt for business analyst role, handles LLM response parsing + validation (3-20 entities, correct categories), handles edge case <3 entities, logs AI usage with sub-type "entity_extraction", stores entities in DB and returns list
- [x] 5. Hypothesis Engine Service
  - [x] 5.1. Create `app/services/discovery/hypothesis_engine.py` with `form_hypotheses(entities, session, prior_hypotheses, rejection_context)` that calls Gemini Flash, builds hypothesis prompt with entities/confirmed directions/rejection reasons/exclusion list, validates output (3-7 hypotheses with quantifiable Reddit metric and correct category), handles retry if <3 returned, handles dedup, assigns initial confidence_score=50, stores provenance JSONB, logs AI usage with sub-type "hypothesis_formation", returns stored hypothesis records
- [x] 6. Confidence Scorer Service
  - [x] 6.1. Create `app/services/discovery/confidence_scorer.py` with `score_hypothesis(hypothesis, signals)` implementing pure Python scoring rules: ≥20 posts + ≥10 avg engagement → +10 to +30, <5 posts OR <3 avg engagement → -10 to -30, both fail → score=15 with no_signal. Generate confidence_reasoning text, calculate confidence_delta, implement No-Signal classification (search_too_narrow → adjacent terms, topic_absent → alternative platforms)
- [x] 7. Reddit Researcher Service
  - [x] 7.1. Create `app/services/discovery/reddit_researcher.py` with `research_hypothesis(hypothesis, entities)` using PRAW: extract search terms from hypothesis + entity names, subreddit search (limit=10), for each subreddit get subscriber count + recent posts (.hot limit=25) + 30-day volume estimate + avg engagement + topic relevance score, reuse rate limiting, broader search for no-signal, return structured reddit_signals dict, handle Reddit API errors gracefully
- [x] 8. Celery Research Task
  - [x] 8.1. Create `app/tasks/discovery.py` with `research_hypotheses_task(session_id, hypothesis_ids)` Celery task: process hypotheses sequentially with rate limiting, update session_metadata research_progress, apply confidence scoring after each, 120s soft timeout, mark remaining as research_failed on timeout, register in worker.py, set retry policy (bind=True, max_retries=2, default_retry_delay=30)
- [x] 9. Report Generator Service
  - [x] 9.1. Create `app/services/discovery/report_generator.py` with `generate_visibility_report(session)` using Claude Sonnet via `call_llm()`: build report prompt with confirmed hypotheses + reddit_signals + entities + client_brief, request all sections (exec summary, demand, communities, activity, entry points, competitive landscape, outcomes, risks), parse into structured JSONB, 60s timeout, log AI usage with sub-type "report_generation", store report with version number, update session status to completed
- [x] 10. Strategy Handoff Service
  - [x] 10.1. Create `app/services/discovery/strategy_handoff.py` with `prepare_handoff_context(session)` and `execute_handoff(session, db)`: create Client if no client_id, link session to client, pre-populate subreddit suggestions, set discovery_session_id on StrategyDocument, log discovery_handoff ActivityEvent
  - [x] 10.2. Modify `strategy_engine.py` → `generate_strategy()` to accept optional `discovery_context` dict parameter and inject into prompt when present; add "Based on Discovery" section to `_render_strategy_md`
- [x] 11. Session Manager Service
  - [x] 11.1. Create `app/services/discovery/session_manager.py` with create_session, get_session (eager-loaded), list_sessions (paginated, sorted desc), abandon_session (state validation), advance_iteration (max 5 validation), update_ai_cost (atomic increment)
- [x] 12. Route Setup
  - [x] 12.1. Create `app/routes/discovery.py` — FastAPI router with prefix `/admin/discovery`, register in `app/main.py`, apply `require_platform_admin` dependency
  - [x] 12.2. Implement GET /admin/discovery (session list, paginated 25/page), GET /admin/discovery/new (form), POST /admin/discovery/new (create + entity extraction → entity review partial), GET /admin/discovery/{session_id} (active session page)
- [x] 13. Iteration Flow Routes
  - [x] 13.1. Implement POST /admin/discovery/{id}/entities (confirm/edit entities → hypothesis formation → hypotheses partial)
  - [x] 13.2. Implement POST /admin/discovery/{id}/research (trigger Celery task → progress partial) and GET /admin/discovery/{id}/progress (HTMX poll endpoint)
  - [x] 13.3. Implement POST /admin/discovery/{id}/decide (confirm/reject decisions → next iteration or report prompt)
  - [x] 13.4. Implement POST /admin/discovery/{id}/report (generate report → report partial), POST /admin/discovery/{id}/report/edit (save notes), GET /admin/discovery/{id}/report/export (branded HTML)
  - [x] 13.5. Implement POST /admin/discovery/{id}/handoff (strategy handoff) and POST /admin/discovery/{id}/abandon (mark abandoned)
- [x] 14. Templates — Pages
  - [x] 14.1. Create `templates/admin_discovery.html` (session list with "New Discovery" button, extends admin_base.html)
  - [x] 14.2. Create `templates/admin_discovery_session.html` (active session container with progress bar, sidebar info, #discovery-content swap target)
  - [x] 14.3. Add "Discovery" link to admin sidebar navigation (between Dashboard and Clients)
- [x] 15. Templates — Partials
  - [x] 15.1. Create `templates/partials/discovery_brief_form.html` (textarea 5000 char max with live counter, client name field, optional client dropdown, submit button)
  - [x] 15.2. Create `templates/partials/discovery_entities.html` (entities grouped by category, editable chips, add/remove, confirm button)
  - [x] 15.3. Create `templates/partials/discovery_hypotheses.html` (hypothesis cards with statement, category badge, confidence bar, Fact/Choice badge)
  - [x] 15.4. Create `templates/partials/discovery_research_progress.html` (per-hypothesis progress dots, hx-trigger="every 2s")
  - [x] 15.5. Create `templates/partials/discovery_results.html` (research results per hypothesis: confidence bar with delta, reddit_signals table, no-signal indicator, confirm/reject buttons with reason field)
  - [x] 15.6. Create `templates/partials/discovery_report.html` (rendered report sections, operator notes textarea, export button, "Create Strategy" handoff button)
  - [x] 15.7. Create `templates/partials/discovery_report_export.html` (clean white-background branded template for print/PDF with TOC and sections)
- [x] 16. Client Detail Integration
  - [x] 16.1. Add "Discovery History" section to client detail page with linked sessions (date, status, iteration count, link to report) and "Start Discovery" button that pre-fills client_id
- [x] 17. Cost Integration
  - [x] 17.1. Ensure all Discovery LLM calls use log_ai_usage() with operation="discovery" and triggered_by=session_id; update admin_ai_costs() route to include "discovery" as filterable operation; add per-session cost display and Discovery cost line item on AI costs page
- [x] 18. Running Cost Display
  - [x] 18.1. On active session page show running total "$X.XX spent this session", update after each LLM call via HTMX oob swap or session page refresh
- [x] 19. Unit Tests
  - [x] 19.1. Create `tests/test_entity_extractor.py` — mock LLM responses, verify entity parsing, edge cases (<3 entities, malformed JSON)
  - [x] 19.2. Create `tests/test_confidence_scorer.py` — verify scoring rules with known inputs (strong signal, weak signal, no signal, narrow, absent)
  - [x] 19.3. Create `tests/test_hypothesis_engine.py` — mock LLM, verify dedup, retry logic, category assignment
  - [x] 19.4. Create `tests/test_session_manager.py` — state transitions, pagination, validation
  - [x] 19.5. Create `tests/test_strategy_handoff.py` — verify Client creation, FK linkage, ActivityEvent logging, subreddit pre-population
- [x] 20. Integration Tests
  - [x] 20.1. Create `tests/test_discovery_flow.py` — full flow with mocked LLM + mocked PRAW: session → entities → hypotheses → research → confirm/reject → report → handoff
  - [x] 20.2. Create `tests/test_discovery_routes.py` — HTTP tests: auth enforcement, HTMX partial responses, validation errors, form preservation on error

## Task Dependency Graph

```json
{
  "waves": [
    {"tasks": [1, 2, 3]},
    {"tasks": [4, 5, 6]},
    {"tasks": [7, 8]},
    {"tasks": [9, 10, 11]},
    {"tasks": [12, 13]},
    {"tasks": [14, 15, 16, 17, 18]},
    {"tasks": [19, 20]}
  ]
}
```

## Notes

- Entity extraction uses Gemini Flash (fast, cheap ~$0.0003/call)
- Hypothesis formation uses Gemini Flash
- Report generation uses Claude Sonnet (high-quality prose for sales artifact)
- Reddit research uses existing PRAW infrastructure (no new dependencies)
- Confidence scoring is pure Python (no LLM calls)
- All LLM costs tracked under operation="discovery" for economic model validation
- Total estimated AI cost per Discovery session: ~$0.07
- Admin UI follows existing dark theme (admin_base.html) with HTMX partials
- Maximum 5 iterations per session
- Visibility Report serves as $4K setup fee deliverable


---

## Sprint 1: Tzvi Demo Readiness (2 days)

> Priority: Give Tzvi a shareable results URL + instant demo + working resume.
> Depends on: All core tasks (1-20) already complete.

- [ ] 21. Shareable Results Page
  - [ ] 21.1. Add `share_token` UUID column to `discovery_sessions` table (nullable, Alembic migration)
  - [ ] 21.2. Create public route `GET /discovery/results/{session_id}` (no auth) that validates `?token=<share_token>`, returns 404 if invalid
  - [ ] 21.3. Create `templates/discovery_results_public.html` — branded report view (same content as export, but with RAMP footer, no admin nav, responsive)
  - [ ] 21.4. Add "Copy Share Link" button to admin session view (`POST /{id}/share` generates token if not exists, returns shareable URL)
  - [ ] 21.5. Add "Revoke Share" button (`DELETE /{id}/share` nullifies token)
  - [ ] 21.6. Test: public URL works without auth; invalid token returns 404; revoked token returns 404

- [ ] 22. Demo Seed Session
  - [ ] 22.1. Create `app/services/discovery/demo_seed.py` — `create_demo_session(db, operator_id)` that inserts realistic pre-seeded data (cybersecurity SaaS client, 6 entities, 5 hypotheses with reddit_signals/confidence, Visibility Report JSONB)
  - [ ] 22.2. Add "Demo Discovery" button to session list page (`POST /admin/discovery/demo`)
  - [ ] 22.3. Enforce max 3 demo sessions — delete oldest if over limit
  - [ ] 22.4. Mark demo sessions with `session_metadata.is_demo = true`; exclude from AI cost aggregation
  - [ ] 22.5. Verify all session steps render correctly with seeded data (entities, hypotheses, results, report, export)

- [ ] 23. Session Resume Fix
  - [ ] 23.1. Audit `SessionManager.get_current_step()` — fix edge case where research task died mid-flight (hypotheses with `status=proposed` + stale `research_progress` in metadata older than 5 min)
  - [ ] 23.2. Add "Research was interrupted — Resume?" banner when stale research detected (HTMX button re-dispatches `research_hypotheses_task` for hypotheses without `reddit_signals`)
  - [ ] 23.3. Fix edge case: all hypotheses decided + no report yet → display "Generate Report" / "Start Next Iteration" choice clearly
  - [ ] 23.4. Test: navigate away mid-research → return → see correct state; refresh after entity confirm but before hypothesis → see entity review

- [ ] 24. "Create Strategy" Button Polish
  - [ ] 24.1. Verify handoff route creates Client (if prospect-only) with correct fields populated from brief + report
  - [ ] 24.2. After handoff: redirect to client detail page (already implemented — verify it works end-to-end)
  - [ ] 24.3. Add success toast on client page: "Strategy created from Discovery session"

- [ ] 25. Export HTML Polish
  - [ ] 25.1. Audit `discovery_report_export.html` — verify all report sections render (exec_summary, demand, communities, activity, entry_points, competitive, outcomes, risks)
  - [ ] 25.2. Add print-friendly CSS: `@media print` rules, page breaks between sections, hide non-essential UI
  - [ ] 25.3. Add "Download PDF" instruction text (Ctrl+P / Cmd+P) or integrate html2pdf.js for one-click

## Sprint 2: Platform Hardening (3 days)

> Priority: Cache, cost visibility, state machine robustness, research persistence.

- [ ] 26. Research Result Caching
  - [ ] 26.1. Create `discovery_cache` table (subreddit_name, search_terms_hash, signals JSONB, fetched_at, ttl_hours default 24)
  - [ ] 26.2. In `reddit_researcher.py` — check cache before PRAW call; if cache hit < TTL → return cached; else fetch + store
  - [ ] 26.3. Display cache hit/miss in research progress partial (badge: "cached" vs "live")
  - [ ] 26.4. Admin setting `discovery_cache_ttl_hours` (default 24) to control staleness

- [ ] 27. AI Cost Panel
  - [ ] 27.1. On active session page: display per-step cost breakdown (entity extraction: $X, hypothesis N: $X, research: $0, report: $X)
  - [ ] 27.2. Compute and show estimated remaining cost ("~$0.03 for report generation")
  - [ ] 27.3. On session list: show total cost per session column

- [ ] 28. State Machine Hardening
  - [ ] 28.1. Implement explicit `SessionState` enum with valid transitions: `in_progress → completed | abandoned`
  - [ ] 28.2. Add DB-level CHECK constraint on `status` column
  - [ ] 28.3. Reject any operation on completed/abandoned sessions (return 409 Conflict)
  - [ ] 28.4. Add `locked_at` field — lock session during Celery research to prevent concurrent operations

- [ ] 29. Research Persistence & Retry
  - [ ] 29.1. Store research task_id on session (`session_metadata.celery_task_id`)
  - [ ] 29.2. On session page load: if task_id exists + hypotheses have no signals → check Celery task state (SUCCESS/FAILURE/PENDING)
  - [ ] 29.3. If task FAILURE: show "Research failed — Retry" button
  - [ ] 29.4. If task PENDING > 5 min: show "Research stalled — Retry" with timeout warning

## Sprint 3: Avatar Discovery Profile (4 days)

> Priority: Profile Reddit accounts for avatar onboarding validation.

- [ ] 30. Avatar Discovery Profile Model
  - [ ] 30.1. Create `app/models/avatar_discovery_profile.py` — AvatarDiscoveryProfile (UUID PK, avatar_id FK, version, observed_interests JSONB, active_subreddits JSONB, expertise_areas JSONB, participation_style JSONB, health_indicators JSONB, deception_risk_score int, niche_fit_score int, scanned_at, profile_data JSONB full snapshot)
  - [ ] 30.2. Alembic migration with index on (avatar_id, scanned_at DESC)

- [ ] 31. Reddit Account Profiler Service
  - [ ] 31.1. Create `app/services/discovery/account_profiler.py` — `profile_reddit_account(username, db)`: fetch last 1000 posts/comments via PRAW, extract interests (ranked, confidence weights), active communities (per-sub metrics), expertise areas (vocabulary + karma concentration), participation style (frequency, tone, type, depth)
  - [ ] 31.2. Use Gemini Flash for interest/expertise classification from post text (batch: send 20 representative posts → get structured output)
  - [ ] 31.3. Handle insufficient data (< 10 posts) → mark as `insufficient_data`
  - [ ] 31.4. Handle suspended/deleted accounts → return error

- [ ] 32. Declared vs Observed Comparison
  - [ ] 32.1. Create `app/services/discovery/deception_detector.py` — `compare_declared_observed(avatar, profile)`: compare `hobby_subreddits` vs observed, `voice_profile_md` vs participation_style, compute deception_risk_score (0-100)
  - [ ] 32.2. Classification per attribute: confirmed / partial_match / contradicted / unverifiable
  - [ ] 32.3. Generate mismatch report with specific evidence citations

- [ ] 33. Niche Fit Scoring
  - [ ] 33.1. Create `app/services/discovery/niche_fit.py` — `compute_niche_fit(avatar, profile, client)`: subreddit overlap (jaccard), topic vocabulary match (keyword intersection), engagement pattern similarity → composite 0-100
  - [ ] 33.2. Store as `niche_fit_score` on AvatarDiscoveryProfile

- [ ] 34. Avatar Discovery UI
  - [ ] 34.1. Add "Analyze Reddit Account" button to avatar detail page (Actions tab)
  - [ ] 34.2. Create `templates/partials/avatar_discovery_profile.html` — observed interests, subreddits, expertise, style, deception score, niche fit
  - [ ] 34.3. Route: `POST /admin/avatars/{id}/discover` → triggers profiling → `GET /admin/avatars/{id}/discovery-profile` returns partial
  - [ ] 34.4. Show declared vs observed comparison table with color-coded match status

- [ ] 35. Avatar Discovery Tests
  - [ ] 35.1. Test profiler with mocked PRAW response (sufficient data, insufficient data, suspended)
  - [ ] 35.2. Test deception detector (full match, partial, contradiction)
  - [ ] 35.3. Test niche fit (perfect overlap, zero overlap, partial)

## Sprint 4: Continuous Discovery & EPG Feed (2 weeks)

> Priority: Delta detection, auto-strategy updates, EPG opportunity injection.

- [ ] 36. Periodic Re-scan Task
  - [ ] 36.1. Create Celery Beat task `rescan_active_avatars` (every 72h configurable) — for each active avatar with a profile, re-run account_profiler, compute delta against last snapshot
  - [ ] 36.2. Store new version in `avatar_discovery_profiles` with delta_summary JSONB
  - [ ] 36.3. Configurable via system setting `discovery_rescan_interval_hours` (default 72, min 24, max 168)

- [ ] 37. Delta Detection & Alerts
  - [ ] 37.1. Create `app/services/discovery/delta_detector.py` — compare current vs previous profile: interest shifts, community migrations, expertise changes, style shifts
  - [ ] 37.2. Define "significant delta" threshold: 3+ interest weight shifts > 0.2, OR new expertise detected, OR community abandoned (30+ days inactive)
  - [ ] 37.3. On significant delta: create ActivityEvent (type="discovery_delta") + admin notification
  - [ ] 37.4. Suggest strategy review when delta contradicts current strategy direction

- [ ] 38. EPG Opportunity Injection
  - [ ] 38.1. After re-scan: identify threads in avatar's subreddits that match updated profile's top interests + client keywords → create pre-scored Opportunity records for EPG 2.0
  - [ ] 38.2. Mark opportunities with `source="discovery_continuous"` to distinguish from scoring pipeline
  - [ ] 38.3. EPG `scan_opportunities()` already reads from Opportunity table — verify integration works

- [ ] 39. Attribution Layer (Source of Truth)
  - [ ] 39.1. Create `app/models/attribution_record.py` — AttributionRecord (recommended_action_id FK to EPGSlot, reported_status, observed_reddit_entity_id, observed_at, attribution_confidence float, outcome_metrics JSONB)
  - [ ] 39.2. On EPGSlot.status → "posted": create AttributionRecord with recommended layer
  - [ ] 39.3. On karma outcome check: update observed layer (actual_karma, is_removed)
  - [ ] 39.4. Compute attribution_confidence (timing proximity + content similarity + target match)

- [ ] 40. Explainability Coverage Metric
  - [ ] 40.1. For each EPG slot: check if traceable to Discovery observation OR Strategy directive → compute daily explainability_coverage per avatar
  - [ ] 40.2. Store in Performance_Metrics table (if < 80% for 7 days → alert)
  - [ ] 40.3. Display on avatar Portfolio tab

- [ ] 41. Auto-Strategy Suggestion
  - [ ] 41.1. When continuous discovery detects opportunity cluster in a subreddit not currently assigned to client → suggest "Add r/X to strategy" notification
  - [ ] 41.2. When zero_day_rate > 50% for 14 days + discovery shows active relevant threads → suggest "Review subreddit assignments"
  - [ ] 41.3. Log suggestions as ActivityEvents for operator review

## Sprint Dependency Graph

```json
{
  "sprints": [
    {"id": 1, "tasks": [21, 22, 23, 24, 25], "duration": "2 days", "blocker": "none"},
    {"id": 2, "tasks": [26, 27, 28, 29], "duration": "3 days", "blocker": "Sprint 1"},
    {"id": 3, "tasks": [30, 31, 32, 33, 34, 35], "duration": "4 days", "blocker": "Sprint 2"},
    {"id": 4, "tasks": [36, 37, 38, 39, 40, 41], "duration": "2 weeks", "blocker": "Sprint 3"}
  ]
}
```

## Sprint 1 Success Criteria (Tzvi Demo)

- [ ] Tzvi can click "Demo Discovery" → see instant results (no waiting)
- [ ] Tzvi can copy a share link → open in incognito → see branded report
- [ ] Tzvi can Cmd+P on export page → get clean PDF
- [ ] Operator can resume any interrupted session without data loss
- [ ] "Create Strategy" button works end-to-end (prospect → client → strategy)
