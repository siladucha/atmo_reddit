---
inclusion: manual
---

# Load Dynamics & AWS Cost Impact — Per Node Analysis

## Overview

This document maps the dynamic load profile of each system node to its AWS cost impact.
It answers: "what happens to my AWS bill when load changes on each node?"

---

## System Nodes — Load Profile

### 1. Scraping Node

**Trigger:** `queue_tick` fires every 60s, checks which subreddits are due for scraping.

**Load formula:**
```
scrapes/day = active_subreddits × (24h / scrape_interval_hours)
```

**Current baseline (10 clients, 50 subreddits, 6h interval):**
- 50 × 4 = **200 scrapes/day**
- Each scrape: 1 PRAW API call (25 posts), ~2-5s duration
- Reddit API rate: 60 req/min per account (shared across all scrapes)

**Scaling:**
| Clients | Subreddits | Scrapes/day | Reddit API calls/day |
|---------|-----------|-------------|---------------------|
| 3 | 15 | 60 | 60 |
| 10 | 50 | 200 | 200 |
| 50 | 250 | 1,000 | 1,000 |
| 100 | 500 | 2,000 | 2,000 |

**AWS cost impact:**
- SQS: 1 send + 1 receive + 1 delete = 3 requests per scrape
- 200 scrapes/day × 3 = 600 SQS requests/day = **18,000/month** (~$0.007)
- Valkey: 1 lock acquire + 1 lock release + 1 rate limiter check = 3 commands per scrape
- 200 × 3 = 600 ECPUs/day = **18,000/month** (~$0.00004)
- **Scraping is essentially free on AWS.** The bottleneck is Reddit API rate limits, not cost.

**Cost driver:** EC2 CPU time (PRAW is synchronous, blocks worker thread during scrape)

---

### 2. Scoring Node

**Trigger:** After scraping completes, or on schedule (8:00, 14:00 UTC).

**Load formula:**
```
scoring_calls/day = new_threads_per_scrape × scrapes/day × scoring_ratio
```

**Current baseline:**
- ~200 new threads/day (across all subreddits)
- Each scoring call: Gemini Flash, ~4,000 input tokens, ~200 output tokens
- Duration: ~1-2s per thread

**Scaling:**
| Clients | New threads/day | Scoring calls/day | Gemini Flash cost/day |
|---------|----------------|-------------------|----------------------|
| 3 | 60 | 60 | $0.02 |
| 10 | 200 | 200 | $0.06 |
| 50 | 1,000 | 1,000 | $0.30 |
| 100 | 2,000 | 2,000 | $0.60 |

**AWS cost impact:**
- SQS: 1 message per scoring batch (per client) = 10 messages/day = **300/month** (~$0)
- Valkey: task result storage (1 SET + 1 GET per batch) = 20 ECPUs/day = **600/month** (~$0)
- **LLM API (external):** $0.06/day at 10 clients = **$1.80/month**
- **This is the cheapest AI node.** Gemini Flash is 40x cheaper than Claude.

**Cost driver:** LLM API cost (Gemini Flash), not AWS infrastructure.

**NOTE (June 2026):** Smart Scoring (`smart_scoring.py`) reduces scoring calls by ~90% — only `remaining_budget × 3` threads scored per avatar (HARD_CAP=15), not all unscored threads.

---

### 3. Generation Node

**Trigger:** After scoring, for threads tagged "engage".

**Load formula:**
```
generations/day = engage_threads/day × (1 + redraft_ratio)
```

**Current baseline:**
- ~15 "engage" threads/day per client (top 7-8% of scored threads)
- Each generation: Claude Sonnet, ~12,000 input + ~200 output tokens
- Duration: ~3-5s per comment

**Scaling:**
| Clients | Engage threads/day | Generations/day | Claude Sonnet cost/day |
|---------|-------------------|-----------------|----------------------|
| 3 | 45 | 45 | $1.62 |
| 10 | 150 | 150 | $5.40 |
| 50 | 750 | 750 | $27.00 |
| 100 | 1,500 | 1,500 | $54.00 |

