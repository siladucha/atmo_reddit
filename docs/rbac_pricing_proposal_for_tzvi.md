# RAMP Platform — Access Control, Pricing & Avatar Model

**Prepared by:** Max (Tech)  
**For review by:** Tzvi (Business)  
**Date:** May 13, 2026  
**Status:** Draft — awaiting business approval before implementation

---

## Purpose

Before we open the platform to external clients, we need to agree on:

1. Who can access what (roles and permissions)
2. Pricing tiers and limits
3. Avatar farm model and rental pricing
4. What the system enforces automatically

This document needs your sign-off before I build it.

---

## 1. User Roles

### Platform Team (us)

| Role | Who | Access |
|------|-----|--------|
| **Owner** | Max | Everything. System settings, kill switches, infrastructure, all clients. |
| **Partner** | Tzvi, Jenny | All clients, user management, AI costs, audit logs. Cannot change system settings or kill switches. |

### B2B Client Team (their people)

| Role | Who | Access |
|------|-----|--------|
| **Client Admin** | CEO/CMO of client company | Manages their team, avatars, subreddits, approves drafts, sees costs for their company. Cannot see other clients. |
| **Client Manager** | Marketing manager at client | Uses avatars, reviews/approves drafts, views activity. Cannot manage team or delete avatars. |
| **Client Viewer** | Stakeholder, read-only | Views dashboard, drafts, reports. Can approve drafts only if we enable it. |

### B2C (future, individual users)

| Role | Who | Access |
|------|-----|--------|
| **B2C User** | Individual person | One personal avatar, simplified UI. Can upgrade to B2B. |

---

## 2. Avatar Model

### Avatar Types

| Type | Owner | Who Pays | Replacement on Ban |
|------|-------|----------|-------------------|
| **Client Owned** | Client's property | Client pays plan | No replacement. Client loses the account. |
| **Farm Rental** | Platform property | Client pays rental fee | We replace (SLA by tier). |
| **B2C Personal** | User's property | User pays B2C plan | No replacement. User loses the account. |

### Avatar Tiers (by karma maturity)

| Tier | Karma Range | What It Can Do | Rental Price |
|------|-------------|----------------|--------------|
| **Bronze** | 50–500 | Hobby comments only. Building credibility. Phase 1 behavior. | $49/mo |
| **Silver** | 500–2,000 | Professional comments + posts. Has history. Phase 2 eligible. | $149/mo |
| **Gold** | 2,000–10,000 | Full access including brand mentions. Phase 3 eligible. | $299/mo |
| **Platinum** | 10,000+ | Maximum credibility. Top-tier influence. Phase 3. | $499/mo |

### Why Higher Tiers Cost More

1. **Better results** — more history = AI generates more accurate, contextual comments
2. **Higher operational cost** — more health checks, CQS monitoring, karma tracking
3. **Higher replacement risk** — Platinum = 5+ months of warming. Bronze = 2 weeks.

### Avatar Phase Rules (what the system enforces)

| Phase | Hobby Comments | Professional Comments | Brand Mentions | Posts |
|-------|---------------|----------------------|----------------|-------|
| **Phase 1** (warming) | ✅ | ❌ | ❌ | ❌ |
| **Phase 2** (seeding) | ✅ | ✅ | ❌ | ✅ |
| **Phase 3** (brand) | ✅ | ✅ | ✅ | ✅ |

**Important:** Tier (karma) determines the *price*. Phase determines what the avatar *can do*. A Gold avatar (high karma) can still be in Phase 2 if we haven't promoted it to Phase 3 yet. Phase promotion is a business decision, not automatic.

---

## 3. Pricing Tiers

### B2B Plans

| Plan | Price/mo | Owned Avatars | Farm Rentals | Comments/mo | Posts/mo | Subreddits |
|------|----------|---------------|--------------|-------------|----------|------------|
| **Seed** | $149 | 1 | +1 optional | 30 | 0 | 5 |
| **Starter** | $399 | 3 | +2 optional | 60 | 0 | 10 |
| **Growth** | $799 | 7 | +3 optional | 150 | 10 | unlimited |
| **Scale** | $1,499 | 15 | +5 optional | 400 | 30 | unlimited |
| **Agency** | custom | per-client | shared farm | custom | custom | unlimited |

### B2C Plan

| Plan | Price/mo | Avatar | Comments/mo | Posts/mo | Subreddits |
|------|----------|--------|-------------|----------|------------|
| **B2C** | $49 | 1 personal (grows own karma) | 30 | 0 | 3 |

### Key Rules

