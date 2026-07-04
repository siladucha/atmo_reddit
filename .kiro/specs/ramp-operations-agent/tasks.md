# Implementation Plan: RAMP Operations Agent

## Overview

Phased implementation of a three-layer autonomous operations agent. Each phase is independently deployable and provides value without subsequent phases. Implementation follows the deployment order: Phase 1 (External Watchdog + Telegram + Health), Phase 2 (Authority + Actions + Alerts), Phase 3 (Economics + Silent Failures), Phase 4 (Briefings + Reports + Scaling).

## Tasks

- [ ] 1. Database foundation — models, migrations, and shared infrastructure
  - [ ] 1.1 Create agent data models (8 tables)
    - Create `reddit_saas/app/models/agent_metric.py` — AgentMetric model with UUID pk, collected_at, category, metric_name, value, unit, component, client_id FK, avatar_id FK, metadata_json JSONB, composite index on (category, metric_name, collected_at)
    - Create `reddit_saas/app/models/agent_alert.py` — AgentAlert model with all fields from design (alert_type, severity, time_horizon, title, message, affected_entity_type/id, status, timestamps, escalation_count, cooldown_until, delivery_status/channel, payload_json JSONB, indexes)
    - Create `reddit_saas/app/models/agent_action.py` — AgentAction model (action_name, permission_level, status, trigger_condition, rationale, expected_impact, rollback_plan, outcome, timestamps, execution_time_ms, metadata_json)
    - Create `reddit_saas/app/models/agent_proposal.py` — AgentProposal model with FK to agent_actions, status lifecycle (pending/approved/rejected/expired), expires_at, decided_by FK to users
    - Create `reddit_saas/app/models/agent_heartbeat.py` — AgentHeartbeat model (overall_status, execution_time_ms, memory_rss_mb, cpu_time_ms, dependency connectivity booleans, details_json)
    - Create `reddit_saas/app/models/agent_economic_snapshot.py` — AgentEconomicSnapshot with Numeric(10,4) cost fields, gross_margin_pct, per_client/avatar breakdown JSONB, optimization_suggestions_json
    - Create `reddit_saas/app/models/agent_weekly_report.py` — AgentWeeklyReport (report_week_start, report_markdown, metrics_json, fleet_status_json, economic_projections_json, scaling_assessment_json, recommendations_json)
    - Create `reddit_saas/app/models/agent_config.py` — AgentConfig (key unique indexed, value, value_type, description, updated_at, updated_by FK)
    - Register all models in `reddit_saas/app/models/__init__.py`
    - _Requirements: 1.1-1.9, 5.7, 10.1-10.4, 12.5, 15.7, 17.1, 22.1-22.3_

  - [ ] 1.2 Create Alembic migration `agent01` for all 8 tables
    - Single migration file `reddit_saas/alembic/versions/agent01_create_agent_tables.py`
    - Create all 8 tables with proper indexes, foreign keys, CHECK constraints
    - Add composite indexes optimized for time-range queries
    - Test migration up and down locally
    - _Requirements: 1.1-1.9, 5.7, 10.1, 22.1_

  - [ ] 1.3 Create agent service package skeleton and shared types
    - Create `reddit_saas/app/services/agent/__init__.py`
    - Create `reddit_saas/app/services/agent/types.py` — shared dataclasses: MetricSnapshot, WatchdogCheck, ActionResult, Alert, Finding, ClientCost, AvatarCost, OptimizationSuggestion, CapacityModel
    - Define enums: PermissionLevel, AlertSeverity, AlertTimeHorizon, ComponentStatus
    - _Requirements: 1.4, 5.1, 15.1_

