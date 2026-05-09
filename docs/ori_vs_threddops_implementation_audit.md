# Ori vs ThreddOps — Comparative Implementation Audit

**Date:** May 9, 2026  
**Method:** Direct code inspection — Ori JSON workflow nodes, ThreddOps Python services, models, tasks, routes, middleware  
**Scope:** All 9 Ori workflows vs full `reddit_saas/` codebase

---

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ EXISTS IN BOTH | Functional equivalent present in both systems |
| ⬆️ BETTER IN THREDDOPS | Present in both; ThreddOps is architecturally superior |
| 🟡 ORI ONLY | Exists in Ori; absent or stub in ThreddOps |
| 🔵 THREDDOPS ONLY | New SaaS-grade capability; no Ori equivalent |
| ❌ MISSING IN BOTH | Neither system fully solves this |

---

## 1. Subreddit Scraping Model

**Classification: ⬆️ BETTER IN THREDDOPS**

### Ori
- Each orchestrator (`Run subreddits - Cyber`) contains a hardcoded array of subreddit URLs in a static node `urls1`.
- Calls `Scrape subreddit` sub-workflow per subreddit — one HTTP call per sub-workflow execution.
- No deduplication beyond filtering posts older than 24h.
- No persistence of which subreddits are assigned to which client.
- Reddit API credentials are a single shared agency OAuth app — no isolation.
- Single client hardcoded (`XM Cyber`); no concept of multiple clients.

### ThreddOps
- `Subreddit` shared registry model (normalized, `subreddits` table, unique index on lowercase name).
- `ClientSubredditAssignment` many-to-many: multiple clients can share one subreddit without re-scraping it (`scrape_subreddit_shared` task).
- `queue_ticker.py`: continuous, priority-based scraping queue — selects the most stale subreddit each tick (60s), not a batch-at-once approach.
- `ScrapeDistributedLock` (Redis SETNX + Lua atomic release): prevents duplicate scraping of the same subreddit by concurrent Celery workers.
- `ScrapeRateLimiter` (Redis sliding window): global RPM cap across all workers, halves effective limit during backoff after 429.
- `ScrapeLog` table: records every scrape run with `posts_found`, `posts_new`, `duration_ms`, `errors`.
- PRAW-native client: official Reddit OAuth; `_log_rate_limit()` captures remaining/used/reset from auth object.

### Architectural Difference
Ori scrapes in bursts on a timer; ThreddOps scrapes continuously with admission control. At 10 clients × 10 subreddits = 100 subreddits, Ori runs 100 sequential API calls every 24h in a single n8n execution. ThreddOps spreads 100 calls over the day at ~1.7 calls/minute, eliminating Reddit API burst exposure entirely.

---

## 2. Thread Discovery & Deduplication

**Classification: ⬆️ BETTER IN THREDDOPS**

### Ori
- Deduplication: filter posts by timestamp > 24h. No persistent seen-ID store.
- If a post appears in two runs within 24h, it may be inserted twice.
- `reddit_native_id` not stored; posts cannot be reliably deduplicated across restarts.

### ThreddOps
- `reddit_native_id` (VARCHAR 255, UNIQUE) — hard constraint at DB level.
- In-memory `existing_ids` set built per-task from DB before scraping; O(1) membership check before insert.
- `is_locked` field on `RedditThread`: thread liveness is tracked (`thread_liveness.py`). Locked/removed/archived threads are flagged and skipped in generation.
- `STALE_THREAD_HOURS = 12`: threads older than 12h get a liveness check before LLM calls are attempted.
- Indexed: `ix_reddit_threads_subreddit_not_locked` (partial), `ix_reddit_threads_scraped_at` (partial on non-locked).

---

## 3. Qualification / Scoring

**Classification: ⬆️ BETTER IN THREDDOPS**

### Ori (`Run subreddits - Cyber`)
- Single LLM call: Gemini Flash or Grok via OpenRouter.
- Returns `alert`, `tag` (engage/monitor/skip), `composite`.
- Result stored directly on thread row in `XM_Cyber_Reddit` table.
- No structured schema validation on LLM output.
- Prompt is hardcoded as a node parameter inside the JSON workflow.
- No retry on bad LLM output.

### ThreddOps
- `scoring.py`: `SCORING_PROMPT` (system prompt) + structured user message with subreddit/post/comments.
- `ScoringOutput` Pydantic schema validation on LLM response.
- `ThreadScore` model: per-client scoring record (separate from thread), supports multiple clients scoring the same thread differently.
- 4-dimension scoring: relevance (0–3), quality (0–3), strategic (0–3), intent classification, composite (0–9).
- Override rule: if company or competitor mentioned AND relevance ≥ 2 → force `alert: true, tag: engage`.
- Retry: `score_threads` Celery task has `max_retries=3` with exponential backoff (60s × 2^retry).
- `is_pipeline_enabled` gate check before any scoring runs.
- Activity event recorded per scoring run with tag distribution counts.
- `dry_run.py`: operator can walk any thread through scoring interactively (renders prompts, accepts pasted LLM output) without triggering real LLM costs.

