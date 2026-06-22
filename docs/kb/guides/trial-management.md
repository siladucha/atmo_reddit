# Trial User Management — Complete Manual

> **Audience:** Platform admins (owner/partner), client admins (trial users)
> **Last updated:** 2026-06-20

## Overview

RAMP offers a 14-day free trial for self-service clients. Trial users get access to the full AI-powered onboarding wizard, client portal, and pipeline — with limited quotas (1 avatar, 30 comments/month). After 14 days, access is blocked until the admin upgrades the client to a paid plan.

This manual covers:
1. How trials are created (self-service signup)
2. What trial users see and can do (client portal)
3. How admins/partners manage trials (admin panel)
4. Trial lifecycle and expiration logic
5. Conversion workflow (trial → paid)

---

## 1. Trial Signup Flow (Self-Service)

### Entry Point

`https://gorampit.com/onboard/trial`

### Requirements

- **Work email only** — personal emails (Gmail, Hotmail, Yahoo, Protonmail, etc.) are blocked
- Password (any length)
- Full name (optional)
- Company name (optional — defaults to email prefix if empty)

### What Happens on Signup

1. System validates the email is a work domain (not in blocked list)
2. Checks email isn't already registered
3. Creates a **Client** record:
   - `plan_type = "trial"`
   - `max_avatars = 1`
   - `max_comments_per_month = 30`
   - `is_active = True`
   - `current_onboarding_step = 1`
4. Creates a **User** record:
   - `role = client_admin` (full client-level permissions)
   - `client_id` → linked to the trial client
5. Logs in automatically via JWT cookie
6. Redirects to `/onboard` (6-step wizard)

### Anti-Bot Protection

- Honeypot field (`gotcha`) — if filled, silently redirects back without creating anything

---

## 2. Client Portal for Trial Users

### What Trial Users See

Trial users get **full portal access** identical to paid clients:

| Section | URL | Available |
|---------|-----|-----------|
| Home / Dashboard | `/clients/{id}/home` | ✅ |
| Review Queue | `/clients/{id}/review` | ✅ |
| Avatars | `/clients/{id}/avatars` | ✅ |
| Avatar Detail | `/clients/{id}/avatars/{avatar_id}` | ✅ |
| Subreddits | `/clients/{id}/subreddits` | ✅ |
| Keywords | `/clients/{id}/keywords` | ✅ |
| Strategy | `/clients/{id}/strategy` | ✅ |
| Reports | `/clients/{id}/report` | ✅ |
| EPG (Daily Program) | `/clients/{id}/epg` | ✅ |
| Settings | `/clients/{id}/settings` | ✅ |
| Notifications | `/clients/{id}/notifications` | ✅ |

### Trial Indicators in Portal

The portal sidebar shows:
- **`is_trial` badge** — indicates trial status
- **`trial_days_remaining`** — countdown (e.g. "7 days left")

### Trial Rate Limits (Portal Actions)

Trial users (with `client_admin` role) can trigger:
- **Pipeline** — max 2 per day
- **EPG Rebuild** — max 1 per day
- **Strategy** — max 1 per week per avatar
- **Regenerate draft** — unlimited

### What Happens When Trial Expires

After 14 days:
1. **All portal pages** render `client/trial_expired.html` instead of normal content
2. **POST actions** return HTTP 403: "Trial expired. Please upgrade to continue using RAMP."
3. **Pipeline tasks** skip the client entirely (scoring, generation, scraping for this client stops)
4. **Data is preserved** — profile, keywords, subreddits, drafts, landscape report all remain intact
5. User sees a CTA: "Upgrade to Start Posting →" (mailto: tzvi@gorampit.com)

### Trial Expired Page

Shows:
- "Your trial has ended" message
- Client name
- Reassurance that data is preserved
- Upgrade button (email link)
- Sign out link

---

## 3. Onboarding Wizard (6 Steps)

Trial users go through an AI-assisted onboarding:

| Step | What | AI Involvement |
|------|------|----------------|
| 1 | Company Profile | AI scrapes website URL, auto-fills company name, product description, value proposition, industry |
| 2 | Problem & Competitors | AI suggests customer pain points, unique advantages, competitor names |
| 3 | ICP Definition | AI suggests job titles, seniority, frustrations, search queries |
| 4 | Voice & Guardrails | AI suggests brand voice, never-associate topics, legal limits, admired style. Tone calibration (5 sample sentences rated by user) |
| 5 | Keywords & Subreddits | AI suggests keywords (high/medium/low priority) and relevant subreddits |
| 6 | Quality Gate & Activate | Validates minimum config, activates client, dispatches Day 1 scraping |

