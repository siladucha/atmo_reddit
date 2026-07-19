# UX Manual Overlay — Single Source of Contextual Help

## Rule (July 19, 2026)

**Every page in client portal and admin portal has exactly ONE "How it works" element: the floating button in the bottom-right corner.** No inline `<details>` blocks with "How it works" text inside page content.

## Architecture

| Component | Location | Role |
|-----------|----------|------|
| `partials/ux_manual.html` | Included in `client_base.html` + `admin_base.html` | Global floating button + slide-in panel |
| `app/manual/screens/*.yaml` | Per-route YAML files | Content source (title, purpose, actions per role) |
| `app/manual/registry.py` | Route → YAML resolver | Maps URL paths to YAML filenames |
| `app/routes/manual.py` | `/api/manual?path=` endpoint | Serves rendered HTML for HTMX |

## How It Works

1. User sees fixed button "? How it works" bottom-right on every page
2. On click → HTMX loads `/api/manual?path=<current_page_url>`
3. Registry resolves path → YAML file (with UUID stripping + route aliases)
4. Content rendered per-role (different actions for client_admin vs client_viewer vs owner)
5. Panel slides in from right with: purpose, actions, flow context

## Rules for Templates

1. **NO inline `<details>` with "How it works"** inside page content. Remove if found.
2. **NO duplicate help text** in page body. All contextual help goes into the YAML file.
3. **Info tooltips (ℹ️) on specific fields are OK** — they explain individual UI elements, not the whole page.
4. **Explanatory banners (colored info boxes)** about specific features are OK — they're not "How it works" but feature announcements/context.

## YAML Coverage Requirements

Every route that serves a full page MUST have a corresponding YAML in `app/manual/screens/`:

### Client Portal (27 pages)
- ✅ portal_home, portal_review, portal_avatars, portal_avatar_detail
- ✅ portal_epg, portal_strategy, portal_report, portal_subreddits
- ✅ portal_keywords, portal_settings, portal_visibility, portal_activity
- ✅ portal_extension, portal_landscape, portal_help, portal_tasks
- ✅ portal_team, portal_billing, portal_subreddits_risk_profile
- ⬜ portal_insights (TODO)
- ⬜ portal_requests (TODO)
- ⬜ portal_report_history (TODO)
- ⬜ portal_intelligence_report (TODO)

### Admin Portal (22+ pages)
- ✅ admin_dashboard, admin_clients, admin_avatars, admin_avatar_detail
- ✅ admin_subreddits, admin_keywords, admin_threads, admin_review
- ✅ admin_settings, admin_users, admin_health, admin_ai_costs
- ✅ admin_billing, admin_geo, admin_discovery, admin_posting
- ✅ admin_tasks, admin_trials, admin_audit_logs, admin_inspector
- ✅ admin_scrape_queue, admin_activity

## Adding a New Page — Checklist

1. Page inherits from `client_base.html` or `admin_base.html` → overlay auto-included ✅
2. Create `app/manual/screens/<route_key>.yaml` with content
3. If path doesn't auto-resolve → add alias to `_ROUTE_ALIASES` in `registry.py`
4. **DO NOT** add inline "How it works" `<details>` blocks
