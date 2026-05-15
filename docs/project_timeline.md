# RAMP / ThreddOps — Project Development Timeline

_Compiled: May 13, 2026_

---

## Starting Point: Ori's Legacy (before April 29, 2026)

Ori built a single-client PoC for XM Cyber on a **no-code stack**:
- 9 n8n workflows + Supabase + Airtable
- Hardcoded to one client (XM Cyber)
- Manual review via Airtable
- AI comment strategy: Paradigm Shift → Helpful → Karma Play
- 4 avatars: Marcus Thorne (CISO), Derek Walsh (VM Lead), Leon Grant (Security Architect), Lucas Parker (Director SecOps)
- AI cost: ~$200/month

**Known problems:** no multi-tenancy, no deduplication, burst scraping (100 API calls at once), no learning from human edits, random persona selection.

---

## Session 1 — Analysis (April 29, 2026)

- Reviewed all 25+ files from Ori's handoff package
- Created core documentation: `memory.md`, `file_index.md`, `ai_cost_benchmark.md`, `letter_to_tzvi.md`
- **Key finding:** AI cost can be reduced from ~$200 to ~$36/month per client (prompt caching + Gemini Flash for scoring)

---

## Session 2 — Call with Tzvi (May 1, 2026)

- **Agreement:** 50/50 partnership — Tzvi (business/clients), Max (all development)
- **Decision:** Build SaaS from scratch — no n8n, no Airtable
- **Stack:** FastAPI + Jinja2/HTMX + PostgreSQL + Celery + Redis + PRAW + LiteLLM
- **Funding:** Prepaid pilot client (~$4K setup + ~$2K/month)
- **Legal entity:** Cyprus company, Tzvi as CEO

---

## Sessions 3–4 — Core MVP Build (May 1–3, 2026)

**Built in 3 days:**

| Component | Status |
|-----------|--------|
| FastAPI skeleton, config, DB (11 tables) | ✅ |
| Auth: register/login/JWT cookie | ✅ |
| Reddit scraping (PRAW), AI service (LiteLLM) | ✅ |
| Scoring / generation / safety pipeline | ✅ |
| 12 Jinja2 + HTMX templates (Tailwind) | ✅ |
| Avatar CRUD + health checks | ✅ |
| Celery Beat scheduler (4 jobs: 8:00, 14:00, 10:00, every 12h) | ✅ |
| Auth middleware + error middleware | ✅ |
| Orchestrator tasks (batch across all clients/avatars) | ✅ |
| **60 unit tests (9 modules)** | ✅ |
| Daily log rotation (7-day history) | ✅ |

---

## May 7 — Pipeline Readiness Report

