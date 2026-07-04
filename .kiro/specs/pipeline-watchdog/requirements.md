# Pipeline Watchdog & Liveness Monitoring

## Problem Statement

RAMP's pipeline died on June 11, 2026 and went undetected for 17 days. The root cause: all monitoring lives inside the system being monitored (Celery tasks, admin UI alerts). When Celery dies, monitoring dies with it.

Additionally, even when workers ARE alive, the pipeline can silently produce zero output without anyone noticing. Zero output is treated as "nothing to do" rather than "something is broken."

This spec addresses two related failures:
1. **External watchdog** — detect system death from outside the system
2. **Backpressure signals** — detect silent pipeline starvation from inside

## Requirements

### FR-1: External Health Monitor (Out-of-Band)

1. THE system SHALL expose a `/health` endpoint that returns machine-readable liveness data including:
   - `worker_alive`: boolean (last heartbeat < 5 min)
   - `pipeline_alive`: boolean (last successful scrape < 24h)
   - `scrape_stale_hours`: float (hours since any successful scrape)
   - `status`: "ok" | "degraded" | "pipeline_dead"
2. AN external monitoring service (UptimeRobot or BetterUptime, free tier) SHALL poll `/health` every 5 minutes
3. WHEN `status != "ok"` for 2 consecutive checks (10 min), THE monitor SHALL:
   - Send email to Max (max.breger@gmail.com)
   - Send email to Tzvi (tzvi@tzvivaknindigital.com)
4. WHEN `status == "degraded"` (DB or Redis down), THE monitor SHALL alert immediately (single check)
5. THE `/health` endpoint SHALL be accessible without authentication

### FR-2: Telegram Alert Bot

1. THE system SHALL send Telegram messages to a designated chat for critical events:
   - Pipeline dead (no scrape > 24h while scrape_enabled=true)
   - Worker offline (no heartbeat > 5 min)
   - P1 violation (paying client with 0 drafts in 7 days)
   - Avatar frozen (any avatar state change to frozen)
2. THE Telegram integration SHALL use a bot token stored in `.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`)
3. Messages SHALL be concise: emoji + one-line summary + link to admin page
4. Rate limit: max 10 messages per hour (prevent spam loops)
5. THE bot SHALL work independently of Celery (can be called from FastAPI request lifecycle or standalone cron)

### FR-3: Pipeline Backpressure Signals

1. WHEN `queue_tick` runs and `scrape_enabled=true` AND active subreddits > 0:
   - IF 0 scrapes dispatched for > 6 consecutive hours → emit `pipeline_starvation` activity event
   - THE event SHALL include: reason, hours_since_last_dispatch, active_sub_count
2. WHEN `generate_comments` runs for a client with Phase 2+ avatars:
   - IF 0 engage threads found for > 48h → emit `p1_threat` activity event
   - THE event SHALL include: client_name, hours_since_last_engage, avatar_count
3. WHEN `build_portfolio` runs for an avatar with budget > 0:
   - IF 0 opportunities found → this is already a zero-day report (existing behavior)
   - IF zero-day reports persist for same avatar > 3 consecutive days → emit `p1_critical` event
4. ALL backpressure events SHALL feed into `alert_aggregation.py` and be visible on dashboard

### FR-4: Auto-Restart Mechanism

1. THE Docker Compose configuration SHALL include `restart: unless-stopped` on:
   - celery
   - celery-fast
   - celery-beat
2. THE Docker Compose configuration SHALL include healthcheck for celery worker:
   ```yaml
   healthcheck:
     test: ["CMD", "celery", "-A", "app.tasks.worker", "inspect", "ping", "--timeout", "10"]
     interval: 60s
     timeout: 15s
     retries: 3
     start_period: 30s
   ```
3. A standalone cron job on the HOST (outside Docker) SHALL run every 5 minutes:
   - Check if celery container is unhealthy/stopped
   - If unhealthy > 2 checks (10 min) → `docker compose restart celery celery-beat`
   - Log restart event to `/var/log/ramp-watchdog.log`
   - Send Telegram notification

### FR-5: Pipeline Dead Alert (In-Band Fallback)

1. THE `alert_aggregation.py` SHALL include a `pipeline_dead` alert:
   - Triggered when: scrape_enabled=true AND max(last_scraped_at) > 24h ago
   - Severity: critical
   - Message includes time since last scrape
2. THIS alert is the in-band fallback — works only when app container is alive and admin visits dashboard
3. THE alert SHALL NOT replace external monitoring (FR-1) — it's defense-in-depth

### FR-6: Auto-Expire Stale Pending Drafts

1. A Celery Beat task SHALL run daily at 23:45 (after expire_overdue_execution_tasks at 23:30):
   - Query: `comment_drafts WHERE status='pending' AND created_at < now() - 14 days`
   - Action: set status='rejected', add rejection_reason='auto_expired_stale_14d'
   - Log: activity event with count of expired drafts
2. THE task SHALL be gated by system setting `auto_expire_drafts_enabled` (default: true)
3. THE task SHALL NOT expire drafts that have been manually edited (edited_draft IS NOT NULL AND edited_at > created_at)

## Non-Functional Requirements

### NFR-1: Independence
- External monitor (FR-1) must work even if entire Docker Compose is down
- Telegram bot (FR-2) must be callable without Celery (direct HTTP from FastAPI or host cron)
- Host cron (FR-4) must work even if all containers are dead

### NFR-2: Cost
- UptimeRobot free tier: 50 monitors, 5-min interval (sufficient)
- Telegram Bot API: free
- No additional infrastructure cost

### NFR-3: No False Alerts
- Pipeline dead alert: only when scrape_enabled=true (intentional disable ≠ alert)
- Worker offline: only after 5 min (not on brief restart)
- Backpressure: only after sustained period (6h/48h), not on single empty run

### NFR-4: Deployment
- `/health` enhancement: already done (June 28 fix)
- `pipeline_dead` alert: already done (June 28 fix)
- Remaining: Telegram bot, host cron, Docker healthcheck, backpressure events, auto-expire task

## Out of Scope

- PagerDuty/Opsgenie integration (overkill for current scale)
- Auto-scaling (not needed at <10 clients)
- Multi-region failover
- Chaos testing (manual verification sufficient)

## Implementation Order

1. Docker restart policy + healthcheck (15 min, config change only)
2. UptimeRobot setup (15 min, no code)
3. Telegram bot service (2-3 hours)
4. Auto-expire stale drafts task (1 hour)
5. Backpressure signals in pipeline tasks (2-3 hours)
6. Host cron watchdog script (1 hour)

## Success Criteria

1. If Celery dies → Max and Tzvi know within 10 minutes (not 17 days)
2. If pipeline produces 0 output for 24h → visible alert on dashboard + Telegram
3. Stale drafts never accumulate beyond 14 days
4. Docker auto-restarts on OOM/crash without human intervention
5. False alert rate < 1/week
