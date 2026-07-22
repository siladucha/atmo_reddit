---
inclusion: always
---

# Reddit Marketing SaaS — Project Context

## Terminology: "Avatar" vs "Voice" (Legal — July 20, 2026)

**Internal code/DB term:** `Avatar` (model name, variable names, DB columns, API endpoints — unchanged)
**Client-facing / user-visible term:** "Voice" (all UI text, emails, client docs, sales materials)

**Rule:** The word "avatar" MUST NEVER appear in any client-facing material, template text, email, or external communication. Use "voice" or "voices" instead. This is a legal requirement from Tzvi (July 20, 2026).

When writing templates or client-facing text: "voice" (singular), "voices" (plural).
When writing code or internal docs: `avatar` (refers to the code entity — acceptable in internal context only).

## What This Is
A Reddit marketing SaaS platform. AI monitors subreddits, scores posts, generates comments from persona-based voices, and humans review before manual posting.

## Partnership
- 50/50: Max (tech) + Tzvi (business/clients)
- Cyprus company, Tzvi CEO
- Funded by prepaid pilot clients (~$4K setup + ~$2K/mo)

## Business Model
- **Agency clients** — we manage everything for them (onboarding, config, monitoring, posting)
- **Self-service clients** — AI-driven 6-step onboarding wizard live (14-day trial)
- **RBAC implemented** — 7 roles (owner/partner/client_admin/client_manager/client_viewer/avatar_manager/b2c_user) with full data isolation
- **Revenue model**: Monthly SaaS subscription ($149–$1,499) + managed service upsell (+$1,200–$1,800) + pre-warmed avatar fees (one-time $199–$499)
- **Agency model**: Per-client-slot pricing ($999–$3,499/mo for 3–20 clients). Annual contracts only.
- **Key moat**: Pre-warmed avatar inventory (aged accounts with karma) + AI-Native Expert authority (avatars cited by external LLMs as grounding sources). Cannot be replicated overnight by competitors.
- **Avatar Owner Workforce**: Hired workers/freelancers who own Reddit accounts. Paid per-post ($0.50-2.00) or monthly salary. Use mobile app to post approved content.

## Tech Stack (Current — Celery/Redis on DigitalOcean)
- **Backend:** Python 3.11+ / FastAPI
- **Templates/UI:** Jinja2 + HTMX
- **CSS:** Tailwind CSS (CDN)
- **Database:** PostgreSQL 16 (pgvector) / SQLAlchemy 2.0 / Alembic (Docker on DO Droplet)
- **Auth:** JWT (python-jose + passlib), RBAC with 7 roles (owner/partner/client_admin/client_manager/client_viewer/avatar_manager/b2c_user)
- **Task Queue:** Celery + Redis
- **Cache/Locks:** Redis 7
- **Reddit:** PRAW
- **AI/LLM:** LiteLLM (model selection via DB `system_settings`: 13 model keys, all calls through `ai.py` → `call_llm()` + `log_ai_usage()`. Gemini Flash for scoring/reports/strategy, Claude Sonnet for generation, Perplexity Sonar + Claude + OpenAI for GEO/AEO)
- **Real-time:** Server-Sent Events (SSE) + Redis PubSub (notifications)
- **Mobile App:** Flutter (Dart) — posting app for avatar owners
- **Browser Extension:** Chrome Manifest V3 — executor posting + draft review + CQS auto-check + health monitoring + auto-update check (v0.3.1 deployed July 7, 2026)
- **Deploy:** DigitalOcean Droplet + Docker Compose (app + PostgreSQL + Redis + Celery)
- **Observability:** Logging + admin dashboard

