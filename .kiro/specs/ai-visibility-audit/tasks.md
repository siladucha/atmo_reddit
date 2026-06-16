# Implementation Plan: AI Visibility Audit

## Overview

This plan implements the AI Visibility Audit product — a standalone, one-time paid deliverable that wraps Discovery Engine + GEO/AEO Monitoring into an automated pipeline with a prospect-facing portal. The implementation consists of 13 tasks organized into 4 layers: data foundation, orchestration/services, UI/routes, and integration/testing.

## Tasks

- [ ] 1. Create AuditSession database model and Alembic migration
  - Create `app/models/audit_session.py` with full schema (prospect info, pricing, status, FK links, results, cost, token, timestamps)
  - Add `is_audit_prospect` boolean column to Client model
  - Create Alembic migration with CREATE TABLE audit_sessions + indexes + ALTER TABLE clients
  - Register model in `app/models/__init__.py`
  - **Requirements:** 1.1, 1.3, 1.6, 1.7
  - **Files:** `app/models/audit_session.py`, `app/models/client.py`, `alembic/versions/`, `app/models/__init__.py`

- [ ] 2. Implement access token generation and validation service
  - Create `app/services/audit_token.py` with `generate_audit_token(audit_id)` using secrets.token_urlsafe + HMAC
  - Implement `validate_audit_token(token)` with DB lookup + expiry check
  - Set token_expires_at to 90 days after completed_at
  - Add `/audit/` to PUBLIC_PREFIXES in auth middleware
  - **Requirements:** 1.2, 5.4, 5.6
  - **Files:** `app/services/audit_token.py`, `app/middleware/auth.py`

- [ ] 3. Build AuditOrchestrator service with phase execution logic
  - Create `app/services/audit_orchestrator.py` with AuditOrchestrator class
  - Implement `start_discovery()` — creates DiscoverySession, extracts entities, auto-confirms
  - Implement `run_hypotheses()` — forms hypotheses, dispatches research, auto-decides (score > 50 = confirm)
  - Implement `run_geo_baseline()` — creates temp Client, generates prompts, runs GEO batch, computes scores
  - Implement `generate_report()` — calls report LLM, stores HTML, computes margin
  - Implement `abandon()` — validates non-terminal status, sets abandoned
  - Add cost warning: emit ActivityEvent if total_ai_cost > $15
  - **Requirements:** 1.4, 1.5, 2.1-2.6, 3.1-3.7, 7.1-7.4
  - **Files:** `app/services/audit_orchestrator.py`

- [ ] 4. Create GEO prompt generator from Discovery findings
  - Create `app/services/audit_geo_prompts.py` with `generate_audit_geo_prompts()` async function
  - Build Gemini Flash system prompt for generating 10-30 buyer-intent prompts from entities + hypotheses
  - Validate output (min 10 prompts, retry once if insufficient)
  - Store as GeoPrompt records linked to temp_client_id + create GeoCompetitor records
  - Log AI usage with triggered_by="audit:{audit_id}"
  - **Requirements:** 3.1, 3.2, 3.3
  - **Files:** `app/services/audit_geo_prompts.py`

- [ ] 5. Implement visibility score and competitive matrix computation
  - Create `app/services/audit_scoring.py` with `compute_visibility_score()` and `compute_competitive_matrix()`
  - Score: avg(brand_appearance_rate) * 100 from geo_frequency_metrics
  - Matrix: count brand + each competitor appearances, sort by score, compute rank
  - **Requirements:** 3.4, 3.5, 3.6
  - **Files:** `app/services/audit_scoring.py`

- [ ] 6. Build audit report generator with branded HTML template
  - Create `app/services/audit_report_generator.py` with `generate_audit_report(db, audit) -> str`
  - Build Claude Sonnet prompt with structured Discovery + GEO data
  - Create `app/templates/audit_report.html` — self-contained HTML (inline CSS, no JS deps)
  - Implement all 7 report sections with data-driven content
  - CSS-only visualizations: gauge (conic-gradient) + bar chart (flexbox)
  - Print CSS: @media print rules, RAMP branding, footer
  - **Requirements:** 4.1-4.6, 8.1
  - **Files:** `app/services/audit_report_generator.py`, `app/templates/audit_report.html`

- [ ] 7. Create Celery task chain for audit pipeline execution
  - Create `app/tasks/audit.py` with `audit_phase_discovery`, `audit_phase_geo`, `audit_phase_report` tasks
  - Implement `trigger_audit_execution()` dispatching Celery chain
  - Configure retries: discovery 3x/60s, geo 3x/exponential, report 2x/60s
  - Implement `_mark_failed()` helper (sets status, emits ActivityEvent)
  - Register in worker autodiscover
  - **Requirements:** 2.6, 3.7
  - **Files:** `app/tasks/audit.py`, `app/tasks/worker.py`

