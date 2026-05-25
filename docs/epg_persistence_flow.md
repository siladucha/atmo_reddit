# EPG Persistence — Full Architecture Flow

## Problem Statement

EPG (Electronic Program Guide) is currently a **read-only, ephemeral** computation.
It selects threads and shows them in the UI, but:
1. Does NOT persist the plan → every page load recomputes (different results each time)
2. Generation tasks (`generate_comments`, `generate_hobby_comments`) use their OWN thread selection logic → EPG plan ≠ what actually gets generated
3. No tracking of slot execution status (was this slot generated? posted? skipped?)
4. Telegram bot (future) has no persistent source of "what to post today"

## Solution: EPG Slots as Persistent Records

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        NEW DATA MODEL                                    │
│                                                                          │
│  epg_slots                                                               │
│  ─────────                                                               │
│  id              UUID PK                                                 │
│  avatar_id       UUID FK → avatars.id                                    │
│  client_id       UUID FK → clients.id (nullable, for business slots)     │
│  plan_date       DATE (the day this slot belongs to)                      │
│  slot_type       VARCHAR: "hobby" | "professional"                       │
│  scheduled_at    TIMESTAMPTZ (target posting time with jitter)            │
│  status          VARCHAR: "planned" | "generated" | "approved" |         │
│                           "posted" | "skipped" | "expired"               │
│                                                                          │
│  # Target (what to generate for)                                         │
│  thread_id       UUID FK → reddit_threads.id (for professional)          │
│  hobby_post_id   UUID FK → hobby_subreddits.id (for hobby)              │
│  subreddit       VARCHAR (denormalized for display)                       │
│  thread_title    VARCHAR (denormalized for display)                       │
│  thread_ups      INT (snapshot at plan time)                              │
│                                                                          │
│  # Result (filled after generation)                                      │
│  draft_id        UUID FK → comment_drafts.id (nullable, set on gen)      │
│                                                                          │
│  # Metadata                                                              │
│  created_at      TIMESTAMPTZ                                             │
│  generated_at    TIMESTAMPTZ (nullable)                                  │
│  posted_at       TIMESTAMPTZ (nullable)                                  │
│  skip_reason     VARCHAR (nullable — why skipped/expired)                 │
│                                                                          │
│  INDEXES:                                                                │
│  - (avatar_id, plan_date) — daily plan lookup                            │
│  - (avatar_id, plan_date, status) — filter by status                     │
│  - (status) WHERE status = 'planned' — pending generation                │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Slot Status Lifecycle

```
                    ┌──────────────────────────────────────────────┐
                    │                                              │
                    ▼                                              │
┌─────────┐    ┌───────────┐    ┌──────────┐    ┌────────┐       │
│ planned  │───▶│ generated │───▶│ approved │───▶│ posted │       │
└─────────┘    └───────────┘    └──────────┘    └────────┘       │
     │              │                │                             │
     │              │                │                             │
     ▼              ▼                ▼                             │
┌─────────┐    ┌─────────┐    ┌──────────┐                       │
│ skipped │    │ skipped  │    │ rejected │───────────────────────┘
└─────────┘    └─────────┘    └──────────┘   (slot freed, can be
                                              re-planned tomorrow)
     │
     ▼
┌─────────┐
│ expired │  (end of day, not generated)
└─────────┘
```

**Transitions:**
- `planned → generated` — LLM called, CommentDraft created, `draft_id` set
- `planned → skipped` — thread locked/removed, avatar frozen, manual skip
- `planned → expired` — end-of-day cleanup (23:59), slot was never generated
- `generated → approved` — human approves the draft (synced from CommentDraft.status)
- `generated → skipped` — human rejects the draft
- `approved → posted` — avatar owner confirms posting on Reddit
- `rejected → planned` — (optional) slot can be re-assigned to a different thread

## Full Flow Diagram