- [ ] 2. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 3. Phase 1A — External watchdog script
  - [ ] 3.1 Create watchdog configuration and install script
    - Create `/Volumes/2SSD/Projects/ReddirSaaS/watchdog/config.yaml` — template with thresholds (heartbeat_max_age: 180s, disk_critical: 95%, health_endpoint_timeout: 10s), Telegram chat_id placeholder, DB credentials placeholder, Redis URL
    - Create `/Volumes/2SSD/Projects/ReddirSaaS/watchdog/requirements.txt` — psycopg2-binary, redis, python-telegram-bot, pyyaml, httpx
    - Create `/Volumes/2SSD/Projects/ReddirSaaS/watchdog/install.sh` — creates /opt/ramp-watchdog/, sets up Python venv, installs deps, creates systemd timer + service units, enables and starts them
    - _Requirements: 22.5, 22.6_

  - [ ] 3.2 Implement watchdog check chain (`watchdog/watchdog.py`)
    - Implement `WatchdogConfig` dataclass loading from config.yaml
    - Implement `DockerHealthCheck` — runs `docker ps --format json`, checks all expected containers healthy
    - Implement `HealthEndpointCheck` — GET http://localhost/health, expect 200 + valid JSON with agent fields
    - Implement `RedisHeartbeatCheck` — GET `ramp:heartbeat:last_at`, verify age < 180s
    - Implement `PostgresConnCheck` — execute `SELECT 1` via psycopg2
    - Implement `PipelineOutputCheck` — query last scrape timestamp, alert if > 12h and scrape_enabled
    - Implement `DiskSpaceCheck` — check disk usage, alert if > 90%
    - Implement `run_all_checks()` — executes all checks, never throws, returns list[WatchdogCheck]
    - Implement `evaluate_and_alert()` — pushes alerts to Redis queue `ramp:watchdog:alerts` if critical/degraded
    - Implement auto-recovery: container restart on unhealthy, Docker daemon restart on unresponsive
    - Main entrypoint: load config, run checks, evaluate, exit
    - _Requirements: 2.1-2.4, 6.1-6.5, 22.5_

  - [ ]* 3.3 Write property test for watchdog check results
    - **Property 2: Component Health State Transitions**
    - **Validates: Requirements 1.5, 1.6**

  - [ ] 3.4 Create systemd unit files for watchdog
    - Create `watchdog/systemd/ramp-watchdog.timer` — OnBootSec=30, OnUnitActiveSec=30
    - Create `watchdog/systemd/ramp-watchdog.service` — Type=oneshot, TimeoutSec=25, User=root
    - Create `watchdog/systemd/ramp-telegram-bot.service` — Type=simple, Restart=always, RestartSec=10
    - _Requirements: 22.5, 22.6_

- [ ] 4. Phase 1B — Telegram bot
  - [ ] 4.1 Implement Telegram bot service (`watchdog/telegram_bot.py`)
    - Implement `TelegramBotService` class using python-telegram-bot v21+ async API
    - Implement `process_alert_queue()` — polls Redis queues `ramp:watchdog:alerts` and `ramp:agent:alerts`, delivers messages
    - Implement `verify_sender()` — checks Telegram user_id against config, silently drops unauthorized messages
    - Implement command handlers: `/status`, `/cost`, `/fleet`, `/alerts`, `/help` (read-only, query DB directly via psycopg2)
    - Implement `/approve {id}` and `/reject {id}` — write to `agent_proposals` table
    - Implement `/silence {duration}` — sets Redis key `ramp:agent:silence_until` with parsed duration (max 8h)
    - Handle unrecognized commands with error message + command list
    - Use long-polling mode (not webhook)
    - Implement retry logic: 3 retries with 30s exponential backoff for failed deliveries
    - Queue undelivered messages to local file fallback (`pending_alerts.json`)
    - _Requirements: 18.1-18.7, 5.2-5.3_

  - [ ]* 4.2 Write property test for Telegram authentication
    - **Property 10: Telegram Command Authentication**
    - **Validates: Requirements 18.7**

  - [ ]* 4.3 Write unit tests for Telegram bot commands
    - Test `/status` returns correct format with mocked DB
    - Test `/approve` and `/reject` with valid and invalid IDs
    - Test `/silence` duration parsing (30m, 2h, 8h cap)
    - Test unauthorized user_id gets no response
    - _Requirements: 18.2-18.4, 18.7_

