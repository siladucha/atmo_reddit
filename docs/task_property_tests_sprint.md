# Задача: Property-Based Tests для трёх спецификаций

## Контекст

Три ключевые спецификации (`mvp-hardening-sprint1`, `avatar-warming-phases`, `scheduled-scraping`) реализованы на 100% по функциональности. Остались только **опциональные property-based тесты** (помечены `*` в tasks.md). Эти тесты нужны для формальной верификации корректности — они генерируют случайные входные данные и проверяют что инварианты системы не нарушаются.

**Стек**: Python 3.12, pytest, Hypothesis (уже установлен), fakeredis, SQLAlchemy 2.0, Pydantic v2.

**Запуск тестов**: `cd reddit_saas && python -m pytest tests/ -x -q`

**Все 187 существующих тестов проходят** — ничего не должно сломаться.

---

## Что нужно сделать

Написать **40 property-based тестов** (Hypothesis) по трём спецификациям. Каждый тест проверяет конкретный инвариант системы.

---

## Спецификация 1: `scheduled-scraping` (13 тестов)

**Файлы спецификации**: `.kiro/specs/scheduled-scraping/`

### Файл: `tests/test_props_rate_limiter.py`

| # | Тест | Что проверяет | Целевой код |
|---|------|---------------|-------------|
| 2.2 | Rate limiter enforcement | При N запросах за 60s, `is_allowed(max_rpm=N)` возвращает False на N+1 запросе | `app/services/rate_limiter.py` |
| 2.3 | Backoff halving | В режиме backoff эффективный лимит = max_rpm // 2 | `app/services/rate_limiter.py` |
| 2.4 | Rate limiter utilization | `get_utilization()` возвращает корректный % (current_count / max_rpm * 100) | `app/services/rate_limiter.py` |

### Файл: `tests/test_props_distributed_lock.py`

| # | Тест | Что проверяет | Целевой код |
|---|------|---------------|-------------|
| 3.2 | Distributed lock unit tests | acquire→True, повторный acquire→False, release→можно снова acquire, TTL expiry | `app/services/distributed_lock.py` |

### Файл: `tests/test_props_queue_ticker.py`

| # | Тест | Что проверяет | Целевой код |
|---|------|---------------|-------------|
| 5.4 | Queue ticker unit tests | paused→"paused", rate_limited→"rate_limited", all_fresh→"all_fresh", lock fallback, Redis down→graceful | `app/tasks/queue_ticker.py` |
| 5.5 | Queue filtering and depth | Для любого набора subreddits с разными last_scraped_at, queue содержит только stale (> freshness_window) | `app/tasks/queue_ticker.py` |
| 5.6 | Staleness score computation | staleness_score = hours_since_last_scrape, NULL last_scraped_at → максимальный приоритет | `app/services/scrape_queue.py` |
| 5.7 | Queue ordering | Результат всегда отсортирован по last_scraped_at ASC NULLS FIRST | `app/tasks/queue_ticker.py` |

### Файл: `tests/test_props_scrape_dashboard.py`

| # | Тест | Что проверяет | Целевой код |
|---|------|---------------|-------------|
| 7.2 | Stale subreddit count | count(stale) = count(subs where last_scraped_at < now - freshness_window OR NULL) | `app/services/scrape_queue.py` |
| 7.3 | Processing speed | speed = scrape_events_in_window / window_minutes | `app/services/scrape_queue.py` |
| 7.4 | ETA calculation | ETA = stale_count / processing_speed (или ∞ если speed=0) | `app/services/scrape_queue.py` |
| 7.5 | Scrape completion event metadata | ActivityEvent содержит subreddit_name, posts_found, posts_new, duration_ms | `app/tasks/queue_ticker.py` |

### Файл: `tests/test_props_settings_validation.py`

| # | Тест | Что проверяет | Целевой код |
|---|------|---------------|-------------|
| 8.4 | Settings range validation | tick_interval ∈ [30,300], freshness_window ∈ [1,168], rate_limit ∈ [1,60] — вне диапазона отклоняется | `app/routes/admin.py` (scrape-queue settings) |

