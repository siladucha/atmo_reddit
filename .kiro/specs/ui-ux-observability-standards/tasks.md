# Implementation Tasks

## Phase 1: Lint + Component Markers (1-2 days)

- [ ] 1. Create shared design tokens CSS file
  - Create `reddit_saas/app/static/css/tokens.css` with all CSS custom properties: spacing (xs-3xl), border-radius (sm/md/lg/full), typography (font sizes, weights, line-heights), transitions, focus ring, form spacing, and three theme palettes (admin dark, client dark-orange, public light)
  - Add `<link rel="stylesheet" href="/static/css/tokens.css">` to all three base templates: `admin_base.html`, `client_base.html`, `base.html`
  - Add `data-theme="admin|client|public"` attribute to `<html>` element in each base template
  - Requirements: 1.1, 1.2, 1.9

- [ ] 2. Create component_attrs Jinja2 macro for conditional markers
  - Create `reddit_saas/app/templates/_macros/_component_attrs.html` with macro that outputs `data-component`, `data-owner`, and optional `data-variant` attributes only when `app_env != 'production'`
  - Register `app_env` in Jinja2 globals for all template instances (admin, portal, pages) by reading from `get_settings().app_env`
  - Add `data-debug-ui` attribute to `<body>` in all three base templates, set to 'true' only when `app_env != 'production'`
  - Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 6.1

- [ ] 3. Add component markers to top 10 most-used partials
  - Identify the 10 most-used partials in `templates/partials/` by grep for `{% include %}` frequency
  - Add `data-component` and `data-owner` attributes to the root element of each, using the macro from task 2
  - Ensure markers are conditionally rendered (not present in production)
  - Requirements: 3.1, 3.2, 3.5

- [ ] 4. Create UI lint script with inline-style and arbitrary-Tailwind checks
  - Create `reddit_saas/scripts/lint_ui.py` implementing `UILinter` class
  - Implement inline `style=""` detection via regex, reporting file:line:type:snippet
  - Implement arbitrary Tailwind bracket notation detection via regex pattern for all utility prefixes
  - Support `--allowlist` flag pointing to `ui_lint_allowlist.txt`
  - Exit code 1 when unallowlisted violations found, 0 otherwise
  - Handle malformed files gracefully (skip + log warning)
  - Requirements: 1.4, 1.5, 1.7, 1.8, 1.11, 8.1, 8.2, 8.9

- [ ] 5. Add component marker check to lint script
  - Extend `lint_ui.py` to scan for `{% include %}` directives in templates
  - For each included partial, verify its root HTML element contains `data-component` attribute
  - Report missing markers as blocking violations
  - Requirements: 3.3, 3.8, 3.9, 8.4

- [ ] 6. Create initial allowlist for existing violations
  - Run `lint_ui.py` against all existing templates to identify current violations
  - Create `reddit_saas/ui_lint_allowlist.txt` with entries for all existing violations, grouped by file with justification comments
  - Format: `path/to/file.html:violation-type  # justification`
  - Requirements: 1.11, 9.9

- [ ] 7. Add Makefile targets for lint-ui and ci-ui
  - Add `lint-ui` target to `reddit_saas/Makefile`: runs `python scripts/lint_ui.py app/templates/`
  - Add `ci-ui` target that runs lint-ui (blocking for Phase 1; drift + specs added in later phases)
  - Requirements: 1.12, 8.6

## Phase 2: UI_MAP Generator + Drift Detection (3-5 days)

- [ ] 8. Create UI_MAP generator script — template scanner
  - Create `reddit_saas/scripts/generate_ui_map.py` implementing `UIMapGenerator` class
  - Implement template scanning: glob `app/templates/**/*.html`, extract `{% extends %}` to detect theme, extract `{% include %}` to map component usage, extract `data-component`/`data-owner`/`data-variant` attributes
  - Build `PageEntry` and `ComponentEntry` data structures
  - Requirements: 2.1, 2.2, 2.3, 2.4

- [ ] 9. Create UI_MAP generator — route extraction
  - Extend `generate_ui_map.py` to scan `app/routes/*.py` files
  - Extract `@router.get`/`@router.post` decorators paired with `TemplateResponse(name="...")` calls
  - Map route URL → template file path
  - Detect theme from base template inheritance chain
  - Requirements: 2.1, 2.4

- [ ] 10. Create UI_MAP generator — Markdown rendering
  - Implement `render_markdown()` method producing deterministic sorted output
  - Structure output with sections: Admin Panel, Client Portal, Public Pages, Marketing Site, Uncategorized
  - Include auto-generated markers (`<!-- AUTO-GENERATED -->`) to separate from manual sections
  - Generate initial `UI_MAP.md` at project root with manually authored navigation paths and descriptions placeholder
  - Requirements: 2.7, 2.8, 2.10, 2.12, 2.13

- [ ] 11. Implement drift detection and reporting
  - Add `--check` mode to `generate_ui_map.py` that compares auto-generated output against existing `UI_MAP.md`
  - Report: new templates not documented, removed templates still documented, renamed files
  - Add `--strict` flag for CI-blocking mode (exit 1 on drift)
  - Support `UI_MAP_DRIFT_MODE` environment variable (warn/error)
  - Requirements: 2.5, 2.6, 2.7, 2.9, 2.11

- [ ] 12. Add generate-ui-map Makefile target and integrate into ci-ui
  - Add `generate-ui-map` target to Makefile
  - Extend `ci-ui` target to run drift check after lint
  - Requirements: 2.10, 8.6

## Phase 3: Debug Overlay Engine (5-7 days)

