# RAMP — Meeting Report: June 5, 2026

**Participants:** Maxim (Tech), Tzvi (Business)
**Duration:** 78 minutes
**Context:** Product roadmap definition + Reddit API risk assessment

---

## Executive Summary

Встреча зафиксировала стратегический сдвиг: вместо зависимости от единственного Reddit API ключа — переход к white-label модели, где каждый клиент (или его аватар) использует собственные Reddit credentials. Это устраняет single point of failure и выравнивает бизнес с Reddit ToS.

Новый приоритет: auto-posting → mobile app → GEO/AIO layer.

---

## 1. Critical Risk: Reddit API Dependency

**Проблема:** Платформа работает на одном legacy Reddit API ключе (`smi_parser_bot`). Reddit больше не выдаёт новые ключи в self-serve режиме (Responsible Builder Policy, май 2026). Отзыв ключа = мгновенная остановка всех операций.

**Решение:** White-label модель — каждый аватар авторизуется через собственные credentials (password auth сейчас, OAuth когда Reddit одобрит).

**Техническая готовность:**
- ✅ Dual-mode auth adapter (password + OAuth) — реализован
- ✅ Per-avatar credentials (encrypted) — реализован
- ✅ Per-avatar proxy support — архитектура готова, нужна закупка
- ✅ First verified post через personal credentials (June 1, r/test)
- ⚠️ OAuth callback deployed, ждём одобрения Reddit

**Вывод Максима:** Технически white-label уже работает на уровне posting (password auth). Единственный legacy ключ используется только для *чтения* (scraping, health checks). Для чтения публичных данных Reddit не ограничивает доступ — это не risk blocker.

---

## 2. New Roadmap (согласован на встрече)

### Priority 1: Auto-Posting Stabilization (this week)

**Статус после встречи:**
- 13 critical bugs fixed (QA Pardo)
- E2E pipeline verified (first real post June 1)
- Remaining: стабильность на 5+ аватарах, proxy integration

**Что реально работает (из анализа кода):**
- 9 safety gates (kill switch, frozen, health, phase, daily cap, proxy, UA, subnet)
- Timing engine (jitter ±30%, min 45 min, active hours, peak bias)
- Celery Beat every 5 min → per-slot task with retry
- PostingEvent audit trail (full forensics)
- Auto-freeze on auth errors / 3 consecutive failures

**Что нужно доделать:**
- [ ] Admin UI: posting logs dashboard, proxy config section
- [ ] Proxy purchase (ProxyJet residential IPs)
- [ ] Test on 5 personal avatars for 3 days without intervention
- [ ] Demo-ready: показать Tzvi pipeline в action

### Priority 2: Mobile App (starts after auto-posting stable)

**Key differentiator** — "human-in-the-loop" daily app:
1. Аватар-владелец открывает app утром
2. Видит EPG (3-7 рекомендаций на день)
3. Tap → approve / edit / reject
4. Copy draft → open Reddit → paste → confirm
5. App track publication (link or auto-detect)

**Техническая готовность backend:**
- ✅ EPG service — полностью реализован (phase-aware, dedup, timing slots)
- ✅ Comment generation — working (learning loop, approach diversity)
- ✅ Strategy engine — working (injection в generation)
- ❌ Mobile REST API — НЕ существует (нужно 5-7 эндпоинтов)
- ❌ Refresh tokens — нет (только bearer JWT)
- ❌ Push notifications — не реализованы

**Необходимый API для Mobile:**
```
GET  /api/mobile/epg?date=YYYY-MM-DD     — дневная программа
GET  /api/mobile/draft/{slot_id}          — черновик для конкретного слота
POST /api/mobile/feedback                 — approve/reject/edit
POST /api/mobile/track_publication        — ссылка на опубликованный пост
POST /api/mobile/auth/login               — email+password → JWT + refresh
POST /api/mobile/auth/refresh             — refresh token flow
GET  /api/mobile/stats                    — базовая статистика аватара
```

**Оценка:** 3-5 дней backend работы на API layer. Flutter app — параллельная разработка.

### Priority 3: GEO/AIO Layer (Generative AI Optimization)

**Концепция:** Помочь аватарам клиентов появляться в ответах AI-систем (ChatGPT, Perplexity, Google AI Overviews).

**Решение:** Интеграция через API с существующим инструментом (Spotlight, ~$200/mo) вместо разработки с нуля.

**Техническая связь с RAMP:**
- Spec `.kiro/specs/ai-native-expert-warming/` уже описывает эту стратегию
- 4 архитектурных принципа: Topic Authority, Citable Content, Tier-2 Signals, Entity Linking
- Authority Score (0-100) + Citability Score запланированы в Phase 2

