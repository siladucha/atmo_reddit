# Tasks — RAMP Pipeline v2

**Roadmap:** MVP (Sprints 0-5) → Growth (Sprints 6-9)
**Timeline:** MVP = 6-8 weeks, Growth = 6-8 weeks after MVP

---

## Sprint 0: Technical Debt Cleanup (1-2 days)

### Task 0.1: Rename and consolidate safety constants
- [ ] In `app/services/phase.py`: rename `MAX_COMMENTS_PER_DAY` → `MAX_COMMENTS_PER_DAY_PHASE2 = 7`
- [ ] In `app/services/safety.py`: remove duplicate `MAX_COMMENTS_PER_DAY = 8` (will be replaced by BudgetEngine in Sprint 3)
- [ ] Verify all references to old constants are updated
- [ ] Run full test suite — fix any broken assertions

**Estimate:** 2h
**Files:** `app/services/phase.py`, `app/services/safety.py`, `tests/`

---

### Task 0.2: Verify get_setting() caching pattern
- [ ] Confirm `get_setting()` in `services/settings.py` handles missing keys gracefully (returns default)
- [ ] Add helper: `get_setting_int(db, key, default)` that casts to int with validation
- [ ] Write test: missing key → default; existing key → value; invalid int → default

**Estimate:** 1h
**Files:** `app/services/settings.py`, `tests/`

---

### Task 0.3: Ensure all hardcoded constants have TODO markers
- [ ] Grep for hardcoded values in safety.py, phase.py, scraping.py that will become configurable
- [ ] Add `# TODO(pipeline-v2): move to system_settings` comments
- [ ] No functional changes — just documentation for Sprint 2

**Estimate:** 30min
**Files:** `app/services/safety.py`, `app/services/phase.py`, `app/tasks/scraping.py`

---

## Sprint 1: Standalone Gates + Inline Editor (3-4 days)

### Task 1.1: Update Phase 2 daily limit
- [ ] In `app/services/phase.py` → `_check_phase2()`: use `MAX_COMMENTS_PER_DAY_PHASE2 = 7`
- [ ] Update tests that assert old value of 10
- [ ] Run phase policy tests

**Estimate:** 1h
**Requirements:** R12
**Files:** `app/services/phase.py`, `tests/`

---

### Task 1.2: Scrape Freshness Gate
- [ ] In `tasks/scraping.py` → `scrape_subreddit_shared()`, add freshness check before scraping:
  - Read `min_scrape_interval_minutes` from settings (hardcode default 30 for now, configurable in Sprint 2)
  - If `subreddit.last_scraped_at` is not NULL and elapsed < threshold: skip + log event
  - If NULL: proceed (never scraped)
- [ ] Log activity event type `"scrape_too_fresh"` with subreddit name and elapsed minutes
- [ ] Do NOT update `last_scraped_at` when skipped
- [ ] Add same gate to `scrape_professional_subreddits()` per-subreddit loop
- [ ] Write test: scraped 10 min ago → skipped; scraped 60 min ago → proceeds; NULL → proceeds

**Estimate:** 3h
**Requirements:** R8
**Files:** `app/tasks/scraping.py`

---

### Task 1.3: Inline Draft Editing (HTMX)
- [ ] Create `templates/partials/draft_editor.html`:
  - Textarea for `edited_draft`, character count, save/cancel buttons
  - Pre-populate with `ai_draft` if `edited_draft` is NULL
  - Visual warning at >1500 chars (yellow border, not blocking)
- [ ] Add route `GET /admin/drafts/{draft_id}/editor` → returns editor partial
- [ ] Add route `PUT /admin/drafts/{draft_id}/edited-draft` → saves field, returns updated card
- [ ] On save: record audit log entry (user_id, draft_id, timestamp)
- [ ] On HTMX error: show error indicator, retain unsaved text (client-side JS)
- [ ] Add "Edit" button to each draft card in review queue template
- [ ] Write test: save → persists; audit log created; ai_draft unchanged

**Estimate:** 6h
**Requirements:** R10
**Files:** `app/templates/partials/draft_editor.html`, `app/routes/admin.py`, `app/templates/admin_review.html`

---

## Sprint 2: Configurable Thresholds + Valkey Cache (5-6 days)

