# Browser Extension — Design

## Overview

Backend-controlled task orchestration over leased Execution Nodes. Extension is an untrusted, stateless runtime that executes signed tasks and reports raw results. All intelligence resides in backend.

**Single Authority Principle:** Backend is sole truth engine for scheduling, state transitions, validation, and policy. Referenced once here — not repeated.

## Architecture

```
EXECUTION NODE (executor machine)          RAMP BACKEND (sole authority)
┌────────────────────────────┐            ┌──────────────────────────────┐
│ Chrome + Extension Runtime │  polling   │ Extension API (FastAPI)      │
│                            │ ────────→  │  GET  /policy (immutable)    │
│ - Service Worker (poll,    │            │  GET  /tasks (assigned)      │
│   HMAC verify, timer,      │  report    │  POST /report (untrusted)    │
│   queue, heartbeat)        │ ────────→  │  POST /heartbeat             │
│                            │            │  POST /register              │
│ - Content Script           │            ├──────────────────────────────┤
│   (reddit.com DOM actions) │            │ Task Orchestrator            │
│                            │            │  - create, assign, validate  │
│ - Popup (mode-dependent)   │            │  - lease management          │
│                            │            │  - expiry + re-delivery      │
│ Reddit Identity = resource │            ├──────────────────────────────┤
└────────────────────────────┘            │ Policy Engine                │
                                          │  - EPG mode per avatar       │
 execution_node_id: uuid                  │  - rate limits, active hours │
 binding: (node_id, username)             ├──────────────────────────────┤
                                          │ Signal Validator             │
                                          │  - normalize raw reports     │
                                          │  - weight health signals     │
                                          │  - trigger PRAW probes       │
                                          │  - emit events/notifications │
                                          └──────────────────────────────┘
```


## Components and Interfaces

### Backend Components

**1. Extension API** (FastAPI routes):
- `GET /api/extension/policy` — immutable per-avatar config (epg_mode, limits, allowed types)
- `GET /api/extension/tasks` — assigned tasks filtered by active_reddit_username
- `POST /api/extension/report` — receives untrusted results, validates idempotency
- `POST /api/extension/heartbeat` — node liveness + active account
- `POST /api/extension/register` — creates execution_node_id

**2. Task Orchestrator** (`extension_dispatcher.py`):
- Creates tasks with HMAC signature
- Assigns to online nodes (CREATED → ASSIGNED)
- Validates reports (REPORTED → FINALIZED)
- Expires stale leases (→ EXPIRED, may re-create)
- Routes: extension (preferred) or email (fallback after 30min offline)

**3. Policy Engine** (per-avatar config):
- `epg_mode`: REQUIRED / OPTIONAL / DISABLED
- Rate limits: daily_cap, min_interval, active_hours
- Priority: diagnostic > content
- Backpressure: max 1 concurrent, queue limit 20

**4. Signal Validator** (`extension_health.py`):
- Normalizes raw probe output → structured data (CQS level extraction)
- Weights health signals (trust_weight, decay_hours)
- Aggregates signals: N signals × weight > threshold → action candidate
- Creates recovery_candidate flags
- Triggers independent PRAW verification

### Extension Components (Manifest V3)

**1. Service Worker** (background.js):
- Poller: GET /tasks every 30s (from policy config)
- HMAC verifier: validates task_hash before queueing
- Timer: holds tasks until scheduled_at
- Queue: local chrome.storage (max 20, priority ordering)
- Heartbeat: every 60s
- Kill switch: instant pause_all
- Account monitor: detects username change → abort executing task

**2. Content Script** (reddit_actions.js):
- Reddit variant detection (shreddit / old / redesign)
- Action executors: postComment(), postCQSCheck(), readKarma(), checkVisibility()
- DOM selector chains (CSS → data-testid → ARIA → XPath)
- Reports raw results only (no interpretation)
- Reports dom_structure_changed if all selectors fail

