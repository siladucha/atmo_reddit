---
inclusion: always
---

# AI Cost Centralization — Architecture Invariant

## Core Principle

**Every LLM call in RAMP MUST go through `app/services/ai.py` → `call_llm()` / `call_llm_json()` AND have its cost recorded via `log_ai_usage()`.**

No exception. No direct `litellm.completion()` calls in service code (except `geo_providers.py` where the caller explicitly logs costs, and `settings.py` ping test which is a 1-token health check).

## Why This Matters

1. **Visibility** — `/admin/ai-costs` shows ALL spend. If something bypasses logging, operator sees underreported costs → wrong margin calculations → wrong pricing decisions.
2. **Budget gate** — 3-layer defense in `call_llm()` prevents unbounded spend. Bypassing services have no runaway protection.
3. **Fallback** — `call_llm()` has automatic model fallback chain. Direct `litellm.completion()` has zero fault tolerance.
4. **Audit** — Per-client, per-avatar, per-operation cost attribution enables unit economics analysis.

## Enforcement

### At code review time

Any new service that calls an LLM must:
1. Import from `app.services.ai` — never `import litellm` for production calls
2. Call `log_ai_usage(db, client_id, operation, result, ...)` after every successful `call_llm`/`call_llm_json`
3. Use an `operation` string that maps to both `admin.py` stage_map AND `billing_dashboard.py` op_labels
4. Pass `triggered_by` parameter (or set `ai_trigger_context` ContextVar at task level)
5. Call `reset_task_call_counter()` at the start of any new Celery task that makes LLM calls

### At runtime — 3-Layer Runaway Protection (R-AI-007, July 2 2026)

| Layer | Mechanism | Limit | Detection Speed | Redis Required |
|-------|-----------|-------|-----------------|---------------|
| 1 — Call count | Redis INCR per hour/day key | 500/hour, 3000/day | Minutes (accumulation) | Yes |
| 2 — Cost window | Redis INCRBYFLOAT per 10-min bucket | $5 per 10 min | 2-5 min (cost accumulates) | Yes |
| 3 — Per-task counter | ContextVar increment per call_llm | 50 calls per task | Immediate (within task) | No |

**Exceptions raised:**
- `LLMBudgetExceeded` — hourly/daily caps exceeded (Layer 1)
- `LLMRunawayDetected(LLMBudgetExceeded)` — circuit breaker or per-task limit tripped (Layers 2, 3)

**Fail-open:** Redis down → Layers 1+2 skip (allow call), Layer 3 still protects (in-process).

**Alert integration:** `alert_aggregation.py` → `_get_llm_spend_rate_alert()` surfaces 🔥 in owner dashboard when spend rate > 3× avg or circuit breaker approaching threshold.

**Maximum damage from any runaway loop:** ~$5 (10-min window ceiling). Previously: unbounded.

## Registered Operations (must be in both stage_map and op_labels)

| Operation | Stage | Description |
|-----------|-------|-------------|
| `scoring` / `scoring_batch` | Scoring | Thread relevance assessment |
| `generation` | Content | Comment writing |
| `persona_select` | Content | Avatar routing |
| `editing` | Content | AI text cleanup |
| `hobby_comment_epg` / `hobby_comment_pipeline` / `hobby_comment_workflow` | Hobby | Phase 1 comments |
| `post_topic` / `post_brief` / `post_generation` | Posts | Reddit post creation |
| `strategy_generation` | Strategy | Avatar strategy docs |
| `avatar_analysis` / `avatar_onboarding` | Avatar Intel | Profile classification |
| `geo_query` / `geo_generate_prompts` / `geo_suggest_competitors` | GEO/AEO | Brand visibility monitoring |
| `discovery` | Discovery | Market research |
| `onboarding_*` (8 variants) | Onboarding | Self-service wizard |
| `emotional_profile` / `emotional_compatibility` | Subreddit Intel | Tone analysis |
| `subreddit_rule_extraction` | Subreddit Intel | Rule parsing from sidebar/wiki |
| `trial_sales_summary` / `trial_reactivation_intel` / `trial_outreach` | Trial Intelligence | Conversion optimization |

## Incident History

