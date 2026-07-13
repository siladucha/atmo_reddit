# Design Document — Telegram Draft Review Channel

## Overview

Extends the existing RAMP Telegram bot (ops alerts) with draft review capabilities. Users with review access receive Draft_Cards via Telegram and can Approve / Skip / Edit drafts from their phone. The Extension on executor's machine handles actual Reddit posting.

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Telegram    │────▶│  Webhook Route   │────▶│  Draft Review    │────▶│  Extension  │
│  (User)      │◀────│  /api/telegram/  │◀────│  Service         │     │  (Executor) │
│              │     │  webhook         │     │                  │     │             │
│  Approve ✅  │     └──────────────────┘     └──────────────────┘     └─────────────┘
│  Skip ❌     │                                       │                       │
│  Edit ✏️     │                                       ▼                       ▼
└──────────────┘                              ┌──────────────────┐     ┌─────────────┐
                                              │  CommentDraft    │     │  Reddit     │
                                              │  EPGSlot         │     │  (Posted)   │
                                              │  ExecutionTask   │     └─────────────┘
                                              └──────────────────┘
```

## Architecture

## Components and Interfaces

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         RAMP Backend (FastAPI)                        │
│                                                                      │
│  ┌─────────────────┐   ┌─────────────────┐   ┌──────────────────┐  │
│  │  telegram/       │   │  telegram/       │   │  telegram/        │  │
│  │  webhook.py      │   │  bot_service.py  │   │  callback_store.py│  │
│  │  (Route)         │   │  (Core Logic)    │   │  (Redis IDs)     │  │
│  └────────┬─────────┘   └────────┬─────────┘   └────────┬─────────┘  │
│           │                      │                       │            │
│           ▼                      ▼                       ▼            │
│  ┌─────────────────┐   ┌─────────────────┐   ┌──────────────────┐  │
│  │  telegram/       │   │  telegram/       │   │  Existing:       │  │
│  │  formatter.py    │   │  draft_review.py │   │  extension_api   │  │
│  │  (Draft Cards)   │   │  (Review Logic)  │   │  (Reused)        │  │
│  └──────────────────┘   └──────────────────┘   └──────────────────┘  │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Existing Infrastructure: Redis, PostgreSQL, Celery              │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

### New Files

| File | Purpose |
|------|---------|
| `app/services/telegram/__init__.py` | Package init |
| `app/services/telegram/bot_service.py` | Core bot logic: send messages, handle callbacks, register webhook |
| `app/services/telegram/draft_review.py` | Draft review operations: notify, approve, skip, edit (calls extension_api logic) |
| `app/services/telegram/callback_store.py` | Redis-based Callback_ID mapping (create, resolve, expire) |
| `app/services/telegram/formatter.py` | Draft_Card formatting (Markdown, inline keyboards, truncation) |
| `app/routes/telegram_webhook.py` | FastAPI route: `POST /api/telegram/webhook` — receives Telegram updates |

### Modified Files

| File | Change |
|------|--------|
| `app/services/epg_executor.py` | Hook `_notify_drafts_pending()` to also call Telegram notification |
| `app/main.py` | Include `telegram_webhook` router |
| `nginx/nginx.conf` | Add `location = /api/telegram/webhook` |
| `app/middleware/auth.py` | Add `/api/telegram/webhook` to public routes whitelist |

---

## Data Model

## Data Models

### No New Database Tables

All state is managed through:
- Existing `User.telegram_chat_id` (already present)
- Existing `User.telegram_notifications_level` (already present)
- Redis keys for Callback_ID mappings (transient, 24h TTL)
- Redis keys for edit session state (transient, 30min TTL)

### Redis Key Schema

```
# Callback ID mapping (24h TTL)
tg:cb:{callback_id} → JSON { "draft_id": "uuid", "action": "approve|skip|edit", "user_id": "uuid" }

# Edit session (30min TTL)
tg:edit:{chat_id}:{message_id} → JSON { "draft_id": "uuid", "original_text": "...", "user_id": "uuid" }

# Rate limit: consecutive failures per user (24h TTL)
tg:fail:{user_id} → int (incremented on API error, reset on success)
```

### Callback_ID Generation

Telegram limits `callback_data` to 64 bytes. Strategy:

```python
import secrets

