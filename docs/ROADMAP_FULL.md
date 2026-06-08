# RAMP — Full Product Roadmap & Status

**Version:** 0.2.0 | **Date:** June 6, 2026 | **Author:** Max

---

## Текущая позиция

```
┌─────────────────────────────────────────────────────────┐
│                    ГДЕ МЫ СЕЙЧАС                         │
├─────────────────────────────────────────────────────────┤
│  Intelligence Platform (scrape→score→generate→EPG)  98% │
│  Automated Posting (core + safety + timing)          75% │
│  Client Portal (basic)                               85% │
│  Admin Panel (ops)                                   95% │
│  Production (DigitalOcean, SSL, Docker)             100% │
│  Revenue                                              0% │
│  Paying Clients                                       0  │
│  First Invoice Target                        July 1 2026 │
└─────────────────────────────────────────────────────────┘
```

**Стратегическая формула (из встречи June 5):**
> Мы продаём intelligence, не posting. Posting — лишь один из способов действия.

---

## Общая карта фаз

| Phase | Название | Сроки | Exit Criteria |
|-------|----------|-------|---------------|
| **0** | Launch Ready | Май — Июнь 2026 | 3 платящих клиента, posting stable, client dashboard live |
| **1** | Product-Market Fit | Июль — Авг 2026 | 10 активных клиентов, self-serve, churn <15% |
| **2** | Scale Engine | Сен — Ноя 2026 | 25+ клиентов, cross-avatar coordination, AEO/GEO |
| **3** | Platform Expansion | Дек 2026 — Q2 2027 | Agency/white-label, 60+ клиентов |

---

## PHASE 0 — LAUNCH READY (текущая)

### ✅ Сделано

| Компонент | Статус | Дата |
|-----------|--------|------|
| Full AI pipeline (scrape → score → generate → review) | ✅ | May 3 |
| Admin panel (dark theme, full CRUD, dashboard) | ✅ | May 3 |
| 7-step onboarding wizard | ✅ | May 3 |
| JWT auth + 6-role RBAC + client isolation | ✅ | May 13 |
| Self-learning loop (edit capture → patterns → few-shot) | ✅ | May 11 |
| Avatar Intelligence (confidence, removal rate, patterns) | ✅ | May 12 |
| Shadowban detection (5-state, auto-freeze) | ✅ | May 10 |
| CQS automated monitoring (daily batch) | ✅ | May 12 |
| System Topology dashboard | ✅ | May 7 |
| Thread liveness protection (locked/removed/archived) | ✅ | May 8 |
| Emergency controls (freeze, kill switches) | ✅ | May 11 |
| LLM output validation (Pydantic schemas) | ✅ | May 11 |
| Context isolation assertions | ✅ | May 11 |
| Avatar behavioral analysis (LLM profiling) | ✅ | May 10 |
| Avatar subreddit presence map | ✅ | May 10 |
| Comment approach diversity (karma-gated) | ✅ | May 14 |
| Repurpose scraping (evergreen top/year) | ✅ | May 14 |
| Marketing site + roadmap page (gorampit.com) | ✅ | May 15 |
| Production deployment (DO, SSL, Docker) | ✅ | May 21 |
| Automated posting core (PRAW, safety gates, timing) | ✅ | Jun 1 |
| First verified post (r/test, u/Hot-Thought2408) | ✅ | Jun 1 |
| Client Portal (home, review, insights, strategy, EPG) | ✅ | May 24 |
| Versioning + POSTING_DISABLED env kill switch | ✅ | Jun 1 |
| EPG service (daily program, phase-aware, dedup) | ✅ | May 20 |
| Strategy engine + injection into generation | ✅ | May 11 |
| Mentor phase (phase 0 exclusion from all pipelines) | ✅ | May 12 |
| Docker workflow (Makefile, db-sync, entrypoint) | ✅ | May 9 |
| Demo data (XM Cyber avatars with real karma) | ✅ | May 24 |

