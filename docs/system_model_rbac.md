# System Model — RBAC & Data Isolation Context

## Entity Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PLATFORM LEVEL (owner, partner)                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐         ┌──────────────────────┐                          │
│  │ SystemSetting│         │     AuditLog         │                          │
│  │──────────────│         │──────────────────────│                          │
│  │ key          │         │ user_id (FK)         │                          │
│  │ value        │         │ client_id (FK, opt)  │                          │
│  │ group        │         │ action               │                          │
│  │ secret       │         │ entity_type          │                          │
│  └──────────────┘         │ details (JSONB)      │                          │
│                           └──────────────────────┘                          │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                        AIUsageLog                                     │   │
│  │  client_id (FK) │ avatar_id (FK) │ operation │ model │ cost_usd      │   │
│  │  input_tokens   │ output_tokens  │ triggered_by │ duration_ms        │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER & ACCESS LAYER                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────┐       ┌─────────────────────────┐                   │
│  │       User         │       │  User_Client_Assignment  │                   │
│  │────────────────────│       │─────────────────────────│                   │
│  │ id (UUID PK)       │──┐    │ id (UUID PK)            │                   │
│  │ email              │  │    │ user_id (FK) ───────────│──┐                │
│  │ role (String)      │  │    │ client_id (FK)          │  │                │
│  │ client_id (FK)  ───│──│──┐ │ role (String)           │  │                │
│  │ is_superuser       │  │  │ │ is_active (Bool)        │  │                │
│  │ is_active          │  │  │ │ assigned_at             │  │                │
│  └────────────────────┘  │  │ └─────────────────────────┘  │                │
│                           │  │                              │                │
│  Roles:                   │  │                              │                │
│  • owner (Max)            │  │                              │                │
│  • partner (Tzvi, Jenny)  │  │                              │                │
│  • client_admin (B2B CEO) │  │                              │                │
│  • client_manager (B2B)   │  │                              │                │
│  • client_viewer (B2B RO) │  │                              │                │
│  • b2c_user (individual)  │  │                              │                │
│                           │  │                              │                │
└───────────────────────────│──│──────────────────────────────│────────────────┘
                            │  │                              │
                            │  ▼                              │