- [ ] 8. Create operator dashboard routes for audit management
  - Create `app/routes/admin_audits.py` with require_platform_admin dependency
  - GET list (summary metrics + tab filters + paginated table)
  - GET new (creation form)
  - POST create (validate, create session, trigger execution)
  - GET detail (discovery summary, GEO results, report preview, costs)
  - POST rerun-geo, convert, deliver, abandon actions
  - Include router in main.py
  - **Requirements:** 6.1-6.5, 8.3
  - **Files:** `app/routes/admin_audits.py`, `app/main.py`

- [ ] 9. Create operator dashboard templates
  - `admin_audit_list.html` — metrics bar, tab filters, table with status badges
  - `admin_audit_detail.html` — timeline, summaries, report preview, cost/margin, action buttons
  - `admin_audit_new.html` — form with dynamic competitor list, pricing selector
  - Status badges: color-coded (green/blue/red/grey per status)
  - Portal link: copy-to-clipboard functionality
  - **Requirements:** 6.1-6.5
  - **Files:** `app/templates/admin_audit_list.html`, `app/templates/admin_audit_detail.html`, `app/templates/admin_audit_new.html`

- [ ] 10. Create prospect portal routes and template
  - Create `app/routes/audit_portal.py` (public, no auth)
  - GET `/audit/{token}` — validate token, render progress or results
  - GET `/audit/{token}/status` — HTMX partial for polling
  - GET `/audit/{token}/report` — standalone report for print
  - Create `app/templates/audit_portal.html` — step progress, auto-refresh (30s), report inline, CTA card
  - Handle expired/invalid token with branded error page
  - Include router in main.py
  - **Requirements:** 5.1-5.6
  - **Files:** `app/routes/audit_portal.py`, `app/templates/audit_portal.html`, `app/main.py`

- [ ] 11. Implement Convert to Client flow
  - POST `/admin/audits/{id}/convert` handler in admin_audits.py
  - Create Client record pre-populated from audit data
  - Create ClientSubredditAssignment records from Discovery subreddits
  - Re-link GeoPrompt records to new client_id
  - Duplicate domain guard (error if existing client with same domain)
  - Set audit.converted_client_id, redirect to client detail
  - **Requirements:** 8.2, 8.3, 8.4
  - **Files:** `app/routes/admin_audits.py`

- [ ] 12. Add admin navigation and filter audit prospects from client list
  - Add "Audits" link to admin sidebar in admin_base.html
  - Filter `is_audit_prospect=True` clients from admin client list queries
  - **Requirements:** 6.1
  - **Files:** `app/templates/admin_base.html`, `app/routes/admin.py`

- [ ] 13. Write end-to-end tests and perform manual QA
  - `tests/test_audit_session_model.py` — model creation, status transitions, token uniqueness
  - `tests/test_audit_orchestrator.py` — mock LLM/PRAW, verify phase execution and status changes
  - `tests/test_audit_scoring.py` — visibility score and competitive matrix with mock data
  - `tests/test_audit_portal.py` — valid/expired token access, report rendering
  - `tests/test_audit_admin.py` — creation, list, detail, actions
  - Manual QA: full flow from creation through portal viewing to client conversion
  - **Requirements:** All
  - **Files:** `tests/test_audit_*.py`

## Task Dependency Graph

```json
{
  "waves": [
    [1],
    [2, 3],
    [4, 5, 6],
    [7],
    [8, 9, 10, 11, 12],
    [13]
  ]
}
```

**Critical path:** 1 → 3 → 4+5+6 → 7 → 8+10 → 13

**Parallelizable:**
- Wave 2: Token service (2) and Orchestrator (3) can be done in parallel
- Wave 3: GEO prompts (4), scoring (5), report generator (6) — all independent after orchestrator
- Wave 5: Admin routes/templates (8,9), portal (10), convert flow (11), navigation (12) — all independent after Celery tasks

## Notes

- All services call existing Discovery Engine and GEO/AEO functions — no logic duplication
- Temporary Client records use `is_audit_prospect=True` + `is_active=False` to avoid appearing in normal admin flows
- Expected AI cost per audit: $0.70-$1.70 (gross margin 99%+ at both pricing tiers)
- The Celery task chain ensures progressive status updates visible in the prospect portal
- Token-based portal access means no user account creation needed for prospects