### Task 2.1: Seed pipeline_v2 system settings (Alembic migration)
- [ ] Create migration `seed_pipeline_v2_settings`
- [ ] Insert 10 keys with defaults (see design.md §7)
- [ ] Use `INSERT ... ON CONFLICT DO NOTHING` for idempotency
- [ ] Verify: runs on fresh DB and on DB with existing settings

**Estimate:** 1h
**Requirements:** All configurable settings
**Files:** `alembic/versions/`

---

### Task 2.2: Thread Freshness Filter
- [ ] In `services/scoring.py` → `score_unscored_threads_for_client()`:
  - Add filter: `COALESCE(RedditThread.created_at, RedditThread.scraped_at) >= cutoff`
  - Read `thread_max_age_hours` from settings (default 48)
- [ ] In `tasks/ai_pipeline.py` → `generate_comments()` engage_threads query:
  - Add same freshness filter
- [ ] Log batch activity event `"thread_too_old"` with count of excluded threads
- [ ] Write test: 24h thread → included; 72h thread → excluded; NULL created_at uses scraped_at

**Estimate:** 3h
**Requirements:** R3
**Files:** `app/services/scoring.py`, `app/tasks/ai_pipeline.py`

---

### Task 2.3: Configurable Subreddit Saturation + Logging
- [ ] In `services/safety.py` → `check_subreddit_limit()`:
  - Replace `MAX_COMMENTS_PER_SUBREDDIT_DAY = 2` with `get_setting_int(db, "max_comments_per_sub_per_day", 2)`
  - Include "pending" status in count (currently only approved/posted)
  - On limit hit: `record_activity_event(db, "saturation_limit_reached", ...)`
- [ ] Write test: configurable threshold; pending counted; event logged

**Estimate:** 2h
**Requirements:** R6
**Files:** `app/services/safety.py`

---

### Task 2.4: Configurable Cooldown + Valkey Cache
- [ ] In `services/safety.py` → cooldown check:
  - Replace `MIN_MINUTES_BETWEEN_COMMENTS = 15` with `get_setting_int(db, "min_comment_interval_minutes", 15)`
  - Add Valkey check: `GET cooldown:{avatar_id}` — if exists, in cooldown
  - After comment generation: `SET cooldown:{avatar_id} 1 EX {seconds}`
  - Fallback to DB if Valkey unavailable
- [ ] Write test: Valkey key present → blocked; absent → check DB; configurable interval

**Estimate:** 3h
**Requirements:** R13
**Files:** `app/services/safety.py`

---

### Task 2.5: Brand Ratio — 30-day window + Valkey cache
- [ ] In `services/safety.py` → brand ratio check:
  - Change window from 7 days to 30 days
  - Read threshold from `get_setting_int(db, "max_brand_ratio_percent", 30)`
  - Use `PhasePolicy.classify_brand_mention()` (text-based, not type-based)
  - Skip enforcement if total comments < 5 in window
  - Cache: `SET brand_ratio:{avatar_id} {ratio} EX 86400`
  - Check Valkey first, recalculate on miss
- [ ] Write test: above threshold → blocked; below → allowed; <5 comments → not enforced

**Estimate:** 4h
**Requirements:** R14
**Files:** `app/services/safety.py`, `app/services/phase.py`

---

## Sprint 3: Budget Engine + Dedup Service (5-6 days)

### Task 3.1: Budget Engine service
- [ ] Create `app/services/budget_engine.py` with `BudgetEngine` class
- [ ] `calculate_daily_limit(avatar)`:
  - `account_age_days` from `reddit_account_created` (fallback: `created_at`)
  - Formula: `min(floor(age/7), 10) + min(floor(karma/500), 5) + min(floor(cqs/20), 3)`
  - CQS NULL → 0
  - Phase cap: `min(formula, phase_cap)` — P1=3, P2=7, P3=uncapped
- [ ] `get_remaining_budget(db, avatar)`: limit - today's pending/approved/posted count
- [ ] `is_exhausted(db, avatar)`: remaining == 0
- [ ] `get_client_budget_summary(db, client_id)`: aggregate across active non-frozen avatars
- [ ] Cache in Valkey: `budget:{avatar_id}:{date}` TTL until midnight UTC
- [ ] Write tests: NULL age fallback, NULL CQS, Phase 1 cap, Phase 3 uncapped, exhaustion