- [ ] 5. Phase 1C — Enhanced health endpoint and pipeline liveness
  - [ ] 5.1 Enhance `/health` endpoint with agent signals
    - Modify `reddit_saas/app/routes/pages.py` (or wherever /health lives) to include `agent` block in response
    - Add fields: health_score (from Redis), last_heartbeat_at, celery_workers_online, last_scrape_at, last_pipeline_output_at, pending_alerts count, db_connections_used, redis_memory_mb
    - Read health_score from Redis key `ramp:agent:health_score` (graceful fallback to null if not set)
    - _Requirements: 1.4, 2.1, 2.5-2.7, 19.1_

  - [ ] 5.2 Implement health score computation (`reddit_saas/app/services/agent/health_score.py`)
    - Implement `compute_health_score(metrics: MetricSnapshot) -> int` with exact weights: infrastructure 40%, pipeline 35%, avatar fleet 25%
    - Infrastructure sub-scores: CPU inverted, memory inverted, disk inverted, DB pool headroom, Redis headroom, container health, worker responsiveness
    - Pipeline sub-scores: scrape freshness, scoring throughput, generation throughput, posting success rate, review queue health
    - Avatar fleet sub-scores: active ratio, frozen ratio inverted, health distribution, phase progression
    - Clamp result to [0, 100]
    - Handle missing metric sources: use last known for ≤5 min, then score 0
    - _Requirements: 1.4, 1.9_

  - [ ]* 5.3 Write property tests for health score computation
    - **Property 1: Health Score Bounded and Weighted**
    - **Validates: Requirements 1.4**
    - **Property 4: Metric Fallback with Timeout**
    - **Validates: Requirements 1.9**

  - [ ] 5.4 Implement component health state machine (`reddit_saas/app/services/agent/component_health.py`)
    - Implement `ComponentHealthTracker` — tracks pass/fail sequences per component
    - Mark "degraded" after 2 consecutive failures (within 120s of first)
    - Restore "healthy" after 3 consecutive successes while in degraded state
    - Store state in Redis keys `ramp:agent:component:{name}:status` and `ramp:agent:component:{name}:streak`
    - _Requirements: 1.5, 1.6_

  - [ ] 5.5 Implement diagnostic report generation (`reddit_saas/app/services/agent/diagnostic.py`)
    - Implement `generate_diagnostic_report(metrics: MetricSnapshot, health_score: int) -> DiagnosticReport`
    - Trigger when health_score < 70
    - List every metric contributing below-normal value, current value, normal range, weighted impact
    - Generate within 30 seconds of detection
    - _Requirements: 1.8_

  - [ ]* 5.6 Write property test for diagnostic report completeness
    - **Property 3: Diagnostic Report Completeness**
    - **Validates: Requirements 1.8**

  - [ ] 5.7 Implement pipeline liveness monitor (`reddit_saas/app/services/agent/pipeline_liveness.py`)
    - Implement `PipelineLivenessMonitor.check_stage_liveness()` — detect zero-output stages exceeding 2x cycle time
    - Implement `check_client_delivery()` — flag clients with 0 drafts for 48h while pipeline enabled
    - Stage cycle times: scraping (2x scrape_freshness_window), scoring/generation (12h), posting (10 min)
    - Return list of StalledStage dataclasses
    - _Requirements: 3.1, 3.2, 3.7_

- [ ] 6. Phase 1D — Metric collector and agent heartbeat (Celery tasks)
  - [ ] 6.1 Implement metric collector service (`reddit_saas/app/services/agent/metric_collector.py`)
    - Collect infrastructure metrics: CPU, memory, disk via psutil; Docker container status; PostgreSQL stats (pg_stat_activity, pool usage); Redis INFO; Celery inspect
    - Collect pipeline metrics: reuse queries from signal_collector (scrape freshness, scoring/generation/posting counts)
    - Collect avatar metrics: frozen count, health distribution, phase breakdown
    - Persist all metrics to `agent_metrics` table with proper category/metric_name/unit
    - Collect at 60s intervals (infrastructure), 5 min (pipeline), 15 min (avatar)
    - _Requirements: 1.1-1.3, 2.1, 2.5-2.8_

  - [ ] 6.2 Implement agent heartbeat task
    - Create heartbeat logic in metric_collector or dedicated module
    - Every 60s: check DB connectivity, Redis connectivity, task queue connectivity
    - Record AgentHeartbeat with overall_status (HEALTHY/DEGRADED/ERROR), execution_time_ms, memory_rss_mb, cpu_time_ms
    - Write `ramp:agent:heartbeat` Redis key with ISO timestamp (TTL 300s)
    - Log self-degradation warning if execution > 30s
    - Track resource consumption for 7-day rolling comparison
    - _Requirements: 22.1-22.4_

  - [ ] 6.3 Create agent Celery tasks file (`reddit_saas/app/tasks/agent.py`)
    - Register `agent_heartbeat` task (every 60s)
    - Register `agent_metric_collector` task (every 60s)
    - Register `agent_pipeline_liveness` task (every 5 min)
    - Add tasks to Celery Beat schedule in `reddit_saas/app/tasks/worker.py`
    - Ensure low priority (pipeline tasks always take precedence)
    - _Requirements: 1.1-1.3, 3.1, 22.1_

  - [ ] 6.4 Implement metric retention and aggregation
    - Daily at 01:00: roll raw samples (>24h) into 5-min averages, delete raw
    - Weekly Sunday 02:00: roll 5-min aggregates (>7d) into daily summaries, delete 5-min
    - Mark aggregated rows with `metadata_json.aggregated=true`
    - Register `agent_metric_aggregation` task in Celery Beat
    - _Requirements: 1.7_

  - [ ] 6.5 Implement self-diagnostic endpoint
    - Create `GET /api/agent/diagnostic` — returns JSON: last heartbeat timestamp, duration, metrics collection success rate (24h), alert delivery success rate (24h), action execution success rate (24h)
    - No auth required (internal monitoring endpoint)
    - _Requirements: 22.7_

