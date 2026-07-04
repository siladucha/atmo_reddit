# Аудит: Захардкоженные LLM модели в кодовой базе

**Дата:** 2 июля 2026  
**Статус:** Только отчёт (без исправлений)  
**Scope:** `reddit_saas/app/` — все `.py` файлы (services, routes, tasks)

---

## Резюме

| Категория | Кол-во | Уровень риска |
|-----------|--------|---------------|
| Service-level константы (`LLM_MODEL = "..."`) | 14 | 🔴 Высокий — нельзя сменить модель без деплоя |
| Inline model= в вызовах call_llm | 5 | 🔴 Высокий — то же самое |
| Fallback/or-default строки | 5 | 🟡 Средний — резервные, но должны быть в конфиге |
| Реестр стоимости (MODEL_COSTS) | 9 записей | 🟢 Допустимо — цены привязаны к конкретным моделям |
| Цепочка fallback (MODEL_FALLBACK_CHAIN) | 5 ключей | 🟡 Средний — можно вынести в DB/config |
| Defaults в settings.py | 3 | 🟢 Допустимо — начальные значения для DB settings |
| GEO provider config | 3 | 🟡 Средний — модели привязаны к провайдерам |
| Embedding модели | 3 | 🟡 Средний — отдельная подсистема, редко меняется |
| Демо/тестовые данные | 1 | 🟢 Безвредно |

**Итого уникальных файлов с проблемными хардкодами: 17**

---

## 🔴 Критические — Service-Level Константы

Модели захардкожены как константы модуля. Единственный способ изменить — деплой кода.

### 1. `app/services/rule_extractor.py` (строка 33)
```python
LLM_MODEL = "gemini/gemini-2.0-flash"
```
**Используется для:** Извлечение правил сабреддитов (sidebar/wiki → structured rules)  
**Должно быть:** `get_config("llm_scoring_model")` или отдельный `llm_rule_extraction_model`

### 2. `app/services/onboarding/ai_prompts.py` (строка 12)
```python
ONBOARDING_MODEL = "gemini/gemini-2.5-flash"
```
**Используется для:** Все 8 AI операций в onboarding wizard  
**Должно быть:** `get_config("llm_onboarding_model")` или DB setting

### 3. `app/services/emotional_profile.py` (строки 31-32)
```python
PROFILE_MODEL = "gemini/gemini-2.5-flash"
COMPATIBILITY_MODEL = "gemini/gemini-2.5-flash-lite"
```
**Используется для:** Суbreddit tone analysis + avatar compatibility scoring  
**Должно быть:** DB settings `llm_emotional_profile_model`, `llm_compatibility_model`

### 4. `app/services/geo_query_runner.py` (строки 45, 49-50)
```python
PERPLEXITY_MODEL = "perplexity/sonar"
GEMINI_GEO_MODEL = "gemini/gemini-2.5-flash-lite"
GEMINI_GEO_FALLBACK = "gemini/gemini-2.5-flash"
```
**Используется для:** GEO monitoring batch runner (запасная модель если Perplexity упал)  
**Должно быть:** DB settings `geo_fallback_model`, `geo_fallback_secondary_model`. Perplexity тоже может меняться (sonar-pro, новые версии).

### 5. `app/services/trial_outreach.py` (строка 35)
```python
LLM_MODEL = "anthropic/claude-sonnet-4-20250514"
```
**Используется для:** Генерация текста outreach email для trial  
**Должно быть:** `get_config("llm_generation_model")` или отдельный `llm_trial_model`

### 6. `app/services/trial_summary.py` (строка 26)
```python
LLM_MODEL = "anthropic/claude-sonnet-4-20250514"
```
**Используется для:** Sales summary генерация  
**Должно быть:** `get_config("llm_generation_model")` или отдельный setting

### 7. `app/services/discovery/entity_extractor.py` (строка 22)
```python
ENTITY_EXTRACTION_MODEL = "gemini/gemini-2.5-flash-lite"
```
**Используется для:** Entity extraction из client brief  
**Должно быть:** DB setting `llm_discovery_model`

