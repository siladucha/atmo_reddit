# RAMP Load Profile & Capacity Analysis — July 9, 2026

**All metrics from production database (57 days uptime, 7-day measurement window)**

---

## Executive Summary

Current architecture comfortably supports **10-12 paying clients (~25 avatars)**. First bottleneck is **morning pipeline duration** (sequential AI calls). Scaling to 20+ clients requires splitting the pipeline into parallel batches (~2h engineering work). Extension posting throughput limits to ~60 real Reddit posts/day per executor node.

Safe production capacity (with 2-3× headroom): **8 paying clients, 20 avatars.**

---

## 1. Per-Avatar Daily Load Profile (Measured)

Current system: **26 active avatars, 9 clients, 71 subreddits.**

### Operations Per Avatar Per Day

| Operation | Per Avatar/Day | Source |
|-----------|---------------|--------|
| Subreddit scrapes | 24 (71 subs ÷ ~3 avatars/sub) | scrape_log |
| AI calls (generation + scoring + hobby) | 1.3 (gen) + 0.3 (scoring) + 1.0 (hobby) = ~2.6 | ai_usage_log |
| Tokens consumed | ~31,600 (822K/day ÷ 26) | ai_usage_log |
| EPG slots created | 1.7 | epg_slots |
| Drafts generated | 1.0 | comment_drafts |
| Execution tasks | 0.35 | execution_tasks |
| Activity events | 49 | activity_events |
| Reddit API calls (health + karma) | 8 (2 health×2 + 4 karma) | calculated |

### Operations Per Client Per Day

| Operation | Per Client/Day | Source |
|-----------|---------------|--------|
| Subreddit scrapes (client subs) | ~70 (624 ÷ 9) | scrape_log |
| AI scoring calls | 0.8 (7 ÷ 9) | ai_usage_log |
| GEO monitoring queries | ~6.4 (58 ÷ 9) | ai_usage_log |
| Drafts generated | 3 (27 ÷ 9) | comment_drafts |
| EPG slots | 4.8 (43 ÷ 9) | epg_slots |

### System-Level Daily Operations (Fixed Cost, Independent of Scale)

| Operation | Per Day | Cost/Day | Notes |
|-----------|---------|----------|-------|
| GEO monitoring (Anthropic Claude) | 15 calls | $2.37 | Dominates cost — 91% of AI spend |
| GEO monitoring (Perplexity) | 43 calls | $0.03 | Cheap alternative |
| Subreddit rule extraction | 21 calls | $0.01 | Weekly batch (Sun), amortized daily |
| Emotional profiles | 9 calls | $0.02 | Weekly batch (Sun), amortized daily |
| Watchdog, heartbeats, Beat | continuous | $0 | Included in infra |

---

## 2. Three-Layer Cost Model

### Layer 1: System (Fixed — Regardless of Client Count)

| Item | Monthly | Daily |
|------|---------|-------|
| Production server (DO 2vCPU/4GB) | $23 | $0.77 |
| Staging server (DO) | $12 | $0.40 |
| GEO Claude monitoring (current) | $71* | $2.37 |
| GEO Perplexity monitoring | $1 | $0.03 |
| Subreddit intelligence (weekly) | $0.50 | $0.02 |
| **System total** | **$107.50** | **$3.59** |

*GEO Claude is optional and can be disabled. Without it: system cost = $36.50/mo.

### Layer 2: Per-Client (Scales with Clients)

| Item | Per Client/Month | Notes |
|------|-----------------|-------|
| Scoring (Gemini Flash) | $1.15 | 7 calls/day × $0.005 × 30 |
| Strategy generation (on-demand) | ~$0.15 | Rare, amortized |
| GEO prompts management | included in system | Shared pool |
| **Client layer** | **~$1.30/client/month** | |

### Layer 3: Per-Avatar (Scales with Avatars)

