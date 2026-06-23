# Brief: EPG Email Task Routing — Per-Avatar Executor Assignment

## Context for AI Analyst

This brief describes a feature gap in RAMP's EPG Email Task Delivery system. The system is live and sending tasks, but routing is primitive. We need to design proper multi-tenant email routing.

---

## What RAMP Is (30-second context)

RAMP is a Reddit marketing SaaS. AI monitors subreddits, scores posts, generates comment drafts, humans approve, and then **Avatar Owners** (hired workers with Reddit accounts) manually post the approved content from their phones/browsers.

**EPG** = Electronic Program Guide. A daily publishing schedule per avatar — what to post, where, and when.

**Avatar Owner** = a person who owns one or more Reddit accounts ("avatars") and is responsible for manually posting approved content.

---

## What's Built (Current State — June 22, 2026)

### Email Task Delivery — Working MVP

When a draft is approved in the system, an email is sent with full posting instructions:
- Thread URL, subreddit, avatar username, comment text, deadline
- Unique task code + action link for accept/submit without login

### Current Routing Logic (Problem)

```
Approved EPG Slot → create_execution_task()
  → recipient = executor_contact parameter (always None currently)
  → fallback: system_setting("email_tasks_default_recipient")
  → result: ALL tasks from ALL clients go to max.breger@gmail.com
```

**There is no per-avatar or per-client email routing.** One global email receives everything.

### What Exists in the Database

| Entity | Has Email Field? | Notes |
|--------|-----------------|-------|
| Avatar | ❌ No `executor_email` | Only reddit_username, no contact info |
| User (avatar_owner role) | ✅ Has `email` | But no link Avatar→User for "who posts for this avatar" |
| Client | ✅ Has contact info | But client ≠ poster |
| AvatarAssignment model | ❌ PLANNED | Was in spec but not implemented |
| ExecutionTask | ✅ `executor_contact` | Stores resolved email per task (currently always the global one) |

### System Settings (email_tasks group)

| Key | Current Value | Purpose |
|-----|---------------|---------|
| `email_tasks_enabled` | `true` | Master toggle |
| `email_tasks_default_recipient` | `max.breger@gmail.com` | Fallback for all tasks |
| `email_tasks_max_resends` | `3` | Anti-spam |
| `email_tasks_cooldown_minutes` | `10` | Anti-spam |
| `email_tasks_deadline_hours` | `4` | Default deadline |
| `brevo_api_key` | (set) | Delivery via Brevo HTTP API |
| `smtp_from_email` | `tasks@gorampit.com` | Sender address |

---

## Business Requirements (What We Need)

### 1. Per-Avatar Email Routing

An avatar owner manages 1-5 Reddit accounts. They should receive tasks ONLY for their assigned avatars.

**Routing priority:**
1. Avatar-level `executor_email` (most specific)
2. Avatar Owner user's email (if assigned via AvatarAssignment)
3. Client-level default executor email (if client manages their own posting team)
4. System-level `email_tasks_default_recipient` (last resort fallback)

### 2. Multi-Avatar per Email

One person can own multiple avatars → one email receives tasks for multiple avatars. This is correct and expected. The email subject/body already includes avatar username so the owner knows which account to use.

### 3. Admin UI for Assignment

**Where admins configure this:**
- Avatar edit page → "Executor Email" field
- (Future) AvatarAssignment model → links Avatar to User(avatar_owner role)
- System Settings → default recipient (already exists)

### 4. Client Portal Visibility

Clients should see (read-only) who is assigned as executor for their avatars. They should NOT be able to change it (security — they shouldn't know the owner's identity beyond a display name).

---

## Technical Scope (For Engineering)

### Minimal Implementation (Phase 1)

1. Add `executor_email: Optional[str]` to Avatar model (Alembic migration)
2. Update `create_execution_task()` routing logic:
   ```
   recipient = avatar.executor_email or get_setting("email_tasks_default_recipient")
   ```
3. Add "Executor Email" field to admin avatar edit form
4. Done. Per-avatar routing works.

### Full Implementation (Phase 2 — when avatar_owner workforce scales)

1. Implement `AvatarAssignment` model (avatar_id → user_id, is_active, assigned_at)
2. Routing: `avatar.executor_email or assignment.user.email or client.default_executor_email or global_default`
3. Avatar Owner dashboard — "My Assignments" page showing their avatars
4. Admin bulk-assign UI — assign multiple avatars to one owner
5. SLA tracking per executor (response time, completion rate)

---

## Roles & Permissions

| Role | Can configure executor email? | Can see executor email? |
|------|------------------------------|------------------------|
| Owner | ✅ All avatars | ✅ |
| Partner | ✅ All avatars | ✅ |
| Client Admin | ❌ | ❌ (sees "Assigned" badge only) |
| Client Manager | ❌ | ❌ |
| Avatar Manager | ✅ Their assigned avatars | ✅ Their scope |
| Avatar Owner | ❌ (set by admin) | ✅ Own email only |

---

## Questions for Analysis

1. Should `executor_email` on Avatar be sufficient for Phase 1, or do we need the full AvatarAssignment model immediately?
2. Is the 4-level routing priority (avatar → owner → client → global) over-engineered for 50 avatars, or is it needed from day one?
3. Should we support Telegram as an alternative delivery channel now, or defer?
4. Does the client need to approve who is assigned as their avatar's executor (trust/NDA concern)?
5. How do we handle executor going on vacation / becoming unavailable? Auto-reassign to fallback?

---

## Constraints

- Python 3.11 / FastAPI / SQLAlchemy 2.0 / Alembic
- Delivery via Brevo HTTP API (DigitalOcean blocks SMTP ports)
- Current scale: ~50 avatars, 3-5 avatar owners, 10 clients
- Target scale (6 months): 200 avatars, 20-30 owners, 50 clients
- No new dependencies allowed without justification
- All emails must be in English (avatar owners are international)

---

## Reference Files

| File | What's There |
|------|-------------|
| `app/services/execution_tasks.py` | Core task creation + routing logic |
| `app/services/email_sender.py` | Brevo API + SMTP sender |
| `app/services/epg_executor.py` | Hook that triggers task creation on approval |
| `app/services/settings.py` | All email_tasks system settings definitions |
| `app/models/avatar.py` | Avatar model (no executor_email yet) |
| `app/templates/admin_tasks.html` | Admin task list UI |
| `docs/kb/guides/email-task-delivery-manual.md` | Operational manual |
