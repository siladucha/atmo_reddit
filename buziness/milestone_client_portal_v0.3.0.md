# Milestone Delivery: Client Portal v0.3.0

**Version:** 0.3.0
**Delivery Date:** June 17, 2026
**Status:** Deployed to production (gorampit.com)
**Scope:** Client Manager Onboarding + Portal UX Overhaul

---

## Delivery Summary

This milestone implements Tzvi's UX/UI Brief v2 and Business Brief requirements for the client-facing product. A client_manager user now has a complete self-contained portal experience from signup through daily operations.

**Production URLs:**
- Trial signup: `https://gorampit.com/onboard/trial`
- Client login: `https://gorampit.com/login`
- Portal home: `https://gorampit.com/clients/{id}/home`

---

## Module Breakdown

### Module 1: Self-Serve Trial Signup

**Route:** `GET /onboard/trial` → `POST /onboard/trial/signup`

**How it works:** Prospect fills signup form with work email, company name, password. System validates email domain (blocks 23 personal providers: Gmail, Hotmail, Yahoo, etc.), creates a Client record (plan_type=trial, max_avatars=0) and a User record (role=client_admin), issues JWT cookie, redirects to onboarding wizard.

**Principle:** Intelligence-only trial. Client sees the analysis layer (scored threads, competitor presence, landscape report) but cannot post (no avatars allocated). Conversion happens via upgrade CTA.

### Module 2: 6-Step Onboarding Wizard

**Route:** `GET/POST /onboard/step/{1-6}`

**How it works:**
1. **Company Intelligence** — Client enters URL → httpx scrapes website → Gemini Flash synthesizes profile → editable card displayed
2. **Problem & Competitors** — Free-text prompts → AI extracts worldview, problem, competitive landscape
3. **ICP Definition** — B2B/B2C toggle, job titles, frustrations → AI synthesizes ICP prose
4. **Voice & Guardrails** — Never-associate topics, legal limits, style inspiration + Tone Calibration Loop (5 AI sentences, client rates 1-5, anchors stored)
5. **Keywords & Subreddits** — AI suggests keywords (high/medium/low) + subreddits with rationale → client confirms/removes
6. **Review & Activate** — Quality gate checks completeness → activate → triggers Day 1 scraping

**Principle:** Feels like a strategist intake, not a form. Each step trains the AI. Quality gate prevents thin briefs from producing bad output.

### Module 3: Privacy Layer

**DB fields:** `avatars.display_name`, `avatars.persona_bio`

**How it works:** Client portal never shows Reddit usernames or raw karma numbers. Instead shows:
- Persona display name (e.g. "Alex" not "Hot-Thought2408")
- One-line bio ("Breathing coach & biohacker")
- Karma tier label (Newcomer / Building / Established / Authority)

When display_name is NULL → fallback to reddit_username with orange ⚙ indicator and tooltip.

**Principle:** Avatars are a service, not property. Client manages outcomes, not infrastructure. Admin panel still shows real usernames.

### Module 4: Day 1 Landscape Report

**Route:** `GET /clients/{id}/landscape`

**How it works:** Analyzes existing scraped threads in client's subreddits. Counts keyword matches, competitor mentions, high-intent threads where brand is absent. Renders: funnel stats, competitor mention list, opportunity threads, share of voice bars.

If no data yet (fresh onboarding): shows scanning animation with HTMX auto-refresh every 30 seconds until threads appear.

**Principle:** The "aha moment" — client sees their invisibility immediately. No avatars needed. Converts trial to paid.

### Module 5: Review Queue Enhancements

**Route:** `GET /clients/{id}/review`, `GET /clients/{id}/partials/drafts`

**New features:**
- **Batch approve** — Checkboxes on pending cards. Sticky bar at 2+ selections: "Approve Selected". Parallel API calls.
- **Regenerate with note** — Browser prompt: "What should be different?" → note injected into AI regeneration context as `reason` parameter.

**Principle:** PMM persona spends 30-60 min/week here. Every edit is a training signal. Batch operations respect their time.

### Module 6: Momentum Events Feed

**Route:** `GET /clients/{id}/partials/momentum` (HTMX loaded on home)

**How it works:** Queries ActivityEvent records for this client (last 7 days). Renders timeline with typed icons (🔍 scrape, ✍ generate, 🚀 phase promotion, 🚨 health alert). Shows subreddit pills and karma scores where relevant.

**Principle:** Client must feel the system is working. Every action is visible. Progress is undeniable.

