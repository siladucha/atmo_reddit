# Requirements Document

## Single Authority Principle

Backend is the only source of truth for:
- Scheduling (when tasks fire)
- State transitions (avatar status changes)
- Validation (reports are untrusted until confirmed)
- Policy enforcement (rate limits, EPG mode, allowed actions)

All other components (extension, executor, external probes) are **untrusted signal sources**. This principle is referenced throughout — not repeated.

---

## System Assumptions (Trust & Failure Model)

1. **Execution nodes are untrusted.** Reports are probabilistic signals, not facts.
2. **All failures are expected, not exceptional.** The system is designed for failure-normal operation.
3. **Backend is sole truth engine.** No state change happens outside backend.
4. **Reddit is adversarial.** DOM changes, session expiry, shadowbans — all normal conditions.
5. **Network is unreliable.** Disconnections, timeouts, partial failures — all handled.
6. **Executor is human.** May go offline, switch accounts, ignore tasks — system adapts.

---

## Architecture Model

```
RAMP = backend-controlled task orchestration system
       over leased Execution Nodes (browser-based runtimes)

Backend (authority):
  - Scheduling
  - Policy (immutable per avatar)
  - Runtime state (mutable per node)
  - State transitions
  - Validation + trust scoring
  - Task signing (HMAC)

Extension (execution):
  - Browser action execution
  - Raw result reporting (untrusted)
  - UI rendering (mode-dependent)
  - Local safety floor (hardcoded 3-min interval)
  - NO scheduling, NO decisions, NO state changes
```

---

## Introduction

Chrome Manifest V3 extension installed on executor machines. Serves as a **leased Execution Node** — receives signed tasks from backend, executes them in browser, reports raw results back.

### Problem Statement

1. **CQS Deadlock** — Frozen avatars excluded from diagnostic tasks → recovery invisible.
2. **Posting Infrastructure** — Proxies ($50-200/mo), OAuth (blocked), API credentials.
3. **Executor Friction** — 8-step manual workflow → delays/drops.
4. **Health Monitoring Gaps** — Frozen avatars excluded from all batch diagnostics.
5. **Fleet Contamination** — 59% dead. Extension eliminates API fingerprint linkage.

## Glossary

| Term | Definition |
|------|-----------|
| Execution Node | Isolated runtime: browser + Reddit session + extension. Identified by `execution_node_id`. Does not decide — executes. |
| Executor | Person operating one or more Execution Nodes. Owns Reddit account(s) and physical device. |
| Reddit Identity | Reddit account — a **resource** within an Execution Node, not a system subject. |
| System action | Backend-initiated diagnostic (CQS probe, health probe). Own rate limits. Runs in any mode. |
| Content action | Comment/post. Subject to daily cap, intervals, active hours, optional approval. |
| Execution lease | Time-limited lock. Expired = task released for re-delivery. Lease is an **attribute**, not a state. |
| EPG Policy Mode | Per-avatar: REQUIRED / OPTIONAL / DISABLED. Immutable until backend changes it. |
| Policy | Long-lived, per-avatar configuration (epg_mode, rate limits, allowed task types). Immutable during session. |
| Runtime | Mutable per-node state (active_account, pause state, online status, queue depth). |

---

## Requirements

### R1 — Communication

- R1.1: HTTPS polling (30-60s). Upgrade path: long-poll/SSE (Phase 2).
- R1.2: JWT authentication (executor token).
- R1.3: Heartbeat every 60s: `execution_node_id`, `active_reddit_username`, `extension_version`, `tasks_in_queue`, `timestamp`.
- R1.4: Tasks from `GET /api/extension/tasks` (server-filtered by active account).
- R1.5: Results to `POST /api/extension/report`.
- R1.6: Works behind NAT/firewall.
- R1.7: TLS only.
- R1.8: Network failure: queue locally, retry with backoff.
- R1.9: Extension does NOT self-schedule. (Single Authority Principle)

### R2 — Diagnostic Probes (System Actions)

Extension executes probes. Backend interprets results via normalization layer.

- R2.1: `diagnostic_probe` task with `probe_type`:
  - `reddit_cqs` — post "What is my CQS?" in r/WhatIsMyCQS, return raw bot reply text.
  - `submission_visibility` — navigate to post in sub /new, return present/absent.
  - `profile_check` — navigate to profile, return karma values + any ban indicators.
- R2.2: Probes execute in background tab (no executor approval).
- R2.3: Extension returns **raw output only**. No parsing, no classification.
- R2.4: Works regardless of avatar frozen/health status.
- R2.5: Reports `auth_expired` if session invalid.
- R2.6: NOT subject to content rate limits. Own limits (1 CQS/hour, 1 health/30min).

**Probe result schema:**
```
DiagnosticResult {
  probe_type: string
  raw_output: string | object    // exact text/DOM state
  execution_metadata: {
    duration_ms: int
    reddit_variant: string       // shreddit/old/redesign
    timestamp: datetime
  }
  // confidence: assigned by backend after normalization, NOT by extension
}
```

### R3 — Comment Posting (Content Action)