**Вывод:** Не строим сами. Подключаем внешний инструмент через API. Фокус разработки — на mobile app.

---

## 3. QA & Demo Plan

### QA (текущая неделя):
- **Pardo:** user-centric QA, UX issues, content quality feedback
- **Maxim:** E2E automated tests на personal avatars (5 аватаров, 3 дня)
- **Критерий стабильности:** 0 auth failures, 0 unexpected freezes за 72 часа

### Demo Plan (следующая неделя):
- **Формат:** Показать desktop admin panel с реальным success story одного аватара
- **Pitch structure:**
  1. "Look what our system did for this avatar in 2 weeks" (karma growth, engagement)
  2. "Here's the daily EPG — AI picks WHERE and WHEN"
  3. "Here's what auto-posting does" (timeline of automated comments)
  4. "Coming soon: mobile app for your team" (mockups)
- **Upsell:** Mobile app + full automation as "next phase" to secure design partners
- **Target:** 2-3 demo calls next week

---

## 4. Confirmed Next Steps

### Maxim (Tech):
- [ ] Finalize auto-posting E2E: 5 avatars, 3 days, zero-intervention
- [ ] Fix remaining bugs from Pardo's QA list
- [ ] Add Tzvi's Reddit user to platform, enable manual posting
- [ ] Email Tzvi: Reddit app/API requirements for white-label + LinkedIn tool link
- [ ] After auto-posting stable: build Mobile REST API (5-7 endpoints, 3-5 days)
- [ ] After API ready: begin Flutter mobile app screens

### Tzvi (Business):
- [ ] Reddit research for white-label application
- [ ] Onboard personal avatar to platform for demo prep
- [ ] Begin customer demos next week (pitch new roadmap)
- [ ] Contact Spotlight founder re: API partnership for GEO/AIO
- [ ] Email meeting recording to Maxim

---

## 5. Technical Assessment: What's Real vs. What Meeting Assumed

| Topic | Meeting Assumption | Actual Code State |
|-------|-------------------|-------------------|
| Auto-posting | "13 bugs fixed, in final testing" | Core works (1 verified post), but no proxy yet, no admin UI |
| Mobile app | "Begin immediately after auto-posting" | Backend EPG ready, but NO mobile API exists yet |
| Reddit API risk | "Single point of failure" | True for scraping key; posting already uses per-avatar auth |
| White-label | "Pivot needed" | Architecture already supports it (per-avatar credentials) |
| GEO/AIO | "Integrate Spotlight via API" | Spec exists, no code yet. Correct to defer. |
| EPG | Not discussed explicitly | Fully working, runs 2x/day, phase-aware |
| Learning loop | Not discussed | Working (edit capture → patterns → few-shot injection) |
| Scoring | Not discussed | Batch mode, pre-filter, ~$0.006/client/day |

---

## 6. Risk Register (updated post-meeting)

| Risk | Severity | Mitigation | Status |
|------|----------|------------|--------|
| Reddit revokes scraping key | High | White-label: each avatar scrapes own data | Architecture ready, not yet implemented for scraping |
| Reddit blocks password auth | Medium | OAuth adapter ready, pending approval | Deployed, waiting |
| Proxy IP detection | Medium | Residential proxies (ProxyJet) | Not purchased yet |
| Mobile app delay | Medium | Desktop copy/paste as interim | Works today via admin panel |
| Demo fails live | Low | Pre-record backup video | Record this week |
| Tzvi's avatar gets banned during demo prep | Low | Use r/test first, then low-risk subs | Standard Phase 1 warming |

---

## 7. Budget Impact of Decisions

| Decision | Monthly Cost Impact |
|----------|-------------------|
| Current state (no change) | ~$50 (DO + LLM for 1-2 test clients) |
| Add 5 proxies for demo avatars | +$12.50 ($2.50/avatar) |
| Spotlight API (GEO/AIO) | +$200 (deferred) |
| Mobile app development | $0 (internal) |
| Scale to 10 clients | ~$378 total (see load_dynamics steering) |

---

## Summary for Tzvi Letter

**Ключевые решения встречи:**
1. White-label model — confirmed (tech уже поддерживает per-avatar auth)
2. Auto-posting — must be stable this week for demos
3. Mobile app — #1 differentiator, начинаем сразу после стабилизации posting
4. GEO/AIO — buy, not build (Spotlight API, $200/mo)
5. Demos — next week, using personal avatar success story

**Главный инсайт:** Intelligence Platform (monitoring, scoring, EPG, strategies, generation) — уже работает. Это наш продукт. Auto-posting и mobile app — это delivery mechanism, не core value. Мы продаём intelligence, не кнопку "publish".
