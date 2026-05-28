---
inclusion: fileMatch
fileMatchPattern: "docs/kb/**"
---

# Documentation Standards — Knowledge Base

## Structure

All user-facing and operational documentation lives in `docs/kb/`:

```
docs/kb/
├── README.md              — Hub / table of contents
├── platform-overview.md   — What RAMP is (for everyone)
├── glossary.md            — Terms & terminology rules
├── roles/                 — User manual per role
│   ├── owner-partner.md
│   ├── client-admin.md
│   ├── client-manager.md
│   ├── client-viewer.md
│   └── avatar-owner.md
├── guides/                — Operational how-to guides
│   ├── onboarding-new-client.md
│   ├── daily-operations.md
│   ├── avatar-management.md
│   ├── pipeline-explained.md
│   └── emergency-controls.md
└── admin/                 — Technical / owner-only docs
    ├── system-settings.md
    ├── deployment.md
    └── troubleshooting.md
```

## Rules When Editing KB Docs

1. **Language:** English only (docs are shared with Tzvi and clients)
2. **Terminology:** Follow `glossary.md` — never use "bot", "fake account", "automated posting"
3. **Header:** Every doc starts with audience + last updated date:
   ```
   > **Audience:** [who this is for]
   > **Last updated:** YYYY-MM-DD
   ```
4. **Update date** when making changes
5. **Keep it practical** — tables, checklists, step-by-step. Avoid walls of text.
6. **Cross-link** between docs using relative paths: `[Glossary](../glossary.md)`
7. **URLs** reference production IP (will change to domain later)
8. **No secrets** — never include API keys, passwords, or tokens in docs
9. **Role-appropriate** — each role doc should only describe what that role can see/do

## When to Update KB

- New feature implemented → update relevant guide + role docs
- New setting added → update `admin/system-settings.md`
- New role or permission change → update role doc + glossary
- Deployment process changed → update `admin/deployment.md`
- New incident type discovered → add to `admin/troubleshooting.md`
- New client onboarded → verify `guides/onboarding-new-client.md` is accurate

## Relationship to Other Docs

| Location | Purpose | Audience |
|----------|---------|----------|
| `docs/kb/` | User manuals, operational guides | Team, clients, avatar owners |
| `docs/` (root) | Architecture, ADRs, audits, reports | Developer (Max) |
| `buziness/` | Letters to Tzvi, forecasts, business docs | Tzvi, partners |
| `.kiro/steering/` | AI context for development | AI assistant |
| `.kiro/specs/` | Feature specifications | Developer (Max) |
