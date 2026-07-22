---
inclusion: always
---

# Engineering Memory — Agent Operational Protocol

## What This Is

Engineering Memory is the QA Intelligence loop. Every bug reported → investigated → fixed → rule created → system improved. The **PostgreSQL `bug_reports` table** is the single source of truth for all known issues.

## Storage

- **Table:** `bug_reports` (PostgreSQL)
- **Model:** `app/models/bug_report.py`
- **Service:** `app/services/engineering_memory.py`
- **Route:** `app/routes/engineering_memory.py`
- **Form:** `/report-issue` (public, auto-detects logged-in user)
- **Admin sidebar:** "Report Bug" + "QA Board" links

## Schema

| Field | Type | Purpose |
|-------|------|---------|
| bug_id | String(20), unique | Auto-increment BUG-001, BUG-002... |
| title | String(200) | Short description |
| problem | Text | Full problem text (what/where/expected/actual) |
| root_cause | Text | Why it happened (filled after investigation) |
| fix | Text | What was done to fix |
| rule | Text | Preventive guideline |
| protection | String(50) | None/Manual/Test/CI/Prompt/Checklist |
| risk_level | String(20) | Low/Medium/High/Critical |
| category | String(30) | AI/UX/Backend/Compliance/Integration |
| status | String(20) | Reported/Investigating/Fixed/Verified |
| environment | String(20) | dev/staging/prod |
| reporter | String(200) | Name + email + [role] |
| screenshot_url | String(500) | /static/uploads/bugs/{uuid}.ext |
| created_at | DateTime | Auto |
| fixed_at | DateTime | Set when status → Fixed |
| verified_at | DateTime | Set when status → Verified |
| verified_by | String(100) | Who verified (Jenny/Tzvi) |
| verification_comment | Text | QA comment on verification |

## Agent Workflow

### Before making changes

1. Query `bug_reports` for existing bugs in the area being changed
2. Check if there's a Rule that applies
3. Address existing bugs or explicitly note why not

### After fixing a bug

1. Update record: root_cause, fix, status → Fixed, fixed_at
2. Propose Rule + Protection
3. Wait for QA verification (Jenny sets → Verified)

### When new bug reported

1. Bug enters DB via form with status = Reported, auto-assigned bug_id
2. I investigate, update root_cause
3. Fix code, update fix field, status → Fixed
4. Rule + Protection added after verification

## Lifecycle

```
Reported → Investigating → Fixed → Verified
```

## Completeness Rule

**Every Verified bug MUST have:** Problem + Root Cause + Fix + Rule + Protection

## Anti-Bot Protection (3 layers)

1. **Honeypot** — hidden `website` field (bots fill it)
2. **JS Challenge** — hidden field computed by JavaScript (7×13=91)
3. **Timing** — form must be open >3 seconds before submit

## Screenshot Flow

1. User attaches image in form
2. Saved to `app/static/uploads/bugs/{uuid}.ext`
3. Accessible at `/static/uploads/bugs/{filename}`
4. Docker volume `uploads` persists across rebuilds
5. After bug Verified → screenshot can be deleted

## Categories

| Category | What |
|----------|------|
| AI | LLM generation, scoring, prompts |
| UX | UI/template issues, navigation, display |
| Backend | Pipeline, services, data logic |
| Compliance | Terminology, legal, audit |
| Integration | Extension, Notion, external APIs |

## Key Rules (from resolved incidents)

1. **Internal term "avatar" cannot appear in client-facing UI** (BUG-001, Compliance)
2. **Extension download must use permanent filename** `ramp_extension_latest.zip` (BUG-021/032)
3. **All navigation items must be present in sidebar after UX restructuring** (BUG-032)

## For QA (Jenny)

- Report bugs via `/report-issue` form on staging/prod
- After engineer marks Fixed → verify on staging
- Set Verified + comment, or Reopen with explanation
- Access via partner account in admin panel

## Migration from Notion

- Notion database still exists (read-only archive)
- MCP connection maintained for historical reference
- New bugs go to PostgreSQL exclusively
- Notion is NOT the source of truth anymore
