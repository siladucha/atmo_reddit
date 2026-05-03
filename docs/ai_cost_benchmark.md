# AI Cost Benchmark — Reddit Engagement SaaS

Based on analysis of Ori's PoC prompts and workflows.

## Token Usage Per Operation

### One Professional Comment (full pipeline)

| Step | Model | Input tokens | Output tokens |
|------|-------|-------------|---------------|
| 1. Scoring (relevance/quality/strategic) | Gemini Flash | ~4,000 | ~200 |
| 2. Persona Selection | Claude Sonnet | ~5,000 | ~300 |
| 3. Comment Generation | Claude Sonnet | ~12,000 | ~200 |
| 4. Comment Editor (quality fix) | Claude Sonnet | ~5,000 | ~200 |
| **Total per comment** | | **~26,000 input** | **~900 output** |

### One Hobby Comment (karma building)

| Step | Model | Input tokens | Output tokens |
|------|-------|-------------|---------------|
| Comment Generation | Gemini Flash | ~3,000 | ~150 |

### One Reddit Post (draft)

| Step | Model | Input tokens | Output tokens |
|------|-------|-------------|---------------|
| Brief + Draft Generation | Claude Sonnet | ~8,000 | ~500 |

---

## Daily Volume (Ori's PoC baseline)

- ~200 posts scraped from subreddits
- All 200 go through scoring
- Top 15 go through full comment pipeline
- ~15 hobby comments generated
- ~2 post drafts generated

---

## Cost Per Operation (current API pricing)

| Model | Input price | Output price |
|-------|-----------|-------------|
| Gemini Flash | $0.075 / 1M tokens | $0.30 / 1M tokens |
| Claude Sonnet | $3.00 / 1M tokens | $15.00 / 1M tokens |

| Operation | Count/day | Model | Cost/unit | Cost/day |
|-----------|----------|-------|-----------|----------|
| Scoring | 200 | Gemini Flash | $0.0003 | $0.06 |
| Persona Selection | 15 | Claude Sonnet | $0.015 | $0.23 |
| Comment Generation | 15 | Claude Sonnet | $0.036 | $0.54 |
| Comment Editor | 15 | Claude Sonnet | $0.015 | $0.23 |
| Hobby Comments | 15 | Gemini Flash | $0.002 | $0.03 |
| Post Drafts | 2 | Claude Sonnet | $0.05 | $0.10 |
| **Total/day** | | | | **~$1.20** |

---

## Monthly Cost Per Client

| Scenario | Comments/day | Posts/day | AI cost/month |
|----------|-------------|----------|---------------|
| Light | 10 | 1 | ~$21 |
| Standard (Ori baseline) | 15 | 2 | ~$36 |
| Active | 25 | 3 | ~$60 |

---

## Total Infrastructure Cost Per Client

| Item | Monthly cost |
|------|-------------|
| AI / LLM API | $25–60 |
| VPS (shared across clients) | $10–20 per client |
| PostgreSQL (shared) | $0 (on VPS) |
| Redis (shared) | $0 (on VPS) |
| Domain + SSL | ~$1 |
| **Total per client** | **$35–80** |

At $2,000/mo client price → **~95-98% gross margin on infrastructure.**

---

## Cost Optimization Levers

1. **Use Gemini Flash for scoring** — 40x cheaper than Claude, good enough for classification
2. **Cache company profiles and voice profiles** — don't resend static context every call
3. **Skip Comment Editor step for hobby comments** — lower quality bar acceptable
4. **Batch scoring calls** — reduce API overhead
5. **Use cheaper models for redrafts** — GPT-4o-mini or Gemini Flash for simple edits

---

## Key Insight

AI token costs are negligible (~$36/mo per client at standard volume).

The real cost is human time: review, editing, and manual posting. Automating the review UI and streamlining the approval flow has 10x more impact on margins than optimizing token usage.

---

*Analysis based on Ori's PoC prompt sizes extracted from n8n workflow JSONs (May 2026).*
*Prices based on current OpenRouter/direct API rates. Subject to change.*
