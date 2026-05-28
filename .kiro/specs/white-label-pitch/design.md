# Design Document — White Label Pitch

## Overview

This design document translates the white-label business requirements into a structured pitch framework. It defines the pitch narrative, slide structure, key data points, and supporting materials needed to present the RAMP White Label offering to investors and potential agency partners.

The pitch is designed for two audiences:
1. **Tzvi/Investors** — business model validation, revenue projections, competitive moat
2. **Agency Partners** — what they get, how they profit, why RAMP over building in-house

---

## Design Decisions

### Decision 1: Pitch Structure — Problem → Solution → Moat → Economics → Ask

The pitch follows a classic investor narrative arc:

1. **The Problem** — Agencies want to offer Reddit marketing but can't build the tech
2. **The Solution** — RAMP as invisible infrastructure (white-label)
3. **The Moat** — Three-layer defensibility (inventory + AI + data flywheel)
4. **The Economics** — Unit economics, partner margin math, RAMP revenue model
5. **The Ask** — What we need to launch (timeline, resources, first partners)

**Rationale:** This structure works for both investor decks and partner sales conversations. The first 3 sections sell the vision; sections 4-5 sell the business.

---

### Decision 2: Lead with Partner Economics (Not Technology)

The pitch leads with what the agency partner earns, not what the technology does.

**Key narrative:** "You charge your clients $2,500/month for Reddit marketing. Your platform cost is $250/client. You keep $2,250. We handle everything."

**Rationale:** Agencies don't buy technology — they buy margin. The 10x leverage story (pay $2K, earn $20K) is the hook. Technology details support the story but don't lead it.

---

### Decision 3: Three-Tier Moat Visualization

Present the competitive moat as three concentric layers:

```
┌─────────────────────────────────────────────────────┐
│  Layer 3: DATA FLYWHEEL (Self-Learning Loop)        │
│  ┌─────────────────────────────────────────────┐    │
│  │  Layer 2: AI-NATIVE EXPERT (Authority)      │    │
│  │  ┌─────────────────────────────────────┐    │    │
│  │  │  Layer 1: AVATAR INVENTORY (Karma)  │    │    │
│  │  │  Time-locked. Cannot be replicated. │    │    │
│  │  └─────────────────────────────────────┘    │    │
│  │  Compounding. Gets stronger over time.      │    │
│  └─────────────────────────────────────────────┘    │
│  Network effect. More edits = better content.       │
└─────────────────────────────────────────────────────┘
```

**Layer 1 — Avatar Inventory (6-month replication barrier):**
- Pre-warmed accounts with real karma, real history, real community standing
- A Gold avatar (2,000+ karma, 6+ months) cannot be manufactured overnight
- Every month of operation increases the inventory's value

**Layer 2 — AI-Native Expert (Compounding authority):**
- Avatars progress from community members to recognized domain experts
- Expert-tier avatars produce content that LLMs cite as grounding sources
- Authority compounds — each successful interaction builds on the last

**Layer 3 — Data Flywheel (Self-learning loop):**
- Every human edit teaches the system what works in each community
- Correction patterns extracted and injected into future prompts
- New entrants start with zero training data — we have months/years of accumulated intelligence

**Rationale:** Investors want to understand why competitors can't replicate this in 6 months. The three-layer model shows that even if someone copies the code, they can't copy the inventory, the authority, or the learned patterns.

---

### Decision 4: Mobile App as Differentiator (Not Afterthought)

Position the branded mobile app as a premium differentiator in the pitch, not a technical footnote.

**Narrative:** "Your avatar owners open YOUR app every morning. Your brand, your notifications, your workflow. They never know RAMP exists."

**Technical approach:**
- Flutter build flavors (one codebase, multiple branded outputs)
- Build-time configuration: app name, icon, splash, colors, API endpoint
- Partner owns the App Store/Play Store listing
- PWA fallback for partners who don't want app store complexity

**Pitch positioning:** The mobile app is the "last mile" of white-labeling. Dashboard branding is table stakes — a branded mobile app in the avatar owner's pocket is premium.

