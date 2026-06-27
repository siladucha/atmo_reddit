# Implementation Plan: Phase 0 Incubation + Mentor Extraction

## Overview

Refactor avatar phase system: extract Mentor into pool classification, repurpose Phase 0 as Incubation for fresh/low-karma avatars. Linear state machine: 0 → 1 → 2 → 3.

Implementation order: migration first, then Mentor extraction (safe — equivalent behavior), then Incubation logic (behind feature flag), then UI, then enable.

## Tasks

- [ ] 1. Database migration
  - [ ] 1.1 Create Alembic migration `incub01`
    - UPDATE all avatars with `warming_phase = 0` → set `pool = 'mentor'`, `warming_phase = 1`
    - INSERT system_settings: `incubation_safe_subreddits` = `'["AskReddit","CasualConversation","NoStupidQuestions","TooAfraidToAsk","Showerthoughts","LifeProTips"]'`
    - INSERT system_settings: `incubation_phase_enabled` = `'false'`
    - INSERT system_settings: `phase_gate_p0_min_age_days` = `'7'`
    - INSERT system_settings: `phase_gate_p0_min_karma` = `'10'`
    - INSERT system_settings: `phase_gate_p0_min_posted_comments` = `'3'`
    - INSERT system_settings: `phase_gate_p0_max_deleted_comments` = `'0'`
    - Downgrade: reverse all changes (set `warming_phase = 0` where `pool = 'mentor'`, delete settings)
    - _Requirements: 1.8, 3.6, 3.7, 4.3, 9.1, 9.2_

- [ ] 2. Mentor extraction (pool-based gating)
  - [ ] 2.1 Update `posting_safety.py` Gate #5
    - Replace `if avatar.warming_phase == 0` with `if avatar.pool == "mentor"`
    - Update reason string: "Mentor (pool): excluded from automated posting"
    - _Requirements: 1.5_

  - [ ] 2.2 Update `PhasePolicy.check_comment_allowed()` in `phase.py`
    - Replace the `if phase == 0: return blocked("Phase 0 Mentor")` block with `if avatar.pool == "mentor": return blocked("Mentor: excluded")`
    - Move this check BEFORE the phase switch (pool is checked before phase)
    - _Requirements: 1.6_

  - [ ] 2.3 Update `PhaseEvaluator.evaluate()` in `phase.py`
    - Replace `if current_phase == 0: return (False, {})` with `if avatar.pool == "mentor": return EvaluationResult(action="none")`
    - _Requirements: 1.4_

  - [ ] 2.4 Update `PhaseEvaluator.check_promotion_eligibility()` in `phase.py`
    - Replace `if current_phase == 0: return (False, {})` with pool check
    - _Requirements: 1.4_

  - [ ] 2.5 Update `ai_pipeline.py` generate_comments filter
    - Replace `avatar.warming_phase == 0` skip with `avatar.pool == "mentor"` skip
    - _Requirements: 1.3_

  - [ ] 2.6 Update `ai_pipeline.py` generate_hobby_comments filter
    - Replace phase 0 check with pool mentor check
    - _Requirements: 1.3_

  - [ ] 2.7 Update `tasks/epg.py` avatar eligibility
    - Replace phase 0 exclusion with pool mentor exclusion
    - _Requirements: 1.3_

  - [ ] 2.8 Update `PhaseTransitionManager.admin_override()` in `phase.py`
    - Allow target_phase in {0, 1, 2, 3} (already does this)
    - Update docstring to explain Phase 0 = Incubation, Mentor = pool
    - _Requirements: 1.7_

  - [ ] 2.9 Update `smart_scoring.py` pre-filter (if any phase 0 check exists)
    - Verify no phase 0 exclusion exists, or replace with pool check
    - _Requirements: 1.3_

  - [ ] 2.10 Grep and fix any remaining `warming_phase == 0` or `phase == 0` references that mean "Mentor"
    - Search: `warming_phase == 0`, `warming_phase==0`, `phase == 0`, `phase==0`, `warming_phase = 0`
    - Evaluate each: if it means "exclude from pipeline" → change to `pool == "mentor"`
    - If it means "incubation logic" → leave for task 3
    - _Requirements: 1.1, 1.3_

