# Production Failure Matrix

Generated: 2026-07-22

## Summary

| Status | Count |
|--------|-------|
| 🔴 Open (Reported) | 26 |
| 🔵 Fixed (awaiting verification) | 1 |
| ✅ Verified | 0 |
| **Total tracked** | **27** |

---

## Active Bugs (Notion QA Database)

| # | Endpoint / Area | User Action | Expected Behavior | Actual Error | Root Cause | Category | Risk | Regression Test |
|---|----------------|-------------|-------------------|--------------|------------|----------|------|-----------------|
| BUG-001 | Client portal (Settings, Onboarding, Review) | View any client-facing page | Term "voice" everywhere | "Avatar" visible in client UI | Terminology not replaced in templates | Compliance | — | ❌ No |
| BUG-002 | `/clients/{id}/review` | Click "Regenerate" on comment | New draft generated | UI error thrown | — (not investigated) | UX | — | ❌ No |
| BUG-003 | Generation pipeline | Daily pipeline run | Complete comments | Partial/cut-off comments for 2-3 days | — (not investigated) | AI | — | ❌ No |
| BUG-004 | Admin → Subreddits | Add hobby subreddit | Hobby subs unlimited | Limit validation blocks hobby adds | Limit applies to business only, not filtered by type | Backend | — | ❌ No |
| BUG-005 | `/clients/{id}/settings` | Edit keywords | Keyword management available | No keyword add/edit option visible | Settings page dedup removed section, only link to Keywords page | UX | — | ❌ No |
| BUG-006 | `/onboard/step/1` | Enter invalid URL → error | URL field re-editable | URL field locked after error | HTMX swap doesn't re-enable input | UX | — | ❌ No |
| BUG-007 | `/onboard/step/4` | AI returns <3 keywords | Soft warning, allow proceed | Hard error blocks onboarding | Quality gate min_keywords is blocking | Backend | — | ❌ No |
| BUG-008 | `/login` → wizard redirect | Re-login after session expiry | Redirect to wizard step | Redirect to dashboard (empty) | Login redirect doesn't check onboarding_complete flag | UX | — | ❌ No |
| BUG-009 | Multiple portal pages | Click "Upgrade" button | Stripe checkout / pricing modal | Button does nothing | Stripe not connected, buttons are placeholders | UX | — | ❌ No |
| BUG-010 | `/admin/review` (partner view) | View review queue | Thread title + subreddit shown | "Unknown thread / r/?" for hobby drafts | Hobby pipeline drafts lack thread FK display (known fix June 28) | UX | — | ❌ No |
| BUG-011 | EPG pipeline | Phase 2 avatar daily generation | Professional comments generated | 0 professional comments | `business_subreddits` empty on avatar → no ClientSubredditAssignment | Backend | — | ❌ No |
| BUG-012 | `/clients/{id}/review` | Click "Mark as Posted" | Status → posted | Crash / error | — (not investigated) | UX | — | ❌ No |
| BUG-013 | All portal pages | Normal viewing at 100% zoom | Readable text (14-16px) | Text too small | Base font-size not set in client_base.html | UX | — | ❌ No |
| BUG-015 | `/clients/{id}/avatars/{id}` | View Recent Activity | Full subreddit name "/r/cybersecurity" | Shows only "/r" | Template string interpolation truncation | UX | — | ❌ No |
| BUG-016 | Browser extension popup | Click Connect with Reddit tab open | Extension activates for account | "Account not recognized" error | Username detection failed for logged-in account | Integration | — | ❌ No |
| BUG-017 | Portal → Client Manager view | Click subreddit count number | Navigate to subreddits list | 404 page | Incorrect URL template (bad route) | UX | — | ❌ No |
| BUG-018 | `/clients/{id}/review` | Edit comment inline → Regenerate | New version generated for same thread | "Thread not found" popup | Regenerate uses thread_id which is NULL for hobby drafts | UX | — | ❌ No |
| BUG-019 | Portal → Keywords page | Hover tooltip (?) icon | Correct instructions | References non-existent Settings menu | Tooltip text not updated after Settings page redesign | UX | — | ❌ No |
| BUG-020 | Extension popup | Click "Review" link on pending draft | Opens portal review queue | Error page | Incorrect URL in extension (missing client_id) | UX | — | ❌ No |
| BUG-021 | Extension download | Download + extract ZIP | manifest.json at root | Nested folder, Chrome can't load | ZIP created with parent directory included | Integration | — | ❌ No |
| BUG-022 | `/static/extension/index.html` | Navigate to old URL | Redirect to portal extension page | Old page still accessible | No redirect configured in nginx | UX | — | ❌ No |
| BUG-023 | Portal → Subreddits | View thread availability | Filtered thread list per subreddit | Feature missing | Not implemented (feature request) | UX | — | ❌ No |
| BUG-024 | Portal → Avatar detail | View Fitness metric | Tooltip explaining metric | No explanation visible | No tooltip or docs link added | UX | — | ❌ No |
| BUG-025 | All system layers | Report a bug | Visible "Report Bug" link | No link anywhere | Not implemented in portal/extension sidebars | UX | — | ❌ No |
| BUG-026 | Extension popup | Click subreddit/post link in task | Navigate to Reddit thread | Links not clickable | `<span>` instead of `<a href>` in popup HTML | UX | — | ❌ No |
| BUG-027 | EPG pipeline | Daily generation | Uses active healthy accounts | Uses legacy/shadowbanned accounts (Middle-Mode3001, emma_richardson) | Client avatar assignments not cleaned up after shadowban detection | Backend | 🟠 High | ❌ No |
| BUG-028 | `/onboard/*` | XM Cyber onboarding wizard | Complete wizard flow | Wizard stalls/freezes | — (not investigated) | UX | 🟠 High | ❌ No |
| BUG-029 | Portal → Landscape Report | Click "Generate Now" | Report generation executes | Shows alert, nothing happens | Button triggers JS alert placeholder, no backend call | Backend | 🟠 High | ❌ No |
| BUG-030 | Discovery Engine | Auto-discovery for client | Relevant hypotheses from main page | Irrelevant hypotheses (career pages scraped) | Website scraper follows subpage links instead of main URL only | AI | 🟠 High | ❌ No |
| BUG-031 | `/onboard/step/3` | Fill ICP form | Optional job title | Job Title required, blocks B2C users | HTML `required` attribute on Job Title input | UX | 🟠 High | ❌ No |
| BUG-032 | Portal sidebar | Navigate to Extension page | "Extension" link in sidebar | No link visible | Sidebar restructured, Extension link removed, not re-added | UX | 🔴 Critical | ✅ Fixed (not verified) |

