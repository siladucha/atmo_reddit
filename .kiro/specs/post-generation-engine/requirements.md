# Requirements Document

## Introduction

The Post Generation Engine is a multi-step AI pipeline for generating Reddit self-posts from persona-based avatars. Unlike comment generation (which responds to existing threads), post generation creates original content that initiates discussions. The engine transforms client strategic goals into authentic-sounding practitioner posts through a 10-step pipeline: strategic theme selection, experience generation, worthiness scoring, persona matching, friction generation, post type selection, post writing, worldview injection, anti-pattern filtering, and authenticity testing.

The engine is designed as a generic, client-configurable system. Each client defines their own themes, forbidden terms, content mix ratios, allowed post types, worldview concepts, and anti-pattern lists. Avatar phase gates and brand mention policies are enforced at pipeline level. All generated posts require human review before publishing.

## Glossary

- **Post_Generation_Engine**: The orchestrating service that runs the full 10-step pipeline to produce Reddit self-posts
- **Theme_Selector**: The pipeline step that picks a strategic theme based on client keywords, industry news, and competitor content
- **Experience_Generator**: The pipeline step that converts a theme into realistic practitioner situations
- **Worthiness_Scorer**: The pipeline step that scores situations on engagement potential dimensions and selects the top candidates
- **Persona_Matcher**: The pipeline step that selects the best avatar for a given situation based on realism and fit
- **Friction_Generator**: The pipeline step that identifies the emotional center of a situation
- **Post_Type_Selector**: The pipeline step that chooses the structural format for the post from client-allowed types
- **Post_Writer**: The pipeline step that generates the post body and title
- **Worldview_Injector**: The pipeline step that optionally injects one brand concept into the post
- **Anti_Pattern_Filter**: The pipeline step that rejects content sounding like LinkedIn, vendor, or consultant copy
- **Authenticity_Tester**: The pipeline step that evaluates whether a tired practitioner would credibly write the post
- **Client_Post_Config**: The client-specific configuration governing post generation behavior (themes, forbidden terms, ratios, post types, worldview concepts, anti-pattern lists, length range)
- **Content_Mix**: The target ratio distribution across content categories (e.g., 60% community, 25% operational, 10% worldview, 5% brand)
- **PostDraft**: The existing database model that stores generated post content, status, and metadata
- **EPG**: Electronic Program Guide — the scheduling system that assigns time slots to posts
- **Avatar_Phase**: The maturity stage of an avatar (Phase 0 Mentor, Phase 1, Phase 2, Phase 3, Expert) determining allowed content types
- **Pipeline_Run**: A single execution of the Post Generation Engine producing one or more PostDraft records
- **Kill_Switch**: A system setting that globally disables post generation
- **Audit_Log**: A record of pipeline actions for traceability and compliance

## Requirements

### Requirement 1: Strategic Theme Selection

**User Story:** As a platform operator, I want the engine to select post themes aligned with client strategy, so that generated posts serve marketing objectives while remaining authentic.

#### Acceptance Criteria

1. WHEN a Pipeline_Run is initiated for a client, THE Theme_Selector SHALL select a theme by combining the client's configured keyword clusters (high/medium/low priority), industry context, and competitive landscape into a ranked list of candidate themes and selecting the highest-ranked candidate that satisfies all other constraints
2. THE Theme_Selector SHALL weight theme selection based on the client's Content_Mix ratios (configured as percentage targets per strategic tier: worldview, problem_awareness, community_value) and maintain the target distribution within a rolling 30-day window, measured as actual post count per tier divided by total posts in the window
3. IF the client has configured forbidden terms, THEN THE Theme_Selector SHALL exclude any candidate theme where a forbidden term appears as a case-insensitive substring match within the theme text
4. THE Theme_Selector SHALL use the client's historical post data to avoid selecting a theme with the same primary keyword or strategic angle as any post generated within the past 14 days
5. IF the Theme_Selector cannot find a suitable theme that satisfies all constraints after evaluating all candidates, THEN THE Post_Generation_Engine SHALL record a structured failure event to the ActivityEvent log including the client_id, timestamp, and reason for failure, and terminate the Pipeline_Run for that client without affecting other queued clients
6. IF the client has no Content_Mix ratios configured, THEN THE Theme_Selector SHALL apply an equal distribution across all available strategic tiers

### Requirement 2: Experience Generation

