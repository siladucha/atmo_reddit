# QA Guide — RAMP Platform

**For:** QA Manager (Zhenya)
**Date:** July 15, 2026
**Repo:** `ReddirSaaS` (private GitHub)
**Language:** Python 3.11+ / FastAPI / Celery

---

## 1. How to Run Tests

### Requirements (Mac/Linux)

- Python 3.11+
- PostgreSQL (local, не Docker)
- Redis (local, не Docker)
- Virtual environment уже создан: `.venv/`

### Запуск

```bash
cd reddit_saas

# Активация venv
source ../.venv/bin/activate

# Все тесты (кроме зависающих):
pytest tests/ -q --timeout=30 --ignore=tests/test_geo_monitoring.py -k "not hypothesis"

# Только критические (EPG + budget + phase):
pytest tests/test_epg_budget_integrity.py tests/test_epg_daily_minimum.py tests/test_epg_responsibility_boundaries.py -v

# Один конкретный файл:
pytest tests/test_epg_budget_integrity.py -v

# Один конкретный тест:
pytest tests/test_epg_budget_integrity.py::TestAllocationFillRate::test_50_opportunities_budget_9_selects_9 -v
```

### Ожидаемый результат (baseline 15 июля 2026)

```
1542 passed, 235 skipped, 1 failed
```

- **1 failed** — `test_rented_avatar_passes_accessibility_check` (known issue, quality gate change)
- **235 skipped** — legacy тесты на рефакторенный код (см. раздел 5)

---

## 2. Структура тестов

```
tests/
├── conftest.py                          # Общие фикстуры (DB session, TestClient, auth)
├── test_epg_budget_integrity.py         # ⭐ КРИТИЧЕСКИЕ: allocation + budget + phase (19 тестов)
├── test_epg_daily_minimum.py            # EPG enforcement (13 тестов)
├── test_epg_responsibility_boundaries.py # EPG architecture contracts (22 тестов)
├── test_fitness_gate.py                 # Subreddit safety gate (39 — SKIPPED, needs mock)
├── test_runaway_protection.py           # LLM cost protection R-AI-007 (14 — SKIPPED)
├── test_phase.py                        # (НЕТ — фаза валидация только в budget_integrity)
├── test_*.py                            # ~90 других файлов (RBAC, isolation, learning, etc.)
└── ...
```

---

## 3. Приоритеты тестов (что проверять первым)

### Tier 1 — Бизнес-критические (если падают → клиент не получает контент)

| Файл | Что проверяет | Тестов |
|------|--------------|--------|
| `test_epg_budget_integrity.py` | Allocation fill rate, phase ceiling, budget math | 19 |
| `test_epg_daily_minimum.py` | EPG enforcement (гарантия ≥1 слот/день) | 13 |
| `test_epg_responsibility_boundaries.py` | EPG архитектурные контракты | 22 |

**Если любой из этих падает → блокер деплоя.**

### Tier 2 — Safety (если падают → риск бана аватаров)

| Файл | Что проверяет | Тестов |
|------|--------------|--------|
| `test_safety.py` | Brand mention protection, phase gates | ? |
| `test_health_checker.py` | Shadowban detection | ? |
| `test_isolation_helper.py` | Client data isolation | ? |
| `test_cross_client_isolation.py` | Client A ≠ Client B | ? |

### Tier 3 — Functional (если падают → фича сломана, но не критично)

Всё остальное: learning loop, discovery, onboarding, admin UI, etc.

---

## 4. Как читать результаты

### PASSED ✅
Тест прошёл. Код работает как ожидается.

### FAILED ❌
Тест упал. **Требует разбора:**
1. Прочитать `AssertionError` — что ожидалось vs что получено
2. Определить: это баг в коде или устаревший тест?
3. Если баг → создать issue
4. Если тест устарел → пометить `@pytest.mark.skip(reason="...")` + создать task на обновление

### SKIPPED ⏭️
Тест пропущен по причине (указана в output). Причины:
- `"Stale assertions after July refactoring"` — код изменился, тест не обновлён
- `"Requires Docker DB"` — тест ожидает Docker порт (5432), а мы на localhost
- `"needs mock isolation"` — тест делает реальные LLM/API вызовы, нужен mock
- `"Hangs in CI"` — зависает, нужна изоляция

---

## 5. Состояние тестов (технический долг)

### Категория A — Мёртвые (удалить)

| Файл | Skipped | Причина |
|------|---------|---------|
| `test_admin_ui_bug_conditions.py` | 16 | "Stale after July refactoring" |
| `test_ai_service.py` | 23 | "Stale after July refactoring" |
| `test_auth.py` | 9 | "Stale after July refactoring" |

**Recommendation:** Delete. The code these tests were written for has been refactored. Not worth rewriting.

### Категория B — Нужен mock (починить)

| Файл | Skipped | Что покрывает |
|------|---------|--------------|
| `test_fitness_gate.py` | 39 | Subreddit safety gate — важно! |
| `test_trial_scoring.py` | 55 | Trial health scoring |
| `test_runaway_protection.py` | 14 | LLM cost protection |

