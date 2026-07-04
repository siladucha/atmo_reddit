# RAMP Execution Protocol Spec v1

## Architecture Identity

RAMP Extension is an **event-sourced reconciliation system**:

```
EPG (intent graph) → Execution Stream (observations) → Reconciliation Engine (RAMP backend) → Derived Truth State
```

Extension = **deterministic runtime**. Backend = **event-sourcing engine**. No assumptions about UI stability.

---

## 1. EPG — Execution Plan Graph

**Definition:** EPG = Execution Plan Graph (not "Electronic Program Guide")

**Properties:**
- Built at t0 (planning time)
- Contains a DAG of execution steps
- NOT a truth source at t1 (execution time)
- Used only as "intent graph" — what SHOULD happen
- Backend reconciles EPG intent with execution observations to derive current state

---

## 2. State Machine — Strict Model

### 2.1 Core States

```
INIT → PRECHECK → NAVIGATING → CONTEXT_VERIFIED → EXECUTING → VERIFYING → COMPLETED
                                                                              ↓
                                                                           FAILED
```

| State | Entry condition | Exit condition |
|-------|----------------|----------------|
| INIT | Task received by extension | Precheck started |
| PRECHECK | Auth valid, rate limit clear, capabilities confirmed | All guards pass |
| NAVIGATING | Browser navigating to target URL | Page loaded + context verified |
| CONTEXT_VERIFIED | Page type matches + DOM fingerprint above threshold + auth valid | Execution started |
| EXECUTING | Action in progress (fill text, click submit) | Action completed or error |
| VERIFYING | Post-execution proof collection | Proof validates or mismatch |
| COMPLETED | Proof valid, result reported | Terminal |
| FAILED | Error condition, result reported | Terminal |

### 2.2 Failure Overlay States

Failure states are **orthogonal** to core states — they explain WHY a transition to FAILED occurred:

```
DOM_CHANGED        — selectors failed, page structure unrecognized
THREAD_DELETED     — target thread no longer exists
AUTH_FAILED        — Reddit session expired (401/403/login wall)
RATE_LIMITED       — Reddit or RAMP rate limit hit
SESSION_LOST       — auth cookie missing, inactivity timeout
CAPABILITY_MISSING — required DOM element not present
UNKNOWN_STATE      — unclassifiable error
```

### 2.3 Transition Rules

```
INIT → PRECHECK
PRECHECK → NAVIGATING              (all guards pass)
PRECHECK → FAILED[AUTH_FAILED]     (session invalid)
PRECHECK → FAILED[RATE_LIMITED]    (rate limit active)

NAVIGATING → CONTEXT_VERIFIED      (pageType valid + fingerprint.confidence >= 0.65)
NAVIGATING → FAILED[DOM_CHANGED]   (fingerprint.confidence < 0.65)
NAVIGATING → FAILED[THREAD_DELETED] (404 / removed indicator)

CONTEXT_VERIFIED → EXECUTING       (guards pass)
EXECUTING → VERIFYING              (action completed without error)
EXECUTING → FAILED[DOM_CHANGED]    (submit button not found, etc.)
EXECUTING → FAILED[SESSION_LOST]   (mid-action auth loss)

VERIFYING → COMPLETED              (proof valid)
VERIFYING → FAILED                 (proof mismatch — comment not found post-submit)
```

### 2.4 Guards (mandatory conditions for CONTEXT_VERIFIED)

```
CONTEXT_VERIFIED :=
    pageType == expected
    AND domFingerprint.confidence >= 0.65
    AND authValid == true
    AND targetElement.visible == true
```

---

## 3. Confidence Model

Confidence is NOT a free-form field. It is computed:

```
confidence = weighted(locator_success_score)
```

| Score | Meaning | Locator type |
|-------|---------|-------------|
| 1.0 | `data-testid` exact match | Strongest |
| 0.85 | `aria-label` / `role` match | Strong |
| 0.7 | Semantic text anchor (button text) | Medium |
| 0.5 | Structural heuristic (nth-child, position) | Weak |
| < 0.5 | Invalid match → REJECT | Do not use |

