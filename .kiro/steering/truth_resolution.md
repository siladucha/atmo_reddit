---
inclusion: manual
---

# Truth Resolution Model — Documentation Layer 2.0

## Core Principle

Documentation is not truth. It is a layered projection of different truth types.
Truth in this system is not stored — it is computed through reconciliation of layers.

---

## Source Hierarchy (Priority Order)

| Priority | Layer | Source | Role | Mutability |
|----------|-------|--------|------|-----------|
| 1 (highest) | **Ops Logs** | Incident records, session logs | Reality — what actually happened | Append-only |
| 2 | **System Docs** | Code, models, migrations, config | Structure — what exists | Code-synced |
| 3 | **Steering** | `.kiro/steering/*.md` | Intent — what should happen | Append-mostly |
| 4 (lowest) | **CSS** | `.kiro/state/current.yaml` | Derived snapshot — computed state | Regenerated |

### External Inputs (Tzvi, clients, third-party)

External documents (emails, briefs, feature requests) are **NOT part of the truth model**.
They pass through a normalization layer before influencing any internal layer:

```
External Input (raw intent)
    ↓
Normalization (extract actionable, verify feasibility, align with principles)
    ↓
Steering (if new principle) OR System (if new feature) OR Ops (if incident report)
```

**Rule:** External docs never directly modify steering without normalization.

---

## Conflict Resolution Protocol

When layers contradict each other:

```
1. ops overrides everything         → reality wins over design
2. system overrides steering        → what exists > what should exist
3. steering overrides external      → internal intent > external suggestion
4. CSS never overrides anything     → it is derived, not authoritative
```

### For AI Agents / LLMs

When answering "what is true right now?":

1. **Read CSS first** — fast current-state projection
2. **If CSS is stale (>48h) or absent** — derive from system + ops directly
3. **If conflict between CSS and ops log** — ops log wins (CSS not yet regenerated)
4. **If conflict between CSS and steering** — steering wins (CSS is snapshot, steering is normative)
5. **If conflict between steering and ops** — FLAG TO HUMAN. This means a principle is being violated in practice. Do not silently resolve.
6. **If no data in CSS** — read code directly. CSS is convenience, not completeness.

### Decision: Which document to update?

| Something changed | Update |
|-------------------|--------|
| Bug fixed / incident resolved | ops log + CSS |
| Architecture changed (new model, migration, service) | system docs + CSS |
| New principle established | steering + CSS |
| External request processed | steering or system (after normalization) + CSS |
| Deployment completed | CSS only (state change, no structural change) |

---

## CSS (Canonical State Snapshot)

**Location:** `.kiro/state/current.yaml`

**What it is:**
- Computed projection of current system state
- Synthesis of ops + system + steering
- Minimal "what is true right now" for any reader (human or AI)

**What it is NOT:**
- Not a primary source of truth
- Not manually authored (generated or reconciled)
- Not a decision-making authority
- Not a replacement for reading code

**Update triggers:**
- After every incident (ops log written → regenerate CSS)
- After every structural change (migration, new service → regenerate CSS)
- After every deploy (state changed → regenerate CSS)
- On demand (`python _generate_css.py` or userTriggered hook)

**Staleness rule:** CSS older than 48 hours should be treated as potentially inaccurate.

---

## Prohibitions

1. **CSS cannot be used as source of truth for decisions.** It is a convenience view.
2. **External docs cannot directly modify steering** without explicit normalization.
3. **Ops logs and system docs must not be mixed** in a single file as primary record.
4. **Steering files must not contain factual state** (e.g., "avatar X is frozen"). State belongs in CSS or ops.
5. **No document is "the one source of truth."** Truth is the reconciliation output.

---

## Architectural Diagram

```
External Inputs (Tzvi, clients, market)
         ↓
    Normalization Layer
         ↓
┌────────────────────────────────────────────┐
│  Steering (intent/principles)              │  ← append-mostly
│  System Docs (code/architecture)           │  ← code-synced
│  Ops Logs (incidents/sessions)             │  ← append-only
└────────────────────┬───────────────────────┘
                     ↓
           Reconciliation Engine
           (priority: ops > system > steering)
                     ↓
         CSS (derived snapshot)
         `.kiro/state/current.yaml`
```

---

## Migration Path from Current State

### What changes:

1. `RAMP_SYSTEM_DIAGNOSTIC.json` — demoted from "operational model" to "architectural reference". Not a truth source. Keep as static reference for graph structure only.
2. Steering files that contain **factual state** (e.g., "Flaky_Finder_13 frozen since June 25") — state facts migrate to CSS. Steering retains only the **principle** ("shadowban → demote to Phase 0").
3. Ops Session Logs in steering files — remain where they are (append-only), but new logs should go to a dedicated location (`docs/ops/` or `.kiro/ops/`).

### What stays the same:

- Steering files remain the normative model (principles, architecture decisions, rules)
- System docs remain code-synced (project.md structure, model descriptions)
- AI agent reconciliation behavior codified above

---

## Relationship to Existing Documentation Standards

This model supersedes the "Relationship to Other Docs" table in `documentation.md`.
New mapping:

| Location | Truth Layer | Priority |
|----------|------------|----------|
| `.kiro/state/current.yaml` | CSS (derived) | Read first, trust least |
| `.kiro/steering/*.md` | Steering (intent) | Normative principles |
| `docs/kb/` | System docs (user-facing) | Structure |
| `docs/ops/` | Ops logs | Reality (highest authority) |
| `RAMP_SYSTEM_DIAGNOSTIC.json` | Architectural reference | Static, not authoritative |
| `buziness/` | External inputs | Requires normalization |
| `.kiro/specs/` | Intent (pre-implementation) | Becomes system docs after implementation |

---

## Summary

The system moved from **document-driven** to **state-reconciled**.

No single document is truth. Truth is computed via:
`reconcile(ops, system, steering) → CSS`

Any agent (AI or human) that reads ONE document and acts on it without reconciliation is operating incorrectly.
