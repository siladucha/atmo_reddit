# AWS Migration Checklist

## Pre-Migration (Before You Start)

### Code Readiness

- [ ] All config via environment variables (no hardcoded URLs)
- [ ] Health endpoint returns JSON with DB + Redis status (`GET /health`)
- [ ] App is stateless (no local file writes, no in-memory sessions)
- [ ] Dockerfile builds cleanly (`docker build -t reddit-saas .`)
- [ ] `pre_deploy_check.py` passes all checks
- [ ] Graceful shutdown handles SIGTERM (Celery + uvicorn)
- [ ] Database migrations are idempotent (`alembic upgrade head` safe to re-run)
- [ ] `.env.production` prepared with all required variables
- [ ] Secrets identified and ready for AWS Secrets Manager / Parameter Store

### Data Inventory

- [ ] Current database size measured (`pg_database_size`)
- [ ] Number of tables and row counts documented
- [ ] Redis data volume measured (keys count, memory usage)
- [ ] Identify data that can be dropped before migration (old scrape logs, etc.)

### DNS & Domain

- [ ] Domain registered and accessible
- [ ] Current DNS provider identified
- [ ] SSL certificate strategy decided (ACM recommended)
- [ ] TTL lowered to 60s on DNS records (48h before migration)

---

## Phase 1: AWS Account Setup (Day 1)

### Account & IAM

- [ ] AWS account created (or existing account confirmed)
- [ ] MFA enabled on root account
- [ ] IAM admin user created (not using root)
- [ ] AWS CLI configured locally (`aws configure`)
- [ ] Budget alert set ($50/mo warning, $100/mo critical)
- [ ] AWS credits applied to account ($7K available)

### Networking (VPC)

- [ ] VPC created (10.0.0.0/16)
- [ ] 2 public subnets (for ALB) in different AZs
- [ ] 2 private subnets (for ECS, RDS, Redis) in different AZs
- [ ] NAT Gateway created (for private subnet internet access)
- [ ] Security groups defined:
  - [ ] `sg-alb`: inbound 80, 443 from 0.0.0.0/0
  - [ ] `sg-app`: inbound 8000 from sg-alb only
  - [ ] `sg-db`: inbound 5432 from sg-app only
  - [ ] `sg-redis`: inbound 6379 from sg-app only

---

## Phase 2: Managed Services (Days 2-3)

### RDS Aurora Serverless v2 (PostgreSQL)

- [ ] Aurora cluster created (PostgreSQL 16 compatible)
- [ ] Serverless v2 capacity: min 0.5 ACU, max 4 ACU
- [ ] Multi-AZ enabled (for production)
- [ ] Automated backups: 7-day retention
- [ ] Master username/password stored in Secrets Manager
- [ ] Parameter group: `shared_preload_libraries = pg_stat_statements`
- [ ] Connection endpoint noted: `cluster.cluster-xxx.region.rds.amazonaws.com`
- [ ] Test connection from local machine (via bastion or VPN)

### ElastiCache Redis

- [ ] Redis cluster created (cache.t3.micro, single node for start)
- [ ] Engine version: Redis 7.x
- [ ] Encryption in transit enabled (TLS)
- [ ] Auth token set and stored in Secrets Manager
- [ ] Subnet group: private subnets only
- [ ] Endpoint noted: `redis-cluster.xxx.cache.amazonaws.com:6379`

### SQS Queues (if migrating from Celery/Redis)

- [ ] Main queue created: `reddit-saas-tasks`
- [ ] DLQ created: `reddit-saas-tasks-dlq`
- [ ] Visibility timeout: 300s (5 min, matches longest task)
- [ ] Message retention: 14 days
- [ ] Redrive policy: maxReceiveCount = 3
- [ ] Queue URL noted

### S3 Bucket

- [ ] Bucket created: `reddit-saas-{env}-assets`
- [ ] Versioning enabled
- [ ] Lifecycle rule: move old logs to Glacier after 90 days
- [ ] Block public access (all)

---

## Phase 3: Container Infrastructure (Days 3-5)

### ECR (Container Registry)

- [ ] Repository created: `reddit-saas`
- [ ] Lifecycle policy: keep last 10 images
- [ ] Push first image:
  ```bash
  aws ecr get-login-password | docker login --username AWS --password-stdin ACCOUNT.dkr.ecr.REGION.amazonaws.com
  docker build -t reddit-saas .
  docker tag reddit-saas:latest ACCOUNT.dkr.ecr.REGION.amazonaws.com/reddit-saas:latest
  docker push ACCOUNT.dkr.ecr.REGION.amazonaws.com/reddit-saas:latest
  ```