**AWS cost impact:**
- SQS: 1 message per generation = 150/day = **4,500/month** (~$0.002)
- Valkey: 1 lock + 1 result = 300 ECPUs/day = **9,000/month** (~$0.00002)
- **LLM API (external):** $5.40/day at 10 clients = **$162/month**
- **This is the most expensive node.** Claude Sonnet dominates total cost.

**Cost driver:** LLM API cost (Claude Sonnet). AWS infra is negligible.

---

### 4. Review Queue Node

**Trigger:** Human-driven (no automated load).

**Load formula:**
```
reviews/day = generations/day (all generated comments enter review)
pending_queue_depth = generations/day × avg_review_latency_hours / 24
```

**Current baseline:**
- ~150 drafts/day enter review (10 clients)
- Average review latency: 4-8 hours
- Queue depth: 25-50 pending items at any time

**AWS cost impact:**
- SQS: 0 (review is synchronous HTTP, not queued)
- Valkey: 0
- EC2: Minimal (FastAPI serves review UI, <1% CPU)
- **Zero marginal AWS cost.** This node is human-bottlenecked.

**Cost driver:** Human time (operator reviewing drafts). Not AWS.

---

### 5. Reddit API Node

**Trigger:** Scraping (PRAW calls) + health checks (shadowban detection).

**Load formula:**
```
reddit_api_calls/day = scrapes/day + health_checks/day
health_checks/day = active_avatars × (24h / health_check_interval)
```

**Current baseline:**
- 200 scrapes/day + 100 health checks/day = **300 Reddit API calls/day**
- Reddit rate limit: 60 req/min per OAuth token
- With 1 token: max 86,400 calls/day (well within limits)

**Scaling concern:**
| Clients | Avatars | API calls/day | Tokens needed |
|---------|---------|---------------|---------------|
| 10 | 50 | 300 | 1 |
| 50 | 250 | 1,500 | 1 |
| 100 | 500 | 3,000 | 1 |
| 500 | 2,500 | 15,000 | 1 (still fine) |

**AWS cost impact:** $0 (Reddit API is free, calls go from EC2 to Reddit directly)

**Cost driver:** Risk of rate limiting / IP bans at high volume. May need proxy rotation at 500+ clients.

---

### 6. LLM API Node

**Trigger:** Scoring (Gemini Flash) + Generation (Claude Sonnet) + Persona Selection + Editing.

**Combined load formula:**
```
total_llm_cost/day = scoring_cost + generation_cost + persona_cost + editing_cost
```

**Full pipeline cost per client per day:**
| Operation | Model | Calls/day | Cost/call | Cost/day |
|-----------|-------|-----------|-----------|----------|
| Scoring | Gemini Flash | 20 | $0.0003 | $0.006 |
| Persona Selection | Claude Sonnet | 15 | $0.020 | $0.30 |
| Comment Generation | Claude Sonnet | 15 | $0.039 | $0.59 |
| Comment Editor | Claude Sonnet | 15 | $0.018 | $0.27 |
| Hobby Comments | Gemini Flash | 15 | $0.0003 | $0.005 |
| GEO/AEO Monitoring | Perplexity Sonar + Claude Sonnet (web search) + OpenAI Search | 60/batch × N providers (40-120 queries) | $0.006-0.08/query | $0.15-0.50/batch, ~2 batches/week |
| **Total per client** | | | | **$1.17/day** |

**Monthly LLM cost scaling:**
| Clients | LLM cost/month | % of total infra |
|---------|---------------|-----------------|
| 3 | $105 | 80% |
| 10 | $351 | 93% |
| 50 | $1,755 | 97% |
| 100 | $3,510 | 98% |

**AWS cost impact:** $0 (LLM APIs are external — OpenRouter/Anthropic/Google direct)