**3. Popup** (mode-dependent):
- REQUIRED_UI: task queue + approve/reject
- NOTIFICATION_ONLY: activity feed + alerts
- MINIMAL: errors only (invisible otherwise)
- Common: connection indicator, pause button, badge

---

## Data Models

```python
class ExecutionNode(Base):
    __tablename__ = "execution_nodes"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    executor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    device_fingerprint: Mapped[str | None]
    extension_version: Mapped[str | None]
    last_heartbeat: Mapped[datetime | None]
    is_online: Mapped[bool] = mapped_column(default=False)
    active_reddit_username: Mapped[str | None]
    tasks_in_queue: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

# Additional fields on ExecutionTask:
execution_node_id: Mapped[uuid.UUID | None]
task_hash: Mapped[str]                       # HMAC-SHA256
lease_expires_at: Mapped[datetime | None]    # attribute, not state
idempotency_key: Mapped[str]
task_lifecycle_status: Mapped[str]           # CREATED/ASSIGNED/EXECUTING/REPORTED/FINALIZED/FAILED/EXPIRED
probe_type: Mapped[str | None]
priority: Mapped[str] = mapped_column(default="content")  # diagnostic | content

# Avatar policy:
epg_mode: Mapped[str] = mapped_column(default="required")
```

---

## Task Lifecycle

```
CREATED → ASSIGNED → EXECUTING → REPORTED → FINALIZED (terminal)
                         ↓
                    FAILED (terminal)

EXPIRED: lease_expires_at passed (terminal, may trigger re-creation)
```

Lease = attribute (`lease_expires_at` + `execution_node_id`), not a state.

| From | To | Trigger | Actor |
|------|-----|---------|-------|
| CREATED | ASSIGNED | Node polls, backend assigns | Backend |
| ASSIGNED | EXECUTING | Extension acknowledges | Extension |
| EXECUTING | REPORTED | Extension sends result | Extension |
| REPORTED | FINALIZED | Backend validates | Backend |
| ASSIGNED/EXECUTING | EXPIRED | Lease timeout | Backend cron |
| EXECUTING | FAILED | Error condition | Extension |

---

## API Contracts

### GET /api/extension/policy
```json
{
  "epg_mode": "required",
  "daily_cap": 3,
  "min_interval_seconds": 180,
  "active_hours_start": "08:00",
  "active_hours_end": "22:00",
  "allowed_task_types": ["post_comment", "diagnostic_probe"],
  "cqs_probe_max_per_hour": 1,
  "health_probe_max_per_30min": 1,
  "max_concurrent_tasks": 1,
  "queue_overflow_limit": 20,
  "poll_interval_seconds": 30
}
```

### GET /api/extension/tasks
```json
{
  "tasks": [
    {
      "task_id": "uuid",
      "idempotency_key": "unique-per-delivery",
      "task_hash": "hmac-sha256",
      "task_type": "post_comment",
      "probe_type": null,
      "priority": "content",
      "avatar_username": "Flaky_Finder_13",
      "thread_url": "https://reddit.com/r/.../comments/...",
      "comment_text": "...",
      "scheduled_at": "2026-06-28T08:00:00Z",
      "lease_expires_at": "2026-06-28T08:30:00Z"
    }
  ],
  "commands": []
}
```

### POST /api/extension/report
```json
{"task_id": "uuid", "idempotency_key": "key", "result_type": "task_completed",
 "status": "posted", "permalink": "url", "comment_id": "id", "posted_at": "ts"}

{"task_id": "uuid", "idempotency_key": "key", "result_type": "probe_result",
 "probe_type": "reddit_cqs",
 "raw_output": "Your current CQS is **LOW**.",
 "execution_metadata": {"duration_ms": 45000, "reddit_variant": "shreddit"}}

{"result_type": "health_signal", "avatar_username": "user",
 "signal_type": "comment_removed", "raw_value": {}, "timestamp": "ts"}

{"task_id": "uuid", "idempotency_key": "key", "result_type": "task_failed",
 "error_code": "account_switch_error", "error_details": "..."}
```

**Idempotency contract:** First valid report wins. Duplicates → 200 NOOP. Backend = final arbiter.