### Architectural Difference
Ori stores scores monolithically on the thread row. ThreddOps stores `ThreadScore` as a child record per client, enabling one thread to be scored independently for each client context — essential for multi-tenant SaaS where clients share subreddits.

---

## 4. Avatar / Persona Matching

**Classification: ⬆️ BETTER IN THREDDOPS**

### Ori (`XM Cyber _ Write comments`)
- `decide_persona` node: LLM call with list of Airtable personas.
- Personas fetched dynamically from Airtable for each generation run.
- No subreddit-specific karma weighting in persona selection.
- No isolation check — any persona could theoretically be selected for any client.
- Mode selection: `bullseye | helpful_peer | karma_only`.

### ThreddOps
- `select_persona()` in `generation.py`.
- `karma_tracker.get_karma_in_subreddit()`: each avatar's per-subreddit karma is fetched and injected into the persona selection prompt. Avatars sorted descending by subreddit karma before LLM sees them.
- **Isolation assertion** (runtime enforcement): `assert avatar.client_ids and str(client.id) in avatar.client_ids` — raises immediately if cross-client contamination occurs.
- `Avatar.client_ids` is a Postgres `ARRAY(String)` — an avatar can serve multiple clients explicitly, but not implicitly.
- Mode selection preserved: `bullseye | helpful_peer | karma_only`.
- Subreddit karma surfaced to LLM as `{ subreddit, comment_karma, post_karma, total }` — explicit ranking signal.

---

## 5. AI Generation (Comment & Post)

**Classification: ⬆️ BETTER IN THREDDOPS**

### Ori
- Comment generation: `expert_redditor_comments` → LLM → `expert_redditor_comments1` (edit pass).
- Two-pass: generate then edit. Prompts hardcoded in n8n nodes.
- No cost tracking per operation.
- No model selection by task type (same model for all).
- Post creation: single-step with `news_scrape` as source (internal agency table).
- Hobby comments: single-pass via Claude Opus.
- No duplicate-prevention across runs (relies on 20-comment history lookup in Airtable).

### ThreddOps
- `generation.py`: `select_persona()` → `generate_comment()` → `edit_comment()` (three distinct LLM calls).
- `ai.py` (LiteLLM wrapper): model routing by task type — cheap model (Haiku/Flash) for scoring, better model for generation/editing.
- `AIUsageLog` table: every LLM call logged with `operation`, `model`, `input_tokens`, `output_tokens`, `cost_usd`, `duration_ms`, `triggered_by`.
- Model cost table in code: `MODEL_COSTS` dict maps model → input/output $/M tokens — updated as prices change.
- `ai_trigger_context` (`ContextVar`): propagates `"scheduler" | "manual" | "orchestrator"` to all log entries automatically.
- LiteLLM timeout: 60s hard cap — prevents hung provider from blocking a Celery worker indefinitely.
- `post_generation.py`: separate service for post drafts with `PostDraft` model.
- `learning_loop.py`: human edits on `AnalysisEditRecord` stored for future few-shot injection.

---

## 6. Approval Workflow

**Classification: ⬆️ BETTER IN THREDDOPS**

### Ori
- Comments saved to Airtable via `Create a record` node.
- Human reviews in Airtable Interface (manually built).
- `comment_sent` checkbox triggers `Update comment sent` webhook → moves record to tracking table.
- No status machine — it's a binary checkbox, not a state flow.
- No edit history.
- Posting is entirely manual: human logs into Reddit account and types.

### ThreddOps
- `CommentDraft` model: `status` field with explicit state machine: `pending → approved → rejected | posted`.
- `review.py` route: `PATCH /review/comments/{id}` with whitelist validation on status transitions.
- `edited_draft` field: human can edit text in-app before approval.
- `posted_at` timestamp set on transition to `posted`.
- Audit log entry on every status change (who changed it, when).
- `record_activity_event()` for every review action.
- `PostDraft` model: parallel state machine for post drafts.
- Karma tracking triggered on `→ posted` transition: `record_comment_score()` called immediately.
- Partial index `ix_comment_drafts_thread_pending` — pending drafts fast lookup.

---

## 7. Audit Logging

**Classification: 🔵 THREDDOPS ONLY**

### Ori
- No structured audit log. Airtable records contain created/updated timestamps, but no actor, no action type, no change history.
- The `Update comment sent` webhook moves records but doesn't log who triggered it or when.

### ThreddOps
- `AuditLog` model: `user_id`, `action`, `entity_type`, `entity_id`, `client_id`, `details` (JSONB).
- `log_action()`: human admin actions.
- `log_system_action()`: background task actions (no user).
- `query_audit_logs()`: paginated, filterable by user, client, action, entity_type, free-text search in JSONB, date range.
- Every admin action (create/update/deactivate client, trigger pipeline, approve comment) creates an audit entry.
- Pipeline errors create system audit entries with truncated error details.
- Immutable: no update/delete on audit rows.

---

## 8. Queue Orchestration

**Classification: ⬆️ BETTER IN THREDDOPS**

