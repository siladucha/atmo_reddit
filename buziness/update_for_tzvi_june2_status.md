# RAMP — Project Status & Next 30 Days

**From:** Max  
**To:** Tzvi  
**Date:** June 2, 2026

---

## Summary

Automated posting is working — first verified post on Reddit (r/test, June 1). The system can now do the full loop: scrape → score → generate → review → post. No human needed at the posting stage.

This letter covers: what's done since our last talk, what's next, and what needs to happen for the first paying client within 30 days.

---

## What's Done Since May 28

### Automated Posting — Core ✅

| Component | Status |
|-----------|--------|
| PRAW posting via avatar credentials | ✅ Working |
| Safety gates (9 pre-posting checks) | ✅ Active |
| Timing engine (jitter, active hours, daily cap) | ✅ Live |
| Celery task every 5 min (execute_pending_posts) | ✅ Running |
| Auto-freeze on auth errors / consecutive failures | ✅ Working |
| PostingEvent audit trail (IP, duration, URL) | ✅ Logging |
| Field encryption (passwords, tokens, proxy URLs) | ✅ AES-128 |
| First real post: r/test via u/Hot-Thought2408 | ✅ Verified |

**Auth mode:** Password auth via existing script app (works without Reddit approval).  
**OAuth:** Ticket submitted to Reddit. Waiting. Not blocking us.

### Versioning & Kill Switches ✅

- `VERSION 0.2.0` — shown in UI footer and `/health` endpoint
- `POSTING_DISABLED=true` on production (no posts until we decide together)
- Local environment: posting enabled for avatar testing

### Production Server

- Live at `161.35.27.165` (gorampit.com with SSL)
- Docker Compose: app + PostgreSQL + Redis + Celery worker + Beat scheduler
- All pipelines running on schedule (scraping, scoring, generation, health checks)

---

## What's NOT Done Yet

| Item | Why it matters | Effort |
|------|---------------|--------|
| Posting Admin UI | You can't see posting logs or configure proxies from the panel | 3-4 days |
| Proxy integration | Each avatar needs its own IP to avoid Reddit linking accounts | Purchase needed ($12.50/mo for 5 avatars) |
| Comment performance tracking | Can't prove ROI to clients without karma/outcome data | 1 week |
| Avatar daily timeline (EPG view) | Manager can't see what happened today per avatar | 3-4 days |

---

## The 30-Day Question

> What must happen for one client to pay and get measurable value?

Here's my honest assessment:

### Must Have (Week 1-2)

| # | Item | What it does | Days |
|---|------|--------------|------|
| 1 | Proxy purchase + integration | Avatars post from unique IPs | 2 |
| 2 | Enable posting for 2-3 avatars | Real comments on real subreddits | 1 |
| 3 | Comment performance tracking | Karma snapshots at 4h/24h/48h + removal detection | 5 |
| 4 | Avatar daily timeline | "What happened today" view per avatar | 3 |

After these 2 weeks: the system posts automatically AND we can show the client metrics.

### Should Have (Week 3-4)

| # | Item | What it does | Days |
|---|------|--------------|------|
| 5 | Quality sentinel | Auto-flag low-performing comments, alert on removals | 4 |
| 6 | Client-facing report page | Weekly summary: posts, karma earned, top comments, growth | 3 |
| 7 | Posting admin UI | Logs, proxy config, posting dashboard | 3 |

After 4 weeks: client can see a report proving the system works.

---

## What I Need From You

| # | Item | Why | Urgency |
|---|------|-----|---------|
| 1 | Proxy budget approval ($12.50/mo) | Can't post from unique IPs without this | This week |
| 2 | Which avatars to activate first? | I'll configure them for automated posting | This week |
| 3 | XM Cyber go/no-go | Are we running the pilot with them or a different client first? | This week |
| 4 | Domain situation | gorampit.com is live but is that the final domain for client demos? | Not urgent |
| 5 | Fredo status | Is he still posting manually? Should I onboard him to the new flow? | Next week |

---

## Strategic Priorities (Beyond Week 4)

These are the things I'm designing now but not building yet:

| Initiative | Why | Status |
|-----------|-----|--------|
| AI-Native Expert Warming | The moat — avatars become sources AI chatbots cite | Spec exists, design pending |
| Client Manager Workflow UX | When we have multiple managers reviewing drafts | Spec exists |
| Pipeline Resilience | Handling Reddit API changes, rate limit escalation | Spec exists |

Everything else (mobile app, white-label, Telegram bot, SQS migration, self-serve portal) is parked until we have 5+ paying clients.

---

## Honest Status Assessment

| Area | Grade | Notes |
|------|-------|-------|
| AI pipeline (scrape → score → generate) | A | Working daily, self-learning from edits |
| Posting infrastructure | B+ | Core works, needs proxies + admin UI |
| Client-facing value proof | C | No outcome tracking yet — can't show ROI in numbers |
| Ops efficiency | B | EPG works, daily timeline view needed |
| Revenue readiness | C+ | System works end-to-end, but client can't see results quantified |

**The gap:** The system does the work. But the client can't see the results in a report. Comment performance tracking is the #1 thing that turns "trust us" into "here are your numbers."

---

## Timeline to First Invoice

| Week | Milestone |
|------|-----------|
| Week 1 (Jun 2-8) | Proxies purchased, 2-3 avatars posting automatically |
| Week 2 (Jun 9-15) | Comment tracking live, daily timeline operational |
| Week 3 (Jun 16-22) | 2 weeks of performance data collected, client report ready |
| Week 4 (Jun 23-30) | Present results to client: "here's what your avatars achieved" |

**First invoice target:** July 1, 2026 — backed by 3-4 weeks of measurable activity data.

---

## Budget Status

| Item | Monthly |
|------|---------|
| DigitalOcean droplet | $23 |
| AI APIs (LLM — 3 active clients) | ~$105 |
| Residential proxies (5 avatars) | $12.50 |
| Dev tools (Cursor, testing) | ~$50 |
| **Total** | **~$190/mo** |

Break-even: 1 client on Starter plan ($399/mo) covers everything with margin.

---

Let me know on the proxy budget and avatar selection — I can have them posting this week.

Max
