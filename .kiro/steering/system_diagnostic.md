# System Diagnostic JSON — Reference

## Truth Layer Classification

**This file is an ARCHITECTURAL REFERENCE (static).** It is NOT a source of current state.

For current system state → `.kiro/state/current.yaml` (CSS)
For reconciliation rules → `.kiro/steering/truth_resolution.md`
For conflict resolution → ops > system > steering > CSS

## Location

`/RAMP_SYSTEM_DIAGNOSTIC.json` — 95 KB, 20 sections, architectural graph model.

## What It Is

Machine-readable behavioral graph model of the entire RAMP system, extracted from production code (v0.3.0, June 25 2026). Serves as:
- Architectural reference (graph structure, node relationships)
- Execution graph (what CAN happen, not what IS happening)
- Prompt registry (30 AI calls documented)
- Signal model (what signals exist)

**What it is NOT:**
- Not current state (use CSS for that)
- Not operational truth (ops logs override)
- Not a decision-making source

## Key Facts for Engineering Context

### AI Model Routing (DB-driven, NO hardcoded models)
- **Invariant (July 2, 2026):** All model selection MUST come from DB `system_settings` via `get_config()`. No hardcoded model strings in service/route code.
- `llm_scoring_model` → Gemini Flash (scoring, hobby, EPG, fitness gate, rule extraction)
- `llm_generation_model` → Claude Sonnet (persona, generation, editor, posts, avatar analysis)
- `llm_strategy_model` → Claude Sonnet (strategy engine, discovery strategy)
- `llm_onboarding_model` → Gemini Flash (onboarding wizard, tone calibration)
- `llm_discovery_model` → Gemini Flash (entity extraction, hypotheses, reports)
- `llm_emotional_model` → Gemini Flash (emotional profiles, compatibility)
- `llm_utility_model` → Claude Haiku (lightweight: competitor suggestions, dry run)
- `llm_trial_model` → Claude Sonnet (trial outreach, summary, failure analysis)
- `geo_model_perplexity` → Perplexity Sonar (GEO/AEO monitoring)
- `geo_model_openai` → OpenAI gpt-4o-search-preview (GEO/AEO, web_search_options)
- `geo_model_anthropic` → Claude Sonnet 4-6 (GEO/AEO, web_search_options)
- `geo_fallback_model` → Gemini Flash Lite (fallback when GEO provider fails)
- `embedding_model` → text-embedding-004 (vector embeddings)
- GEO multi-provider: same prompts run against ALL enabled providers per batch. Provider abstraction in `geo_providers.py`.
- **Cost centralization:** ALL LLM calls through `app/services/ai.py` → `call_llm()`/`call_llm_json()` + `log_ai_usage()`. 3-layer runaway protection (R-AI-007): per-task counter (50 max), cost circuit breaker ($5/10min Redis window), call count caps (500/hour, 3000/day Redis). `LLMRunawayDetected` exception on breach. Dashboard alert in `alert_aggregation.py`.
- **38 registered operations** across 7 pipeline stages. Every call logged in `ai_usage_log` table. **Verified July 7, 2026:** 38 call sites = 38 log_ai_usage calls (1:1 parity, zero leakage).
- **Quality monitoring (July 19, 2026):** Every `ai_usage_log` record includes `quality_outcome` (success/empty/parse_error/timeout/error/fallback_used), `retry_count`, `fallback_model`. Periodic task `check_llm_quality` (every 4h) detects degradation vs 7-day baseline. Admin: `/admin/llm-quality`. Alert: `_get_llm_quality_alerts()` in dashboard.
- **Audit trail coverage (verified July 7, 2026):** 17 CRUD actions in admin service + 47 route-level audit entries (freeze, phase_override, kill switches, posting config, strategy, EPG, email verification) + 4 portal actions (draft approve/edit/skip/posted) + settings changes + email toggles. Full coverage of all mutable operations.
- **Known violations (July 2 audit):** 17 files still hardcode models. See `/HARDCODED_MODELS_AUDIT.md`.
- NO formal AI registry. NO per-client routing. NO A/B testing capability.

### Orchestration (distributed, not centralized)
- Celery Beat = temporal (WHEN) — runs as lightweight `beat_app.py` (no task imports, ~25 MB). Schedule defined in `app/tasks/beat_app.py`.
- Task chaining = causal (ORDER within pipeline)
- State polling = reactive (WHAT based on DB state)
- NO single orchestrator that sees full system state.
- **External Watchdog (July 2, 2026):** systemd timer on host (outside Docker). Checks Redis, PG, App, Beat, Workers, Disk every 30s. Auto-restarts dead containers. Telegram alerts (pending token config). Survives container crash, Celery death, Docker failure.

### State Machines (6 formal)
- CommentDraft: pending → approved/rejected → posted
- EPGSlot: planned → generated → approved → posted/skipped/expired
- ExecutionTask: generated → emailed → accepted → submitted → verified/failed/expired
- Avatar Phase: 0(Incubation) → 1 → 2 → 3. Mentor is pool-based (`avatar.pool == "mentor"`), NOT a phase.
- Avatar Health: unknown / active / limited / shadowbanned / suspended
- **Activation Zone: safe → bridge → target** (within Phase 0-1, feature-flagged via `activation_routing_enabled`). Zone graduation checked daily at 06:00 alongside phase evaluation. Stored in `avatar.activation_route` JSONB.