- [ ] 3. Phase 0 Incubation logic (behind feature flag)
  - [ ] 3.1 Add `_P0_DEFAULTS` and Phase 0 threshold loading to `PhaseEvaluator.get_thresholds()`
    - Add `_P0_DEFAULTS = {"min_age_days": 7, "min_karma": 10, "min_posted_comments": 3, "max_deleted_comments": 0}`
    - Add `if current_phase == 0:` branch loading `phase_gate_p0_*` settings
    - _Requirements: 4.3, 4.4_

  - [ ] 3.2 Add `_check_phase0()` to `PhasePolicy`
    - Check feature flag `incubation_phase_enabled`; if "false" → delegate to `_check_phase1()` (backward compat)
    - If enabled: enforce hobby only, safe subreddits, 1/day limit, zero brand
    - Load safe subs from `get_setting(db, "incubation_safe_subreddits")`, parse JSON
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 9.3_

  - [ ] 3.3 Add Phase 0 → 1 promotion logic to `PhaseEvaluator.check_promotion_eligibility()`
    - Check feature flag; if disabled, Phase 0 avatars → immediately eligible (promote to 1)
    - If enabled: evaluate age, karma, posted_count, deleted_count against P0 thresholds
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [ ] 3.4 Update `check_demotion_triggers()` — demotion to Phase 0 instead of freeze
    - Change `if avatar.warming_phase <= 1: return (False, ...)` to `if avatar.warming_phase <= 0: return (False, ...)`
    - Shadowban → target_phase = 0 (from ANY phase, not just Phase 2+)
    - CQS lowest (Phase 2+) → target_phase = 0 (NOT freeze)
    - Survival <70% (Phase 1+) → target_phase = 0
    - Karma drop (Phase 2+) → target_phase = current - 1 (gradual)
    - Check feature flag; if disabled, keep floor at 1 and preserve old freeze behavior
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ] 3.5 Remove CQS auto-freeze from `cqs_checker.py`
    - Remove the block: `if cqs_level == "lowest" and not avatar.is_frozen and warming_phase >= 2: freeze`
    - Instead: trust that next phase evaluation (daily 06:00) will demote to Phase 0
    - Keep CQS recovery detection logging (already works)
    - _Requirements: 5.2, 5.6_

  - [ ] 3.6 Add Phase 0 timeout freeze
    - In `evaluate_all_avatar_phases` task (or new daily task): if avatar in Phase 0 for > N days → freeze
    - N = `phase0_freeze_timeout_days` system setting (default 30)
    - Freeze reason: "Phase 0 timeout: {days} days without graduation"
    - _Requirements: 5.8_

  - [ ] 3.7 Add shadowban clearance detection in `health_checker.py`
    - If previous status was "shadowbanned" and new status is "active" → set `is_shadowbanned = False`
    - Emit `shadowban_cleared` ActivityEvent
    - Avatar stays in Phase 0, graduates normally
    - _Requirements: 5.9_

  - [ ] 3.8 Remove `is_frozen` filter from `health_check_all_avatars`
    - Frozen avatars (from suspend/timeout) still need health monitoring
    - Phase 0 shadowbanned avatars are NOT frozen → already included
    - But suspended-frozen avatars should also be re-checked (suspension may be temporary)
    - _Requirements: 5.6_

  - [ ] 3.9 Add Phase 0 auto-approve override
    - In `portfolio_manager.py` (or EPG auto-approve logic): if `warming_phase == 0`, force slot status to "generated" (skip auto-approve)
    - _Requirements: 6.5_

  - [ ] 3.10 Add `AttentionBudget` Phase 0 handling
    - In `AttentionBudget.from_avatar()`: if `warming_phase == 0` → `max_comments=1, max_posts=0`
    - _Requirements: 6.1_

  - [ ] 3.11 Add `get_avatar_available_subreddit_names()` Phase 0 branch
    - If `phase == 0`: return safe subreddits from setting (parsed JSON list)
    - _Requirements: 6.2_

