# RAMP + Devvit Integration — Feasibility & Architecture Analysis

**Date:** July 3, 2026
**Author:** Max (technical analysis for internal decision-making)
**Status:** Research complete, decision pending

---

## Executive Summary

Devvit — это **жизнеспособная долгосрочная платформа** для одного конкретного use case: управление клиентским сабреддитом (модерация + engagement внутри community). Однако это НЕ замена текущей RAMP-модели, а **параллельный продукт** для другого типа клиента.

**Ключевой вывод:** Devvit + RAMP = устойчивая архитектура для "Community Management as a Service". Но это ДОПОЛНЕНИЕ к текущему продукту, не миграция.

---

## 1. Архитектура: Devvit ↔ RAMP Communication

### 1.1 Что умеет Devvit (подтверждено ресерчем, июль 2026)

| Capability | Как работает | Подтверждение |
|-----------|-------------|---------------|
| **Event Triggers** | `onPostCreate`, `onCommentCreate`, `onModAction`, `PostSubmit` — код срабатывает при событии в сабреддите | Десятки apps на devpost.com используют |
| **Scheduler** | Cron-подобные scheduled jobs (ежедневно, ежечасно, custom) | discipline-track, Scheduled Manager apps |
| **Redis (KV Store)** | Встроенный Redis для state management per-subreddit | Все Devvit apps используют |
| **HTTP Fetch** | Devvit может вызывать внешние HTTP API из серверного кода | hashnode tutorial: "call outside APIs with fetch" |
| **Reddit API (context.reddit)** | Полный доступ к Reddit API: approve, remove, submitComment, flair, modmail, lock, sticky | KeyModerator, AgenticMod, PolicyPilot apps |
| **UI (Blocks/Web)** | Custom UI inside Reddit (interactive posts, dashboards, menus) | Devvit Web apps — React + Vite |
| **Menu Actions** | Добавление кнопок в контекстное меню постов/комментов для модераторов | discipline-track, FlairGuard |
| **Moderator Permissions** | App действует от имени модератора, который установил app | Все mod apps |

### 1.2 Communication Model: Devvit → RAMP Backend

```
┌─────────────────────────────────────────────────────┐
│  Reddit (Subreddit)                                  │
│  ┌─────────────────────────────────────────────────┐│
│  │  Devvit App (runs inside Reddit's serverless)   ││
│  │                                                 ││
│  │  Triggers: onPostCreate, onCommentCreate,       ││
│  │           onModAction, Scheduler (cron)         ││
│  │                                                 ││
│  │  Actions: approve, remove, sticky, reply,       ││
│  │          flair, lock, submitComment, modmail    ││
│  │                                                 ││
│  │  Storage: Redis (per-subreddit state)           ││
│  └────────────────────┬────────────────────────────┘│
│                       │ HTTP fetch()                 │
└───────────────────────┼─────────────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────────────┐
│  RAMP Backend (gorampit.com)                           │
│                                                        │
│  POST /api/devvit/event                               │
│    ← receives: subreddit events (new post, comment,   │
│       modqueue item, user action, scheduled tick)      │
│    → responds: action instructions (approve, reply,   │
│       remove, flair, or "no action")                  │
│                                                        │
│  AI Layer: analyzes content, decides action,           │
│  respects client rules, generates responses            │
│                                                        │
│  State: PostgreSQL (cross-subreddit intelligence,      │
│  client config, analytics, billing)                    │
└───────────────────────────────────────────────────────┘
```

### 1.3 Event Schema (Devvit → RAMP)

```json
{
  "event_type": "post_created | comment_created | mod_queue_item | scheduled_check | user_interaction",
  "subreddit": "r/ClientSubreddit",
  "installation_id": "devvit-install-uuid",
  "timestamp": "2026-07-03T12:00:00Z",
  "payload": {
    "post_id": "t3_abc123",
    "author": "username",
    "title": "...",
    "body": "...",
    "flair": "...",
    "score": 5,
    "num_comments": 3,
    "is_mod_queue": false
  },
  "context": {
    "subreddit_subscribers": 15000,
    "author_karma": 500,
    "author_account_age_days": 120
  }
}
```

### 1.4 Response Schema (RAMP → Devvit)

```json
{
  "actions": [
    {
      "type": "approve | remove | reply | flair | sticky | lock | no_action",
      "target": "t3_abc123",
      "params": {
        "reply_text": "Welcome to our community! ...",
        "flair_id": "flair-uuid",
        "removal_reason": "Rule 3: No self-promotion",
        "sticky": true
      }
    }
  ],
  "state_update": {
    "author_trust_score": 72,
    "content_category": "question",
    "intent_signals": ["purchase_intent", "comparison_shopping"]
  },
  "analytics": {
    "event_processed": true,
    "ai_confidence": 0.87
  }
}
```