**User Story:** As a platform operator, I want the engine to generate realistic practitioner situations from a theme, so that posts feel grounded in real-world experience.

#### Acceptance Criteria

1. WHEN a theme is selected, THE Experience_Generator SHALL produce 20 practitioner situations derived from that theme, where no two situations share the same combination of role, industry context, and core challenge
2. THE Experience_Generator SHALL generate each situation as a structured object containing at minimum: a practitioner role, an industry or team context, a specific tool or technology reference, a timeline or scale indicator (team size, duration, or volume), and a concrete outcome or observation
3. THE Experience_Generator SHALL use Gemini Flash as the LLM backend for situation generation
4. A situation SHALL be considered valid only when it contains all required fields from criterion 2 and its content length is between 50 and 500 characters
5. IF the Experience_Generator produces fewer than 5 valid situations, THEN THE Post_Generation_Engine SHALL retry generation once with a prompt that explicitly instructs the LLM to vary role and industry context before terminating the Pipeline_Run with a logged failure event
6. IF the Gemini Flash LLM call fails or returns a non-parseable response, THEN THE Experience_Generator SHALL retry the call once with exponential backoff and, if the retry also fails, THE Post_Generation_Engine SHALL terminate the Pipeline_Run and log the error details

### Requirement 3: Worthiness Scoring

**User Story:** As a platform operator, I want situations scored on engagement potential, so that only high-quality candidates proceed to post generation.

#### Acceptance Criteria

1. WHEN 20 situations are generated, THE Worthiness_Scorer SHALL score each situation on five dimensions: curiosity (1-10), relatability (1-10), frustration (1-10), authenticity (1-10), and discussion_potential (1-10), where each dimension is an integer value
2. THE Worthiness_Scorer SHALL compute a composite score as the weighted average of all five dimensions using weights configurable per client (default weights: curiosity 0.2, relatability 0.2, frustration 0.2, authenticity 0.2, discussion_potential 0.2), producing a result between 1.0 and 10.0 rounded to one decimal place
3. THE Worthiness_Scorer SHALL select the top N situations by composite score, where N is configurable per client with a minimum of 1, maximum of 10, and default of 3; IF fewer than N situations score at or above the minimum composite threshold, THEN the Worthiness_Scorer SHALL select only those that meet the threshold
4. THE Worthiness_Scorer SHALL use Gemini Flash as the LLM backend for scoring, with a maximum response time of 30 seconds per batch of 20 situations
5. IF all situations score below a minimum composite threshold of 5.0, THEN THE Post_Generation_Engine SHALL discard the batch, log a low-quality-themes event containing the theme name, client_id, highest composite score in the batch, and timestamp, and terminate the Pipeline_Run without proceeding to Persona Matching
6. IF the Worthiness_Scorer LLM call fails or returns an unparseable response, THEN THE Worthiness_Scorer SHALL retry once after 5 seconds, and IF the retry also fails, THEN THE Post_Generation_Engine SHALL log a scoring-failure event and terminate the Pipeline_Run
7. WHEN fewer than 20 situations are received from the Experience_Generator (minimum 5 per Requirement 2), THE Worthiness_Scorer SHALL score all received situations using the same dimensions and selection logic

### Requirement 4: Persona Matching

**User Story:** As a platform operator, I want the best avatar matched to each situation, so that posts come from a credible author who would naturally experience the situation.

#### Acceptance Criteria

1. WHEN a situation passes worthiness scoring, THE Persona_Matcher SHALL evaluate all client-accessible avatars for fit against that situation
2. THE Persona_Matcher SHALL score avatar fit based on: subreddit karma in the target subreddit, professional background alignment with the situation topic, voice profile compatibility with the situation tone, and phase eligibility
3. THE Persona_Matcher SHALL exclude avatars in Phase 0 (Mentor) from all automated pipeline generation, and SHALL exclude Phase 1 avatars from post generation
4. THE Persona_Matcher SHALL exclude frozen avatars, shadowbanned avatars, and avatars with health_status of "shadowbanned" or "suspended"
5. WHEN multiple situations are being processed in one Pipeline_Run, THE Persona_Matcher SHALL distribute situations across available avatars such that no single avatar is assigned more than 2 consecutive situations before another eligible avatar is used
6. IF no eligible avatar exists for a situation after applying all exclusion and accessibility filters, THEN THE Persona_Matcher SHALL skip that situation and emit an activity event recording the situation details, client_id, and the exclusion reasons that eliminated all candidates
7. IF the LLM persona selection call fails, THEN THE Persona_Matcher SHALL fall back to selecting the avatar with the highest subreddit karma in the target subreddit from the eligible candidate list