### ECS Cluster

- [ ] ECS cluster created (Fargate launch type)
- [ ] CloudWatch Container Insights enabled

### Task Definitions

- [ ] **App task definition:**
  - Image: ECR repo latest
  - CPU: 512 (0.5 vCPU), Memory: 1024 MB
  - Port mapping: 8000
  - Command: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
  - Environment: from Secrets Manager / Parameter Store
  - Health check: `curl -f http://localhost:8000/health`
  - Log driver: awslogs

- [ ] **Worker task definition:**
  - Image: ECR repo latest
  - CPU: 1024 (1 vCPU), Memory: 2048 MB
  - Command: `celery -A app.tasks.worker worker --loglevel=info --concurrency=8`
  - Environment: same as app
  - No port mapping
  - Log driver: awslogs

- [ ] **Beat task definition:**
  - Image: ECR repo latest
  - CPU: 256 (0.25 vCPU), Memory: 512 MB
  - Command: `celery -A app.tasks.worker beat --loglevel=info`
  - Desired count: 1 (never more than 1!)
  - Log driver: awslogs

### ECS Services

- [ ] App service: desired count 2, ALB target group attached
- [ ] Worker service: desired count 2-4
- [ ] Beat service: desired count 1 (singleton)
- [ ] Auto-scaling policies:
  - App: scale on CPU > 70% (min 2, max 6)
  - Worker: scale on SQS queue depth > 50 (min 2, max 12)

### Application Load Balancer

- [ ] ALB created in public subnets
- [ ] HTTPS listener (port 443) with ACM certificate
- [ ] HTTP listener (port 80) → redirect to HTTPS
- [ ] Target group: port 8000, health check path `/health`
- [ ] Stickiness disabled (app is stateless)

---

## Phase 4: Data Migration (Day 6)

### Database Migration

- [ ] Put app in maintenance mode (or schedule downtime window)
- [ ] Final `pg_dump` from source:
  ```bash
  pg_dump -h source-host -U user -d reddit_saas \
    --no-owner --no-acl --format=custom -f /tmp/final_dump.custom
  ```
- [ ] Restore to Aurora:
  ```bash
  pg_restore -h cluster.xxx.rds.amazonaws.com -U admin -d reddit_saas \
    --no-owner --no-acl /tmp/final_dump.custom
  ```
- [ ] Verify row counts match source
- [ ] Run `alembic stamp head` on new DB
- [ ] Test app connectivity to new DB

### Redis Migration

- [ ] Redis data is ephemeral (locks, rate limiters, cache)
- [ ] No migration needed — fresh Redis is fine
- [ ] Celery Beat will re-populate schedule on startup
- [ ] Rate limiter windows will reset (acceptable)

---

## Phase 5: DNS Cutover (Day 7)

### Pre-Cutover Verification

- [ ] App running on ECS, accessible via ALB DNS name
- [ ] Health endpoint returns 200 with all checks passing
- [ ] Test full pipeline: scrape → score → generate → review
- [ ] Celery Beat firing scheduled tasks
- [ ] Worker processing tasks from queue
- [ ] Admin panel accessible and functional
- [ ] LLM calls working (check AI usage logs)

### DNS Switch

- [ ] Update DNS A/CNAME record to point to ALB
- [ ] Wait for propagation (check with `dig`)
- [ ] Verify HTTPS working with real domain
- [ ] Monitor error rates for 1 hour

### Post-Cutover

- [ ] Old server: keep running 48h as fallback
- [ ] Monitor CloudWatch metrics
- [ ] Check no 5xx errors in ALB access logs
- [ ] Verify Celery Beat schedule executing on time
- [ ] Confirm LLM costs are normal (no duplicate calls)

---

## Phase 6: Monitoring & Hardening (Days 8-10)

### CloudWatch Alarms

- [ ] ECS CPU > 80% → alert
- [ ] ECS Memory > 85% → alert
- [ ] RDS CPU > 70% → alert
- [ ] RDS connections > 80% of max → alert
- [ ] ALB 5xx count > 10/min → alert
- [ ] ALB target response time p95 > 3s → alert
- [ ] SQS DLQ messages > 0 → alert (critical)
- [ ] SQS queue depth > 100 → scale workers