---

## Historical Incidents (from Steering Ops Logs, June-July 2026)

| Date | Endpoint / Area | Trigger | Expected | Actual | Root Cause | Fix | Regression Test |
|------|----------------|---------|----------|--------|------------|-----|-----------------|
| Jun 22 | Phase demotion | 1-2 posted comments in 7d | No demotion (insufficient sample) | False demotion → zero output | `_DEMOTION_MIN_SAMPLE_SIZE` not enforced | Added min sample = 5 | `test_epg_budget_integrity.py` ✅ |
| Jun 24 | EPG Source 1 | Phase 1 avatar scoring | Hobby-only (no professional) | Source 1 returned 0 for Phase 1 → budget wasted | Source 1 not gated to Phase 2+ | Gated `scan_opportunities()` Source 1 to Phase 2+ | `test_epg_responsibility_boundaries.py` ✅ |
| Jun 24 | EPG budget | get_budget_used_today | Only counts generated/approved/posted | Counted all non-planned incl. skipped-without-draft | Missing filter for `draft_id IS NOT NULL` on skipped | Fixed filter in `get_budget_used_today()` | `test_epg_budget_integrity.py` ✅ |
| Jun 24 | Discovery handoff | Execute handoff | Returns dict → access `result["client_id"]` | AttributeError: dict has no .id | Route used `.id` attribute on dict | Changed to `result['client_id']` | ❌ No |
| Jun 24 | Worker heartbeat | Alert check | Worker shown as alive | 🔴 "Worker offline" false positive | Heartbeat wrote to stdout only, alert checked empty table | Heartbeat → Redis `ramp:heartbeat:last_at` | ❌ No |
| Jun 25 | EPG dedup | Deploy restarts trigger Beat catch-up | One EPG build per day | 7-22 duplicate slots created per restart | Dedup guard checked only `status != skipped` | 2-level dedup: active slots + max 2 attempts/day | `test_epg_budget_integrity.py` ✅ |
| Jun 25 | Email dispatch | Slot scheduled in avatar TZ | Email at executor's day time | 2AM emails (persona TZ ≠ executor TZ) | No quiet hours gate | Added 23:00-07:00 Israel time block | ❌ No |
| Jun 25 | AttentionBudget | CQS=lowest avatar | Budget = 0 | Budget = 3 (CQS ignored) | `from_avatar()` didn't check cqs_level | CQS=lowest → budget 0 | `test_epg_budget_integrity.py` ✅ |
| Jun 26 | Hobby pipeline | Generate from hobby posts | Skip image/video posts | Image posts with body text passed filter | URL filter missing in hobby pipeline | Added URL filter to opportunity_engine + ai_pipeline | `test_hobby_media_filter.py` ✅ |
| Jun 26 | Email tasks | Dispatch task for thread | Check thread alive before sending | Email sent for locked thread | No pre-dispatch liveness check | Added liveness check + "Can't Post" button | ❌ No |
| Jun 27 | Onboarding step4 | Save keywords | Keywords stored in client.keywords JSONB | Keywords silently dropped | `step4_save()` only processed voice, not keywords | Added keyword parsing to step4_save + flag_modified | `test_onboarding_bugfixes.py` ✅ |
| Jun 27 | CQS batch | Check frozen avatar | CQS checked regardless of freeze | Frozen avatars skipped | `is_frozen` filter in batch query | Removed filter from cqs_checker + cqs_task_generator | `test_cqs_task_generator.py` ✅ |
| Jun 28 | Health checker | Avatar with old comments (>7d) | Classified as "inactive" | Classified as shadowbanned (false positive) | `total_sampled=0` confused with `total_from_api=0` | Added `total_from_api` distinction in 3-tuple return | `test_health_checker.py` ✅ |
| Jun 28 | Admin review queue | View hobby drafts | Thread title + subreddit shown | "Unknown thread / r/?" | No FK/relationship on hobby_post_id | Added FK + relationship + HobbyThreadProxy | ❌ No |
| Jun 30 | GEO batch | Multi-provider run | All providers complete | Partial (35%) — timeout at 5 min | Timeout too short for multi-provider batches | Increased 300s → 1200s | ❌ No |
| Jul 2 | Extension v1 | Auto-open composer | Comment box expands | 50% failure rate | Shadow DOM `.click()` → `isTrusted` rejected | chrome.debugger CDP trusted events | ❌ No |
| Jul 7 | Celery Beat | Continuous operation | Stable memory | 225 MB → OOM every 3-6h | Beat imported all 31 task modules (unnecessary) | Separate lightweight beat_app.py (25 MB stable) | ❌ No |
| Jul 7 | Signal collector | Daily review verdict | Worker shown alive | 🔴 "Worker offline" (stale source) | Collector read activity_events (empty), not Redis | Read from Redis `ramp:heartbeat:last_at` primary | ❌ No |
| Jul 7 | Anthropic budget | Generation pipeline | Drafts generated | 0 drafts — all fail | Credits exhausted ($50 limit), no alert | Provider budget multi-channel alerting (Telegram + email) | ❌ No |
| Jul 13 | EPG opportunity engine | Diversified slot allocation | Even distribution across subs | 100% from one sub (worldcup 51 posts) | No per-sub limit in `scan_opportunities()` | Added per-sub limit + shuffle | ❌ No |
| Jul 13 | EPG hobby prompt | Comment quality | Diverse, specific comments | "Respect for the analysis" × 3 (generic) | Weak placeholder prompt in epg_executor | Full prompt rewrite (6 angles, anti-repetition rules) | ❌ No |

