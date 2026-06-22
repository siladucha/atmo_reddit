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

## Components and Interfaces

### Component: UILinter (`scripts/lint_ui.py`)

**Interface:**
```
CLI: python scripts/lint_ui.py <template_dir> [--fix] [--fix --write] [--allowlist <path>]
Exit: 0 (pass) | 1 (violations found)
Output: stdout (violation report in format: file:line:type:snippet)
```

**Public API (if imported):**
```python
class Violation:
    file: Path
    line: int
    violation_type: str  # "inline-style" | "arbitrary-tailwind" | "duplicate-pattern" | "missing-marker"
    snippet: str
    suggested_fix: str | None

class UILinter:
    def __init__(self, template_dir: Path, allowlist_path: Path | None = None): ...
    def run_all_checks(self) -> list[Violation]: ...
    def get_exit_code(self) -> int: ...
```

### Component: UIMapGenerator (`scripts/generate_ui_map.py`)

**Interface:**
```
CLI: python scripts/generate_ui_map.py [--output <path>] [--check] [--strict]
  --output: Write generated UI_MAP to path (default: stdout)
  --check: Compare against existing UI_MAP and report drift
  --strict: Exit non-zero on drift (for CI blocking mode)
Exit: 0 (no drift or output mode) | 1 (drift detected in strict mode)
Output: Markdown (generated map) or drift report to stdout
```

**Public API:**
```python
class PageEntry:
    name: str
    url: str
    template: str
    theme: str  # "admin" | "client" | "public"
    components_used: list[str]

class ComponentEntry:
    name: str
    owner_file: str
    used_in_pages: list[str]
    variants: list[str]

class UIMapGenerator:
    def __init__(self, template_dir: Path, routes_dir: Path): ...
    def scan(self) -> tuple[list[PageEntry], list[ComponentEntry]]: ...
    def render_markdown(self) -> str: ...
    def diff_against(self, existing_map_path: Path) -> DriftReport: ...

class DriftReport:
    new_components: list[str]
    removed_components: list[str]
    new_pages: list[str]
    removed_pages: list[str]
    missing_descriptions: list[str]
    def has_drift(self) -> bool: ...
```

### Component: ScreenSpecValidator (`scripts/validate_screen_specs.py`)

**Interface:**
```
CLI: python scripts/validate_screen_specs.py <specs_dir> [--routes-dir <path>]
Exit: 0 (all valid) | 1 (schema violations found)
Output: Validation errors to stdout, coverage warnings to stderr
```

**Public API:**
```python
class ValidationError:
    file: Path
    field: str
    message: str

class ScreenSpecValidator:
    def __init__(self, specs_dir: Path, routes_dir: Path | None = None): ...
    def validate_all(self) -> list[ValidationError]: ...
    def check_coverage(self) -> list[str]: ...  # Templates without specs
```

### Component: DebugOverlayEngine (`static/js/debug-overlay.js`)

**Interface (JavaScript):**
```javascript
// Global namespace
window.RampDebug = {
  activate(): void,    // Initialize all layers
  deactivate(): void,  // Remove all overlays
  toggle(layer: 'borders' | 'labels' | 'grid'): void,
  rescan(): void,      // Full DOM re-scan
  rescanSubtree(element: HTMLElement): void,  // Partial re-scan
};
```

**Events emitted:**
- None (internal only)

**Events consumed:**
- `htmx:afterSwap` — triggers `rescanSubtree(evt.detail.target)`
- `htmx:beforeSwap` — triggers overlay cleanup for target container
- `scroll`, `resize` — triggers position recalculation via rAF

### Component: ComponentAttrs Macro (`_macros/_component_attrs.html`)

**Jinja2 Interface:**
```jinja2
{% from "_macros/_component_attrs.html" import component_attrs %}

{# Usage: #}
<div {{ component_attrs("avatar_card", "partials/_avatar_card.html", variant="compact") }}>
```

**Output (development):**
```html
<div data-component="avatar_card" data-owner="partials/_avatar_card.html" data-variant="compact">
```

**Output (production):**
```html
<div>
```

