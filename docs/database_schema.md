# Database Schema — Reddit Marketing SaaS

_Source of truth: SQLAlchemy models in `reddit_saas/app/models/`._
_Tables are created via `Base.metadata.create_all()` (see `app/seed.py`); Alembic migration is still pending — see TODO.md Task 2.1._

All primary keys are UUIDs unless noted. All `*_id` foreign keys reference the parent's `id` column.

---

## Auth

### `users` — `app/models/user.py`
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID, PK | |
| `email` | String(255), UNIQUE, INDEX | |
| `hashed_password` | String(255) | bcrypt |
| `full_name` | String(255), nullable | |
| `role` | String(20), INDEX | `owner` \| `partner` \| `client_admin` \| `client_manager` \| `client_viewer` \| `b2c_user` |
| `client_id` | UUID, FK → `clients.id`, nullable | For client-scoped users |
| `is_active` | Boolean, default `true` | |
| `is_superuser` | Boolean, default `false` | Legacy — maps to `owner` role |
| `created_at` | timestamptz | |

### `user_client_assignments` — `app/models/user_client_assignment.py`
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID, PK | |
| `user_id` | UUID, FK → `users.id`, CASCADE | |
| `client_id` | UUID, FK → `clients.id`, CASCADE | |
| `role` | String(20) | Mirrors user role for this client |
| `is_active` | Boolean, default `true` | |
| `created_at` | timestamptz | |
| | UNIQUE(user_id, client_id) | |

---

## Tenant Configuration

### `clients` — `app/models/client.py`
One row per agency client. Stores everything the AI needs to write in their voice.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID, PK | |
| `client_name` | String(255) | |
| `brand_name` | String(255) | |
| `company_profile` | Text, nullable | |
| `company_worldview` | Text, nullable | |
| `company_problem` | Text, nullable | |
| `competitive_landscape` | Text, nullable | |
| `brand_voice` | Text, nullable | |
| `case_studies` | Text, nullable | |
| `icp_profiles` | Text, nullable | |
| `keywords` | JSONB, nullable | scoring keywords with priority |
| `max_avatars` | Integer, default `3` | Plan limit on avatar count |
| `plan_type` | String(20), default `'starter'` | seed \| starter \| growth \| scale \| agency |
| `draft_approval_enabled` | Boolean, default `false` | Allows client_viewer to approve drafts |
| `is_active` | Boolean, default `true` | |
| `created_at` | timestamptz | |

### `personas` — `app/models/persona.py`
Strategic identity layer (separate from operational `avatars`).

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID, PK | |
| `client_id` | UUID, FK → `clients.id` | |
| `persona_name` | String(255) | |
| `platform` | String(50), default `'reddit'` | |
| `voice_profile` | Text, nullable | |
| `is_active` | Boolean, default `true` | |
| `created_at` | timestamptz | |

### `client_subreddits` — `app/models/subreddit.py`
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID, PK | |
| `client_id` | UUID, FK → `clients.id` | |
| `subreddit_name` | String(255) | |
| `type` | String(50), default `'professional'` | `professional` \| `hobby` |
| `is_active` | Boolean, default `true` | |
| `created_at` | timestamptz | |

### `avatars` — `app/models/avatar.py`
Operational Reddit account layer. One row per Reddit account; one avatar can serve multiple clients.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID, PK | |
| `client_ids` | text[], nullable | array — multi-tenant |
| `reddit_username` | String(255), UNIQUE | |
| `email_address` | String(255), nullable | |
| `active` | Boolean, default `true` | |
| `voice_profile_md` | Text, nullable | |
| `tone_principles` | Text, nullable | |
| `speech_patterns` | Text, nullable | |
| `hill_i_die_on` | Text, nullable | core belief, used in bullseye mode |
| `helpful_mode_topics` | Text, nullable | |
| `constraints` | Text, nullable | what avatar would never say |
| `vocabulary_lean` | Text, nullable | |
| `hobby_subreddits` | JSONB, nullable | list/dict of hobby sub names |
| `business_subreddits` | JSONB, nullable | list/dict of business sub names |
| `karma_post` | Integer, default `0` | |
| `karma_comment` | Integer, default `0` | |
| `is_shadowbanned` | Boolean, default `false` | |
| `is_frozen` | Boolean, default `false` | |
| `freeze_reason` | Text, nullable | |
| `frozen_at` | timestamptz, nullable | |
| `warming_phase` | Integer, default `1` | 0=mentor, 1-3=warming phases |
| `is_farm_avatar` | Boolean, default `false` | Available for rental |
| `rent_price` | Numeric(10,2), nullable | |
| `last_health_check` | timestamptz, nullable | |
| `created_at` | timestamptz | |