**Key insight:** LLM API is 93%+ of total operational cost at 10 clients. AWS infra is noise.

---

### 7. Database Node

**Trigger:** Every operation reads/writes PostgreSQL.

**Load formula:**
```
queries/day ≈ scrapes × 30 + scoring × 5 + generation × 10 + reviews × 5 + admin_ui × 100
```

**Current baseline (10 clients):**
- ~200 × 30 + 200 × 5 + 150 × 10 + 150 × 5 + 100 = **9,350 queries/day**
- PostgreSQL on Docker (EC2): 0 marginal cost
- Connection pool: 10 connections (SQLAlchemy default)

**When to upgrade to RDS:**
| Trigger | Threshold | Action | Cost impact |
|---------|-----------|--------|-------------|
| Data loss risk | 5+ paying clients | Docker PG → RDS db.t4g.small | +$24/mo |
| Connection exhaustion | 50+ clients | RDS db.t4g.medium | +$48/mo |
| Read replicas needed | 100+ clients | RDS Multi-AZ | +$48/mo |

**AWS cost impact (current):** $0 (Docker on EC2)
**AWS cost impact (RDS):** $24-96/mo depending on scale

---

### 8. Task Queue Node (SQS)

**Trigger:** Every task produces SQS messages.

**Load formula:**
```
sqs_requests/day = (tasks/day × 3) + (worker_polls/day) + (dlq_checks)
```

**Breakdown at 10 clients:**
| Source | Messages/day | SQS Requests/day |
|--------|-------------|-----------------|
| queue_tick (every 60s) | 1,440 | 4,320 (send+receive+delete) |
| Scrape tasks | 200 | 600 |
| AI pipeline (score+generate) | 20 | 60 |
| Health checks | 2 | 6 |
| Worker long-poll (4 workers × 20s) | — | 5,760 (empty receives) |
| **Total** | **~1,662** | **~10,746** |

**Monthly:** ~322,380 requests → **free tier covers it** (1M free/month)

**Scaling:**
| Clients | SQS requests/month | Cost/month |
|---------|-------------------|-----------|
| 10 | 322K | $0 (free tier) |
| 50 | 1.6M | $0.24 |
| 100 | 3.2M | $0.88 |
| 500 | 16M | $6.00 |

**Key insight:** SQS is essentially free at any realistic scale. Even at 500 clients = $6/mo.

---

### 9. Cache/Locks Node (Valkey)

**Trigger:** Every scrape needs a lock, every task stores a result.

**Load formula:**
```
ecpus/day = locks × 2 + rate_limiter × 3 + results × 2 + heartbeat × 2
```

**Breakdown at 10 clients:**
| Operation | Commands/day | ECPUs/day |
|-----------|-------------|-----------|
| Scrape locks (SET NX + DEL) | 400 | 400 |
| Rate limiter (ZADD + ZCARD + ZREM) | 600 | 600 |
| Task results (SET + GET) | 3,324 | 3,324 |
| Heartbeat (PING) | 1,440 | 1,440 |
| Tick gating (GET + SET) | 2,880 | 2,880 |
| **Total** | **~8,644** | **~8,644** |

**Monthly:** ~259,320 ECPUs

**Cost:** Dominated by **storage floor** ($6.13/mo for 100 MB minimum), not by ECPUs.

**Scaling:**
| Clients | ECPUs/month | Storage | Cost/month |
|---------|------------|---------|-----------|
| 10 | 259K | <5 MB | $6.14 (floor) |
| 50 | 1.3M | <20 MB | $6.14 (floor) |
| 100 | 2.6M | <50 MB | $6.14 (floor) |
| 500 | 13M | ~150 MB | $9.50 |

**Key insight:** Valkey cost is flat at $6.14/mo until you exceed 100 MB storage. That won't happen until 500+ clients.

---

## Cost Summary by Node (Updated July 8, 2026 — post-optimization)