### 8. `app/services/discovery/hypothesis_engine.py` (строка 29)
```python
HYPOTHESIS_MODEL = "gemini/gemini-2.5-flash-lite"
```
**Используется для:** Hypothesis generation/validation  
**Должно быть:** DB setting `llm_discovery_model` (общий для discovery subsystem)

### 9. `app/services/discovery/report_generator.py` (строка 32)
```python
REPORT_MODEL = "gemini/gemini-2.5-flash"
```
**Используется для:** Discovery report generation  
**Должно быть:** DB setting `llm_report_model`

### 10. `app/services/discovery/strategy_generator.py` (строка 26)
```python
STRATEGY_MODEL = "gemini/gemini-2.5-flash"
```
**Используется для:** Client strategy generation from discovery  
**Должно быть:** `get_config("llm_strategy_model")` (уже есть в DB!)

---

## 🔴 Критические — Inline model= в вызовах

Модель передаётся строковым литералом прямо в вызов LLM. Невозможно изменить без правки кода.

### 11. `app/services/avatar_onboard_analysis.py` (строка 298)
```python
result = call_llm_json(
    messages=messages,
    model="anthropic/claude-sonnet-4-20250514",
    ...
)
```
**Используется для:** AI классификация Reddit профиля при onboarding аватара  
**Должно быть:** `get_config("llm_generation_model")` (это задача уровня generation)

### 12. `app/services/trial_failure.py` (строка 215)
```python
result = call_llm(
    messages=[{"role": "user", "content": prompt}],
    model="anthropic/claude-sonnet-4-20250514",
    ...
)
```
**Используется для:** Trial failure analysis  
**Должно быть:** `get_config("llm_generation_model")` или `llm_trial_model`

### 13. `app/routes/onboarding.py` (строка 1391)
```python
result = call_llm_json(
    messages=messages,
    model="gemini/gemini-2.5-flash",
    ...  # tone calibration
)
```
**Используется для:** Tone calibration (генерация sample sentences)  
**Должно быть:** `get_config("llm_onboarding_model")` или `ONBOARDING_MODEL` из ai_prompts (но тот тоже хардкожен)

### 14. `app/routes/onboarding.py` (строка 1553)
```python
result = call_llm_json(
    messages=messages,
    model="gemini/gemini-2.5-flash",
    ...  # sentence generation
)
```
**Используется для:** Voice sentence generation  
**Должно быть:** `get_config("llm_onboarding_model")`

### 15. `app/routes/admin_geo.py` (строка 844)
```python
for model_name in ["anthropic/claude-haiku-4-5", get_config("llm_scoring_model")]:
```
**Используется для:** Competitor suggestion (первая попытка — Haiku, потом scoring model)  
**Должно быть:** DB setting для lightweight model, например `llm_utility_model`

---

## 🟡 Средний — Fallback/or-default строки

Модель используется как fallback когда DB setting = None. Менее критично (DB обычно заполнена), но всё равно хардкод.

### 16. `app/services/avatar_analysis.py` (строки 182-183)
```python
primary_model = get_setting(db, "avatar_analysis_primary_model") or "openai/gpt-4o-mini"
fallback_model = get_setting(db, "avatar_analysis_fallback_model") or "anthropic/claude-sonnet-4-20250514"
```
**Проблема:** Если DB settings не заполнены (новый env, reset), подставляются конкретные модели  
**Должно быть:** Fallback из `settings.py` DEFAULT_SETTINGS (уже есть механизм)

### 17. `app/routes/dry_run.py` (строка 185)
```python
model_name = get_setting(db, "llm_scoring_model") or "anthropic/claude-3-5-haiku-20241022"
```
**Проблема:** Устаревшая модель как fallback  
**Должно быть:** `get_config("llm_scoring_model")` (который имеет свой default в settings.py)

### 18. `app/services/ai.py` (строка 470)
```python
ultimate = "anthropic/claude-sonnet-4-6"
```
**Контекст:** Последний рубеж когда DB полностью недоступна  
**Оправдание:** Нужен КАКОЙ-ТО fallback когда даже DB не работает  
**Рекомендация:** Вынести в environment variable `LLM_ULTIMATE_FALLBACK` или оставить как есть (единственное допустимое место для hardcode)

