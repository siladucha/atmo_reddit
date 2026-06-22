# Technical Design Document

## Overview

This document describes the technical architecture for the UI/UX + Frontend Observability Standards system. The system introduces an instrumented UI runtime layer across three base templates (admin_base.html, client_base.html, base.html) using Python-based tooling for lint/generation and vanilla JavaScript for the debug overlay — no build pipeline required.

**Key design constraints:**
- No bundler/build step exists — all JS/CSS served as raw static files or CDN
- Tailwind CSS loaded from CDN with runtime `tailwind.config` (not compiled)
- Three independent base templates with no shared parent
- HTMX is the primary interaction model (65+ partials loaded dynamically)
- Environment control via `Settings.app_env` (production/development)

## Architecture

### System Layers

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CI ENFORCEMENT LAYER                          │
│  make ci-ui → lint_ui.py + generate_ui_map.py + validate_specs.py   │
└─────────────────────────────────────────────────────────────────────┘
         │                    │                      │
         ▼                    ▼                      ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────────────┐
│  UI_Lint         │ │  UI_MAP_Generator│ │  Screen_Spec Validator   │
│  (Python)        │ │  (Python)        │ │  (Python)                │
│                  │ │                  │ │                          │
│ • inline style   │ │ • scan templates │ │ • YAML schema check     │
│ • arbitrary TW   │ │ • extract routes │ │ • route coverage        │
│ • dup patterns   │ │ • drift report   │ │ • field completeness    │
│ • marker check   │ │ • auto-gen map   │ │                          │
└──────────────────┘ └──────────────────┘ └──────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     TEMPLATE INSTRUMENTATION LAYER                   │
│                                                                     │
│  Component Markers: data-component / data-owner / data-variant      │
│  Conditional rendering: {% if app_env != 'production' %}            │
│  Design Tokens: static/css/tokens.css (shared) + theme overrides    │
└─────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     DEBUG OVERLAY LAYER (dev only)                   │
│                                                                     │
│  static/js/debug-overlay.js                                         │
│  • Reads [data-component] markers from DOM                          │
│  • Draws bounding boxes + labels via absolute-positioned overlays   │
│  • Listens htmx:afterSwap / htmx:beforeSwap for re-scan            │
│  • Floating toggle panel (localStorage preferences)                 │
│  • Viewport-only rendering for performance                          │
└─────────────────────────────────────────────────────────────────────┘
```

### File Structure (New Files)

```
reddit_saas/
├── scripts/
│   ├── lint_ui.py              # UI linter (inline styles, arbitrary TW, markers, dups)
│   ├── generate_ui_map.py      # Auto-generate UI_MAP.md from template scanning
│   └── validate_screen_specs.py # Validate YAML screen specs against schema
├── app/
│   ├── static/
│   │   ├── css/
│   │   │   ├── tokens.css      # Shared design tokens (CSS custom properties)
│   │   │   └── client-tokens.css  # (existing — becomes client theme extension)
│   │   └── js/
│   │       └── debug-overlay.js   # Debug mode overlay engine
│   └── templates/
│       ├── _macros/
│       │   ├── _input.html     # Parametric input component
│       │   ├── _button.html    # Parametric button component
│       │   ├── _loading.html   # Loading state component
│       │   ├── _error.html     # Error state component
│       │   └── _empty.html     # Empty state component
│       └── (existing templates — modified to add markers)
├── docs/
│   ├── contracts/
│   │   ├── input.yaml          # Input component contract
│   │   ├── button.yaml         # Button component contract
│   │   ├── loading.yaml        # Loading state contract
│   │   ├── error.yaml          # Error state contract
│   │   └── empty.yaml          # Empty state contract
│   └── screen_specs/
│       └── *.yaml              # Per-page YAML screen specifications
├── UI_MAP.md                   # Auto-generated + manually enriched
├── ui_lint_allowlist.txt       # Allowlist for existing violations
└── Makefile                    # New targets: lint-ui, generate-ui-map, ci-ui
```

## Component Design

### 1. Design Token System (`static/css/tokens.css`)

A single CSS file defining all design tokens as CSS custom properties, imported by all three base templates. The existing `client-tokens.css` is retained as a theme-specific extension.

```css
/* static/css/tokens.css — Shared RAMP Design Tokens */