### 1.5 State Management

| Where | What | Why there |
|-------|------|-----------|
| **Devvit Redis** | Per-subreddit hot state: author scores, recent actions, cooldowns, queue claims | Low latency, Reddit-native, survives app restarts |
| **RAMP PostgreSQL** | Cross-subreddit intelligence, client config, billing, analytics, AI usage logs, historical data | Complex queries, multi-client isolation, RAMP ecosystem |
| **Split invariant** | Devvit Redis = operational cache, RAMP DB = source of truth for business logic | If Devvit Redis is wiped, RAMP can re-seed; if RAMP is down, Devvit operates in degraded mode (cached rules only) |

---

## 2. Ограничения Reddit (July 2026 — UPDATED)

### 2.1 Что изменилось в 2026

| Дата | Изменение | Влияние на RAMP |
|------|-----------|-----------------|
| **May 28, 2026** | Reddit заблокировал unauthenticated `.json` доступ (403 Forbidden, без deprecation window) | Скрапинг без OAuth мёртв. Наш PRAW (OAuth) работает, но Reddit явно охотится на автоматизацию |
| **July 1, 2026** | old.reddit.com требует логин (объявлено, rollout в течение месяца) | Закрытие ещё одного канала скрапинга. Вектор "анонимный доступ" мёртв |
| **March 31, 2026** | Новый User Agreement (v2026) | Ужесточение правил автоматизации |
| **2026 ongoing** | App Migration Program — Reddit хочет перевести все Data API apps на Devvit | Сигнал: Reddit-preferred path = Devvit, не внешние OAuth apps |
| **2026 ongoing** | Developer Funds — Reddit платит Devvit-разработчикам до $167K per app | Сильный сигнал: Reddit инвестирует в Devvit ecosystem |
| **2026** | Commercial API = $12,000/mo minimum ($0.24/1K calls) | Коммерческий скрапинг/чтение = дорого. Devvit apps = бесплатно |

### 2.2 Responsible Builder Policy (действует, подтверждено июль 2026)

Ключевые правила:
- **"You cannot use any Reddit developer tools and services for commercial purposes without first getting our permission."**
- "Developers should use the Developer Platform (Devvit) to build apps on Reddit."
- "All moderator tools are also subject to the Devvit App Review process."
- Запрет на multiple accounts / multiple requests for same use case
- "Be transparent: You must not misrepresent or mask how or why you are accessing Reddit data."

### 2.3 Что Devvit МОЖЕТ

| Действие | Возможно | Как |
|----------|----------|-----|
| Approve/remove posts+comments | ✅ | `context.reddit.approve()`, `context.reddit.remove()` |
| Submit comments (as app bot) | ✅ | `context.reddit.submitComment()` |
| Sticky/lock posts | ✅ | Native Reddit API via context |
| Flair posts/users | ✅ | Native Reddit API via context |
| Read modqueue | ✅ | Trigger on `onModAction` or poll |
| Send modmail | ✅ | Native Reddit API |
| Call external HTTP | ✅ | `fetch()` plugin |
| Scheduled tasks | ✅ | Devvit scheduler (cron) |
| Store state | ✅ | Redis KV store (per-subreddit) |
| Custom UI in posts | ✅ | Devvit Web (React), Blocks UI |
| Menu actions for mods | ✅ | Custom items in ⋮ menu |
| React to user interactions | ✅ | Button clicks, form submissions in custom posts |

### 2.4 Что Devvit НЕ МОЖЕТ

| Ограничение | Влияние | Workaround |
|-------------|---------|-----------|
| **Не может постить от имени пользователя** (только как "[App Name] Bot") | Комменты от аватара невозможны через Devvit | Extension остаётся для avatar posting |
| **Execution environment — serverless** (cold starts, timeout limits) | Долгие LLM вызовы могут timeout'нуться | RAMP backend делает AI-вызовы, Devvit только получает результат |
| **Один app = один суб за раз** (multi-sub = multiple installs) | Нет проблем для нашего кейса (per-client sub) | Каждый клиент — отдельная установка |
| **App Review process** — Reddit ревьюит все public apps | Может занять дни/недели. Policy compliance обязательна | Начать ревью процесс заранее |
| **Нет доступа к DMs пользователей** | Не можем мониторить private messages | Не нужно для mod use case |
| **Comments от app = явно от бота** (не stealth) | Нельзя выдавать app за человека | Для mod-assistant это ОК (прозрачность = плюс) |
| **Rate limits внутри Devvit** (не документированы публично) | Может быть ограничение на количество Reddit API вызовов per minute | Batch actions, queue management |
| **Нет websockets / long-lived connections** | Только request-response или scheduled | Polling RAMP backend через scheduler |
| **Коммерческое использование требует разрешения Reddit** | Продавать Devvit app как сервис = нужен approval | Пока framing = "moderation tool" (допустимо), не "commercial data service" |

