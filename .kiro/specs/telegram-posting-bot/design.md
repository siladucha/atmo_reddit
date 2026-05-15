# Design Document — Telegram Posting Bot

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Telegram Bot (aiogram 3.x)                   │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │  /start  │  │  /queue  │  │ Callbacks│  │  /stats      │   │
│  │  handler │  │  handler │  │ (Posted/ │  │  handler     │   │
│  │          │  │          │  │  Skip)   │  │              │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘   │
│       │              │              │               │            │
│       └──────────────┴──────────────┴───────────────┘            │
│                              │                                    │
│                    ┌─────────┴─────────┐                         │
│                    │  Bot Service      │                         │
│                    │  (internal calls) │                         │
│                    └─────────┬─────────┘                         │
└──────────────────────────────┼───────────────────────────────────┘
                               │ Direct DB / Service calls
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Existing FastAPI Backend                       │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Bot runs IN-PROCESS (same FastAPI app)                    │ │
│  │  OR as separate Celery-like process sharing DB session     │ │
│  │                                                            │ │
│  │  Services used directly:                                   │ │
│  │  - avatar_assignments (query)                              │ │
│  │  - comment_drafts (query + update)                         │ │
│  │  - posting_events (insert)                                 │ │
│  │  - audit_log (insert)                                      │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │ avatar_      │  │ comment_     │  │ posting_events     │    │
│  │ assignments  │  │ drafts       │  │ (new table)        │    │
│  │ (new table)  │  │ (existing)   │  │                    │    │
│  └──────────────┘  └──────────────┘  └────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

## Deployment Architecture

### Option A: In-Process (Recommended for MVP)

Bot runs as part of the FastAPI app using webhook mode:

```
FastAPI app
├── /api/* routes (existing)
├── /webhook/telegram (new — receives Telegram updates)
└── Bot dispatcher (aiogram) processes updates
```

**Pros:** Single process, shared DB session, no extra infra.
**Cons:** Bot restarts with app. Acceptable for MVP.

### Option B: Separate Process (for scale)

Bot runs as a separate Docker container:

```
docker-compose.yml:
  app:        FastAPI (web)
  worker:     Celery (tasks)
  bot:        Telegram bot (polling or webhook)
```

**When to switch:** If bot message handling creates latency on web requests (unlikely at <100 owners).

---

## Database Changes

### New Table: `avatar_assignments`

```sql
CREATE TABLE avatar_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,  -- optional, for web-linked users
    telegram_user_id BIGINT,                              -- Telegram user ID (primary auth)
    telegram_username VARCHAR(255),                       -- @username (for admin display)
    avatar_id UUID NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    assigned_by UUID REFERENCES users(id),
    is_active BOOLEAN NOT NULL DEFAULT true,
    UNIQUE(telegram_user_id, avatar_id)
);

CREATE INDEX idx_avatar_assignments_telegram ON avatar_assignments(telegram_user_id) WHERE is_active = true;
CREATE INDEX idx_avatar_assignments_avatar ON avatar_assignments(avatar_id) WHERE is_active = true;
```

**Key difference from Flutter spec:** `telegram_user_id BIGINT` is the primary auth mechanism. No JWT needed for bot — Telegram guarantees user identity.

### New Table: `posting_events`

```sql
CREATE TABLE posting_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id UUID NOT NULL,
    draft_type VARCHAR(20) NOT NULL,        -- 'comment' | 'post'
    telegram_user_id BIGINT NOT NULL,
    avatar_id UUID NOT NULL REFERENCES avatars(id),
    action VARCHAR(50) NOT NULL,            -- 'view_detail' | 'confirm_posted' | 'skip' | 'reminder_sent'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_posting_events_telegram ON posting_events(telegram_user_id, created_at DESC);
CREATE INDEX idx_posting_events_draft ON posting_events(draft_id);
```

### Modifications to Existing Tables

**`comment_drafts`** — add columns:
```sql
ALTER TABLE comment_drafts ADD COLUMN posted_by_telegram BIGINT;
ALTER TABLE comment_drafts ADD COLUMN posted_source VARCHAR(20) DEFAULT 'web';  -- 'web' | 'telegram_bot'
ALTER TABLE comment_drafts ADD COLUMN posting_speed_seconds INTEGER;
```

**`post_drafts`** — same:
```sql
ALTER TABLE post_drafts ADD COLUMN posted_by_telegram BIGINT;
ALTER TABLE post_drafts ADD COLUMN posted_source VARCHAR(20) DEFAULT 'web';
ALTER TABLE post_drafts ADD COLUMN posting_speed_seconds INTEGER;
```