### Onboarding Progress Tracking

- `Client.current_onboarding_step` — tracks which step user is on (1-6)
- `Client.onboarding_completed_at` — timestamp when wizard completes
- Users can return to `/onboard` and resume from where they left off
- Admin sees step progress in trial management panel

---

## 4. Admin / Partner Trial Management

### Access

- **URL**: `https://gorampit.com/admin/trials`
- **Required role**: `owner` or `partner` (require_superuser dependency)
- **Navigation**: Admin panel → sidebar → "Trial Management"

### Trial List View

Shows all trial clients with:

| Column | Description |
|--------|-------------|
| Client / Company | Client name (link to client detail) |
| User | Full name of the user who signed up |
| Email | Registration email (monospace font) |
| Status | Badge: `Active` (green) / `Expiring` (amber, ≤3 days left) / `Expired` (red, 0 days) |
| Days Left | X / 14 counter |
| Started | Creation date |
| Onboarding | Step X/6 or "Complete" or "Not started" |
| Actions | View, Upgrade, +7d, Delete |

### Summary Counters

Top of page shows:
- Active trials (green badge)
- Expiring soon (amber badge, ≤3 days)
- Expired trials (red badge)

### Available Actions

#### View Client
Link to `/admin/clients/{client_id}` — full client detail page in admin panel.

#### Upgrade to Paid Plan
- **Button**: "Upgrade" (green)
- **Confirmation**: "Upgrade {name} to Starter plan?"
- **What it does**:
  - Sets `plan_type` from `"trial"` to `"starter"`
  - Sets `max_avatars` from 1 to 3
  - Logs audit event: `upgrade_trial` (from: trial, to: starter)
- **Result**: Client immediately gets full paid access, pipeline resumes

#### Extend Trial (+7 days)
- **Button**: "+7d" (amber)
- **Confirmation**: "Extend trial for {name} by 7 days?"
- **What it does**:
  - Shifts `created_at` back by 7 days (effectively adding 7 days to the 14-day window)
  - Logs audit event: `extend_trial` (extended_days: 7)
- **Result**: Days left counter resets, pipeline resumes if it was expired

#### Delete Trial Client
- **Button**: "Delete" (red)
- **Flow**:
  1. Opens confirmation modal
  2. Fetches cascade preview from `/admin/clients/{id}/delete-preview`
  3. Shows what will be deleted (users, drafts, subreddit assignments, etc.)
  4. "Confirm Delete" → `POST /admin/clients/{id}/delete`
- **Result**: Client and all associated data permanently removed

---

## 5. Trial Lifecycle

### Timeline

```
Day 0         Day 11        Day 14        Day 14+
  │              │              │              │
  ▼              ▼              ▼              ▼
Signup      "Expiring"      Expired      Data preserved
& Wizard     (3 days       Pipeline     Portal blocked
             warning)       stops        Upgrade CTA
```

### Status Logic

```python
days_elapsed = (now - client.created_at).days

if days_elapsed > 14:
    status = "expired"      # Red badge, portal blocked
elif 14 - days_elapsed <= 3:
    status = "expiring"     # Amber badge, warning state
else:
    status = "active"       # Green badge, fully functional
```

### Pipeline Gating

The trial guard (`trial_guard.py`) is checked at:
- `orchestrator.py` — full pipeline orchestration
- `ai_pipeline.py` → `score_threads` — blocks AI scoring
- `ai_pipeline.py` → `generate_comments` — blocks AI generation
- `ai_pipeline.py` → `generate_posts` — blocks post generation
- `portal.py` — blocks all POST actions in portal

Logic: if `client.plan_type == "trial"` AND `(now - created_at).days > 14` → skip/block.

### Trial Limits vs Paid Plans

| Feature | Trial | Starter | Growth | Scale |
|---------|-------|---------|--------|-------|
| Duration | 14 days | Unlimited | Unlimited | Unlimited |
| Avatars | 1 | 3 | 7 | 15 |
| Comments/month | 30 | 60 | 150 | 400 |
| Subreddits | Unlimited | 2 | 5 | Unlimited |
| Pipeline runs | 2/day | Unlimited | Unlimited | Unlimited |
| EPG rebuilds | 1/day | 1/day | 1/day | 1/day |
| Strategy | 1/week | 1/week | 1/week | 1/week |

