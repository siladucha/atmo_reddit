# System Behavior Model (SBM)

## What This Is

10 properties that must hold true for RAMP-as-a-whole to be operating correctly.
These are system-level invariants, not component health checks.

SBM is the compass for the Meta-loop: architectural tension = SBM property under threat.

---

## Properties

### P1: Monotonic Progress

**Statement:** For every active client with ≥1 healthy avatar, `drafts_generated(7d) > 0`.

**Violation means:** System is dead for that client. Pipeline not producing value.

**Enforcement:** Automated (scheduled)
- Detector: `alert_aggregation.py` — "paying clients with 0 posts in 7d"
- Signal collector checks daily

**Gap:** Alert is advisory. No escalation path if ignored >48h. Need: auto-escalation (notify partner after 48h, freeze client pipeline after 72h to prevent silent death).

---

### P2: Recovery Reachability

**Statement:** For any avatar in any state (except suspended/deactivated), there exists a path back to Phase 1+ without manual intervention.

**Violation means:** Deadlock. Avatar stuck forever. (CQS deadlock June 27 was this.)

**Enforcement:** Manual (code review)
- At every PR that adds skip/filter/gate to diagnostic tasks: reviewer asks "does this create a deadlock for frozen/shadowbanned avatars?"
- Principle: "Diagnostic systems must NEVER be gated by the condition they diagnose"

**Gap:** No automated detector possible without formal state machine reachability analysis. Cost of formalization > value at current scale. Caught via incidents + P9 as secondary signal.

---

### P3: Cost Proportionality

**Statement:** `LLM_cost(day) ≤ k × active_budget(day)` where k ≈ $0.15 per comment slot.

**Violation means:** Money burning without value output (retry loops, failed generations counted as cost).

**Enforcement:** Automated (scheduled) — partial
- `cost_governor.py` enforces $1/day for agent ops (Daily Review)
- `billing_dashboard.py` shows AI cost breakdown
- Alert: cost/slot > $0.20

**Gap:** No hard circuit breaker on pipeline LLM calls. If Gemini Flash errors trigger retries, cost accumulates without output. Need: per-task cost cap + daily pipeline cost ceiling with auto-pause.

---

### P4: Safety Monotonicity

**Statement:** If `avatar.phase = N`, then ALL content restrictions for phase N are enforced. No path exists where Phase 1 avatar receives brand content.

**Violation means:** Brand safety breach. Legal exposure.

**Enforcement:** Automated (runtime) — full
- `safety_blocks.py` blocks brand content for Phase 1/2
- `posting_safety.py` gate 5: Phase 0 exclusion
- Generation prompt assembly includes phase-appropriate constraints
- Runtime assertion in `generate_comment()`

**Gap:** None. This property is fully enforced. Can only be violated by code change → caught at review.

---

### P5: Human Gate Integrity

**Statement:** Between generate and post, there ALWAYS exists a human decision point. Auto-approve = explicit configured policy, not bypass.

**Violation means:** Autonomous posting without consent. Legal + safety breach.

**Enforcement:** Automated (runtime) — structural
- `POSTING_DISABLED` env var (gate 0 in posting_safety)
- `draft_approval_enabled` per client (DB flag)
- Auto-approve requires explicit `auto_approve_drafts=true` on avatar
- EPG slot requires status=approved before dispatch

**Gap:** None. Structural invariant. Code change = only violation vector → caught at review.

---

### P6: Feedback Closure

**Statement:** Every posted comment receives outcome measurement (karma snapshot) within ≤48h.

**Violation means:** System is blind to results. Learning loop broken. EPG model correction stale.

**Enforcement:** Automated (scheduled) — partial
- `snapshot_comment_outcomes` runs every 4h, covers 4h/24h/48h/7d windows
- Checks up to 100 comments per run

