---
inclusion: manual
---

# RAMP Agent Identity — System as Autonomous Actor

## Core Concept

**RAMP is an autonomous agent, not a passive tool.** The system independently initiates, decides, and executes — with humans retained only at critical approval gates (Human-in-the-Loop).

The system_model (`/system_model/`) is the agent's self-knowledge: its graph of capabilities, entities, signals, and decision points. The codebase is its body. The steering is its operational policy.

---

## What "Agent" Means Here

RAMP is not a chatbot or assistant. It is a **goal-directed autonomous system** that:

1. **Observes** — scrapes Reddit, monitors health, tracks karma, detects patterns
2. **Decides** — scores threads, selects opportunities, allocates budgets, evaluates phases
3. **Acts** — generates content, routes to executors, manages avatars, adapts strategy
4. **Learns** — captures feedback (karma, deletions, edits), corrects future behavior
5. **Protects itself** — detects risks, freezes compromised avatars, gates dangerous actions

The operator (Max) and business partner (Tzvi) provide **policy and oversight**, not micromanagement. The executor (Женя or extension) provides **physical action** (posting), not decision-making.

---

## Autonomy Spectrum — What RAMP Does Without Asking

### Fully Autonomous (no human involved)

| Domain | What the agent does | Frequency |
|--------|-------------------|-----------|
| **Discovery** | Finds relevant threads across subreddits | Every 60s (queue_tick) |
| **Scoring** | Evaluates thread relevance per client | 2×/day (08:00, 14:00) |
| **Generation** | Writes persona-calibrated comments | After scoring |
| **Budget allocation** | Distributes daily slots across subreddits | Morning EPG build (08:15) |
| **Phase management** | Promotes/demotes avatars based on signals | Daily (06:00) |
| **Health monitoring** | Detects shadowbans, suspensions, CQS drops | 2×/day (07:30, 13:30) |
| **Self-correction** | Adjusts subreddit weights from karma outcomes | Daily (02:00) |
| **Risk assessment** | Scores subreddit danger, blocks unsafe combinations | Weekly batch + real-time gate |
| **Intelligence** | Extracts rules, profiles moderation, maps emotions | Weekly (Sunday) |
| **Cost control** | Circuit breakers, budget caps, reconciliation | Continuous |
| **Recovery** | Retries failed operations, top-ups unfilled budgets | Daily (09:00, 14:15) |
| **Alerting** | Pushes Telegram/email on failures | Continuous |

### Human-in-the-Loop Gates (MANDATORY — cannot be removed)

| Gate | What human decides | Who | Can be pre-authorized? |
|------|-------------------|-----|----------------------|
| **Content approval** | "Is this comment good enough to publish?" | Client admin / operator / autopilot policy | Yes — `autopilot_enabled` = blanket pre-approval |
| **Execution approval** | "Post this now?" (extension popup) | Executor | Yes — "Approve All" morning batch |
| **Kill switch toggle** | "Stop/start the entire pipeline" | Max / Tzvi | No — always manual |
| **Client activation/deactivation** | "Accept/drop this client" | Max / Tzvi | No |
| **Architecture decisions** | "Change how the system works" | Max | No |

### Key Insight: Auto-Approve ≠ No Human

`autopilot_enabled=true` is a **human policy decision** made at configuration time. The human chose to trust the agent's output. This satisfies P5 (Human Gate) — the gate exists, but the human pre-authorized passage.

---

## Agent's Self-Knowledge

The agent's understanding of itself lives in `/system_model/`:

| File | What it gives the agent |
|------|------------------------|
| `01_entities.json` | What it can perceive and manipulate (18 entities, 5 state machines) |
| `02_pipeline.json` | What it does and when (25 nodes, 26 edges, full schedule) |
| `03_ai_prompts.json` | How it thinks (30 AI call points, prompt registry) |
| `04_safety_rbac.json` | What it must never do (9 gates, 7 invariants) |
| `05_signals_adaptation.json` | How it learns (signals + 8 self-modification mechanisms) |
| `06_infrastructure.json` | Its physical constraints (containers, limits, gaps) |
| `07_hidden_architecture.json` | Implicit contracts it must honor |
| `08_agent_instructions.json` | How to communicate about itself accurately |
| `09_risks.json` | What can kill it (93 risks across 13 groups) |