### 2.5 Policy Risk Assessment

| Действие | Risk Level | Обоснование |
|----------|-----------|-------------|
| AI-assisted moderation (approve/remove) | 🟢 LOW | Десятки таких apps уже на Devvit (AgenticMod, ModSentinel, PolicyPilot). Reddit поощряет |
| Auto-reply to new posts (welcome, FAQ) | 🟢 LOW | Scheduled Manager, SubNotify — common pattern |
| External AI backend для решений | 🟡 MEDIUM | Apps используют OpenAI/Anthropic API. Но "commercial external backend" может вызвать вопросы при app review |
| Intent signal collection (отправка данных во внешнюю систему) | 🟡 MEDIUM | Допустимо если anonymized и для moderation purposes. Нельзя: selling user data |
| Engagement manipulation (scheduled community prompts) | 🟡 MEDIUM | Допустимо как "community engagement tool". Нельзя: fake activity, vote manipulation |
| Avatar posting THROUGH Devvit | 🔴 HIGH | Devvit не может постить от имени юзера. Технически невозможно. Extension path остаётся |
| Multi-subreddit orchestration from one backend | 🟡 MEDIUM | Каждый sub = отдельная install. Но один backend managing 50 subs may raise "commercial without permission" flag |

---

## 3. Модель Доступа (Onboarding без API Keys)

### 3.1 Как клиент "подключает сабреддит к RAMP"

```
1. Клиент (модератор сабреддита) открывает Devvit App Directory
2. Находит наш app (e.g., "RAMP Community Assistant")
3. Нажимает "+ Add to Community"
4. Reddit показывает permission prompt:
   "This app requests: Manage Posts, Manage Comments, Read Modmail,
    Manage Flairs, Submit Comments (as bot), Read Subreddit Settings"
5. Клиент одобряет → app установлен
6. App при первом запуске:
   - Генерирует unique installation_id
   - Показывает Setup UI (custom post): "Enter your RAMP client ID"
   - ИЛИ: показывает код активации "Enter this code at gorampit.com/connect"
7. На стороне RAMP: клиент вводит код → subreddit привязан к аккаунту
8. Done. Никаких OAuth keys, API tokens, или технических шагов.
```

### 3.2 Permissions Model

| Уровень | Что видит/делает | Как реализуется |
|---------|------------------|-----------------|
| **Subreddit-level isolation** | Devvit Redis = per-install. RAMP DB = per-client_id. Никогда не пересекаются | Standard RAMP isolation (P7) |
| **Moderator permissions** | App наследует permissions от мода, который установил | Reddit-native. Если мод снят — app permissions остаются |
| **RAMP client identity** | Installation → RAMP client mapping. Stored in Devvit Redis + RAMP DB | Bidirectional link |

### 3.3 Отличие от текущей модели

| | Текущий RAMP (avatars) | Devvit RAMP (community) |
|-|------------------------|------------------------|
| Auth | Avatar OAuth + PRAW + proxy | Zero — Devvit install = done |
| API keys | Per-avatar Reddit app credentials | None needed |
| Posting identity | Avatar account (stealth) | App bot account (transparent) |
| Risk of ban | High (shadowban, suspension) | Zero (Devvit app = Reddit-endorsed) |
| Scope | Comment in OTHER people's subs | Moderate OWN sub |
| Revenue model | Per-comment SaaS | Per-subreddit management fee |

---

## 4. MVP Scope

### 4.1 Safe MVP Features (✅ Allowed by Reddit Policy)

| Feature | Complexity | Value |
|---------|-----------|-------|
| **AI-powered mod queue triage** — new posts scored, ranked, approve/remove suggestion | Medium | HIGH — biggest pain point for mods |
| **Welcome bot** — auto-reply to first-time posters with contextual greeting | Low | Medium — retention signal |
| **Scheduled community threads** — weekly discussion, daily prompt | Low | Medium — engagement structure |
| **Flair automation** — auto-flair based on content classification | Low | Medium — organization |
| **Modmail assistant** — AI drafts replies to common modmail questions | Medium | HIGH — time-saver |
| **Content analytics → RAMP dashboard** — engagement trends, author quality, topic distribution | Medium | HIGH — differentiator vs free tools |
| **Rule enforcement** — detect rule violations, suggest removal reason | Medium | HIGH — consistency |
| **Intent signal collection** — anonymized "purchase intent" signals from community interactions → RAMP analytics | Medium | HIGH — the real value for real estate client |

