# AWS Infrastructure Budget — RAMP Platform

**Date:** May 6, 2026  
**Architecture:** EC2 + SQS + ElastiCache Serverless Valkey + PostgreSQL (Docker)  
**Region:** us-east-1 (N. Virginia)

---

## Target Architecture

```
┌─────────────────────────────────────────────────────────┐
│  EC2 t3.small (2 vCPU, 2 GB RAM)                       │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ FastAPI App  │  │ SQS Workers  │  │ PostgreSQL    │  │
│  │ (Uvicorn)   │  │ (asyncio)    │  │ (Docker)      │  │
│  └──────┬──────┘  └──────┬───────┘  └───────────────┘  │
└─────────┼────────────────┼──────────────────────────────┘
          │                │
          ▼                ▼
┌──────────────────┐  ┌─────────────────────────────────┐
│  AWS SQS         │  │  ElastiCache Serverless Valkey   │
│  (Standard)      │  │  (locks, rate limiter, results)  │
│  - Task queues   │  │  - Distributed locks (SETNX)     │
│  - DLQ per queue │  │  - Rate limiter (sorted set)     │
│  - 14-day retain │  │  - Task results (TTL 5 min)      │
└──────────────────┘  └─────────────────────────────────┘
```

---

## Decision Rationale

| Decision | Why |
|----------|-----|
| SQS over Celery+Redis | Native DLQ, 14-day message persistence, visibility timeout, CloudWatch metrics, no broker management |
| Valkey Serverless over Redis Docker | Managed HA (multi-AZ), auto-scaling, no ops overhead, 33% cheaper than Redis OSS Serverless |
| EC2 over ECS/Fargate | Simpler, cheaper for single-instance. Docker Compose for local dev parity |
| PostgreSQL on EC2 Docker (initial) | $0 cost. Migrate to RDS when data loss risk is unacceptable (5+ clients) |

---

## Monthly Cost Breakdown (10 clients, 50 avatars, 500 subreddits)

### Compute — EC2

| Component | Spec | Cost/mo |
|-----------|------|---------|
| EC2 t3.small (On-Demand) | 2 vCPU, 2 GB RAM | $15.18 |
| EBS gp3 (20 GB) | Boot volume + PostgreSQL data | $1.60 |
| Elastic IP | Static public IP | $3.65 |
| **Subtotal** | | **$20.43** |

### Task Queue — AWS SQS

| Metric | Value |
|--------|-------|
| Tasks/day | ~17,430 |
| SQS requests/day (Send+Receive+Delete+Poll) | ~58,000 |
| Requests/month | ~1.74M |
| Free tier deduction | -1M |
| Billable requests | 0.74M |
| **Cost (Standard @ $0.40/M)** | **$0.30** |

#### SQS Request Breakdown

| Source | Tasks/day | SQS Requests/day |
|--------|-----------|-----------------|
| queue_tick (every 60s) | 1,440 | 4,320 |
| Scrape tasks (~30/min peak) | ~14,400 | 43,200 |
| AI pipeline (score + generate) | ~100 | 300 |
| Heartbeat | 1,440 | 4,320 |
| Phase evaluation | ~50 | 150 |
| Worker polling (long poll, 4 workers) | — | 5,760 |
| **Total** | **~17,430** | **~58,050** |

### Cache/Locks — ElastiCache Serverless Valkey

| Metric | Value |
|--------|-------|
| Data stored | ~1-5 MB actual (100 MB minimum) |
| Storage cost | 0.1 GB × 730 hrs × $0.084/GB-hr = $6.13 |
| ECPUs/day | ~73,840 |
| ECPUs/month | ~2.2M |
| ECPU cost | 2.2M / 1M × $0.0023 = $0.005 |
| **Subtotal** | **$6.14** |

#### Valkey ECPU Breakdown

| Operation | Commands/day | ECPUs/day |
|-----------|-------------|-----------|
| Rate limiter (ZADD, ZCARD, ZREMRANGEBYSCORE) | ~4,320 | ~4,320 |
| Distributed locks (SET NX, Lua GET+DEL) | ~28,800 | ~28,800 |
| Phase locks | ~100 | ~100 |
| Tick gating (GET, SET) | ~2,880 | ~2,880 |
| Heartbeat (PING, INFO) | ~2,880 | ~2,880 |
| Task results (SET, GET with TTL) | ~34,860 | ~34,860 |
| **Total** | **~73,840** | **~73,840** |

### Database — PostgreSQL

| Component | Spec | Cost/mo |
|-----------|------|---------|
| PostgreSQL 16 (Docker on EC2) | Shared EC2 resources | $0 |
| Daily pg_dump to S3 (optional) | ~100 MB compressed | ~$0.02 |
| **Subtotal** | | **$0.02** |

### Data Transfer

| Type | Cost |
|------|------|
| EC2 ↔ SQS (same region) | $0 |
| EC2 ↔ Valkey (same AZ) | $0 |
| Internet egress (admin UI, <1 GB) | $0 (first 100 GB free) |
| **Subtotal** | **$0** |

