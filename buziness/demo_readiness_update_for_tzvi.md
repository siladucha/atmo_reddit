# RAMP — Demo Readiness Update

**From:** Max (Tech)
**To:** Tzvi
**Date:** May 24, 2026

---

## Status: Ready for Client Demo

The platform is ready to demonstrate to prospects. Both the admin panel (our ops view) and the client portal (what the client sees) are fully functional with live data.

---

## What We Can Show

### Client Portal (what the client sees)
- **Home Dashboard** — live metrics: comments posted, upvotes earned, active subreddits
- **Review Queue** — approve / edit / skip AI-generated drafts before posting
- **Insights & Report** — engagement funnel, subreddit performance, top comments (with 30/60/90 day selector)
- **Avatars** — avatar list with phase, karma tier, health status, voice profile
- **Strategy** — AI-generated 30-day strategy per avatar (goals, tone, subreddit priorities)
- **Schedule (EPG)** — daily publishing program: what gets posted, where, when
- **Subreddits** — active subreddits with type and status
- **Keywords** — keyword performance analytics

### Admin Panel (our ops view)
- Full pipeline control: scraping → scoring → generation → review
- Client onboarding wizard (7 steps)
- Avatar management: freeze/unfreeze, phase override, health monitoring
- System topology: real-time pipeline health, kill switches
- AI cost tracking per client, per avatar
- Self-learning loop: edit patterns, correction rules, few-shot injection

---

## Demo Data

XM Cyber client is populated with:
- active avatars (ThorneMarcus92, Middle-Mode3001, d-wreck-w12, leon_grant10, lucas_parker2)
- posted comments with real karma scores (19–71 upvotes each, 590 total)
- pending drafts in review queue (ready to demonstrate approve/edit/skip flow)
- active subreddits (cybersecurity, netsec, sysadmin, blueteam, CloudSecurity, etc.)
- Strategy documents generated
- EPG schedule populated

---

## What's NOT in the Demo (and what to say)

| Topic | What to say |
|-------|-------------|
| Domain/SSL | "We're setting up the custom domain this week — currently on staging server" |
| Nested comment replies | "Phase 2 feature — currently we reply to posts, comment threading coming next month" |
| Billing/payments | "Handled separately during onboarding, not in the platform UI yet" |
| Mobile posting app | "Telegram-based posting workflow launching next week" |
| Outcome tracking (karma over time) | "Coming in June — will show karma growth curves per avatar" |

---

## How to Access

**Production server:** `http://161.35.27.165` (no domain yet)

Login credentials — try to use your own access to create/check.

Client portal URL: `/clients/{client_id}/home`
Admin panel: `/admin/`

---

## Recommended Demo Flow (10 min)

1. **Start with admin** — show the dashboard, pipeline topology, explain the system
2. **Show client onboarding** — walk through the 7-step wizard
3. **Switch to client portal** — "this is what your team sees"
4. **Home** — metrics at a glance
5. **Review Queue** — demonstrate approve/edit/skip on a pending draft
6. **Report** — show the engagement funnel, switch between 30/60/90 days
7. **Strategy** — show the AI-generated strategy document
8. **Schedule (EPG)** — "this is today's publishing program for your avatars"
9. **Close** — "everything is managed by us, you just review and approve"

---

## Next Steps After Demo

- [ ] Domain + SSL (waiting on your DNS decision)

---

Let me know when you want to schedule the demo. I can be available to support live or you can run it solo with the flow above.
