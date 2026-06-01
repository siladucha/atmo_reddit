# Requirements Document

## Introduction

The Emotional Resonance Engine adds emotional intelligence to the comment generation pipeline. It analyzes the emotional climate of subreddits and individual threads, then ensures avatar comments match the appropriate emotional register. This operates as a separate dimension from the existing approach diversity system (which handles rhetorical technique) — emotional tone is orthogonal to comment approach.

Three levels of emotional analysis:
1. **Subreddit level** — community emotional baseline (e.g., r/sysadmin = tired sarcasm, r/startups = enthusiasm)
2. **Thread level** — specific emotional context of the conversation (rant, question, celebration, cry for help)
3. **Avatar level** — which emotions suit this avatar's persona and which are off-limits

The engine integrates into the existing generation pipeline by injecting emotional context into the system prompt alongside strategy, learning, and approach diversity contexts.

## Glossary

- **Emotional_Profile**: A structured representation of a subreddit's dominant emotional patterns, stored as JSONB on the Subreddit model. Contains primary emotions, intensity levels, and example emotional markers.
- **Thread_Emotion**: A classification of the emotional context of a specific thread (e.g., frustration, curiosity, celebration, despair, humor). Determined at scoring time by the Scoring_Service.
- **Avatar_Emotional_Range**: A configuration on the Avatar model defining which emotions the avatar can express, which are forbidden, and the avatar's default emotional baseline.
- **Emotional_Context**: The combined output of all three analysis levels (subreddit profile + thread emotion + avatar range), formatted as a prompt section for injection into the Generation_Service.
- **Resonance_Score**: A 0-100 metric indicating how well a generated comment's emotional tone matches the thread's emotional context. Used for quality feedback.
- **Profile_Analyzer**: The service component that analyzes top comments in a subreddit to build the Emotional_Profile.
- **Thread_Classifier**: The service component that classifies a thread's emotional context during the scoring phase.
- **Emotional_Dimension**: One axis of emotional expression (e.g., warmth, sarcasm, formality, vulnerability, enthusiasm). Each subreddit profile contains 3-5 dominant dimensions.
- **Generation_Service**: The existing `services/generation.py` module that produces comment drafts via Claude Sonnet.
- **Scoring_Service**: The existing `services/scoring.py` module that evaluates threads via Gemini Flash.
- **Celery_Scheduler**: The periodic task scheduler (Celery Beat) that triggers background jobs.

## Requirements

### Requirement 1: Subreddit Emotional Profile Analysis

**User Story:** As a platform operator, I want the system to automatically analyze the emotional climate of each subreddit, so that avatars can match community tone without manual configuration.

#### Acceptance Criteria

1. WHEN a subreddit has no Emotional_Profile or the existing profile is older than 7 days, THE Profile_Analyzer SHALL analyze the top 50 comments from the subreddit's most recent hot threads to build an Emotional_Profile.
2. THE Profile_Analyzer SHALL produce an Emotional_Profile containing: 3-5 dominant Emotional_Dimensions with intensity scores (0.0-1.0), a text summary of the community's emotional baseline, and 2-3 example phrases that exemplify the tone.
3. THE Profile_Analyzer SHALL use Gemini Flash for analysis to minimize cost (same model as scoring).
4. WHEN the Profile_Analyzer completes analysis, THE System SHALL store the Emotional_Profile as a JSONB field on the Subreddit model with a `profile_analyzed_at` timestamp.
5. IF the Profile_Analyzer receives an error from the LLM API, THEN THE System SHALL log the error and retain the previous Emotional_Profile without modification.
6. THE Celery_Scheduler SHALL trigger Emotional_Profile refresh for all active subreddits weekly (Sunday 04:00, before the repurpose scrape at 03:00 is complete).

### Requirement 2: Thread Emotional Classification

**User Story:** As a platform operator, I want each thread to be classified by emotional context during scoring, so that the generation pipeline knows what emotional register to use.

#### Acceptance Criteria

1. WHEN the Scoring_Service scores a thread, THE Thread_Classifier SHALL classify the thread's emotional context as part of the same LLM call (piggybacked on existing scoring prompt).
2. THE Thread_Classifier SHALL produce a Thread_Emotion containing: a primary emotion label (from a fixed taxonomy of 12 emotions), a secondary emotion label (optional), and an intensity value (0.0-1.0).
3. THE Thread_Classifier SHALL store the Thread_Emotion as a JSONB field on the ThreadScore model.
4. WHEN a thread has no comments and only a post title, THE Thread_Classifier SHALL classify based on the post title and body text alone.
5. IF the Thread_Classifier fails to produce a valid classification, THEN THE System SHALL default to a neutral emotional context and proceed with generation.

### Requirement 3: Avatar Emotional Range Configuration

**User Story:** As a platform operator, I want to define which emotions each avatar can express, so that generated comments stay consistent with the avatar's persona.

#### Acceptance Criteria

1. THE System SHALL store an Avatar_Emotional_Range as a JSONB field on the Avatar model containing: allowed emotions (list), forbidden emotions (list), default emotional baseline (single emotion + intensity), and emotional intensity cap (0.0-1.0).
2. WHEN an Avatar has no Avatar_Emotional_Range configured, THE System SHALL infer a default range from the avatar's voice_profile_md using a one-time LLM analysis.
3. WHEN an operator updates an avatar's voice_profile_md, THE System SHALL mark the Avatar_Emotional_Range as stale for re-inference on next generation cycle.
4. THE Admin_Panel SHALL provide a UI section on the avatar detail page to view and override the Avatar_Emotional_Range.