### Interface: Makefile Targets

| Target | Description | Blocking |
|--------|-------------|----------|
| `make lint-ui` | Run UI linter on all templates | Yes (exit 1 on violation) |
| `make generate-ui-map` | Regenerate UI_MAP.md | No |
| `make validate-specs` | Validate screen spec YAMLs | Yes (exit 1 on schema error) |
| `make ci-ui` | Run all checks sequentially | Yes (exit on first failure) |

## Correctness Properties

### Property 1: Environment Isolation
**Validates: Requirements 3.5, 3.6, 6.10**
No debug artifacts (markers, overlay script, debug attributes) appear in production HTML. Guaranteed by `{% if app_env != 'production' %}` guards.

### Property 2: Token Completeness
**Validates: Requirements 1.1, 5.1**
Every CSS property used in component contracts must have a corresponding token in `tokens.css`. Validated by contract-to-token cross-reference in lint.

### Property 3: Marker Consistency
**Validates: Requirements 3.1, 3.2**
Every `data-component` value in HTML must match exactly one entry in the Component_Registry. UIMapGenerator validates this during scan.

### Property 4: Deterministic Generation
**Validates: Requirements 2.12**
UIMapGenerator produces byte-identical output for identical input (sorted alphabetically by page URL, then by component name).

### Property 5: HTMX Coherence
**Validates: Requirements 6.8**
After any `htmx:afterSwap`, all new `[data-component]` elements in the swapped subtree gain overlay within 200ms.

### Property 6: Variant Safety
**Validates: Requirements 4.6, 4.7**
Invalid variant values fall back to default (first enum value) at render time. No runtime error produced.

### Property 7: Allowlist Soundness
**Validates: Requirements 1.11, 8.1**
Each allowlist entry must reference an existing file path. Stale entries (file deleted) produce a warning during lint.

## Error Handling

| Scenario | Handling | User Impact |
|----------|----------|-------------|
| Malformed HTML in template (lint) | Skip file, log warning, continue scanning | No block — reported as parse warning |
| Missing allowlist file | Treat as empty allowlist (all violations reported) | Stricter checking |
| Invalid variant passed to component | Render with default variant, no error | Silent fallback |
| YAML parse error in screen spec | Report file + error message, exit 1 | CI blocks merge |
| Route file without template reference | Skip in UIMapGenerator (no page entry created) | Gap reported in coverage |
| Debug overlay JS error | Caught in try/catch, overlay deactivated gracefully | No user-facing impact |
| >200 components on page | IntersectionObserver limits rendering to viewport | Degraded debug experience, not broken |
| Template with no {% extends %} | Classified as "unknown" theme, placed in Uncategorized | Listed with warning flag |

## Testing Strategy

Since no test framework exists for frontend and the system is primarily tooling (Python scripts + static JS), testing follows this approach:

### Unit Tests (Python scripts)

```python
# tests/test_lint_ui.py
class TestInlineStyleDetection:
    def test_detects_plain_style_attr(self): ...
    def test_ignores_jinja2_dynamic_width(self): ...
    def test_allowlist_suppresses_violation(self): ...

class TestArbitraryTailwindDetection:
    def test_detects_text_bracket(self): ...
    def test_detects_p_bracket(self): ...
    def test_ignores_standard_tailwind_class(self): ...

class TestComponentMarkerCheck:
    def test_reports_missing_data_component(self): ...
    def test_passes_with_marker_present(self): ...

class TestUIMapGenerator:
    def test_extracts_route_from_decorator(self): ...
    def test_detects_theme_from_extends(self): ...
    def test_deterministic_output(self): ...
    def test_drift_detection_finds_new_template(self): ...
```

### Integration Tests

- Run `make ci-ui` against a fixture directory of test templates (valid + invalid)
- Verify exit codes match expected results
- Verify drift report format against known baseline

### Manual Verification

- Debug overlay: Open any page with `?debug=ui` in development, verify overlays render
- HTMX re-scan: Navigate a page with HTMX partials, verify overlays update on swap
- Production safety: Deploy to server, verify no `data-component` or debug script in HTML source