### Log Groups

- [ ] `/ecs/reddit-saas-app` — app logs
- [ ] `/ecs/reddit-saas-worker` — worker logs
- [ ] `/ecs/reddit-saas-beat` — beat logs
- [ ] Log retention: 30 days
- [ ] Metric filter: count ERROR level logs

### Backup Verification

- [ ] RDS automated backup confirmed (check console)
- [ ] Test point-in-time recovery (to a test instance)
- [ ] Document recovery procedure

---

## Phase 7: Cleanup (Day 10+)

- [ ] Decommission old DO/EC2 server
- [ ] Remove old DNS records
- [ ] Update documentation with new architecture
- [ ] Update `.env.example` with AWS-specific vars
- [ ] Document runbook for common operations:
  - [ ] How to deploy new version
  - [ ] How to rollback
  - [ ] How to scale manually
  - [ ] How to access logs
  - [ ] How to connect to DB (bastion/SSM)

---

## Environment Variables for AWS

```bash
# .env.production (AWS)

# Database (Aurora)
DATABASE_URL=postgresql://admin:PASSWORD@cluster.xxx.us-east-1.rds.amazonaws.com:5432/reddit_saas

# Redis (ElastiCache)
REDIS_URL=rediss://default:AUTH_TOKEN@redis.xxx.cache.amazonaws.com:6379/0

# App
APP_ENV=production
APP_HOST=0.0.0.0
APP_PORT=8000
SECRET_KEY=<generated-64-char-token>

# Reddit
REDDIT_CLIENT_ID=xxx
REDDIT_CLIENT_SECRET=xxx
REDDIT_USER_AGENT=reddit-saas:v1.0.0

# LLM
LITELLM_API_KEY=sk-xxx
GEMINI_API_KEY=AIza-xxx

# Passwords
POSTGRES_PASSWORD=<strong-random>
REDIS_PASSWORD=<strong-random>

# Admin
ADMIN_EMAIL=max@ramp.com
ADMIN_PASSWORD=<strong-random>

# AWS-specific (if using SQS)
AWS_REGION=us-east-1
AWS_SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/ACCOUNT/reddit-saas-tasks
```

---

## Cost Tracking After Migration

### Monthly Review Checklist

- [ ] Check AWS Cost Explorer — compare to budget
- [ ] Review RDS Aurora ACU usage (right-size min/max)
- [ ] Review ECS task count history (right-size desired count)
- [ ] Check SQS DLQ (failed tasks = wasted LLM money)
- [ ] Review LLM API costs (from ai_usage_log table)
- [ ] Calculate cost per client (total / active clients)
- [ ] Compare actual vs projected from scaling playbook

### Expected Monthly Costs (First 3 Months on AWS)

| Month | Clients | AWS Infra | LLM | Total | Credits Used |
|-------|---------|-----------|-----|-------|-------------|
| 1 | 5 | ~$150 | ~$175 | ~$325 | $325 |
| 2 | 10 | ~$200 | ~$351 | ~$551 | $551 |
| 3 | 15 | ~$250 | ~$525 | ~$775 | $775 |
| **Cumulative** | | | | | **~$1,651** |

With $7K credits: ~4+ months of runway before paying.

---

## Rollback Plan

If AWS migration fails:

1. **DNS rollback** — point domain back to old server (TTL = 60s, propagates in minutes)
2. **Old server** — keep running for 48h post-migration as hot standby
3. **Data sync** — if rollback needed after data diverges:
   ```bash
   # Dump from Aurora
   pg_dump -h aurora-endpoint -U admin -d reddit_saas -f /tmp/aws_dump.custom --format=custom
   # Restore to old server
   pg_restore -h old-server -U user -d reddit_saas --clean /tmp/aws_dump.custom
   ```
4. **Decision point** — if rollback needed after 48h, accept data loss on old server and restore from Aurora dump

---

## Notes

- **Don't migrate during active pipeline windows** (08:00-08:30, 14:00-14:30 UTC)
- **Best migration window:** Saturday 20:00-24:00 UTC (no pipeline runs, low review activity)
- **Keep Celery/Redis architecture initially** — SQS migration is a separate project
- **Aurora Serverless v2 scales to zero** — but cold start is 15-30s (acceptable for background workers, not for web requests — keep min 0.5 ACU)