### 4.2 Risky Features (⚠️ Require Mitigation)

| Feature | Risk | Mitigation |
|---------|------|-----------|
| **Sending full post text to external backend** | "Data exfiltration" perception | App review framing: "moderation analysis". Anonymize user PII. Only send content + metadata, not user identity |
| **Commercial intent signal collection** | "Using mod access for commercial purposes" | Frame as "community health analytics". Don't sell data to third parties. It informs client's own marketing, not data brokering |
| **AI-generated engagement posts** (the Devvit hypothesis) | "Inauthentic engagement" if mishandled | Posts clearly from "[App Bot]". Never pretend to be human. Value = interactive content (polls, quizzes, market updates), not fake engagement |
| **Multi-client deployment** (one app, many subreddits) | "Commercial use without permission" | Get Reddit's commercial approval BEFORE scaling beyond 2-3 clients. One email to developer relations |

### 4.3 Not Feasible (❌)

| Feature | Why Not |
|---------|---------|
| Avatar posting through Devvit | Devvit posts as app bot, not as user. Cannot impersonate |
| Reading user DMs | No API access to private messages via Devvit |
| Cross-subreddit content manipulation | Each install is isolated. Can't approve posts in sub B from sub A |
| Scraping other subreddits for leads | Not what Devvit is for. Would violate Responsible Builder Policy |
| Vote manipulation / coordinated voting | Devvit has no vote API, and this violates Reddit rules absolutely |
| Stealth operations | All Devvit actions are logged. App identity is visible |

---

## 5. Трудоёмкость

### 5.1 Devvit App Development

| Component | Effort | Dependencies |
|-----------|--------|-------------|
| Basic Devvit app scaffold (triggers, scheduler, Redis) | 2-3 days | Devvit CLI, TypeScript |
| Content analysis trigger (onPostCreate → fetch to RAMP) | 1-2 days | RAMP endpoint |
| Mod actions (approve/remove/flair based on RAMP response) | 1-2 days | Response schema |
| Setup UI (activation code flow) | 1 day | RAMP client linking |
| Moderator dashboard (custom post with stats) | 2-3 days | Devvit Web, React |
| Modmail integration | 1-2 days | Reddit modmail API |
| **Total Devvit app:** | **8-13 days** | |

### 5.2 RAMP Backend Integration

| Component | Effort | Dependencies |
|-----------|--------|-------------|
| `POST /api/devvit/event` endpoint | 1 day | FastAPI route |
| Event processing service (classify, decide action) | 2-3 days | Existing AI services |
| Client ↔ Devvit installation linking | 1 day | DB model + admin UI |
| Community analytics dashboard (RAMP portal) | 2-3 days | Templates, services |
| Intent signal processing + storage | 1-2 days | New model, analytics service |
| **Total backend:** | **7-10 days** | |

### 5.3 Reddit App Review & Deployment

| Step | Duration | Notes |
|------|----------|-------|
| Submit app for review | — | Upload to Reddit |
| Review process | **3-14 days** | Unknown. Could be fast (simple mod tool) or slow (external backend raises questions) |
| Iterations on reviewer feedback | 1-5 days | May need to adjust permissions, add disclosures |
| **Total review cycle:** | **4-19 days** | Unpredictable |

### 5.4 Ongoing Maintenance

| Item | Effort | Frequency |
|------|--------|-----------|
| Devvit SDK updates | 1-2h | Monthly |
| Reddit UI/DOM changes | 0 (Devvit abstracts this) | — |
| Feature additions | Varies | On demand |
| Monitoring & debugging | Low (Reddit hosts infra) | Weekly check |

### 5.5 Total Timeline to Working MVP

```
Week 1-2:  Devvit app + RAMP backend integration (parallel work)
Week 2-3:  Testing on private subreddit (no review needed for own sub)
Week 3-5:  Reddit App Review process (unpredictable)
Week 5:    Deploy to first client subreddit

Conservative estimate: 5-6 weeks to first client
Optimistic estimate: 3-4 weeks (fast review)
```

---

## 6. Ключевой Вывод

### Является ли Devvit + RAMP устойчивой долгосрочной платформой?

**ДА, для use case "Community Management" — это идеальная архитектура.**