### Requirement 5: Friction Generation

**User Story:** As a platform operator, I want the engine to identify the emotional center of each situation, so that posts resonate with readers on a human level.

#### Acceptance Criteria

1. WHEN a situation is matched to an avatar, THE Friction_Generator SHALL select exactly one primary emotional center from: annoyance, surprise, curiosity, unanswered_question, frustration, or disbelief, based on the situation content and context
2. THE Friction_Generator SHALL produce a friction statement consisting of a single sentence between 40 and 200 characters that names the identified emotion and describes the specific tension or hook present in the situation
3. THE Friction_Generator SHALL produce a friction statement that uses vocabulary, sentence structure, and tone consistent with the matched avatar's voice profile, containing no terms listed in the avatar's voice profile "avoid" list
4. IF the Friction_Generator cannot identify a primary emotional center with sufficient distinction from the situation content, THEN THE Friction_Generator SHALL return a fallback emotional center of "curiosity" and include a low-confidence flag in the output

### Requirement 6: Post Type Selection

**User Story:** As a platform operator, I want the engine to choose an appropriate post structure type, so that posts vary in format and match the situation's nature.

#### Acceptance Criteria

1. WHEN friction is generated, THE Post_Type_Selector SHALL choose one post type from the client's allowed types list based on the friction type and historical distribution
2. THE Post_Type_Selector SHALL support these post types: War_Story, Observation, Frustration, Discussion_Question, Contrarian_Insight
3. WHEN the client has 10 or more posts within the trailing 30-day window, THE Post_Type_Selector SHALL enforce that no single type exceeds 40% of posts in that window
4. THE Post_Type_Selector SHALL select post type using the following friction-to-type affinity: frustration friction maps to Frustration or War_Story; surprise or disbelief friction maps to Contrarian_Insight or Observation; curiosity or unanswered_question friction maps to Discussion_Question or Observation; annoyance friction maps to Frustration or Discussion_Question
5. IF the client's allowed types list contains fewer than 2 types, THEN THE Post_Type_Selector SHALL select from the available type without applying the 40% distribution constraint
6. IF the friction-to-type affinity yields only types not present in the client's allowed types list, THEN THE Post_Type_Selector SHALL fall back to the allowed type with the lowest usage percentage in the trailing 30-day window

### Requirement 7: Post Writing

**User Story:** As a platform operator, I want the engine to generate authentic Reddit posts with proper structure, so that content passes as genuine community contributions.

#### Acceptance Criteria

1. WHEN a post type is selected, THE Post_Writer SHALL generate a post with a title and body following the structure: what happened, why it mattered, what surprised, and a closing question or observation
2. THE Post_Writer SHALL generate body text within the client's configured target length range (default: 150-350 words), where the range is defined as a minimum and maximum word count stored in client configuration
3. THE Post_Writer SHALL use Claude Sonnet as the LLM backend for post writing
4. THE Post_Writer SHALL apply the matched avatar's voice profile (tone, vocabulary, sentence patterns) to the generated content
5. THE Post_Writer SHALL follow all existing anti-pattern rules: no em-dashes, no buzzwords, no academic transitions, no passive voice, mandatory contractions, lowercase default
6. THE Post_Writer SHALL produce a title between 10 and 300 characters that is self-contained and ends with a statement, question, or observation that can be responded to without reading the body
7. IF the generated body exceeds the configured maximum word count, THEN THE Post_Writer SHALL regenerate with the maximum word count reduced by 20% (one retry allowed)
8. IF the regenerated body still exceeds the configured maximum word count after one retry, THEN THE Post_Writer SHALL truncate the body at the last complete sentence within the word limit and log a warning event
9. IF the matched avatar has no voice profile defined, THEN THE Post_Writer SHALL reject the generation request and return an error indicating that a voice profile is required

### Requirement 8: Worldview Injection

**User Story:** As a platform operator, I want the engine to optionally inject brand worldview concepts into posts, so that posts build brand association without being promotional.

#### Acceptance Criteria