**Rule:** If best available confidence < 0.5, transition to `FAILED[DOM_CHANGED]`.

---

## 4. Proof-of-Execution

### 4.1 Proof Structure

```json
{
  "proof_type": "comment_posted",
  "post_id": "abc123",
  "dom_hash": "sha256:...",
  "screenshot_id": "local-blob-id",
  "timestamp": "2026-06-29T14:05:00Z",
  "confidence": 0.95,
  "extraction_method": "url_parse"
}
```

### 4.2 Storage

- `screenshot_id` → local blob store (Extension IndexedDB)
- Async upload to RAMP storage (optional, non-blocking)
- Backend does NOT block on screenshot — it's evidence, not gate

### 4.3 DOM Hash Definition

```
domHash = SHA-256(normalizedAccessibilityTree)
```

NOT full HTML. Accessibility tree only — stable across minor CSS/layout changes.

### 4.4 Post ID Extraction Priority

1. URL parsing: `/comments/{id}/`
2. DOM attribute: `data-post-id`, `data-comment-id`
3. Fallback: regex on permalink element

---

## 5. DOM Drift Detection

### Page Types

```
pageType ∈ { SUBREDDIT, THREAD, COMPOSER, PROFILE, UNKNOWN }
```

### Fingerprint

```
fingerprint = hash(accessibilityTree, key_landmarks_only)
```

Key landmarks: comment box presence, submit button, thread title, reply controls.

### Threshold

```
if fingerprint.confidence < 0.65 → transition to FAILED[DOM_CHANGED]
```

---

## 6. SESSION_LOST — Deterministic Triggers

```
SESSION_LOST :=
    401 OR 403 on navigation
    OR missing auth cookie (reddit_session / token_v2)
    OR login wall detected (login form in DOM)
    OR inactivity timeout (no page interaction > 30 min)
```

**Detection:** Periodic heartbeat check every 30-60s while task is active.

---

## 7. Capability Protocol — Handshake

### On connect (after activation):

```json
{
  "type": "CAPABILITIES_DECLARED",
  "execution_node_id": "uuid",
  "capabilities": {
    "post_comment": true,
    "post_submission": false,
    "cqs_check": true,
    "visibility_probe": true,
    "karma_read": true,
    "screenshot_capture": true
  },
  "reddit_variant": "shreddit",
  "extension_version": "1.0.0",
  "browser": "Chrome/126"
}
```

Backend uses capabilities to route tasks only to nodes that can execute them.

### Capability mismatch:

If task requires capability the node doesn't have → `FAILED[CAPABILITY_MISSING]`, backend re-routes.

---

## 8. Retry Policy

```json
{
  "maxRetries": {
    "DOM_CHANGED": 2,
    "RATE_LIMITED": 5,
    "SESSION_LOST": 3,
    "THREAD_DELETED": 0,
    "AUTH_FAILED": 1,
    "CAPABILITY_MISSING": 0,
    "UNKNOWN_STATE": 1
  },
  "backoff": {
    "baseMs": 500,
    "maxMs": 10000,
    "jitter": true,
    "formula": "min(baseMs * 2^attempt + random(0, baseMs), maxMs)"
  }
}
```

**Non-retriable:** THREAD_DELETED, CAPABILITY_MISSING — these are permanent conditions.

---

## 9. Visibility (Anti-False-Completion)

A comment is VISIBLE if and only if:

```
VISIBLE :=
    element exists in DOM
    AND not display:none / visibility:hidden
    AND not "removed by moderator" indicator
    AND present in subreddit feed OR thread view (for submissions)
    AND author matches expected avatar username
```

**Post-execution verification:**
1. After submit → wait 3s → check DOM for new comment
2. If comment found with matching text (first 50 chars) → VISIBLE = true
3. If not found after 10s → VISIBLE = uncertain → report with low confidence

