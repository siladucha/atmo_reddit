---
inclusion: fileMatch
fileMatchPattern: "**/extension*,**/ramp_extension/**,**/executor*"
---

# Browser Extension — Architecture & Design Decisions

## What It Is

A Chrome Manifest V3 browser extension installed on executor machines. Connects to RAMP backend via HTTPS polling. Performs Reddit actions (CQS checks, comment posting, health monitoring) through the executor's authenticated browser session.

## Why It Exists (June 27, 2026 Decision)

Three problems converged:

1. **CQS Deadlock** — frozen/shadowbanned avatars can't get CQS checks (batch skips them), but CQS improvement is the recovery signal. Circular dependency.
2. **Posting Infrastructure Complexity** — residential proxies ($50-200/mo), OAuth approval (months pending), API credentials per account — all fragile and expensive.
3. **Executor Friction** — email → open Reddit → find thread → copy → paste → post → copy permalink → submit back = 8 manual steps, delays, drops.

Extension solves all three with one component.

## Core Principles

1. **No credential exfiltration.** Extension never sends cookies, passwords, or session tokens to RAMP. It receives task instructions FROM RAMP and reports results TO RAMP. The browser session stays on the executor's machine.

2. **Measurement ≠ State transition.** Extension reports raw signals (CQS level, health observations). RAMP backend makes state decisions based on validated signals, never on a single heuristic alone.

3. **System actions ≠ Content actions.** CQS checks and health probes are diagnostics that run independently of posting limits. Content posting has separate rate limits and can be paused without affecting diagnostics.

## Key Architecture Decisions

### Communication: HTTPS Polling (MVP), Long-Poll/SSE (Upgrade Path)

MVP: Extension polls `GET /api/extension/tasks` every 30s. Reasons:
- Works behind any NAT/firewall/corporate proxy
- No persistent connection to maintain (Chrome kills idle sockets in MV3)
- Manifest V3 service workers are ephemeral — can't hold WebSocket
- 30s polling is fast enough for EPG tasks (scheduled minutes/hours ahead)

Upgrade path (Phase 2): Long-poll or SSE for sub-second task delivery when needed.

### Task Routing: Extension-First, Email-Fallback

```
Task created → Is executor's extension online?
  YES + correct account → deliver to extension
  YES + wrong account → hold + notify "switch account"
  OFFLINE < 30 min → hold (might reconnect)
  OFFLINE > 30 min → fall back to email
  NOT REGISTERED → email only
```

Extension and email coexist. Extension is preferred channel when available.

### Two-Class Action Model

| Class | Examples | Rate Limited | Requires Approval | Runs When Paused |
|-------|----------|-------------|-------------------|------------------|
| **System action** | CQS check, health probe, karma read | Own limits (1/hour CQS, 1/30min health) | No | Yes |
| **Content action** | Comment posting | Yes (daily cap, 3 min interval, active hours) | Yes (manual mode) or No (auto mode) | No |

This separation prevents CQS diagnostics from being blocked by content posting limits and vice versa.

### State Transition Layer (Recovery Decisions)

**Critical design:** Extension health signals are best-effort heuristics, NOT authoritative state-change triggers.

```
Extension reports CQS=LOW (measurement)
  → RAMP records cqs_level=low immediately (factual)
  → RAMP creates "recovery_candidate" flag
  → RAMP triggers independent PRAW verification (submission_visibility_probe)
  → If PRAW confirms visible → auto-unfreeze (dual confirmation)
  → If PRAW still shows invisible → notify operator, keep frozen
  → Operator can manually unfreeze at any time via admin UI
```

Single extension signal alone NEVER triggers auto-unfreeze. Either:
- Operator approves manually (always available), OR
- Two independent signals confirm (CQS improved + PRAW probe passes)

### Task Integrity & Idempotency

- Each task has `idempotency_key` — prevents duplicate execution if task re-delivered
- Tasks include HMAC signature (backend secret) — extension verifies before execution
- Execution lease: task has `lease_expires_at` — if not reported by deadline, released for re-delivery
- Backend rejects duplicate reports (same idempotency_key) with 200 OK, no re-processing

### CQS Self-Healing Loop