- [ ] 7. Checkpoint — Phase 1 complete
  - Ensure all tests pass, ask the user if questions arise.
  - Verify: watchdog runs checks, Telegram bot delivers alerts, /health returns agent block, metrics are being collected, heartbeat writes to Redis

- [ ] 8. Phase 2A — Authority framework
  - [ ] 8.1 Implement authority framework (`reddit_saas/app/services/agent/authority_framework.py`)
    - Define `AUTHORITY_MATRIX` dict mapping action names to PermissionLevel enum (autonomous, confirmation_required, forbidden) — all entries from design
    - Implement `AuthorityFramework.get_permission(action, db)` — check DB overrides first (`agent_config` table), fall back to static matrix, default to confirmation_required for unknown actions
    - Implement `execute_if_allowed(action, db)` — validate permission, execute autonomous, propose confirmation_required, block forbidden
    - Implement `propose_action(action, db)` — create AgentProposal record with 8h expiry, push notification
    - Audit log every decision (timestamp, action_name, permission_level, entity, actor, outcome)
    - _Requirements: 15.1-15.10_

  - [ ]* 8.2 Write property tests for authority framework
    - **Property 7: Authority Classification with Default**
    - **Validates: Requirements 15.1, 15.2, 15.3, 15.4, 15.10**
    - **Property 8: Forbidden Actions Always Blocked**
    - **Validates: Requirements 15.5**
    - **Property 9: Audit Trail Completeness**
    - **Validates: Requirements 15.7**

- [ ] 9. Phase 2B — Action executor
  - [ ] 9.1 Implement action executor (`reddit_saas/app/services/agent/action_executor.py`)
    - Implement `ActionExecutor` class with handler methods:
      - `restart_celery_worker()` — restart worker process when heartbeat missing 120s
      - `freeze_avatar(avatar_id, reason)` — freeze with audit trail
      - `flush_redis_expired()` — flush expired keys when Redis memory > 90%
      - `rotate_logs()` — log rotation when disk > 85%
      - `adjust_concurrency(delta)` — increase/decrease worker concurrency (min 1, max 4)
      - `reprioritize_scrape_queue(subreddit_ids)` — move stale subreddits to front
      - `redistribute_drafts(source_avatar, targets)` — redistribute when avatar hits daily cap
      - `pause_avatar_proxy(avatar_id)` — set posting_mode to paused on proxy errors
      - `retry_failed_task(task_id)` — retry pipeline run after transient error with 5-min delay
      - `enforce_data_retention()` — archive activity_events >90d, delete orphaned threads >180d (max 1000/run)
    - Implement `execute(action)` — dispatch to handler, log ActionResult, handle rollback on failure
    - If autonomous action fails 2x consecutively: stop retrying, escalate to Platform Owner
    - Check memory after concurrency increase: revert if > 90%
    - _Requirements: 12.1-12.8, 13.1-13.6, 14.1-14.8_

  - [ ] 9.2 Implement action executor Celery task
    - Register `agent_action_executor` task (every 60s) in `reddit_saas/app/tasks/agent.py`
    - Check all recovery trigger conditions: worker heartbeat, Redis memory, container status, disk usage
    - Check pipeline management conditions: stale scrape queue, consecutive posting failures, proxy errors, daily cap redistribution
    - Check resource optimization conditions: task queue depth, idle workers, LLM latency
    - Coordinate with authority framework before each action
    - Use Redis locks `ramp:agent:lock:{action_name}` to prevent concurrent execution
    - _Requirements: 12.7, 13.1-13.6, 14.1-14.4_

  - [ ]* 9.3 Write unit tests for action executor handlers
    - Test restart_celery_worker with mocked subprocess
    - Test freeze_avatar writes correct DB records
    - Test flush_redis_expired with mocked Redis
    - Test adjust_concurrency respects min/max bounds
    - Test redistribute_drafts selects eligible target avatars
    - Test data retention processes max 1000 records
    - _Requirements: 12.1-12.5, 14.1-14.2, 14.5-14.8_

