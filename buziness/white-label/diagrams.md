# RAMP White Label — Visual Diagrams

> Presentation-ready diagrams for pitch deck and supporting materials.
> Best viewed in monospace font (Courier, Menlo, SF Mono, JetBrains Mono).

---

## 1. Three-Layer Moat — Competitive Defensibility

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   LAYER 3: DATA FLYWHEEL                                                        │
│   ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄                                                      │
│   Every human edit teaches the system what works.                                │
│   Correction patterns extracted → injected into future prompts.                 │
│   New entrants start with ZERO training data. We have months of intelligence.   │
│   ⟹ Network effect: more edits = better content = more clients = more edits    │
│                                                                                 │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │                                                                         │   │
│   │   LAYER 2: AI-NATIVE EXPERT                                             │   │
│   │   ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄                                           │   │
│   │   Avatars progress from members → recognized domain experts.            │   │
│   │   Expert-tier content gets cited by ChatGPT, Perplexity, Gemini.        │   │
│   │   Authority compounds — each interaction builds on the last.            │   │
│   │   ⟹ Compounding advantage: impossible to shortcut, only grows          │   │
│   │                                                                         │   │
│   │   ┌─────────────────────────────────────────────────────────────────┐   │   │
│   │   │                                                                 │   │   │
│   │   │   LAYER 1: AVATAR INVENTORY                                     │   │   │
│   │   │   ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄                                  │   │   │
│   │   │   Pre-warmed accounts: real karma, real history, real trust.     │   │   │
│   │   │   Gold avatar = 2,000+ karma, 6+ months, community standing.    │   │   │
│   │   │   ⟹ 6-MONTH REPLICATION BARRIER — cannot be manufactured.      │   │   │
│   │   │                                                                 │   │   │
│   │   │          ┌───────────────────────────────────┐                  │   │   │
│   │   │          │  ★ TIME-LOCKED CORE ASSET ★       │                  │   │   │
│   │   │          │  Every month of operation          │                  │   │   │
│   │   │          │  increases inventory value.        │                  │   │   │
│   │   │          │  Competitors need 6+ months        │                  │   │   │
│   │   │          │  just to reach parity.             │                  │   │   │
│   │   │          └───────────────────────────────────┘                  │   │   │
│   │   │                                                                 │   │   │
│   │   └─────────────────────────────────────────────────────────────────┘   │   │
│   │                                                                         │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

    WHY IT MATTERS:
    ───────────────
    Even if a competitor copies our code tomorrow, they still need:
    • 6 months to build equivalent avatar inventory (Layer 1)
    • 12+ months to develop expert-level authority (Layer 2)
    • Our entire edit history to match content quality (Layer 3)

    Each layer protects the one inside it. Together = unbreakable.
```

---

## 2. Architecture Overview — Multi-Tenant White Label

```
    agency-alpha.com        agency-beta.io        agency-gamma.co
         │                       │                       │
         │    HTTPS (custom domains, auto-SSL)           │
         ▼                       ▼                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│                         NGINX REVERSE PROXY                                  │
│                                                                             │
│   ┌───────────────────┐  ┌───────────────────┐  ┌───────────────────┐      │
│   │ agency-alpha.com  │  │ agency-beta.io    │  │ agency-gamma.co   │      │
│   │ → Partner #1      │  │ → Partner #2      │  │ → Partner #3      │      │
│   └───────────────────┘  └───────────────────┘  └───────────────────┘      │
│                                                                             │
│   Routes by domain → same backend, different branding context               │
│                                                                             │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│                    FASTAPI APPLICATION (single instance)                     │
│                                                                             │
│   ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────────────┐  │
│   │                 │   │                 │   │                         │  │
│   │   BRANDING      │   │   RBAC +        │   │   PARTNER PORTAL        │  │
│   │   MIDDLEWARE     │   │   QUERY SCOPE   │   │   (Jinja2 + HTMX)      │  │
│   │                 │   │                 │   │                         │  │
│   │  domain →       │   │  partner_id →   │   │  Renders UI with        │  │
│   │  BrandingConfig │   │  data isolation │   │  partner's logo,        │  │
│   │  (logo, colors, │   │  (6 roles,      │   │  colors, domain.        │  │
│   │   name, domain) │   │   scoped queries)│   │  Zero RAMP traces.     │  │
│   │                 │   │                 │   │                         │  │
│   └─────────────────┘   └─────────────────┘   └─────────────────────────┘  │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                                                                     │   │
│   │              CORE SERVICES (shared across ALL partners)              │   │
│   │                                                                     │   │
│   │   Scraping │ Scoring │ Generation │ Review │ Posting │ Learning     │   │
│   │   Health   │ Safety  │ Strategy   │ Phase  │ Karma   │ Analytics    │   │
│   │                                                                     │   │
│   │   ★ Same AI pipeline, same quality, same improvements for all ★     │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│                    POSTGRESQL (single instance)                              │
│                                                                             │
│   ┌──────────────┐  ┌──────────────────┐  ┌──────────────────────────┐     │
│   │  partners    │  │  branding_configs │  │  clients                 │     │
│   │              │  │                  │  │                          │     │
│   │  id          │  │  partner_id (FK) │  │  id                     │     │
│   │  name        │  │  logo_url        │  │  partner_id (FK)        │     │
│   │  tier        │  │  primary_color   │  │  name                   │     │
│   │  max_slots   │  │  custom_domain   │  │  avatars, keywords...   │     │
│   │  contract    │  │  app_name        │  │                          │     │
│   └──────────────┘  └──────────────────┘  └──────────────────────────┘     │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  ALL existing tables (threads, drafts, avatars, scores, events...)  │   │
│   │  gain partner_id FK → every query scoped automatically              │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   COST PER NEW PARTNER: $0 infrastructure │ 1 row in partners table         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

    KEY INSIGHT:
    ────────────
    Adding a new white-label partner = adding a database row.
    No new servers. No new containers. No new deployments.
    Marginal cost per partner: $0.
