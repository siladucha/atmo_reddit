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

## Cost Model Reference

| Model | Input $/1M | Output $/1M | Typical use |
|-------|-----------|------------|-------------|
| `gemini/gemini-2.5-flash` | $0.15 | $0.60 | Scoring, onboarding, strategy, reports |
| `gemini/gemini-2.5-flash-lite` | $0.00 | $0.00 | Entity extraction, hypothesis (free tier) |
| `gemini/gemini-2.0-flash` | $0.075 | $0.30 | Rule extraction |
| `anthropic/claude-sonnet-4-20250514` | $3.00 | $15.00 | Generation, editing, persona, trials |
| `anthropic/claude-haiku-4-5` | $1.00 | $5.00 | JSON retry fallback |
| `perplexity/sonar` | ~$0.006/q | — | GEO monitoring |

**Estimated daily cost per client (10 clients, full pipeline): ~$1.17**
**Monthly LLM cost at 10 clients: ~$351** (93% of total operational cost)
