# AWS Cost Estimate — RAMP Platform

**Updated:** May 6, 2026  
**Architecture:** EC2 + AWS SQS + ElastiCache Serverless Valkey  
**Region:** us-east-1 (N. Virginia)

> **Architecture Decision:** Migrating from Celery+Redis to SQS+Valkey Serverless.  
> See `docs/adr_sqs_valkey_migration.md` for rationale.  
> See `docs/aws_budget_may2026.md` for detailed breakdown with ECPU/request calculations.

---

## MVP Setup (1–3 clients)

| Service | Spec | $/month |
|---------|------|---------|
| **EC2** (app + SQS workers + PostgreSQL Docker) | t3.small (2 vCPU, 2 GB RAM) | **$15.18** |
| **EBS** (boot + PostgreSQL data) | 20 GB gp3 | **$1.60** |
| **Elastic IP** | 1 static IP | **$3.65** |
| **AWS SQS** (task queue) | ~1.74M requests/mo (1M free tier) | **$0.30** |
| **ElastiCache Serverless Valkey** (locks, rate limiter) | 100 MB min + ~2.2M ECPUs/mo | **$6.14** |
| **S3** (pg_dump backups, optional) | ~100 MB/mo | **$0.02** |
| **CloudWatch** (SQS + Valkey metrics) | Basic (free tier) | **$0** |
| | | |
| **Total MVP** | | **~$27/mo** |

---

## Growth Setup (10–50 clients)

| Service | Spec | $/month |
|---------|------|---------|
| **EC2** | t3.small (sufficient up to ~50 clients) | **$15.18** |
| **EBS** | 30 GB gp3 | **$2.40** |
| **Elastic IP** | 1 static IP | **$3.65** |
| **AWS SQS** | ~5-8M requests/mo | **$1.60–$2.80** |
| **ElastiCache Serverless Valkey** | 100 MB + ~10M ECPUs/mo | **$6.16** |
| **RDS PostgreSQL** (upgrade from Docker) | db.t4g.small (2 vCPU, 2 GB RAM) | **$24.00** |
| **S3** (backups) | ~500 MB/mo | **$0.05** |
| | | |
| **Total Growth** | | **~$54/mo** |

---

## Scale Setup (100+ clients)

| Service | Spec | $/month |
|---------|------|---------|
| **EC2** (app) | t3.medium (2 vCPU, 4 GB RAM) | **$30.37** |
| **EC2** (workers, optional) | t3.small | **$15.18** |
| **EBS** | 50 GB gp3 (×2 instances) | **$4.00** |
| **Elastic IP** | 1 (behind ALB) | **$3.65** |
| **AWS SQS** | ~15M requests/mo | **$5.60** |
| **ElastiCache Serverless Valkey** | ~200 MB + ~50M ECPUs/mo | **$6.50** |
| **RDS PostgreSQL** | db.t4g.small Multi-AZ | **$48.00** |
| **ALB** (optional, for HA) | Application Load Balancer | **$16.20** |
| | | |
| **Total Scale** | | **~$130/mo** |

---

## Annual Projection

| Phase | Monthly | Annual |
|-------|---------|--------|
| MVP — Pilot (months 1–6) | $27 | $162 |
| Growth (months 7–12) | $54 | $324 |
| **Year 1 Total** | | **~$486** |

---

## Cost Comparison: Old vs New Architecture

| Setup | Old (Celery+Redis+RDS) | New (SQS+Valkey+Docker PG) | Savings |
|-------|------------------------|---------------------------|---------|
| MVP | $46/mo | $27/mo | **-41%** |
| Growth | $78/mo | $54/mo | **-31%** |

The new architecture is cheaper because:
1. PostgreSQL runs in Docker on EC2 (no RDS cost at MVP stage)
2. Valkey Serverless ($6) is cheaper than ElastiCache node ($12)
3. SQS ($0.30) is essentially free vs provisioned Redis

---

## What's Free on AWS

- **CloudWatch** (basic metrics for SQS, Valkey, EC2) — free tier
- **SQS** (first 1M requests/month) — free tier
- **IAM** — free
- **S3** (5 GB free tier first year) — free
- **SNS** (1M notifications free) — for DLQ alerting
- **ACM** (SSL certificates) — free
- **EventBridge Scheduler** (first 14M invocations/mo) — free

---

## Reserved Instance Savings

| Option | EC2 Cost/mo | Total/mo | vs On-Demand |
|--------|-------------|----------|-------------|
| On-Demand | $15.18 | $27 | baseline |
| Reserved 1yr (no upfront) | $10.43 | $22 | -19% |
| Reserved 1yr (all upfront) | $9.13 | $21 | -22% |

---

## Upgrade Triggers

| Trigger | Action | Cost Impact |
|---------|--------|-------------|
| Data loss unacceptable (5+ clients) | Docker PG → RDS db.t4g.small | +$24/mo |
| EC2 CPU > 80% sustained | t3.small → t3.medium | +$15/mo |
| Need zero-downtime deploys | Add ALB + 2nd EC2 | +$35/mo |
| 500+ clients | Separate worker EC2 instances | +$50/mo |

---

## SQS Queue Architecture

| Queue Name | Purpose | Visibility Timeout | DLQ |
|------------|---------|-------------------|-----|
| `ramp-scrape` | Subreddit scraping | 300s | `ramp-scrape-dlq` (3 retries) |
| `ramp-ai` | Scoring + generation | 600s | `ramp-ai-dlq` (3 retries) |
| `ramp-health` | Heartbeat + phases | 60s | `ramp-health-dlq` (5 retries) |

---

## Valkey Key Budget

| Key Pattern | Count (10 clients) | Memory |
|-------------|-------------------|--------|
| Distributed locks | ~500 (1 per subreddit) | <500 KB |
| Rate limiter | 1 sorted set | <10 KB |
| Phase locks | ~50 (1 per avatar) | <50 KB |
| Task results | ~1,000 (with 5-min TTL) | ~5 MB |
| **Total** | | **<6 MB** |

Minimum billed: 100 MB ($6.13/mo floor regardless of actual usage).

---

## Credit Usage (if available)

| Credits | Covers |
|---------|--------|
| $500 | ~18 months of MVP |
| $1,000 | ~18 months of Growth |
| $2,000 | ~3 years of full operation |

---

*Previous version of this document used Celery+Redis+RDS architecture ($46/mo MVP).  
Updated May 6, 2026 to reflect SQS+Valkey Serverless decision.*
