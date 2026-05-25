# Design Document — Client Portal Redesign

## Overview

Transform the existing Client Hub (`/clients/{client_id}`) into a polished, dark-themed client-facing portal following the RAMP UX Developer Spec v3. The backend is already built — this is primarily a frontend/template layer change with a thin API response filtering layer.

**Phasing for MVP (sales-ready):**
- **P0 (this sprint):** Design tokens, dark theme, sidebar nav, home screen, review queue, safety blocks, API allowlist, toast system, skeleton loading
- **P1 (post-first-sale):** Onboarding wizard, avatars screen, momentum feed, system banners, filter bar, settings, empty states
- **P2 (deferred):** Insights screen, batch approve, mobile layout, upsell system, reports

## Architecture

### Template Hierarchy

```
templates/
├── base.html              # Light theme (existing, unchanged)
├── admin_base.html        # Dark theme admin (existing, unchanged)
├── client_base.html       # NEW — dark theme client portal
├── client/
│   ├── home.html          # Home/overview screen
│   ├── review.html        # Review queue
│   ├── avatars.html       # Avatars grid (P1)
│   ├── settings.html      # Settings screen (P1)
│   └── onboarding.html    # Onboarding wizard (P1)
└── partials/
    └── client/
        ├── sidebar.html           # Sidebar navigation
        ├── metric_card.html       # Headline metric card
        ├── draft_card.html        # Review queue draft card
        ├── toast.html             # Toast notification container
        ├── skeleton_card.html     # Skeleton loading placeholder
        ├── empty_state.html       # Empty state component
        ├── system_banner.html     # System banner (P1)
        └── avatar_card.html       # Avatar card (P1)
```

### Route Structure

```python
# New router: app/routes/portal.py
# Prefix: /clients/{client_id}
# Auth: require_client_access(client_id) dependency

GET  /clients/{client_id}              → redirect to /clients/{client_id}/home
GET  /clients/{client_id}/home         → home screen
GET  /clients/{client_id}/review       → review queue
GET  /clients/{client_id}/avatars      → avatars screen (P1)
GET  /clients/{client_id}/settings     → settings screen (P1)

# HTMX partials (hx-get targets)
GET  /clients/{client_id}/partials/drafts       → draft cards list
GET  /clients/{client_id}/partials/metrics      → metric cards
GET  /clients/{client_id}/partials/momentum     → momentum feed (P1)

# API actions
POST /clients/{client_id}/drafts/{id}/approve   → approve draft (with safety check)
POST /clients/{client_id}/drafts/{id}/skip      → skip draft
POST /clients/{client_id}/drafts/{id}/edit      → edit + approve draft
```

### API Response Allowlist

```python
# app/schemas/client_portal.py

class ClientDraftResponse(BaseModel):
    """Fields exposed to client-facing endpoints. Explicit include list."""
    id: UUID
    avatar_name: str
    avatar_phase: int
    subreddit_name: str
    thread_title: str
    thread_body_excerpt: str  # max 120 chars
    comment_text: str
    comment_approach: str | None
    created_at: datetime
    status: str

    # NEVER include: reddit_username, proxy_ip, ai_cost, confidence_score,
    # raw_karma_score, browser_profile_id, survival_rate, phase_eligibility_calculation

class ClientAvatarResponse(BaseModel):
    """Avatar data safe for client display."""
    id: UUID
    name: str
    bio: str | None
    warming_phase: int
    karma_tier: str  # "newcomer" | "building" | "established" | "authority"
    last_active_at: datetime | None
    is_shadowbanned: bool
    active_subreddits: list[str]

    # NEVER include: reddit_username, proxy_ip, raw karma int, ai_cost, confidence_score

class ClientMetricsResponse(BaseModel):
    """Home screen metrics."""
    comments_posted: int
    total_upvotes: int
    active_subreddits: int
    pending_drafts: int
```

### Design Token System

