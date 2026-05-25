# Implementation Tasks — Client Portal Redesign

## Phase P0: Sales-Ready Portal (Priority: P0, ~5-6 days)

### Task 1: Design Token System & Base Template
- [ ] Create `app/static/css/client-tokens.css` with all CSS custom properties (colors, typography, spacing, radius, shadows, transitions) per UX spec v3
- [ ] Create `app/templates/client_base.html` — new base template extending nothing, includes client-tokens.css, Tailwind CDN, HTMX, sidebar include, toast container
- [ ] Ensure `client_base.html` is fully independent from `base.html` and `admin_base.html` — no shared token pollution
- [ ] Add skeleton loading CSS animation (opacity pulse 0.4–0.7, 1.2s interval) to client-tokens.css
- [ ] Add toast notification CSS (bottom-right positioning, slide-from-right animation, stacked max 3)
- _Requirements: 1, 2, 9_

### Task 2: Sidebar Navigation Partial
- [ ] Create `app/templates/partials/client/sidebar.html` — fixed 240px left panel, full viewport height, --color-surface background
- [ ] Add nav items: Home (icon), Review Queue (icon + badge), Avatars (icon), Settings (icon)
- [ ] Implement active state: 3px solid orange left border + surface-alt background, determined by current URL path
- [ ] Add pending draft count badge on Review Queue item (orange pill, red if >10) — passed via template context
- [ ] Add red dot badge on Avatars item when any client avatar is shadowbanned — passed via template context
- [ ] Add client company name in bottom-pinned footer section (truncated to 20 chars with ellipsis)
- [ ] Ensure main content area offset by 240px from left edge
- [ ] Wire nav items with `hx-get` + `hx-push-url` for SPA-like navigation without full page reload
- _Requirements: 3_

### Task 3: Portal Router & Dependencies
- [ ] Create `app/routes/portal.py` — new APIRouter with prefix pattern for `/clients/{client_id}`
- [ ] Add `require_client_access(client_id)` dependency on all portal routes (reuse existing RBAC guard)
- [ ] Implement `GET /clients/{client_id}` → redirect to `/clients/{client_id}/home`
- [ ] Implement `GET /clients/{client_id}/home` → render `client/home.html` with sidebar context (pending_count, has_shadowbanned)
- [ ] Implement `GET /clients/{client_id}/review` → render `client/review.html` with draft list
- [ ] Register portal router in `app/main.py`
- [ ] Add helper function `get_sidebar_context(client_id, db)` → returns pending_count, has_shadowbanned, client_name
- _Requirements: 3, 16_

### Task 4: API Response Allowlist Schemas
- [ ] Create `app/schemas/client_portal.py` with Pydantic models: `ClientDraftResponse`, `ClientAvatarResponse`, `ClientMetricsResponse`
- [ ] `ClientDraftResponse`: id, avatar_name, avatar_phase, subreddit_name, thread_title, thread_body_excerpt (120 chars), comment_text, comment_approach, created_at, status
- [ ] `ClientAvatarResponse`: id, name, bio, warming_phase, karma_tier (label not int), last_active_at, is_shadowbanned, active_subreddits list
- [ ] `ClientMetricsResponse`: comments_posted, total_upvotes, active_subreddits, pending_drafts
- [ ] Ensure NO sensitive fields: reddit_username, proxy_ip, browser_profile_id, raw_karma_score, ai_cost, confidence_score, survival_rate, phase_eligibility_calculation
- [ ] Apply schemas to all portal API responses (response_model parameter on endpoints)
- _Requirements: 7_

### Task 5: Home Screen
- [ ] Create `app/templates/client/home.html` extending `client_base.html`
- [ ] Add 3 headline metric cards (Comments Posted, Total Upvotes, Subreddits Active) with --text-display numbers, --text-small labels
- [ ] Add skeleton loading placeholders for metrics (shown on initial load, replaced by HTMX partial)
- [ ] Create `GET /clients/{client_id}/partials/metrics` endpoint — returns metric cards partial with real data
- [ ] Implement Pending Approvals CTA: 0 items → grey pill "Queue empty"; 1-4 → amber pill with count; 5+ → orange banner with "Review now →" link
- [ ] CTA links to review queue page
- [ ] Implement metrics query: count posted drafts in period, sum upvotes (from reddit_score), count active subreddits
- _Requirements: 4, 9_