**Estimate:** 6h
**Requirements:** R1
**Files:** `app/services/budget_engine.py`

---

### Task 3.2: Budget Dashboard UI
- [ ] Create `templates/partials/budget_dashboard.html`:
  - Table grouped by client
  - Per-avatar rows: name, limit, used, remaining, progress bar
  - Client-level aggregate row
  - Exhausted avatars highlighted red
- [ ] Add route `GET /admin/budget` → full page
- [ ] Add route `GET /admin/budget/panel` → HTMX partial (`hx-trigger="every 60s"`)
- [ ] Write test: endpoint returns correct data

**Estimate:** 4h
**Requirements:** R1
**Files:** `app/templates/partials/budget_dashboard.html`, `app/templates/admin_budget.html`, `app/routes/admin.py`

---

### Task 3.3: Cross-Avatar Deduplication service
- [ ] Create `app/services/dedup_service.py`
- [ ] `get_excluded_thread_ids(db, client_id, avatar_id)`:
  - Query comment_drafts: client_id match, avatar_id != current, status != "rejected"
  - "approved"/"posted": within `dedup_lookback_days` (default 30)
  - "pending": no time limit
  - Return set of thread_ids
- [ ] `log_dedup_exclusion(db, thread_id, blocked_avatar_id, existing_avatar_id)`: activity event
- [ ] Integrate into `tasks/ai_pipeline.py` → `generate_comments()`: filter engage_threads
- [ ] Write test: approved draft by avatar B → excluded for A; rejected → not excluded; old beyond lookback → not excluded

**Estimate:** 4h
**Requirements:** R2
**Files:** `app/services/dedup_service.py`, `app/tasks/ai_pipeline.py`

---

## Sprint 4: Safety Orchestration + Dashboard Panels (5-6 days)

### Task 4.1: Pre-Generation Safety Orchestrator
- [ ] In `services/safety.py`, create `run_pre_generation_checks(db, avatar, thread, client)`:
  - Order: phase_gate → budget → saturation → cooldown → brand_ratio
  - Stop at first failure
  - Log `"pre_generation_check_failed"` with check name, avatar_id, thread_id
  - Return SafetyCheckResult
- [ ] Refactor `tasks/ai_pipeline.py` → `generate_comments()`:
  - Replace separate `check_avatar_can_post()` + `check_subreddit_limit()` with `run_pre_generation_checks()`
  - Track skipped (avatar, thread) pairs in set — no retry in current run
- [ ] Write test: each check blocks; first failure stops; event logged; no retry

**Estimate:** 5h
**Requirements:** R7
**Files:** `app/services/safety.py`, `app/tasks/ai_pipeline.py`

---

### Task 4.2: Scoring Cost Preview
- [ ] In `services/budget_engine.py`, add `get_scoring_cost_preview(db, client_id)`:
  - Count unscored threads (no ThreadScore) that are fresh + not locked
  - Cost: `count * ((4000 * 0.075 / 1_000_000) + (200 * 0.30 / 1_000_000))`
  - Return `{unscored_count, estimated_cost_usd, eligible: bool}`
- [ ] Add route `POST /admin/budget/scoring-preview/{client_id}` → HTMX partial
- [ ] Add route `POST /admin/budget/execute-scoring/{client_id}` → triggers score_threads task
- [ ] Create `templates/partials/scoring_preview.html`: count, cost, Proceed/Cancel
- [ ] If count == 0: "No threads available", disable Proceed
- [ ] Write test: correct count/cost; zero → disabled

**Estimate:** 3h
**Requirements:** R4
**Files:** `app/services/budget_engine.py`, `app/routes/admin.py`, `app/templates/partials/scoring_preview.html`

---

### Task 4.3: Today's Activity Summary panel
- [ ] In `services/transparency.py`, add `get_today_activity_summary(db)`:
  - Query ActivityEvents for current UTC day
  - Group by avatar_id (from event_metadata)
  - Count: generated, approved, posted, scored, skipped (by reason)
- [ ] Add `get_avatar_today_timeline(db, avatar_id)`: chronological events (limit 100)
- [ ] Create `templates/partials/activity_summary.html`
- [ ] Add routes: `GET /admin/activity/today`, `GET .../panel` (hx-trigger="every 300s"), `GET .../avatar/{id}`
- [ ] Write test: summary aggregates correctly; timeline chronological

