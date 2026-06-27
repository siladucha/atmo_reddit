# Browser Extension — Design

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  Executor's Machine                                      │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Chrome Browser                                  │    │
│  │                                                  │    │
│  │  ┌─────────────────────────────────────────┐    │    │
│  │  │  RAMP Extension (Manifest V3)           │    │    │
│  │  │                                         │    │    │
│  │  │  ┌──────────┐  ┌──────────────────┐    │    │    │
│  │  │  │ Service  │  │  Content Script   │    │    │    │
│  │  │  │ Worker   │  │  (reddit.com/*)   │    │    │    │
│  │  │  │          │  │                    │    │    │    │
│  │  │  │ - Poller │  │ - DOM interaction │    │    │    │
│  │  │  │ - Queue  │  │ - Post comments   │    │    │    │
│  │  │  │ - Timer  │  │ - Read karma      │    │    │    │
│  │  │  │ - Auth   │  │ - Detect bans     │    │    │    │
│  │  │  └────┬─────┘  └──────────────────┘    │    │    │
│  │  │       │                                  │    │    │
│  │  │  ┌────┴─────┐                           │    │    │
│  │  │  │  Popup   │ (task queue, settings)    │    │    │
│  │  │  └──────────┘                           │    │    │
│  │  └─────────────────────────────────────────┘    │    │
│  │                                                  │    │
│  │  Reddit session (cookies, logged in)             │    │
│  └──────────────────────┬───────────────────────────┘    │
│                          │                                │
└──────────────────────────┼────────────────────────────────┘
                           │ HTTPS (polling every 30s)
                           ▼
┌──────────────────────────────────────────────────────────┐
│  RAMP Backend (gorampit.com)                              │
│                                                           │
│  ┌──────────────────────────────────────────────────┐    │
│  │  Extension API Layer (FastAPI)                    │    │
│  │                                                   │    │
│  │  GET  /api/extension/tasks     → pending tasks   │    │
│  │  POST /api/extension/report    → results/signals │    │
│  │  POST /api/extension/heartbeat → online status   │    │
│  │  POST /api/extension/register  → initial setup   │    │
│  │  GET  /api/extension/config    → limits/settings │    │
│  └──────────────────────────────────────────────────┘    │
│                                                           │
│  ┌──────────────────────────────────────────────────┐    │
│  │  Extension Dispatcher (replaces email for online) │    │
│  │                                                   │    │
│  │  - Checks executor online status                 │    │
│  │  - Routes task to extension (online) or email    │    │
│  │  - Handles fallback (offline > 30 min → email)   │    │
│  └──────────────────────────────────────────────────┘    │
│                                                           │
│  ┌──────────────────────────────────────────────────┐    │
│  │  Health Signal Ingestion                          │    │
│  │                                                   │    │
│  │  - Processes extension health reports            │    │
│  │  - Updates avatar.health_status                  │    │
│  │  - Triggers auto-unfreeze on recovery            │    │
│  │  - Emits activity events + notifications         │    │
│  └──────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

## Extension Components (Manifest V3)

### Service Worker (background.js)

Long-lived background process. Handles:
- **Polling loop** — GET /api/extension/tasks every 30s (when active)
- **Task queue** — local storage of pending tasks
- **Timer engine** — fires tasks at scheduled_at time
- **Heartbeat** — POST /api/extension/heartbeat every 60s
- **Auth management** — JWT token storage + refresh
- **Kill switch** — instant pause on "pause_all" command from backend

```
State Machine (Service Worker):
  idle → polling → task_received → dispatching → waiting_result → reporting → idle
                                                     ↓
                                               content_script
```

### Content Script (reddit_actions.js)

Injected into reddit.com pages. Handles:
- **Comment posting** — locate comment box, fill text, submit
- **CQS posting** — navigate to r/WhatIsMyCQS/submit, create post, read reply
- **Karma reading** — parse profile page for karma values
- **Health monitoring** — detect ban notices, removed content indicators
- **Session detection** — identify currently logged-in Reddit username

DOM interaction strategy:
```
Primary: CSS selectors (Reddit's Shreddit web components)
Fallback 1: data-testid attributes
Fallback 2: ARIA labels
Fallback 3: XPath (last resort)

If all fail → report "dom_structure_changed" error to RAMP
```

### Popup (popup.html + popup.js)

Executor-facing UI:
- Task queue with approve/reject buttons
- Auto/Manual mode toggle
- Pause button
- Connection status indicator
- History tab (last 20 completed tasks)
- Settings (RAMP URL, active hours)

## Backend API Design

### Data Models

```python
# New model: ExtensionSession
class ExtensionSession(Base):
    __tablename__ = "extension_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    executor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    avatar_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("avatars.id"))
    device_fingerprint: Mapped[str | None]  # browser/OS identifier
    extension_version: Mapped[str]
    last_heartbeat: Mapped[datetime]
    is_online: Mapped[bool] = mapped_column(default=False)
    active_reddit_username: Mapped[str | None]  # currently logged-in account
    mode: Mapped[str] = mapped_column(default="manual")  # "auto" | "manual" | "paused"
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
```

### API Endpoints

#### GET /api/extension/tasks

Returns pending tasks for the executor's currently active Reddit account.

```json
// Response
{
  "tasks": [
    {
      "task_id": "uuid",
      "idempotency_key": "unique-per-task-delivery",
      "task_signature": "hmac-sha256-of-task-payload",
      "task_type": "post_comment | cqs_check",
      "avatar_username": "Flaky_Finder_13",
      "thread_url": "https://reddit.com/r/...",
      "thread_title": "...",
      "comment_text": "...",
      "reply_to_comment_id": null,
      "scheduled_at": "2026-06-28T08:00:00Z",
      "lease_expires_at": "2026-06-28T08:30:00Z",
      "deadline": "2026-06-28T20:00:00Z",
      "priority": "normal | high",
      "action_class": "content | system",
      "config": {
        "daily_cap": 3,
        "min_interval_seconds": 180,
        "active_hours_start": "08:00",
        "active_hours_end": "22:00"
      }
    }
  ],
  "commands": ["pause_all"] // or empty — system-level commands
}
```

**Integrity & Idempotency:**
- `idempotency_key`: unique per task delivery attempt. Extension includes it in report. Backend rejects duplicate reports (200 OK, no re-processing).
- `task_signature`: HMAC-SHA256 of task payload signed with backend secret. Extension verifies before execution — rejects tampered tasks.
- `lease_expires_at`: if extension doesn't report result by this time, task is released for re-delivery (to email fallback or next poll cycle).
- `action_class`: "system" (CQS, health) or "content" (comments). Extension applies different rate limits per class.

#### POST /api/extension/report

```json
// Request — task result
{
  "task_id": "uuid",
  "idempotency_key": "same-key-from-task-delivery",
  "result_type": "task_completed",
  "status": "posted | blocked | error",
  "permalink": "https://reddit.com/r/.../comment/...",
  "comment_id": "abc123",
  "posted_at": "2026-06-28T08:05:32Z",
  "error_reason": null,  // "thread_locked" | "auth_expired" | "dom_error" | ...
  "metadata": {}
}

// Request — health signal (best-effort, NOT authoritative for state changes)
{
  "result_type": "health_signal",
  "avatar_username": "Flaky_Finder_13",
  "signal": "comment_removed | ban_notice | profile_restricted",
  "details": { "karma": {"comment": 5, "link": 1} }
}

// Request — CQS result (factual — bot's response)
{
  "result_type": "cqs_result",
  "avatar_username": "Flaky_Finder_13",
  "cqs_level": "low",
  "post_id": "1uge4ov",
  "bot_reply_text": "Your current CQS is **LOW**."
}
```

#### POST /api/extension/heartbeat

```json
// Request
{
  "session_id": "uuid",
  "active_reddit_username": "Flaky_Finder_13",
  "extension_version": "1.0.0",
  "mode": "auto",
  "browser": "chrome/126",
  "tasks_in_local_queue": 2
}
```

## Task Routing Logic

```python
def route_task_to_executor(task: ExecutionTask, avatar: Avatar) -> str:
    """Decide delivery channel: extension or email.

    Priority:
    1. Extension online + correct account active → extension
    2. Extension online + wrong account → hold (notify switch account)
    3. Extension offline < 30 min → hold (might come back)
    4. Extension offline > 30 min → email fallback
    5. No extension registered → email only
    """
    session = get_active_extension_session(avatar.executor_email)

    if not session:
        return "email"

    if session.is_online and session.active_reddit_username == avatar.reddit_username:
        return "extension"

    if session.is_online and session.active_reddit_username != avatar.reddit_username:
        return "extension_wrong_account"  # notify executor to switch

    offline_duration = datetime.utcnow() - session.last_heartbeat
    if offline_duration < timedelta(minutes=30):
        return "hold"  # wait for reconnect

    return "email"  # fallback
```

## CQS Self-Healing Flow (Extension-Enabled)

```
Day 0: Avatar frozen (shadowban detected)
        ↓
Day 0-7: generate_cqs_check_tasks() includes frozen avatars
          Creates ExecutionTask(task_type="cqs_check", action_class="system")
        ↓
Next polling cycle (30s): Extension picks up CQS task
        ↓
Extension: Opens r/WhatIsMyCQS/submit in background tab (system action)
           Posts "What is my CQS?"
           Waits 30-60s for AutoModerator reply
           Reads reply → parses CQS level
        ↓
Extension → RAMP: POST /api/extension/report
           {result_type: "cqs_result", cqs_level: "low", idempotency_key: "..."}
        ↓
RAMP — Measurement layer:
  Records avatar.cqs_level = "low" (factual)
        ↓
RAMP — State transition layer:
  CQS improved from "lowest"? → YES
  Creates recovery_candidate flag
  Triggers independent PRAW submission_visibility_probe
        ↓
PRAW probe result:
  If post visible in subreddit feed → DUAL CONFIRMATION → auto-unfreeze
    + notify operator post-factum with evidence chain
  If post still invisible → KEEP FROZEN
    + notify operator: "CQS improved but shadowban persists"
    + retry CQS in 7 days
```

**Key invariant:** Single extension signal NEVER triggers state transition alone.
Auto-unfreeze requires dual confirmation (CQS improved + PRAW probe passes) OR manual operator action.

## Comment Posting Flow (Extension)

```
1. EPG builds slot → draft approved → ExecutionTask created (with idempotency_key + lease)
2. dispatch_due_email_tasks checks: extension online?
3. YES → task.delivery_channel = "extension", status = "dispatched_to_extension"
4. Extension polls → receives task (verifies task_signature HMAC before proceeding)
5. Extension checks:
   - Is task_signature valid? (reject if tampered)
   - Is scheduled_at reached? (wait if not)
   - Is within active hours? (content actions only)
   - Is min_interval satisfied? (content actions only)
   - Is daily cap not exceeded? (content actions only)
6. Extension navigates to thread_url
7. Extension checks: thread locked? removed? archived?
8. If blocked → report {status: "blocked", reason: "...", idempotency_key: "..."}
9. If OK → locate comment box → fill text → submit
10. Extract permalink from newly posted comment
11. Report {status: "posted", permalink: "...", comment_id: "...", idempotency_key: "..."}
12. RAMP receives → verifies idempotency_key not already processed
    → updates draft.status="posted", slot.status="posted"
    No reconciliation needed — system knows immediately.
13. If lease_expires_at reached without report → task released for re-delivery (email fallback)
```

## Security Model

### What Extension CAN access:
- Reddit DOM on reddit.com/* (content script)
- RAMP API at gorampit.com/api/extension/* (service worker)
- Local storage for task queue + settings

### What Extension CANNOT access:
- Reddit cookies/session tokens (isolated by Chrome security model)
- Other tabs/sites content
- File system
- Other extensions

### Authentication:
- Executor receives unique JWT token during RAMP onboarding
- Token stored in extension's chrome.storage.local (encrypted at rest by Chrome)
- Token has limited scope: only /api/extension/* endpoints
- Token refresh: RAMP issues new token on each heartbeat (rolling expiry)

### Manifest V3 Permissions:
```json
{
  "permissions": ["storage", "alarms", "notifications"],
  "host_permissions": [
    "https://www.reddit.com/*",
    "https://old.reddit.com/*",
    "https://gorampit.com/api/extension/*"
  ]
}
```

## Reddit DOM Interaction Strategy

Reddit has multiple UI variants:
- **New Reddit (Shreddit)** — Web Components (`<shreddit-comment-action-row>`)
- **Old Reddit** — Classic HTML (`#comment_reply_form`)
- **Redesign (React)** — React-rendered DOM

Extension detects active variant and uses appropriate selectors:

```javascript
// Variant detection
function detectRedditVariant() {
  if (document.querySelector('shreddit-app')) return 'shreddit';
  if (document.querySelector('#header-bottom-left')) return 'old';
  return 'redesign';
}

// Comment posting — variant-specific
const COMMENT_SELECTORS = {
  shreddit: {
    replyButton: '[slot="reply-button"]',
    textArea: 'shreddit-composer textarea, div[contenteditable="true"]',
    submitButton: 'button[type="submit"][slot="submit-button"]',
  },
  old: {
    replyButton: '.reply-button',
    textArea: '.usertext-edit textarea',
    submitButton: '.save',
  },
  redesign: {
    replyButton: '[data-testid="comment-reply-button"]',
    textArea: '[data-testid="comment-composer"] div[contenteditable]',
    submitButton: '[data-testid="comment-submit-button"]',
  }
};
```

## Fallback & Error Handling

| Scenario | Extension Behavior | RAMP Behavior |
|----------|-------------------|---------------|
| Reddit session expired | Report auth_expired, stop tasks | Mark executor offline, fall back to email |
| DOM selectors broken | Report dom_error with page HTML snippet | Alert operator, pause auto-mode for this executor |
| Network disconnection | Queue results locally, retry on reconnect | After 30 min offline → email fallback |
| Browser closed | Service worker terminated (MV3 limitation) | Heartbeat timeout → mark offline |
| Reddit rate limit (UI) | Detect "you're doing this too much", wait | Extend min_interval for this avatar |
| Wrong account logged in | Show warning in popup, hold tasks | Hold tasks until correct account active |
| Kill switch received | Immediately stop all pending tasks | Confirmed via next heartbeat |

## Phase Plan

### Phase 1 — MVP (2-3 weeks)
- Chrome extension with Service Worker + Content Script
- Popup with task queue (manual mode only)
- CQS auto-check (R2)
- Health monitoring basic (karma + session detection)
- Backend: 4 API endpoints + ExtensionSession model
- Single-account support

### Phase 2 — Auto-Posting (1-2 weeks)
- Auto-mode for comment posting (R3)
- Timer engine (scheduled_at respect)
- Safety limits enforcement (cap, interval, active hours)
- Thread liveness check before posting
- Permalink extraction + immediate RAMP update

### Phase 3 — Intelligence (1 week)
- Shadowban probe (incognito visibility check)
- Auto-unfreeze logic (R10)
- Multi-account detection (R7)
- Extension status in admin UI

### Phase 4 — Polish (1 week)
- Firefox port
- Error recovery + retry logic
- Onboarding wizard in extension
- Chrome Web Store submission
