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
- **Self-service clients** — they manage their own setup (future, not yet implemented)
- Multi-tenancy with role-based access is planned but deferred to post-MVP
- **Revenue model**: Monthly SaaS subscription ($149–$1,499) + managed service upsell (+$1,200–$1,800) + pre-warmed avatar fees (one-time $199–$499)
- **Agency model**: Per-client-slot pricing ($999–$3,499/mo for 3–20 clients). Annual contracts only.
- **Key moat**: Pre-warmed avatar inventory (aged accounts with karma). Cannot be replicated overnight by competitors.

## Tech Stack (Current — Celery/Redis on DigitalOcean)
- **Backend:** Python 3.11+ / FastAPI
- **Templates/UI:** Jinja2 + HTMX
- **CSS:** Tailwind CSS (CDN)
- **Database:** PostgreSQL 16 / SQLAlchemy 2.0 / Alembic (Docker on DO Droplet)
- **Auth:** JWT (python-jose + passlib), `is_superuser` flag for admin access
- **Task Queue:** Celery + Redis
- **Cache/Locks:** Redis 7
- **Reddit:** PRAW
- **AI/LLM:** LiteLLM (Gemini Flash for scoring, Claude Sonnet for generation)
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
- **Domain:** None yet (access via IP:8000)
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
ssh root@161.35.27.165 "curl -s http://localhost:8000/health"

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
│   │   └── admin.py           # require_superuser dependency
│   ├── middleware/
│   │   ├── auth.py            # JWT auth middleware
│   │   └── errors.py          # Error handling middleware
│   ├── models/                # SQLAlchemy models (23 models)
│   │   ├── user.py            # User (is_superuser, is_active)
│   │   ├── client.py          # Client (keywords JSONB, profiles)
│   │   ├── avatar.py          # Avatar (client_ids, voice, is_frozen, warming_phase)
│   │   ├── thread.py          # RedditThread (is_locked, locked_detected_at)
│   │   ├── comment_draft.py   # CommentDraft (status workflow, learning_metadata)
│   │   ├── post_draft.py      # PostDraft
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
│   │   └── strategy_document.py # StrategyDocument
│   ├── schemas/               # Pydantic validation schemas
│   │   ├── avatar_analysis.py # BehavioralProfile, AvatarAnalysisRequest
│   │   └── llm_outputs.py     # ScoringOutput, CommentOutput
│   ├── routes/
│   │   ├── admin.py           # Admin panel (all /admin/* routes)
│   │   ├── pages.py           # User-facing pages (dashboard, review, etc.)
│   │   ├── auth.py            # Login/register API
│   │   ├── avatar_analysis.py # Avatar behavioral analysis API
│   │   ├── avatar_pipeline.py # Avatar pipeline management
│   │   ├── avatars.py         # Avatar API
│   │   ├── clients.py         # Client API
│   │   ├── dashboard.py       # API stats endpoints (/api/admin/*)
│   │   ├── dry_run.py         # Dry run testing endpoints
│   │   ├── export.py          # Data export endpoints
│   │   ├── pipeline.py        # Pipeline trigger API
│   │   └── review.py          # Review API (with learning hook)
│   ├── services/              # Business logic (48 services)
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
│   │   ├── pre_filter.py      # Pre-filter logic (avatar health exclusion)
│   │   ├── presence.py        # Avatar subreddit presence scanning
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
│   │   └── transparency.py    # Activity events, pipeline stats
│   ├── tasks/                 # Celery background tasks
│   │   ├── ai_pipeline.py     # AI scoring/generation (retry, kill switches)
│   │   ├── health_check.py    # Avatar health checks
│   │   ├── heartbeat.py       # Worker heartbeat
│   │   ├── karma_tracking.py  # Karma tracking tasks
│   │   ├── orchestrator.py    # Pipeline orchestration
│   │   ├── presence.py        # Avatar presence scanning
│   │   ├── profile_analytics.py # Profile analytics tasks
│   │   ├── queue_ticker.py    # Queue tick (scrape scheduling)
│   │   ├── scraping.py        # Reddit scraping tasks
│   │   ├── strategy.py        # Strategy generation tasks
│   │   └── worker.py          # Celery worker configuration
│   ├── templates/             # Jinja2 templates (50 pages + 65 partials)
│   │   ├── base.html          # Light theme (user pages)
│   │   ├── admin_base.html    # Dark theme (admin panel)
│   │   ├── admin_*.html       # Admin pages (35+ templates)
│   │   └── partials/          # HTMX partials (65 files)
│   └── static/
├── alembic/                   # DB migrations
├── tests/                     # 40 test files
├── Makefile                   # Docker/DB commands (db-sync, fresh-start, etc.)
├── DOCKER.md                  # Container data management docs
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
└── entrypoint.sh              # Migrations + seed on startup
```

## What's Built (MVP Status — May 12, 2026)

### Core Platform
- **Admin panel** (dark theme): dashboard, user/client/persona/keyword/subreddit CRUD, task monitoring, system health, AI costs, audit logs, billing placeholder
- **7-step onboarding wizard**: client profile → subreddits → keywords → avatars → personas → pipeline config → test run
- **NeuroYoga seed data**: first client (ATMO) with subreddits, keywords, persona
- **User-facing pages**: dashboard, review queue, threads, avatars, settings
- **JWT authentication** + admin access control
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
- Global kill switches (pipeline_enabled, generation_enabled, scrape_enabled)
- Context isolation assertions (avatar-client ownership verified at runtime)
- Shadowban detection (5-state health model, auto-freeze)
- CQS (Contributor Quality Score) automated monitoring — periodic batch check via Celery Beat, auto-freeze on lowest (Phase 2+)
- Text sanitizer (strips Markdown, Unicode, formatting artifacts)
- Content safety checks (brand ratio, phase gates, promotional language)
- Client deactivation cascade (is_active=false → assignments deactivated → avatars unassigned → all tasks skip)

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

## What's NOT Built Yet
- Production deployment (Docker Compose ready, not deployed to AWS)
- Self-service client access (multi-tenancy, role-based views)
- Strategy Questions feedback loop — LLM generates questions_for_client in strategy; future: multiple-choice answers (A/B/C/D) + free text field, saved as client preferences, injected into next strategy generation. MVP: questions visible in strategy markdown only, no answer mechanism.
- Subreddit rule extraction (PRAW sidebar/wiki → LLM parsing → compliance checks)
- Comment outcome tracking (karma snapshots at 4h/24h/48h + removal detection)
- Budget engine (smart daily limits per avatar)
- Cross-avatar deduplication (prevent two avatars commenting on same thread)
- Real billing/payments
- Plan action limits enforcement (max_comments_per_month)
- Data retention cleanup (TTL for old scraped threads)
- Agency multi-tenant workspace (deferred until 3+ agency clients)
- White-label (custom domain, branding) — deferred
- Cross-avatar routing / upvote coordination — deferred
- Viral acceleration rules — deferred
- GoLogin/AdsPower browser automation — deferred (posting is manual)
- Auto-generated PDF reports — deferred

## Key Data Flow
1. Celery worker scrapes subreddits → saves RedditThread records (skips locked threads)
2. AI scores threads (relevance/quality/strategic) → tags: engage/monitor/skip (skips locked)
3. AI generates comment drafts for "engage" threads (liveness check for stale threads)
4. Self-learning loop injects few-shot examples + correction patterns into generation prompt
5. Human reviews drafts → approve/reject/edit (locked indicator visible)
6. Learning service captures edits → extracts patterns → improves future generation
7. Approved comments posted manually to Reddit
8. Periodic liveness refresh auto-rejects drafts for newly locked threads

## Task Architecture (Current — Celery + Redis)
- **Producer**: FastAPI app / Celery Beat sends tasks
- **Consumer**: Celery workers (prefork pool)
- **Scheduler**: Celery Beat (periodic tasks)
- **Locks**: Redis SETNX with Lua atomic release
- **Rate Limiter**: Redis sorted set sliding window
- **Retry**: bind=True, max_retries=3, countdown=60×2^attempt (AI tasks only)

### Celery Beat Schedule (UTC)
| Time | Task | Purpose |
|------|------|---------|
| every 60s | `queue_tick` | Scrape scheduling (gated by DB interval) |
| every 60s | `system_heartbeat` | System health pulse |
| 05:20 | `snapshot_profile_analytics_all_avatars` | Profile analytics |
| 06:00 | `evaluate_all_avatar_phases` | Phase evaluation |
| 06:30 | `check_cqs_all_avatars` | CQS batch check (auto-freeze on lowest) |
| 07:30, 13:30 | `health_check_all_avatars` | Shadowban/suspension detection |
| 08:00, 14:00 | `run_full_pipeline_all_clients` | Score → Generate → Posts |
| 10:00 | `run_hobby_pipeline_all_avatars` | Hobby scrape + generate |
| every 4h | `track_karma_all_avatars` | Karma tracking |

## Comment Draft Status Workflow
`pending` → `approved` / `rejected` → `posted`

## Keywords Structure (JSONB in clients.keywords)
```json
{"high": ["term1", "term2"], "medium": ["term3"], "low": ["term4"]}
```

## Key Reference Files
- `docs/memory.md` — Project knowledge base
- `docs/update_for_tzvi_may11.md` — Latest status update for Tzvi
- `docs/aws_budget_may2026.md` — Detailed AWS budget with SQS/Valkey calculations
- `docs/aws_cost_estimate.md` — AWS cost estimate (summary, scaling projections)
- `docs/adr_sqs_valkey_migration.md` — Architecture Decision Record: SQS+Valkey migration
- `docs/ai_cost_benchmark.md` — AI token cost analysis
- `docs/file_index.md` — Index of all Ori's handoff files
- `docs/Reddit Project Legal Risks.docx` — 6 categories of legal exposure (Tzvi's lawyer)
- `docs/Reddit_Avatar_Army_Business_Brief.docx` — Full product/pricing/agency model (May 2026)
- `Reddit Personas-Grid view.csv` — Avatar voice profiles
- `keywords-Grid view.csv` — Scoring keywords
- `XM Cyber _ Write comments copy.json` — Ori's prompts (most valuable)

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