def create_callback_id(draft_id: str, action: str, user_id: str) -> str:
    """Generate short callback ID and store mapping in Redis."""
    callback_id = secrets.token_urlsafe(12)  # 16 chars, URL-safe
    redis.setex(
        f"tg:cb:{callback_id}",
        86400,  # 24h TTL
        json.dumps({"draft_id": draft_id, "action": action, "user_id": user_id})
    )
    return callback_id  # Fits in 64-byte callback_data easily
```

---

## Sequence Diagrams

### Flow 1: Draft Notification Delivery

```
EPG Build (08:15)
    │
    ▼
epg_executor.py generates drafts
    │
    ▼
_notify_drafts_pending() [EXISTING — portal bell]
    │
    ├──▶ notify_client() — SSE portal bell [existing]
    │
    └──▶ telegram_draft_review.notify_pending_drafts() [NEW]
              │
              ▼
         Query Users with:
           - telegram_chat_id IS NOT NULL
           - telegram_notifications_level IN ('all', 'warning')
           - role IN (owner, partner, client_admin, client_manager)
           - has access to this client (via role or UserClientAssignment)
           - client.autopilot_enabled = false
              │
              ▼
         For each eligible user:
           - Format Draft_Card (formatter.py)
           - Create Callback_IDs in Redis (callback_store.py)
           - Send via Telegram Bot API (bot_service.py)
           - If >5 drafts: send summary + "Approve All" first
```

### Flow 2: Approve via Callback

```
User taps "✅ Approve" on Draft_Card
    │
    ▼
Telegram sends callback_query to webhook
    │
    ▼
telegram_webhook.py:
    1. Extract chat_id, callback_data
    2. Lookup User by telegram_chat_id
    3. Resolve callback_id from Redis → { draft_id, action, user_id }
    4. Verify user_id matches (security)
    │
    ▼
telegram_draft_review.py:
    1. Load draft from DB
    2. Check draft.status == "pending" (idempotent if not)
    3. Check user has access to draft.client_id (P7)
    4. Approve: draft.status = "approved", slot.status = "approved"
    5. Create ExecutionTask (same as extension flow)
    6. Commit
    │
    ▼
bot_service.py:
    1. editMessageReplyMarkup — remove buttons
    2. editMessageText — add "✅ Approved" badge
    │
    ▼
Extension picks up ExecutionTask (next poll cycle, 30s)
    │
    ▼
Extension posts to Reddit at scheduled time
```

### Flow 3: Edit via LLM Regeneration

```
User taps "✏️ Edit" on Draft_Card
    │
    ▼
Telegram sends callback_query to webhook
    │
    ▼
telegram_webhook.py → telegram_draft_review.start_edit_session()
    1. Load full draft text
    2. Store edit session in Redis: tg:edit:{chat_id}:{msg_id} (30min TTL)
    3. bot_service.sendMessage: full text + "Send corrections as reply"
    │
    ▼
User replies with edit guidance text
    │
    ▼
Telegram sends message update to webhook (reply_to_message_id present)
    │
    ▼
telegram_webhook.py → telegram_draft_review.process_edit_reply()
    1. Match reply_to_message_id to edit session in Redis
    2. Load draft + thread context from DB
    3. Call LLM: system="Regenerate this Reddit comment incorporating user's feedback"
                 user=f"Original: {original}\nFeedback: {user_guidance}\nThread: {context}"
    4. Update draft.body = regenerated_text
    5. Commit
    │
    ▼
bot_service.py:
    1. Send new Draft_Card with regenerated text
    2. New Callback_IDs (Approve / Skip / Edit again)
    │
    ▼
User can Approve → normal flow
       or Edit again → loop