### `avatar_rentals` — `app/models/avatar_rental.py`
Farm avatar rentals — clients can rent pre-warmed avatars.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID, PK | |
| `avatar_id` | UUID, FK → `avatars.id`, CASCADE | |
| `client_id` | UUID, FK → `clients.id`, CASCADE | |
| `is_active` | Boolean, default `true` | |
| `rented_at` | timestamptz | |
| `expires_at` | timestamptz, nullable | null = no expiry |
| `price` | Numeric(10,2), nullable | |
| | UNIQUE(avatar_id, client_id) | |

### `avatar_assignments` — `app/models/avatar_assignment.py` [PLANNED]
Links avatar owners (users) to avatars they manage for mobile posting.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID, PK | |
| `user_id` | UUID, FK → `users.id`, CASCADE | |
| `avatar_id` | UUID, FK → `avatars.id`, CASCADE | |
| `role` | String(50), default `'owner'` | `owner` \| `viewer` |
| `assigned_at` | timestamptz | |
| `assigned_by` | UUID, FK → `users.id`, nullable | Admin who made assignment |
| `is_active` | Boolean, default `true` | |
| | UNIQUE(user_id, avatar_id) | |

---

## Pipeline Tables

### `reddit_threads` — `app/models/thread.py`
Scraped Reddit posts. Used by both professional and hobby pipelines.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID, PK | |
| `client_id` | UUID, FK → `clients.id` | |
| `type` | String(50), default `'professional'` | `professional` \| `hobby` |
| `reddit_native_id` | String(255), UNIQUE | dedup key |
| `subreddit` | String(255) | |
| `post_title` | Text | |
| `post_body` | Text, nullable | |
| `comments_json` | Text, nullable | flattened comment tree |
| `url` | Text, nullable | |
| `author` | String(255), nullable | |
| `score` / `ups` / `downs` | Integer, default `0` | |
| `tag` | String(50), nullable | `engage` \| `monitor` \| `skip` |
| `alert` | Boolean, default `false` | |
| `relevance` / `quality` / `strategic` / `composite` | Integer, nullable | AI scores |
| `intent` | String(100), nullable | |
| `scoring_reasoning` | Text, nullable | |
| `scraped_at` | timestamptz | |
| `created_at` | timestamptz | |

### `comment_drafts` — `app/models/comment_draft.py`
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID, PK | |
| `thread_id` | UUID, FK → `reddit_threads.id` | |
| `client_id` | UUID, FK → `clients.id` | |
| `avatar_id` | UUID, FK → `avatars.id` | |
| `type` | String(50), default `'professional'` | |
| `ai_draft` | Text, nullable | raw AI output |
| `edited_draft` | Text, nullable | human-edited version |
| `comment_to` | Text, nullable | who/what we reply to |
| `location_depth` | Integer, nullable | depth in comment tree |
| `location_reasoning` | Text, nullable | |
| `comment_approach` | String(100), nullable | |
| `strategic_angle` | String(100), nullable | |
| `engagement_mode` | String(100), nullable | `bullseye` \| `helpful_peer` \| `karma_only` |
| `status` | String(50), default `'pending'` | `pending` \| `approved` \| `rejected` \| `posted` |
| `posted_at` | timestamptz, nullable | |
| `posted_by` | UUID, FK → `users.id`, nullable | Who confirmed posting (mobile app) |
| `posted_source` | String(20), nullable | `web` \| `mobile_app` |
| `posting_speed_seconds` | Integer, nullable | Seconds from approved to posted |
| `created_at` | timestamptz | |

