# RAMP System Capacity & Cost Analysis — July 9, 2026

## Infrastructure

- **Production:** DigitalOcean Droplet ($23/mo) — scalable on demand (resize takes 1 min)
- **Staging:** DigitalOcean Droplet ($12/mo) — test environment
- **Total infra:** $35/mo (2 servers)

Hardware is NOT the bottleneck — DO allows instant vertical scaling. The real limits are **speed/throughput constraints** in the architecture.

---

## 1. Speed Limits — What Actually Bottlenecks

### Sequential Processing (cannot parallelize without code changes)

| Bottleneck | Current Speed | Limit Per Day | What Depends on It |
|------------|--------------|---------------|-------------------|
| **Claude Sonnet generation** | ~3-5s per comment | ~17,000 (single worker) | Draft output |
| **Extension posting** | 1 post per 3 min minimum | **320 posts/day** (8h x 20/h) per executor | Actual Reddit posts |
| **Reddit API (PRAW)** | 60 req/min (1 token) | 86,400 calls/day | Scraping, health, karma |
| **Scoring batch** | ~2s per batch of 5 threads | ~43,000 threads/day | Thread selection |
| **GEO per-query latency** | Perplexity 5s, Claude 35s | ~700 Perp / ~100 Claude per day | Visibility monitoring |

### Extension is the Real Ceiling

| Executors | Posts/day (per exec) | Total Posts/day | Avatars Serviceable |
|-----------|---------------------|-----------------|---------------------|
| 1 | 320 (theoretical) / ~60 (realistic) | 60 | ~8-10 (Phase 2-3) |
| 2 | 60 each | 120 | ~15-20 |
| 3 | 60 each | 180 | ~25-30 |
| 5 | 60 each | 300 | ~40-50 |

**Realistic per executor:** ~60 posts/day (active hours 08-22 = 14h, minus delays, retries, missed windows).

### Pipeline Throughput (per daily cycle)

| Stage | Speed | At 10 clients | At 20 clients | At 50 clients |
|-------|-------|---------------|---------------|---------------|
| Scraping (all subs) | 4 scrapes/min | 25 min | 50 min | 125 min |
| Scoring | 150 threads/min (batch) | 10 min | 20 min | 50 min |
| Generation | 12-20 comments/min | 8 min | 15 min | 40 min |
| EPG build | ~30s per avatar | 10 min | 20 min | 50 min |
| **Total morning pipeline** | — | **~53 min** | **~105 min** | **~265 min** |

**At 20 clients:** morning pipeline takes ~1h45m (08:00 to 09:45). Tasks scheduled for 09:00 will be late.
**At 50 clients:** pipeline takes 4.5h. Fundamentally broken without parallelization.

### Fix at Scale (when needed)

| Clients | Fix | Effort |
|---------|-----|--------|
| 15-20 | Split morning pipeline into 2 batches (08:00 + 10:00) | 2h |
| 30+ | Add second Celery worker with concurrency=4 | Config change |
| 50+ | Parallel scoring (asyncio/multi-thread) | 1 week |
| 100+ | Multiple Reddit API tokens + async PRAW | 2 weeks |

---

## 2. Costs

### Current Monthly (July 2026)

| Item | Cost/month | Cost/day |
|------|-----------|----------|
| AI (LLM — all providers) | $18.27 | $0.61 |
| Production server (DO) | $23.00 | $0.77 |
| Staging server (DO) | $12.00 | $0.40 |
| Email (Brevo free tier) | $0 | $0 |
| **Total** | **$53.27** | **$1.78** |

### AI Cost Per Avatar/Month (measured, post-optimization)

| Operation | $/avatar/month |
|-----------|---------------|
| Comment generation (Claude Sonnet) | $6.50 |
| Scoring (Gemini Flash) | $0.50 |
| GEO monitoring (shared across client) | $1.00 |
| Other (persona, editing, hobby, strategy) | $0.50 |
| **Total** | **~$8.50** |

### Scaling Forecast

| Clients | Avatars | AI/mo | Infra/mo | Total/mo | Per client |
|---------|---------|-------|----------|----------|-----------|
| 1 | 1 | $12 | $35 | $47 | $47 |
| 5 | 10 | $85 | $35 | $120 | $24 |
| 10 | 20 | $170 | $35 | $205 | $20.50 |
| 20 | 40 | $340 | $35 | $375 | $18.75 |
| 30 | 60 | $510 | $35 | $545 | $18.17 |
| 50 | 100 | $850 | $50* | $900 | $18.00 |

*Server upgrade at 50 clients (4 vCPU, $48/mo prod)

### Margins

| Plan | Price/mo | Avatars | Cost/mo | Margin |
|------|----------|---------|---------|--------|
| Seed $149 | $149 | 1 | ~$12 | **92%** |
| Starter $399 | $399 | 3 | ~$28 | **93%** |
| Growth $799 | $799 | 7 | ~$62 | **92%** |
| Scale $1,499 | $1,499 | 15 | ~$130 | **91%** |

### Break-Even

One Seed client ($149/mo) covers ALL operating costs ($53/mo). Profitable from day 1.

---

## 3. Summary: How Many Can We Serve TODAY

| Metric | Current (comfortably) | Before slowdowns | Notes |
|--------|----------------------|------------------|-------|
| **Paying clients** | 10-12 | 15-20 | Pipeline duration is first issue |
| **Avatars (total)** | 30-40 | 50-60 | Extension throughput is ceiling |
| **Subreddits monitored** | 150-200 | 300 | Scraping time grows linearly |
| **Posts per day (all avatars)** | 30-50 | 60-100 | Depends on executor count |
| **GEO queries/day** | 20-30 | 50 | Provider latency, not server |
| **Executors (extension nodes)** | 1-2 | 3-5 | Each adds ~60 posts/day capacity |

**Bottom line:** Current architecture handles **10-15 paying clients** with no changes. Hardware scales instantly on DO. Code parallelization needed at 20+.