| Date | Issue | Impact | Fix |
|------|-------|--------|-----|
| 2026-07-02 | `trial_summary.py`, `trial_failure.py`, `trial_outreach.py` called `litellm.completion()` directly | Costs invisible on /admin/ai-costs, no budget gate, no fallback | Replaced with `call_llm()` + `log_ai_usage()` |
| 2026-07-02 | `rule_extractor.py` used `call_llm()` but never called `log_ai_usage()` | ~$0.003/call invisible (weekly batch, minor) | Added `log_ai_usage()` with `operation="subreddit_rule_extraction"` |
| 2026-07-02 | `emotional_profile.py` `compute_compatibility()` used `call_llm_json()` but never logged | Compatibility scoring costs invisible | Added `log_ai_usage()` with `operation="emotional_compatibility"` |
| 2026-07-02 | R-AI-007 — No runaway loop protection beyond blunt hourly/daily caps | A single bug could burn $100+ before 500/h cap triggered | 3-layer defense: per-task counter (50 calls), cost circuit breaker ($5/10min), dashboard alert. Max damage now ~$5. |
| 2026-07-07 | Anthropic credits exhausted ($50/mo limit) | ALL generation fallback blocked, 0 drafts generated | Root cause: Claude Sonnet GEO web search ($0.08/query) + generation calls. Need: monitor spend vs provider limits, alert before exhaustion. |

## CRITICAL INVARIANT: Zero Cost Leakage (Established July 7, 2026)

**Statement:** Every single API call that costs money MUST be recorded in `ai_usage_log` with accurate `cost_usd`. No exceptions. No "I'll add logging later."

**Verification status (July 7, 2026): ✅ CONFIRMED**
- 38 `call_llm`/`call_llm_json` call sites = 38 `log_ai_usage` calls (1:1 parity)
- 0 direct `litellm.completion()` calls outside `ai.py` (except `geo_providers.py` where caller logs, and `settings.py` ping test)
- `cost_usd` always populated via `litellm.completion_cost()` (primary) or `MODEL_COSTS` dict (fallback, 17 models)
- GEO providers: cost computed in provider → logged by `geo_query_runner.py` caller

**Why this is P0:**
- $50/mo Anthropic limit exhausted July 7 without anyone noticing until pipeline broke
- If 10% of calls leak (no logging), spend tracking is useless for budget decisions
- Provider bills ≠ internal tracking → trust destroyed, pricing wrong, margins miscalculated

**Enforcement checklist (before ANY deploy):**

1. `grep -r "litellm.completion\|litellm.acompletion" app/services/ app/routes/ app/tasks/` → MUST return 0 results (except `ai.py` itself and `geo_providers.py` caller-logged)
2. Every `call_llm()`/`call_llm_json()` MUST be followed by `log_ai_usage()` in the same function
3. `cost_usd` field MUST be populated (not NULL, not 0) — `log_ai_usage()` calculates from `MODEL_COSTS` dict
4. New models added to any service → MUST also be added to `MODEL_COSTS` in `ai.py`

**Provider Budget Monitoring (July 7 → IMPLEMENTED July 15, 2026):**

| Provider | Monthly Limit | Alert Threshold | Where to Check |
|----------|--------------|-----------------|----------------|
| Anthropic | $50 | Alert at $35 (70%) | console.anthropic.com |
| Google (Gemini) | Free tier / $300 credits | Alert at $210 (70%) | console.cloud.google.com |
| Perplexity | $50 (configurable) | Alert at $35 (70%) | perplexity.ai/settings |
| OpenAI | $50 (configurable) | — | platform.openai.com |

**Implementation (July 15, 2026):**
- `app/tasks/provider_budget_check.py` → `check_provider_budgets` Celery task
- Schedule: every 4h (03:45, 07:45, 11:45, 15:45, 19:45, 23:45) via beat_app.py
- Detection: `_get_provider_budget_alerts()` from alert_aggregation.py
- Delivery: 3 channels simultaneously:
  1. **Telegram** — `notify_ops(level, title, body, category="cost_alert")` → pushes to owner/partner phones
  2. **Email** — Brevo to all owner + partner users (HTML + plaintext)
  3. **Admin bell** — Redis PubSub `notifications:ops` channel
- Cooldown: Redis key `ramp:provider_budget_alert:{type}:{severity}` with 12h TTL (no spam)
- Partner dashboard now shows alerts bar (same as owner)
- DB settings: `provider_budget_*_usd` (per provider), `provider_budget_alert_threshold_pct` (70), `provider_budget_block_threshold_pct` (95)

**Prevents:** Repeat of July 7 incident where Anthropic credits exhausted silently. Now: Telegram push + email at 70% ($35/$50), critical at 95% ($47.50/$50).

**LITELLM_API_KEY usage (current — July 7, 2026):**
- Single Anthropic key (`sk-ant-...`) set as `LITELLM_API_KEY` in Docker `.env`
- LiteLLM uses it as fallback for ALL providers without dedicated keys
- This means: Anthropic key is used for Claude Sonnet, Claude Haiku, AND as web_search key for GEO
- When this key's credits hit 0 → ALL Claude calls fail → generation fallback fails → pipeline dead

