# Requirements Document: Phase 0 Incubation + Mentor Extraction

## Introduction

This spec refactors the avatar phase system to solve two problems:

1. **Phase 0 (Mentor) is misplaced** — it's stored as a phase value but is functionally a category flag. It never transitions, never evaluates, never generates. It's a boolean masquerading as a state machine state.

2. **Cold-start gap for new avatars** — fresh accounts (0 karma, <7 days old) enter Phase 1 and immediately receive hobby generation tasks. Reddit AutoMod kills their first comments. No incubation period exists.

The solution:
- Extract Mentor from the phase system into `avatar.pool` (already exists: b2b/b2c/mentor/warm)
- Repurpose Phase 0 as **Incubation** — a real phase with rules, budget, evaluation, and graduation criteria
- Phase system becomes linear: 0 (Incubation) → 1 (Hobby) → 2 (Professional) → 3 (Brand)

## Glossary

- **Incubation (Phase 0)**: New real phase for fresh/low-karma avatars. Ultra-conservative engagement: 1 comment/day, safe subs only, mandatory human approval, simple prompts. Purpose: survive first week without AutoMod kills.
- **Mentor**: Category of pre-warmed high-karma accounts excluded from all automated pipelines. NOT a phase — a pool classification. Set via admin action.
- **Safe Subreddits**: Curated list of low-moderation, newcomer-friendly subs where fresh accounts can post without AutoMod interference (e.g., r/AskReddit, r/CasualConversation, r/NoStupidQuestions).
- **Graduation Criteria**: Conditions for Phase 0 → Phase 1 transition: account age, minimum karma, manually posted comments, no AutoMod removals.
- **Pool**: Avatar operational category (enum: b2b, b2c, mentor, warm). Determines pipeline eligibility independently of phase.

## Requirements

### Requirement 1: Mentor Extraction from Phase System

**User Story:** As an engineer, I want Mentor status stored as a pool value instead of a phase value, so that the phase state machine remains linear and Mentor semantics are clear.

#### Acceptance Criteria

1. THE system SHALL identify Mentor avatars by `avatar.pool == "mentor"` instead of `avatar.warming_phase == 0`
2. THE `AvatarPool` enum SHALL retain the existing `mentor` value (no schema change needed)
3. WHEN `avatar.pool == "mentor"`, THE system SHALL exclude the avatar from ALL automated pipelines (scoring, generation, EPG, posting, email tasks) regardless of `warming_phase` value
4. THE PhaseEvaluator SHALL skip avatars where `pool == "mentor"` (no promotion/demotion evaluation)
5. THE `posting_safety.py` Gate #5 SHALL check `avatar.pool == "mentor"` instead of `avatar.warming_phase == 0`
6. THE PhasePolicy SHALL check `avatar.pool == "mentor"` and return `blocked` with reason "Mentor: excluded from automated pipelines"
7. THE admin override SHALL continue to allow setting any phase value (0-3) on Mentor avatars for metadata purposes, but pipeline exclusion is determined by pool, not phase
8. A database migration SHALL update all existing avatars with `warming_phase == 0` to `pool = "mentor"` and `warming_phase = 1` (their actual phase is irrelevant since pool gates them)

### Requirement 2: Phase 0 — Incubation Definition

**User Story:** As a system operator, I want new/low-karma avatars to enter an Incubation phase that protects them from AutoMod kills, so that fresh accounts build minimum viability before entering the hobby pipeline.

#### Acceptance Criteria

1. THE system SHALL recognize `warming_phase == 0` as the Incubation phase (not Mentor — Mentor is now pool-based)
2. WHEN a new avatar is created with `reddit_karma_comment < 10` AND `reddit_account_age < 14 days`, THE system SHALL assign `warming_phase = 0`
3. WHEN a new avatar is created with `reddit_karma_comment >= 10` OR `reddit_account_age >= 14 days`, THE system SHALL assign `warming_phase = 1` (current behavior preserved for pre-warmed imports)
4. THE Incubation phase SHALL have the following characteristics:
   - Maximum 1 comment per day
   - Only "safe subreddits" (system-configured list)
   - Mandatory human approval (override `auto_approve_drafts` to false)
   - Simple/short prompts (max 40 words target, Gemini Flash)
   - Zero brand mentions
   - Zero professional content

### Requirement 3: Phase 0 Content Restrictions (Incubation Policy)

**User Story:** As a system operator, I want Incubation avatars restricted to ultra-safe engagement only, so that their first comments survive AutoMod scrutiny.

#### Acceptance Criteria

