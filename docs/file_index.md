# File Index — Reddit Marketing SaaS

_Last updated: 2026-05-03_

This is a map of the repo. The actual application lives under [reddit_saas/](../reddit_saas/); everything else is documentation, legacy data, and Ori's original PoC artifacts.

---

## Application — `reddit_saas/`

### Top level
| File | Purpose |
|------|---------|
| `pyproject.toml` | Python deps + project config |
| `Dockerfile` | App image (FastAPI + workers) |
| `docker-compose.yml` | Local stack: web + worker + db + redis |
| `alembic.ini` + `alembic/` | DB migrations (initial migration not yet generated — see TODO 2.1) |
| `.env.example` | Required environment vars template |
| `README.md` | Quick start instructions |
| `logs/` | Daily-rotated app logs (7-day retention) |
| `tests/` | 60 unit tests across 9 modules |

### `reddit_saas/app/`

#### Bootstrap
- [`main.py`](../reddit_saas/app/main.py) — FastAPI app init, mounts middleware, includes routers, mounts static
- [`config.py`](../reddit_saas/app/config.py) — `pydantic-settings` config from `.env`
- [`database.py`](../reddit_saas/app/database.py) — SQLAlchemy engine + `SessionLocal` + `Base`
- [`logging_config.py`](../reddit_saas/app/logging_config.py) — daily-rotated file handler, 7-day retention
- [`seed.py`](../reddit_saas/app/seed.py) — `Base.metadata.create_all()` + test data seed

#### `routes/` — HTTP endpoints
| File | Purpose |
|------|---------|
| `auth.py` | `/auth/login`, `/auth/register`, `/auth/logout` |
| `clients.py` | Client CRUD |
| `avatars.py` | Avatar CRUD + health endpoints |
| `dashboard.py` | Admin stats + AI cost breakdown |
| `review.py` | Comment/post approval queue |
| `pipeline.py` | Manual pipeline triggers (scrape/score/generate) |
| `pages.py` | Jinja2 HTML page renders |

#### `models/` — SQLAlchemy ORM
See [database_schema.md](database_schema.md) for full field lists. Files:
`user.py`, `client.py`, `persona.py`, `subreddit.py`, `avatar.py`,
`thread.py`, `comment_draft.py`, `post_draft.py`, `hobby.py`,
`ai_usage.py`, `audit.py`.

#### `services/` — Business logic
| File | Purpose |
|------|---------|
| `auth.py` | Password hashing + JWT issue/verify |
| `reddit.py` | PRAW wrapper, scraping, comment-tree flattening |
| `ai.py` | LLM calls (Bedrock/LiteLLM) with cost logging |
| `scoring.py` | Thread relevance/quality/strategic scoring |
| `generation.py` | Comment + post draft generation |
| `safety.py` | Brand-ratio checks, avatar quarantine, health |

#### `tasks/` — Celery
| File | Purpose |
|------|---------|
| `worker.py` | Celery app + Beat schedule (4 jobs: 8am, 14:00, 10:00, every 12h) |
| `orchestrator.py` | `run_full_pipeline_all_clients`, `run_hobby_pipeline_all_avatars`, `check_all_avatars_health` |
| `scraping.py` | Per-client and per-avatar scrape tasks |
| `ai_pipeline.py` | Score → generate task chain |

#### `middleware/`
| File | Purpose |
|------|---------|
| `auth.py` | JWT cookie check; redirect to `/login` if not authenticated. Bypasses: `/login`, `/register`, `/logout`, `/health`, `/docs`, `/auth/*`, `/static/*` |
| `errors.py` | Global exception handler with friendly HTML error pages |

#### `templates/` — Jinja2 + HTMX + Tailwind
12 templates: `base.html`, `login.html`, `register.html`, `dashboard.html`,
`client_detail.html`, `client_new.html`, `avatars.html`, `avatar_new.html`,
`review.html`, `threads.html`, `admin.html`, `guide.html`.

---

## Documentation — `docs/`

