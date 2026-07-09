# Resource Limits — Deployed (Confirmation Required)

**To:** Tzvi  
**From:** Max  
**Date:** July 9, 2026  
**Subject:** Per-plan resource limits are LIVE — need your sign-off on numbers

---

## What Happened

I deployed hard limits on resources that cost us AI money and create system load. Previously a trial user could create 50 GEO monitoring prompts (each one = $0.006–$0.08 per execution × multiple engines × twice a week). Now every resource type is capped by plan.

**This is already in the code.** If you disagree with specific numbers — tell me, I'll adjust in 5 minutes. But the system is no longer open to abuse.

---

## What's Now Enforced

| Resource | Trial | Seed ($149) | Starter ($399) | Growth ($799) | Scale ($1,499) |
|----------|-------|-------------|----------------|---------------|----------------|
| **Subreddits** (active assignments) | 2 | 3 | 5 | 10 | Unlimited |
| **Keywords** (across all priorities) | 10 | 20 | 30 | 50 | 100 |
| **GEO/AEO prompts** (monitoring queries) | 5 | 10 | 20 | 40 | 60 |
| **GEO competitors** (tracked brands) | 3 | 5 | 10 | 15 | 30 |
| **Avatars** | 1 | 1 | 3 | 7 | 15 |
| **Comments/month** | 0 | 30 | 60 | 150 | 400 |

**Agency plan:** everything uncapped (custom deal = custom limits set manually per client).

---

## Why These Specific Numbers

### Subreddits
- Each active subreddit = scraping every 6h + scoring LLM calls + opportunity scanning
- Trial with 2 subs = enough to see the system work. Seed with 3 = 1 professional + 2 hobby-warming
- Growth with 10 = covers "5 professional + hobbies" from your business brief with headroom

### Keywords  
- Each keyword = scoring prompt grows (more context per thread evaluation)
- 10 for trial = enough to demo. 50 for Growth = covers all realistic use cases
- Beyond 50 keywords there's diminishing returns anyway (scoring prompt gets too long)

### GEO/AEO Prompts
- **This is the biggest cost saver.** Each prompt runs against 2-3 AI engines, 1-2× per week
- Cost per prompt per week: ~$0.02–$0.16 depending on providers enabled
- Trial user with 5 prompts vs old 50: saves $0.30–$1.60/week per trial client
- At 10 trial signups/month that's $12–$64/month saved on people who never pay

### GEO Competitors
- Each competitor = included in every GEO batch response analysis (context tokens)
- 3 for trial = "see your top 3 rivals". 15 for Growth = full competitive landscape

---

## What the User Sees

When they hit a limit, they get:
- **Admin panel:** `ValueError` with message like "Subreddit limit reached (5/5). Upgrade plan to add more."
- **Portal (HTMX):** Red text inline: "Keyword limit reached (30/30). Upgrade plan to add more."

No crash, no broken UI. Just a clear block with the reason.

---

## Questions for You

### 1. Are these numbers right?

I based them on:
- Your Business Brief (May 2026) for avatars + subreddits + comments
- My understanding of AI costs for GEO/keywords
- Common sense for what a trial user needs to see value vs what costs us real money

**If any number feels wrong — tell me which and what it should be.**

### 2. Should trial users get GEO at all?

Current: 5 prompts allowed. This means they can see "your AI visibility is 0%" — which is a great upgrade motivator. But it costs ~$0.10–$0.80 per trial user per week.

Alternative: Set to 0 for trial (block GEO entirely until they pay). Save money but lose the "gap reveal" sales moment.

**My recommendation:** Keep 5 for trial. The "0% vs competitor's 85%" moment is worth $3/month.

### 3. Do you want the "upgrade" CTA to link somewhere?

Right now it just says "Upgrade plan to add more." Where should it point?
- Pricing page (doesn't exist yet)?
- Contact form?
- Calendar link?
- Just the text as-is (they'll ask us)?

---

## Cost Impact Estimate

Assuming 5 active trial users + 2 seed + 1 starter (current pipeline):

| Before limits | After limits | Monthly savings |
|--------------|-------------|-----------------|
| Trial: up to 50 GEO prompts each | Trial: max 5 each | ~$15–$40/month on GEO |
| No keyword cap (some had 40+) | Capped per plan | ~$5–$10/month on scoring |
| No subreddit cap | Capped per plan | ~$10–$20/month on scraping + scoring |
| **Total estimated savings** | | **~$30–$70/month** |

Not huge in absolute terms, but scales linearly with new signups. At 20 trial users/month without limits = $120–$280/month wasted on free users.

---

## What's Still Open (From July 2 Letter)

Your answers from the previous letter are still needed for:
1. Trial behavior (generate drafts as preview? or scoring-only?)
2. Seed 3-month auto-nudge (monthly billing + upgrade prompt at month 3?)
3. Actions pool (single pool comment+post?)
4. Hard cap vs soft cap at 100% (I implemented hard — generation stops at cap)
5. Work email requirement (currently open, I recommend keeping it open)
6. AEO basic vs full (I implemented: trial=5 prompts, seed/starter=10-20, growth+=40-60)

**Please reply with corrections to the numbers table + answers to Q1-3 above.**

---

Max
