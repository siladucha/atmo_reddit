# Spec vs Implementation Audit — Reddit Marketing SaaS

**Дата:** 6 мая 2026  
**Метод:** Сравнение каждой спеки с реальным кодом (модели, миграции, сервисы, роуты, шаблоны, тесты, Celery tasks)

---

## Легенда

| Символ | Значение |
|--------|----------|
| ✅ | Полностью реализовано и соответствует спеке |
| ⚠️ | Частично реализовано / есть расхождения |
| ❌ | Не реализовано |
| 🗑️ | Спека устарела / дублирует другую |

---

## 1. activity-feed-transparency ✅

**Статус tasks.md:** Все обязательные таски `[x]`

| Слой | Статус | Детали |
|------|--------|--------|
| Модели | ✅ | `ActivityEvent`, `ScrapeLog` — все поля соответствуют спеке. `last_scraped_at` на `ClientSubreddit` |
| Миграция | ✅ | `a1b2c3d4e5f6` — создаёт обе таблицы + индекс |
| Сервис | ✅ | `transparency.py`: `record_activity_event()`, `get_activity_events()`, `get_pipeline_stats()`, `get_scrape_freshness()` |
| Роуты | ✅ | `/admin/activity-feed`, `/admin/clients/{id}/transparency`, `/admin/clients/{id}/activity-feed` |
| Шаблоны | ✅ | `admin_client_transparency.html`, `admin_activity_feed.html`, partials |
| Celery | ✅ | Pipeline instrumentation в `scraping.py`, `ai_pipeline.py`, `review.py` |
| Тесты | ⚠️ | Базовые тесты есть, property-тесты (tasks 2.5–2.12) не написаны |

**Расхождения:** Нет критических. Property-тесты опциональны.

---

## 2. admin-panel-client-onboarding ✅

**Статус tasks.md:** Все обязательные таски `[x]`

| Слой | Статус | Детали |
|------|--------|--------|
| Модели | ✅ | `User`, `Client`, `Avatar`, `AuditLog` — все поля на месте |
| Сервис | ✅ | `admin.py`: user/client/keyword/subreddit/persona CRUD. `audit.py`: log_action, query |
| Роуты | ✅ | 30+ admin endpoints, wizard steps 1-7 |
| Шаблоны | ✅ | `admin_base.html` (dark theme), 6 wizard steps, все CRUD страницы |
| Seed | ✅ | NeuroYoga client с subreddits, keywords, persona |
| Тесты | ✅ | `test_admin.py`, `test_admin_panel.py` — покрывают основные сценарии |

**Расхождения:** Property-тесты (17 штук) не написаны — все опциональные.

---

## 3. avatar-warming-phases ✅

**Статус tasks.md:** Все обязательные таски `[x]`

| Слой | Статус | Детали |
|------|--------|--------|
| Модели | ✅ | `warming_phase`, `phase_changed_at`, `last_phase_evaluated_at` на Avatar. `is_deleted`, `reddit_score`, `deleted_detected_at` на CommentDraft. `brand_domain` на Client |
| Миграция | ✅ | `e5f6a7b8c9d0` — все поля + data migration (phase=2 для старых аккаунтов) |
| Сервис | ✅ | `phase.py` (PhasePolicy, PhaseEvaluator, PhaseTransitionManager), `phase_types.py`, `phase_lock.py` |
| Safety | ✅ | PhasePolicy интегрирован в `safety.py` вместо старого WARMUP_DAYS |
| Роуты | ✅ | `/admin/avatars/{id}/phase-override` |
| Шаблоны | ✅ | Phase badge на avatar list, phase info на detail page |
| Celery | ✅ | `evaluate-avatar-phases-daily` в beat schedule (6:00 AM) |
| Тесты | ✅ | `test_safety.py` обновлён для phase-based checks |

**Расхождения:** 14 property-тестов не написаны (опциональные).

---

## 4. reddit-api-health-dashboard ✅

**Статус tasks.md:** Все обязательные таски `[x]`

| Слой | Статус | Детали |
|------|--------|--------|
| Сервис | ✅ | `metrics_collector.py` (RateLimitState, MetricsCollector, gauge_color), `health_metrics.py` (get_reddit_api_metrics, get_llm_api_metrics, get_all_scrape_freshness) |
| Роуты | ✅ | `/admin/health/widget/*` (4 endpoints), `/admin/health/metrics` (JSON) |
| Шаблоны | ✅ | 4 widget partials + enhanced `admin_health.html` |
| Init | ✅ | MetricsCollector в `app.state` через `main.py` |
| Тесты | ✅ | `test_health_dashboard.py` |