### 🔲 Осталось в Phase 0

| # | Задача | Effort | Блокирует | Status |
|---|--------|--------|-----------|--------|
| 1 | **Auto-posting E2E: 5 avatars × 3 days stable** | 3 дня тестов | Demos | 🟡 In progress |
| 2 | **Proxy purchase + integration (ProxyJet)** | 1-2 дня + $12.50/мо | Real posting | 🔴 Blocked (budget) |
| 3 | **Posting Admin UI** (logs, proxy config, dashboard) | 3-4 дня | Ops visibility | 🔲 Not started |
| 4 | **Customer demos** (desktop, live data) | 1-2 дня prep | First sale | 🟡 Ready (Jun 10-12) |
| 5 | **XM Cyber validation** (data test with Tzvi) | 0.5 дня | Pilot proof | 🔲 Waiting on Tzvi |
| 6 | **Comment performance tracking** (karma 4h/24h/48h) | 5 дней | ROI proof | 🔲 Not started |
| 7 | **Mobile REST API** (7 endpoints) | 3-5 дней | Mobile app | 🔲 Not started |
| 8 | **Flutter MVP** (login, EPG, copy, track) | 5-7 дней | Avatar owners | 🔲 Not started |

### Phase 0 Timeline

```
Jun 6-9     Auto-posting stable (5 avatars, zero-intervention)
Jun 10-12   Customer demos (desktop)
Jun 13-15   Mobile REST API
Jun 16-20   Comment performance tracking
Jun 22-28   Flutter MVP (login + EPG + copy)
Jun 30      Mobile testable on real phone
Jul 1       First invoice target
```

---

## PHASE 1 — PRODUCT-MARKET FIT (Июль — Авг 2026)

**Goal:** 10 active clients, retention, depth.

| # | Feature | Spec | Effort | Revenue Impact |
|---|---------|------|--------|----------------|
| 0 | **Discovery Engine** (Visibility Report) | `.kiro/specs/discovery-engine/` | 2-3 недели | $4K setup fee justification, sales closer |
| 1 | **Activity Pacing** (стратегическое молчание) | ❌ New | 2 дня | Avatar survival ↑ |
| 2 | **Quality Sentinel** (auto-flag bad comments) | `.kiro/specs/quality-sentinel/` | 4 дня | Client trust |
| 3 | **Subreddit Intelligence** (rule parsing) | Part of `platform-readiness` | 3-4 дня | -30% removals |
| 4 | **Budget Engine** (daily limits per plan) | ❌ New | 2 дня | Plan enforcement |
| 5 | **Cross-Avatar Deduplication** | ❌ New | 1 день | Safety |
| 6 | **Nested Comment Replies** | ❌ New | 3-4 дня | Engagement depth |
| 7 | **Competitor Intelligence** | ❌ New | 4-5 дней | Upsell feature |
| 8 | **Client Report (weekly PDF/HTML)** | ❌ New | 3 дня | Client retention |
| 9 | **Self-Serve Onboarding** (AI wizard) | Part of roadmap | 5-7 дней | Scale past Tzvi |
| 10 | **Stripe Billing** | ❌ New | 3-4 дня | Revenue automation |
| 11 | **Pagination** (all list endpoints) | — | 2 дня | Scaling |
| 12 | **Idempotency Keys** | — | 1 день | Reliability |
| 13 | **Context Assembler** (unified LLM context) | `.kiro/specs/context-assembler/` | 3 дня | Quality ↑ |
| 14 | **Conversation Memory** (avatar remembers) | Part of `platform-readiness` | 2 дня | Depth |

**Phase 1 Exit:** 10 paying clients, self-serve works, churn <15%.

---

## PHASE 2 — SCALE ENGINE (Сен — Ноя 2026)

**Goal:** 25+ clients, moat deepening, automation.