---

## Спецификация 2: `avatar-warming-phases` (14 тестов)

**Файлы спецификации**: `.kiro/specs/avatar-warming-phases/`

### Файл: `tests/test_props_phase_policy.py`

| # | Тест | Что проверяет | Целевой код |
|---|------|---------------|-------------|
| 4.2 | Phase 1 policy | Phase 1 avatar: ТОЛЬКО hobby subs, ТОЛЬКО hobby type, NO brand mentions, max 3/day | `app/services/phase.py` → `PhasePolicy.check_comment_allowed()` |
| 4.3 | Phase 2 policy | Phase 2: hobby + professional subs, block explicit brand, requires_review для inferred | `app/services/phase.py` |
| 4.4 | Phase 3 policy + ramp-up | Phase 3: все типы, ramp-up stages (early/mid/complete), brand ratio enforcement | `app/services/phase.py` |
| 4.5 | Brand mention classification | explicit_brand_link > explicit_brand_name > inferred_brand (приоритет severity) | `app/services/phase.py` → `classify_brand_mention()` |

### Файл: `tests/test_props_phase_evaluator.py`

| # | Тест | Что проверяет | Целевой код |
|---|------|---------------|-------------|
| 5.2 | Eligibility evaluation | P1→P2: age≥60, karma≥100, activity≥20, survival≥80%. P2→P3: age≥150, karma≥500, activity≥50, survival≥85%, avg_score≥2.0 | `app/services/phase.py` → `PhaseEvaluator.check_promotion_eligibility()` |
| 5.3 | Piggyback cooldown | `should_piggyback()` = True только если last_phase_evaluated_at > 4h ago или NULL | `app/services/phase.py` |
| 5.4 | Inactive avatar skip | Inactive (active=False) или shadowbanned аватары не оцениваются | `app/services/phase.py` |

### Файл: `tests/test_props_phase_transitions.py`

| # | Тест | Что проверяет | Целевой код |
|---|------|---------------|-------------|
| 7.2 | Promotion invariants | promote() всегда: new_phase = old_phase + 1, phase_changed_at обновляется, ActivityEvent создаётся | `app/services/phase.py` → `PhaseTransitionManager.promote()` |
| 7.3 | Admin override | admin_override(target) → warming_phase = target для любого target ∈ {1,2,3} | `app/services/phase.py` → `PhaseTransitionManager.admin_override()` |
| 7.4 | Shadowban demotion | Shadowbanned avatar → всегда demote to Phase 1 | `app/services/phase.py` → `PhaseEvaluator.check_demotion_triggers()` |
| 7.5 | Quality degradation demotion | survival_rate < 70% → demote by 1 (но не ниже Phase 1) | `app/services/phase.py` |
| 7.6 | New avatar defaults | Новый avatar всегда начинает с warming_phase=1 | `app/models/avatar.py` |

### Файл: `tests/test_props_safety_phase.py`

| # | Тест | Что проверяет | Целевой код |
|---|------|---------------|-------------|
| 8.2 | Policy block logging | Каждый block от PhasePolicy → ActivityEvent с event_type="policy_block" | `app/services/safety.py` |
| 9.2 | Health endpoint phase fields | `get_avatar_health()` всегда содержит warming_phase ∈ {1,2,3}, phase_label ∈ {строки}, phase_progress dict | `app/services/safety.py` |

---

## Спецификация 3: `mvp-hardening-sprint1` (13 тестов)

**Файлы спецификации**: `.kiro/specs/mvp-hardening-sprint1/`

### Файл: `tests/test_props_freeze.py`

| # | Тест | Что проверяет | Целевой код |
|---|------|---------------|-------------|
| 1.5 | Frozen avatar exclusion | Frozen avatars (is_frozen=True) НИКОГДА не попадают в candidate list для generation | `app/tasks/ai_pipeline.py` |
| 11.1 | Frozen avatar exclusion (Hypothesis) | Для любого набора avatars с random is_frozen, фильтрация оставляет только non-frozen | `app/tasks/ai_pipeline.py` |