**Gap:** No alert when comments fall through (posted >48h, 0 snapshots). Need: SQL query in signal_collector:
```sql
SELECT COUNT(*) FROM comment_drafts cd
WHERE cd.status = 'posted'
  AND cd.posted_at < now() - interval '48 hours'
  AND cd.id NOT IN (SELECT DISTINCT draft_id FROM karma_snapshots WHERE draft_id IS NOT NULL)
```
If count > 0 → alert "feedback closure broken for N comments".

---

### P7: Isolation Guarantee

**Statement:** Client A never sees Client B data. Avatar assigned to Client A never generates content for Client B.

**Violation means:** Data breach. Trust destruction.

**Enforcement:** Automated (runtime) — full
- `query_scope.py` scopes all DB queries by client_id
- `isolation.py` runtime assertions (avatar↔client ownership)
- Property-based tests in test suite

**Gap:** None. Strongest enforcement in the system.

---

### P8: Temporal Consistency

**Statement:** If action X scheduled at time T, then `dispatch(X) ∈ [T-5min, T+35min]`. No emails at executor's night time.

**Violation means:** Spam burst, 2AM emails, executor trust erosion.

**Enforcement:** Automated (runtime) — partial
- Quiet hours gate (23:00-07:00 Israel time) in `dispatch_due_email_tasks`
- Dispatch window check [now-5min, now+30min]
- Jitter in timing_engine (±30%)

**Gap:** No executor timezone validation. Slot timezone (avatar persona) ≠ executor timezone (real human). Flaky_Finder_13 incident June 25: persona=NY, executor=Israel → 2AM emails. Fix: use executor timezone for dispatch gate, not avatar timezone.

---

### P9: Diagnostic Independence

**Statement:** For any diagnostic system D designed to detect condition C: `D.can_run(avatar)` MUST NOT depend on `C(avatar)`.

**Violation means:** "Patient too sick to examine." Recovery invisible to system.

**Enforcement:** Manual (principle + code review)
- Principle established June 27, documented in steering
- Code review checklist: "Does this filter exclude the avatar state being diagnosed?"

**Gap:** No automated detector. Would require meta-annotation on every filter ("this filter checks the condition being diagnosed"). Cost > benefit. Caught through P2 (reachability) when deadlock actually occurs.

---

### P10: Graceful Degradation

**Statement:** If component X is unavailable, remaining system continues (degraded quality, no cascade failure). Kill switch for X must not break Y.

**Violation means:** Single point of failure cascades. System-wide outage from local problem.

**Enforcement:** Partial (runtime + manual)
- Kill switches exist (pipeline_enabled, generation_enabled, scrape_enabled, auto_posting_enabled)
- Feature flags (epg2_enabled, fitness_gate_enabled, email_tasks_enabled)
- Services use try/except with fallback behavior

**Gap:** No automated failure injection (chaos testing). No periodic verification that disabling one component doesn't cascade. Manual verification at architecture review time.

---

## Enforcement Summary

| Category | Properties | Action needed |
|----------|-----------|---------------|
| **Runtime (hard block)** | P4, P5, P7 | None — fully enforced |
| **Scheduled (detect + alert)** | P1, P3, P6, P8 | P6 needs alert SQL, P3 needs circuit breaker, P8 needs TZ fix |
| **Manual (review time)** | P2, P9, P10 | Cannot automate — structural reasoning required |

---

## Using SBM

### For Daily Ops Review
Signal collector results → interpret through properties:
- "error rate up 3x" → P1 threatened?
- "5 avatars frozen" → P2 at risk?
- "AI cost spike" → P3 violated?

### For Architecture Decisions
Before every architectural change, for each property:
- Violates property? → BLOCK
- Weakens property? → DOCUMENT + MITIGATE
- Strengthens property? → GOOD

### For Incident Post-mortem
Every incident maps to ≥1 SBM property. Post-mortem must state which property was violated and what enforcement failed.

### For Tension Detection
SBM property degrading (not fully violated but trending toward violation) = architectural tension. Auto-detectable via signal trends.
