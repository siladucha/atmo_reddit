# Отчёт: Состав проекта / воркфлоу Ори

_Дата: 14 мая 2026_

---

## Стек Ори (оригинальная система)

| Компонент | Инструмент |
|-----------|-----------|
| Автоматизация | n8n (self-hosted) |
| База данных | Supabase (PostgreSQL) |
| UI / Ревью | Airtable (интерфейсы + автоматизации) |
| Скрейпинг Reddit | n8n Reddit node (OAuth через аккаунт Ори) |
| LLM роутинг | OpenRouter (Claude Sonnet, Gemini Flash, Opus) |
| Хранение комментариев | Supabase + Airtable (дублирование) |

---

## Воркфлоу Ори — полный пайплайн

### 1. Scraping (`Run subreddits - Cyber` → `Scrape subreddit`)

**Что делает:**
- Хардкод-список из 33 сабреддитов с лимитами (cybersecurity: 70, sysadmin: 80, и т.д.)
- Для каждого сабреддита вызывает sub-workflow `Scrape subreddit`
- Скрейпит через Reddit API (n8n node, OAuth Ори)
- Фильтрует: только посты за последние 24 часа + только с текстом (selftext не пустой)
- Извлекает изображения из постов (gallery, i.redd.it)
- Для каждого поста вызывает sub-workflow `Reddit Comments Official` — скрейпит дерево комментариев (до 20 штук)
- Rate limiting: wait 15 секунд между батчами (Reddit API 60 req/min)
- Результат: нормализованный JSON (title, content, comments, ups, downs, images, permalink, subreddit_id)

### 2. Scoring / Qualification (`Run subreddits - Cyber` → scoring node)

**Что делает:**
- Gemini Flash (дешёвая модель) классифицирует каждый тред
- Выходной формат: `{ alert, tag, scores: {relevance, quality, strategic, composite}, intent, triggers, override_applied, reason }`
- Три тега: `engage` / `monitor` / `skip`
- Composite score = relevance + quality + strategic (0-9)
- Override rules: company mentioned → alert, competitor + relevance ≥ 2 → engage, buying signal → alert
- Intent classification: help_seeking, comparison, opinion_forming, venting, announcement, other
- Trigger detection: competitor_mentioned, company_mentioned, buying_signal

**Промпт включает:**
- Company Profile (XM Cyber) — worldview, competitors, keywords, positioning
- Scoring framework с чёткими критериями 0-3 по каждой оси
- Structured output parser (JSON schema validation)

### 3. Persona Selection (отдельный LLM вызов)

**Что делает:**
- Gemini Flash выбирает лучшего аватара для каждого треда
- Входные данные: тред + все персоны с их сабреддитами и триггерами
- Выходной формат: `{ persona[], mode, audience, thread_angle, pov_opportunity, selection_reasoning }`
- Три режима: `bullseye` (push core belief), `helpful_peer` (practical + soft POV), `karma_only` (build presence)
- Multi-persona support: может выбрать 1-3 аватаров для одного треда

**Decision flow:**
1. Hard filter — subreddit eligibility (персона подписана на этот сабреддит?)
2. Audience read — кто в треде, что обсуждают
3. Match scoring — peer fit × topic fit × strategic fit
4. Priority check — karma level, multi-persona consideration
5. Select — best persona + engagement mode

### 4. Comment Generation (`XM Cyber | Write comments`)

**Что делает:**
- Claude Sonnet (через OpenRouter) генерирует комментарий
- Один комментарий за вызов, structured JSON output

**Промпт V2 (самый ценный артефакт) включает:**

1. **System prompt** — "Reddit Comment Writer Prompt V2" (~3000 слов):
   - 3 стратегических тира: Reframe → Tear Down → Karma Play
   - 5 подходов: Reframe Drop, Cynical Deconstruction, The Scar, The Contrarian, The Drive-By
   - Жёсткие ограничения: 20-60 слов (hard max 80), один параграф, без форматирования
   - Anti-monotony: 6 типов опенеров, diversity enforcement (5 проверок перед генерацией)
   - Forbidden patterns: em-dashes, LinkedIn spacing, academic transitions, passive voice, "Th" starters, gerund openers
   - Technical depth rule: "what happened" > technical play-by-play
   - Language simplicity: banned buzzwords с plain-language заменами
   - Stream-of-consciousness standard
   - Location choosing logic (engagement + relevance + depth)