```
═══════════════════════════════════════════════════════════════════════════
PHASE 1: PLAN (EPG Build)
═══════════════════════════════════════════════════════════════════════════

Trigger: Manual "Rebuild" button OR Celery Beat (08:00 daily)

┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│  build_daily_epg(db, avatar, client)                                 │
│                                                                      │
│  1. Health gates (frozen? shadowbanned? mentor? inactive?)           │
│  2. Budget calc: daily_limit(phase) - used_today = remaining         │
│  3. Phase split: P1=100% hobby, P2=50/50, P3=30/70                  │
│  4. Dedup: exclude threads with existing drafts/slots                │
│  5. Select hobby threads (round-robin subreddits, by ups)            │
│  6. Select business threads (keyword score × log(ups))               │
│  7. Generate time slots (08:00-21:00, ±30min jitter, 45min gap)      │
│                                                                      │
│  NEW: 8. Persist → INSERT INTO epg_slots (one row per slot)          │
│       9. Delete old "planned" slots for today (rebuild = replace)     │
│      10. Keep "generated"/"approved"/"posted" slots intact            │
│                                                                      │
│  Returns: EPGResult (same as before, but now backed by DB)           │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │   epg_slots (DB)  │
                    │                   │
                    │  slot 1: hobby    │  status = "planned"
                    │  slot 2: hobby    │  status = "planned"
                    │  slot 3: pro      │  status = "planned"
                    │  slot 4: pro      │  status = "planned"
                    │  slot 5: pro      │  status = "planned"
                    └───────────────────┘


═══════════════════════════════════════════════════════════════════════════
PHASE 2: GENERATE (LLM Calls)
═══════════════════════════════════════════════════════════════════════════

Trigger: Manual "Generate" button per slot OR "Generate All" OR Celery Beat

┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│  generate_epg_slot(db, slot_id)  — NEW function                      │
│                                                                      │
│  1. Load EPGSlot from DB (status must be "planned")                  │
│  2. Verify thread still valid (not locked, not removed)              │
│     - If invalid → slot.status = "skipped", slot.skip_reason = ...   │
│  3. Call LLM:                                                        │
│     - Hobby: inline Gemini Flash call (same as workflow_generate)    │
│     - Professional: select_persona → generate_comment → edit_comment │
│  4. Create CommentDraft record                                       │
│  5. Link: slot.draft_id = draft.id                                   │
│  6. Update: slot.status = "generated", slot.generated_at = now()     │
│                                                                      │
│  Returns: CommentDraft (or None if skipped)                          │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘

  Batch variant:

┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│  generate_all_planned_slots(db, avatar_id, plan_date=today)          │
│                                                                      │
│  1. Query: SELECT * FROM epg_slots                                   │
│            WHERE avatar_id = ? AND plan_date = today                  │
│            AND status = 'planned'                                     │
│            ORDER BY scheduled_at                                      │
│  2. For each slot: generate_epg_slot(db, slot.id)                    │
│  3. Return count of generated                                        │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘


═══════════════════════════════════════════════════════════════════════════
PHASE 3: REVIEW (Human Decision)
═══════════════════════════════════════════════════════════════════════════

Trigger: Human clicks Approve/Reject in Workflow tab or Decision Center

┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│  When CommentDraft.status changes:                                   │
│                                                                      │
│  draft.status = "approved"                                           │
│    → Find EPGSlot WHERE draft_id = draft.id                          │
│    → slot.status = "approved"                                        │
│                                                                      │
│  draft.status = "rejected"                                           │
│    → Find EPGSlot WHERE draft_id = draft.id                          │
│    → slot.status = "skipped"                                         │
│    → slot.skip_reason = "rejected_by_reviewer"                       │
│                                                                      │
│  (Sync happens in review route hooks — same place learning fires)    │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘


═══════════════════════════════════════════════════════════════════════════
PHASE 4: POST (Avatar Owner Action)
═══════════════════════════════════════════════════════════════════════════

Trigger: Owner confirms "Posted" (Workflow tab / Telegram bot)

┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│  When CommentDraft.status = "posted":                                │
│                                                                      │
│  draft.status = "posted", draft.posted_at = now()                    │
│    → Find EPGSlot WHERE draft_id = draft.id                          │
│    → slot.status = "posted"                                          │
│    → slot.posted_at = now()                                          │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘


═══════════════════════════════════════════════════════════════════════════
PHASE 5: CLEANUP (End of Day)
═══════════════════════════════════════════════════════════════════════════

Trigger: Celery Beat at 23:55 daily

┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│  expire_stale_epg_slots(plan_date=today)                             │
│                                                                      │
│  UPDATE epg_slots                                                    │
│  SET status = 'expired', skip_reason = 'end_of_day'                  │
│  WHERE plan_date = today AND status = 'planned'                      │
│                                                                      │
│  (Slots that were planned but never generated → expired)             │
│  (Generated but not approved → stay as "generated", carry over?)     │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

## UI Changes (Workflow Tab)

### Before (current):
```
EPG shows slots → "Generate" button calls LLM inline or dispatches Celery task
                   with its OWN thread selection (ignores EPG)