- [ ] 10. Phase 2C — Alert engine
  - [ ] 10.1 Implement alert conditions (`reddit_saas/app/services/agent/alert_conditions.py`)
    - Define all immediate alert conditions (6): pipeline_stopped, database_down, cache_down, avatar_suspended, disk_full, systemic_posting_failure
    - Define all short-term alert conditions (6): avatar_posting_failure, llm_degradation, reddit_rate_limit, task_backlog, stuck_task, pipeline_missed
    - Define all plannable alert conditions (6): cost_spike, engagement_declining, backup_overdue, elevated_freeze_rate, cert_renewal, storage_growth
    - Define all trend alert conditions (4): quality_declining, unit_economics_deteriorating, authority_growth_slowing, fleet_attrition
    - Each condition: evaluation function taking MetricSnapshot or DB session, returns Alert or None
    - _Requirements: 6.1-6.8, 7.1-7.9, 8.1-8.9, 9.1-9.6_

  - [ ] 10.2 Implement alert engine core (`reddit_saas/app/services/agent/alert_engine.py`)
    - Implement `AlertEngine` class with methods: evaluate_immediate_alerts, evaluate_short_term_alerts, evaluate_plannable_alerts, evaluate_trend_alerts
    - Implement `should_suppress(alert, db)` — check cooldown: immediate 30 min, short_term 30 min, plannable 24h, trend 7d
    - Implement `escalate_if_needed(alert, db)` — escalate severity if fired 3+ times in 24h without resolution; add "escalation_ceiling_reached" annotation if already immediate
    - Implement `deliver(alert, db)` — route to Telegram (immediate/high), hourly digest (short_term below high), daily briefing (plannable), weekly report (trend)
    - Persist alert to `agent_alerts` table with full lifecycle tracking
    - Handle Telegram delivery failure: retry 3x with 30s backoff, fall back to email
    - _Requirements: 5.1-5.10, 6.7-6.8, 7.7-7.9, 8.7-8.9_

  - [ ]* 10.3 Write property tests for alert deduplication and escalation
    - **Property 5: Alert Deduplication Respects Cooldown**
    - **Validates: Requirements 5.6, 6.7, 7.8, 8.8**
    - **Property 6: Alert Escalation on Repeated Firing**
    - **Validates: Requirements 5.8, 5.9**

  - [ ] 10.4 Implement alert engine Celery tasks
    - Register `agent_alert_evaluator` task (every 60s) — evaluates immediate + short-term conditions
    - Register `agent_plannable_alerts` task (every 60 min) — evaluates plannable conditions
    - Add to Celery Beat schedule
    - Alert evaluation must complete within 10s (timeout guard)
    - _Requirements: 6.1-6.6, 7.7, 8.7_

  - [ ] 10.5 Implement Telegram delivery service (`reddit_saas/app/services/agent/telegram_delivery.py`)
    - Implement `format_alert_message(alert: Alert) -> str` — Telegram markdown, include timestamp, severity, alert_type
    - Implement `push_to_queue(message: str, priority: str)` — LPUSH to Redis `ramp:agent:alerts`
    - Implement email fallback when Telegram fails > 30 min
    - Respect silence mode: check `ramp:agent:silence_until` key before delivery (except critical/high)
    - _Requirements: 18.1, 18.5-18.6_

- [ ] 11. Checkpoint — Phase 2 complete
  - Ensure all tests pass, ask the user if questions arise.
  - Verify: authority framework blocks forbidden actions, action executor performs recovery, alerts fire and deliver via Telegram, proposals expire after 8h