**Estimate:** 5h
**Requirements:** R9
**Files:** `app/services/transparency.py`, `app/templates/partials/activity_summary.html`, `app/routes/admin.py`

---

## Sprint 5: MVP Completion — Hill Tracking + Simple Reports (5-6 days)

### Task 5.1: Add hill_hook_used column (migration)
- [ ] Create Alembic migration: `ADD COLUMN hill_hook_used VARCHAR(255) NULL` to comment_drafts
- [ ] Update `app/models/comment_draft.py`
- [ ] Verify: migration runs, model loads, tests pass

**Estimate:** 30min
**Requirements:** R18
**Files:** `alembic/versions/`, `app/models/comment_draft.py`

---

### Task 5.2: Hill Tracker service
- [ ] Create `app/services/hill_tracker.py`
- [ ] `record_hook_usage(db, draft_id, hook_text)`: set `hill_hook_used` on draft
- [ ] `get_hook_ratio(db, avatar_id)`: count with hook / total (30-day, posted only)
- [ ] `get_hook_guidance(db, avatar_id)`: prompt instruction or None
  - Below 25%: "Naturally incorporate your key perspective..."
  - Above 35%: "Avoid your signature perspective this time..."
  - Between: None
- [ ] In `services/generation.py` → `generate_comment()`:
  - After generation: detect hook (check if `avatar.hill_i_die_on` substring in comment text)
  - Call `record_hook_usage()`
  - Before generation: call `get_hook_guidance()`, inject into prompt if not None
- [ ] Write test: hook detected → recorded; ratio correct; guidance at boundaries

**Estimate:** 5h
**Requirements:** R18
**Files:** `app/services/hill_tracker.py`, `app/services/generation.py`

---

### Task 5.3: Simple Client Report (template-based, no LLM)
- [ ] Create Alembic migration: `create_client_reports` table
- [ ] Create `app/models/client_report.py`
- [ ] Create `app/services/report_engine.py` with `ReportEngine`:
  - `generate_report(db, client_id, period_type, start, end)`:
    - Compile from DB: comments posted, karma gained, top subreddits, brand ratio, phase status
    - Compare to previous period (simple delta)
    - Render as markdown template (no LLM call — just data formatting)
    - Store as ClientReport record
  - `export_report(db, report_id, format)`: return markdown or JSON bytes
- [ ] Add routes: `GET /admin/clients/{id}/reports`, `POST .../generate`, `GET /admin/reports/{id}`, `GET .../export/{format}`
- [ ] Create `templates/admin_reports.html`: report list + viewer + generate button
- [ ] Write test: report generated with correct data; export works

**Estimate:** 8h
**Requirements:** R21 (simplified — no LLM forecast, no strategy sections)
**Files:** `app/models/client_report.py`, `app/services/report_engine.py`, `app/routes/admin.py`, `app/templates/admin_reports.html`, `alembic/versions/`

---

### Task 5.4: Integration test — MVP pipeline with all guards
- [ ] Write E2E test exercising full generation pipeline with v2 guards:
  - Test client + avatars (Phase 1, Phase 2, Phase 3)
  - Test threads (fresh, stale, locked)
  - Assert: Phase 1 → hobby only; stale → excluded; locked → excluded
  - Assert: budget exhaustion stops; saturation respected; cooldown enforced
  - Assert: dedup prevents double-comment; all skips logged
- [ ] Mock LLM responses
- [ ] Verify activity events have correct types/metadata

**Estimate:** 6h
**Requirements:** R1-R14 integration
**Files:** `tests/test_pipeline_v2_integration.py`

---

## ═══════════════════════════════════════════════════════
## GROWTH PHASE (post-MVP, after pilot feedback)
## ═══════════════════════════════════════════════════════

## Sprint 6: Analysis Services (6-8 days)

### Task 6.1: Mentor Analysis model + service
- [ ] Create migration: `create_mentor_analyses` table
- [ ] Create `app/models/mentor_analysis.py`
- [ ] In `services/strategy_engine.py` (create file), implement `analyze_mentor()`:
  - Fetch top 50 comments via PRAW
  - LLM analysis: tone, length, openings, topics, triggers
  - Store MentorAnalysis record
- [ ] Add routes + template for mentor analysis UI
- [ ] Write test with mocked PRAW + LLM

