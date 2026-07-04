# Meta-Loop — Architecture Evolution Process

## What This Is

The Meta-loop governs how RAMP's architecture changes over time.
It is the layer ABOVE the operational loop (SENSE→DECIDE→GENERATE→EXECUTE→LEARN).

The operational loop processes content. The Meta-loop processes the system itself.

---

## Process Model

```
OBSERVE → TENSION → PROPOSE → COMMIT
   ▲                              │
   └──────── feedback ────────────┘
```

### OBSERVE — Detect architecture pressure

| Source | Mechanism | Automation |
|--------|-----------|------------|
| SBM scheduled check fails | Signal collector detects threshold breach | Automated (Phase 2 Daily Review) |
| Incident occurs | Ops log written → tension extracted in post-mortem | Manual |
| Code review catches structural issue | Reviewer creates tension | Manual |
| External change (Reddit API, model deprecation) | Observation → manual entry | Manual |
| Recurring alert (same alert 3+ days) | Pattern detection → auto-create tension | Automated (future) |
| Scale threshold crossed | clients >10, avatars >100, cost >$500/mo | Manual (monitoring) |
| Risk Registry review | `/admin/risk-registry` — visual dashboard of all identified risks + status | Manual (weekly architecture review) |

### TENSION — Formalize the problem

Tension = divergence between current architecture and required behavior.

**Created in:** `.kiro/state/tensions.yaml`
**Required fields:** id, title, detected, source, sbm_property, severity, status, description
**Lifecycle:** `open → investigating → proposed → resolved` or `open → deferred (with revisit_date)`

### PROPOSE — Design the fix

For non-trivial changes (multi-file, new component, behavior change):
- Write ADR (Architecture Decision Record) in `docs/adr_*.md`
- ADR format: Tension → Options (2-3 with trade-offs) → Decision → Consequences → Reversal cost
- Reference SBM properties affected

For trivial fixes (single file, obvious solution):
- Fix directly, document in ops log + tension resolution

### COMMIT — Ship and record

1. Code change shipped (local → staging → production)
2. Tension status → resolved (with date, action, files)
3. Steering updated if new principle established
4. CSS regenerated if system state changed

---

## Trigger Model (Hybrid: periodic + event-driven)

### Periodic: Weekly Architecture Review (Friday)

**Input:**
- `tensions.yaml` — all open/investigating items
- SBM check results from Daily Ops Review signals
- Architecture debt table (gaps_06_05_2026.md)

**Process:**
1. Read open tensions (severity ≥ medium)
2. For each: decide → act / defer / dismiss
3. Update tension status
4. If acting: write ADR or fix directly

**Output:** Updated tensions.yaml, new ADRs if needed

**Owner:** Max (sole engineer)
**Duration:** 30 min max
**When to skip:** No open tensions with severity ≥ medium

### Event: SBM Critical Violation

**Trigger:** P1, P2, P4, P5, or P7 violated (any critical property)
**Response:** Investigation within 4 hours (same day)
**Example:** "Client X has 0 drafts for 7 days" = P1 critical → immediate investigation

### Event: Repeated Incident (same root cause 2×)

**Trigger:** Ops log shows same tension triggered second time
**Response:** Severity escalated to critical. Architecture fix required (not ops workaround).
**Rule:** "If same tension fires twice → code fix, not patch"
**Example:** EPG dedup (June 24 + June 25) → full rewrite

### Event: Scale Threshold Crossed

**Trigger:** clients > 10, avatars > 100, LLM cost > $500/mo
**Response:** Review load_dynamics doc. Check if architecture holds at new scale.
**Currently:** Manual observation
**Future:** Automated when billing dashboard crosses threshold

---

## Human-in-the-Loop Matrix

### Where human is MANDATORY gate (blocking)

