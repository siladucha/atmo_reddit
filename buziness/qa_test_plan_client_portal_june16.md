# QA Test Plan — Client Portal UX Update (June 16, 2026)

**Sprint:** Client Portal UX Brief v2 Implementation
**Prepared by:** Max (dev)
**For:** Jenny (QA)
**Date:** June 16, 2026
**Environment:** Local (Docker Compose) → then Production (161.35.27.165)

---

## Context

16 new features were added to the client portal based on Tzvi's UX/UI Brief v2 and Business Brief. This test plan covers:
- New feature scenarios (happy path + edge cases)
- Regression scenarios (existing flows must not break)

**Test accounts:**
- `jekorn12@gmail.com` — role: `client_manager`, client: NeuroYoga (existing user, regression)
- New trial account — create during testing via `/onboard/trial`
- `admin@ramp.com` / owner account — verify admin panel unaffected

---

## PART 1: New Feature Scenarios

### 1. Trial Signup Flow

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 1.1 | Navigate to `/onboard/trial` | Signup page loads: "See what your buyers are saying on Reddit", form with Full Name / Work Email / Company / Password | |
| 1.2 | Submit with `test@gmail.com` | Error: "Please use your work email. Personal emails not accepted." | |
| 1.3 | Submit with `test@hotmail.com` | Same error | |
| 1.4 | Submit with `test@protonmail.com` | Same error | |
| 1.5 | Submit with valid work email (e.g. `jenny@testcompany.io`), company "Test Corp", password 8+ chars | Redirects to `/onboard` → `/onboard/step/1`. User is logged in (cookie set). | |
| 1.6 | Check DB: new User exists with role=`client_admin`, client_id set | User linked to new Client with plan_type=`trial`, max_avatars=0 | |
| 1.7 | Try signup again with same email | Error: "This email is already registered. Please sign in." | |
| 1.8 | Navigate to `/login` page | Should show "Start your free trial" link at bottom | |

### 2. Onboarding Wizard (6 Steps)

**Prerequisite:** Logged in as trial user from 1.5

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 2.1 | Step 1: Enter `https://xmcyber.com` → click Analyze | Loading indicator → Profile card appears with auto-detected company info | |
| 2.2 | Step 1: Edit company name, click Next | Redirects to Step 2. Client record updated in DB. | |
| 2.3 | Step 2: Fill 3 text areas (before_product, unique_value, competitors), click Next | Redirects to Step 3. company_worldview/company_problem populated via AI | |
| 2.4 | Step 3: Select B2B, fill job titles + frustration + search query, click Next | Redirects to Step 4. icp_profiles populated. | |
| 2.5 | Step 4: Fill guardrails (never_associated, legal_limits, admired_style) | Fields saved | |
| 2.6 | Step 4: Click "Generate Sample Sentences" | 5 sample sentences appear with 1-5 rating options each | |
| 2.7 | Step 4: Rate 3+ sentences as 4 or 5, click Next | Redirects to Step 5. brand_voice field has "Tone anchors" section | |
| 2.8 | Step 4: Rate all sentences 1-2, click Next | Still proceeds (warning only, not blocking in MVP) | |
| 2.9 | Step 5: Click to trigger AI suggestions | Keywords (high/medium/low) and Subreddits appear with checkboxes | |
| 2.10 | Step 5: Deselect some, add custom keyword, click Next | Redirects to Step 6. keywords JSONB + ClientSubredditAssignment created | |
| 2.11 | Step 6: Review page shows all data. Click "Activate" | Redirects to `/onboard/complete`. client.onboarding_completed_at set. | |
| 2.12 | Complete page shows "View Landscape Report" button | Button links to `/clients/{id}/landscape` | |

### 3. Onboarding Resume

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 3.1 | During wizard (e.g. step 3), close browser, reopen, go to `/home` | Redirects to `/onboard` → resumes at last saved step (step 3) | |
| 3.2 | After completing wizard, go to `/home` | Redirects to `/clients/{id}/home` (portal, not wizard) | |

### 4. Day 1 Landscape Report

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 4.1 | After wizard completion, navigate to `/clients/{id}/landscape` | Page loads with: subreddits monitored, threads found (may be 0 initially) | |
| 4.2 | Wait 5 min (for scraping to run), refresh | Threads Found > 0. Competitor mentions and high-intent threads populate. | |
| 4.3 | Check Share of Voice section | Shows brand (0 or low) vs competitor bars | |
| 4.4 | "Upgrade" CTA button visible at bottom | Links to mailto:tzvi@... | |
| 4.5 | Landscape link visible in sidebar | Active orange state when on the page | |