**Рекомендация:** Переписать с mock'ами для LLM/DB зависимостей. Высокий приоритет для fitness_gate и runaway.

### Категория C — Инфраструктурные (исправить конфиг)

| Файл | Skipped | Причина |
|------|---------|---------|
| `test_cqs_dispatch_pipeline.py` | 13 | Hangs — нужна mock изоляция |
| `test_cqs_task_generator.py` | 18 | Seed data interference |
| `test_discovery_routes.py` | 8 | Docker port != localhost |
| `test_pages.py` | 13 | Docker port issue |
| `test_security.py` | 10 | Docker port issue |

**Рекомендация:** Поправить DB URL в тестах (уже работает через conftest.py `DATABASE_URL` env var). Для CQS — мокнуть seed data.

---

## 6. Как добавлять новые тесты

### Правила

1. **Один тест = один баг** — каждый тест написан потому что этот баг был найден на проде
2. **Не тестировать implementation** — тестировать поведение (что система делает), не как (какой метод вызывает)
3. **Fixture `db`** — всегда используй `db` fixture из conftest. Она rollback'ит после каждого теста
4. **Naming:** `test_{что_тестируем}_{ожидаемый_результат}` — пример: `test_phase3_low_karma_demotes`
5. **Assertions**: один-два assert на тест. Не 10 assert в одном тесте.

### Шаблон

```python
def test_my_feature_expected_behavior(self, db: Session):
    """What this tests + why it matters."""
    # Arrange
    avatar = _make_avatar(db, phase=2, ...)
    
    # Act
    result = my_function(db, avatar)
    
    # Assert
    assert result == expected, f"Описание что пошло не так: got {result}"
```

### Где размещать

| Область | Файл |
|---------|------|
| EPG / Budget / Allocation | `test_epg_budget_integrity.py` |
| Phase transitions | `test_epg_budget_integrity.py` (TestPhaseCeilingValidation) |
| Scraping / Scoring | Новый файл `test_pipeline_scoring.py` |
| Extension / Posting | Новый файл `test_execution_pipeline.py` |
| Isolation / RBAC | `test_cross_client_isolation.py` |

---

## 7. CI Pipeline (GitHub Actions)

**Файл:** `.github/workflows/ci.yml`

**Что запускает:**
1. Install dependencies
2. `python -c "from app.main import app"` — import smoke test
3. `alembic heads` — single migration head check
4. `pytest tests/ -x -q --timeout=30 ...` — full test run

**Блокирует merge?** Пока нет (Phase 1 — информационный). Станет блокером когда 0 failures 5 дней подряд.

---

## 8. Git / Repo навигация

### Ключевые директории

```
reddit_saas/
├── app/
│   ├── services/           # Бизнес-логика (allocation_engine, phase, generation)
│   ├── tasks/              # Celery tasks (epg, ai_pipeline, execution_tasks)
│   ├── models/             # SQLAlchemy модели (avatar, epg_slot, post_draft)
│   ├── routes/             # FastAPI endpoints (admin, portal, extension_api)
│   └── templates/          # Jinja2 HTML (admin, client portal)
├── tests/                  # ← ТЕСТЫ ЗДЕСЬ
├── alembic/                # DB migrations
├── .github/workflows/      # CI/CD
└── .kiro/steering/         # Architecture docs (для AI agent)
```

### Как найти тест для конкретного сервиса

```bash
# Пример: найти тесты связанные с EPG
grep -rl "epg\|allocation\|portfolio" tests/

# Найти тесты для phase evaluation
grep -rl "PhaseEval\|phase_ceiling\|check_demotion" tests/

# Найти все тесты которые создают Avatar
grep -rl "_make_avatar\|Avatar(" tests/
```

### Как посмотреть coverage конкретного модуля

```bash
pytest tests/test_epg_budget_integrity.py --cov=app.services.allocation_engine --cov-report=term
```

---

## 9. Production Monitoring (связь с тестами)

Каждый тест в `test_epg_budget_integrity.py` соответствует реальному production инциденту:

| Тест | Инцидент (15 июля 2026) |
|------|------------------------|
| `test_50_opportunities_budget_9_selects_9` | d-wreck-w12: budget=9, получил 1 слот |
| `test_phase3_low_karma_demotes` | Hot-Thought2408: Phase 3 без кармы, 15 слотов |
| `test_phase1_cqs_low_budget_2` | Flaky_Finder_13: budget должен быть 2, получил 3 |
| `test_all_same_subreddit_still_fills_with_cap` | Phase 1 аватары с 1 sub получали 1 из 3 |

**Правило:** Каждый новый production баг → сначала тест (red), потом фикс (green).

---

## 10. Контакты

- **Код:** Max (tech lead) — все вопросы по архитектуре и "почему так"
- **Бизнес-логика:** Max + Tzvi — что система ДОЛЖНА делать
- **Infra:** Max — деплой, CI, серверы
