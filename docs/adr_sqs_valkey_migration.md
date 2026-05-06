# ADR: Migrate from Celery+Redis to SQS+Valkey Serverless

**Status:** Accepted  
**Date:** May 6, 2026  
**Decision Makers:** Max (tech lead)

---

## Context

The current RAMP platform uses Celery with Redis as both message broker and result backend. While functional for development, this architecture has critical production gaps:

1. **No Dead Letter Queue** — failed tasks are silently lost
2. **No message persistence** — Redis crash = all pending tasks gone
3. **No visibility timeout** — worker crash = task never retried
4. **No observability** — no queue depth metrics, no alerting
5. **Single point of failure** — Redis on same EC2 instance

For a paid SaaS serving agency clients, these gaps are unacceptable.

---

## Decision

Replace Celery + Redis with:
- **AWS SQS Standard** — task queue (broker replacement)
- **AWS ElastiCache Serverless Valkey** — distributed locks, rate limiting, task results

---

## Consequences

### Positive

- **DLQ built-in**: Failed tasks automatically routed to dead letter queue after N retries
- **14-day message retention**: Tasks survive any infrastructure failure
- **Visibility timeout**: If worker crashes mid-task, message becomes visible again after timeout
- **CloudWatch metrics free**: Queue depth, message age, DLQ count — all with alerting
- **Multi-AZ HA**: Valkey Serverless is automatically replicated across availability zones
- **Zero ops**: No Redis monitoring, no OOM kills, no manual restarts
- **Cost predictable**: $27/mo regardless of traffic patterns (within current scale)

### Negative

- **Higher latency**: SQS ~20-50ms vs Redis ~1ms (acceptable for background tasks)
- **Migration effort**: ~2 weeks to rewrite task layer
- **No Celery ecosystem**: Lose Flower, celery-beat, task chaining syntax
- **Vendor lock-in**: SQS is AWS-specific (mitigated by thin abstraction layer)
- **Slightly higher cost**: +$7/mo vs all-in-Docker approach

### Neutral

- **Scheduler replacement**: Celery Beat → EventBridge Scheduler or cron on EC2
- **Worker model change**: Celery prefork → asyncio long-poll loop
- **Testing**: Need to mock SQS in tests (localstack or moto)

---

## Migration Plan

### Phase 1: SQS Producer + Consumer (Week 1)

1. Create `app/tasks/sqs_producer.py` — thin wrapper around boto3 SQS send_message
2. Create `app/tasks/sqs_consumer.py` — asyncio loop with long polling (20s)
3. Create SQS queues: `ramp-scrape`, `ramp-ai`, `ramp-health`, `ramp-dlq`
4. Wire existing task functions to new consumer dispatch

### Phase 2: Valkey Client (Week 1)

1. Replace `redis.Redis.from_url()` with Valkey-compatible client (same protocol)
2. Update connection string to ElastiCache Serverless endpoint
3. Verify distributed locks and rate limiter work unchanged (Valkey is Redis-compatible)

### Phase 3: Scheduler (Week 2)

1. Replace Celery Beat with simple cron-based scheduler on EC2
2. Scheduler sends messages to SQS at configured intervals
3. Alternative: AWS EventBridge Scheduler (free for <1M invocations/mo)

### Phase 4: Cleanup (Week 2)

1. Remove Celery dependencies from pyproject.toml
2. Remove Redis from docker-compose.yml (keep for local dev with Valkey emulation)
3. Update Dockerfile (no celery worker/beat commands)
4. Update tests to mock SQS (moto library)
5. Update admin dashboard to show SQS metrics instead of Celery task status

---

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| Keep Celery, add Redis Sentinel | Still no DLQ, adds complexity, Redis Sentinel costs more than Valkey Serverless |
| Celery + SQS broker | Celery SQS transport is poorly maintained, limited features |
| AWS Lambda + SQS | Overkill for current scale, cold starts, harder to debug |
| ECS + SQS | More expensive, unnecessary container orchestration for 1 instance |
| Self-hosted RabbitMQ | More ops overhead than SQS, no free tier |

---

## Success Criteria

- [ ] All existing tasks execute correctly via SQS
- [ ] DLQ captures failed tasks with full context
- [ ] CloudWatch alarms fire on queue depth > 100 or DLQ > 0
- [ ] Distributed locks work identically on Valkey
- [ ] Rate limiter works identically on Valkey
- [ ] No task loss during EC2 restart
- [ ] All 93+ tests pass with mocked SQS
- [ ] Monthly cost stays under $30

---

## References

- [AWS SQS Pricing](https://aws.amazon.com/sqs/pricing/)
- [ElastiCache Serverless for Valkey](https://aws.amazon.com/elasticache/pricing/)
- [Valkey compatibility with Redis](https://valkey.io/topics/compatibility/)
- `docs/aws_budget_may2026.md` — Full cost breakdown

---

*Document created: May 6, 2026*