1. WHILE an avatar is in Phase 0, THE PhasePolicy SHALL allow only comments of type "hobby"
2. WHILE an avatar is in Phase 0, THE PhasePolicy SHALL allow only subreddits from the system setting `incubation_safe_subreddits` (JSON list of subreddit names)
3. WHILE an avatar is in Phase 0, THE PhasePolicy SHALL enforce a maximum of 1 comment per day
4. WHILE an avatar is in Phase 0, THE PhasePolicy SHALL block any comment containing brand mentions of any level
5. WHILE an avatar is in Phase 0, THE system SHALL force `auto_approve_drafts = false` behavior (drafts require human approval even if avatar flag is set)
6. THE default value for `incubation_safe_subreddits` SHALL be: `["AskReddit", "CasualConversation", "NoStupidQuestions", "TooAfraidToAsk", "Showerthoughts", "LifeProTips"]`
7. THE `incubation_safe_subreddits` list SHALL be configurable via SystemSetting without code changes

### Requirement 4: Phase 0 → Phase 1 Graduation

**User Story:** As a system operator, I want Incubation avatars to automatically graduate to Phase 1 when they demonstrate minimum viability, so that the warming pipeline begins without manual intervention.

#### Acceptance Criteria

1. THE PhaseEvaluator SHALL evaluate Phase 0 → Phase 1 eligibility using ALL of:
   - Reddit account age >= 7 days
   - `reddit_karma_comment` >= 10
   - At least 3 comments with status "posted" (system-generated or manually posted)
   - Zero comments with `is_deleted = true` in the last 7 days (no AutoMod kills)
2. WHEN all Phase 0 → Phase 1 criteria are met, THE PhaseTransitionManager SHALL promote the avatar to Phase 1
3. THE graduation thresholds SHALL be configurable via SystemSettings with prefix `phase_gate_p0_` (keys: `min_age_days`, `min_karma`, `min_posted_comments`, `max_deleted_comments`)
4. THE default thresholds SHALL be: age=7, karma=10, posted=3, max_deleted=0
5. THE daily evaluation task (06:00) SHALL include Phase 0 avatars in its batch (unlike the old Mentor which was skipped)
6. WHEN graduation occurs, THE system SHALL record a `phase_promotion` ActivityEvent with previous_phase=0, new_phase=1, and criteria values

### Requirement 5: Phase 0 as Recovery Destination (Demotion Instead of Freeze)

**User Story:** As a system operator, I want avatars that lose credibility to be demoted to Phase 0 (Incubation) instead of being frozen, so that monitoring continues, recovery is automatic, and there is no deadlock where a frozen avatar can never prove it recovered.

#### Acceptance Criteria

1. WHEN a shadowban is detected for ANY phase avatar (1, 2, or 3), THE system SHALL demote to Phase 0 AND set `is_shadowbanned = true` — but SHALL NOT set `is_frozen = true`
2. WHEN CQS drops to "lowest" for a Phase 2+ avatar, THE system SHALL demote to Phase 0 — but SHALL NOT freeze
3. WHEN survival_rate < 70% (7-day window, min 5 sample) for Phase 1, THE system SHALL demote to Phase 0
4. THE `check_demotion_triggers` logic SHALL change `max(1, current_phase - 1)` to target Phase 0 directly for shadowban/CQS triggers (not "current - 1")
5. WHEN an avatar is demoted to Phase 0, THE system SHALL record an `auto_downgrade` ActivityEvent with target_phase=0 and trigger_reason
6. WHILE in Phase 0, health checks and CQS monitoring SHALL continue to run for the avatar (no `is_frozen` exclusion since avatar is NOT frozen)
7. Phase 0 avatars with `is_shadowbanned = true` SHALL still be allowed 1/day generation in safe subs — this activity serves as shadowban probe (if comment gets karma → shadowban may be lifted)
8. THE system SHALL freeze an avatar ONLY when:
   - Reddit returns 404/403 (account suspended/deleted — not recoverable)
   - Admin manual action
   - Phase 0 without graduation progress for > 30 days (configurable via `phase0_freeze_timeout_days` setting)
9. WHEN a Phase 0 avatar's shadowban clears (detected by health check visibility probe), THE system SHALL set `is_shadowbanned = false` and emit `shadowban_cleared` ActivityEvent. Avatar remains in Phase 0 and graduates normally via Phase 0 → 1 criteria.
10. WHEN a Phase 0 avatar's CQS improves from "lowest", THE system SHALL emit `cqs_recovery_detected` ActivityEvent. Avatar remains in Phase 0 and graduates normally.