### `post_drafts` — `app/models/post_draft.py`
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID, PK | |
| `client_id` | UUID, FK → `clients.id` | |
| `avatar_id` | UUID, FK → `avatars.id` | |
| `subreddit` | String(255) | |
| `ai_title` / `ai_body` | Text, nullable | raw AI output |
| `edited_title` / `edited_body` | Text, nullable | human-edited |
| `brief` | Text, nullable | generation brief/strategy |
| `source_url` | Text, nullable | |
| `status` | String(50), default `'pending'` | `pending` \| `approved` \| `rejected` \| `posted` |
| `posted_at` | timestamptz, nullable | |
| `posted_by` | UUID, FK → `users.id`, nullable | Who confirmed posting (mobile app) |
| `posted_source` | String(20), nullable | `web` \| `mobile_app` |
| `posting_speed_seconds` | Integer, nullable | Seconds from approved to posted |
| `created_at` | timestamptz | |

### `hobby_subreddits` — `app/models/hobby.py`
Storage for hobby pipeline scrapes + their AI-generated comments. (Distinct from `client_subreddits` which lists which subs to monitor.)

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID, PK | |
| `subreddit` | String(255) | |
| `post_id` | String(255), nullable | |
| `post_title` / `post_body` / `comments` | Text, nullable | |
| `url` / `permalink` | Text, nullable | |
| `author` / `avatar_username` | String(255), nullable | |
| `post_image` | JSONB, nullable | |
| `post_ups` / `post_downs` | Integer, default `0` | |
| `ai_comment` | Text, nullable | |
| `status` | String(50), nullable | |
| `scraped_at` | timestamptz | |
| `created_at` | timestamptz | |

---

## Operations / Audit

### `ai_usage_log` — `app/models/ai_usage.py`
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID, PK | |
| `client_id` | UUID, FK → `clients.id`, nullable | |
| `operation` | String(100) | `scoring` \| `persona_select` \| `generation` \| `editing` |
| `model` | String(255) | LLM model id |
| `input_tokens` / `output_tokens` | Integer, default `0` | |
| `cost_usd` | Numeric(10, 6), default `0` | |
| `duration_ms` | Integer, default `0` | |
| `created_at` | timestamptz | |

### `audit_log` — `app/models/audit.py`
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID, PK | |
| `user_id` | UUID, FK → `users.id`, nullable | |
| `client_id` | UUID, FK → `clients.id`, nullable | |
| `action` | String(100) | `approve_comment` \| `reject_comment` \| `edit_comment` \| ... |
| `entity_type` | String(100), nullable | `comment_draft` \| `post_draft` |
| `entity_id` | UUID, nullable | |
| `details` | JSONB, nullable | |
| `created_at` | timestamptz | |

---

## Notes

- **No `news_scrape` table.** Post creation sources material directly from `reddit_threads`. The original Ori workflow had a separate scraper; we collapsed it.
- **No `parallel_job_results` table.** That was an n8n infrastructure artifact; Celery handles parallelism natively.
- **Avatar / hobby subreddits** are stored both as a JSONB list on `avatars.hobby_subreddits` (which subs an avatar follows) AND as scraped content rows in the `hobby_subreddits` table (one row per scraped post). Same name, different roles.
- **RBAC tables** (May 2026): `user_client_assignments` + `avatar_rentals` + extended columns on `users`, `clients`, `avatars`. Full permission matrix in `docs/permission_matrix.md`.
- **Mobile posting tables** (PLANNED): `avatar_assignments` + `device_registrations` + `posting_events` + new columns on `comment_drafts`/`post_drafts` (`posted_by`, `posted_source`, `posting_speed_seconds`). See `.kiro/specs/mobile-posting-app/design.md`.

## Planned Tables (Mobile Posting App)

### `device_registrations` [PLANNED]
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID, PK | |
| `user_id` | UUID, FK → `users.id`, CASCADE | |
| `fcm_token` | String(500), UNIQUE | Firebase Cloud Messaging token |
| `device_type` | String(20) | `ios` \| `android` |
| `device_name` | String(255), nullable | |
| `is_active` | Boolean, default `true` | |
| `registered_at` | timestamptz | |
| `last_seen_at` | timestamptz | |

### `posting_events` [PLANNED]
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID, PK | |
| `draft_id` | UUID | comment_draft or post_draft ID |
| `draft_type` | String(20) | `comment` \| `post` |
| `user_id` | UUID, FK → `users.id` | |
| `avatar_id` | UUID, FK → `avatars.id` | |
| `action` | String(50) | `tap_post` \| `confirm_posted` \| `skip` \| `reminder_sent` |
| `device_type` | String(20), nullable | |
| `ip_address` | String(45), nullable | |
| `created_at` | timestamptz | |