- **Comments/mo** = total across ALL avatars (owned + rented). Hobby comments during warming count too.
- **Posts/mo** = Reddit posts (not comments). Only available on Growth+.
- **Subreddits** = how many subreddits we monitor for this client.
- Farm rentals are **additional cost** on top of plan price.

---

## 4. Client Cost Calculator

### Formula

```
Monthly total = Plan price + Sum of all avatar rentals
```

### Examples

| Scenario | Plan | Rentals | Total/mo |
|----------|------|---------|----------|
| Startup, 1 own avatar, no rentals | Seed $149 | — | **$149** |
| Startup + 1 Bronze rental | Seed $149 | 1× Bronze $49 | **$198** |
| Mid-size, 3 own + 1 Gold rental | Starter $399 | 1× Gold $299 | **$698** |
| Growth, 7 own + 2 Silver rentals | Growth $799 | 2× Silver $298 | **$1,097** |
| Enterprise, 15 own + 5 Gold rentals | Scale $1,499 | 5× Gold $1,495 | **$2,994** |
| Enterprise, 15 own + 3 Platinum | Scale $1,499 | 3× Platinum $1,497 | **$2,996** |
| B2C individual | B2C $49 | — | **$49** |

---

## 5. Replacement SLA (when avatar gets banned)

| Avatar Type | Replacement? | Timeframe | Who Pays |
|-------------|-------------|-----------|----------|
| Client Owned | ❌ No | N/A | Client loses the account |
| Farm Bronze | ✅ Yes | 3 days | We absorb |
| Farm Silver | ✅ Yes | 5 days | We absorb |
| Farm Gold | ✅ Yes | 14 days | We absorb |
| Farm Platinum | ✅ Yes | 30–45 days | We absorb |
| B2C Personal | ❌ No | N/A | User loses the account |

**Note:** Replacement = same tier from available inventory. If no Platinum available, we offer Gold + credit until Platinum is ready.

---

## 6. What Each Role Can See and Do

### Platform Admin Panel (owner + partner only)

Clients NEVER see this.

- All clients dashboard, system health, topology
- Kill switches (owner only)
- System settings (owner only)
- User management (create any user, assign roles)
- AI cost analytics (all clients)
- Audit logs, avatar farm management

### B2B Client Hub (what clients see)

| Feature | Client Admin | Client Manager | Client Viewer |
|---------|-------------|----------------|---------------|
| Dashboard (metrics) | ✅ | ✅ | ✅ |
| Subreddits (view) | ✅ | ✅ | ✅ |
| Subreddits (add/remove) | ✅ | ✅ | ❌ |
| Avatars (view + stats) | ✅ | ✅ | ✅ |
| Avatars (create new) | ✅ (within limit) | ❌ | ❌ |
| Avatars (delete) | ✅ | ❌ | ❌ |
| Drafts (view) | ✅ | ✅ | ✅ |
| Drafts (approve/reject) | ✅ | ✅ | Only if enabled |
| Activity feed | ✅ | ✅ | ✅ |
| Reports | ✅ | ✅ | ✅ |
| Team management | ✅ (own company) | ❌ | ❌ |
| Client settings | ✅ | ❌ | ❌ |

### What Clients CANNOT See (ever)

- Other clients' data
- Platform-wide analytics
- System settings / kill switches
- Audit logs
- AI cost breakdown by model/token (they see total $ only)
- Learning data internals
- Admin panel

---

## 7. System Settings — What You Control vs. What I Control

**Key principle:** You sell the client access to the platform. You are financially responsible for their account. The client pays you, you pay operational costs from that revenue.

### Settings Only I (Owner) Can Change

These can break the system if misconfigured.

| Setting | What It Does |
|---------|-------------|
| Kill switches (pipeline/generation/scrape) | Emergency stop for all operations |
| API keys (Reddit, LLM, Gemini) | Breaking = all operations stop |
| AI model selection | Wrong model = 10x cost or quality drop |
| Infrastructure (Redis, ports, env) | Breaking = system crash |
| Dry run mode | Accidentally on = no output generated |

### Settings You (Partner) Can See and Monitor

| Setting | Why You Need It |
|---------|----------------|
| Monthly AI budget ($) | Know the spending cap |
| AWS credits remaining | Financial planning |
| AI cost per client | Know your margins |
| Audit logs | Security, accountability |

### Settings You (Partner) Can Change

Operational tuning that affects client experience but can't break the system:

| Setting | What It Does | Default |
|---------|-------------|---------|
| AI pipeline schedule | When comments are generated (UTC hours) | 8:00, 14:00 |
| Hobby pipeline schedule | When hobby comments run | 10:00 |
| Scrape freshness window | How often subreddits re-scraped | 12 hours |
| Max comments per subreddit/day | Safety limit per avatar | 2 |
| Min interval between comments | Gap between posts by same avatar | 15 min |
| Max brand mention ratio | Safety cap (% of comments with brand) | 30% |
| Thread max age | Don't comment on old threads | 48 hours |
| Health check interval | How often avatars checked for bans | 12 hours |