- [ ] 13. Create debug overlay engine — core module and activation
  - Create `reddit_saas/app/static/js/debug-overlay.js`
  - Implement activation check: `document.body.dataset.debugUi === 'true'` AND `localStorage.getItem('debug_ui_active') === 'true'`
  - Expose `window.RampDebug` namespace with `activate()`, `deactivate()`, `toggle(layer)`, `rescan()`
  - Load layer preferences from `localStorage.getItem('debug_ui_prefs')`
  - Requirements: 6.1, 6.2

- [ ] 14. Implement border overlay layer
  - Scan all `[data-component]` elements in DOM
  - Call `getBoundingClientRect()` on each and draw 2px solid colored border using absolutely-positioned overlay div
  - Use rotating color palette (6+ distinct colors) assigned by component type or DOM order
  - Ensure overlays don't affect layout (`pointer-events: none`, absolute positioning on separate z-layer)
  - Requirements: 6.3, 6.11

- [ ] 15. Implement label overlay layer
  - For each `[data-component]` element, create a small positioned label showing `data-component` value + `data-owner` value
  - Display current page template path in a fixed header bar
  - Labels use small font, semi-transparent background, positioned at top-left of component boundary
  - Requirements: 6.4, 6.12

- [ ] 16. Implement grid overlay layer
  - Detect elements using CSS Grid or Flexbox layout (via `getComputedStyle`)
  - Draw column boundaries, row gaps, and container edges as semi-transparent overlay lines
  - Requirements: 6.5

- [ ] 17. Implement floating toggle panel
  - Create fixed-position panel (bottom-right, high z-index)
  - Three toggle buttons: Borders, Labels, Grid — each independently controllable
  - Persist preferences to `localStorage` under `debug_ui_prefs` key
  - Show/hide panel via a small toggle button
  - Requirements: 6.6, 6.7

- [ ] 18. Implement HTMX re-scan support
  - Listen for `htmx:afterSwap` event, re-scan only `evt.detail.target` subtree for new `[data-component]` elements within 200ms
  - Listen for `htmx:beforeSwap` event, remove overlay elements for the target container before content replacement
  - Requirements: 6.8, 6.9

- [ ] 19. Implement viewport-only rendering for performance
  - Use IntersectionObserver to track which `[data-component]` elements are visible
  - Only render overlays for visible elements
  - Recalculate positions on scroll/resize via `requestAnimationFrame` (within 100ms)
  - When page has >200 `[data-component]` elements, enforce viewport-only mode
  - Requirements: 6.13, 6.14

- [ ] 20. Integrate debug overlay into base templates
  - Add conditional script inclusion in all three base templates: `{% if app_env != 'production' %}<script src="/static/js/debug-overlay.js" defer></script>{% endif %}`
  - Verify debug script NOT included when `app_env == 'production'`
  - Requirements: 6.10

## Phase 4: Screen Specs + Component Contracts (3-5 days)

- [ ] 21. Create component contract YAML files
  - Create `reddit_saas/docs/contracts/` directory
  - Write `input.yaml`: states (default/focus/error/disabled), height/padding/border tokens per state per theme, focus ring spec, error message positioning
  - Write `button.yaml`: variants enum (primary/secondary/danger/ghost), loading state, padding/radius/font tokens, hover effects, disabled opacity
  - Write `loading.yaml`, `error.yaml`, `empty.yaml` contracts
  - Requirements: 5.1, 5.2, 5.3, 5.4, 5.7

- [ ] 22. Create parametric component macros based on contracts
  - Create `reddit_saas/app/templates/_macros/_input.html` — parametric input with states
  - Create `reddit_saas/app/templates/_macros/_button.html` — parametric button with variants
  - Create `reddit_saas/app/templates/_macros/_loading.html` — loading state (skeleton vs spinner)
  - Create `reddit_saas/app/templates/_macros/_error.html` — error display with dismissal
  - Create `reddit_saas/app/templates/_macros/_empty.html` — empty state with CTA
  - Each macro uses design tokens from `tokens.css` and includes component markers
  - Requirements: 4.1, 4.3, 5.1, 5.5, 5.6

- [ ] 23. Create screen spec YAML schema and validation script
  - Create `reddit_saas/scripts/validate_screen_specs.py` implementing `ScreenSpecValidator`
  - Define JSON Schema for screen spec format (required fields: page, theme, entry, states, sections, verifiable_by)
  - Validate `theme` enum (admin/client/public), `verifiable_by` enum, states must have all 4 keys, sections non-empty
  - Check coverage: report templates with routes that lack a YAML spec file
  - Exit code 1 on schema violations, warnings for missing coverage
  - Requirements: 7.1, 7.2, 7.7, 7.8

- [ ] 24. Write screen specs for 5 critical pages
  - Create `reddit_saas/docs/screen_specs/` directory
  - Write YAML specs for: `admin_dashboard.yaml`, `admin_clients.yaml`, `portal_home.yaml`, `portal_review.yaml`, `login.yaml`
  - Each spec includes: page URL, theme, entry path, all 4 states described, sections with visual content, verifiable_by, test_data
  - Requirements: 7.2, 7.3, 7.4, 7.5, 7.6, 7.9

- [ ] 25. Add validate-specs Makefile target and complete ci-ui pipeline
  - Add `validate-specs` target to Makefile
  - Update `ci-ui` to run full sequence: lint → markers → drift → specs validation
  - Verify `ci-ui` exits with highest non-zero code from any blocking check
  - Requirements: 8.5, 8.6

- [ ] 26. Add duplicate DOM pattern detection to lint script
  - Extend `lint_ui.py` with hash-based DOM fingerprinting (tag + class structure)
  - Group fragments by fingerprint, report groups appearing 3+ times as extraction candidates
  - Include in existing `lint-ui` target
  - Requirements: 1.6, 4.4, 8.1
