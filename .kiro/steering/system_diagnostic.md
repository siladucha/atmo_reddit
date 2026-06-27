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

### AI Model Routing (NO centralized dispatcher)
- `llm_scoring_model` DB setting → Gemini Flash (scoring, rules, hobby, strategy, reports)
- `llm_generation_model` DB setting → Claude Sonnet (persona, generation, editor, posts, avatar analysis)
- Per-service `get_config()` calls at runtime. Some services hardcode model constants (ONBOARDING_MODEL, REPORT_MODEL).
- NO formal AI registry. NO per-client routing. NO A/B testing capability.

### Orchestration (distributed, not centralized)
- Celery Beat = temporal (WHEN)
- Task chaining = causal (ORDER within pipeline)
- State polling = reactive (WHAT based on DB state)
- NO single orchestrator that sees full system state.

### State Machines (5 formal)
- CommentDraft: pending → approved/rejected → posted
- EPGSlot: planned → generated → approved → posted/skipped/expired
- ExecutionTask: generated → emailed → accepted → submitted → verified/failed/expired
- Avatar Phase: 0(Incubation) → 1 → 2 → 3. Mentor is pool-based (`avatar.pool == "mentor"`), NOT a phase.
- Avatar Health: unknown / active / limited / shadowbanned / suspended

### Common Misinterpretations (LLMs hallucinate these)
- TWO Celery queues exist: "celery" (default, bulk) + "fast" (on-demand). See docker-compose.yml + worker.py task_routes
- NO per-subreddit slot cap (2/day is false)
- NO 40% presence cap
- 70% is DEMOTION threshold. 80% is PROMOTION threshold (Phase 1→2). 85% for Phase 2→3. Both exist in PhaseEvaluator
- EPG race condition FIXED June 25 (DistributedLock in tasks/epg.py + dedup guard in portfolio_manager.py)
- Expert phase NOT coded (spec only)
- System does NOT auto-post in production (POSTING_DISABLED=true)
- **Mentor is NOT Phase 0.** Mentor = `avatar.pool == "mentor"` (pool classification). Phase 0 = Incubation (real phase for fresh/recovering avatars). Spec: `phase-incubation-mentor-refactor`
- **Shadowban does NOT freeze.** Shadowban → demote to Phase 0 (monitoring continues). Freeze is ONLY for suspended (404/403), admin manual, or Phase 0 timeout >30d.

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
