# Implementation Tasks — Platform Readiness MVP (Timing Jitter)

## Overview

Implement timing jitter across all automated intervals to prevent Reddit anti-spam detection. Three integration points: comment gaps, scraping intervals, and per-avatar daily activity windows. Pure Python, no migrations, no external dependencies.

## Tasks

- [ ] 1. Create Jitter Service Core
  - [ ] 1.1 Create `app/services/jitter.py` with `TimingWindow` dataclass
    - `TimingWindow(min_minutes, max_minutes)` with `sample(seed=None)` method
    - Production: use `secrets.randbelow()` (CSPRNG)
    - Testing: use seeded SHA-256 hash for deterministic output
    - Validate min <= max on construction
    - _Requirements: 1.5, 1.6_

  - [ ] 1.2 Implement `get_comment_delay(avatar_id, seed)` function
    - Load window from SystemSettings (`jitter_comment_min_minutes`, `jitter_comment_max_minutes`) with defaults (12, 45)
    - Return float (minutes) — drop-in replacement for `MIN_MINUTES_BETWEEN_COMMENTS`
    - Each call produces independent sample (no state between calls)
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [ ] 1.3 Implement `get_next_scrape_offset(subreddit_id, seed)` function
    - Load window from SystemSettings (`jitter_scrape_min_minutes`, `jitter_scrape_max_minutes`) with defaults (55, 90)
    - Return float (minutes) to add to last_scraped_at
    - Independent per subreddit (no global synchronization)
    - _Requirements: 2.1, 2.2_

  - [ ] 1.4 Implement `get_cold_start_offset(seed)` function
    - Fixed window: 0-5 minutes
    - Used for subreddits that have never been scraped
    - _Requirements: 2.3_

  - [ ] 1.5 Implement `compute_daily_activity_window(avatar_id, date, seed)` function
    - Derive seed from avatar_id + date.isoformat() for day-to-day variation
    - Load hour ranges from SystemSettings with defaults (start: 7-11, end: 20-23)
    - Return (start_hour, end_hour) tuple
    - Guarantee minimum 8-hour window width
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ] 1.6 Implement `is_within_activity_window(avatar_id, current_hour, date)` function
    - Returns (bool, reason_string) tuple
    - Reason string describes when activity resumes (for logging)
    - _Requirements: 3.4_

  - [ ] 1.7 Add DEBUG logging for all jitter decisions
    - Log computed delay/offset with window bounds
    - Log activity window computation per avatar
    - Log INFO when avatar is blocked (outside window)
    - _Requirements: 2.4_

- [ ] 2. Integrate Comment Timing Jitter
  - [ ] 2.1 Find current `MIN_MINUTES_BETWEEN_COMMENTS` usage in `services/safety.py` or `services/rate_limiter.py`
    - Identify the exact function that checks comment gap
    - Document current behavior before modification

  - [ ] 2.2 Replace fixed constant with `get_comment_delay()` call
    - Import jitter service
    - Call `get_comment_delay(avatar_id=avatar.id)` where the constant was used
    - Maintain same function signature (backward compatible)
    - _Requirements: 1.1, 12.1_

  - [ ] 2.3 Verify pipeline still works end-to-end after replacement
    - Run existing tests to confirm no regression
    - Verify rate limiter still blocks comments that are too close together

- [ ] 3. Integrate Scraping Interval Jitter
  - [ ] 3.1 Find current scrape scheduling logic in `tasks/queue_ticker.py`
    - Identify where `scrape_freshness_window_hours` is compared to `last_scraped_at`
    - Document current "is subreddit due?" logic

  - [ ] 3.2 Replace fixed interval check with jitter-based check
    - Instead of: `now - last_scraped_at > fixed_interval`
    - Use: `now - last_scraped_at > get_next_scrape_offset(subreddit_id)` (converted to same units)
    - For never-scraped subreddits: use `get_cold_start_offset()` as initial delay
    - _Requirements: 2.1, 2.2, 2.3, 12.1_

  - [ ] 3.3 Log computed next-scrape timestamp for each subreddit
    - Add DEBUG log: "subreddit=r/{name} next_scrape_offset={X}min"
    - _Requirements: 2.4_