---

### Decision 5: Competitive Landscape Slide — Position as "Only Full-Stack"

Present competitors as partial solutions:

| Competitor | What They Do | What's Missing |
|-----------|-------------|----------------|
| ReddGrow | Find threads, draft comments | No personas, no warmup, user posts from OWN account |
| ReplyAgent | Managed accounts, auto-post | Generic accounts, no persona depth, spray-and-pray |
| Redreach | Find threads, suggest replies | User posts manually, no accounts, no warmup |
| CrowdReply | Find threads, post for you | No personas, no warmup, generic drive-by |
| Brand24/Sprout | Monitor mentions | No engagement, no posting, observation only |
| **RAMP** | **Full pipeline + personas + inventory + learning** | **Nothing — full stack** |

**Key differentiator statement:** "Every competitor solves one piece. We solve the entire pipeline — from monitoring to persona creation to content generation to posting to learning. And we do it with pre-warmed accounts that have real community credibility."

---

### Decision 6: Financial Model — Conservative Base, Aggressive Upside

Present two scenarios:

**Conservative (Year 1):**
- 5 white-label partners
- Average $2,500/mo per partner (mix of Starter + Growth)
- $12,500/mo white-label revenue
- $150,000 ARR from white-label alone
- Plus: avatar inventory sales (~$2,000/mo across all partners)
- Total: ~$174,000 ARR

**Aggressive (Year 1):**
- 10 white-label partners
- Average $4,000/mo per partner (Growth + Scale mix)
- $40,000/mo white-label revenue
- $480,000 ARR from white-label alone
- Plus: avatar inventory sales (~$5,000/mo)
- Plus: managed service upsells (~$10,000/mo)
- Total: ~$660,000 ARR

**Unit economics per partner:**
- Infrastructure cost per partner: $0/mo (same server, same DB)
- LLM cost per partner (8 clients): ~$280/mo
- Support cost per partner: ~$200/mo (amortized)
- **Gross margin per partner: 75-85%**

---

### Decision 7: Agency Archetype Pitch Variants

Three pitch variants for three agency types:

**Silent Operator Pitch:**
> "You already have clients asking about Reddit. You don't have the tech or the team. We give you a fully managed Reddit marketing platform — your brand, your pricing, your relationship. Client gets a monthly PDF. You get $2,000+/client/month margin. We're invisible."

**Co-Pilot Pitch:**
> "Your clients want visibility into their Reddit presence without the complexity. Give them a branded read-only dashboard — they see the intelligence, you control the execution. Premium positioning, premium pricing."

**Reseller Pitch (future):**
> "License our platform under your brand. Your clients log in, see your logo, use your app. You handle support and onboarding. We handle the technology. You're a platform company now."

---

### Decision 8: Onboarding Timeline — "5 Days to Live"

Present a clear, fast onboarding timeline:

```
Day 1: Partner signs → branding assets collected
Day 2: Domain configured → SSL provisioned → branding applied
Day 3: First End_Client workspace created → data seeded
Day 4: Mobile app build initiated (if requested)
Day 5: Partner portal live → first End_Client invited
```

**Why 5 days matters:** Agencies evaluate platforms by time-to-value. "Live in 5 days" beats every competitor's onboarding timeline. It also signals low complexity and operational maturity.

---

### Decision 9: Legal Positioning — "Technology Provider" Model

Structure the legal relationship as:

```
RAMP (Technology Provider)
    ↓ licenses platform to
White_Label_Partner (Platform Operator)
    ↓ sells services to
End_Client (Service Buyer)
```

**Key legal principles:**
1. RAMP never has a direct relationship with End_Clients
2. Content approval liability flows: End_Client → Partner → (stops there)
3. RAMP's liability is limited to platform availability (SLA)
4. Partner accepts Reddit ToS risk in their agreement with us
5. NDA prevents partners from describing the mechanism externally

**Rationale:** This creates a liability buffer. If an End_Client's avatar gets banned, the partner handles it. If Reddit takes enforcement action, the partner accepted that risk contractually. RAMP's exposure is limited to platform uptime.