### 5. Privacy Layer (Avatar Display)

**Test as:** `jekorn12@gmail.com` (client_manager, NeuroYoga)

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 5.1 | Go to `/clients/{id}/avatars` | See CARD layout (not table). Each card has initial circle + name. | |
| 5.2 | Check what name is shown | If display_name is set → shows display_name. If NULL → shows reddit_username (fallback). | |
| 5.3 | Check for raw karma numbers | NO raw number visible. Only "Trust: Newcomer/Building/Established/Authority" | |
| 5.4 | Click avatar card → detail page | Shows display_name in header. Karma tier. NO reddit_username visible. | |
| 5.5 | Check review queue → avatar names in draft cards | Display names used (or fallback to username if display_name NULL) | |
| 5.6 | Check EPG page → avatar names | Display names used | |
| 5.7 | Check report → top comments → avatar names | Display names used | |
| 5.8 | **Admin panel** (`/admin/avatars`) → same avatar | Still shows reddit_username (admin not affected by privacy layer) | |

### 6. Review Queue — Batch Approve

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 6.1 | Open review queue with 3+ pending drafts | Each pending card has a checkbox (left of avatar name) | |
| 6.2 | Check 1 item | No batch bar appears (need 2+) | |
| 6.3 | Check 2 items | Sticky bar appears: "2 selected — Approve Selected" | |
| 6.4 | Check 4 items | Bar updates: "4 selected" | |
| 6.5 | Click "Approve Selected" | All 4 cards animate out. Drafts moved to approved status. | |
| 6.6 | Refresh page | Approved count increased by 4. Pending decreased by 4. | |
| 6.7 | Check approved tab | The 4 drafts appear there | |
| 6.8 | No checkbox on safety-blocked drafts | If a draft has safety_block, no checkbox rendered | |

### 7. Review Queue — Regenerate with Note

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 7.1 | Click "↻ Regenerate" on a pending draft | Browser prompt appears: "What should be different? (optional)" | |
| 7.2 | Type "Too formal, make it more casual" → OK | Card disappears, toast "New draft generated" | |
| 7.3 | Check new draft in pending queue | New draft appears (different text from original) | |
| 7.4 | Click Regenerate → Cancel (press Escape or Cancel button) | Nothing happens, draft stays | |
| 7.5 | Click Regenerate → leave note empty → OK | Still regenerates (note is optional) | |

### 8. Momentum Events Feed (Home)

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 8.1 | Go to portal home | "Momentum" section visible between metrics and navigation tiles | |
| 8.2 | If ActivityEvents exist for this client | Feed shows events with icons, messages, timestamps, subreddit pills | |
| 8.3 | If no events | Empty state: "No activity yet..." message | |
| 8.4 | "View all →" link | Links to `/clients/{id}/activity` | |
| 8.5 | Approve a draft, then refresh home | New "draft_approved" event appears in momentum feed | |

### 9. PDF Report Download

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 9.1 | Go to Report page | "📄 Download Report" button visible in header | |
| 9.2 | Click Download Report | Browser downloads file: `RAMP_Report_{brand}_{days}d_{date}.html` | |
| 9.3 | Open downloaded file in browser | Clean white-background report with metrics, subreddit table, top comments | |
| 9.4 | Print the file (Cmd+P) → check Print Preview | Looks professional, no cut-off content, suitable for forwarding to CMO | |
| 9.5 | Change period to 60d → download again | File name and content reflect 60-day period | |

### 10. Trial Expiration

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 10.1 | Log in as trial user (< 14 days old) | Orange trial banner: "Free Trial — X days remaining — Upgrade →" | |
| 10.2 | Banner visible on ALL portal pages (home, review, avatars, etc.) | Consistent presence, not just home | |
| 10.3 | Manually set `client.created_at` to 15 days ago in DB | Next page load → "Your trial has ended" page, no portal access | |
| 10.4 | Trial expired page has "Upgrade to Start Posting" button | Button is mailto link | |
| 10.5 | Trial expired page has "Sign out" link | Works, redirects to login | |
| 10.6 | **Regression:** JJ (plan_type=`starter`) never sees trial banner | No trial banner, no expiration block | |

