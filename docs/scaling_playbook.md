# Scaling Playbook — Reddit Marketing SaaS

## Current Baseline (May 2026)

| Metric | Value |
|--------|-------|
| Avatars | ~50 (target for pilot) |
| Clients | 3-5 |
| Subreddits | ~30 active |
| Comments generated/day | ~45-75 |
| LLM calls/day | ~200 |
| Infrastructure | Single server (Docker Compose) |
| Monthly infra cost | ~$27 (EC2/DO) + ~$105 LLM |

### Architecture Summary

```
┌─────────────────────────────────────────────────┐
│  Single Server (4GB RAM)                        │
│                                                 │
│  ┌──────────┐  ┌────────┐  ┌───────────────┐  │
│  │ FastAPI  │  │ Celery │  │ Celery Beat   │  │
│  │ (uvicorn)│  │ Worker │  │ (scheduler)   │  │
│  └────┬─────┘  └───┬────┘  └───────────────┘  │
│       │             │                           │
│  ┌────┴─────────────┴────┐  ┌───────────────┐  │
│  │   PostgreSQL 16       │  │   Redis 7     │  │
│  └───────────────────────┘  └───────────────┘  │
└─────────────────────────────────────────────────┘
         │                           │
         ▼                           ▼
   Reddit API (PRAW)         LLM APIs (Anthropic, Google)
```

---

## Scenario A: DigitalOcean Scaling Roadmap

### Phase 1: Pilot (3-10 clients, 50 avatars) — $24-48/mo

**Infrastructure:**
- 1x Droplet 4GB ($24/mo) — app + worker + DB + Redis all on one box
- Docker Compose (current setup, no changes needed)

**Code changes:** None. Current architecture handles this.

**Bottleneck:** LLM API cost ($105-351/mo), not infrastructure.

---

### Phase 2: Growth (10-30 clients, 100-150 avatars) — $102-150/mo

**Infrastructure:**

| Component | Spec | Cost/mo |
|-----------|------|---------|
| App Server | 1x 8GB Droplet | $48 |
| Managed PostgreSQL | 1 GB (Basic) | $15 |
| Managed Redis | 1 GB | $15 |
| Spaces (logs/backups) | 250 GB | $5 |
| **Total** | | **$83** |

**Why split:**
- DB on managed service = automated backups, failover, no data loss risk
- Redis managed = persistence, no restart data loss
- App server gets full 8GB for FastAPI + Celery workers

**Code changes needed:**

```python
# .env changes only — no code changes
DATABASE_URL=postgresql://user:pass@db-cluster.ondigitalocean.com:25060/reddit_saas?sslmode=require
REDIS_URL=rediss://default:pass@redis-cluster.ondigitalocean.com:25061
```

**Celery tuning:**
```python
# worker.py — increase concurrency for more avatars
celery_app.conf.update(
    worker_concurrency=8,  # was 4
    worker_max_tasks_per_child=200,  # recycle workers to prevent memory leaks
)
```

---

### Phase 3: Scale (30-80 clients, 200-300 avatars) — $250-350/mo

**Infrastructure:**

| Component | Spec | Cost/mo |
|-----------|------|---------|
| App Server | 1x 8GB Droplet (FastAPI only) | $48 |
| Worker Server | 1x 8GB Droplet (Celery workers) | $48 |
| Beat Server | on App Server (lightweight) | — |
| Managed PostgreSQL | 4 GB (Primary + standby) | $60 |
| Managed Redis | 2 GB | $30 |
| Load Balancer | DO LB (if 2 app servers) | $12 |
| Spaces | 250 GB | $5 |
| **Total** | | **$203-250** |

**Why separate workers:**
- LLM calls block Celery threads (3-5s each)
- 300 avatars × 15 generations/day = 4,500 LLM calls
- At 5s/call, 4 workers = 22,500s = 6.25 hours of wall time
- Need 8-12 concurrent workers to finish within pipeline windows (08:00-08:30, 14:00-14:30)

**Code changes needed:**

