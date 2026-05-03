# Architecture, Design & Flow

## System Overview

```
┌─────────────────────────────────────────────────────┐
│                    AWS Cloud                         │
│                                                     │
│  ┌──────────┐   ┌──────────┐   ┌──────────────┐   │
│  │  EC2     │   │  RDS     │   │ ElastiCache  │   │
│  │          │   │ Postgres │   │   Redis      │   │
│  │ FastAPI  │◄─►│          │   │              │   │
│  │ Celery   │◄─►│ 10 tables│   │  Job queue   │   │
│  │ Jinja2   │   │          │   │              │   │
│  └────┬─────┘   └──────────┘   └──────────────┘   │
│       │                                             │
│       │         ┌──────────┐                        │
│       └────────►│ Bedrock  │                        │
│                 │ Claude   │                        │
│                 │ Haiku    │                        │
│                 └──────────┘                        │
└─────────────────────────────────────────────────────┘
        ▲                              ▲
        │ HTTPS                        │ Reddit API
        │                              │
   ┌────┴────┐                   ┌─────┴─────┐
   │  Users  │                   │  Reddit   │
   │ (Tzvi)  │                   │   API     │
   └─────────┘                   └───────────┘
```

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Web framework | FastAPI | API + server-side rendering |
| Templates | Jinja2 + HTMX | Interactive UI without JS framework |
| CSS | Tailwind CSS | Styling |
| Database | PostgreSQL (RDS) | All persistent data |
| ORM | SQLAlchemy 2.0 + Alembic | Models + migrations |
| Auth | JWT (python-jose) | User authentication |
| Background jobs | Celery + Redis (ElastiCache) | Scraping, AI calls, scheduling |
| Reddit | PRAW | Official Reddit API client |
| AI/LLM | Amazon Bedrock (via LiteLLM) | Claude Sonnet 4 + Claude Haiku |
| Deploy | Docker on EC2 | Containerized deployment |

---

## Database Schema

### Core Tables

```
users
  id (uuid, PK)
  email (unique)
  hashed_password
  full_name
  is_active
  is_superuser
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
  is_active
  created_at

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
  last_health_check (timestamp)
  created_at

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
  created_at
```

### Operations Tables

```
ai_usage_log
  id (uuid, PK)
  client_id (FK → clients)
  operation (text)              -- 'scoring' | 'persona_select' | 'generation' | 'editing'
  model (text)                  -- 'claude-sonnet-4' | 'claude-haiku-3.5'
  input_tokens (int)
  output_tokens (int)
  cost_usd (decimal)
  duration_ms (int)
  created_at

audit_log
  id (uuid, PK)
  user_id (FK → users)
  client_id (FK → clients)
  action (text)                 -- 'approve_comment' | 'reject_comment' | 'edit_comment' | etc.
  entity_type (text)            -- 'comment_draft' | 'post_draft'
  entity_id (uuid)
  details (jsonb)
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
   │
   ▼
7. MANUAL POSTING ─────────────────────────────────────
   │ Tzvi logs into Reddit avatar account
   │ Copies approved comment
   │ Posts manually
   │ Marks as 'posted' in UI
   │ Log to audit_log
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

### Admin Pages (Max)

| Page | Purpose |
|------|---------|
| `/admin/dashboard` | AI costs, usage stats, credit remaining, forecasts |
| `/admin/clients` | Manage clients (CRUD) |
| `/admin/avatars` | Manage avatars, health status, karma tracking |
| `/admin/jobs` | Background job status, logs |

### Client Review Pages (Tzvi / client team)

| Page | Purpose |
|------|---------|
| `/review/comments` | Review queue: pending comments, grouped by persona |
| `/review/posts` | Review queue: pending post drafts |
| `/review/tracking` | Published comments/posts history |
| `/review/analytics` | Basic stats: comments/day, karma trends |

### Onboarding Pages

| Page | Purpose |
|------|---------|
| `/onboard/client` | New client setup: company profile, keywords, subreddits |
| `/onboard/avatar` | New avatar setup: voice profile, hobby subs |

---

## Scheduling

| Job | Frequency | What it does |
|-----|-----------|-------------|
| `scrape_professional` | 2x daily (8am, 2pm) | Scrape professional subreddits |
| `scrape_hobby` | 1x daily (10am) | Scrape hobby subreddits |
| `score_threads` | After each scrape | Score new threads with AI |
| `generate_comments` | After scoring | Generate comments for 'engage' threads |
| `generate_hobby_comments` | After hobby scrape | Generate hobby comments |
| `generate_posts` | 2x daily (9am, 3pm) | Generate post drafts |
| `health_check_avatars` | 2x daily | Check shadowban status, update karma |

---

## Security

- All passwords hashed (bcrypt)
- JWT tokens for API auth
- HTTPS only (ACM certificate)
- Reddit avatar credentials encrypted in DB
- No client data exposed between tenants (client_id filtering on every query)
- Audit log for all human actions
- AI usage log for cost tracking