┌───────────────────────────│─────────────────────────────────│────────────────┐
│                           │    CLIENT (TENANT) LEVEL        │                │
├───────────────────────────│─────────────────────────────────│────────────────┤
│                           │                                 │                │
│  ┌────────────────────────▼─────────────────────────────────▼──────────┐    │
│  │                          Client                                      │    │
│  │──────────────────────────────────────────────────────────────────────│    │
│  │ id (UUID PK)                                                         │    │
│  │ client_name │ brand_name │ is_active                                 │    │
│  │ company_profile │ company_worldview │ company_problem                 │    │
│  │ competitive_landscape │ brand_voice │ icp_profiles                    │    │
│  │ keywords (JSONB: {high:[], medium:[], low:[]})                       │    │
│  │ max_avatars (Int, default 3) ← NEW                                   │    │
│  │ plan_type (String, default "starter") ← NEW                          │    │
│  │ draft_approval_enabled (Bool, default false) ← NEW                   │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│       │              │              │              │                          │
│       │              │              │              │                          │
│       ▼              ▼              ▼              ▼                          │
│  ┌─────────┐  ┌───────────┐  ┌──────────┐  ┌──────────────┐               │
│  │ Avatars │  │ Subreddit │  │ Threads  │  │ ActivityEvent│               │
│  │ (owned) │  │Assignments│  │          │  │              │               │
│  └────┬────┘  └───────────┘  └──────────┘  └──────────────┘               │
│       │                                                                      │
│       ▼                                                                      │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    CONTENT PIPELINE                                    │   │
│  │                                                                        │   │
│  │  CommentDraft ──→ EditRecord ──→ CorrectionPattern                    │   │
│  │       │                                                                │   │
│  │       ▼                                                                │   │
│  │  ThreadScore (per-client scoring of shared threads)                    │   │
│  │                                                                        │   │
│  │  StrategyDocument (per-avatar, versioned, approval workflow)           │   │
│  │                                                                        │   │
│  │  PostDraft (post generation, same status workflow)                     │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│                         AVATAR FARM (Platform-owned)                           │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │                          Avatar                                       │    │
│  │──────────────────────────────────────────────────────────────────────│    │
│  │ id (UUID PK)                                                          │    │
│  │ client_ids (ARRAY[String]) ← which clients OWN this avatar            │    │
│  │ reddit_username │ voice_profile_md │ tone_principles                   │    │
│  │ warming_phase (0=Mentor, 1-3=Active)                                  │    │
│  │ is_frozen │ freeze_reason │ health_status                             │    │
│  │ karma_post │ karma_comment │ cqs_level                                │    │
│  │ is_farm_avatar (Bool) ← NEW: platform-owned, rentable                 │    │
│  │ rent_price (Numeric) ← NEW: monthly rental price                      │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│       │                                                                       │
│       │  ┌─────────────────────────────────────┐                             │
│       └──│         Avatar_Rental (NEW)          │                             │
│          │─────────────────────────────────────│                             │
│          │ id (UUID PK)                         │                             │
│          │ avatar_id (FK) ← farm avatar         │                             │
│          │ client_id (FK) ← renting client      │                             │
│          │ is_active (Bool)                      │                             │
│          │ rented_at (DateTime)                  │                             │
│          │ expires_at (DateTime, nullable)       │                             │
│          │ price (Numeric, nullable)             │                             │
│          └─────────────────────────────────────┘                             │
│                                                                               │
│  Farm avatars are pre-warmed (high karma, aged accounts).                     │
│  Clients rent them for a fee. Rental grants access to USE the avatar          │
│  for comment generation, but the avatar remains platform property.            │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│                         SHARED RESOURCES (no client_id)                        │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐     │
│  │    Subreddit      │     │   ScrapeLog      │     │  HobbySubreddit  │     │
│  │──────────────────│     │──────────────────│     │──────────────────│     │
│  │ id (UUID PK)      │     │ subreddit_id     │     │ avatar_id (FK)   │     │
│  │ subreddit_name    │     │ posts_found      │     │ subreddit_name   │     │
│  │ last_scraped_at   │     │ posts_new        │     │ type             │     │
│  │ is_active         │     │ duration_ms      │     └──────────────────┘     │
│  └──────────────────┘     │ scraped_at       │                               │
│                            └──────────────────┘                               │
│                                                                               │
│  These are NOT tenant-owned. Subreddits are shared across clients.            │
│  ScrapeLog tracks scraping metrics per subreddit (no client_id).              │
│  HobbySubreddit is per-avatar (avatar warming, not client-scoped).            │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Role → Resource Access Matrix

