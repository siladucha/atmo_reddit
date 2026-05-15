# Architecture, Design & Flow

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    DigitalOcean / AWS Cloud                          │
│                                                                     │
│  ┌──────────┐   ┌──────────┐   ┌──────────────┐                   │
│  │  EC2/DO  │   │PostgreSQL│   │    Redis     │                   │
│  │          │   │          │   │              │                   │
│  │ FastAPI  │◄─►│ 26 tables│   │  Job queue   │                   │
│  │ Celery   │◄─►│          │   │  Locks       │                   │
│  │ Jinja2   │   │          │   │              │                   │
│  └────┬─────┘   └──────────┘   └──────────────┘                   │
│       │                                                             │
│       │         ┌──────────┐                                        │
│       └────────►│ LiteLLM  │                                        │
│                 │ Claude   │                                        │
│                 │ Gemini   │                                        │
│                 └──────────┘                                        │
└───────┬─────────────────────────────────────────────────────────────┘
        │                              ▲                    ▲
        │ HTTPS                        │ Reddit API         │ FCM
        │                              │                    │
   ┌────┴────┐    ┌─────────┐   ┌─────┴─────┐    ┌───────┴───────┐
   │  Admin  │    │ Client  │   │  Reddit   │    │ Mobile App    │
   │  (Max)  │    │  Users  │   │   API     │    │ (Flutter)     │
   └─────────┘    └─────────┘   └───────────┘    │ Avatar Owners │
                                                   └───────────────┘
```

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Web framework | FastAPI | API + server-side rendering |
| Templates | Jinja2 + HTMX | Interactive UI without JS framework |
| CSS | Tailwind CSS | Styling |
| Database | PostgreSQL 16 (Docker) | All persistent data |
| ORM | SQLAlchemy 2.0 + Alembic | Models + migrations |
| Auth | JWT (python-jose) + RBAC | 6 roles, query scoping, permission guards |
| Background jobs | Celery + Redis | Scraping, AI calls, scheduling |
| Reddit | PRAW | Official Reddit API client |
| AI/LLM | LiteLLM (Gemini Flash + Claude Sonnet) | Scoring + generation |
| Mobile | Flutter (Dart) | Posting app for avatar owners |
| Push | Firebase Cloud Messaging (FCM) | Notifications to mobile app |
| Deploy | Docker Compose on DigitalOcean | Containerized deployment |

---

## Database Schema

### Core Tables

```
users
  id (uuid, PK)
  email (unique)
  hashed_password
  full_name
  role (varchar(20))             -- owner | partner | client_admin | client_manager | client_viewer | b2c_user
  client_id (FK → clients, nullable)  -- for client-scoped users
  is_active
  is_superuser                   -- legacy, maps to 'owner' role
  created_at

clients
  id (uuid, PK)
  client_name
  brand_name
  company_profile (text)        -- full company context for AI
  company_worldview (text)      -- what the company believes
  company_problem (text)        -- what problem they solve
  competitive_landscape (text)  -- competitors and positioning
  brand_voice (text)            -- tone and style guidelines
  icp_profiles (text)           -- ideal customer profiles
  keywords (jsonb)              -- scoring keywords with priorities
  max_avatars (int, default 3)  -- plan limit
  plan_type (varchar(20))       -- seed | starter | growth | scale | agency
  draft_approval_enabled (bool) -- allows client_viewer to approve drafts
  is_active
  created_at

user_client_assignments
  id (uuid, PK)
  user_id (FK → users, CASCADE)
  client_id (FK → clients, CASCADE)
  role (varchar(20))            -- mirrors user role for this client
  is_active
  created_at
  UNIQUE(user_id, client_id)

personas
  id (uuid, PK)
  client_id (FK → clients)
  persona_name
  platform ('reddit')
  voice_profile (text)          -- full voice profile markdown
  is_active
  created_at

avatars
  id (uuid, PK)
  client_ids (text[])           -- can serve multiple clients
  reddit_username
  email_address
  active
  voice_profile_md (text)       -- voice, tone, speech patterns
  tone_principles (text)
  speech_patterns (text)
  hill_i_die_on (text)          -- core belief for bullseye mode
  helpful_mode_topics (text)
  constraints (text)            -- what avatar would never do
  vocabulary_lean (text)
  hobby_subreddits (jsonb)
  karma_post (int)
  karma_comment (int)
  is_shadowbanned (bool)
  is_frozen (bool)
  freeze_reason (text)
  frozen_at (timestamp)
  warming_phase (int)           -- 0=mentor, 1-3=warming phases
  is_farm_avatar (bool)         -- available for rental
  rent_price (decimal)
  last_health_check (timestamp)
  created_at