| Decision | Why | Who | Can automate? |
|----------|-----|-----|---------------|
| Content approval (draft → posted) | Legal: human approves all published content | Client/Operator | No. Auto-approve = pre-authorized policy, still human decision at config time. |
| Architecture decisions (tension → commit) | System cannot modify its own code | Max (engineer) | No. |
| Kill switch toggle (enable/disable pipeline) | Affects all clients simultaneously | Max / Tzvi | No. |
| Incident response (destructive: freeze all, kill pipeline) | High blast radius | Max | No. Automated responses limited to non-destructive. |
| Client deactivation | Business + legal implications | Max / Tzvi | No. |

### Where human is ADVISORY (non-blocking)

| Decision | Why | Who | Notes |
|----------|-----|-----|-------|
| Phase evaluation (promote/demote) | Automated with safety (min sample, cool-down) | System | Operator can override manually |
| Recovery (unfreeze) — dual-confirm mode | Two independent signals confirm | System | Operator notified, can intervene |
| Alert triage (which alert to investigate first) | Priority auto-calculated | System | Human picks when to act |
| Tension severity | Auto-detected, human validates | Max | Can adjust up/down |

### Where human is ABSENT (safe without human)

| Decision | Why safe | Enforcement |
|----------|----------|-------------|
| EPG portfolio allocation (thread selection) | Within approved budget, phase-gated | Budget cap + phase + safety gates |
| Scoring (thread relevance) | No action taken, just classification | Read-only evaluation |
| Generation (draft creation) | Doesn't publish — goes to review | Human gate downstream |
| Health detection (shadowban, CQS) | Read-only diagnostic | No state change on detection alone |
| Karma tracking | Observation only | No action taken |
| Scraping | Public data collection | Rate-limited by Reddit API |

### Scaling considerations

**At 2+ engineers:**
- Architecture decisions → Max has veto, others propose (ADR required)
- Incident response → on-call rotation
- Tension creation → anyone creates, owner triages

**At 10+ clients without dedicated ops:**
- Content approval → auto-approve for mature clients (policy decision by client_admin)
- Incident response → automated first-response (reduce budget, defer tasks), human for resolve
- Alert handling → automated escalation (48h ignored → notify partner)

---

## Architectural Pressure Auto-Detection (Phase 2 — Future)

When Daily Ops Review Phase 2 is built, signal_collector will include:

```python
def detect_architectural_tensions(signals, history):
    tensions = []
    
    # Same error elevated 3+ consecutive days
    if consecutive_elevated_days(history, "error_count_24h") >= 3:
        tensions.append(Tension(sbm="P1", severity="high"))
    
    # Cost growing faster than clients (1.5x ratio)
    if cost_growth_ratio(signals) > 1.5 * client_growth_ratio(signals):
        tensions.append(Tension(sbm="P3", severity="medium"))
    
    # Frozen avatars accumulating without resolution
    if signals["frozen_avatars"] > 3 and no_resolution_trend(history):
        tensions.append(Tension(sbm="P2", severity="high"))
    
    # Feedback gap growing (P6 partial violation)
    if signals["comments_without_snapshots_48h"] > 5:
        tensions.append(Tension(sbm="P6", severity="medium"))
    
    return tensions
```

This is the mechanism by which the system initiates architecture change without manual trigger:
- System detects pattern → creates tension artifact → tension enters weekly review → human decides

The system does NOT change itself. It detects the NEED for change and surfaces it.

---

## What Makes This a System (not just a process)

1. **Tensions have storage** — `.kiro/state/tensions.yaml` (not someone's memory)
2. **Triggers are defined** — periodic (Friday) + event-driven (SBM violation, repeated incident)
3. **Ownership is explicit** — Max for all decisions (scales to rotation later)
4. **Lifecycle is tracked** — open → resolved/deferred with dates
5. **Input is partially automated** — signal_collector feeds OBSERVE (Phase 2)
6. **Output is verifiable** — tension resolved = code shipped + steering updated + CSS regenerated
7. **History is preserved** — resolved tensions stay in registry (pattern analysis)

What it is NOT:
- Self-modifying (cannot change code autonomously)
- Fully automated (PROPOSE and COMMIT always require human)
- Real-time (weekly cadence, except for critical events)

These are correct boundaries for a 1-engineer team at <10 clients. Automation frontier advances with scale.