1. WHILE an avatar is in Phase 1, THE Worldview_Injector SHALL inject zero brand concepts into the post
2. WHILE an avatar is in Phase 2 or Phase 3, THE Worldview_Injector SHALL inject at most one brand concept per post from the client's configured worldview_concepts list
3. IF the LLM evaluates that the post's topic has no semantic overlap with any concept in the worldview_concepts list, THEN THE Worldview_Injector SHALL output "karma-only" and skip injection for that post
4. THE Worldview_Injector SHALL track the cumulative count of brand concept injections per avatar over a rolling 30-day window and enforce the client's configured brand_mention_cap (an integer representing maximum allowed injections in that window)
5. IF injection would cause the avatar to exceed the brand_mention_cap over the rolling 30-day window, THEN THE Worldview_Injector SHALL skip injection for that post
6. IF the client's worldview_concepts list is empty or the brand_mention_cap is not configured (null), THEN THE Worldview_Injector SHALL skip injection for all posts for that client's avatars

### Requirement 9: Anti-Pattern Filtering

**User Story:** As a platform operator, I want the engine to reject content that sounds inauthentic, so that no post reads like LinkedIn, vendor marketing, or consultant copy.

#### Acceptance Criteria

1. WHEN a post is written, THE Anti_Pattern_Filter SHALL check the post against the client's configured anti-pattern word list using case-insensitive substring matching
2. THE Anti_Pattern_Filter SHALL check for generic patterns: listicles, motivational conclusions, CTAs, "thought leadership" language, and self-promotional framing
3. IF the Anti_Pattern_Filter detects two or more anti-pattern violations, THEN THE Post_Generation_Engine SHALL reject the post and log the specific violations with word matches and pattern names
4. WHEN a post is rejected by the Anti_Pattern_Filter, THE Post_Generation_Engine SHALL attempt one regeneration with an explicit "avoid these patterns" instruction appended to the prompt before discarding
5. IF a post contains exactly one anti-pattern violation, THEN THE Anti_Pattern_Filter SHALL pass the post but include a warning flag in the pipeline metadata for human reviewer awareness

### Requirement 10: Authenticity Testing

**User Story:** As a platform operator, I want the engine to test whether posts sound like they were written by a real practitioner, so that inauthenticity is caught before human review.

#### Acceptance Criteria

1. WHEN a post passes the Anti_Pattern_Filter, THE Authenticity_Tester SHALL evaluate the post against the question: "Would a tired practitioner write this after a long day?"
2. THE Authenticity_Tester SHALL produce a binary pass/fail result, a confidence score (0.0-1.0), and a textual explanation listing up to 3 specific inauthenticity markers detected (or confirming authenticity if passed)
3. THE Authenticity_Tester SHALL determine pass/fail based on a configurable confidence threshold (default: 0.6), where a confidence score at or above the threshold indicates a pass
4. IF the Authenticity_Tester returns a fail result, THEN THE Post_Generation_Engine SHALL rewrite the post once by passing the tester's inauthenticity markers as explicit avoidance instructions to the Post_Writer, then re-test
5. IF the post fails authenticity testing after one rewrite, THEN THE Post_Generation_Engine SHALL discard the post and log the failure reason including the confidence score and inauthenticity markers from both attempts
6. THE Authenticity_Tester SHALL use Gemini Flash as the LLM backend

### Requirement 11: Client Configuration Management

**User Story:** As a platform operator, I want each client's post generation behavior to be independently configurable, so that the engine adapts to different industries and strategies.

#### Acceptance Criteria

1. THE Post_Generation_Engine SHALL support per-client configuration of: allowed_themes (list of keyword clusters, maximum 50 entries), forbidden_terms (word list, maximum 500 entries), content_mix_ratios (category-to-percentage mapping where each percentage is an integer between 1 and 100), allowed_post_types (subset of supported types: War_Story, Observation, Frustration, Discussion_Question, Contrarian_Insight), worldview_concepts (list of injectable brand terms, maximum 20 entries), anti_pattern_words (additional banned terms, maximum 200 entries), target_post_length_range (min and max word count where min is between 50 and 2000 and max is between min and 2000), and top_n_situations (integer between 1 and 10 representing the worthiness threshold count)
2. IF a client has no explicit post generation configuration, THEN THE Post_Generation_Engine SHALL use system-wide default values for all configuration fields
3. WHEN a post generation configuration is created or updated, THE Post_Generation_Engine SHALL validate that content_mix_ratios values sum to exactly 100
4. IF content_mix_ratios validation fails, THEN THE Post_Generation_Engine SHALL reject the configuration change and return an error message indicating that the ratios do not sum to 100
5. IF allowed_post_types contains a value not in the set of 5 supported post types, THEN THE Post_Generation_Engine SHALL reject the configuration change and return an error message indicating the invalid post type
6. IF a client configuration specifies only a subset of configuration fields, THEN THE Post_Generation_Engine SHALL use system-wide default values for any unspecified fields

