# RAMP v0.3.0 — Client Portal UX Overhaul

**Release Date:** June 17, 2026
**Previous Version:** 0.2.0
**Deploy Target:** 161.35.27.165 (production)

---

## Summary

Major client-facing UX update implementing Tzvi's UX/UI Brief v2 and Business Brief requirements. Adds self-serve trial signup, privacy layer, onboarding wizard improvements, and 16 new portal features.

---

## New Features

### Self-Serve Trial (P0 — Tzvi's letter June 7)
- **Trial signup page** (`/onboard/trial`) — public, no auth required
- Work email validation (23 blocked personal domains)
- Creates trial Client (plan_type=trial, 0 avatars) + User (client_admin)
- Auto-login → redirect to 6-step onboarding wizard
- 14-day trial with automatic expiration enforcement
- Trial banner on all portal pages with days remaining + Upgrade CTA
- Trial expired page blocks access after 14 days

### Privacy Layer (UX Brief v2 §04)
- `display_name` + `persona_bio` fields on Avatar model (new DB columns)
- Client portal shows persona names instead of Reddit usernames
- Karma tier names (Newcomer/Building/Established/Authority) instead of raw numbers
- Fallback indicator: orange color + ⚙ icon + tooltip when display_name not set
- Admin panel unaffected (still shows real usernames)

### Avatars Screen Redesign (UX Brief v2 §04)
- **Table → Card layout** with persona circle, display name, bio
- Phase badge, karma tier, health status per card
- Shadowban alert inline (red box with explanation)
- Avatar expansion upsell card when at plan limit

### Day 1 Landscape Report (Business Brief §02 "aha moment")
- `GET /clients/{id}/landscape` — competitive presence analysis
- Competitor mentions in monitored subreddits
- High-intent opportunities (relevant threads where brand is absent)
- Share of voice bar chart (brand vs competitors)
- Auto-refresh (HTMX every 30s) while scanning in progress
- Upgrade CTA at bottom

### Review Queue Enhancements (UX Brief v2 §04)
- **Batch approve** — checkboxes + sticky "Approve Selected" bar (2+ items)
- **Regenerate with note** — prompt asks "What should be different?" → note passed to LLM
- Safety blocks remain enforced (no checkbox on blocked drafts)

### Momentum Events Feed (UX Brief v2 §04 / Business Brief §04)
- HTMX-loaded feed on home page (between metrics and tiles)
- Shows last 7 days: breakout comments, pipeline activity, phase changes, alerts
- Event icons by type, subreddit pills, karma scores
- "View all →" link to full activity log

### PDF Report Download (UX Brief v2 §04)
- `GET /clients/{id}/report/download?days=30|60|90`
- Standalone HTML file (white background, professional layout, print-ready)
- Executive summary + subreddit table + top comments
- "📄 Download Report" button in report page header

### Tone Calibration Loop (UX Brief v2 §03 Step 4)
- "Generate Sample Sentences" button in onboarding Step 4
- AI generates 5 Reddit-style sentences in brand voice (Gemini Flash)
- Client rates each 1-5 with radio buttons
- Sentences rated 4-5 stored as tone anchors (few-shot examples for future generation)

### Budget Cap System (UX Brief v2 §05)
- Monthly usage tracking (comments generated vs plan limit)
- Amber warning banner at 80% usage
- Red enforcement banner at 100% (non-critical actions paused)
- Upgrade CTA on both banners
- `_get_usage_context()` injected into all portal renders

### Upsell Framework (UX Brief v2 §06)
- Subreddit limit: "Add 5 more for $99/month" (instead of generic error)
- Avatar expansion card (dashed border, CTA) on avatars page
- Share of Voice: locked state for Seed/Starter ("Available on Growth plan →")
- Non-blocking, contextual, dismissable

### Share of Voice (UX Brief v2 §04 Insights)
- Bar visualization on report page for Growth/Scale plans
- Locked state with upsell for Seed/Starter/Trial plans
- Links to full Landscape Report for detailed breakdown

---

## UX Polish