### Файл: `tests/test_props_kill_switches.py`

| # | Тест | Что проверяет | Целевой код |
|---|------|---------------|-------------|
| 2.6 | Kill switch guards | pipeline_enabled=false → score_threads returns 0. generation_enabled=false → generate returns 0. scrape_enabled=false → scrape returns 0 | `app/tasks/ai_pipeline.py`, `app/tasks/scraping.py` |

### Файл: `tests/test_props_schemas.py`

| # | Тест | Что проверяет | Целевой код |
|---|------|---------------|-------------|
| 11.2 | ScoringOutput round-trip | Любой valid ScoringOutput → JSON → parse back → identical | `app/schemas/llm_outputs.py` |
| 11.3 | CommentOutput round-trip | Любой valid CommentOutput → JSON → parse back → identical | `app/schemas/llm_outputs.py` |
| 11.4 | Schema rejects invalid | Invalid data (relevance>3, bad tag, missing fields) → ValidationError | `app/schemas/llm_outputs.py` |
| 7.5 | Schema validation unit tests | call_llm_json с schema отклоняет malformed output | `app/services/ai.py` |

### Файл: `tests/test_props_isolation.py`

| # | Тест | Что проверяет | Целевой код |
|---|------|---------------|-------------|
| 11.5 | Client isolation in persona selection | Avatar без client_id в client_ids → AssertionError в select_persona | `app/services/generation.py` |
| 8.3 | Context isolation assertions | generate_comment с wrong client → AssertionError | `app/services/generation.py` |

### Файл: `tests/test_props_admin_emergency.py`

| # | Тест | Что проверяет | Целевой код |
|---|------|---------------|-------------|
| 4.5 | Admin emergency endpoints | freeze → is_frozen=True + audit log. unfreeze → is_frozen=False + audit log. pipeline controls → validates keys | `app/routes/admin.py` |

### Файл: `tests/test_props_retry.py`

| # | Тест | Что проверяет | Целевой код |
|---|------|---------------|-------------|
| 5.5 | Retry configuration | AI tasks: bind=True, max_retries=3. Countdown = 60 * 2^attempt (60, 120, 240). Scraping tasks НЕ имеют retry | `app/tasks/ai_pipeline.py`, `app/tasks/scraping.py` |

---

## Правила написания тестов

1. **Hypothesis settings**: `@settings(max_examples=100)` для всех property tests
2. **Стратегии**: используй `st.integers()`, `st.booleans()`, `st.text()`, `st.lists()`, `st.sampled_from()` и т.д.
3. **Fixtures**: используй существующие из `tests/conftest.py` (fake_redis, db session, test client)
4. **Изоляция**: каждый тест работает с in-memory DB (SQLite) или fakeredis — никаких внешних зависимостей
5. **Naming**: `test_prop_<property_name>` для property tests, `test_<scenario>` для unit tests
6. **Не ломай существующие тесты**: `python -m pytest tests/ -x -q` должен проходить полностью

## Критерии приёмки

- [ ] Все 40 тестов написаны и проходят
- [ ] `python -m pytest tests/ -x -q` — 0 failures (включая все 187 существующих)
- [ ] Каждый тест файл имеет docstring объясняющий какие инварианты проверяются
- [ ] Property tests используют `@settings(max_examples=100)` минимум
- [ ] Тесты не зависят от внешних сервисов (Redis, Reddit API, LLM)

## Оценка трудозатрат

~4-6 часов для опытного Python разработчика знакомого с Hypothesis.

## Как проверять

Я (Kiro) проверю реализацию по:
1. Соответствие каждого теста описанию в таблице выше
2. Корректность Hypothesis стратегий (генерируют валидные данные)
3. Тесты реально проверяют инварианты (не тривиальные assert True)
4. Все тесты проходят: `python -m pytest tests/ -x -q --tb=short`
5. Property tests находят реальные edge cases (не просто happy path)