### NOT needed (vs Flutter spec):
- ❌ `device_registrations` — Telegram handles push delivery
- ❌ `refresh_tokens` — no JWT for bot
- ❌ FCM tokens — Telegram is the push channel

---

## Bot Commands & Handlers

### Commands

| Command | Description | Handler |
|---------|-------------|---------|
| `/start` | Register / show status | `cmd_start` |
| `/queue` | Show pending drafts | `cmd_queue` |
| `/stats` | Posting statistics | `cmd_stats` |
| `/avatars` | List assigned avatars | `cmd_avatars` |
| `/help` | List commands | `cmd_help` |
| `/mute` | Mute notifications | `cmd_mute` |
| `/unmute` | Unmute notifications | `cmd_unmute` |

### Callback Queries (Inline Buttons)

| Callback Data | Action |
|---------------|--------|
| `open:{draft_id}` | Show draft detail message |
| `posted:{draft_id}` | Confirm posted → update DB |
| `skip:{draft_id}` | Skip draft → log event |
| `next:{offset}` | Next page in queue |
| `prev:{offset}` | Previous page in queue |

---

## Message Templates

### Queue Message

```
📋 Queue: 7 pending

👤 StopAutomatic717 (4 pending)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. r/cybersecurity — "What's the best approach to..." (2h ago)
2. r/netsec — "Anyone tried the new..." (1h ago)
3. r/sysadmin — "Looking for recommendations..." (45m ago)
4. r/AskNetsec — "How do you handle..." (30m ago)

👤 Flaky_Finder_13 (3 pending)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. r/yoga — "Best morning routine..." (3h ago)
6. r/meditation — "Struggling with..." (2h ago)
7. r/flexibility — "Progress check..." (1h ago)

[📝 Open #1] [📝 Open #2] [📝 Open #3]
[Next → ]
```

### Draft Detail Message

```
👤 StopAutomatic717 → r/cybersecurity
📌 Thread: "What's the best approach to zero trust?"

💬 Comment:
───────────────────────────────
Honestly, the biggest mistake I see teams make is treating
zero trust as a product you buy rather than an architecture
you build. Start with identity — if you can't verify who's
accessing what, nothing else matters.

We shifted to microsegmentation last year and the visibility
alone was worth it. Happy to share more specifics if helpful.
───────────────────────────────

[🔗 Open Reddit]  [✅ Posted]  [⏭ Skip]
```

### Posted Confirmation

```
✅ Posted! (took 1m 23s)

Next in queue:
👤 StopAutomatic717 → r/netsec
"Anyone tried the new..."

[📝 Open] [📋 Full Queue]
```

### Notification (New Draft Approved)

```
🔔 New comment ready!

👤 Flaky_Finder_13 → r/yoga
"Best morning routine for flexibility"

[📝 Open] [📋 Queue (3 pending)]
```

### Batch Notification

```
🔔 5 new comments ready to post!

👤 StopAutomatic717: 3 new
👤 Flaky_Finder_13: 2 new

[📋 Open Queue]
```

---

## Notification Architecture

### Trigger Flow

```
[CommentDraft.status → 'approved']
        │
        ▼
[Review route (approve action)]
        │
        ▼
[notify_avatar_owner_telegram(avatar_id, draft)]
        │
        ├── Find owner: SELECT telegram_user_id FROM avatar_assignments WHERE avatar_id = X
        ├── Check mute: SELECT is_muted FROM owner preferences
        ├── Batch check: Redis INCR push_batch:{telegram_user_id}, TTL 5min
        │   └── If count > 5 → send batch message instead
        │
        ▼
[bot.send_message(telegram_user_id, notification_text, reply_markup=inline_keyboard)]
```

### Reminder (Stale Drafts)

Celery Beat task every 30 minutes:
```python
@celery_app.task
def remind_stale_approved_drafts():
    """Find approved drafts >4h old, notify owners."""
    stale = get_stale_approved_drafts(hours=4)
    for owner_id, drafts in group_by_owner(stale):
        if not is_muted(owner_id):
            bot.send_message(owner_id, f"⏰ {len(drafts)} comments waiting >4h")
```

---