| # | Feature | Spec | Effort | Strategic Value |
|---|---------|------|--------|-----------------|
| 1 | **AI-Native Expert Warming** | `.kiro/specs/ai-native-expert-warming/` | 3-4 недели | Core moat |
| 2 | **Discovery Engine** | `.kiro/specs/discovery-engine/` | 2-3 недели | Sales artifact ($4K setup) |
| 3 | **Cross-Avatar Coordination** (upvote, reply) | ❌ New | 2 недели | Karma compounding |
| 4 | **AEO/GEO Integration** (Spotlight API) | External | 1 неделя | Upsell |
| 5 | **Emotional Resonance Engine** | `.kiro/specs/emotional-resonance-engine/` | 2 недели | Comment quality |
| 6 | **Prompt Versioning + A/B** | ❌ New | 3-4 дня | Optimization |
| 7 | **Pipeline Resilience** | `.kiro/specs/pipeline-resilience-hardening/` | 1 неделя | Reliability |
| 8 | **Strategy Questions Feedback** | ❌ New | 2 дня | Strategy quality |
| 9 | **Expanded Client Dashboard** (SoV, momentum) | Part of `client-portal-redesign` | 1 неделя | Enterprise sell |
| 10 | **OAuth Mode** (Reddit approval dependent) | `.kiro/specs/oauth-avatar-auth/` | 3-4 дня | Future-proofing |
| 11 | **Author Intelligence** | `.kiro/specs/author-intelligence/` | 1 неделя | Targeting quality |
| 12 | **Queue Observability** (DLQ + metrics) | — | 2 дня | Ops maturity |
| 13 | **Trust Engine** (per-avatar decay scores) | ❌ New | 1 неделя | Avatar longevity |
| 14 | **Vector Memory** (pgvector, long-term) | — | 1 неделя | Learning depth |

**Phase 2 Exit:** 25+ clients, AI-Native Expert working, cross-avatar coordination live.

---

## PHASE 3 — PLATFORM EXPANSION (Дек 2026+)

**Goal:** 60+ clients, new revenue streams.

| # | Feature | Trigger |
|---|---------|---------|
| 1 | **Agency & White-Label** | 3+ agency clients in pipeline |
| 2 | **SQS + Valkey Migration** | 100+ avatars OR enterprise requirement |
| 3 | **LinkedIn Avatar Expansion** | Reddit stable at 25+ clients |
| 4 | **Client Self-Service Portal** | 5+ self-service clients |
| 5 | **AWS Migration** (ECS, RDS, ALB) | Enterprise/compliance requirement |
| 6 | **Personal Brand Module** | 3+ client requests |
| 7 | **Twitter/X Expansion** | LinkedIn stable + demand confirmed |
| 8 | **White-Label Client Websites** | Agency specifically requests |
| 9 | **Multi-Platform Intelligence** | Reddit + LinkedIn both stable |

---

## Product Flow Debt (разрывы в цепочке клиента)

Путь клиента от контакта до ROI — каждый разрыв = потерянная продажа или churn.

```
Discovery → Onboarding → Strategy → EPG → Generation → Review → Posting → Outcome → Report
   ❌           ✅          🟡        ✅       ✅          ✅       🟡         ❌        ❌
```

| # | Разрыв | Что сломано | Impact | Effort | Phase |
|---|--------|-------------|--------|--------|-------|
| 1 | **Discovery** | Нет исследования Reddit-fit для клиента. Tzvi продаёт на словах. Setup fee $4K без deliverable. | Blocks sales close | 2-3 нед | 0-1 |
| 2 | **Strategy ← Discovery handoff** | Strategy генерится без validated data из Discovery. Гадаем вместо того чтобы знать. | Weak strategy quality | 2-3 дня (after Discovery) | 1 |
| 3 | **Posting last mile** | Нет proxy (один IP), нет mobile app (2-5 min/comment), нет Admin UI для ops | Blocks scaling past 5 avatars | 2 нед total | 0 |
| 4 | **Outcome tracking** | Не отслеживаем karma/removals/engagement после публикации. Система слепая. | Can't prove ROI, no learning signal | 5 дней | 0 |
| 5 | **Client Report** | Нечего показать клиенту. "Мы работаем" без цифр. | Churn risk, weak retention | 3 дня | 0-1 |

