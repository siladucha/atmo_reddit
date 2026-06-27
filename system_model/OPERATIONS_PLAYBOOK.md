# RAMP — Operations Playbook & System Model Verification

**Автор:** AI Agent (Kiro)
**Дата:** June 27, 2026
**Версия системы:** 0.3.0
**Цель:** Полное описание того, что система делает автономно, какие решения принимает сама, где есть разрывы и риски. Документ для верификации Max + Tzvi до передачи автономного управления агенту.

---

## Часть 1. Что система делает пока вы спите

### 1.1 Ежедневный цикл (Asia/Jerusalem timezone)

Каждый день, без участия человека, RAMP выполняет ~30 Celery Beat задач:

| Время | Задача | Автономное решение |
|-------|--------|-------------------|
| каждые 60с | `queue_tick` | Решает какие сабреддиты пора скрейпить (по freshness window) |
| каждые 60с | `system_heartbeat` | Только мониторинг (пишет в Redis) |
| каждые 5 мин | `execute_pending_posts` | **ПОСТИТ** если все 9 safety gates пройдены |
| каждые 5 мин | `dispatch_due_email_tasks` | **РЕШАЕТ**: послать email или отменить (liveness + health + quiet hours) |
| каждые 4ч (:15) | `track_karma_all_avatars` | Обновляет karma + auto-link drafts к Reddit комментам |
| каждые 4ч (:30) | `check_trial_negative_signals` | Детектит проблемы trial клиентов |
| каждые 4ч (:45) | `snapshot_comment_outcomes` | Проверяет karma/удаления комментов |
| 01:00 | `compute_daily_performance_metrics` | Агрегация метрик (информационно) |
| 01:30 | `archive_old_decision_records` | Удаляет записи >90 дней |
| 02:00 | `run_feedback_loop_all` | **КОРРЕКТИРУЕТ** EPG модель (суб. приоритеты, гипотезы) |
| 02:30 | `classify_expired_trials` | Помечает expired trials |
| 05:20 | `snapshot_profile_analytics` | Снимок Reddit профилей |
| 06:00 | `evaluate_all_avatar_phases` | **РЕШАЕТ**: повысить/понизить фазу аватара |
| 06:30 | `check_cqs_all_avatars` | **РЕШАЕТ**: заморозить при lowest CQS |
| 07:00 | `generate_cqs_check_tasks` | Создает CQS задачи для исполнителей |
| 07:30, 13:30 | `health_check_all_avatars` | **РЕШАЕТ**: заморозить при shadowban/suspended |
| 07:45, 13:45 | `scrape_hobby_all_avatars` | Скрейпит hobby сабреддиты |
| 08:00, 14:00 | `run_full_pipeline_all_clients` | **РЕШАЕТ**: какие треды score=engage, генерирует комменты |
| 08:15, 14:15 | `build_and_generate_epg_all_avatars` | **РЕШАЕТ**: бюджет, слоты, auto-approve |
| 12:15, 18:15 | `check_karma_outcomes` | 4ч karma outcome check |
| 00:15, 06:15 | `check_karma_outcomes` | 24-28ч karma outcome check |
| 23:30 | `expire_overdue_execution_tasks` | Expired задачи переходят в terminal state |

**Еженедельные (Sunday):**

| Время | Задача | Автономное решение |
|-------|--------|-------------------|
| 03:00 Sun | `scrape_repurpose_all_subreddits` | Скрейпит top/year для evergreen контента |
| 04:00 Sun | `run_continuous_discovery_all` | **ГЕНЕРИРУЕТ** гипотезы, entity extraction |
| 04:30 Sun | `refresh_subreddit_emotional_profiles` | **ОБНОВЛЯЕТ** emotional profiles сабреддитов |
| 05:00 Sun | `extract_subreddit_rules_batch` | **ИЗВЛЕКАЕТ** правила из sidebar/wiki через LLM |
| 05:15 Sun | `compute_moderation_profiles_batch` | Агрегирует moderation статистику |
| 05:30 Sun | `compute_risk_scores_batch` | **ВЫЧИСЛЯЕТ** risk score (0-100) для сабреддитов |

---

### 1.2 Решения, которые система принимает САМА

#### Категория A — Заморозка аватара (необратима без ручного вмешательства)

| Триггер | Условие | Действие | Откат |
|---------|---------|----------|-------|
| Health check | profile inaccessible (404/403) | `is_frozen=True`, `freeze_reason=suspended` | Admin → Unfreeze |
| Health check | visibility ratio = 0 | `is_frozen=True`, `freeze_reason=shadowbanned` | Admin → Unfreeze |
| Health check | submission не видна в ленте sub | `is_frozen=True`, `freeze_reason=shadowbanned` | Admin → Unfreeze |
| Health check | unknown >48h | `is_frozen=True`, `freeze_reason=health_unknown_stale_48h` | Admin → Unfreeze |
| CQS check | cqs_level=lowest + Phase 2+ | `is_frozen=True`, `freeze_reason=cqs_lowest` | Admin → Unfreeze |
| Posting | 3 consecutive failures | `is_frozen=True`, `freeze_reason=consecutive_failures` | Admin → Unfreeze |
| Posting | Auth error (401/403) | `is_frozen=True`, `freeze_reason=auth_error` | Admin → Unfreeze |

**Последствия заморозки:** Аватар выпадает из ВСЕХ пайплайнов (EPG, scoring, generation, email tasks). Исполнитель перестает получать задачи. Клиент видит меньше активности.

**⚠️ РИСК:** Ложная заморозка здорового аватара (напр. Reddit API timeout → consecutive failures → freeze). Клиент теряет coverage до ручного unfreeze.

#### Категория B — Понижение фазы (снижает output на 80%)

