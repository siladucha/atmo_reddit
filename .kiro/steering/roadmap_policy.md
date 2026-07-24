# Roadmap Policy

## Rule: All Ideas → Roadmap

Every feature idea, improvement, or future concept discussed in conversation MUST be recorded in the roadmap before the conversation ends.

**Where to record:**
- `reddit_saas/data/10_roadmap.json` — internal admin roadmap (source of truth for dev priorities)
- `docs/TODO.md` — extended backlog with detailed descriptions

**What to capture:**
- Title (short, descriptive)
- Phase/priority (P0/P1/P2/P3)
- Type (feature/bugfix/infrastructure/moat/revenue/experiment)
- Description (1-3 sentences: what + why)
- SBM property relation (which system invariant does this protect/strengthen?)
- Blocks / dependencies
- Trigger condition (when should we build this?)

## Rule: Cross-Reference Risks & Bugs

Before assigning priority to a new roadmap item, check:
1. `bug_reports` table — is there a related open bug that this would fix?
2. SBM properties (system_behavior_model.md) — which property does this strengthen?
3. `data/09_risks.json` — does this mitigate a known risk?

If a roadmap item addresses a known bug or risk, note the reference (e.g., "Mitigates: SBM P1", "Closes: BUG-045").

## Rule: Marketing Roadmap Sync

The public marketing roadmap (`marketing_site/app/templates/marketing_roadmap.html`) MUST be updated when:
- A Phase's items are >80% complete → mark phase as Done, shift "In Progress" indicator
- New client-visible features ship → add to completed items
- Phase dates become inaccurate by >2 months → update timeline

**Sync frequency:** Monthly or on major milestone (whichever comes first).

**Current status (July 24, 2026):** Marketing roadmap is STALE — last updated May 2026. Phase 0-2 items are mostly done. Needs full refresh to reflect:
- Phase 0 + Phase 1 → Done (portal, posting, jitter, SSL, onboarding, performance tracking all shipped)
- Phase 1.5 → Partially done (GEO/outcome tracking shipped; topic authority/citability/entity linking not started)
- Phase 2 → Mostly done (EPG budget, A/B, rule extraction shipped; pagination/idempotency/prompt versioning not done)
- Phase 3 → Current focus should shift here (agency multi-tenant, trust engine remain)
- Self-service + Stripe billing → Done (was Phase 5, moved up)

## Anti-Pattern

❌ Discussing a feature idea and NOT recording it anywhere
❌ Recording in TODO.md but not in 10_roadmap.json (admin dashboard won't show it)
❌ Recording without SBM/risk cross-reference
❌ Marketing roadmap showing "in progress" for things shipped 2 months ago