**Estimate:** 8h
**Requirements:** R16
**Files:** `app/models/mentor_analysis.py`, `app/services/strategy_engine.py`, `app/routes/admin.py`, `alembic/versions/`

---

### Task 6.2: Subreddit Analysis model + service
- [ ] Create migration: `create_subreddit_analyses` table
- [ ] Create `app/models/subreddit_analysis.py`
- [ ] In `services/strategy_engine.py`, implement `analyze_subreddit()`:
  - Fetch top 50 comments from all-time top posts
  - LLM analysis: tone, length, humor, expertise, formats, topics
  - Store SubredditAnalysis record (upsert)
- [ ] Add routes + template
- [ ] Write test with mocked PRAW + LLM

**Estimate:** 6h
**Requirements:** R17
**Files:** `app/models/subreddit_analysis.py`, `app/services/strategy_engine.py`, `app/routes/admin.py`, `alembic/versions/`

---

## Sprint 7: Strategy Document (8-10 days)

### Task 7.1: Strategy Document model + migration
- [ ] Create migration: `create_strategy_documents` table
- [ ] Create `app/models/strategy_document.py`
- [ ] Fields: avatar_id, goals, subreddit_priorities, tone_guidelines, cadence_rules, hook_inventory, forecast, document_md, version, generated_at, is_current, edited_by_user_id, edited_at

**Estimate:** 2h
**Requirements:** R15
**Files:** `app/models/strategy_document.py`, `alembic/versions/`

---

### Task 7.2: Strategy Document generation logic
- [ ] In `services/strategy_engine.py`, implement `generate_strategy_document()`:
  - Inputs: persona, subreddits, brand brief, phase, mentor/subreddit analyses
  - LLM prompt → structured output (goals, priorities, tone, cadence, hooks)
  - Mark previous as `is_current = False`, create new with `is_current = True`
- [ ] Implement `generate_forecast()`: karma trend projection, phase date, brand trajectory
- [ ] Write test: mock LLM → document created; versioning works

**Estimate:** 8h
**Requirements:** R15
**Files:** `app/services/strategy_engine.py`

---

### Task 7.3: Strategy Document admin UI
- [ ] Create `templates/admin_strategy.html`: viewer (goals, priorities, hooks, forecast)
- [ ] Routes: view, generate, edit, history
- [ ] Warning if no strategy doc exists
- [ ] Write test: generate creates doc; edit updates; history shows versions

**Estimate:** 5h
**Requirements:** R15
**Files:** `app/templates/admin_strategy.html`, `app/routes/admin.py`

---

### Task 7.4: Strategy as Pipeline Input
- [ ] In `services/generation.py` → `generate_comment()`:
  - Load current StrategyDocument (is_current=True, generated_at < 30 days)
  - If exists: inject tone, cadence, hooks, priorities into prompt
  - If not: base persona only + log warning
  - Include hook guidance from HillTracker
- [ ] Add strategy summary panel to review queue (visible during review)
- [ ] Write test: with doc → prompt enriched; without → base only; expired → base only

**Estimate:** 5h
**Requirements:** R25
**Files:** `app/services/generation.py`, `app/templates/`

---

## Sprint 8: Auto-Correction + Coordination (6-8 days)

### Task 8.1: Auto-Correction on negative performance
- [ ] In `services/strategy_engine.py`, implement `check_auto_correction()`:
  - Query last 3 posted drafts in subreddit where reddit_score IS NOT NULL
  - If all 3 ≤ 0: trigger LLM review
  - Analyze failures + subreddit patterns → update strategy doc
  - Log `"strategy_auto_corrected"` event
- [ ] Hook into karma tracking (when reddit_score updated)
- [ ] Add corrections history route
- [ ] Write test: 3 low → triggered; 2 low + 1 positive → not; NULL ignored

**Estimate:** 6h
**Requirements:** R19
**Files:** `app/services/strategy_engine.py`, `app/routes/admin.py`

---

### Task 8.2: Cross-Avatar Coordination service
- [ ] Create `app/services/coordination_service.py`
- [ ] `distribute_threads()`: weighted round-robin by remaining budget
  - 50% cap per avatar per subreddit
  - Tiebreaker: highest subreddit karma
  - Respect all constraints via `run_pre_generation_checks()`
