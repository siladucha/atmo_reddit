# RAMP — Knowledge Base

> Internal documentation hub. Structured by audience and purpose.

---

## Quick Navigation

### For Everyone
- [Platform Overview](./platform-overview.md) — What RAMP is, how it works, key concepts
- [Glossary](./glossary.md) — Terms, abbreviations, definitions

### User Manuals (by Role)
- [Owner / Partner](./roles/owner-partner.md) — Full system access, settings, pipeline control
- [Client Admin](./roles/client-admin.md) — Company management, team, avatars, strategy
- [Client Manager](./roles/client-manager.md) — Daily review, approve/reject, subreddit management
- [Client Viewer](./roles/client-viewer.md) — Read-only dashboard, reports
- [Avatar Owner (Posting Workforce)](./roles/avatar-owner.md) — Mobile app, posting queue, daily workflow

### Operational Guides
- [Onboarding a New Client](./guides/onboarding-new-client.md) — Step-by-step client setup
- [Daily Operations](./guides/daily-operations.md) — Review, approve, monitor, post
- [Avatar Management](./guides/avatar-management.md) — Create, warm, freeze, health, phases
- [Pipeline Explained](./guides/pipeline-explained.md) — Scrape → Score → Generate → Review → Post
| [Content Review & Learning](guides/content-review-and-learning.md) | How to review drafts, Edit & Approve workflow, self-learning loop |
- [Emergency Controls](./guides/emergency-controls.md) — Kill switches, freeze, ban response

### Admin / Technical
- [System Settings Reference](./admin/system-settings.md) — All settings and what they do
- [Deployment](./admin/deployment.md) — Docker, server, deploy commands
- [Troubleshooting](./admin/troubleshooting.md) — Common problems and solutions

---

## Document Conventions

- **Audience** is marked at the top of each doc
- **Last updated** date on every page
- Screenshots use placeholder descriptions (actual screenshots TBD)
- URLs reference production: `http://161.35.27.165` (will change to domain later)

---

## Contributing

When updating these docs:
1. Keep language simple and direct
2. Use English for all documentation (code, UI, docs)
3. Never use terms: "bot", "fake account", "automated posting" — see [Glossary](./glossary.md) for correct terminology
4. Update "Last updated" date when editing
5. Every doc must have audience + date header
6. Cross-link between docs using relative paths

## Steering Integration

This KB is referenced in `.kiro/steering/project.md` (Key Reference Files section).  
Documentation standards are enforced via `.kiro/steering/documentation.md` (auto-loaded when editing `docs/kb/**` files).
