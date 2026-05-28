# Partner Onboarding Checklist — 5-Day Timeline

## Contract signing to first client live in 5 business days.

---

## Pre-Onboarding (Partner Prepares Before Day 1)

Before signing, the partner should have these items ready to avoid delays:

### Branding Assets

- [ ] Logo in SVG format (vector, for web rendering)
- [ ] Logo in PNG format (minimum 512×512px, transparent background)
- [ ] Favicon (32×32px PNG or ICO)
- [ ] Primary brand color (hex code, e.g., `#2563EB`)
- [ ] Accent brand color (hex code, e.g., `#F59E0B`)
- [ ] Company name (as it should appear in the portal UI and emails)

### Domain

- [ ] Custom domain chosen (e.g., `reddit.theiragency.com` or `platform.agencyname.com`)
- [ ] Access to DNS management for that domain (ability to add CNAME record)

### Email

- [ ] Sender name decided (e.g., "AgencyName Platform")
- [ ] Sender email address decided (e.g., `notifications@agencyname.com`)
- [ ] SPF/DKIM records accessible (for email deliverability — RAMP provides the values to add)

### Mobile App (if requesting branded app)

- [ ] App name decided (e.g., "AgencyName Poster")
- [ ] App icon designed (1024×1024px PNG, no transparency, follows App Store/Play Store guidelines)
- [ ] Splash screen design (optional — RAMP can generate from logo + colors)
- [ ] Apple Developer Account ($99/year) — if publishing to iOS
- [ ] Google Play Developer Account ($25 one-time) — if publishing to Android

### First Client

- [ ] First End-Client identified (brand name, industry, target subreddits)
- [ ] Client keywords prepared (high/medium/low priority tiers)
- [ ] Avatar requirements estimated (how many, which tier: Silver or Gold)

---

## Day 1: Contract + Assets

**Goal:** Agreement signed, all assets received, partner record created in system.

- [ ] Partner signs white-label agreement (annual contract)
- [ ] Partner provides branding assets (logo SVG/PNG, favicon, primary color hex, accent color hex)
- [ ] Partner provides domain choice (e.g., `reddit.theiragency.com`)
- [ ] Partner provides email sender details (from_name, from_address)
- [ ] Partner provides mobile app details (app_name, icon — if requesting branded app)
- [ ] RAMP creates partner record in system (name, tier, pricing model, max_client_slots, contract dates)
- [ ] RAMP sends welcome email with onboarding guide (DNS instructions, timeline, what to expect)

### RAMP Internal Actions (Day 1)

- [ ] Partner record created in `partners` table
- [ ] Branding config created in `branding_configs` table (logo_url, colors, company_name, domain)
- [ ] Partner tier confirmed and billing initiated
- [ ] Onboarding ticket created in internal tracker
- [ ] Assign onboarding owner (ops team for Starter/Growth, AM for Scale/Enterprise)

---

## Day 2: Configuration

**Goal:** Domain live, SSL active, portal branded and accessible, partner can log in.

