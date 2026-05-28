# User Manual — Owner & Partner

> **Audience:** Owner (Max), Partner (Tzvi, Jenny)  
> **Last updated:** 2026-05-28

---

## Your Role

**Owner** has full system access — infrastructure, settings, kill switches, all data.  
**Partner** has access to all clients, users, analytics, and audit logs — but NOT system settings or kill switches.

Both roles see all clients and can manage the entire business operation.

---

## What You Can Do

| Area | Owner | Partner |
|------|-------|---------|
| View all clients & data | ✅ | ✅ |
| Create/edit clients | ✅ | ✅ |
| Manage users (all roles) | ✅ | ✅ |
| Approve/reject drafts | ✅ | ✅ |
| Trigger pipeline manually | ✅ | ✅ |
| View AI cost analytics | ✅ | ✅ |
| View audit logs | ✅ | ✅ |
| Avatar farm management | ✅ | ✅ |
| Create avatar rentals | ✅ | ✅ |
| Set rent prices | ✅ | ❌ |
| System settings | ✅ | ❌ |
| Kill switches | ✅ | ❌ |

---

## Key Pages

| Page | URL | Purpose |
|------|-----|---------|
| Dashboard | `/admin/dashboard` | System overview, topology, activity feed |
| Clients | `/admin/clients` | All clients, onboarding, configuration |
| Avatars | `/admin/avatars` | All avatars, health, phases, intelligence |
| Review | `/admin/review` | Approve/reject/edit pending drafts |
| Users | `/admin/users` | User management, role assignment |
| Subreddits | `/admin/subreddits` | Subreddit registry, scraping status |
| Settings | `/admin/settings` | System settings (Owner only) |
| AI Costs | `/admin/ai-costs` | LLM usage and cost tracking |
| Audit Logs | `/admin/audit-logs` | Full action history |

---

## Daily Workflow (Partner — Tzvi)

### Morning (10 min)
1. **Dashboard** → check system health (all nodes green?)
2. **Review Queue** → approve/reject pending drafts for priority clients
3. **Activity Feed** → scan for anomalies (failed tasks, frozen avatars)

### As Needed
4. **Client onboarding** → use 7-step wizard for new clients
5. **Strategy review** → check/update strategy documents per avatar
6. **Avatar health** → review any frozen/shadowbanned avatars
7. **Reports** → export data for client meetings

---

## Client Management

### Onboarding a New Client

1. Go to `/admin/clients` → **"+ New Client"**
2. Complete the 7-step wizard:
   - Company profile (name, brand, industry)
   - Subreddits (where their audience lives)
   - Keywords (high/medium/low priority terms)
   - Avatars (assign existing or create new)
   - Personas (voice profiles for assigned avatars)
   - Pipeline config (scoring thresholds, generation limits)
   - Test run (dry run to verify setup)
3. Activate client → pipeline starts processing

### Deactivating a Client

1. Go to client detail → click **"Deactivate"**
2. Cascade: all assignments off, avatars unassigned, pipeline skips everything
3. Data preserved (can reactivate later)

### Reactivating a Client

1. Go to client detail → click **"Activate"**
2. Reassign avatars and subreddits as needed
3. Pipeline resumes on next scheduled run

---

## Avatar Farm Operations

### Farm Avatars
- Avatars with `is_farm_avatar=true` are in the shared inventory
- Not assigned to any client until rented
- Warming continues independently

### Creating a Rental
1. Go to avatar detail → **"Create Rental"**
2. Select client, set price, set duration (or indefinite)
3. Client can now use this avatar for their campaigns

### Pricing
- Silver (3-6 months warmed): $199 one-time
- Gold (6+ months, high karma): $499 one-time
- Monthly rental: varies by avatar quality

---

## Pipeline Control

### Manual Pipeline Trigger
- Dashboard → **"Run Pipeline"** button
- Triggers: scrape → score → generate for all active clients
- Use when: testing new client setup, or after config changes

### Kill Switches (Owner Only)

| Switch | Effect |
|--------|--------|
| `pipeline_enabled` | Stops ALL automated tasks (scraping, scoring, generation) |
| `generation_enabled` | Stops AI generation only (scraping and scoring continue) |
| `scrape_enabled` | Stops subreddit scraping only |

**When to use:** Suspected issues, Reddit API problems, cost spikes, avatar bans.

### Avatar Freeze
- Immediate exclusion from all pipelines
- Use when: shadowban detected, suspicious activity, client request
- Unfreeze when issue resolved

---

## User Management

### Creating Users

1. Go to `/admin/users` → **"+ New User"**
2. Select role:
   - `partner` — full business access (for Tzvi, Jenny)
   - `client_admin` — company admin (for client's main contact)
   - `client_manager` — daily reviewer (for client's team)
   - `client_viewer` — read-only (for client executives)
3. Assign to client (for client-scoped roles)
4. Send credentials

### Role Hierarchy
```
owner → can do everything
  └── partner → all clients, no system settings
        └── client_admin → own company, team management
              └── client_manager → own company, review only
                    └── client_viewer → own company, read-only
```

---

## Monitoring & Alerts

### What to Watch

| Signal | Where | Action |
|--------|-------|--------|
| Red topology node | Dashboard | Check logs, may need kill switch |
| Frozen avatar | Avatars page | Investigate reason, unfreeze or replace |
| High removal rate (>20%) | Avatar detail | Review voice profile, adjust strategy |
| CQS "lowest" | Avatar detail | Avatar auto-frozen, may need new account |
| Stale scraping (>24h) | Subreddits page | Check Reddit API, rate limits |
| AI cost spike | AI Costs page | Check for runaway generation loops |

### Audit Trail
- Every action logged: who, what, when, details
- Filter by user, action type, date range
- Export available for compliance

---

## Reporting (for Client Meetings)

### Available Exports
- Avatar performance report (karma, removal rate, patterns)
- Client activity summary (drafts generated, approved, posted)
- Pipeline transparency (what happened, when, why)

### Key Metrics to Share with Clients
- Comments posted this week/month
- Engagement rate (upvotes on posted comments)
- Subreddit coverage
- Avatar health status
- Top-performing comments
