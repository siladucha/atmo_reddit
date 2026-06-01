# Requirements Document

## Introduction

This is the **unified spec** for all emotional/behavioral intelligence about subreddits. It consolidates overlapping requirements from three previously separate specs:
- `emotional-resonance-engine` — subreddit emotional profiling + thread emotion + avatar range
- `subreddit-emotional-profile` — compatibility scoring + admin UI + pipeline integration
- `smart-post-routing` (Req 5.3 — tone_risk assessment)

**Motivation:** Avatar u/Hot-Thought2408 repeatedly lost karma posting in subreddits hostile to its tone (r/S24Ultra: emotional rant in tech sub, r/redditdev: off-topic complaint). The system needs to understand subreddit culture and prevent tone mismatches before they cost karma.

**Scope:** This spec covers:
1. Subreddit emotional profile analysis (what tones work/fail)
2. Thread-level emotional classification (what's the mood of this conversation)
3. Avatar-subreddit compatibility scoring (does this avatar fit here)
4. Admin UI for visibility and warnings
5. Pipeline integration (inject tone context into generation)
6. Outcome correlation (does compatibility predict karma)

**Out of scope:** Smart Post Routing (separate spec), Quality Sentinel (separate spec), AI-Native Expert warming (separate spec).

## Cost & Load Analysis

### LLM Cost (Gemini Flash — $0.075/1M input, $0.30/1M output)

| Operation | Input tokens | Output tokens | Cost/call | Frequency |
|-----------|-------------|---------------|-----------|-----------|
| Subreddit profile analysis | ~6,000 | ~400 | ~$0.0006 | Weekly per subreddit |
| Thread emotion classification | +200 tokens | +50 tokens | ~$0.00002 | Piggybacked on scoring (free) |
| Compatibility scoring | ~2,000 | ~200 | ~$0.0002 | Weekly per avatar-subreddit pair |
| Avatar emotional range inference | ~3,000 | ~300 | ~$0.0003 | One-time per avatar |

**Monthly cost at scale:**

| Scale | Subreddits | Avatars | Pairs | Total LLM/mo |
|-------|-----------|---------|-------|-------------|
| 3 clients | 15 | 10 | ~40 | **$0.05** |
| 10 clients | 50 | 50 | ~150 | **$0.20** |
| 50 clients | 250 | 250 | ~750 | **$1.00** |
| 100 clients | 500 | 500 | ~2000 | **$2.50** |

**Conclusion:** Negligible cost at any scale. Thread classification is free (piggybacked on existing scoring call).

### Reddit API Load

- ~550 calls/week for 50 subreddits (hot threads + comments)
- Spread over Sunday 04:30 with 5s delays = ~45 min runtime
- No impact on weekday pipeline schedule

### Database Impact

- 3 JSONB columns on `subreddits` table (emotional_profile, previous_emotional_profile, emotional_profile_analyzed_at)
- 1 JSONB column on `thread_scores` table (thread_emotion)
- 1 JSONB column on `avatars` table (emotional_range)
- 1 new table `avatar_subreddit_compatibility` (~2,500 rows at 100 clients)

## Glossary

- **Emotional_Profile**: Structured JSONB on Subreddit model — rewarded tones, punished tones, community temperament, formality/humor/vulnerability levels.
- **Thread_Emotion**: Classification of a thread's emotional context (primary emotion + intensity). Stored on ThreadScore model.
- **Avatar_Emotional_Range**: JSONB on Avatar model — allowed emotions, forbidden emotions, default baseline, intensity cap.
- **Compatibility_Score**: 0-100 score indicating avatar-subreddit voice fit. Stored in `avatar_subreddit_compatibility` table.
- **Tone_Mismatch_Warning**: Alert when Compatibility_Score < 40.
- **Rewarded_Tones**: Patterns that earn positive karma in a subreddit.
- **Punished_Tones**: Patterns that earn negative karma in a subreddit.
- **Community_Temperament**: 2-3 sentence characterization of subreddit behavioral norms.
- **Emotion_Taxonomy**: Fixed set of 12 emotional labels used across all analysis levels.
- **Profile_Analyzer**: Service that builds Emotional_Profile from top comments via LLM.
- **Thread_Classifier**: Component that classifies thread emotion during scoring (piggybacked, no extra LLM call).

## Priority Tiers

| Tier | Requirements | Rationale |
|------|-------------|-----------|
| **P0 — MVP** | Req 1, 10, 4, 8 | Core analysis + schema + UI display + on-demand trigger. Minimum viable: operator can see what tones work in a sub. |
| **P1 — Value** | Req 3, 5, 7, 2 | Compatibility scoring + warnings + pipeline injection + auto-refresh. The actual prevention of karma loss. |
| **P2 — Intelligence** | Req 6, 9, 11, 12 | Thread emotions + avatar range + list indicators + correlation. Deeper intelligence layer. |

## Requirements

### Requirement 1: Subreddit Emotional Profile Analysis [P0]

**User Story:** As a platform operator, I want the system to analyze the emotional and behavioral characteristics of each subreddit, so that I can understand what content tone works before assigning avatars.

#### Acceptance Criteria

1. WHEN triggered (on-demand or weekly refresh), THE Profile_Analyzer SHALL fetch the subreddit's hot listing (up to 10 threads) via PRAW and collect the top 30 comments by score (minimum score of 2) across those threads.
2. THE Profile_Analyzer SHALL send the collected comments to Gemini Flash with a prompt requesting structured emotional analysis, and validate the response against EmotionalProfileSchema (Req 10).
3. WHEN analysis completes successfully, THE System SHALL store the result in `subreddits.emotional_profile` (JSONB) and update `subreddits.emotional_profile_analyzed_at` timestamp.
4. IF the subreddit has fewer than 10 comments with score ≥ 2, THEN THE System SHALL log a warning and retain the previous profile (or NULL if first-time).
5. IF the LLM returns invalid output (fails schema validation), THE Profile_Analyzer SHALL retry once with a corrective prompt including the validation error. If retry fails, log error and retain previous profile.
6. THE `confidence` field SHALL be set to: "high" (25-30 comments from 5+ threads), "medium" (15-24 comments or 3-4 threads), "low" (<15 comments or <3 threads).
7. IF a Profile_Analyzer task is already running for a given subreddit (Redis lock, 5-min TTL), THE System SHALL skip duplicate execution.

### Requirement 2: Periodic Profile Refresh [P1]

**User Story:** As a platform operator, I want emotional profiles to stay current as subreddit culture evolves.

#### Acceptance Criteria

1. THE Celery_Scheduler SHALL run `refresh_subreddit_emotional_profiles` weekly (Sunday 04:30 Israel time) for all subreddits with active ClientSubredditAssignments.
2. Processing SHALL be sequential with configurable delay (`emotional_profile_rate_limit_seconds`, default 5).
3. Before overwriting, THE System SHALL copy current profile to `previous_emotional_profile` JSONB field.
4. WHEN tones are added/removed vs previous, THE System SHALL log ActivityEvent `emotional_profile_drift_detected` with subreddit name and changed tones.
5. 3 consecutive LLM errors → pause 60s. 5 pauses in one run → abandon run.
6. Single subreddit failure → skip, retain existing, log warning, continue.
7. On completion → log ActivityEvent `emotional_profile_refresh_completed` with counts (refreshed/skipped/failed/duration).
8. After all profiles are refreshed, THE System SHALL trigger compatibility score recomputation (Req 3) for all affected avatar-subreddit pairs.

### Requirement 3: Avatar-Subreddit Compatibility Scoring [P1]

**User Story:** As a platform operator, I want to see how well each avatar's voice fits each assigned subreddit, so that I can reassign avatars before they lose karma.

#### Acceptance Criteria

1. WHEN a subreddit has an Emotional_Profile AND an avatar has non-empty `voice_profile_md`, THE System SHALL compute a Compatibility_Score (integer, 0-100).
2. Scoring uses a single Gemini Flash call with avatar's voice_profile_md + tone_principles + subreddit's rewarded_tones + punished_tones + community_temperament → returns `{"score": int, "mismatch_reasons": [str]}`.
3. Score < 40 → classified as Tone_Mismatch_Warning.
4. Scores recomputed: (a) during weekly refresh after profiles update, (b) on-demand via admin UI button.
5. Storage: table `avatar_subreddit_compatibility` with columns: id (UUID PK), avatar_id (FK), subreddit_name (String, lowercase), score (Integer), mismatch_reasons (JSONB), is_stale (Boolean), computed_at (DateTime).
6. LLM failure + previous score exists → retain, set is_stale=true, log warning.
7. LLM failure + no previous score → don't create record (pair remains unscored).
8. Uses `subreddit_name` (string) as join key for compatibility with SubredditKarma.

### Requirement 4: Admin Panel — Subreddit Emotional Profile Display [P0]

**User Story:** As a platform operator, I want to see the emotional profile of each subreddit in the admin panel.

#### Acceptance Criteria

1. THE Admin_Panel SHALL display "Emotional Profile" section on subreddit detail page (`/admin/subreddits/{id}`).
2. Section shows: Community_Temperament, Rewarded_Tones (green pills, description on hover), Punished_Tones (red pills), formality/humor/vulnerability badges, confidence indicator, analyzed_at timestamp (Israel TZ).
3. No profile → "Not yet analyzed" placeholder + "Run Analysis" button.
4. "Run Analysis" / "Refresh Profile" → dispatch Celery task, disable button with "Analyzing…", poll HTMX every 5s, timeout 120s.
5. Task failure → show error, re-enable button.
6. Section loads via HTMX (`hx-get`, `hx-trigger="load"`), skeleton placeholder, 10s timeout.
7. Visible to: owner, partner, client_admin.

### Requirement 5: Admin Panel — Compatibility Warnings on Avatar Page [P1]

**User Story:** As a platform operator, I want to see tone mismatch warnings on the avatar detail page.

#### Acceptance Criteria

1. "Compatibility" tab on avatar detail page showing all assigned subreddits with scores (0-100).
2. Score < 40: red + mismatch_reasons (truncated 200 chars, expandable). Score 40-70: amber. Score > 70: green.
3. Sorted by score ascending (worst first). Unscored → gray "Not scored", listed last.
4. HTMX async load, skeleton, 10s timeout with "Retry" button.
5. No assigned subreddits → empty state message.
6. "Recompute All" button dispatches scoring for all pairs of this avatar.
7. Visible to: owner, partner, client_admin.

### Requirement 6: Admin Panel — Subreddit List Indicators [P2]

**User Story:** As a platform operator, I want to see emotional profile status at a glance on the subreddits list.

#### Acceptance Criteria

1. Colored dot per row: green (≤14 days), amber (>14 days), gray (never). Tooltip = Community_Temperament for green/amber.
2. Included in existing query (no extra DB round-trip — field is on same table).
3. Filter pills: all (default) / profiled / stale / unanalyzed.
4. Gray dots → no tooltip.

### Requirement 7: Pipeline Integration — Tone Context in Generation [P1]

**User Story:** As a platform operator, I want the generation pipeline to use emotional profile data to avoid producing content that clashes with subreddit culture.

#### Acceptance Criteria

1. Service function `get_subreddit_emotional_profile(db, subreddit_name) → EmotionalProfileSchema | None` — cached from DB, no LLM call.
2. Service function `get_avatar_compatibility(db, avatar_id, subreddit_name) → dict | None` — returns `{"score": int, "mismatch_reasons": [...], "tone_warning": [...] | None}`.
3. `tone_warning` populated only when score < 40 (list of punished tone names that conflict).
4. WHEN `generate_comment()` is called and target subreddit has an Emotional_Profile, THE System SHALL append "SUBREDDIT TONE CONTEXT" section to generation prompt containing: community_temperament, punished_tones ("AVOID"), rewarded_tones ("WORKS WELL").
5. Non-blocking: if profile unavailable, generation proceeds without it. No LLM call at generation time.
6. Placed after voice profile, before thread content (same position as strategy injection).

### Requirement 8: On-Demand Profile Analysis [P0]

**User Story:** As a platform operator, I want to trigger analysis for a specific subreddit immediately.

#### Acceptance Criteria

1. "Run Analysis" on unanalyzed sub → dispatch Celery task `analyze_subreddit_emotional_profile`, set Redis key `emotional_profile_analyzing:{subreddit_id}` (120s TTL).
2. "Refresh Profile" on analyzed sub → same task, preserve existing profile until new one succeeds.
3. HTMX polls every 5s while Redis key exists. Key gone → reload section.
4. Task failure → delete Redis key, store error in `emotional_profile_error` field (displayed in UI).
5. Duplicate trigger while key exists → reject with "Analysis already in progress" (HTTP 409).

### Requirement 9: Karma Correlation Display [P2]

**User Story:** As a platform operator, I want to see whether karma performance correlates with compatibility scores.

#### Acceptance Criteria

1. Compatibility section (Req 5) includes "Karma Trend" column: "↑" (total_delta > 0), "→" (== 0), "↓" (< 0). Computed from SubredditKarma current vs previous.
2. Score < 40 AND trend "↓" → "⚠ Confirmed Mismatch" (red bg + icon).
3. Score > 70 AND trend "↑" → "✓ Good Fit" (green bg + icon).
4. No SubredditKarma data → "—", excluded from classification.
5. Single DB query joining `avatar_subreddit_compatibility` with `subreddit_karma` on avatar_id + subreddit_name.

### Requirement 10: Profile Data Schema [P0]

**User Story:** As a developer, I want validated schema for Emotional_Profile data.

#### Acceptance Criteria

1. All Emotional_Profile JSONB validated against `EmotionalProfileSchema` (Pydantic v2) before DB storage.
2. Schema enforces:
   - `rewarded_tones`: list[1-5] of `{name: str(1-100), description: str(1-300)}`
   - `punished_tones`: list[0-5] of `{name: str(1-100), description: str(1-300)}`
   - `community_temperament`: str(1-500)
   - `formality_level`: Literal["casual", "moderate", "formal"]
   - `humor_tolerance`: Literal["none", "low", "moderate", "high"]
   - `vulnerability_tolerance`: Literal["none", "low", "moderate", "high"]
   - `confidence`: Literal["low", "medium", "high"]
3. LLM validation failure → retry once with corrective prompt. Second failure → log error, retain previous (or NULL).
4. Defined in `app/schemas/emotional_profile.py`.
5. Round-trip: `EmotionalProfileSchema(**schema.model_dump(mode="json"))` == original.

### Requirement 11: Thread Emotional Classification [P2]

**User Story:** As a platform operator, I want each thread classified by emotional context during scoring, so generation knows what register to use.

#### Acceptance Criteria

1. THE Thread_Classifier SHALL piggyback on the existing scoring LLM call by adding 2 fields to the scoring prompt: `thread_emotion` (primary emotion from Emotion_Taxonomy) and `emotion_intensity` (0.0-1.0).
2. THE result SHALL be stored as JSONB in `thread_scores.thread_emotion` field.
3. No additional LLM call — zero marginal cost.
4. IF classification fails or returns invalid emotion, THE System SHALL default to `{"emotion": "neutral", "intensity": 0.5}` and proceed.
5. Emotion_Taxonomy (12 labels): tired_sarcasm, enthusiasm, warmth, technical_precision, frustration, curiosity, humor, vulnerability, authority, empathy, skepticism, celebration. Stored as Python constant.

### Requirement 12: Avatar Emotional Range [P2]

**User Story:** As a platform operator, I want to define which emotions each avatar can express, so generated comments stay in character.

#### Acceptance Criteria

1. `avatars.emotional_range` JSONB field containing: `allowed_emotions` (list from taxonomy), `forbidden_emotions` (list), `default_emotion` (str + intensity float), `intensity_cap` (0.0-1.0).
2. WHEN avatar has no emotional_range AND has voice_profile_md, THE System SHALL infer range via one-time Gemini Flash call (cost: ~$0.0003).
3. WHEN voice_profile_md changes, mark emotional_range as stale (set `emotional_range_stale = true`). Re-infer on next generation cycle.
4. Admin UI: read-only display on avatar detail page (Overview tab). Manual override via JSON editor for advanced users.
5. WHEN generating a comment and thread_emotion conflicts with avatar's forbidden_emotions, THE generation prompt SHALL instruct to use the closest allowed emotion instead.

## Design Decisions

### Why `subreddit_name` (string) not `subreddit_id` (UUID)?
SubredditKarma, CommentDraft (via thread.subreddit), and avatar hobby/business lists all use string names. String key avoids complex joins.

### Why weekly refresh?
Subreddit culture changes slowly. Weekly is sufficient, avoids LLM cost waste, and doesn't compete with weekday pipeline (08:00, 14:00).

### Why piggyback thread emotion on scoring?
Zero marginal cost. Scoring already calls Gemini Flash per thread — adding 2 fields to the response costs ~$0.00002 extra per thread.

### Why not a separate "Emotional Resonance Engine"?
The original spec was over-engineered. This unified spec covers the same ground with simpler architecture: profile on Subreddit model, thread emotion on ThreadScore, avatar range on Avatar, compatibility in a small table. No new services needed — just functions in existing services.

### Data retention
Only current + previous emotional profile per subreddit. No historical archive. Previous is overwritten each refresh.

### RBAC
Emotional profiles visible to owner, partner, client_admin. Not visible to client_manager, client_viewer, b2c_user.

## Superseded Specs

This spec supersedes:
- `.kiro/specs/emotional-resonance-engine/` — fully absorbed (Req 1, 2, 7, 11, 12)
- `.kiro/specs/smart-post-routing/` Req 5.3 (tone_risk) — covered by Req 3 compatibility scoring

The following specs remain independent:
- `smart-post-routing` — post routing pipeline (uses compatibility data from this spec as input)
- `quality-sentinel` — outcome tracking and auto-adaptation (consumes karma data, not emotional profiles directly)
- `context-assembler` — unified LLM context assembly (will consume emotional profile via Req 7 service functions)