### Requirement 4: Emotional Context Injection into Generation

**User Story:** As a platform operator, I want the generation pipeline to use emotional context when writing comments, so that avatar comments feel emotionally appropriate for each thread.

#### Acceptance Criteria

1. WHEN the Generation_Service generates a comment, THE System SHALL assemble an Emotional_Context from the subreddit's Emotional_Profile, the thread's Thread_Emotion, and the avatar's Avatar_Emotional_Range.
2. THE System SHALL inject the Emotional_Context into the generation system prompt as a dedicated section between the strategy context and the approach diversity constraint.
3. WHEN the subreddit has no Emotional_Profile, THE System SHALL omit the subreddit emotional context and proceed with thread-level and avatar-level context only.
4. WHEN the thread has no Thread_Emotion classification, THE System SHALL omit the thread emotional context and proceed with subreddit-level and avatar-level context only.
5. IF the avatar's Avatar_Emotional_Range forbids the thread's primary emotion, THEN THE System SHALL instruct the Generation_Service to use the avatar's closest allowed emotion instead.
6. THE Emotional_Context injection SHALL be non-critical: IF assembly fails for any reason, THEN THE Generation_Service SHALL proceed without emotional context and log a warning.

### Requirement 5: Emotion Taxonomy

**User Story:** As a platform operator, I want a fixed taxonomy of emotions used across all analysis levels, so that emotional classifications are consistent and comparable.

#### Acceptance Criteria

1. THE System SHALL use a fixed taxonomy of 12 primary emotions: tired_sarcasm, enthusiasm, warmth, technical_precision, frustration, curiosity, humor, vulnerability, authority, empathy, skepticism, celebration.
2. THE System SHALL define each emotion in the taxonomy with: a label, a description, and 2-3 example Reddit-style phrases.
3. WHEN the Profile_Analyzer or Thread_Classifier produces an emotion outside the taxonomy, THE System SHALL map the output to the closest taxonomy emotion using semantic similarity.
4. THE taxonomy SHALL be stored as a Python constant (not in the database) and versioned with the codebase.

### Requirement 6: Emotional Profile Refresh Task

**User Story:** As a platform operator, I want emotional profiles to stay current as subreddit culture evolves, so that avatar tone remains appropriate over time.

#### Acceptance Criteria

1. THE Celery_Scheduler SHALL run a `refresh_emotional_profiles` task weekly for all active subreddits.
2. WHEN refreshing an Emotional_Profile, THE Profile_Analyzer SHALL compare the new profile to the previous one and log significant shifts (any dimension changing by more than 0.3).
3. THE System SHALL store the previous Emotional_Profile in a `previous_emotional_profile` JSONB field for drift comparison.
4. WHILE the `refresh_emotional_profiles` task is running, THE System SHALL process subreddits sequentially with a configurable delay between calls (`emotional_profile_rate_limit_seconds`, default 5) to avoid LLM API rate limits.
5. IF a subreddit has fewer than 10 comments available for analysis, THEN THE Profile_Analyzer SHALL skip the subreddit and retain the existing profile.

### Requirement 7: Emotional Resonance Feedback

**User Story:** As a platform operator, I want to track whether emotional tone matching improves comment performance, so that the system can learn which emotional approaches work best.

#### Acceptance Criteria

1. WHEN a comment draft is generated with Emotional_Context, THE System SHALL store the emotional context metadata in the CommentDraft's `learning_metadata` JSONB field (subreddit_emotion, thread_emotion, avatar_emotion_used).
2. WHEN a human reviewer edits a draft's emotional tone (detected via edit_summary keywords), THE Learning_Service SHALL capture this as an emotional correction pattern.
3. THE Admin_Panel SHALL display emotional profile information on the subreddit detail page, showing dominant emotions and last analysis timestamp.

### Requirement 8: Emotional Context Formatting

**User Story:** As a platform operator, I want the emotional context to be formatted clearly for the LLM, so that Claude Sonnet can reliably interpret and apply the emotional guidance.

#### Acceptance Criteria

1. THE System SHALL format the Emotional_Context as a Markdown section with the header "## Emotional Resonance".
2. THE Emotional_Context section SHALL contain: the subreddit's emotional baseline (1-2 sentences), the thread's specific emotional context (1 sentence), the avatar's emotional instruction (1 sentence specifying which emotion to use and at what intensity).
3. THE Emotional_Context section SHALL be concise (under 200 tokens) to minimize generation cost impact.
4. WHEN the avatar's forbidden emotions conflict with the thread emotion, THE Emotional_Context SHALL explicitly state the alternative emotion to use.

### Requirement 9: Cost Control

**User Story:** As a platform operator, I want the emotional resonance engine to add minimal cost to the pipeline, so that per-client economics remain viable.

#### Acceptance Criteria

1. THE Profile_Analyzer SHALL use Gemini Flash (not Claude Sonnet) for all subreddit emotional analysis to keep cost below $0.01 per subreddit per analysis.
2. THE Thread_Classifier SHALL piggyback on the existing scoring LLM call (no additional API call) by extending the scoring prompt with emotional classification fields.
3. THE Avatar_Emotional_Range inference SHALL be a one-time cost per avatar (triggered only on creation or voice profile change), not a recurring expense.
4. THE total additional LLM cost per client per day from the Emotional Resonance Engine SHALL remain below $0.05 (excluding one-time avatar range inference).