:root {
  /* ===== SPACING ===== */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 32px;
  --space-2xl: 40px;
  --space-3xl: 48px;

  /* ===== BORDER RADIUS ===== */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-full: 9999px;

  /* ===== TYPOGRAPHY ===== */
  --font-sans: 'Inter', ui-sans-serif, system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, monospace;

  --text-xs: 11px;
  --text-sm: 13px;
  --text-base: 15px;
  --text-lg: 18px;
  --text-xl: 22px;
  --text-2xl: 30px;
  --text-3xl: 48px;

  --weight-normal: 400;
  --weight-medium: 500;
  --weight-semibold: 600;
  --weight-bold: 700;

  --leading-tight: 1.25;
  --leading-normal: 1.5;
  --leading-relaxed: 1.75;

  /* ===== TRANSITIONS ===== */
  --transition-fast: 150ms ease-out;
  --transition-normal: 250ms ease-out;

  /* ===== FOCUS ===== */
  --focus-ring-width: 2px;
  --focus-ring-offset: 2px;

  /* ===== FORM SPACING ===== */
  --form-label-gap: 6px;
  --form-field-gap: 16px;
  --form-section-gap: 24px;
  --form-button-gap: 24px;
}

/* ===== THEME: ADMIN (DARK) ===== */
[data-theme="admin"], .theme-admin {
  --color-bg: #0F172A;
  --color-surface: #1E293B;
  --color-surface-alt: #334155;
  --color-border: #475569;
  --color-text: #F1F5F9;
  --color-text-muted: #94A3B8;
  --color-primary: #818CF8;
  --color-primary-hover: #A5B4FC;
  --color-success: #22C55E;
  --color-warning: #F59E0B;
  --color-error: #EF4444;
  --color-info: #60A5FA;
  --focus-ring-color: #818CF8;
}

/* ===== THEME: CLIENT (DARK - ORANGE) ===== */
[data-theme="client"], .theme-client {
  --color-bg: #0D0D1A;
  --color-surface: #1A1A2E;
  --color-surface-alt: #1E1E32;
  --color-border: #2E2E4A;
  --color-text: #FFFFFF;
  --color-text-muted: #AAAAAA;
  --color-primary: #FF6B35;
  --color-primary-hover: #FF8C5A;
  --color-success: #22C55E;
  --color-warning: #F59E0B;
  --color-error: #E53935;
  --color-info: #60A5FA;
  --focus-ring-color: #FF6B35;
}

