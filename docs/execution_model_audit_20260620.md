# Execution Model Audit — EPG/IPG + Marketplace + Auto-posting

**Date:** 2026-06-20
**Scope:** ExecutionTask system, automated posting, verification, billing readiness
**Verdict:** 6 architectural problems found, 3 critical race conditions, 0 billing vulnerabilities (billing not yet implemented)

---

## 1. Source of Truth (CRITICAL)

### Current state

The system has **TWO sources of truth** for "task completed":

| Path | Source of truth | Location |
|------|----------------|----------|
| **AUTO posting** | PRAW API success response (reddit `comment.id` returned) | `app/services/posting.py` line ~110: `comment = submission.reply(comment_text)` |
| **HUMAN/MARKETPLACE** | Executor self-reports URL → PRAW read verification | `app/services/execution_tasks.py`: `submit_url()` → future `verify_full()` |

### Problem

- AUTO path: truth = Reddit API returns `comment.id` → immediate `draft.status = "posted"`, `slot.status = "posted"`
- HUMAN path: truth = executor says "I posted" → system verifies via PRAW read

**These are DIFFERENT trust models.** AUTO path trusts the system's own PRAW session (fully reliable). HUMAN path trusts executor's self-report validated by read-back.

### Missing: Unified POST_CONFIRMED event

There is no single `POST_CONFIRMED` event that both paths emit. Instead:
- AUTO: updates `draft.status`, `slot.status`, creates `PostingEvent` — all in one transaction
- HUMAN: updates `task.status` → verified, then separately updates `draft.status`, `slot.status`

### Recommendation (patch level)

Add an `execution_source` field to track WHO actually posted:

```python
# On CommentDraft or PostingEvent:
execution_source: str  # "auto" | "human_executor" | "marketplace_provider"
execution_source_id: UUID  # PostingEvent.id or ExecutionTask.id
```

Both paths should emit the same finalization logic:
```python
def confirm_post(db, draft_id, slot_id, reddit_url, execution_source, source_id):
    """Single source of truth: comment confirmed on Reddit."""
    # Atomic: update draft + slot + emit event
```

---

## 2. Execution Mode Separation

### Current state

`execution_mode` is **NOT stored anywhere** explicitly.

| Component | How mode is determined | Problem |
|-----------|----------------------|---------|
| Avatar | `avatar.posting_mode == "auto"` | Only controls auto-posting eligibility |
| EPGSlot | No execution_mode field | Doesn't know if it should go AUTO or HUMAN |
| ExecutionTask | Exists only for HUMAN path | Its existence implies HUMAN mode |

### Problem

The system determines execution mode **implicitly**:
- If `email_tasks_enabled=true` → creates ExecutionTask (HUMAN path activated)
- If `avatar.posting_mode="auto"` + proxy configured → auto-posting runs in parallel
- **BOTH can fire for the same slot** (by design, "first wins")

But there's no explicit `slot.execution_mode` that says "this slot should be executed by X".

### Race condition #1: Both paths execute the same slot

```
T+0:  slot.status = "approved"
T+0:  ExecutionTask created (HUMAN path)
T+2m: execute_pending_posts finds slot (AUTO path)
T+3m: AUTO posts comment successfully → slot.status = "posted"
T+45m: Executor also posts the comment → duplicate comment on Reddit
T+50m: Executor submits URL → verification sees THEIR comment (passes!)
```

**Result:** Two comments posted for one slot. Both "verified" from their perspective.

### Current mitigation (partial)

- `post_comment` task checks `if slot.status == "posted": return` (line in tasks/posting.py)
- But ExecutionTask verification does NOT check slot.status before confirming

### Recommendation (patch level)

Add to `verify_full()` and `submit_url()`:
```python
# Before accepting verification:
slot = db.query(EPGSlot).get(task.epg_slot_id)
if slot.status == "posted":
    task.status = "cancelled"
    task.cancel_reason = "slot_already_posted_by_auto"
    return  # Don't double-post
```

Add to `execute_pending_posts` (already partially there):
```python
# Before dispatching:
existing_task = db.query(ExecutionTask).filter(
    ExecutionTask.epg_slot_id == slot.id,
    ExecutionTask.status == "verified"
).first()
if existing_task:
    continue  # Already posted by executor
```

---

## 3. Billing Correctness

### Current state

**Billing is NOT implemented.** The `cost_per_task` field on ExecutionTask is nullable and unused.

### Future vulnerability (design-time)