avatar_rentals
  id (uuid, PK)
  avatar_id (FK → avatars, CASCADE)
  client_id (FK → clients, CASCADE)
  is_active (bool)
  rented_at (timestamp)
  expires_at (timestamp, nullable)
  price (decimal, nullable)
  UNIQUE(avatar_id, client_id)

avatar_assignments                -- for mobile posting app (PLANNED)
  id (uuid, PK)
  user_id (FK → users, CASCADE)
  avatar_id (FK → avatars, CASCADE)
  role (varchar(50))            -- 'owner' | 'viewer'
  assigned_at (timestamp)
  assigned_by (FK → users)
  is_active (bool)
  UNIQUE(user_id, avatar_id)

client_subreddits
  id (uuid, PK)
  client_id (FK → clients)
  subreddit_name
  type ('professional' | 'hobby')
  is_active
  created_at
```

### Pipeline Tables

```
reddit_threads
  id (uuid, PK)
  client_id (FK → clients)
  type ('professional' | 'hobby')
  reddit_native_id (unique)
  subreddit
  post_title
  post_body (text)
  comments_json (text)          -- flattened comment tree
  url
  author
  score
  ups / downs
  tag ('engage' | 'monitor' | 'skip')
  alert (bool)
  relevance / quality / strategic / composite (int)
  intent (text)
  scoring_reasoning (text)
  scraped_at (timestamp)
  created_at

comment_drafts
  id (uuid, PK)
  thread_id (FK → reddit_threads)
  client_id (FK → clients)
  avatar_id (FK → avatars)
  type ('professional' | 'hobby')
  ai_draft (text)               -- raw AI output
  edited_draft (text)           -- human-edited version
  comment_to (text)             -- who/what we reply to
  location_depth (int)
  location_reasoning (text)
  comment_approach (text)
  strategic_angle (text)
  engagement_mode (text)        -- bullseye | helpful_peer | karma_only
  status ('pending' | 'approved' | 'rejected' | 'posted')
  posted_at (timestamp)
  posted_by (FK → users)        -- who confirmed posting (mobile app)
  posted_source (varchar(20))   -- 'web' | 'mobile_app'
  posting_speed_seconds (int)   -- seconds from approved to posted
  created_at

post_drafts
  id (uuid, PK)
  client_id (FK → clients)
  avatar_id (FK → avatars)
  subreddit
  ai_title (text)
  ai_body (text)
  edited_title (text)
  edited_body (text)
  brief (text)                  -- generation brief/strategy
  status ('pending' | 'approved' | 'rejected' | 'posted')
  source_url (text)
  posted_at (timestamp)
  posted_by (FK → users)        -- who confirmed posting (mobile app)
  posted_source (varchar(20))   -- 'web' | 'mobile_app'
  posting_speed_seconds (int)   -- seconds from approved to posted
  created_at
```

### Operations Tables

```
ai_usage_log
  id (uuid, PK)
  client_id (FK → clients)
  operation (text)              -- 'scoring' | 'persona_select' | 'generation' | 'editing'
  model (text)                  -- 'claude-sonnet-4' | 'gemini-2.5-flash-lite'
  input_tokens (int)
  output_tokens (int)
  cost_usd (decimal)
  duration_ms (int)
  created_at

audit_log
  id (uuid, PK)
  user_id (FK → users)
  client_id (FK → clients)
  action (text)                 -- 'approve_comment' | 'reject_comment' | 'edit_comment' | 'confirm_posted' | etc.
  entity_type (text)            -- 'comment_draft' | 'post_draft'
  entity_id (uuid)
  details (jsonb)               -- includes source='mobile_app' for mobile actions
  created_at

device_registrations            -- for mobile push notifications (PLANNED)
  id (uuid, PK)
  user_id (FK → users, CASCADE)
  fcm_token (varchar(500), UNIQUE)
  device_type (varchar(20))     -- 'ios' | 'android'
  device_name (varchar(255))
  is_active (bool)
  registered_at (timestamp)
  last_seen_at (timestamp)

posting_events                  -- mobile posting analytics (PLANNED)
  id (uuid, PK)
  draft_id (uuid)
  draft_type (varchar(20))      -- 'comment' | 'post'
  user_id (FK → users)
  avatar_id (FK → avatars)
  action (varchar(50))          -- 'tap_post' | 'confirm_posted' | 'skip' | 'reminder_sent'
  device_type (varchar(20))
  ip_address (varchar(45))
  created_at
```

---

## Data Flow

### Flow 1: Professional Comments (main pipeline)

```
[Scheduled Job - 1-2x daily]
        │
        ▼
