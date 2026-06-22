---
inclusion: always
---

# Reddit Marketing SaaS — Project Context

## What This Is
A Reddit marketing SaaS platform. AI monitors subreddits, scores posts, generates comments from persona-based avatars, and humans review before manual posting.

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
- **AI/LLM:** LiteLLM (Gemini Flash for scoring, Claude Sonnet for generation)
- **Real-time:** Server-Sent Events (SSE) + Redis PubSub (notifications)
- **Mobile App:** Flutter (Dart) — posting app for avatar owners
- **Deploy:** DigitalOcean Droplet + Docker Compose (app + PostgreSQL + Redis + Celery)
- **Observability:** Logging + admin dashboard

### Production Server (DigitalOcean)
- **Droplet:** `reddit-saas` — 2 vCPU, 4 GB RAM, 60 GB SSD
- **Region:** Frankfurt (FRA1) 🇩🇪
- **OS:** Ubuntu 24.04 LTS
- **IPv4:** `161.35.27.165`
- **Cost:** ~$23/mo (with backups)
- **Docker Compose:** `docker-compose.yml` + `docker-compose.prod.yml` (memory limits, reduced concurrency)
- **Access:** `ssh root@161.35.27.165`, project at `/app/`
- **Domain:** gorampit.com (SSL via Let's Encrypt)
- **Backups:** DO weekly backups enabled

### Deployment Commands (from local Mac)
```bash
# Push code to server:
cd reddit_saas
rsync -avz --exclude='.venv/' --exclude='__pycache__/' --exclude='.hypothesis/' \
  --exclude='.git/' --exclude='*.pyc' --exclude='.DS_Store' --exclude='logs/' \
  --exclude='.env' --exclude='.claude/' --exclude='.kiro/' --exclude='.vscode/' \
  --exclude='tests/' --delete \
  ./ root@161.35.27.165:/app/

# Rebuild and restart on server:
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml build && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"

# Check health:
ssh root@161.35.27.165 "curl -s http://localhost/health"

# View logs:
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f --tail=50"

# DB sync (local → server):
# 1. Dump local: docker compose exec -T db pg_dump -U reddit_saas_user -d reddit_saas --no-owner --format=custom -f /tmp/dump.custom
# 2. Copy out: docker compose cp db:/tmp/dump.custom /tmp/reddit_saas_live.custom
# 3. Upload: scp /tmp/reddit_saas_live.custom root@161.35.27.165:/tmp/
# 4. Restore: ssh root@161.35.27.165 "docker compose ... exec -T db pg_restore -U reddit_saas_user -d reddit_saas --clean --if-exists --no-owner --single-transaction /tmp/reddit_saas_live.custom"
```

### Infrastructure Decisions (May 2026)
- **DigitalOcean over AWS**: Simpler, cheaper for MVP. Single droplet with Docker Compose.
- **AWS migration planned**: When enterprise clients require it OR 100+ avatars OR ops burden > 4h/week. $7K AWS credits available.
- **PostgreSQL in Docker** (current): Migrate to DO Managed DB ($15/mo) when 5+ paying clients.
- **SQS migration deferred**: Celery + Redis works fine for current scale (50 avatars).
- **Timezone**: All containers, PostgreSQL, Celery Beat, and logs use `Asia/Jerusalem` (IDT/IST). Set via `TZ` env var in docker-compose + `PGTZ` for PostgreSQL + `-c timezone=Asia/Jerusalem` in postgres command + Celery `timezone="Asia/Jerusalem"` config.

### Versioning & Environment Controls (June 2026)
- **VERSION file**: `reddit_saas/VERSION` — single source of truth (currently `0.3.0`)
- **`app/version.py`**: reads VERSION file, exposes `__version__`
- **Health endpoint**: `/health` returns `{"version": "0.3.0", "env": "...", "posting_disabled": true/false, ...}`
- **UI footer**: version + env + posting status shown in both `base.html` and `admin_base.html` (sidebar) for all roles
- **`POSTING_DISABLED` env var**: env-level kill switch for automated posting. Cannot be toggled from admin UI.
  - Server `.env`: `POSTING_DISABLED=true` (posting blocked until business decision)
  - Local `.env`: not set (defaults to `false`, posting works for local avatar testing)
  - Checked as gate #0 in `posting_safety.py` — before all other checks
- **`pyproject.toml` version**: kept in sync with VERSION file
- **Bump workflow**: update `reddit_saas/VERSION` → pyproject.toml auto-reads it at build time

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
│   ├── models/                # SQLAlchemy models (47 models)
│   │   ├── user.py            # User (role, is_active, client_id)
│   │   ├── user_role.py       # UserRole enum (owner/partner/client_admin/client_manager/client_viewer/avatar_manager/b2c_user)
│   │   ├── user_client_assignment.py # UserClientAssignment (user↔client mapping)
│   │   ├── client.py          # Client (keywords JSONB, profiles, max_avatars, plan_type, draft_approval_enabled)
│   │   ├── avatar.py          # Avatar (client_ids, voice, is_frozen, warming_phase, is_farm_avatar)
│   │   ├── avatar_rental.py   # AvatarRental (farm avatar rentals)
│   │   ├── avatar_assignment.py # AvatarAssignment (avatar↔owner for mobile posting) [PLANNED]
│   │   ├── thread.py          # RedditThread (is_locked, locked_detected_at)
│   │   ├── comment_draft.py   # CommentDraft (status workflow, learning_metadata, posted_by, posted_source)
│   │   ├── post_draft.py      # PostDraft (posted_by, posted_source)
│   │   ├── subreddit.py       # Subreddit, ClientSubreddit, ClientSubredditAssignment
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
│   │   ├── voice_feedback.py  # VoiceFeedback (client voice/tone training signals)
│   │   ├── client_action_log.py # ClientActionLog (rate-limited portal actions)
│   │   ├── subreddit_request.py # SubredditRequest (client requests: pending → approved/rejected)
│   │   └── avatar_subreddit_compatibility.py # AvatarSubredditCompatibility (emotional profile scoring)
│   ├── schemas/               # Pydantic validation schemas
│   │   ├── avatar_analysis.py # BehavioralProfile, AvatarAnalysisRequest
│   │   └── llm_outputs.py     # ScoringOutput, CommentOutput
│   ├── routes/
│   │   ├── admin.py           # Admin panel (all /admin/* routes)
│   │   ├── mobile.py          # Mobile API (/api/mobile/*) [PLANNED]
│   │   ├── pages.py           # User-facing pages (dashboard, review, etc.)
│   │   ├── auth.py            # Login/register API
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
│   │   └── oauth.py           # OAuth callback for Reddit
│   ├── services/              # Business logic (95+ services)
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
│   │   ├── distributed_lock.py # Redis distributed locks
│   │   ├── dry_run.py         # Dry run pipeline testing
│   │   ├── export.py          # Data export
│   │   ├── generation.py      # Comment generation (with learning injection)
│   │   ├── health_checker.py  # Shadowban/health detection
│   │   ├── health_metrics.py  # Health metrics aggregation
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
│   │   ├── encryption.py      # Fernet field encryption (proxy URLs, passwords, tokens)
│   │   ├── posting_safety.py  # 9 pre-posting safety gates
│   │   ├── timing_engine.py   # Jitter, active hours, daily cap, peak bias
│   │   ├── praw_factory.py    # Dual-mode PRAW client (password + OAuth) with proxy
│   │   ├── posting.py         # Core posting orchestration (load → safety → post → audit)
│   │   ├── notifications.py   # Notification creation + Redis PubSub publishing
│   │   ├── task_notifications.py # Celery-safe notification helpers (pipeline, EPG, draft, avatar)
│   │   ├── smart_scoring.py   # Budget-aware scoring (N threads per avatar, 90% cost reduction)
│   │   ├── risk_prediction.py # AI ban risk forecasting (6-factor composite + prescriptive actions)
│   │   ├── billing_dashboard.py # Cost/usage analytics (AI costs, plan usage, P&L, trends)
│   │   ├── trial_guard.py     # 14-day trial expiry check (gates pipeline tasks)
│   │   ├── team_management.py # Team RBAC enforcement (user create/edit permissions by role)
│   │   ├── safety_blocks.py   # Brand mention protection (blocks Phase 1/2 brand drafts)
│   │   ├── avatar_onboard_analysis.py # PRAW fetch + Claude AI classification for avatar onboarding
│   │   └── onboarding/        # AI-driven onboarding subsystem (prompts, scraper, quality gate, landscape)
│   ├── tasks/                 # Celery background tasks
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
│   │   └── worker.py          # Celery worker configuration
│   ├── templates/             # Jinja2 templates (60+ pages + 100+ partials)
│   │   ├── base.html          # Light theme (user pages)
│   │   ├── admin_base.html    # Dark theme (admin panel)
│   │   ├── admin_*.html       # Admin pages (35+ templates)
│   │   └── partials/          # HTMX partials (65 files)
│   └── static/
├── alembic/                   # DB migrations
├── tests/                     # 50+ test files (incl. RBAC property-based tests)
├── Makefile                   # Docker/DB commands (db-sync, fresh-start, etc.)
├── DOCKER.md                  # Container data management docs
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
└── entrypoint.sh              # Migrations + seed on startup

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

## What's Built (Status — June 19, 2026)

### Core Platform
- **Admin panel** (dark theme): dashboard, user/client/persona/keyword/subreddit CRUD, task monitoring, system health, AI costs, audit logs, billing placeholder
- **7-step onboarding wizard**: client profile → subreddits → keywords → avatars → personas → pipeline config → test run
- **NeuroYoga seed data**: first client (ATMO) with subreddits, keywords, persona
- **User-facing pages**: dashboard, review queue, threads, avatars, settings
- **RBAC** (7 roles): owner, partner, client_admin, client_manager, client_viewer, avatar_manager, b2c_user — with query scoping, permission guards, LLM context isolation
- **JWT authentication** + role-based access control + client data isolation
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

### Discovery Engine (June 2026)
- **Session-based research** — create → extract entities → confirm → research → hypotheses → report → strategy handoff
- **Entity extraction** — LLM-based extraction from client brief
- **Hypothesis engine** — generate, validate, score confidence
- **Reddit researcher** — PRAW-based community intelligence gathering
- **Continuous discovery** — weekly automated runs (Sunday 04:00)
- **Strategy handoff** — convert findings to strategy documents

### GEO/AEO Prompt Monitoring (June 2026)
- **Prompt management** — track brand visibility queries for AI platforms
- **Competitor tracking** — monitor competitor mentions in AI responses
- **Brand detection** — automated scoring of brand presence in AI search
- **Citation parsing** — extract and analyze citations from AI responses
- **Batch execution** — run monitoring queries with history and detail views

### Client Portal (June 2026)
- **Full portal** — home, review queue, avatars, avatar detail, subreddits, keywords, strategy, report, EPG
- **Draft management** — approve, skip, mark posted, edit from portal
- **RBAC-scoped** — clients see only their own data
- **Client Hub** — tab-based overview with lazy-loaded partials

### Decision Center (June 2026)
- **Live Pulse** — real-time system status (pipeline, avatars, slots, events)
- **Queue** — pending decisions (drafts, approvals)
- **Insights** — system-generated recommendations and alerts
- **Bulk approve** — batch operations
- **Execute action** — trigger pipeline ops from Decision Center
- **Risk Prediction** — 6-factor ban risk scoring + prescriptive actions per avatar

### Self-Service Onboarding (June 2026)
- **6-step AI wizard** — website URL → AI scrapes → ICP synthesis → keywords/subreddits suggestions → avatar config → quality gate → activate
- **Trial signup** — work-email-only, 14-day free trial (plan_type="trial")
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

### Security Hardening (June 2026)
- **SecurityHeadersMiddleware** — X-Frame-Options, X-Content-Type-Options, HSTS, Referrer-Policy, Permissions-Policy
- **RateLimitMiddleware** — 5 auth attempts per 15 min per IP (production only), global 100 req/min per IP
- **Custom 403 page** — friendly HTML error page instead of raw JSON

## What's NOT Built Yet
- ~~Production deployment~~ → **DONE** (gorampit.com, DigitalOcean, SSL)
- ~~Automated Posting — Admin UI~~ → **DONE** (posting dashboard with stats, events, traceability)
- **Automated Posting — Proxy integration** — need to buy residential proxies (ProxyJet)
- **Automated Posting — OAuth mode** — pending Reddit approval for web app creation
- ~~Comment outcome tracking~~ → **DONE** (KarmaSnapshot at 4h/24h/48h/7d + deletion detection)
- ~~Budget engine~~ → **DONE** (EPG 2.0 AttentionBudget + daily cap + portfolio allocation)
- ~~Self-service onboarding~~ → **DONE** (6-step AI wizard + 14-day trial)
- Strategy Questions feedback loop — future: multiple-choice answers, saved as client preferences
- Subreddit rule extraction (PRAW sidebar/wiki → LLM parsing → compliance checks)
- Cross-avatar deduplication (prevent two avatars commenting on same thread)
- Real billing/payments (Stripe)
- Plan action limits enforcement (max_comments_per_month)
- Data retention cleanup (TTL for old scraped threads)
- Agency multi-tenant workspace (deferred until 3+ agency clients)
- White-label (custom domain, branding) — deferred
- Cross-avatar routing / upvote coordination — deferred
- Auto-generated PDF reports — deferred

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

## Task Architecture (Current — Celery + Redis)
- **Producer**: FastAPI app / Celery Beat sends tasks
- **Consumer**: Celery workers (prefork pool)
- **Scheduler**: Celery Beat (periodic tasks)
- **Locks**: Redis SETNX with Lua atomic release
- **Rate Limiter**: Redis sorted set sliding window
- **Retry**: bind=True, max_retries=3, countdown=60×2^attempt (AI tasks only)

### Celery Beat Schedule (Israel Time — Asia/Jerusalem) — Updated June 19, 2026
| Time | Task | Purpose |
|------|------|---------|
| every 60s | `queue_tick` | Scrape scheduling (gated by DB interval) |
| every 60s | `system_heartbeat` | System health pulse |
| every 5 min | `execute_pending_posts` | Automated posting (approved EPG slots) |
| every 4h at :15 | `track_karma_all_avatars` | Karma tracking |
| every 4h at :45 | `snapshot_comment_outcomes` | Karma/deletion snapshots |
| 01:00 | `compute_daily_performance_metrics` | Aggregate yesterday's avatar metrics |
| 01:30 | `archive_old_decision_records` | Prune records > 90 days |
| 02:00 | `run_feedback_loop_all` | Outcome analysis → EPG model correction |
| 03:00 Sun | `scrape_repurpose_all_subreddits` | Weekly evergreen harvest |
| 04:00 Sun | `run_continuous_discovery_all` | Weekly continuous discovery |
| 05:20 | `snapshot_profile_analytics_all_avatars` | Profile analytics |
| 06:00 | `evaluate_all_avatar_phases` | Phase evaluation |
| 06:30 | `check_cqs_all_avatars` | CQS batch check (auto-freeze on lowest) |
| 07:30, 13:30 | `health_check_all_avatars` | Shadowban/suspension detection |
| 07:45, 13:45 | `scrape_hobby_all_avatars` | Hobby scraping (before EPG) |
| 08:00, 14:00 | `run_full_pipeline_all_clients` | Score → Generate → Posts |
| 08:15, 14:15 | `build_and_generate_epg_all_avatars` | EPG plan + generate |
| 12:15, 18:15 | `check_karma_outcomes` | 4h karma outcome check |
| 00:15, 06:15 | `check_karma_outcomes` | 24-28h karma outcome check |
| 04:30 Sun | `refresh_subreddit_emotional_profiles` | Weekly subreddit emotional profile refresh |

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
- **Deployment:** `rsync ... ./ root@161.35.27.165:/marketing_site/` then `cd /app && docker compose build --no-cache marketing && docker compose up -d marketing`
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

## Avatar Phases (from Business Brief)
- **Mentor (phase 0)**: Pre-warmed high-karma accounts. Excluded from ALL automated pipelines (scoring, generation, hobby, posts). Not subject to phase evaluation/promotion/demotion. Used for reputation presence, not automated engagement. Set via admin Phase Override.
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