---

## 10. Event Schema (Core Events)

### Task Events (Extension → Backend)

```json
{"event": "task_received", "task_id": "...", "timestamp": "...", "state": "INIT"}
{"event": "precheck_passed", "task_id": "...", "guards": {...}, "state": "PRECHECK"}
{"event": "navigation_started", "task_id": "...", "url": "...", "state": "NAVIGATING"}
{"event": "context_verified", "task_id": "...", "fingerprint": {...}, "confidence": 0.9, "state": "CONTEXT_VERIFIED"}
{"event": "execution_started", "task_id": "...", "action": "fill_comment", "state": "EXECUTING"}
{"event": "execution_completed", "task_id": "...", "state": "VERIFYING"}
{"event": "proof_collected", "task_id": "...", "proof": {...}, "state": "COMPLETED"}
{"event": "task_failed", "task_id": "...", "failure_state": "DOM_CHANGED", "details": "...", "state": "FAILED"}
```

### Health Events (Extension → Backend)

```json
{"event": "health_signal", "avatar": "...", "signal_type": "comment_removed", "raw_value": {...}}
{"event": "session_check", "avatar": "...", "auth_valid": true, "cookies_present": true}
```

### Command Events (Backend → Extension)

```json
{"event": "pause_all"}
{"event": "resume"}
{"event": "update_policy", "policy": {...}}
```

---

## 11. Reconciliation Model

Backend reconciles intent (EPG) with observations (execution events):

```
For each EPG slot:
  intent = slot.plan (subreddit, time, text)
  observations = events where task.epg_slot_id == slot.id
  
  derived_state = reconcile(intent, observations)
    → posted (proof valid)
    → failed (all retries exhausted)
    → pending (no observations yet)
    → in_progress (events received, not terminal)
    → expired (lease timeout, no observations)
```

**Rule:** Backend NEVER trusts a single observation. State transitions require:
- Proof-of-execution (post_id extractable + DOM hash) for COMPLETED
- Explicit failure event for FAILED
- Lease timeout for EXPIRED

---

## 12. Implementation Sequence

| Phase | Scope | Outcome |
|-------|-------|---------|
| **P1** (current) | Fix auth + wire tasks to extension | Extension receives tasks, executor approves, posts via Approve button |
| **P2** | Implement state machine + event stream | Each execution emits structured events, backend processes stream |
| **P3** | Add proof model + verification | Screenshots, DOM hash, post-execution visibility check |
| **P4** | Reconciliation engine | Backend derives truth from events, handles drift, auto-retry |
| **P5** | Auto-mode (no approve) | Full autonomous execution with event audit trail |

---

## 13. Files to Create (Implementation)

| File | Purpose |
|------|---------|
| `ramp_extension/background/state-machine.js` | XState-compatible statechart |
| `ramp_extension/background/event-emitter.js` | Structured event creation + queue |
| `ramp_extension/content/dom-fingerprint.js` | Accessibility tree hashing |
| `ramp_extension/content/proof-collector.js` | Post-execution proof extraction |
| `ramp_extension/content/visibility-check.js` | Anti-false-completion verification |
| `reddit_saas/app/services/execution_reconciler.py` | Event-sourcing reconciliation engine |
| `reddit_saas/app/routes/extension_events.py` | Event ingestion endpoint |

---

## Summary

Extension is a **deterministic runtime** that:
1. Receives signed task intent
2. Executes through strict state machine
3. Emits structured events at every transition
4. Collects proof-of-execution
5. Reports observations (never claims truth)

Backend is an **event-sourcing engine** that:
1. Creates intent (EPG slots → tasks)
2. Ingests execution events
3. Reconciles intent vs observations
4. Derives truth (posted / failed / unknown)
5. Triggers retry / fallback / escalation

Neither side makes assumptions about the other. The protocol is the contract.