**Суть:** Середина pipe (шаги 2-6) отполирована. Начало (Discovery) и конец (Outcome → Report) — пусты. Клиент не понимает зачем пришёл и не видит что получил.

---

## Технический долг (Tech Debt)

### 🔴 Критический (блокирует масштабирование)

| Debt | Impact | Effort | When |
|------|--------|--------|------|
| **No comment outcome tracking** | Не можем доказать ROI | 5 дней | Phase 0 (NOW) |
| **No proxy integration** | Все аватары = один IP | 1-2 дня + бюджет | Phase 0 (NOW) |
| **No mobile API** | Manual copy-paste = 2-5 min/comment | 3-5 дней | Phase 0 |
| **Posting Admin UI missing** | Ops слепые к posting status | 3-4 дня | Phase 0 |
| **No Discovery Engine** | Tzvi продаёт на словах, не на данных. $4K setup fee без deliverable. Онбординг = ручной, не масштабируется | 2-3 недели | Phase 0-1 (revenue enabler) |

### 🟡 Важный (замедляет рост)

| Debt | Impact | Effort | When |
|------|--------|--------|------|
| **No idempotency keys** | Duplicate task execution | 1 день | Phase 1 |
| **No pagination** | UI breaks at 100+ items | 2 дня | Phase 1 |
| **Prompts hardcoded** | No versioning, no A/B | 3-4 дня | Phase 1-2 |
| **No activity pacing** (natural cadence) | Avatars post like bots | 2 дня | Phase 1 |
| **Fixed timing in Celery Beat** | Predictable schedule = detectable | 1 день | Phase 1 |
| **No subreddit rule parsing** | Comments removed by mods | 3-4 дня | Phase 1 |
| **No budget caps per client** | Over-posting possible | 2 дня | Phase 1 |
| **No nested replies** | Top-level only = bot pattern | 3-4 дня | Phase 1 |
| **No conversation memory** | Avatar forgets previous interactions | 2 дня | Phase 1 |

### 🟢 Отложенный (не блокирует до 50+ clients)

| Debt | Impact | Effort | When |
|------|--------|--------|------|
| No DLQ (Celery limitation) | Failed tasks lost silently | Part of SQS migration | Phase 3 |
| Celery introspection limited | Hard to debug stuck tasks | Part of SQS migration | Phase 3 |
| Single DB (Docker PG) | No HA, no auto-backup | Migrate to RDS ($24/mo) | 5+ paying |
| No horizontal scaling | Workers compete for CPU | Separate pools | CPU >80% |
| No data retention cleanup | DB grows unbounded | TTL + archival | Phase 2 |
| Monolithic worker | All tasks share one pool | Task routing | Phase 2 |
| Tests coverage gaps | 50+ tests but no integration suite | CI/CD pipeline | Phase 1 |

---

## Spec Inventory — Status Map

### ✅ Built & Deployed (16 specs)

| Spec | Completed |
|------|-----------|
| rbac-client-isolation | May 13 |
| self-learning-loop | May 11 |
| avatar-analysis | May 10 |
| avatar-reddit-status | May 10 |
| shadowban-detection | May 10 |
| mvp-hardening-sprint1 | May 11 |
| system-topology-timeline | May 7 |
| avatar-warming-phases | May 12 |
| avatar-intelligence-learning | May 12 |
| shared-subreddit-registry | May 11 |
| scheduled-scraping | May 11 |
| automated-proxy-posting (core) | Jun 1 |
| client-portal-redesign (P0) | May 24 |
| admin-panel-client-onboarding | May 5 |
| activity-feed-transparency | May 8 |
| settings-consolidation | May 9 |