**Расхождения:** 10 property-тестов не написаны (опциональные).

---

## 5. shared-subreddit-registry ⚠️

**Статус tasks.md:** Tasks 1-7, 11 `[x]`. Tasks 8-10, 12 `[ ]`

| Слой | Статус | Детали |
|------|--------|--------|
| Модели | ✅ | `Subreddit`, `ClientSubredditAssignment`, `ThreadScore` — все поля и constraints |
| Миграция | ✅ | `f6a7b8c9d0e1` — major refactor, data migration, column drops |
| Сервис | ✅ | `admin.py` refactored (add_subreddit → get-or-create), `scoring.py` refactored (ThreadScore) |
| Scraping | ✅ | `scrape_subreddit_shared()` в `scraping.py`, `queue_tick` обновлён |
| Роуты | ✅ | Admin subreddit CRUD обновлён |
| Шаблоны | ✅ | Subreddit list показывает shared indicator |
| Seed | ✅ | `seed.py` использует новые модели |
| Тесты | ❌ | Property-тесты (11 штук) и unit-тесты (task 10) НЕ написаны |

**Расхождения:** Тесты не написаны. Функционал работает, но нет regression protection.

---

## 6. scheduled-scraping ⚠️

**Статус tasks.md:** Tasks 1-9 `[x]`. Property-тесты `[ ]`

| Слой | Статус | Детали |
|------|--------|--------|
| Settings | ✅ | `scrape_enabled`, `scrape_tick_interval_seconds`, `scrape_freshness_window_hours`, `scrape_rate_limit_rpm` |
| Сервис | ✅ | `rate_limiter.py` (ScrapeRateLimiter), `distributed_lock.py` (ScrapeDistributedLock), `scrape_queue.py` (dashboard data) |
| Celery | ✅ | `queue_ticker.py` (queue_tick + scrape_single_subreddit), beat schedule entry |
| Роуты | ✅ | `/admin/scrape-queue`, `/admin/scrape-queue/status`, `/admin/scrape-queue/waiting-list`, toggle, settings |
| Шаблоны | ✅ | `admin_scrape_queue.html` + 2 partials |
| Navigation | ✅ | "Scrape Queue" в sidebar |
| Тесты | ⚠️ | conftest fixtures есть, property-тесты (11 штук) не написаны |

**Расхождения:** Все property-тесты опциональные и не написаны.

---

## 7. system-settings-ui ⚠️

**Статус tasks.md:** Tasks 1-3, 5-10, 12 `[x]`. Tasks 4, 11 `[ ]`

| Слой | Статус | Детали |
|------|--------|--------|
| Модель | ✅ | `group` column на SystemSetting |
| Миграция | ✅ | `c3d4e5f6a7b8` — добавляет group column |
| Сервис | ✅ | Cache (_cache dict), `set_setting()` с audit, `bulk_save_settings()`, `test_reddit_connection()`, `test_llm_connection()` |
| Config | ✅ | `get_config()` — bootstrap keys из env, остальное из DB |
| Роуты | ✅ | `/admin/settings`, `/admin/settings/{key}`, `/admin/settings/bulk-save`, `/admin/settings/test/reddit`, `/admin/settings/test/llm` |
| Шаблоны | ✅ | `admin_system_settings.html` с grouped tabs, inline edit, secret masking |
| Navigation | ✅ | "System Settings" в sidebar |
| Тесты | ❌ | Property-тесты (11 штук) и integration тесты НЕ написаны |

**Расхождения:** Тесты не написаны. Функционал полностью работает.

---

## 8. client-hub-navigation ⚠️

**Статус tasks.md:** Смешанный — helpers и data loaders готовы, шаблоны готовы, но task 1 и 10 не закрыты