### Ori
- Orchestration: `Run subreddits - Cyber` is a manual/scheduled n8n workflow that iterates subreddits serially via `Split Out` → `Call sub-workflow` → `Aggregate`.
- No parallel execution; n8n executes nodes sequentially within a workflow.
- Orchestrator calls sub-workflows synchronously — if one subreddit fails, the error propagates.
- No independent retry per subreddit.

### ThreddOps
- Celery task queue: `scraping.py`, `ai_pipeline.py`, `orchestrator.py` all dispatch async tasks.
- `orchestrator.py`: `run_full_pipeline_all_clients` iterates all active clients and dispatches a Celery chain per client: `score_threads.si | generate_comments.si | generate_posts.si`. Each chain runs independently — one client failure doesn't block others.
- `run_hobby_pipeline_all_avatars`: per-avatar chains dispatched independently.
- `queue_ticker`: continuous scraping at `queue_tick` every 60s (Celery Beat), priority-based (most stale subreddit first).
- Worker concurrency configurable: `--concurrency=4` in docker-compose.
- Queue depth, stale counts, processing speed all exposed in `scrape_queue.py` dashboard service.

---

## 9. Retry / Failure Handling

**Classification: ⬆️ BETTER IN THREDDOPS**

### Ori
- No retry logic. If an n8n node fails, the execution fails.
- n8n has built-in retry on HTTP errors, but it's not configured in these workflows.
- Failed executions visible in n8n UI but not logged to a DB.

### ThreddOps
- `score_threads` Celery task: `bind=True, max_retries=3`, exponential backoff `60s × 2^retry`.
- `generate_comments`: same retry policy.
- LiteLLM timeout (60s): prevents zombie workers on hanging API calls.
- Exception in one client's pipeline chain is caught and logged; other clients continue.
- Exception in one subreddit scrape: logged to `ScrapeLog.errors`, task continues with next subreddit.
- System error activity event written to DB on pipeline failures.
- Audit log entry created for every task-level error.
- `is_pipeline_enabled` and `is_generation_enabled` settings: operator can kill pipeline without restarting workers.

---

## 10. Anti-Spam / Safety

**Classification: 🔵 THREDDOPS ONLY (no Ori equivalent)**

### Ori
- No safety layer. The only protection is the human review in Airtable.
- Comment frequency not tracked — theoretically unlimited comments per avatar per day.
- No brand-mention ratio enforcement.
- No link frequency limits.
- No shadowban detection.

### ThreddOps (`safety.py`, `phase.py`)

**Rate Limits (enforced in code):**
- `MAX_COMMENTS_PER_DAY = 8` per avatar
- `MAX_PROFESSIONAL_PER_DAY = 5`
- `MAX_HOBBY_PER_DAY = 5`
- `MIN_MINUTES_BETWEEN_COMMENTS = 15`
- `MAX_COMMENTS_PER_SUBREDDIT_DAY = 2` (no subreddit domination)
- `MAX_LINKS_PER_WEEK = 1`
- `MAX_COMMENT_LENGTH = 500` characters
- `BRAND_MENTION_COOLDOWN_HOURS = 72`
- `MAX_BRAND_RATIO = 0.30` (30% of weekly comments max)

**Phase Policy (`phase.py`):**
- 3-phase warming system: Phase 1 (new avatar, hobby only), Phase 2 (limited professional), Phase 3 (full professional + links).
- `PhasePolicy.classify_brand_mention()`: regex detects explicit brand links vs. brand name mentions — different severity levels.
- `PhaseEvaluator.should_piggyback()`: phase promotion/demotion evaluated lazily on next safety check, no extra scheduled call needed.
- `PhaseTransitionLock`: prevents concurrent phase transitions on the same avatar.
- Policy block events logged as `ActivityEvent` type `policy_block`.

**Shadowban Detection (`health_checker.py`):**
- Profile accessibility check via unauthenticated PRAW.
- Comment visibility ratio check via unauthenticated HTTP scrape.
- `HealthCheckResult` dataclass: `visibility_ratio`, `comments_sampled`, `comments_visible`, `detection_method`.
- Auto-updates `avatar.health_status`, `avatar.is_shadowbanned`.
- `consecutive_check_failures` counter: distinguishes transient API errors from actual bans.

---

## 11. Scaling Model

**Classification: 🔵 THREDDOPS ONLY**

### Ori
- Hard-coded to one client (`XM Cyber`). Client ID appears literally in SQL queries.
- Adding a second client requires duplicating all workflows and all credentials.
- n8n worker is single-instance; no horizontal scaling.
- Airtable tables are shared across all clients with no row-level isolation.

### ThreddOps
- `Client` model with `is_active` flag: unlimited clients in DB.
- Celery worker horizontal scaling: add workers by scaling the `celery` Docker service (`--concurrency=N` per worker + N workers).
- Scrape queue is shared and prioritized by staleness — new clients automatically participate.
- `ClientSubredditAssignment`: one subreddit scraped once, scored separately per client. At 10 clients × 5 shared subreddits: 10× cost reduction on scraping vs. Ori.
- Redis: stateless rate limiting and distributed locking work across any number of workers.
- `is_pipeline_enabled` / `is_generation_enabled` / `scrape_enabled`: per-system toggles via `system_settings` table — operator can pause specific stages without code changes.

---

## 12. Multi-Client Isolation