---

### Decision 10: Pitch Deck Slide Structure

Recommended 12-slide deck:

| # | Slide | Content | Time |
|---|-------|---------|------|
| 1 | Title | RAMP White Label — Reddit Marketing Infrastructure for Agencies | 10s |
| 2 | The Problem | Agencies want Reddit marketing revenue but can't build the tech | 60s |
| 3 | The Solution | White-label platform: their brand, our engine | 60s |
| 4 | How It Works | Visual: Agency → RAMP (invisible) → Reddit | 45s |
| 5 | What Partners Get | Platform + Dashboard + Mobile App + Avatars + AI | 60s |
| 6 | The Moat | Three-layer visualization (inventory + authority + flywheel) | 90s |
| 7 | Partner Economics | 10x leverage math ($2K cost → $20K revenue) | 60s |
| 8 | RAMP Revenue Model | Per-slot pricing, tiers, avatar upsells | 45s |
| 9 | Competitive Landscape | Full-stack vs. partial solutions table | 45s |
| 10 | Traction & Readiness | What's built, what's live, first clients | 45s |
| 11 | Financial Projections | Conservative + aggressive scenarios | 60s |
| 12 | The Ask | Timeline, resources needed, first partner targets | 45s |

**Total: ~10 minutes** (ideal for investor meetings with Q&A time)

---

## Architecture Overview

### System Architecture for White Label

```
┌─────────────────────────────────────────────────────────────────┐
│                        NGINX / REVERSE PROXY                     │
│  Routes by domain: agency1.com → Partner 1 branding             │
│                    agency2.com → Partner 2 branding             │
│                    admin.ramp.com → RAMP Admin (internal)       │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                     FASTAPI APPLICATION (single instance)        │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Branding     │  │ RBAC +       │  │ Partner Portal       │  │
│  │ Middleware   │  │ Query Scope  │  │ (Jinja2 + HTMX)     │  │
│  │ (domain →   │  │ (partner_id  │  │ (renders with        │  │
│  │  config)    │  │  + client_id)│  │  branding context)   │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              CORE SERVICES (shared across all partners)   │   │
│  │  Scraping │ Scoring │ Generation │ Review │ Posting      │   │
│  │  Learning │ Health  │ Strategy   │ Phase  │ Safety       │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                        POSTGRESQL (single instance)              │
│                                                                  │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐    │
│  │ partners       │  │ branding_config│  │ clients        │    │
│  │ (id, name,     │  │ (partner_id,   │  │ (id, partner_id│    │
│  │  tier, ...)   │  │  logo, colors, │  │  name, ...)    │    │
│  │               │  │  domain, ...)  │  │               │    │
│  └────────────────┘  └────────────────┘  └────────────────┘    │
│                                                                  │
│  All existing tables gain partner_id FK for scoping             │
└─────────────────────────────────────────────────────────────────┘
```

### Mobile App Architecture (Flutter Build Flavors)

