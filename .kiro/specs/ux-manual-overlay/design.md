# Design Document: UX Manual Overlay

## Overview

The UX Manual Overlay is a global in-page help system that provides contextual guidance on every screen of the RAMP platform. It consists of:

1. A persistent "How it works" button rendered from all 3 base templates
2. A slide-in panel overlay loaded via HTMX from a centralized content registry
3. A Python-based content registry (YAML files) keyed by route path
4. A FastAPI endpoint serving manual content as HTML partials

The system follows the existing HTMX partial-loading pattern already used throughout the codebase.

## Architecture

```
Base Templates (admin_base / base / client_base)
  {% include "partials/ux_manual.html" %}  <-- before </body>
  Contains: button (fixed position) + empty overlay shell
  JS: /static/js/ux-manual.js
        |
        | hx-get on click
        v
GET /api/manual?path=/current/route
  Route: app/routes/manual.py
  Reads: app/manual/registry.py -> loads YAML from app/manual/screens/
  Returns: rendered Jinja2 partial (manual_content.html)
        |
        v
Content Registry: app/manual/
  __init__.py         # registry loader
  registry.py         # get_manual_content(route_path, role)
  flows.py            # flow chain definitions
  screens/            # YAML content per screen
      admin_dashboard.yaml
      portal_home.yaml
      ...
```

## Components and Interfaces

### 1. Template Partial: partials/ux_manual.html

A single Jinja2 partial included in all 3 base templates. Contains:

- Button: Fixed-position trigger (bottom-right, z-index 60)
- Overlay shell: Hidden right-side panel with backdrop
- No content: Content loaded dynamically via HTMX on open

The button uses hx-get="/api/manual?path={{ request.url.path }}" with hx-target="#ux-manual-content" to load content on first click.

### 2. JavaScript: /static/js/ux-manual.js

Minimal vanilla JS (~40 lines):
- openManual() shows overlay, triggers HTMX fetch if content empty
- closeManual() hides overlay
- Escape key handler
- Backdrop click handler
- HTMX event listener (htmx:afterSwap) to handle content load

### 3. CSS: Inline in the partial (scoped)

Uses CSS custom properties for theme adaptation. Each base template already defines different values for --color-surface, --color-border, --color-muted so the overlay adapts automatically.