### Requirement 12: Pipeline Output and Integration

**User Story:** As a platform operator, I want pipeline output to integrate with existing systems, so that generated posts flow through review and scheduling without manual intervention.

#### Acceptance Criteria

1. WHEN a post passes all pipeline steps, THE Post_Generation_Engine SHALL create a PostDraft record with status "pending", the generated title in ai_title, generated body in ai_body, matched avatar_id, client_id, target subreddit, and the full strategic brief serialized as JSON in the brief field
2. THE Post_Generation_Engine SHALL store pipeline provenance in the PostDraft.brief field as a JSON string containing at minimum: theme, situation, worthiness_scores, friction_statement, post_type, worldview_injected, authenticity_score
3. WHEN a PostDraft is created with status "pending", THE Post_Generation_Engine SHALL make the draft queryable by the review queue so that operators can approve, reject, or edit it before scheduling
4. IF the number of pending or posted PostDrafts for a given avatar on the current calendar day (Asia/Jerusalem timezone) equals or exceeds the avatar's effective daily cap (minimum of phase_daily_limit and the auto_posting_daily_cap system setting, default 8), THEN THE Post_Generation_Engine SHALL skip post generation for that avatar in the current Pipeline_Run and log the skip reason as an activity event
5. WHEN a PostDraft creation fails due to a database error, THE Post_Generation_Engine SHALL roll back the transaction and raise a RuntimeError without leaving partial records in the database

### Requirement 13: Safety and Phase Gates

**User Story:** As a platform operator, I want safety controls that prevent policy violations, so that no post breaks avatar progression rules or brand exposure limits.

#### Acceptance Criteria