```
┌─────────────────────┬────────┬─────────┬────────────┬──────────────┬─────────────┬──────────┐
│ Resource            │ owner  │ partner │ client_    │ client_      │ client_     │ b2c_user │
│                     │        │         │ admin      │ manager      │ viewer      │          │
├─────────────────────┼────────┼─────────┼────────────┼──────────────┼─────────────┼──────────┤
│ System Settings     │ ✅ RW  │ ❌      │ ❌         │ ❌           │ ❌          │ ❌       │
│ Kill Switches       │ ✅ RW  │ ❌      │ ❌         │ ❌           │ ❌          │ ❌       │
│ Pipeline Triggers   │ ✅     │ ✅      │ ❌         │ ❌           │ ❌          │ ❌       │
│ User Management     │ ✅ all │ ✅ all  │ ✅ own co  │ ❌           │ ❌          │ ❌       │
│ AI Cost Analytics   │ ✅ all │ ✅ all  │ ✅ own     │ ✅ own       │ ✅ own (RO) │ ❌       │
│ Audit Logs          │ ✅ all │ ✅ all  │ ❌         │ ❌           │ ❌          │ ❌       │
├─────────────────────┼────────┼─────────┼────────────┼──────────────┼─────────────┼──────────┤
│ Client Data         │ ✅ all │ ✅ all  │ ✅ own     │ ✅ own (RO)  │ ✅ own (RO) │ ❌       │
│ Client Settings     │ ✅ all │ ✅ all  │ ✅ own     │ ❌           │ ❌          │ ❌       │
├─────────────────────┼────────┼─────────┼────────────┼──────────────┼─────────────┼──────────┤
│ Avatars (owned)     │ ✅ all │ ✅ all  │ ✅ CRUD    │ ✅ RU        │ ✅ R        │ ✅ own 1 │
│ Avatars (rented)    │ ✅ all │ ✅ all  │ ✅ R+use   │ ✅ R+use     │ ✅ R        │ ❌       │
│ Avatar Farm Mgmt    │ ✅     │ ✅      │ ❌         │ ❌           │ ❌          │ ❌       │
│ Avatar Delete       │ ✅     │ ✅      │ ✅ own     │ ❌           │ ❌          │ ❌       │
│ Avatar Create       │ ✅     │ ✅      │ ✅ (limit) │ ❌           │ ❌          │ ❌       │
├─────────────────────┼────────┼─────────┼────────────┼──────────────┼─────────────┼──────────┤
│ Subreddits          │ ✅ all │ ✅ all  │ ✅ own     │ ✅ own       │ ✅ own (RO) │ ❌       │
│ Threads             │ ✅ all │ ✅ all  │ ✅ own     │ ✅ own       │ ✅ own (RO) │ ❌       │
│ Thread Scores       │ ✅ all │ ✅ all  │ ✅ own     │ ✅ own       │ ✅ own (RO) │ ❌       │
├─────────────────────┼────────┼─────────┼────────────┼──────────────┼─────────────┼──────────┤
│ Comment Drafts      │ ✅ all │ ✅ all  │ ✅ CRUD    │ ✅ R+approve │ ✅ R (*)    │ ✅ own   │
│ Post Drafts         │ ✅ all │ ✅ all  │ ✅ CRUD    │ ✅ R+approve │ ✅ R (*)    │ ❌       │
│ Draft Approve/Rej   │ ✅     │ ✅      │ ✅         │ ✅           │ (*) flag    │ ✅ own   │
├─────────────────────┼────────┼─────────┼────────────┼──────────────┼─────────────┼──────────┤
│ Activity Feed       │ ✅ all │ ✅ all  │ ✅ own     │ ✅ own       │ ✅ own (RO) │ ✅ own   │
│ Reports             │ ✅ all │ ✅ all  │ ✅ own     │ ✅ own       │ ✅ own (RO) │ ✅ own   │
├─────────────────────┼────────┼─────────┼────────────┼──────────────┼─────────────┼──────────┤
│ Strategy Documents  │ ✅ all │ ✅ all  │ ✅ own     │ ✅ own (RO)  │ ❌          │ ❌       │
│ Learning Data       │ ✅ all │ ✅ all  │ ❌         │ ❌           │ ❌          │ ❌       │
│ Correction Patterns │ ✅ all │ ✅ all  │ ❌         │ ❌           │ ❌          │ ❌       │
├─────────────────────┼────────┼─────────┼────────────┼──────────────┼─────────────┼──────────┤
│ Admin Panel         │ ✅     │ ✅      │ ❌         │ ❌           │ ❌          │ ❌       │
│ Client Hub          │ ✅ all │ ✅ all  │ ✅ own     │ ✅ own       │ ✅ own      │ ✅ own   │
└─────────────────────┴────────┴─────────┴────────────┴──────────────┴─────────────┴──────────┘

(*) client_viewer can approve/reject ONLY if client.draft_approval_enabled = true
```

---

## Data Flow — Who Sees What

```
                    ┌─────────────────────────────────────────┐
                    │           PLATFORM ADMIN VIEW            │
                    │         (owner + partner only)           │
                    ├─────────────────────────────────────────┤
                    │                                          │
                    │  /admin/ ─── Dashboard (all clients)     │
                    │  /admin/clients ─── All clients list     │
                    │  /admin/avatars ─── All avatars          │
                    │  /admin/billing ─── AI costs (all)       │
                    │  /admin/audit-logs ─── All audit events  │
                    │  /admin/settings ─── System config       │ ← owner ONLY
                    │  /admin/users ─── All users              │
                    │  /admin/scrape-queue ─── Queue status    │
                    │                                          │
                    └─────────────────────────────────────────┘

                    ┌─────────────────────────────────────────┐
                    │           B2B CLIENT VIEW                 │
                    │   (client_admin, client_manager,          │
                    │    client_viewer)                         │
                    ├─────────────────────────────────────────┤
                    │                                          │
                    │  /clients/{id} ─── Client Hub            │
                    │    ├── Overview (metrics, profile)       │
                    │    ├── Subreddits (own assignments)      │
                    │    ├── Avatars (owned + rented)          │
                    │    ├── Threads (own client_id only)      │
                    │    ├── Review (own drafts only)          │
                    │    └── Reports (own AI costs, stats)     │
                    │                                          │
                    │  /review ─── Review queue (own only)     │
                    │                                          │
                    │  client_admin ALSO sees:                 │
                    │    /clients/{id}/users ─── Team mgmt     │
                    │    /clients/{id}/settings ─── Config     │
                    │                                          │
                    └─────────────────────────────────────────┘

                    ┌─────────────────────────────────────────┐
                    │           B2C USER VIEW                   │
                    │         (b2c_user only)                   │
                    ├─────────────────────────────────────────┤
                    │                                          │
                    │  /my ─── Personal Dashboard              │
                    │    ├── My Avatar (1 only)                │
                    │    ├── My Drafts (pending/approved)      │
                    │    ├── Activity (own avatar only)        │
                    │    └── Reports (own stats)               │
                    │                                          │
                    │  Cannot create second avatar             │
                    │  Cannot see other users/clients          │
                    │                                          │
                    └─────────────────────────────────────────┘
```