2. **Reddit Engagement Guide** (~2500 слов):
   - Audience & Intent Blueprint
   - Content Archetypes (7 типов комментариев)
   - Narrative Assembly (4-part spine)
   - Reddit Platform Mechanics
   - Engagement Psychology
   - Anti-Shill Safeguards (9.1-9.5)
   - Account Lifecycle (karma → authority → occasional promotion)

3. **Company Profile** (XM Cyber) — worldview, competitors, vocabulary, guardrails

4. **Voice Profile** — полный профиль выбранного аватара

5. **Previous 20 comments** — для diversity enforcement

**Выходной формат:**
```json
{
  "comment": "текст",
  "location": "цитата того, кому отвечаем / 'post'",
  "location_depth": 2,
  "location_reasoning": "почему это место",
  "comment_approach": "reframe_drop / cynical_deconstruction / the_scar / the_contrarian / the_drive_by",
  "strategic_angle": "reframe / tear_down / karma_play",
  "reframe_intensity": "subtle / moderate / none"
}
```

### 5. Hobby Comment Generation (`Hobby Comment Writing`)

**Что делает:**
- Отдельный пайплайн для хобби-сабреддитов (karma building)
- Supabase: hobby_subreddits table (посты за 24ч)
- Matching: avatar ↔ hobby subreddit по subreddit_id
- Random sampling: 1-4 поста на сабреддит, 1 аватар на сабреддит
- Claude Opus (через OpenRouter) генерирует комментарий
- Другой промпт: "Hobby & Karma Comment Writer" — без стратегии, чистый karma

**Отличия от профессионального:**
- Цель: karma, не worldview seeding
- Тон: casual participant, не authority
- 6 engagement angles: sharp_take, yeah_and, useful_drop, micro_story, reality_check, question
- Knowledge depth rule: "casual participant, not authority"
- Нет Company Profile в контексте

### 6. Post Generation (`XM Cyber — Reddit Post Creation`)

**Двухэтапный процесс:**

**Этап 1 — Brief Generator (Claude Sonnet):**
- Берёт новость из `news_scrape` table (Supabase)
- Генерирует стратегический бриф: treatment mode, post type, strategic tier, body architecture, title direction, worldview note
- 6 treatment modes: news_share, blog_research_share, inspiration, original, discussion_catalyst, update_sequel
- 10 post types: breaking news, personal narrative, career frustration, hot take, discussion prompt, research, deep-dive, tool showcase, policy alert, leadership question
- 3 body architectures: narrative arc, evidence stack, rant with structure

**Этап 2 — Post Writer (отдельный LLM):**
- Получает бриф + voice profile + company profile
- Пишет финальный пост (title + body)

**Этап 3 — Persona Selection (Gemini Flash):**
- Выбирает аватара для поста (тот же механизм что для комментариев)

### 7. Review & Posting (`Update comment sent`)

**Что делает:**
- Airtable Interface: человек видит комментарий, может отредактировать в "Refined Version"
- Чекбокс `comment_sent` → Airtable automation → webhook в n8n
- n8n workflow: читает запись из Airtable → копирует в "Reddit Comments Tracking" → удаляет из очереди
- Человек вручную постит в Reddit (copy-paste)

---

## Данные Ори (Airtable CSV экспорты)

| Таблица | Записей | Содержание |
|---------|---------|-----------|
| Reddit Personas | 7 | Полные voice profiles (Marcus, Lena, Derek, Leon, Emma, Lucas/Maurice, Connor/Ken) |
| Keywords | ~120 | HIGH/MEDIUM/LOW приоритет |
| Reddit Comments | ? | AI-сгенерированные комментарии (очередь на ревью) |
| Reddit Comments Tracking | 8000+ | Исторические отправленные комментарии |
| XM Cyber Reddit Posts | ? | AI-сгенерированные посты |
| Scrape | 24000+ | Сырые скрейпнутые посты |
| Influencers list | пусто | Только заголовки |

---

## Аватары Ори (7 персон для XM Cyber)