Причины:
1. **Reddit actively endorses Devvit** — Developer Funds ($167K), migration program, ecosystem investment. Devvit = Reddit's chosen future.
2. **Zero infrastructure risk** — никаких прокси, OAuth токенов, shadowbans. App runs inside Reddit.
3. **Zero policy risk for moderation** — десятки AI-mod apps уже одобрены. Это encouraged behavior.
4. **Scalable by design** — каждый суб = отдельная install. Reddit handles hosting.
5. **Revenue-compatible** — Reddit allows paid Devvit apps (Reddit Gold economy). Commercial partnership possible.

### Однако — это НЕ замена текущего RAMP

| Текущий RAMP | Devvit RAMP |
|--------------|-------------|
| Post in OTHER people's subs | Manage YOUR OWN sub |
| Stealth presence | Transparent bot |
| Multi-avatar | Single app identity |
| Content seeding | Community management |
| Brand mentions | Community engagement |
| AEO/GEO grounding | Community retention |

**Правильная модель: два продукта, одна платформа.**

```
RAMP Core (existing):
  → Avatar content seeding in third-party subs
  → AEO/GEO authority building
  → Extension-based posting
  → = "Outbound Reddit marketing"

RAMP Community (new, Devvit):
  → Client-owned subreddit management
  → AI moderation + engagement
  → Intent signal collection
  → = "Inbound community platform"
```

### Рекомендация для Цви (real estate lead)

**Можно предлагать прямо сейчас:**
- "Client-owned subreddit management" как add-on к основному RAMP пакету
- Moderator task types (approve, remove, sticky, reply) — MVP **3-5 дней** если через browser extension (без Devvit)
- Community management через Devvit — MVP **5-6 недель** (полная платформа)
- **Recurring cost per client: ~$0** (Reddit hosts Devvit бесплатно, AI costs = same as existing RAMP pipeline per LLM call)

**Timeline ответ для Цви:**
- Moderator tasks через extension = **3-5 days** (минимальные добавления к существующему коду)
- Full community management через Devvit = **5-6 weeks** (новый продукт, но реалистичный)
- Operational cost = **zero recurring** (no proxies, no infra, only LLM calls when AI moderation triggered — estimated $5-20/mo per active subreddit)

---

## 7. Risks & Open Questions

### Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Reddit rejects app at review (commercial use without permission) | Medium | High | Contact Reddit Developer Relations proactively. Frame as "community moderation tool" not "marketing automation" |
| Devvit SDK breaking changes | Low | Medium | Pin versions. Devvit is in active development but core APIs are stable |
| Reddit changes policy on external backend calls | Low | High | Keep RAMP logic thin in Devvit (just relay), business logic on our side. If fetch() blocked, we degrade gracefully |
| Client's subreddit gets banned/quarantined | Low | Medium | Not our fault (client's content). Contract clause |
| Competitor builds similar first | Medium | Low | Execution speed matters. First mover with AI backend = defensible |

### Open Questions (for decision)

1. **Do we approach Reddit Developer Relations now?** — Getting commercial approval before building is the safe path. Risk: they say no. Upside: legal clarity.

2. **Naming: should the Devvit app be branded "RAMP" or neutral?** — Neutral name ("Community Assistant") avoids associating our brand with automation perceptions. But less brand building.

3. **Do we build the Devvit path first, or moderator extension tasks first?** — Extension tasks = 3-5 days, works NOW. Devvit = 5-6 weeks, better long-term. For the real estate lead's timeline, extension mod tasks first makes sense.

4. **The Devvit pilot hypothesis (interactive AI entity) — separate track or merged?** — My recommendation: separate. Mod tooling is safe MVP. AI entity in subreddit = more experimental, higher review risk.

---

## Appendix: Reddit Platform Changes Timeline (2026)

| Date | Change | Source |
|------|--------|--------|
| March 31, 2026 | New User Agreement effective | redditinc.com |
| May 28, 2026 | `.json` unauthenticated access blocked (403) | r/modnews announcement |
| June 2026 | App Migration Program active (Data API → Devvit) | Reddit Help Center |
| July 1, 2026 | old.reddit.com login required (announced, 1-month rollout) | Ars Technica, r/reddit.com |
| 2026 ongoing | Commercial API = $12K/mo minimum | citybiz.co |
| 2026 ongoing | Developer Funds = up to $167K per Devvit app | phaser.io, Reddit Help |

**Trend: Reddit is systematically closing non-official access paths and pushing developers toward Devvit.** This makes Devvit not just viable but strategically necessary for long-term Reddit platform presence.