```python
# docker-compose.production.yml — separate worker service
services:
  app:
    image: reddit-saas:latest
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
    deploy:
      resources:
        limits:
          memory: 2G

  celery-worker:
    image: reddit-saas:latest
    command: celery -A app.tasks.worker worker --loglevel=info --concurrency=12
    deploy:
      resources:
        limits:
          memory: 4G

  celery-beat:
    image: reddit-saas:latest
    command: celery -A app.tasks.worker beat --loglevel=info
```

**LLM pipeline optimization (critical at this scale):**

```python
# services/scoring.py — batch scoring (10 threads per LLM call)
async def score_threads_batch(threads: list[RedditThread], client) -> list[ThreadScore]:
    """Score up to 10 threads in a single LLM call."""
    batch_prompt = format_batch_scoring_prompt(threads, client)
    result = call_llm_json(
        messages=[{"role": "system", "content": batch_prompt}],
        model=get_config("llm_scoring_model"),
        schema=BatchScoringOutput,
    )
    return parse_batch_scores(result["data"], threads)
```

```python
# services/generation.py — decision tree pre-filter
def should_generate(thread: RedditThread, avatar: Avatar, client: Client) -> bool:
    """Quick heuristic check before expensive LLM generation call."""
    # Skip if thread too old
    if thread.age_hours > 48:
        return False
    # Skip if avatar already commented in this subreddit today
    if avatar.comments_today_in(thread.subreddit) >= 2:
        return False
    # Skip if thread score below threshold
    if thread.latest_score and thread.latest_score.total < 6.0:
        return False
    return True
```

---

### Phase 4: Full Scale (80+ clients, 300+ avatars) — $300-400/mo

**Infrastructure:**

| Component | Spec | Cost/mo |
|-----------|------|---------|
| App Servers | 2x 8GB + Load Balancer | $108 |
| Worker Servers | 2x 8GB (Celery pools) | $96 |
| Managed PostgreSQL | 4 GB (Primary + Read Replica) | $80 |
| Managed Redis | 2 GB (HA) | $30 |
| Spaces | 500 GB | $10 |
| **Total** | | **~$324** |

**Additional code changes:**

```python
# Separate Celery queues for priority routing
celery_app.conf.task_routes = {
    "app.tasks.ai_pipeline.*": {"queue": "ai"},
    "app.tasks.scraping.*": {"queue": "scraping"},
    "app.tasks.health_check.*": {"queue": "maintenance"},
}

# Worker startup: specify queue
# Worker 1 (AI-heavy): celery -A app.tasks.worker worker -Q ai --concurrency=8
# Worker 2 (scraping): celery -A app.tasks.worker worker -Q scraping --concurrency=16
# Worker 3 (maintenance): celery -A app.tasks.worker worker -Q maintenance --concurrency=4
```

---

## Scenario B: AWS Scaling Roadmap

### When to Consider AWS

| Trigger | Why |
|---------|-----|
| 100+ avatars consistently | Managed services reduce ops burden |
| 3+ DO servers | AWS economies of scale kick in |
| Enterprise client requirement | SOC2, compliance, SLA guarantees |
| Multi-region needed | AWS Global Accelerator / CloudFront |
| Auto-scaling needed | ECS Fargate scales to zero |
| $7K AWS credits available | Free runway to build on AWS |

### AWS Architecture (300 avatars)

```
CloudFront (static assets CDN)
         │
Application Load Balancer ($25/mo)
         │
    ┌────┴────┐
    │         │
ECS Fargate   ECS Fargate
(FastAPI)     (FastAPI)
 2-4 tasks    auto-scale
    │
    ├──── SQS Standard Queue (main) ──── DLQ
    │
    ┌────┴────┐
    │         │
ECS Fargate   ECS Fargate
(Celery)      (Celery)
 4-12 tasks   auto-scale by queue depth
    │
    ├──── RDS Aurora Serverless v2 (PostgreSQL)
    │     (0.5-4 ACU, auto-scales)
    │
    └──── ElastiCache Redis (cache.t3.micro)
          (single node, 0.5 GB)
```