- R3.1: Task contains: thread_url, comment_text, reply_to, idempotency_key, task_hash (HMAC), scheduled_at.
- R3.2: Extension validates task_hash (HMAC) before execution. Invalid → reject + error report.
- R3.3: Navigates, fills comment box, submits.
- R3.4: Returns: {status, permalink, comment_id, posted_at, idempotency_key}.
- R3.5: Detects locked/archived/removed → {status: "blocked", reason}.
- R3.6: Holds until `scheduled_at` (from backend).
- R3.7: Approval behavior determined by EPG mode (R12). Extension renders UI accordingly.
- R3.8: Subject to rate limits (R8).
- R3.9: If `active_reddit_username` changes mid-execution → abort → report `account_switch_error`.

### R4 — Health Monitoring (Passive)

- R4.1: Passively observes ban indicators on Reddit pages.
- R4.2: Reports signals with trust model:

```
HealthSignal {
  type: string              // comment_removed, ban_notice, profile_restricted
  value: string | object    // raw observation
  timestamp: datetime
  trust_weight: float       // assigned by BACKEND (not extension), 0.0-1.0
  decay_hours: int          // backend-assigned: signal weight decays over time
}
```

- R4.3: Signals are **untrusted, probabilistic, decaying**. Backend aggregates, weights, and decides.
- R4.4: No forced navigation — passive only.
- R4.5: Backend aggregation model: N signals with weight > threshold over T hours → action.

### R5 — Karma Reporting

- R5.1: Reads karma from profile (comment_karma, link_karma).
- R5.2: Reports as piggyback on health cycle.
- R5.3: Raw measurement only. Backend records.

### R6 — Executor UX (Three Modes)

Mode determined by backend policy (`epg_mode`):

**REQUIRED_UI** (epg_mode = REQUIRED):
- R6.1: Popup shows task queue with approve/reject controls.
- R6.2: Task cards: subreddit, thread title, comment preview, time.
- R6.3: Unapproved tasks expire by backend TTL.

**NOTIFICATION_ONLY** (epg_mode = OPTIONAL):
- R6.4: Tasks auto-execute. Popup shows recent activity + alerts.
- R6.5: Executor notified on failures/warnings.

**MINIMAL** (epg_mode = DISABLED):
- R6.6: No proactive UI except errors. Extension is invisible runtime.
- R6.7: Only surfaces on: auth_expired, dom_error, kill_switch.

**Common (all modes):**
- R6.8: Connection status indicator.
- R6.9: Pause button (stops content, keeps diagnostics).
- R6.10: Badge count.
- R6.11: UI does NOT display business logic (no phase, strategy, "why").

### R7 — Multi-Account Binding

- R7.1: Binding: `(execution_node_id, reddit_username)` = unique pair.
- R7.2: Extension detects active account, reports in heartbeat.
- R7.3: Tasks server-side filtered by active account from last heartbeat.
- R7.4: No automatic account switching. Mismatch → warn + hold.
- R7.5: One executor can run multiple nodes (Chrome profiles).
- R7.6: **If `active_reddit_username` changes during EXECUTING state → abort task → report `account_switch_error`.**

### R8 — Safety & Rate Limits

Content actions (R3):
- R8.1: Daily cap (from backend policy).
- R8.2: Min interval (from backend policy, default 3 min).
- R8.3: Active hours only (from backend policy).
- R8.4: Absolute floor: 1 post / 3 min (hardcoded, non-overridable).

System actions (R2):
- R8.5: Own limits: 1 CQS/hour, 1 health/30min (from backend policy).
- R8.6: Independent of content limits.
- R8.7: Run in any mode including paused.

General:
- R8.8: No action if session expired → `auth_expired`.
- R8.9: Zero credential exfiltration.
- R8.10: Kill switch: `pause_all` stops ALL instantly.
- R8.11: Writes ONLY on signed tasks. Extension cannot generate tasks.

**Backpressure model:**
- R8.12: Max concurrent tasks per node: 1 (sequential execution).
- R8.13: Queue overflow: if local queue > 20 tasks → reject new deliveries until drained.
- R8.14: Priority tiers: `diagnostic > content`. Diagnostics execute first regardless of queue order.

### R9 — Backend API

**Two endpoint classes** (policy vs runtime separation):

Policy endpoints (long-lived config):
- R9.1: `GET /api/extension/policy` — returns immutable per-avatar config:
  ```json
  { "epg_mode": "required", "daily_cap": 3, "min_interval_seconds": 180,
    "active_hours_start": "08:00", "active_hours_end": "22:00",
    "allowed_task_types": ["post_comment", "diagnostic_probe"],
    "cqs_probe_max_per_hour": 1, "health_probe_max_per_30min": 1 }
  ```

Runtime endpoints (mutable state):
- R9.2: `GET /api/extension/tasks` — pending tasks for this node + account.
- R9.3: `POST /api/extension/report` — untrusted results. Idempotency enforced.
- R9.4: `POST /api/extension/heartbeat` — node status + active account.
- R9.5: `POST /api/extension/register` — returns `execution_node_id`.

