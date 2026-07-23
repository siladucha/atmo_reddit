# Marketing Site — Technical Context

## What It Is

Separate FastAPI application serving the public marketing website. Lives in `marketing_site/` directory (NOT inside `reddit_saas/`).

**Live URL:** https://gorampit.com (nginx catch-all proxies to marketing_app; specific paths like `/admin`, `/api/*` go to main_app)

## Tech Stack

- **Framework:** FastAPI
- **Templates:** Jinja2 (`marketing_site/app/templates/`)
- **CSS:** Tailwind CDN (no local build)
- **JS:** Vanilla only (no frameworks, no libraries)
- **Base template:** `marketing_base.html` — all pages extend this
- **Router:** `marketing_site/app/routes/pages.py`

## Project Structure

```
marketing_site/
├── app/
│   ├── main.py              # FastAPI app
│   ├── routes/
│   │   └── pages.py         # All page routes
│   ├── data/
│   │   └── faq_data.py      # FAQ content (structured data)
│   └── templates/
│       ├── marketing_base.html
│       ├── marketing_home.html
│       ├── marketing_mobile.html
│       ├── marketing_proxy.html
│       ├── marketing_pricing.html
│       ├── marketing_roadmap.html
│       ├── marketing_faq.html
│       ├── marketing_thank_you.html
│       └── partials/
│           └── faq_section.html
├── tests/
└── requirements.txt
```

## Conventions

### Naming
- Templates: `marketing_{page_name}.html`
- Routes: async handlers in `pages.py`, `response_class=HTMLResponse`
- Partials: `partials/{component_name}.html` (shared via `{% include %}`)

### Route Pattern
```python
@router.get("/page-name", response_class=HTMLResponse)
async def page_name(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="marketing_page_name.html",
        context={...},
    )
```

### UI Pattern
- Dark theme (consistent with main app admin)
- Accordion/toggle: `aria-expanded` + CSS `max-height` transition + vanilla JS handler
- Responsive: `max-w-{size} mx-auto px-4 sm:px-6 lg:px-8`
- Sections: full-width with constrained inner content

### Data Approach
- Static content as Python modules (`app/data/`) — not DB, not JSON files
- Passed to templates via Jinja2 context
- Git-versioned, type-checkable

## Deployment

```bash
# Push code:
rsync -avz --exclude='.venv/' --exclude='__pycache__/' --exclude='.git/' \
  --exclude='*.pyc' --exclude='.DS_Store' --delete \
  marketing_site/ ramp:/marketing_site/

# Rebuild and restart:
ssh ramp "cd /app && docker compose build --no-cache marketing && docker compose up -d marketing"
```

**Server path:** `/marketing_site/` (NOT `/app/marketing_site/`)
**Docker service:** `marketing` in `reddit_saas/docker-compose.yml`, build context `../marketing_site`

## Content Rules

All text on marketing site MUST comply with `client_facing_language.md` steering:
- No prohibited terms
- "community" not "subreddit"
- "voice" not "avatar"
- Approved descriptor phrases in explanatory text
- No operational mechanics

## Testing

```bash
# Run marketing site tests:
cd marketing_site && pytest tests/ -x -q
```

Uses pytest + httpx AsyncClient. Test files: `tests/test_*.py`.