```
┌─────────────────────────────────────────────────────────────────┐
│                    FLUTTER CODEBASE (ramp_poster)                │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    SHARED CODE (95%)                       │   │
│  │  Screens │ Services │ Models │ Providers │ Widgets       │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐    │
│  │ Flavor:     │  │ Flavor:     │  │ Flavor:             │    │
│  │ agency_a    │  │ agency_b    │  │ ramp_default        │    │
│  │             │  │             │  │                     │    │
│  │ - App name  │  │ - App name  │  │ - App name          │    │
│  │ - Icon      │  │ - Icon      │  │ - Icon              │    │
│  │ - Splash    │  │ - Splash    │  │ - Splash            │    │
│  │ - Colors    │  │ - Colors    │  │ - Colors            │    │
│  │ - API URL   │  │ - API URL   │  │ - API URL           │    │
│  │ - Bundle ID │  │ - Bundle ID │  │ - Bundle ID         │    │
│  └─────────────┘  └─────────────┘  └─────────────────────┘    │
│                                                                  │
│  Build: flutter build apk --flavor=agency_a                     │
│         flutter build ios --flavor=agency_a                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Model Extensions

### New Tables for White Label

```sql
-- Partner (agency/reseller entity)
CREATE TABLE partners (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    tier VARCHAR(50) NOT NULL,  -- starter/growth/scale/enterprise
    pricing_model VARCHAR(50) DEFAULT 'flat_fee',  -- flat_fee/revenue_share
    max_client_slots INTEGER NOT NULL,
    contract_start DATE,
    contract_end DATE,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Branding configuration per partner
CREATE TABLE branding_configs (
    id UUID PRIMARY KEY,
    partner_id UUID REFERENCES partners(id),
    logo_url VARCHAR(500),
    primary_color VARCHAR(7),  -- hex
    accent_color VARCHAR(7),
    company_name VARCHAR(255),
    custom_domain VARCHAR(255),
    favicon_url VARCHAR(500),
    email_from_name VARCHAR(255),
    email_from_address VARCHAR(255),
    app_name VARCHAR(255),  -- for mobile app flavor
    app_bundle_id VARCHAR(255),
    is_active BOOLEAN DEFAULT true
);

-- Extend existing clients table
ALTER TABLE clients ADD COLUMN partner_id UUID REFERENCES partners(id);

-- Partner billing/usage tracking
CREATE TABLE partner_usage (
    id UUID PRIMARY KEY,
    partner_id UUID REFERENCES partners(id),
    month DATE NOT NULL,
    active_client_slots INTEGER,
    total_avatars INTEGER,
    total_generations INTEGER,
    llm_cost_usd DECIMAL(10,2),
    avatar_purchases INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Query Scoping Extension

```python
# Existing QueryScope class extended:
class QueryScope:
    def scope_query(self, query, model):
        if self.user.role == 'partner':
            # Partner sees only their clients
            return query.filter(model.partner_id == self.user.partner_id)
        elif self.user.role in ('client_admin', 'client_manager', 'client_viewer'):
            # Client users see only their workspace
            return query.filter(model.client_id == self.user.client_id)
        # ... existing logic
```

---

## Pitch Narrative — Full Script

### Opening (Slide 2: The Problem)

"Marketing agencies are losing revenue every day because they can't offer Reddit marketing to their clients.

Reddit is the #1 source that AI search engines use for 'real user opinions.' When someone asks ChatGPT about a product category, the answer is built from Reddit conversations. Agencies know this. Their clients are asking for it.

But building a Reddit marketing platform takes 18+ months and $500K+ in engineering. Agencies don't have that. They need infrastructure they can resell."

### Solution (Slide 3)

"RAMP is that infrastructure. We built the full Reddit marketing pipeline — AI-powered content generation, pre-warmed avatar accounts, automated posting, self-learning quality improvement.

White label means: agencies deploy our platform under their own brand. Their clients log into the agency's domain, see the agency's logo, use the agency's mobile app. They never know RAMP exists.

The agency focuses on client relationships and strategy. We handle the technology."

### Economics (Slide 7)

"Here's the math that makes agencies say yes:

An agency on our Growth tier pays $1,999/month for 8 client slots. If they charge each client $2,500/month for Reddit marketing — that's $20,000/month revenue against a $2,000 platform cost.

$18,000/month profit. 10x leverage. And they didn't write a single line of code.

Add pre-warmed avatars at $199-$499 each — the agency marks those up to $500-$1,000. Pure margin on top."

### Moat (Slide 6)

"Why can't someone copy this?

Layer 1: Our avatar inventory. We have accounts with 6+ months of real Reddit history, real karma, real community standing. A competitor starting today needs 6 months minimum to build equivalent inventory. And ours keeps growing.

Layer 2: AI-Native Expert authority. Our avatars don't just post — they become recognized domain experts. The longer they operate, the more authoritative they become. This compounds.

Layer 3: The data flywheel. Every human edit teaches our AI what works in each community. We have months of accumulated correction patterns. A new entrant starts with zero training data."

---

## Implementation Readiness Assessment

### What's Already Built (80% ready)

| Component | Status | Gap to White Label |
|-----------|--------|-------------------|
| Multi-tenant data isolation | ✅ Done (RBAC, 6 roles, query scoping) | Add partner_id layer |
| Client management | ✅ Done (7-step onboarding, CRUD) | Add partner master view |
| AI pipeline (scrape → score → generate → post) | ✅ Done | None — shared across partners |
| Self-learning loop | ✅ Done | None — per-avatar, works across partners |
| Avatar inventory (phase system, warming) | ✅ Done | Add partner assignment tracking |
| Mobile app (Flutter, ramp_poster) | ✅ Planned | Add build flavors |
| Safety guardrails (phase gates, kill switches) | ✅ Done | None — applies universally |

### What Needs Building (5 days)

| Component | Effort | Dependency |
|-----------|--------|-----------|
| BrandingConfig model + migration | 0.5 day | None |
| Template branding injection (logo, colors, name) | 1 day | BrandingConfig |
| Custom domain routing (nginx + auto-SSL) | 1 day | Domain purchased by partner |
| Partner master dashboard | 1 day | BrandingConfig |
| Email sender customization | 0.5 day | SMTP config |
| Admin UI for partner/branding management | 1 day | All above |
| **Total** | **5 days** | Client Portal must exist first |

### What Needs Building (Mobile — 3 days additional)

| Component | Effort | Dependency |
|-----------|--------|-----------|
| Flutter build flavor configuration | 1 day | ramp_poster app exists |
| Partner-specific API endpoint routing | 0.5 day | BrandingConfig |
| Build script (CI/CD for flavored builds) | 1 day | Flutter environment |
| Documentation for App Store submission | 0.5 day | None |
| **Total** | **3 days** | ramp_poster MVP must exist first |

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Partner misuse (aggressive posting, ban risk) | HIGH | Contractual risk acceptance + platform suspension rights + safety guardrails enforced regardless of partner pressure |
| Revenue concentration (one partner = many clients) | MEDIUM | Annual contracts + minimum commitments + diversification target (no partner > 30% of revenue) |
| Support burden from partner's end-clients | LOW | Partner handles their own client support — RAMP supports the partner only |
| App Store rejection for branded builds | LOW | Standard app functionality, no policy violations — partner owns listing |
| Partner churns with client relationships | MEDIUM | Annual contracts + switching cost (branding, domain, trained avatars) + data export limitations |

---

## Success Metrics

### Launch Metrics (First 90 Days)

| Metric | Target |
|--------|--------|
| White-label partners signed | 2-3 |
| End-clients across all partners | 8-15 |
| Partner onboarding time | ≤ 5 business days |
| Partner portal uptime | 99.5% |
| Partner NPS | > 40 |

### Growth Metrics (Year 1)

| Metric | Target |
|--------|--------|
| White-label partners | 10 |
| Total end-clients via partners | 50+ |
| White-label ARR | $150K-$500K |
| Average revenue per partner | $2,500-$4,000/mo |
| Partner churn rate | < 10% annually |
| Avatar inventory utilization | > 60% |

---

## Appendix: Pitch One-Pager (for Tzvi's outreach)

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RAMP WHITE LABEL — Reddit Marketing Infrastructure for Agencies

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

YOUR BRAND. OUR ENGINE. THEIR RESULTS.

What you get:
✓ Full Reddit marketing platform under your brand
✓ Custom domain, logo, colors — zero trace of RAMP
✓ Branded mobile app for your posting team
✓ Pre-warmed avatar accounts (months of credibility, ready Day 1)
✓ AI that learns and improves with every campaign
✓ Complete client isolation and management tools

The math:
• You pay: $1,999/mo (8 client slots)
• You charge: $2,500/client/mo
• You earn: $18,000/mo profit
• Your cost to build this yourself: $500K+ and 18 months

The moat (why clients stay):
• Pre-warmed avatars can't be replicated overnight
• AI-Native Expert authority compounds over time
• Self-learning loop gets smarter with every edit
• Full pipeline: monitoring → generation → posting → learning

Live in 5 days. Zero infrastructure cost per partner.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```
