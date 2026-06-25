# RAMP System Diagnostic — Guide

## What is RAMP_SYSTEM_DIAGNOSTIC.json

A complete machine-readable operational model of the RAMP system, extracted from production codebase via reverse engineering (June 25, 2026).

**Location:** `/RAMP_SYSTEM_DIAGNOSTIC.json` (root of project)

**Size:** ~95 KB, 20 top-level sections

## Structure

| Section | Content |
|---------|---------|
| `meta` | Version, generation date, extraction method |
| `deployment` | Production infra (DO, containers, deploy sequence) |
| `system_graph` | 25 nodes + 26 edges + 13 layers (full execution graph) |
| `state_machines` | 5 FSMs: draft, slot, execution_task, avatar_phase, avatar_health |
| `safety_system` | 10 posting gates + content gates + kill switches |
| `signals` | Engagement + health + moderation + missing signals |
| `temporal_model` | Celery Beat schedule + retry policies + timezone |
| `rbac` | 7 roles + enforcement points + isolation layers |
| `known_gaps` | 12 architectural gaps with severity |
| `invariants` | 7 system contracts that must never be violated |
| `dual_pipeline` | Professional (Phase 2+, Claude) vs Hobby (Phase 1+, Gemini) |
| `economics` | Unit costs, margins, scaling projections |
| `entities` | 18 DB entities with all fields, types, constraints |
| `prompt_registry` | 12 prompt definitions (model, input, output schema) |
| `system_update_rules` | 8 self-modification mechanisms + protected invariants |
| `ai_usage_map` | 30 AI call points (model, frequency, cost, trigger) |
| `prompt_full_texts` | Full text of 3 core prompts |
| `engineering_answers` | 10 blocks of architecture audit answers |
| `common_misinterpretations` | 10 explicit negations (prevents LLM hallucination) |
| `hidden_architecture` | Ownership map, contracts, data flows, missing layers, scale limits |

## Use Cases

1. **UML generation** — feed to analyst tool for sequence/state/ER/component diagrams
2. **LLM Q&A** — load into NotebookLM/Claude/DeepSeek for architecture questions
3. **Investor/partner briefing** — non-code system overview for Tzvi
4. **Onboarding** — new engineer reads JSON to understand full system
5. **Diff tracking** — compare versions when system evolves
6. **Audit** — verify code matches documented behavior

## How to Update

When system changes:
1. Update relevant section in JSON
2. Bump `meta.version`
3. Add change to `meta` or create changelog entry

## Key Principles

- **AS-IS only** — documents what code does, not what it should do
- **UNKNOWN** marked explicitly where ambiguous
- **common_misinterpretations** prevents LLM hallucination on load
- **hidden_architecture** captures undocumented but critical behaviors

## Related Files

- `SYSTEM_ARCHITECTURE_SUMMARY.md` — human-readable summary (for analysts)
- `docs/TODO.md` — product roadmap
- `.kiro/steering/gaps_06_05_2026.md` — gap analysis (updated regularly)
- `.kiro/steering/pipeline_safety_architecture.md` — safety details