**Classification: 🔵 THREDDOPS ONLY**

### Ori
- No isolation. All avatars can be used for any client.
- DB rows have no `client_id` partitioning (single-client system).
- Airtable has no row-level security.

### ThreddOps
- `client_id` foreign key on: `RedditThread`, `CommentDraft`, `PostDraft`, `ThreadScore`, `AIUsageLog`, `ActivityEvent`, `AuditLog`, `ScrapeLog`.
- `Avatar.client_ids` (ARRAY): explicit allowlist — avatar cannot appear in another client's pipeline.
- Runtime assertion in `select_persona()` raises immediately on context isolation violation.
- `require_superuser` dependency: all admin routes protected; no client can access another's data via UI.
- `AIUsageLog.client_id`: costs attributable per client — basis for SaaS billing.
- All admin dashboard queries filter by `client_id`; no cross-client data leakage in UI.

---

## 13. Analytics

**Classification: ⬆️ BETTER IN THREDDOPS**

### Ori
- Analytics = Airtable views and formulas. No computed metrics. No funnel view.
- No AI cost attribution. No per-subreddit performance data.

### ThreddOps
- `transparency.py`: `get_pipeline_stats()` — threads (total/24h/7d), tags (engage/monitor/skip/unscored), drafts by status, AI costs (total + by operation).
- `inspector.py`: pipeline funnel visualization — 7 stages (Scraped → Scored → Engage → Generated → Pending → Approved → Posted) with conversion rates between adjacent stages.
- `subreddit_intel.py`: per-subreddit analytics — total/7d threads, comment counts by status, avg score, avatar performance, scrape history.
- `operations_dashboard.py`: top metrics bar, client status cards, scrape freshness, run history.
- `topology.py`: 9-node pipeline topology with state (idle/running/success/warning/error/stale), 24-bucket hourly timelines, forecast of next scheduled run.
- `keyword_analytics.py`: keyword tracking service.
- `reddit_profile_analytics.py` + `profile_analytics.py`: per-avatar Reddit profile stats.

---

## 14. Cost Tracking

**Classification: 🔵 THREDDOPS ONLY**

### Ori
- No cost tracking. OpenRouter usage is paid globally with no per-client attribution.

### ThreddOps
- `AIUsageLog` table: every LLM call → `operation`, `model`, `input_tokens`, `output_tokens`, `cost_usd` (Decimal, 6 decimal places), `duration_ms`, `triggered_by`.
- `MODEL_COSTS` dict: per-model input/output $/M token pricing — updated in code as prices change.
- Cost summed per client in `get_pipeline_stats()` and `get_top_metrics()`.
- `triggered_by` context variable: distinguishes scheduler vs. manual vs. orchestrator calls — enables cost attribution by trigger source.
- AWS Bedrock model variants in `MODEL_COSTS`: foundation for routing to lower-cost providers.
- `shadowban detection` comment in `orchestrator.py` shows explicit cost-savings accounting: "each shadowbanned avatar skipped saves ~$0.90/day".

---

## 15. Moderation / Admin Tooling

**Classification: 🔵 THREDDOPS ONLY (largely)**

### Ori
- Admin = Airtable UI (manually built via Airtable Interfaces — separate doc required).
- No unified admin panel.
- No pipeline control toggles.
- No avatar status management beyond Airtable checkboxes.

### ThreddOps (`admin.py` route, 30+ endpoints)
- Full admin panel at `/admin/` (FastAPI + Jinja2, dark Tailwind theme).
- Client CRUD: create/edit/deactivate with full company profile, keywords, worldview, ICP.
- Avatar management: list, create, edit, freeze/unfreeze, subreddit assignments.
- Subreddit management: add/remove per client, activate/deactivate.
- Pipeline controls: `pipeline_enabled`, `generation_enabled`, `scrape_enabled` toggles in UI.
- Dry-run mode: inspect prompts, simulate scoring without LLM calls.
- `MetricsCollector`: gauge colors, real-time metrics bar.
- Queue dashboard: depth, stale count, processing speed, rate limiter utilization, ETA.
- Audit log UI: paginated, searchable, filterable.
- Avatar wizard (7-step onboarding for new client).

---

## 16. Reputation / Warmup Systems

**Classification: ⬆️ BETTER IN THREDDOPS**

### Ori
- Hobby subreddits assigned per avatar in Airtable.
- `Hobby Comment Writing` workflow: generates karma-building comments on hobby threads.
- No phase system — all avatars treated equally regardless of account age/karma.
- No tracking of karma gain per subreddit.
- No automatic phase progression.

### ThreddOps
- `Avatar.warming_phase` (1–3): explicit phase with `phase_changed_at`, `last_phase_evaluated_at`.
- `PhasePolicy`: per-phase rules enforced on every comment attempt (not advisory).
- `SubredditKarma` model: `avatar_id + subreddit_name` → `comment_karma`, `post_karma`, `comment_count`, `previous_comment_karma`, `previous_post_karma`.
- `karma_tracker.py`: records comment score events, reconciles with Reddit API, classifies subreddit as professional/hobby.
- `karma_history.py`: time-series karma snapshots.
- `karma_feedback.py`: feedback loop from posted comments to karma records.
- `AvatarSubredditPresence` model: tracks avatar's observed presence in each subreddit.
- `presence.py`: scans subreddit threads for avatar activity, updates presence table.
- `PhaseEvaluator.evaluate()`: computes promotion/demotion eligibility based on karma, post history, age — runs lazily on safety check piggyback.