```

---

## Service Interfaces

### `app/services/telegram/bot_service.py`

```python
class TelegramBotService:
    """Low-level Telegram Bot API wrapper."""

    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    async def send_message(
        self, chat_id: str, text: str, reply_markup: dict | None = None,
        parse_mode: str = "HTML"
    ) -> dict:
        """Send message with optional inline keyboard."""

    async def edit_message_text(
        self, chat_id: str, message_id: int, text: str,
        reply_markup: dict | None = None
    ) -> dict:
        """Edit existing message text and/or keyboard."""

    async def answer_callback_query(
        self, callback_query_id: str, text: str | None = None, show_alert: bool = False
    ) -> None:
        """Acknowledge callback query (required within 10s)."""

    async def register_webhook(self, url: str, secret_token: str) -> bool:
        """Set webhook URL with Telegram API."""

    async def send_draft_card(
        self, chat_id: str, draft_card: "DraftCard"
    ) -> dict:
        """Send formatted draft card with inline keyboard."""
```

### `app/services/telegram/draft_review.py`

```python
class TelegramDraftReview:
    """Draft review operations triggered from Telegram."""

    def notify_pending_drafts(
        self, db: Session, client_id: str, drafts: list["CommentDraft"]
    ) -> int:
        """Send draft notifications to all eligible users for this client.
        Returns count of messages sent."""

    def approve_draft(
        self, db: Session, user: "User", draft_id: str
    ) -> dict:
        """Approve a single draft. Returns {"status": "approved"} or error."""

    def skip_draft(
        self, db: Session, user: "User", draft_id: str
    ) -> dict:
        """Skip/reject a single draft. Returns {"status": "rejected"} or error."""

    def start_edit_session(
        self, db: Session, user: "User", draft_id: str, chat_id: str, message_id: int
    ) -> str:
        """Start edit session. Returns full draft text for display."""

    def process_edit_reply(
        self, db: Session, user: "User", draft_id: str, guidance_text: str
    ) -> dict:
        """Regenerate draft via LLM with user guidance. Returns new text."""

    def bulk_approve(
        self, db: Session, user: "User", avatar_username: str
    ) -> dict:
        """Approve all pending drafts for avatar. Returns {"approved": N}."""

    def get_pending_for_user(
        self, db: Session, user: "User", limit: int = 5
    ) -> list[dict]:
        """Get pending drafts grouped by client→avatar for this user."""
```

### `app/services/telegram/callback_store.py`

```python
class CallbackStore:
    """Redis-based short ID mapping for Telegram callback_data."""

    def create(self, draft_id: str, action: str, user_id: str) -> str:
        """Generate callback_id, store in Redis with 24h TTL. Returns short ID."""

    def resolve(self, callback_id: str) -> dict | None:
        """Resolve callback_id to {draft_id, action, user_id}. None if expired."""

    def invalidate(self, callback_id: str) -> None:
        """Delete callback_id (after processing)."""
```

### `app/services/telegram/formatter.py`

```python
class DraftCardFormatter:
    """Format drafts as Telegram messages with inline keyboards."""

    def format_draft_card(
        self, draft: "CommentDraft", callback_ids: dict, client_name: str | None = None
    ) -> tuple[str, dict]:
        """Returns (text, reply_markup) for sendMessage.

        Text format (HTML):
            📝 <b>Draft for r/subreddit</b>
            👤 avatar_name | 🏢 ClientName (if multi-client user)
            📌 <a href="url">Thread title (truncated 80ch)...</a>

            <i>Comment text truncated to 300 chars...</i>

        reply_markup: InlineKeyboardMarkup with 3 buttons
        """

    def format_summary(
        self, drafts_by_avatar: dict[str, int], callback_ids: dict
    ) -> tuple[str, dict]:
        """Summary message when >5 drafts. Per-avatar "Approve All" buttons."""

    def format_approved(self, draft_text_truncated: str) -> str:
        """Format message after approval: ✅ Approved badge, no buttons."""

    def format_skipped(self, draft_text_truncated: str) -> str:
        """Format message after skip: ❌ Skipped badge, no buttons."""
```

---

## Webhook Route

### `app/routes/telegram_webhook.py`

```python
from fastapi import APIRouter, Request, HTTPException

router = APIRouter(prefix="/api/telegram", tags=["telegram"])

