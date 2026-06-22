# Requirements Document

## Introduction

This feature closes the architectural gap between client onboarding and avatar execution in the trial flow. Currently, a trial client can reach "Active" status without a confirmed Avatar, creating a dead state where the pipeline has no execution actor (zero comments, zero EPG slots, zero output). The solution introduces an AvatarDraft intermediate entity, an async BYOA (Bring Your Own Avatar) pipeline, an ExternalRequestScheduler for all outbound calls, and a system invariant that prevents any client from being active without a confirmed avatar.

## Glossary

- **System**: The RAMP platform backend (FastAPI + Celery + PostgreSQL)
- **Onboarding_Wizard**: The 6-step client self-service onboarding flow
- **Avatar_Draft**: An intermediate entity representing a Reddit account undergoing analysis, not yet confirmed as an Avatar
- **Avatar**: A confirmed execution entity (Reddit account) assigned to a client, eligible for pipeline participation
- **BYOA_Pipeline**: The Bring Your Own Avatar async workflow: username input → Reddit fetch → AI analysis → user confirmation → Avatar creation
- **External_Request_Scheduler**: A centralized service that queues, rate-limits, and retries all outbound calls (Reddit PRAW, AI/LLM, scraping)
- **Reddit_Snapshot**: A stored record of fetched Reddit profile data (comments, posts, subreddits, karma) for a given username at a point in time
- **AI_Profile_Analysis**: The Claude-generated behavioral profile (tone, topics, risk flags, voice) derived from a Reddit_Snapshot
- **Trial_Client**: A client with plan_type="trial" on a 14-day free evaluation period
- **Client_Status**: The lifecycle state of a client (onboarding_incomplete, pending_execution, active)
- **Profiling_Job**: A queued background task in the BYOA_Pipeline (FETCH_REDDIT_PROFILE or AI_PROFILE_ANALYSIS)

## Requirements

### Requirement 1: AvatarDraft Entity Lifecycle

**User Story:** As a platform operator, I want an intermediate AvatarDraft state between username submission and Avatar creation, so that avatars only exist after full analysis and user confirmation.

#### Acceptance Criteria

1. WHEN a user submits a Reddit username for avatar onboarding, THE System SHALL create an Avatar_Draft entity with status "pending_fetch", storing the reddit_username, client_id, created_by_user_id, created_at timestamp, and status field
2. THE Avatar_Draft SHALL store: reddit_username (max 20 characters), client_id, created_by_user_id, status, created_at, and a nullable foreign key reference to the associated Reddit_Snapshot record and AI_Profile_Analysis record
3. WHILE an Avatar_Draft exists in a non-terminal status ("pending_fetch", "analyzing", or "ready_for_review"), THE System SHALL prevent creation of an Avatar entity for that reddit_username within the same client scope
4. WHEN the AI_Profile_Analysis completes successfully for an Avatar_Draft, THE System SHALL transition the Avatar_Draft status to "ready_for_review"
5. WHEN a user confirms an Avatar_Draft in status "ready_for_review", THE System SHALL create the Avatar entity with data from the draft (reddit_username, display_name, persona_bio, voice_profile, hobby/business subreddits), assign it to the client, and transition the Avatar_Draft status to "confirmed"
6. WHEN a user rejects an Avatar_Draft, THE System SHALL transition the Avatar_Draft status to "rejected" and retain the draft record for a minimum of 90 days
7. IF the FETCH_REDDIT_PROFILE job fails after 3 retry attempts, THEN THE System SHALL transition the Avatar_Draft status to "fetch_failed" and create an in-app notification for the user who initiated the draft indicating the fetch failure and the reddit_username
8. IF the AI_PROFILE_ANALYSIS job fails after 3 retry attempts, THEN THE System SHALL transition the Avatar_Draft status to "analysis_failed" and create an in-app notification for the user who initiated the draft indicating the analysis failure and the reddit_username
9. THE Avatar_Draft SHALL enforce uniqueness on reddit_username per client for drafts in non-terminal statuses ("pending_fetch", "analyzing", "ready_for_review"), while permitting a new draft if all existing drafts for that username within the client are in terminal statuses ("confirmed", "rejected", "fetch_failed", "analysis_failed")
10. IF an Avatar_Draft remains in status "pending_fetch" or "analyzing" for more than 60 minutes without a state transition, THEN THE System SHALL transition the Avatar_Draft status to the corresponding failure status ("fetch_failed" or "analysis_failed") and create an in-app notification for the user who initiated the draft