---

## Financial Model — What's Implemented vs. Planned

### Implemented (in code today)

| Component | Status | Where |
|-----------|--------|-------|
| AI cost tracking per operation | ✅ Done | `AIUsageLog` model, logged on every LLM call |
| AI cost per client | ✅ Done | `AIUsageLog.client_id` FK, `get_ai_costs_by_client()` |
| AI cost per avatar | ✅ Done | `AIUsageLog.avatar_id` FK |
| AI cost per operation type | ✅ Done | `AIUsageLog.operation` (scoring/generation/editing/etc) |
| Monthly budget setting | ✅ Done | `SystemSetting: monthly_budget_usd` (global, not per-client) |
| Admin billing page | ✅ Done | `/admin/billing` — shows AI costs summary + budget |
| Admin AI usage API | ✅ Done | `/api/admin/stats`, `/api/admin/ai-usage` |
| Daily comment limits | ✅ Done | `MAX_COMMENTS_PER_DAY = 8` per avatar (hardcoded) |
| Per-subreddit daily limit | ✅ Done | `MAX_COMMENTS_PER_SUBREDDIT_DAY = 2` (hardcoded) |

### Discussed / Planned (not yet implemented)

| Component | Status | Notes |
|-----------|--------|-------|
| Per-client monthly budget | 📋 Planned | Currently global only |
| Plan action limits | 📋 Planned | `max_comments_per_month` per plan tier |
| Budget engine (smart daily limits) | 📋 Planned | Replace hardcoded MAX_COMMENTS_PER_DAY |
| Avatar rental pricing | 📋 NEW | `avatar_rentals.price` + `avatars.rent_price` |
| Plan types (Seed/Starter/Growth/Scale) | 📋 Planned | `clients.plan_type` column |
| Max avatars per plan | 📋 NEW | `clients.max_avatars` column |
| Real billing/payments | ❌ Deferred | No Stripe/payment integration |
| Invoice generation | ❌ Deferred | Manual invoicing for now |

### Pricing Tiers (from Business Brief)

| Plan | Price/mo | Avatars | Subreddits | Comments/mo |
|------|----------|---------|------------|-------------|
| Seed | $149 | 1 | 1 | 30 |
| Starter | $399 | 3 | 2 pro + hobbies | 60 |
| Growth | $799 | 7 | 5 pro + hobbies | 150 + 10 posts |
| Scale | $1,499 | 15 | unlimited | 400 actions |
| Agency | Custom | multi-client | unlimited | custom |

### What Client Sees (Reports tab)

Currently implemented in `_tab_reports()`:
- Drafts by status (pending/approved/rejected/posted counts)
- Total AI cost for their client
- Threads by tag (engage/monitor/skip counts)
- Active avatars count

---

## Tenant Isolation — Entity Classification

### Strictly Tenant-Owned (MUST be scoped by client_id)

| Entity | client_id location | Notes |
|--------|-------------------|-------|
| Client | IS the tenant | Self-referential |
| CommentDraft | `client_id` FK | Direct |
| PostDraft | `client_id` FK | Direct |
| RedditThread | `client_id` FK | Per-client scoring creates per-client threads |
| ThreadScore | `client_id` FK | Same thread scored differently per client |
| ActivityEvent | `client_id` FK | Pipeline events per client |
| EditRecord | `client_id` FK | Learning data per client |
| CorrectionPattern | `client_id` FK | Learned patterns per client |
| ClientSubredditAssignment | `client_id` FK | Which subs a client monitors |
| ClientSubreddit (legacy) | `client_id` FK | Old model, still in use |