### At 10 Clients (target)

| Node | AWS Cost/mo | LLM Cost/mo | Total/mo | % of total |
|------|------------|------------|---------|-----------|
| Scraping | $0.01 | — | $0.01 | 0% |
| Scoring | $0.00 | $4.20 | $4.20 | 2% |
| Generation (Sonnet) | $0.00 | $81.90 | $81.90 | 42% |
| Editing (Gemini Flash) | $0.00 | $0.80 | $0.80 | 0.4% |
| Persona Selection (Gemini Flash) | $0.00 | $4.20 | $4.20 | 2% |
| Hobby Comments (Gemini Flash) | $0.00 | $0.20 | $0.20 | 0.1% |
| GEO/AEO (Perplexity) | $0.00 | $10.80 | $10.80 | 6% |
| Client Portal Actions | $0.00 | $2.50 | $2.50 | 1% |
| Review Queue | $0.00 | — | $0.00 | 0% |
| Reddit API | $0.00 | — | $0.00 | 0% |
| Database (Docker) | $0.00 | — | $0.00 | 0% |
| Task Queue (SQS/Redis) | $0.00 | — | $0.00 | 0% |
| Cache (Redis) | $0.00 | — | $0.00 | 0% |
| Compute (DO Droplet) | $23.00 | — | $23.00 | 12% |
| Intelligence (weekly batches) | $0.00 | $1.00 | $1.00 | 0.5% |
| **TOTAL (10 clients × 2 avatars)** | **$23.01** | **$105.60** | **$192.01** | **100%** |

### Cost Distribution (post-optimization)

```
LLM APIs:                          88%  ███████████████████████████████████████
  └─ Claude Sonnet (generation):   42%  ████████████████
  └─ Gemini Flash (scoring+edit):   5%  ██
  └─ Perplexity (GEO):              6%  ██
  └─ Other:                         1%  ░
AWS/Infra (DO Droplet):            12%  █████
```

### Forecast: Cost at Scale (post-optimization)

| Clients | Avatars | LLM/mo | Infra/mo | Total/mo | Revenue/mo | Margin |
|---------|---------|--------|----------|----------|------------|--------|
| 1 | 1 | $10 | $23 | $33 | $149 | 78% |
| 5 | 10 | $96 | $23 | $119 | $1,995 | 94% |
| 10 | 20 | $192 | $23 | $215 | $3,990 | 95% |
| 50 | 100 | $960 | $38* | $998 | $39,950 | 97% |
| 100 | 200 | $1,920 | $130** | $2,050 | $79,900 | 97% |

*Managed DB at 50 clients. **EC2 upgrade at 100 clients.

**Key insight (post-optimization):** Generation (Claude Sonnet) is 85% of LLM cost. Everything else moved to free/near-free Gemini. Margins stay 94%+ from 5 clients onwards.

---

## Load Dynamics — Time Patterns

### Daily Load Profile (UTC)

```
Hour  | Scraping | Scoring | Generation | Review
------+----------+---------+------------+--------
00-06 | ████     | ░       | ░          | ░       (scraping runs continuously)
05:20 | ████     | ░       | ░          | ░       (profile analytics snapshots)
06:00 | ████     | ░       | ░          | ░       (phase evaluation fires)
06:30 | ████     | ░       | ░          | ░       (CQS batch check — Reddit API)
07:30 | ████     | ░       | ░          | ░       (health check — shadowban/suspension)
08:00 | ████     | ████████| ████████   | ░       (AI pipeline morning run)
09-13 | ████     | ░       | ░          | ████████ (human review window)
10:00 | ████     | ░       | ████       | ████████ (hobby pipeline)
14:00 | ████     | ████████| ████████   | ████████ (AI pipeline afternoon run)
15-20 | ████     | ░       | ░          | ████████ (human review window)
20-24 | ████     | ░       | ░          | ░       (scraping continues)
```

### Peak Load Windows