| Имя | Username | Роль | Статус | Профессиональные сабы | Хобби |
|-----|----------|------|--------|----------------------|-------|
| Marcus Thorne | ThorneMarcus92 | CISO, 52 | Active | r/CISO, r/securityoperations | wine, sailing, investing |
| Lena Gupta | Lena_Gupta19 | Head of Cloud Security, 35 | Not Active | r/cloudsecurity, r/devsecops | marathontraining, homelab |
| Derek Walsh | d-wreck-w12 | VM Lead, 41 | Active | r/redteamsec, r/netsec | amateurradio, securityctf |
| Leon Grant | leon_grant10 | Security Architect, 33 | Active | r/infosec, r/netsec | NFL, popcultureanalysis |
| Emma Richardson | emma_richardson | IAM Lead | Not Active | r/cloudsecurity, r/sysadmin | travel, cocktails |
| Lucas Parker | lucas_parker2 | Director SecOps, 46 | Active | r/securityoperations, r/sysadmin | dodgers, steelydan |
| Connor Lloyd | connor_lloyd | IAM Lead, 55 | Not Active | r/cloudsecurity, r/sysadmin | travel, cocktails |

---

## Что было у Ори, но НЕТ у нас

### 🔴 Критичное (влияет на качество генерации)

| Компонент | У Ори | У нас | Статус |
|-----------|-------|-------|--------|
| **Forbidden Patterns document** | Отдельный файл `forbidden_patterns.md` — полный список запрещённых конструкций (em-dashes, "Th" starters, gerunds, passive voice, academic transitions, LinkedIn spacing, staccato sentences, binary oppositions) | Частично в промпте, нет отдельного документа | ❌ Не портировано как отдельная сущность |
| **Reddit Guide document** | Отдельный файл `Reddit_Guide.md` — subreddit-specific rules, culture, what gets upvoted/buried | Нет | ❌ Не портировано |
| **Subreddit Culture & Rules** | `subreddit_culture_and_rules.md` — per-subreddit нормы | Нет (есть spec на subreddit intelligence, но не реализовано) | ❌ Spec ready, не реализовано |
| **ICP Personas document** | `[company]_ICP_Personas.md` — target audience pains, motivations, language signals, "Tuesday triggers" | Нет отдельного документа | ❌ Не портировано |
| **Previous 20 comments injection** | Последние 20 комментариев аватара подаются в промпт для diversity enforcement | Нет (self-learning loop есть, но не previous comments) | ❌ Не реализовано |
| **Diversity enforcement (5 проверок)** | Opener scan, Theme scan, Approach scan, Vocabulary scan, Structure scan — перед каждой генерацией | Нет | ❌ Не реализовано |
| **Comment approach diversity** | 5 подходов с принудительной ротацией (reframe_drop, cynical_deconstruction, the_scar, the_contrarian, the_drive_by) | Подходы есть в промпте, но нет enforcement/rotation | ⚠️ Частично (P0 в бэклоге) |
| **Prep Step (pre-generation analysis)** | Отдельный LLM вызов перед генерацией: определяет mode, audience, thread_angle, pov_opportunity | У нас persona selection делает это, но без отдельного "prep step" | ⚠️ Частично (merged в persona selection) |
| **News scraping для постов** | `news_scrape` table в Supabase — новости для генерации постов | Нет источника новостей | ❌ Не реализовано |
| **Two-stage post generation** | Brief Generator (стратег) → Post Writer (исполнитель) — два отдельных LLM вызова | У нас один вызов `generate_post` | ❌ Не реализовано |
| **Post Brief Generator prompt** | Детальный промпт стратега: 6 treatment modes, 10 post types, 3 body architectures, title direction framework | Нет | ❌ Не портировано |
| **Image extraction from posts** | Извлечение изображений из Reddit постов (gallery, i.redd.it) для контекста | Нет | ❌ Не реализовано |
| **Deduplication (aggressive)** | Дедупликация по permalink + post content перед генерацией | У нас дедупликация на уровне scraping (по reddit_id), но не по content | ⚠️ Частично |

### 🟡 Важное (влияет на операционную эффективность)

