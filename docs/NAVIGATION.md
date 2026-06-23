# RAMP Documentation — Navigation Guide

**Branch:** `feature/june-updates`  
**Base URL:** `https://github.com/siladucha/atmo_reddit/tree/feature/june-updates`

---

## Quick Links

| What | Where |
|------|-------|
| **This guide** | You're here |
| **Knowledge Base** | [docs/kb/](docs/kb/README.md) |
| **Full Roadmap** | [docs/TODO.md](docs/TODO.md) |
| **Feature Specs** | [.kiro/specs/](.kiro/specs/) |
| **Business Docs** | [buziness/](buziness/) |
| **Incident Reports** | [buziness/](buziness/) (files with dates) |
| **Troubleshooting** | [buziness/troubleshooting_no_comments_generated.md](buziness/troubleshooting_no_comments_generated.md) |

---

## Knowledge Base (docs/kb/)

Start here: [docs/kb/README.md](docs/kb/README.md)

| Section | Content |
|---------|---------|
| [platform-overview.md](docs/kb/platform-overview.md) | What RAMP is, how it works, key concepts |
| [glossary.md](docs/kb/glossary.md) | All terms and abbreviations |
| **Roles** | |
| [roles/owner-partner.md](docs/kb/roles/owner-partner.md) | Owner & Partner user manual |
| [roles/client-admin.md](docs/kb/roles/client-admin.md) | Client Admin manual |
| [roles/client-manager.md](docs/kb/roles/client-manager.md) | Client Manager manual |
| [roles/client-viewer.md](docs/kb/roles/client-viewer.md) | Client Viewer manual |
| [roles/avatar-owner.md](docs/kb/roles/avatar-owner.md) | Avatar Owner (posting workforce) manual |
| **Operational Guides** | |
| [guides/onboarding-new-client.md](docs/kb/guides/onboarding-new-client.md) | How to onboard a new client |
| [guides/daily-operations.md](docs/kb/guides/daily-operations.md) | Daily ops checklist |
| [guides/avatar-management.md](docs/kb/guides/avatar-management.md) | Avatar lifecycle management |
| [guides/pipeline-explained.md](docs/kb/guides/pipeline-explained.md) | How the AI pipeline works |
| [guides/content-review-and-learning.md](docs/kb/guides/content-review-and-learning.md) | Review workflow + self-learning |
| [guides/emergency-controls.md](docs/kb/guides/emergency-controls.md) | Kill switches and emergency procedures |
| [guides/discovery-engine.md](docs/kb/guides/discovery-engine.md) | Discovery Engine usage |
| [guides/trial-management.md](docs/kb/guides/trial-management.md) | Trial client management |
| **Admin / Technical** | |
| [admin/system-settings.md](docs/kb/admin/system-settings.md) | All system settings reference |
| [admin/deployment.md](docs/kb/admin/deployment.md) | Deployment procedures |
| [admin/troubleshooting.md](docs/kb/admin/troubleshooting.md) | Technical troubleshooting |

---

## Feature Specs (.kiro/specs/)

Each spec folder contains up to 3 files:
- `requirements.md` — What we're building and why
- `design.md` — Technical architecture and approach
- `tasks.md` — Implementation task list with status

### Key Active Specs

| Spec | Status | Description |
|------|--------|-------------|
| [ai-native-expert-warming/](.kiro/specs/ai-native-expert-warming/) | Ready | AI-Native Expert warming system |
| [production-readiness-audit/](.kiro/specs/production-readiness-audit/) | In progress | Production audit and hardening |
| [staging-cicd-infrastructure/](.kiro/specs/staging-cicd-infrastructure/) | In progress | Staging environment + CI/CD |
| [subreddit-emotional-profile/](.kiro/specs/subreddit-emotional-profile/) | Done | Subreddit tone analysis |
| [epg-attention-portfolio/](.kiro/specs/epg-attention-portfolio/) | Done | EPG 2.0 portfolio manager |
| [discovery-engine/](.kiro/specs/discovery-engine/) | Done | Market research automation |
| [rbac-client-isolation/](.kiro/specs/rbac-client-isolation/) | Done | RBAC + data isolation |
| [automated-proxy-posting/](.kiro/specs/automated-proxy-posting/) | Done | Automated posting core |

---

## Business Documents (buziness/)

| File | Content |
|------|---------|
| [xm_cyber_generation_halt_report_june22.md](buziness/xm_cyber_generation_halt_report_june22.md) | XM Cyber incident — why generation stopped |
| [troubleshooting_no_comments_generated.md](buziness/troubleshooting_no_comments_generated.md) | Ops guide: diagnose "no comments" |
| [demo_readiness_update_for_tzvi.md](buziness/demo_readiness_update_for_tzvi.md) | Demo readiness status |
| [client_manager_user_manual.md](buziness/client_manager_user_manual.md) | Client manager role manual |
| [discovery_module_spec.md](buziness/discovery_module_spec.md) | Discovery module overview |
| [letter_to_tzvi_automated_posting.md](buziness/letter_to_tzvi_automated_posting.md) | Automated posting update |

---

## How to Use This Repo

1. **Browse online** — click through folders on GitHub, everything renders as formatted pages
2. **Search** — use GitHub's search (top-left) to find any term across all docs
3. **History** — click "History" on any file to see when it was last updated and what changed
4. **Branch** — always use `feature/june-updates` (this is the active development branch)
