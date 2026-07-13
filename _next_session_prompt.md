# Следующая сессия — AI Cost Optimization Phase 2

## Контекст
Спек: `.kiro/specs/ai-cost-optimization/` (requirements.md, design.md, tasks.md, unit-economics.md)

В прошлой сессии (July 8):
- Pipeline починен, fallback на Gemini работает
- Claude GEO disabled, editing+persona на Flash, runs 3→1
- Cost снижен с $120/мес → ~$10/мес на 1 клиента
- Ops notifications (bell + Telegram) задеплоены
- Anthropic credits нужно пополнить (Цви)

## Задачи (в порядке приоритета)

### 1. GEO Daily Smoothing
Сейчас: Tue+Fri 09:30 — все промпты за раз (spike day).
Надо: ежедневно 09:30, ~1/7 промптов в день (ротация по hash prompt_id % 7).
- Файлы: `app/tasks/geo_monitoring.py`, `app/tasks/beat_app.py`, `app/services/geo_query_runner.py`
- Добавить `prompts_override` param в `run_geo_batch_for_client()`
- Новый task `run_geo_monitoring_daily()` с day-group логикой
- Beat: заменить `crontab(day_of_week="2,5")` на `crontab()` (daily)

### 2. AI Costs Page Redesign
Для Цви (partner role). Вместо инженерного debug view:
- Hero: budget bars per provider (Anthropic $X of $50, Perplexity $X of $20)
- Unit economics card: $/client/month, $/avatar/month, $/draft
- "At N clients" forecast
- Daily burn chart (stacked by operation, GEO days highlighted)
- Existing detail tables → collapsed `<details>`
- Файлы: `app/templates/admin_ai_costs.html`, `app/routes/admin.py`, новый `app/services/unit_economics.py`

### 3. Обрезать Generation Context
Сейчас input ~12K tokens (пост full body + all comments + full voice + strategy + few-shot).
Цель: 8K tokens max.
- `thread.post_body[:500]` (вместо full, часто 2000+ chars)
- `thread.comments_json` → top 3 comments only (вместо all)
- `voice_profile_md[:300]` (вместо full)
- few-shot examples: max 3 (вместо 5-10)
- Файл: `app/services/generation.py` → `generate_comment()` prompt assembly

### 4. Anthropic Prompt Caching
Anthropic поддерживает `cache_control: {"type": "ephemeral"}` на system message.
System prompt + voice profile (~8K tokens) одинаковы для всех calls одного аватара.
Cached tokens: $0.30/1M вместо $3/1M = 90% скидка на cached portion.
- Добавить `cache_control` к system message в `call_llm()` когда model = anthropic/*
- LiteLLM поддерживает: `messages[0]["cache_control"] = {"type": "ephemeral"}`
- Файл: `app/services/ai.py` → `call_llm()`, `app/services/generation.py`
- Ожидаемая экономия: ~$5/мес/avatar (8K cached × 210 calls × $2.70 saved per 1M)

### 5. Batch Scoring
Сейчас: 1 thread = 1 LLM call (600 calls/мес/avatar).
Надо: 5 threads = 1 call (120 calls/мес/avatar).
- Prompt: "Here are 5 posts. For each, return engage/monitor/skip with score."
- Response: JSON array of 5 decisions.
- Файл: `app/services/scoring.py` или `app/services/smart_scoring.py`
- Fallback: если batch parse fails → score individually (retry each)

### 6. Cost Reconciliation Task
Ежедневно 01:00: recompute expected cost from (input_tokens × rate + output_tokens × rate) per model, compare to logged cost_usd.
If delta >5% for any model → notify_ops warning.
- Новый файл: `app/tasks/cost_reconciliation.py`
- Register in `beat_app.py` (daily 01:00)
- Помогает ловить ситуации когда litellm.completion_cost() неточен или model pricing изменился

## Перед началом
- Проверить что Anthropic credits пополнены (спросить)
- Проверить health: `ssh ramp "curl -sf https://localhost/health --insecure"`
- Убедиться что generation работает: rebuild EPG → drafts появляются