- Trial home page: "Your intelligence trial is active" guidance block with CTAs
- Landscape Report loading state: animated scanning indicator + auto-refresh
- Display name fallback: orange text + ⚙ icon + tooltip for unconfigured avatars
- Login page: "Start your free trial" link added
- Onboarding complete page: "View Landscape Report" button added
- Sidebar: "Landscape" nav item added

---

## Infrastructure Changes

### Database Migration (`b1c2d3e4f5g6`)
```sql
ALTER TABLE avatars ADD COLUMN display_name VARCHAR(100);
ALTER TABLE avatars ADD COLUMN persona_bio VARCHAR(255);
```
- Nullable fields, no data loss
- Fallback logic: display_name → reddit_username if NULL

### Auth Middleware
- `/onboard/trial` and `/onboard/trial/signup` added to PUBLIC_ROUTES

### New Files
| File | Purpose |
|------|---------|
| `app/routes/onboarding.py` (extended) | Trial signup + tone calibration routes |
| `app/services/onboarding/landscape_report.py` | Day 1 report generation service |
| `app/templates/onboarding/trial_signup.html` | Trial signup page |
| `app/templates/client/landscape.html` | Landscape report page |
| `app/templates/client/trial_expired.html` | Trial expired block page |
| `app/templates/client/report_pdf.html` | Downloadable report template |
| `app/templates/partials/client/momentum_feed.html` | Momentum events partial |
| `alembic/versions/b1c2d3e4f5g6_...py` | Display name migration |

### Modified Files (key changes)
| File | Changes |
|------|---------|
| `app/models/avatar.py` | +display_name, +persona_bio |
| `app/routes/portal.py` | +_karma_tier, +_avatar_display_name, +_get_usage_context, +landscape route, +momentum partial, +PDF download, privacy layer on all avatar references |
| `app/routes/portal_actions.py` | +Form import, regenerate note parameter |
| `app/routes/pages.py` | Onboarding redirect for incomplete clients |
| `app/middleware/auth.py` | Trial routes in PUBLIC_ROUTES |
| `app/templates/client/avatars.html` | Full rewrite: table → cards |
| `app/templates/client/avatar_detail.html` | display_name + karma_tier |
| `app/templates/client/home.html` | +momentum feed, +trial guidance block |
| `app/templates/client/report.html` | +download button, +share of voice section |
| `app/templates/client_base.html` | +trial banner, +budget warning banners |
| `app/templates/partials/client/drafts_list.html` | +batch checkboxes, +regenerate note prompt |
| `app/templates/partials/client/sidebar.html` | +Landscape nav item |
| `app/templates/login.html` | +trial link |
| `app/templates/onboarding/complete.html` | +Landscape Report button |
| `app/templates/onboarding/step4.html` | +tone calibration UI |
| `VERSION` | 0.2.0 → 0.3.0 |

---

## Rollback Plan

If issues found post-deploy:
```bash
# 1. Restore database from backup
ssh root@161.35.27.165 "docker compose exec -T db pg_restore -U reddit_saas_user -d reddit_saas --clean --if-exists --no-owner --single-transaction /tmp/backup_pre_deploy_june17.custom"

# 2. Revert code (git)
cd reddit_saas && git checkout HEAD~1
# Re-rsync + rebuild
```

---

## Post-Deploy Checklist

- [ ] Verify health: `curl http://161.35.27.165/health`
- [ ] Verify trial page: `curl -s http://161.35.27.165/onboard/trial` (should return 200)
- [ ] Login as JJ → portal loads (regression)
- [ ] Set `display_name` for existing avatars via admin panel or DB
- [ ] Trigger pipeline for NeuroYoga (so landscape report has data)
- [ ] Send Tzvi the trial URL: `http://161.35.27.165/onboard/trial`

---

## Known Limitations (v0.3.0)

1. **PDF is HTML file** — client saves as PDF via browser Print. True PDF generation (weasyprint) deferred.
2. **Tone calibration not blocking** — client can skip without rating 3+ sentences at 4+. Quality gate is advisory only.
3. **Landscape report depends on scraped data** — first 5-10 min after onboarding shows "scanning" state.
4. **Display names need manual setup** — admin must set persona names for existing avatars.
5. **Share of Voice is comment count, not %** — true SOV requires competitor thread monitoring (GEO module).
