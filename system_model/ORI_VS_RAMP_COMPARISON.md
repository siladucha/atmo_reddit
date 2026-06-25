# Ori (n8n/Make.com) vs RAMP (Python) — Prompt Comparison

> Comparison of prompts from the original Ori system (n8n automation, XM Cyber client)
> with the current RAMP implementation (Python/FastAPI).

---

## Structural Comparison

| Aspect | Ori (n8n) | RAMP (Python) |
|--------|-----------|---------------|
| **Format** | n8n workflow JSON (nodes + connections) | Python string constants in .py files |
| **Storage** | File `XM Cyber _ Write comments copy.json` (176 KB) | `services/generation.py`, `services/scoring.py` and . |
| **Orchestration** | n8n visual workflow (node graph) | Celery tasks + chaining |
| **LLM provider** | OpenRouter (Claude Opus, GPT, Gemini) | LiteLLM → Anthropic + Google direct |
| **Output parsing** | n8n Structured Output Parser (JSON schema) | Pydantic models (ScoringOutput, CommentOutput) |
| **Client context** | Hardcoded XM Cyber profile in system message | Dynamic from DB (client.company_worldview etc.) |
| **Personas** | 6 fixed personas (ThorneMarcus92, d-wreck-w12...) | Dynamic from DB (avatar.voice_profile_md) |
| **Subreddit logic** | Airtable lookup → n8n filter | PostgreSQL query + smart_scoring budget |

---

## Prompt-by-Prompt Comparison

### 1. Comment Generation (Core Prompt)

| | Ori | RAMP |
|---|---|---|
| **Prompt name** | `expert_redditor_comments` system message | `COMMENT_WRITER_PROMPT` |
| **Length** | 47,930 chars (!) | ~4,200 chars |
| **Model** | Claude Opus (via OpenRouter) | Claude Sonnet (via LiteLLM) |
| **Structure** | Massive single prompt with Company Profile + Engagement Guide + Voice Profile injected as 4 separate system messages | Single template with {variables} + runtime injections (strategy, learning, approach) |
| **Word limit** | "10-100 words" | "20-60 words, hard max 80" |
| **Forbidden patterns** | Extensive (same spirit as RAMP, originated here) | Inherited and expanded (added banned starters, diversity enforcement) |
| **Diversity** | Not enforced programmatically | Programmatic: diversity scan of previous_comments before generation |
| **Learning** | None (static prompt) | Few-shot examples + CorrectionPatterns injected dynamically |
| **Output** | JSON {comment, Location} | JSON {comment, comment_to, location_depth, location_reasoning, comment_approach, strategic_angle, perspective_push} |

**Verdict:** RAMP prompt is 10x shorter but produces richer output metadata. Diversity enforcement and learning injection are entirely new. Ori relied on prompt length to constrain behavior; RAMP uses shorter prompt + dynamic context.

### 2. Comment Editor

| | Ori | RAMP |
|---|---|---|
| **Prompt name** | `expert_redditor_comments1` system message | `EDITOR_PROMPT` |
| **Length** | 12,219 chars | ~800 chars |
| **Purpose** | Same: fix AI slop, make human-sounding | Same |
| **Rules** | 50+ rules (exhaustive) | 10 rules (distilled) |
| **Output** | Text only (same) | Text only (same) |

**Verdict:** Same function, RAMP distilled to essential rules. Ori's exhaustive list was needed because Opus sometimes ignored shorter instructions; Sonnet responds well to concise rules.

### 3. Persona Selection

| | Ori | RAMP |
|---|---|---|
| **Prompt name** | `decide_persona` system message | `PERSONA_SELECT_PROMPT` |
| **Length** | 8,841 chars + 15,492 chars (personas) | ~500 chars (template) + dynamic personas_json |
| **Personas** | 6 hardcoded (XM Cyber specific) | N dynamic (from DB, per-client) |
| **Output** | `{persona: [array], mode, audience, thread_angle, pov_opportunity}` | `{persona_username, mode, audience, thread_angle, pov_opportunity, selection_reasoning}` |
| **Multi-select** | Yes (1-3 personas returned) | No (1 persona per thread) |

**Verdict:** RAMP simplified to single-persona selection (better for budget control). Personas are dynamic, not hardcoded.

### 4. Scoring

| | Ori | RAMP |
|---|---|---|
| **In Ori?** | No separate scoring prompt — n8n filter by keyword match from Airtable | Full LLM scoring with 3-dimension framework (relevance/quality/strategic) |
| **Model** | N/A (rule-based filter) | Gemini Flash (cheap) |
| **Output** | Binary: passes filter or not | Rich: {tag, composite 0-9, intent, reason} |

**Verdict:** RAMP added AI scoring as entirely new capability. Ori used simple keyword matching. This is one of RAMP's key innovations — budget-aware intelligent thread selection.

---

## What RAMP Inherited from Ori

1. **Voice profile concept** — Ori invented the persona voice profiles (cynical practitioner, anti-vendor, peer-first). RAMP preserved this identity.
2. **Forbidden patterns** — The banned buzzwords, em-dashes, academic transitions. Originated in Ori's 48K-char prompt.
3. **Two-stage generation** — Writer → Editor. Both systems use separate LLM calls for generation and cleanup.
4. **Location intelligence** — "Reply to post or specific comment?" Ori invented this, RAMP formalized as `location_depth` + `location_reasoning`.
5. **Company context injection** — Company worldview/problem as context for the LLM.
6. **Mode classification** — bullseye / helpful_peer / karma_only. Originated in Ori's persona selection.

## What RAMP Added (Not in Ori)

1. **Self-learning loop** — EditRecord → CorrectionPattern → few-shot injection. Ori was static.
2. **Scoring pipeline** — AI evaluation of threads (Ori used keyword matching only).
3. **Budget-aware generation** — Smart Scoring limits calls per avatar. Ori processed all matches.
4. **Diversity enforcement** — Programmatic scan of previous outputs before generating next.
5. **Strategy injection** — Dynamic strategy_context from Discovery engine. Ori had static company profile.
6. **Multi-client support** — Ori was single-client (XM Cyber). RAMP handles N clients with isolated context.
7. **Phase system** — Avatar maturity gating content type. Ori had no concept of phases.
8. **Approach diversity** — 5 approaches (reframe_drop, cynical_deconstruction, the_scar, contrarian, drive_by). Ori didn't categorize approaches.
9. **Output metadata** — perspective_push, strategic_angle, comment_approach tracked per draft. Ori tracked only the comment text.
10. **Feedback loop** — Karma outcomes feed back into EPG weights. Ori had no outcome tracking.

## What Ori Had That RAMP Lost/Changed

1. **Multi-persona selection** — Ori could select 1-3 personas per thread. RAMP selects 1 (simpler, cheaper).
2. **Prompt verbosity** — Ori's 48K-char system message gave the LLM extreme detail. RAMP trusts Sonnet to follow shorter instructions.
3. **n8n visual workflow** — Non-engineers could see and modify the flow. RAMP requires Python.
4. **Airtable as DB** — Ori stored everything in Airtable (visual, editable by business). RAMP uses PostgreSQL (faster, harder to inspect for non-devs).
5. **OpenRouter model switching** — Ori could swap models in UI. RAMP requires DB setting change (but not deploy).

---

## Summary

```
Ori  = Long prompts + static personas + no learning + single client + visual workflow
RAMP = Short prompts + dynamic everything + self-learning + multi-client + code-based
```

The DNA is preserved (voice identity, forbidden patterns, mode system). Everything else is rebuilt for scale, multi-tenancy, and self-improvement.