```
Frozen avatar (CQS=lowest, shadowbanned)
  ↓ [cqs_task_generator — NO is_frozen filter]
ExecutionTask(task_type="cqs_check") created
  ↓ [extension online]
Extension posts "What is my CQS?" in background tab
  ↓ [AutoModerator replies within 60s]
Extension reads reply, reports CQS level to RAMP
  ↓ [RAMP state transition layer]
CQS recorded → recovery_candidate if improved
  → independent PRAW probe triggered
  → dual confirmation → auto-unfreeze OR operator notification
```

### Reddit DOM Strategy

Reddit has 3 UI variants that the content script must handle:
- **Shreddit** (new default) — Web Components, `<shreddit-*>` tags
- **Old Reddit** — classic HTML, `#comment_reply_form`
- **Redesign** — React-rendered DOM

Extension auto-detects variant and uses appropriate selectors. Falls back through chain: CSS → data-testid → ARIA → XPath. Reports `dom_structure_changed` if all fail.

### Safety Invariants

1. **Never posts without task from RAMP** — extension is execution-only, not autonomous
2. **Daily cap enforced client-side** — even if RAMP sends extra tasks, extension respects cap
3. **Minimum 3-minute interval for content posts** — hard limit, cannot be overridden
4. **Active hours only for content posts** — no posting outside 08:00-22:00 executor local time in auto-mode
5. **Kill switch** — RAMP can send `pause_all` command, instantly stops ALL actions
6. **Auth check before every action** — if Reddit session expired, reports error, does nothing
7. **System actions always run** — CQS checks and health probes are never blocked by content limits or pause state

## Backend Changes Required

| Component | Change |
|-----------|--------|
| `cqs_task_generator.py` | Remove `is_frozen` skip, remove `health_status` skip (**DONE June 27**) |
| `cqs_checker.py` | Remove `warming_phase >= 2` and `is_frozen` filter from batch (**DONE June 27**) |
| `health_checker.py` | Add separate "frozen probe" or remove `is_frozen` filter |
| `execution_tasks.py` | Add `delivery_channel` field, `idempotency_key`, extension routing |
| `dispatch_due_email_tasks` | Check extension online before email fallback |
| New: `extension_api.py` | 4 endpoints (tasks, report, heartbeat, register) |
| New: `extension_dispatcher.py` | Routing logic + lease management |
| New: `extension_health.py` | Health signal ingestion + recovery candidate creation |
| New: `avatar_recovery.py` | State transition layer (dual confirmation + operator notification) |
| New: `extension_session` model | ExtensionSession table |

## Executor Time Investment

| Mode | What executor does | Daily time |
|------|-------------------|-----------|
| **Manual-mode (MVP)** | Opens popup, approves/rejects 3-7 tasks | 1-2 min |
| **Auto-mode (Phase 2)** | Nothing — browser open is sufficient | 0 min |
| **Review-mode** | "Approve All" batch once in morning | 30 sec |

CQS checks and health monitoring require ZERO executor time in all modes.

## Phases

| Phase | Scope | Timeline |
|-------|-------|----------|
| **1 — MVP** | CQS auto-check + health monitoring + backend API + popup (manual mode only) | 2-3 weeks |
| **2 — Auto-Posting** | Auto-mode + safety limits + thread checks + long-poll upgrade | 1-2 weeks |
| **3 — Intelligence** | Dual-confirmation auto-unfreeze + multi-account + PRAW integration | 1 week |
| **4 — Polish** | Firefox port, Chrome Web Store, onboarding wizard | 1 week |

## Impact on Existing Systems

| System | Before Extension | After Extension |
|--------|-----------------|-----------------|
| Proxy infrastructure | Required ($50-200/mo) | Not needed (DEFERRED) |
| OAuth approval | Required (blocked) | Not needed (DEFERRED) |
| Email task delivery | Primary channel | Fallback channel |
| Draft reconciliation | Essential (3-pass matching) | Optional (extension reports permalink directly) |
| CQS deadlock | Broken (frozen skip) | Fixed (batch filter removed June 27) |
| Health monitoring for frozen | None (skipped) | Extension reports signals |
| API rate limits | Shared 60 req/min | Posting via browser session, no API consumption |
| Executor friction | 8 steps manual | 1 click (MVP) → 0 steps (Phase 2) |