When marketplace billing is added, the billable event MUST be:
```
POST_CONFIRMED (reddit_comment_url exists + PRAW verified) 
  AND execution_source == "marketplace_provider"
  AND task.status == "verified"
  AND NOT already_billed (idempotency)
```

### Problems in current design that would enable incorrect billing

1. **No `billed_at` field** — no idempotency guard against double billing
2. **No `execution_source` on PostingEvent** — can't distinguish who actually posted
3. **Verification currently allows the same URL to verify multiple tasks** (theoretical — UNIQUE on epg_slot_id prevents in practice, but no check on reddit_comment_url uniqueness across tasks)

### Recommendation (patch level, prepare for billing)

```python
# Add to ExecutionTask model:
billed_at: DateTime | None  # Set once when billing event created
billing_event_id: UUID | None  # FK to future billing_events table

# Add to PostingEvent model:
execution_source: String(50)  # "auto" | "human" | "marketplace"
execution_task_id: UUID | None  # FK to execution_tasks (if human/marketplace)
```

---

## 4. Race Conditions

### Race #1: AUTO wins before HUMAN (described above)

**Impact:** Duplicate Reddit comment.
**Mitigation needed:** Check `slot.status` before executor verification confirms.

### Race #2: Two Celery workers process same delivery

**Current mitigation:** UNIQUE(task_id, attempt_number) on DeliveryAttempt → IntegrityError caught.
**Verdict:** ✅ Properly handled.

### Race #3: expire_overdue_tasks runs while executor is submitting

```
T+0: Task deadline passes
T+0: Celery expire job starts, loads task (status=accepted)
T+0: Executor clicks Submit (concurrent request)
T+1: Executor's submit_url() commits (status=submitted)
T+2: Expire job commits (status=expired) — OVERWRITES submitted!
```

**Impact:** Executor loses their work. Task incorrectly marked expired.

**Mitigation needed:** Use optimistic locking or check status in expire:
```python
# In expire_overdue_tasks:
# Instead of loading all + updating, use atomic UPDATE with WHERE
db.query(ExecutionTask).filter(
    ExecutionTask.status.in_(active_statuses),
    ExecutionTask.deadline < now,
    ExecutionTask.submitted_url.is_(None),  # Don't expire if URL already submitted
).update({"status": "expired", "status_changed_at": now})
```

---

## 5. Email as Transport vs Execution Logic

### Current state

Email is **correctly separated** as transport only:
- `email_sender.py` — pure SMTP transport (send_email returns success/message_id)
- `DeliveryAttempt` — delivery tracking (channel-agnostic)
- `ExecutionTask` — execution logic (status, verification, billing)

### Verdict: ✅ Clean separation

Email does NOT influence execution_mode or billing. It's purely a notification channel. The status transitions are on ExecutionTask, not on DeliveryAttempt.

---

## 6. Marketplace Trust Model

### Current state

Verification is **two-stage** (designed but not yet implemented):
1. Stage 1: URL exists, accessible, correct subreddit, correct author
2. Stage 2: Text similarity >60%, not [removed], not [deleted]

### Attacks NOT currently defended against

| Attack | Current defense | Gap |
|--------|----------------|-----|
| Fake permalink (made-up URL) | Stage 1: PRAW fetch fails | ✅ Defended |
| Wrong subreddit | Stage 1: subreddit check | ✅ Defended |
| Wrong author | Stage 1: author match | ✅ Defended |
| Reused URL from old task | **NONE** | ❌ VULNERABILITY |
| Heavily edited text | Stage 2: 60% threshold | ✅ Defended (threshold may need tuning) |
| Deleted after verification | Not checked post-verification | ⚠️ Partial (KarmaSnapshot catches at 4h/24h) |

### Critical gap: URL reuse

An executor could:
1. Post comment for Task A
2. Get verified for Task A
3. Submit SAME URL for Task B (different task, same comment)
4. System verifies: URL exists, author matches, subreddit matches → PASS

**This allows marketplace executors to get paid twice for one post.**

### Recommendation (patch level)

```python
# Before verification, check URL uniqueness:
existing = db.query(ExecutionTask).filter(
    ExecutionTask.submitted_url == reddit_url,
    ExecutionTask.status == "verified",
    ExecutionTask.id != task.id,
).first()
if existing:
    return VerificationResult(passed=False, failure_reason="URL already used for another task")
```

---

## 7. Observer Layer (Watcher)

### Current state

**There is NO independent observer that scans Reddit for our avatars' comments.**

The system relies on:
- AUTO path: trusts its own PRAW response (sufficient)
- HUMAN path: trusts executor's submitted URL + read-back verification (vulnerable to URL reuse)

