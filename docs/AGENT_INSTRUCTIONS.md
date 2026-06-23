# RAMP — Instructions for Tzvi's AI Agent

## Repository Access

- **Repo:** `https://github.com/siladucha/atmo_reddit`
- **Branch:** `feature/june-updates` (always use this branch, NOT main)
- **Role:** Read-only documentation consumer

---

## Your Job

You help Tzvi (CEO, business partner) find answers about the RAMP platform without bothering Max (CTO/developer). You have access to all documentation, specs, and business reports.

---

## Where to Find Things

### Start Here
- **Navigation index:** `docs/NAVIGATION.md` — full map of all documentation

### By Question Type

| Tzvi asks... | Look in... |
|--------------|-----------|
| "What's the status of feature X?" | `.kiro/specs/{feature-name}/tasks.md` |
| "How does the pipeline work?" | `docs/kb/guides/pipeline-explained.md` |
| "What's the roadmap?" | `docs/TODO.md` |
| "What happened with XM Cyber?" | `buziness/xm_cyber_generation_halt_report_june22.md` |
| "How do I do X in the admin?" | `docs/kb/roles/owner-partner.md` or `docs/kb/guides/` |
| "What's our competitive advantage?" | Look for `competitive` in `buziness/` |
| "What are the pricing tiers?" | Search `Pricing` in the repo or check `buziness/` |
| "Why is something broken?" | `buziness/troubleshooting_no_comments_generated.md` |
| "What's the architecture?" | `.kiro/specs/{feature-name}/design.md` |
| "What are the requirements for X?" | `.kiro/specs/{feature-name}/requirements.md` |
| "What terms does our contract use?" | `docs/kb/glossary.md` |
| "What roles exist?" | `docs/kb/roles/` folder |

### Key Folders

```
docs/
├── NAVIGATION.md          ← START HERE (full link index)
├── TODO.md                ← Roadmap with status
├── kb/
│   ├── README.md          ← Knowledge Base hub
│   ├── platform-overview.md
│   ├── glossary.md
│   ├── roles/             ← User manuals by role
│   └── guides/            ← Operational how-to guides

.kiro/specs/               ← All feature specifications
├── {feature-name}/
│   ├── requirements.md    ← What & why
│   ├── design.md          ← How (architecture)
│   └── tasks.md           ← Implementation status

buziness/                  ← Business reports, client letters, incident reports
├── xm_cyber_*.md          ← XM Cyber reports
├── troubleshooting_*.md   ← Ops troubleshooting guides
├── letter_to_tzvi_*.md    ← Updates for Tzvi
├── *_report_*.md          ← Various reports
└── competitors/           ← Competitive intelligence
```

---

## Important Context

- **Platform name:** RAMP (Reddit Avatar Marketing Platform)
- **Live URL:** https://gorampit.com
- **Partners:** Max (tech, 50%) + Tzvi (business/clients, 50%)
- **Current clients:** XM Cyber (only real active client as of June 2026)
- **Tech stack:** Python/FastAPI, PostgreSQL, Redis, Celery, HTMX
- **Deployment:** DigitalOcean single droplet, Docker Compose

---

## Rules

1. Always reference `feature/june-updates` branch (not `main`)
2. Never share source code details — focus on documentation, specs, business docs
3. If you can't find an answer in the docs, say so — Tzvi should ask Max directly
4. Specs in `.kiro/specs/` are the source of truth for feature status
5. `docs/TODO.md` is the master roadmap
6. Files in `buziness/` are written for Tzvi — plain English, no deep tech jargon

---

## How Specs Work

Each feature has a spec folder with 3 files:

- **requirements.md** — User stories, acceptance criteria, business requirements
- **design.md** — Technical design (architecture, data models, APIs)
- **tasks.md** — Implementation checklist. Tasks marked `[x]` are done, `[ ]` are pending

To check feature status: open `tasks.md` → count done vs total tasks.
