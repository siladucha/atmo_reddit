# MVP #1 — Capacity & Cost Forecast

**Date:** May 8, 2026  
**Target scale:** 100 avatars (production) + 100 (warming/test) = 200 total, 1000 subreddits, 10 clients  
**Architecture:** Celery + Redis + PostgreSQL (Docker) on EC2 t3.small. Single Reddit OAuth token.

---

## Verdict: ✅ Current architecture handles MVP #1

No infrastructure changes needed. No SQS, Valkey, sharding, or multi-token required.

---

## Reddit API Budget

| Metric | Value |
|--------|-------|
| Reddit rate limit | 60 RPM (86,400 calls/day) |
| Our self-imposed limit | 30 RPM (43,200 calls/day) |
| Total demand (scraping + karma) | ~4,400 calls/day |
| **Utilization** | **~10%** |

### Scraping Capacity

| Setting | Current | Recommended for 1000 subs |
|---------|---------|--------------------------|
| `scrape_tick_interval_seconds` | 90 | 45 |
| `scrape_rate_limit_rpm` | 15 | 30 |
| `scrape_freshness_window_hours` | 12 | 12 |

With recommended settings:
- Scrapes possible/day: **1,920**
- Unique subreddits (realistic, with sharing): ~300
- Scrapes needed/day (300 × 2): **600**
- **Coverage: 320%** — massive headroom

Worst case (1000 truly unique subs):
- Scrapes needed/day: 2,000
- Coverage: 96% — still fine

### Karma Tracking

| Metric | Value |
|--------|-------|
| Avatars tracked | 100 |
| API calls per avatar per run | 4 |
| Runs per day (every 4h) | 6 |
| Total karma API calls/day | 2,400 |
| Time per run (2s delay) | ~3 minutes |

No bottleneck. Fits easily within API budget.

---

## Monthly Cost Forecast (10 clients)

### AWS Infrastructure

| Service | Cost/mo |
|---------|---------|
| EC2 t3.small + EBS + EIP | $20.43 |
| Redis (Docker on EC2) | $0 |
| PostgreSQL (Docker on EC2) | $0 |
| **AWS Total** | **$20/mo** |

### AI / LLM APIs

| Operation | Model | Calls/day | Cost/month |
|-----------|-------|-----------|-----------|
| Scoring | Gemini Flash | 2,000 | $18 |
| Persona Selection | Claude Sonnet | 150 | $68 |
| Comment Generation | Claude Sonnet | 150 | $162 |
| Comment Editor | Claude Sonnet | 150 | $68 |
| Hobby Comments | Gemini Flash | 150 | $1 |
| Post Drafts | Claude Sonnet | 20 | $30 |
| **AI Total** | | | **$347/mo** |

### Total

| Category | Cost/month | % |
|----------|-----------|---|
| AI / LLM | $347 | 94% |
| AWS | $20 | 5% |
| Other (domain, SSL) | $1 | <1% |
| **TOTAL** | **$368/mo** | 100% |

---

## Revenue vs Cost

| Clients | Revenue (avg $500/client) | Costs | Margin |
|---------|--------------------------|-------|--------|
| 1 | $500 | $57 | 89% |
| 3 | $1,500 | $130 | 91% |
| 5 | $2,500 | $210 | 92% |
| 10 | $5,000 | $370 | 93% |

---

## Scaling Triggers (when to upgrade)

| Trigger | Action | Added cost |
|---------|--------|-----------|
| 5+ paying clients, data loss unacceptable | PostgreSQL → RDS db.t4g.small | +$24/mo |
| EC2 CPU > 80% sustained | t3.small → t3.medium | +$15/mo |
| Need zero-downtime deploys | Add ALB + second EC2 | +$35/mo |
| 200+ avatars, karma tracking > 10 min/run | Increase karma interval to 6h or parallelize | $0 |
| 1000+ unique subs, coverage < 90% | Raise RPM to 45, reduce tick to 30s | $0 |
| Reddit starts rate-limiting aggressively | Add second OAuth token (second Reddit app) | $0 |

---

## What Does NOT Need to Change for MVP #1

- ❌ No SQS migration needed
- ❌ No Valkey/ElastiCache needed
- ❌ No multi-token Reddit API
- ❌ No sharding
- ❌ No Kafka/event streaming
- ❌ No separate worker instances
- ❌ No RDS (until 5+ clients)

---

## Key Insight

**93% of costs = LLM APIs (Claude Sonnet).** AWS infrastructure is noise at this scale.

The only cost optimization that matters before 50 clients:
1. Replace Claude Sonnet with Haiku for comment editing (saves ~$50/mo)
2. Skip persona selection for single-avatar clients (saves ~$20/mo per such client)
3. Batch scoring (10 threads per prompt) — saves ~30% on scoring tokens

---

*Next review: when reaching 5 paying clients or when daily coverage drops below 90%.*
