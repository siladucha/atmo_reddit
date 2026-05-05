# Implementation Plan: Avatar Warming Phases

## Overview

Replace the binary 14-day warmup check with a formal 3-phase progression model. Implementation proceeds bottom-up: database schema first, then supporting types, service components (PhasePolicy → PhaseEvaluator → PhaseTransitionManager), safety integration, Celery task, and finally admin UI.

## Tasks

- [x] 1. Database migration and model changes
  - [x] 1.1 Create Alembic migration for warming phase fields
    - Add `warming_phase` (Integer, default=1), `phase_changed_at` (DateTime, server_default=now), `last_phase_evaluated_at` (DateTime, nullable) to `avatars` table
    - Add `is_deleted` (Boolean, default=False), `reddit_score` (Integer, nullable), `deleted_detected_at` (DateTime, nullable) to `comment_drafts` table
    - Add `brand_domain` (String(255), nullable) to `clients` table
    - Include conditional UPDATE: set `warming_phase=2` for avatars with `reddit_account_created < NOW() - INTERVAL '60 days'`
    - Include downgrade to drop all added columns
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 1.6_

  - [x] 1.2 Update Avatar model with warming phase fields
    - Add `warming_phase`, `phase_changed_at`, `last_phase_evaluated_at` mapped columns to `app/models/avatar.py`
    - _Requirements: 1.1, 1.2, 1.6_

  - [x] 1.3 Update CommentDraft model with deletion tracking fields
    - Add `is_deleted`, `reddit_score`, `deleted_detected_at` mapped columns to `app/models/comment_draft.py`
    - _Requirements: 5.1, 5.2 (survival rate and avg score depend on these fields)_

  - [x] 1.4 Update Client model with brand_domain field
    - Add `brand_domain` mapped column to `app/models/client.py`
    - _Requirements: 12.2_

- [x] 2. Supporting types and enums
  - [x] 2.1 Create phase types module at `app/services/phase_types.py`
    - Define `BrandMentionLevel` enum (explicit_brand_link, explicit_brand_name, inferred_brand)
    - Define `PolicyStatus` enum (allowed, blocked, requires_review)
    - Define `RampUpStage` enum (early, mid, complete)
    - Define `PolicyResult` dataclass (status, reason, brand_mention_level)
    - Define `EvaluationResult` dataclass (action, target_phase, criteria_values, trigger_reason)
    - _Requirements: 12.1, 14.1_

- [x] 3. Implement PhaseTransitionLock
  - [x] 3.1 Create `PhaseTransitionLock` class in `app/services/phase_lock.py`
    - Follow `ScrapeDistributedLock` pattern with KEY_PREFIX="phase_lock:", DEFAULT_TTL=30
    - Implement `acquire(avatar_id, timeout=5)` with polling every 0.5s
    - Implement `release(avatar_id)` using atomic Lua script
    - Use `_RELEASE_SCRIPT` pattern from `distributed_lock.py`
    - _Requirements: 6.8, 6.9_

- [x] 4. Implement PhasePolicy (content restrictions)
  - [x] 4.1 Create `PhasePolicy` class in `app/services/phase.py`
    - Implement `classify_brand_mention(comment_text, client)` — check URL match against `brand_domain`, case-insensitive `brand_name` match, return highest-severity level
    - Implement `get_daily_comment_count(db, avatar)` — count today's approved/posted comments
    - Implement `get_brand_ratio(db, avatar, window_days=7)` — calculate brand comment ratio
    - Implement `get_ramp_up_stage(avatar)` — determine EARLY/MID/COMPLETE based on `phase_changed_at`
    - Implement `check_comment_allowed(db, avatar, comment_type, target_subreddit, comment_text, client, thread_tag)` — enforce phase-specific rules
    - Phase 1: hobby only, hobby_subreddits only, no brand mentions, max 3/day
    - Phase 2: hobby + professional, hobby + business subreddits, block explicit brand, requires_review for inferred, standard daily limit
    - Phase 3: all types allowed, enforce ramp-up constraints, brand ratio, brand links only on "engage" threads
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

  - [ ]* 4.2 Write property test for Phase 1 policy correctness
    - **Property 1: Phase 1 Policy Correctness**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

  - [ ]* 4.3 Write property test for Phase 2 policy correctness
    - **Property 2: Phase 2 Policy Correctness**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**

  - [ ]* 4.4 Write property test for Phase 3 policy with ramp-up
    - **Property 3: Phase 3 Policy with Ramp-Up Correctness**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6**

  - [ ]* 4.5 Write property test for brand mention classification priority
    - **Property 12: Brand Mention Classification Priority**
    - **Validates: Requirements 12.1, 12.2, 12.3, 12.5, 12.6**