For base.html (which does not define custom properties), CSS uses fallback values: var(--color-surface, #ffffff).

Button: position fixed, bottom-right, 44x44 min tap target, z-index 60.
Panel: position fixed, right side, 420px width (100vw on mobile), z-index 70, slide-in animation.
Backdrop: rgba(0,0,0,0.4) covering the page.

### 4. Backend Route: app/routes/manual.py

FastAPI router with single endpoint:
- GET /api/manual?path={current_route_path}
- Reads user_role from request.state (injected by auth middleware)
- Calls registry.get_manual_content(path, role)
- Returns rendered partials/manual_content.html

No special auth dependency needed (inherits from global AuthMiddleware).

### 5. Content Registry: app/manual/registry.py

- Loads YAML files from app/manual/screens/ directory
- Uses functools.lru_cache for performance (loaded once per process)
- Path-to-key mapping: /admin/clients -> admin_clients, /clients/{id}/home -> portal_home
- Returns structured dict with: title, lifecycle_stage, flow_position, screen_context, screen_purpose, available_actions (role-filtered), role_behavior
- Returns fallback content if YAML not found (found=False, generic message)

### 6. YAML Content Schema

Each screen gets one YAML file in app/manual/screens/:

```yaml
title: "Client Dashboard"
lifecycle_stage: "execution"

flow_position:
  flow_name: "Daily Operations"
  current_step: 1
  total_steps: 5
  steps:
    - name: "Dashboard"
      active: true
    - name: "Review Queue"
      active: false
    - name: "EPG Schedule"
      active: false
    - name: "Avatars"
      active: false
    - name: "Reports"
      active: false

screen_context:
  before: "Login / authentication"
  after: "Review queue to approve pending drafts"
  description: "Central overview after login. Shows pipeline health, recent activity, and quick actions."

screen_purpose: "Monitor your Reddit presence program at a glance."

available_actions:
  all:
    - name: "Run Pipeline"
      description: "Trigger a fresh content generation cycle"
      destructive: false
  client_viewer:
    - name: "View Review Queue"
      description: "Navigate to see approved/pending drafts (read-only)"
      destructive: false

role_behavior:
  summary: "All client roles can view the dashboard."
  differences:
    - role: "Client Admin"
      access: "Full access"
    - role: "Client Viewer"
      access: "Read-only"
```

### 7. Flow Chain Definitions: app/manual/flows.py

Defines the lifecycle flow chains for the Flow Position Indicator:

- onboarding: Website Analysis -> ICP Synthesis -> Keywords -> Subreddits -> Avatars -> Activate
- daily_operations: Dashboard -> Review Queue -> EPG Schedule -> Avatars -> Reports
- admin_management: Dashboard -> Clients -> Avatars -> Pipeline -> Analytics
- trial_lifecycle: Signup -> Configure -> First Pipeline -> Review Results -> Upgrade

LIFECYCLE_STAGES = [onboarding, trial, execution, review, billing, monitoring, configuration]

### 8. Content Partial: partials/manual_content.html

Renders the manual content with sections:
1. Flow Position Indicator (lifecycle badge + step breadcrumb)
2. Screen Context (where you are, before/after)
3. Screen Purpose (what you do here)
4. Available Actions (role-filtered list with destructive warnings)
5. Role Behavior (permissions summary)

Shows "Documentation pending" placeholder when content not found.

## Data Models

The overlay uses CSS custom properties already defined differently in each base template:

| Property        | admin_base   | client_base  | base.html    |
|----------------|--------------|--------------|--------------|
| --color-surface | #1E293B      | #1A1A2E      | #ffffff (fb) |
| --color-border  | #334155      | #2E2E4A      | #e5e7eb (fb) |
| --color-muted   | #94a3b8      | #AAAAAA      | #6b7280 (fb) |

(fb) = fallback value in CSS var()

## Integration Points

1. Base templates: Add {% include "partials/ux_manual.html" %} + script tag before </body> in all 3
2. main.py: Add app.include_router(manual.router)
3. No auth dependency: Uses existing AuthMiddleware session

## File Structure (New Files)

```
app/
  manual/
    __init__.py
    registry.py              # Content loading + caching
    flows.py                 # Flow chain definitions
    screens/                 # YAML per screen (~60 files)
      admin_dashboard.yaml
      admin_clients.yaml
      admin_avatars.yaml
      portal_home.yaml
      portal_review.yaml
      ...
  routes/
    manual.py                # GET /api/manual
  templates/
    partials/
      ux_manual.html         # Button + overlay shell
      manual_content.html    # Rendered content partial
  static/
    js/
      ux-manual.js           # Open/close/escape logic
```

## Implementation Phases

### Phase 1: Component skeleton (1 day)
- Create partials/ux_manual.html with button + overlay
- Add ux-manual.js
- Include in all 3 base templates
- Create app/routes/manual.py returning placeholder
- Result: Button visible everywhere, opens overlay with "Coming soon"

### Phase 2: Content registry (1 day)
- Create app/manual/registry.py + flows.py
- Define YAML schema
- Create 5 pilot YAML files (admin_dashboard, portal_home, portal_review, admin_clients, admin_avatars)
- Wire route to registry
- Result: 5 screens have full manual content

### Phase 3: Full coverage (2-3 days)
- Write YAML for remaining ~55 screens
- Add verification script (scripts/verify_manual_coverage.py)
- Add make verify-manual command
- Result: 100% screen coverage

### Phase 4: Polish (1 day)
- Mobile responsive adjustments
- Keyboard navigation (Tab trap inside overlay)
- Startup warning for uncovered routes
- Result: Production-ready

## Error Handling

scripts/verify_manual_coverage.py:
- Imports the FastAPI app, iterates all registered routes
- Filters for routes serving HTML pages (not API/partials)
- Compares against YAML files in app/manual/screens/
- Reports: total screens, covered, missing
- Exits non-zero on gaps
- Callable via: make verify-manual

## Correctness Properties

### Property 1: Universality
Every page extending a base template shows the Manual button without per-page opt-in. No individual template action is needed.

### Property 2: Isolation
The overlay cannot affect page state. No form resets, no scroll loss, no HTMX interference when opening/closing.

### Property 3: Idempotency
Opening/closing the manual multiple times does not accumulate event listeners or DOM elements.

### Property 4: Role Safety
Manual content never exposes actions a user cannot perform. Actions are filtered server-side by role before rendering.

### Property 5: Cache Coherence
lru_cache ensures YAML is loaded once per process. Content updates require restart (acceptable for deploy-time changes).

### Property 6: Theme Correctness
The overlay matches the surrounding theme via CSS custom properties with safe fallbacks for base.html.

### Property 7: Graceful Degradation
If JS fails to load, the button is inert (no broken state). If YAML is missing, a placeholder renders.

## Testing Strategy

1. YAML over DB: Content changes rarely, does not need runtime editing. YAML is git-trackable and editable by non-developers.
2. HTMX over client-side rendering: Matches existing codebase pattern. No new JS frameworks.
3. lru_cache: YAML loaded once per process lifetime. Cache invalidated on restart (acceptable for content that changes at deploy time).
4. No per-page modification: Button appears via base template include. Adding a new page = adding a YAML file only.
5. CSS custom properties for theming: Leverages existing client-tokens.css system. Falls back gracefully for base.html.
6. No database models: Zero-migration, version-controllable, easy to edit.
