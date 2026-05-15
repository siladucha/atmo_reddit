# Implementation Tasks — Mobile Posting App

## Phase 1: Backend API + Admin (Priority: P0)

### Task 1.1: Avatar Assignments Model & Migration
- [ ] Create `app/models/avatar_assignment.py` — SQLAlchemy model for `avatar_assignments` table
- [ ] Create `app/models/device_registration.py` — SQLAlchemy model for `device_registrations` table
- [ ] Create `app/models/posting_event.py` — SQLAlchemy model for `posting_events` table
- [ ] Create Alembic migration adding all 3 tables
- [ ] Create Alembic migration adding `posted_by`, `posted_source`, `posting_speed_seconds` to `comment_drafts` and `post_drafts`
- [ ] Register new models in `app/models/__init__.py`

### Task 1.2: Mobile API Router
- [ ] Create `app/routes/mobile.py` — new FastAPI router with prefix `/api/mobile`
- [ ] Implement `GET /api/mobile/queue` — fetch approved drafts for user's assigned avatars, with pagination and avatar filter
- [ ] Implement `POST /api/mobile/drafts/{id}/confirm-posted` — validate ownership, update status to 'posted', compute posting_speed_seconds, log posting_event
- [ ] Implement `POST /api/mobile/drafts/{id}/skip` — validate ownership, log posting_event with action='skip'
- [ ] Implement `GET /api/mobile/stats` — aggregate posting stats (today/week/total/streak)
- [ ] Implement `POST /api/mobile/device` — register/update FCM token
- [ ] Add ownership validation dependency: `require_avatar_owner(draft_id, current_user)`
- [ ] Register router in `app/main.py`

### Task 1.3: Auth Enhancements for Mobile
- [ ] Add refresh token support: `POST /auth/refresh` endpoint
- [ ] Extend JWT claims with `avatar_ids` list for mobile tokens
- [ ] Set mobile token expiry to 7 days (detect via `X-Client-Type: mobile` header or login param)

### Task 1.4: Admin — Avatar Assignment UI
- [ ] Add "Owner" section to `/admin/avatars/{id}` page — dropdown to assign/unassign user
- [ ] Create HTMX partial `partials/avatar_owner_assignment.html`
- [ ] Add `POST /admin/avatars/{id}/assign-owner` endpoint
- [ ] Add `POST /admin/avatars/{id}/unassign-owner` endpoint
- [ ] Add audit log entries for assignment changes

### Task 1.5: Admin — Posting Team Page
- [ ] Create `app/templates/admin_posting_team.html` — table of all avatar owners with stats
- [ ] Create `app/services/posting_analytics.py` — aggregate posting stats per user
- [ ] Add `GET /admin/posting-team` route in `routes/admin.py`
- [ ] Add HTMX partial for per-owner detail expansion (avatar breakdown, recent events)
- [ ] Add nav link to posting team page in admin sidebar

### Task 1.6: Review Flow Integration
- [ ] Modify `routes/review.py` — on approve, check if avatar has assigned owner → trigger notification placeholder
- [ ] Modify `routes/pages.py` — same hook on UI-based approval
- [ ] Ensure `confirm-posted` from mobile writes to `audit_log` with `source='mobile_app'`

---

## Phase 2: Flutter App MVP (Priority: P0 — PARALLEL with Phase 1)

### Task 2.1: Flutter Project Setup
- [ ] Initialize Flutter project: `flutter create ramp_poster`
- [ ] Configure dependencies: go_router, riverpod, dio, flutter_secure_storage, url_launcher, local_auth
- [ ] Set up Dio API client with JWT interceptor (auto-refresh on 401)
- [ ] Create mock JSON server (json-server or local Dart mock) matching API spec from design.md
- [ ] Configure app: name "RAMP Poster", bundle ID, icons

### Task 2.2: Auth Screens
- [ ] Login screen: email + password form, "Remember me" toggle
- [ ] Biometric unlock (local_auth package)
- [ ] Token storage in flutter_secure_storage
- [ ] Auto-login on app open if valid token exists
- [ ] Logout + clear secure storage

### Task 2.3: Queue Screen
- [ ] Tab view: one tab per assigned avatar (TabBar + TabBarView)
- [ ] List view: approved drafts sorted by approval time (ListView.builder)
- [ ] Each item: avatar badge, subreddit, thread title preview, time waiting
- [ ] Pull-to-refresh (RefreshIndicator) + auto-refresh (60s timer via Riverpod)
- [ ] Empty state: "No pending posts 🎉"
- [ ] Badge count per avatar tab

### Task 2.4: Draft Detail Screen
- [ ] Full comment text display (scrollable, SelectableText)
- [ ] Thread context: title, subreddit, comment_to
- [ ] "Post" button (primary, large, bottom-fixed)
- [ ] "Skip" button (secondary, smaller)
- [ ] Thread URL link (opens in browser for context)