**Comment pipeline — 100% implemented** (full parity with Ori's n8n workflows):

```
queue_tick (every 60s) → scrape subreddits
      ↓
run_full_pipeline (08:00, 14:00 UTC) → score_threads (Gemini Flash)
      ↓
generate_comments (Claude Sonnet)
├─ select_persona → AI picks best avatar per thread
├─ generate_comment → writes draft
└─ edit_comment → polishes tone
      ↓
Human review queue → Manual posting to Reddit
```

**Post-creation pipeline** — stub (does not block the pilot; comments are 90% of the product value).

---

## May 8 — Meeting with Tzvi: 4 Critical Blockers Identified

| Blocker | Status at meeting end |
|---------|----------------------|
| Shadowban detection | ⏳ |
| Self-learning loop | ⏳ |
| Comment rendering bug | ⏳ |
| XM Cyber data loaded into system | ⏳ |

---

## May 11 — All Blockers Resolved. Full Status Report to Tzvi

**10 days (May 1–11) — complete system built from scratch:**

| Category | Achievement |
|----------|-------------|
| **Automated tests** | 187 passing (up from 60) |
| **Admin panel** | Dark theme, dashboard, users, clients, avatars, personas, keywords, subreddits, AI costs, audit logs |
| **Client onboarding wizard** | 7-step flow for new client setup |
| **Infrastructure** | Dockerized, AWS-ready, architecture supports 10+ clients on a $27/month server |
| **Alembic migrations** | Full DB migration system in place |
| **Client deactivation cascade** | `is_active=false` → subreddit assignments off → avatars unassigned → all pipeline tasks skip |

**AI Pipeline improvements over Ori's legacy system:**

| Feature | ThreddOps | Ori (legacy) |
|---------|-----------|--------------|
| Persona routing | AI selects best avatar by subreddit karma history + voice fit | Random or manual |
| Strategy | 5 engagement approaches × 3 strategic angles, AI picks optimal combination | Fixed templates |
| **Self-learning loop** | Learns from every human edit, extracts correction patterns, injects few-shot examples into future prompts | Zero learning capability |
| Per-client scoring | Same thread can score differently for different clients (multi-tenant foundation) | One score per thread, hardcoded to XM Cyber |
| Comment placement | AI decides WHERE in the thread to reply (depth + reasoning) | Fixed position |
| Deduplication | `reddit_native_id` UNIQUE constraint at DB level | Timestamp filter only (24h window) |
| Scraping model | Continuous (1.7 calls/min, Redis distributed locks) | Burst: 100 API calls at once |
| AI cost | ~$36/month per client | ~$200/month |

---

## May 12 — Specification Audit

**46 specs tracked in `.kiro/specs/`:**

| Status | Count |
|--------|-------|
| Fully completed | **9** |
| Partially completed | 5 |
| Ready to implement (design + tasks done) | 10 |
| Requirements only (need design) | 22 |

**9 completed specifications:**

| Spec | Business Value |
|------|----------------|
| `admin-panel-client-onboarding` | Full admin panel + 7-step client wizard |
| `avatar-warming-phases` | 3-phase avatar warming model (Phase 1→2→3 with gates) |
| `shadowban-detection` | 5-state health model, auto-freeze on detection — protects avatar inventory |
| `self-learning-loop` | Edit capture → pattern extraction → few-shot injection — quality improves over time |
| `scheduled-scraping` | Priority queue scraping by staleness (queue_tick) — continuous data freshness |
| `system-topology-timeline` | 9-node topology panel + 24h heatmap + forecast — real-time pipeline health |
| `activity-feed-transparency` | Full activity feed + scrape log + per-client transparency dashboard |
| `reddit-api-health-dashboard` | Reddit API rate-limit metrics on admin health page |
| `avatar-analysis` | LLM behavioral profiling of avatars + learning loop — better persona matching |

**Deployment decision:** DigitalOcean instead of AWS for speed-to-market.
- Droplet ($12–24/month) + Managed PostgreSQL ($15/month) = production in ~1 hour
- Total infra cost: ~$27–39/month
- Docker Compose deploys as-is, no IAM/VPC complexity

**Platform readiness: ~98% MVP-ready for internal operations.**

---

## Key Milestones at a Glance

| Date | Milestone |
|------|-----------|
| Apr 29 | Analyzed Ori's PoC, identified cost savings and architectural gaps |
| May 1 | 50/50 partnership agreed, full technical plan defined |
| May 1–3 | Core MVP built in 3 days: 60 tests, 12 templates, full pipeline |
| May 7 | Comment pipeline at 100% parity with Ori — pilot-ready |
| May 8 | Joint meeting: 4 critical blockers identified before pilot launch |
| May 11 | All 4 blockers resolved. 187 tests. Self-learning loop live. Deploy-ready. |
| May 12 | 9 specs completed. DigitalOcean deployment decision. ~98% MVP readiness. |

---

## Business Summary

- **Revenue model:** ~$2K/month per client, prepaid
- **Infrastructure cost:** ~$27–39/month (10+ clients on one server)
- **AI cost:** ~$36/month per client (Gemini Flash for scoring + Claude for generation)
- **Gross margin:** ~95% on infrastructure
- **First client:** XM Cyber (cybersecurity) — data already loaded (7 avatars, 33 subreddits, 100+ keywords)
- **Competitive edge:** This is not a rebuild of Ori's system — it is a generation ahead. The AI learns from feedback and makes strategic decisions the legacy n8n workflow could not.
