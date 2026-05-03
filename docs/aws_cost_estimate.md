# AWS Cost Estimate — Reddit Marketing SaaS

Region: eu-west-1 (Ireland) or il-central-1 (Tel Aviv)

## MVP Setup (1–3 clients)

| Service | Spec | $/hour | $/month |
|---------|------|--------|---------|
| **EC2** (app + Celery worker) | t3.small (2 vCPU, 2GB RAM) | $0.021 | **$15** |
| **RDS PostgreSQL** | db.t3.micro (2 vCPU, 1GB RAM, 20GB SSD) | $0.018 | **$13** |
| **ElastiCache Redis** | cache.t3.micro (1 vCPU, 0.5GB) | $0.017 | **$12** |
| **EBS** (EC2 storage) | 30GB gp3 | — | **$2.40** |
| **RDS Storage** | 20GB gp3 | — | **$2.30** |
| **Data Transfer** | ~5GB/mo outbound (minimal) | — | **$0.45** |
| **Route 53** (DNS) | 1 hosted zone | — | **$0.50** |
| **ACM** (SSL cert) | Free | — | **$0** |
| | | | |
| **Total MVP** | | | **~$46/mo** |

## Growth Setup (5–10 clients)

| Service | Spec | $/month |
|---------|------|---------|
| **EC2** | t3.medium (2 vCPU, 4GB RAM) | **$30** |
| **RDS PostgreSQL** | db.t3.small (2 vCPU, 2GB RAM, 50GB) | **$26** |
| **ElastiCache Redis** | cache.t3.micro | **$12** |
| **EBS + RDS Storage** | 50GB + 50GB gp3 | **$8** |
| **Data Transfer** | ~20GB/mo | **$1.80** |
| **Route 53 + ACM** | | **$0.50** |
| | | |
| **Total Growth** | | **~$78/mo** |

## Annual Projection

| Phase | Monthly | Annual |
|-------|---------|--------|
| MVP (months 1–6) | $46 | $276 |
| Growth (months 7–12) | $78 | $468 |
| **Year 1 Total** | | **~$744** |

## What's Free on AWS

- **ACM** (SSL certificates) — free
- **CloudWatch** (basic monitoring) — free tier
- **IAM** — free
- **S3** (5GB free tier first year) — free
- **SNS** (1M notifications free) — free

## Comparison

| | AWS | VPS (Hetzner) |
|---|---|---|
| MVP monthly | $46 | $15–20 |
| Growth monthly | $78 | $30–40 |
| Managed DB backups | ✅ Auto | Manual |
| Scaling | Easy | Manual migration |
| **With free credits** | **$0** | $15–20 |

## Credit Usage

| Credits available | Covers |
|-------------------|--------|
| $1,000 | ~21 months of MVP |
| $2,000 | ~12 months of Growth setup |
| $5,000 | ~2 years of full operation |
| $10,000 | ~3+ years, room for experiments |

## Recommended Setup for Day 1

```
EC2 t3.small          → App (FastAPI + Celery worker)
RDS db.t3.micro       → PostgreSQL
ElastiCache t3.micro  → Redis
```

Total: ~$46/mo, fully covered by credits.

Upgrade to t3.medium + db.t3.small when you hit 5+ clients.
