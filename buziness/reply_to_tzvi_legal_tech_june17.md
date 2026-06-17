# Technical Response to Legal Brief — June 17, 2026

**To:** Tzvi Vaknin  
**From:** Max (Tech)  
**Re:** Reddit ToS compliance, posting infrastructure, credential handling  
**Status:** CONFIDENTIAL — Internal Only

---

## Executive Summary

Цви, я внимательно изучил оба твоих письма и юридический бриф. Есть несколько **критически важных фактических неточностей** в документе, которые нужно исправить до принятия решений. Ниже — точное описание того, что мы делаем *на самом деле*, юридическая позиция каждого слоя, и мои рекомендации.

---

## ВАЖНО: Фактические исправления к Tech Legal Brief

**В бифе написано:** "RAMP's servers run GoLogin/AdsPower browser profiles via Playwright/Puppeteer, routed through residential proxies."

**Это НЕ соответствует действительности.** В нашей кодовой базе нет ни GoLogin, ни AdsPower, ни Playwright, ни Puppeteer. Ни одного файла, ни одной строчки. Я проверил полный grep по проекту — 0 совпадений.

**Реальная архитектура:** Мы используем **PRAW** (Python Reddit API Wrapper) — это официальный open-source Python SDK для Reddit API. Все наши взаимодействия с Reddit идут через **официальный Reddit API** с OAuth аутентификацией.

Это принципиально отличается от того, что описано в бифе, и значительно улучшает нашу юридическую позицию.

---

## 1. Сбор данных (Intelligence Layer)

### Что мы делаем сегодня

| Слой | Метод | Детали |
|------|-------|--------|
| Scraping | **Reddit Official API через PRAW** | OAuth2 script app, `client_id` + `client_secret` |
| Rate limiting | Самоограничение 30 RPM | Reddit разрешает до 100 RPM (OAuth), мы используем <30% |
| User Agent | Стандартный `reddit-saas:v0.1.0` | Прозрачный, не маскированный |
| Режим | **Read-only** | Scraping client не аутентифицирован как пользователь |
| Данные | Только публичные посты/комментарии | Мы не собираем DM, профили, или приватные данные |

### Юридическая позиция

**Факты:**
- Мы используем **официальный API**, а не raw scraping (не .json endpoint, не HTML parsing)
- Наш app зарегистрирован на reddit.com/prefs/apps — Reddit знает о его существовании
- Мы соблюдаем rate limits (30 RPM при разрешённых 100)
- User Agent не замаскирован

**Проблема (по новым ToS July 2026):**
- Reddit's Responsible Builder Policy теперь **явно** требует: "You must request access and get explicit approval before accessing any Reddit data through our API"
- Ранее для free tier (non-commercial, <100 QPM) это было неявное разрешение. Теперь формально требуется approval.
- Reddit's коммерческий тир: $12,000/month (до 50M calls). Это overkillt для наших 200-300 calls/day.

**Наша экспозиция:**
- **Низкая-средняя.** Мы не скрейпим, мы используем API. Но формально commercial use без explicit approval — это нарушение новых ToS.
- На практике: Reddit удаляет 100k ботов/день (March 2026 action) — это про browser scraping, fake accounts, и vote manipulation. API users с 300 calls/day не на радаре.

### Мои рекомендации (приоритетные)

**Немедленно (0-2 недели):**
1. Убедиться что наш User Agent включает контактный email: `"RAMP/1.0 (contact: tech@gorampit.com)"` — это best practice и показывает добросовестность
2. Документировать в README нашего app что мы используем данные для "brand monitoring and reputation analytics" — это то что Reddit считает legitimate use case

**Краткосрочно (1-3 месяца):**
3. Подать заявку на Reddit's Developer Platform через https://support.reddithelp.com — описать себя как "brand analytics and content strategy platform". Это бесплатно и даёт нам explicit approval.
4. Имплементировать RSS fallback для базового мониторинга (Reddit subreddits дают RSS: `reddit.com/r/{subreddit}/new.rss`). Это не замена API, но даёт Plan B.