## Current Status (Updated July 2, 2026)

**Extension v2 deployed and working.** Full automated flow via `chrome.debugger` API for trusted clicks.

**Spec:** `.kiro/specs/extension-v2-debugger/requirements.md`

### What's Live (v2)

- **Backend API endpoints (production):** activate, dashboard, tasks, report, heartbeat, events, tasks/{id}/approve, tasks/{id}/retry, tasks/{id} PATCH (edit) — all working
- **Extension (Chrome MV3, Load Unpacked):** polling, heartbeat, auto-auth, text insertion via InputEvent — working
- **chrome.debugger trusted clicks:** Composer open + submit via CDP `Input.dispatchMouseEvent` — reliable
- **Content script bundle rebuilt:** All message handlers present (DISMISS_BANNERS, CLEAR_DRAFTS, WAIT_FOR_COMPOSER, INSERT_TEXT, VERIFY_POSTED, GET_ELEMENT_COORDS)
- **Scheduler:** 15s tick, 3-min minimum interval, active hours 08:00-22:00, dom_health check, pause_all
- **Popup UI v2:** Clean executor UI — "Needs Approval" → "Today stats" → "Done/Failed". No debug clutter.
- **Delivery channel selector:** Admin → Avatar → Posting tab → "Task Delivery Channel" (email/extension/both)
- **Download:** https://gorampit.com/static/extension/index.html

### v1 → v2 Migration Summary (July 2, 2026)

| Component | v1 (broken) | v2 (working) |
|-----------|------------|-------------|
| Composer open | `.click()` on shadow DOM (50% success) | `chrome.debugger` CDP trusted mousePressed/Released (reliable) |
| Submit | Manual (executor clicks) | `chrome.debugger` trusted click on submit button |
| Execution mode | PREPARE_ONLY (stop before submit) | Full auto after approval |
| Popup | Debug-heavy (execution state, 6 stats, EPG slots, drafts) | Clean (approve → today → done/failed) |
| Delivery routing | Email only, extension auto-detected on dispatch | Explicit `delivery_channel` field on Avatar (admin selectable) |
| Content bundle | Stale (missing DISMISS_BANNERS, CLEAR_DRAFTS handlers) | Rebuilt with all 5 source modules |

### v2 → v3 Default Strategy Change (July 4, 2026)

**Decision:** Default posting strategy changed from `new_reddit_debugger` to `old_reddit`.

| Aspect | v2 (before) | v3 (now) |
|--------|------------|----------|
| Default strategy | `new_reddit_debugger` (chrome.debugger) | `old_reddit` (textarea + .save) |
| Fallback | old_reddit only for explicit A/B test | new_reddit_debugger only for explicit A/B test |
| Task creation | `posting_strategy` = NULL → debugger | `posting_strategy` = "old_reddit" → textarea |
| Extension scheduler | NULL → executeTask() | NULL/old_reddit → executeTaskOldReddit() |
| Debugger permission | Required | Kept (only used when A/B test assigns new_reddit_debugger) |

**Rationale:**
- Old reddit is 10× more reliable (no Shadow DOM, no reCAPTCHA, no isTrusted)
- DOM unchanged for 10+ years — zero maintenance
- chrome.debugger path kept exclusively for A/B test comparison
- Simpler executor experience (no debugger permission warnings)

**Files changed:**
- `ramp_extension/background/scheduler.js` — default strategy = old_reddit
- `app/services/execution_tasks.py` — set `posting_strategy="old_reddit"` on extension tasks
- `app/services/extension_dispatcher.py` — set `posting_strategy="old_reddit"` on created tasks + API response default
- `app/routes/extension_api.py` — API response default "old_reddit"

### Delivery Channel Architecture (July 2, 2026)

Avatar model field: `delivery_channel` (email | extension | both)

| Channel | Behavior |
|---------|----------|
| `email` | ExecutionTask created → email sent to executor_email ~30min before scheduled_at |
| `extension` | ExecutionTask created with `task_lifecycle_status="CREATED"` → extension polls `/tasks` → auto-executes |
| `both` | Task created for extension. If extension offline >30min, `dispatch_due_email_tasks` falls back to email |

Admin UI: Avatar → Posting tab → "Task Delivery Channel" dropdown.