- [x] 5. Implement PhaseEvaluator (eligibility checks)
  - [x] 5.1 Add `PhaseEvaluator` class to `app/services/phase.py`
    - Implement `get_thresholds(db, current_phase)` — load from SystemSettings with `phase_gate_` prefix, fallback to defaults
    - Implement `compute_comment_survival_rate(db, avatar, window_days)` — (total_posted - deleted) / total_posted
    - Implement `compute_avg_comment_score(db, avatar, window_days)` — mean reddit_score over window
    - Implement `should_piggyback(avatar)` — True if `last_phase_evaluated_at` is None or > 4 hours ago
    - Implement `check_promotion_eligibility(db, avatar)` — check all criteria for next phase (P1→P2: age≥60, karma≥100, activity≥20, survival≥80%; P2→P3: age≥150, karma≥500, activity≥50, survival≥85%, avg_score≥2.0)
    - Implement `check_demotion_triggers(db, avatar)` — shadowban→Phase 1, survival<70%→demote by 1, karma velocity drop>50%→demote by 1
    - Implement `evaluate(db, avatar)` — orchestrate promotion/demotion checks, update `last_phase_evaluated_at`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 6.5, 6.7, 11.1, 11.2, 11.3, 11.6, 15.2, 15.3, 15.5_

  - [ ]* 5.2 Write property test for eligibility evaluation correctness
    - **Property 4: Eligibility Evaluation Correctness**
    - **Validates: Requirements 5.1, 5.2, 5.3**

  - [ ]* 5.3 Write property test for piggyback evaluation cooldown
    - **Property 6: Piggyback Evaluation Cooldown**
    - **Validates: Requirements 6.7, 15.2, 15.3**

  - [ ]* 5.4 Write property test for inactive avatar evaluation skip
    - **Property 14: Inactive Avatar Evaluation Skip**
    - **Validates: Requirements 6.5**

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement PhaseTransitionManager (promotions, demotions, overrides)
  - [x] 7.1 Add `PhaseTransitionManager` class to `app/services/phase.py`
    - Implement `promote(db, avatar, criteria_values)` — acquire lock, update `warming_phase` to current+1, update `phase_changed_at`, record `phase_promotion` ActivityEvent, release lock
    - Implement `demote(db, avatar, target_phase, trigger_reason)` — acquire lock, update fields, record `auto_downgrade` ActivityEvent; if already Phase 1, log but don't demote
    - Implement `admin_override(db, avatar, target_phase, admin_user_id, reason)` — validate target_phase in {1,2,3}, acquire lock, update fields, record `phase_override` ActivityEvent
    - Implement `_record_event(db, avatar, event_type, previous_phase, new_phase, metadata)` — create ActivityEvent record
    - _Requirements: 6.1, 6.2, 6.3, 6.8, 6.9, 7.1, 7.2, 7.3, 7.5, 11.1, 11.4, 11.5, 11.7_

  - [ ]* 7.2 Write property test for promotion execution invariants
    - **Property 5: Promotion Execution Invariants**
    - **Validates: Requirements 6.1, 6.2, 6.3**

  - [ ]* 7.3 Write property test for admin override execution
    - **Property 7: Admin Override Execution**
    - **Validates: Requirements 7.1, 7.2, 7.3**

  - [ ]* 7.4 Write property test for shadowban demotion
    - **Property 10: Shadowban Demotion**
    - **Validates: Requirements 11.1, 11.4, 11.5**

  - [ ]* 7.5 Write property test for quality degradation demotion
    - **Property 11: Quality Degradation Demotion**
    - **Validates: Requirements 11.2, 11.3, 11.4, 11.5, 11.7**

  - [ ]* 7.6 Write property test for new avatar phase defaults
    - **Property 13: New Avatar Phase Defaults**
    - **Validates: Requirements 1.3**

- [x] 8. Safety service integration
  - [x] 8.1 Integrate PhasePolicy into `check_avatar_can_post()` in `app/services/safety.py`
    - Remove the existing `WARMUP_DAYS` / `WARMUP_MAX_PER_DAY` binary check (Check 2)
    - Add PhasePolicy call as the first content check after active/shadowban checks
    - Pass `comment_type`, target subreddit, comment text, and client to `PhasePolicy.check_comment_allowed()`
    - If PhasePolicy returns blocked → return `SafetyCheckResult(allowed=False)` with phase restriction reason
    - If PhasePolicy returns `requires_review` → return appropriate result
    - Log `policy_block` ActivityEvent when PhasePolicy blocks a comment
    - Add piggyback evaluation: call `PhaseEvaluator.should_piggyback()` and if True, run `evaluate()`
    - Keep existing rate limit checks (daily limit, type limit, time gap, brand ratio) as additional constraints for Phase 3
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 15.2_

  - [ ]* 8.2 Write property test for policy block logging
    - **Property 8: Policy Block Logging**
    - **Validates: Requirements 8.2, 8.6**