### What's missing

A proper marketplace trust model needs:
```
Independent Observer:
  every N hours:
    for each avatar:
      fetch recent comments via PRAW
      for each comment:
        match against pending/verified execution tasks
        if match found: emit POST_CONFIRMED
        if unmatched comment found: log anomaly
```

### Current partial coverage

`snapshot_comment_outcomes` (Celery Beat every 4h) does scan posted comments for karma/deletion — but it only checks ALREADY VERIFIED tasks. It does NOT independently discover posts.

### Recommendation (refactor level — not MVP)

For marketplace launch, add a `confirm_execution_observer` task:
- Runs every 30 min
- For tasks in `submitted` status: independently fetch avatar's recent comments
- Match by thread_id + timestamp proximity + text similarity
- This eliminates dependency on executor's self-reported URL entirely

### Recommendation (patch level — MVP sufficient)

For now, the two-stage verification is sufficient IF URL reuse is blocked (see #6 above). The executor must provide a valid URL, system confirms it exists with correct author/text. This is good enough for internal executors (admin, avatar_owner). For external marketplace providers, add the observer before launch.

---

## 8. Idempotency

### Current guards

| Operation | Idempotency mechanism | Verdict |
|-----------|----------------------|---------|
| Create ExecutionTask | UNIQUE(epg_slot_id) | ✅ |
| Create DeliveryAttempt | UNIQUE(task_id, attempt_number) | ✅ |
| Auto-post same slot | `if slot.status == "posted": return` | ✅ |
| Verify same task twice | Status check (verified is terminal) | ✅ |
| POST_CONFIRMED → billing | **NOT YET IMPLEMENTED** | ⚠️ Design needed |

### Gap: Multiple POST_CONFIRMED for same slot

If both AUTO and HUMAN succeed (race #1), there could be:
- 1 PostingEvent (auto) + 1 verified ExecutionTask (human)
- Both claim credit for the slot

**Mitigation:** The slot can only be "posted" once. Whoever gets there first wins. But we need to ensure only ONE billing event is generated regardless of how many confirmations arrive.

### Recommendation

```python
# Future billing guard:
if slot.status == "posted" and slot.billing_event_id is not None:
    return  # Already billed, skip
```

---

## 9. State Machine Consistency

### Current state

States are defined in TWO places:
1. `ExecutionTask.status` field comment: `generated|emailed|accepted|submitted|url_verified|content_verified|verified|failed|expired|needs_regeneration|cancelled`
2. `_transition_status()` function handles transitions but has NO validation of allowed transitions

### Problem

No formal state machine. Any code can set any status. Example:
```python
task.status = "verified"  # Nothing prevents going from "generated" → "verified" directly
```

### Recommendation (patch level)

Add transition validation:
```python
ALLOWED_TRANSITIONS = {
    "generated": {"emailed", "expired", "cancelled"},
    "emailed": {"accepted", "expired", "cancelled"},
    "accepted": {"submitted", "expired", "cancelled"},
    "submitted": {"url_verified", "failed", "expired", "cancelled"},
    "url_verified": {"content_verified", "failed", "cancelled"},
    "content_verified": {"verified", "failed", "cancelled"},
    # Terminal states: no transitions out
    "verified": set(),
    "failed": {"submitted"},  # Allow retry
    "expired": set(),
    "cancelled": set(),
}

def _transition_status(db, task, new_status, by="system"):
    allowed = ALLOWED_TRANSITIONS.get(task.status, set())
    if new_status not in allowed:
        raise ValueError(f"Invalid transition: {task.status} -> {new_status}")
    # ... existing logic
```

---

## 10. Economic Correctness

### Explicit formulation

**Marketplace provider receives payment ONLY when ALL of these are true:**

1. `execution_task.executor_type == "marketplace_provider"` (task was assigned to marketplace)
2. `execution_task.status == "verified"` (full two-stage verification passed)
3. `execution_task.submitted_url` is not NULL and verified via PRAW
4. `execution_task.billed_at` is NULL (not already billed — idempotency)
5. The linked `epg_slot.status == "posted"` (slot is finalized)
6. The `submitted_url` is NOT used by any other verified task (URL uniqueness)

**Auto system "wins" when:**
- `slot.status` becomes "posted" via `execute_post()` (PRAW success)
- Any pending ExecutionTask for the same slot is auto-cancelled at next expire cycle

**If both channels execute the same slot:**
- Two Reddit comments exist (duplicate)
- Only the FIRST to mark `slot.status = "posted"` gets credit
- Second confirmation is rejected (slot already posted)
- NO double billing (future: billed_at idempotency guard)

---

## Summary of Findings

### Critical (fix before marketplace launch)

| # | Issue | Risk | Fix complexity |
|---|-------|------|---------------|
| 1 | No URL reuse prevention | Double billing | S — add URL uniqueness check in verification |
| 2 | Race: AUTO + HUMAN both post | Duplicate Reddit comments | S — check slot.status before verification confirms |
| 3 | Race: expire overlaps with submit | Lost executor work | S — atomic UPDATE with WHERE guard |

### Important (fix before 10+ executors)

| # | Issue | Risk | Fix complexity |
|---|-------|------|---------------|
| 4 | No execution_source on PostingEvent | Can't attribute who posted | S — add field |
| 5 | No state machine validation | Invalid status transitions possible | S — add ALLOWED_TRANSITIONS dict |
| 6 | No billed_at idempotency field | Future double billing | S — add nullable column now |

### Design-Level (before marketplace GA)

| # | Issue | Risk | Fix complexity |
|---|-------|------|---------------|
| 7 | No independent observer | Relies on executor self-report | M — new Celery task |
| 8 | No unified confirm_post() function | Two different finalization paths | M — refactor |
| 9 | No explicit execution_mode on slot | Implicit "both paths fire" | S — add field, default "auto" |

---

## Proposed Patches (minimal, preserves current architecture)

### Patch 1: URL uniqueness check (Critical)
```python
# In task_verification.py verify_full():
existing = db.query(ExecutionTask).filter(
    ExecutionTask.submitted_url == reddit_url,
    ExecutionTask.status == "verified",
    ExecutionTask.id != task.id,
).first()
if existing:
    return VerificationResult(passed=False, failure_reason=f"URL already verified for task {existing.task_code}")
```

### Patch 2: Check slot.status before confirming (Critical)
```python
# In task_verification.py after verification passes:
slot = db.query(EPGSlot).get(task.epg_slot_id)
if slot.status == "posted":
    _transition_status(db, task, "cancelled", by="system")
    task.cancel_reason = "slot_already_posted_by_other_channel"
    db.commit()
    return VerificationResult(passed=False, failure_reason="Slot already posted")
```

### Patch 3: Atomic expire with guard (Critical)
```python
# Replace current expire loop with atomic UPDATE:
count = db.query(ExecutionTask).filter(
    ExecutionTask.status.in_(("generated", "emailed", "accepted")),
    ExecutionTask.deadline < now,
    ExecutionTask.submitted_url.is_(None),
).update({"status": "expired", "status_changed_at": now}, synchronize_session="fetch")
```

### Patch 4: Add execution_source to PostingEvent
```python
# In app/models/posting_event.py:
execution_source: Mapped[str | None] = mapped_column(String(50), nullable=True)  # auto|human|marketplace
execution_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
```

### Patch 5: State machine validation
```python
# In execution_tasks.py, add ALLOWED_TRANSITIONS dict (shown above)
# Modify _transition_status to validate
```

### Patch 6: Prepare billing fields
```python
# In app/models/execution_task.py (already has cost_per_task):
billed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
billing_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
```

---

## Ideal Version (refactor level, NOT needed for MVP)

```python
# Unified execution confirmation:
def confirm_post(db, slot_id, reddit_url, execution_source, source_id):
    """Single entry point for POST_CONFIRMED regardless of channel."""
    slot = db.query(EPGSlot).with_for_update().get(slot_id)
    if slot.status == "posted":
        return None  # Already confirmed by another channel
    
    slot.status = "posted"
    slot.posted_at = now()
    
    draft = db.query(CommentDraft).get(slot.draft_id)
    draft.status = "posted"
    draft.posted_at = now()
    draft.reddit_comment_url = reddit_url
    
    event = PostingEvent(
        slot_id=slot_id,
        execution_source=execution_source,
        execution_task_id=source_id if execution_source != "auto" else None,
        reddit_comment_url=reddit_url,
    )
    db.add(event)
    
    # Cancel any competing execution tasks
    if execution_source == "auto":
        pending_tasks = db.query(ExecutionTask).filter(
            ExecutionTask.epg_slot_id == slot_id,
            ExecutionTask.status.notin_(["verified", "cancelled", "expired"]),
        ).all()
        for t in pending_tasks:
            t.status = "cancelled"
            t.cancel_reason = "slot_posted_by_auto"
    
    db.commit()
    return event
```

This unified function would replace the duplicated finalization logic in both `posting.py` and `task_verification.py`. But it requires refactoring existing working code — defer until marketplace launch.