- [ ] 12. Phase 3A — Economics engine
  - [ ] 12.1 Implement economics engine (`reddit_saas/app/services/agent/economics_engine.py`)
    - Implement `compute_cost_per_client(db, date)` — query AIUsageLog, break down by: llm_scoring, llm_generation, llm_persona, llm_editing, proxy_fees, infrastructure_share (total fixed / active clients). Store to 4 decimal places.
    - Implement `compute_cost_per_avatar(db, date)` — posting cost, content generation cost, health monitoring cost per avatar
    - Implement `compute_margins(db, period)` — daily/weekly/monthly: total LLM + infra + proxy spend vs revenue (plan_type × price / days). Gross margin % rounded to 2 decimal places.
    - Implement `identify_outliers(db)` — flag clients where daily cost > 3x average, include per-category breakdown
    - Implement `compute_breakeven(db)` — min monthly revenue per client to cover variable costs (LLM + proxy)
    - Implement `get_top_expensive_operations(db)` — top 3 most expensive operation types per week
    - Mark incomplete days as "partial" with percentage of expected pipeline runs having cost records
    - _Requirements: 10.1-10.8_

  - [ ] 12.2 Implement cost optimization suggestions
    - Detect high rejection rate avatars (>50% for 7 days) → suggest reduce generation frequency
    - Detect zero-engage subreddits (14 days) → suggest deactivation
    - Detect over-cost clients (>40% of plan revenue in LLM cost) → flag for pricing review
    - Detect cheaper model opportunity (within 5pp approval rate, 100+ drafts, 14 days) → suggest switch with projected savings
    - Only emit suggestions when estimated monthly savings > $5
    - Rank suggestions by estimated dollar savings descending
    - Surface on admin dashboard + record with timestamp, entity, type, savings
    - _Requirements: 11.1-11.7_

  - [ ] 12.3 Implement economics Celery task and persistence
    - Register `agent_economics_daily` task (02:00) — runs full cost computation, persists AgentEconomicSnapshot
    - Register weekly breakeven computation (Monday 03:00)
    - Store per_client_breakdown_json and per_avatar_breakdown_json as JSONB
    - _Requirements: 10.1, 10.7_

  - [ ]* 12.4 Write unit tests for economics engine
    - Test cost_per_client with known AIUsageLog fixture data
    - Test margin calculation with known revenue/cost
    - Test outlier detection threshold (3x average)
    - Test breakeven formula
    - Test incomplete day marking
    - _Requirements: 10.1-10.5, 10.7-10.8_

- [ ] 13. Phase 3B — Silent failure detection
  - [ ] 13.1 Implement silent failure detector (`reddit_saas/app/services/agent/silent_failure_detector.py`)
    - Implement `detect_quality_drift(db)` — approval rate dropped >20pp vs 4-week avg per client
    - Implement `detect_phantom_scraping(db)` — subreddit averaged 3+ threads/scrape but returned 0 for 3 consecutive scrapes
    - Implement `detect_scoring_inflation(db)` — engage % up >15pp WoW but avg karma not increased
    - Implement `detect_stale_learning(db)` — no edit records for 14 days with ≥5 reviews
    - Implement `detect_orphaned_avatars(db)` — no pipeline activity for 7 days, not frozen, not Phase 0
    - Implement `run_all(db)` — execute all detectors, return list[Finding], record as ActivityEvent category "silent_failure"
    - _Requirements: 21.1-21.6_

  - [ ]* 13.2 Write property test for silent failure detection
    - **Property 11: Silent Failure Detection Accuracy**
    - **Validates: Requirements 21.5**

  - [ ] 13.3 Implement silent failure Celery task
    - Register `agent_silent_failures` task (03:00 daily)
    - Run all detectors, persist findings, include summary in daily ops report
    - _Requirements: 21.6_

- [ ] 14. Checkpoint — Phase 3 complete
  - Ensure all tests pass, ask the user if questions arise.
  - Verify: economics snapshot generated daily at 02:00, cost per client breakdown correct, optimization suggestions surface, silent failures detected for test data

- [ ] 15. Phase 4A — Daily briefing service
  - [ ] 15.1 Implement briefing service (`reddit_saas/app/services/agent/briefing_service.py`)
    - Implement `generate_daily_briefing(db)` — SQL-first data collection: health_score, active clients, active avatars, posts 24h, errors 24h, LLM cost 24h, revenue/cost ratio, top risk item
    - Include "top 3 actions taken" section ranked by impact (freezes > kill-switch > phase changes > posting)
    - Include up to 5 pending confirmation_required items (age-ordered) with overflow count
    - Implement "all clear" shortened briefing when zero errors/frozen/failed/pending
    - Implement `format_telegram_message(briefing)` — Telegram markdown, max 500 words (full) or 150 words (all clear)
    - Implement `deliver(message, channel)` — push to Redis alert queue, retry 3x with 60s intervals
    - _Requirements: 16.1-16.7_

  - [ ] 15.2 Register daily briefing Celery task
    - Register `agent_daily_briefing` task at 08:30 Asia/Jerusalem
    - Add to Celery Beat schedule
    - _Requirements: 16.1_

