# System Behavior Model (SBM)

## What This Is

11 properties that must hold true for RAMP-as-a-whole to be operating correctly.
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

**Incidents fixed:**
- June 27: CQS batch filter deadlock (frozen avatars excluded from diagnostic tasks)
- June 28: Health checker false positive deadlock — `zero_content_with_history` incorrectly classified inactive avatars as shadowbanned → froze them → they became more inactive → loop. Fix: API returning ANY data = not shadowbanned (profile 404 = shadowban invariant).
- June 28: Shadowban recovery undetected — Flaky_Finder_13 + connor_lloyd recovered from shadowban weeks earlier, but system never detected recovery because frozen avatars were not re-probed. Now fixed: health checker correctly interprets API responses.

---

### P3: Cost Proportionality

**Statement:** `LLM_cost(day) ≤ k × active_budget(day)` where k ≈ $0.15 per comment slot.

**Violation means:** Money burning without value output (retry loops, failed generations counted as cost).

**Enforcement:** Automated (scheduled + runtime) — hardened July 2, 2026
- `cost_governor.py` enforces $1/day for agent ops (Daily Review)
- `billing_dashboard.py` shows AI cost breakdown per model/operation/client
- Alert: cost/slot > $0.20
- **Budget gate (runtime) — 3-layer defense (R-AI-007, July 2 2026):**
  - Layer 1: Redis call counters — 500 calls/hour, 3000 calls/day. `LLMBudgetExceeded` raised on breach.
  - Layer 2: Cost circuit breaker — $5 per 10-min rolling window in Redis. `LLMRunawayDetected` raised when cost accumulates too fast. Auto-recovers when window rotates.
  - Layer 3: Per-task call counter — max 50 LLM calls per single Celery task invocation (`ContextVar`). Detects infinite loops within one task immediately. No Redis dependency.
- **Single-call cost alert:** Calls > $0.10 logged as WARNING. Calls > $1.00 logged as CRITICAL.
- **Dashboard alert:** `alert_aggregation.py` shows 🔥 when hourly cost > 3× 7-day average OR > $3 absolute.
- **Centralization invariant:** ALL LLM calls go through `call_llm()`/`call_llm_json()` → budget gate enforced universally. See `ai_cost_centralization.md`.
- **`log_ai_usage()`** — mandatory after every successful call. Ensures `/admin/ai-costs` reflects 100% of spend.
- Fail-open on Redis failure (layers 1+2 skip, layer 3 still protects).

**Gap:** None for runaway protection. Fully enforced. Maximum possible damage from any runaway loop: ~$5 (10-min window before circuit breaker trips). Remaining: no per-client daily cost cap (client-level budget controls not yet implemented — spec exists).

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
- Auto-approve requires explicit `auto_approve_drafts=true` on avatar OR `autopilot_enabled=true` on client (client-level overrides avatar-level)
- EPG slot requires status=approved before dispatch
- **Executor email verification (July 4, 2026):** changing executor_email resets `executor_email_verified=false` and blocks ALL task creation until executor confirms via email link. Prevents tasks being sent to wrong person.

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

**Enforcement:** Automated (runtime + external watchdog) — STRENGTHENED July 2, 2026
- Kill switches exist (pipeline_enabled, generation_enabled, scrape_enabled, auto_posting_enabled)
- Feature flags (epg2_enabled, fitness_gate_enabled, email_tasks_enabled)
- Services use try/except with fallback behavior
- **External watchdog (systemd, every 30s):** checks Redis, PG, App, Beat, Workers, Disk. Auto-restarts any dead container. Telegram alert. Tested: cascade kill (all containers) → full recovery in ≤60s.
- **PG backup (daily 03:00):** pg_dump + 14-day rotation. Alert on failure.
- Nginx serves maintenance page when app is unavailable (auto-refresh 10s)

**Gap (partially closed July 2):** ~~No automated failure detection or restart.~~ External watchdog now handles container-level failures. Remaining: no application-level failure injection (chaos testing), no periodic verification that disabling one feature flag doesn't cascade.

---

### P11: Subreddit Intelligence Freshness

**Statement:** For every subreddit where avatars actively post, a `SubredditRiskProfile` exists with `risk_score` computed within ≤14 days.

**Violation means:** Avatars posting blind — no awareness of moderation patterns, dangerous hours, or rule changes. Removal rate spikes undetected.

**Enforcement:** Automated (scheduled) — weekly batch
- `extract_subreddit_rules_batch` (Sun 05:00) — PRAW sidebar/wiki → Gemini Flash → extracted_rules
- `compute_moderation_profiles_batch` (Sun 05:15) — 30-day deletion aggregation, dangerous hours
- `compute_risk_scores_batch` (Sun 05:30) — weighted formula → risk_score + is_high_risk flags
- `fitness_gate.py` — real-time pre-generation gate using cached profile data

**Enforcement of profile existence:**
- Fitness gate is fail-open (no profile → allow generation) — means P4/P5 not violated, but avatar posts without intelligence
- Activity event `fitness_gate_warning` emitted when no profile exists — operator can see in feed

**Gap:** No alert when subreddits have stale or missing profiles. Need: signal_collector check:
```sql
SELECT s.subreddit_name FROM subreddits s
JOIN client_subreddit_assignments csa ON csa.subreddit_id = s.id AND csa.is_active = true
LEFT JOIN subreddit_risk_profiles srp ON srp.subreddit_id = s.id
WHERE srp.id IS NULL OR srp.updated_at < now() - interval '14 days'
```
If count > 0 → alert "N active subreddits have stale/missing risk profiles".

