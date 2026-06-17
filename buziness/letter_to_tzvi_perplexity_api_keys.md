# Tzvi — Perplexity API Keys Needed for GEO Monitoring

**Date:** June 17, 2026
**From:** Max
**Priority:** Low (not blocking, but needed for demo)

---

## What's Ready

The GEO/AEO monitoring module is live on production. I've set up everything for ATMO (NeuroYoga):

- **12 buyer-intent prompts** — questions real buyers ask AI assistants ("best neurofeedback apps", "breathing app that works", "Calm vs Headspace vs neurofeedback apps", etc.)
- **9 competitors tracked** — Calm, Welltory, Oura, WHOOP, Headspace, Muse, Insight Timer, Breathwrk, Othership
- **Brand detection engine** — checks if "ATMO" appears in AI responses
- **Citation parser** — extracts Reddit URLs from AI answers (proves our Reddit presence gets cited)

When you press "Run" on the GEO page, it sends all 12 prompts to Perplexity Sonar (3 runs each = 36 queries), then shows you:
- Brand appearance rate (% of queries where ATMO is mentioned)
- Which competitors appear instead
- Which Reddit threads get cited

---

## What I Need From You

**Perplexity API key** — go to https://www.perplexity.ai/settings/api

I need **two keys**:
1. **Development key** — for my local testing (can be on free tier / minimal budget)
2. **Production key** — for the live system (separate billing, easy to track cost)

The cost is minimal — each GEO run costs ~$0.10-0.15 (36 queries × Sonar pricing). Even with twice-weekly automated runs, it's ~$3-4/month per client.

---

## What's Coming Next

- **Model fallback** — if Perplexity is down or rate-limited, system will fall back to another model (Google Gemini or direct OpenAI). Building this now.
- **Automated schedule** — twice-weekly runs (Tuesday/Friday mornings) without manual trigger
- **Historical trends** — brand visibility rate over time (week-over-week improvement chart)
- **Client portal integration** — clients already see the Visibility page, just need data flowing

---

## How to Set the Key

Once you have the key, two options:
1. Send it to me — I'll configure it on the server (System Settings → `geo_perplexity_api_key`)
2. Go to Admin → System Settings → find `geo_perplexity_api_key` → paste the key

After that, go to `/admin/clients/.../geo` and press Run — you'll see results within 2-3 minutes.

— Max