## Model Routing Invariant (July 2, 2026)

**NO hardcoded model strings in service/route code.** Every LLM model selection MUST come from a DB setting via `get_config()` or `get_setting()`.

### Why

Hardcoded model = requires code deploy to change model. This violates:
- **Operational agility** — can't switch from Flash to Sonnet during incident without deploy
- **Cost optimization** — can't downgrade models for non-critical ops without deploy
- **Model deprecation** — provider removes model version → service breaks until deploy

### Canonical Model Settings (DB `system_settings` table)

| Setting Key | Default | Used By |
|------------|---------|---------|
| `llm_scoring_model` | `gemini/gemini-2.0-flash` | scoring, hobby generation, EPG, fitness gate, rule extraction |
| `llm_generation_model` | `anthropic/claude-sonnet-4-20250514` | comment generation, persona, editing, posts, avatar onboarding, trials |
| `llm_strategy_model` | `anthropic/claude-sonnet-4-20250514` | strategy engine, discovery strategy |
| `llm_onboarding_model` | `gemini/gemini-2.5-flash` | onboarding wizard (8 AI ops), tone calibration |
| `llm_discovery_model` | `gemini/gemini-2.5-flash` | entity extraction, hypotheses, reports |
| `llm_emotional_model` | `gemini/gemini-2.5-flash` | emotional profiles, compatibility |
| `llm_utility_model` | `anthropic/claude-haiku-4-5` | lightweight tasks (competitor suggestions, dry run display) |
| `llm_trial_model` | `anthropic/claude-sonnet-4-20250514` | trial outreach, trial summary, trial failure analysis |
| `geo_model_perplexity` | `perplexity/sonar` | GEO monitoring (Perplexity provider) |
| `geo_model_openai` | `openai/gpt-4o-search-preview` | GEO monitoring (OpenAI provider) |
| `geo_model_anthropic` | `anthropic/claude-sonnet-4-6` | GEO monitoring (Anthropic provider) |
| `geo_fallback_model` | `gemini/gemini-2.5-flash-lite` | GEO fallback when primary provider fails |
| `embedding_model` | `text-embedding-004` | vector embeddings |

### Correct Pattern

```python
# ✅ CORRECT — model from DB, changeable at runtime
from app.config import get_config

model = get_config("llm_scoring_model")
result = call_llm_json(messages=messages, model=model, ...)
```

### Anti-Patterns (PROHIBITED)

```python
# ❌ WRONG — module-level constant
LLM_MODEL = "gemini/gemini-2.0-flash"

# ❌ WRONG — inline literal
result = call_llm(messages=msgs, model="anthropic/claude-sonnet-4-20250514", ...)

# ❌ WRONG — hardcoded or-fallback
model = get_setting(db, "some_key") or "anthropic/claude-sonnet-4-20250514"
# ✅ CORRECT — fallback via get_config which reads DEFAULT_SETTINGS
model = get_config("llm_generation_model")
```

### Exceptions (Acceptable Hardcodes)

1. **`MODEL_COSTS` dict** (`ai.py`) — price registry, keyed by model name by definition
2. **`MODEL_FALLBACK_CHAIN`** (`ai.py`) — infrastructure-level failover logic
3. **`DEFAULT_SETTINGS`** (`settings.py`) — seed values for DB; runtime reads from DB not from this dict
4. **Ultimate fallback** (`ai.py` line ~470) — last resort when DB is completely unavailable
5. **`_get_json_retry_model()`** (`ai.py`) — cross-provider retry for JSON parse failures
6. **Demo/test data** — non-functional static strings

### Known Violations (Audit July 2, 2026)

17 files with 19 critical violations. Full report: `/HARDCODED_MODELS_AUDIT.md`

**Priority 1 (service constants — easiest fix):**
- `rule_extractor.py` → use `get_config("llm_scoring_model")`
- `onboarding/ai_prompts.py` → use `get_config("llm_onboarding_model")`
- `emotional_profile.py` (×2) → use `get_config("llm_emotional_model")`
- `trial_outreach.py` → use `get_config("llm_trial_model")`
- `trial_summary.py` → use `get_config("llm_trial_model")`
- `discovery/entity_extractor.py` → use `get_config("llm_discovery_model")`
- `discovery/hypothesis_engine.py` → use `get_config("llm_discovery_model")`
- `discovery/report_generator.py` → use `get_config("llm_discovery_model")`
- `discovery/strategy_generator.py` → use `get_config("llm_strategy_model")`
- `geo_query_runner.py` (×3) → use `get_config("geo_model_perplexity")`, `get_config("geo_fallback_model")`