| Item | Per Avatar/Month | Notes |
|------|-----------------|-------|
| Comment generation (Claude Sonnet) | $2.75 | 1 call/day × $0.031 × 30 (low — Phase 1 only hobby) |
| Hobby comments (Gemini Flash) | $0.60 | 1 call/day × $0.001 × 30 |
| Persona selection | $0.81 | Amortized |
| Editing | $0.17 | Amortized |
| Reddit API (health + karma) | $0 | Free |
| Extension execution | $0 | Free (Chrome) |
| **Avatar layer (Phase 1)** | **~$4.33/avatar/month** | |
| **Avatar layer (Phase 2-3, full generation)** | **~$8.50/avatar/month** | More gen calls |

### Combined Formula

```
Monthly cost = $36.50 (system, no Claude GEO)
             + $71 (Claude GEO, if enabled)
             + N_clients × $1.30
             + N_avatars × $4.33 (Phase 1) or $8.50 (Phase 2-3)
```

---

## 3. Temporal Load Profile (Peak Analysis)

### AI Calls by Hour (7-day measured)

```
Hour  | Calls | Cost    | Activity
------+-------+---------+----------------------------------
 04:00|    64 | $0.13   | Weekly batches (Sun): rules, emotional
 06:00|    50 | $0.04   | Phase eval, CQS checks
 08:00|   219 | $1.01   | ★ PEAK 1: Morning pipeline (score + generate + EPG)
 09:00|   172 | $5.79   | ★ PEAK 2: GEO monitoring batch
 10:00|   112 | $6.08   | ★ PEAK 3: GEO continues + hobby generation
 11:00|   101 | $2.35   | Tail: remaining generations
 12:00|   134 | $2.63   | Second scrape cycle + GEO tail
 14:00|    17 | $0.07   | Afternoon pipeline (smaller)
 Rest |   <10 | <$0.05  | Heartbeats, on-demand
```

### Scraping by Hour (7-day measured)

```
Hour  | Scrapes | Notes
------+---------+------
 03-04|   244   | Pre-dawn: weekly batch subs
 09-10|   449   | ★ PEAK: After morning pipeline triggers queue_tick
 11-13|   999   | Sustained: continuous scraping
 18-21| 1,547   | ★ HIGHEST: Evening scrape cycle (6h interval from morning)
```

### Daily Cycle Timeline

```
06:00  Phase evaluation + zone evaluation
06:30  CQS batch check
07:30  Health check (shadowban detection)
07:45  Hobby scraping
08:00  ★ SCORING + GENERATION (main pipeline) — CPU peak
08:15  EPG build + generate
09:30  ★ GEO monitoring — AI cost peak
10:00  Hobby generation continues
12:15  Karma outcome check
13:30  Health check #2
13:45  Hobby scraping #2
14:00  Afternoon pipeline (top-up)
14:15  EPG top-up
~all day: Extension posting (08:00-22:00, 3 min intervals)
~every 4h: Karma tracking + draft reconciliation
23:30  Expire overdue tasks
```

### Peak Duration (Morning Window)

At current load (9 clients, 26 avatars):
- **08:00-08:30**: Scoring + generation = ~22 min
- **08:30-09:00**: EPG build = ~13 min
- **09:00-10:30**: GEO monitoring = ~90 min (Claude latency 45s/query × 15 queries)

**Total morning critical path: ~125 min (08:00 to 10:05)**

---

## 4. Scaling Table — Per Client Avatar with Business Assumptions

### Business Assumptions (from pricing model)

| Plan | Avatars | Subreddits | Comments/month | Posts/month |
|------|---------|-----------|----------------|-------------|
| Seed ($149) | 1 | 1 professional + hobbies | 30 | 0 |
| Starter ($399) | 3 | 2 professional + hobbies | 60 | 0 |
| Growth ($799) | 7 | 5 professional + hobbies | 150 | 10 |
| Scale ($1,499) | 15 | unlimited | 400 | 20 |

### What One Avatar Actually Costs the System Per Day

**Phase 1 avatar (hobby only, 2-3 comments/day):**

| Resource | Per Day | Calculation |
|----------|---------|-------------|
| Reddit API calls | 8 | 2 health + 4 karma + 2 hobby scrape |
| AI calls | 2.6 | 1 hobby gen + 0.3 scoring + 1 EPG + 0.3 misc |
| Tokens | ~5,000 | Gemini Flash only (cheap) |
| AI cost | $0.003 | Gemini Flash: ~$0.001/call |
| DB writes | ~55 | Events + scrape log + slots + drafts |
| Celery tasks | ~8 | Scrape + health + karma + EPG + generation |
| Worker-thread-seconds | ~45s | Scraping (9s×3) + AI calls (1.6s×2.6) + EPG (5s) |
| Extension posts | 2-3 | 3 min each = 6-9 min of executor time |

