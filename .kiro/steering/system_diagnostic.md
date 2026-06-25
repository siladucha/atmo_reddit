# System Diagnostic JSON — Reference

## Location

`/RAMP_SYSTEM_DIAGNOSTIC.json` — 95 KB, 20 sections, full operational model.

## What It Is

Machine-readable behavioral graph model of the entire RAMP system, extracted from production code (v0.3.0, June 25 2026). Serves as:
- System specification
- Execution graph
- State model
- Prompt registry (30 AI calls documented)
- Signal model
- Self-modification rules

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
- Avatar Phase: 0(Mentor) / 1 / 2 / 3 (Expert NOT implemented)
- Avatar Health: unknown / active / limited / shadowbanned / suspended

### Common Misinterpretations (LLMs hallucinate these)
- NO "fast" Celery queue (only default)
- NO per-subreddit slot cap (2/day is false)
- NO 40% presence cap
- NO 80% promotion threshold (70% is demotion)
- NO EPG race condition fix (GAP-003 still open)
- Expert phase NOT coded (spec only)
- System does NOT auto-post in production (POSTING_DISABLED=true)

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