**Relationship to other properties:**
- P1 (Monotonic Progress) — if fitness gate blocks ALL threads for an avatar (risk_score too high + low karma), drafts_generated drops to 0
- P4 (Safety Monotonicity) — fitness gate is an additional safety layer (blocks dangerous subs for low-karma avatars)
- P10 (Graceful Degradation) — fitness gate fail-open ensures missing profile never blocks pipeline
- **Risk-Aware Activation (July 2, 2026)** — `ActivationRouter` uses risk_score for zone classification (safe 0-25, bridge 26-50, target 51-80). Stale profiles degrade zone routing accuracy but don't block (subs without profile default to bridge zone — conservative). Missing weekly batch → avatars may route into subs that changed moderation patterns. P11 freshness directly affects activation routing quality.

---

### P11: Execution Gate Integrity

**Statement:** Between EPG intent and Reddit post, there ALWAYS exists an executor confirmation step (Approve button in extension popup). No path exists where content is auto-published without explicit executor action.

**Violation means:** Autonomous posting via extension without human consent. Legal + safety breach. Extension becomes a bot.

**Enforcement:** Automated (runtime) — structural
- Extension operates in REQUIRED_UI mode only (auto-dispatch was prototyped June 29 then REMOVED)
- Executor must click "Approve" in popup before any post is submitted
- State machine requires `CONTEXT_VERIFIED → EXECUTING` transition, which is gated by UI action
- Backend tasks are delivered as proposals, not auto-executed commands
- Event stream provides full audit trail of every approval action

**Gap:** None. Structural invariant enforced by extension architecture. Auto-dispatch code was removed June 29 after brief prototype — confirmed that no code path exists to bypass the approve step. Code change = only violation vector → caught at review.

**Relationship to P5:** P5 covers the generate→approve gate (draft approval). P11 covers the approve→post gate (execution approval). Together they ensure two human decision points exist in the full pipeline: one at content review, one at posting execution.

**Active Risk (July 4, 2026):** Extension v3 transitioning to old.reddit.com for DOM interaction. An A/B test is planned to validate that posting method (old reddit vs new reddit vs manual) doesn't differentially affect avatar health. If automated posting is detected by Reddit as higher-risk → may need to add human-typing simulation delays or revert to email-only for certain avatar phases.

**Established:** June 29, 2026 (browser extension MVP development session).

---

### P12: Forecast Truth Separation

**Statement:** For any client-facing report or visualization, observed data (📍) is NEVER conflated with projected data (📈). Each value has an explicit provenance label and source layer.

**Violation means:** Client makes decisions based on projected values they believe are measurements. Trust destroyed when reality doesn't match. Legal risk if projections presented as guarantees.

**Enforcement:** Structural (data model) + Manual (review)
- `client_intelligence_reports` table separates layers into independent JSONB columns (observed_json ≠ forecasted_json)
- UI template uses distinct visual markers: solid/bold = measured, dashed/italic = projected
- Every projected value accompanied by confidence interval (never point estimate)
- Forecast accuracy tracked: predicted vs actual stored in `forecast_accuracy_log`
- Report generation blocked if all key sources exceed staleness threshold

**Gap:** System not yet implemented (spec complete July 2, 2026). Once built:
- Runtime enforcement via JSONB schema validation (observed_json cannot contain forecast fields)
- Automated staleness detection blocks report generation if data too old
- Forecast accuracy tracking detects systematic bias and auto-widens confidence intervals

**Relationship to other properties:**
- P1 (Monotonic Progress) — if client sees forecast of "38%" but actual stays at 8% for 12 weeks, P1 is not violated (pipeline running) but P12 IS violated if report doesn't clearly communicate the gap between forecast and reality
- P7 (Isolation) — reports are client-scoped, competitor data comes from same instrument (no cross-client leakage)
- P10 (Graceful Degradation) — if GEO monitoring fails, report degrades to "observed only" (no forecast section) rather than showing stale projections

**Established:** July 2, 2026 (Forecast & Reporting Layer spec session).

---

## Enforcement Summary

| Category | Properties | Action needed |
|----------|-----------|---------------|
| **Runtime (hard block)** | P3, P4, P5, P7, P11 | P3 fully enforced (3-layer: per-task 50 calls, $5/10min circuit breaker, 500/h + 3000/d caps). P4/P5/P7/P11 fully enforced. |
| **Runtime + External Watchdog** | P10 | External systemd watchdog (30s): auto-restart dead containers. Tested July 2 (cascade kill → full recovery ≤60s). Remaining: chaos testing for feature flags |
| **Scheduled (detect + alert)** | P1, P6, P8 | P6 needs alert SQL, P8 needs TZ fix |
| **Structural (data model)** | P12 | Not yet implemented (spec ready). Once built: JSONB separation + schema validation + staleness gate |
| **Manual (review time)** | P2, P9 | Cannot automate — structural reasoning required |

---

## Using SBM

### For Daily Ops Review
Signal collector results → interpret through properties:
- "error rate up 3x" → P1 threatened?
- "5 avatars frozen" → P2 at risk?
- "AI cost spike" → P3 violated?
- "removal rate spike in r/sysadmin" → P11 intelligence stale? fitness_gate not blocking?

### For Architecture Decisions
Before every architectural change, for each property:
- Violates property? → BLOCK
- Weakens property? → DOCUMENT + MITIGATE
- Strengthens property? → GOOD

### For Incident Post-mortem
Every incident maps to ≥1 SBM property. Post-mortem must state which property was violated and what enforcement failed.

### For Tension Detection
SBM property degrading (not fully violated but trending toward violation) = architectural tension. Auto-detectable via signal trends.