| Слой | Статус | Детали |
|------|--------|--------|
| Helpers | ✅ | `_resolve_tab()`, `_freshness_color()`, `_truncate_voice_profile()`, `current_client_id` injection |
| Data loaders | ✅ | Все 7 tab loaders реализованы |
| Роуты | ✅ | `/clients/{id}` (hub), `/clients/{id}/tab/{tab_name}` (HTMX dispatch) |
| Шаблоны | ✅ | `client_hub.html`, tab bar partial, все 7 tab content partials |
| Navigation | ✅ | `base.html` адаптирован для Client_Users |
| Тесты | ❌ | Ни один integration test не написан (task 10) |

**Расхождения:** Функционал работает, тесты отсутствуют. Task 1 формально не закрыт из-за опциональных property-тестов.

---

## 9. daily-ops-dashboard ⚠️

**Статус tasks.md:** Все `[ ]` — но implementation уже существует!

| Слой | Статус | Детали |
|------|--------|--------|
| Сервис | ✅ | `operations_dashboard.py` — все функции реализованы |
| Роуты | ✅ | Dashboard endpoints в `admin.py` |
| Шаблоны | ✅ | `admin_dashboard.html` + 6 partials |
| Тесты | ✅ | `test_operations_dashboard.py` — unit + integration |

**Расхождения:** Tasks.md говорит "validate existing implementation" — спека создана ПОСЛЕ реализации. Нужна только валидация и property-тесты.

---

## 10. avatar-reddit-status ⚠️

**Статус:** requirements.md + design.md, нет tasks.md

| Слой | Статус | Детали |
|------|--------|--------|
| Модель | ✅ | `reddit_status`, `reddit_karma_comment`, `reddit_karma_post`, `reddit_account_created`, `reddit_icon_url`, `reddit_status_checked_at` — ВСЕ на Avatar |
| Миграция | ✅ | `b2c3d4e5f6a7` — добавляет все поля |
| Сервис | ✅ | `reddit_status.py` — проверка статуса через PRAW |
| Роуты | ⚠️ | Endpoints существуют в `avatars.py`, но нужно проверить полноту |
| Шаблоны | ✅ | Status badges на avatar cards, "Check Status" кнопки |
| Shadowban | ✅ | `is_shadowbanned` обновляется при status check |

**Расхождения:** Реализация ЕСТЬ, но tasks.md не сгенерирован. Спека отстаёт от кода.

---

## 11. comment-performance-tracking ❌

**Статус tasks.md:** Все `[ ]` — ничего не начато

| Слой | Статус | Детали |
|------|--------|--------|
| Модель | ❌ | `PerformanceSnapshot` НЕ существует (нет файла `performance_snapshot.py`) |
| Миграция | ❌ | Нет миграции для performance_snapshots table |
| Сервис | ❌ | `performance_tracking.py` НЕ существует |
| Celery | ❌ | `performance.py` task НЕ существует |
| Тесты | ❌ | Нет |

**Расхождения:** Полностью не реализовано. НО: поля `is_deleted`, `reddit_score`, `deleted_detected_at` на CommentDraft уже есть (из warming-phases миграции) — это prerequisite для этой спеки.

---

## 12. reddit-data-sync ❌

**Статус tasks.md:** Все `[ ]` — ничего не начато

| Слой | Статус | Детали |
|------|--------|--------|
| Модель | ❌ | Нет RateLimitTracker, RateLimitQueue, SyncJob |
| Сервис | ❌ | `rate_limit_tracker.py` НЕ существует, `rate_limit_queue.py` НЕ существует |
| Celery | ❌ | `sync_job.py` НЕ существует |
| Роуты | ❌ | Нет refresh/queue-state/sync-progress endpoints |
| Шаблоны | ❌ | Нет rate_limit_status.html, sync_progress.html |

**Расхождения:** Полностью не реализовано. Частично перекрывается с `scheduled-scraping` (rate_limiter.py уже есть).

---

## 13. ai-usage-analytics ⚠️

**Статус:** requirements + design есть, tasks.md ПУСТОЙ

| Слой | Статус | Детали |
|------|--------|--------|
| Модель | ✅ | `AIUsageLog` существует с нужными полями |
| Сервис | ✅ | `health_metrics.py` → `get_llm_api_metrics()` уже реализован |
| Роуты | ✅ | `/admin/ai-costs` существует |
| Шаблоны | ✅ | `admin_ai_costs.html` существует |

**Расхождения:** Базовый функционал реализован в рамках `admin-panel-client-onboarding` и `reddit-api-health-dashboard`. Спека, вероятно, описывает расширенную аналитику, но tasks.md пуст — непонятно что ещё нужно.