---

## Regression Test Coverage

| Area | Tests Exist | Key Test Files | Gaps |
|------|:-----------:|----------------|------|
| EPG Budget/Allocation | ✅ | `test_epg_budget_integrity.py` (19), `test_epg_daily_minimum.py` (13), `test_epg_responsibility_boundaries.py` (22) | Prompt quality not tested |
| RBAC / Isolation | ✅ | `test_permission_guards.py` (113), `test_cross_client_isolation.py` (35), `test_rbac_scenarios.py` (53) | — |
| Health Detection | ✅ | `test_health_checker.py` (41) | No test for false-positive on `total_from_api > 0` |
| Hobby Media Filter | ✅ | `test_hobby_media_filter.py` (12) | — |
| CQS Task Generation | ✅ | `test_cqs_task_generator.py` (27), `test_cqs_dispatch_pipeline.py` (13) | — |
| Onboarding Flow | ✅ | `test_onboarding.py` (28), `test_onboarding_bugfixes.py` (7) | XM Cyber stall not covered |
| Fitness Gate | ✅ | `test_fitness_gate.py` (39) | — |
| Route Smoke | ✅ | `test_route_smoke.py` (119) | Only status codes, no business logic |
| Extension Dispatch | ✅ | `test_extension_dispatcher.py` (48) | DOM interaction not testable |
| Portal Navigation | ⚠️ | `test_portal_nav_redesign.py` (10) | Limited (BUG-032 gap found) |
| Stripe Billing | ✅ | `test_stripe_billing.py` (24), `test_stripe_config.py` (11) | Not live yet |
| Discovery | ⚠️ | `test_discovery_state.py` (13), `test_discovery_routes.py` (8) | Wrong-page scrape not tested |
| GEO/AEO Batch | ❌ | `test_geo_monitoring.py` (ignored in CI) | Timeout handling untested |
| Email Dispatch | ❌ | — | Pre-dispatch liveness, quiet hours |
| Beat Memory | ❌ | — | Not unit-testable |
| Draft Regeneration | ❌ | — | BUG-002, BUG-018 untested |
| Terminology Compliance | ❌ | — | BUG-001 (grep-based CI check would work) |

---

## Priority Actions

### P0 — Revenue blockers (affects pilot demo/sign-up)
- BUG-009: Upgrade buttons (needs Stripe integration — spec exists)
- BUG-028: XM Cyber onboarding stall
- BUG-027: Legacy shadowbanned accounts in pipeline

### P1 — Client experience (partner-reported, high visibility)
- BUG-001: "Avatar" → "Voice" terminology sweep
- BUG-002: Comment Regenerate crashes
- BUG-003: Partial/incomplete comments
- BUG-029: Landscape Report "Generate Now" broken
- BUG-030: Discovery scrapes wrong pages

### P2 — QA findings (Jenny, functional issues)
- BUG-012: Mark as Posted crash
- BUG-016: Extension "Account not recognized"
- BUG-018: Regenerate "thread not found"
- BUG-021: Extension ZIP structure

### P3 — Polish (UX improvements)
- BUG-006, BUG-007, BUG-008, BUG-013, BUG-015, BUG-019, etc.