### Task 6: Review Queue — Draft Cards
- [ ] Create `app/templates/client/review.html` extending `client_base.html`
- [ ] Add page header: "Review Queue" title + "[N] drafts waiting for your approval" subtitle
- [ ] Create `app/templates/partials/client/draft_card.html` — card with: avatar name + phase badge (left), subreddit pill + timestamp (right), thread title bold, thread body excerpt (120 chars, muted), comment text on surface-alt background
- [ ] Create `app/templates/partials/client/skeleton_card.html` — skeleton placeholder matching draft card shape
- [ ] Add 3 action buttons per card: Approve (green fill), Edit (orange outline), Skip (ghost) — min 44px height
- [ ] Phase badge colors: Phase 1 grey, Phase 2 orange, Phase 3 green (using --color-phase1/2/3 tokens)
- [ ] Implement `GET /clients/{client_id}/partials/drafts` endpoint — returns list of draft cards for pending drafts, filtered by client_id
- [ ] Query: CommentDraft where status="pending", avatar.client_ids contains client_id, ordered by created_at desc
- _Requirements: 5, 9_

### Task 7: Review Queue — Approve/Skip/Edit Actions
- [ ] Implement `POST /clients/{client_id}/drafts/{id}/approve` — validate ownership, run safety check, update status to "approved", return 200 with HX-Trigger toast
- [ ] Implement `POST /clients/{client_id}/drafts/{id}/skip` — validate ownership, update status to "rejected" (or "skipped"), return 200 with HX-Trigger toast
- [ ] Implement `POST /clients/{client_id}/drafts/{id}/edit` — accept edited_text body, capture edit diff via `capture_edit_record`, run safety check, approve, return 200 with learning toast
- [ ] On approve: HTMX response removes card from DOM (`hx-swap="outerHTML swap:150ms"` with empty response)
- [ ] On skip: same card removal with fade animation
- [ ] On edit+approve: same card removal + toast "Got it — we'll remember this for future drafts"
- [ ] RBAC check: client_viewer cannot approve/edit (return 403)
- [ ] Call `notify_owner_new_draft` after approve (if Telegram bot is active — graceful skip if not)
- _Requirements: 5, 6_

### Task 8: Safety Blocks (Brand Mention Protection)
- [ ] Create `app/services/safety_blocks.py` with `check_safety_blocks(draft, client)` function
- [ ] Implement brand mention detection: if avatar.warming_phase < 3 AND client.brand_name found in comment_text → return block info
- [ ] On safety block: approve endpoint returns 422 with JSON `{rule, avatar_phase, brand_detected, message}`
- [ ] Client-side: on 422 response, inject red banner at top of draft card via `hx-swap-oob` with block message
- [ ] Disable Approve button while safety block is active (re-enable after edit removes brand mention)
- [ ] Server-side enforcement: approve endpoint ALWAYS checks safety regardless of client-side state
- _Requirements: 6_

### Task 9: Toast Notification System
- [ ] Create `app/static/js/toast.js` — listens for HTMX `showToast` trigger events, creates toast elements
- [ ] Toast positioning: fixed bottom-right, max 3 stacked, newest at bottom
- [ ] Auto-dismiss after 4 seconds with fade-out animation
- [ ] Color coding: success → --color-green, warning → --color-amber, error → --color-red
- [ ] Slide-from-right entry animation (150ms ease-out)
- [ ] Include toast.js in `client_base.html`
- [ ] Server sends toasts via `HX-Trigger: {"showToast": {"type": "success", "message": "Approved"}}` response header
- _Requirements: 8_

### Task 10: Integration & Polish
- [ ] Verify admin panel unchanged — no modifications to `admin_base.html` templates or `/admin/` routes
- [ ] Verify existing API endpoints used by admin panel still work without breaking changes
- [ ] Test RBAC: client_admin can approve, client_viewer can only view, owner/partner can preview portal
- [ ] Test safety block: brand mention in Phase 1/2 draft → 422 → red banner → edit removes mention → approve works
- [ ] Test optimistic updates: approve removes card immediately, server error restores it
- [ ] Verify no sensitive data leaks in any portal response (check with browser dev tools)
- [ ] Add portal link to admin client detail page ("Preview Client Portal →")
- _Requirements: 16_

---

## Phase P1: Client Experience (Priority: P1, ~4-5 days)

### Task 11: Avatars Screen
- [ ] Create `app/templates/client/avatars.html` — card grid (3 col desktop, 2 tablet, 1 mobile)
- [ ] Avatar card: name, bio, phase badge, karma tier label (not raw score), last active timestamp
- [ ] Amber "last active" text if >7 days inactive
- [ ] Red "PAUSED" banner on shadowbanned avatars
- [ ] Empty state: "Your avatars are being configured. Check back in 24–48 hours."
- [ ] Implement `GET /clients/{client_id}/avatars` route with `ClientAvatarResponse` schema
- _Requirements: 11, 14_