### AWS Cost Estimate (300 avatars)

| Service | Spec | Cost/mo |
|---------|------|---------|
| ECS Fargate (app) | 2 tasks × 0.5 vCPU × 1GB | ~$30 |
| ECS Fargate (workers) | 4-8 tasks × 1 vCPU × 2GB | ~$120 |
| RDS Aurora Serverless v2 | 0.5-2 ACU avg | ~$90 |
| ElastiCache Redis | cache.t3.micro | ~$15 |
| SQS | ~3M requests/mo | ~$2 |
| ALB | 1 LB + LCU | ~$25 |
| S3 | 50 GB | ~$2 |
| CloudWatch | Logs + metrics | ~$10 |
| ECR | Container registry | ~$5 |
| **Total** | | **~$300-350** |

**Note:** With $7K AWS credits, this is ~20 months free.

### AWS Advantages Over DO

| Feature | DigitalOcean | AWS |
|---------|-------------|-----|
| Auto-scaling | Manual (add droplets) | ECS auto-scale by CPU/queue depth |
| Queue reliability | Redis (volatile) | SQS (14-day retention, DLQ) |
| DB failover | Manual standby | Aurora auto-failover (30s) |
| Monitoring | Basic | CloudWatch alarms, X-Ray tracing |
| SLA | 99.99% | 99.95-99.99% per service |
| Compliance | Limited | SOC2, HIPAA, ISO ready |
| Cost at scale | Linear | Sub-linear (reserved, spot) |

---

## Decision Matrix: DO vs AWS

| Criterion | Weight | DigitalOcean | AWS | Winner |
|-----------|--------|-------------|-----|--------|
| Cost (< 100 avatars) | 25% | $24-83 | $100-150 | DO |
| Cost (300 avatars) | 15% | $300 | $350 | DO (barely) |
| Ops complexity | 20% | Low (Docker Compose) | Medium (IaC, ECS) | DO |
| Auto-scaling | 15% | Manual | Native | AWS |
| Reliability/SLA | 10% | Good | Excellent | AWS |
| Enterprise readiness | 10% | Limited | Full | AWS |
| Migration effort | 5% | N/A | 2-3 weeks | DO |

**Recommendation:**
- **Start on DO** (pilot through 50 clients)
- **Migrate to AWS** when: enterprise client requires it OR 100+ avatars OR ops burden exceeds 4h/week

---

## LLM Pipeline Scaling Strategies

### 1. Decision Tree Pre-Filter (saves 30-50% of LLM calls)

```python
# Before calling expensive Claude Sonnet for generation:
def pre_filter_thread(thread, avatar, client, db) -> tuple[bool, str]:
    """Return (should_generate, skip_reason)."""
    
    # Rule 1: Thread age
    if thread.age_hours > int(get_config("thread_max_age_hours")):
        return False, "thread_too_old"
    
    # Rule 2: Already have draft for this thread+avatar
    existing = db.query(CommentDraft).filter_by(
        thread_id=thread.id, avatar_id=avatar.id
    ).first()
    if existing:
        return False, "draft_exists"
    
    # Rule 3: Avatar daily limit reached
    today_count = count_avatar_drafts_today(db, avatar.id, thread.subreddit_name)
    max_per_sub = int(get_config("max_comments_per_sub_per_day"))
    if today_count >= max_per_sub:
        return False, "daily_limit"
    
    # Rule 4: Score threshold
    score = get_thread_score(db, thread.id, client.id)
    if score and score.total_score < 6.0:
        return False, "low_score"
    
    return True, ""
```

### 2. Response Caching (saves 10-20% on repeated patterns)

```python
import hashlib
from datetime import timedelta

def get_cached_or_generate(prompt_hash: str, generate_fn, ttl_hours: int = 24):
    """Cache LLM responses for identical prompts."""
    cache_key = f"llm_cache:{prompt_hash}"
    
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    
    result = generate_fn()
    redis_client.setex(cache_key, timedelta(hours=ttl_hours), json.dumps(result))
    return result

# Usage in scoring (same thread scored for multiple clients with same keywords):
def score_thread_cached(thread, client):
    prompt = build_scoring_prompt(thread, client)
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
    return get_cached_or_generate(prompt_hash, lambda: call_scoring_llm(prompt))
```

