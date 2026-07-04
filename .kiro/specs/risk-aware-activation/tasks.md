# Tasks — Risk-Aware Avatar Activation

## Task 1: Database Migration — activation_route field
- [x] Create Alembic migration `raa01_activation_route`
- [x] Add `activation_route` JSONB nullable column to `avatars` table
- [x] Add `activation_zone` varchar(20) column (denormalized for queries: safe/bridge/target/none)
- [x] Add `zone_entered_at` timestamp column
- [x] Create index on `activation_zone` for filtering
- [ ] Test migration up/down

## Task 2: ActivationRouter service — core
- [x] Create `app/services/activation_router.py`
- [x] Implement `plan_route(db, avatar, client)` → generates route JSONB
- [x] Implement `get_current_zone_subs(avatar)` → list of subreddit names
- [x] Implement `refresh_route(db, avatar, client)` → regenerate on sub changes
- [x] Define `ZONE_THRESHOLDS`, `UNIVERSAL_SAFE_LIST`, `ZONE_BUDGETS` constants
- [x] Add system settings: `activation_routing_enabled` (default: false)
- [x] Fallback: if no route, return hobby_subreddits (backward compat)
- [ ] Tests: route planning, zone sub selection, legacy fallback

## Task 3: Bridge Discovery logic
- [x] Implement `_find_bridge_subs(db, avatar, target_subs)` in ActivationRouter
- [x] Query SubredditRiskProfile for risk_score 26-50 in related categories
- [x] Filter by AvatarSubredditCompatibility score ≥ 50
- [x] Fallback to hobby_subreddits if <3 bridges found
- [x] Max 8 bridge subs per route
- [ ] Tests: bridge found, bridge fallback, empty compatibility

## Task 4: Zone Graduation evaluator
- [x] Create `app/services/zone_evaluator.py`
- [x] Implement `evaluate_graduation(db, avatar)` → new zone or None
- [x] Safe→Bridge criteria: karma≥10, survival≥90%, age≥7d, ≥3 posted, 0 deleted, CQS≠lowest
- [x] Bridge→Target criteria: karma≥15 in 2+ bridge subs, survival≥85%, total_karma≥50, compat≥60
- [x] Minimum sample size: 5 posted (same as phase demotion)
- [x] Implement `graduate(db, avatar, new_zone)` → update route + emit event
- [x] Implement `demote_zone(db, avatar, reason)` → move to previous zone
- [x] Emit activity events: `zone_graduation`, `zone_demotion`
- [ ] Tests: graduation pass/fail, sample size guard, demotion

## Task 5: Integration — Phase Evaluator
- [x] Modify `app/tasks/ai_pipeline.py` `evaluate_all_avatar_phases()`
- [x] After phase evaluation, run zone graduation for Phase 0-1 avatars
- [x] Zone demotion on survival_rate < 70% in current zone
- [x] Gated by `activation_routing_enabled` setting
- [x] If bridge→target graduation → trigger phase promotion re-check (handled: Phase eval runs first, zone eval second)
- [ ] Tests: zone eval runs after phase eval, feature flag respected

## Task 6: Integration — EPG Portfolio Manager
- [x] Modify `app/services/opportunity_engine.py` `scan_opportunities()`
- [x] For Phase 0-1 avatars with activation_route: use zone subs instead of hobby_subreddits
- [x] Fallback: no route = existing behavior
- [x] Dangerous hours filtering integrated in opportunity scan
- [ ] Tests: route subs used, budget respected, fallback works

## Task 7: Integration — Dangerous Hours
- [x] Add `is_safe_posting_time(subreddit, hour, db)` to `app/services/timing_engine.py`
- [x] Integrate into opportunity filtering (before slot creation) — in scan_opportunities
- [ ] Deferred slots shift +1-3h (not dropped) — currently filtered out, not deferred
- [ ] Tests: dangerous hour blocked, normal hour passes, no profile = safe

## Task 8: Integration — Avatar Creation & Demotion triggers
- [x] In `app/routes/avatar_onboard.py`: call `plan_route()` after avatar creation
- [x] In `app/services/phase.py` on demotion to Phase 0/1: call `plan_route()` (fresh route)
- [x] In `app/services/admin.py` on subreddit add/remove: call `refresh_route()` for affected avatars
- [ ] Tests: route created on avatar create, route refreshed on demotion

## Task 9: Admin UI — Zone display
- [x] Create `app/templates/partials/avatar_zone.html` partial
- [x] Show: current zone badge (safe🟢/bridge🟡/target🔵), zone subs list, graduation progress
- [x] Add to avatar detail page (admin + portal)
- [x] Show graduation_history timeline
- [x] Show "Next graduation requirements" checklist (what's missing)

## Task 10: Route backfill + system settings
- [x] Create management script `_backfill_activation_routes.py`
- [x] Generate routes for all existing Phase 0-1 avatars
- [x] Add system settings: `activation_routing_enabled`
- [x] Settings visible in admin system settings page (group: pipeline_v2)
- [ ] Test: backfill script idempotent, settings toggle

## Task 11: Observability & Activity Events
- [x] Emit `route_planned` event on new route
- [x] Emit `route_updated` event on refresh
- [x] Emit `zone_graduation` event with from/to
- [x] Emit `zone_demotion` event with reason
- [ ] Zero-day report includes zone context
- [x] Admin Activity Feed shows zone events (standard activity_event model)

## Task 12: Deploy & Verify
- [ ] Run migration on staging
- [ ] Enable feature flag on staging
- [ ] Verify route planning for test avatars
- [ ] Verify EPG uses zone subs
- [ ] Verify graduation works
- [ ] Deploy to production (with flag disabled initially)
- [ ] Enable per-avatar (gradual rollout)