### 11. Budget Cap Warnings

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 11.1 | Client with < 80% usage | No budget banner visible | |
| 11.2 | Set `max_comments_per_month=10` in DB, generate 8+ drafts this month | Amber banner: "You have used X% of your monthly action allowance" | |
| 11.3 | Generate until 100%+ | Red banner: "Monthly limit reached" with Upgrade link | |
| 11.4 | **Regression:** Admin panel does not show budget banners | Admin pages unaffected | |

### 12. Upsell Touchpoints

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 12.1 | Client at subreddit limit → try to add subreddit in Settings | Message: "Subreddit limit reached. Add 5 more for $99/month" | |
| 12.2 | Avatars page when avatar_count >= max_avatars | Dashed "+" upsell card: "Your avatars are fully deployed — Add more →" | |
| 12.3 | Report page, client on Seed/Starter plan | Share of Voice section shows locked: "Available on Growth plan →" | |
| 12.4 | Report page, client on Growth plan | Share of Voice section shows bar chart (active) | |
| 12.5 | Only ONE upsell visible per screen (per Tzvi's brief rule) | Verify no screen shows 2+ upsell prompts simultaneously | |

### 13. Tone Calibration (Onboarding Step 4)

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 13.1 | Step 4: Click "Generate Sample Sentences" | 5 sentences appear with 1-5 radio buttons | |
| 13.2 | Click a rating number | Visual highlight on selected rating (orange background) | |
| 13.3 | Rate sentences and click Next | Sentences rated 4-5 saved as "Tone anchors" in brand_voice field | |
| 13.4 | Skip calibration entirely (don't click generate) → Next | Proceeds without tone anchors (non-blocking in MVP) | |
| 13.5 | Calibration button works multiple times (regenerate samples) | New 5 sentences each time | |

---

## PART 2: Regression Scenarios

### R1. Login/Auth Flow

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| R1.1 | Login as `jekorn12@gmail.com` (client_manager) | Lands on `/clients/{id}/home` (not onboarding, since already completed) | |
| R1.2 | Login as owner/partner | Lands on `/admin/` | |
| R1.3 | Login as `primocabron@gmail.com` (avatar_manager) | Lands on `/admin/avatars` | |
| R1.4 | Invalid credentials | Error message, stays on login page | |
| R1.5 | Deactivated user cannot login | Redirect to login | |

### R2. Portal Home (Existing Clients)

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| R2.1 | Home loads with correct metrics (comments, upvotes, subreddits) | Numbers match DB reality | |
| R2.2 | Pending CTA shows correct count | Matches actual pending drafts for this client | |
| R2.3 | Navigation tiles render correctly | All 6 tiles (Avatars, Schedule, Subreddits, Keywords, Strategy, Report) | |
| R2.4 | Quick Actions (Run Pipeline, Rebuild EPG) visible for client_manager | Buttons present, not for client_viewer | |
| R2.5 | Skeleton loading → real data | Metrics area loads via HTMX without errors | |

### R3. Review Queue (Existing Functionality)

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| R3.1 | Pending tab shows drafts with correct data | Avatar name, subreddit, thread title, comment text | |
| R3.2 | Approve a single draft | Card disappears, draft status → approved | |
| R3.3 | Edit text → Save & Approve | Edited text saved, status → approved, learning loop triggered | |
| R3.4 | Skip a draft | Card disappears, status → rejected | |
| R3.5 | Safety block on Phase 1 brand mention | Red banner, approve button blocked | |
| R3.6 | Approved tab → Mark as Posted | Draft moves to posted | |
| R3.7 | Posted tab shows last 30 days | "View on Reddit" links work | |
| R3.8 | Avatar filter works | Selecting an avatar filters drafts | |
| R3.9 | Tab switching (Pending/Approved/Posted) | Content reloads correctly per tab | |
| R3.10 | client_viewer role | Can see drafts but NO action buttons (approve/edit/skip) | |

### R4. Avatar Detail

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| R4.1 | Click avatar card → detail page loads | Voice profile, tone principles, subreddits, recent activity visible | |
| R4.2 | Recent activity shows correct statuses | Posted (green), Approved (blue), Pending (orange) | |
| R4.3 | Back link → returns to avatars list | No navigation break | |
| R4.4 | Phase badge correct | Matches avatar.warming_phase | |

### R5. Settings

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| R5.1 | Add keyword | Keyword appears in list, toast confirmation | |
| R5.2 | Remove keyword | Keyword disappears, toast confirmation | |
| R5.3 | Duplicate keyword | Error: "This keyword already exists" | |
| R5.4 | Request subreddit (below limit) | Success: "Request sent" toast | |
| R5.5 | Update guardrails | Toast: "Guardrails updated" | |
| R5.6 | Submit voice feedback | Toast: "Got it — we'll apply this" | |
| R5.7 | Voice feedback history shows last 5 | Correct order and content | |

### R6. Report & Insights

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| R6.1 | Report page loads with 30d default | All sections render without errors | |
| R6.2 | Switch to 60d → 90d | Data updates, period selector highlights correctly | |
| R6.3 | Engagement funnel numbers consistent | threads_scored >= threads_engage >= week_generated | |
| R6.4 | Subreddit performance table | Sorted by activity descending | |
| R6.5 | Top comments link to Reddit | External links open in new tab | |

### R7. EPG / Schedule

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| R7.1 | EPG page loads | Shows avatar daily programs with slot statuses | |
| R7.2 | History section (last 30 days) | Grouped by date, correct data | |
| R7.3 | Page works when 0 avatars | Empty state or "no slots" message | |

### R8. Strategy

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| R8.1 | Strategy page loads | Shows current strategy document per avatar | |
| R8.2 | Avatar filter works | Filters to selected avatar's strategy | |
| R8.3 | If no strategy exists | Empty state message | |

### R9. Admin Panel (Must Be Unaffected)

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| R9.1 | `/admin/` dashboard loads normally | All widgets, no errors | |
| R9.2 | `/admin/avatars` shows reddit_username | NOT display_name (admin sees real data) | |
| R9.3 | Admin review queue shows reddit_username | Admin review not affected by privacy layer | |
| R9.4 | Admin avatar detail shows raw karma | Full operational data visible | |
| R9.5 | Onboarding wizard (admin, 7-step) still works | `/admin/clients/{id}/wizard` unaffected | |
| R9.6 | Admin user CRUD works | Create/edit/deactivate users | |
| R9.7 | Admin client CRUD works | All client management operations | |
| R9.8 | Kill switches work | pipeline_enabled/generation_enabled toggles | |

### R10. RBAC Isolation

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| R10.1 | client_manager cannot access another client's portal | 403 or redirect | |
| R10.2 | client_viewer cannot approve/reject/edit drafts | Buttons not rendered, API returns 403 | |
| R10.3 | Trial user (client_admin) cannot access admin panel | 403 | |
| R10.4 | Trial user portal shows 0 avatars gracefully | Empty state card, no errors | |

### R11. Mobile Responsiveness

| # | Step | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| R11.1 | Portal home on mobile viewport (375px) | Readable, no horizontal scroll, tiles stack | |
| R11.2 | Review queue on mobile | Draft cards readable, buttons tappable (min-height 44px) | |
| R11.3 | Trial signup on mobile | Form usable, button full-width | |

---

## PART 3: Edge Cases & Error States

| # | Scenario | Expected Result | Pass/Fail |
|---|----------|-----------------|-----------|
| E1 | Scraper URL timeout (invalid domain in Step 1) | Error message: "Could not auto-detect. Fill manually." | |
| E2 | LLM API failure during keyword suggestions (Step 5) | Graceful fallback, not a 500 error page | |
| E3 | LLM API failure during tone calibration (Step 4) | Error message with Retry button | |
| E4 | Landscape report with 0 threads (freshly created trial, no scraping yet) | Page loads with 0 counts, no crashes | |
| E5 | Budget warning when max_comments_per_month is NULL | No banner (NULL = unlimited) | |
| E6 | Client with plan_type=NULL | Defaults to "starter" limits, no crashes | |
| E7 | Avatar with display_name=NULL | Falls back to reddit_username gracefully | |
| E8 | Batch approve when session expires mid-action | 303 redirect to login (not silent failure) | |
| E9 | Regenerate when Celery worker is down | Error toast, draft stays in pending | |
| E10 | Double-click Approve (race condition) | Second click is no-op (card already animating out) | |

---

## Deployment Checklist (Pre-QA)

- [ ] Run `alembic upgrade head` (adds display_name, persona_bio columns)
- [ ] Set `display_name` for existing avatars (or verify fallback to username works)
- [ ] Verify `onboarding.router` is included in `main.py` (already confirmed)
- [ ] Verify `/onboard/trial` accessible without auth (public route)
- [ ] Smoke test: `curl http://localhost:8000/onboard/trial` returns 200

---

## Sign-off

| Role | Name | Date | Status |
|------|------|------|--------|
| Dev | Max | June 16, 2026 | Ready for QA |
| QA | Jenny | | |
| Product | Tzvi | | |