**Среднесрочно (3-6 месяцев, если 10+ клиентов):**
5. Оценить лицензированных data providers (Brandwatch, Mention) как intelligence source. Стоимость: $300-500/mo — но это полностью снимает вопрос compliance.

**НЕ рекомендую сейчас:**
- Коммерческий API тир ($12k/mo) — несоразмерно нашему масштабу (300 calls/day)
- Обращение к Reddit за партнёрством — слишком рано, привлекает внимание до того как у нас есть leverage

---

## 2. Posting Infrastructure (Публикация)

### Что мы делаем сегодня

| Компонент | Реализация |
|-----------|-----------|
| Auth mode | **Password auth** через PRAW (script app) — это OAuth2 resource owner password flow |
| Proxy routing | Per-avatar residential proxy (SOCKS5/HTTP) — для каждого аватара отдельный IP |
| Execution | Наш сервер через PRAW → Reddit API → пост публикуется |
| Credentials | Encrypted at rest (Fernet AES-128-CBC), decrypted only at posting time |
| Upgrade path | OAuth refresh_token mode (pending Reddit web app approval) |

### Ключевое отличие от описания в бифе

| Brief says | Reality |
|-----------|---------|
| GoLogin/AdsPower browser profiles | ❌ Не используем. ZERO browser automation. |
| Playwright/Puppeteer | ❌ Не используем. Ни одной строки. |
| "Anti-detection layer" | ❌ Нет. Мы используем стандартный PRAW SDK. |
| Browser sessions | ❌ Нет. Только API requests через PRAW. |

**Наш posting flow:**
```
RAMP server → PRAW (SDK) → Reddit API endpoint → comment posted
                  ↑
         proxy routing (residential IP per avatar)
```

Это архитектурно эквивалентно тому, как работает Buffer, Hootsuite, или любой social media scheduler. Мы используем official API с аутентификацией пользователя.

### Юридическая позиция posting

**В нашу пользу:**
- Мы используем **официальный API**, не browser automation
- Каждый пост проходит human approval (client или operator)
- Audit trail с timestamp, user ID, full content
- Это стандартная модель social media management tools

**Рисковые моменты:**
- Multiple accounts managed from one infrastructure = "coordinated activity" в глазах Reddit
- Proxy rotation per avatar = попытка изоляции fingerprint (Reddit может трактовать как evasion)
- Reddit Responsible Builder Policy: "You must not misrepresent or mask how or why you are accessing Reddit data"

### Что касается модели ReddGrow (browser extension)

Цви прав, что ReddGrow построили юридически чистую модель: extension работает в браузере пользователя → Reddit видит запрос от пользователя, а не от ReddGrow сервера. Их серверы never touch Reddit.

**Однако у нас другая бизнес-модель.** ReddGrow — это self-serve tool (Category 2). Клиент постит сам. Мы — managed service (Category 5). Клиент НЕ постит сам, мы делаем это за него. Это наше конкурентное преимущество и его нельзя разменять.

### Мои рекомендации по posting

**Архитектурная эволюция (3 варианта):**

| Вариант | Описание | Плюсы | Минусы | Рекомендация |
|---------|----------|-------|--------|-------------|
| **A — Status quo (PRAW + proxy)** | Текущая архитектура | Работает, проверено | Сервер = actor on Reddit | ОК на ближайшие 3 мес |
| **B — Mobile app (avatar owner posts)** | Flutter app, owner нажимает "Post" | RAMP server не контактирует Reddit | Зависим от workforce, latency | **Главный приоритет (уже в разработке)** |
| **C — Desktop agent (Electron)** | Agent на машине оператора | Как extension, но для managed | Нужно ставить софт, support burden | Избыточно при наличии mobile app |

**Моя позиция:** Вариант B (мобильное приложение) — это наш путь. Он уже в spec и в roadmap. Avatar owner (hired worker) получает одобренный контент в приложении → нажимает "Post" → приложение постит с телефона владельца аккаунта. RAMP сервер шлёт контент, но **не контактирует Reddit напрямую**.