**Phase 2 avatar (professional + hobby, 7 comments/day):**

| Resource | Per Day | Calculation |
|----------|---------|-------------|
| Reddit API calls | 12 | 2 health + 4 karma + 4 pro scrape + 2 hobby scrape |
| AI calls | 9 | 1 gen + 1 persona + 1 edit + 1 scoring + 3 hobby + 1 EPG + 1 misc |
| Tokens | ~25,000 | Claude Sonnet (~12K) + Gemini Flash (~13K) |
| AI cost | $0.05 | Claude $0.031 + Gemini $0.005×8 |
| DB writes | ~110 | More drafts, more events, more scores |
| Celery tasks | ~15 | More generation + scoring tasks |
| Worker-thread-seconds | ~95s | Gen (6.5s) + persona (10s) + scoring (12s×0.8) + scraping + misc |
| Extension posts | 7 | 3 min each = 21 min of executor time |

**Phase 3 avatar (full brand, 12-15 comments/day):**

| Resource | Per Day | Calculation |
|----------|---------|-------------|
| Reddit API calls | 16 | More karma tracking, more health |
| AI calls | 16 | More generation + scoring cycles |
| Tokens | ~45,000 | Multiple Claude Sonnet calls |
| AI cost | $0.12 | 3-4 Claude gen calls + supporting Gemini |
| DB writes | ~180 | Full pipeline activity |
| Celery tasks | ~22 | Full pipeline |
| Worker-thread-seconds | ~180s | Multiple gen + scoring + scraping |
| Extension posts | 12-15 | 3 min each = 36-45 min of executor time |

### Capacity Per Plan (with current infrastructure)

| Plan | Avatars | Phase Mix | AI Cost/day | Extension min/day | Worker-sec/day | Max Clients on Current Infra |
|------|---------|-----------|-------------|-------------------|----------------|------------------------------|
| Seed | 1 | Phase 1-2 | $0.003-0.05 | 6-21 min | 45-95s | **40+** (not the bottleneck) |
| Starter | 3 | 1×Ph2 + 2×Ph1 | $0.06 | 33 min | ~185s | **20+** |
| Growth | 7 | 3×Ph2 + 4×Ph1 | $0.16 | 75 min | ~400s | **10-12** |
| Scale | 15 | 7×Ph2 + 5×Ph1 + 3×Ph3 | $0.50 | 180 min (3h!) | ~1,200s | **4-5** |

### The Real Constraint: Extension Time Budget

Available executor time per day: **14h × 60min = 840 min**

| Plan | Extension Time Needed | % of 1 Executor's Day |
|------|----------------------|----------------------|
| Seed (1 avatar) | 6-21 min | 1-3% |
| Starter (3 avatars) | 33 min | 4% |
| Growth (7 avatars) | 75 min | 9% |
| Scale (15 avatars) | 180 min | 21% |

**One executor can handle:**
- 5× Scale clients (900 min / 840 min ≈ limit)
- 10× Growth clients
- 25× Starter clients
- Unlimited Seed clients

But this assumes 100% uptime and 0% failure. With realistic 60% efficiency:

**One executor realistically handles:**
- 3× Scale clients
- 6× Growth clients  
- 15× Starter clients

### Full Scaling Matrix (Realistic)

