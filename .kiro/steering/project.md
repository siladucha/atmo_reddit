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

## Tech Stack
- **Backend:** Python 3.11+ / FastAPI
- **Templates/UI:** Jinja2 + HTMX
- **CSS:** Tailwind CSS
- **Database:** PostgreSQL / SQLAlchemy 2.0 / Alembic
- **Auth:** JWT (python-jose + passlib)
- **Background jobs:** Celery + Redis
- **Reddit:** PRAW
- **AI/LLM:** LiteLLM (Gemini Flash for scoring, Claude Sonnet for generation)
- **Deploy:** Docker + VPS (AWS later)

## Code Style
- Python: type hints everywhere, async where beneficial
- Models: SQLAlchemy 2.0 mapped_column style
- Config: pydantic-settings with .env
- No no-code tools (n8n, Airtable, Supabase, Make, Zapier)
- All code custom — use libraries (FastAPI, Celery, HTMX, SQLAlchemy, PRAW) but no no-code platforms

## Project Structure
```
reddit_saas/
├── app/
│   ├── config.py          # Settings (pydantic-settings)
│   ├── database.py        # SQLAlchemy engine + session
│   ├── main.py            # FastAPI app
│   ├── models/            # SQLAlchemy models
│   ├── routes/            # FastAPI route handlers
│   ├── services/          # Business logic
│   │   ├── reddit.py      # Reddit API (PRAW)
│   │   ├── ai.py          # LLM calls (LiteLLM)
│   │   ├── scoring.py     # Post scoring pipeline
│   │   └── generation.py  # Comment/post generation
│   ├── tasks/             # Celery background tasks
│   ├── templates/         # Jinja2 templates
│   └── static/            # CSS/JS
├── alembic/               # DB migrations
├── pyproject.toml
├── Dockerfile
└── docker-compose.yml
```

## Key Reference Files
- `memory.md` — Project knowledge base
- `ai_cost_benchmark.md` — AI token cost analysis
- `file_index.md` — Index of all Ori's handoff files
- `Reddit Personas-Grid view.csv` — Avatar voice profiles
- `keywords-Grid view.csv` — Scoring keywords
- `XM Cyber _ Write comments copy.json` — Ori's prompts (most valuable)

## Language
- Code: English
- Comments in code: English
- Communication with user: Russian (default) or English
- Documents for Tzvi: English