### POST /api/extension/heartbeat
```json
{"execution_node_id": "uuid", "active_reddit_username": "user",
 "extension_version": "1.0.0", "tasks_in_local_queue": 2}
```

---

## Correctness Properties

1. **No duplicate execution:** idempotency_key + lease_expires_at + backend dedup.
2. **No unauthorized execution:** HMAC verification. Invalid hash → reject.
3. **No state corruption:** Extension cannot change avatar state. Only backend.
4. **No credential leak:** Chrome isolation + extension permission model.
5. **Diagnostic independence:** Probes run regardless of frozen/health state.
6. **Graceful degradation:** Extension offline → email fallback (30 min threshold).
7. **Account binding:** username mismatch → hold/abort (never execute on wrong account).

---

## Error Handling

| Error | Extension Action | Backend Action |
|-------|-----------------|----------------|
| `auth_expired` | Report, stop all tasks | Mark node offline, email fallback |
| `dom_structure_changed` | Report with page context | Alert operator, pause auto for node |
| `thread_locked` | Report blocked | Cancel task, update slot |
| `account_switch_error` | Abort, report | Release lease, hold for correct account |
| Network disconnect | Queue locally, retry | After 30 min → email fallback |
| HMAC invalid | Reject task, report error | Investigate (possible tampering) |
| Queue overflow (>20) | Reject new deliveries | Backend holds tasks until drained |
| Lease expired | N/A (extension dead) | Re-create task or email fallback |

---

## Reddit DOM Strategy

```javascript
function detectRedditVariant() {
  if (document.querySelector('shreddit-app')) return 'shreddit';
  if (document.querySelector('#header-bottom-left')) return 'old';
  return 'redesign';
}

const SELECTORS = {
  shreddit: {
    replyButton: '[slot="reply-button"]',
    textArea: 'shreddit-composer textarea, div[contenteditable="true"]',
    submitButton: 'button[type="submit"][slot="submit-button"]'
  },
  old: {
    replyButton: '.reply-button',
    textArea: '.usertext-edit textarea',
    submitButton: '.save'
  },
  redesign: {
    replyButton: '[data-testid="comment-reply-button"]',
    textArea: '[data-testid="comment-composer"] div[contenteditable]',
    submitButton: '[data-testid="comment-submit-button"]'
  }
};
```

---

## Testing Strategy

| Layer | What | How |
|-------|------|-----|
| Unit | HMAC verification, timer logic, queue management | Jest (extension) |
| Unit | Task orchestrator, policy engine, signal validator | pytest (backend) |
| Integration | Poll → receive → execute → report → validate cycle | Playwright + mock Reddit DOM |
| Contract | API request/response shapes | Pydantic schema validation |
| E2E | CQS self-healing: frozen avatar → probe → report → recovery candidate | Staging environment |
| Fault | Lease expiry, network drop, account switch mid-task | Chaos injection |

---

## Security Model

| Element | Trust | Reason |
|---------|:-----:|--------|
| Task from backend (valid HMAC) | Trusted | Signed by backend secret |
| Task with invalid HMAC | Rejected | Tampering/replay |
| Extension report | Untrusted | Validated server-side |
| Reddit DOM | Untrusted | May be manipulated |
| Backend state | Authoritative | Single Authority Principle |

**Extension cannot:** generate tasks, modify task content, replay old tasks, trigger state transitions, access Reddit credentials.

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

---

## Phase Plan

| Phase | Scope | Timeline |
|-------|-------|----------|
| 1 (MVP) | CQS probe + comment posting (REQUIRED_UI mode) + health probe + heartbeat + backend API | 2-3 weeks |
| 2 | OPTIONAL/DISABLED modes (auto-execute) + timer engine + full rate limit enforcement | 1-2 weeks |
| 3 | Dual-confirmation auto-unfreeze + signal aggregation + multi-node admin UI | 1 week |
| 4 | Firefox port + Chrome Web Store + onboarding wizard + polish | 1 week |
