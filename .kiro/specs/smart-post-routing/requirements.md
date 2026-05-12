# Requirements Document

## Introduction

Smart Post Routing is an intelligent post idea processing pipeline that takes a free-form post idea from an operator, selects the optimal avatar and subreddits, repackages the content for each target community, and presents variants for human review. The feature prevents the kind of misrouted posts that caused the Hot-Thought2408 karma drop (posting off-topic content in a subreddit where the avatar had no presence) by automating avatar selection, subreddit routing, tone adaptation, and risk assessment.

## Glossary

- **Routing_Engine**: The service that accepts a raw post idea and orchestrates avatar selection, subreddit routing, content repackaging, and risk scoring
- **Avatar_Selector**: The component that evaluates which avatar best matches a given post idea based on niche alignment, voice profile, and topic expertise
- **Subreddit_Router**: The component that identifies optimal target subreddits for a post idea based on avatar presence, topic relevance, and phase constraints
- **Content_Repackager**: The component that adapts a post idea into subreddit-specific variants matching the avatar's voice and the community's culture
- **Risk_Assessor**: The component that evaluates downvote risk, factual accuracy, and phase compliance for each post variant
- **Post_Idea**: A free-form natural language input from an operator describing a thought, complaint, insight, or topic they want published on Reddit
- **Post_Variant**: A fully repackaged post (title + body) tailored for a specific avatar/subreddit combination
- **Routing_Result**: The complete output of the routing pipeline containing avatar selection, subreddit recommendations, post variants, and risk scores
- **Presence_Score**: A numeric measure of an avatar's established activity in a specific subreddit, derived from AvatarSubredditPresence and SubredditKarma data
- **Risk_Score**: A numeric assessment (0-100) of the likelihood a post variant will receive negative engagement in its target subreddit
- **Operator**: A human user (client manager or client) who submits post ideas and reviews generated variants

## Requirements

### Requirement 1: Post Idea Submission

**User Story:** As an operator, I want to submit a free-form post idea in natural language, so that the system can intelligently route and repackage it without me needing to specify avatar, subreddit, or tone.

#### Acceptance Criteria

1. THE Routing_Engine SHALL accept a Post_Idea as a free-form text input with a minimum length of 10 characters and a maximum length of 5000 characters
2. IF a Post_Idea is submitted with fewer than 10 characters or more than 5000 characters, THEN THE Routing_Engine SHALL reject the submission and display an error message indicating the length constraint violation
3. WHEN a Post_Idea is submitted, THE Routing_Engine SHALL associate the Post_Idea with the operator's active client profile, including the client's keywords, assigned subreddits, and assigned avatars
4. WHEN a Post_Idea is submitted without specifying a target avatar, THE Avatar_Selector SHALL automatically select the highest-ranked eligible avatar based on subreddit karma score, voice-profile relevance to the Post_Idea topic, and current warming phase eligibility
5. IF an operator specifies a preferred avatar that is frozen, unhealthy, or in a warming phase that prohibits the target action, THEN THE Routing_Engine SHALL reject the avatar selection and display an error message indicating the avatar is ineligible along with the reason
6. WHERE an operator specifies a preferred avatar that is eligible, THE Routing_Engine SHALL use the specified avatar and skip automatic avatar selection
7. WHERE an operator specifies one or more preferred subreddits, THE Subreddit_Router SHALL include those subreddits in the routing evaluation and display a warning indicator on each subreddit that fails avatar presence or phase eligibility checks, while still allowing the operator to proceed with the submission

### Requirement 2: Avatar Selection

**User Story:** As an operator, I want the system to automatically select the avatar whose niche best matches my post idea, so that the content appears authentic and credible in the target communities.

#### Acceptance Criteria

1. WHEN a Post_Idea is submitted without a specified avatar, THE Avatar_Selector SHALL evaluate all active, non-frozen avatars belonging to the client whose warming_phase is between 1 and 3 inclusive, whose health_status is not "shadowbanned" or "suspended", and whose cqs_level is not "lowest"
2. IF only one eligible avatar remains after filtering, THEN THE Avatar_Selector SHALL assign that avatar directly without invoking the LLM scoring call
3. WHEN evaluating avatar fit across two or more eligible candidates, THE Avatar_Selector SHALL score each candidate based on: topic alignment with voice_profile and hill_i_die_on (weight 40%), subreddit presence overlap with the post topic (weight 30%), and current karma in the target subreddit (weight 30%)
4. THE Avatar_Selector SHALL return the top-scoring avatar along with a confidence score (0-100), the selected engagement mode, and a one-sentence explanation of why the avatar was selected
5. IF no eligible avatar scores above a confidence threshold of 30, THEN THE Avatar_Selector SHALL reject the Post_Idea with a message indicating that no suitable avatar exists for this topic and listing the count of candidates evaluated
6. IF no avatars pass the eligibility filters for the client, THEN THE Avatar_Selector SHALL reject the Post_Idea with a message indicating that zero eligible avatars are available, without invoking the scoring step
7. THE Avatar_Selector SHALL complete the selection process and return a result within 10 seconds of invocation