```

---

## 3. Partner Flow — End-to-End Journey

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 PHASE A: PARTNER ONBOARDING (5 days)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Day 1          Day 2              Day 3              Day 4          Day 5
┌─────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────┐   ┌──────────┐
│ Agency  │   │ Domain       │   │ First client │   │ Mobile   │   │ Portal   │
│ signs   │──→│ configured   │──→│ workspace    │──→│ app build│──→│ LIVE     │
│ contract│   │ + SSL        │   │ created      │   │ initiated│   │          │
│         │   │ + branding   │   │ + data seeded│   │ (if req) │   │ ✓ Ready  │
└─────────┘   └──────────────┘   └──────────────┘   └──────────┘   └──────────┘
     │                                                                    │
     │         Assets collected: logo, colors, domain, app icon           │
     └────────────────────────────────────────────────────────────────────┘
                        Total elapsed: 5 business days


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 PHASE B: CLIENT ONBOARDING (per end-client)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Agency adds client          Platform provisions           Pipeline runs
┌──────────────────┐       ┌──────────────────────┐      ┌──────────────────┐
│                  │       │                      │      │                  │
│  Agency creates  │──────→│  Isolated workspace  │─────→│  AI pipeline     │
│  new client in   │       │  provisioned:        │      │  activates:      │
│  partner portal  │       │                      │      │                  │
│                  │       │  • Subreddits        │      │  • Scraping      │
│  Enters:         │       │  • Keywords          │      │  • Scoring       │
│  - Brand name    │       │  • Avatars assigned  │      │  • Generation    │
│  - Keywords      │       │  • Pipeline config   │      │  • Review queue  │
│  - Target subs   │       │  • Data isolation ✓  │      │  • Self-learning │
│                  │       │                      │      │                  │
└──────────────────┘       └──────────────────────┘      └──────────────────┘
                                                                   │
                                                                   ▼
                                                         ┌──────────────────┐
                                                         │  Results flow    │
                                                         │  to agency's     │
                                                         │  branded portal  │
                                                         └──────────────────┘


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 PHASE C: END-CLIENT EXPERIENCE (what the client sees)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   END-CLIENT PERSPECTIVE                                                    │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                                                                     │   │
│   │   "I use [Agency Name]'s Reddit marketing platform."                │   │
│   │                                                                     │   │
│   │   ✓ I log into agency-alpha.com                                     │   │
│   │   ✓ I see Agency Alpha's logo and colors                            │   │
│   │   ✓ I get reports with Agency Alpha's branding                      │   │
│   │   ✓ My avatar owners use Agency Alpha's mobile app                  │   │
│   │   ✓ Emails come from hello@agency-alpha.com                         │   │
│   │                                                                     │   │
│   │   ✗ I have never heard of "RAMP"                                    │   │
│   │   ✗ I see no trace of the underlying platform                       │   │
│   │   ✗ I don't know other agencies use the same technology             │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

                    ┌─────────────────────────────────┐
                    │                                 │
                    │   WHAT ACTUALLY HAPPENS:        │
                    │                                 │
                    │   End-Client                    │
                    │       │                         │
                    │       ▼                         │
                    │   Agency Brand (visible)        │
                    │       │                         │
                    │       ▼                         │
                    │   ┌─────────────────────┐      │
                    │   │  RAMP (invisible)   │      │
                    │   │                     │      │
                    │   │  AI Pipeline        │      │
                    │   │  Avatar Inventory   │      │
                    │   │  Self-Learning      │      │
                    │   │  Safety Guards      │      │
                    │   │  Infrastructure     │      │
                    │   └─────────────────────┘      │
                    │       │                         │
                    │       ▼                         │
                    │   Reddit (results)              │
                    │                                 │
                    └─────────────────────────────────┘


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 SUMMARY: THE INVISIBLE ENGINE MODEL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    ┌──────────────┐         ┌──────────────┐         ┌──────────────┐
    │              │  pays   │              │  pays   │              │
    │  End-Client  │────────→│   Agency     │────────→│    RAMP      │
    │              │ $2,500  │  (Partner)   │ $250    │  (Invisible) │
    │              │  /mo    │              │ /client │              │
    │              │         │              │  /mo    │              │
    │  Sees:       │         │  Keeps:      │         │  Provides:   │
    │  Agency brand│         │  $2,250/mo   │         │  Everything  │
    │  Agency app  │         │  per client  │         │  under the   │
    │  Agency URL  │         │  (90% margin)│         │  hood        │
    │              │         │              │         │              │
    └──────────────┘         └──────────────┘         └──────────────┘

    Agency charges what they want. RAMP charges flat fee.
    Agency keeps the spread. Everyone wins.
```

---

*Last updated: May 2026 — For use in investor deck and partner sales conversations.*
