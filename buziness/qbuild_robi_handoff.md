# Q-BUILD Robi — MVP Architecture & Implementation Handoff

## Для кого этот документ

Ты — разработчик (AI-agent или человек), который будет реализовывать MVP Robi.
Этот документ даёт тебе всё: контекст, архитектуру, data model, pipeline, оценки.

---

## Контекст: откуда взялась эта архитектура

### RAMP — предыдущий проект (референс)

Перед Robi я (Макс) построил RAMP — Reddit Marketing SaaS Platform. Полная статистика:

| Метрика | Значение |
|---------|----------|
| Общее время проекта | **~500 человеко-часов** (мои) |
| Из них архитектура и планирование | **~80–100 часов** (18-20%) |
| Эквивалент без AI-ассистента | ~2,500–3,000 часов |
| Коэффициент AI-усиления | **5–6×** (на коде), **2×** (на архитектуре) |
| Результат | 65+ моделей, 120+ сервисов, 35 route-файлов, 31 Celery task |
| Стек | FastAPI + PostgreSQL + Redis + Celery + LiteLLM + HTMX |
| Deploy | DigitalOcean, Docker Compose, production с клиентами |

### Что я вынес из RAMP (и заложил в Robi)

| Урок из RAMP | Как применено в Robi |
|-------------|---------------------|
| Steering files (17 файлов) = архитектурная память проекта | Этот документ — полный контекст для агента |
| State machines формализовать сразу (6 в RAMP) | Event state machine (pending→approved/rejected/expired) |
| Append-only для audit trail (Journal = RAMP's PostingEvent + AuditLog) | journal_entry: INSERT only, DB role enforced |
| AI calls через единый сервис + logging | Adapter pattern + usage tracking с первого дня |
| Kill switches и feature flags | Feature flags на Night Analysis, chat feedback |
| owner_id на каждой таблице (RAMP: client_id + query_scope) | owner_id + RLS-ready с первого коммита |
| Webhook idempotency (RAMP: wa_message_id dedup) | UNIQUE(wa_message_id) на messages |
| Celery Beat отдельно от Workers (RAMP: beat_app.py) | Beat schedule отдельный файл |
| Confidence thresholds калиброваны на реальных данных | 0.4/0.7 gate + prompt tuning sprint |

### Трудоёмкость архитектуры Robi

| Этап | Часы Макса | Что сделано |
|------|-----------|-------------|
| Анализ домена (8 встреч со Славой) | ~20 | Понимание строительной коммуникации |
| Архитектурные решения | ~25 | Стек, data model, pipeline, AI strategy |
| Оценка и декомпозиция | ~10 | Компоненты, часы, milestones |
| Документация (этот документ + презентация) | ~15 | Формализация для передачи |
| **Итого архитектура Robi** | **~70 часов** | — |

**Эти 70 часов сэкономят ~100+ часов переделок**, потому что:
- Data model не придётся менять при переходе к multi-tenant
- Pipeline не придётся переписывать при смене LLM провайдера
- State machine покрывает все edge cases (expiration, escalation)
- Append-only journal не даст потерять доказательства

---

## Что такое Robi (в одном абзаце)

**AI Project Memory Agent для строительных проектов в Израиле.**

WhatsApp сообщения от участников стройки (подрядчики, клиент, дизайнер) → AI находит важные события (изменения, риски, завершения, решения) → Менеджер подтверждает в Cockpit → Append-only Evidence Journal.

**Ключевой принцип: Zero Autonomy.** Robi НИКОГДА не принимает решений сам. Только предлагает, человек подтверждает.

---

## Tech Stack

| Layer | Technology | Обоснование |
|-------|-----------|-------------|
| Backend | FastAPI (Python 3.11+) | Async, type hints, проверено на RAMP |
| Database | PostgreSQL 16 | JSONB, append-only constraints, RLS-ready |
| Queue/Cache | Redis | Message queue + rate limiting |
| Tasks | Celery | Night analysis, expiration checks |
| AI/LLM | OpenAI (GPT-4o-mini + GPT-4o) | Single provider MVP |
| STT | OpenAI Whisper API | Иврит/арабский/русский |
| Frontend | React/Next.js | Mobile-first Cockpit |
| Auth | JWT + Phone OTP | Строители не используют email |
| Deploy | Docker Compose → VPS | Простая MVP инфра |
| Messaging | WhatsApp Business API (Meta Cloud) | Прямое подключение, без BSP |
| Dev sandbox | Telegram Bot API | Пока WhatsApp verification (2-4 нед) |

---

## Data Model (5 таблиц MVP)

```sql
-- Принцип: owner_id на каждой таблице с первого дня (multi-tenant ready)
-- journal_entry: INSERT only, no UPDATE/DELETE (enforced DB role)

CREATE TABLE project (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL,
    name TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'active',  -- active | paused | closed | archived
    metadata JSONB DEFAULT '{}',  -- budget, address, stages
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE participant (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES project(id),
    owner_id UUID NOT NULL,
    phone TEXT NOT NULL,
    display_name TEXT,
    role TEXT NOT NULL,  -- architect | contractor | client | designer | supplier
    language TEXT DEFAULT 'he',  -- he | ar | ru | en
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE message (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES project(id),
    owner_id UUID NOT NULL,
    sender_id UUID REFERENCES participant(id),
    source TEXT NOT NULL,  -- whatsapp | telegram | manual
    wa_message_id TEXT UNIQUE,  -- idempotency: Meta retries won't create duplicates
    content_type TEXT NOT NULL,  -- text | voice | image | document | location
    text_content TEXT,  -- original text or STT transcript
    raw_audio_url TEXT,  -- S3 URL for voice evidence
    image_url TEXT,
    metadata JSONB DEFAULT '{}',  -- forwarded_from, reply_to, group_id
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ
);

CREATE TABLE event (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES project(id),
    owner_id UUID NOT NULL,
    message_id UUID NOT NULL REFERENCES message(id),
    type TEXT NOT NULL,  -- task_completed | change_request | risk_problem | decision
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | expired
    exact_quote TEXT NOT NULL,  -- mandatory: нет цитаты = нет события
    confidence FLOAT NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    ai_reasoning TEXT,
    proposed_action TEXT,
    cost_impact NUMERIC,  -- extracted ₪ if mentioned
    time_impact TEXT,  -- extracted delay if mentioned
    expires_at TIMESTAMPTZ NOT NULL,  -- 48h from detection
    decided_at TIMESTAMPTZ,
    decided_by UUID REFERENCES participant(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE journal_entry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES project(id),
    owner_id UUID NOT NULL,
    event_id UUID NOT NULL REFERENCES event(id),
    actor_id UUID NOT NULL REFERENCES participant(id),
    final_decision TEXT NOT NULL,  -- approved | approved_with_edit
    manager_note TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
    -- NO updated_at column. This table is APPEND-ONLY.
);
```

**DB roles (enforce append-only):**
```sql
CREATE ROLE robi_app;      -- SELECT, INSERT, UPDATE on all except journal_entry
CREATE ROLE robi_journal;  -- SELECT, INSERT on journal_entry (NO UPDATE, NO DELETE)
CREATE ROLE robi_readonly; -- SELECT everywhere
```

---

## Event State Machine

```
[Message arrives] → AI detection
        │
        ▼
    ┌─────────┐
    │ PENDING │ (expires_at = created_at + 48h)
    └────┬────┘
         │
    ┌────┼────────────────┐
    │    │                 │
    ▼    ▼                 ▼
APPROVED  REJECTED     EXPIRED (auto, Celery task)
    │                      │
    ▼                      ▼
JOURNAL_ENTRY         Escalation notification
(append-only)         (remind manager)
```

**Celery Beat schedule:**
- Every 5 min: check expired events → status='expired' → notify manager
- Every night (02:00): Night Deep Analysis → new event candidates
- Every hour: health check + LLM usage aggregation

---

## Message Processing Pipeline

```
WhatsApp/Telegram Message
    │
    ▼
[Webhook] ── verify Meta signature ── dedup by wa_message_id
    │
    ▼
[Store] ── INSERT message (always, even noise)
    │
    ▼
[Media] ── voice? → Whisper STT → update text_content
        ── image? → store URL (no OCR in MVP)
    │
    ▼
[Fast Filter] ── < 5 chars? → skip
              ── emoji/sticker only? → skip
              ── keyword hit? (שינוי, סיימתי, בעיה, תוספת) → force AI
              ── else → AI classification
    │
    ▼ (~30% of messages)
[AI: GPT-4o-mini] ── structured output:
    │                  { type, exact_quote, confidence, proposed_action }
    │
    ▼
[Confidence Gate]
    ── < 0.4 → discard (log for review)
    ── 0.4–0.7 → create event, no chat feedback
    ── > 0.7 → create event + send "🔍 Noticed: ..." to group
    │
    ▼
[Create Event] ── INSERT (status=pending, expires_at=+48h)
    │
    ▼
[Notify Manager] ── push to Cockpit + WhatsApp template
```

---

## AI Prompts Architecture

### Fast Mode (per message, real-time)

```
Model: GPT-4o-mini
Latency: < 2 sec
Cost: ~$0.001/msg
```

**System prompt (skeleton):**
```
You are Robi, a construction project observer.
You analyze messages from project participants.
Your job: detect events that require manager attention.

4 event types:
- task_completed: participant claims work is done
- change_request: scope/budget/timeline change proposed
- risk_problem: blocker, delay, problem reported  
- decision: choice made, agreement reached

Rules:
- ALWAYS include exact_quote from original message
- If no clear event → respond with {"type": null}
- Confidence 0.0-1.0 (be conservative, 0.7+ = very clear)
- Languages: Hebrew, Arabic, Russian, English (detect automatically)
- Voice transcripts may have STT errors — be lenient with spelling

Output JSON only:
{"type": "...", "exact_quote": "...", "confidence": 0.0, 
 "proposed_action": "...", "cost_impact": null, "time_impact": null}
```

### Deep Mode (nightly batch)

```
Model: GPT-4o
Latency: 10-20 sec (batch, async)
Cost: ~$0.03/analysis
Runs: 02:00 nightly via Celery Beat
```

**Task:** Analyze all day's messages in context. Find:
- Events that Fast mode missed (lower confidence signals)
- Contradictions between participants
- Implicit commitments ("I'll do it tomorrow")
- Escalation candidates (unresolved issues)

**Output:** Night Report → Cockpit morning view for manager.

---

## LLM Budget & Tracking

| Metric | Target |
|--------|--------|
| Monthly budget hard cap | $150 |
| Alert at | $100 (70%) |
| Cost per message (fast) | ~$0.001 |
| Cost per night analysis | ~$0.03 |
| Cost per STT minute | ~$0.006 |

**Every LLM call logged:**
```python
log_ai_usage(
    project_id=...,
    operation="fast_classify" | "night_analysis" | "stt",
    model="gpt-4o-mini",
    input_tokens=...,
    output_tokens=...,
    cost_usd=...,
    latency_ms=...
)
```

Lesson from RAMP: without per-call logging, you discover budget overruns after the fact. Track from day 1.

---

## API Endpoints (v1)

```
/api/v1/
├── auth/
│   ├── POST /send-otp           # phone → OTP via SMS/WhatsApp
│   └── POST /verify-otp         # OTP → JWT
├── projects/
│   ├── GET  /                    # list (paginated)
│   ├── POST /                    # create
│   ├── GET  /{id}               # detail + stats
│   └── PATCH /{id}              # update metadata
├── participants/
│   ├── GET  /projects/{id}/participants
│   ├── POST /projects/{id}/participants
│   └── PATCH /participants/{id}
├── events/
│   ├── GET  /inbox               # pending events (Cockpit main screen)
│   ├── GET  /projects/{id}/events
│   ├── POST /{id}/approve        # → journal_entry created
│   ├── POST /{id}/reject
│   └── POST /{id}/edit-approve   # approve with modification
├── journal/
│   ├── GET  /projects/{id}/journal  # history (paginated)
│   └── GET  /projects/{id}/journal/export
├── webhooks/
│   ├── POST /whatsapp            # Meta Cloud API (signature verified!)
│   └── POST /telegram            # dev sandbox
├── internal/
│   ├── POST /night-analysis/trigger
│   └── GET  /health
```

All list endpoints: `?page=1&per_page=20&sort=-created_at&filter[status]=pending`

---

## Cockpit (Frontend)

**Two screens. Mobile-first. Manager opens on construction site.**

### Screen 1: Inbox

What needs decisions NOW.

- Card per pending event
- Shows: event type badge, exact_quote, confidence (green/yellow), timestamp
- Source message expandable (tap to see full context)
- Actions: [Approve] [Reject] [Edit & Approve]
- Sort: by confidence DESC, then by created_at DESC
- Filter: by project, by type, by date range

### Screen 2: History (Journal)

What's already been decided.

- Timeline of journal entries
- Shows: who confirmed, when, original quote, manager's note
- Filter: by type, by participant, by date
- Export: PDF summary for project closure

### Design principles:
- One-hand operable (big tap targets, bottom navigation)
- Works on 4G (light payloads, lazy load)
- Hebrew RTL + Arabic RTL + Russian LTR (layout adapts)
- Offline indicator (queue approvals when back online — nice-to-have)

---

## WhatsApp Integration Details

### Prerequisites (MUST start immediately, 2-4 week lead time):
1. Meta Business Account (create + verify with company docs)
2. Dedicated phone number for Robi
3. HTTPS webhook endpoint with valid SSL
4. Privacy Policy URL on company website

### Architecture:
- Robi creates project group via WhatsApp Business API (max 8 participants)
- Robi is member from creation (sees all messages)
- Template messages for: invitations, event notifications, daily summaries
- 24-hour window for free-form messages (event feedback in chat)

### Limitation >8 participants:
- Multiple groups by role (contractors group, client group)
- Or: "extra" participants communicate 1:1 with Robi
- Cockpit aggregates across all project channels

### Telegram sandbox:
- Mirror the webhook interface (same payload structure internally)
- Use for development until WhatsApp verification completes
- Adapter pattern: `MessageSource` interface → WhatsAppAdapter | TelegramAdapter

---

## Project Structure (recommended)

```
robi/
├── app/
│   ├── main.py                 # FastAPI app
│   ├── config.py               # pydantic-settings
│   ├── database.py             # SQLAlchemy engine + session
│   ├── models/                 # SQLAlchemy models (5 tables)
│   │   ├── project.py
│   │   ├── participant.py
│   │   ├── message.py
│   │   ├── event.py
│   │   └── journal_entry.py
│   ├── schemas/                # Pydantic request/response
│   ├── routes/
│   │   ├── auth.py
│   │   ├── projects.py
│   │   ├── events.py
│   │   ├── journal.py
│   │   └── webhooks.py
│   ├── services/
│   │   ├── ai.py               # LLM wrapper + logging (SINGLE ENTRY POINT)
│   │   ├── stt.py              # Whisper transcription
│   │   ├── pipeline.py         # Message processing pipeline
│   │   ├── event_detector.py   # AI classification logic
│   │   ├── approval.py         # State machine transitions
│   │   └── notifications.py    # WhatsApp templates + push
│   ├── adapters/
│   │   ├── whatsapp.py         # Meta Cloud API client
│   │   └── telegram.py         # Telegram Bot API client
│   ├── tasks/
│   │   ├── worker.py           # Celery config
│   │   ├── night_analysis.py   # Deep mode batch
│   │   └── expiration.py       # Event timeout checker
│   └── middleware/
│       ├── auth.py             # JWT verification
│       └── logging.py          # Structured JSON logs
├── alembic/                    # Migrations from commit #1
├── tests/
├── frontend/                   # Next.js Cockpit
├── docker-compose.yml
├── Dockerfile
├── .env.example
└── Makefile
```

---

## Implementation Estimate

| Component | Hours | Priority | Notes |
|-----------|-------|----------|-------|
| **Confirmation Loop (state machine)** | 40–60 | ⭐ CORE | Ядро продукта. 45% бюджета. |
| **AI Event Detection (4 типа + prompts)** | 25–40 | ⭐ CORE | Structured output, confidence, exact_quote |
| Architecture & Data Model | 15–20 | Foundation | 5 таблиц, migrations, seed |
| WhatsApp Integration + STT | 25–40 | Foundation | Business API, webhook, STT |
| Backend (FastAPI + DB + Journal) | 25–45 | Foundation | REST API, append-only |
| Web Cockpit (Inbox + History) | 25–35 | UI | React/Next.js, mobile-first |
| Night Analysis Cycle | 15–25 | Feature | Deep mode, report |
| Auth + Infra + Testing | 40–55 | Platform | JWT, Docker, CI/CD, E2E |
| **TOTAL** | **210–320h** | — | Mean: ~265h |
| **With 20% buffer** | **~320h** | — | — |

---

## Milestones

| Week | Milestone | Definition of Done |
|------|-----------|-------------------|
| 4 | First E2E cycle | 1 message → AI → event in Inbox → approve → journal |
| 8 | Cockpit working | Full Inbox + History, state machine complete, Night Analysis |
| 10-12 | **MVP Ready** | 10 messages correctly processed without intervention on real project |

---

## Architecture Decisions Already Made (don't revisit)

| Decision | Rationale |
|----------|-----------|
| WhatsApp Business API direct (no BSP) | Full control, no middleman costs |
| Single LLM provider (OpenAI) for MVP | Simplicity. Multi-provider after MVP. |
| Fast + Deep two-mode AI | Real-time detection + context-aware nightly review |
| Zero Autonomy (human confirms everything) | Trust building. Autonomy earned later via track record. |
| Append-only journal (DB role enforced) | Legal evidence. Cannot be disputed. |
| owner_id on every table | Multi-tenant ready without schema migration |
| Telegram as dev sandbox | WhatsApp verification takes 2-4 weeks |
| Phone OTP auth (no email) | Target users are construction workers |
| 48h expiration on events | Force timely decisions, prevent stale inbox |
| 4 event types only in MVP | Precision > coverage. Expand after calibration. |

---

## What NOT to Build (MVP scope out)

- ❌ Self-service onboarding (manual in MVP)
- ❌ Multi-tenant isolation (1 tenant, but schema ready)
- ❌ BIM / OCR / photo analysis
- ❌ Automatic cost estimation / ERP
- ❌ RAG / vector search
- ❌ Native mobile app (responsive web)
- ❌ Autonomous AI decisions
- ❌ Complex analytics / dashboards
- ❌ Telegram as production channel
- ❌ Multiple LLM providers

---

## Production-Ready Foundations (build into MVP from day 1)

These cost ~0 extra hours but save weeks of refactoring later:

1. **`owner_id` on every table** — multi-tenant = add RLS policy, not migrate schema
2. **API versioning `/api/v1/`** — can evolve without breaking clients
3. **Pagination on all lists** — won't break at 1000 records
4. **Webhook signature verification** — Meta signs every request, verify it
5. **Structured JSON logging** — production monitoring = connect sink, not rewrite
6. **Health endpoint** — `/health` checks PG, Redis, Celery
7. **LLM usage tracking** — every call logged (model, tokens, cost, latency)
8. **Adapter pattern for externals** — swap LLM/WhatsApp/STT = change one file
9. **Feature flags** — toggle Night Analysis, chat feedback without redeploy
10. **Idempotency on webhooks** — `UNIQUE(wa_message_id)` prevents duplicate processing
11. **Alembic migrations from commit #1** — every schema change tracked
12. **Seed data for dev** — new developer up in 30 minutes

---

## Key Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| WhatsApp verification delayed (>4 weeks) | Can't test real flow | Telegram sandbox mirrors full pipeline |
| Hebrew/Arabic STT quality low | Missed events from voice | Confidence gate + raw audio as evidence |
| LLM hallucinated events (false positives) | Manager trust erosion | exact_quote mandatory + confidence visible |
| Manager ignores Cockpit (no adoption) | Events expire, no value | 48h escalation + WhatsApp reminders |
| Meta API rate limits | Message loss | Queue + retry with exponential backoff |
| Cost overrun on LLM | Budget blown | Hard cap $150/mo + per-call tracking + alerts at 70% |

---

## Summary for the Implementing Agent

You are building a **5-table system with one state machine and one AI pipeline.** It is intentionally simple.

The complexity is in the **prompt calibration** (getting Hebrew construction slang right) and the **UX** (making a construction manager actually open the Cockpit every morning).

Don't over-engineer. The architecture is production-ready by design — simple implementation on solid foundations.

**Start with:** Telegram webhook → message storage → AI event detection → hardcoded Inbox page.
**Then:** State machine → approval flow → journal → WhatsApp integration → Night Analysis.

Definition of Done: **10 consecutive real messages processed correctly without manual intervention.**