---

## Total Monthly Budget

| Service | Cost/mo |
|---------|---------|
| EC2 t3.small + EBS + EIP | $20.43 |
| AWS SQS Standard | $0.30 |
| ElastiCache Serverless Valkey | $6.14 |
| PostgreSQL (Docker) | $0.02 |
| Data transfer | $0 |
| **TOTAL** | **$26.89/mo** |

---

## Scaling Projections

| Scale | Clients | SQS | Valkey | EC2 | Total/mo |
|-------|---------|-----|--------|-----|----------|
| Pilot | 1-3 | $0 (free tier) | $6.14 | $20.43 | **~$27** |
| Growth | 10 | $0.30 | $6.14 | $20.43 | **~$27** |
| Traction | 50 | $2.80 | $6.15 | $20.43 | **~$30** |
| Scale | 100 | $5.60 | $6.20 | $35* | **~$47** |
| Agency | 500 | $27.60 | $7.00 | $70** | **~$105** |

*t3.medium ($30/mo) needed at 100 clients  
**t3.large or 2× t3.small at 500 clients

---

## Cost Optimization Options

| Option | Savings | Trade-off |
|--------|---------|-----------|
| EC2 Reserved Instance (1yr, no upfront) | ~31% on EC2 ($10.43 vs $15.18) | 1-year commitment |
| EC2 Spot for workers (if separated) | ~57% on worker instance | Can be interrupted |
| SQS batching (10 messages per request) | Up to 10× fewer requests | Slight latency increase |
| Valkey: reduce result TTL to 1 min | Fewer stored keys | Results expire faster |

### With Reserved Instance (1yr)

| Service | Cost/mo |
|---------|---------|
| EC2 t3.small Reserved | $10.43 |
| EBS + EIP | $5.25 |
| SQS | $0.30 |
| Valkey Serverless | $6.14 |
| **TOTAL (optimized)** | **$22.12/mo** |

---

## Migration Path: When to Upgrade

| Trigger | Action | New Cost |
|---------|--------|----------|
| 5+ clients, data loss unacceptable | PostgreSQL → RDS db.t4g.small | +$24/mo |
| 100+ clients, EC2 CPU saturated | t3.small → t3.medium | +$15/mo |
| Need HA for app | Add second EC2 + ALB | +$35/mo |
| 500+ clients | Separate worker instances | +$50/mo |

---

## Comparison: Old Architecture vs New

| Metric | Old (Celery+Redis Docker) | New (SQS+Valkey) |
|--------|--------------------------|-------------------|
| Monthly cost | ~$20 (EC2 only) | ~$27 |
| DLQ (failed tasks) | ❌ Lost | ✅ Automatic |
| Message persistence | ❌ RAM only | ✅ 14 days (SQS) |
| High availability | ❌ Single point of failure | ✅ Multi-AZ (Valkey) |
| Observability | ❌ No metrics | ✅ CloudWatch free |
| Ops overhead | ⚠️ Monitor Redis, restart on OOM | ✅ Zero (managed) |
| Visibility timeout | ❌ None | ✅ Configurable |
| Retry policy | ❌ Manual | ✅ Built-in (maxReceiveCount) |
| Latency | ~1ms (Redis) | ~20-50ms (SQS) |

**Net cost of reliability: +$7/mo** — worth it for production.

---

## SQS Queue Design

| Queue | Purpose | Visibility Timeout | DLQ Max Receives |
|-------|---------|-------------------|-----------------|
| `ramp-scrape` | Subreddit scraping tasks | 300s (5 min) | 3 |
| `ramp-ai` | Scoring + generation tasks | 600s (10 min) | 3 |
| `ramp-health` | Heartbeat + phase evaluation | 60s | 5 |
| `ramp-dlq` | Dead letter (all failed tasks) | — | — |

---

## Valkey Key Design

| Key Pattern | Type | TTL | Purpose |
|-------------|------|-----|---------|
| `scrape_lock:r/{subreddit}` | String | 300s | Prevent concurrent scrapes |
| `phase_lock:{avatar_id}` | String | 30s | Prevent concurrent transitions |
| `rate_limiter:scrape` | Sorted Set | 120s | Reddit API sliding window |
| `rate_limiter:backoff` | String | 300s | Backoff flag on 429 |
| `queue_tick:last_run` | String | 120s | Tick interval gating |
| `task_result:{task_id}` | String | 300s | Task execution results |

---

## Annual Budget Summary

| Scenario | Monthly | Annual |
|----------|---------|--------|
| Pilot (1-3 clients, On-Demand) | $27 | **$324** |
| Pilot (Reserved Instance) | $22 | **$264** |
| Growth (10 clients) | $27 | **$324** |
| Scale (100 clients) | $47 | **$564** |

---

*Document created: May 6, 2026*  
*Next review: When reaching 10 clients or before adding RDS*
