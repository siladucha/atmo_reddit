# Design Document: Phase 0 Incubation + Mentor Extraction

## Overview

Two structural changes to the avatar lifecycle:

1. **Mentor → Pool classification** — `avatar.pool == "mentor"` becomes the single source of truth for pipeline exclusion. Phase value becomes irrelevant for Mentors.

2. **Phase 0 = Incubation** — real phase with policy, budget, evaluation, graduation. Solves cold-start problem for fresh accounts.

Result: clean linear state machine (0 → 1 → 2 → 3) with Mentor as an orthogonal pool flag.

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Mentor detection | `avatar.pool == "mentor"` | Pool enum already exists with `mentor` value; no schema change needed |
| Phase 0 semantics | Incubation (real phase) | Reuses existing integer field; no migration of historical data needed beyond Mentor→pool move |
| Safe subreddits | SystemSetting JSON list | Configurable without deploy; different per-environment |
| Graduation criteria | age + karma + posted + zero_deleted | Hybrid time + interaction based; covers AutoMod survival signal |
| Feature flag | `incubation_phase_enabled` | Allows deploy → test → enable without rollback risk |
| Existing Phase 0 avatars | Migrate to pool=mentor, phase=1 | All current Phase 0 are Mentors; no real Incubation avatars exist yet |
| Demotion floor | Phase 0 (not Phase 1) | Gives system a recovery path below hobby; matches the intent of "account needs to prove itself again" |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Avatar Lifecycle                       │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Pool Check (first gate):                                │
│  ┌──────────────┐                                        │
│  │ pool=mentor? │──YES──► EXCLUDED from all pipelines    │
│  └──────┬───────┘                                        │
│         │ NO                                             │
│         ▼                                                │
│  Phase State Machine:                                    │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐│
│  │ Phase 0 │──►│ Phase 1 │──►│ Phase 2 │──►│ Phase 3 ││
│  │Incubate │   │ Hobby   │   │ Profess │   │ Brand   ││
│  └─────────┘   └─────────┘   └─────────┘   └─────────┘│
│       ▲              │              │                    │
│       └──────────────┴──── demotion ┘                    │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

## Component Changes

### 1. Pipeline Entry Gate (all tasks)

Currently every pipeline task checks:
```python
if avatar.warming_phase == 0:
    skip("Mentor")
if avatar.is_frozen:
    skip("Frozen")
```

New logic:
```python
if avatar.pool == "mentor":
    skip("Mentor: pool exclusion")
if avatar.is_frozen:
    skip("Frozen")
# Phase 0 avatars proceed — they get 1/day incubation treatment
```

