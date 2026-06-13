# Discovery — Priority Plan

**Date:** June 8, 2026  
**Context:** Tzvi ждёт demo/onboarding deliverable. Max строит Discovery как часть AI-агента для Reddit intelligence.

---

## Два трека, одна система

| Track | Owner | Deliverable | Timeline |
|-------|-------|-------------|----------|
| **Tzvi Track** | Sales/Demo | "Day 1 Report" + client onboarding via Discovery | This week |
| **Platform Track** | Engineering | Persistent workflow + Avatar onboarding + Ongoing Discovery | 2-4 weeks |

Они не конфликтуют — Tzvi Track это P0 subset из Platform Track. Делаем Tzvi's deliverable FIRST, потом расширяем в полный workflow.

---

## Sprint 1: Tzvi's Deliverable (3-4 дня)

**Цель:** Tzvi может на Zoom-демо запустить Discovery для бренда проспекта и через 5 минут показать Visibility Report.

| # | Task | Effort | Why Tzvi Needs This |
|---|------|--------|---------------------|
| 1 | **Results Page** (`/admin/discovery/{id}/results`) — stable URL с полными данными сессии | 4h | "Вот ссылка на ваш отчёт" — шарить проспекту |
| 2 | **Export HTML** — branded one-page report (printable/PDF) | 4h | Проспект пересылает CMO |
| 3 | **Demo seed session** — pre-built session с XM Cyber данными (не требует Reddit API) | 2h | Мгновенный демо без ожидания |
| 4 | **"Create Strategy" button** на results page | 2h | После демо → "а теперь мы настраиваем вашу стратегию" |
| 5 | **Session resume fix** — state machine вместо эвристики | 3h | Не терять прогресс если проспект ушёл |

**Итого: ~15 часов = 2 рабочих дня**

**Что Цви получает:**
- URL для демо: `https://gorampit.com/admin/discovery` → New Session → brief → 5 min → Results Page
- Export кнопка → branded HTML (открыть в браузере → Print → Save as PDF)
- Demo mode: pre-loaded session без Reddit API (для быстрых показов)
- Handoff: "Results → Create Strategy" → клиент видит что дальше

---

## Sprint 2: Persist + Intelligence (1 неделя)

**Цель:** Discovery становится законченным persistent workflow — data layer для AI-агента.

| # | Task | Effort | What It Enables |
|---|------|--------|-----------------|
| 6 | **Reddit Research Cache** — Redis layer перед PRAW, TTL 24-72h | 4h | Не тратить rate limit на повторные запросы |
| 7 | **Cost/Usage panel** — AI calls, Reddit calls, cache hits в UI | 3h | Operator awareness + audit |
| 8 | **Regenerate Report from Saved Data** (no Reddit rerun) | 2h | Переделать отчёт без потери времени |
| 9 | **Session state machine** — explicit statuses (draft → entities_confirmed → research_complete → report_generated → handed_off) | 4h | Clean resume, audit, progress |
| 10 | **Reddit research persistence** — each PRAW call logged (query, subreddit, cached/fresh, count, timestamp) | 4h | Audit trail + cache-first prerequisite |
| 11 | **Strategy Handoff enrichment** — передать в Strategy: subreddits + keywords + competitors + risks + opportunities (structured) | 4h | Strategy не из пустого места |

**Итого: ~21 час = 3 рабочих дня**

---

## Sprint 3: Avatar Onboarding (1 неделя)

**Цель:** Avatar Discovery Profile — аватар наследует от стратегии + сравнивается с Reddit реальностью.

| # | Task | Effort | What It Enables |
|---|------|--------|-----------------|
| 12 | **AvatarDiscoveryProfile model** — niche, declared expertise, assigned communities, trust baseline | 4h | Структурированный avatar onboarding |
| 13 | **"Configure Avatar" from Strategy** — UI flow: Strategy → select reddit account → scan → create profile | 6h | Avatar не из пустоты |
| 14 | **Reddit history scan** — PRAW user history → actual subreddits, topics, karma distribution | 4h | Observed data |
| 15 | **Declared vs Observed comparison** — mismatch score, warnings | 4h | "This account posts in r/gaming, not r/cybersecurity" |
| 16 | **Niche fit score** — cosine similarity between declared niche and observed activity | 4h | Go/no-go для avatar assignment |
| 17 | **Avatar onboarding UI** — tab/page on avatar detail: Discovery Profile, declared vs observed, niche fit | 6h | Operator sees the full picture |

**Итого: ~28 часов = 4 рабочих дня**

---

## Sprint 4: Ongoing Discovery (2 недели)

**Цель:** Continuous intelligence — Delta detection, auto-strategy updates, EPG feed.

| # | Task | Effort |
|---|------|--------|
| 18 | **OngoingDiscoveryRun model** — scheduled run, scope (client/avatar/global), delta output | 4h |
| 19 | **DiscoveryDelta model** — what changed: new threads, rule changes, competitor mentions, engagement shifts | 4h |
| 20 | **Weekly environment scan** (Celery Beat, Sunday 04:00) — per-client subreddit health check | 8h |
| 21 | **Delta → Strategy confidence update** — auto-adjust if environment shifted | 4h |
| 22 | **Delta → EPG priority adjustments** — auto-reprioritize subreddits/topics based on delta | 6h |
| 23 | **Operator alerts** — "r/cybersecurity removed 3 posts this week", "new competitor active" | 4h |
| 24 | **Source of Truth rule** — Recommended vs Reported vs Observed vs Outcome (4 layers) | 6h |
| 25 | **Monthly Discovery report** — auto-generated per client, delta summary | 4h |

**Итого: ~40 часов = 2 недели**

---

## What Tzvi Can Say TODAY (After Sprint 1)

> "Let me show you what Reddit looks like for your brand. Give me 2 minutes."
> 
> *Runs Discovery session on Zoom*
> 
> "Here — 8 subreddits where your buyers discuss attack surface management. 200+ posts per month. Average 15 upvotes. Your competitors are already there — Brand X mentioned 12 times last week."
> 
> "I'll send you this report. When you're ready, we set up avatars and start building authority in these communities."

---

## Architecture Principle (For AI Agent Vision)

Discovery is not a wizard. It's a **knowledge base builder** that:

```
Observes Reddit → Structures understanding → Persists as facts
                                                      ↓
                          Strategy uses facts → EPG uses strategy
                                                      ↓
                          Avatars act → Reddit reacts → Discovery observes again
```

The AI agent role:
- **Entity extraction** — AI reads brief, outputs structured entities
- **Hypothesis formation** — AI generates testable claims about Reddit
- **Report generation** — AI summarizes findings into narrative
- **Niche comparison** — AI compares declared vs observed
- **Delta detection** — AI identifies what changed since last scan

Everything else is **deterministic logic** — cache lookups, PRAW calls, score calculations, state transitions. AI is the brain, not the nervous system.

---

## Definition of "Done" Per Sprint

**Sprint 1 done when:** Tzvi can demo Discovery on Zoom, send results link to prospect, export report.

**Sprint 2 done when:** Operator can resume any session, see full audit trail, regenerate report without rerunning research. Cache prevents redundant Reddit calls.

**Sprint 3 done when:** New avatar created from Strategy data. Reddit history compared with declared niche. Mismatch flagged before avatar enters pipeline.

**Sprint 4 done when:** Weekly delta runs automatically. Strategy confidence updates. EPG priorities shift based on environment changes. Monthly report generated.