```

### After (new):
```
EPG shows slots FROM DB → "Generate" button calls generate_epg_slot(slot_id)
                          which generates for EXACTLY that thread
                          → result appears inline
```

### Workflow Tab Layout (unchanged visually, different data source):

```
┌─────────────────────────────────────────────────────────────────┐
│  📺 Today's Plan (EPG)                          [🔄 Rebuild]    │
│                                                                  │
│  08:23  🟢  Best yoga mat for beginners?    r/yoga      hobby   │
│  10:45  🟢  How to fix lower back pain      r/fitness   hobby   │
│  13:12  🔵  CISO burnout is real            r/cybersec  pro     │
│  15:30  🔵  Zero trust implementation       r/netsec    pro     │
│  18:00  🔵  SOC team scaling challenges     r/blueteam  pro     │
│                                                                  │
│  Budget: 2/5 used today                                          │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  ⚡ Generate Comments                                            │
│                                                                  │
│  🟢 Best yoga mat for beginners?  r/yoga  42↑   [Generate]      │
│  🟢 How to fix lower back pain    r/fitness 18↑ [✓ Done]        │
│  🔵 CISO burnout is real          r/cybersec 67↑ [Generate]     │
│  🔵 Zero trust implementation     r/netsec 23↑  [Generate]      │
│  🔵 SOC team scaling challenges   r/blueteam 31↑ [✓ Done]       │
│                                                                  │
│  [⚡ Generate All Remaining]                                     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  📤 Review & Post                    2 pending · 1 to post       │
│                                                                  │
│  ✓ Ready to Post                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ r/fitness · How to fix lower back pain                   │    │
│  │ ┌─────────────────────────────────────────────────────┐ │    │
│  │ │ Started doing dead hangs 3x/week and the difference │ │    │
│  │ │ was night and day. Took about 2 weeks to notice...  │ │    │
│  │ └─────────────────────────────────────────────────────┘ │    │
│  │ [Reddit ↗]  [URL: ___________] [📤 Posted]              │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ⏳ Pending Review                                               │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ r/blueteam · SOC team scaling challenges                 │    │
│  │ ┌─────────────────────────────────────────────────────┐ │    │
│  │ │ We went from 3 to 12 analysts in 18 months and the  │ │    │
│  │ │ playbook sprawl was the real killer...               │ │    │
│  │ └─────────────────────────────────────────────────────┘ │    │
│  │ [✓ Approve]  [✗ Reject]  [Reddit ↗]                     │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

## Integration with Existing Systems

### 1. Celery Beat Schedule (automated daily flow)

```
08:00  run_full_pipeline_all_clients
         │
         ├── score_threads(client_id)          ← unchanged
         │
         └── NEW: build_and_generate_epg_all_avatars()
                    │
                    ├── For each active avatar:
                    │     build_daily_epg(db, avatar, client)  → persists slots
                    │     generate_all_planned_slots(db, avatar.id)
                    │
                    └── (replaces generate_comments + generate_hobby_comments
                         for the scheduled pipeline run)
```

### 2. Manual Trigger (admin UI)

```
Admin clicks "Rebuild" on Workflow tab
  → DELETE FROM epg_slots WHERE avatar_id=? AND plan_date=today AND status='planned'
  → build_daily_epg(db, avatar, client)  → INSERT new planned slots
  → Return updated workflow partial

Admin clicks "Generate" on a specific slot
  → generate_epg_slot(db, slot.id)
  → Return inline result (✓ Done / Error)

Admin clicks "Generate All Remaining"
  → generate_all_planned_slots(db, avatar.id, plan_date=today)
  → Return updated workflow partial
```

### 3. Telegram Bot (future)

```
Bot reads from epg_slots:
  SELECT * FROM epg_slots
  WHERE avatar_id = ? AND plan_date = today
  AND status IN ('approved')
  ORDER BY scheduled_at

Bot shows: "You have 3 comments to post today"
  → Each with: subreddit, thread title, comment text, Reddit URL
  → Owner taps "Posted" → slot.status = 'posted'
```

### 4. Budget Tracking (improved)