Behavior:
- R9.6: Extension preferred when online. Email fallback after 30 min offline.
- R9.7: Extension-posted comments auto-update draft + slot (no reconciliation).
- R9.8: HMAC on every task. Extension MUST verify. Invalid = reject.
- R9.9: `lease_expires_at` attribute on task. Expired → released.
- R9.10: Duplicate prevention: same idempotency_key → 200 OK, NOOP.

**Idempotency contract:**
- R9.11: First valid report wins.
- R9.12: All duplicate reports are NOOP (200 OK, no side effects).
- R9.13: Backend is final arbiter of execution truth. If conflict → backend state wins.

### R10 — State Transition Layer

**Measurement (extension) and decisions (backend) are strictly separated.**

Measurement (extension reports raw):
- R10.1: Raw bot reply text (backend extracts CQS via normalization).
- R10.2: Health observations (untrusted, weighted, decaying).
- R10.3: Karma values (factual).
- R10.4: Submission visibility (present/absent).

Decision (backend — Single Authority Principle):
- R10.5: CQS level normalized + recorded by backend.
- R10.6: State transitions require: (a) operator approval, OR (b) dual confirmation.
- R10.7: Single signal NEVER triggers state change. Creates `recovery_candidate`.
- R10.8: Operator notification with evidence.
- R10.9: Auto-unfreeze (Phase 3): CQS improved + PRAW probe passes. Both required.
- R10.10: Operator notified post-factum.

### R11 — Task Lifecycle

```
CREATED → ASSIGNED → EXECUTING → REPORTED → FINALIZED
                         ↓
                    FAILED (terminal)

Separately: EXPIRED (terminal) — triggered by lease timeout
```

**States:**
- CREATED: task exists, no node assigned.
- ASSIGNED: backend assigned to node via `/tasks` response. `lease_expires_at` set. `execution_node_id` set.
- EXECUTING: extension acknowledged, action in progress.
- REPORTED: extension sent result. Awaiting backend validation.
- FINALIZED: backend validated. State change applied. Terminal.
- FAILED: extension reported error. Terminal. May trigger re-creation.
- EXPIRED: `lease_expires_at` passed without report. Terminal. Backend may re-create.

**Note:** "Lease" is an **attribute** (`lease_expires_at` + `execution_node_id`), not a separate state. This avoids LEASED/ASSIGNED ambiguity.

Required fields per task:
- R11.1: `idempotency_key` — unique per delivery attempt.
- R11.2: `lease_expires_at` — deadline for report (attribute, not state).
- R11.3: `execution_node_id` — assigned node (NULL = unassigned).
- R11.4: `task_hash` — HMAC signature.
- R11.5: `scheduled_at` — when to execute.
- R11.6: `task_type` — `post_comment | diagnostic_probe`.
- R11.7: `probe_type` (diagnostics) — `reddit_cqs | submission_visibility | profile_check`.
- R11.8: `priority` — `diagnostic | content`. Diagnostics always first.

### R12 — EPG Policy Mode

Immutable per-avatar policy. Set by backend admin. Delivered via `/api/extension/policy`.

- R12.1: `avatar.policy.epg_mode`: `REQUIRED | OPTIONAL | DISABLED`
- R12.2: REQUIRED → executor approval before execution. Unapproved expire by TTL.
- R12.3: OPTIONAL → auto-execute. Notifications on completion/failure.
- R12.4: DISABLED → pure runtime. No UI except errors.
- R12.5: Mode from backend policy endpoint. Extension never determines locally.
- R12.6: Mode transitions server-side only.

---

## Non-Functional Requirements

### NF1 — Performance
- < 50ms added to Reddit page load.
- Probes complete within 90s.
- Memory < 50MB.
- Poll interval from backend config (default 30s).

### NF2 — Security
- Zero credential exfiltration.
- HTTPS only.
- Minimal permissions: Reddit + RAMP API domains.
- HMAC task verification.
- Extension cannot generate/modify/replay tasks.
- Source available for executor inspection.

### NF3 — Reliability
- MV3 compliant. Survives Chrome updates.
- Recovers from browser restart (chrome.storage.local).
- Reddit DOM: selector fallbacks + `dom_structure_changed` error.
- Idempotent: re-delivery does not duplicate.
- Lease expiry handles crash-during-execution.

### NF4 — Observability
- Local log (popup History).
- Errors to RAMP.
- Admin UI: per-node status.

---

## Out of Scope (MVP)

- Firefox
- Post creation (comments only)
- Voting
- Content editing post-publish
- Mobile browser
- Auto Chrome profile switching
- Auto-mode content (Phase 2 — OPTIONAL/DISABLED modes)
- Long-poll/SSE (Phase 2)
- Auto-unfreeze (Phase 3)
- DOM scraping subreddits (PRAW handles)

## Dependencies

- Backend extension API (R9)
- Executor onboarding (token + install)
- Chrome Web Store ($5)
- Reddit DOM stability (fallback selectors)

## Success Metrics

- CQS latency: 7-10 days → < 24 hours
- Posting friction: 8 steps → 1 click → 0
- Proxy cost: $50-200/mo → $0
- Recovery detection: never → < 7 days
- Task completion: ~60% → >90%
- API write consumption: 100% → 0%