### 3. Batch Scoring (saves 40-60% on scoring tokens)

```python
# Instead of 1 thread per LLM call, batch 10:
BATCH_SCORING_PROMPT = """Score these {n} threads for relevance to client "{client_name}".
Keywords: {keywords}

{threads_json}

Return JSON array with scores for each thread_id."""

def score_batch(threads: list, client) -> list[dict]:
    batch_size = int(get_config("scoring_batch_size"))  # default 10
    results = []
    
    for chunk in chunked(threads, batch_size):
        batch_result = call_llm_json(
            messages=[{"role": "system", "content": format_batch_prompt(chunk, client)}],
            model=get_config("llm_scoring_model"),
        )
        results.extend(batch_result["data"]["scores"])
    
    return results
```

### 4. Model Routing by Complexity

```python
# Use cheaper models for simpler tasks:
MODEL_ROUTING = {
    "scoring": "gemini/gemini-2.0-flash",           # $0.075/1M input
    "persona_select_single": None,                   # Skip LLM entirely
    "persona_select_multi": "gemini/gemini-2.0-flash",  # Cheap routing
    "generation_hobby": "gemini/gemini-2.0-flash",   # Hobby = low stakes
    "generation_professional": "anthropic/claude-sonnet-4-20250514",  # Quality matters
    "editing": "anthropic/claude-3-5-haiku-20241022",  # Editing is simpler
}
```

### 5. Concurrency Optimization

```python
# Current: sequential LLM calls (1 at a time per worker)
# Target: async concurrent calls within a task

import asyncio
from litellm import acompletion

async def generate_comments_concurrent(threads: list, avatar, client, max_concurrent=5):
    """Generate comments for multiple threads concurrently."""
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def generate_one(thread):
        async with semaphore:
            return await acompletion(
                model=get_config("llm_generation_model"),
                messages=build_generation_messages(thread, avatar, client),
                max_tokens=512,
            )
    
    tasks = [generate_one(t) for t in threads]
    return await asyncio.gather(*tasks, return_exceptions=True)
```

---

## Cost Projections

### Infrastructure Cost (DO path)

| Avatars | Clients | DO Infra/mo | LLM/mo | Total/mo | Revenue/mo |
|---------|---------|-------------|---------|----------|-----------|
| 50 | 5 | $24 | $175 | $199 | $2,500 |
| 100 | 15 | $83 | $525 | $608 | $7,500 |
| 150 | 30 | $150 | $1,050 | $1,200 | $15,000 |
| 300 | 60 | $324 | $2,100 | $2,424 | $30,000 |

### Margin Analysis

| Scale | Total Cost | Revenue | Gross Margin |
|-------|-----------|---------|-------------|
| 50 avatars | $199 | $2,500 | 92% |
| 150 avatars | $1,200 | $15,000 | 92% |
| 300 avatars | $2,424 | $30,000 | 92% |

**Key insight:** Margins stay flat at ~92% because LLM costs scale linearly with revenue (more clients = more LLM calls = more subscription fees).

---

## Migration Plan: DO → AWS

### Prerequisites (do before migration)

1. **Externalize all config** — already done (pydantic-settings + DB settings)
2. **Health endpoint** — already done (`GET /health`)
3. **Stateless app** — already done (no local file storage, sessions in DB)
4. **Container-ready** — already done (Dockerfile + docker-compose)
5. **Queue abstraction** — TODO (see code changes below)

### Migration Steps