### Requirement 2: Async BYOA Pipeline

**User Story:** As a trial user, I want to submit my Reddit username and have the system analyze it in the background, so that I am not blocked waiting for Reddit API and AI calls to complete.

#### Acceptance Criteria

1. WHEN a user submits a Reddit username in the BYOA step, THE System SHALL create the Avatar_Draft in "pending_fetch" status and enqueue a FETCH_REDDIT_PROFILE Profiling_Job within 2 seconds
2. WHEN a FETCH_REDDIT_PROFILE job executes, THE System SHALL fetch the last 100 comments, 25 posts, subreddit activity, and karma data from Reddit using PRAW, and store the result as a Reddit_Snapshot
3. WHEN a Reddit_Snapshot is stored successfully, THE System SHALL enqueue an AI_PROFILE_ANALYSIS Profiling_Job
4. WHEN an AI_PROFILE_ANALYSIS job executes, THE System SHALL produce tone, topics, risk_flags, voice_profile, strategy suggestions, and persona_bio from the Reddit_Snapshot data
5. WHEN the AI_Profile_Analysis completes, THE System SHALL store the structured result and transition the Avatar_Draft to "ready_for_review"
6. THE BYOA_Pipeline SHALL process jobs in sequential order per Avatar_Draft (FETCH_REDDIT_PROFILE must complete before AI_PROFILE_ANALYSIS begins)
7. IF the Reddit username does not exist or the account is suspended, THEN THE System SHALL mark the Avatar_Draft as "fetch_failed" with an error message indicating the reason for failure (account not found or account suspended) within the FETCH_REDDIT_PROFILE job
8. IF the AI_PROFILE_ANALYSIS job fails after 3 retry attempts (exponential backoff: 60, 120, 240 seconds), THEN THE System SHALL mark the Avatar_Draft as "analysis_failed" with an error message indicating the failure reason
9. IF a FETCH_REDDIT_PROFILE job fails due to a transient error (timeout or rate limit), THEN THE System SHALL retry up to 3 times with exponential backoff (60, 120, 240 seconds) before marking the Avatar_Draft as "fetch_failed"

### Requirement 3: ExternalRequestScheduler

**User Story:** As a platform operator, I want all external API calls (Reddit, AI, scraping) to go through a centralized scheduler with rate limiting and retry logic, so that the system respects API limits and handles transient failures gracefully.

#### Acceptance Criteria

1. THE External_Request_Scheduler SHALL route all outbound Reddit PRAW calls through a per-service rate limiter enforcing a configurable maximum request rate (default 30 requests per 60-second sliding window)
2. THE External_Request_Scheduler SHALL route all outbound AI/LLM calls through a per-service rate limiter enforcing a configurable maximum request rate (default 60 requests per 60-second sliding window)
3. THE External_Request_Scheduler SHALL enforce a global concurrency cap across all external call types (configurable, default 10 concurrent outbound requests)
4. WHEN an external call fails with a transient error (HTTP 429, HTTP 5xx, or no response within the per-service timeout — default 30 seconds), THE External_Request_Scheduler SHALL retry with exponential backoff (base 60 seconds, max 3 retries, yielding delays of 60s, 120s, 240s)
5. THE External_Request_Scheduler SHALL implement a priority queue where paid client requests (plan_type other than "trial") execute before trial client requests at the same priority tier
6. THE External_Request_Scheduler SHALL implement a priority queue where user-facing flows (BYOA onboarding) execute before background jobs (scheduled scraping, health checks), with requests at equal priority processed in FIFO order
7. WHEN the global concurrency cap is reached, THE External_Request_Scheduler SHALL queue additional requests and process them in priority order as capacity becomes available
8. THE External_Request_Scheduler SHALL log all outbound requests with: service_name, duration_ms, success/failure, retry_count, priority_level
9. IF an external call has exhausted all 3 retry attempts, THEN THE External_Request_Scheduler SHALL mark the request as permanently failed, emit an activity event with service_name and failure reason, and propagate the failure to the calling task without further retry

### Requirement 4: Non-Blocking Onboarding UX

**User Story:** As a trial user, I want the onboarding wizard to remain interactive while my Reddit profile is being analyzed, so that I can continue setting up other aspects of my account or wait for the result.

#### Acceptance Criteria