### Per-Client Settings (you configure during onboarding)

| Setting | What It Does |
|---------|-------------|
| Plan type | Determines all limits |
| Max avatars (owned + rented) | Capacity cap |
| Max comments/month | Action volume cap |
| Max posts/month | Post volume cap |
| Max subreddits | Monitoring cap |
| Draft approval for viewers | Can their read-only users approve? |
| Active/inactive toggle | Deactivate = all pipelines stop |
| Keywords | What topics to score for |
| Subreddit assignments | Which subs to monitor |
| Avatar assignments | Which avatars work for them |

---

## 8. Financial Responsibility Model

```
Client pays you  →  You pay operational costs  →  System operates

$399/mo (Starter)     $500/mo (shared across      ~$50/client AI cost
+ $299 (Gold rental)   all clients)
= $698 from client                                 Your margin: ~$648
```

### What You're Selling

You are NOT selling "AI tokens" or "server time." You are selling:

1. **Platform access** — login, dashboard, review queue
2. **Avatar capacity** — X owned + Y rented slots
3. **Action volume** — X comments/month, Y posts/month
4. **Monitoring coverage** — X subreddits watched
5. **Pre-warmed credibility** — farm avatars with established karma (our moat)

The client never sees AI costs, token counts, or infrastructure. They see: "I have 3 avatars, 60 comments/month, 10 subreddits."

### What Happens When Limits Are Hit

| Limit | System Behavior | Your Action |
|-------|----------------|-------------|
| Max comments/month | Pipeline stops generating. Pending drafts still reviewable. | Upsell or wait for next month. |
| Max avatars | "Maximum reached" error on create. | Upsell or suggest rental. |
| Max subreddits | Cannot add new. Must remove one first. | Upsell to Growth (unlimited). |
| Avatar banned | Auto-frozen. | Replace from farm (SLA). You eat the cost. |
| AI costs spike | No auto-stop within plan limits. | Monitor dashboard. Adjust if needed. |

---

## 9. Security Guarantees

| Guarantee | How |
|-----------|-----|
| Client A cannot see Client B's data | Every query filtered by client_id. Backend enforces. |
| Direct URL manipulation blocked | `/clients/other-uuid` returns 403. |
| AI never mixes client data | Prompts contain ONLY the requesting client's data. Runtime assertion. |
| Rented avatar isolation | Each client sees only their own drafts/activity for shared avatar. |
| Role changes immediate | Next click enforces new permissions. |

---

## 10. Questions for You (Tzvi)

### Pricing

1. **Seed at $149 or $399?** — Your PRD/Budget docs say $399, Business Brief says $149. Which is current?

2. **B2C at $49** — right price? Or higher ($79) to avoid support overhead?

3. **Farm rental prices** — Bronze $49, Silver $149, Gold $299, Platinum $499. Feel right?

4. **Posts only on Growth+** — Seed/Starter get 0 posts. Correct? Posts are higher risk.

5. **Subreddit limits** — B2C=3, Seed=5, Starter=10, Growth+=unlimited. Enough pressure to upgrade?

### Roles

6. **Client Admin creating other Client Admins** — current proposal: NO (only we can). Prevents power escalation. OK?

7. **Draft approval for Viewer** — toggle per client. Default OFF. Charge extra or just a config?

8. **Jenny's role** — `partner` (same as you). Full access minus system settings. OK?

### Avatar Farm

9. **Platinum replacement 30–45 days** — acceptable? Or offer Gold + credit as interim?

10. **Client sees avatar tier?** — I assume yes ("Gold avatar, 4200 karma, r/cybersecurity"). Confirm?

11. **Rental cancellation** — immediate or end-of-billing-period? Prorate?

### Financial

12. **Who handles billing/invoicing?** — You manually, or do we need Stripe integration?

13. **Monthly budget** — current $500/mo covers 10 clients. When we hit 10, budget goes up proportionally?

---

## 11. Implementation Priority

| Phase | What | When |
|-------|------|------|
| **1** | Role enforcement + data isolation | Week 1–2 |
| **2** | Plan limits enforcement | Week 2–3 |
| **3** | Avatar farm & rentals | Week 3–4 |
| **4** | B2C flow | Week 4+ |

Phase 1 is P0 — blocks pilot with external client access.

---

*Please review, mark up, and answer the questions. Once approved, I start building.*