### Module 7: Report & PDF Download

**Route:** `GET /clients/{id}/report/download?days=30|60|90`

**How it works:** Generates standalone HTML file with executive metrics, subreddit table, top comments. Served as download attachment. Client opens in browser → Print → Save as PDF.

**Principle:** The report is the champion's internal tool. Opens with progress, not process. Designed to forward to CMO unchanged.

### Module 8: Budget & Upsell System

**How it works:** `_get_usage_context()` calculates monthly actions vs plan limit on every page render. Injects `usage_pct`, `budget_warning`, `budget_exhausted`, `avatar_at_limit`, `sub_at_limit` into template context.

**UI effects:**
- 80% usage → amber banner with Upgrade CTA
- 100% usage → red banner: "Monthly limit reached"
- Subreddit at limit → "$99/month for 5 more" message
- Avatar at limit → dashed upsell card on avatars page
- Share of Voice → locked for Seed/Starter ("Available on Growth plan")

**Principle:** Contextual, data-driven upsells at the moment of friction. Never more than one per screen. Non-blocking.

### Module 9: Trial Lifecycle

**How it works:**
- Trial banner on every portal page: "Free Trial — X days remaining — Upgrade →"
- 14-day hard enforcement: after 14 days, `_portal_render` serves `trial_expired.html` instead of any portal page
- Data preserved: client profile, keywords, subreddits, landscape data all kept for conversion

**Principle:** Trial is not punishment. It demonstrates value. Expiration is a conversion mechanism, not a wall.

### Module 10: Tone Calibration Loop (Onboarding Step 4)

**Route:** `POST /onboard/step/4/calibrate`

**How it works:** AI generates 5 Reddit-style sample sentences in the brand voice. Client rates each 1-5. Sentences rated 4-5 stored as "tone anchors" in `brand_voice` field. These become few-shot examples for all future AI generation.

**Principle:** The most important quality gate in onboarding. Good tone anchors = good content = retention. Cannot be skipped (advisory in MVP, enforced later).

---

## Architecture Principles

1. **Show only what matters.** Every screen element earns its place. If the client doesn't act on it, remove it.

2. **Client manages outcomes, not infrastructure.** No usernames, no raw karma, no proxy details, no AI costs. Client sees: what was posted, how it performed, what's next.

3. **Safety is technical, not advisory.** Phase gates, brand mention blocks, budget caps — all enforced server-side. Client cannot override.

4. **Every edit trains the system.** Approvals, rejections, text edits, voice feedback, tone ratings — all captured as signals. The longer a client uses RAMP, the harder it is to leave.

5. **Intelligence before execution.** Trial proves value through insight (you're invisible, competitors aren't). Posting is the upsell, not the demo.

---

## Files Changed (Key)

| Module | Files |
|--------|-------|
| Trial Signup | `routes/onboarding.py`, `middleware/auth.py`, `templates/onboarding/trial_signup.html` |
| Privacy | `models/avatar.py`, `routes/portal.py`, `templates/client/avatars.html`, `templates/client/avatar_detail.html` |
| Landscape | `services/onboarding/landscape_report.py`, `routes/portal.py`, `templates/client/landscape.html` |
| Review Enhancements | `routes/portal_actions.py`, `templates/partials/client/drafts_list.html` |
| Momentum | `routes/portal.py`, `templates/partials/client/momentum_feed.html` |
| PDF Report | `routes/portal.py`, `templates/client/report_pdf.html`, `templates/client/report.html` |
| Budget/Upsell | `routes/portal.py`, `templates/client_base.html`, `templates/client/avatars.html` |
| Trial Lifecycle | `routes/portal.py`, `routes/pages.py`, `templates/client/trial_expired.html` |
| Tone Calibration | `routes/onboarding.py`, `templates/onboarding/step4.html` |
| DB Migration | `alembic/versions/ux030_add_avatar_display_name_persona.py` |

---

## Known Limitations

1. PDF is HTML-based (browser Print → Save as PDF). True PDF generation deferred.
2. Tone calibration is advisory — does not block wizard completion in MVP.
3. Landscape report depends on scraped data — 5-10 min delay after onboarding.
4. Share of Voice is comment count, not percentage — requires GEO module for true SOV.
5. Display names require manual admin setup per avatar.

---

## Sign-off

| Role | Name | Status |
|------|------|--------|
| Development | Max | ✅ Delivered |
| QA | Jenny | Pending (test plan ready) |
| Product | Tzvi | Pending review |