| Window | Nodes Active | EC2 CPU Impact | LLM API Burst |
|--------|-------------|---------------|---------------|
| 08:00-08:30 | Scrape + Score + Generate | 60-80% | 150 calls in 30 min |
| 14:00-14:30 | Scrape + Score + Generate | 60-80% | 150 calls in 30 min |
| 10:00-10:15 | Hobby scrape + generate | 30-40% | 50 calls in 15 min |

### Scraping is Continuous, AI is Bursty

- **Scraping:** Steady ~8 scrapes/hour (queue_tick every 60s, gates by interval)
- **Scoring + Generation:** Burst at 08:00 and 14:00 (all clients processed in batch)
- **Review:** Depends on human availability (typically 09:00-20:00 local time)

---

## Cost Optimization Priorities

### High Impact (saves $100+/mo at 10 clients)

1. ~~**Batch scoring calls**~~ → **DONE** (Smart Scoring: budget-aware, only N threads per avatar, 90% reduction)
2. **Replace Claude Sonnet with Claude Haiku for editing** — editing is simple cleanup, doesn't need Sonnet quality. Saves ~$70/mo.
3. **Skip persona selection for single-avatar clients** — if client has 1 avatar, no routing needed. Saves ~$30/mo per such client.

### Medium Impact (saves $10-50/mo)

4. **Cache voice profiles in prompt** — don't re-fetch from DB on every generation call.
5. **Reduce generation context** — trim thread body to 500 tokens max (currently sends full body).
6. **Use Gemini Flash for hobby comments** — already doing this, good.

### Low Impact (saves <$10/mo)

7. **SQS message batching** — send 10 messages per request. Saves ~$0.20/mo.
8. **Reduce Valkey TTL** — task results from 5 min to 1 min. Saves ~$0.001/mo.
9. **EC2 Reserved Instance** — saves $5/mo. Worth it after 6 months of stable usage.

---

## Forecast: Cost at Scale

| Clients | AWS Infra/mo | LLM API/mo | Total/mo | Revenue/mo (avg $500/client) | Margin |
|---------|-------------|-----------|---------|------------------------------|--------|
| 3 | $27 | $105 | $132 | $1,500 | 91% |
| 10 | $27 | $351 | $378 | $5,000 | 92% |
| 50 | $54 | $1,755 | $1,809 | $25,000 | 93% |
| 100 | $130 | $3,510 | $3,640 | $50,000 | 93% |

**Key insight:** Margins stay above 90% at all scales. LLM costs scale linearly with clients, but so does revenue. AWS infra is sub-linear (shared resources).

---

## Dashboard Implications for System Topology

The topology timeline should visualize:

1. **Load intensity per node** — color intensity based on operations/hour
2. **Cost attribution** — hover shows estimated cost contribution
3. **Burst detection** — highlight when multiple nodes fire simultaneously
4. **Forecast accuracy** — show if actual execution matches expected schedule
5. **Stale detection** — if a node hasn't fired when expected, mark as warning

### Recommended Metrics per Node (for dashboard)

| Node | Primary Metric | Secondary Metric | Alert Threshold |
|------|---------------|-----------------|-----------------|
| Scraping | scrapes/hour | avg duration_ms | > 10s or 0 for 2h |
| Scoring | threads scored/hour | avg score | 0 for 4h after scrape |
| Generation | drafts created/hour | avg tokens used | 0 for 4h after scoring |
| Review | pending queue depth | avg review latency | > 50 pending or > 24h oldest |
| Reddit API | calls/hour | error rate % | > 5% errors or 429 received |
| LLM API | calls/hour | cost/hour | > $5/hour or > 10% error rate |
| Database | queries/sec | connection pool usage | > 80% pool or > 100ms avg |
| Queue (SQS) | messages in flight | DLQ depth | DLQ > 0 or depth > 100 |
| Cache (Valkey) | commands/sec | memory usage | > 80 MB or connection errors |