- [ ] 16. Phase 4B — Weekly report
  - [ ] 16.1 Implement weekly report generation
    - Extend `briefing_service.py` with `generate_weekly_report(db)` method
    - Week-over-week comparison: threads scraped, scored, drafts generated/approved/posted, total AI cost, active/frozen avatars — show current, previous, percentage change
    - Classify trends: "improving" (>5% favourable), "declining" (>5% unfavourable), "stable" (±5%)
    - Cost breakdown per client (sorted descending)
    - Avatar fleet status: count by phase, by health, frozen with reasons
    - Top 3 and bottom 3 avatars by posted count (not removed)
    - Economic projections: projected monthly cost (from 7d), projected margin, break-even client count
    - Recommendations section: up to 3 suggestions with affected metric and estimated improvement
    - Scaling readiness: which component hits capacity first, estimated additional clients
    - Handle <14 days history: include notice, skip WoW comparisons
    - Persist as AgentWeeklyReport (full markdown + structured JSONB fields)
    - _Requirements: 17.1-17.10_

  - [ ] 16.2 Implement trend analysis
    - Implement weekly trend scores (0-100 scale, 50=stable) for: LLM cost efficiency, pipeline throughput, avatar fleet health, client satisfaction
    - Run every Sunday 04:00 Asia/Jerusalem
    - Evaluate trend alert conditions (from Req 9): quality_declining, unit_economics_deteriorating, authority_growth_slowing, fleet_attrition
    - Skip computation if fewer than 20 data points in analysis window (log insufficient-data)
    - Register `agent_trend_analysis` task in Celery Beat
    - _Requirements: 9.1-9.6_

  - [ ] 16.3 Register weekly report Celery task
    - Register `agent_weekly_report` task — Sunday 10:00 Asia/Jerusalem
    - Deliver summary via Telegram, store full report in DB
    - _Requirements: 17.1_

  - [ ]* 16.4 Write unit tests for weekly report generation
    - Test WoW calculations with known fixture data
    - Test trend classification logic (improving/declining/stable)
    - Test insufficient data handling
    - _Requirements: 17.2-17.3, 17.10_

- [ ] 17. Phase 4C — Scaling intelligence
  - [ ] 17.1 Implement scaling intelligence (`reddit_saas/app/services/agent/scaling_intelligence.py`)
    - Implement `compute_capacity_model(db)` — estimate max clients across 5 dimensions: CPU, memory, DB connections, Reddit API rate, LLM budget
    - Per-client consumption: compute average from trailing 30 days of agent_metrics
    - Implement `project_time_to_limit(model)` — days to 90% capacity per dimension based on client growth rate (30-day delta)
    - Implement `get_scaling_playbook(dimension)` — structured entry: dimension, threshold, upgrade action, cost, capacity gain
    - Generate scaling advisory when utilization > 70% on any dimension
    - Present scaling playbook as confirmation_required action when > 80% capacity
    - Register `agent_scaling_assessment` task — Monday 03:00
    - _Requirements: 20.1-20.5_

- [ ] 18. Checkpoint — Phase 4 complete
  - Ensure all tests pass, ask the user if questions arise.
  - Verify: daily briefing delivers at 08:30, weekly report generates Sunday 10:00, trend analysis runs Sunday 04:00, scaling assessment runs Monday 03:00

