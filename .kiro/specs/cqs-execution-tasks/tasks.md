# Implementation Plan: CQS Execution Tasks

## Overview

Implements periodic CQS check task emails to executors. 9 tasks covering: DB migration, generator service, Celery task, email template, dispatch integration, anti-spam, self-healing verification, kill switch, and deploy.

## Task Dependency Graph

```json
{
  "waves": [
    {"tasks": [1]},
    {"tasks": [2, 8]},
    {"tasks": [3, 4]},
    {"tasks": [5, 6, 7]},
    {"tasks": [9]}
  ]
}
```

## Tasks

- [x] 1. Database Migration — Make epg_slot_id nullable. Create Alembic migration `cqs_tasks_01`: ALTER TABLE execution_tasks ALTER COLUMN epg_slot_id DROP NOT NULL; drop unique constraint; create partial index WHERE epg_slot_id IS NOT NULL. Update `app/models/execution_task.py` to `nullable=True, index=True`. Verify existing EPG task creation still works. [Requirements: R11]
- [x] 2. CQS Task Generator Service — Create `app/services/cqs_task_generator.py` with `generate_cqs_check_tasks(db)`. Implement interval logic (7d for lowest/young, 30d for mature), eligibility query (active, not frozen, not banned, verified email), pending-task check, and ExecutionTask creation with task_type="cqs_check", epg_slot_id=NULL, subreddit="WhatIsMyCQS", generated_text="What is my cqs?", scheduled_at=07:05 Israel, deadline=48h. Return summary dict. [Requirements: R1, R2, R3, R4, R5]
- [x] 3. Celery Task + Beat Schedule — Create `app/tasks/cqs_tasks.py` with `generate_cqs_check_tasks_all_avatars` shared_task. Check kill switch, call generator, log summary. Add Beat entry in `app/tasks/worker.py`: crontab(hour=7, minute=0) named "cqs-check-tasks-daily". [Requirements: R10, R12]
- [x] 4. CQS Email Template — Add CQS_CHECK_EMAIL_TEMPLATE constant and branch in `compose_task_email` for task_type="cqs_check". Subject: "[RAMP] CQS Check — u/{username} — {code}". Body: login instructions, r/WhatIsMyCQS/submit link, "What is my cqs?" text, action link, 48h deadline note. [Requirements: R7]
- [x] 5. Dispatch Pipeline Integration — Verify dispatch_due_email_tasks handles CQS tasks (no thread_id = skip liveness check). Verify health gate cancels if avatar frozen. Verify expire_overdue handles 48h deadline. Verify _cancel_task_as_locked handles NULL epg_slot_id gracefully. [Requirements: R6, R8]
- [x] 6. Anti-Spam and Interval Logic — Verify: skip if pending CQS task exists; skip if last task within interval. Handle account age calculation (avatar.created_at vs Reddit account age). Test no duplicates on consecutive runs; test new task created after interval passes. [Requirements: R3, R5]
- [x] 7. Self-Healing Loop Verification — Verify: check_cqs_all_avatars upgrades cqs_level → AttentionBudget returns budget>0 → next EPG build generates slots. Verify interval switches from 7d to 30d after recovery. Add code comments documenting recovery timeline. [Requirements: R9]
- [x] 8. System Setting + Kill Switch — Add `cqs_check_tasks_enabled` to seed data (default "true"). Verify Celery task checks it before processing. Existing admin settings page shows it automatically. [Requirements: R12]
- [x] 9. Deploy and Verify — Run migration locally. Test full flow locally. Deploy to staging. Verify Beat fires, tasks created, emails dispatched. Verify existing EPG tasks unaffected. Request production deploy from user. [Requirements: all]

## Notes

- CQS tasks do NOT require an EPG slot or draft — they are standalone execution tasks
- The 48h deadline is intentionally longer than content task deadlines (4h) because CQS checks are non-time-sensitive
- Account age approximation: uses `avatar.created_at` (DB row creation during onboarding). For avatars onboarded on day 1 this equals Reddit age; for later onboarding it underestimates age (conservative — checks more often)
- The self-healing loop: CQS task email → executor posts → bot replies → check_cqs_all_avatars reads → cqs_level updates → budget restores → EPG resumes