| Триггер | Условие | Действие |
|---------|---------|----------|
| Phase eval (06:00) | survival_rate < 70% за 7 дней (мин. 5 posted) | Phase N → Phase N-1 |
| Phase eval (06:00) | avg karma < -2 за 14 дней | Phase N → Phase N-1 |
| Health check | shadowban detected | → Phase 1 |

**Последствия:** Phase 2→1 = профессиональный pipeline отключается (source 1 gated to Phase 2+). Остается только hobby pipeline (1-3 комментов/день вместо 5-15). Клиент видит резкое падение активности.

**Safety:** `_DEMOTION_MIN_SAMPLE_SIZE = 5` — если <5 posted за 7 дней, survival rate = 1.0 (нет демотии). Защита от ложных срабатываний при малом объеме.

#### Категория C — Фильтрация контента (снижает объем выдачи)

| Фильтр | Условие | Что пропускается |
|--------|---------|-----------------|
| Hot thread | ups > 200 И karma аватара < 100 в этом sub | Тред пропускается |
| Link/video/image | url указывает на внешний домен | Тред пропускается |
| Fitness gate | min_karma / min_age / frequency / aggressiveness / dangerous hours | Тред блокируется для этого аватара |
| Subreddit ban | Avatar banned from sub | Тред блокируется |
| Thread locked | `is_locked = True` | Тред пропускается |
| Thread age | > 48 часов | Тред не скорится |
| Budget cap | remaining_budget × 3 (HARD_CAP=15) | Только top-N тредов скорятся |

**⚠️ РИСК:** Все фильтры fail-open по умолчанию (кроме subreddit ban). Если Risk Profile отсутствует — fitness gate пропускает. Если HobbySubreddit не имеет url — пропускает.

#### Категория D — Auto-approve (человек полностью исключен)

| Условие | Эффект |
|---------|--------|
| `client.autopilot_enabled = True` | ВСЕ draft-ы для этого клиента approve автоматически |
| `avatar.auto_approve_drafts = True` | ВСЕ draft-ы этого аватара approve автоматически |

**Последствия:** Draft → approved → execution task → email → executor posts. Человек НЕ видит контент до отправки. Весь pipeline: AI → approve → deliver за один цикл.

**⚠️ КРИТИЧЕСКИЙ РИСК:** Если LLM сгенерирует нежелательный контент (brand mention в Phase 1, оскорбления, nonsense) — он будет auto-approved и отправлен исполнителю. Единственная защита: PhasePolicy + safety_blocks (проверяет brand mentions программно).

#### Категория E — Feedback Loop (автоматическая коррекция модели)

| Что корректируется | Как | Масштаб |
|-------------------|-----|---------|
| Hypothesis confidence | Outcomes (karma, deletion) → confidence change | Discovery engine |
| Subreddit priority | Performance data → priority adjustments | EPG allocation |
| Performance context | Summary stored for next strategy generation | Strategy prompt |

**Это тихая адаптация** — система меняет свои внутренние веса, что влияет на будущие решения (какие сабреддиты получат больше слотов, какие гипотезы будут приоритизированы). Нет UI для отслеживания этих изменений в реальном времени.

---

## Часть 2. Что мне (агенту) известно и понятно

### 2.1 Полностью понятные подсистемы (могу модифицировать уверенно)

| Подсистема | Почему понятна | Confidence |
|-----------|---------------|-----------|
| Posting Safety Gates | 9 проверок в порядке, каждая документирована в коде. Линейная логика. | 99% |
| Phase Policy | PhasePolicy + PhaseEvaluator: правила, пороги, daily limits — всё explicit. | 95% |
| Smart Scoring | Budget formula + filters + hot thread guard. Один файл, чистая логика. | 98% |
| Kill Switches | 8 switches в settings.py, каждый проверяется в конкретном месте. | 99% |
| Fitness Gate | 6 проверок + fail-open. Документировано какие правила из какого поля. | 95% |
| Trial Guard | 3 строки кода. Тривиально. | 100% |
| Execution Tasks | State machine (ALLOWED_TRANSITIONS dict), идемпотентность, anti-spam. | 95% |
| Health Checker | Multi-layer detection: profile → comments → submissions. Логика ветвления ясна. | 90% |
| EPG Dedup Guard | 2-level check + max 2 attempts. Зафиксирован после incident June 25. | 98% |
| Draft Reconciliation | 3-pass matching (exact, fuzzy, thread+timing). Понятные thresholds. | 95% |
| Email Dispatch | Quiet hours gate + health check + liveness check + anti-spam. | 95% |

### 2.2 Подсистемы с неполным пониманием

| Подсистема | Что неясно | Почему важно |
|-----------|-----------|-------------|
| Feedback Loop → EPG weights | КАК именно subreddit_priority_adjustments влияют на allocation_engine? Трассировка: feedback_loop.py → store → ... portfolio_manager reads? Или нет? | Тихая адаптация может дрейфить в нежелательном направлении |
| Outcome Analysis | generate_feedback_packet() — какие именно сигналы и с какими весами? | Определяет что feedback loop "видит" |
| Opportunity Engine scoring | 6 dimensions (visibility, competition, trust, karma, risk, strategic) — формулы? Как считается каждый dimension score? | Определяет какие треды попадают в EPG |
| Return Engine | estimate_returns() — subreddit_karma_multiplier, trust/visibility/influence — как вычисляются? | Определяет ранжирование opportunities |
| Continuous Discovery | Что именно entity_extractor извлекает? Как hypothesis_engine решает confirmed/rejected? | Влияет на strategy_context клиента |
| Strategy Handoff → Generation | Как strategy_context инжектится в generation prompt? Какие поля используются? | Может влиять на качество/тон комментов |
| Learning Loop | Как few-shot examples отбираются? Max кол-во? Retention policy? | Определяет адаптацию генерации |
| PRAW Factory | Dual-mode (password + OAuth). Какой mode active? Proxy routing per avatar? | Критично для posting reliability |
| Celery Beat catch-up | После restart Beat fires overdue tasks. `--skip-overdue` используется? celerybeat-schedule file чистится? | Был root cause дупликации June 25 |