```
Current: _get_used_today() counts CommentDrafts created today
New:     _get_used_today() counts EPGSlots for today with status != 'planned'/'expired'

This is more accurate because:
- A rebuilt EPG doesn't double-count
- Rejected slots don't permanently consume budget (can be re-planned)
- Clear distinction between "planned" and "consumed"
```

## Deduplication (improved)

### Current problem:
EPG uses `_get_avatar_used_thread_ids()` which checks ALL CommentDrafts ever.
But EPG is ephemeral — if you rebuild, it might pick different threads.
Two rebuilds in a row could show different plans.

### New approach:
```python
def _get_avatar_used_thread_ids(db, avatar, plan_date):
    """Threads that are OFF-LIMITS for today's plan."""
    # 1. Threads with existing CommentDrafts (any status, any date)
    draft_threads = set(...)
    
    # 2. Threads already in today's EPG with status != 'planned'
    #    (generated/approved/posted — these are committed)
    committed_slot_threads = set(...)
    
    return draft_threads | committed_slot_threads
```

This means:
- "Rebuild" can reassign `planned` slots to different threads (they're not committed)
- Once a slot is `generated`, that thread is locked to this avatar
- Historical drafts still prevent re-engagement (no double-commenting)

## Migration Plan

### Alembic Migration

```python
"""Add epg_slots table.

Revision ID: epg_slots_001
"""

def upgrade():
    op.create_table(
        'epg_slots',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('avatar_id', UUID(as_uuid=True), sa.ForeignKey('avatars.id'), nullable=False),
        sa.Column('client_id', UUID(as_uuid=True), sa.ForeignKey('clients.id'), nullable=True),
        sa.Column('plan_date', sa.Date, nullable=False),
        sa.Column('slot_type', sa.String(50), nullable=False),  # hobby | professional
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='planned'),
        
        # Target
        sa.Column('thread_id', UUID(as_uuid=True), sa.ForeignKey('reddit_threads.id'), nullable=True),
        sa.Column('hobby_post_id', UUID(as_uuid=True), nullable=True),
        sa.Column('subreddit', sa.String(255), nullable=True),
        sa.Column('thread_title', sa.Text, nullable=True),
        sa.Column('thread_ups', sa.Integer, nullable=True),
        
        # Result
        sa.Column('draft_id', UUID(as_uuid=True), sa.ForeignKey('comment_drafts.id'), nullable=True),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('skip_reason', sa.String(255), nullable=True),
    )
    
    op.create_index('ix_epg_slots_avatar_date', 'epg_slots', ['avatar_id', 'plan_date'])
    op.create_index('ix_epg_slots_avatar_date_status', 'epg_slots', ['avatar_id', 'plan_date', 'status'])
    op.create_index('ix_epg_slots_status_planned', 'epg_slots', ['status'],
                    postgresql_where=text("status = 'planned'"))
    op.create_index('ix_epg_slots_draft_id', 'epg_slots', ['draft_id'])
```

## Files to Create/Modify

### New files:
- `app/models/epg_slot.py` — SQLAlchemy model
- `app/services/epg_executor.py` — `generate_epg_slot()`, `generate_all_planned_slots()`
- `app/tasks/epg.py` — Celery tasks: `build_and_generate_epg_all_avatars`, `expire_stale_slots`
- `alembic/versions/xxx_add_epg_slots.py` — migration

### Modified files:
- `app/services/epg.py` — `build_daily_epg()` now persists to DB + reads existing slots
- `app/routes/avatar_workflow.py` — reads from `epg_slots` table, generate calls `generate_epg_slot`
- `app/routes/avatars.py` — `build_avatar_epg` endpoint uses new flow
- `app/templates/partials/avatar_workflow.html` — minor: slot status badges
- `app/tasks/worker.py` — register new tasks
- `app/tasks/ai_pipeline.py` — `generate_comments` becomes a fallback (for non-EPG contexts)

### Celery Beat additions:
```python
# In worker.py beat_schedule:
'build-epg-morning': {
    'task': 'build_and_generate_epg_all_avatars',
    'schedule': crontab(hour=8, minute=0),
},
'expire-epg-slots-nightly': {
    'task': 'expire_stale_epg_slots',
    'schedule': crontab(hour=23, minute=55),
},
```

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| EPG slots are per-day, not per-week | Simpler, matches daily budget model. Tomorrow gets fresh plan. |
| "Rebuild" deletes only `planned` slots | Preserves work already done (generated/approved/posted). |
| Slot ↔ Draft is 1:1 | One slot = one comment. Clear tracking. |
| Denormalized subreddit/title on slot | Avoids JOINs for display. Snapshot at plan time. |
| `generate_comments` task kept as fallback | Backward compat for API triggers that don't use EPG. |
| No separate "scheduling" service | Time slots are informational (for Telegram bot timing). Generation is on-demand. |
| Expired slots don't count against budget | Only generated/approved/posted consume budget. |

## Sequence Diagram: Full Day

```
Time    Admin UI              EPG Service           DB (epg_slots)        LLM
─────   ────────              ───────────           ──────────────        ───
08:00   [Celery Beat fires]
        │                     build_daily_epg()
        │                     │ health check ✓
        │                     │ budget: 0/5 used
        │                     │ select 2 hobby + 3 pro
        │                     │                     INSERT 5 slots (planned)
        │                     │
        │                     generate_all_planned()
        │                     │ slot 1 (hobby)      status→generated      call Flash
        │                     │ slot 2 (hobby)      status→generated      call Flash
        │                     │ slot 3 (pro)        status→generated      call Sonnet×3
        │                     │ slot 4 (pro)        thread locked!
        │                     │                     status→skipped
        │                     │ slot 5 (pro)        status→generated      call Sonnet×3
        │                     │
        │                     done: 4 generated, 1 skipped

10:00   Admin opens Workflow tab
        │ GET /workflow
        │                     read epg_slots for today
        │                     read comment_drafts (pending/approved)
        │ ◀── render: 4 drafts pending review

10:05   Admin approves draft #1
        │ POST /approve
        │                     draft.status = approved
        │                                           slot.status→approved
        │ ◀── updated card (ready to post)

10:10   Admin rejects draft #3
        │ POST /reject
        │                     draft.status = rejected
        │                                           slot.status→skipped

14:00   Admin clicks "Rebuild"
        │ POST /rebuild-epg
        │                     DELETE planned slots (none left)
        │                     budget: 4/5 used (gen+approved+posted)
        │                     remaining: 1
        │                     select 1 new pro thread
        │                                           INSERT 1 slot (planned)
        │ ◀── render: 1 new slot + existing results

14:05   Admin clicks "Generate" on new slot
        │ POST /generate-slot
        │                     generate_epg_slot()
        │                                           status→generated      call Sonnet×3
        │ ◀── inline "✓ Done"

18:00   [Telegram bot checks]
        │                     query: approved slots for this avatar
        │                     → 1 approved slot ready to post
        │ ◀── push notification to owner

18:30   Owner posts on Reddit, confirms
        │                     draft.status = posted
        │                                           slot.status→posted

23:55   [Celery Beat: expire]
        │                     expire_stale_epg_slots()
        │                                           0 planned left → nothing to expire
```

## Budget Accounting (Revised)

```python
def _get_used_today(db: Session, avatar: Avatar) -> int:
    """Count slots that consumed budget today.
    
    Consumed = generated OR approved OR posted (not planned, not expired, not skipped).
    """
    today = date.today()
    count = (
        db.query(sa_func.count(EPGSlot.id))
        .filter(
            EPGSlot.avatar_id == avatar.id,
            EPGSlot.plan_date == today,
            EPGSlot.status.in_(["generated", "approved", "posted"]),
        )
        .scalar()
    )
    return count or 0
```

**Why this is better:**
- Rejected drafts free up budget (slot → skipped, doesn't count)
- Expired slots don't count (never generated)
- Rebuild doesn't double-count (planned slots are replaced)
- Single source of truth (no more counting CommentDrafts + HobbySubreddits separately)

## Backward Compatibility

1. **`generate_comments` Celery task** — still works for API/external triggers. But the scheduled pipeline (08:00, 14:00) switches to EPG-based flow.
2. **`generate_hobby_comments` Celery task** — same, kept for backward compat but EPG handles hobby slots directly.
3. **Existing CommentDrafts** — unchanged. EPGSlot.draft_id points to them. All review/learning/posting logic stays the same.
4. **Decision Center** — reads CommentDrafts as before. EPG is an additional layer on top.
5. **Content tab** — unchanged (reads CommentDrafts). Workflow tab is the EPG-aware view.