- [ ] 19. Admin panel integration — routes and templates
  - [ ] 19.1 Create agent admin routes (`reddit_saas/app/routes/admin_agent.py`)
    - `GET /admin/agent` — agent overview dashboard page
    - `GET /admin/agent/health-map` — component health map (green/yellow/red/grey)
    - `GET /admin/agent/alerts` — alert history (7-day rolling)
    - `GET /admin/agent/actions` — action log (7-day rolling)
    - `GET /admin/agent/economics` — cost charts + margin
    - `GET /admin/agent/reports` — weekly reports archive
    - `GET /admin/agent/config` — configuration editor
    - `POST /admin/agent/config` — save configuration (validate values)
    - Widget endpoints (HTMX partials, polled every 60s): `/admin/agent/widget/health-score`, `/admin/agent/widget/alerts-count`, `/admin/agent/widget/actions-recent`, `/admin/agent/widget/cost-today`
    - `POST /admin/agent/proposals/{id}/approve` — approve confirmation_required action, execute within 60s
    - `POST /admin/agent/proposals/{id}/reject` — reject action
    - Require superuser on all routes
    - _Requirements: 19.1-19.7_

  - [ ] 19.2 Create agent dashboard template (`reddit_saas/app/templates/admin_agent.html`)
    - Extends `admin_base.html`
    - Health score badge (large, color-coded)
    - Active alerts count with severity breakdown
    - Last 5 autonomous actions timeline
    - Today's cost vs budget bar
    - HTMX polling every 60s for live updates
    - Link to sub-pages: health-map, alerts, actions, economics, reports, config
    - _Requirements: 19.1_

  - [ ] 19.3 Create health map template (`reddit_saas/app/templates/admin_agent_health_map.html`)
    - Grid/card layout showing all monitored components
    - Color indicators: green (>80), yellow (50-80), red (<50), grey (no data >120s)
    - Component details on click/expand: last check time, current value, trend sparkline
    - Auto-refresh via HTMX every 60s
    - _Requirements: 19.3_

  - [ ] 19.4 Create agent HTMX partials
    - Create `reddit_saas/app/templates/partials/agent/health_score.html` — score badge with color
    - Create `reddit_saas/app/templates/partials/agent/alerts_count.html` — count by severity
    - Create `reddit_saas/app/templates/partials/agent/actions_recent.html` — last 5 actions
    - Create `reddit_saas/app/templates/partials/agent/cost_today.html` — today's spend vs budget
    - Create `reddit_saas/app/templates/partials/agent/proposal_card.html` — actionable proposal with approve/reject buttons
    - _Requirements: 19.1, 19.6_

  - [ ] 19.5 Create configuration editor template and validation
    - Template: alert thresholds (numeric per metric), notification channel preferences (Telegram/email/both per severity), authority overrides (promote/demote actions)
    - Server-side validation: reject values outside metric valid ranges, reject empty required fields
    - Changes take effect within 60s (invalidate Redis-cached config)
    - _Requirements: 19.4-19.5_

  - [ ] 19.6 Create alerts page and action log templates
    - Alerts page: filterable by severity, time_horizon, status. 7-day rolling window. Resolution actions (acknowledge, resolve, mark false-positive)
    - Action log page: filterable by action_name, status. 7-day rolling window. Shows trigger, outcome, execution time
    - Economics page: daily cost chart (7d), margin chart, per-client breakdown table, optimization suggestions list
    - Reports page: list of weekly reports with view/expand
    - _Requirements: 19.2, 5.7, 8.9_

- [ ] 20. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
  - Verify complete integration: watchdog → Telegram, metrics → health score → alerts → delivery, authority → actions, economics → suggestions, briefings → Telegram, admin panel shows all data

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation between phases
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The watchdog code lives in `watchdog/` at repo root (deployed to `/opt/ramp-watchdog/` on server)
- All agent services are in `reddit_saas/app/services/agent/` package
- All agent Celery tasks consolidated in `reddit_saas/app/tasks/agent.py`
- Agent tasks use low Celery priority — pipeline tasks always take precedence
- Agent LLM usage (briefing analysis only) shares existing cost_governor $1/day budget
- Phases are independently deployable — each provides value without requiring subsequent phases
- External watchdog (Layer 1) has zero dependency on Celery/Docker — survives complete internal failure

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["3.1", "3.2", "3.4"] },
    { "id": 2, "tasks": ["3.3", "4.1"] },
    { "id": 3, "tasks": ["4.2", "4.3", "5.1", "5.2"] },
    { "id": 4, "tasks": ["5.3", "5.4", "5.5", "5.7"] },
    { "id": 5, "tasks": ["5.6", "6.1", "6.2"] },
    { "id": 6, "tasks": ["6.3", "6.4", "6.5"] },
    { "id": 7, "tasks": ["8.1"] },
    { "id": 8, "tasks": ["8.2", "9.1"] },
    { "id": 9, "tasks": ["9.2", "9.3", "10.1"] },
    { "id": 10, "tasks": ["10.2", "10.5"] },
    { "id": 11, "tasks": ["10.3", "10.4"] },
    { "id": 12, "tasks": ["12.1", "13.1"] },
    { "id": 13, "tasks": ["12.2", "12.3", "13.2", "13.3"] },
    { "id": 14, "tasks": ["12.4", "15.1"] },
    { "id": 15, "tasks": ["15.2", "16.1"] },
    { "id": 16, "tasks": ["16.2", "16.3", "16.4", "17.1"] },
    { "id": 17, "tasks": ["19.1"] },
    { "id": 18, "tasks": ["19.2", "19.3", "19.4", "19.5", "19.6"] }
  ]
}
```