### Requirement 6: EPG / Budget / Smart Scoring Integration

**User Story:** As a system operator, I want Phase 0 avatars to receive minimal pipeline resources, so that they participate in the system without over-exposure.

#### Acceptance Criteria

1. THE `AttentionBudget.from_avatar()` SHALL return `max_comments=1, max_posts=0` for Phase 0 avatars
2. THE Smart Scoring service SHALL use Phase 0's safe subreddits (from `incubation_safe_subreddits` setting) as the available subreddit list
3. THE hobby pipeline (`generate_hobby_comments`) SHALL respect Phase 0's 1/day limit and safe subreddit restriction
4. THE EPG Portfolio Manager SHALL include Phase 0 avatars in Source 2 (hobby) only, limited to 1 slot/day
5. IF a Phase 0 avatar has `auto_approve_drafts = true`, THE EPG auto-approve logic SHALL NOT auto-approve — require human confirmation

### Requirement 7: Generation Prompt for Phase 0

**User Story:** As a system operator, I want Incubation avatars to produce ultra-simple, short comments that blend in as genuine newcomer activity, so that AutoMod and human moderators do not flag them.

#### Acceptance Criteria

1. THE hobby generation prompt for Phase 0 SHALL target 10-30 words (shorter than Phase 1's 5-60 range)
2. THE prompt SHALL instruct the LLM to write as a "curious newcomer" — asking questions, sharing brief reactions, expressing agreement with slight personal detail
3. THE prompt SHALL FORBID: assertive opinions, technical advice, links, formatting (bold, lists, headers), and multi-paragraph responses
4. THE prompt SHALL use Gemini Flash (same model as Phase 1 hobby)
5. THE prompt temperature SHALL be 0.9 (slightly more creative/varied than Phase 1's 0.85 to avoid repetitive short patterns)

### Requirement 8: Admin UI Changes

**User Story:** As an administrator, I want the UI to clearly distinguish between Mentor (pool-based) and Incubation (Phase 0), so that operational decisions are unambiguous.

#### Acceptance Criteria

1. THE admin avatar list SHALL display Phase 0 as "Incubation" with a distinct badge color (e.g., gray/blue)
2. THE admin avatar list SHALL display Mentor as a pool badge (existing behavior, not a phase label)
3. THE "Phase Override" dropdown SHALL include options: 0 (Incubation), 1 (Hobby), 2 (Professional), 3 (Brand)
4. THE admin avatar detail page SHALL show Phase 0 graduation criteria progress (age, karma, posted count, deleted count)
5. THE admin "Set as Mentor" action SHALL set `avatar.pool = "mentor"` without changing `warming_phase`
6. THE admin "Remove Mentor" action SHALL set `avatar.pool` back to its previous value (b2b/b2c/warm) and the avatar resumes at its current `warming_phase`

### Requirement 9: Migration Safety

**User Story:** As an engineer, I want the migration to be safe and reversible, so that existing production behavior is preserved during rollout.

#### Acceptance Criteria

1. THE Alembic migration SHALL:
   - Update all avatars with `warming_phase = 0` to `pool = 'mentor'` and `warming_phase = 1`
   - NOT change any avatar with `warming_phase` in (1, 2, 3)
   - Add system setting `incubation_safe_subreddits` with default JSON value
2. THE migration SHALL be reversible (downgrade restores `warming_phase = 0` for `pool = 'mentor'` avatars)
3. A feature flag `incubation_phase_enabled` (SystemSetting) SHALL gate the new behavior:
   - When "false" (default at deploy): Phase 0 avatars treated as Phase 1 (legacy behavior)
   - When "true": Full Incubation rules active
4. THE feature flag SHALL allow gradual rollout: enable for specific clients first, then globally

### Requirement 10: Phase Labels Update

**User Story:** As all system users, I want consistent phase labeling throughout the system, so that the naming is clear and unambiguous.

#### Acceptance Criteria

1. THE system SHALL use these phase labels everywhere (UI, logs, events, API):
   - Phase 0: "Incubation"
   - Phase 1: "Credibility Building" (unchanged)
   - Phase 2: "Content Seeding" (unchanged)
   - Phase 3: "Brand Integration" (unchanged)
2. THE system SHALL use "Mentor" as a pool label, never as a phase label
3. ALL ActivityEvent messages, log strings, and API responses referencing "Phase 0 (Mentor)" SHALL be updated to distinguish:
   - `pool == "mentor"` → "Mentor (pool): excluded from pipelines"
   - `warming_phase == 0` → "Phase 0 (Incubation): ultra-conservative engagement"