| Step | Duration | Risk |
|------|----------|------|
| 1. Set up AWS account + VPC | 1 day | Low |
| 2. Create RDS Aurora instance | 1 day | Low |
| 3. Create ElastiCache Redis | 1 day | Low |
| 4. Set up ECR + push image | 1 day | Low |
| 5. Create ECS task definitions | 2 days | Medium |
| 6. Set up ALB + target groups | 1 day | Low |
| 7. Data migration (pg_dump → RDS) | 2 hours | Medium |
| 8. DNS cutover | 1 hour | Low |
| 9. Verify + monitor | 2 days | Low |
| **Total** | **~10 days** | |

### Code Changes for AWS Readiness

```python
# 1. Abstract queue interface (prepare for SQS)
# app/services/queue_interface.py

from abc import ABC, abstractmethod

class TaskQueue(ABC):
    @abstractmethod
    def send_task(self, task_name: str, args: tuple = (), kwargs: dict = None, 
                  queue: str = "default", countdown: int = 0) -> str:
        """Send a task to the queue. Returns task ID."""
        pass

    @abstractmethod
    def get_queue_depth(self, queue: str = "default") -> int:
        """Get number of messages waiting in queue."""
        pass

class CeleryTaskQueue(TaskQueue):
    def __init__(self, celery_app):
        self.app = celery_app
    
    def send_task(self, task_name, args=(), kwargs=None, queue="default", countdown=0):
        result = self.app.send_task(task_name, args=args, kwargs=kwargs,
                                     queue=queue, countdown=countdown)
        return result.id
    
    def get_queue_depth(self, queue="default"):
        with self.app.connection_or_acquire() as conn:
            return conn.default_channel.queue_declare(queue, passive=True).message_count

# Future: SQSTaskQueue implementation
```

```python
# 2. Container health check for ECS
# Already exists at GET /health — ECS will use this

# 3. Graceful shutdown for ECS SIGTERM
# app/main.py — add shutdown handler
import signal

@app.on_event("shutdown")
def on_shutdown():
    logger.info("Graceful shutdown initiated")
    # Celery workers handle SIGTERM natively
```

---

## Monitoring & Alerts (Both Platforms)

### Key Metrics to Track

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| LLM error rate | > 5% | > 15% | Check API key / provider status |
| Queue depth | > 50 | > 200 | Scale workers |
| DB connections | > 80% pool | > 95% pool | Increase pool / upgrade |
| Response time (p95) | > 2s | > 5s | Check DB queries |
| Failed tasks/hour | > 5 | > 20 | Check DLQ / logs |
| LLM cost/day | > $20 | > $50 | Review pipeline efficiency |
| Disk usage | > 70% | > 90% | Cleanup / expand |

### DO Monitoring Setup

```bash
# Install DO monitoring agent
curl -sSL https://repos.insights.digitalocean.com/install.sh | sudo bash

# Set up uptime checks (DO built-in)
# Target: https://your-domain.com/health
# Interval: 1 minute
# Alert: Slack webhook
```

### AWS Monitoring Setup (CloudWatch)

```json
{
  "alarms": [
    {
      "name": "HighQueueDepth",
      "metric": "ApproximateNumberOfMessagesVisible",
      "threshold": 100,
      "action": "scale-up-workers"
    },
    {
      "name": "HighCPU",
      "metric": "CPUUtilization",
      "threshold": 80,
      "action": "scale-up-app"
    }
  ]
}
```

---

## Summary: Recommended Path

```
NOW (May 2026)          6 months              12 months            18 months
─────────────────────────────────────────────────────────────────────────────
DO 4GB Droplet    →   DO 8GB + Managed DB  →  AWS ECS + RDS    →  AWS auto-scale
$24/mo                 $83/mo                  $300/mo              $300-600/mo
50 avatars             150 avatars             300 avatars          500+ avatars
Docker Compose         Docker Compose          ECS + Terraform      ECS + CDK
Manual ops             Semi-automated          Fully managed        Self-healing
```

**Decision points:**
1. **Move to Managed DB** → when you have 5+ paying clients (data loss = revenue loss)
2. **Separate workers** → when pipeline windows exceed 30 minutes
3. **Move to AWS** → when enterprise client requires it OR ops burden > 4h/week
4. **Auto-scaling** → when traffic is unpredictable OR 300+ avatars
