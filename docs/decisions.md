# Decisions & Open Questions

_Last updated: 2026-05-03_

## What's Clear ✅

### Architecture (rewrite from Ori's PoC)
- **Stack:** FastAPI + Jinja2/HTMX + PostgreSQL + Celery + Redis + PRAW + LiteLLM. No n8n, no Airtable, no Supabase dependency.
- **From Ori we keep:** prompts, scoring strategy, voice profiles, keyword data, fallback ladder (Paradigm Shift → Helpful → Karma).
- **Multi-tenant from day 1** — every query filters by `client_id`. Avatars can serve multiple clients via `client_ids` array.
- **Human-in-the-loop is permanent.** All Reddit posting is manual: AI drafts → human reviews/edits → human logs into avatar account → posts → marks as posted. This is the anti-ban policy, not a temporary stage.
- **Hobby karma pipeline** runs in parallel for avatar warming and authenticity.

### Strategy (from Ori, validated)
- Comment strategy: Paradigm Shift → Helpful → Karma Play fallback
- Avatar selection: "Who would be least annoying to the audience?"
- 7 voice profiles seeded from `Reddit Personas-Grid view.csv`
- Keywords with HIGH/MEDIUM/LOW priority drive scoring

### Cost model
- **AI cost:** ~$36/mo per client at standard volume (15 prof + 15 hobby comments + 2 posts/day) — see [`ai_cost_benchmark.md`](ai_cost_benchmark.md)
- **Infra:** ~$50–100/mo per client → ~95% margin at $2K/mo
- Use Gemini Flash (cheap) for scoring/qualification, Claude Sonnet for generation/editing

---

## What Needs Decisions 🔶

### 1. LLM Provider
Code uses LiteLLM, configured for Bedrock by default but supports any provider.

| Option | Pros | Cons |
|--------|------|------|
| **AWS Bedrock** (current default) | No API key juggling on AWS; cost transparency; prompt caching | Region-locked; need AWS account |
| **OpenRouter** | Easy switch between models; one API key | ~10% markup; no native prompt caching |
| **Direct Anthropic** | Cheapest for Claude; full prompt caching | One-provider lock-in |

**Status:** Bedrock is the default; we should confirm prompt caching is enabled before measuring costs in production.

### 2. Reddit API Access
Three options for the avatar/scraping app:
- **A. Create own Reddit App at reddit.com/prefs/apps** (free, recommended) — script-type, gives full read access
- **B. RapidAPI Reddit Unofficial** (paid, simpler)
- **C. Reddit RSS** (free, limited data)

**Status:** Code uses PRAW (option A). Credentials need to be configured in `.env` before pipeline can run for real.

### 3. Pricing model for clients
- $2K/mo prepaid was the Day-1 assumption from Tzvi
- Need to decide: setup fee structure, contract length, what's included vs add-on

**Status:** Waiting on Tzvi to lock pilot client + propose price ladder for clients 2–5.

### 4. Hosting
- Local dev: `docker-compose up`
- Production target: AWS (EC2 + RDS + ElastiCache + Bedrock)
- Question: skip VPS interim and go straight to AWS, or run on a VPS for the first 1–2 clients?

**Status:** Unresolved. AWS deployment is in TODO Priority 4 (Task 4.3).

---

## What's Missing / Unclear 🔴

### 1. No `news_scrape` data source — resolved by design choice
Original Ori workflow had a separate news scraper feeding the post-creation pipeline. We collapsed it: post generation now sources from `reddit_threads` directly (high-scoring threads as raw material).

**Implication:** Post-creation may need a richer source later (e.g., RSS feeds, knowledge lake). Tracked as Task 1.3.

### 2. Avatar credentials in DB
- Reddit usernames are stored on `avatars`, but credentials (`reddit_password`, etc.) are **not** in the schema
- Original Ori model stored them in plaintext; we deferred this until we decide on encryption strategy
- For now, humans posting manually means credentials live in their password manager, not the DB

**Status:** Deliberate. Will need to revisit if/when we automate posting.

### 3. Tzvi-side deliverables
| Item | Status |
|------|--------|
| First client brief | ⏳ |
| Functional requirements (UI/UX) | ⏳ |
| Reddit API credentials / avatar accounts | ⏳ |
| Pilot pricing finalized | ⏳ |
| Cyprus legal entity setup | ⏳ |

### 4. No automated posting (intentional)
- All Reddit posting is manual to protect avatars from bans
- Significant daily human effort (Tzvi as gatekeeper)
- Long-term: semi-automated posting with avatar-specific risk scoring is in Phase 3 roadmap, not committed

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Reddit avatar bans | HIGH | Hobby karma pipeline, manual posting, brand-ratio caps in `services/safety.py`, 12h health checks |
| LLM costs spike | MEDIUM | Gemini Flash for cheap ops, AI usage logged per call (`ai_usage_log` table), per-client cost dashboard |
| Reddit API rate limits | LOW | PRAW handles backoff; we scrape full subreddits, not keyword-based |
| Prompt quality below Ori's | MEDIUM | Use Ori's prompts as baseline; tune on real client data after pilot |
| Pilot client delay | MEDIUM | Building client-independent core; second-client onboarding is no-code (UI-driven) |
| Reddit terms-of-service interpretation | MEDIUM | Human review + manual posting reduces "bot" exposure; invite-only model limits volume |

---

## Resolved Since Day 1

| Decision | Resolution |
|----------|------------|
| Build vs. fork Ori's n8n | **Build from scratch.** No n8n/Airtable/Supabase. |
| Auth approach | JWT cookie + middleware on every protected route |
| UI framework | Jinja2 + HTMX (no SPA). Done. |
| Scheduling | Celery Beat with 4 jobs (8:00, 14:00, 10:00, every 12h). Done. |
| Error handling | Global middleware → friendly HTML pages. Done. |
| Testing | pytest, 60 tests across 9 modules. Ongoing. |
| Logging | Daily file rotation, 7-day retention. Done. |