### v3.1 — Draft Review + Auto-Update (July 7, 2026)

**Extension becomes Reviewer + Executor.** Previously extension could only execute pre-approved tasks. Now it can review pending drafts (approve/reject) directly from popup — eliminating the dependency on admin UI for draft approval.

**New capabilities:**

| Feature | What | How |
|---------|------|-----|
| **Draft Review in Popup** | "📝 Review Drafts" section shows pending drafts with Approve/Reject buttons | Fetches from `/api/extension/dashboard` → `pending_drafts`, actions via `/api/extension/drafts/{id}/review` |
| **Bulk Approve** | "Approve All" button for all pending drafts | `POST /api/extension/drafts/approve-all?avatar_username=X` |
| **Auto-Update Check** | Heartbeat response includes `update_available`, `latest_version`, `download_url` | Server compares `extension_version` from heartbeat vs `extension_latest_version` DB setting |
| **Update Banner** | Green banner in popup: "⬆️ Update available (vX.Y.Z) [Download]" | Stored in `chrome.storage.local` from heartbeat response |
| **Portal Bell Notification** | SSE notification "New draft ready for review" pushed after EPG generation (when auto-approve=false) | `_notify_drafts_pending()` in `epg_executor.py` calls `notify_client()` |

**Draft review flow (without autopilot):**
```
EPG build → slot "generated" → draft "pending"
    → Portal bell: "New draft ready for review"
    → Extension popup badge: N drafts
    → User opens popup → sees "Review Drafts" section
    → Approve → draft "approved" → slot "approved" → ExecutionTask created
    → Extension polls tasks → sees new task → scheduler posts at scheduled_at
```

**Backend endpoints added:**
- `POST /api/extension/drafts/{draft_id}/review` — approve/reject single draft (supports edit before approve)
- `POST /api/extension/drafts/approve-all?avatar_username=X` — bulk approve all pending

**Version management:**
- `extension_latest_version` DB setting — server's knowledge of latest version
- `extension_download_url` DB setting — URL for download
- Heartbeat compares: `extension_version < extension_latest_version` → `update_available=true`
- To push update: bump `extension_latest_version` in admin settings, upload new zip to `/static/extension/`

**SBM compliance:**
- P5 (Human Gate) satisfied: executor explicitly approves draft in popup before execution
- P11 (Execution Gate) satisfied: after draft approve, executor still approves task execution via scheduler
- Two human decision points maintained: draft review (📝) → task execution (🔔)

**Files changed (July 7):**
- `app/routes/extension_api.py` — draft review endpoints + version check in heartbeat + `_version_lt()` helper
- `app/services/epg_executor.py` — `_notify_drafts_pending()` portal bell notification
- `ramp_extension/manifest.json` — version 0.3.1
- `ramp_extension/popup/popup.html` — Review Drafts section + update banner
- `ramp_extension/popup/popup.js` — `fetchPendingDrafts()`, `handleApproveAllDrafts()`, `checkHealth()` update check
- `ramp_extension/popup/popup.css` — `.badge--review`, `.task-card--draft`, `.alert--update` styles
- `ramp_extension/background/heartbeat.js` — parse heartbeat response, store update/pause/maintenance state

Migration: `ext04_avatar_delivery_channel.py` (depends on raa01).

### REQUIRED_UI Mode → Executor Approval Mode

**v2:** Executor approves tasks in morning (popup "Approve All") → extension auto-executes at scheduled times → submits → verifies → reports.

P5 (Human Gate) satisfied: executor explicitly approves content before auto-execution.
P11 (Execution Gate) satisfied: explicit Approve action required.

## Spec Location

`.kiro/specs/browser-extension/` — requirements.md, design.md, tasks.md

## Related Incidents

- June 27, 2026: Flaky_Finder_13 CQS improved from LOWEST to LOW (Jenny posted manually). RAMP never detected improvement because frozen avatar = skipped by all diagnostic batch tasks. Batch filters fixed same day. Browser extension decision made to close remaining gaps.
- June 29, 2026: First successful automated comment posted via extension (r/test, Hot-Thought2408). End-to-end flow confirmed working: task poll → approve → navigate → expand composer → insert text → submit → verify → report back.
