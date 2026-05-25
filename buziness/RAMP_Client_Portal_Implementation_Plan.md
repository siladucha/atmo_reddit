# RAMP Client Portal — Implementation Plan & Response to UX Spec v3

## For: Tzvi
## From: Max (Tech)
## Date: May 21, 2026

---

## Executive Summary

I've reviewed both documents (UX Developer Spec v3 and Brand Guidelines). The spec is excellent — detailed, well-structured, and covers every edge case. It's exactly what we need as a North Star.

Here's the plan: I'm implementing this in phases, starting with the core experience that clients will use daily. The backend is already built — this is a frontend redesign of the existing Client Hub that client managers already access.

**Key point:** The system already works. Clients already log in, see their data, and review drafts. What we're doing now is making it look and feel like a premium product instead of an internal tool.

---

## What Gets Built — Phase 1 (2-3 weeks)

These are the things clients interact with every single day:

### Dark Theme + Design System
- Full dark theme per the spec (#0D0D1A background, orange accents, the whole token system)
- New `client_base.html` template — admin panel stays untouched
- All the typography, spacing, border-radius tokens from Section 01

### Sidebar Navigation
- Fixed 240px sidebar replacing the current tab bar
- 4 items: Home, Review Queue, Avatars, Settings
- Badge on Review Queue (pending count), red dot on Avatars (if shadowbanned)
- Company name in footer

### Review Queue (Core Value)
- Redesigned cards per the spec (avatar + phase badge, subreddit pill, thread excerpt, draft text)
- 3 actions: Approve (green), Edit (orange), Skip (ghost)
- Inline editing with "Save & Approve"
- Optimistic updates (card disappears immediately on approve)
- Toast notifications (bottom-right, auto-dismiss 4s)
- Brand mention safety block (red banner, blocks approve for Phase 1/2)
- Skeleton loading (no spinners)

### Home Screen
- 3 headline metrics (Comments Posted, Upvotes Earned, Subreddits Active)
- Pending Approvals CTA (scales with queue depth)
- Momentum Events feed (breakout comments + shadowban alerts only)

### API Security
- Response allowlist on all client-facing endpoints
- Never expose: reddit_username, proxy_ip, karma score, AI cost, confidence score

---

## What Gets Built — Phase 2 (weeks 4-5)

### Avatars Screen
- Card grid (name, bio, phase badge, last active)
- Shadowban "PAUSED" banner
- Empty state for pre-activation

### Settings Screen
- Keywords management (add/remove/priority)
- Subreddits management (add/remove)
- Brand guardrails (tag input)
- RBAC enforced (viewer = read-only)

### System Banners
- Shadowban alert (red, non-dismissable)
- 7-day inactivity warning (amber, 24h snooze)

### Filter Bar (Review Queue)
- Avatar + Subreddit chip filters
- URL param persistence

### Empty States
- Branded copy for all screens per Section 11

---

## What Gets Built — Phase 3 (weeks 6-8)

### Simplified Onboarding Wizard
- 5 steps: Company Profile → ICP → Keywords → Subreddits → Guardrails
- Form-based (no web scraping, no AI auto-fill)
- Progress bar, validation, back navigation
- Full-screen takeover on first login

---

## What's Deferred (v2 — after pilot feedback)

| Feature | Reason | When |
|---------|--------|------|
| Insights screen (Share of Voice, Content Recommendations) | Requires competitor data aggregation | After 10 clients |
| Batch Approve | Clients handle 10-20 drafts manually fine | After feedback |
| Avatar Detail slide-in panel | Card grid is sufficient for MVP | After feedback |
| Strategic Rationale accordion | Needs stable ML explanations | v2 |
| PDF Report generation | Complex; CSV export available now | v2 |
| Mobile-optimized layout (bottom tab bar) | Responsive desktop works on mobile | v2 |
| Upsell system | No paid tiers in pilot | After PMF |
| Tone Calibration Loop (file upload + rating) | Complex AI loop | v2 |
| WebSocket real-time updates | Polling (30s) works fine | v2 |
| Plan & Billing | One flat plan during pilot | After PMF |
| Team / Invite | Single user per client in pilot | v2 |

---

## What We Never Build

- **Web scraping for onboarding auto-fill** — 2-3 months of Puppeteer/anti-bot work for a "wow moment" that doesn't affect core value
- **Pre-warmed avatar marketplace** (Silver/Gold upsell) — violates Reddit ToS

---

## Timeline

| Week | Deliverable | Client Impact |
|------|-------------|---------------|
| 1 | Design tokens + dark theme + sidebar + base template | Visual foundation |
| 2 | Review Queue redesign (cards, actions, optimistic updates, safety blocks) | Core daily workflow |
| 3 | Home screen + toast system + skeleton loading | Dashboard experience |
| 4 | Avatars screen + Settings screen | Full navigation |
| 5 | System banners + filter bar + empty states | Polish |
| 6-7 | Onboarding wizard (5 steps) | New client flow |
| 8 | Testing with pilot clients, bug fixes | Launch-ready |

---

## What Clients Will Experience

**Before (current):**
- Light theme, looks like an internal admin tool
- Tab-based navigation
- Basic review functionality
- No branded experience

**After (Phase 1 complete):**
- Dark, polished RAMP-branded portal
- Sidebar navigation with live badges
- Smooth review workflow (approve in one click, instant feedback)
- Safety blocks protecting avatar credibility
- Professional metrics dashboard

---

## Technical Notes (for reference)

- Stack unchanged: Python/FastAPI + Jinja2 + HTMX + Tailwind CSS
- No React, no separate SPA — server-rendered with HTMX for interactivity
- Admin panel completely untouched (separate template inheritance)
- All existing backend logic (pipeline, RBAC, learning loop) stays as-is
- This is purely a frontend/template layer change + API response filtering

---

## Questions for You

1. **Pilot timeline** — When do you want the first client to see this? I can have Phase 1 (dark theme + review queue + home) ready in 2-3 weeks.

2. **Brand Guidelines vs UX Spec conflict** — The UX spec uses orange (#FF6B35) as the primary accent. The Brand Guidelines say "never use orange." I'm going with the UX spec for the product UI (orange), and Brand Guidelines for marketing materials (blue). Correct?

3. **Onboarding priority** — For existing pilot clients (XM Cyber), they're already onboarded via admin. The wizard is for NEW clients. Should I prioritize it (Phase 3) or focus on polishing the daily experience first?

---

**Bottom line:** The spec is our roadmap for the next 12 months. Phase 1 (3 weeks) gives clients a premium experience on the thing they use daily — reviewing and approving content. Everything else layers on top.