### 🟡 Spec Exists, Not Built Yet (15 specs)

| Spec | Phase | Priority |
|------|-------|----------|
| discovery-engine | 0-1 | P0 (revenue enabler) |
| ai-native-expert-warming | 2 | P0 (moat) |
| mobile-posting-app | 0 | P0 |
| quality-sentinel | 1 | P1 |
| emotional-resonance-engine | 2 | P2 |
| pipeline-resilience-hardening | 2 | P1 |
| context-assembler | 1 | P2 |
| author-intelligence | 2 | P2 |
| oauth-avatar-auth | 2 | P1 |
| unified-posting-dashboard | 0 | P1 |
| telegram-posting-bot | Cancelled | — |
| sqs-valkey-migration | 3 | P2 |
| platform-readiness (partial) | 1 | P1 |
| client-manager-workflow-ux | 1 | P2 |
| landing-pages-ab-testing | 2 | P3 |

### ⚪ Ops/Bug Fix Specs (done or irrelevant)

| Spec | Status |
|------|--------|
| admin-ui-qa-fixes | Done |
| comment-rendering-bug/fix | Done |
| cascade-delete | Done |
| db-audit-optimization | Done |
| disk-cleanup-automation | Done |
| ui-info-tooltips | Done |
| admin-navigation-consolidation | Done |
| various others | Done/Superseded |

---

## Cost Model (текущее + projected)

### Сейчас ($0 revenue)

| Item | Monthly |
|------|---------|
| DigitalOcean | $23 |
| LLM APIs (test load) | ~$50 |
| Dev tools | ~$50 |
| **Total** | **~$123/mo** |

### At 3 Clients ($1,500 revenue)

| Item | Monthly |
|------|---------|
| DigitalOcean | $23 |
| LLM APIs | $105 |
| Proxies (15 avatars) | $37.50 |
| **Total** | **~$166/mo** |
| **Margin** | **89%** |

### At 10 Clients ($5,000 revenue)

| Item | Monthly |
|------|---------|
| DigitalOcean | $23 |
| LLM APIs | $351 |
| Proxies (50 avatars) | $125 |
| **Total** | **~$499/mo** |
| **Margin** | **90%** |

### At 50 Clients ($25,000 revenue)

| Item | Monthly |
|------|---------|
| AWS Infrastructure | $130 |
| LLM APIs | $1,755 |
| Proxies (250 avatars) | $625 |
| **Total** | **~$2,510/mo** |
| **Margin** | **90%** |

---

## Стратегические решения (зафиксированы)

| Решение | Дата | Обоснование |
|---------|------|-------------|
| DigitalOcean, не AWS | May 2026 | Проще, дешевле для MVP. Миграция при enterprise |
| Celery + Redis, не SQS | May 2026 | Работает до 100 аватаров |
| Password auth, не OAuth | Jun 2026 | Reddit не одобряет новые apps. Работает сейчас |
| Per-avatar credentials | Jun 2026 | White-label = каждый аватар = свой аккаунт |
| Intelligence > Posting | Jun 5 | Core value = мониторинг + scoring + рекомендации |
| Mobile app > Telegram bot | Jun 5 | Tzvi хочет нативное приложение |
| GEO/AIO: buy, not build | Jun 5 | Spotlight API ($200/mo) vs. месяцы разработки |
| No multi-platform until 25+ clients | Jun 2026 | Расфокус убивает стартапы |

---

## Риски (Top 10)

