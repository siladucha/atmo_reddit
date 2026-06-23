# Dashboard Redesign — Deployed June 23, 2026

**For:** Tzvi
**From:** Max
**Status:** Code ready. Deploy requires: rsync + docker compose build + up -d (image rebuild needed)

---

## What Changed

Your dashboard at `/admin/` has been completely redesigned. Instead of showing pipeline operations (Scraped/Scored/Generated) that don't help you make business decisions, you now see a **Business Cockpit**.

### What You See Now

**Top Row — Business KPIs:**
- **MRR** — Monthly Recurring Revenue (clients × plan price)
- **Paying** — Active paying clients count
- **Trials** — Active trial clients
- **AI Spend** — This month's AI API costs
- **Margin** — Revenue minus AI costs as percentage

**Attention Bar** — Red/amber banner when something needs your action:
- Trial clients about to expire (< 3 days left)
- Paying clients with 0 posts this week (value not delivered)
- Drafts pending review
- Frozen avatars

**Client Health Table:**
| What You See | What It Means |
|---|---|
| 🟢 Green dot | Everything working — posts flowing |
| 🟡 Yellow dot | Warning — low activity or some frozen avatars |
| 🔴 Red dot (pulsing) | Critical — no posts, all frozen, or expired trial |
| "no posts" note | This client pays but got nothing this week — call them |
| "3d left" | Trial expires in 3 days — conversion opportunity |

**Trial Funnel** — How trials progress through your onboarding pipeline.

**Cost & Revenue** — MRR vs AI spend with per-client breakdown.

### What Was Removed From Your View

- Pipeline trigger buttons (Scrape/Score/Generate) — you don't need these
- System topology visualization — ops concern
- Worker status / heartbeat — ops concern
- Scrape freshness / backup status — ops concern
- Per-client pipeline trigger buttons — ops concern

These are still visible on Max's (owner) dashboard.

---

## For Trial Clients

Trial clients now see a **guided onboarding experience** instead of an empty portal:
- Progress bar (Step X of 6)
- "What's happening now" — contextual messages about their campaign state
- Countdown timer ("12 days left")
- Celebration moment when first AI draft is ready
- Simplified navigation (no empty Strategy/Report/EPG pages)

---

## Client Manager Role Change

Client managers no longer see a separate admin-themed dashboard. They're redirected straight to the Client Portal with elevated action buttons. One interface instead of two.

---

## How MRR Is Calculated

Currently: `active clients × plan list price`

| Plan | Price |
|------|-------|
| Trial | $0 |
| Seed | $149 |
| Starter | $399 |
| Growth | $799 |
| Scale | $1,499 |

When Stripe is connected, this will switch to actual billed amounts.

---

## What You Can Do With This

1. **Daily check (30 seconds):** Open dashboard → see if attention bar has items → act on them
2. **Weekly review:** Check client health table → any 🔴? Call them. Any trial expiring? Push conversion.
3. **Monthly P&L:** MRR vs AI Spend = your margin. No spreadsheet needed.

---

## Questions For You

1. Do you want to see "pending reviews" as a CTA? (Do you review drafts yourself?)
2. Any other metric you check regularly that should be on this page?
3. Is the client health definition correct? (Red = 0 posts/week OR all avatars frozen OR trial expired)