1. SCRAPE ─────────────────────────────────────────────
   │ For each client:
   │   For each client_subreddit (type=professional):
   │     PRAW → fetch hot/new posts (last 24h)
   │     Deduplicate (by reddit_native_id)
   │     Save to reddit_threads (tag=null)
   │
   ▼
2. SCORE ──────────────────────────────────────────────
   │ For each unscored thread:
   │   Send to Claude Haiku (Bedrock):
   │     - Thread content
   │     - Client company profile + keywords
   │   Receive: relevance, quality, strategic, composite, tag, alert
   │   Update reddit_threads with scores
   │   Log to ai_usage_log
   │
   ▼
3. SELECT PERSONA ─────────────────────────────────────
   │ For each thread where tag='engage':
   │   Send to Claude Sonnet (Bedrock):
   │     - Thread content
   │     - All active avatars for this client
   │     - Client company profile
   │   Receive: avatar_id, engagement_mode, thread_angle
   │   Log to ai_usage_log
   │
   ▼
4. GENERATE COMMENT ───────────────────────────────────
   │ For each selected thread+avatar:
   │   Send to Claude Sonnet (Bedrock):
   │     - Thread content
   │     - Avatar voice profile
   │     - Client company profile + ICP
   │     - Last 20 comments (diversity check)
   │     - Reddit engagement guide
   │   Receive: comment, location, approach, strategic_angle
   │   Log to ai_usage_log
   │
   ▼
5. EDIT / QUALITY CHECK ───────────────────────────────
   │ For each generated comment:
   │   Send to Claude Sonnet (Bedrock):
   │     - Draft comment
   │     - Original thread
   │     - Forbidden patterns
   │   Receive: cleaned comment
   │   Save to comment_drafts (status='pending')
   │   Log to ai_usage_log
   │
   ▼
6. HUMAN REVIEW (UI) ─────────────────────────────────
   │ Tzvi opens review UI:
   │   Sees pending comments grouped by persona
   │   For each: original post, AI comment, metadata
   │   Actions: Approve / Edit / Reject / Redraft
   │   On approve: status → 'approved'
   │   Log to audit_log
   │   Push notification sent to avatar owner's mobile app
   │
   ▼
7. MOBILE POSTING (Flutter App) ───────────────────────
   │ Avatar owner receives push notification
   │ Opens app → sees approved drafts queue
   │ Taps "Post":
   │   - Comment text copied to clipboard
   │   - Reddit thread opens in browser
   │   - Owner pastes comment, submits on Reddit
   │ Returns to app → confirms "Posted"
   │ Status → 'posted', posted_at = now()
   │ Log to audit_log (source='mobile_app')
   │ Log to posting_events (speed tracking)
```

### Flow 2: Hobby Karma Building

```
[Scheduled Job - daily]
        │
        ▼
1. For each active avatar:
     Get hobby_subreddits from avatar profile
     Scrape hot posts from each hobby sub
     Save to reddit_threads (type='hobby')
        │
        ▼
2. Generate hobby comments:
     Simpler prompt (no company worldview)
     Focus on being helpful/funny/authentic
     Use Claude Haiku (cheaper)
     Save to comment_drafts (type='hobby')
        │
        ▼
3. Human review + manual posting (same as Flow 1)
```

### Flow 3: Post Creation

```
[Scheduled Job - 2x daily or manual trigger]
        │
        ▼
1. Find source material:
     High-scoring threads from reddit_threads
     OR external news/content (future: knowledge lake)
        │
        ▼
2. Generate brief:
     Claude Sonnet analyzes source
     Creates post strategy (type, angle, persona fit)
        │
        ▼
3. Generate post:
     Claude Sonnet writes title + body
     In selected avatar's voice
     Save to post_drafts (status='pending')
        │
        ▼