---

## 6. Conversion Workflow (Trial → Paid)

### Current Process (Manual)

1. **Admin monitors** `/admin/trials` for "expiring" clients
2. **Admin reaches out** to client (email/call) before expiration
3. **Client agrees** to a plan
4. **Admin clicks "Upgrade"** → instant conversion to Starter plan
5. Alternatively: manually edit client via `/admin/clients/{id}` to set any plan_type (starter/growth/scale)

### What "Upgrade" Changes

| Field | Before (Trial) | After (Starter) |
|-------|---------------|-----------------|
| `plan_type` | `"trial"` | `"starter"` |
| `max_avatars` | 1 | 3 |
| Portal access | Blocked after 14d | Always active |
| Pipeline | Skipped after 14d | Always runs |

### No Self-Service Upgrade Yet

Currently there is no Stripe billing integration. All upgrades are manual via admin panel. The upgrade flow is:
1. Client emails tzvi@gorampit.com (from expired page CTA)
2. Tzvi/Max upgrades manually in admin panel
3. Client immediately regains access

### Future: Automated Conversion (Planned)

The `trial-conversion-intelligence` spec outlines automated:
- Trial health scoring (engagement signals)
- Conversion emails (day 3, 7, 12, 14)
- Self-service Stripe checkout
- Auto-downgrade on payment failure

---

## 7. RBAC for Trial Users

### Role Assignment

Trial users are created with **`client_admin`** role, which gives them:
- ✅ Approve/reject comment drafts
- ✅ Manage subreddits and keywords
- ✅ View all client data (avatars, EPG, strategy, reports)
- ✅ Trigger pipeline/EPG/strategy from portal (rate-limited)
- ✅ Manage team (create client_manager / client_viewer users)
- ❌ Access admin panel
- ❌ See other clients' data
- ❌ Change system settings

### Client Scope Isolation

- Trial user's `User.client_id` = their trial `Client.id`
- All queries scoped to this client only
- Avatar access limited to avatars assigned to their client
- Cannot see or interact with other clients' data

### Team Management During Trial

A trial `client_admin` can:
- Invite `client_manager` users (their colleagues can help review)
- Invite `client_viewer` users (read-only observers)
- Cannot create another `client_admin`

Invited users also lose access when the trial expires (same client scope).

---

## 8. Data Preservation on Expiry

When a trial expires, **nothing is deleted**:
- ✅ Client profile (company, brand, ICP, voice)
- ✅ Keywords (high/medium/low)
- ✅ Subreddit assignments
- ✅ Landscape report
- ✅ Generated drafts (pending/approved/rejected)
- ✅ Strategy documents
- ✅ Activity events history
- ✅ User accounts (all team members)

This is intentional: when a client upgrades, everything is ready to resume immediately with zero re-onboarding.

---

## 9. Monitoring & Alerts

### For Owner/Partner (Admin Panel)

- Check `/admin/trials` daily for "expiring" clients (amber badge)
- Each trial shows onboarding progress — incomplete onboarding (Step 1-5) = low conversion probability
- Use "Extend" for promising leads who need more time
- Use "Delete" for spam signups or abandoned trials

### Key Metrics to Watch

- **Signup → Onboarding complete** rate (Step 6 reached)
- **Active usage** during trial (drafts approved, pipeline triggered)
- **Expiring → Upgrade** conversion rate
- **Days before expiry when client last logged in**

---

## 10. Common Operations

### Extend a Trial

1. Go to `/admin/trials`
2. Find the client
3. Click "+7d"
4. Confirm

The client's `created_at` shifts back 7 days, giving them 7 more days of access.

### Upgrade a Trial to Any Plan

**Quick (Starter only):**
1. `/admin/trials` → "Upgrade" button

**Custom plan:**
1. `/admin/clients/{client_id}` → Edit client
2. Change `plan_type` to desired plan (starter/growth/scale)
3. Update `max_avatars` accordingly
4. Save

### Deactivate a Trial Client

Option A: Let it expire naturally (pipeline stops, portal shows expired page)

Option B: Deactivate manually:
1. `/admin/clients/{client_id}` → Set `is_active = False`
2. All linked users immediately lose access (403 on any page)
3. All pipeline tasks skip this client

### Check if Pipeline is Running for a Trial

1. `/admin/clients/{client_id}/transparency` — check Activity Feed
2. If trial expired: no new events after expiration date
3. If trial active: events show scraping/scoring/generation activity