| Clients | Plan Mix | Avatars | AI $/day | Ext Time/day | Executors Needed | Infra | Total $/month |
|---------|----------|---------|----------|-------------|-----------------|-------|---------------|
| 1 | 1× Starter | 3 | $0.06 | 33 min | 1 (Max) | Current | $47 |
| 3 | 2× Starter + 1× Growth | 13 | $0.28 | 141 min | 1 | Current | $75 |
| 5 | 3× Starter + 2× Growth | 23 | $0.50 | 249 min | 1 | Current | $105 |
| 8 | 4× Starter + 3× Growth + 1× Scale | 42 | $1.10 | 543 min | 1 (tight) | Current | $185 |
| 10 | 5× Starter + 4× Growth + 1× Scale | 58 | $1.50 | 720 min | 2 ⚠️ | Current | $240 |
| 15 | 7× Starter + 5× Growth + 3× Scale | 86 | $2.50 | 1,215 min | 3 | Upgrade | $380 |
| 20 | Mix | ~110 | $3.50 | 1,700 min | 4 | Upgrade | $520 |

### Critical Insight

**The system bottleneck is NOT servers, NOT AI, NOT Reddit API. It's executor time.**

Every post requires 3 minutes of a Chrome extension being active. At Scale plan (15 avatars × 12-15 posts/day), a single client needs 3 hours of executor time daily.

This means the scaling question is fundamentally: **how many executors (human workers with Chrome) do we operate?**

| Executors | Posts/day (realistic) | Avatars Supported | Revenue Potential |
|-----------|----------------------|-------------------|--------------------|
| 1 (Max alone) | ~50 | ~7-10 Phase 2 | ~$3,000/mo |
| 2 | ~100 | ~15-20 | ~$6,000/mo |
| 3 | ~150 | ~22-30 | ~$10,000/mo |
| 5 | ~250 | ~35-50 | ~$15,000/mo |

---

## 5. Constraint Analysis

### Reddit API (60 req/min = 86,400/day)

| Current usage | 832 calls/day | **1% of limit** |
|---------------|--------------|-----------------|

**Not a bottleneck** until 100+ avatars. Single PRAW token handles ~2,600 avatars theoretically.