## Tech Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Bot framework | aiogram 3.x | Async, modern, well-maintained, Python (same as backend) |
| Webhook server | FastAPI (shared) | No extra process, reuses existing app |
| State management | Stateless | All state in DB, bot fetches on each interaction |
| Notifications | Telegram API (sendMessage) | Free, reliable, no FCM needed |
| Batching | Redis (INCR + TTL) | Already have Redis, simple counter |
| Rate limiting | aiogram middleware | Built-in throttling |

### Why aiogram (not python-telegram-bot):

- Fully async (matches FastAPI's async nature)
- aiogram 3.x has clean router/handler architecture
- Better typing support
- Active development, good docs

---

## Integration with Existing Services

### Services the bot calls directly:

```python
# No HTTP API needed — bot is part of the same codebase

from app.database import get_session
from app.models import AvatarAssignment, CommentDraft, PostingEvent
from app.services.audit import log_audit_event

async def get_owner_queue(telegram_user_id: int) -> list[CommentDraft]:
    async with get_session() as db:
        assignments = await db.execute(
            select(AvatarAssignment.avatar_id)
            .where(AvatarAssignment.telegram_user_id == telegram_user_id)
            .where(AvatarAssignment.is_active == True)
        )
        avatar_ids = [a.avatar_id for a in assignments.scalars()]
        
        drafts = await db.execute(
            select(CommentDraft)
            .where(CommentDraft.avatar_id.in_(avatar_ids))
            .where(CommentDraft.status == 'approved')
            .order_by(CommentDraft.approved_at.asc())
        )
        return drafts.scalars().all()
```

### Notification hook in review flow:

```python
# In routes/review.py and routes/pages.py — after approve action:

from app.services.telegram_bot import notify_owner_new_draft

async def approve_draft(draft_id, db):
    draft.status = 'approved'
    draft.approved_at = datetime.now(tz=...)
    await db.commit()
    
    # Trigger Telegram notification (non-blocking)
    await notify_owner_new_draft(draft.avatar_id, draft)
```

---

## Comparison: Telegram Bot vs Flutter App

| Aspect | Flutter (original spec) | Telegram Bot |
|--------|------------------------|--------------|
| Dev time | 2 weeks (parallel tracks) | 2-3 days |
| App Store | Required (iOS $99/yr + review) | Not needed |
| Push notifications | FCM setup + certificates | Free (Telegram native) |
| Installation | Download from store | Click bot link |
| Updates | App store review cycle | Instant (redeploy) |
| Auth | JWT + refresh tokens + biometric | telegram_user_id (automatic) |
| Clipboard | Flutter Clipboard API | Long-press message to copy |
| Open Reddit | url_launcher package | URL inline button |
| Offline | 5-min cache + sync | Not needed (always online for Reddit anyway) |
| UX quality | Custom UI, animations | Telegram-native, functional |
| Maintenance | Flutter upgrades, store compliance | Minimal (Python, no store) |
| Cost | ~$8/mo (App Store) | $0 |

---

## Phased Delivery

### Phase 1: Core Bot (2-3 days)
- avatar_assignments table + migration
- Bot setup (aiogram, webhook on FastAPI)
- `/start`, `/queue`, `/help` commands
- Draft detail with inline buttons
- "Posted" + "Skip" callbacks
- posting_events logging

### Phase 2: Notifications (1 day)
- Hook into review approval flow
- Send Telegram message on new approved draft
- Batch logic (5+ in 5 min → single message)
- `/mute` / `/unmute` commands

### Phase 3: Stats & Admin (1 day)
- `/stats` command
- Admin posting-team page
- Avatar assignment UI in admin panel
- Stale draft reminders (Celery Beat)

### Total: 4-5 days (vs 2 weeks for Flutter)

---

## Security Model

| Concern | Solution |
|---------|----------|
| User identity | telegram_user_id (guaranteed by Telegram API, cannot be spoofed) |
| Data isolation | All queries filtered by telegram_user_id → avatar_assignments |
| Bot token security | Stored in .env, never in code |
| Rate limiting | aiogram ThrottlingMiddleware (30 req/min per user) |
| Data persistence | Stateless bot — no local storage of draft content |
| Audit trail | All actions logged with telegram_user_id + timestamp |
| Webhook security | Telegram webhook secret token validation |

---

## Future Enhancements (not MVP)

- Reddit OAuth verification (prove account ownership)
- Inline mode (share drafts to other chats — unlikely needed)
- Voice messages (owner records confirmation — proof of human)
- Multi-language support (bot messages in owner's language)
- Earnings calculator in /stats
- Gamification (streaks, leaderboard via /stats)