### Task 2.5: Posting Flow
- [ ] On "Post" tap: copy text to clipboard (Clipboard.setData)
- [ ] Show SnackBar: "Copied ✓ — Opening Reddit..."
- [ ] Open thread URL via url_launcher (launchUrl)
- [ ] On app resume (WidgetsBindingObserver / AppLifecycleState): show confirm dialog
- [ ] Confirm dialog: "Did you post?" → [Yes ✓] [Not yet] [Skip]
- [ ] On "Yes": call confirm-posted API, remove from local queue, show success animation
- [ ] On "Not yet": dismiss dialog, item stays in queue
- [ ] On "Skip": call skip API, mark item visually

### Task 2.6: Stats Screen
- [ ] Today's stats: posted count, pending count
- [ ] Weekly chart (fl_chart: simple bar chart, posts per day)
- [ ] Streak counter with flame emoji
- [ ] Average posting speed

### Task 2.7: Settings Screen
- [ ] Notification preferences (per-avatar mute toggle)
- [ ] Biometric toggle
- [ ] Logout button
- [ ] App version display

### Task 2.8: Integration (Day 3-4)
- [ ] Replace mock API with real backend URL
- [ ] Test login → queue → post → confirm flow end-to-end
- [ ] Fix edge cases (network errors, token expiry, empty states)
- [ ] Verify ownership validation (403 on wrong avatar)

---

## Phase 3: Push Notifications (Priority: P1)

### Task 3.1: Firebase Setup
- [ ] Create Firebase project for RAMP
- [ ] Configure FCM for iOS (APNs key) and Android
- [ ] Add `firebase-admin` to backend requirements
- [ ] Add FCM credentials to `.env` (server key / service account)

### Task 3.2: Push Notification Service
- [ ] Create `app/services/push_notifications.py`
- [ ] Implement `notify_avatar_owner(avatar_id, draft_summary)` — find owner, find devices, send FCM
- [ ] Implement batching logic: Redis counter `push_batch:{user_id}`, 5-min window
- [ ] Implement `send_reminder(user_id, stale_count)` — for drafts pending >4h

### Task 3.3: Notification Triggers
- [ ] Hook into review approval flow: after status='approved', call notification service
- [ ] Add Celery Beat task: `check_stale_approved_drafts` every 30 min — find approved drafts >4h old, send reminders
- [ ] Respect mute preferences (check user settings before sending)

### Task 3.4: Mobile Push Integration
- [ ] Add firebase_messaging to Flutter app
- [ ] Request push permission on first login
- [ ] Send FCM token to `POST /api/mobile/device` on registration
- [ ] Handle notification tap → deep link to draft detail screen (go_router)
- [ ] Handle foreground notifications (overlay banner via firebase_messaging onMessage)

---

## Phase 4: Polish & Analytics (Priority: P2)

### Task 4.1: Gamification
- [ ] Streak logic: consecutive days with ≥1 post
- [ ] Weekly leaderboard (if multiple owners): rank by posts count
- [ ] "Personal best" tracking (most posts in a day)
- [ ] Subtle animations on milestones (10th post today, etc.)

### Task 4.2: Admin Analytics Enhancement
- [ ] Posting speed histogram on posting-team page
- [ ] Target speed configuration (system setting: `target_posting_speed_minutes`)
- [ ] Compliance rate calculation (% of drafts posted within target)
- [ ] Export posting data to CSV

### Task 4.3: Earnings Calculator
- [ ] System setting: `posting_rate_per_comment` (default $1.00)
- [ ] Mobile stats screen: "Estimated earnings this month: $X"
- [ ] Admin posting-team page: "Estimated payout" column

### Task 4.4: App Store Submission & Monitoring
- [ ] Add Sentry (sentry_flutter) for crash reporting
- [ ] Add basic analytics (screen views, posting funnel)
- [ ] App Store submission (iOS + Android)
- [ ] Configure CI/CD for Flutter builds (GitHub Actions or Codemagic)

---

## Dependencies & Blockers

| Task | Depends On | Blocker |
|------|-----------|---------|
| Phase 2 (Flutter) | API spec only (mocks API) | None — runs in parallel |
| Task 2.8 (Integration) | Phase 1 API deployed | Backend must be accessible |
| Task 3.1 (Firebase) | Apple Developer Account | Need $99/yr enrollment |
| Task 3.4 (mobile push) | Task 3.1 + 3.2 | Firebase project must exist |
| Task 4.4 (App Store) | Phase 2 + integration | App review takes 1-7 days |

## Estimated Timeline

| Phase | Duration | Parallel? |
|-------|----------|-----------|
| Phase 1: Backend API | 5-7 days | ← runs in parallel with Phase 2 |
| Phase 2: Flutter MVP | 3 days (experienced dev) | ← runs in parallel with Phase 1 |
| Integration | 1 day | After both Phase 1 + 2 |
| Phase 3: Push | 2-3 days | After integration |
| Phase 4: Polish | 3-5 days | After Phase 3 |
| **Total** | **~2 weeks** | With parallel tracks |

**Critical path:** RBAC spec (current) → Phase 1 backend → Integration day → Done.
**Flutter track:** Starts immediately with API spec, no backend dependency until integration.

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Posting speed | <2 min per comment | `posting_speed_seconds` avg |
| Queue clearance | 90% posted within 4h | Stale draft count |
| Skip rate | <10% | skipped / total |
| Daily active owners | 100% on workdays | Last posting_event per user |
| App crash rate | <1% | Sentry/Expo metrics |