### Requirement 3: Subreddit Routing

**User Story:** As an operator, I want the system to identify 2-3 optimal subreddits for my post idea, so that the content reaches communities where it will be well-received.

#### Acceptance Criteria

1. WHEN an avatar is selected and a post idea is provided, THE Subreddit_Router SHALL identify between 2 and 3 target subreddits from the avatar's hobby_subreddits and business_subreddits lists
2. THE Subreddit_Router SHALL only select subreddits where the avatar has a Presence_Score greater than 0 (at least one prior comment or post recorded in AvatarSubredditPresence)
3. THE Subreddit_Router SHALL only select subreddits that are permitted by the avatar's current warming_phase (Phase 1: hobby_subreddits only; Phase 2+: hobby_subreddits and business_subreddits)
4. WHEN scoring subreddit candidates, THE Subreddit_Router SHALL evaluate: topic relevance of the post idea to the subreddit's known focus based on keyword and theme overlap (weight 40%), avatar total_karma in the subreddit from SubredditKarma records (weight 30%), and recency of avatar activity in the subreddit where activity within 7 days scores full marks and activity older than 30 days scores zero with linear decay between (weight 30%)
5. THE Subreddit_Router SHALL return each selected subreddit with a relevance score (0-100) and a rationale of no more than 200 characters explaining why the subreddit was chosen
6. IF fewer than 2 subreddits pass all eligibility checks, THEN THE Subreddit_Router SHALL return the available subreddits (which may be zero or one) along with a warning flag indicating that routing options are limited
7. THE Subreddit_Router SHALL apply a penalty of minus 20 points to the composite score of any subreddit where the avatar's total_karma is negative, after which standard ranking by final score applies
8. IF no post idea text is provided, THEN THE Subreddit_Router SHALL return an error indicating that a post idea is required for routing

### Requirement 4: Content Repackaging

**User Story:** As an operator, I want the system to adapt my post idea into subreddit-specific variants that match the avatar's voice and each community's culture, so that posts appear authentic and earn engagement.

#### Acceptance Criteria

1. WHEN subreddits are selected, THE Content_Repackager SHALL generate one Post_Variant (title + body) for each target subreddit
2. THE Content_Repackager SHALL adapt the tone and framing of each Post_Variant to match the selected avatar's voice_profile, tone_principles, and speech_patterns
3. THE Content_Repackager SHALL adapt the format and vocabulary of each Post_Variant to match the target subreddit's community culture based on the subreddit's known topic focus and formality level
4. WHILE the avatar is in warming_phase 1, THE Content_Repackager SHALL generate Post_Variants with zero brand mentions (brand name, brand URL, or brand product names)
5. WHILE the avatar is in warming_phase 2, THE Content_Repackager SHALL generate Post_Variants with zero explicit brand name or brand link mentions
6. THE Content_Repackager SHALL preserve the core insight or argument from the original Post_Idea across all variants while allowing framing and emphasis to differ per subreddit
7. THE Content_Repackager SHALL generate a title between 10 and 300 characters and a body between 100 and 600 words for each Post_Variant
8. THE Content_Repackager SHALL use the existing post generation pipeline (brief generation followed by post writing) for each variant, passing the Post_Idea as the topic_direction input
9. IF the Content_Repackager LLM call fails for a specific subreddit variant, THEN THE Content_Repackager SHALL skip that variant and continue generating remaining variants, returning a partial result with an error flag on the failed variant

### Requirement 5: Risk Assessment

**User Story:** As an operator, I want the system to assess the risk of each post variant before I approve it, so that I can avoid posts likely to get downvoted or damage avatar credibility.

#### Acceptance Criteria

1. WHEN a Post_Variant is generated, THE Risk_Assessor SHALL compute a Risk_Score between 0 and 100 for the variant within 10 seconds of generation completing
2. THE Risk_Assessor SHALL evaluate factual accuracy by prompting the LLM to identify unsupported claims in the Post_Variant that are not grounded in the provided post topic context, and assign a factual_risk sub-score between 0 and 30
3. THE Risk_Assessor SHALL evaluate tone alignment by comparing the Post_Variant's tone against the target subreddit's historical top-post language patterns (formality level, jargon usage, sentiment), and assign a tone_risk sub-score between 0 and 25
4. THE Risk_Assessor SHALL evaluate presence risk by checking whether the avatar has fewer than 3 prior interactions in the target subreddit, and if so, increase the Risk_Score by 20 points
5. THE Risk_Assessor SHALL evaluate phase compliance by verifying the Post_Variant contains no content prohibited by the avatar's current warming_phase (brand mentions in Phase 1, explicit brand links in Phase 2), and assign a phase_risk sub-score of 0 (compliant) or 25 (violation detected)
6. IF a Post_Variant receives a Risk_Score above 70, THEN THE Risk_Assessor SHALL flag the variant with a warning message indicating the highest-scoring risk dimension and its sub-score
7. THE Risk_Assessor SHALL return a breakdown containing the individual sub-scores for each evaluated dimension (factual_risk, tone_risk, presence_risk, phase_risk) alongside the total Risk_Score
8. IF the Risk_Assessor fails to compute a Risk_Score due to an LLM error or timeout, THEN THE Risk_Assessor SHALL assign a default Risk_Score of 100 and flag the variant with a warning indicating assessment failure