---

## 17. Scheduling

**Classification: ⬆️ BETTER IN THREDDOPS**

### Ori
- Scheduling: n8n schedule triggers. `XM Cyber — Reddit Post Creation` has 8am/2pm schedule nodes.
- Manual trigger and webhook trigger also available.
- No global enable/disable for schedules.
- No visibility into next scheduled run.

### ThreddOps (`worker.py` Celery Beat schedule)
- Morning pipeline: 8:00 UTC — score + generate.
- Afternoon pipeline: 14:00 UTC — score + generate.
- Hobby pipeline: 10:00 UTC — all avatars.
- Avatar health check: 7:30, 13:30 UTC.
- Phase evaluation: 6:00 UTC daily.
- Karma tracking: every 4h (at :15).
- Shadowban check: runs before AI pipeline (flagged avatars excluded from expensive LLM calls).
- `queue_tick`: every 60s (scraping).
- All schedules visible in ops dashboard `_SCHEDULE_ENTRIES` with human labels and "next run" forecasts.
- `scrape_enabled`, `pipeline_enabled`, `generation_enabled`: operator can pause specific stages without stopping Beat.

---

## 18. Operational Transparency

**Classification: 🔵 THREDDOPS ONLY**

### Ori
- Transparency = n8n execution log (exists but is raw JSON, not operator-friendly).
- No dashboard showing pipeline health.
- No activity feed.

### ThreddOps
- `ActivityEvent` model: typed events (`scrape`, `score`, `generate`, `review`, `system`, `policy_block`) with message + JSONB metadata.
- Activity feed at `/admin/activity-feed` (HTMX partial, auto-refreshes).
- Per-client transparency page: scrape freshness, comment stats, AI costs.
- `topology.py`: 9-node pipeline topology diagram with live state and hourly timelines.
- `operations_dashboard.py`: unified daily ops view — all clients, avatar health, schedule forecast.
- `ScrapeLog`: per-subreddit scrape history with timing and error details.
- Heartbeat task (`heartbeat.py`): periodic liveness ping for monitoring.
- `health_metrics.py`: aggregated health metrics for the ops bar.

---

## 19. Infrastructure Readiness

**Classification: ⬆️ BETTER IN THREDDOPS**

### Ori
- Infrastructure: n8n self-hosted (or n8n.cloud). No containerization defined.
- Database: Supabase (managed PostgreSQL). No migration system beyond manual SQL.
- No Redis. No task queue.
- Single-process execution.
- Credentials: hardcoded in n8n credential store per-instance.

### ThreddOps
- `Dockerfile`: non-root `appuser`, minimal `python:3.11-slim` base, `pip install` from `pyproject.toml`.
- `docker-compose.yml`: `app` + `celery` + `celery-beat` + `db` (Postgres 16-alpine) + `redis` (7-alpine with password + maxmemory LRU policy).
- Health checks on all services (`pg_isready`, `redis-cli ping`) with `depends_on.condition: service_healthy`.
- `entrypoint.sh`: runs Alembic migrations then starts server — zero-downtime migration on container restart.
- Ports: Postgres and Redis NOT exposed to host in production config (internal Docker network only).
- Alembic: versioned migrations in `alembic/versions/` — schema changes are tracked, reversible.
- `pyproject.toml`: dependency pinning, reproducible builds.
- `logs/` with daily rotation (`app.log.{date}` pattern visible in repo).

---

## 20. AWS Readiness

**Classification: ⬆️ BETTER IN THREDDOPS (partial)**

### Ori
- Zero AWS readiness. Entire system runs on n8n + Supabase. No AWS services referenced.

### ThreddOps
- `MODEL_COSTS` includes `bedrock/anthropic.claude-sonnet-4-20250514-v1:0` and `bedrock/anthropic.claude-3-5-haiku-20241022-v1:0` — Bedrock routing prepared in LiteLLM wrapper.
- Docker containers are ECS/EKS-ready (non-root user, health check endpoints, env-file config).
- Redis can be swapped for ElastiCache (connection string in env var).
- PostgreSQL can be swapped for RDS (connection string in env var).
- `aws_cost_estimate.md` and `aws_budget_may2026.md` exist in `docs/` — infrastructure planning has been done.
- `adr_sqs_valkey_migration.md`: Architecture Decision Record for migrating from Redis to SQS/Valkey — documented but not yet executed.
- **Gap:** No SQS integration yet. Celery still uses Redis as broker. ADR is planned, not implemented.
- **Gap:** No S3 integration. No CloudWatch metrics export. No IAM roles defined.

---

## 21. Reddit API Efficiency

**Classification: ⬆️ BETTER IN THREDDOPS**