Real constraint: **PRAW is synchronous** — each call blocks a worker thread for 3-33s. At 50 avatars, scraping alone needs ~4,500 calls/day = still only 5% of API limit, but consumes ~11 hours of worker-thread-seconds/day (with 2 workers, that's ~33% of available capacity).

### AI Pipeline

| Bottleneck type | Details |
|----------------|---------|
| **Latency** | Claude GEO: 45s/call. Claude generation: 6.5s/call. Gemini: 1.5-12s. |
| **Cost** | Claude GEO dominates (91%). Generation is $0.03/comment. |
| **Concurrency** | No parallel AI calls — sequential per Celery task. Worker blocks until response. |

**Primary AI bottleneck: Latency × Sequentiality.** 15 GEO queries × 45s = 11 min just for GEO Claude. This runs sequentially in one worker.

### Extension Posting

| Constraint | Value | Nature |
|-----------|-------|--------|
| Minimum interval | 3 min | Hard-coded safety |
| Active hours | 08:00-22:00 (14h) | Configurable |
| Window miss tolerance | 30 min | Then task fails |
| Success rate (current) | ~50% | Improving with old.reddit |
| **Realistic throughput** | **40-60 posts/day per executor** | After retries, misses |

**Extension is the ceiling for actual Reddit output.** Everything above is preparation; extension is the final mile.

### Database

| Metric | Current | At 50 avatars | At 100 avatars |
|--------|---------|---------------|----------------|
| DB size | 199 MB | ~400 MB | ~700 MB |
| Writes/day | ~2,880 rows | ~5,500 | ~11,000 |
| Connections active | 1 of 50 | ~3-5 | ~8-10 |
| Query latency | <5ms | <5ms | <10ms |

**Not a bottleneck** until 200+ avatars or 50+ concurrent requests.

---

## 6. Safe Production Capacity (with 2-3× headroom)

### Definition of "Safe"

- CPU peak never exceeds 60% (currently 30%)
- RAM never exceeds 75% (currently 56%)  
- Pipeline completes before 10:00 (currently finishes ~10:05)
- API usage stays below 10% of limit
- Worker queue depth stays <50 (currently ~0)

### Verdict

| Metric | Safe Limit | Calculation |
|--------|-----------|-------------|
| **Avatars** | 20 | CPU headroom ÷ per-avatar load |
| **Clients** | 8 | ~2.5 avatars per client avg |
| **Posts/day** | 50 | 1 executor × conservative throughput |
| **Subreddits** | 120 | Scraping time budget |

### What Triggers First

1. **Pipeline duration >1h** at ~15 clients → morning tasks delayed
2. **Extension throughput** at ~8 avatars (Phase 2-3 with 7 posts/day each) → queue builds up
3. **RAM pressure** at ~40 avatars → worker OOM risk during peak

---

## 7. Scaling Roadmap

### Phase 1: Current (0-8 clients, 0-20 avatars)

No changes needed. System operates at 30-50% capacity.

| Resource | Utilization |
|----------|-------------|
| CPU | 11% avg, 30% peak |
| RAM | 56% |
| API | 1% |
| Workers | 18% |

### Phase 2: Growth (8-20 clients, 20-50 avatars)

| Change | Effort | When |
|--------|--------|------|
| Split morning pipeline: 08:00 + 10:00 batches | 2h | At 12 clients |
| Disable Claude GEO (use Perplexity only) | 5 min config | Immediately (saves $71/mo) |
| Add 2nd executor (human worker) | Ops | At 8 Phase 2+ avatars |
| Increase Celery concurrency: 2→4 | Config | At 30 avatars |

### Phase 3: Scale (20-50 clients, 50-100 avatars)

| Change | Effort | When |
|--------|--------|------|
| Server upgrade: 4 vCPU / 8 GB | 1 min (DO resize) | At 40 avatars |
| Parallel scoring (asyncio) | 1 week | At 30 clients |
| Multiple PRAW tokens (1 per client group) | 2 days | At 50 avatars |
| Dedicated executor machines | Ops decision | At 50 avatars |
| DB connection pooling (PgBouncer) | 1 day | At 50 clients |

### Phase 4: Enterprise (50+ clients, 100+ avatars)

| Change | Effort | When |
|--------|--------|------|
| Managed PostgreSQL (DO or RDS) | Migration | At 100 avatars |
| Separate worker nodes | Infra | At 100 avatars |
| Async PRAW / httpx | 2 weeks | At 100 clients |
| Queue priority system | 1 week | At 100 clients |
| AWS migration (optional) | 2-4 weeks | At enterprise SLA requirement |

---

## 8. Risks to Capacity

| Risk | Impact on Capacity | Probability | Mitigation |
|------|-------------------|-------------|-----------|
| Reddit shadowban spike | Reduces active avatar count | Medium | Phase system, health monitoring |
| Comment deletion rate increase | Wasted generation cost | Medium-High | Fitness gate, risk profiles |
| Claude API price increase | Margin compression | Low | Model routing via DB, switch in minutes |
| Anthropic credit exhaustion ($50/mo cap) | Generation stops completely | High (happened July 7) | Increase limit, monitor spend alerts |
| Reddit API deprecation | Scraping breaks | Very Low | old.reddit.com stable 10+ years |
| Extension DOM breaking | Posting stops | Very Low (old.reddit) | old.reddit unchanged for decade |
| Single server failure | Full outage 1-2 min | Low | Watchdog auto-recovery (tested: 60s) |
| Morning pipeline overrun | Tasks delivered late | Medium (at 15+ clients) | Split batches |
| Executor unavailability | Posts not made | Medium | Email fallback, multiple executors |

---

## Conclusion

**Current architecture comfortably supports 8 paying clients (~40 avatars) with one executor.**

**The bottleneck is NOT technology — it's executor time.** Every Reddit post requires 3 minutes of Chrome extension active time. A single executor (Max) can handle ~50 posts/day = ~7-10 Phase 2 avatars = ~$3,000/mo revenue.

**Scaling is an operations decision, not an engineering decision:**
- At 10 clients: need 2nd executor ($200-500/mo workforce cost)
- At 20 clients: need 3-4 executors
- At 50 clients: need dedicated posting workforce (5-10 people) or headless Chrome automation

**Infrastructure scales trivially:** DO resize (1 min), add workers (config change), add executors (hire). No code rewrites needed until 50+ clients.

**Cost structure is healthy:** 91-93% gross margins at all tiers. System fixed cost ($36.50/mo without Claude GEO) covered by one Seed client. Claude GEO ($71/mo) is optional and can be disabled immediately.