1. WHEN a user submits a Reddit username in the BYOA step, THE Onboarding_Wizard SHALL dispatch the profile analysis as a background task and display an "AVATAR_PROFILING_IN_PROGRESS" state within 2 seconds, leaving all wizard navigation and other form fields interactive
2. WHILE the Avatar_Draft is in status "pending_fetch" or "analyzing", THE Onboarding_Wizard SHALL poll the backend every 2 seconds and display a progress indicator showing the current stage (fetching profile, running AI analysis)
3. IF the Avatar_Draft has not transitioned out of "pending_fetch" or "analyzing" within 90 seconds of submission, THEN THE Onboarding_Wizard SHALL stop polling and display a timeout error with an option to retry
4. WHEN the Avatar_Draft transitions to "ready_for_review", THE Onboarding_Wizard SHALL display the AI interpretation preview with editable fields (display_name, persona_bio, voice_profile, tone_principles, hill_i_die_on, helpful_mode_topics, hobby_subreddits, business_subreddits) for user confirmation
5. THE Onboarding_Wizard SHALL allow the user to remain on the BYOA step and wait for completion, or navigate away and return later; the Avatar_Draft SHALL persist for at least 24 hours
6. WHEN the user returns to the BYOA step with an existing Avatar_Draft in "ready_for_review" status, THE Onboarding_Wizard SHALL display the preview card within 2 seconds of page load without re-running analysis
7. IF the Avatar_Draft enters a failed state (fetch_failed or analysis_failed), THEN THE Onboarding_Wizard SHALL display an error message indicating the failure reason (profile not found, account suspended, or AI service unavailable) with an option to retry with the same or different username
8. IF the user submits a new Reddit username while an existing Avatar_Draft is in "pending_fetch" or "analyzing" status, THEN THE Onboarding_Wizard SHALL cancel the previous analysis and start a new one for the submitted username

### Requirement 5: Client Active State Invariant

**User Story:** As a platform operator, I want to guarantee that no client can be in "active" status without at least one confirmed Avatar, so that the pipeline always has an execution actor for active clients.

#### Acceptance Criteria

1. THE System SHALL enforce the invariant: a client with is_active=True AND onboarding_completed_at set MUST have at least one Avatar where avatar.active=True AND the client's ID is present in the avatar's client_ids array
2. WHEN the Onboarding Wizard step 6 activation endpoint is invoked, THE System SHALL block activation (return user to step 6 with an error message indicating missing avatar) unless at least one Avatar exists with active=True and the client's ID in its client_ids array
3. WHILE a client has zero Avatars matching the invariant condition (active=True AND client ID in client_ids), THE System SHALL prevent setting onboarding_completed_at and SHALL keep is_active=False regardless of other onboarding steps completed
4. IF the last Avatar matching the invariant condition for a client is deactivated (active set to False) or unassigned (client ID removed from client_ids), THEN THE System SHALL set client.is_active to False, which causes all pipeline tasks (scraping, scoring, generation, EPG building, posting) to skip that client
5. WHEN a client has is_active=False due to zero qualifying Avatars and a new Avatar is assigned with active=True and the client's ID in client_ids, THE System SHALL set client.is_active back to True within 60 seconds, restoring pipeline task eligibility for that client
6. THE System SHALL run a daily integrity check (scheduled via Celery Beat) that queries all clients where is_active=True AND onboarding_completed_at IS NOT NULL, verifies at least one qualifying Avatar exists for each, and for any violating client sets is_active=False and creates a Notification record of type "invariant_violation" visible to users with owner or partner role

### Requirement 6: BYOA Step Integration in Onboarding Wizard

**User Story:** As a trial user, I want the onboarding wizard to include a dedicated BYOA avatar step where I provide my Reddit username, see the AI analysis, and confirm my avatar before completing onboarding.

#### Acceptance Criteria