### Ori
- Reddit API: agency OAuth app (shared credential). No rate limit tracking visible in code.
- Comment tree fetching: recursive sub-workflow (`Reddit _ Comments _ Official`) — each level is a separate API call.
- All subreddits fetched in one burst when orchestrator runs.
- No awareness of Reddit's 60 req/min limit.
- `scrape subreddit` workflow: fetches posts + comments in series.

### ThreddOps
- `ScrapeRateLimiter`: global sliding window (60s) across all Celery workers — enforces RPM ceiling set in `system_settings`.
- `_log_rate_limit()`: reads PRAW's internal rate limiter state after every scrape call and logs remaining/used/reset.
- Backoff mode: after 429, effective limit halved automatically until backoff expires.
- `check_thread_liveness()`: single PRAW call to check if thread is locked/removed/archived — avoids attempting to fetch full comment tree for dead threads.
- `scrape_subreddit()`: skips stickied posts, tracks `skipped_stickied`, `skipped_old`, `skipped_locked` metrics.
- `deduplicate_posts()`: filters already-known `reddit_native_id` before ANY data processing.
- `reddit_freshness.py`: freshness guards prevent redundant API calls in <6h windows for manual actions.

---

## Summary Matrix

| Capability | Classification | Ori | ThreddOps |
|------------|---------------|-----|-----------|
| Subreddit scraping | ⬆️ BETTER IN THREDDOPS | Burst, per-client hardcoded | Continuous queue, shared registry, distributed lock |
| Thread deduplication | ⬆️ BETTER IN THREDDOPS | 24h time filter only | DB-level UNIQUE + in-memory set + liveness tracking |
| Thread scoring | ⬆️ BETTER IN THREDDOPS | Single LLM, monolithic row | Per-client ThreadScore, Pydantic validation, retry |
| Avatar/persona matching | ⬆️ BETTER IN THREDDOPS | Airtable lookup, no karma weighting | Subreddit karma ranking + isolation assertion |
| AI generation | ⬆️ BETTER IN THREDDOPS | 2-pass, one model | 3-pass, model routing, cost tracking, learning loop |
| Approval workflow | ⬆️ BETTER IN THREDDOPS | Airtable checkbox | State machine, edit history, audit trail |
| Audit logging | 🔵 THREDDOPS ONLY | None | AuditLog table, system/human actions, searchable |
| Queue orchestration | ⬆️ BETTER IN THREDDOPS | Serial n8n execution | Celery chains, independent per-client/avatar |
| Retry/failure handling | ⬆️ BETTER IN THREDDOPS | None | max_retries=3, exponential backoff, error events |
| Anti-spam/safety | 🔵 THREDDOPS ONLY | None | Rate limits, phase policy, brand ratio enforcement |
| Shadowban detection | 🔵 THREDDOPS ONLY | None | Visibility ratio check, health status, auto-quarantine |
| Scaling model | 🔵 THREDDOPS ONLY | Single-client hardcoded | Multi-client, horizontal Celery scaling |
| Multi-client isolation | 🔵 THREDDOPS ONLY | None | client_id on all models, runtime assertion |
| Analytics | ⬆️ BETTER IN THREDDOPS | Airtable views | Pipeline funnel, subreddit intel, topology, costs |
| Cost tracking | 🔵 THREDDOPS ONLY | None | AIUsageLog, per-client attribution, Bedrock pricing |
| Admin tooling | 🔵 THREDDOPS ONLY (largely) | Airtable UI | Full admin panel, 30+ endpoints, wizard |
| Warmup/reputation | ⬆️ BETTER IN THREDDOPS | Hobby posts, no phases | 3-phase system, SubredditKarma, PhaseEvaluator |
| Scheduling | ⬆️ BETTER IN THREDDOPS | n8n schedule nodes | Celery Beat, 6 jobs, toggleable per-stage |
| Operational transparency | 🔵 THREDDOPS ONLY | n8n execution log | ActivityEvent feed, topology, ops dashboard |
| Infrastructure readiness | ⬆️ BETTER IN THREDDOPS | No containerization | Docker Compose, Alembic, health checks, non-root |
| AWS readiness | ⬆️ BETTER IN THREDDOPS (partial) | Zero | Bedrock routes prepared, ADR for SQS, not yet implemented |
| Reddit API efficiency | ⬆️ BETTER IN THREDDOPS | No rate control | Sliding window RPM, backoff, liveness guard, freshness cache |
| Dry-run / preview | 🔵 THREDDOPS ONLY | None | Dry-run mode: step through any thread with manual LLM |
| Thread liveness | 🔵 THREDDOPS ONLY | None | is_locked detection, stale check before generation |
| Distributed lock | 🔵 THREDDOPS ONLY | None | Redis SETNX + Lua atomic release per subreddit |
| Hobby karma tracking | ✅ EXISTS IN BOTH | Airtable tracking | SubredditKarma model, karma_tracker service |
| Post creation | ✅ EXISTS IN BOTH | From news_scrape | From reddit_threads (PostDraft model, stub pipeline) |

---

## Architectural Differences: Key Themes

### 1. Stateless Workflow vs. Stateful Application
Ori is a collection of stateless n8n workflows that read from and write to Airtable/PostgreSQL. There is no persistent in-process state. Every run starts fresh.

