# RAMP — White Label: Technical Brief

**To:** Tzvi  
**From:** Max  
**Date:** May 27, 2026  
**Subject:** White label capability — what, why, how, timeline, cost

---

## What This Is

The ability to deploy the RAMP client portal under a different brand for agency clients or resellers. Same system, different skin — their logo, their colors, their domain.

From the end-client's perspective — they're using their agency's proprietary Reddit engagement platform. They never see "RAMP."

---

## How It Works (Simple Version)

```
Agency signs up as a partner
         ↓
We configure: their domain, logo, colors, company name
         ↓
Their clients log in at agency-brand.com
         ↓
Same portal, same features — different paint job
```

**We build the engine. They put their badge on it.**

---

## Why This Matters

| Without white label | With white label |
|--------------------|-----------------|
| Agency refers clients to "RAMP" | Agency owns the relationship |
| Client knows who built it | Client sees agency's brand |
| Agency is a reseller | Agency is a platform owner |
| One price point | Agency marks up freely |
| We compete with our own partners | Partners are distribution channels |

**Revenue impact:**
- Agency pricing: $999–$3,499/mo per agency (3–20 client slots)
- White label premium: +$500–$1,000/mo on top
- Zero additional support cost (agency handles their own clients)

---

## What Gets Customized

| Layer | What changes | Effort |
|-------|-------------|--------|
| Logo | Sidebar logo, login page, favicon | Config |
| Colors | Primary accent, surface tones (CSS tokens) | Config |
| Domain | `app.agencyname.com` → our server | DNS + SSL |
| Company name | Footer, emails, empty states | Config |
| Email sender | `noreply@agencyname.com` | SMTP config |

**What does NOT change:**
- Backend logic (pipeline, AI, safety)
- Admin panel (stays RAMP-branded, only we see it)
- API structure
- Database (multi-tenant, already isolated by client_id)

---

## Architecture (Already 80% Ready)

The client portal redesign (UX Spec v3) already separates:
- `client_base.html` — client-facing template (dark theme, sidebar)
- `admin_base.html` — our internal admin (untouched)

White label = make `client_base.html` read branding from a config table instead of hardcoded values.

```python
# What exists today:
class Client(Base):
    id, name, keywords, is_active, plan_type...

# What we add:
class BrandingConfig(Base):
    client_id        # or agency_id
    logo_url         # uploaded SVG/PNG
    primary_color    # hex, replaces --color-orange
    accent_color     # hex, hover states
    company_name     # shown in UI
    custom_domain    # app.agencyname.com
    favicon_url      # browser tab icon
    email_from_name  # "AgencyName" in emails
    email_from_addr  # noreply@agencyname.com
```

Template reads branding at render time:
```html
<!-- Before (hardcoded) -->
<img src="/static/ramp-logo.svg">
<style>:root { --color-orange: #FF6B35; }</style>

<!-- After (dynamic) -->
<img src="{{ branding.logo_url }}">
<style>:root { --color-orange: {{ branding.primary_color }}; }</style>
```

---

## Custom Domain Setup

| Step | Who does it | Time |
|------|-------------|------|
| Agency buys domain | Agency | Their problem |
| Agency points CNAME to us | Agency (we give instructions) | 5 min |
| We add SSL cert (Let's Encrypt) | Automated (Caddy/nginx) | Instant |
| We map domain → client branding | Admin panel | 1 click |

**No separate deployment per agency.** One server, one codebase. Domain routing handled at nginx/reverse proxy level.

---

## What's NOT White Label

Things that stay RAMP-only (our moat):

- **Admin panel** — agencies never see pipeline internals
- **AI prompts** — our IP, not exposed
- **Avatar management** — we control the infrastructure
- **Proxy/posting config** — operational layer stays hidden
- **System topology** — internal observability

Agencies get: client portal + review queue + dashboard + settings.  
We keep: everything that makes it work.

---

## Timeline

| Day | What Gets Done |
|-----|----------------|
| 1 | `BrandingConfig` model + migration + admin CRUD |
| 2 | Template injection (logo, colors, company name) |
| 3 | Custom domain routing (nginx config + auto-SSL) |
| 4 | Email sender customization |
| 5 | Admin UI for branding management + preview |
| **5** | **First white-label portal live** |

**5 working days from start to first branded portal.**

Prerequisite: Client Portal Phase 1 (dark theme + review queue) must be done first. White label is a layer on top of the portal redesign.

---

## Cost

### Development Cost
- My time only. No external dependencies.

### Operational Cost Per White-Label Client

| Item | Cost/mo |
|------|---------|
| Custom domain SSL | $0 (Let's Encrypt) |
| Extra server load | $0 (same app, same DB) |
| Logo/asset storage | $0 (S3, pennies) |
| **Total per agency** | **$0/mo marginal** |

### Revenue Per White-Label Agency

| Model | Monthly |
|-------|---------|
| Agency base (5 client slots) | $999/mo |
| White label premium | +$500/mo |
| Additional client slots (×$200) | variable |
| **Minimum per agency** | **$1,499/mo** |

At 3 agency partners: **$4,500+/mo** with zero marginal infrastructure cost.

---

## Competitive Positioning

**What agencies hear:**

> "Your clients see YOUR brand. Your platform, your relationship, your markup. We're the invisible engine underneath. You focus on client success — we handle the technology."

**Why agencies want this:**
- They already have Reddit marketing clients
- They don't want to build the tech (2 years, $500K+)
- They want to own the client relationship
- They want to set their own pricing (mark up 2-3x)
- They need something that looks like THEIR product

---

## Legal Position

- Standard SaaS white-label agreement
- Agency is the "platform operator" to their clients
- We are the "technology provider" to the agency
- Client data isolation already enforced (RBAC, query scoping)
- Agency sees only their clients' data (already built)

---

## What I Need From You

1. **Priority check** — is this before or after automated posting? I'd say: posting first (revenue enabler), white label second (distribution enabler).
2. **Pricing validation** — $500/mo white label premium on top of agency pricing. Too high? Too low?
3. **First target** — do you have an agency partner in mind who'd want this?
4. **Brand guidelines question** — the UX spec uses orange (#FF6B35) as accent. For white label, each agency picks their own accent color. Our RAMP brand guidelines say "never orange" — but that's for OUR brand. Agencies can use whatever color they want. Correct?

---

## Bottom Line

> **5 days → first white-label portal live.**  
> **$0/mo marginal cost per agency.**  
> **$1,500+/mo revenue per agency partner.**  
> **Same codebase, same server, different paint.**  
> **Agencies become distribution channels, not competitors.**

Waiting for your go.