### Indirectly Tenant-Owned (scoped via avatar → client relationship)

| Entity | Scoping mechanism | Notes |
|--------|-------------------|-------|
| Avatar | `client_ids` ARRAY contains client_id | Multi-client possible |
| StrategyDocument | `avatar_id` FK → avatar.client_ids | Per-avatar strategy |
| AvatarSubredditPresence | `avatar_id` FK → avatar.client_ids | Per-avatar presence |
| SubredditKarma | `avatar_id` FK → avatar.client_ids | Per-avatar karma |
| AvatarProfileSnapshot | `avatar_id` FK → avatar.client_ids | Per-avatar analytics |
| HealthStatus | `avatar_id` FK → avatar.client_ids | Per-avatar health |

### Shared (NO client scoping needed)

| Entity | Why shared | Notes |
|--------|-----------|-------|
| Subreddit | One subreddit serves many clients | Shared registry |
| ScrapeLog | Scraping is subreddit-centric | No client_id |
| HobbySubreddit | Per-avatar warming | Scoped by avatar, not client |
| SystemSetting | Platform-wide config | owner-only access |

### Platform-Level (visible only to owner/partner)

| Entity | Why platform-level | Notes |
|--------|-------------------|-------|
| AuditLog | Cross-client security audit | Has optional client_id |
| AIUsageLog | Cost tracking (platform pays) | Has client_id for attribution |
| User | User management | Platform manages all users |

---

## Avatar Ownership Model

```
Avatar.client_ids = ["uuid-client-A", "uuid-client-B"]
                         │                    │
                         ▼                    ▼
                    Client A sees        Client B sees
                    this avatar          this avatar

Avatar.is_farm_avatar = true
Avatar.rent_price = 499.00
                         │
                         ▼
              ┌─────────────────────┐
              │   Avatar_Rental     │
              │─────────────────────│
              │ avatar_id = this    │
              │ client_id = C       │──→ Client C can USE this avatar
              │ is_active = true    │    (generation, review)
              │ expires_at = ...    │    but does NOT own it
              └─────────────────────┘

Client sees avatars from TWO sources:
1. OWNED: Avatar.client_ids contains their client_id
2. RENTED: avatar_rentals WHERE client_id = theirs AND is_active AND not expired
```

---

## LLM Context Assembly — Isolation Boundaries

```
generate_comment(db, thread, client, avatar, persona_selection)
    │
    ├── ASSERT: avatar.client_ids contains client.id  ← EXISTING
    │
    ├── Load StrategyDocument WHERE avatar_id = avatar.id
    │   └── ASSERT: avatar belongs to this client     ← EXISTING
    │
    ├── Load EditRecords WHERE avatar_id AND client_id = client.id
    │   └── FILTER: only records matching THIS client  ← EXISTING
    │
    ├── Load CorrectionPatterns WHERE avatar_id AND client_id = client.id
    │   └── FILTER: only patterns for THIS client      ← EXISTING
    │
    ├── Load few-shot examples WHERE client_id = client.id
    │   └── FILTER: CommentDraft.client_id match       ← EXISTING
    │
    └── NEW (for rented avatars):
        ├── Rented avatar may have StrategyDocument from platform setup
        │   └── INCLUDE: strategy if avatar is rented by this client
        ├── Rented avatar may have EditRecords from THIS client's usage
        │   └── INCLUDE: only THIS client's edit records
        └── Rented avatar may have EditRecords from OTHER clients
            └── EXCLUDE: never include other client's learning data
```

---

## Key Design Decisions for RBAC

1. **client_admin vs client_manager** — client_admin can manage team + delete avatars; client_manager can only use avatars and approve drafts
2. **Avatar farm** — platform owns pre-warmed avatars, rents them out; rental grants usage rights, not ownership
3. **Shared subreddits** — scraping is shared, scoring is per-client; no client scoping on Subreddit/ScrapeLog
4. **Budget is global** — per-client budget engine is planned but not implemented; current system has global `monthly_budget_usd`
5. **AI costs visible to clients** — clients can see their own AI cost in Reports tab (already implemented)
6. **No real billing** — manual invoicing, no Stripe; `plan_type` and `max_avatars` are enforcement-only fields
