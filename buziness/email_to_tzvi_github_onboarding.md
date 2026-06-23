# Email to Tzvi — GitHub Access Confirmed

**Subject:** You're in — here's how to use it

---

Hey Tzvi,

Done. I've added you to the repo. You should have gotten an invite email from GitHub — accept it and you're in.

**Repo link:** https://github.com/siladucha/atmo_reddit

## How to use

Just open the link, click through folders, read. Everything renders as nice formatted pages. No code skills needed.

## Where to find what

| What you want | Where to look |
|---------------|---------------|
| **"What's the platform and how does it work?"** | [docs/kb/platform-overview.md](https://github.com/siladucha/atmo_reddit/blob/feature/june-updates/docs/kb/platform-overview.md) |
| **Full roadmap + current status** | [docs/TODO.md](https://github.com/siladucha/atmo_reddit/blob/feature/june-updates/docs/TODO.md) |
| **All terms explained (glossary)** | [docs/kb/glossary.md](https://github.com/siladucha/atmo_reddit/blob/feature/june-updates/docs/kb/glossary.md) |
| **Feature specs (what's planned, designed, built)** | [.kiro/specs/](https://github.com/siladucha/atmo_reddit/tree/feature/june-updates/.kiro/specs) |
| **Business docs & client reports** | [buziness/](https://github.com/siladucha/atmo_reddit/tree/feature/june-updates/buziness) |
| **Navigation guide (full index)** | [docs/NAVIGATION.md](https://github.com/siladucha/atmo_reddit/blob/feature/june-updates/docs/NAVIGATION.md) |

## Top 5 pages to start with

1. **Platform Overview** — what RAMP is, key concepts, how things connect
   → `docs/kb/platform-overview.md`

2. **Roadmap** — milestones, what's done, what's next, priorities
   → `docs/TODO.md`

3. **Spec Audit & Roadmap** — recent big-picture status report
   → `docs/SPEC_AUDIT_AND_ROADMAP_June2026.md`

4. **XM Cyber Investigation** — example of how we track and resolve incidents
   → `buziness/xm_cyber_generation_halt_report_june22.md`

5. **Daily Operations Guide** — how the system runs day to day
   → `docs/kb/guides/daily-operations.md`

## Key specs (each has requirements + design + tasks)

| Feature | Folder | Status |
|---------|--------|--------|
| AI-Native Expert Warming | `.kiro/specs/ai-native-expert-warming/` | Designed, ready to build |
| Automated Posting | `.kiro/specs/automated-proxy-posting/` | Done |
| EPG 2.0 (Portfolio Manager) | `.kiro/specs/epg-attention-portfolio/` | Done |
| Production Audit | `.kiro/specs/production-readiness-audit/` | In progress |
| Staging + CI/CD | `.kiro/specs/staging-cicd-infrastructure/` | In progress |
| RBAC & Client Isolation | `.kiro/specs/rbac-client-isolation/` | Done |
| Discovery Engine | `.kiro/specs/discovery-engine/` | Done |

## Tips

- **Branch**: make sure you're on `feature/june-updates` (should be default). If you see old content, switch branch at the top.
- **Search**: use the search bar (top of page) to find anything — "XM Cyber", "avatar", "posting", whatever.
- **History**: click "History" on any file to see when it was last changed.
- **Mobile**: works fine on phone too — GitHub renders Markdown cleanly.

## What you won't see

The actual source code (Python, templates, etc.) is also there but you can ignore it completely. Everything relevant for you is in:
- `docs/` — documentation
- `buziness/` — business reports
- `.kiro/specs/` — feature specifications

---

Let me know if you have questions or can't find something.

Max