**Priority 2 (inline model= in call_llm):**
- `avatar_onboard_analysis.py` → use `get_config("llm_generation_model")`
- `trial_failure.py` → use `get_config("llm_trial_model")`
- `routes/onboarding.py` (×2) → use `get_config("llm_onboarding_model")`
- `routes/admin_geo.py` → use `get_config("llm_utility_model")`

**Priority 3 (or-fallback strings):**
- `avatar_analysis.py` (×2) → add to DEFAULT_SETTINGS
- `routes/dry_run.py` → use `get_config("llm_scoring_model")`

**GEO providers (`geo_providers.py`):**
- Replace hardcoded model in each GeoProviderConfig with `get_config("geo_model_*")`

---

## Adding a New LLM Operation — Checklist

1. ✅ Use `call_llm()` or `call_llm_json()` from `app.services.ai`
2. ✅ Get model via `get_config("<setting_key>")` — **NEVER hardcode model string**
3. ✅ Call `log_ai_usage(db, client_id, "<operation_name>", result, ...)`
4. ✅ Add operation to `admin.py` → `stage_map` dict
5. ✅ Add operation to `billing_dashboard.py` → `op_labels` dict
6. ✅ If operation uses a model not in `MODEL_COSTS` dict → add it
7. ✅ If operation is scheduled → set `ai_trigger_context.set("scheduler")` in the Celery task
8. ✅ If new setting key needed → add to `DEFAULT_SETTINGS` in `settings.py`
9. ✅ Test: after one call, verify row appears in `ai_usage_log` table

## Cost Model Reference (Updated July 8, 2026 — post-optimization)

| Model | Input $/1M | Output $/1M | Used for | Monthly cost (1 client, 1 avatar) |
|-------|-----------|------------|----------|----------------------------------|
| `gemini/gemini-2.5-flash` | $0.15 | $0.60 | Scoring, editing, persona, onboarding, strategy, reports | $0.50 |
| `gemini/gemini-2.5-flash-lite` | $0.00 | $0.00 | Entity extraction, hypothesis, emotional profiles (free) | $0.05 |
| `anthropic/claude-sonnet-4-20250514` | $3.00 | $15.00 | Comment generation ONLY | $8.19 |
| `perplexity/sonar` | ~$1.00 | ~$1.00 + $0.005/search | GEO monitoring | $1.08 |

**Optimized (July 8, 2026):**
- Editing: Claude Sonnet → Gemini Flash (saves $8/mo)
- Persona selection: Claude Sonnet → Gemini Flash (saves $9/mo)
- GEO: Claude web search DISABLED (saves $40-70/mo)
- GEO: runs_per_prompt 3→1 (saves 67% of Perplexity cost)
- Fallback chain: Anthropic removed from all fallbacks → Gemini-only

**Unit economics formula:** `Monthly = N_avatars × $8.50 + $3.50 overhead`
- 1 avatar: ~$10/mo (93% margin at $149 Seed)
- 2 avatars: ~$19/mo (95% margin at $399 Starter)
- 3 avatars: ~$28/mo (93% margin at $399 Starter)

**Phase 2 Additions (July 9, 2026):**
- Context trimming: generation input 12K→8K tokens. Saves ~$2.70/mo/avatar on Claude Sonnet input.
- Anthropic prompt caching: `cache_control: {"type": "ephemeral"}` on system message. Saves ~$5/mo/avatar (90% discount on ~4K cached tokens).
- GEO daily smoothing: `prompt.id.int % 7` rotates prompts across weekdays. Cost-neutral, eliminates Tue+Fri spikes.
- Batch scoring default: 10→5 threads/call (better parse reliability while still 80% fewer calls than individual).
- Cost reconciliation task (`run_cost_reconciliation`, daily 01:05): compares `(tokens × MODEL_COSTS rates)` vs logged `cost_usd`. Alerts on >5% delta.
- AI Costs page redesign: provider budget bars + unit economics + forecast + Chart.js burn chart. Replaces engineering debug view.
- New service: `app/services/unit_economics.py` (get_unit_economics, get_provider_budget_status, get_daily_burn_data, get_client_forecast).
- New task: `app/tasks/cost_reconciliation.py` (registered in beat_app at 01:05).
- New settings: `generation_max_body_chars` (500), `generation_max_voice_chars` (500).
- Modified: `generation.py` (context trimming), `ai.py` (prompt caching), `geo_query_runner.py` (prompts_override), `geo_monitoring.py` (daily task), `beat_app.py` (schedule), `admin_ai_costs.html` (template redesign).