### Requirement 6: Variant Review and Approval

**User Story:** As an operator, I want to review all generated post variants side-by-side, so that I can approve, edit, or reject each one before posting.

#### Acceptance Criteria

1. WHEN the Routing_Engine completes processing, THE Routing_Engine SHALL present all Post_Variants to the operator in a single review interface displaying between 1 and 3 variants simultaneously
2. THE Routing_Engine SHALL display for each Post_Variant: the target subreddit, the selected avatar name, the generated title and body, the Risk_Score with per-dimension breakdown, and the subreddit relevance score (0-100)
3. WHEN an operator approves a Post_Variant, THE Routing_Engine SHALL create a PostDraft record with status "pending", populating client_id, avatar_id, subreddit, ai_title, and ai_body from the variant data
4. WHEN an operator edits a Post_Variant before approval, THE Routing_Engine SHALL store the AI-generated version in ai_title and ai_body, and the operator's edited version in edited_title and edited_body on the PostDraft record, enforcing a body length between 1 and 600 words
5. WHEN an operator rejects a Post_Variant, THE Routing_Engine SHALL log an ActivityEvent with action "post_variant_rejected" including the variant's subreddit and avatar_id, and SHALL NOT create a PostDraft for that variant
6. THE Routing_Engine SHALL allow the operator to approve, edit, or reject each variant independently without requiring all variants to be actioned before any decision takes effect
7. WHEN an operator completes an approve, edit, or reject action on a Post_Variant, THE Routing_Engine SHALL display a confirmation indicator on that variant showing the action taken and its timestamp
8. IF an operator submits an edited Post_Variant with an empty title or empty body, THEN THE Routing_Engine SHALL reject the submission and display an error message indicating which field is missing

### Requirement 7: Performance Tracking

**User Story:** As an operator, I want to track how routed posts perform after publishing, so that I can evaluate the routing quality and improve future decisions.

#### Acceptance Criteria

1. WHEN a routed PostDraft transitions to status "posted", THE Routing_Engine SHALL associate the post with its original Post_Idea and routing metadata via a routing_request_id foreign key on the PostDraft record
2. THE Routing_Engine SHALL track reddit_score, reddit_upvote_ratio, and reddit_num_comments for each posted variant using the existing karma tracking pipeline (track_karma_all_avatars task)
3. WHEN performance data is available (reddit_score is not null), THE Routing_Engine SHALL compute a routing success indicator: "success" if reddit_score is greater than 1, "neutral" if reddit_score is 0 or 1, "failure" if reddit_score is negative
4. THE Routing_Engine SHALL store routing metadata (selected avatar rationale, subreddit relevance scores, risk assessment breakdown, original Post_Idea text) in a JSONB column on the PostDraft record for retrospective analysis

### Requirement 8: Routing Pipeline Orchestration

**User Story:** As an operator, I want the routing pipeline to complete within a reasonable time, so that I can review and approve posts without excessive waiting.

#### Acceptance Criteria

1. WHEN a Post_Idea is submitted, THE Routing_Engine SHALL execute the pipeline steps in sequence (avatar selection, then subreddit routing, then content repackaging, then risk assessment) as a single asynchronous operation
2. THE Routing_Engine SHALL complete the full pipeline within 60 seconds for a standard routing request (1 avatar, 3 subreddits, 3 variants)
3. IF the pipeline exceeds 60 seconds without completing, THEN THE Routing_Engine SHALL terminate the operation and return a partial result containing any steps that completed before the timeout
4. IF any step in the pipeline fails, THEN THE Routing_Engine SHALL return a partial result containing the outputs of all completed steps and an error indication identifying which step failed and the failure category (LLM timeout, validation error, or upstream dependency failure)
5. IF the selected avatar does not belong to the requesting client, THEN THE Routing_Engine SHALL reject the routing request before content generation begins and return an error indicating a context isolation violation
6. THE Routing_Engine SHALL log an ActivityEvent for each routing request with the client_id, avatar_id, subreddit targets, and outcome (one of: "completed", "partial_failure", "rejected", or "timeout")
7. THE Routing_Engine SHALL enforce context isolation by verifying the selected avatar belongs to the requesting client before executing the content repackaging step