- [x] 9. Update avatar health endpoint
  - [x] 9.1 Update `get_avatar_health()` in `app/services/safety.py`
    - Add `warming_phase` (integer 1-3) to return dictionary
    - Add `phase_label` (string mapping: 1→"Credibility Building", 2→"Content Seeding", 3→"Brand Integration")
    - Add `phase_progress` dictionary with current values vs thresholds for next phase criteria (karma, age, activity, survival_rate, avg_score)
    - Add `phase_eligible_for_next` boolean (call `PhaseEvaluator.check_promotion_eligibility()`)
    - Remove the existing `in_warmup` boolean field
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [ ]* 9.2 Write property test for health endpoint phase fields
    - **Property 9: Health Endpoint Phase Fields**
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4**

- [x] 10. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Celery daily evaluation task
  - [x] 11.1 Create `evaluate_all_avatar_phases` task in `app/tasks/ai_pipeline.py`
    - Query all active, non-shadowbanned avatars
    - For each avatar, call `PhaseEvaluator.evaluate(db, avatar)`
    - If evaluation returns promote → call `PhaseTransitionManager.promote()`
    - If evaluation returns demote → call `PhaseTransitionManager.demote()`
    - Handle per-avatar failures independently (log error, continue with next avatar)
    - _Requirements: 6.4, 6.5, 11.6, 15.4_

  - [x] 11.2 Register daily evaluation task in Celery beat schedule
    - Add `evaluate-avatar-phases-daily` entry to `beat_schedule` in `app/tasks/worker.py`
    - Schedule at a suitable time (e.g., `crontab(hour=6, minute=0)`)
    - Add `"app.tasks.ai_pipeline"` to include list if not already present
    - _Requirements: 6.4, 15.4_

- [x] 12. On-demand evaluation after comment posting
  - [x] 12.1 Add post-posting evaluation trigger
    - In the appropriate location where comment status changes to "posted", call `PhaseEvaluator.evaluate()` for the posting avatar
    - Respect the 4-hour cooldown via `should_piggyback()` check
    - _Requirements: 6.6, 15.1, 15.5_

- [x] 13. Admin phase override endpoint
  - [x] 13.1 Create admin override route for phase changes
    - Add POST endpoint at `/admin/avatars/{avatar_id}/phase-override` in admin routes
    - Accept `target_phase` (int) and `reason` (str) in request body
    - Require superuser authentication (`require_superuser` dependency)
    - Call `PhaseTransitionManager.admin_override()`
    - Return validation error if target_phase not in {1, 2, 3}
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

- [x] 14. Admin UI — phase visibility
  - [x] 14.1 Update avatar list page with phase badge
    - Add warming phase column/badge to the admin avatar list template
    - Display phase number with descriptive label (Phase 1/2/3)
    - _Requirements: 9.4_

  - [x] 14.2 Update avatar detail page with phase information
    - Display current warming phase with label (Credibility Building / Content Seeding / Brand Integration)
    - Display progress indicators: current values vs required thresholds for next phase (karma, age, activity, survival rate, avg score)
    - Display "eligible for promotion" indicator when all criteria are met
    - Display phase transition history (chronological list of Phase_Transition_Events from activity_events)
    - Add phase override form (HTMX partial) for admin to set phase manually
    - _Requirements: 9.1, 9.2, 9.3, 9.5_

- [x] 15. Update existing tests for safety service changes
  - [x] 15.1 Update `tests/test_safety.py` to account for PhasePolicy integration
    - Update existing safety tests that relied on `WARMUP_DAYS` constant
    - Ensure tests pass with the new phase-based check replacing the binary warmup check
    - Add test for PhasePolicy being called before rate limits
    - _Requirements: 8.1, 8.3_

- [x] 16. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (14 properties total)
- The PhaseTransitionLock follows the proven `ScrapeDistributedLock` pattern already in the codebase
- SystemSettings keys for thresholds use the `phase_gate_` prefix convention
- All phase transitions are recorded as ActivityEvent records for audit trail
