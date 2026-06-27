# Implementation Plan: Pipeline Resilience & Hardening

## Overview

15 implementation tasks organized in 4 dependency layers. Tasks 1-5 have no dependencies (foundations). Tasks 6-9 depend on tasks 1-2. Tasks 10-12 depend on tasks 1-2. Tasks 13-15 depend on earlier layers.

## Task Dependency Graph

```json
{
  "waves": [
    [1, 2, 3, 4, 5],
    [6, 7],
    [8, 9, 10, 11],
    [12, 13, 14],
    [15]
  ]
}
```

Explanation:
- Wave 1: Foundations (no dependencies) — error classification, operator alerts, worker memory, log persistence, beat fix
- Wave 2: Core safety (depends on wave 1) — kill switch, task dedup
- Wave 3: Integration (depends on waves 1-2) — circuit breaker, provenance, health endpoint, redis health
- Wave 4: Monitoring (depends on wave 1-3) — heartbeat watcher, feedback observability, demotion alerts
- Wave 5: Deployment & verification (depends on all)

## Tasks

- [ ] 1. Create error classification module (`app/services/error_classification.py`) with `ErrorType` enum (TRANSIENT/PERMANENT/CRITICAL) and `classify_error()` function. Wrap `distributed_lock.py` Redis calls with try/except + classify. Add `socket_timeout=5` to all Redis clients.
  - Requirements: 9.1, 9.5, 9.6, 9.7, 9.8, 9.9, 9.10, 9.11
  - Files: create `app/services/error_classification.py`, modify `app/services/distributed_lock.py`

- [ ] 2. Create operator alert service (`app/services/operator_alerts.py`) with `emit_alert()` supporting Redis PubSub + Telegram + email, rate limiting (20/hr), dedup (3 same type+entity/hr), Redis-down fallback to Telegram. Add system settings.
  - Requirements: 5.4, 5.5, 5.6, 5.7, 5.8, 5.9
  - Files: create `app/services/operator_alerts.py`, modify `app/services/settings.py`

- [ ] 3. Add `worker_max_tasks_per_child` to Celery config (default 200, configurable via `CELERY_MAX_TASKS_PER_CHILD` env var).
  - Requirements: 11.1, 11.2, 11.3, 11.4
  - Files: modify `app/tasks/worker.py`

- [ ] 4. Add `json-file` logging driver with rotation (`max-size: 50m`, `max-file: 5`) to all services in Docker Compose.
  - Requirements: 13.1, 13.2, 13.3, 13.4
  - Files: modify `docker-compose.yml`, modify `docker-compose.prod.yml`

- [ ] 5. Add `celerybeat-schedule` file deletion to celery-beat container startup command. Prevents Beat catch-up firing overdue tasks after deploy.
  - Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
  - Files: modify `docker-compose.yml` (celery-beat command)

- [ ] 6. Create kill switch utility (`app/services/kill_switch.py`) with `is_killed()`, `set_kill_switch()`, `clear_kill_switch()`, `get_active_kill_switches()`. Add admin route for toggle. Add dashboard banner partial. Add 2-line check to ALL Celery task functions.
  - Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10
  - Depends on: Task 1
  - Files: create `app/services/kill_switch.py`, create `app/templates/partials/kill_switch_banner.html`, modify `app/routes/admin.py`, modify `app/templates/admin_base.html`, modify ALL `app/tasks/*.py`

- [ ] 7. Create task dedup decorator (`app/services/task_dedup.py`) with `@task_dedup(cooldown_seconds=N)`. Apply to `build_and_generate_epg_all_avatars` (600s) and `run_full_pipeline_all_clients` (900s). Fail-open on Redis errors.
  - Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7
  - Depends on: Task 1
  - Files: create `app/services/task_dedup.py`, modify `app/tasks/epg.py`, modify `app/tasks/ai_pipeline.py`

- [ ] 8. Integrate freeze circuit breaker into `run_health_check_batch()`. Count NEW freezes per batch, halt at configurable threshold (default 5), emit Operator_Alert + ActivityEvent. Add system setting.
  - Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8
  - Depends on: Task 2
  - Files: modify `app/services/health_checker.py`, modify `app/services/settings.py`

- [ ] 9. Add `approved_by` String(100) nullable column to `comment_drafts`. Set to "autopilot" in EPG auto-approve paths, `current_user.email` in human approve paths, "system:{process}" in bulk operations. Show in admin + portal draft views.
  - Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8
  - Files: create `alembic/versions/res01_approved_by_field.py`, modify `app/models/comment_draft.py`, modify `app/services/epg_executor.py`, modify `app/routes/review.py`, modify `app/routes/portal.py`, modify `app/tasks/ai_pipeline.py`

- [ ] 10. Create `/health/external` endpoint (no auth) returning JSON with status (healthy/degraded/critical), version, per-component checks (Redis, DB, workers) with latency. HTTP 503 when 2+ components down.
  - Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7
  - Depends on: Task 1
  - Files: modify `app/main.py` or create `app/routes/health.py`

- [ ] 11. Create `check_redis_health` Celery task running every 5 min. PING + SET/GET roundtrip + latency. Alert on >100ms or inconsistency. Write results to `ramp:redis_health` hash.
  - Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6
  - Depends on: Task 2
  - Files: create `app/tasks/redis_health.py`, modify `app/tasks/worker.py` (include + Beat schedule)

- [ ] 12. Create heartbeat watcher standalone script (`scripts/heartbeat_watcher.py`) + Docker Compose service. Checks heartbeat every 60s. If stale >5min → alert + `docker restart celery`. 3 min recovery cooldown. Mount Docker socket.
  - Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8
  - Depends on: Task 2
  - Files: create `scripts/heartbeat_watcher.py`, modify `docker-compose.yml`, modify `docker-compose.prod.yml`

- [ ] 13. Enhance `feedback_loop.py` to emit granular ActivityEvents: `feedback_adjustment` per subreddit change, `feedback_hypothesis_update` per confidence change, `feedback_loop_summary` on completion. Add drift detection (>30% cumulative → alert).
  - Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6
  - Depends on: Task 2
  - Files: modify `app/services/feedback_loop.py`

- [ ] 14. Add `emit_alert()` calls at all freeze and demotion points: health_checker freeze, phase evaluator demotion, CQS=lowest transition. Include avatar username, client name, trigger reason.
  - Requirements: 5.1, 5.2, 5.3
  - Depends on: Task 2
  - Files: modify `app/services/health_checker.py`, modify `app/tasks/ai_pipeline.py`

- [ ] 15. Deploy to staging and verify all 13 requirements end-to-end. Run migration, test kill switch toggle, verify heartbeat watcher, confirm log rotation, test circuit breaker below threshold, verify approved_by field, check feedback events. Production deploy with operator approval.
  - Requirements: All
  - Depends on: Tasks 1-14

## Notes

- Tasks 3, 4, 5 are trivial config changes (< 10 lines each) — can be done in one commit
- Task 6 (kill switch) touches ALL task files — do as a single focused PR to minimize merge conflicts
- Task 9 (Alembic migration) is zero-downtime (nullable column add) — safe to deploy independently
- Task 12 (heartbeat watcher) requires Docker socket mount — security consideration for production review
- Production deploy (Task 15) requires explicit operator approval per environments.md rules
