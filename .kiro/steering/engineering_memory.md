---
inclusion: always
---

# Engineering Memory — Agent Operational Protocol

## What This Is

Engineering Memory is the QA Intelligence loop. Every bug reported → investigated → fixed → rule created → system improved. The Notion database is the single source of truth for all known issues.

## Notion Database

- **Database ID:** `3a404a57-f8f3-8108-8481-dab416265d5d`
- **Parent page:** RAMP QA (`668fc31a-4b09-4b31-8f7f-5d41128ac995`)
- **Access:** Notion MCP (configured in `~/.kiro/settings/mcp.json`)

## Agent Workflow (How I Use This)

### Before making changes

1. Query Notion for existing bugs in the area I'm changing
2. Check if there's a Rule or Protection that applies
3. If modifying a component with known bugs → address them or explicitly note why not

### After fixing a bug

1. Update Notion record: Root Cause, Fix, Status → Fixed
2. Propose Rule + Protection
3. Wait for verification (Tzvi/Jenny sets Status → Verified)

### When new bug reported

1. Bug enters Notion with Status = Reported
2. I investigate, add Root Cause
3. Fix code, update Notion with Fix field, Status → Fixed
4. Rule + Protection proposed after verification

## Lifecycle

```
Reported → Investigating → Fixed → Verified
```

- **Reported:** Problem described, Category assigned by QA
- **Investigating:** Root cause being identified
- **Fixed:** Code fix deployed, Root Cause + Fix documented
- **Verified:** QA confirmed fix works, Rule + Protection populated

## Completeness Rule

**Every Verified incident MUST have:** Problem + Root Cause + Fix + Rule + Protection

Protection = "None" is valid (accepted risk). But it must be explicit.

## Categories

| Category | What |
|----------|------|
| AI | LLM generation, scoring, prompts |
| UX | UI/template issues, navigation, display |
| Backend | Pipeline, services, data logic |
| Compliance | Terminology, legal, audit |
| Integration | Extension, Notion, external APIs |

## For Tzvi (Visibility)

Tzvi has read access to the Notion database with these views:
- **By Status** (board) — see what's Reported/Investigating/Fixed/Verified
- **Open Issues** — everything not yet Verified
- **Recently Verified** — completed fixes with Rules

## Key Rules (from resolved incidents)

These are active constraints I must follow:

1. **Internal term "avatar" cannot appear in client-facing UI** (BUG-001, Compliance)
2. **Extension download must use permanent filename** `ramp_extension_latest.zip` (BUG-021/032)
3. **All navigation items must be present in sidebar after UX restructuring** (BUG-032)

## Intake Form

- **URL:** `/report-issue` (public, pre-fills role if logged in)
- **Admin sidebar:** "Report Bug" link in Operations section
- **Client sidebar:** Not added yet (BUG-025 addresses this)

## MCP Access Pattern

```
# Query open bugs
mcp_notion_API_query_data_source(data_source_id="3a404a57-f8f3-8108-8481-dab416265d5d", filter={"property": "Status", "select": {"does_not_equal": "Verified"}})

# Update bug after fix
mcp_notion_API_patch_page(page_id="...", properties={"Status": {"select": {"name": "Fixed"}}, "Root Cause": {"rich_text": [...]}, "Fix": {"rich_text": [...]}})
```