4. Human review + manual posting
```

---

## UI Pages

### Admin Pages (Max — `owner` role)

| Page | Purpose |
|------|---------|
| `/admin/dashboard` | AI costs, usage stats, credit remaining, forecasts |
| `/admin/clients` | Manage clients (CRUD) |
| `/admin/avatars` | Manage avatars, health status, karma tracking |
| `/admin/posting-team` | Avatar owner stats, posting speed, compliance |
| `/admin/jobs` | Background job status, logs |

### Client Review Pages (Tzvi / client team — `partner`/`client_admin`/`client_manager`)

| Page | Purpose |
|------|---------|
| `/review/comments` | Review queue: pending comments, grouped by persona |
| `/review/posts` | Review queue: pending post drafts |
| `/review/tracking` | Published comments/posts history |
| `/review/analytics` | Basic stats: comments/day, karma trends |

### Mobile App (Avatar Owners — Flutter)

| Screen | Purpose |
|--------|---------|
| Login | Email + password, biometric re-login |
| Queue | Approved drafts per avatar (tabs), pull-to-refresh |
| Detail | Full comment text, thread context, "Post" button |
| Confirm | "Did you post?" dialog after returning from Reddit |
| Stats | Posted today/week, streak, avg speed |

### Onboarding Pages

| Page | Purpose |
|------|---------|
| `/onboard/client` | New client setup: company profile, keywords, subreddits |
| `/onboard/avatar` | New avatar setup: voice profile, hobby subs |

---

## Scheduling

Implemented via Celery Beat — see [`reddit_saas/app/tasks/worker.py`](../reddit_saas/app/tasks/worker.py) lines 24–41.

| Beat job | Schedule (UTC) | Task |
|----------|----------------|------|
| `scrape-and-generate-morning` | 08:00 daily | `run_full_pipeline_all_clients` |
| `scrape-and-generate-afternoon` | 14:00 daily | `run_full_pipeline_all_clients` |
| `hobby-pipeline-daily` | 10:00 daily | `run_hobby_pipeline_all_avatars` |
| `avatar-health-check` | every 12h at :30 | `check_all_avatars_health` |

Post generation is currently triggered manually via `/pipeline/*` routes (see TODO.md Task 1.3).

### Orchestrator

All Beat jobs dispatch through orchestrator tasks in [`reddit_saas/app/tasks/orchestrator.py`](../reddit_saas/app/tasks/orchestrator.py). Each orchestrator queries DB for active clients/avatars and queues per-tenant Celery chains:

- **`run_full_pipeline_all_clients()`** — for each active `Client`, queues a chain `score_threads → generate_comments → generate_posts`
- **`run_hobby_pipeline_all_avatars()`** — for each active `Avatar` (not frozen, not shadowbanned), queues a chain `scrape_hobby_subreddits → generate_hobby_comments`
- **`check_all_avatars_health()`** — for each active avatar, runs `services.safety.get_avatar_health()`, logs warnings for high brand ratio, updates `last_health_check`

Scraping is handled separately by `queue_tick` (fires every 60s, selects next stale subreddit from shared registry).

Per-client/avatar chains run in parallel via Celery's queue; failures in one tenant don't block others.

### Client Deactivation Cascade

When a client is deactivated (`POST /admin/clients/{id}/deactivate`):

1. `client.is_active = False`
2. All `ClientSubredditAssignment` for this client → `is_active = False`
3. All legacy `ClientSubreddit` for this client → `is_active = False`
4. Client ID removed from `avatar.client_ids` for all assigned avatars

**Pipeline guards after deactivation:**
- `queue_tick`: subreddits only scraped if at least one active client has an active assignment (shared subreddit registry)
- `run_full_pipeline_all_clients`: only queries `Client.is_active == True`
- `score_threads` / `generate_comments` / `generate_posts` / `scrape_professional_subreddits`: each checks `client.is_active` before processing
- Avatar filtering: since client ID is removed from `client_ids`, no avatars match for that client
- Hobby pipeline: avatars with empty `client_ids` still run hobby karma building (by design — avatars are reusable assets)

---

## Middleware

Two middleware layers in [`reddit_saas/app/middleware/`](../reddit_saas/app/middleware/):

- **`auth.py`** — JWT cookie auth check on every request. Bypasses: `/login`, `/register`, `/logout`, `/health`, `/docs`, `/auth/*`, `/static/*`. Unauthenticated requests are redirected to `/login`.
- **`errors.py`** — Global exception handler. Catches unhandled exceptions, logs them, and returns a friendly HTML error page (instead of FastAPI's raw "Internal Server Error").

## Security

- All passwords hashed (bcrypt)
- JWT tokens stored in HttpOnly cookies (web) / secure storage (mobile)
- HTTPS only (ACM certificate, AWS deploy)
- Reddit avatar credentials encrypted in DB
- **RBAC with 6 roles** — deny-by-default permission matrix (see `docs/permission_matrix.md`)
- **Query scoping** — client-scoped users only see their own data (enforced at DB query level)
- **LLM context isolation** — runtime assertions prevent cross-client data leakage in AI prompts
- No client data exposed between tenants (`client_id` filtering on every query)
- Audit log for all human actions (includes `source='mobile_app'` for mobile)
- AI usage log for cost tracking
- Auth middleware enforces login on all protected routes
- **Mobile app security**: biometric auth, SSL pinning, no local draft persistence, 7-day token expiry
- **Avatar ownership validation**: mobile API validates avatar assignment before any action
