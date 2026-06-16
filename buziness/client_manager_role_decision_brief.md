# Client Manager Role — Decision Brief

**For:** Tzvi, Jenny, Max  
**Date:** June 15, 2026  
**Purpose:** Complete picture of what a Client Manager can and cannot do in RAMP, for product decisions

---

## Role Summary

**Client Manager** — the daily operator on the client side. This is the person (like jekorn12@gmail.com) who reviews content, approves or rejects, manages keywords/subreddits, and monitors campaign performance.

They are the **human-in-the-loop** — without their daily action, nothing gets posted.

---

## Access Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    RAMP Role Hierarchy                     │
├──────────────────────────────────────────────────────────┤
│  owner (Max)       — full system, kill switches, infra    │
│  partner (Tzvi)    — all clients, onboarding, reports     │
│  avatar_manager    — avatar lifecycle, EPG, warming        │
│  qa (Jenny)        — cross-client review, read all data   │
│  ─────────── CLIENT BOUNDARY ──────────────────────────── │
│  client_admin      — team management + everything below   │
│  client_manager    — daily ops (review, keywords, subs)   │ ← THIS DOC
│  client_viewer     — read-only dashboard + reports        │
└──────────────────────────────────────────────────────────┘
```

**Scoping rule:** Client Manager sees ONLY their own company's data. Cannot access other clients. Cannot see admin panel. Cannot see internal system configuration.

---

## What Client Manager CAN Do

### Daily Operations (Review Queue)

| Action | How | Notes |
|--------|-----|-------|
| View pending drafts | Review Queue page | New drafts arrive 2×/day (08:00, 14:00 IST) |
| Approve a draft | Click "Approve" | Moves to posting queue |
| Reject (skip) a draft | Click "Skip" | AI learns from rejections |
| Edit & approve | Inline edit → Save & Approve | Edit diff is captured for AI learning |
| Mark as posted | Click "Mark as Posted" | After manual posting on Reddit |
| Filter by avatar/subreddit | Filter bar | Persistent in URL |

### Configuration (Settings — to be built)

| Action | Current Status | After Settings Rebuild |
|--------|---------------|----------------------|
| Edit company profile fields | ❌ Read-only | ✅ Editable |
| Edit worldview / problem / competitors | ❌ Read-only | ✅ Editable |
| Edit brand voice | ❌ Read-only | ✅ Editable |
| Edit ICP profiles | ❌ Read-only | ✅ Editable |
| Edit case studies | ❌ Read-only | ✅ Editable |
| Manage keywords (add/remove/priority) | ✅ Separate page exists | ✅ Also in Settings |
| Manage subreddits (add/remove) | ✅ Separate page exists | ✅ Also in Settings |
| Set brand guardrails | ❌ Not implemented | ✅ New feature |
| Submit voice/tone feedback | ❌ Not implemented | ✅ New feature |

### Monitoring (Read-Only Views)

| Page | What They See | Can Interact? |
|------|---------------|--------------|
| **Home** | Pending count, active avatars, subreddits, keywords, weekly posts | View only |
| **Avatars** | List of avatars with phase, karma tier, status | View only (no freeze/unfreeze) |
| **Avatar Detail** | Voice profile, activity history, subreddit territory | View only |
| **Subreddits** | Scan status, last result, next scheduled scan | Add/remove (see above) |
| **Keywords** | Keywords by priority + performance stats | Add/remove (see above) |
| **Strategy** | Current strategy document per avatar | View only |
| **Report** | 30/60/90 day analytics, top comments, subreddit performance | View only (no export yet) |
| **EPG (Schedule)** | Today's engagement plan per avatar, history | View only |
| **Activity Log** | Audit trail — who did what, last 30 days | View only |

---

## What Client Manager CANNOT Do

| Action | Who Can | Why Restricted |
|--------|---------|---------------|
| Create/delete avatars | client_admin, owner, partner | Avatar = expensive resource, requires proxy + warmup |
| Manage team members (invite/remove) | client_admin only | Team access is admin responsibility |
| Delete subreddits permanently | owner, partner | Deactivation is allowed, deletion is destructive |
| Change avatar credentials | owner only | Security risk, never exposed |
| Modify pipeline timing/schedule | owner only | System-level config |
| Trigger pipeline manually | client_manager ✅ (rate-limited) | Can trigger from portal (1×/hour limit) |
| Access admin panel | owner, partner, avatar_manager | Internal operations only |
| See other clients' data | owner, partner, qa | Hard data isolation |
| Modify system settings | owner only | Kill switches, intervals, etc. |
| Freeze/unfreeze avatars | owner, partner, avatar_manager | Automated + ops team |
| Override avatar phase | owner, partner, avatar_manager | System-managed progression |
| Undo an approval | Nobody (currently) | Contact account manager |

---

## Portal Pages — Complete Map

```
/clients/{id}/home        — Dashboard overview
/clients/{id}/review      — Review queue (3 tabs: pending/approved/posted)
/clients/{id}/avatars     — Avatar grid
/clients/{id}/avatars/{x} — Avatar detail (voice, activity, subreddits)
/clients/{id}/subreddits  — Subreddit management + scan status
/clients/{id}/keywords    — Keyword management + analytics
/clients/{id}/strategy    — Strategy documents per avatar
/clients/{id}/report      — Performance analytics (30/60/90 days)
/clients/{id}/epg         — Daily engagement schedule + history
/clients/{id}/activity    — Activity/audit log
/clients/{id}/settings    — Campaign profile (currently read-only → being rebuilt)
```

---

## Daily Workflow Timeline

```
08:00 IST — Morning pipeline runs (score → generate → EPG build)
08:30 IST — New drafts appear in Review Queue