### Task 12: System Banners
- [ ] Create `app/templates/partials/client/system_banner.html` — full-width banner component
- [ ] Red banner: shadowbanned avatar detected → "[Avatar] has been paused. We are investigating — no action needed from you."
- [ ] Amber banner: no approvals in 7+ days → "Your drafts are waiting. Unapproved content delays avatar progress."
- [ ] Priority: red > amber, show only one at a time
- [ ] Red banner: not dismissable. Amber banner: dismissable with 24h snooze (localStorage)
- [ ] Include banner in `client_base.html` content area top
- _Requirements: 12_

### Task 13: Filter Bar (Review Queue)
- [ ] Create filter chip row below review queue subtitle
- [ ] Avatar filter chips (one per client avatar) + Subreddit filter chips (top 5 + "More" dropdown)
- [ ] Active filters shown as removable chips with × icon
- [ ] "Clear all" text link at right end
- [ ] Filter state persisted in URL query parameters (?avatar=X&subreddit=Y)
- [ ] HTMX reload of draft list on filter change
- _Requirements: 10_

### Task 14: Settings Screen
- [ ] Create `app/templates/client/settings.html` — sections: Keywords, Subreddits, Brand Guardrails
- [ ] Keywords: chip display with add/remove via HTMX, priority labels (high/medium/low)
- [ ] Subreddits: list with add/remove via HTMX
- [ ] Brand guardrails: editable tag inputs for "never associate" terms
- [ ] RBAC: client_viewer sees read-only (edit controls hidden)
- [ ] Implement HTMX endpoints for inline CRUD operations
- _Requirements: 13_

### Task 15: Empty States
- [ ] Create `app/templates/partials/client/empty_state.html` — reusable component with icon, title, description
- [ ] Review Queue empty: "Nothing to review right now. Your avatars are active — new drafts appear here as opportunities are found." + "Last draft appeared: X ago"
- [ ] Avatars empty: "Your avatars are being configured. Check back in 24–48 hours."
- [ ] Home momentum empty: "No activity yet. Your avatars are warming up — momentum events will appear here as they engage."
- [ ] Style: --color-muted text, centered on --color-surface background
- _Requirements: 14_

### Task 16: Onboarding Wizard (Simplified)
- [ ] Create `app/templates/client/onboarding.html` — full-screen takeover, no sidebar
- [ ] 5 steps: Company Profile → ICP → Keywords → Subreddits → Brand Guardrails
- [ ] Progress bar: 4px height, orange fill, step label "Step N of 5"
- [ ] Validation: required fields must be completed before next step
- [ ] On completion: save config, redirect to home, toast "Setup complete. Your avatars will be active in 24–48 hours."
- [ ] Back navigation with pre-filled fields
- [ ] Trigger: first login when client has no keywords AND no subreddits
- _Requirements: 15_

---

## Phase P2: Deferred (Post-Launch)

### Task 17: Insights Screen
- [ ] Share of Voice, Top Content, High-Intent Appearances, Content Recommendations, Subreddit Performance
- _Requirements: (future — not in current requirements)_

### Task 18: Mobile Layout
- [ ] Bottom tab bar replacing sidebar on <768px
- [ ] 2×2 action button grid on mobile
- [ ] Full-screen textarea overlay for editing
- _Requirements: (future)_

### Task 19: Batch Approve
- [ ] Checkboxes on cards, sticky "Approve selected (X)" bar
- [ ] Safety check on batch — warn about blocked drafts
- _Requirements: (future)_

### Task 20: Upsell System
- [ ] Server-side upsell_trigger in page context
- [ ] Max one upsell per screen
- [ ] Contextual CTAs based on plan limits
- _Requirements: (future)_

---

## Dependencies & Blockers

| Task | Depends On | Notes |
|------|-----------|-------|
| Task 3 (Router) | Existing RBAC (require_client_access) | Already built |
| Task 7 (Actions) | Task 6 (Draft cards exist) | Sequential |
| Task 8 (Safety) | Task 7 (Approve endpoint exists) | Sequential |
| Task 9 (Toast) | Task 1 (Base template exists) | Sequential |
| All P1 tasks | P0 complete | Phase gate |

## Estimated Timeline

| Phase | Duration | Notes |
|-------|----------|-------|
| P0: Sales-Ready | 5-6 days | Tokens + sidebar + home + review queue + safety + toast |
| P1: Client Experience | 4-5 days | Avatars + banners + filters + settings + empty states + wizard |
| P2: Deferred | TBD | Insights, mobile, batch, upsell |
| **Total P0+P1** | **9-11 days** | Full client portal |

## Success Criteria

| Metric | Target |
|--------|--------|
| Client can log in and see dashboard | P0 |
| Client can approve/edit/skip drafts | P0 |
| Safety blocks prevent premature brand mentions | P0 |
| No sensitive data exposed in any response | P0 |
| Admin panel completely unaffected | P0 |
| Tzvi can demo to prospects | P0 complete |
