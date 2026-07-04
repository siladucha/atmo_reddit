# RAMP System Model — Source of Truth

> This folder is the single source of truth about RAMP system architecture and behavior.
> Any AI agent, analyst, or engineer starts here.

---

## What is RAMP

**RAMP (Reddit Attention Management Platform)** — a Human-in-the-Loop platform for managing reputation presence on Reddit.

The system finds relevant discussions, generates persona-calibrated responses via AI, sends them for human approval, routes approved content to executors for manual posting, collects feedback signals (karma, deletions), and automatically corrects its own behavior.

**Key property:** No content is published without a human decision. AI proposes — human decides — system learns.

**What this is NOT:**
- Not a bot or automated spam system
- Not a Reddit manipulation tool
- Not model fine-tuning (uses few-shot injection into prompt)
- Not a real-time system (batch pipeline on schedule)

---

## Current State (v0.3.0, June 2026)

| Parameter | Value |
|-----------|-------|
| Production | gorampit.com (DigitalOcean, Frankfurt) |
| Clients | ~10 |
| Avatars | ~50 |
| AI calls per day | ~560 |
| Cost per client | $1.17/day (LLM) |
| Margin | >90% |
| Auto-posting | DISABLED (POSTING_DISABLED=true). Executors post manually via email. |

---

## Folder Structure

| File | Contents | For whom |
|------|----------|----------|
| `RAMP_FULL_MODEL.json` | **Complete model** (104 KB). All 21 sections. Single file for LLM loading. | Agents, ChatGPT, NotebookLM |
| `01_entities.json` | 18 DB entities (all fields, types, constraints) + 5 state machines with transitions and side effects | Engineers, ER diagrams |
| `02_pipeline.json` | Execution graph: 25 nodes, 26 edges, 13 layers. Celery Beat schedule. Dual Pipeline. | Sequence diagrams, planning |
| `03_ai_prompts.json` | 30 AI call points + prompt registry + full texts of key prompts | Prompt engineering, AI audit |
| `04_safety_rbac.json` | 9 posting gates + content gates + kill switches + 7 roles + enforcement points + 7 system invariants | Security audit, compliance |
| `05_signals_adaptation.json` | All signals (engagement, health, moderation, MISSING) + 8 self-modification mechanisms | Understanding feedback loops |
| `06_infrastructure.json` | Deployment, containers, economics, 12 known gaps, 4 accepted improvements | Ops, scaling decisions |
| `07_hidden_architecture.json` | Ownership map (who decides what), implicit contracts, missing layers, scale limits | Architecture decisions |
| `08_agent_instructions.json` | Instructions for AI agents: terminology, answer rules, common LLM errors | Load FIRST when working with LLM |
| `09_risks.json` | **Risk registry** (93 risks across 13 groups: Platform, Infrastructure, Architecture, Business, Security, Posting, Scaling, Data, Ops, AI, Documentation, Ban Detection, Forecast). Priority matrix + spec coverage + mitigation plan. | Risk management, architecture review |
| `diagrams_state_machines.md` | 5 Mermaid state machine diagrams (draft, slot, task, phase, health) | Visualization, Tzvi |
| `diagrams_pipeline.md` | Mermaid: full pipeline sequence diagram + dual pipeline + component architecture | Visualization, analyst |
| `diagrams_safety_ai.md` | Mermaid: safety gates + AI model routing + learning loop + deployment | Visualization, security |
| `AGENT_QUESTIONS.md` | 10 open questions from RAMP agent (prioritized P1/P2/P3) | Max (tech), Tzvi (business) |
| `ORI_VS_RAMP_COMPARISON.md` | Detailed comparison: Ori (n8n/Make.com) vs RAMP (Python) prompts and architecture | Heritage understanding |

---

## How to Use

### For AI agent (ChatGPT, Claude, DeepSeek, NotebookLM)
1. Load `08_agent_instructions.json` — prevents hallucinations
2. Load `RAMP_FULL_MODEL.json` — full context
3. Ask questions

### For analyst / Tzvi
1. Open `diagrams_pipeline.md` — see full flow
2. Open `diagrams_state_machines.md` — understand lifecycles
3. Read `AGENT_QUESTIONS.md` — business questions (Q7-Q10)

### For new engineer
1. Read this README
2. Open `02_pipeline.json` — understand what runs when
3. Open `01_entities.json` — understand data model
4. Open `03_ai_prompts.json` — understand where and which AI is used

### For security audit
1. `04_safety_rbac.json` — gates, roles, invariants
2. `06_infrastructure.json` — gaps and risks
3. `07_hidden_architecture.json` — implicit contracts, scale limits

---

## Key Architecture Facts

### What is implemented
- **5 Docker containers**: app, db, redis, celery, celery-beat (NO celery-fast)
- **2 AI model settings** in DB: `llm_scoring_model` (Gemini Flash), `llm_generation_model` (Claude Sonnet)
- **No centralized AI router** — each service calls `get_config()` per-call
- **No single orchestrator** — orchestration via Celery Beat (temporal) + task chaining (causal) + state polling (reactive)
- **Dual Pipeline**: Professional (Phase 2+, Claude) and Hobby (Phase 1+, Gemini) — different tables, different scoring, different models

### What is NOT implemented (critical gaps)
- **GAP-003**: No lock on EPG build (race condition, duplicates possible)
- **GAP-004**: No adaptation to Reddit algorithm changes (adversarial)
- **GAP-008**: Single server, no failover
- **GAP-012**: Prompts not versioned (no A/B, no rollback)
- **Expert phase**: In spec only, not in code

### Common confusion (LLMs hallucinate these)
- "survival >= 80% for promotion" — In code **no 80%**. 70% is the DEMOTION threshold.
- "2 slots per subreddit per day" — No per-sub cap exists.
- "40% presence cap" — Does not exist.
- "EPG race condition fixed" — GAP-003 is NOT fixed.
- "fast queue in Celery" — One queue (default).
- "System auto-posts" — POSTING_DISABLED=true. Executors post manually.
- "Fine-tuning models on edits" — Few-shot injection into prompt (models unchanged).

---

## How to Update

Update this folder when:
- New AI prompt added → `03_ai_prompts.json`
- Celery task added → `02_pipeline.json`
- State machine changed → `01_entities.json`
- New entity/model → `01_entities.json`
- Safety gate modified → `04_safety_rbac.json`
- Kill switch added → `04_safety_rbac.json`
- Infrastructure changed → `06_infrastructure.json`
- GAP closed → `06_infrastructure.json`

After changes:
1. Update domain file (01-08)
2. Rebuild `RAMP_FULL_MODEL.json` (run script or manually)
3. Bump `meta.version` in affected files

---

## Origin

This model was **extracted from production codebase** via reverse engineering (June 25, 2026).
This is an AS-IS description — what the code actually does, not what it "should" do.

Where code lacks explicit information — marked `UNKNOWN`.
Where behavior diverges from documentation — code takes priority.

---

*Maintained by: Max (tech lead) | Last updated: July 2, 2026*
