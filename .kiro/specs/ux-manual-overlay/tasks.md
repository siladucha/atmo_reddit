# Implementation Plan: UX Manual Overlay

## Overview

This plan implements the UX Manual Overlay — a global in-page help system providing contextual guidance on every screen. The implementation follows 4 phases: skeleton component, content registry, full YAML coverage, and verification/polish.

## Tasks

- [x] 1. Create Manual Overlay template partial (`app/templates/partials/ux_manual.html`) with fixed-position button (bottom-right, z-index 60, 44x44px), hidden overlay shell (right-side slide-in panel, 420px, z-index 70), backdrop div, HTMX `hx-get="/api/manual?path={{ request.url.path }}"` targeting `#ux-manual-content`, and inline scoped CSS using custom properties with fallbacks
- [x] 2. Create `/static/js/ux-manual.js` with vanilla JS: show/hide overlay, Escape key close, backdrop click-to-close, body overflow management
- [x] 3. Include `{% include "partials/ux_manual.html" %}` and `<script src="/static/js/ux-manual.js" defer></script>` before `</body>` in all 3 base templates (`admin_base.html`, `base.html`, `client_base.html`)
- [x] 4. Create `app/manual/__init__.py`, `app/manual/registry.py` (with `get_manual_content(path, role)` using `@lru_cache`, path-to-key mapping stripping UUIDs), and `app/manual/flows.py` (4 flow chains + LIFECYCLE_STAGES list)
- [x] 5. Create `app/routes/manual.py` with FastAPI router: `GET /api/manual?path=` endpoint reading user_role from request.state, calling registry, rendering `partials/manual_content.html`
- [x] 6. Create `app/templates/partials/manual_content.html` rendering flow position indicator, screen context, purpose, available actions (with destructive warnings), role behavior, and fallback placeholder
- [x] 7. Register manual router in `app/main.py`: `app.include_router(manual.router)`
- [x] 8. Create `app/manual/screens/` directory with 5 pilot YAML files: `admin_dashboard.yaml`, `admin_clients.yaml`, `admin_avatars.yaml`, `portal_home.yaml`, `portal_review.yaml` — each with full schema (title, lifecycle_stage, flow_position, screen_context, screen_purpose, available_actions, role_behavior)
- [x] 9. Create YAML files for remaining admin panel screens (~15 files): pipeline, EPG, decision center, posting dashboard, users, subreddits, keywords, personas, discovery, GEO, topology, activity, settings, audit, billing, trials, export, avatar detail/onboard/workflow
- [x] 10. Create YAML files for client portal screens (~10 files): avatars, avatar detail, EPG, strategy, report, subreddits, keywords, settings, plus onboarding wizard steps (6 steps + trial)
- [x] 11. Create YAML files for public/auth and base.html screens (~5 files): login, register, dashboard, review, avatars page
- [x] 12. Create `scripts/verify_manual_coverage.py`: imports app, iterates routes, filters HTML page routes, compares against YAML files, reports coverage stats, exits non-zero on gaps
- [x] 13. Add `verify-manual` target to Makefile and add startup warning in `app/main.py` logging uncovered routes on boot
- [x] 14. Run verification script, confirm 100% coverage, and document YAML schema in `docs/kb/guides/manual-content.md`

## Task Dependency Graph

```json
{
  "waves": [
    [1, 2, 4],
    [3, 5],
    [6, 7],
    [8],
    [9, 10, 11],
    [12, 13],
    [14]
  ]
}
```

## Notes

- Phase 1 (tasks 1-3): Delivers visible button on all screens in ~1 day
- Phase 2 (tasks 4-8): Delivers working overlay with 5 pilot screens in ~1 day
- Phase 3 (tasks 9-11): Full YAML content coverage in ~2-3 days
- Phase 4 (tasks 12-14): Verification and enforcement in ~1 day
- No database migrations needed — all content is YAML on disk
- YAML files are cached via lru_cache; changes require process restart
- PyYAML dependency already exists in the project (used by other services)