1. THE Onboarding_Wizard SHALL include a BYOA step as Step 5 (shifting the current "Keywords & Subreddits" step to Step 4 or merging it with an earlier step) that displays a single text input field accepting a Reddit username (with or without the "u/" prefix, maximum 20 characters per Reddit's username limit)
2. WHEN a user enters a Reddit username in the BYOA step and submits the form, THE Onboarding_Wizard SHALL display the text "We are analyzing your profile" accompanied by a visible progress animation, and SHALL disable the submit button to prevent duplicate submissions
3. WHEN analysis completes successfully, THE Onboarding_Wizard SHALL display the AI interpretation preview including: voice_profile.tone, voice_profile.style, strategy.helpful_mode_topics, subreddits (hobby and business lists), persona_bio, voice_profile.tone_principles, classification.avatar_type, and classification.synthetic_likelihood
4. WHEN analysis completes successfully, THE Onboarding_Wizard SHALL render the following fields as editable text inputs or textareas pre-filled with AI-generated values: display_name (max 50 characters), persona_bio (max 200 characters), and tone_principles (free-text)
5. WHEN the user confirms the preview by clicking the confirmation button, THE System SHALL create the Avatar record assigned to the user's client, set warming_phase to 1, and allow the wizard to proceed to the final activation step
6. THE Onboarding_Wizard SHALL block progression past the BYOA step until at least one Avatar has been confirmed, by disabling the "Next" or "Continue" button and displaying a message indicating that an avatar is required
7. IF the user has previously confirmed an Avatar and navigates back to the BYOA step, THE Onboarding_Wizard SHALL display a summary card showing the confirmed avatar's display_name, reddit_username, and tone, and SHALL display an "Add Another Avatar" button only if the number of confirmed avatars is less than the client's max_avatars plan limit
8. IF the AI analysis fails (Reddit profile not found, account suspended, or LLM error), THEN THE Onboarding_Wizard SHALL display an error message indicating the failure reason and allow the user to re-enter a different username without losing any previously entered wizard data
9. IF the entered Reddit username already exists in the system (assigned to any client), THEN THE Onboarding_Wizard SHALL display a message indicating the username is unavailable and SHALL NOT proceed with analysis

### Requirement 7: Trial Avatar Limit Enforcement

**User Story:** As a platform operator, I want trial accounts limited to one avatar through the BYOA flow, so that trial resource consumption is bounded.

#### Acceptance Criteria

1. WHILE a client has plan_type="trial", THE System SHALL allow a maximum of one Avatar_Draft in non-terminal status (pending_fetch, analyzing, ready_for_review) at any time
2. WHILE a client has plan_type="trial", THE System SHALL allow a maximum of one confirmed, active Avatar (Avatar.active=True)
3. IF a trial client attempts to create a second Avatar_Draft while the combined count of non-terminal Avatar_Drafts plus confirmed active Avatars is already 1 or more, THEN THE System SHALL reject the request with an error message indicating the trial plan is limited to one avatar and an upgrade is required to add more
4. WHEN an Avatar_Draft for a trial client transitions to a terminal status (fetch_failed, analysis_failed, rejected), THE System SHALL allow the client to initiate a new Avatar_Draft submission without counting the terminated draft toward the trial limit
5. WHEN a trial client upgrades to a paid plan (plan_type changes from "trial" to "starter", "growth", or "scale"), THE System SHALL remove the single-avatar restriction and allow additional BYOA submissions up to the client's max_avatars limit
6. IF a trial client's only confirmed Avatar is deactivated (Avatar.active set to False), THEN THE System SHALL allow the client to initiate a new Avatar_Draft submission

### Requirement 8: First Value Generation Target

**User Story:** As a trial user, I want the system to begin generating value (pipeline output) within 24 hours of avatar confirmation, so that I experience the platform's capabilities quickly.

#### Acceptance Criteria

1. WHEN an Avatar is confirmed through the BYOA flow, THE System SHALL dispatch the post-onboarding pipeline (discovery session creation, entity extraction, strategy generation, subreddit scraping, scoring, and comment generation) as Celery tasks within 5 minutes of confirmation
2. WHEN the post-onboarding pipeline is dispatched for a client with at least 1 active subreddit assignment and at least 1 keyword configured, THE System SHALL generate at least 1 comment draft within 60 minutes of avatar confirmation
3. WHEN the first comment draft is generated for a newly confirmed avatar, THE System SHALL send a notification of type "success" to the client via the existing notification system (SSE + Redis PubSub) indicating that content is ready for review and linking to the review queue
4. IF no comment drafts are generated within 24 hours of avatar confirmation, THEN THE System SHALL create an admin alert (stored as an ActivityEvent of type "onboarding_stall_detected") identifying the client ID, avatar ID, and the last completed pipeline step for manual investigation
5. IF the post-onboarding pipeline is dispatched for a client with no active subreddit assignments or no keywords configured, THEN THE System SHALL send a notification to the client indicating that subreddit and keyword configuration is required before content generation can begin
