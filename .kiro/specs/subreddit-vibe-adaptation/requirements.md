# Requirements Document

## Introduction

The Subreddit Vibe Adaptation feature extends the existing Emotional Profile system with comment format intelligence (length, style, grammar) and injects this context into both the Hobby and Professional generation pipelines. Currently, RAMP generates polished, uniformly-formatted comments regardless of subreddit culture — causing a mismatch where casual communities expect short reactions but receive 30-50 word grammatically perfect text. This feature makes the generation pipeline adapt comment format to match each subreddit's observed communication style, while respecting existing safety gates.

## Glossary

- **Vibe_Profile**: The extended portion of a subreddit's emotional profile containing comment format fields (typical_comment_length, comment_style, grammar_strictness, example_top_comments).
- **Emotional_Profile_Service**: The existing `app/services/emotional_profile.py` module responsible for analyzing subreddit tone patterns via Gemini Flash.
- **Hobby_Pipeline**: The comment generation pipeline using `_build_hobby_system_prompt()` and `generate_hobby_comments()` for Phase 1+ avatars.
- **Professional_Pipeline**: The comment generation pipeline using `generate_comments()` with tone injection via `get_subreddit_tone_context()` for Phase 2+ avatars.
- **Vibe_Analyzer**: The component within Emotional_Profile_Service that performs daily analysis of subreddit comment format patterns.
- **Format_Injector**: The component that constructs format-aware prompt context from a subreddit's Vibe_Profile for injection into generation prompts.
- **Active_Subreddit**: A subreddit that has at least one avatar currently assigned to it (via `hobby_subreddits`, `business_subreddits`, or `ClientSubredditAssignment`).
- **Grammar_Adaptation**: The technique of adjusting comment grammar level (sloppy, casual, correct, formal) to match community norms without triggering Reddit anti-spam detection.
- **Voice_Profile**: The avatar's configured personality, expertise, and communication style that takes precedence over vibe adaptation when conflicts arise.
- **Fitness_Gate**: The existing `SubredditRiskProfile`-based pre-generation safety check that blocks comments in high-risk subreddits.

## Requirements

### Requirement 1: Extend Emotional Profile Schema with Format Fields

**User Story:** As an operator, I want the emotional profile to capture comment format patterns (length, style, grammar), so that the generation pipeline can adapt output format per subreddit.

#### Acceptance Criteria

1. THE Emotional_Profile_Service SHALL store `typical_comment_length` as one of: "ultra_short" (1-10 words), "short" (10-25 words), "medium" (25-60 words), "long" (60+ words) per subreddit.
2. THE Emotional_Profile_Service SHALL store `comment_style` as one of: "reaction", "opinion", "advice", "story", "technical" per subreddit.
3. THE Emotional_Profile_Service SHALL store `grammar_strictness` as one of: "sloppy", "casual", "correct", "formal" per subreddit.
4. THE Emotional_Profile_Service SHALL store `example_top_comments` as a list of 3-5 actual top-scoring comments from the subreddit, each capped at 200 characters.
5. WHEN a Vibe_Profile field cannot be determined from available data, THE Emotional_Profile_Service SHALL omit that field from the stored profile rather than guessing a default value.
6. THE Emotional_Profile_Service SHALL validate Vibe_Profile fields using a Pydantic schema before storing them in the database.

### Requirement 2: Daily Vibe Analysis for Active Subreddits

**User Story:** As an operator, I want vibe analysis to run daily for subreddits with assigned avatars, so that comment format adapts to trending topics and event-driven style changes.

#### Acceptance Criteria

1. THE Vibe_Analyzer SHALL run daily for every Active_Subreddit that has at least one non-frozen avatar assigned.
2. THE Vibe_Analyzer SHALL analyze both subreddits from the `subreddits` table (professional) and subreddits from the `hobby_subreddits` table (hobby) that have active avatar assignments.
3. THE Vibe_Analyzer SHALL consume at most $0.01 per subreddit per daily analysis run when using Gemini Flash.
4. THE Vibe_Analyzer SHALL schedule daily analysis at a time that does not conflict with existing Celery Beat tasks between 06:00-08:00 (Israel time).
5. WHEN the Vibe_Analyzer encounters a Reddit API error or LLM error for a specific subreddit, THE Vibe_Analyzer SHALL log the error and continue processing remaining subreddits without failing the batch.
6. THE Vibe_Analyzer SHALL retain the previous Vibe_Profile when a daily analysis fails, so that generation continues with stale-but-available data.
7. THE Vibe_Analyzer SHALL process subreddits sequentially with a minimum 2-second delay between Reddit API calls to respect rate limits.
8. WHEN a subreddit has fewer than 10 qualifying comments (score >= 2, body length > 20 characters), THE Vibe_Analyzer SHALL skip format analysis for that subreddit and retain any existing Vibe_Profile.