- [ ] 4. Integrate Daily Activity Window
  - [ ] 4.1 Add activity window check to AI pipeline pre-filter
    - In `tasks/ai_pipeline.py` (or `services/pre_filter.py`): before generating comments for an avatar, check `is_within_activity_window()`
    - If outside window: skip avatar with INFO log, continue to next avatar
    - Do NOT block scraping or scoring — only generation/posting is gated
    - _Requirements: 3.4_

  - [ ] 4.2 Add activity window check to hobby pipeline
    - In `tasks/ai_pipeline.py` `run_hobby_pipeline_all_avatars`: same check before hobby generation
    - _Requirements: 3.4_

  - [ ] 4.3 Verify pipeline gracefully skips avatars outside window
    - Ensure no errors when all avatars are outside window (empty run is OK)
    - Ensure avatars inside window still get processed normally

- [ ] 5. Seed SystemSettings
  - [ ] 5.1 Add jitter settings to seed data (`app/seed.py`)
    - `jitter_comment_min_minutes` = "12" (group: "jitter")
    - `jitter_comment_max_minutes` = "45" (group: "jitter")
    - `jitter_scrape_min_minutes` = "55" (group: "jitter")
    - `jitter_scrape_max_minutes` = "90" (group: "jitter")
    - `jitter_activity_start_min_hour` = "7" (group: "jitter")
    - `jitter_activity_start_max_hour` = "11" (group: "jitter")
    - `jitter_activity_end_min_hour` = "20" (group: "jitter")
    - `jitter_activity_end_max_hour` = "23" (group: "jitter")
    - Include descriptions for each setting
    - _Requirements: 1.1, 2.1, 3.1, 3.2_

  - [ ] 5.2 Add validators for jitter settings in settings service
    - Validate min < max for all window pairs
    - Validate hours are 0-23
    - Validate minutes are positive
    - _Requirements: 1.2, 1.3_

- [ ] 6. Write Tests
  - [ ] 6.1 Unit tests for TimingWindow.sample()
    - With seed: deterministic output
    - Without seed: output within [min, max] bounds (run 100 samples)
    - Edge case: min == max → always returns that value
    - _Requirements: 1.2, 1.3, 1.5, 1.6_

  - [ ] 6.2 Unit tests for get_comment_delay()
    - Returns value in [12, 45] range (default settings)
    - Two consecutive calls produce different values (with high probability)
    - With same seed: produces same value
    - _Requirements: 1.1, 1.4, 1.5, 1.6_

  - [ ] 6.3 Unit tests for compute_daily_activity_window()
    - Window always >= 8 hours
    - Same avatar + same date = same window (deterministic per day)
    - Same avatar + different date = different window (varies day-to-day)
    - Hours within valid range (7-23)
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ] 6.4 Unit tests for is_within_activity_window()
    - Returns (True, "") when inside window
    - Returns (False, reason) when outside window
    - Reason string contains resume time
    - _Requirements: 3.4_

  - [ ] 6.5 Integration test: pipeline skips avatar outside activity window
    - Mock current time to be outside window
    - Run pipeline task
    - Verify avatar was skipped (no generation call made)
    - Verify other avatars inside window were processed
    - _Requirements: 3.4, 12.1_

---

## Dependencies & Blockers

| Task | Depends On | Notes |
|------|-----------|-------|
| Task 2 (Comment jitter) | Task 1 (Service exists) | Sequential |
| Task 3 (Scrape jitter) | Task 1 (Service exists) | Sequential |
| Task 4 (Activity window) | Task 1 (Service exists) | Sequential |
| Task 5 (Settings) | None | Can be done in parallel with Task 1 |
| Task 6 (Tests) | Tasks 1-4 complete | After implementation |

## Estimated Timeline

| Task | Duration | Notes |
|------|----------|-------|
| Task 1: Jitter Service | 0.5 day | Pure Python, no dependencies |
| Task 2: Comment integration | 0.5 day | Find + replace constant |
| Task 3: Scrape integration | 0.5 day | Modify queue_ticker logic |
| Task 4: Activity window | 0.5 day | Add pre-filter gate |
| Task 5: Settings seed | 0.25 day | Add to seed.py |
| Task 6: Tests | 0.5 day | Unit + integration |
| **Total** | **2.5 days** | |

## Success Criteria

| Metric | Target |
|--------|--------|
| Comment gaps vary between 12-45 min | No two consecutive comments at same interval |
| Scrape intervals vary between 55-90 min | No synchronized scraping across subreddits |
| Each avatar has different daily activity hours | Day-to-day variation visible in logs |
| Existing pipeline tests still pass | Zero regressions |
| No migrations needed | Pure service-layer change |