### 2.3 Что мне известно из продакшена (верифицировано)

Факты, подтвержденные кодом и ops логами:

1. **POSTING_DISABLED=true** на продакшене → автопостинг заблокирован на уровне env var (не togglable из admin)
2. **3 аватара с executor_email** (Hot-Thought2408, Flaky_Finder_13, StopAutomatic717) — остальные 22 не настроены
3. **Flaky_Finder_13 globally shadowbanned** (June 25) — заморожен
4. **5 suspended аватаров** — ThorneMarcus92, RoutineAnywhere2705, leon_grant10, JJVillanM, naomi_rush
5. **epg2_enabled = true** — Portfolio Manager active (не legacy EPG)
6. **email_tasks_enabled** — должно быть "true" для email доставки
7. **fitness_gate_enabled = true** (default)
8. **pipeline_enabled = true, generation_enabled = true, scrape_enabled = true** — pipeline работает
9. **auto_posting_daily_cap = 8** (default)
10. **Quiet hours: 23:00-07:00 Israel** — email dispatch не работает в это время

---

## Часть 3. Разрывы (Gaps) — что я вижу

### 3.1 Архитектурные разрывы

| # | Gap | Severity | Описание | Риск |
|---|-----|----------|----------|------|
| G1 | Нет "undo" для auto-approve | HIGH | Если autopilot_enabled=True и LLM генерирует мусор — draft уходит в approved без review. Единственная защита: PhasePolicy brand check (regex-based). | Испорченный контент отправлен исполнителю |
| G2 | Feedback loop не наблюдаем | MEDIUM | Adjustments (subreddit priorities, hypothesis confidence) применяются молча. Нет UI для отслеживания drift. Activity event пишется, но не визуализирован. | Система может дрейфить к нежелательным сабреддитам |
| G3 | Нет rate limit на freeze events | MEDIUM | Если Reddit API нестабилен → batch health check может заморозить 15+ аватаров за один run. Нет "circuit breaker" (если >N frozen за run → pause). | Массовая заморозка парализует клиента |
| G4 | Beat catch-up после deploy | HIGH | Celery Beat с persistent schedule file fires overdue tasks на рестарте. Деплой → beat restart → все overdue crontabs fire → duplicate EPG/pipeline runs. Dedup guard ЧАСТИЧНО решает (для EPG), но не для pipeline/scoring. | Дублирование AI calls, потенциальные race conditions |
| G5 | Нет executor timezone gate | MEDIUM | Email dispatch проверяет quiet hours по Israel time (23:00-07:00). Но executor может быть в NY → получает email в 2 AM NY если scheduled_at попал в Israel daytime. | Раздражение исполнителя, пропущенные задачи |
| G6 | CQS=lowest → budget=0 → NO notification | MEDIUM | Если CQS check ставит lowest → AttentionBudget даёт 0 слотов. Клиент/operator не получает уведомление. Аватар просто перестает генерировать. | "Silent death" — клиент думает система сломана |
| G7 | Demotion → нет alert | MEDIUM | Phase 2→1 demotion происходит тихо (activity_event пишется). Нет push notification оператору и нет notification клиенту. | 80% падение output без объяснения |
| G8 | Reconciliation window = 72h | LOW | Если executor постит через 4 дня (напр. weekend) — draft не будет reconciled автоматически. Останется "approved" навсегда. | Грязные данные (approved drafts that were actually posted) |
| G9 | Нет cross-avatar dedup | MEDIUM | Два аватара одного клиента могут получить слоты на один тред. Fitness gate не проверяет "другой аватар уже на этом треде". | Два комментария клиента в одном треде → заметно |
| G10 | Single Redis → single point of failure | HIGH | Redis = locks + rate limiter + heartbeat + task broker + SSE pubsub. Redis down = вся система стоит. | Полный outage |

### 3.2 Операционные разрывы

| # | Gap | Описание | Как чинить |
|---|-----|----------|-----------|
| O1 | 22/25 аватаров без executor_email | Email tasks не создаются для них | Настроить emails или включить автопостинг |
| O2 | 5 suspended аватаров в DB | Занимают место, показываются в UI (frozen) | Деактивировать (active=False) или удалить |
| O3 | POSTING_DISABLED=true | Автопостинг невозможен даже если proxy настроен | Бизнес-решение: включить когда прокси куплены |
| O4 | Нет proxy на аватарах | posting_safety gate 7 блокирует (proxy_url_encrypted empty) | Купить ProxyJet, настроить per-avatar |
| O5 | Brevo domain не верифицирован | Emails могут идти в спам | Верифицировать gorampit.com в Brevo |
| O6 | celerybeat-schedule file | Persistent на диске → catch-up проблема | Удалять при rebuild или использовать `--schedule=/dev/null` |

### 3.3 Бизнес-логические разрывы

| # | Gap | Вопрос | Требует решения от |
|---|-----|--------|-------------------|
| B1 | Autopilot = no human review | Кто несет ответственность за контент при autopilot? | Tzvi (contractual) |
| B2 | Phase demotion notification | Нужно ли уведомлять клиента о demotion? Или только оператора? | Max + Tzvi |
| B3 | Frozen avatar replacement | Если аватар заморожен, автоматически ли система переключает coverage на другого? | Architecture decision |
| B4 | Trial expiry grace period | Trial expired → pipeline skips client. Есть ли grace period? | Tzvi (pricing) |
| B5 | Max autopilot budget | Есть ли лимит сколько auto-approved drafts может создаться за день при autopilot? | Safety decision |
| B6 | Discovery → Strategy автоматизм | Сейчас strategy handoff ручной. Должен ли continuous discovery автоматически обновлять strategy? | Architecture decision |
| B7 | Multi-avatar collision | Два аватара одного клиента на одном треде — это баг или допустимо? | Business rule |