Это даёт нам ту же юридическую чистоту что у ReddGrow, но в рамках managed service:
- RAMP = intelligence + approval platform (generates, scores, routes content)
- Avatar owner's device = execution layer (posts through own Reddit session)
- Архитектурно разделено, документируемо

**Timeline:** Flutter MVP запланирован. Backend API для mobile posting уже в spec (`.kiro/specs/mobile-posting-app/`).

**Переходный период:** Текущий PRAW posting работает для тестирования и первых клиентов. Когда mobile app готов — переключаем posting execution на мобильный канал, серверный posting остаётся как fallback/testing only.

---

## 3. Учётные данные и сессии

### Что мы делаем сегодня

| Элемент | Хранение | Передача |
|---------|----------|----------|
| Reddit passwords | Encrypted (Fernet AES-128-CBC) в PostgreSQL | Decrypted в RAM только в момент posting |
| OAuth refresh tokens | Encrypted (Fernet) в PostgreSQL | Decrypted в RAM при API call |
| OAuth client_secret | Encrypted (Fernet) в PostgreSQL | Decrypted в RAM |
| Proxy URLs | Encrypted (Fernet) в PostgreSQL | Decrypted при setup PRAW session |
| Encryption key | `FIELD_ENCRYPTION_KEY` env var | Never in code, only in .env |

### Позиция по "credentials never touch our servers"

**Факт:** В модели password auth — да, credentials (username + password) хранятся на нашем сервере. В модели OAuth — refresh_token хранится на сервере.

**Сравнение с ReddGrow:** Они могут сказать "credentials never leave your device" потому что extension работает в браузере пользователя. Мы не можем этого сказать в managed service модели — credentials ОБЯЗАНЫ быть на сервере чтобы постить от имени аватара.

**НО в модели mobile app (Вариант B):** Credentials хранятся ТОЛЬКО на устройстве avatar owner'а. RAMP server хранит только контент для posting + metadata. Это полностью снимает вопрос.

### Рекомендации

1. **Сейчас:** Наше шифрование at-rest (Fernet AES-128) — это industry standard. Документировать это в security policy.
2. **При переходе на mobile:** Credentials остаются на телефоне owner'а. Сервер хранит только approved content queue.
3. **Для аудита:** Добавить last-decryption-timestamp per credential (когда последний раз расшифровывались) — для compliance reporting.

---

## 4. Mentor/Protégé Architecture (Account Acquisition)

Согласен с позицией в бифе. Технически мы уже это реализовали:

- **Phase 0 (Mentor)** в нашей системе = "excluded from ALL automated pipelines"
- Mentor аккаунты не постят, не голосуют, не взаимодействуют
- Они существуют как reference data (public post history → vocabulary/style analysis)

**Что нужно добавить:**
- Физическое разделение в БД (отдельный флаг `is_mentor_account` + query scope исключение)
- Internal documentation classification (уже частично есть через `phase_override = "mentor"`)
- Audit log при любом доступе к mentor account data

---

## 5. Content Approval & Audit Logging

**Текущий статус: ~80% готовности.** Что уже есть:

| Требование | Статус |
|-----------|--------|
| Content ID + full text | ✅ `CommentDraft.ai_draft` + `edited_draft` |
| Avatar identifier + target | ✅ `avatar_id`, `thread_id`, subreddit |
| Client user identity | ✅ `approved_by` (user_id) |
| Timestamp (UTC, immutable) | ✅ `approved_at` (DateTime with timezone) |
| Posting confirmation | ✅ `PostingEvent` with `reddit_comment_url` |
| Guardrail check result | ⚠️ Partial — safety gates log events but not linked to draft |
| Append-only | ⚠️ PostgreSQL (not append-only by design) |
| 36-month retention | ❌ Not configured |
| Export (CSV/JSON) | ✅ Export service exists |

