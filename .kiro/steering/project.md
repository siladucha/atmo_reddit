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

## Tech Stack (Target Architecture)
- **Backend:** Python 3.11+ / FastAPI
- **Templates/UI:** Jinja2 + HTMX
- **CSS:** Tailwind CSS (CDN)
- **Database:** PostgreSQL / SQLAlchemy 2.0 / Alembic (on EC2 Docker initially, RDS later)
- **Auth:** JWT (python-jose + passlib), `is_superuser` flag for admin access
- **Task Queue:** AWS SQS Standard (replaces Celery + Redis broker)
- **Cache/Locks:** AWS ElastiCache Serverless Valkey (distributed locks, rate limiting, task results)
- **Reddit:** PRAW
- **AI/LLM:** LiteLLM (Gemini Flash for scoring, Claude Sonnet for generation)
- **Deploy:** EC2 t3.small + SQS + Valkey Serverless (Docker for app + PostgreSQL)
- **Observability:** CloudWatch (SQS metrics, Valkey metrics, EC2 metrics)

### Infrastructure Decisions (May 2026)
- **SQS over Celery**: Native DLQ, message persistence (14 days), visibility timeout, CloudWatch metrics. Cost: ~$0.30/mo at current scale.
- **Valkey Serverless over Redis Docker**: Managed HA, multi-AZ, no ops overhead. Cost: ~$6.14/mo (minimum 100 MB storage floor).
- **EC2 over ECS/Fargate**: Simpler, cheaper for single-instance deployment. Docker Compose on EC2 for app + PostgreSQL.
- **PostgreSQL on EC2 Docker** (initial): Migrate to RDS db.t4g.small ($24/mo) when data loss becomes unacceptable (5+ clients).

