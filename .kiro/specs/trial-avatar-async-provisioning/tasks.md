# Implementation Plan: Trial Avatar Async Provisioning

## Overview

This plan implements the AvatarDraft state machine, async BYOA pipeline, ExternalRequestScheduler, and client-active-state invariant to close the trial execution gap. Tasks are ordered by dependency: data model first, then services, then tasks, then routes/UI, then integration.

## Task Dependency Graph

```json
{
  "waves": [
    ["1. AvatarDraft Model + Migration"],
    ["2. ExternalRequestScheduler Service"],
    ["3. BYOA Celery Tasks", "4. BYOA Pipeline Service", "5. Avatar Invariant Service", "6. Onboarding Step Restructure (Step 4 Merge)"],
    ["7. BYOA Step UI (Step 5 Routes + Templates)", "8. Step 6 Activation Guard", "9. Onboarding Stall Detection", "10. Trial Limit Enforcement"],
    ["11. Integration Testing"],
    ["12. Deploy + Backfill"]
  ]
}
```

## Tasks

- [x] 1. AvatarDraft Model + Migration
  Create `app/models/avatar_draft.py` with AvatarDraft SQLAlchemy model. Fields: id (UUID PK), reddit_username (String 20), client_id (UUID FK clients), created_by_user_id (UUID FK users), status (String 20, default pending_fetch), error_message (Text nullable), reddit_snapshot (JSONB nullable), ai_analysis (JSONB nullable), avatar_id (UUID FK avatars nullable), created_at, updated_at, fetch_started_at, fetch_completed_at, analysis_started_at, analysis_completed_at, confirmed_at (all DateTime tz nullable). Add partial unique index on (reddit_username, client_id) WHERE status IN ('pending_fetch', 'analyzing', 'ready_for_review'). Create Alembic migration. Register in models init. Requirements: R1.

- [x] 2. ExternalRequestScheduler Service
  Create `app/services/external_scheduler.py`. Implement multi-service rate limiter extending ScrapeRateLimiter for keys "reddit" (30 RPM) and "ai_llm" (60 RPM). Implement Redis semaphore for global concurrency cap (default 10) using INCR/DECR on key `external_request:active_count`. Methods: acquire(service, priority) -> bool, release(service), wait_for_slot(service, priority, max_wait=30) -> bool. Add SystemSetting lookup for config overrides. Log all acquisitions with service_name, duration_ms, success/failure, retry_count, priority. Requirements: R3.

- [x] 3. BYOA Celery Tasks
  Create `app/tasks/byoa.py`. Implement fetch_reddit_profile_for_draft (bind=True, max_retries=3): load draft, verify status=pending_fetch, call fetch_reddit_profile() via scheduler, store reddit_snapshot, chain to analyze task. Handle NotFound/suspended as fetch_failed, transient errors as retry. Implement analyze_reddit_profile_for_draft (bind=True, max_retries=3): load draft, call analyze_avatar_with_ai() via scheduler, store ai_analysis, transition to ready_for_review. Implement check_stale_avatar_drafts (periodic every 10 min): find stuck drafts older than 60 min, transition to failure, notify user. Register in Celery Beat. Requirements: R1, R2.

- [x] 4. BYOA Pipeline Service
  Create `app/services/byoa_pipeline.py`. Implement create_avatar_draft(): validate username, check global Avatar uniqueness, check trial limit, check client-scoped draft uniqueness, create record, enqueue fetch task, return draft. Implement confirm_avatar_draft(): verify ready_for_review status, create Avatar from draft data + user edits (warming_phase=1, active=True, pool=b2b), set draft confirmed + avatar_id, trigger post-onboarding pipeline via existing trigger_avatar_onboarding, return avatar. Implement reject_avatar_draft(): transition to rejected. Implement cancel_draft(): for in-progress drafts, mark rejected. Implement check_trial_avatar_limit(): count non-terminal drafts + active avatars, return (allowed, error_msg). Requirements: R1, R2, R7.

- [x] 5. Avatar Invariant Service
  Create `app/services/avatar_invariant.py`. Implement has_active_avatar(client_id, db) -> bool: query Avatar with active=True and client_ids containing str(client_id). Implement enforce_invariant_on_deactivation(client_id, db): if not has_active_avatar then set client.is_active=False. Implement enforce_invariant_on_activation(client_id, db): if client.onboarding_completed_at and not client.is_active then reactivate. Modify admin avatar freeze/unassign routes to call deactivation enforcement. Implement check_avatar_invariant Celery task (daily 02:30): find violating clients, deactivate, notify owner/partner. Register in Celery Beat. Requirements: R5.