### 19. `app/services/ai.py` (строки 487-489)
```python
if failed_model.startswith("gemini/"):
    return "anthropic/claude-haiku-4-5"
elif failed_model.startswith("anthropic/"):
    return "gemini/gemini-2.5-flash-lite"
```
**Контекст:** JSON retry — если один провайдер не смог выдать валидный JSON, пробуем другой  
**Рекомендация:** Вынести маппинг в конфигурацию или DB. Или как минимум в константу рядом с MODEL_FALLBACK_CHAIN.

---

## 🟡 Средний — GEO Provider Config

### 20. `app/services/geo_providers.py` (строки 53, 63, 73)
```python
PROVIDER_PERPLEXITY: GeoProviderConfig(model="perplexity/sonar", ...)
PROVIDER_OPENAI: GeoProviderConfig(model="openai/gpt-4o-search-preview", ...)
PROVIDER_ANTHROPIC: GeoProviderConfig(model="anthropic/claude-sonnet-4-6", ...)
```
**Контекст:** Конфигурация GEO провайдеров. Модели привязаны к специфичным возможностям (web search).  
**Проблема:** Perplexity может обновить sonar → sonar-pro. OpenAI может сменить preview → stable.  
**Рекомендация:** DB settings `geo_model_perplexity`, `geo_model_openai`, `geo_model_anthropic`

---

## 🟡 Средний — Embedding модели

### 21. `app/services/embedding.py` (строки 30-35, 239, 261)
```python
DEFAULT_MODEL = "text-embedding-004"
DIMENSIONS = {
    "text-embedding-3-small": 1536,
    "text-embedding-004": 768,
}
# + hardcoded "text-embedding-3-small" in OpenAI API calls (строки 239, 261)
```
**Контекст:** Embedding модели имеют фиксированные dimensions — смена модели требует re-embedding всех данных  
**Рекомендация:** Допустимо оставить — embedding модель меняется крайне редко и требует data migration. Но DEFAULT_MODEL стоит вынести в DB setting для будущей миграции.

---

## 🟢 Допустимые хардкоды (НЕ требуют исправления)

### MODEL_COSTS dict (`app/services/ai.py`, строки 31-41)
Реестр цен за 1M токенов. Привязан к конкретным моделям по определению. При добавлении новой модели — добавляется запись.

### DEFAULT_SETTINGS (`app/services/settings.py`, строки 139-151)
Начальные значения для DB settings при первом запуске. Это seed data, а не runtime config. Корректно — задаёт дефолт, который потом оверрайдится из DB.

### MODEL_FALLBACK_CHAIN (`app/services/ai.py`, строки 47-51)
Определяет логику fallback между провайдерами. Можно вынести в DB, но это инфраструктурная конфигурация уровня платформы (не бизнес-логика). Средний приоритет.

### `discovery/demo_seed.py` (строка 313)
```python
model_used="gemini/gemini-2.5-flash-lite (demo)"
```
Статические тестовые данные. Не влияет на runtime.

---

## Правильные паттерны (для справки)

Эти сервисы делают правильно — читают модель из DB:

| Файл | Как получает модель |
|------|-------------------|
| `services/generation.py` | `get_config("llm_generation_model")` |
| `services/scoring.py` | `get_config("llm_scoring_model")` |
| `services/post_generation.py` | `get_config("llm_generation_model")` |
| `services/strategy_engine.py` | `get_config("llm_strategy_model")` |
| `services/epg_executor.py` | `get_config("llm_scoring_model")` |
| `tasks/ai_pipeline.py` (hobby) | `get_config("llm_scoring_model")` |
| `routes/admin_geo.py` (prompt gen) | `get_config("llm_scoring_model")` |

---

## Рекомендации по исправлению

### Стратегия: Минимум новых DB settings

Не нужно 20 новых settings. Группируем по паттерну использования:

| Новый DB Setting | Заменяет хардкоды в | Дефолт |
|------------------|-------------------|--------|
| `llm_onboarding_model` | onboarding/ai_prompts.py, routes/onboarding.py (×2) | `gemini/gemini-2.5-flash` |
| `llm_discovery_model` | entity_extractor, hypothesis_engine, report_generator, strategy_generator | `gemini/gemini-2.5-flash` |
| `llm_rule_extraction_model` | rule_extractor.py | `gemini/gemini-2.0-flash` |
| `llm_emotional_model` | emotional_profile.py (×2) | `gemini/gemini-2.5-flash` |
| `llm_trial_model` | trial_outreach, trial_summary, trial_failure | `anthropic/claude-sonnet-4-20250514` |
| `llm_utility_model` | admin_geo competitor suggestion, dry_run fallback | `anthropic/claude-haiku-4-5` |
| `geo_model_perplexity` | geo_providers.py, geo_query_runner.py | `perplexity/sonar` |
| `geo_model_openai` | geo_providers.py | `openai/gpt-4o-search-preview` |
| `geo_model_anthropic` | geo_providers.py | `anthropic/claude-sonnet-4-6` |
| `geo_fallback_model` | geo_query_runner.py (×2) | `gemini/gemini-2.5-flash-lite` |
| `embedding_model` | embedding.py | `text-embedding-004` |

**Для avatar_onboard_analysis.py:** использовать существующий `llm_generation_model`  
**Для avatar_analysis.py:** уже использует DB settings, но fallback хардкожен — добавить в DEFAULT_SETTINGS  

### Приоритет исправления

1. **Сервисы с константой `LLM_MODEL =`** — самые простые в исправлении (заменить на `get_config()`)
2. **Inline model= в call_llm** — потребует прокидывание DB session или lazy config
3. **Fallback строки** — наименьший приоритет (сработает только при отсутствии DB settings)

### Оценка работы: ~2-3 часа

- Добавить ~10 новых settings в `DEFAULT_SETTINGS` dict
- Заменить 14 константных хардкодов на `get_config()` вызовы
- Заменить 5 inline model= на переменную из конфига
- Убедиться что все используемые модели есть в `MODEL_COSTS`
- Один alembic migration не нужен (settings пишутся в DB через seed/get_config default)

---

## Полная карта хардкодов

```
app/services/
├── ai.py                     — MODEL_COSTS (9), FALLBACK_CHAIN (5 keys), ultimate fallback (1), json retry (2)
├── settings.py               — DEFAULT_SETTINGS defaults (3) ✅ допустимо
├── rule_extractor.py         — LLM_MODEL 🔴
├── emotional_profile.py      — PROFILE_MODEL, COMPATIBILITY_MODEL 🔴🔴
├── geo_query_runner.py       — PERPLEXITY_MODEL, GEMINI_GEO_MODEL, GEMINI_GEO_FALLBACK 🟡
├── geo_providers.py          — 3 provider configs 🟡
├── trial_outreach.py         — LLM_MODEL 🔴
├── trial_summary.py          — LLM_MODEL 🔴
├── trial_failure.py          — inline model= 🔴
├── avatar_analysis.py        — or "model" fallbacks (×2) 🟡
├── avatar_onboard_analysis.py — inline model= 🔴
├── embedding.py              — DEFAULT_MODEL + inline (×2) 🟡
├── onboarding/
│   └── ai_prompts.py         — ONBOARDING_MODEL 🔴
├── discovery/
│   ├── entity_extractor.py   — ENTITY_EXTRACTION_MODEL 🔴
│   ├── hypothesis_engine.py  — HYPOTHESIS_MODEL 🔴
│   ├── report_generator.py   — REPORT_MODEL 🔴
│   ├── strategy_generator.py — STRATEGY_MODEL 🔴
│   └── demo_seed.py          — static string ✅
app/routes/
├── onboarding.py             — inline model= (×2) 🔴
├── admin_geo.py              — inline hardcoded first in list 🔴
└── dry_run.py                — or "model" fallback 🟡
```

**Всего 🔴 проблемных мест: 17** (14 констант + 5 inline = 19, минус 2 пересечения с допустимыми)  
**Всего 🟡 средних: 9** (fallbacks + GEO providers + embedding)  
**Файлов затронуто: 17**