### Requirement 3: Inject Vibe into Hobby Pipeline

**User Story:** As an operator, I want hobby comment generation to receive subreddit vibe context, so that generated comments match the communication style of each hobby community.

#### Acceptance Criteria

1. WHEN generating a hobby comment, THE Hobby_Pipeline SHALL inject Vibe_Profile context (typical_comment_length, comment_style, grammar_strictness, example_top_comments) into the system prompt.
2. WHEN no Vibe_Profile exists for a hobby subreddit, THE Hobby_Pipeline SHALL proceed with generation using the existing prompt without vibe context (fail-open behavior).
3. THE Format_Injector SHALL format Vibe_Profile data as a clearly delineated section within the system prompt, separate from existing voice profile and rules sections.
4. THE Format_Injector SHALL include the example_top_comments as style reference examples within the injected context.
5. WHEN Vibe_Profile specifies `typical_comment_length` of "ultra_short", THE Format_Injector SHALL instruct the LLM to target 3-10 words for the generated comment.
6. WHEN Vibe_Profile specifies `typical_comment_length` of "short", THE Format_Injector SHALL instruct the LLM to target 10-25 words for the generated comment.

### Requirement 4: Inject Vibe into Professional Pipeline

**User Story:** As an operator, I want professional comment generation to receive the new format fields alongside existing tone context, so that professional comments also adapt their length and style per subreddit.

#### Acceptance Criteria

1. WHEN generating a professional comment, THE Professional_Pipeline SHALL inject Vibe_Profile format fields (typical_comment_length, comment_style, grammar_strictness, example_top_comments) alongside the existing tone context from `get_subreddit_tone_context()`.
2. WHEN no Vibe_Profile exists for a professional subreddit, THE Professional_Pipeline SHALL continue injecting existing tone context without format fields (fail-open behavior).
3. THE Format_Injector SHALL produce a unified tone-and-format context block that combines existing emotional profile data with the new Vibe_Profile fields for the Professional_Pipeline.

### Requirement 5: Voice Profile Precedence Over Vibe Adaptation

**User Story:** As an operator, I want the avatar's voice profile to take precedence over vibe adaptation when they conflict, so that avatars maintain authentic expert identity even in casual subreddits.

#### Acceptance Criteria

1. WHEN a thread requires technical depth (based on thread content complexity) and the Vibe_Profile specifies "ultra_short" length, THE Format_Injector SHALL include a directive that allows the LLM to exceed the typical length to provide substantive technical content.
2. THE Format_Injector SHALL present Vibe_Profile as guidance ("typical for this community") rather than as hard constraints, so that the LLM can deviate when the avatar's expertise demands a longer or more structured response.
3. THE Format_Injector SHALL never instruct the LLM to produce content that contradicts the avatar's Voice_Profile tone principles.

### Requirement 6: Safety Gate Compatibility

**User Story:** As an operator, I want vibe adaptation to respect all existing safety mechanisms, so that subreddit style matching does not bypass brand safety, phase gates, or risk controls.

#### Acceptance Criteria

1. THE Format_Injector SHALL NOT override or weaken existing safety constraints (brand safety blocks, phase gates, SubredditRiskProfile fitness gate).
2. WHEN Vibe_Profile grammar_strictness is "sloppy", THE Format_Injector SHALL instruct the LLM to use relaxed grammar naturally without injecting artificial typos, deliberate misspellings, or obvious "humanization" patterns.
3. THE Vibe_Analyzer SHALL NOT modify the existing `formality_level`, `humor_tolerance`, `rewarded_tones`, or `punished_tones` fields during daily format analysis — those fields remain on the weekly refresh cycle.
4. IF the Fitness_Gate blocks comment generation for a subreddit, THEN THE Format_Injector SHALL NOT be invoked for that subreddit (safety gate runs before format injection).

### Requirement 7: Observability and Admin Visibility

**User Story:** As an operator, I want to see vibe profile data in the admin UI and track analysis runs, so that I can monitor adaptation quality and troubleshoot mismatches.

#### Acceptance Criteria

1. THE Vibe_Analyzer SHALL emit an `ActivityEvent` of type "vibe_profile_analyzed" for each successful subreddit analysis, including the determined format fields in event metadata.
2. WHEN a daily vibe analysis batch completes, THE Vibe_Analyzer SHALL emit a summary `ActivityEvent` with counts of analyzed, skipped, and failed subreddits.
3. THE Emotional_Profile_Service SHALL expose Vibe_Profile fields (typical_comment_length, comment_style, grammar_strictness, example_top_comments) in the existing subreddit emotional profile admin UI section.
4. WHEN a comment is generated with vibe context injected, THE generation task SHALL log the subreddit name and the vibe profile fields used for that generation.