ThreddOps is a stateful application with a persistent DB schema, versioned migrations, typed ORM models, and background workers that maintain continuity between runs. Phase state, karma history, subreddit freshness, and distributed locks all depend on this persistent state.

### 2. Client-Scoped vs. Single-Client
Ori was built for one client. Every table name, SQL query, and credential references `XM Cyber` explicitly. Adding Client B requires forking the entire system.

ThreddOps is designed with `client_id` as a first-class concept across every model. The same infrastructure serves all clients simultaneously with enforced isolation.

### 3. n8n Pull vs. Celery Push
Ori: n8n schedule fires → workflow pulls data → processes in series → writes results. One execution per schedule run.

ThreddOps: Celery Beat fires tasks → tasks dispatch work → independent workers process in parallel → results written async. Failed tasks retry independently without affecting sibling tasks.

### 4. Manual Safety vs. Systematic Safety
Ori relies entirely on the human reviewer in Airtable to prevent unsafe behavior. No code enforces comment frequency, brand ratio, or phase restrictions.

ThreddOps enforces safety at the code level: `check_avatar_can_post()` is called before every comment enters the generation pipeline. A blocked comment never reaches LLM — saving cost and preventing the draft from existing at all.

---

## Operational Implications

| Implication | Ori | ThreddOps |
|-------------|-----|-----------|
| Adding a new client | Duplicate all workflows + credentials | Insert `Client` row + assign subreddits |
| One subreddit goes down | Manual investigation | `ScrapeLog.errors` + stale count dashboard |
| Avatar gets shadowbanned | Discovery lag: days/weeks | Detected within 6–12h, auto-flagged |
| Posting too much | Human reviewer catches it | Blocked at `check_avatar_can_post()` before LLM call |
| Cost spike | No visibility | `AIUsageLog` → per-client cost breakdown in dashboard |
| LLM provider is down | Workflow execution fails | Celery task retries 3× with exponential backoff |
| Reddit API 429 | Workflow fails, manual retry | Rate limiter halves effective RPM, backoff mode |
| Schema change needed | Manual SQL, high risk | `alembic revision --autogenerate` + migration |

---

## Scalability Implications

| Dimension | Ori Ceiling | ThreddOps Ceiling |
|-----------|------------|-------------------|
| Clients | 1 (hardcoded) | Unlimited (DB rows) |
| Subreddits | ~10-20 (serial burst) | Hundreds (queue, priority, shared registry) |
| Avatars | ~5-10 (Airtable rows) | Unlimited (DB rows, per-avatar phase tracking) |
| Throughput | Single n8n thread | Celery workers × concurrency (horizontal) |
| Failure isolation | None — one failure kills the run | Per-client, per-task — independent retry |
| Reddit API saturation | Uncontrolled | Enforced RPM ceiling + backoff |
| Cost growth | Linear, untracked | Linear, tracked per client, alertable |

---

## Compliance / Safety Implications

| Risk | Ori Exposure | ThreddOps Exposure |
|------|-------------|-------------------|
| Avatar ban (posting too fast) | High — no rate limits in code | Low — enforced 8/day max, 15-min gap |
| Subreddit domination detection | High — same avatar posts unlimited | Low — max 2/day per subreddit |
| Brand spam detection | High — no ratio enforcement | Low — 30% brand ratio ceiling, 72h cooldown |
| Cross-client data leakage | N/A (single client) | Low — runtime assertion + client_id partitioning |
| Shadowban propagation | High — detected manually | Low — 6–12h detection, auto-quarantine |
| Audit trail for compliance | None | Full AuditLog with actor, action, timestamp |
| Phase 1 avatar brand-posting | Not controlled | Blocked by PhasePolicy at Phase 1 |

---

## Critical Missing Systems Before First Paying Clients

These are gaps where the current ThreddOps code is either a stub, missing entirely, or not production-ready — and their absence directly blocks commercial deployment.

### 1. Post Generation Pipeline (STUB)
**Location:** `services/post_generation.py`, `tasks/ai_pipeline.py:generate_posts`  
`generate_posts` task exists and is called by the orchestrator chain, but `post_generation.py` is either a stub or incomplete. `PostDraft` model exists. The source-material selection, brief generation, and post-to-subreddit routing are not production-ready.  
**Impact:** Clients cannot receive original post drafts — only comment drafts.

### 2. Reddit Posting Automation (Intentionally Missing — Needs UI)
**Status:** By design, posting is manual. Human copies text from admin UI and posts to Reddit manually.  
**Gap:** There is no `reddit_comment_url` population mechanism — the field exists on `CommentDraft` but is only populated externally. There is no way for the human to record the actual Reddit URL of a posted comment from within the app.  
**Impact:** Karma tracking (via `reddit_score`) never gets real feedback because there's no closed loop. `SubredditKarma` depends on `reddit_score` being populated post-posting.

### 3. Notification System (Missing)
**Status:** No email, Slack, or push notification when a comment draft is generated.  
**Ori had:** Pushover push notifications via the `Push a message4` node.  
**Impact:** Human reviewers must poll the Airtable/admin UI manually. Approved comments will pile up or expire without someone actively watching.