---

## Часть 4. Safety Gates — полная карта

### 4.1 Posting Safety (9 gates, sequential)

```
Gate 0: POSTING_DISABLED (env var) — immutable, cannot toggle from UI
Gate 1: auto_posting_enabled (DB setting) — toggleable from admin
Gate 2: avatar.posting_mode == "auto" — per-avatar config
Gate 3: avatar.is_frozen == False
Gate 4: avatar.health_status not in (shadowbanned, suspended)
Gate 5: avatar.warming_phase != 0 (Mentor excluded)
Gate 6: today_post_count < min(PHASE_LIMITS[phase], system_cap)
         Phase 1: 3 (CQS lowest: 1)
         Phase 2: 7
         Phase 3: 18
         System cap default: 8
Gate 7: avatar.proxy_url_encrypted is not empty
Gate 8: avatar.user_agent_string is not empty
Gate 9: same /24 subnet as last post (fail-open if malformed)
```

**Принцип:** Cheapest checks first. Fail-fast. Любой fail = пост отклонен с reason.

### 4.2 Content Safety (Phase Policy)

```
Phase 1:
  - ONLY hobby type comments
  - ONLY hobby subreddits
  - ZERO brand mentions (any mention → blocked)
  - Max 3 comments/day

Phase 2:
  - hobby + professional types
  - hobby + business subreddits
  - explicit_brand_link → blocked
  - explicit_brand_name → blocked
  - inferred_brand → requires_review
  - Max 7 comments/day

Phase 3:
  - All types, all subreddits
  - Brand links only in "engage" tagged threads
  - Ramp-up stages:
    - Early (<30 days in phase): max 1 brand comment total
    - Mid (30-60 days): brand ratio ≤ 10%
    - Complete (>60 days): brand ratio ≤ 30%
  - Max 18 comments/day
```

### 4.3 Fitness Gate (pre-generation)

```
Check 0: Subreddit ban (hard block, no fail-open)
Check 1: No risk profile → PASS (fail-open)
Check 2: min_karma rule from extracted rules
Check 3: min_account_age rule
Check 4: posting_frequency_limit
Check 5: extreme aggressiveness + karma < 50 → block
Check 6: dangerous hours + karma < 200 → block
```

**Kill switch:** `fitness_gate_enabled` (can be disabled from admin without deploy)

### 4.4 Kill Switches — Complete List

| Switch | Location | Default | What it stops |
|--------|----------|---------|---------------|
| `POSTING_DISABLED` | env var (.env) | true (prod) | ALL automated posting |
| `pipeline_enabled` | DB setting | true | ALL AI pipeline tasks (score, generate) |
| `generation_enabled` | DB setting | true | Comment generation only (scoring still runs) |
| `scrape_enabled` | DB setting | true | Subreddit scraping |
| `auto_posting_enabled` | DB setting | true | Automated posting (posting_safety gate 1) |
| `email_tasks_enabled` | DB setting | true | Email task creation + dispatch |
| `epg2_enabled` | DB setting | true | Portfolio Manager (false = legacy EPG) |
| `fitness_gate_enabled` | DB setting | true | Subreddit fitness pre-check |
| `cqs_check_tasks_enabled` | DB setting | true | CQS check task generation |
| `dry_run_enabled` | DB setting | false | When true, LLM renders prompt but doesn't call API |

---

## Часть 5. Failure Modes — что ломается и как

### 5.1 LLM Failure

| Scenario | System behavior | Recovery |
|----------|----------------|---------|
| Gemini Flash timeout | EPG slot → "skipped" (skip_reason). Afternoon run retries. | Automatic (dedup allows 1 retry) |
| Gemini Flash empty response | ~15% hobby generations fail. Slot skipped. | Automatic (afternoon retry) |
| Claude Sonnet timeout | Professional generation fails. Draft not created. | No retry (task-level). Next day regenerates. |
| Claude Sonnet 429 | Retry 3x with exponential backoff (60, 120, 240s) | Automatic |
| LiteLLM routing error | Task fails. Celery retry if bind=True. | Automatic (3 retries) |
| Monthly budget exceeded | `monthly_budget_usd` check (if implemented) | Manual: increase budget |

**⚠️ ВОПРОС:** Где проверяется `monthly_budget_usd`? Вижу setting в defaults, но не нашел enforcement в pipeline code. Возможно это только информационный setting без gate.

### 5.2 Reddit API Failure

| Scenario | System behavior | Recovery |
|----------|----------------|---------|
| PRAW timeout on scrape | Scrape task fails. Next tick retries (60s later). | Automatic |
| PRAW 429 (rate limit) | Rate limiter (30 RPM default) should prevent. If hit: queue_tick backs off. | Automatic |
| Profile not found (404) | Health check → SUSPENDED → freeze | Manual unfreeze needed |
| Intermittent 5xx | consecutive_check_failures increments. At 5 → UNKNOWN. At 5 + 48h → auto-freeze. | Auto (freeze) + Manual (unfreeze) |
| Reddit global outage | ALL health checks fail → ALL avatars accumulate failures → mass UNKNOWN → mass freeze at 48h | CATASTROPHIC. Need circuit breaker (Gap G3). |

### 5.3 Email Delivery Failure