CLIENT MANAGER MORNING (5-15 min):
├── Login → check badge (pending count)
├── Review pending drafts (approve / edit / skip)
├── Copy approved text → open thread → paste → post on Reddit
├── Mark as Posted in RAMP
└── Done until afternoon

14:00 IST — Afternoon pipeline runs
14:30 IST — More drafts appear

CLIENT MANAGER AFTERNOON (5-10 min):
├── Review new drafts
├── Post approved ones
└── Done for the day

WEEKLY (5 min):
├── Check Report page for trends
├── Review keyword performance
└── Adjust keywords or subreddits if needed
```

---

## AI Learning Signals (Why Edits Matter)

Every client manager action trains the AI:

| Action | Signal Strength | What AI Learns |
|--------|----------------|----------------|
| Approve unchanged | Weak positive | "This format/tone is acceptable" |
| Edit & approve | **Strong signal** | Exact diff captured → future drafts adjust |
| Reject (skip) | Moderate negative | "Don't generate content like this" |
| Voice feedback (new) | Direction signal | "Change overall tone going forward" |
| Guardrails (new) | Hard constraint | "Never mention X, never claim Y" |

**Key insight for Tzvi:** The more a client manager edits (instead of just approving/rejecting), the faster AI quality improves. 5-10 consistent edits = measurable improvement in next pipeline run.

---

## Safety Protections (Automatic)

The system prevents client managers from accidentally:

| Protection | What Happens |
|------------|--------------|
| Brand mention in Phase 1/2 | Red block banner, approve button disabled |
| Competitor attack from low-karma avatar | Block + neutral rewrite offered |
| Promotional language in early phase | Orange warning, requires second confirm |
| Thread is locked/removed | Draft auto-rejected, not shown |
| Shadowbanned avatar | "PAUSED" badge, drafts not generated |

Client managers **cannot override hard safety blocks**. They can acknowledge soft warnings.

---

## What's Missing (Decisions Needed)

### Settings Page Functionality (in progress)

| Section | Status | Decision Needed? |
|---------|--------|-----------------|
| Campaign Profile editing | Building now | No — clear requirement |
| Keywords in settings | Building now | No — exists on separate page, adding to settings |
| Subreddits in settings | Building now | No — same as above |
| Brand Guardrails | Building now | **Where to store?** New JSONB field on Client model |
| Voice Feedback | Building now | **New model** (VoiceFeedback table) |
| Notifications | Deferred | When? After 3+ clients? |
| Team management | Deferred | client_admin only — when do we implement? |
| Plan & Billing | Deferred | After Stripe integration |

### Open Questions for Decision

1. **Can client_manager edit the campaign profile (company_profile, worldview, etc.)?**
   - Current spec says yes
   - Alternative: only client_admin can edit, client_manager is read-only on profile
   - **Recommendation:** client_manager can edit (they know the brand best, they use the system daily)

2. **Subreddit removal: soft-delete (deactivate) or hard-delete?**
   - Current: client_manager can deactivate (is_active=false)
   - Existing constraint: "Delete subreddits = ❌" in KB docs
   - **Recommendation:** Keep as soft-delete (deactivate). No permanent deletion from portal.

3. **Should voice feedback actually influence generation, or just be logged?**
   - Option A: Log only — operations team manually adjusts
   - Option B: Inject into generation prompt automatically
   - **Recommendation:** Phase 1 = log + toast confirmation. Phase 2 = inject into prompt context.

4. **Brand guardrails enforcement: hard block or soft warning?**
   - "Never-associate topics" → hard block (AI rejects draft if topic detected)
   - "Restricted claims" → soft warning (orange badge, requires second click)
   - "Style inspiration" → prompt context only (no enforcement)
   - **Recommendation:** Start with prompt context only. Add enforcement after validation.

5. **Notifications section: when to build?**
   - Currently no email/Slack integration exists
   - Growth plan doesn't exist yet (all clients are pilot)
   - **Recommendation:** Defer until 5+ active clients

---

## Metrics to Track (Client Manager Engagement)

| Metric | What It Tells Us | Alert Threshold |
|--------|-----------------|-----------------|
| Days since last login | Client disengaging | > 3 days |
| Approval rate (approved/total) | AI quality improving | < 40% = bad AI, > 90% = rubber stamp |
| Edit rate (edited/approved) | Client cares about quality | 0% = concern (no feedback signal) |
| Avg review latency | How fast they respond | > 24h = drafts going stale |
| Drafts in queue | Overwhelmed or ignoring | > 30 pending = problem |

---

## Summary for Decision-Makers

**For Tzvi (business):**
- Client Manager is the daily touchpoint. If they stop reviewing, the campaign stalls.
- Every edit they make directly improves AI quality (self-reinforcing loop).
- The Settings rebuild gives them self-service power → fewer "please change my keywords" emails to us.
- Voice Feedback is a lightweight way to steer AI without editing every draft.

**For Jenny (QA):**
- You have cross-client review access (can approve/reject any client's drafts).
- Client Manager actions are fully audited in Activity Log.
- Safety blocks cannot be bypassed by client managers — they are technical enforcement.
- Brand guardrails (new) will add another safety layer you can verify.

**For Max (tech):**
- Settings rebuild is 4 MVP sections + profile editing = ~5 backend routes + 1 new model.
- VoiceFeedback model needed (simple: id, client_id, user_id, text, created_at).
- Brand guardrails: add JSONB field `brand_guardrails` to Client model.
- All HTMX partials pattern — same as existing admin CRUD.
- RBAC already handles viewer/manager split via `user.user_role` check.
