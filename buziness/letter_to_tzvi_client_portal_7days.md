# RAMP Client Portal — 1 Week Delivery Plan

**To:** Tzvi  
**From:** Max  
**Subject:** What you can show a client in 7 days

---

## The Reality

You need something to show a client in 7 days. I can deliver that.

But I cannot deliver the full UX spec. Nobody can.

---

## What You Get in 7 Days

| Component | What client sees |
|-----------|-----------------|
| Dark theme (#0F0F1A + Signal blue) | Premium look |
| Sidebar navigation | Home, Review Queue, Avatars, Settings |
| Review Queue | Draft cards + Approve/Skip (optimistic) |
| Home screen | 3 metrics (comments, upvotes, subreddits) |
| Avatars list | Names + phases + shadowban badges |
| Brand mention safety block | Red banner, blocks approve |
| Empty states | Clean copy, no "no data" |

**Client can log in, see drafts, approve them, watch them disappear. That's the value.**

---

## What You DO NOT Get in 7 Days

| Feature | Why not |
|---------|---------|
| Inline editing | Complex, needs backend diff storage |
| Regenerate with feedback | Needs LLM + feedback loop |
| Filter bar | URL params + state management |
| Time-frame selector | localStorage + data refetch |
| PDF reports | Async job + email fallback |
| Onboarding wizard | Full-screen takeover + multi-step state |
| Settings (keywords/guardrails) | CRUD + API endpoints |
| Insights / Share of Voice | Needs data aggregation |
| Mobile bottom bar | Responsive only, not optimized |

**These come in weeks 2-4.**


---

## What You Tell the Client

> "This is the core product. You approve comments, we post them. Dark theme, fast, safe — brand mentions blocked until Phase 3. What you see here works today. The roadmap: inline editing next week, insights in 30 days, full self-serve onboarding in 60 days."

---

## My Commitment

| Day | Deliverable |
|-----|-------------|
| Day 3 | Dark theme + sidebar + avatars list |
| Day 5 | Review Queue (cards + approve/skip) |
| Day 7 | Home metrics + safety block + polished demo |

**Day 7 — you log in with a client and show them a working product.**

---

## Pricing & Plans — Ready to Implement

I have the pricing spec ready. Once you confirm, I wire it into the portal (plan badges, action limits, upsell triggers):

| Plan | Price | Own Avatars | Rentals | Comments/mo | Subreddits |
|------|-------|-------------|---------|-------------|------------|
| Seed | $149 | 1 | +1 | 30 | 5 |
| Starter | $399 | 3 | +2 | 60 | 10 |
| Growth | $799 | 7 | +3 | 150 | unlimited |
| Scale | $1,499 | 15 | +5 | 400 | unlimited |

**Avatar Rentals (ours, ban replacement included):**

| Tier | Karma | Price/mo | Replacement |
|------|-------|----------|-------------|
| Bronze | 50–500 | $49 | 3 days |
| Silver | 500–2,000 | $149 | 5 days |
| Gold | 2,000–10,000 | $299 | 14 days |
| Platinum | 10,000+ | $499 | 30–45 days |

**B2C:** $49/mo — 1 own avatar, 30 comments, 3 subreddits.

**What I need from you:**
1. Seed price: $149 or $399? (your docs say different things)
2. B2C: $49 or $79?
3. Posts only on Growth+ ($799) — confirmed?
4. Billing: manual invoicing for pilot, or Stripe from day 1?

**Implementation:** Plan tier badge in sidebar footer, action counter on home screen, soft warning at 80% usage. No hard billing integration needed for pilot — just display limits and track usage. Stripe comes after 5 paying clients.

---

## Partnership Leads

You mentioned 2 leads from Ori's time. Worth discussing — if we're pitching agencies, the portal demo becomes even more important. Let's talk timing.

---

## Two Questions

1. **Color:** Signal blue (#2563C4) from brand guidelines, or orange (#FF6B35) from UX spec?
2. **Pricing confirmation:** Answer the 4 questions above so I can wire limits into the UI.

---

## Bottom Line

> **7 days = working demo with core value (approve drafts) + plan tier display.**  
> **Not 7 days = full UX spec.**

Say yes, I start now.