| Scenario | System behavior | Recovery |
|----------|----------------|---------|
| Brevo API error | DeliveryAttempt.status=failed. Celery retry (3x, exponential). | Automatic |
| Invalid email | send_task_email returns (False, None). No retry (anti-spam blocks). | Manual: fix email |
| Email in spam | Not detectable. Executor doesn't see task. Task expires at 23:30. | Not automated. Need domain verification. |
| Max resends (3) | can_resend() returns False. Task stuck until deadline → expired. | Manual resend from admin (force=True) |

### 5.4 Cascading Failures

| Root cause | Cascade | Impact |
|-----------|---------|--------|
| Redis down | Locks fail → tasks proceed without dedup → duplicate posts. Beat can't persist schedule. Rate limiter offline → Reddit may rate-limit us. | TOTAL SYSTEM FAILURE |
| PostgreSQL down | All tasks fail on DB access. Celery workers crash-loop. | TOTAL SYSTEM FAILURE |
| Deploy during peak (08:00-08:30) | Containers restart → Beat catch-up → duplicate EPG builds + pipeline runs → extra LLM costs + potential duplicate drafts | Financial + quality (dedup guard partially protects EPG) |
| All avatars frozen | Client has zero activity. No notifications sent. | Silent client churn |

---

## Часть 6. Autonomous Agent Readiness Assessment

### 6.1 Что агент МОЖЕТ делать сейчас (без дополнительной инфраструктуры)

| Capability | Mechanism | Risk |
|-----------|-----------|------|
| Мониторить health (read-only) | SSH to server, read logs/redis/db | LOW |
| Диагностировать проблемы | Read activity_events, check avatar states | LOW |
| Предлагать исправления | Generate code changes, create PRs | LOW |
| Деплоить на staging | rsync + docker compose (staging) | LOW |
| Менять kill switches (staging) | DB update | LOW |
| Unfreeze аватары (staging) | DB update | LOW |

### 6.2 Что агент НЕ ДОЛЖЕН делать без human approval

| Action | Why | Approval from |
|--------|-----|---------------|
| Deploy to production | Live system with real client data | Max |
| Toggle kill switches (prod) | Affects all clients immediately | Max |
| Unfreeze avatar (prod) | May be legitimately frozen (real shadowban) | Max |
| Change phase manually (prod) | Business impact (output level) | Max + Tzvi |
| Enable autopilot for client | Removes human review gate | Tzvi |
| Change LLM model (prod) | Quality/cost tradeoff | Max |
| Modify prompts (prod) | Content quality affected | Max |
| Delete/deactivate avatars (prod) | Permanent business impact | Tzvi |
| Modify client config (prod) | Affects client's service delivery | Tzvi |

### 6.3 Предпосылки для автономного агента

Для перехода к автономному операционному агенту нужно:

1. **Alerting pipeline** — агент должен получать events (не polling). Сейчас: нет webhook/SSE endpoint для агента.
2. **Action audit trail** — каждое действие агента должно быть logged с reasoning. Сейчас: AuditLog есть, но нет agent_action_log.
3. **Sandbox/dry-run** — агент должен иметь возможность "попробовать" действие без выполнения. Сейчас: `dry_run_enabled` только для LLM calls.
4. **Escalation path** — если агент не уверен, он должен создать ticket/notification для человека. Сейчас: Notification model есть (для клиентов), но нет "ops notification" для Max/Tzvi.
5. **Rate limiting agent actions** — агент не должен иметь возможность сделать 50 изменений за минуту. Нужен budget per session.
6. **Rollback mechanism** — если действие агента ухудшает метрики, нужен автоматический rollback. Сейчас: нет.

---

## Часть 7. Риски — ранжированный список

### 7.1 Критические (могут остановить бизнес)

| # | Риск | Вероятность | Impact | Mitigation |
|---|------|-------------|--------|-----------|
| R1 | Redis SPOF → total outage | Low (DO infra reliable) | Critical | Planned: Managed Redis/Valkey. Not yet done. |
| R2 | Reddit массово банит аватары | Medium (policy change) | Critical | Avatar isolation (different IPs, different apps). BUT no proxy yet. |
| R3 | LLM provider outage (Anthropic/Google) | Low | High | LiteLLM fallback. But no tested failover path. |
| R4 | Deploy corruption (bad code → prod crash) | Medium | High | Docker image rebuild required. Rollback = redeploy previous commit. |
| R5 | Celery Beat desync → no tasks fire | Low | High | Heartbeat monitoring. But no auto-recovery. |

### 7.2 Высокие (снижают quality of service)

| # | Риск | Вероятность | Impact | Mitigation |
|---|------|-------------|--------|-----------|
| R6 | False demotion → 80% output drop | Low (min_sample=5) | High per client | Admin manual phase override. But no alert. |
| R7 | Mass freeze from API instability | Medium | High (all clients) | NONE. Need circuit breaker (Gap G3). |
| R8 | Auto-approve generates bad content | Low (PhasePolicy checks) | Medium-High | Brand regex check. But no semantic check. |
| R9 | Feedback loop drift | Unknown (not observable) | Medium | NONE. Need monitoring UI (Gap G2). |
| R10 | Email tasks never reach executor | Medium (spam filters) | Medium | Need Brevo domain verification (Gap O5). |

### 7.3 Средние (degraded experience)

| # | Риск | Вероятность | Impact | Mitigation |
|---|------|-------------|--------|-----------|
| R11 | Demotion without notification | Certain (no alert exists) | Medium per client | Gap G7 — need to build. |
| R12 | Cross-avatar collision on same thread | Medium (no dedup) | Low-Medium | Gap G9 — need cross-avatar check. |
| R13 | Stale strategy (>30 days) | Medium (weekly discovery exists) | Low | strategy_max_age_days setting exists but not enforced as gate. |
| R14 | EPG overkill on retry | Low (dedup guard exists) | Low | Fixed June 25. Max 2 attempts/day. |