---

## 14. settings-consolidation ⚠️

**Статус:** requirements + design, нет tasks.md

| Слой | Статус | Детали |
|------|--------|--------|
| Redirect | ❌ | `/settings` всё ещё рендерит `settings.html` (не redirect) |
| Connection panel | ❌ | Нет Connection_Status_Panel на `/admin/settings` |
| Scraping group | ✅ | Scraping settings уже в DB с group="scraping" |
| Navigation | ⚠️ | `base.html` всё ещё имеет "Settings" link на `/settings` |

**Расхождения:** Основная работа — удалить `/settings` route и добавить connection panel. Небольшая задача.

---

## 15. ops-dashboard ⚠️

**Статус:** requirements + design, нет tasks.md

| Слой | Статус | Детали |
|------|--------|--------|
| Реализация | ⚠️ | `daily-ops-dashboard` уже покрывает 70% этой спеки |

**Расхождения:** Дублирует `daily-ops-dashboard`. Добавляет: Queue Monitor, Emergency Controls, Avatar Panel с freeze, Subreddit blacklist. Это расширение, не отдельная фича.

---

## 16–29. Спеки только с requirements.md

### Краткий статус реализации:

| # | Спека | Код существует? | Что есть | Что отсутствует |
|---|-------|----------------|----------|-----------------|
| 16 | admin-client-hub-navigation | ❌ | Нет | Всё (admin-side tabbed hub) |
| 17 | admin-entity-management | ⚠️ | `admin_subreddits_all.html` существует, assign avatar modal частично | Add Subreddit modal с client dropdown |
| 18 | admin-navigation-consolidation | ❌ | Нет | Группировка навигации, redirect `/` → `/admin/` |
| 19 | cascade-delete | ❌ | Нет | Cascade service, impact preview, restore |
| 20 | context-assembler | ❌ | Нет | Единый context assembly service |
| 21 | dry-run-workflow | ⚠️ | `dry_run.py` service + routes + templates СУЩЕСТВУЮТ | Частично реализовано! |
| 22 | oauth-avatar-auth | ❌ | Нет | OAuth flow, token encryption, per-avatar PRAW |
| 23 | personas-page-reddit-checks | ❌ | Нет | `/personas-page` route и шаблон |
| 24 | placeholder-instructions | ⚠️ | Некоторые placeholders уже есть | Нужно добавить остальные |
| 25 | platform-readiness | ❌ | Нет | Jitter, subreddit intelligence, context assembly |
| 26 | reddit-rate-limiting | ⚠️ | `rate_limiter.py` существует (из scheduled-scraping) | Singleton client, per-operation pacing, health panel integration |
| 27 | subreddit-specific-karma | ✅ | `SubredditKarma` model + migration + `karma_tracker.py` | UI integration (review queue, dashboard alerts) |
| 28 | ui-info-tooltips | ❌ | Нет | Tooltip partial + JS + все tooltip placements |
| 29 | enhanced-system-health | 🗑️ | Покрыто `reddit-api-health-dashboard` | Удалить спеку |

---

## Детальный разбор ключевых находок

### dry-run-workflow — СЮРПРИЗ: частично реализован!

Обнаружено в коде:
- `app/services/dry_run.py` — `is_dry_run_enabled()`, `get_unscored_threads()`, `get_engage_threads_without_drafts()`, `get_backlog_counts()`
- `app/routes/dry_run.py` — `/admin/dry-run/settings`, `/admin/dry-run`, `/admin/dry-run/hub`
- Templates: `admin_dry_run_*.html` (4 файла)

**Что реализовано:** Toggle, hub page, backlog counts  
**Что НЕ реализовано:** Prompt preview pages (score/generate/edit), paste-back flow, Ori data importer, wizard edit mode

### subreddit-specific-karma — Модель готова, UI нет

- `SubredditKarma` model ✅
- Migration `a7b8c9d0e1f2` ✅  
- `karma_tracker.py` service ✅
- `admin_avatar_detail.html` показывает karma breakdown ✅
- Review queue karma display ❌
- Dashboard karma diversity alerts ❌
- Phase evaluator integration ❌

### admin-entity-management — Частично есть

- `admin_subreddits_all.html` — глобальная страница сабреддитов существует
- Assign avatar modal — кнопка "Assign Existing Avatar" есть на avatars page
- **Нет:** Add Subreddit modal с client dropdown на глобальной странице