### Legacy Stack (being migrated away)
- ~~Celery + Redis~~ → AWS SQS + Valkey Serverless
- ~~Docker Compose (all-in-one)~~ → EC2 + managed AWS services

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
│   ├── main.py                # FastAPI app
│   ├── seed.py                # Seed data (NeuroYoga + defaults)
│   ├── dependencies/
│   │   └── admin.py           # require_superuser dependency
│   ├── middleware/
│   │   ├── auth.py            # JWT auth middleware
│   │   └── errors.py          # Error handling middleware
│   ├── models/                # SQLAlchemy models
│   │   ├── user.py            # User (is_superuser, is_active)
│   │   ├── client.py          # Client (keywords JSONB, profiles)
│   │   ├── avatar.py          # Avatar (client_ids array, voice)
│   │   ├── persona.py         # Persona (per-client voice profile)
│   │   ├── thread.py          # RedditThread (scoring fields)
│   │   ├── comment_draft.py   # CommentDraft (status workflow)
│   │   ├── post_draft.py      # PostDraft
│   │   ├── subreddit.py       # ClientSubreddit (+last_scraped_at)
│   │   ├── ai_usage.py        # AIUsageLog (cost tracking)
│   │   ├── audit.py           # AuditLog
│   │   ├── activity_event.py  # ActivityEvent (pipeline transparency)
│   │   ├── scrape_log.py      # ScrapeLog (per-subreddit metrics)
│   │   └── settings.py        # SystemSetting (key-value)
│   ├── routes/
│   │   ├── admin.py           # Admin panel (all /admin/* routes)
│   │   ├── pages.py           # User-facing pages (dashboard, review, etc.)
│   │   ├── auth.py            # Login/register API
│   │   ├── dashboard.py       # API stats endpoints (/api/admin/*)
│   │   ├── avatars.py         # Avatar API
│   │   ├── clients.py         # Client API
│   │   ├── pipeline.py        # Pipeline trigger API
│   │   └── review.py          # Review API
│   ├── services/
│   │   ├── admin.py           # Admin CRUD (users, clients, keywords, etc.)
│   │   ├── audit.py           # Audit logging
│   │   ├── ai.py              # LLM calls (LiteLLM)
│   │   ├── auth.py            # Auth logic
│   │   ├── generation.py      # Comment/post generation
│   │   ├── reddit.py          # Reddit API (PRAW)
│   │   ├── safety.py          # Content safety checks
│   │   ├── scoring.py         # Post scoring pipeline
│   │   ├── settings.py        # System settings service
│   │   └── transparency.py    # Activity events, pipeline stats, scrape freshness
│   ├── tasks/                 # SQS-based background tasks (migrating from Celery)
│   │   ├── sqs_consumer.py    # SQS long-poll consumer loop
│   │   ├── sqs_producer.py    # Send messages to SQS queues
│   │   ├── scheduler.py       # Periodic task scheduling
│   │   ├── orchestrator.py    # Pipeline orchestration
│   │   ├── scraping.py        # Reddit scraping tasks
│   │   └── ai_pipeline.py     # AI scoring/generation tasks
│   ├── templates/             # Jinja2 templates
│   │   ├── base.html          # Light theme (user pages)
│   │   ├── admin_base.html    # Dark theme (admin panel)
│   │   ├── admin_*.html       # Admin pages (20+ templates)
│   │   └── partials/          # HTMX partials
│   └── static/
├── alembic/                   # DB migrations
├── tests/                     # 93 tests (all passing)
├── pyproject.toml
├── Dockerfile
└── docker-compose.yml
```

## What's Built (MVP Status)
- **Admin panel** (dark theme): dashboard, user/client/persona/keyword/subreddit CRUD, task monitoring, system health, AI costs, audit logs, billing placeholder
- **7-step onboarding wizard**: client profile → subreddits → keywords → avatars → personas → pipeline config → test run
- **NeuroYoga seed data**: first client (ATMO) with subreddits, keywords, persona
- **User-facing pages**: dashboard, review queue, threads, avatars, settings
- **Pipeline**: scrape → score → generate → edit (SQS tasks, migrating from Celery)
- **93 tests passing** (pytest)

## What's Built — Activity Feed & Transparency (new)
- `ActivityEvent` model + `ScrapeLog` model + `last_scraped_at` on ClientSubreddit
- `services/transparency.py` — record_activity_event, get_activity_events, get_pipeline_stats, get_scrape_freshness
- Pipeline instrumentation: scraping, scoring, generation, review all emit activity events
- Admin dashboard Activity Feed (HTMX async load, client filter)
- Client Transparency Dashboard at `/admin/clients/{id}/transparency`
- Subreddit freshness tracking with stale indicators

## What's NOT Built Yet
- **System Topology Timeline** — real-time pipeline node visualization with history + forecast (spec in `.kiro/steering/system_topology_dashboard.md`)
- Self-service client access (multi-tenancy, role-based views)
- Customer Success Dashboard (business metrics per client)
- Enhanced System Health (detailed diagnostics, load metrics)
- Real billing/payments
- Production deployment (Docker Compose ready, not deployed)
- Plan action limits enforcement (max_comments_per_month)
- Data retention cleanup (TTL for old scraped threads)
- Agency multi-tenant workspace (deferred until 3+ agency clients)
- White-label (custom domain, branding) — deferred
- Cross-avatar routing / upvote coordination — deferred
- Viral acceleration rules — deferred
- GoLogin/AdsPower browser automation — deferred (posting is manual)
- Auto-generated PDF reports — deferred

## Key Data Flow
1. SQS worker scrapes subreddits → saves RedditThread records
2. AI scores threads (relevance/quality/strategic) → tags: engage/monitor/skip
3. AI generates comment drafts for "engage" threads
4. Human reviews drafts → approve/reject/edit
5. Approved comments posted manually to Reddit

## Task Architecture (Target)
- **Producer**: FastAPI app / scheduler sends messages to SQS queues
- **Consumer**: Python workers (asyncio loop) poll SQS with long polling (20s)
- **Scheduler**: EventBridge Scheduler (replaces Celery Beat) or cron on EC2
- **Locks**: Valkey SETNX with Lua atomic release (same pattern as current)
- **Rate Limiter**: Valkey sorted set sliding window (same pattern as current)
- **DLQ**: SQS Dead Letter Queue per task type (automatic after N failures)
- **Results**: Valkey with TTL (short-lived, 5 min default)

## Comment Draft Status Workflow
`pending` → `approved` / `rejected` → `posted`

## Keywords Structure (JSONB in clients.keywords)
```json
{"high": ["term1", "term2"], "medium": ["term3"], "low": ["term4"]}
```

## Key Reference Files
- `docs/memory.md` — Project knowledge base
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
