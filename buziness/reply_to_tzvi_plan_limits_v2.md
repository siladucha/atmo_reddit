# Re: Plan Limits — Updated and Deployed

**To:** Tzvi  
**From:** Max  
**Date:** July 12, 2026  
**Subject:** Plan limits updated per your decisions — all clear on cost exposure

---

## Done

Updated all plan limits to match your table. Here's what's now live in the config:

| Resource | Trial | Seed ($149) | Starter ($399) | Growth ($799) | Scale ($1,499) |
|----------|-------|-------------|----------------|---------------|----------------|
| Active subreddits | 1 | 2 | 4 | 8 | Unlimited |
| Platform Voices | 0 (5-comment burst) | 1 | 3 | 7 | 15 |
| Comments/month | 5 (one-time burst) | 30 | 60 | 150 | 400 |
| GEO/AEO prompts | 3 | 10 | 20 | 40 | 60 |
| Keywords | Unlimited (not shown to client) | | | | |
| GEO competitors | Unlimited internally, top 3–5 shown dynamically | | | | |

Agency clients continue to get custom limits set individually.

---

## Your Question: Cost Exposure from Unlimited Keywords + Competitors

**Short answer: no meaningful risk.**

**Keywords** — don't generate API calls on their own. They're a matching list inside the scoring prompt (a few hundred tokens in a 4K-token prompt). Even a client with 200 keywords adds ~$0.03/month to scoring cost. The subreddit limit is what actually gates scraping volume, and that's still capped.

**GEO competitors** — even cheaper. Competitor tracking is a regex/string match against AI responses we've already retrieved. Whether we check for 5 competitors or 50 in the same response text, the cost is identical. No extra API calls generated.

The only scenario where "more keywords" could cause trouble is if keywords were used to discover new subreddits automatically (more keywords → more subs found → more scraping). But since subreddits are hard-limited separately (2/4/8/unlimited), this can't happen.

---

## Trial Behavior — 5-Comment Burst

Implemented as you described: trial gets 5 comments total (not per day). This means the full loop runs once — find thread → generate draft → approve → post → track karma — then the client hits the wall with a clear "this is what the pipeline does at scale, here's what you'd get on Starter" message.

The trial subreddit cap of 1 means we find relevant threads fast (no dilution), and the burst is concentrated enough that the client sees results in 1–2 days, not spread over a week.

---

## What This Changes Operationally

1. **Keyword and competitor enforcement functions still exist in code** — they just return "allowed" for everyone since limits are 999. If you ever want to bring caps back for specific plans, it's a config change.

2. **Client dashboard for competitors** — I'll update the visibility page to show "Top 5 by AI visibility score" dynamically ranked (per your spec) rather than a static tracked list. This is a UI change I'll handle separately.

3. **Seed upgrade pressure** — agreed with the tighter subreddit cap (2). With 1 avatar posting 30 comments/month across only 2 subreddits, the client will clearly see "I need more coverage" within the first month.

---

## Still Waiting On (From Your Email)

- Trial behavior details (preview vs full generation) — partially answered with the burst model
- Seed 3-month upgrade flow
- Shared action pool (comments + posts = one meter?)
- Hard vs soft monthly limits
- Work email requirement
- AEO feature packaging

No rush — the limits are deployed and won't block anything on my side. Take the day or two you mentioned.

Max
