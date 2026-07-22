# Design Document

## Overview

**Engineering Memory is the primary product of Layer 0.** Intake forms, views, and integrations exist only to populate and use this memory. Without the memory loop working end-to-end, nothing else has value.

Engineering Memory Layer 0 uses Notion as external storage, a simple web form for client intake, and Notion MCP for engineer AI access. No separate backend is built — the system leverages existing RAMP infrastructure only for the intake form endpoint, while all data lives in Notion.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     RAMP Engineering Memory                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────┐     ┌──────────────┐     ┌────────────────────┐   │
│  │  Client   │────▶│ Intake Form  │────▶│  Notion Database   │   │
│  │  (web)    │     │ (HTML/RAMP)  │     │  (Engineering      │   │
│  └──────────┘     └──────────────┘     │   Memory)          │   │
│                                         │                    │   │
│  ┌──────────┐     ┌──────────────┐     │                    │   │
│  │ QA/Jenny │────▶│ Notion UI    │────▶│  Views:            │   │
│  │          │     │ (direct)     │     │  - By Status       │   │
│  └──────────┘     └──────────────┘     │  - Recently Closed │   │
│                                         │  - Open Issues     │   │
│  ┌──────────┐     ┌──────────────┐     │  - Stale Flag      │   │
│  │ Engineer │────▶│ Notion MCP   │────▶│                    │   │
│  │ (AI)     │     │ (search/CRUD)│     │                    │   │
│  └──────────┘     └──────────────┘     │                    │   │
│                                         │                    │   │
│  ┌──────────┐     ┌──────────────┐     │                    │   │
│  │ Tzvi/PO  │────▶│ Notion UI    │────▶│                    │   │
│  │          │     │ (read views) │     └────────────────────┘   │
│  └──────────┘     └──────────────┘                               │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Component Design

### 1. Notion Database Setup

**Database name:** RAMP Engineering Memory

**Properties:**

| Property | Type | Configuration |
|----------|------|---------------|
| ID | ID (auto-increment) | Prefix: "EM-", digits: 4 |
| Title | Title (text) | Required |
| Problem | Rich text | Required on create |
| Root Cause | Rich text | Required for Fixed→Verified |
| Fix | Rich text | Required for Fixed→Verified |
| Rule | Rich text | Required for Verified |
| Protection | Select | Options: None / Manual / Test / CI / Prompt / Checklist |
| Risk Level | Select | Options: Low / Medium / High / Critical |
| Category | Select | Options: AI / UX / Backend / Compliance / Integration |
| Status | Select | Options: Reported / Investigating / Fixed / Verified |
| Reporter | Rich text | — |
| Date | Date | Created time default |
| Source | URL | — |
| Audit Reference | Rich text | — |

**Views:**

| View Name | Type | Filter/Sort | Used By |
|-----------|------|-------------|---------|
| All Incidents | Table | Sort by Date desc | QA |
| By Status (Board) | Board | Group by Status | QA / PO |
| Open Issues | Table | Status ≠ Verified, sort Date desc | PO |
| Recently Verified | Table | Status = Verified, sort Date desc, limit 20 | PO / Engineer |
| Rules Library | Table | Status = Verified, show only Title+Category+Rule+Protection | Engineer |
| Stale (>7d Investigating) | Table | Status = Investigating AND Date < 7 days ago | QA |

### 2. Intake Form

A simple HTML form served from the RAMP application at a public route (no auth required for clients). On submission, the form calls the Notion API to create a new database entry.

**Route:** `GET /report-issue` — renders the form page
**Route:** `POST /api/report-issue` — processes form submission, creates Notion page

**Form fields:**
- What happened? (textarea, required)
- Where did it happen? (text, required)
- What was expected? (textarea, required)
- What was the result? (textarea, required)
- Screenshot (file upload, optional) — stored as Notion file block
- Your email (email input, optional)

**Backend logic (`app/services/engineering_memory.py`):**
- Takes form data
- Creates Notion page via API with Status=Reported, Category left empty (QA assigns manually)
- Populates Title from "What happened?" (truncated to first sentence if >100 chars)
- Populates Problem from concatenation of all four text fields
- Populates Reporter from Email or "Client"
- Returns confirmation response

**Note:** Category is NOT auto-assigned via keyword matching. Non-technical reporters write ambiguous descriptions ("avatar doesn't work" could be UX, Compliance, or AI). QA assigns Category during triage — better no automation than bad automation.

**Template:** `app/templates/report_issue.html` — standalone page, branded, accessible without RAMP login. Uses `marketing_base.html` or minimal standalone layout.

### 3. Notion MCP Integration

Engineers access the Engineering Memory Database through their AI development tools (Kiro/Claude) using the Notion MCP server. This is a configuration task — no custom code needed.

**MCP Configuration:**
- Server: `@modelcontextprotocol/server-notion` (or equivalent)
- Auth: Notion integration token with access to Engineering Memory database
- Capabilities: search pages, read pages, create pages, update pages