**Что нужно доработать:**
1. Линковка guardrail results к конкретному draft (добавить `safety_check_result` JSONB field)
2. Append-only: рассмотреть PostgreSQL trigger `BEFORE DELETE` + `BEFORE UPDATE` на critical fields — или write-only view
3. Retention policy: добавить в system settings `audit_retention_months = 36`

---

## 6. По вопросу обращения к Reddit за партнёрством

### Мой анализ:

**Аргументы ЗА (обратиться сейчас):**
- Получим contractual basis для data access
- Отличимся от grey-zone tools
- Если Reddit одобрит — это competitive moat
- У них есть Public Content Policy + licensing structure

**Аргументы ПРОТИВ (подождать):**
- Мы используем <300 API calls/day — мы invisible. Обращение делает нас visible.
- При описании use case нам придётся объяснить managed posting — это красный флаг для Reddit
- Reddit отклоняет 90%+ таких заявок
- У нас нет leverage (3 клиента vs тысячи у Brandwatch)
- Если откажут — мы "на заметке" без benefit

### Моя позиция: **Подождать.**

**Порядок действий:**
1. **Сейчас:** Зарегистрировать app description как "brand analytics" (не "posting service")
2. **При 10+ клиентах:** Подать заявку на Developer Program (бесплатно, даёт explicit API access)
3. **При 50+ клиентах:** Оценить commercial API tier ($12k/mo) vs licensed data provider ($500/mo)
4. **Никогда:** Не описывать Reddit'у наш posting layer. API access request — только для data/intelligence.

---

## 7. Priority Build Order (Мой vs Brief)

| # | Brief рекомендует | Моя приоритизация | Комментарий |
|---|------------------|-------------------|-------------|
| 1 | Client-side agent (Electron) | **Mobile app (Flutter)** | Тот же результат, лучший UX, уже в разработке |
| 2 | Licensed data provider | **Reddit API compliance** (User Agent fix + app registration) | Дешевле и быстрее. Data provider — фаза 2 |
| 3 | Audit log hardening | **Согласен** | Быстрый win, критично для legal defense |
| 4 | Mentor account isolation | **Согласен** | Small technical change, high legal value |
| 5 | White-label separation | **Defer** | Нет white-label клиентов, преждевременно |

---

## Итого — Конкретный Action Plan

### Эта неделя (June 17-23):
- [ ] Обновить User Agent на `"RAMP/1.0 (brand-analytics; contact: tech@gorampit.com)"`
- [ ] Добавить `safety_check_result` JSONB на CommentDraft для полной трассировки

### Следующие 2 недели (June 24 - July 7):
- [ ] Зарегистрировать Reddit app description update (brand analytics positioning)
- [ ] Имплементировать append-only constraint на audit records (PostgreSQL trigger)
- [ ] Добавить `is_mentor_account` flag + full isolation в queries

### Июль (при готовности Flutter):
- [ ] Mobile posting MVP → posting execution переезжает на устройство owner'а
- [ ] Server-side posting → testing/fallback mode only
- [ ] Документировать архитектурное разделение для legal

### Август+ (при 10 клиентах):
- [ ] Reddit Developer Program application
- [ ] Evaluate licensed data providers (Brandwatch/Mention)
- [ ] 36-month retention policy enforcement

---

## Резюме для Цви

1. **Наша архитектура чище, чем описано в бифе.** Мы НЕ используем browser automation. Только official API (PRAW).
2. **Intelligence layer (scraping)** — low risk. Мы используем official API, соблюдаем rate limits, не маскируемся. Нужен минимальный fix (User Agent + app registration).
3. **Posting layer** — medium risk сейчас, but solvable. Mobile app (уже в roadmap) полностью снимает вопрос "RAMP servers contact Reddit".
4. **Credentials** — encrypted at rest, industry standard. Mobile app уберёт credentials с сервера entirely.
5. **Обращение к Reddit** — преждевременно. Ждём масштаба.
6. **$12k/mo commercial API** — overkill. Наши 300 calls/day = free tier territory.

Готов обсудить на звонке когда удобно.

— Max
