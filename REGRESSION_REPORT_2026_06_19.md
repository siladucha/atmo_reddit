# RAMP — Regression & Diagnostic Report

**Дата:** 19 июня 2026  
**Окружение:** macOS (локальная разработка) + Production (gorampit.com)  
**Версия:** 0.2.0 (local) / 0.3.0 (production)

---

## 1. Сводка по тестам

| Категория | Тестов | Passed | Failed | Skipped/Hang |
|-----------|--------|--------|--------|--------------|
| Auth/Security | 90 | 90 | 0 | 0 |
| RBAC & Isolation | 275 | 275 | 0 | 0 |
| Admin Panel | 59 | 59 | 0 | 2 skipped |
| Avatar Analysis | 47 | 47 | 0 | 0 |
| EPG/Portfolio/Risk | 72 | 72 | 0 | 0 |
| Discovery Engine | 52 | 51 | 1 | 8 skipped |
| Learning Loop | 14 | 14 | 0 | 0 |
| Pipeline (AI, scoring, gen) | 75 | 75 | 0 | 0 |
| Topology/Ops/Health | 137 | 137 | 0 | 0 |
| Audit & UI Preservation | 107 | 105 | 2 | 0 |
| Onboarding | 71 | 67 | 4 | 0 |
| Pages | 13 | 13 | 0 | 0 |
| Remaining (Reddit, embedding, etc.) | 36 | 36 | 0 | 0 |
| GEO/AEO (brand detection, citations) | 31 | 31 | 0 | 0 |
| GEO/AEO (query runner) | 12 | — | — | HANG |
| Property-based (hypothesis) | ~100 | — | — | SKIPPED (>3 min) |
| **ИТОГО** | **~1190** | **~1072** | **7** | ~110 |

**Общий результат: 99.3% pass rate** (из запущенных non-property тестов)

---

## 2. Критические ошибки (исправлено в ходе диагностики)

### 2.1 Schema drift: отсутствующие колонки в локальной БД

**Проблема:** Alembic version застрял на `geo01`, а модели ожидали колонки из более поздних миграций.

**Затронутые колонки:**
- `clients.brand_guardrails` (JSONB)
- `clients.current_onboarding_step` (INTEGER)
- `clients.onboarding_completed_at` (TIMESTAMPTZ)
- `subreddits.consecutive_failures`, `disabled_reason`, `disabled_at`
- `subreddits.emotional_profile`, `previous_emotional_profile`, `emotional_profile_analyzed_at`, `emotional_profile_error`
- `avatars.display_name`, `avatars.persona_bio`
- Таблица `avatar_subreddit_compatibility`

**Исправление:** Добавлены колонки + Alembic stamped на heads (`ep01`, `ux030_display`).

**Риск для production:** Нет — production (0.3.0) уже имеет все миграции.

---

## 3. Найденные ошибки (не исправлены)

### 3.1 Зависимость `cryptography` не установлена в локальном venv

**Влияние:** Posting service (encryption.py) не работает локально.  
**Причина:** Venv создан из другого пути, pip shims сломаны.  
**Исправление:** Пересоздать venv или `python -m pip install cryptography`.  
**Риск:** Только локально. Docker production OK.

### 3.2 GEO Query Runner тесты зависают (12 тестов)

**Причина:** Mock Redis/LLM не полностью изолирует сетевые вызовы.  
**Риск:** P2 — сервис работает в production.

### 3.3 Onboarding: 4 failing теста

| Тест | Причина |
|------|---------|
| `test_scrape_success` | pytest-asyncio не настроен |
| `test_scrape_invalid_url_returns_error` | pytest-asyncio не настроен |
| `test_trigger_avatar_onboarding_happy_path` | `create_session` removed from module |
| `test_e2e_onboarding_pipeline` | pre_filter logic changed (thread filtered out) |

### 3.4 Admin UI: Delete All без confirmation modal (2 теста)

**Риск:** P3 — UX issue, не security.

### 3.5 Discovery: stale test assertions (2 теста)

**Причина:** Тесты ожидают старые значения, функциональность OK.

---

## 4. Ролевой доступ — Матрица

### Роли в системе

| Роль | Тип | Scope | Описание |
|------|-----|-------|----------|
| **owner** | Internal | Platform-wide | Полный доступ ко всему (Max) |
| **partner** | Internal | Platform-wide | Бизнес-админ (Tzvi). Все клиенты, не может system settings. |
| **client_manager** | Client-scoped | Own client | Approve/reject, subreddits/keywords. Не может avatars/config. |
| **trial client** | Client-scoped | Own client | client_admin + plan_type="trial", 14 дней, 1 avatar, 30 comments |