| # | Риск | Severity | Mitigation | Status |
|---|------|----------|------------|--------|
| 1 | Reddit отзывает API ключ | HIGH | Per-avatar auth для posting (done), scraping = публичные данные | ✅ Mitigated |
| 2 | Аватары банят пачкой (IP-линковка) | HIGH | Residential proxies per avatar | 🔴 Proxy not purchased |
| 3 | Нет revenue к July 1 | HIGH | Demos Jun 10-12, aggressive timeline | 🟡 In progress |
| 4 | Tzvi не закрывает сделки | MED | Demo materials ready, value proof needed | 🟡 Pending |
| 5 | Comment removals (subreddit rules) | MED | Subreddit intelligence (Phase 1) | 🔲 Not started |
| 6 | Reddit blocks password auth | MED | OAuth adapter ready, waiting for approval | 🟡 Waiting |
| 7 | Mobile app delays | MED | Desktop copy-paste as interim | ✅ Interim works |
| 8 | LLM costs spike (Claude price change) | LOW | Haiku fallback, model switching via LiteLLM | ✅ Mitigated |
| 9 | Single server failure | LOW | DO backups weekly, Docker volumes | ✅ Acceptable |
| 10 | Competition (ReddGrow etc) | LOW | Different positioning ($2K+ managed vs $59 self-serve) | ✅ Strategic |

---

## RAMP 2.0 Vision (из презентации Navigational Intelligence)

Долгосрочный vision: RAMP = навигационная система для управления цифровыми сигналами.

| Layer | Текущий статус | Target |
|-------|---------------|--------|
| **Discovery** (наблюдение за средой) | 70% — scraping + scoring | Full ecosystem mapping, sentiment, trends |
| **Strategy** (курс) | 50% — strategy engine + documents | Feedback loop, question mechanism, adaptation |
| **EPG** (ежедневные действия) | 80% — service + timing + dedup | + Activity pacing, silence gates, full automation |
| **Signal Intelligence** | 30% — approach diversity only | Cadence + Silence + Depth metrics |
| **Avatar as Digital Entity** | 75% — phases, presence, karma, health | + Trust score, authority score, citability |

### Что из Vision реально строить и когда:

| Концепция из RAMP 2.0 | Фаза | Что это в коде |
|------------------------|------|----------------|
| Discovery Layer | Phase 0-1 | `discovery-engine` spec (15 requirements ready) — revenue enabler |
| Strategy Layer feedback | Phase 1-2 | Strategy Questions + client preferences |
| Activity Pacing (молчание) | Phase 1 | `silence_gates.py` service (~100 строк) |
| Signal Management | Phase 2 | Outcome tracking + cadence metrics |
| AI-Native Expert | Phase 2 | `ai-native-expert-warming` spec (full) |
| Avatar Anatomy (trust, authority) | Phase 2-3 | Trust engine + authority score |
| Ecosystem Mapping | Phase 2 | Discovery + competitor intel |
| Multi-platform (Reddit → LinkedIn → X) | Phase 3 | Only after Reddit = 25+ clients stable |

---

## Execution Summary

```
                NOW ──────────── Phase 0 ──────────── Phase 1 ──────── Phase 2 ──── Phase 3
                 │                                       │                │              │
Revenue:        $0                                   $1.5-5K          $5-12K         $25K+
Clients:         0                                     3-5             10             25-60
Avatars:         5 (test)                              15-25           50-100         250+
Monthly cost:  $123                                   $166            $499           $2,510
Margin:         —                                      89%             90%            90%

Key milestones:
Jun 8-9:    Auto-posting stable ●
Jun 10-12:  First demos ●
Jun 30:     Mobile MVP testable ●
Jul 1:      First invoice ●●●
Jul-Aug:    10 clients ●●
Sep-Nov:    AI-Native Expert ●●●●
```

---

## TL;DR — Что делать прямо сейчас

1. **Proxy purchase** — без этого posting = один IP на всех
2. **5 avatars × 3 days** — доказать стабильность
3. **Demos** (Jun 10-12) — Tzvi закрывает первую сделку
4. **Comment tracking** — "вот ваши цифры" для клиента
5. **Mobile API + Flutter** — масштабировать posting team

Всё остальное — после первого invoice.