| Компонент | У Ори | У нас | Статус |
|-----------|-------|-------|--------|
| **Refined Version field** | Человек пишет отредактированную версию → анализируется для улучшения промптов | У нас `EditRecord` + `CorrectionPattern` (self-learning loop) | ✅ Реализовано лучше |
| **Comment tracking (8000+ records)** | Полная история всех отправленных комментариев с метаданными | У нас `CommentDraft` с полным lifecycle | ✅ Реализовано |
| **Alert system** | `alert: true` на высокоприоритетных тредах → отдельная обработка | У нас scoring с tag=engage, но нет отдельного "alert" флага с push-уведомлением | ⚠️ Частично |
| **Hobby subreddit random sampling** | 1-4 поста на сабреддит, рандомный выбор аватара | У нас hobby pipeline есть, но логика sampling может отличаться | ⚠️ Проверить |
| **Multi-persona per thread** | Может выбрать 1-3 аватаров для одного треда (consensus building) | У нас один аватар на тред | ❌ Не реализовано |
| **Structured output parser + auto-fix** | n8n `outputParserAutofixing` — если JSON невалидный, LLM пытается починить | У нас Pydantic validation, но без auto-fix retry | ⚠️ Частично (retry есть, auto-fix нет) |

### 🟢 Реализовано у нас лучше (чего у Ори НЕ было)

| Компонент | У нас | У Ори |
|-----------|-------|-------|
| Self-learning loop (edit records → correction patterns → few-shot injection) | ✅ Полная реализация | ❌ Только manual prompt tuning |
| Thread liveness protection (locked/removed/archived detection) | ✅ На всех этапах пайплайна | ❌ Нет |
| Avatar health monitoring (shadowban, CQS, auto-freeze) | ✅ 5-state health model | ❌ Нет |
| Warming phases (0-3) с pipeline gates | ✅ Полная реализация | ❌ Нет (все аватары одинаковые) |
| RBAC (6 ролей, client isolation, query scoping) | ✅ Полная реализация | ❌ Single-tenant |
| Strategy documents per avatar | ✅ Реализовано | ❌ Нет |
| Karma tracking per subreddit | ✅ Реализовано | ❌ Нет |
| Avatar subreddit presence map | ✅ Реализовано | ❌ Нет |
| System topology dashboard | ✅ Реализовано | ❌ Нет |
| Emergency controls (kill switches, freeze) | ✅ Реализовано | ❌ Нет |
| Retry with exponential backoff | ✅ Реализовано | ⚠️ Простой retry в n8n |
| LLM output validation (Pydantic schemas) | ✅ Реализовано | ⚠️ JSON schema в n8n (менее строгий) |
| Context isolation assertions | ✅ Runtime checks | ❌ Нет |
| Scraping architecture (subreddit-centric, rate-limited, freshness-gated) | ✅ Продвинутая | ⚠️ Простой loop с wait |
| Admin panel (35+ страниц) | ✅ Полный | ❌ Airtable interfaces |
| Mobile posting app (spec) | ✅ Spec ready | ❌ Manual copy-paste |
| Multi-client support | ✅ Полная изоляция | ❌ Single client (XM Cyber) |
| Avatar Intelligence UI | ✅ Confidence, removal rate, patterns | ❌ Нет |
| Audit logging | ✅ Полный audit trail | ❌ Нет |

---

## Приоритеты портирования

### P0 — Перед пилотом (влияет на качество комментариев)

1. **Previous comments injection** — ✅ DONE: query последних 20 posted/approved/pending drafts **per avatar** (не per client). Кэш в рамках одного pipeline run.
2. **Comment approach diversity enforcement** — ✅ DONE: полный блок diversity enforcement в промпте (5 проверок: opener, approach, vocabulary, structure + таблица 6 типов опенеров)
3. **Forbidden patterns** — ✅ DONE: полная секция в промпте (banned starters, banned endings, banned words, banned structures)
4. **`perspective_push` field** — ✅ DONE: migration + model + schema + generation output (hard/medium/low/undetected)

### P1 — Перед 10 клиентами

5. **ICP Personas document** — per-client target audience description для injection в промпт
6. **Subreddit culture/rules** — per-subreddit нормы (spec уже есть)
7. **News source for post generation** — RSS/scraping новостей для двухэтапной генерации постов
8. **Two-stage post generation** — Brief Generator → Post Writer
9. **Multi-persona per thread** — возможность 2-3 аватаров на один тред

### P2 — Nice to have

10. **Image extraction** — изображения из постов как контекст для LLM
11. **Reddit Guide document** — общий гайд по платформе (можно встроить в промпт)
12. **Auto-fix parser** — если LLM output невалидный, повторный вызов с инструкцией починить