@router.post("/webhook")
async def telegram_webhook(request: Request):
    """Receive Telegram updates via webhook.

    Validates secret_token header, routes to appropriate handler:
    - Message with /command → command handler
    - Message as reply → edit handler
    - Callback query → button press handler
    """

    # 1. Validate X-Telegram-Bot-Api-Secret-Token header
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != EXPECTED_SECRET:
        raise HTTPException(status_code=403)

    # 2. Parse Update object
    update = await request.json()

    # 3. Route by update type
    if "callback_query" in update:
        await _handle_callback(update["callback_query"])
    elif "message" in update:
        message = update["message"]
        if message.get("reply_to_message"):
            await _handle_reply(message)
        elif "text" in message and message["text"].startswith("/"):
            await _handle_command(message)

    # 4. Always return 200 (Telegram retries on non-200)
    return {"ok": True}
```

---

## LLM Regeneration (Edit Flow)

When user provides edit guidance, the system regenerates:

```python
async def _regenerate_draft(
    db: Session, draft: CommentDraft, user_guidance: str
) -> str:
    """Regenerate draft body using LLM with user guidance.

    Uses same model as comment generation (llm_generation_model from DB).
    Records in learning service for correction pattern extraction.
    """
    from app.services.ai import call_llm, log_ai_usage
    from app.config import get_config

    model = get_config("llm_generation_model")

    # Build context (same as generation.py but with edit instruction)
    thread = draft.thread or draft.hobby_post
    thread_title = thread.title if thread else "Unknown"
    thread_body = (thread.body or "")[:500]

    messages = [
        {"role": "system", "content": EDIT_SYSTEM_PROMPT},
        {"role": "user", "content": f"""Original draft:
{draft.body}

Thread context: "{thread_title}" in r/{thread.subreddit if thread else '?'}
{thread_body}

User's feedback/guidance:
{user_guidance}

Regenerate the comment incorporating the user's feedback. Keep the same voice and style as the original. Output ONLY the new comment text."""}
    ]

    result = call_llm(messages=messages, model=model, max_tokens=500)
    new_text = result.choices[0].message.content.strip()

    # Log AI usage
    log_ai_usage(
        db, draft.client_id, "telegram_draft_edit",
        result, model=model, triggered_by="telegram"
    )

    return new_text
```

---

## Access Control (P7 Enforcement)

```python
def _user_can_review_draft(user: User, draft: CommentDraft) -> bool:
    """Check if user has review access to this draft's client.

    Rules:
    - owner, partner → access to ALL clients
    - client_admin, client_manager → access only to their assigned client(s)
    - Other roles → no access
    """
    if user.role in ("owner", "partner"):
        return True
    if user.role in ("client_admin", "client_manager"):
        # Check via User.client_id (direct) or UserClientAssignment
        if str(user.client_id) == str(draft.client_id):
            return True
        # Multi-client assignments
        from app.models.user_client_assignment import UserClientAssignment
        assigned = db.query(UserClientAssignment.client_id).filter(
            UserClientAssignment.user_id == user.id,
            UserClientAssignment.is_active == True,
        ).all()
        return str(draft.client_id) in {str(a.client_id) for a in assigned}
    return False
```

---

## Integration with Existing Notification Flow

### Hook Point: `epg_executor.py` → `_notify_drafts_pending()`

```python
def _notify_drafts_pending(db: Session, client_id, avatar: Avatar, subreddit: str) -> None:
    """Emit notifications that a draft is pending review."""
    # EXISTING: Portal bell
    try:
        from app.services.notifications import notify_client
        if client_id:
            notify_client(db, client_id=client_id, ...)
    except Exception:
        pass

    # NEW: Telegram notification
    try:
        from app.services.telegram.draft_review import TelegramDraftReview
        # Get the specific draft(s) just generated for this avatar
        pending_drafts = _get_just_generated_drafts(db, avatar.id, client_id)
        if pending_drafts:
            TelegramDraftReview().notify_pending_drafts(db, client_id, pending_drafts)
    except Exception:
        pass  # Non-critical — don't break generation pipeline