### Common Misinterpretations (LLMs hallucinate these)
- TWO Celery queues exist: "celery" (default, bulk) + "fast" (on-demand). See docker-compose.yml + worker.py task_routes
- NO per-subreddit slot cap (2/day is false)
- NO 40% presence cap
- 70% is DEMOTION threshold. 80% is PROMOTION threshold (Phase 1→2). 85% for Phase 2→3. Both exist in PhaseEvaluator
- EPG race condition FIXED June 25 (DistributedLock in tasks/epg.py + dedup guard in portfolio_manager.py). **Redesigned July 6:** single morning build (08:15) + afternoon top-up (14:15) for underfilled avatars. No more duplicate slot creation possible.
- Expert phase NOT coded (spec only)
- System does NOT auto-post in production (POSTING_DISABLED=false as of June 28)
- **Mentor is NOT Phase 0.** Mentor = `avatar.pool == "mentor"` (pool classification). Phase 0 = Incubation (real phase for fresh/recovering avatars). Spec: `phase-incubation-mentor-refactor`
- **Shadowban does NOT freeze.** Shadowban → demote to Phase 0 (monitoring continues). Freeze is ONLY for suspended (404/403), admin manual, or Phase 0 timeout >30d.
- **Shadowban = profile 404 at Reddit API level.** If `redditor.comments.new()` returns ANY data (even old) → account is NOT shadowbanned. PRAW docs: "Shadowbanned accounts are treated the same as non-existent accounts." Confirmed empirically June 28: d-wreck-w12 (5 old comments returned → not shadowbanned), NotSoDelgado88 (comment returned but HIDDEN in thread → subreddit ban, not global shadowban).
- **`total_sampled=0` does NOT mean shadowban.** It means no comments within lookback window. Must check `total_from_api` — if >0, avatar is alive but inactive. Fixed June 28 in health_checker.py.
- **Auto-approve has TWO triggers (OR logic).** `avatar.auto_approve_drafts=true` OR `client.autopilot_enabled=true`. Client-level setting overrides avatar-level. Checked in `epg_executor.py` → `_should_auto_approve()`. Common confusion: avatar toggle is OFF but drafts still auto-approved because client has `autopilot_enabled=true`.
- **Subreddit Risk Profile ≠ real-time.** Profiles are computed WEEKLY (Sun 05:00-05:30). Fitness gate uses CACHED profile data at generation time. No daily refresh. Rules extracted from sidebar/wiki cover ~60-70% of explicit rules; hidden AutoMod configs remain opaque.
- **Fitness gate is fail-open.** No profile → allow generation (score=50). Does NOT block pipeline for new subreddits. Only blocks when profile exists AND criteria not met.
- **Risk score ≠ "don't post here."** Score 0-100 measures moderation intensity. Low-karma avatars blocked from high-risk subs; high-karma avatars may still post. The gate is karma-relative, not absolute.
- **AI costs are NOT fully visible unless ALL calls go through `call_llm()`+`log_ai_usage()`.** `/admin/ai-costs` shows ONLY what's in `ai_usage_log` table. Direct `litellm.completion()` bypasses = invisible spend. Invariant enforced July 2, 2026. See `ai_cost_centralization.md`.
- **Models MUST NOT be hardcoded in services.** All model strings come from DB settings via `get_config()`. 13 DB settings define all models. Hardcoding a model = cannot change without deploy = operational debt. Audit: `/HARDCODED_MODELS_AUDIT.md`.
- **Activation Zone ≠ Phase.** Zone (safe/bridge/target) = subreddit routing within Phase 0-1. Phase (0/1/2/3) = content type + brand eligibility. Zone graduation does NOT trigger phase promotion directly. Bridge→Target graduation in Phase 1 triggers a Phase 2 re-evaluation CHECK, not automatic promotion.
- **Activation Route is optional.** Avatars without `activation_route` JSONB use legacy `hobby_subreddits` path. Route only exists when `activation_routing_enabled=true` AND route was planned. System never blocks on missing route.
- **Dangerous hours ≠ "never post here."** Dangerous hours (from SubredditRiskProfile) filters opportunities in `scan_opportunities()`. Slot is not created during those hours — it's not deferred to later (currently). Lost opportunity, not blocked pipeline.

### Hidden Architecture (not visible in node/edge graph)
- `hidden_architecture.ownership_map` — WHO decides WHAT at each stage
- `hidden_architecture.implicit_contracts` — 8 undocumented module contracts
- `hidden_architecture.missing_formal_layers` — 5 layers that should exist but don't (AI Registry, Orchestration, Prompt Store, Client FSM, Consistency Manager)
- `hidden_architecture.scalability_boundaries` — where system breaks under scale

## When to Update

Update JSON when:
- New AI prompt added
- New Celery task added
- State machine transition added/changed
- New entity/model created
- Safety gate added/modified
- Kill switch added
- Deployment infra changed
- Subreddit risk profile logic changed (fitness gate checks, scoring formula, extraction rules)
- New risk identified → add to `data/09_risks.json` (displayed at `/admin/risk-registry`)
