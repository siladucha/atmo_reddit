# Tasks

## Phase 1: Notion Database Setup

- [x] 1.1 Create "RAMP Engineering Memory" Notion database with all properties: ID (auto-increment, prefix EM-), Title, Problem, Root Cause, Fix, Rule, Protection (select: None/Manual/Test/CI/Prompt/Checklist), Risk Level (select: Low/Medium/High/Critical), Category (select: AI/UX/Backend/Compliance/Integration), Status (select: Reported/Investigating/Fixed/Verified), Reporter, Date, Source (URL), Audit Reference
- [x] 1.2 Create database views: "All Incidents" (table, date desc), "By Status" (board, grouped by Status), "Open Issues" (filter Status≠Verified, date desc), "Recently Verified" (filter Status=Verified, date desc), "Rules Library" (Status=Verified, show Title+Category+Rule+Protection only), "Stale Investigating" (Status=Investigating, Date > 7 days ago)
- [x] 1.3 Configure Notion automation: when Status changes to Verified, show formula/indicator if Rule or Protection is empty (visual enforcement of completeness rule)
- [x] 1.4 Write database description documenting lifecycle rules, field requirements per status, and the principle "Every closed incident MUST have Problem + Root Cause + Fix + Rule + Protection"

## Phase 2: Seed Data

- [x] 2.1 Create seed incident #1: "Public UI contained internal 'avatar' terminology" (Category: Compliance, all fields populated, Status: Verified)
- [x] 2.2 Create seed incident #2: "Weekly system report showed conflicting metrics" (Category: Backend, all fields populated, Status: Verified)
- [x] 2.3 Create seed incident #3: "Client portal showed raw JSON in subreddit field" (Category: UX, all fields populated, Status: Verified)
- [x] 2.4 Create seed incident #4: "AI generation produced repetitive closing phrases" (Category: AI, all fields populated, Status: Verified)
- [ ] 2.5 Create seed incident #5: "Audit log missing entries for executor email changes" (Category: Compliance, all fields populated, Status: Verified)

## Phase 3: Client Intake Form

- [x] 3.1 Create `app/services/engineering_memory.py` with `create_incident(form_data)` function that calls Notion API to create a new page with Status=Reported and Category left empty for QA triage
- [x] 3.2 Create `app/routes/engineering_memory.py` with `GET /report-issue` (renders form) and `POST /api/report-issue` (processes submission, creates Notion page, returns confirmation)
- [x] 3.3 Create `app/templates/report_issue.html` — standalone branded page with form fields: "What happened?" (required textarea), "Where?" (required text), "Expected?" (required textarea), "Actual result?" (required textarea), Screenshot (optional file), Email (optional). Include honeypot field for bot protection.
- [x] 3.4 Add Notion API token to system_settings (`notion_engineering_memory_token`, `notion_engineering_memory_database_id`)
- [x] 3.5 Register route in `app/main.py`, add `/report-issue` and `/api/report-issue` to auth middleware public routes whitelist
- [x] 3.6 Add nginx location block for `/report-issue` route

## Phase 4: Notion MCP Configuration

- [ ] 4.1 Create Notion integration with access to Engineering Memory database (read/write pages)
- [ ] 4.2 Configure Notion MCP server in Kiro powers (or equivalent MCP client) with the integration token and database ID
- [ ] 4.3 Document engineer workflows in a steering file (`.kiro/steering/engineering_memory.md`): how to query for similar problems, how to check existing rules, how to add new incidents after a fix
- [ ] 4.4 Test MCP access: verify search by keyword, create new incident, read rules by category

## Phase 5: Documentation & Process

- [ ] 5.1 Create `.kiro/steering/engineering_memory.md` documenting: the cycle (Problem → Report → Memory → Investigation → Root Cause → Fix → Rule + Protection → Verification → System Improved), roles and responsibilities, how engineers must use the database before and after changes
- [ ] 5.2 Share intake form URL with Jenny (QA operator) and confirm she can access all Notion views
- [ ] 5.3 Share read-only Notion views with Tzvi (Product Owner): "By Status" board, "Open Issues" list, "Recently Verified" list
- [ ] 5.4 Verify end-to-end flow: submit form → incident appears in Notion → QA can transition status → Engineer can query via MCP → Verified incident has all fields populated
- [ ] 5.5 **Learning Loop Acceptance Test**: QA creates incident → Engineer fixes and adds Rule + Protection → Different engineer queries "What constraints exist for [that area]?" via MCP → System returns the created Rule. This test validates that Layer 0 works as a learning loop, not just a task list.
