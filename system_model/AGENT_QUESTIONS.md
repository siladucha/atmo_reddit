# RAMP Agent — Open Questions & Architectural Concerns

From the perspective of the RAMP system agent (the entity that maintains and evolves this codebase), these are unresolved questions that affect system correctness, scalability, and business logic.

---

## Priority 1: Safety & Correctness

### Q1: EPG Race Condition (GAP-003)
**Question:** Should we implement `pg_advisory_lock(avatar_id)` wrapping `build_portfolio()` call, as recommended by external analyst?

**Context:** If Celery Beat fires `build_and_generate_epg_all_avatars` while previous run is still executing (slow LLM responses), two EPG builds for same avatar can run in parallel → duplicate slots → avatar exceeds daily cap → ban risk.

**My recommendation:** Yes. 10 lines of code. Zero infra dependency. Use integer hash of avatar UUID for advisory lock key.

**Status:** Accepted, not implemented.

---

### Q2: Kill Switch Propagation Latency
**Question:** Should we add a Redis check (`ramp:kill:posting_disabled`) immediately before `praw.submit()` in posting.py?

**Context:** Current kill switch takes up to 5 minutes to propagate (next task execution). If an incident requires INSTANT stop, there is a window where posts can still go out.

**My recommendation:** Yes. 3 lines of code. Redis GET before submit. Cost: 1 Redis RTT per post (~0.5ms).

**Status:** Accepted, not implemented.

---

### Q3: Draft Reconciliation False Positives
**Question:** Can 3-pass matching produce false positives that incorrectly mark a draft as "posted" when it wasn't?

**Context:** Pass 3 (thread + timing) uses 75% confidence with ±72h window + similar length. In theory, if executor posts a DIFFERENT comment in same thread within 72h with similar character count, system could false-match.

**Assessment:** Low risk (requires exact thread match + time window + length similarity). But no manual override to un-reconcile exists.

---

## Priority 2: Architecture & Scale

### Q4: Orchestration Visibility
**Question:** How do we answer "what is the system doing right now?" without querying 5+ tables?

**Context:** No single view exists. To understand current state requires checking: EPGSlot statuses, CommentDraft statuses, ExecutionTask statuses, Celery task queue, Redis locks.

**Options:**
- A) Build a "System Pulse" view (existing Live Pulse in Decision Center — partially does this)
- B) Add centralized PipelineRun entity tracking state across stages
- C) Accept current state as adequate for <50 clients

---

### Q5: Prompt Version Tracking
**Question:** When we change a prompt (e.g., COMMENT_WRITER_PROMPT), how do we know if the change improved or degraded output quality?

**Context:** Currently: no tracking. CorrectionPatterns trained on old prompt will pollute learning for new prompt. No way to compare draft quality pre/post prompt change.

**Minimal fix:** Add `prompt_version` field to CommentDraft. When prompt changes, bump version. Query: "avg karma by prompt_version" answers the question.

---

### Q6: Multi-Client Avatar Conflicts
**Question:** If Avatar X has `client_ids = [ClientA, ClientB]` and both clients are in cybersecurity niche, can the system generate content for ClientA that conflicts with ClientB's strategy?

**Context:** `isolation.py` ensures LLM context assembly only sees ONE client at a time. But the avatar's karma/reputation is SHARED. If ClientA's strategy causes removals, ClientB suffers.

**Assessment:** Theoretical risk. No current clients share avatars across competing niches. But no detection mechanism exists.

---

## Priority 3: Business Logic

### Q7: Phase Promotion Criteria Transparency
**Question:** What exactly are the promotion thresholds per phase?

**Context:** `PhaseEvaluator.get_thresholds()` reads from code but thresholds are not exposed in admin UI or in this JSON. Operator cannot predict when an avatar will promote.

**Should we:** Expose thresholds in admin UI? Or keep as internal implementation detail?

---

### Q8: Feedback Loop Effectiveness
**Question:** Is the feedback loop (epg_adjustments in Redis) actually improving outcomes? No A/B test exists.

**Context:** `run_feedback_loop_all` runs daily. Updates subreddit weights. But we cannot measure if weighted allocation produces better karma than uniform allocation. We're flying blind on whether this mechanism helps or adds noise.

**Options:**
- A) Add 10% random allocation (control group) alongside 90% weighted
- B) Track "karma before feedback vs after" longitudinally
- C) Accept as "probably helps" and move on

---

### Q9: Hobby Pipeline ROI
**Question:** Is the hobby pipeline (1-3 Gemini Flash comments/day) actually warming avatars effectively?

**Measurement needed:** Compare time-to-phase-2 for avatars WITH hobby pipeline vs hypothetical baseline. Currently no baseline exists.

---

### Q10: Strategy Context Staleness
**Question:** When does `client.strategy_context` become stale? No automatic refresh trigger exists.

**Current state:** Strategy generated once (on discovery handoff). If market changes, strategy stays the same until manually regenerated (max 1/week). No staleness detection.

**Options:**
- A) Add `strategy_expires_at` field, alert on expiry
- B) Tie strategy refresh to discovery (already weekly) — force regeneration if hypotheses changed
- C) Accept current manual trigger as sufficient

---

## Meta: What This Document Is

These are not bugs. They are **architectural decision points** where the system's current behavior is correct-by-implementation but potentially sub-optimal or risky at scale.

Each question has:
- Clear context (what exists now)
- Risk assessment
- Options for resolution
- My (agent's) recommendation where applicable

**For Max:** Review P1 questions (Q1-Q3) for implementation. P2 (Q4-Q6) for design decisions. P3 (Q7-Q10) for business priorities.

**For Tzvi:** Q7 (transparency), Q8 (ROI measurement), Q9 (warming effectiveness) are business-relevant.