1. WHILE an avatar is in Phase 1, THE Post_Generation_Engine SHALL generate only community-value posts (posts targeting hobby subreddits with zero brand name mentions, zero brand domain references, and zero brand links)
2. WHILE an avatar is in Phase 2, THE Post_Generation_Engine SHALL allow external source citations and worldview seeding (indirect references to the client's worldview concepts) but SHALL reject any post containing explicit brand name mentions or direct brand links
3. THE Post_Generation_Engine SHALL enforce the client's brand_mention_cap as a hard limit over a rolling 30-day window — when an avatar's brand mention count within that window equals or exceeds the cap, the pipeline SHALL skip post generation for that avatar entirely until the rolling window count drops below the cap
4. IF a client's brand_mention_cap is not configured (NULL), THEN THE Post_Generation_Engine SHALL apply no brand mention cap enforcement for that client's avatars
5. THE Post_Generation_Engine SHALL require human review for all generated posts (status remains "pending" until explicitly approved)
6. WHILE the system setting `post_generation_enabled` is set to false, THE Post_Generation_Engine SHALL not initiate any Pipeline_Run and SHALL return immediately without queuing tasks

### Requirement 14: Kill Switch and Operational Controls

**User Story:** As a platform operator, I want a kill switch and operational controls for post generation, so that the pipeline can be disabled instantly in emergencies.

#### Acceptance Criteria

1. THE Post_Generation_Engine SHALL check the `post_generation_enabled` system setting before starting any Pipeline_Run
2. IF `post_generation_enabled` is false, THEN THE Post_Generation_Engine SHALL skip execution without processing any queued or new Pipeline_Runs, and SHALL emit an ActivityEvent indicating post generation is disabled
3. IF a client's `post_generation_active` flag on the Client_Post_Config is false, THEN THE Post_Generation_Engine SHALL skip that client's Pipeline_Run and SHALL emit an ActivityEvent indicating the client's post generation is disabled
4. WHEN a Pipeline_Run exceeds 5 minutes of wall-clock time, THE Post_Generation_Engine SHALL terminate the run, discard any PostDraft records created during that run that have not yet reached "pending" status, and SHALL log a timeout ActivityEvent including the client_id and elapsed duration
5. THE Post_Generation_Engine SHALL evaluate the global `post_generation_enabled` setting before evaluating the per-client `post_generation_active` flag — if the global setting is false, no per-client evaluation occurs

### Requirement 15: Audit Logging and Observability

**User Story:** As a platform operator, I want full audit logging of pipeline executions, so that every decision is traceable for compliance and debugging.

#### Acceptance Criteria

1. THE Post_Generation_Engine SHALL log an AuditLog entry for each Pipeline_Run start (action: "pipeline_run_start") and completion (action: "pipeline_run_complete") or failure (action: "pipeline_run_failed"), with entity_type "pipeline_run" and details including the pipeline run_id, client_id, avatar_id, and list of pipeline steps to execute
2. WHEN a PostDraft is created during a pipeline run, THE Post_Generation_Engine SHALL log an ActivityEvent with event_type "post_draft_created" and metadata containing the pipeline run_id, the originating pipeline step name, the draft_id, and the target subreddit
3. WHEN an LLM call completes within the pipeline, THE Post_Generation_Engine SHALL log an AIUsageLog entry recording the operation name, model identifier, input_tokens, output_tokens, cost_usd, duration_ms, and the pipeline run_id as triggered_by context
4. IF any pipeline step fails, THEN THE Post_Generation_Engine SHALL log the failure as an AuditLog entry with action "pipeline_step_failed", details including the step name, error message (max 1000 characters), list of previously completed step names, and the pipeline run_id for correlation
5. THE Post_Generation_Engine SHALL emit structured JSON logs at INFO level for each pipeline step completion and at ERROR level for failures, where each log entry includes the fields: timestamp, level, pipeline run_id, step_name, client_id, duration_ms, and status ("success" or "error")
6. THE Post_Generation_Engine SHALL assign a unique run_id (UUID) to each Pipeline_Run and include this run_id in all AuditLog entries, ActivityEvent metadata, AIUsageLog records, and structured log entries emitted during that run, enabling end-to-end correlation of a single pipeline execution

### Requirement 16: Self-Learning Integration

**User Story:** As a platform operator, I want the engine to improve over time based on human edits, so that post quality increases with accumulated feedback.

#### Acceptance Criteria

1. WHEN a human editor approves a post draft with modifications, THE Post_Generation_Engine SHALL capture an EditRecord storing the original AI draft, the edited draft, a deterministic edit summary (max 500 characters), the associated avatar, client, and subreddit
2. WHEN a human editor approves a draft unchanged or rejects a draft, THE Post_Generation_Engine SHALL capture an EditRecord with the corresponding final status (approved_unchanged or rejected) so that rejection examples and approval-without-edit signals are available for learning
3. WHEN generating a new post, THE Post_Generation_Engine SHALL select up to 3 few-shot examples (max 2 positive, max 1 negative) from the 50 most recent non-archived EditRecords for that avatar-client pair, scored by subreddit match (+2) and post_type match (+1), and inject them into the generation prompt as before/after correction pairs
4. WHEN 5 or more approved-with-edits EditRecords exist for an avatar-client pair, THE Post_Generation_Engine SHALL extract correction patterns that recur in 2 or more edit summaries, store the top 3 patterns by frequency as imperative rules (max 100 characters each), and inject them into the generation prompt as correction constraints
5. IF the learning service fails during edit capture or prompt injection, THEN THE Post_Generation_Engine SHALL log the failure and continue generation without learning context, ensuring the review and generation workflows are never blocked by learning errors
6. THE Post_Generation_Engine SHALL enforce retention limits of 200 non-archived EditRecords per avatar-client pair, archiving oldest records beyond this cap and permanently deleting archived records older than 180 days

### Requirement 17: Scheduling Integration

**User Story:** As a platform operator, I want generated posts to integrate with EPG scheduling, so that posts are published at optimal times.

#### Acceptance Criteria

1. WHEN a PostDraft is created with status "pending", THE Post_Generation_Engine SHALL mark the draft as eligible for EPG slot assignment within 5 seconds of creation
2. WHILE assigning an EPG slot to a PostDraft, THE Post_Generation_Engine SHALL enforce a minimum interval of 24 hours between any two scheduled post slots for the same avatar
3. IF a PostDraft is created for an avatar that already has 2 or more PostDrafts with status "pending", THEN THE Post_Generation_Engine SHALL reject the generation request and log the rejection reason as "queue_full"
4. IF no EPG slot is available within the next 7 days for the target avatar, THEN THE Post_Generation_Engine SHALL set the PostDraft status to "pending" without a slot assignment and emit an activity event indicating no available scheduling window