---

## Часть 8. Вопросы для Max и Tzvi

### Для Max (технические):

1. **Beat catch-up:** используется ли `--skip-overdue` или celerybeat-schedule чистится при rebuild? Если нет — нужно добавить.
2. **monthly_budget_usd:** это enforcement или только информационный setting? Не нашел gate в pipeline code.
3. **Feedback loop drift:** нужен ли мониторинг для subreddit_priority_adjustments? Или trust-and-forget?
4. **Circuit breaker:** добавить лимит "если >5 аватаров frozen за один batch → pause и alert"?
5. **Redis failover:** план на managed Redis (DO $15/mo) или Valkey Serverless? Timeline?

### Для Tzvi (бизнес):

1. **Autopilot risk:** клиент с autopilot_enabled — кто видит контент до публикации? Executor? Или никто?
2. **Demotion communication:** как объяснять клиенту падение активности при demotion? Нужен шаблон email?
3. **Suspended аватары (5 шт.):** деактивировать? Или попытаться восстановить через appeal?
4. **Email timing:** исполнители в какой timezone? Нужен ли per-executor timezone setting?
5. **Trial grace:** trial expired → сразу отключаем pipeline? Или 3-day grace period?

---

## Часть 9. Моя рекомендация по приоритету фиксов

### Must-Have (до передачи автономии агенту):

1. **Circuit breaker на health check** — если >5 frozen за batch → stop + alert
2. **Demotion notification** — activity event + operator notification при phase down
3. **CQS=lowest notification** — alert при переходе в budget=0
4. **Beat catch-up fix** — добавить `celerybeat-schedule` cleanup в entrypoint.sh
5. **Feedback loop observability** — минимум: лог в admin activity feed с деталями adjustments

### Should-Have (улучшает операционную надежность):

6. **Autopilot content sampling** — раз в день отправлять оператору 3 случайных auto-approved draft для spot-check
7. **Cross-avatar dedup** — простая проверка: thread_id уже имеет approved/posted draft от другого аватара этого клиента
8. **Executor timezone setting** — email dispatch проверяет executor local time, не Israel time
9. **monthly_budget_usd enforcement** — реальный gate на LLM calls (если setting > 0)
10. **Redis health check** — celery task проверяет Redis и alert если недоступен

### Nice-to-Have (quality of life):

11. Reconciliation window 72h → 7d
12. Stale strategy gate (block generation if strategy_age > 30d)
13. Agent action log model (для будущего autonomous agent)
14. Per-client daily digest email (what happened today)

---