Affected locations:
- `posting_safety.py` Gate #5
- `PhasePolicy.check_comment_allowed()`
- `ai_pipeline.py` generate_comments filter
- `ai_pipeline.py` generate_hobby_comments filter
- `smart_scoring.py` pre-filter
- `tasks/epg.py` avatar eligibility
- `tasks/health_check.py` (Mentors still get health checks — pool doesn't block monitoring)

### 2. PhasePolicy — New `_check_phase0()`

```python
def _check_phase0(self, db, avatar, comment_type, target_subreddit, comment_text, client):
    """Phase 0 (Incubation): ultra-conservative engagement."""
    
    # Rule: Only hobby
    if comment_type != "hobby":
        return PolicyResult(blocked, "Phase 0: only hobby allowed")
    
    # Rule: Only safe subreddits
    safe_subs = get_setting(db, "incubation_safe_subreddits") or DEFAULT_SAFE_SUBS
    if target_subreddit.lower() not in [s.lower() for s in safe_subs]:
        return PolicyResult(blocked, f"Phase 0: '{target_subreddit}' not in safe subreddits")
    
    # Rule: Max 1/day
    if self.get_daily_comment_count(db, avatar) >= 1:
        return PolicyResult(blocked, "Phase 0: daily limit reached (1/1)")
    
    # Rule: Zero brand
    if self.classify_brand_mention(comment_text, client) is not None:
        return PolicyResult(blocked, "Phase 0: brand mentions not allowed")
    
    return PolicyResult(allowed, "Phase 0: comment allowed")
```

### 3. PhaseEvaluator — Phase 0 → 1 Promotion

Add to `check_promotion_eligibility()`:

```python
if current_phase == 0:
    thresholds = self.get_thresholds(db, 0)  # phase_gate_p0_*
    
    age_days = (now - account_created).days
    karma = avatar.reddit_karma_comment
    
    # Count posted comments (any status=posted)
    posted_count = count(CommentDraft, avatar_id, status="posted")
    
    # Count deleted in last 7 days
    deleted_count = count(CommentDraft, avatar_id, is_deleted=True, posted_at >= now-7d)
    
    eligible = (
        age_days >= thresholds["min_age_days"]       # default 7
        and karma >= thresholds["min_karma"]          # default 10
        and posted_count >= thresholds["min_posted"]  # default 3
        and deleted_count <= thresholds["max_deleted"] # default 0
    )
    return (eligible, criteria_values)
```

New defaults:
```python
_P0_DEFAULTS = {
    "min_age_days": 7,
    "min_karma": 10,
    "min_posted_comments": 3,
    "max_deleted_comments": 0,
}
```

### 4. PhaseEvaluator — Demotion: Phase 0 Instead of Freeze

The fundamental change: **shadowban and CQS-lowest trigger demotion to Phase 0, not freeze.**

Current (broken):
```python
def check_demotion_triggers(self, db, avatar):
    if avatar.warming_phase <= 1:
        return (False, current_phase or 1, None)  # Can't demote below 1
    
    if avatar.is_shadowbanned:
        return (True, 1, "shadowban_detected")  # + freeze happens elsewhere
```

New:
```python
def check_demotion_triggers(self, db, avatar):
    if avatar.warming_phase <= 0:
        return (False, 0, None)  # Can't demote below 0
    
    # Shadowban → Phase 0 (NOT freeze). Monitoring continues.
    if avatar.is_shadowbanned:
        return (True, 0, "shadowban_detected")
    
    # CQS lowest (Phase 2+) → Phase 0 (NOT freeze)
    if avatar.cqs_level == "lowest" and avatar.warming_phase >= 2:
        return (True, 0, "cqs_lowest")
    
    # Survival rate (Phase 1+) → Phase 0
    if avatar.warming_phase >= 1:
        survival = self.compute_comment_survival_rate(db, avatar, _DEMOTION_WINDOW_DAYS)
        if survival * 100 < _DEMOTION_MIN_SURVIVAL_RATE:
            return (True, 0, "low_survival_rate")
    
    # Karma drop (Phase 2+) → current - 1
    if avatar.warming_phase >= 2:
        should_demote_karma, avg_score = check_karma_drop_demotion(db, avatar)
        if should_demote_karma:
            return (True, avatar.warming_phase - 1, f"karma_drop (avg={avg_score:.2f})")
    
    return (False, avatar.warming_phase, None)
```

Key changes:
- Shadowban → always Phase 0 (not Phase 1, not freeze)
- CQS lowest → always Phase 0 (not freeze)
- Survival rate → always Phase 0 (from any phase)
- Karma drop → current - 1 (gradual, stays above 0)
- Floor is 0, not 1

### 4b. Freeze Reduction — When to Actually Freeze

Freeze is reserved for truly unrecoverable states:

```python
# health_checker.py — only freeze on SUSPENDED (404/403)
if health_status == "suspended":
    avatar.is_frozen = True
    avatar.freeze_reason = "Reddit account suspended (404/403)"

# cqs_checker.py — REMOVE auto-freeze on CQS lowest
# OLD: if cqs_level == "lowest" and phase >= 2: freeze
# NEW: demotion handles this (check_demotion_triggers returns Phase 0)

# New: Phase 0 timeout freeze
# Celery task (daily, after phase evaluation):
if avatar.warming_phase == 0:
    days_in_phase0 = (now - avatar.phase_changed_at).days
    timeout = int(get_setting(db, "phase0_freeze_timeout_days") or 30)
    if days_in_phase0 > timeout:
        avatar.is_frozen = True
        avatar.freeze_reason = f"Phase 0 timeout: {days_in_phase0} days without graduation"
```

### 4c. Health Check for Phase 0 (Shadowbanned) Avatars

Remove `is_frozen` filter from `health_check_all_avatars`. Since we no longer freeze on shadowban, this is natural — Phase 0 shadowbanned avatars are NOT frozen, so health checks continue automatically.

But also: Phase 0 avatars with `is_shadowbanned = true` still generate 1 comment/day. This comment serves as a **shadowban probe** — if it gets karma > 0, the shadowban may have been lifted. The next health check will confirm.

```python
# health_checker.py — detection of shadowban CLEARANCE
if previous_status == "shadowbanned" and new_status == "active":
    avatar.is_shadowbanned = False
    record_activity_event(db, "shadowban_cleared", 
        f"Shadowban cleared for {avatar.reddit_username}", ...)
    # Avatar stays in Phase 0, graduates normally via criteria
```

### 5. Avatar Creation Logic

Currently: always `warming_phase = 1`.

New (in `avatar_onboard.py` / `onboarding.py` / admin create):
```python
# Determine initial phase based on account maturity
if avatar.reddit_karma_comment >= 10 or account_age_days >= 14:
    avatar.warming_phase = 1  # Pre-warmed, skip incubation
else:
    avatar.warming_phase = 0  # Fresh account, needs incubation
```

This preserves backward compatibility: existing avatars imported with decent karma start at Phase 1.

### 6. Generation Prompt (Phase 0)

New function in `ai_pipeline.py`:

```python
def _build_incubation_system_prompt(avatar, previous_comments):
    return f"""You are a new Reddit user exploring communities.
    
Write a SHORT comment (10-30 words max). You are curious, friendly, brief.

ALLOWED styles:
- Ask a genuine question about the topic
- Share a brief personal reaction ("this happened to me too")  
- Agree with someone and add one small detail
- Express surprise or interest

FORBIDDEN:
- Opinions longer than one sentence
- Technical advice
- Links or formatting (no bold, no lists)
- Multi-paragraph responses
- Starting with "I think" or "In my opinion"

Previous comments (do NOT repeat patterns):
{chr(10).join(previous_comments[-5:])}

Output: just the comment text, nothing else."""
```

### 7. AttentionBudget Integration

```python
# portfolio_manager.py → AttentionBudget.from_avatar()
if avatar.warming_phase == 0:
    return AttentionBudget(max_comments=1, max_posts=0, ...)
```

### 8. Smart Scoring Phase 0 Handling

`get_avatar_available_subreddit_names()` already routes by phase:
```python
if phase == 0:
    # Return safe subreddits from system setting
    safe_subs_json = get_setting(db, "incubation_safe_subreddits")
    return json.loads(safe_subs_json) if safe_subs_json else DEFAULT_SAFE_SUBS
if phase == 1:
    return hobby_subs
```

But Phase 0 avatars won't typically go through Smart Scoring (professional pipeline). They go through hobby pipeline only. The safe sub list is enforced at PhasePolicy level.

### 9. EPG Auto-Approve Override

```python
# portfolio_manager.py or epg generation
if avatar.warming_phase == 0:
    # Never auto-approve, even if avatar.auto_approve_drafts == True
    slot.status = "generated"  # NOT "approved"
```

### 10. Migration Plan

```sql
-- Alembic upgrade
-- Step 1: Move Mentors from phase to pool
UPDATE avatars 
SET pool = 'mentor', warming_phase = 1 
WHERE warming_phase = 0;

-- Step 2: Add system setting
INSERT INTO system_settings (key, value) 
VALUES ('incubation_safe_subreddits', '["AskReddit","CasualConversation","NoStupidQuestions","TooAfraidToAsk","Showerthoughts","LifeProTips"]');

-- Step 3: Feature flag (disabled by default)
INSERT INTO system_settings (key, value) 
VALUES ('incubation_phase_enabled', 'false');
```

Downgrade:
```sql
-- Revert Mentors back to phase 0
UPDATE avatars 
SET warming_phase = 0 
WHERE pool = 'mentor';

DELETE FROM system_settings WHERE key IN ('incubation_safe_subreddits', 'incubation_phase_enabled');
```

### 11. Feature Flag Behavior

When `incubation_phase_enabled = "false"`:
- New avatars still created with `warming_phase = 1` (old behavior)
- PhasePolicy Phase 0 check → treat as Phase 1 (fallback)
- PhaseEvaluator Phase 0 → 1 → never fires (no Phase 0 avatars exist)
- Demotion floor stays at Phase 1

When `incubation_phase_enabled = "true"`:
- New avatars with low karma/age → `warming_phase = 0`
- PhasePolicy Phase 0 → full incubation rules
- PhaseEvaluator Phase 0 → 1 evaluation active
- Demotion to Phase 0 possible

## Affected Files

| File | Change Type | Description |
|------|-------------|-------------|
| `app/services/phase.py` | Modify | Add `_check_phase0()`, update demotion floor, add P0 thresholds, Mentor→pool check |
| `app/services/phase_types.py` | Modify | No changes needed (PolicyResult/EvaluationResult already support phase 0) |
| `app/services/posting_safety.py` | Modify | Gate #5: `pool == "mentor"` instead of `phase == 0` |
| `app/services/safety_blocks.py` | Modify | Check `pool == "mentor"` for pipeline exclusion |
| `app/services/smart_scoring.py` | Modify | Phase 0 safe sub routing |
| `app/tasks/ai_pipeline.py` | Modify | Add `_build_incubation_system_prompt`, Mentor check by pool, Phase 0 generation logic |
| `app/tasks/epg.py` | Modify | Mentor check by pool, Phase 0 auto-approve block |
| `app/services/portfolio_manager.py` | Modify | AttentionBudget Phase 0 = 1 comment |
| `app/routes/admin.py` | Modify | Phase override allows 0-3, Mentor toggle via pool |
| `app/routes/avatar_onboard.py` | Modify | Initial phase assignment logic |
| `app/routes/onboarding.py` | Modify | Initial phase for wizard-created avatars |
| `app/templates/admin_*.html` | Modify | Phase 0 "Incubation" badge, Mentor as pool badge |
| `app/templates/partials/avatar_*.html` | Modify | Phase labels, graduation progress |
| `alembic/versions/incub01_*.py` | New | Migration: Mentor→pool, settings |

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Existing Mentor avatars disrupted | Migration is pure data move (pool already exists). Code change gates on `pool == "mentor"` which is semantically equivalent |
| Phase 0 avatars stuck (never graduate) | Daily evaluation includes Phase 0. Graduation criteria are intentionally low (7d, 10 karma, 3 posts). Phase 0 timeout (30d) → freeze as last resort. Admin override available |
| Backward compatibility | Feature flag defaults to "false" — no behavior change at deploy |
| Demotion loops (Phase 1 ↔ 0) | Phase 0 has no demotion below. Shadowbanned avatars in Phase 0 still get 1/day probe activity. Timeout freeze prevents infinite Phase 0 |
| Tests break on `phase == 0` Mentor assumption | Grep and fix. Limited surface area (6-8 locations) |
| Shadowbanned avatar generates spam | Phase 0 + shadowbanned = 1 comment/day in safe subs only. Reddit won't penalize further for 1 invisible comment. This IS the probe mechanism |
| CQS checker freeze removal causes unsafe avatars to stay active | Demotion to Phase 0 = 1/day limit. Effectively same protection as freeze but with monitoring |
| Phase 0 timeout too aggressive | Configurable setting (default 30d). Admin can override per-avatar |