- [ ] Integrate into `tasks/ai_pipeline.py` → replace sequential selection
- [ ] Write test: distribution by weight; 50% cap; constraints respected

**Estimate:** 6h
**Requirements:** R20
**Files:** `app/services/coordination_service.py`, `app/tasks/ai_pipeline.py`

---

## Sprint 9: Enhanced Scoring + Unified Reports (6-8 days)

### Task 9.1: scoring_metadata column + Enhanced Scoring
- [ ] Migration: add `scoring_metadata JSONB NULL` to thread_scores
- [ ] In `services/strategy_engine.py`, implement `apply_strategic_scoring()`:
  - +20% hill alignment, -30% repeat topic, +15% high history
- [ ] In `services/scoring.py`: apply after base scoring if valid strategy doc exists
- [ ] Store metadata on ThreadScore
- [ ] Write test: each bonus/penalty applied correctly; no doc → no adjustments

**Estimate:** 5h
**Requirements:** R22
**Files:** `app/services/strategy_engine.py`, `app/services/scoring.py`, `alembic/versions/`

---

### Task 9.2: Batch Scoring
- [ ] In `services/scoring.py`, implement `score_threads_batch()`:
  - Group into batches of `scoring_batch_size`
  - Single LLM call per batch, parse individual scores
  - Validate count preservation (N in → N out)
  - Fallback to individual on parse failure
- [ ] Replace individual scoring in `tasks/ai_pipeline.py`
- [ ] Track daily cost in Valkey, expose on budget dashboard
- [ ] Write test: batch → correct scores; count mismatch → fallback; cost tracked

**Estimate:** 6h
**Requirements:** R23
**Files:** `app/services/scoring.py`, `app/tasks/ai_pipeline.py`

---

### Task 9.3: Unified Client Report (LLM-enhanced)
- [ ] Enhance `services/report_engine.py`:
  - Add Strategy section (from StrategyDocument)
  - Add Forecast section (LLM-generated karma/phase projections)
  - Add "Questions for Client" (LLM-generated)
  - Add PDF export (markdown → PDF via weasyprint or similar)
- [ ] Update template to show all sections
- [ ] Write test: full report with all sections; PDF export

**Estimate:** 6h
**Requirements:** R24
**Files:** `app/services/report_engine.py`, `app/routes/admin.py`

---

### Task 9.4: Pipeline v2 Settings admin page
- [ ] Route `GET /admin/settings/pipeline-v2` → all pipeline_v2 settings
- [ ] Route `PUT /admin/settings/pipeline-v2` → HTMX inline edit
- [ ] Validate ranges on save
- [ ] Template: table with current values + edit buttons

**Estimate:** 3h
**Requirements:** All settings
**Files:** `app/routes/admin.py`, `app/templates/admin_settings_pipeline_v2.html`

---

## Summary

### MVP Delivery (Sprints 0-5): ~30-35 days

| Sprint | Days | Deliverable |
|--------|------|-------------|
| 0 | 1-2 | Tech debt cleanup |
| 1 | 3-4 | Phase limit + scrape gate + inline editor |
| 2 | 5-6 | Configurable thresholds + Valkey cache |
| 3 | 5-6 | Budget engine + dashboard + dedup |
| 4 | 5-6 | Safety orchestrator + cost preview + activity panel |
| 5 | 5-6 | Hill tracking + simple reports + integration test |

**MVP Result:** All operational guardrails (R1-R14) active, hill tracking (R18), basic client reports (R21 simplified), full integration test.

### Growth Delivery (Sprints 6-9): ~30-35 days

| Sprint | Days | Deliverable |
|--------|------|-------------|
| 6 | 6-8 | Mentor + subreddit analysis |
| 7 | 8-10 | Strategy document generation + pipeline integration |
| 8 | 6-8 | Auto-correction + cross-avatar coordination |
| 9 | 6-8 | Enhanced scoring + batch scoring + unified reports + settings UI |

**Growth Result:** Full strategic engine (R15-R25), LLM-powered strategy docs, auto-correction, enhanced scoring, unified reports with forecast.

### What's Deferred (not in this spec)
- PDF export (R24.5) — can use markdown-to-PDF library, add when client requests it
- Scheduled report delivery — manual trigger only for now
- A/B testing of strategies — future
- Vector memory — future
- Cross-avatar upvote coordination — explicitly deferred