- [ ] Partner configures DNS (CNAME record: `reddit.theiragency.com` → `partners.ramp-platform.com`)
- [ ] RAMP verifies DNS propagation (allow up to 24h, typically <1h)
- [ ] RAMP provisions SSL certificate (automated via certbot / Let's Encrypt)
- [ ] RAMP applies branding to partner portal (logo, colors, company name, favicon)
- [ ] RAMP configures email sender (from_name, from_address, SPF/DKIM guidance sent to partner)
- [ ] RAMP verifies portal renders correctly at partner's custom domain
- [ ] RAMP creates partner admin user account (email + temporary password)
- [ ] Partner logs in and verifies branding (logo placement, color scheme, domain, page titles)
- [ ] Partner confirms email notifications arrive with correct sender identity

### Verification Checklist (Day 2)

- [ ] `https://reddit.theiragency.com` loads with valid SSL (green lock)
- [ ] Logo appears in header, login page, and email templates
- [ ] Primary color applied to buttons, links, active states
- [ ] Accent color applied to highlights, badges, secondary actions
- [ ] Company name appears in page titles, footer, and email subject lines
- [ ] Favicon displays in browser tab
- [ ] No RAMP branding visible anywhere in the partner portal
- [ ] Login flow works (email + password → dashboard)

---

## Day 3: First Client

**Goal:** First End-Client workspace provisioned, pipeline tested, first content generated.

- [ ] Partner creates first End-Client workspace (via partner dashboard or RAMP assists)
- [ ] Partner configures client: brand name, industry, target keywords (high/medium/low)
- [ ] Partner configures client: target subreddits (professional + hobby mix)
- [ ] RAMP assigns pre-warmed avatars to client workspace (Silver or Gold tier, per order)
- [ ] Avatar voice profiles configured (persona, tone, expertise areas)
- [ ] Pipeline test run: scrape target subreddits → score threads → generate first drafts
- [ ] Partner reviews first generated content (quality check — tone, relevance, brand alignment)
- [ ] Partner provides feedback on content quality (if adjustments needed, iterate same day)

### Quality Gate (Day 3)

Before proceeding, partner should confirm:

- [ ] Generated comments match expected tone and expertise level
- [ ] No brand mentions appear in Phase 1/2 content (safety guardrails working)
- [ ] Subreddit targeting is accurate (relevant threads being scored)
- [ ] Avatar voice feels authentic (not generic, not robotic)

---

## Day 4: Mobile App (if requested)

**Goal:** Branded app build produced, tested on both platforms, partner reviews.

- [ ] RAMP initiates Flutter build with partner's flavor config (app_name, icon, colors, splash, API endpoint, bundle_id)
- [ ] iOS build compiled and signed (TestFlight-ready)
- [ ] Android build compiled (APK/AAB for internal testing)
- [ ] Test build verified on both iOS and Android (login, queue view, draft detail, notifications)
- [ ] Partner receives test build for internal review (TestFlight invite + APK link)
- [ ] Partner confirms app branding (icon, splash screen, in-app colors, app name)
- [ ] App Store / Play Store submission guidance provided (screenshots, description template, category recommendation)
- [ ] Partner initiates store submission (under their own developer account)

### If No Mobile App Requested

- [ ] PWA (Progressive Web App) configured with partner branding
- [ ] PWA tested on mobile browsers (iOS Safari, Android Chrome)
- [ ] Partner confirms PWA works for their avatar owners' workflow

---

## Day 5: Go Live

**Goal:** Everything confirmed working, first client invited, support channel active, partner operational.

- [ ] Partner portal confirmed live and accessible (final check — SSL, branding, performance)
- [ ] All pipeline components verified operational (scraping, scoring, generation, review queue)
- [ ] First End-Client invited (if partner ready — partner sends invite from their portal)
- [ ] End-Client access level configured (full / read-only / none — per partner's operating model)
- [ ] Support channel established (email for Starter, Slack for Growth+, dedicated AM for Scale+)
- [ ] Onboarding call completed (Growth+ tiers — 30-60 min walkthrough, Q&A, best practices)
- [ ] Partner confirms "ready to operate" (verbal or written sign-off)
- [ ] RAMP marks partner as "active" in system (`is_active = true`, contract start date recorded)
- [ ] Onboarding ticket closed in internal tracker

### Go-Live Verification

- [ ] Partner can create new End-Client workspaces independently
- [ ] Partner can assign avatars to clients
- [ ] Partner can review and approve/reject/edit generated content
- [ ] Partner can access analytics and reporting
- [ ] Partner knows how to reach support (correct channel for their tier)
- [ ] Partner has documentation access (knowledge base, partner portal docs)

---

## Post-Onboarding: First 30 Days Success Milestones

### Week 1 (Days 6–10)

| Milestone | Target | Owner |
|-----------|--------|-------|
| First End-Client workspace fully configured | 1 client live | Partner |
| First batch of approved comments posted | 10+ comments | Partner + RAMP pipeline |
| Partner comfortable with review workflow | Self-sufficient | Partner |
| Any branding/config issues resolved | Zero open tickets | RAMP |

### Week 2 (Days 11–17)

| Milestone | Target | Owner |
|-----------|--------|-------|
| Second End-Client onboarded (if applicable) | 2 clients live | Partner |
| Content quality feedback loop established | Partner editing drafts, learning loop active | Partner |
| Avatar karma growth visible | Positive trend in dashboard | RAMP pipeline |
| Partner using analytics dashboard regularly | Daily or every-other-day login | Partner |

### Week 3 (Days 18–24)

| Milestone | Target | Owner |
|-----------|--------|-------|
| 3+ End-Clients active (Growth+ tiers) | Per tier minimum | Partner |
| Pipeline running autonomously (no RAMP intervention needed) | Zero manual triggers | RAMP |
| Partner has established review cadence | Consistent daily/weekly review schedule | Partner |
| First monthly check-in call scheduled (Growth+) | Calendar invite sent | RAMP AM |

### Week 4 (Days 25–30)

| Milestone | Target | Owner |
|-----------|--------|-------|
| Partner at or above minimum client slot commitment | 3+ slots active (per contract) | Partner |
| Mobile app published to stores (if requested) | Live in App Store / Play Store | Partner |
| First performance report generated | Branded PDF or dashboard snapshot | RAMP |
| Partner NPS collected (informal — "How's it going?") | Score > 40 target | RAMP |
| Upgrade conversation (if partner hitting slot limits) | Proactive outreach | RAMP AM |

---

## Success Criteria — Onboarding Complete

The onboarding is considered **successfully complete** when:

1. ✅ Partner portal live at custom domain with correct branding
2. ✅ At least 1 End-Client workspace active with avatars assigned
3. ✅ Pipeline has generated and partner has reviewed at least one batch of content
4. ✅ Support channel confirmed working (partner can reach RAMP)
5. ✅ Partner confirms "ready to operate" (self-sufficient for daily operations)

---

## Escalation — If Onboarding Stalls

| Blocker | Resolution | Owner |
|---------|-----------|-------|
| DNS not propagated after 24h | Verify CNAME record, check for conflicting A records, try alternate subdomain | RAMP + Partner |
| Partner unresponsive (no assets provided) | Day 3 reminder email, Day 5 phone call, Day 10 contract pause discussion | RAMP AM |
| Content quality rejected by partner | Schedule call to align on voice/tone, adjust persona config, re-run pipeline | RAMP ops |
| Mobile app store rejection | Review rejection reason, fix metadata/screenshots, resubmit (add 3-5 days) | RAMP + Partner |
| SSL certificate failure | Check domain ownership, verify CNAME, manual cert provision if needed | RAMP ops |

---

## Internal RAMP Checklist (Ops Team Reference)

### Before Day 1

- [ ] Confirm partner tier and pricing in CRM
- [ ] Prepare partner record template (pre-fill what's known from sales process)
- [ ] Verify avatar inventory availability (enough Silver/Gold for partner's first clients)
- [ ] Assign onboarding owner internally

### After Day 5

- [ ] Send "Onboarding Complete" confirmation email to partner
- [ ] Schedule first monthly check-in (Growth+) or QBR (Scale+)
- [ ] Add partner to platform updates newsletter
- [ ] Update internal dashboard (partner count, active slots, revenue)
- [ ] Document any custom configurations or special arrangements
- [ ] Retrospective: what went well, what to improve for next onboarding