- [ ] 4. Generation prompt for Phase 0
  - [ ] 4.1 Add `_build_incubation_system_prompt()` in `ai_pipeline.py`
    - Write incubation prompt: curious newcomer, 10-30 words, questions/reactions only
    - Forbid: opinions, advice, links, formatting, multi-paragraph
    - Temperature: 0.9
    - Model: Gemini Flash (same as hobby)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ] 4.2 Wire Phase 0 prompt into `generate_hobby_comments`
    - If `avatar.warming_phase == 0` AND feature flag enabled → use incubation prompt instead of standard hobby prompt
    - Respect 1/day limit at generation level (don't generate more than 1)
    - _Requirements: 6.3, 6.4, 7.1_

- [ ] 5. Avatar creation — initial phase assignment
  - [ ] 5.1 Update avatar creation in `routes/avatar_onboard.py`
    - After PRAW profile fetch: if `reddit_karma_comment < 10` AND `account_age < 14 days` → `warming_phase = 0`
    - Otherwise → `warming_phase = 1` (current behavior)
    - Gate behind feature flag (if disabled, always phase 1)
    - _Requirements: 2.2, 2.3_

  - [ ] 5.2 Update avatar creation in `routes/onboarding.py` (self-service wizard)
    - Same logic: check karma + age at avatar connect step → assign phase 0 or 1
    - Gate behind feature flag
    - _Requirements: 2.2, 2.3_

  - [ ] 5.3 Update admin avatar creation (if manual create exists)
    - Apply same logic or allow admin to choose
    - _Requirements: 2.2_

- [ ] 6. Admin UI changes
  - [ ] 6.1 Update phase labels in templates
    - Phase 0 badge: "Incubation" (gray/blue color)
    - Mentor: shown as pool badge (separate from phase)
    - Update `admin_avatars.html`, `admin_avatar_detail.html`, relevant partials
    - _Requirements: 8.1, 8.2, 10.1, 10.2_

  - [ ] 6.2 Update "Phase Override" dropdown
    - Add option: "0 — Incubation"
    - Existing: "1 — Credibility Building", "2 — Content Seeding", "3 — Brand Integration"
    - _Requirements: 8.3_

  - [ ] 6.3 Add Phase 0 graduation progress to avatar detail
    - Show: age (X/7 days), karma (X/10), posted (X/3), deleted (X/0)
    - Only visible when `warming_phase == 0`
    - _Requirements: 8.4_

  - [ ] 6.4 Add "Set as Mentor" / "Remove Mentor" admin actions
    - "Set as Mentor": sets `pool = "mentor"` (does NOT change warming_phase)
    - "Remove Mentor": sets `pool` back to previous (b2b/b2c/warm based on client assignment)
    - _Requirements: 8.5, 8.6_

  - [ ] 6.5 Update client portal avatar display (if Phase 0 visible to clients)
    - Show "Warming up..." status for Phase 0 avatars
    - Hide generation metrics (they'll be near-zero)
    - _Requirements: 10.1_

- [ ] 7. Logging and events
  - [ ] 7.1 Update all ActivityEvent messages that reference "Phase 0 (Mentor)"
    - Distinguish: `pool == "mentor"` → "Mentor (pool)" vs `phase == 0` → "Phase 0 (Incubation)"
    - Search templates, services, tasks for "Mentor" strings
    - _Requirements: 10.3_

  - [ ] 7.2 Add `incubation_graduation` activity event type
    - Emitted when Phase 0 → 1 promotion happens
    - Include criteria values in event_metadata
    - _Requirements: 4.6_

- [ ] 8. Testing and verification
  - [ ] 8.1 Verify migration on local DB
    - Run migration up/down
    - Confirm Mentor avatars moved to pool correctly
    - Confirm settings created
    - _Requirements: 9.1, 9.2_

  - [ ] 8.2 Test Mentor extraction (feature flag OFF)
    - Confirm pipeline still skips Mentor avatars
    - Confirm no behavior change for Phase 1/2/3 avatars
    - Confirm phase override still works
    - _Requirements: 1.3, 1.5, 1.6, 1.7_

  - [ ] 8.3 Test Incubation (feature flag ON)
    - Create test avatar with low karma → should get Phase 0
    - Verify 1/day limit, safe subs only, no auto-approve
    - Verify graduation after criteria met
    - Verify demotion from Phase 1 → 0 on shadowban
    - _Requirements: 2.2, 3.1-3.7, 4.1-4.6, 5.1-5.4_

  - [ ] 8.4 Test backward compatibility (feature flag OFF)
    - Confirm no Phase 0 avatars are created
    - Confirm demotion floor stays at Phase 1
    - Confirm all existing tests pass
    - _Requirements: 9.3, 9.4_

- [ ] 9. Deploy and enable
  - [ ] 9.1 Deploy to staging with feature flag OFF
    - Run migration
    - Verify Mentor avatars behave identically
    - Run full pipeline cycle
    - _Requirements: 9.1_

  - [ ] 9.2 Enable feature flag on staging
    - Create test avatar with fresh account
    - Verify full Incubation → Phase 1 graduation flow
    - Verify demotion to Phase 0 works
    - _Requirements: 9.3_

  - [ ] 9.3 Deploy to production (with user permission)
    - Feature flag OFF initially
    - Enable after staging verification
    - _Requirements: 9.3, 9.4_

- [ ] 10. Documentation updates
  - [ ] 10.1 Update steering files
    - Update `project.md`: Phase 0 = Incubation, Mentor = pool
    - Update `pipeline_safety_architecture.md`: new demotion floor, Phase 0 budget
    - Update `system_diagnostic.md`: state machine description
    - _Requirements: 10.1, 10.2, 10.3_

  - [ ] 10.2 Update RAMP_SYSTEM_DIAGNOSTIC.json
    - Add Phase 0 node to state machine section
    - Update Mentor reference
    - _Requirements: 10.1_