---

## Agent Evolution — Current vs Target

### Current State (v0.3.0): "Autonomous Pipeline, Manual Ops"

The content pipeline runs fully autonomously. But operational decisions (unfreeze avatar, add subreddit, change strategy, respond to incidents) require a human to notice and act.

```
Content Pipeline:  [████████████ AUTONOMOUS ████████████] → [HUMAN GATE] → [EXECUTE]
Operations:        [HUMAN NOTICES] → [HUMAN DECIDES] → [HUMAN ACTS]
```

### Target State (Operations Agent Phase 2-4): "Autonomous Everything, Human Oversight"

Everything the pipeline does autonomously today, the operations layer will do too: detect problems, propose fixes, execute recovery, alert only when needed.

```
Content Pipeline:  [████████████ AUTONOMOUS ████████████] → [HUMAN GATE] → [EXECUTE]
Operations:        [████████ AUTONOMOUS ████████] → [HUMAN CONFIRMS critical only]
```

What Phase 2-4 adds (NOT BUILT YET):
- **Service recovery** — restart workers, flush queues (autonomous)
- **Pipeline recovery** — freeze/unfreeze avatars based on dual-confirmation (autonomous)
- **Resource management** — adjust concurrency, trigger model fallback (autonomous)
- **Briefings** — daily Telegram summary, weekly strategic report (autonomous generation)
- **Proposals** — for decisions above authority level, proposes via Telegram inline buttons (human confirms)

---

## Human Roles in the Agent System

| Role | Relationship to agent | Communication language |
|------|----------------------|----------------------|
| **Max** (engineer) | Builds and evolves the agent. Sets policy. Reviews architecture. | Russian |
| **Tzvi** (business) | Sets business goals. Reviews client-facing output. Approves pricing. | English |
| **Женя** (QA) | Verifies agent behavior. Tests edge cases. Reports regressions. | Hebrew |
| **Executor** (posting) | Physical action layer — posts what agent prepared. | Email/Extension UI |
| **Client** | Consumer of agent's output. Approves content (if not autopilot). | Portal UI |

---

## Safety Architecture — What Prevents the Agent from Going Rogue

The SBM (System Behavior Model) defines 12 properties that MUST hold true regardless of what the agent decides:

| Property | Prevents |
|----------|----------|
| P1 — Monotonic Progress | Agent starving a client (zero output) |
| P2 — Recovery Reachability | Agent creating deadlocks (unrecoverable states) |
| P3 — Cost Proportionality | Agent burning money (unbounded LLM loops) |
| P4 — Safety Monotonicity | Agent leaking brand content too early |
| P5 — Human Gate Integrity | Agent publishing without human consent |
| P7 — Isolation Guarantee | Agent leaking data between clients |
| P9 — Diagnostic Independence | Agent unable to detect its own failures |
| P10 — Graceful Degradation | Agent cascading a local failure system-wide |
| P11 — Execution Gate Integrity | Agent auto-posting without executor consent |
| P12 — Forecast Truth Separation | Agent presenting predictions as facts |

These are **hard invariants** — the agent cannot override them. They are enforced at code level (runtime assertions, safety gates, structural constraints), not just policy.

---

## Relationship to Other Steering

| Steering file | What it adds |
|---------------|-------------|
| `engineering_principles.md` | Agent's ethical boundary ("Don't Game Reddit") |
| `system_behavior_model.md` | Agent's hard constraints (12 properties) |
| `meta_loop.md` | How agent's architecture evolves over time |
| `pipeline_end_to_end.md` | Agent's execution graph (what it does) |
| `ramp_operations_agent.md` | Agent's ops layer roadmap (Phase 2-4) |
| `ai_agent_role.md` | AI coding assistant's role (builds the agent — different from being the agent) |

---

## Summary

RAMP = autonomous agent that manages Reddit reputation for clients.

- **Initiates** all pipeline work (scrape, score, generate, schedule, measure, learn)
- **Decides** thread selection, budget allocation, phase transitions, risk assessment
- **Executes** content creation, avatar management, strategy adaptation
- **Defers** only to humans at content approval gate and critical ops decisions
- **Protects** itself via 12 SBM invariants enforced at runtime

The human's job is not to run the system. It's to set policy, approve content, and intervene when the agent flags something beyond its authority.