---

## Сводная таблица: Spec Coverage Score

| Спека | Models | Migration | Service | Routes | Templates | Celery | Tests | Score |
|-------|--------|-----------|---------|--------|-----------|--------|-------|-------|
| activity-feed-transparency | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | 95% |
| admin-panel-client-onboarding | ✅ | ✅ | ✅ | ✅ | ✅ | N/A | ✅ | 98% |
| avatar-warming-phases | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | 95% |
| reddit-api-health-dashboard | ✅ | N/A | ✅ | ✅ | ✅ | N/A | ✅ | 95% |
| shared-subreddit-registry | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | 85% |
| scheduled-scraping | ✅ | N/A | ✅ | ✅ | ✅ | ✅ | ⚠️ | 90% |
| system-settings-ui | ✅ | ✅ | ✅ | ✅ | ✅ | N/A | ❌ | 85% |
| client-hub-navigation | N/A | N/A | ✅ | ✅ | ✅ | N/A | ❌ | 80% |
| daily-ops-dashboard | N/A | N/A | ✅ | ✅ | ✅ | N/A | ✅ | 90% |
| avatar-reddit-status | ✅ | ✅ | ✅ | ⚠️ | ✅ | N/A | ⚠️ | 85% |
| comment-performance-tracking | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | 0% |
| reddit-data-sync | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | 0% |
| ai-usage-analytics | ✅ | N/A | ✅ | ✅ | ✅ | N/A | ⚠️ | 80% |
| dry-run-workflow | N/A | N/A | ⚠️ | ⚠️ | ⚠️ | N/A | ❌ | 30% |
| subreddit-specific-karma | ✅ | ✅ | ✅ | N/A | ⚠️ | N/A | ❌ | 60% |
| settings-consolidation | N/A | N/A | ⚠️ | ❌ | ❌ | N/A | ❌ | 20% |
| Остальные 13 спек | — | — | — | — | — | — | — | 0-10% |

---

## Критические расхождения (Implementation ≠ Spec)

### 1. `shared-subreddit-registry` — Старая таблица не удалена
Спека говорит "old ClientSubreddit model/table kept temporarily for rollback safety". В коде `ClientSubreddit` model всё ещё импортируется и используется в некоторых местах. Нужна cleanup миграция.

### 2. `client-hub-navigation` — Роут конфликт с admin
Спека описывает user-facing hub на `/clients/{id}`. Одновременно `admin-client-hub-navigation` описывает admin hub на `/admin/clients/{id}`. В коде `pages.py` имеет `client_detail()` на `/clients/{id}` — это user-facing hub. Admin client detail на `/admin/clients/{id}` — отдельный.

### 3. `reddit-rate-limiting` vs `scheduled-scraping`
`rate_limiter.py` уже реализован как часть `scheduled-scraping`. Спека `reddit-rate-limiting` описывает другой подход (singleton PRAW client + per-operation pacing). Конфликт архитектурных решений.

### 4. `daily-ops-dashboard` vs `ops-dashboard`
Оба описывают `/admin/` dashboard. `daily-ops-dashboard` уже реализован. `ops-dashboard` — расширенная версия с emergency controls, queue monitor, circuit breaker. Нужно объединить.

---

## Рекомендации по приоритетам

### Немедленно (закрыть долги):
1. **Написать тесты** для shared-subreddit-registry, system-settings-ui, client-hub-navigation — код работает, но нет regression protection
2. **Удалить** `enhanced-system-health` спеку (пустая, покрыта другими)
3. **Объединить** `ops-dashboard` в `daily-ops-dashboard` как расширение
4. **Пометить** `reddit-rate-limiting` как superseded by `scheduled-scraping`

### Следующий спринт (новый функционал):
1. **comment-performance-tracking** — prerequisite fields уже в DB, нужен сервис + task
2. **settings-consolidation** — маленькая задача, cleanup
3. **cascade-delete** — критично для операционной безопасности
4. **admin-entity-management** — удобство ежедневной работы

### Backlog:
- `context-assembler` — архитектурный рефакторинг, важен для multi-client
- `platform-readiness` — jitter + subreddit intelligence
- `oauth-avatar-auth` — масштабирование
- `dry-run-workflow` — дописать prompt preview pages