### 4. SQS / Persistent Task Queue (ADR Written, Not Implemented)
**Status:** `adr_sqs_valkey_migration.md` exists but Celery still uses Redis as broker.  
**Risk:** Redis task queue is not durable — tasks in flight are lost on Redis restart. For production with real clients, a durable queue (SQS or RabbitMQ) is needed.  
**Impact:** Any Redis failure drops all queued tasks silently.

### 5. Billing / Client Invoicing (Missing)
**Status:** `AIUsageLog` exists and cost tracking is implemented. But there is no billing model, invoice generation, or Stripe integration.  
**Impact:** Cannot charge clients — the business model has no collection mechanism.

### 6. Persona CRUD (Missing UI, TODO listed)
**Status:** `Avatar` model stores `voice_profile_md`, `tone_principles`, `speech_patterns`, etc. But there is no admin UI to edit persona configuration after initial seed.  
**Impact:** Client persona onboarding requires direct DB access or a developer.

### 7. Redraft / Regenerate (Missing, TODO listed)
**Status:** No "regenerate this comment" button on review page.  
**Impact:** If a generated comment is bad, reviewer must reject it and wait for the next pipeline run (8am or 2pm) to get a new draft. No real-time iteration possible.

### 8. Shadowban Auto-Quarantine Notification (Partially Wired)
**Status:** `check_all_avatars_health` logs a warning but does NOT call `quarantine_avatar()` automatically. Comment in orchestrator: "Don't quarantine, just log — human decides."  
**Impact:** A shadowbanned avatar continues to have comments drafted and approved (LLM cost is spent) until a human notices the warning in the logs.

### 9. Real Integration Tests (Auth Flow)
**Status:** 60 tests pass but most use mocked auth middleware. No tests that exercise real JWT cookie creation → protected route flow.  
**Impact:** Auth bugs in production cannot be caught by CI.

### 10. Tracking / Published Comments History Page (Missing, TODO listed)
**Status:** `comment_drafts` with `status=posted` + `posted_at` exists in DB. No UI page showing published history, karma gained, or performance metrics.  
**Impact:** Clients have no visibility into what has been posted on their behalf.

---

## What ThreddOps Already Does Better Than Ori Structurally

### 1. Shared Subreddit Registry
Single scrape serves multiple clients. Ori duplicates every API call per client. At 3 clients × 10 subreddits, ThreddOps makes 10 API calls where Ori makes 30. This directly reduces Reddit API ban risk and infrastructure cost.

### 2. Phase-Gated Safety by Default
In Ori, a brand-new avatar can post brand-adjacent professional comments on Day 1. ThreddOps blocks this at Phase 1 in code — not as a guideline, but as an enforced policy that raises a `SafetyCheckResult(False)` before any LLM call is made.

### 3. Per-Client Cost Attribution
Every LLM call in ThreddOps is tagged with `client_id`, `operation`, `model`, `triggered_by`. Ori has no cost visibility. ThreddOps already has the data structure to generate per-client monthly invoices from `AIUsageLog`.

### 4. Versioned Database Schema
Ori has no migration system — schema changes require manual SQL on Supabase. ThreddOps uses Alembic with timestamped migration files. Schema changes are code-reviewed, reversible, and applied automatically on container restart via `entrypoint.sh`.

### 5. Distributed Locking for Concurrent Workers
Ori cannot horizontally scale — n8n is single-instance per workflow execution. ThreddOps can run N Celery workers simultaneously with no subreddit duplication because `ScrapeDistributedLock` (Redis SETNX + Lua atomic release) guarantees exactly-once scraping per subreddit per tick.

### 6. Thread Liveness Awareness
Ori generates comments on threads regardless of lock/removal status. ThreddOps checks `is_locked` before any LLM call, preventing wasted generation on threads where a comment can never be posted.

### 7. Operational Observability Without External Tools
Ori requires n8n execution logs + Airtable views to understand system state. ThreddOps has a built-in ops dashboard with topology nodes, activity feed, pipeline funnel, scrape queue depth, and avatar health — all in the admin panel. No external BI tool required.

### 8. Subreddit-Specific Karma Informs Persona Selection
Ori's persona selector sees only global karma (`karma_comment` on Avatar). ThreddOps injects per-subreddit karma into the LLM prompt and ranks personas by it before the prompt is even rendered. The most credible avatar for `r/cybersecurity` is selected, not just the highest-karma avatar overall.

### 9. Dry-Run Mode for Safe Testing
Ori has no way to test the pipeline without making real LLM calls and writing to production tables. ThreddOps has `dry_run.py` with a toggle in the admin UI — operator can walk any thread through the full pipeline, inspect every prompt, paste in mock responses, and see what would have been written — at zero LLM cost.

### 10. Idempotent Pipeline Design
Celery chains with `score_threads.si(cid) | generate_comments.si(cid) | generate_posts.si(cid)`: the `.si()` (immutable signature) means each step receives its own `client_id` argument — no implicit data passing between steps. If `generate_comments` is re-triggered for the same client, it only picks up unprocessed `engage` threads — it doesn't double-generate. Ori has no such idempotency guarantee.