### Living documents (kept in sync with code)
| File | Purpose |
|------|---------|
| [`TODO.md`](TODO.md) | Open tasks by priority, with file pointers |
| [`architecture.md`](architecture.md) | System design, data flows, scheduling |
| [`database_schema.md`](database_schema.md) | All tables — single source-of-truth view |
| [`file_index.md`](file_index.md) | This file |
| [`memory.md`](memory.md) | High-level project knowledge base |
| [`decisions.md`](decisions.md) | Decisions made + open questions |
| [`session.md`](session.md) | Work session log |

### Status / cost analyses (point-in-time snapshots)
| File | Purpose |
|------|---------|
| [`status_report_may1.md`](status_report_may1.md) | Day-1 status (RU) |
| [`status_report_may1_en.md`](status_report_may1_en.md) | Day-1 status (EN) |
| [`ai_cost_benchmark.md`](ai_cost_benchmark.md) | Per-client LLM cost projection |
| [`aws_cost_estimate.md`](aws_cost_estimate.md) | Infra cost projection |

### Historical / context
| File | Purpose |
|------|---------|
| [`call_notes_tzvi.md`](call_notes_tzvi.md) | Prep notes for May 1 call with Tzvi |
| [`letter_to_tzvi.md`](letter_to_tzvi.md) | Initial analysis sent to Tzvi |
| [`Reddit Project Handoff - April 15.txt`](Reddit%20Project%20Handoff%20-%20April%2015.txt) | Notes from Ori's 24-min handoff call |

### Legacy reference (Ori's PoC, pre-rewrite)
These describe the original n8n + Airtable + Supabase setup. We are replacing all of it with the FastAPI codebase. Keep for context only.

| File | Purpose |
|------|---------|
| [`airtable_interfaces.md`](airtable_interfaces.md) | UI requirements as Airtable interfaces — implemented now in `app/templates/` |
| [`airtable_automation.md`](airtable_automation.md) | Single Airtable webhook — replaced by direct API endpoints |
| [`untitled text.txt`](untitled%20text.txt) | Unrelated TestFlight note (different project), kept as-is |

---

## Root — Ori's PoC Artifacts

These files at repo root are kept as reference. They are **not** imported, executed, or deployed; they are sources to extract prompts, voice profiles, and keyword data from.

### n8n workflow JSON exports
`Run subreddits - Cyber copy.json`, `Scrape subreddit copy.json`,
`Reddit _ Comments _ Official copy.json`,
`XM Cyber _ Write comments copy.json`, `Hobby Comment Writing copy.json`,
`Run hobby subreddits [1] copy.json`, `Scrape hoby subreddit [2] copy.json`,
`XM Cyber — Reddit Post Creation (draft) copy.json`,
`XM Cyber — Reddit Post Creation (draft).json`,
`Update comment sent copy.json`.

The valuable parts inside these are the **prompts** and **scoring logic** — already ported into `app/services/ai.py`, `services/scoring.py`, `services/generation.py`.

### Airtable CSV exports (reference data)
| File | Use |
|------|-----|
| `Reddit Personas-Grid view.csv` | 7 fully-defined avatars — seed data for `avatars` table |
| `keywords-Grid view.csv` | ~120 keywords with HIGH/MEDIUM/LOW priority — seed for `clients.keywords` JSONB |
| `Reddit Comments-Grid view.csv` | Sample AI comments — useful as few-shot examples |
| `Reddit Comments Tracking-Grid view.csv` | 8000+ historical posted comments |
| `XM Cyber Reddit Posts-Grid view.csv` | Sample AI posts with full briefs |
| `Scrape-Grid view.csv` | 24000+ raw scraped posts (large) |
| `Reddit Posts-Grid view.csv`, `Reddit Posts tracking-Grid view.csv`, `Influencers list-Grid view.csv` | Empty (just headers) |

### Project root
- [`CLAUDE.md`](../CLAUDE.md) — Claude Code project instructions (legacy n8n migration guide; superseded by this codebase but kept for the migration-step docs)
- `.gitignore`, `.venv/`, `.kiro/`, `.vscode/` — standard tooling

---

## What to read first (recommended order)

1. [`reddit_saas/README.md`](../reddit_saas/README.md) — get the app running
2. [`architecture.md`](architecture.md) — understand the system
3. [`database_schema.md`](database_schema.md) — understand the data
4. [`TODO.md`](TODO.md) — what to work on
5. [`memory.md`](memory.md) — high-level project context