```css
/* app/static/css/client-tokens.css */
:root {
  /* Colors */
  --color-bg: #0D0D1A;
  --color-surface: #1A1A2E;
  --color-surface-alt: #1E1E32;
  --color-border: #2E2E4A;
  --color-orange: #FF6B35;
  --color-orange-light: #FF8C5A;
  --color-white: #FFFFFF;
  --color-muted: #AAAAAA;
  --color-red: #E53935;
  --color-amber: #F59E0B;
  --color-green: #22C55E;
  --color-phase1: #6B7280;
  --color-phase2: #FF6B35;
  --color-phase3: #22C55E;

  /* Typography */
  --text-display: 48px;
  --text-h1: 28px;
  --text-h2: 20px;
  --text-h3: 16px;
  --text-body: 14px;
  --text-small: 12px;
  --text-micro: 10px;

  /* Spacing (8px base) */
  --space-1: 8px;
  --space-2: 16px;
  --space-3: 24px;
  --space-4: 32px;
  --space-5: 40px;
  --space-6: 48px;

  /* Radius */
  --radius-card: 8px;
  --radius-input: 4px;
  --radius-pill: 999px;

  /* Shadows */
  --shadow-card: 0 2px 12px rgba(0,0,0,0.4);

  /* Transitions */
  --transition-fast: 150ms ease-out;
}
```

### Safety Block Logic (Server-Side)

```python
# In approve endpoint
def check_safety_blocks(draft: CommentDraft, client: Client) -> dict | None:
    """Return safety block info or None if safe to approve."""
    avatar = draft.avatar
    
    # Hard block: brand mention in Phase 1/2
    if avatar.warming_phase < 3:
        brand_terms = [client.brand_name.lower()]
        if any(term in draft.comment_text.lower() for term in brand_terms):
            return {
                "rule": "brand_mention_phase_block",
                "avatar_phase": avatar.warming_phase,
                "brand_detected": client.brand_name,
                "message": f"Brand mention blocked — {avatar.name} is still building credibility. Brand mentions unlock at Phase 3."
            }
    
    return None  # Safe to approve
```

### Toast Notification System

JavaScript-based, triggered by HTMX response headers or inline script:

```javascript
// Toast triggered via HX-Trigger response header
// Server sends: HX-Trigger: {"showToast": {"type": "success", "message": "Approved"}}
// JS listener creates toast element, auto-dismisses after 4s
```

### Optimistic Updates (Review Queue)

HTMX `hx-swap="outerHTML swap:150ms"` with CSS fade-out animation. On server error, HTMX `hx-swap-oob` restores the card.

## Data Flow

### Home Screen Load
1. Client navigates to `/clients/{client_id}/home`
2. Server renders `client/home.html` with skeleton placeholders
3. HTMX `hx-get` fires for `/clients/{client_id}/partials/metrics` (lazy load)
4. Metrics partial returns 3 metric cards with data
5. Pending approvals CTA rendered based on `pending_drafts` count

### Review Queue Approve Flow
1. Client clicks "Approve" button on draft card
2. HTMX `hx-post` to `/clients/{client_id}/drafts/{id}/approve`
3. Card fades out immediately (CSS animation via `hx-swap`)
4. Server runs safety check → if blocked, returns 422 with block info
5. On 422: card restored, red banner injected via `hx-swap-oob`
6. On 200: toast "Approved" via `HX-Trigger` header, sidebar badge decremented

### Review Queue Edit Flow
1. Client clicks "Edit" → JS transforms comment block to textarea
2. Client edits text, clicks "Save & Approve"
3. HTMX `hx-post` to `/clients/{client_id}/drafts/{id}/edit` with edited text
4. Server captures edit diff (learning signal), runs safety check, approves
5. Card fades out, toast "Got it — we'll remember this for future drafts"

## Security Considerations

- All client-facing endpoints use `require_client_access(client_id)` dependency
- API responses filtered through Pydantic allowlist schemas (never expose sensitive fields)
- Safety blocks enforced server-side (422 response) — client-side is UI hint only
- RBAC: client_viewer can view but not approve/edit; client_manager+ can approve
- No raw karma scores, reddit usernames, proxy IPs, or AI costs exposed

## Dependencies

- Existing RBAC system (require_client_access, query scoping)
- Existing CommentDraft model (status workflow)
- Existing learning loop (capture_edit_record on edit+approve)
- HTMX (already in use)
- Tailwind CSS CDN (already in use) — tokens override via custom CSS file

## Performance Targets

- Skeleton appears within 100ms of navigation
- Approve/Skip UI update within 200ms (optimistic)
- Metrics partial loads within 1s
- No spinner elements anywhere — skeleton loading only