*Документ создан на основе reverse-engineering исходного кода (app/services/*.py, app/tasks/*.py), RAMP_SYSTEM_DIAGNOSTIC.json, и операционных логов June 24-27, 2026.*

---

## ADDENDUM (Post-Review) — Ответы на верификационные вопросы

*Добавлено после review от Max. Маркировка уровня достоверности: VERIFIED (код), OBSERVED (логи), INFERRED (вывод).*

---

### A. Маркировка фактов vs интерпретаций — исправления

#### "Redis down → tasks proceed without dedup → duplicate posts"

**Реальное поведение (VERIFIED from distributed_lock.py):**

```
DistributedLock.acquire() → redis.set(key, value, nx=True, ex=ttl)
```

- **НЕТ try/except** в acquire(). Если Redis unreachable → `redis.ConnectionError` → exception propagates up.
- В EPG task: `lock.acquire()` вызывается ВНУТРИ `try/except Exception` (строка 103 epg.py). При Redis down → exception → avatar skipped → `results["errors"] += 1`. Следующий avatar пробует снова.
- **ВЫВОД: Redis down = НЕ fail-open, а FAIL-CLOSED (задача падает с ошибкой)**. НЕ "proceed without dedup".

**Исправленная маркировка:**
- Redis down → lock.acquire() throws ConnectionError → FAIL-CLOSED [VERIFIED]
- Redis down → Celery broker unreachable → NO TASKS FIRE AT ALL [INFERRED — Celery uses Redis as broker]
- Redis down → rate limiter offline → scraping may exceed Reddit API limits [INFERRED]

#### "Массовая заморозка"

- health_check_batch НЕ имеет circuit breaker [VERIFIED — код просто итерирует avatars]
- Каждый health check вызывает Reddit API (PRAW) [VERIFIED]
- Reddit API timeout → HealthCheckError → consecutive_failures++ [VERIFIED]
- consecutive_failures >= 5 → UNKNOWN [VERIFIED]
- UNKNOWN > 48h → auto-freeze [VERIFIED]
- **Сценарий:** Reddit API down 48+ часов → ВСЕ аватары → UNKNOWN → auto-freeze [INFERRED]
- **Вероятность:** LOW (Reddit API rarely down >48h), но impact = CRITICAL

#### "Feedback drift"

- feedback_loop.py вызывает _store_epg_adjustments() [VERIFIED]
- Adjustments записываются как ActivityEvent [VERIFIED — `_log_feedback_event`]
- НО: adjustments хранятся только как JSONB в activity_event.metadata [VERIFIED]
- НЕТ UI для визуализации drift over time [VERIFIED — нет route/template]
- **Drift реален, но медленный** — loop runs daily, adjustments incremental [INFERRED]

---

### B. Decision Ownership Map

| Решение | Кто принимает | Кто может отменить | SLA отмены | Provenance |
|---------|--------------|-------------------|-----------|-----------|
| Freeze avatar (health) | System (health_checker.py) | Operator (admin UI) | До следующего pipeline run (~hours) | AuditLog + health_check_details JSONB |
| Freeze avatar (CQS) | System (cqs_checker.py) | Operator (admin UI) | Same | AuditLog + activity_event |
| Freeze avatar (posting fail) | System (posting.py) | Operator (admin UI) | Same | PostingEvent |
| Phase demotion | System (PhaseEvaluator) | Max (admin phase override) | 24h (next eval at 06:00) | AuditLog "phase_evaluation_completed" |
| Phase promotion | System (PhaseEvaluator) | Max (admin phase override) | N/A (beneficial) | AuditLog |
| Auto-approve draft | Client config (autopilot_enabled) | Tzvi (disable autopilot) | Immediate (next draft) | No provenance (no log of WHY approved) |
| Thread selection (EPG) | System (portfolio_manager) | Nobody (irreversible) | N/A | DecisionRecord model (full snapshot) |
| Feedback weight adjust | System (feedback_loop) | Nobody (no rollback UI) | N/A | ActivityEvent (metadata JSONB) |
| Email task cancel | System (liveness check) | Nobody (correct behavior) | N/A | ExecutionTask.status_history |
| Subreddit risk score | System (risk_scorer) | Nobody (weekly overwrite) | 7 days (next batch) | SubredditRiskProfile.score_history |
| Trial expired | System (trial_guard) | Nobody (date-based) | N/A | Client.created_at + 14 days |

**⚠️ КРИТИЧЕСКИЙ ВЫВОД:**
- `Thread selection` и `Feedback adjustments` — **НЕОБРАТИМЫ и НЕ имеют владельца отмены**.
- `Auto-approve` — НЕТ провенанса (не логируется WHY approved, только ЧТО approved).

---

### C. Decision Graph (Causal Chain)

```
[Scraping] ─scraped_at────→ [Smart Scoring]
                                │
                         score=engage ──→ [EPG Build (Portfolio Manager)]
                                              │
                                    ┌─────────┼─────────┐
                                    │         │         │
                              [Budget]  [Opportunities] [Risk Filter]
                                    │         │         │
                                    └─────────┼─────────┘
                                              │
                                        [Allocation]
                                              │
                                     EPG Slots (planned)
                                              │
                                   [Generation (LLM)]
                                              │
                                     EPG Slots (generated)
                                              │
                              ┌────────────────┼────────────────┐
                              │                                 │
                    [Auto-approve?]                    [Human Review Queue]
                              │                                 │
                     Slot = approved                    approve/reject/edit
                              │                                 │
                              └────────────────┬────────────────┘
                                               │
                                   [Dispatch Email Task]
                                               │
                                    ┌──────────┼──────────┐
                                    │          │          │
                            [Quiet hours?] [Health OK?] [Thread live?]
                                    │          │          │
                                    └──────────┼──────────┘
                                               │
                                        [Send Email]
                                               │
                                    [Executor Posts Manually]
                                               │
                                    [Draft Reconciliation (4h)]
                                               │
                                   ┌───────────┼───────────┐
                                   │           │           │
                           [Karma Snapshot] [Deletion?] [Reply count]
                                   │           │           │
                                   └───────────┼───────────┘
                                               │
                                   [Outcome Analysis (02:00)]
                                               │
                                    [Feedback Packet]
                                               │
                              ┌────────────────┼────────────────┐
                              │                │                │
                  [Hypothesis updates]  [Subreddit adj.]  [Performance ctx]
                              │                │                │
                              └────────────────┼────────────────┘
                                               │
                                    [Next day EPG allocation]
                                               │
                                        ↺ LOOP
```

**Замкнутый цикл (closed loop):** Outcome → Feedback → EPG weights → Thread selection → Generation → Posting → Outcome

**Точки разрыва цикла (circuit breakers):**
1. Kill switch `pipeline_enabled=false` → разрывает на Score
2. Kill switch `generation_enabled=false` → разрывает на Generation
3. `POSTING_DISABLED=true` → разрывает на Posting
4. Human review (при autopilot=false) → разрывает на Approve
5. Avatar freeze → разрывает на EPG Build (excluded)

---

### D. Ответы на 5 вопросов

#### 1. Где хранится decision provenance?

| Решение | Где хранится | Полнота |
|---------|-------------|---------|
| Phase eval | AuditLog (action="phase_evaluation_completed", details={evaluated, promoted, demoted}) | Агрегат. Нет per-avatar reasoning. |
| Health freeze | AuditLog (action="health_status_changed") + avatar.health_check_details JSONB | ХОРОШО — visibility_ratio, method, sampled, visible |
| EPG allocation | DecisionRecord model (avatar_state, community_states, portfolio_allocation, budget) | ХОРОШО — full snapshot |
| Feedback adjust | ActivityEvent (type="feedback_loop_run", metadata=adjustments dict) | ЧАСТИЧНО — есть что изменено, нет WHY |
| Auto-approve | CommentDraft.status="approved" + EPGSlot.status="approved" | ПЛОХО — нет поля "approved_by=system" vs "approved_by=human" |
| Smart scoring | ThreadScore (score, tag, reasoning) | ХОРОШО — LLM reasoning stored |
| Fitness gate | ActivityEvent (type="fitness_gate_blocked") | Только blocked. Passes не логируются. |

**ВЫВОД:** Провенанс неполный. Главные дыры:
- Auto-approve не различает system vs human в draft record
- Phase demotion не хранит per-avatar trigger (только aggregate count)
- Fitness gate passes (allowed) не логируются

#### 2. Можно ли воспроизвести решение за прошлую дату?

- **EPG allocation:** ДА — DecisionRecord содержит полный snapshot (budget, opportunities, allocation). Можно replay.
- **Phase evaluation:** ЧАСТИЧНО — AuditLog хранит "promoted: 2, demoted: 1", но НЕ хранит какой avatar и почему.
- **Health check:** ДА — avatar.health_check_details = полный snapshot последней проверки.
- **Feedback loop:** НЕТ — ActivityEvent содержит ТЕКУЩИЕ adjustments, но не предыдущее состояние (нет diff).
- **Smart scoring:** ДА — ThreadScore хранит reasoning + score + tag.

**ВЫВОД:** Replay возможен для EPG и scoring. НЕ возможен для feedback loop и phase demotion per-avatar.

#### 3. Source of truth — DB, Redis, ActivityLog или Celery?

| Данные | Source of Truth | Вторичные копии |
|--------|-----------------|-----------------|
| Avatar state (phase, frozen, health) | **PostgreSQL** (avatars table) | Нет кеша |
| Lock state | **Redis** (SETNX keys, TTL) | Нет persistence |
| Task schedule | **Celery Beat** (in-memory + celerybeat-schedule file) | Нет DB backup |
| Pipeline decisions | **PostgreSQL** (DecisionRecord, ThreadScore, ActivityEvent) | Нет |
| System settings | **PostgreSQL** (system_settings table) | In-memory cache (settings.py) |
| Heartbeat | **Redis** (ramp:heartbeat:last_at, TTL 300s) | Нет |
| Email delivery | **PostgreSQL** (ExecutionTask, DeliveryAttempt) | Нет |

**⚠️ ПРОБЛЕМА:** Celery Beat schedule живет в файле на диске (`celerybeat-schedule`). При container restart — catch-up fires overdue. Нет DB-backed schedule.

#### 4. Есть ли kill switch, который за 30 секунд останавливает ВСЁ?

**НЕТ ЕДИНОГО.**

Ближайший вариант — нужно 3 действия:
1. `pipeline_enabled=false` (DB) → stops scoring + generation + EPG build
2. `POSTING_DISABLED=true` (env var) → stops posting (already true on prod)
3. `email_tasks_enabled=false` (DB) → stops email dispatch

**Почему не работает как "один kill switch":**
- `pipeline_enabled` НЕ останавливает: scraping, health checks, karma tracking, feedback loop
- `POSTING_DISABLED` — env var, требует redeploy для изменения
- Redis key `ramp:kill:posting_disabled` — проверяется ТОЛЬКО в posting.py (не в pipeline)

**Для emergency stop (30 sec) сейчас нужно:**
```bash
ssh ramp "docker compose stop celery celery-beat celery-fast"
```
Это останавливает ВСЕ workers. Но также останавливает health мониторинг.

**РЕКОМЕНДАЦИЯ:** Добавить `ramp:kill:all` Redis key, проверяемый в начале КАЖДОГО Celery task (single decorator/mixin). One Redis SET → everything stops.

#### 5. Есть ли инвариант: одна сущность → один агент → одно действие → один outcome?

**НЕТ.** Конкретные нарушения:

| Нарушение | Где |
|-----------|-----|
| Один avatar → несколько EPG slots per day | By design (budget = 3-12 slots) |
| Один thread → несколько avatars (разных клиентов) | By design (multi-tenant) |
| Один thread → несколько avatars **одного клиента** | BUG (Gap G9 — no cross-avatar dedup) |
| Один feedback loop run → множественные hypothesis updates | By design |
| Один health_check_batch → множественные freeze actions | By design (no circuit breaker) |

**Closest invariant that DOES hold:**
- ONE EPGSlot → ONE CommentDraft → ONE ExecutionTask → ONE Reddit Comment [VERIFIED — UNIQUE constraints]
- ONE avatar → ONE phase at a time [VERIFIED — single field]
- ONE thread → ONE score per client [VERIFIED — UNIQUE on thread_id + client_id]

---

### E. Revised Priority (после review)

**P0 (блокеры автономности):**
1. `ramp:kill:all` — единый emergency stop через Redis (проверка в каждом task)
2. Freeze circuit breaker — max 3 freeze per batch, then pause + alert
3. Auto-approve provenance — добавить `approved_by` field (system/human/autopilot)
4. Agent audit log model — каждое действие агента с reasoning
5. Beat catch-up fix — удалять celerybeat-schedule в entrypoint.sh

**P1 (observability для передачи):**
6. Feedback loop observability — trend visualization (subreddit weights over time)
7. Phase demotion per-avatar logging — WHY this avatar, WHAT triggered
8. Cross-avatar dedup
9. Demotion + freeze alerts (push notification to Max)

**P2 (операционное качество):**
10. Executor timezone setting
11. monthly_budget_usd enforcement
12. Strategy freshness gate
13. Sampling auto-approved content (daily spot-check)
14. Fitness gate pass logging (not just blocks)

---

### F. Скрытая автономия — формализация

Ты правильно заметил: система УЖЕ автономна. Вот формализация:

**Closed loops (работают без человека):**

| Loop | Cycle time | Human touchpoint | Can drift? |
|------|-----------|-----------------|-----------|
| Scrape → Score → Generate → [Approve] → Dispatch → Post → Outcome → Feedback → Score | 24h | Review queue (если autopilot=OFF) | YES (feedback changes weights) |
| Health check → Freeze → Exclude from pipeline | 12h | Unfreeze (manual) | NO (binary: frozen/not) |
| Phase eval → Demotion → Reduced budget → Less output | 24h | Phase override (manual) | NO (rule-based, deterministic) |
| Subreddit risk → Fitness gate → Thread blocked | 7 days | None | LOW (weekly refresh, rules from sidebar) |

**Loops WITHOUT human interface for course correction:**
- Feedback loop → EPG allocation (no UI to see/override weights)
- Continuous discovery → Hypothesis confidence (admin can see, but no "reject hypothesis" action)

**Ключевое:** проблема не "агент станет автономным". Проблема: **feedback loop уже автономен, но без наблюдаемости и без rollback**.

---

*Обновлено June 27, 2026 после verification review.*