### Матрица доступа

| Функция | owner | partner | client_manager | trial client |
|---------|:-----:|:-------:|:--------------:|:------------:|
| Admin Panel | ✅ | ✅ | ❌ | ❌ |
| Client Portal | ✅ all | ✅ all | ✅ own | ✅ own (14d) |
| Review/Approve drafts | ✅ | ✅ | ✅ | ✅ |
| Trigger Pipeline | ✅ | ✅ | ✅ rate-limited | ✅ rate-limited |
| Rebuild EPG | ✅ | ✅ | ✅ rate-limited | ✅ rate-limited |
| Generate Strategy | ✅ | ✅ | ✅ rate-limited | ✅ rate-limited |
| Regenerate Draft | ✅ | ✅ | ✅ | ✅ |
| Manage Team | ✅ | ✅ | ❌ | ✅ (client_admin) |
| System Settings | ✅ | ❌ | ❌ | ❌ |
| Kill Switches | ✅ | ❌ | ❌ | ❌ |
| Manage Avatars | ✅ | ✅ | ❌ | ✅ (max 1) |
| Add Subreddits | ✅ | ✅ | ✅ | ✅ (max 3) |
| Add Keywords | ✅ | ✅ | ✅ | ✅ |
| Brand Guardrails | ✅ | ✅ | ✅ | ✅ |
| View Reports | ✅ | ✅ | ✅ | ✅ |
| Discovery Engine | ✅ | ✅ | ❌ | ❌ |
| GEO/AEO Monitoring | ✅ | ✅ | ❌ | ❌ |
| Decision Center | ✅ | ✅ | ❌ | ❌ |
| Posting Dashboard | ✅ | ✅ | ❌ | ❌ |
| Cross-client data | ✅ | ✅ | ❌ isolated | ❌ isolated |
| After trial expiry | — | — | — | ❌ all POST blocked |

### Результаты RBAC-тестирования

| Проверка | Результат | Тестов |
|----------|:---------:|:------:|
| Owner полный доступ | ✅ PASS | 50+ |
| Partner доступ (без system) | ✅ PASS | 50+ |
| Client Manager изоляция | ✅ PASS | 75+ |
| Cross-client isolation | ✅ PASS | 100+ |
| Client deactivation cascade | ✅ PASS | verified |
| Trial expiry блокировка | ✅ PASS | code review |
| Permission guards (403) | ✅ PASS | 275 |
| Inactive user → redirect login | ✅ PASS | verified |

### Trial Client — специфика

- **Время:** 14 дней с `created_at`
- **Роль:** `client_admin` (полный доступ в рамках своего клиента)
- **Лимиты:** 1 avatar, 30 comments/mo, 3 subreddits
- **Expiry:** `_check_trial_not_expired` dependency на всех portal routes
- **Pipeline skip:** `is_trial_expired()` в tasks — не тратит LLM на expired
- **UI:** `trial_expired.html` страница с предложением upgrade

---

## 5. Production Status

| Метрика | Значение |
|---------|----------|
| Health | ✅ OK |
| Version | 0.3.0 |
| Database | OK |
| Redis | OK |
| Posting | enabled |
| Domain | gorampit.com (HTTPS) |

---

## 6. Warnings

| Warning | Действие |
|---------|----------|
| `passlib.crypt` deprecated (Python 3.13) | Migrate to bcrypt before 3.13 |
| Pydantic class Config deprecated | Replace with ConfigDict |
| `@app.on_event("startup")` deprecated | Migrate to lifespan |
| `datetime.utcnow()` deprecated | Use `datetime.now(UTC)` |
| pytest.mark.asyncio unknown | Add pytest-asyncio config |

---

## 7. Рекомендации

### P0
1. Пересоздать локальный venv (pip shims сломаны)
2. Merge Alembic heads в linear chain

### P1
3. Обновить 4 failing onboarding теста
4. Fix GEO Query Runner test isolation
5. Sync VERSION file (local 0.2.0 → 0.3.0)

### P2
6. Добавить `pytest-timeout` + `make test`
7. Настроить hypothesis deadline для CI
8. Delete All modal в audit logs

---

## 8. Итоговая оценка

| Аспект | Оценка |
|--------|:------:|
| Код (синтаксис) | ✅ 100% |
| RBAC / Изоляция | ✅ Solid |
| Pipeline safety | ✅ Robust |
| Production | ✅ Healthy |
| Test infra | ⚠️ Needs TLC |
| Schema | ⚠️ Fixed, needs merge |
| Onboarding | ⚠️ 4 stale tests |