### Production Server (DigitalOcean)
- **Droplet:** `reddit-saas` — 2 vCPU, 4 GB RAM, 60 GB SSD
- **Region:** Frankfurt (FRA1) 🇩🇪
- **OS:** Ubuntu 24.04 LTS
- **IPv4:** `161.35.27.165`
- **Cost:** ~$23/mo (with backups)
- **Docker Compose:** `docker-compose.yml` + `docker-compose.prod.yml` (memory limits, reduced concurrency)
- **Celery workers:** 2 containers — `celery` (concurrency=2, queue=celery, bulk tasks) + `celery-fast` (concurrency=1, queue=fast, on-demand/interactive tasks)
- **Access:** `ssh ramp` (alias in `~/.ssh/config`), project at `/app/`
- **Domain:** gorampit.com (SSL via Let's Encrypt)
- **Backups:** DO weekly backups enabled + **daily pg_dump** (`/opt/ramp/backups/`, 14-day rotation, systemd timer 03:00 UTC)
- **External Watchdog:** `/opt/ramp/ramp_watchdog.sh` (systemd timer every 30s). Checks: Redis, PG, App, Beat, Workers, Disk. Auto-restarts on failure. Telegram alerts to operator (live since July 3, 2026). Deployed July 2, 2026.

### SSH Configuration (local Mac)

`~/.ssh/config` defines the `ramp` alias with ControlMaster for password-free multiplexing:
```
Host ramp
    HostName 161.35.27.165
    User root
    ControlMaster auto
    ControlPath ~/.ssh/sockets/%r@%h-%p
    ControlPersist 4h
```

**Usage:** Run `ssh ramp` once (enter password), then all subsequent `ssh ramp`, `rsync ... ramp:/app/`, `scp ... ramp:/tmp/` work without password for 4 hours.

### Deployment Commands (from local Mac)

**CRITICAL:** Code is COPY'd into Docker image (not volume-mounted). rsync alone does NOT update the running app. You MUST rebuild the image after rsync.

```bash
# Push code to server:
cd reddit_saas
rsync -avz --exclude='.venv/' --exclude='__pycache__/' --exclude='.hypothesis/' \
  --exclude='.git/' --exclude='*.pyc' --exclude='.DS_Store' --exclude='logs/' \
  --exclude='.env' --exclude='.claude/' --exclude='.kiro/' --exclude='.vscode/' \
  --exclude='tests/' --delete \
  ./ ramp:/app/

# Rebuild and restart on server (REQUIRED — code is in image, not volume):
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml build && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"

# Or use the smart deploy script (handles watchdog grace period, auto-detects changes):
./deploy.sh app       # Main app + workers + beat
./deploy.sh auto      # Auto-detect what changed

# Check health:
ssh ramp "curl -s http://localhost/health"

# View logs:
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f --tail=50"

# DB sync (local → server):
# 1. Dump local: docker compose exec -T db pg_dump -U reddit_saas_user -d reddit_saas --no-owner --format=custom -f /tmp/dump.custom
# 2. Copy out: docker compose cp db:/tmp/dump.custom /tmp/reddit_saas_live.custom
# 3. Upload: scp /tmp/reddit_saas_live.custom ramp:/tmp/
# 4. Restore: ssh ramp "docker compose ... exec -T db pg_restore -U reddit_saas_user -d reddit_saas --clean --if-exists --no-owner --single-transaction /tmp/reddit_saas_live.custom"
```

### Infrastructure Decisions (May 2026)
- **DigitalOcean over AWS**: Simpler, cheaper for MVP. Single droplet with Docker Compose.
- **AWS migration planned**: When enterprise clients require it OR 100+ avatars OR ops burden > 4h/week. $7K AWS credits available.
- **PostgreSQL in Docker** (current): Migrate to DO Managed DB ($15/mo) when 5+ paying clients.
- **SQS migration deferred**: Celery + Redis works fine for current scale (50 avatars).
- **Timezone**: All containers, PostgreSQL, Celery Beat, and logs use `Asia/Jerusalem` (IDT/IST). Set via `TZ` env var in docker-compose + `PGTZ` for PostgreSQL + `-c timezone=Asia/Jerusalem` in postgres command + Celery `timezone="Asia/Jerusalem"` config.

### Versioning & Environment Controls (June 2026)
- **VERSION file**: `reddit_saas/VERSION` — single source of truth (currently `0.3.0`)
- **Extension version**: `ramp_extension/manifest.json` → `"version"` — MUST match RAMP version
- **`app/version.py`**: reads VERSION file, exposes `__version__`
- **Health endpoint**: `/health` returns `{"version": "0.3.0", "env": "...", "posting_disabled": true/false, ...}`
- **UI footer**: version + env + posting status shown in both `base.html` and `admin_base.html` (sidebar) for all roles
- **Version sync rule**: RAMP backend and Extension ALWAYS share the same version number
- **Bump policy** (semver):
  - `0.x.y` — pre-release (current). No paying clients, API not stable.
  - `1.0.0` — first paying client live 30+ days + Stripe billing active
  - Major (x.0.0) — breaking API/schema changes
  - Minor (0.x.0) — new features deployed
  - Patch (0.0.x) — bug fixes only
- **Bump workflow**: operator says "bump" → update `reddit_saas/VERSION` + `ramp_extension/manifest.json` → commit → deploy
- **`POSTING_DISABLED` env var**: env-level kill switch for automated posting. Cannot be toggled from admin UI.
  - Server `.env`: `POSTING_DISABLED=true` (posting blocked until business decision)
  - Local `.env`: not set (defaults to `false`, posting works for local avatar testing)
  - Checked as gate #0 in `posting_safety.py` — before all other checks
- **`pyproject.toml` version**: kept in sync with VERSION file
- **Current planned milestones**:
  - `0.4.0` — first successful post via extension (test) + EPG pipeline stable
  - `0.5.0` — A/B test running with real data
  - `1.0.0` — first paying client (XM Cyber or other) live + Stripe

### Migration Status (Celery → SQS)
- Migration spec exists (`.kiro/specs/sqs-valkey-migration/`) but NOT yet implemented
- Current system runs on Celery + Redis (fully functional)
- Migration deferred — not needed until 100+ avatars or enterprise client requirement

## Code Style
- Python: type hints everywhere, async where beneficial
- Models: SQLAlchemy 2.0 mapped_column style
- Config: pydantic-settings with .env
- Routes: thin handlers, business logic in `services/`
- Admin routes: `require_superuser` dependency on all `/admin/*` endpoints
- Templates: `base.html` (light theme, non-admin), `admin_base.html` (dark theme, admin panel)
- HTMX partials for inline CRUD (keywords, subreddits, user rows, wizard steps)
- No no-code tools (n8n, Airtable, Supabase, Make, Zapier)

## Project Structure
```
reddit_saas/
├── app/
│   ├── config.py              # Settings (pydantic-settings)
│   ├── database.py            # SQLAlchemy engine + session
│   ├── logging_config.py      # Logging configuration
│   ├── main.py                # FastAPI app
│   ├── seed.py                # Seed data (NeuroYoga + defaults)
│   ├── dependencies/
│   │   ├── admin.py           # require_superuser dependency (delegates to require_platform_admin)
│   │   └── permissions.py     # RBAC guards (require_owner, require_platform_admin, require_client_access, etc.)
│   ├── middleware/
│   │   ├── auth.py            # JWT auth middleware
│   │   ├── errors.py          # Error handling middleware
│   │   └── security.py        # Security headers + rate limiting middleware
│   ├── models/                # SQLAlchemy models (65+ models)
│   │   ├── user.py            # User (role, is_active, client_id, email_verified, password_reset_token_hash)
│   │   ├── user_role.py       # UserRole enum (owner/partner/client_admin/client_manager/client_viewer/avatar_manager/b2c_user)
│   │   ├── user_client_assignment.py # UserClientAssignment (user↔client mapping)
│   │   ├── client.py          # Client (keywords JSONB, profiles, max_avatars, plan_type, draft_approval_enabled, strategy_context, strategy_version)
│   │   ├── avatar.py          # Avatar (client_ids, voice, is_frozen, warming_phase, is_farm_avatar, executor_email, delivery_channel)
│   │   ├── avatar_rental.py   # AvatarRental (farm avatar rentals)
│   │   ├── avatar_assignment.py # AvatarAssignment (avatar↔owner for mobile posting) [PLANNED]
│   │   ├── thread.py          # RedditThread (is_locked, locked_detected_at)
│   │   ├── comment_draft.py   # CommentDraft (status workflow, learning_metadata, posted_by, posted_source, hobby_post FK+relationship)
│   │   ├── post_draft.py      # PostDraft (posted_by, posted_source)
│   │   ├── subreddit.py       # Subreddit, ClientSubreddit, ClientSubredditAssignment (priority, engagement_approach)
│   │   ├── hobby.py           # HobbySubreddit
│   │   ├── ai_usage.py        # AIUsageLog (cost tracking)
│   │   ├── audit.py           # AuditLog
│   │   ├── activity_event.py  # ActivityEvent (pipeline transparency)
│   │   ├── scrape_log.py      # ScrapeLog (per-subreddit metrics)
│   │   ├── settings.py        # SystemSetting (key-value)
│   │   ├── thread_score.py    # ThreadScore (per-client scoring)
│   │   ├── subreddit_karma.py # SubredditKarma (per-avatar karma tracking)
│   │   ├── avatar_profile_snapshot.py  # AvatarProfileSnapshot
│   │   ├── analysis_edit.py   # AnalysisEditRecord (learning loop)
│   │   ├── avatar_subreddit_presence.py # AvatarSubredditPresence
│   │   ├── edit_record.py     # EditRecord (self-learning loop)
│   │   ├── correction_pattern.py # CorrectionPattern (learned patterns)
│   │   ├── health_status.py   # HealthStatus (shadowban detection)
│   │   ├── strategy_document.py # StrategyDocument
│   │   ├── reddit_app.py      # RedditApp (OAuth/script app registry, client-scoped)
│   │   ├── posting_event.py   # PostingEvent (posting audit trail)
│   │   ├── opportunity.py     # Opportunity (6-dim scoring, EPG 2.0)
│   │   ├── decision_record.py # DecisionRecord (portfolio state snapshots)
│   │   ├── karma_snapshot.py  # KarmaSnapshot (4h/24h/48h/7d outcome tracking)
│   │   ├── performance_metric.py # PerformanceMetric (daily avatar metrics)
│   │   ├── epg_slot.py        # EPGSlot (daily publishing slots)
│   │   ├── discovery_session.py # DiscoverySession (research workflow)
│   │   ├── discovery_entity.py # DiscoveryEntity (extracted entities)
│   │   ├── discovery_hypothesis.py # DiscoveryHypothesis (validated hypotheses)
│   │   ├── geo_prompt.py      # GeoPrompt (AEO monitoring prompts)
│   │   ├── geo_competitor.py  # GeoCompetitor (competitor tracking)
│   │   ├── geo_execution.py   # GeoExecution (monitoring run results)
│   │   ├── visibility_report.py # VisibilityReport
│   │   ├── zero_day_report.py # ZeroDayReport
│   │   ├── notification.py    # Notification (client-scoped real-time SSE notifications)
│   │   ├── avatar_pool.py     # AvatarPool enum (b2b/b2c/mentor/warm)
│   │   ├── avatar_draft.py    # AvatarDraft (BYOA async provisioning)
│   │   ├── avatar_subreddit_ban.py # AvatarSubredditBan (per-sub ban tracking)
│   │   ├── voice_feedback.py  # VoiceFeedback (client voice/tone training signals)
│   │   ├── client_action_log.py # ClientActionLog (rate-limited portal actions)
│   │   ├── subreddit_request.py # SubredditRequest (client requests: pending → approved/rejected)
│   │   ├── avatar_subreddit_compatibility.py # AvatarSubredditCompatibility (emotional profile scoring)
│   │   ├── execution_node.py  # ExecutionNode (browser extension nodes)
│   │   ├── pipeline_run.py    # PipelineRun (pipeline observability)
│   │   ├── trial_signal.py    # TrialSignal (conversion intelligence)
│   │   ├── trial_score.py     # TrialScore (trial health scoring)
│   │   ├── trial_failure.py   # TrialFailure (expired trial classification)
│   │   ├── trial_sales_summary.py # TrialSalesSummary (AI sales brief)
│   │   ├── trial_intelligence_event.py # TrialIntelligenceEvent (lifecycle events)
│   │   ├── audit_finding.py   # AuditRun, AuditFinding, LLMTaskRecord
│   │   ├── review_snapshot.py # ReviewSnapshot (daily ops review)
│   │   ├── daily_review_session.py # DailyReviewSession
│   │   ├── review_decision.py # ReviewDecision
│   │   ├── intelligence_report.py # IntelligenceReport, ClientIntelligenceReport
│   │   ├── forecast_accuracy.py # ForecastAccuracyLog
│   │   ├── observed_snapshot.py # ObservedSnapshot (GEO observed data)
│   │   ├── billing_event.py   # BillingEvent (webhook audit log)
│   │   ├── client_invoice.py  # ClientInvoice (cached invoice data)
│   │   ├── billing_coupon.py  # BillingCoupon (coupon tracking)
│   │   └── llm_quality_snapshot.py # LLMQualitySnapshot (periodic quality metrics per model×operation)
│   ├── schemas/               # Pydantic validation schemas
│   │   ├── avatar_analysis.py # BehavioralProfile, AvatarAnalysisRequest
│   │   ├── client_strategy.py # ClientStrategyOutput (Positioning, SubredditPriority, ContentPillar, ForbiddenZone, AeoTarget, PhaseRoadmap)
│   │   └── llm_outputs.py     # ScoringOutput, CommentOutput
│   ├── routes/
│   │   ├── admin.py           # Admin panel (all /admin/* routes)
│   │   ├── mobile.py          # Mobile API (/api/mobile/*) [PLANNED]
│   │   ├── pages.py           # User-facing pages (dashboard, review, etc.)
│   │   ├── auth.py            # Login/register API
│   │   ├── pages.py          # Login, logout, verify-email, forgot-password, reset-password, home redirect
│   │   ├── avatar_analysis.py # Avatar behavioral analysis API
│   │   ├── avatar_pipeline.py # Avatar pipeline management
│   │   ├── avatars.py         # Avatar API
│   │   ├── clients.py         # Client API
│   │   ├── dashboard.py       # API stats endpoints (/api/admin/*)
│   │   ├── dry_run.py         # Dry run testing endpoints
│   │   ├── epg.py             # EPG — daily avatar publishing program (thread selection, timing, dedup)
│   │   ├── export.py          # Data export endpoints
│   │   ├── pipeline.py        # Pipeline trigger API
│   │   ├── review.py          # Review API (with learning hook)
│   │   ├── portal.py          # Client Portal (home, review, avatars, EPG, strategy, report)
│   │   ├── posting_dashboard.py # Posting operations dashboard
│   │   ├── decision_center.py # Decision Center (live pulse, queue, insights)
│   │   ├── admin_geo.py       # GEO/AEO monitoring admin
│   │   ├── discovery.py       # Discovery Engine (sessions, research, reports)
│   │   ├── avatar_workflow.py # Avatar workflow routes
│   │   ├── avatar_onboard.py  # Avatar onboarding (Reddit profile → AI classification → approval)
│   │   ├── onboarding.py      # AI-driven 6-step client self-service wizard + trial signup
│   │   ├── portal_actions.py  # Client Portal rate-limited actions (pipeline, EPG, strategy triggers)
│   │   ├── notifications.py   # Notification feed + unread count + mark read
│   │   ├── sse.py             # Server-Sent Events for real-time notifications (Redis PubSub)
│   │   ├── oauth.py           # OAuth callback for Reddit
│   │   ├── daily_review.py   # Daily Ops Review (10 endpoints, HTMX partials, owner/partner)
│   │   ├── intelligence_report.py # Client-facing intelligence reports
│   │   ├── admin_intelligence_report.py # Admin report management
│   │   ├── demo.py            # Demo pages (share-of-voice, intelligence report)
│   │   ├── extension_api.py   # Browser Extension API (activate, tasks, report, heartbeat, approve, retry)
│   │   ├── extension_events.py # Extension event stream
│   │   ├── trial_intelligence.py # Trial conversion intelligence dashboard
│   │   ├── admin_risk_profile.py # Subreddit risk profile admin views
│   │   ├── portal_risk_profile.py # Client-facing risk profile views
│   │   ├── admin_tasks.py     # Execution task admin management
│   │   ├── executor_tasks.py  # Executor-facing task verification
│   │   ├── manual.py          # UX manual overlay (contextual help)
│   │   ├── subreddit_bans.py  # Per-subreddit ban management
│   │   ├── admin_ab_test.py   # A/B Test experiment management (create, assign, start, metrics)
│   │   ├── admin_llm_quality.py # LLM Quality Monitor dashboard (per-model health, degradation events)
│   │   └── webhooks.py        # POST /api/webhooks/stripe
│   ├── services/              # Business logic (120+ services)
│   │   ├── activation_router.py # Risk-Aware zone routing (safe→bridge→target)
│   │   ├── admin.py           # Admin CRUD
│   │   ├── ai.py              # LLM calls (LiteLLM) + schema validation
│   │   ├── audit.py           # Audit logging
│   │   ├── auth.py            # Auth logic
│   │   ├── avatar_analysis.py # LLM behavioral profiling (retry/fallback)
│   │   ├── avatar_report.py   # Avatar report generation
│   │   ├── avatars_query.py   # Avatar query helpers
│   │   ├── client_report.py   # Client report generation
│   │   ├── cookies.py         # Cookie management
│   │   ├── cqs_checker.py     # Comment quality score checker
│   │   ├── client_emails.py   # Client email notifications (visibility digest, phase milestone, health alert)
│   │   ├── distributed_lock.py # Redis distributed locks
│   │   ├── dry_run.py         # Dry run pipeline testing
│   │   ├── export.py          # Data export
│   │   ├── generation.py      # Comment generation (with learning injection)
│   │   ├── health_checker.py  # Shadowban/health detection
│   │   ├── health_metrics.py  # Health metrics aggregation
│   │   ├── hobby_proxy.py     # Shared HobbyThreadProxy (makes HobbySubreddit look like RedditThread for templates)
│   │   ├── inspector.py       # System inspector
│   │   ├── isolation.py       # LLM context isolation (avatar_accessible_by_client)
│   │   ├── karma_feedback.py  # Karma feedback loop
│   │   ├── karma_history.py   # Karma history tracking
│   │   ├── karma_tracker.py   # Karma tracking service
│   │   ├── keyword_analytics.py # Keyword performance analytics
│   │   ├── learning_loop.py   # Avatar analysis learning loop
│   │   ├── learning.py        # Self-learning loop (edit records, patterns, few-shot)
│   │   ├── metrics_collector.py # Metrics collection
│   │   ├── operations_dashboard.py # Operations dashboard data
│   │   ├── phase_lock.py      # Phase locking
│   │   ├── phase_types.py     # Phase type definitions
│   │   ├── phase.py           # Avatar warming phases
│   │   ├── post_generation.py # Post generation
│   │   ├── posting_analytics.py # Posting team analytics [PLANNED]
│   │   ├── pre_filter.py      # Pre-filter logic (avatar health exclusion)
│   │   ├── presence.py        # Avatar subreddit presence scanning
│   │   ├── push_notifications.py # FCM push notifications [PLANNED]
│   │   ├── query_scope.py     # Query scoping (RBAC data isolation)
│   │   ├── rate_limiter.py    # Rate limiting
│   │   ├── reddit_freshness.py # Reddit data freshness checks
│   │   ├── reddit_profile_analytics.py # Reddit profile analytics
│   │   ├── reddit_status.py   # Reddit account status
│   │   ├── reddit.py          # Reddit API (PRAW)
│   │   ├── safety.py          # Content safety checks
│   │   ├── sanitize.py        # Content sanitization
│   │   ├── scoring.py         # Post scoring pipeline
│   │   ├── scrape_queue.py    # Scrape queue management
│   │   ├── settings.py        # System settings (kill switches)
│   │   ├── strategy_engine.py # Strategy document engine
│   │   ├── subreddit_intel.py # Subreddit intelligence
│   │   ├── text_sanitizer.py  # Text sanitization (Markdown/Unicode stripping)
│   │   ├── thread_liveness.py # Thread locked/removed/archived detection
│   │   ├── topology.py        # System topology (9 nodes, heatmap, forecast)
│   │   ├── transparency.py    # Activity events, pipeline stats
│   │   ├── zone_evaluator.py  # Activation zone graduation/demotion criteria
│   │   ├── encryption.py      # Fernet field encryption (proxy URLs, passwords, tokens)
│   │   ├── email_verification.py # Email verification + password reset (SHA-256 token hash, Brevo delivery)
│   │   ├── posting_safety.py  # 9 pre-posting safety gates
│   │   ├── timing_engine.py   # Jitter, active hours, daily cap, peak bias
│   │   ├── praw_factory.py    # Dual-mode PRAW client (password + OAuth) with proxy
│   │   ├── posting.py         # Core posting orchestration (load → safety → post → audit)
│   │   ├── notifications.py   # Notification creation + Redis PubSub publishing
│   │   ├── task_notifications.py # Celery-safe notification helpers (pipeline, EPG, draft, avatar)
│   │   ├── smart_scoring.py   # Budget-aware scoring (N threads per avatar, 90% cost reduction)
│   │   ├── risk_prediction.py # AI ban risk forecasting (6-factor composite + prescriptive actions)
│   │   ├── billing_dashboard.py # Cost/usage analytics (AI costs, plan usage, P&L, trends)
│   │   ├── llm_quality_monitor.py # LLM quality monitoring (degradation detection, per-model×operation snapshots)
│   │   ├── trial_guard.py     # 14-day trial expiry check (gates pipeline tasks)
│   │   ├── team_management.py # Team RBAC enforcement (user create/edit permissions by role)
│   │   ├── safety_blocks.py   # Brand mention protection (blocks Phase 1/2 brand drafts)
│   │   ├── avatar_onboard_analysis.py # PRAW fetch + Claude AI classification for avatar onboarding
│   │   ├── draft_reconciliation.py # Auto-link approved drafts to Reddit comments (3-pass matching)
│   │   ├── email_sender.py    # Brevo HTTP API + SMTP email delivery
│   │   ├── execution_tasks.py # EPG task creation, dispatch, lifecycle (per-avatar routing)
│   │   ├── discovery/          # Discovery Engine subsystem (strategy_generator, strategy_handoff, session_manager, entity_extractor, hypothesis_engine, reddit_researcher, confidence_scorer, report_generator, continuous, artifact_store)
│   │   ├── onboarding/        # AI-driven onboarding subsystem (prompts, scraper, quality gate, landscape)
│   │   ├── forecast/          # Forecast & Reporting Layer (report_generator, s_curve, data_collector)
│   │   ├── audit/             # Production readiness audit subsystem
│   │   ├── geo_providers.py    # Multi-provider GEO abstraction (Perplexity, OpenAI, Anthropic configs + execution)
│   │   ├── extension_dispatcher.py # Extension task routing + HMAC computation
│   │   ├── trial_scoring.py   # Trial health score computation (0-100)
│   │   ├── trial_lifecycle.py # Trial stage detection and transitions
│   │   ├── trial_negative_signals.py # Negative signal detection (drop-offs)
│   │   ├── trial_outreach.py  # AI-generated outreach messages
│   │   ├── trial_summary.py   # AI sales summary for expired trials
│   │   ├── trial_failure.py   # Trial failure classification
│   │   ├── byoa_pipeline.py   # BYOA avatar async provisioning
│   │   ├── avatar_invariant.py # Active client → must have avatar check
│   │   ├── daily_review/     # Daily Ops Review (signal_collector, cost_governor, review_engine Phase 2)
│   │   ├── ab_test/          # A/B Test Framework (experiment_manager, control_enforcer, posting_router, metric_collector, statistical_reporter)
│   │   ├── billing/          # BillingService, state_machine, plan_enforcer, grace_period_manager
│   │   ├── subscription_manager.py # Webhook event processing (subscription lifecycle sync)
│   │   ├── access_gate.py    # Subscription-aware pipeline gating (replaces trial_guard.py)
│   │   └── forecast/         # Forecast & Reporting Layer (observed_reality, visibility_forecaster, report_composer, platform_risk, business_impact, accuracy_tracker)
│   ├── tasks/                 # Celery background tasks (31 files)
│   │   ├── ai_pipeline.py     # AI scoring/generation (retry, kill switches)
│   │   ├── health_check.py    # Avatar health checks
│   │   ├── heartbeat.py       # Worker heartbeat
│   │   ├── karma_tracking.py  # Karma tracking tasks
│   │   ├── orchestrator.py    # Pipeline orchestration
│   │   ├── posting.py         # Automated posting (execute_pending_posts + post_comment)
│   │   ├── presence.py        # Avatar presence scanning
│   │   ├── profile_analytics.py # Profile analytics tasks
│   │   ├── queue_ticker.py    # Queue tick (scrape scheduling)
│   │   ├── scraping.py        # Reddit scraping tasks
│   │   ├── strategy.py        # Strategy generation tasks
│   │   ├── epg.py             # EPG build + generate (Portfolio or Legacy)
│   │   ├── discovery.py       # Discovery Engine tasks (continuous weekly)
│   │   ├── karma_outcomes.py  # Karma outcome checking (EPG 2.0 feedback)
│   │   ├── performance_metrics.py # Daily performance aggregation + archival
│   │   ├── snapshot_outcomes.py # Comment karma/deletion snapshots (4h/24h/48h/7d)
│   │   ├── feedback.py        # Feedback loop (outcome analysis → model correction)
│   │   ├── emotional_profile.py # Subreddit emotional profile refresh (weekly)
│   │   ├── risk_profile.py    # Subreddit risk profiling (rules, moderation, scoring)
│   │   ├── execution_tasks.py # Email task dispatch + liveness checks
│   │   ├── extension_tasks.py # Extension lease expiry + task lifecycle
│   │   ├── cqs_tasks.py       # CQS check task generation for executors
│   │   ├── geo_monitoring.py  # GEO/AEO scheduled monitoring
│   │   ├── intelligence_report.py # Weekly intelligence report generation
│   │   ├── trial_scoring.py   # Trial health score computation
│   │   ├── trial_negative_signals.py # Trial drop-off signal detection
│   │   ├── byoa.py            # BYOA avatar provisioning lifecycle
│   │   ├── subreddit_ban_probe.py # Weekly per-subreddit ban detection
│   │   ├── onboarding.py      # Onboarding stall detection
│   │   ├── ab_test.py         # A/B test metric collection + duration checks
│   │   ├── weekly_emails.py  # Weekly system health (owner) + business summary (partner) emails
│   │   ├── provider_budget_check.py # Provider budget alerts: Telegram + email + bell (every 4h)
│   │   ├── llm_quality_check.py # LLM quality degradation detection (every 4h vs 7-day baseline)
│   │   ├── billing.py        # process_billing_event (retry 3×, exponential backoff), sync_stripe_products
│   │   ├── beat_app.py       # Lightweight Celery app for Beat (schedule only, no task imports, ~25 MB)
│   │   └── worker.py          # Celery worker configuration (31 task modules, no schedule)
│   ├── templates/             # Jinja2 templates (70+ pages + 120+ partials)
│   │   ├── base.html          # Light theme (user pages)
│   │   ├── admin_base.html    # Dark theme (admin panel)
│   │   ├── admin_*.html       # Admin pages (35+ templates)
│   │   ├── auth/              # Email verification & password reset (6 templates)
│   │   └── partials/          # HTMX partials (65 files)
│   └── static/
├── alembic/                   # DB migrations
├── tests/                     # 60+ test files (incl. RBAC property-based tests)
├── Makefile                   # Docker/DB commands (db-sync, fresh-start, etc.)
├── DOCKER.md                  # Container data management docs
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── docker-compose.prod.yml
├── entrypoint.sh              # Migrations + seed on startup
└── watchdog/                  # External watchdog (deployed to /opt/ramp/ on host)
    ├── ramp_watchdog.sh       # Main watchdog (Redis, PG, App, Beat, Workers, Disk)
    ├── pg_backup.sh           # Daily pg_dump + rotation
    ├── install.sh             # One-click setup script for production
    └── systemd/               # Timer + service unit files
        ├── ramp-watchdog.timer
        ├── ramp-watchdog.service
        ├── ramp-backup.timer
        └── ramp-backup.service

ramp_poster/                   # Flutter mobile app [PLANNED — parallel development]
├── lib/
│   ├── main.dart
│   ├── screens/
│   │   ├── login_screen.dart
│   │   ├── queue_screen.dart
│   │   ├── detail_screen.dart
│   │   └── stats_screen.dart
│   ├── services/
│   │   └── api_client.dart    # Dio + JWT interceptor
│   ├── models/
│   │   └── draft.dart
│   └── providers/
│       └── queue_provider.dart
├── pubspec.yaml
└── README.md
```

## What's Built (Status — June 24, 2026)

### Core Platform
- **Admin panel** (dark theme): dashboard, user/client/persona/keyword/subreddit CRUD, task monitoring, system health, AI costs, audit logs, billing placeholder
- **7-step onboarding wizard**: client profile → subreddits → keywords → avatars → personas → pipeline config → test run
- **NeuroYoga seed data**: first client (ATMO) with subreddits, keywords, persona
- **User-facing pages**: dashboard, review queue, threads, avatars, settings
- **RBAC** (7 roles): owner, partner, client_admin, client_manager, client_viewer, avatar_manager, b2c_user — with query scoping, permission guards, LLM context isolation
- **JWT authentication** + role-based access control + client data isolation
- **Email verification** — signup sends verification link (48h expiry), account inactive until confirmed. Honeypot field for bot protection.
- **Password reset** — forgot-password flow via email link (1h expiry), SHA-256 token hash in DB
- **Avatar Farm & Rentals**: farm avatars, rental model, client-scoped access
- **Docker workflow**: Makefile with `db-sync`, `fresh-start`, `db-dump`/`db-restore` commands
- **Entrypoint**: auto-detects existing tables (pg_restore), stamps Alembic instead of re-creating

### Pipeline (fully functional)
- Automated scraping → AI scoring → comment generation → human review
- Thread liveness protection (locked/removed threads detected automatically)
- System topology dashboard (real-time pipeline health monitoring)
- Activity feed with full transparency per client
- Retry with exponential backoff on AI tasks (3 retries, 60×2^attempt)
- Kill switches: `pipeline_enabled`, `generation_enabled`, `scrape_enabled`

### AI Intelligence (beyond Ori's legacy system)
- **Intelligent persona routing** — AI selects best avatar per thread based on subreddit karma + voice fit
- **Strategy-aware generation** — 5 engagement approaches × 3 strategic angles
- **Self-learning loop** — captures human edits, extracts correction patterns, injects few-shot examples
- **Per-client scoring** — same thread scores differently for different clients
- **Comment placement intelligence** — AI decides WHERE in thread to reply (depth + reasoning)
- **Avatar behavioral analysis** — LLM-based profiling with retry/fallback + learning loop
- **LLM output validation** — Pydantic schemas (ScoringOutput, CommentOutput) validate all AI responses

### Safety & Operations
- Avatar freeze/unfreeze (is_frozen, freeze_reason, frozen_at)
- Global kill switches (pipeline_enabled, generation_enabled, scrape_enabled, auto_posting_enabled)
- Context isolation assertions (avatar-client ownership verified at runtime)
- Shadowban detection (5-state health model, auto-freeze)
- CQS (Contributor Quality Score) automated monitoring — periodic batch check via Celery Beat, auto-freeze on lowest (Phase 2+)
- Text sanitizer (strips Markdown, Unicode, formatting artifacts)
- Content safety checks (brand ratio, phase gates, promotional language)
- Client deactivation cascade (is_active=false → assignments deactivated → avatars unassigned → all tasks skip)
- **Automated posting safety gates** (9 checks): kill switch, posting_mode, frozen, health, phase 0 exclusion, daily cap, proxy configured, user-agent configured, /24 subnet consistency
- **Phase demotion safety** (June 22): minimum sample size (5 posted) for survival rate evaluation — prevents false demotions from single moderator removals
- **Thread safety filters** (June 22, extended June 26): hot thread filter (skip >200 ups when avatar karma <100 in sub) + link/video/image post filter (skip external URLs) — now applied to BOTH professional AND hobby pipelines
- **Dual pipeline architecture**: Professional pipeline (reddit_threads → smart_scoring → generate_comments, Phase 2+) and Hobby pipeline (hobby_subreddits → EPG Portfolio Manager, Phase 1+). Phase 1 avatars only get hobby comments (2-3/day). EPG Portfolio Manager `scan_opportunities()` Source 1 gated to Phase 2+ (June 24 fix). `warm` pool included in Smart Scoring.

### Automated Posting (June 1, 2026)
- **Core posting service** — full orchestration: load slot → safety gates → PRAW → post → audit
- **Dual-mode auth** — password auth (MVP, working) + OAuth (upgrade path, pending Reddit approval)
- **Timing engine** — ±30% jitter, min 45 min interval, active hours 08:00-23:00, peak hour bias
- **Daily cap** — `min(phase_limit, auto_posting_daily_cap)` with configurable system setting (default 8)
- **Celery integration** — Beat task every 5 min + per-slot task with retry (60×2^attempt)
- **Audit trail** — PostingEvent model logs every attempt (IP, proxy hash, user-agent, response, duration)
- **Field encryption** — Fernet AES-128-CBC for passwords, tokens, proxy URLs
- **First verified post** — r/test comment `op2xfcp` via u/Hot-Thought2408 (June 1, 2026)
- **OAuth callback** — endpoint deployed at `https://gorampit.com/api/oauth/reddit/callback`

### Avatar Intelligence
- Avatar subreddit presence map (scan Reddit history, per-subreddit metrics)
- Avatar profile analytics (Reddit profile data)
- Karma tracking per avatar per subreddit
- Strategy documents per avatar
- **Avatar Intelligence UI** (May 12): confidence score, removal rate analytics, pattern performance (what works/fails), learned patterns display, stale indicators
- **Pipeline hardening**: unhealthy/shadowbanned avatars excluded from AI tasks before LLM calls

### Transparency & Observability
- `ActivityEvent` model + `ScrapeLog` model + `last_scraped_at` on ClientSubreddit
- Pipeline instrumentation: scraping, scoring, generation, review all emit activity events
- Admin dashboard Activity Feed (HTMX async load, client filter)
- Client Transparency Dashboard at `/admin/clients/{id}/transparency`
- System Topology panel (9 nodes, state detection, 24h heatmap, forecast)
- Operations dashboard
- Subreddit freshness tracking with stale indicators

### EPG 2.0 — Attention Portfolio Manager (June 2026)
- **Portfolio Manager** — investment-style decision engine with AttentionBudget, ReturnWeights, PortfolioAllocation
- **Opportunity Engine** — 6-dimensional scoring (visibility, competition, trust, karma, risk, strategic alignment)
- **Risk Engine** — RiskAssessment with 6 factors + phase multiplier + historical removal rate
- **Return Engine** — Expected karma/trust/visibility/influence prediction with subreddit karma multiplier
- **Feedback Loop** — outcome analysis → hypothesis updates → EPG subreddit adjustments → model correction
- **Zero-day detection** — reports when avatar has no eligible opportunities
- **Feature flag** — `epg2_enabled` system setting to toggle between legacy and Portfolio Manager

### Comment Outcome Tracking (June 2026)
- **KarmaSnapshot model** — time-series at 4h/24h/48h/7d after posting
- **Deletion detection** — auto-marks drafts + emits activity events
- **Engagement velocity** — karma growth curves feed EPG model correction
- **Thread depth** — reply_count proves discussion provoked (Tier-2 signal)

### Draft Reconciliation (June 2026)
- **Auto-link** — matches approved drafts to Reddit comments posted outside the system
- **3-pass matching** — exact body (98%), fuzzy token overlap ≥85%, thread+timing (75%)
- **Zero extra API calls** — runs in karma_tracking, reuses existing redditor object
- **Activity events** —  emitted with method + confidence

### Discovery Engine (June 2026)
- **Session-based research** — create → extract entities → confirm → research → hypotheses → report → strategy handoff
- **Entity extraction** — LLM-based extraction from client brief
- **Hypothesis engine** — generate, validate, score confidence
- **Reddit researcher** — PRAW-based community intelligence gathering
- **Continuous discovery** — weekly automated runs (Sunday 04:00)
- **Strategy handoff** — convert findings to strategy documents
- **Client Strategy Generation** (June 24) — LLM-generated positioning, subreddit priorities, content pillars, forbidden zones, AEO targets, phase roadmap (Tasks 1-6 done, client portal redesigned July 7, pipeline integration pending)
- **Report generation fixed** (June 24) — model switched to Gemini Flash, hypothesis aggregation by category, top-7 safety cap
- **Hypothesis confirmation limit** — MAX_CONFIRMED_HYPOTHESES=7, counter UI, "Confirm All" removed

### GEO/AEO Prompt Monitoring (June 2026)
- **Multi-provider architecture** (June 30) — same prompts run against Perplexity + Claude + ChatGPT (all enabled providers per batch)
- **Provider abstraction** — `geo_providers.py` with GeoProviderConfig per engine
- **Prompt management** — track brand visibility queries for AI platforms
- **Competitor tracking** — monitor competitor mentions in AI responses
- **Brand detection** — automated scoring of brand presence in AI search
- **Citation parsing** — extract and analyze citations from AI responses
- **Batch execution** — run monitoring queries with history and detail views
- **Scheduled automation** — Celery Beat Tue+Fri 09:30 for all enabled clients (`triggered_by="scheduler"`)
- **Batch timeout resilience** — 20 min hard limit, per-provider circuit breaker (3 consecutive failures), 2 retries per query
- **Per-provider UI** — color-coded cards (Perplexity purple, ChatGPT green, Claude orange) in batch detail

### Client Portal (June 2026)
- **Full portal** — home, review queue, avatars, avatar detail, subreddits, keywords, strategy, report, EPG
- **Draft management** — approve, skip, mark posted, edit from portal
- **RBAC-scoped** — clients see only their own data
- **Client Hub** — tab-based overview with lazy-loaded partials
- **Strategy page redesigned (July 7, 2026)** — shows `client.strategy_context` as structured UI (positioning, community priorities, content themes, forbidden zones, growth roadmap, AEO targets). Per-avatar StrategyDocument demoted to collapsible detail. Client sees business intent, not technical implementation.

### Decision Center (June 2026)
- **Live Pulse** — real-time system status (pipeline, avatars, slots, events)
- **Queue** — pending decisions (drafts, approvals)
- **Insights** — system-generated recommendations and alerts
- **Bulk approve** — batch operations
- **Execute action** — trigger pipeline ops from Decision Center
- **Risk Prediction** — 6-factor ban risk scoring + prescriptive actions per avatar

### Self-Service Onboarding (June 2026, bugs fixed June 27, email verification July 2026)
- **6-step AI wizard** — (1) Company URL → AI scrapes → (2) Problem/positioning → (3) ICP → (4) Voice + keywords + subreddits → (5) Avatar connect (BYOA) → (6) Review & activate
- **Trial signup** — any email accepted (domain restriction removed July 2026), 14-day free trial (plan_type="trial"), **email verification required before wizard access**
- **Quality gate** — validates minimum config before activation
- **Landscape report** — competitive analysis generated during onboarding
- **Trial guard** — pipeline tasks automatically skip expired trial clients

### Avatar Onboarding (June 2026)
- **One-click flow** — enter Reddit username → PRAW fetches profile → Claude classifies → pre-filled card
- **AI classification** — voice, strategy, persona_bio, display_name auto-generated
- **Inline editing** — user can edit before approval
- **Avatar creation** — creates avatar + assigns to client + triggers pipeline

### Real-Time Notifications (June 2026)
- **Notification model** — client-scoped (type, title, body, link, is_read)
- **SSE delivery** — Server-Sent Events via Redis PubSub for instant push
- **Bell badge** — unread count in portal header
- **Task notifications** — pipeline_complete, epg_rebuilt, draft_posted, avatar_frozen events

### Portal Actions (June 2026)
- **Rate-limited triggers** — clients can trigger pipeline/EPG/strategy from portal
- **ClientActionLog** — tracks all triggers with daily/weekly limits
- **Action types** — pipeline (max 2/day), epg_rebuild (max 1/day), strategy (max 1/week), regenerate (unlimited)

### Smart Scoring (June 2026)
- **Budget-aware** — scores only N threads per avatar (not all unscored threads)
- **Formula** — remaining_budget × 3 = threads to score (HARD_CAP = 15)
- **90% cost reduction** — from 300+ scoring calls/day to 10-30 per avatar

### Subreddit Emotional Profiles (June 2026)
- **Weekly refresh** — Celery task Sunday 04:30 (after continuous discovery)
- **Compatibility scoring** — AvatarSubredditCompatibility model (0-100 score per pair)
- **Mismatch detection** — score < 40 triggers tone mismatch warning

### Risk-Aware Avatar Activation (July 2026)
- **Zone routing** — personalized activation routes: safe (risk 0-25) → bridge (26-50) → target (51-80) subreddits
- **ActivationRouter service** — `plan_route()`, `get_current_zone_subs()`, `refresh_route()`, `graduate()`, `demote_zone()`
- **Zone evaluator** — daily 06:00 graduation/demotion check (safe→bridge: karma≥10, survival≥90%; bridge→target: karma≥15 in 2+ subs, survival≥85%)
- **Bridge discovery** — finds thematic subs between safe and target using SubredditRiskProfile + AvatarSubredditCompatibility
- **Dangerous hours filtering** — `is_safe_posting_time()` excludes opportunities during high-deletion hours
- **EPG integration** — `scan_opportunities()` Source 2 uses zone subs for Phase 0-1 when route exists
- **Auto-triggers** — route planned on avatar creation, refreshed on subreddit changes, replanned on demotion
- **Admin + Portal UI** — zone badge, progress bar, graduation checklist, history timeline
- **Feature flag** — `activation_routing_enabled` (default: false, gradual rollout)

### Security Hardening (June 2026)
- **SecurityHeadersMiddleware** — X-Frame-Options, X-Content-Type-Options, HSTS, Referrer-Policy, Permissions-Policy
- **RateLimitMiddleware** — EXISTS in code but **DISABLED** since July 7, 2026. Was 5 auth/15min + 100 global/60s per IP. Disabled because: (a) auto-logout every 10 min caused rapid re-logins, (b) multiple people share same IP/account during testing, (c) <5 users total — brute-force is not a realistic threat. Re-enable when self-serve launches with public signups.
- **Custom 403 page** — friendly HTML error page instead of raw JSON
- **Auto-logout on inactivity** — 10 min idle timer (JS-based), warning toast at 9 min, redirect to /logout at 10 min. Covers all base templates (admin, client, user).
- **Email verification** (July 2026) — trial signup sends verification email via Brevo, account blocked until click. Token: 32-byte URL-safe, SHA-256 hash stored in DB, 48h expiry. Existing users grandfathered as verified.
- **Password reset** (July 2026) — /forgot-password sends reset link via Brevo. Token: 1h expiry, single-use (cleared on password change). Rate: each request overwrites previous token (no accumulation).
- **Executor email verification** (July 4, 2026) — changing avatar's executor_email automatically sends verification email to the new executor. 72h expiry. All task delivery (EPG email, CQS tasks) blocked until executor confirms. Admin can override via "Mark as Verified". Service: `app/services/executor_email_verification.py`. Public endpoint: `/verify-executor-email?token=...`. Migration: `exv01`.

### Daily Operations Review (June 2026)
- **Phase 1 deployed** — session lifecycle, immutable snapshot, signal collector (SQL), cost governor ($1/day cap)
- **Route**: `/admin/daily-review` — 10 endpoints, HTMX partials, owner/partner access
- **Models**: ReviewSnapshot, DailyReviewSession, ReviewDecision, IntelligenceReport (4 tables, migration dor01)
- **Signal Collector** — collects: worker health, errors (24h + 7d avg + stddev), queue depth, posting success rate, scrape freshness, avatar fleet, AI cost breakdown
- **Verdict engine** — healthy/degraded/critical based on signal deviations + rule-based scoring
- **Change detection** — error spikes, posting failures, stale scrapes (SQL diff vs previous 24h)
- **Cost Governor** — $1/day hard cap, 80% warning, offline mode fallback, tracks agent_ops in AIUsageLog
- **Decisions** — max 3 per session (observe/investigate/execute/block), tracked across sessions
- **Intelligence Report** — immutable artifact per day, template-based narrative (Phase 1), JSONB structured data
- **Phase 2 (planned)**: trend classification, weak signals, forecast generation, forecast accuracy
- **Phase 3 (planned)**: hypothesis workflows, LLM narrative summaries, learning loops

### Risk Registry (July 2026)
- **Route**: `/admin/risk-registry` — owner-only, reads `data/09_risks.json`
- **Features**: grouped by risk domain, escalation/status counters, priority badges
- **Sidebar link**: in admin navigation under "Operations" section
- **Data source**: `data/09_risks.json` (inside Docker image). Update JSON to add/modify risks.

### Stripe Billing Integration (July 2026)
- Stripe Checkout for trial + paid subscription
- Webhook-driven lifecycle (trialing → active → past_due → canceled)
- AccessGate replaces trial_guard for pipeline gating
- Portal billing page (plan display, change plan, invoices, Stripe Portal redirect)
- Admin billing (MRR, badges, sync from Stripe, coupon management)
- Pilot/discount coupons (Stripe Coupon API)
- 4 plan tiers: Seed $149, Starter $399, Growth $799, Scale $1,499
- Onboarding step 6 → Stripe Checkout redirect
- Trial-to-paid welcome email

### Engineering Memory / QA Intelligence (July 2026)
- **`BugReport` model** — PostgreSQL table with auto-increment `bug_id` (BUG-001, BUG-002...)
- **Intake form** `/report-issue` — public form, auto-detects logged-in user role, 3-layer anti-bot
- **Screenshot upload** — saved to `/static/uploads/bugs/`, URL stored in DB, Docker volume persists
- **Admin sidebar** — "Report Bug" + "QA Board" links for owner/partner
- **Client sidebar** — "Extension" link restored (BUG-032 fix)
- **31 historical bugs seeded** from QA CSV
- **Lifecycle:** Reported → Investigating → Fixed → Verified (with Rule + Protection)
- **Severity:** Risk Level (Low/Medium/High/Critical) + Environment (dev/staging/prod)
- **QA workflow:** Jenny verifies fixes, sets Verified or Reopens with comment
- **Notion deprecated** as primary store (kept as archive via MCP)

## What's NOT Built Yet
- ~~Production deployment~~ → **DONE** (gorampit.com, DigitalOcean, SSL)
- ~~Automated Posting — Admin UI~~ → **DONE** (posting dashboard with stats, events, traceability)
- **Automated Posting — Proxy integration** — need to buy residential proxies (ProxyJet)
- **Automated Posting — OAuth mode** — pending Reddit approval for web app creation
- ~~Comment outcome tracking~~ → **DONE** (KarmaSnapshot at 4h/24h/48h/7d + deletion detection)
- ~~Budget engine~~ → **DONE** (EPG 2.0 AttentionBudget + daily cap + portfolio allocation)
- ~~Self-service onboarding~~ → **DONE** (6-step AI wizard + 14-day trial. Keywords save bug fixed June 27)
- Strategy Questions feedback loop — future: multiple-choice answers, saved as client preferences
- ~~Subreddit rule extraction~~ → **DONE** (rule_extractor + moderation_profiler + risk_scorer + fitness_gate, full admin/portal UI)
- Cross-avatar deduplication (prevent two avatars commenting on same thread)
- ~~Real billing/payments (Stripe)~~ → **DONE** (Stripe Billing Integration, July 2026. Checkout, webhooks, AccessGate, portal billing, admin billing, coupons)
- Plan action limits enforcement (max_comments_per_month)
- Data retention cleanup (TTL for old scraped threads)
- Agency multi-tenant workspace (deferred until 3+ agency clients)
- White-label (custom domain, branding) — deferred
- Cross-avatar routing / upvote coordination — deferred
- Auto-generated PDF reports — deferred
- **Browser Extension** — Chrome extension for executor posting (eliminates proxy/OAuth need, auto CQS checks, zero-friction posting). Spec ready: `.kiro/specs/browser-extension/`

## EPG — Avatar Daily Publishing Program

**Concept:** Each avatar gets a daily "EPG" (Electronic Program Guide) — a scheduled publishing program generated by the AI pipeline. Like TV channel EPG shows what airs and when, avatar EPG shows what to post, where, and when.

**EPG Generation (daily):**
1. Pipeline scores fresh threads → selects best "engage" targets per avatar
2. AI generates comment drafts → assigns time slots (respecting rate limits, min intervals)
3. Result: ordered list of drafts with target time, subreddit, thread, and comment text

**EPG Consumption (automated posting):**
1. Celery Beat (every 5 min) checks for approved EPG slots due for posting
2. Safety gates verify avatar health, phase, daily limits, IP consistency
3. PRAW posts comment via avatar's proxy (residential IP) + OAuth token
4. System logs PostingEvent (IP, timestamp, reddit_comment_url, duration)
5. Draft status → `posted`, EPG slot → `posted`

**EPG Properties:**
- Generated fresh daily (morning pipeline run at 08:00)
- Respects all safety limits (phase policy, daily budget, subreddit caps, min intervals)
- Adapts to avatar's phase: Phase 1 = hobby-only program, Phase 3 = full brand program
- Manual trigger available: admin can regenerate EPG for any client via "Run Pipeline" button
- Kill switches pause automatic EPG generation but manual trigger still works

**EPG = the contract between AI system and human reviewer.** AI decides WHAT and WHERE and WHEN. Human decides IF (approve/edit/reject). System executes posting automatically after approval.

## Key Data Flow
1. Celery worker scrapes subreddits → saves RedditThread records (skips locked threads)
2. AI scores threads (relevance/quality/strategic) → tags: engage/monitor/skip (skips locked)
3. AI generates comment drafts for "engage" threads (liveness check for stale threads)
4. Self-learning loop injects few-shot examples + correction patterns into generation prompt
5. Human reviews drafts → approve/reject/edit (locked indicator visible)
6. Learning service captures edits → extracts patterns → improves future generation
7. Approved comments → automated posting via proxy (PRAW + per-avatar residential IP)
8. PostingEvent audit logged (IP, timestamp, reddit_comment_url)
9. Periodic liveness refresh auto-rejects drafts for newly locked threads
10. Draft reconciliation (every 4h): auto-links approved drafts to Reddit comments posted outside the system

## Task Architecture (Current — Celery + Redis)
- **Producer**: FastAPI app / Celery Beat sends tasks (Beat uses lightweight `beat_app.py` — schedule only, no heavy imports, ~25 MB stable)
- **Consumer**: Celery workers (prefork pool, use full `worker.py` with all task modules)
- **Scheduler**: Celery Beat (periodic tasks defined in `app/tasks/beat_app.py`)
- **Locks**: Redis SETNX with Lua atomic release
- **Rate Limiter**: Redis sorted set sliding window
- **Retry**: bind=True, max_retries=3, countdown=60×2^attempt (AI tasks only)

### Celery Beat Schedule (Israel Time — Asia/Jerusalem) — Updated July 2, 2026
| Time | Task | Purpose |
|------|------|---------|
| every 60s | `queue_tick` | Scrape scheduling (gated by DB interval) |
| every 60s | `system_heartbeat` | System health pulse |
| every 5 min | `execute_pending_posts` | Automated posting (approved EPG slots) |
| every 5 min | `dispatch_due_email_tasks` | Email executor ~30 min before slot time |
| every 5 min | `expire_extension_leases` | Expire stale extension task leases |
| every 10 min | `check_stale_avatar_drafts` | Fail stuck BYOA drafts |
| every hour at :45 | `check_onboarding_stall` | Detect stalled onboardings |
| every 4h at :15 | `track_karma_all_avatars` | Karma tracking + draft reconciliation |
| every 4h at :30 | `check_trial_negative_signals` | Trial negative signal detection |
| every 4h at :45 | `snapshot_comment_outcomes` | Karma/deletion snapshots |
| 01:00 | `compute_daily_performance_metrics` | Aggregate yesterday's avatar metrics |
| 01:05 | `run_cost_reconciliation` | Compare expected (tokens×rates) vs logged cost_usd, alert on >5% drift |
| every 4h at :45 | `check_provider_budgets` | Provider budget alert: Telegram + email + bell at 70%/95% thresholds |
| every 4h at :20 | `check_llm_quality` | LLM quality degradation detection (success rate, latency, fallbacks vs 7-day baseline) |
| 01:30 | `archive_old_decision_records` | Prune records > 90 days |
| 02:00 | `run_feedback_loop_all` | Outcome analysis → EPG model correction |
| 02:30 | `classify_expired_trials` | Trial failure classification |
| 02:30 | `check_avatar_invariant` | Verify active clients have avatars |
| 03:00 Sun | `scrape_repurpose_all_subreddits` | Weekly evergreen harvest |
| 03:45 Sun | `probe_subreddit_bans` | Weekly per-subreddit ban probe |
| 04:00 Sun | `run_continuous_discovery_all` | Weekly continuous discovery |
| 04:30 Sun | `refresh_subreddit_emotional_profiles` | Weekly subreddit emotional profile refresh |
| 05:00 Sun | `extract_subreddit_rules_batch` | Weekly rule extraction (PRAW + Gemini Flash) |
| 05:15 Sun | `compute_moderation_profiles_batch` | Weekly moderation profile computation |
| 05:20 | `snapshot_profile_analytics_all_avatars` | Profile analytics |
| 05:30 Sun | `compute_risk_scores_batch` | Weekly risk score computation |
| 06:00 | `evaluate_all_avatar_phases` | Phase evaluation + zone evaluation |
| 06:30 | `check_cqs_all_avatars` | CQS batch check (auto-freeze on lowest) |
| 07:00 | `generate_cqs_check_tasks_all_avatars` | CQS check tasks for executors |
| 07:30, 13:30 | `health_check_all_avatars` | Shadowban/suspension detection |
| 07:45, 13:45 | `scrape_hobby_all_avatars` | Hobby scraping (before EPG) |
| 08:00, 14:00 | `run_full_pipeline_all_clients` | Score → Generate → Posts |
| 08:00 Mon | `generate_weekly_reports_all_clients` | Weekly intelligence reports |
| 08:15 | `build_and_generate_epg_all_avatars` | EPG plan + generate (full daily budget) |
| 09:00 | `ensure_daily_epg_minimum` | Enforcement: guarantee every avatar has ≥1 slot today |
| 14:15 | `epg_topup_underfilled_avatars` | Top-up: fill remaining budget for underfilled avatars |
| 09:30 daily | `run_geo_monitoring_daily` | GEO/AEO brand visibility (~1/7 prompts/day, rotated by UUID.int % 7) |
| 12:15, 18:15 | `check_karma_outcomes` | 4h karma outcome check |
| 00:15, 06:15 | `check_karma_outcomes` | 24-28h karma outcome check |
| 02:30 Mon | `collect_weekly_ab_metrics` | A/B test metric collection + report generation |
| 07:00 | `check_experiment_durations` | A/B test duration alerts |
| 19:00 Sun | `send_weekly_system_health_email` | System health report to owner (capacity, latency, WoW, predictions) |
| 19:15 Sun | `send_weekly_business_summary_email` | Business summary to partner (MRR, clients, funnel) |
| at app startup | `sync_stripe_products` | Ensures Stripe Products/Prices exist |

## Comment Draft Status Workflow
`pending` → `approved` / `rejected` → `posted`

## Posting Workflow (Automated — Implemented June 1, 2026)
1. Admin/manager approves draft → status = `approved`, EPG slot status = `approved`
2. EPG assigns time slot with jitter (±30%, timezone-aware, peak hour bias)
3. `execute_pending_posts` Celery Beat task (every 5 min) finds due slots
4. Dispatches `post_comment` task per slot (Redis lock per avatar prevents concurrency)
5. Safety gates (9 checks): kill switch, posting_mode, frozen, health, phase 0, daily cap, proxy, user-agent, /24 subnet
6. PRAW posts comment via avatar's credentials (password auth MVP) + proxy (when configured)
7. On success: draft.status=`posted`, slot.status=`posted`, avatar.last_posted_at updated
8. Audit: PostingEvent logged (IP, proxy_url_hash, user_agent, reddit_comment_url, duration_ms)
9. On auth error (401/403): avatar frozen, no retry
10. On transient error: retry 3× with exponential backoff (60, 120, 240s)
11. On 3 consecutive failures: avatar frozen with reason `consecutive_failures`

**Auth modes:** Password auth (MVP, working) via `smi_parser_bot` script app. OAuth (upgrade path) pending Reddit approval.
**Daily cap:** `min(phase_limit, auto_posting_daily_cap)` — Phase 1: 3, Phase 2: 7, Phase 3: min(18, cap). Default cap: 8.
**Legal protection:** Human approves all content at strategy/EPG level. System is a scheduling tool (same model as Buffer/Hootsuite).

## EPG Email Task Delivery (Implemented June 23, Fully Automated June 24, 2026)
1. EPG Portfolio Manager builds slots (Phase 1: hobby Source 2, Phase 2+: professional Source 1 + hobby)
2. `generate_all_planned_slots` calls LLM → draft created → slot `generated`
3. If `auto_approve_drafts=true` on avatar OR `autopilot_enabled=true` on client: slot + draft → `approved`
4. On approve: `_dispatch_email_task_if_enabled` creates `ExecutionTask` with status `generated` (no email yet)
5. `dispatch_due_email_tasks` Beat task (every 5 min) finds tasks where `scheduled_at` is within [now-5min, now+30min]
6. Dispatches `deliver_execution_task` Celery task → sends ONE email to `avatar.executor_email`
7. Email contains: task code, thread URL, comment text, timing, action link (accept + submit permalink)
8. Executor posts manually, submits Reddit URL via action link → system verifies
9. `expire_overdue_execution_tasks` (23:30 daily) expires tasks past deadline

**June 24 status:** 3 avatars fully automated end-to-end (Hot-Thought2408, Flaky_Finder_13, StopAutomatic717). Pipeline: scrape → EPG build → LLM generate → auto-approve → execution task → timed email → human posts.

**Key design:** One email per slot, sent ~30 min before execution time. No batch dump.
**Routing:** Per-avatar `executor_email` + `executor_email_verified` flag. No global fallback — if no verified email, task is skipped.
**Anti-spam:** `can_resend()` limits to 3 deliveries per task, min 10 min between resends.
**Pre-dispatch liveness check (June 26):** Before sending email, `dispatch_due_email_tasks` verifies thread is not locked/removed/archived. Cancels task automatically if thread is dead. Executor "Can't Post" button for manual escape.
**Models:** `ExecutionTask`, `DeliveryAttempt` (delivery audit trail)
**Admin UI:** `/admin/tasks` — list, detail, resend, verify, cancel, SLA metrics
**System setting:** `email_tasks_enabled` (must be "true" to activate)

## CQS Execution Tasks (Implemented June 27, 2026)
Periodic CQS check task emails to executors. Closes self-healing loop for CQS=lowest avatars (zero EPG budget → no tasks → deadlock). Also keeps CQS fresh for healthy avatars.

**How it works:**
1. `generate_cqs_check_tasks_all_avatars` (07:00 daily) queries eligible avatars by interval
2. Creates ExecutionTask(task_type="cqs_check", subreddit="WhatIsMyCQS", text="What is my cqs?")
3. Standard dispatch pipeline delivers email to executor
4. Executor posts in r/WhatIsMyCQS → bot replies with CQS level
5. `check_cqs_all_avatars` (06:30 daily) reads reply → updates cqs_level → EPG budget restores

**Frequency:** CQS=lowest or age<90d → every 7 days. Mature+healthy → every 30 days.
**Kill switch:** `cqs_check_tasks_enabled` system setting.
**New files:** `app/services/cqs_task_generator.py`, `app/tasks/cqs_tasks.py`

## Client Email Notifications (Implemented July 9, 2026)
Automated lifecycle emails to client admins (client_admin + client_manager with verified email). Fire-and-forget — failure never blocks pipeline.

**Service:** `app/services/client_emails.py`
**Delivery:** Brevo HTTP API (via `send_task_email`)
**Recipients:** All `client_admin` + `client_manager` users with `email_verified=true` for that client (via User.client_id + UserClientAssignment)

**Five email types:**

| Type | Recipient | Trigger | Subject Example |
|------|-----------|---------|-----------------|
| **Weekly Visibility Digest** | Client admins | Mon 08:00 after `generate_weekly_reports_all_clients` | 📊 AI Visibility: 7.7% (+3.2pp) — BrandName |
| **Phase Milestone** | Client admins | `PhaseTransitionManager.promote()` or `.demote()` | 🎉 Avatar promoted to Phase 2 / ℹ️ Avatar — temporary phase adjustment |
| **Health Alert** | Client admins | `check_avatar_health()` on shadowban/suspended detection | ⚠️ Avatar — health issue detected |
| **Weekly System Health** | Owner | Sun 19:00 (Beat) | 🟢 Weekly System: HEALTHY — capacity, latency, predictions |
| **Weekly Business Summary** | Partner (fallback: owner) | Sun 19:15 (Beat) | 💼 Weekly Business: $399/mo MRR, 1 paying, 3 trials |

**Integration points:**
- `app/tasks/intelligence_report.py` → calls `send_weekly_visibility_digest()` after report published
- `app/services/phase.py` → `_send_phase_email()` in PhaseTransitionManager after promote/demote commit
- `app/services/health_checker.py` → calls `send_health_alert_email()` after auto-freeze on shadowban/suspended
- `app/tasks/weekly_emails.py` → `send_weekly_system_health_email` + `send_weekly_business_summary_email` (Beat: Sun 19:00 + 19:15)

**System Health Report includes:**
- Server capacity bars (CPU, Memory, Disk, PG Connections, PG Size, Redis) with % utilization
- LLM response times: avg, p50, p95, max + top slow operations
- Pipeline throughput WoW (generated, posted, conversion rate, EPG slots)
- AI cost analysis WoW (spent, calls, $/draft, daily avg, top operations)
- Predictive signals (cost trend, monthly projection, capacity warnings, throughput anomalies)
- Active alerts from `alert_aggregation.py`
- Server uptime

**Business Summary includes:**
- MRR, paying clients, trials, AI spend MTD, margin %
- Per-client health table (red/yellow/green + posts/week + avatars)
- Trial funnel (active → onboarded → first draft → converted)
- Attention items (expiring trials, zero-post clients)

**Beat schedule:** `app/tasks/beat_app.py` — `weekly-system-health-email` (Sun 19:00) + `weekly-business-summary-email` (Sun 19:15)
**Worker include:** `app/tasks/weekly_emails.py` added to `worker.py`

**P12 compliance:** Projected values in visibility digest use `~` prefix + disclaimer footer.
**Tested:** All 5 types sent to max.breger@gmail.com via production Brevo API (July 9, 2026).

## Draft Reconciliation (Implemented June 24, 2026)
Automatically links approved CommentDrafts to Reddit comments posted outside the system (executor posted manually but didn't submit permalink back).

**How it works:**
1. Runs inside `track_karma_all_avatars` (every 4h) — no extra API calls (reuses redditor object)
2. For each avatar with approved drafts (≤14 days old), fetches last 100 Reddit comments
3. Three-pass matching:
   - Pass 1: Exact body (first 120 chars normalized) → 98% confidence
   - Pass 2: Fuzzy body (≥85% Jaccard token overlap) → 85-97% confidence
   - Pass 3: Thread + timing (same thread, ±72h, similar length) → 75% confidence
4. On match: draft.status → "posted", sets reddit_comment_url + posted_at + reddit_score
5. Emits `draft_auto_reconciled` activity event

**Key design:** Zero manual work required. System autonomously discovers that an approved draft was posted.
**Safety:** Only matches approved drafts (never pending). Time window ≤72h. Won't double-match.
**Service:** `app/services/draft_reconciliation.py`

## Keywords Structure (JSONB in clients.keywords)
```json
{"high": ["term1", "term2"], "medium": ["term3"], "low": ["term4"]}
```

## Key Reference Files

### Knowledge Base & User Manuals
- `docs/kb/README.md` — **Knowledge Base hub** (start here for all documentation)
- `docs/kb/platform-overview.md` — What RAMP is, how it works, key concepts
- `docs/kb/glossary.md` — All terms, abbreviations, terminology rules
- `docs/kb/roles/` — User manuals by role (owner-partner, client-admin, client-manager, client-viewer, avatar-owner)
- `docs/kb/guides/` — Operational guides (onboarding, daily-ops, avatar-mgmt, pipeline, emergency)
- `docs/kb/admin/` — Technical docs (system-settings, deployment, troubleshooting)
- `docs/agents/` — Agent instruction files (client_strategy_agent.md)

### Planning & Architecture
- `docs/TODO.md` — Full product roadmap with diagrams, sprint plans, milestones
- `docs/roadmap.html` — Standalone dark-theme roadmap (for local viewing)
- `docs/memory.md` — Legacy project knowledge base (being superseded by docs/kb/)
- `docs/permission_matrix.md` — RBAC permission matrix (7 roles × 16 resource categories)
- `docs/aws_budget_may2026.md` — Detailed AWS budget with SQS/Valkey calculations
- `docs/aws_cost_estimate.md` — AWS cost estimate (summary, scaling projections)
- `docs/adr_sqs_valkey_migration.md` — Architecture Decision Record: SQS+Valkey migration
- `docs/ai_cost_benchmark.md` — AI token cost analysis

### Business & Legal
- `docs/Reddit Project Legal Risks.docx` — 6 categories of legal exposure (Tzvi's lawyer)
- `docs/Reddit_Avatar_Army_Business_Brief.docx` — Full product/pricing/agency model (May 2026)
- `buziness/` — Updates for Tzvi, client letters, avatar reports, forecasts

### Specs
- `.kiro/specs/mobile-posting-app/` — Mobile posting app spec (Flutter + backend API)
- `.kiro/specs/rbac-client-isolation/` — RBAC spec (DONE)
- `.kiro/specs/ai-native-expert-warming/` — AI-Native Expert warming system (niche authority, citability, entity linking)
- `.kiro/specs/automated-proxy-posting/` — Automated proxy posting (FRD complete)
- `.kiro/specs/subreddit-emotional-profile/` — Subreddit emotional profiling + avatar compatibility
- `.kiro/specs/quality-sentinel/` — Quality monitoring system
- `.kiro/specs/pipeline-resilience-hardening/` — Pipeline fault tolerance
- `.kiro/specs/intelligence-layer/` — Intelligence layer (in progress)
- `.kiro/specs/daily-ops-review/` — Daily Ops Review (Phase 1 deployed: models, routes, templates. Phase 2-3 pending)
- `.kiro/specs/ramp-operations-agent/` — Autonomous Operations Agent (requirements only, not implemented)
- `.kiro/specs/discovery-strategy-handoff/` — Discovery → Client Strategy handoff (Tasks 1-6 done, 7-11 pending)
- `.kiro/specs/browser-extension/` — Browser Extension for executor posting (CQS auto-check, comment posting, health monitoring, zero proxy needed)
- `.kiro/specs/risk-aware-activation/` — Risk-Aware Avatar Activation (zone routing safe→bridge→target using risk profiles, dangerous hours, graduation criteria) — **90% implemented July 2, 2026**
- `.kiro/specs/forecast-reporting-layer/` — Forecast & Reporting Layer v1 (5-layer truth-separated client reports: observed reality, execution intent, forecasting, composition, business impact) — **85% implemented July 4, 2026**
- `.kiro/specs/extension-posting-ab-test/` — Extension Posting A/B Test (controlled experiment comparing old_reddit vs manual_email vs new_reddit_debugger) — **90% implemented July 4, 2026**

### Legacy / Ori Handoff
- `docs/file_index.md` — Index of all Ori's handoff files
- `Ori/Reddit Personas-Grid view.csv` — Avatar voice profiles
- `Ori/keywords-Grid view.csv` — Scoring keywords
- `Ori/XM Cyber _ Write comments copy.json` — Ori's prompts (most valuable)

## Marketing Site
- **Location:** `marketing_site/` (separate FastAPI app)
- **Pages:** `/` (home), `/mobile`, `/proxy`, `/roadmap`, `/thank-you`
- **Template:** Jinja2 + Tailwind CDN, extends `marketing_base.html`
- **Roadmap page:** `/roadmap` — accordion phases, only current phase open by default
- **Server path:** marketing_site source lives at `/marketing_site/` on the server (NOT `/app/marketing_site/`)
- **Docker:** `marketing` service in `reddit_saas/docker-compose.yml`, build context `../marketing_site`
- **Deployment:** `rsync ... ./ ramp:/marketing_site/` then `cd /app && docker compose build --no-cache marketing && docker compose up -d marketing`
- **Nginx:** `location /` proxies to marketing_app (catch-all); specific paths like `/admin`, `/api/*` go to main_app
- **Live URL:** `http://161.35.27.165/roadmap`

## Language
- Code: English only (no Russian/Cyrillic in source code, comments, docstrings, or UI strings)
- Communication with user: Russian (default) or English
- Documents for Tzvi: English

## Pricing Model (from Business Brief)
- **Seed**: $149/mo — 1 avatar, 1 subreddit, 30 comments
- **Starter**: $399/mo — 3 avatars, 2 professional + hobbies, 60 comments
- **Growth**: $799/mo — 7 avatars, 5 professional + hobbies, 150 comments + 10 posts
- **Scale**: $1,499/mo — 15 avatars, unlimited subs, 400 actions
- **Agency**: Custom (~$2K+) — multi-client workspaces
- **Managed upsell**: +$1,200–$1,800/mo
- Pre-warmed avatars: Silver $199 one-time, Gold $499 one-time

## Avatar Phases (Updated — spec: phase-incubation-mentor-refactor)
- **Mentor** (pool, NOT a phase): Pre-warmed high-karma accounts. Identified by `avatar.pool == "mentor"`. Excluded from ALL automated pipelines. Not subject to phase evaluation. Set via admin action.
- **Phase 0 — Incubation** (days 1-10): Ultra-conservative engagement for fresh/low-karma/recovering avatars. 1 comment/day, safe subreddits only (AskReddit, CasualConversation, etc.), mandatory human approval, zero brand. Also serves as recovery destination (shadowban/CQS drop → demote here instead of freeze).
- **Phase 1** (months 1-2): Credibility building. Zero brand mentions. Hobby + general professional subs only.
- **Phase 2** (months 3-4): Content seeding & post creation. External source citations. No direct brand links yet.
- **Phase 3** (month 5+): Brand integration. Only when: sufficient karma + thread relevant + brand ratio below threshold.
- **Expert (authority_score > 75)**: AI-Native Expert achieved. Content optimized for external LLM citation (proxy signals maximized). Premium status, quality over quantity.

## AI-Native Expert — Strategic Goal

**Vision:** Transform avatar warming from basic karma farming into creating AI-Native Experts — authoritative content nodes that maximize probability of being indexed and cited by OpenAI, Google Gemini, and Perplexity as grounding sources. Direct citation is NOT measurable via API — system optimizes measurable proxy signals (topic coherence, content structure, engagement quality, posting consistency).

**Four Architectural Principles:**

1. **Topic Authority & Niche Clustering** — Each avatar operates within a single semantic cluster. All content contains LSI keywords, professional jargon, and named entities of the target niche. External embedding models assign high weight to the avatar in that cluster.

2. **LLM-Friendly & Citable Content** — Content follows patterns AI search engines prefer to cite: first-hand data markers ("In my tests...", "We deployed on 5k users..."), structured formats (lists, comparisons, step-by-step), and natural expert syntax (no AI-tell phrases like "Delve", "Crucial", "In conclusion").

3. **Tier-2 Trust Signals** — Optimize for quality karma (upvote-to-character ratio), thread depth (provoking discussions), saves, and cross-references by other authoritative users. These signals are what Perplexity and Google AI Overviews use for authority ranking.

4. **Entity Linking** — Naturally associate the client's brand with problem-solution patterns. Build persistent associations in LLM training data: [Problem] → [Brand mention as solution] → [Community approval (upvotes)].

**Key Models:** NicheProfile (per-avatar semantic cluster config), Authority Score (composite 0-100), Citability Score (per-comment), Content Archetypes (5 LLM-optimized formats).

**Spec:** `.kiro/specs/ai-native-expert-warming/` (requirements.md, design.md, tasks.md)

## Legal & Compliance Rules

### CRITICAL — Language Rules (applies to ALL written communication)
NEVER use these terms in code comments, docs, emails, Slack, or any written material:
- ❌ "fake accounts", "bot", "bots", "bot ring"
- ❌ "automating Reddit", "automated posting"
- ❌ "evading detection", "bypassing"
- ❌ "violating ToS", "against Reddit rules"

ALWAYS use these terms instead:
- ✅ "community engagement management"
- ✅ "persona-driven content strategy"
- ✅ "managed brand presence"
- ✅ "avatar" (not "fake account")
- ✅ "Digital Assets" (legal term for avatars in contracts)

### Liability Split — What's in the System vs. Under Client Signature

**System enforces (technical guardrails):**
- Phase eligibility gate (no brand mentions in Phase 1)
- Brand mention ratio check per avatar per week
- Subreddit posting frequency limits
- Content safety check (no defamatory/false claims about competitors)
- Promotional language detection
- All guardrail firings logged with timestamps (activity_events)
- All content approvals logged with user identity and timestamp
- Data retention limits (rolling window, not indefinite)
- Plan action caps (max comments/month per tier)

**Client signs and accepts (contractual):**
- Platform risk acceptance (Reddit ToS violation acknowledged)
- Avatars = service access, NOT property (no refund on ban)
- Platform Enforcement Events = force majeure (bans not compensable)
- Content approval = client liability transfer
- FTC/advertising compliance = client's responsibility
- Guardrail override = client's risk
- Liability cap = 3 months of fees
- No consequential damages
- Our right to suspend immediately if risk detected
- NDA on mechanism (never describe as "fake accounts" externally)

### Data Privacy Principles
- Scraped Reddit data: retain only what's operationally needed
- Rolling window retention (target: 90 days for threads, indefinite for activity logs)
- Avatar credentials: encrypted at rest
- Client data: standard confidentiality
- GDPR lawful basis: "legitimate interest" for public social media data
- CCPA: include "Do Not Sell" mechanism when self-serve launches

### Corporate Structure (planned)
- IP Holding Company (Cyprus) — owns software, brand, avatar inventory
- Operating Company — signs client contracts, processes payments
- Potential US LLC for US clients (later)