- [x] 6. Onboarding Step Restructure (Step 4 Merge)
  Modify `app/routes/onboarding.py`: merge step4_save (voice/guardrails) and step5_save (keywords/subreddits) into combined Step 4. After step 4 save, set current_onboarding_step=5 and redirect to /onboard/step/5 (BYOA). Create/modify `app/templates/onboarding/step4.html` to show both voice/guardrails fields AND keywords/subreddits fields on one page. Keep existing AI suggest HTMX buttons for both sections. Step progression now goes 4 -> 5 (BYOA) -> 6 (activate). Requirements: R6.

- [x] 7. BYOA Step UI (Step 5 Routes + Templates)
  Add routes in onboarding.py: GET /onboard/step/5 (render BYOA page), POST step/5/submit-username (create draft, return progress partial), GET step/5/draft-status (return status partial), POST step/5/confirm (confirm draft, redirect step 6), POST step/5/reject (reject, return input), POST step/5/retry (cancel old, create new). Create step5.html template with username form + byoa-result div. Create partials: byoa_progress.html (polling div with hx-trigger every 2s + data-poll-count), byoa_preview.html (editable form with confirm/reject), byoa_error.html (error + retry), byoa_confirmed.html (summary card). Requirements: R4, R6.

- [x] 8. Step 6 Activation Guard
  Modify step6_activate() in onboarding.py: before quality gate check, call has_active_avatar(client.id, db). If False: return error "At least one confirmed avatar is required". Update step6.html template: show avatar status indicator, disable Activate button if no avatar, add link back to Step 5. Requirements: R5.

- [x] 9. Onboarding Stall Detection
  Implement check_onboarding_stall Celery task in byoa.py: query avatars created 24-48 hours ago, check if CommentDraft exists for that client, if zero drafts create ActivityEvent(type=onboarding_stall_detected) with client_id, avatar_id, last pipeline step. Register hourly in Celery Beat. Add notification trigger in generation service: when first draft created for new avatar, call notify_client with success message. Add check for missing subreddits/keywords: if pipeline dispatched without config, notify client that setup required. Requirements: R8.

- [x] 10. Trial Limit Enforcement
  Integrate check_trial_avatar_limit into BYOA flow (already in byoa_pipeline.py Task 4). Update existing _check_trial_limit in avatar_onboard.py to also count non-terminal AvatarDrafts. Add limit check in step 5 GET route: show summary-only view if trial limit reached with confirmed avatar. Add limit check in submit-username route: reject with message if limit reached. Verify upgrade path: plan_type change lifts restriction (governed by max_avatars field). Requirements: R7.

- [x] 11. Integration Testing
  Test full BYOA flow end-to-end: submit username, poll status, confirm, verify avatar created. Test failure paths: invalid username gives fetch_failed; AI error gives analysis_failed. Test trial limit: second submission blocked; failed draft allows retry. Test invariant: activation blocked without avatar; deactivation pauses client; reactivation on assign. Test stale cleanup: draft stuck 60+ min gets failed. Test step 4 merge: voice + keywords save together. Test backward compat: admin avatar onboard unchanged. Test returning user: ready_for_review shown on reload. Requirements: All.

- [x] 12. Deploy + Backfill
  Run Alembic migration on production. Deploy code (tasks + services + routes + templates). Verify Celery Beat picks up new periodic tasks (check_stale every 10 min, invariant daily 02:30, stall hourly). Run check_avatar_invariant manually to flag existing violating clients. Monitor stale draft cleanup for 24 hours. Verify admin avatar onboarding unaffected. Monitor first trial signup through BYOA flow. Requirements: All.

## Notes

- Existing admin avatar onboarding (/clients/{id}/avatar-onboard) remains unchanged — it creates Avatar directly for managed clients
- The ExternalRequestScheduler wraps existing infrastructure (Redis + Celery) without new dependencies
- Step numbering (1-6) stays the same for users; only content of steps 4 and 5 changes
- The daily integrity check (Task 5) serves as a safety net for edge cases missed by real-time enforcement
- Trial limit uses combined count: non-terminal drafts + active avatars <= 1
