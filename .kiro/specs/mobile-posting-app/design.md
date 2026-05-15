# Design Document — Mobile Posting App

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Mobile App (Expo/React Native)            │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │  Auth    │  │  Queue   │  │  Detail  │  │    Stats     │  │
│  │  Screen  │  │  Screen  │  │  Screen  │  │    Screen    │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘  │
│       │              │              │               │           │
│       └──────────────┴──────────────┴───────────────┘           │
│                              │                                   │
│                    ┌─────────┴─────────┐                        │
│                    │   API Client      │                        │
│                    │   (axios + JWT)   │                        │
│                    └─────────┬─────────┘                        │
└──────────────────────────────┼──────────────────────────────────┘
                               │ HTTPS
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Existing FastAPI Backend                       │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  /api/mobile/*  (new router)                               │ │
│  │                                                            │ │
│  │  GET  /queue          — approved drafts for user's avatars │ │
│  │  POST /drafts/{id}/confirm-posted                          │ │
│  │  POST /drafts/{id}/skip                                    │ │
│  │  GET  /stats          — posting stats                      │ │
│  │  POST /device         — register FCM token                 │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │ avatar_      │  │ comment_     │  │ push_notification  │    │
│  │ assignments  │  │ drafts       │  │ service (FCM)      │    │
│  │ (new table)  │  │ (existing)   │  │ (new service)      │    │
│  └──────────────┘  └──────────────┘  └────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

## Database Changes

### New Table: `avatar_assignments`

```sql
CREATE TABLE avatar_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    avatar_id UUID NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL DEFAULT 'owner',  -- 'owner' | 'viewer'
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    assigned_by UUID REFERENCES users(id),      -- admin who made the assignment
    is_active BOOLEAN NOT NULL DEFAULT true,
    UNIQUE(user_id, avatar_id)
);

CREATE INDEX idx_avatar_assignments_user ON avatar_assignments(user_id) WHERE is_active = true;
CREATE INDEX idx_avatar_assignments_avatar ON avatar_assignments(avatar_id) WHERE is_active = true;
```

### New Table: `device_registrations`

```sql
CREATE TABLE device_registrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fcm_token VARCHAR(500) NOT NULL,
    device_type VARCHAR(20) NOT NULL,  -- 'ios' | 'android'
    device_name VARCHAR(255),
    is_active BOOLEAN NOT NULL DEFAULT true,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(fcm_token)
);

CREATE INDEX idx_device_registrations_user ON device_registrations(user_id) WHERE is_active = true;
```

### New Table: `posting_events`

```sql
CREATE TABLE posting_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id UUID NOT NULL,             -- comment_draft or post_draft ID
    draft_type VARCHAR(20) NOT NULL,    -- 'comment' | 'post'
    user_id UUID NOT NULL REFERENCES users(id),
    avatar_id UUID NOT NULL REFERENCES avatars(id),
    action VARCHAR(50) NOT NULL,        -- 'tap_post' | 'confirm_posted' | 'skip' | 'reminder_sent'
    device_type VARCHAR(20),
    ip_address VARCHAR(45),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_posting_events_user ON posting_events(user_id, created_at DESC);
CREATE INDEX idx_posting_events_draft ON posting_events(draft_id);
```

### Modifications to Existing Tables

**`comment_drafts`** — add columns:
```sql
ALTER TABLE comment_drafts ADD COLUMN posted_by UUID REFERENCES users(id);
ALTER TABLE comment_drafts ADD COLUMN posted_source VARCHAR(20);  -- 'web' | 'mobile_app'
ALTER TABLE comment_drafts ADD COLUMN posting_speed_seconds INTEGER;  -- seconds from approved to posted
```

**`post_drafts`** — same additions:
```sql
ALTER TABLE post_drafts ADD COLUMN posted_by UUID REFERENCES users(id);
ALTER TABLE post_drafts ADD COLUMN posted_source VARCHAR(20);
ALTER TABLE post_drafts ADD COLUMN posting_speed_seconds INTEGER;
```

---

## API Design

### Authentication

Mobile uses the same JWT system as web, with adjustments:
- Access token: 7 days expiry (vs 24h for web)
- Refresh token: 30 days, stored in secure device storage (Keychain/Keystore)
- Login endpoint: existing `POST /auth/login` (returns JWT)
- New: `POST /auth/refresh` — exchange refresh token for new access token

### Endpoints

#### `GET /api/mobile/queue`

```json
// Request
GET /api/mobile/queue?limit=20&offset=0&avatar_id=optional-filter

// Response 200
{
  "items": [
    {
      "id": "uuid",
      "type": "comment",  // or "post"
      "avatar": {
        "id": "uuid",
        "reddit_username": "StopAutomatic717"
      },
      "subreddit": "cybersecurity",
      "thread_title": "What's the best approach to...",
      "thread_url": "https://reddit.com/r/cybersecurity/comments/abc123/...",
      "comment_text": "Full text of the approved comment...",
      "comment_to": "reply to u/SomeUser's comment about...",
      "approved_at": "2026-05-13T08:30:00Z",
      "waiting_minutes": 45
    }
  ],
  "total": 12,
  "by_avatar": {
    "StopAutomatic717": 5,
    "Flaky_Finder_13": 4,
    "HotThought2408": 3
  }
}
```

#### `POST /api/mobile/drafts/{id}/confirm-posted`

```json
// Request
POST /api/mobile/drafts/{id}/confirm-posted
{
  "draft_type": "comment",  // or "post"
  "device_type": "ios"
}

// Response 200
{
  "status": "posted",
  "posted_at": "2026-05-13T09:15:00Z",
  "posting_speed_seconds": 2700
}

// Response 403
{
  "error": "This draft does not belong to your assigned avatars"
}

// Response 409
{
  "error": "Draft already posted"
}
```

#### `POST /api/mobile/drafts/{id}/skip`

```json
// Request
POST /api/mobile/drafts/{id}/skip
{
  "draft_type": "comment",
  "reason": "optional skip reason"
}

// Response 200
{
  "status": "skipped",
  "remaining_in_queue": 11
}
```

#### `GET /api/mobile/stats`

```json
// Response 200
{
  "today": {
    "posted": 7,
    "skipped": 1,
    "pending": 4,
    "avg_speed_seconds": 1800
  },
  "week": {
    "posted": 34,
    "skipped": 3,
    "avg_speed_seconds": 2100
  },
  "streak_days": 5,
  "total_posted": 156
}
```

#### `POST /api/mobile/device`

```json
// Request
POST /api/mobile/device
{
  "fcm_token": "dGhpcyBpcyBhIHRva2Vu...",
  "device_type": "ios",
  "device_name": "iPhone 15 Pro"
}

// Response 200
{
  "registered": true
}
```

---

## Mobile App Architecture

### Tech Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Framework | Flutter (Dart) | Cross-platform, fast dev, single codebase, hot reload |
| Navigation | go_router | Declarative routing, deep links |
| State | Riverpod | Reactive, testable, no boilerplate |
| API | Dio + riverpod async | Caching, auto-refresh, interceptors |
| Push | firebase_messaging | Cross-platform push (FCM) |
| Storage | flutter_secure_storage | JWT tokens in Keychain/Keystore |
| Clipboard | Flutter services (Clipboard) | Built-in, no extra package |
| Linking | url_launcher | Open Reddit URLs |
| Auth | local_auth | Biometric (Face ID / fingerprint) |

### Development Strategy — Parallel Tracks

```
Week 1-2:  Backend (RBAC + mobile API)     |  Flutter dev (UI + mocked API)
           ─────────────────────────────    |  ──────────────────────────────
           avatar_assignments migration     |  Login screen + token storage
           /api/mobile/* endpoints          |  Queue screen (tabs, list)
           ownership validation             |  Detail screen + Post flow
           posting_team admin page          |  Confirm dialog + stats
                                            |  Uses local JSON mock server
                                            |
Day 3-4:   Integration                     |
           ─────────────────────────────────────────────────────────────
           Flutter points to real API
           E2E test: login → queue → post → confirm
           Bug fixes, edge cases
           Done ✓
```

**Contract-first approach:** Flutter dev gets the API spec (endpoints + JSON schemas from this design doc) on day 1 and builds against mocks. No blocking dependency on backend completion.

### Screen Flow

```
┌─────────┐     ┌──────────┐     ┌──────────────┐     ┌───────────┐
│  Login  │────►│  Queue   │────►│ Draft Detail │────►│  Reddit   │
│         │     │  (tabs   │     │              │     │  (browser)│
│ email + │     │  per     │     │ Full text    │     │           │
│ password│     │  avatar) │     │ + Post btn   │     │  Paste &  │
│         │     │          │     │              │     │  Submit   │
│ biometric│    │ Pull to  │     │ Copy to      │     │           │
│ re-login│     │ refresh  │     │ clipboard    │     │           │
└─────────┘     └──────────┘     └──────────────┘     └─────┬─────┘
                     ▲                                        │
                     │           ┌──────────────┐             │
                     │           │  Confirm     │◄────────────┘
                     │           │  Dialog      │   (return to app)
                     │           │              │
                     │           │ "Posted?" ✓  │
                     └───────────│  Yes / No    │
                                 └──────────────┘
```

### Key UX Decisions

1. **Clipboard + Browser (not Reddit API)** — мы НЕ используем Reddit API для постинга. Владелец сам вставляет текст в Reddit. Это ключевое юридическое отличие от автоматизации.

2. **One-tap flow:**
   - Tap "Post" → text copied + Reddit opens → paste → submit → return → confirm
   - Total time: 15-30 seconds per comment (vs 2-5 minutes manual)

3. **No local storage of drafts** — после подтверждения постинга текст удаляется из памяти приложения. Если телефон потерян/украден, нет компрометирующих данных.

4. **Avatar tabs** — если владелец управляет 3 аватарами, он видит 3 таба с очередями. Переключение одним свайпом.

5. **Offline resilience** — очередь кэшируется на 5 минут. Если нет сети при подтверждении, событие сохраняется локально и синхронизируется при восстановлении.

---

## Push Notification Architecture

### Flow

```
[CommentDraft.status → 'approved']
        │
        ▼
[Celery signal / DB trigger]
        │
        ▼
[notification_service.notify_avatar_owner(avatar_id, draft)]
        │
        ├── Find owner via avatar_assignments
        ├── Find FCM tokens via device_registrations
        ├── Batch check (5+ in 5 min → single notification)
        │
        ▼
[Firebase Admin SDK → FCM → Device]
```

### Implementation

- **Trigger:** Hook into the review approval flow (existing `routes/review.py` and `routes/pages.py`)
- **Service:** New `app/services/push_notifications.py`
- **Batching:** Redis key `push_batch:{user_id}` with 5-minute TTL, increment on each approval
- **Reminder:** Celery Beat task every 30 minutes checks for approved drafts older than 4 hours without posting

---

## Posting Flow — Deep Link Strategy

### For Comments

Reddit doesn't support pre-filled comment text via URL params. Strategy:

1. Copy text to clipboard
2. Open thread URL: `https://www.reddit.com/r/{subreddit}/comments/{thread_id}/...`
3. User navigates to the correct comment (guided by `comment_to` context shown in app)
4. User pastes and submits

### For Posts

Reddit DOES support pre-filled post submissions:

```
https://www.reddit.com/r/{subreddit}/submit?title={encoded_title}&text={encoded_body}
```

1. Copy body to clipboard (backup)
2. Open pre-filled submit URL
3. User reviews and submits

### Future Enhancement: Reddit App Intent

If Reddit mobile app is installed, use intent/universal link:
```
reddit://reddit.com/r/{subreddit}/comments/{thread_id}
```

This opens directly in the Reddit app (faster, already logged in).

---

## Admin Panel Integration

### New Page: `/admin/posting-team`

| Column | Description |
|--------|-------------|
| Owner Name | User full_name |
| Avatars | List of assigned avatar usernames |
| Posted Today | Count of confirmed posts today |
| Posted This Week | Count this week |
| Avg Speed | Average posting_speed_seconds (formatted as "Xm Ys") |
| Skip Rate | skipped / (posted + skipped) × 100% |
| Last Active | Last posting_event timestamp |
| Status | 🟢 Active / 🟡 Slow / 🔴 Inactive (>24h) |

### Avatar Detail Enhancement

On `/admin/avatars/{id}`, add a "Posting" tab:
- Assigned owner (with link to user)
- Posting history (last 20 events)
- Average posting speed for this avatar
- Queue depth (approved but not yet posted)

---

## Security Model

### Authorization Matrix

| Action | Avatar Owner | Admin | Unassigned User |
|--------|-------------|-------|-----------------|
| View own queue | ✓ | ✓ | ✗ |
| Confirm posted (own avatar) | ✓ | ✓ | ✗ |
| Skip (own avatar) | ✓ | ✓ | ✗ |
| View all owners' stats | ✗ | ✓ | ✗ |
| Assign avatars | ✗ | ✓ | ✗ |
| Register device | ✓ | ✓ | ✗ |

### Data Flow Security

1. **No Reddit credentials in mobile app** — app never sees Reddit passwords. Owner is already logged into Reddit on their phone.
2. **No draft content persistence** — after confirm/skip, draft text is removed from local state.
3. **Audit trail** — every tap_post, confirm_posted, skip logged with timestamp + IP + device.
4. **Rate limiting** — max 60 confirm-posted calls per hour per user (prevents abuse).

---

## Phased Delivery

### Phase 1 — Backend API + Admin (1 week)
- `avatar_assignments` table + migration
- Mobile API endpoints (queue, confirm, skip, stats)
- Admin: assign avatars to users, posting team page
- No push notifications yet (polling only)

### Phase 2 — Mobile App MVP (1-2 weeks)
- Expo app: login, queue, detail, clipboard+browser flow, confirm dialog
- Stats screen
- Biometric re-login

### Phase 3 — Push Notifications (3-5 days)
- FCM integration
- Device registration
- Approval trigger → push
- Reminder for stale approved drafts

### Phase 4 — Polish & Analytics (1 week)
- Gamification (streaks, leaderboard)
- Posting speed targets
- Owner earnings calculator
- OTA updates via Expo

---

## Cost Impact

| Component | Monthly Cost | Notes |
|-----------|-------------|-------|
| Firebase (FCM) | $0 | Free tier covers 100K+ notifications/month |
| Expo (OTA updates) | $0 | Free tier for <50 users |
| App Store ($99/yr) | $8.25/mo | Apple Developer Program |
| Google Play ($25 one-time) | ~$0 | One-time fee |
| Backend API | $0 | Runs on existing EC2/Droplet |
| **Total** | **~$8/mo** | Negligible |

---

## Alternatives Considered

| Option | Pros | Cons | Decision |
|--------|------|------|----------|
| Telegram Bot | No app store, instant | No clipboard control, no deep links, looks like bot | ✗ Rejected |
| PWA (web app) | No app store review | No push on iOS, no biometric, limited clipboard | ✗ Rejected |
| Flutter | Cross-platform, fast dev, hot reload, single Dart codebase | App store review needed | ✓ Selected |
| React Native (Expo) | JS ecosystem, OTA updates | Slower build, bridge overhead, Expo limitations | ✗ Flutter preferred |
| Native iOS + Android | Best performance | 2x development cost | ✗ Overkill |
| WhatsApp integration | Owners already use it | No clipboard, no deep links, manual flow | ✗ Rejected |