/* ===== THEME: PUBLIC (LIGHT) ===== */
[data-theme="public"], .theme-public {
  --color-bg: #F8FAFC;
  --color-surface: #FFFFFF;
  --color-surface-alt: #F1F5F9;
  --color-border: #E2E8F0;
  --color-text: #1E293B;
  --color-text-muted: #64748B;
  --color-primary: #6366F1;
  --color-primary-hover: #818CF8;
  --color-success: #22C55E;
  --color-warning: #F59E0B;
  --color-error: #EF4444;
  --color-info: #3B82F6;
  --focus-ring-color: #6366F1;
}
```

**Integration:** Each base template adds `<link rel="stylesheet" href="/static/css/tokens.css">` and applies the theme via `data-theme` attribute on `<html>` or `<body>`.

### 2. Component Marker System

Components add markers conditionally based on environment:

```jinja2
{# Jinja2 macro pattern for component markers #}
{% macro component_attrs(name, owner, variant=None) %}
{% if app_env != 'production' %}data-component="{{ name }}" data-owner="{{ owner }}"{% if variant %} data-variant="{{ variant }}"{% endif %}{% endif %}
{% endmacro %}
```

Usage in partials:
```html
{# partials/_avatar_card.html #}
<div {{ component_attrs('avatar_card', 'partials/_avatar_card.html') }}
     class="surface p-4 rounded-lg">
  ...
</div>
```

**Template globals registration** (in each route file's Jinja2Templates setup):
```python
templates.env.globals["app_env"] = get_settings().app_env
```

### 3. Parametric Component Templates

Example: `_macros/_button.html`:
```jinja2
{# _macros/_button.html — Parametric button component #}
{% macro button(text, variant="primary", type="button", disabled=false, loading=false, icon=None, href=None) %}
{% set variants = {
  "primary": "bg-[var(--color-primary)] text-white hover:bg-[var(--color-primary-hover)]",
  "secondary": "bg-[var(--color-surface-alt)] text-[var(--color-text)] border border-[var(--color-border)] hover:border-[var(--color-text-muted)]",
  "danger": "bg-[var(--color-error)] text-white hover:opacity-90",
  "ghost": "bg-transparent text-[var(--color-text-muted)] border border-[var(--color-border)] hover:text-[var(--color-text)] hover:border-[var(--color-text-muted)]"
} %}
{% set classes = variants.get(variant, variants.primary) %}
{% set tag = "a" if href else "button" %}
<{{ tag }}
  {{ component_attrs('button', '_macros/_button.html', variant) }}
  {% if href %}href="{{ href }}"{% endif %}
  {% if tag == "button" %}type="{{ type }}"{% endif %}
  {% if disabled %}disabled{% endif %}
  class="inline-flex items-center justify-center gap-1.5 min-h-[44px] px-5 py-2.5 rounded-[var(--radius-sm)] text-[var(--text-base)] font-semibold cursor-pointer transition-all duration-[var(--transition-fast)] border-none disabled:opacity-40 disabled:cursor-not-allowed {{ classes }}"
>
  {% if loading %}<span class="portal-spinner"></span>{% endif %}
  {% if icon %}<span>{{ icon }}</span>{% endif %}
  {{ text }}
</{{ tag }}>
{% endmacro %}
```

### 4. Debug Overlay Engine (`static/js/debug-overlay.js`)

Architecture:
```
┌────────────────────────────────────────────────────────┐
│                  debug-overlay.js                        │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ BorderLayer  │  │ LabelLayer   │  │ GridLayer    │ │
│  │              │  │              │  │              │ │
│  │ Draws 2px   │  │ Shows name + │  │ CSS grid     │ │
│  │ colored     │  │ owner file   │  │ overlay      │ │
│  │ borders     │  │ labels       │  │ (columns,    │ │
│  │ around each │  │ on each      │  │ rows, gaps)  │ │
│  │ [data-comp] │  │ component    │  │              │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐                   │
│  │ FloatPanel   │  │ HTMXWatcher  │                   │
│  │              │  │              │                   │
│  │ Toggle UI    │  │ Listens:     │                   │
│  │ (bottom-     │  │ afterSwap    │                   │
│  │ right)       │  │ beforeSwap   │                   │
│  │ localStorage │  │ Re-scans     │                   │
│  │ persistence  │  │ subtree      │                   │
│  └──────────────┘  └──────────────┘                   │
└────────────────────────────────────────────────────────┘
```

**Activation flow:**
1. Backend renders `<body data-debug-ui="true">` when `app_env != 'production'`
2. Script checks `document.body.dataset.debugUi === 'true'`
3. Checks `localStorage.getItem('debug_ui_active') === 'true'`
4. If both true, initializes overlay layers based on `localStorage.getItem('debug_ui_prefs')`

**HTMX re-scan:**
```javascript
document.body.addEventListener('htmx:afterSwap', (evt) => {
  const target = evt.detail.target;
  rescanSubtree(target); // Only re-scan the swapped subtree
});

document.body.addEventListener('htmx:beforeSwap', (evt) => {
  const target = evt.detail.target;
  removeOverlaysForContainer(target); // Clean up before new content
});
```

**Performance (>200 components):**
- Uses IntersectionObserver to track which `[data-component]` elements are in viewport
- Only renders overlays for visible elements
- Recalculates positions on scroll/resize via `requestAnimationFrame`

### 5. UI Lint Script (`scripts/lint_ui.py`)

**Architecture:**
```python
class UILinter:
    def __init__(self, template_dir: Path, allowlist_path: Path):
        self.template_dir = template_dir
        self.allowlist = self._load_allowlist(allowlist_path)
        self.violations: list[Violation] = []

    def run_all_checks(self) -> int:
        """Run all checks, return exit code (0 = pass, 1 = violations found)."""
        for html_file in self.template_dir.rglob("*.html"):
            content = html_file.read_text()
            lines = content.splitlines()
            self._check_inline_styles(html_file, lines)
            self._check_arbitrary_tailwind(html_file, lines)
            self._check_component_markers(html_file, content)
        self._check_duplicate_patterns()
        return 1 if self._has_unallowlisted_violations() else 0
```

**Check implementations:**

1. **Inline style detection:** Regex `r'style\s*=\s*["\']'` on each line, excluding Jinja2 dynamic expressions
2. **Arbitrary Tailwind:** Regex `r'(text|bg|border|p|px|py|pt|pb|pl|pr|m|mx|my|mt|mb|ml|mr|w|h|min-w|min-h|max-w|max-h|gap|rounded|top|left|right|bottom|inset|opacity|z|tracking|leading|indent)-\['`
3. **Component markers:** Parse `{% include "..." %}` directives, read target file, check for `data-component` on first HTML element
4. **Duplicate patterns:** Build DOM fingerprints (tag + class structure), group by fingerprint, report groups ≥ 3

**Allowlist format** (`ui_lint_allowlist.txt`):
```
# Dynamic widths in progress bars
partials/_progress_bar.html:inline-style  # width computed from percentage

# Legacy admin pages (Phase 2 migration)
admin_dashboard.html:arbitrary-tailwind
admin_clients.html:arbitrary-tailwind
```

### 6. UI_MAP Generator (`scripts/generate_ui_map.py`)

**Scanning pipeline:**

```
1. Scan app/routes/*.py → extract @router.get/post decorators
   → map route URL → template name (from TemplateResponse)

2. Scan app/templates/**/*.html:
   a. Detect base template ({% extends "admin_base.html" %} → theme=admin)
   b. Extract {% include "..." %} directives → component dependencies
   c. Extract data-component attributes → component names
   d. Extract data-variant attributes → variant list

3. Build data model:
   Pages: [{name, url, template, theme, includes}]
   Components: [{name, owner, used_in_pages, variants}]

4. Render to Markdown (deterministic sort)

5. Compare with existing UI_MAP.md → produce Drift_Report
```

**Drift detection:** Compares auto-generated sections against existing UI_MAP using section markers:
```markdown
<!-- AUTO-GENERATED: DO NOT EDIT BELOW -->
...pages/components...
<!-- END AUTO-GENERATED -->

<!-- MANUAL SECTION: Descriptions and navigation paths -->
...
```

### 7. Screen Spec YAML Schema

```yaml
# JSON Schema for screen_specs/*.yaml validation
type: object
required: [page, theme, entry, states, sections, verifiable_by]
properties:
  page:
    type: string
    pattern: "^/"
  theme:
    type: string
    enum: [admin, client, public]
  entry:
    type: string
    description: "Navigation path from login (e.g., 'Login → Admin → Clients')"
  states:
    type: object
    required: [loading, empty, error, filled]
    properties:
      loading: { type: object }
      empty: { type: object }
      error: { type: object }
      filled: { type: object }
  sections:
    type: object
    minProperties: 1
  verifiable_by:
    type: string
    enum: [visual_only, visual_with_test_data, requires_backend_state]
  test_data:
    type: object
    properties:
      seed: { type: string }
      setup: { type: string }
```

**Example screen spec:**
```yaml
# docs/screen_specs/admin_clients.yaml
page: /admin/clients
theme: admin
entry: "Login (owner) → Admin sidebar → Clients"
states:
  loading:
    description: "Skeleton placeholders for client table"
  empty:
    description: "Empty state with 'No clients yet' message and 'Add Client' CTA"
  error:
    description: "Red error banner with retry button"
  filled:
    description: "Table with client rows"
sections:
  header:
    elements: ["h1: Clients", "button: Add Client"]
  client_table:
    columns: [name, plan, avatars, status, actions]
    row_actions: [edit, deactivate]
    empty_state: "No clients configured yet"
verifiable_by: visual_with_test_data
test_data:
  seed: "python scripts/seed_demo_data.py"
```

### 8. Makefile Integration

New targets added to `reddit_saas/Makefile`:

```makefile
# --- UI Observability ---

lint-ui:  ## Run UI lint checks (inline styles, arbitrary Tailwind, markers)
	python scripts/lint_ui.py app/templates/

generate-ui-map:  ## Auto-generate UI_MAP.md from template scanning
	python scripts/generate_ui_map.py --output ../UI_MAP.md

validate-specs:  ## Validate screen spec YAML files
	python scripts/validate_screen_specs.py docs/screen_specs/

ci-ui:  ## Run all UI checks (lint + markers + drift + specs)
	@echo "=== UI Lint ==="
	python scripts/lint_ui.py app/templates/ || exit 1
	@echo "=== UI MAP Drift ==="
	python scripts/generate_ui_map.py --check
	@echo "=== Screen Spec Validation ==="
	python scripts/validate_screen_specs.py docs/screen_specs/
	@echo "=== All UI checks passed ==="
```

## Data Models

No database models are introduced. All data is file-based:

| Artifact | Format | Location | Generated/Manual |
|----------|--------|----------|-----------------|
| Design tokens | CSS | `static/css/tokens.css` | Manual |
| Component contracts | YAML | `docs/contracts/*.yaml` | Manual |
| Screen specs | YAML | `docs/screen_specs/*.yaml` | Manual |
| UI_MAP | Markdown | `/UI_MAP.md` | 70% auto / 30% manual |
| Allowlist | Text | `ui_lint_allowlist.txt` | Manual |
| Drift report | stdout | (CI output) | Auto-generated |

## Integration Points

### Base Template Modifications

**All three base templates gain:**
1. `<link rel="stylesheet" href="/static/css/tokens.css">` in `<head>`
2. `data-theme="admin|client|public"` on `<html>` element
3. `data-debug-ui="{{ 'true' if app_env != 'production' else 'false' }}"` on `<body>`
4. Conditional debug script inclusion:
```jinja2
{% if app_env != 'production' %}
<script src="/static/js/debug-overlay.js" defer></script>
{% endif %}
```

### Jinja2 Globals Registration

Added once in `app/main.py` (shared across all route template instances):
```python
from app.config import get_settings

# UI observability globals
settings = get_settings()
templates.env.globals["app_env"] = settings.app_env
templates.env.globals["component_attrs"] = _component_attrs_helper
```

Where `_component_attrs_helper` is a Jinja2 callable that returns data attributes conditionally.

### Route File Impact

No changes to route Python files. Template rendering logic unchanged — only templates themselves gain markers.

## Performance Considerations

- **Zero production overhead:** Debug overlay script not loaded, markers not rendered, tokens CSS is a single cacheable file (~3KB)
- **Debug mode performance:** IntersectionObserver + requestAnimationFrame for >200 components; subtree-only re-scan on HTMX swaps
- **Lint script performance:** Single-pass file scanning with regex; no HTML parsing (BeautifulSoup) needed for primary checks; duplicate detection uses hash-based fingerprinting
- **UI_MAP generator:** One-time scan of ~130 template files; deterministic output enables git diff for drift detection

## Security Considerations

- Component markers (`data-component`, `data-owner`) stripped in production to prevent information disclosure about file structure
- Debug overlay script not included in production HTML output
- Screen specs contain no secrets (only UI-visible content descriptions)
- Allowlist file committed to repo (no secrets, justification comments only)

## Phased Delivery Map

| Phase | Delivers | Files Created | Effort |
|-------|----------|---------------|--------|
| 1 | Lint + Markers | `scripts/lint_ui.py`, `ui_lint_allowlist.txt`, marker macro, tokens.css | 1-2 days |
| 2 | UI_MAP Generator | `scripts/generate_ui_map.py`, `UI_MAP.md` | 3-5 days |
| 3 | Debug Overlay | `static/js/debug-overlay.js`, base template mods | 5-7 days |
| 4 | Screen Specs | `scripts/validate_screen_specs.py`, `docs/screen_specs/*.yaml`, contracts | 3-5 days |