```

---

## Configuration

### System Settings (existing DB table)

| Key | Value | Purpose |
|-----|-------|---------|
| `telegram_bot_token` | (already exists) | Bot API token |
| `telegram_webhook_secret` | (new) | Secret for webhook validation |
| `telegram_draft_review_enabled` | `true`/`false` (new) | Kill switch for draft review feature |

### Environment / Startup

On app startup (`main.py` lifespan or startup event):
1. Read `telegram_bot_token` and `telegram_webhook_secret` from settings
2. If both present AND `telegram_draft_review_enabled=true`:
   - Register webhook: `https://gorampit.com/api/telegram/webhook`
   - Set bot commands via `setMyCommands` API

---

## Error Handling

### Rate Limiting & Error Handling

#### Telegram API Limits

- 30 messages/second to different chats (global)
- 1 message/second to same chat (burst)
- Solution: async queue with `asyncio.sleep(0.05)` between sends

### Failure Handling

| Scenario | Action |
|----------|--------|
| User blocked bot (403) | Increment `tg:fail:{user_id}`, clear chat_id after 3 |
| Chat not found (400) | Same as blocked |
| Timeout (5s) | Log, skip this notification (non-critical) |
| Callback_ID expired | "Session expired, use /pending" message |
| Draft already reviewed | Show current status, remove buttons |
| LLM regeneration fails | Notify user, keep original draft |
| Redis down | Skip Telegram notifications (fail-open, P10) |

---

## Nginx Configuration

```nginx
# Add to HTTPS server block:
location = /api/telegram/webhook {
    proxy_pass http://main_app;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    # No auth needed — validated via secret_token header
}
```

---

## Dependencies

| Package | Purpose | Version |
|---------|---------|---------|
| `httpx` | Telegram Bot API calls (already in project) | existing |
| — | No new dependencies required | — |

No `python-telegram-bot` or `aiogram` — raw `httpx` calls to Bot API (consistent with existing `ops_notifications.py` pattern). Keeps the dependency footprint minimal.

---

## Correctness Properties

### Property 1: Idempotent Approval
Approving an already-approved draft via any channel returns success with no state change. The backend never transitions a draft backward (approved → pending).

**Validates: Requirements 3.3, 10.2, 10.5**

### Property 2: Single Source of Truth
Draft status lives in PostgreSQL only. Redis Callback_IDs are transient references — if Redis is flushed, callbacks expire gracefully ("session expired") but no data is lost.

**Validates: Requirements 9.3, 9.6**

### Property 3: Fail-Open on Telegram Failure
Telegram API unavailability does NOT affect portal, extension, or email channels. Draft notifications are best-effort. Pipeline never blocks on Telegram delivery.

**Validates: Requirements 7.1, 2.5**

### Property 4: Edit Session Isolation
Each edit session is keyed by `chat_id + message_id` — concurrent edits on different drafts by the same user don't collide. Only direct replies to the specific edit prompt message are processed.

**Validates: Requirements 5.4, 5.6**

### Property 5: Role Boundary Enforcement
A Callback_ID encodes `user_id` — even if callback_data is intercepted, it resolves to the original user's context. Re-verification of user access happens at processing time, not just at callback creation time.

**Validates: Requirements 9.1, 9.4, 6.7**

### Property 6: No Duplicate Notifications
Draft status is checked immediately before sending Telegram notification. If already reviewed (approved/rejected) by another channel during the async delivery window, the notification is skipped.

**Validates: Requirements 2.7, 10.1**

---

## SBM Compliance

| Property | How Satisfied |
|----------|--------------|
| P3 (Cost) | LLM regeneration uses existing `call_llm()` + `log_ai_usage()`. Budget gate applies. |
| P5 (Human Gate) | Telegram = explicit human approve press. Same gate as portal/extension. |
| P7 (Isolation) | `_user_can_review_draft()` enforces client scoping via role + assignments. |
| P10 (Graceful Degradation) | Telegram failure = fall-open. Other channels unaffected. Kill switch exists. |
| P11 (Execution Gate) | Telegram doesn't post. Extension executor still required. |

---

## Testing Strategy

1. **Unit tests** for `callback_store.py` (create/resolve/expire)
2. **Unit tests** for `formatter.py` (text truncation, keyboard layout, 64-byte limit)
3. **Integration test** for webhook route (mock Telegram payload → verify DB state change)
4. **Manual test** for E2E: generate draft → receive in Telegram → approve → verify Extension picks up