**Engineer workflows (knowledge operations, not CRUD):**
- "Were there similar problems to [X]?" → MCP searches Title + Problem + Root_Cause
- "What rules exist for [component/category]?" → MCP filters Status=Verified, returns Rule+Protection
- "What risks exist when changing [area]?" → MCP filters by Category + Risk_Level, returns relevant constraints
- "Add new incident: [description]" → MCP creates new page with Status=Reported

**Design principle:** Engineers interact with engineering memory as a knowledge base, not as a database. The interface is: search, read, add. Not: create_page, update_property, delete_block.

### 4. Lifecycle Enforcement

Notion does not natively enforce transition rules. Enforcement is through:

1. **Process discipline** — QA follows checklist (documented in Notion database description)
2. **Views as guides** — "Stale" view highlights overdue items
3. **Completeness check** — before QA sets Status=Verified, they verify Rule + Protection are populated (Notion form validation via template/button)

**Protection "None" is valid.** Sometimes the engineering decision is "We accept this risk." A Protection value of "None" with explicit rationale in the Rule field is a legitimate closure. This prevents fake entries ("Protection: Manual") just to close tickets.

**Notion automation (optional, via Notion's built-in automations):**
- When Status changes to "Investigating" → set "Investigation Started" date property (hidden, for stale calculation)
- When Status changes to "Verified" → check Rule and Protection are not empty (formula/rollup indicator)

### 5. Seed Data

Five initial incidents pre-populated:

| # | Title | Category | Problem Summary | Rule | Protection |
|---|-------|----------|-----------------|------|------------|
| 1 | Public UI contained internal "avatar" terminology | Compliance | Internal product term "avatar" appeared in client-facing output | Internal product terms cannot appear in public outputs | Prompt constraint + future automated terminology scan |
| 2 | Weekly system report showed conflicting metrics | Backend | Two report sections showed different numbers for same metric | Report data sources must be reconciled from single query; never compute same metric independently in two places | Checklist item in weekly report template |
| 3 | Client portal showed raw JSON in subreddit field | UX | Avatar detail page rendered `{"subreddit": "name"}` dict instead of formatted name | Template rendering must handle both dict and string formats for JSONB fields | Manual review + template pattern established |
| 4 | AI generation produced repetitive closing phrases | AI | Three consecutive hobby comments used "Respect for the analysis" as closing | Generation prompt must ban specific filler phrases; include anti-repetition instruction | Prompt constraint (banned closers list in system prompt) |
| 5 | Audit log missing entries for executor email changes | Compliance | Changing executor_email was not recorded in audit trail | All mutable operations on sensitive fields must be audit-logged | CI check (grep for field mutations without audit_log call) |

### 6. Security & Access

| Component | Access Level | Auth Method |
|-----------|-------------|-------------|
| Intake Form (web) | Public (no RAMP login) | None — honeypot field for bots |
| Notion Database | Restricted to team | Notion workspace membership |
| Notion MCP | Engineer AI tools only | Integration token (read/write) |
| Notion Views (PO) | Read-only share | Notion page share link |

### 7. File Structure

```
app/
├── routes/
│   └── engineering_memory.py    # GET /report-issue, POST /api/report-issue
├── services/
│   └── engineering_memory.py    # create_incident(), categorize_problem()
└── templates/
    └── report_issue.html        # Client-facing intake form
```

## Correctness Properties

1. **Completeness invariant:** Every Verified incident contains non-empty Problem, Root_Cause, Fix, Rule, and Protection fields
2. **Lifecycle ordering:** Status transitions follow Reported → Investigating → Fixed → Verified (no skipping)
3. **Categorization coverage:** Every intake submission creates an Incident; Category is assigned by QA during triage (not auto-assigned)
4. **No data loss:** Every form submission results in a Notion page creation (retry on API failure)
5. **Seed data validity:** All 5 seed incidents have every field populated and Status=Verified
6. **Learning Loop (primary acceptance test):** A Rule created from one incident is retrievable by a different engineer querying for constraints in that area — proving the system transforms experience into reusable knowledge

## Out of Scope (Layer 0)

- No autonomous QA Agent
- No automatic fix generation
- No complex dashboards beyond Notion views
- No full CI integration (Protection field is declarative, not enforced by CI)
- No separate backend/database (everything in Notion)
- No automatic intake from audit logs (future Layer 1)
- No AI classification of incoming reports (future Layer 1)
- No automatic similar case search on intake (future Layer 1)

## Future Architecture (Layer 1+ — for context only)

```
Audit Logs (existing RAMP system)
     |
     v
Incident Detection (automated, Layer 1)
     |
     v
Engineering Memory (this database)
     |
     v
New Protection (rules feed back into system)
```

Audit_Reference field exists now as a manual link. In Layer 1, it becomes the automated entry point — Audit Logs create Incidents automatically. This is why the field exists in Layer 0 schema even though it's optional today.
