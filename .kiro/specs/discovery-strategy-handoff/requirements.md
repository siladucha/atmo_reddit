# Requirements Document

## Introduction

Replace the current shallow Discovery-to-Strategy handoff with a full Client Strategy generation step. When an operator clicks "Create Strategy" on a completed Discovery session, the system generates a structured Client Strategy document using Gemini Flash (single LLM call, ~10-15s). This Client Strategy becomes the operational context that downstream pipeline components (generation, EPG, phase evaluation, GEO) consume to produce targeted, strategy-aware content. The feature eliminates manual operator work of copying report findings into strategy documents.

## Glossary

- **Client_Strategy**: A structured JSON document stored per client containing positioning, subreddit priorities, content pillars, forbidden zones, AEO targets, and phase roadmap. Generated from Discovery Report data via a single LLM call.
- **Handoff_Service**: The service (`strategy_handoff.py`) responsible for orchestrating the Discovery → Client Strategy generation flow, including client creation, strategy generation, subreddit import, GEO prompt creation, and session status update.
- **Strategy_Generator**: The component that takes Visibility Report content and client brief as input, calls Gemini Flash, and produces a validated Client_Strategy JSON object.
- **Visibility_Report**: The JSON report produced by the Discovery Engine containing communities, entry points, competitive landscape, visibility outcomes, and confirmed hypotheses.
- **Operator**: A platform admin (owner or partner role) who manages Discovery sessions and triggers strategy creation.
- **Pipeline**: The downstream content generation system that reads Client_Strategy for approach selection, slot allocation, and phase-appropriate content generation.
- **GEO_Module**: The GEO/AEO monitoring subsystem that tracks brand visibility in AI search results using configured prompts per client.

## Requirements

### Requirement 1: Client Strategy Generation via LLM

**User Story:** As an operator, I want the system to generate a structured Client Strategy from the Discovery Report, so that the pipeline has operational context for content generation without manual strategy authoring.

#### Acceptance Criteria

1. WHEN the operator triggers strategy creation on a completed Discovery session, THE Strategy_Generator SHALL produce a Client_Strategy JSON containing: positioning, subreddit_priorities, content_pillars, forbidden_zones, aeo_targets, and phase_roadmap sections.
2. THE Strategy_Generator SHALL use the Gemini Flash model (`gemini/gemini-2.5-flash`) with max_tokens=2048 for generation.
3. WHEN the Strategy_Generator receives Visibility Report content and client brief as input, THE Strategy_Generator SHALL complete generation within 15 seconds under normal network conditions.
4. THE Strategy_Generator SHALL validate the LLM output against a Pydantic schema before persisting the Client_Strategy.
5. IF the LLM returns invalid JSON or fails schema validation, THEN THE Strategy_Generator SHALL retry generation once with the same input.
6. IF both generation attempts fail validation, THEN THE Handoff_Service SHALL log the failure, report an error to the operator, and leave the session in its current state without data loss.

### Requirement 2: Client Strategy Data Model

**User Story:** As a pipeline developer, I want Client Strategy stored in a structured, queryable format, so that downstream services can read specific strategy sections without parsing free text.

#### Acceptance Criteria

1. THE Client_Strategy SHALL be stored as a JSONB field on the Client model or as a dedicated model linked to the Client.
2. THE Client_Strategy SHALL contain the following top-level sections: positioning (object), subreddit_priorities (array), content_pillars (array of 3-5 items), forbidden_zones (array), aeo_targets (array), and phase_roadmap (object with phase_1, phase_2, phase_3 keys).
3. THE Client_Strategy SHALL include metadata: generated_at timestamp, source_session_id (UUID of the Discovery session), model_used, and generation_cost_usd.
4. WHEN a new Client_Strategy is generated for a client that already has one, THE Handoff_Service SHALL replace the existing strategy with the new version.

### Requirement 3: One-Click Handoff Flow

**User Story:** As an operator, I want a single button click to execute the full strategy handoff (generate strategy, import subreddits, create GEO prompts, mark session), so that I don't perform multiple manual steps.

#### Acceptance Criteria

1. WHEN the operator clicks "Create Strategy" on a completed Discovery session, THE Handoff_Service SHALL execute the following steps in order: create or resolve client record, generate Client_Strategy via LLM, save strategy to client, import subreddit assignments with priorities from the report, create GEO prompts from AEO targets (if geo_monitoring_enabled is true for the client), and mark the session status as "handed_off".
2. WHEN all handoff steps complete successfully, THE Handoff_Service SHALL redirect the operator to the client detail page.
3. IF any step after client resolution fails, THEN THE Handoff_Service SHALL roll back database changes and display an error message to the operator.
4. WHILE the strategy generation is in progress, THE Handoff_Service SHALL display a loading indicator to the operator.

### Requirement 4: Subreddit Priority Import

**User Story:** As a pipeline developer, I want subreddit assignments to carry priority rankings from the Discovery Report, so that EPG can allocate slots proportionally.

#### Acceptance Criteria

1. WHEN subreddits are imported during handoff, THE Handoff_Service SHALL assign a priority rank (1-based integer) to each ClientSubredditAssignment based on the relevance score ordering from the Visibility Report communities.
2. WHEN subreddits are imported, THE Handoff_Service SHALL store the recommended engagement approach from the report on each assignment.
3. THE Handoff_Service SHALL import a maximum of 10 subreddits from the report communities list.
4. IF a subreddit is already assigned to the client, THEN THE Handoff_Service SHALL update the priority and approach fields without creating a duplicate assignment.

### Requirement 5: GEO Prompt Auto-Creation

**User Story:** As an operator, I want GEO monitoring prompts automatically created from the strategy's AEO targets, so that brand visibility tracking starts immediately after handoff.

#### Acceptance Criteria

1. WHEN geo_monitoring_enabled is true for the client AND the Client_Strategy contains aeo_targets, THE Handoff_Service SHALL create one GeoPrompt record per AEO target entry.
2. THE Handoff_Service SHALL set the GeoPrompt category to "discovery_generated" for auto-created prompts.
3. IF a GeoPrompt with identical prompt_text already exists for the client, THEN THE Handoff_Service SHALL skip creation of that prompt without error.
4. WHEN geo_monitoring_enabled is false for the client, THE Handoff_Service SHALL skip GEO prompt creation entirely.

### Requirement 6: Pipeline Consumption of Client Strategy

**User Story:** As a pipeline developer, I want generation and EPG services to read Client Strategy fields, so that content is strategy-aware from the first pipeline run after handoff.

#### Acceptance Criteria

1. WHEN generating a comment for an avatar assigned to a client with a Client_Strategy, THE Pipeline SHALL include the positioning and content_pillars from Client_Strategy in the generation prompt context.
2. WHEN building the EPG for an avatar, THE Pipeline SHALL use subreddit_priorities from Client_Strategy to weight slot allocation.
3. WHEN evaluating phase transitions, THE Pipeline SHALL reference phase_roadmap from Client_Strategy to determine phase-appropriate activities.
4. WHEN generating content, THE Pipeline SHALL respect forbidden_zones from Client_Strategy by including them as negative constraints in the generation prompt.

### Requirement 7: Strategy-to-Avatar Strategy Linkage

**User Story:** As a pipeline developer, I want avatar-level StrategyDocument to reference the parent Client Strategy, so that avatar strategies inherit and specialize from the client-level context.

#### Acceptance Criteria

1. WHEN a StrategyDocument is generated for an avatar belonging to a client with a Client_Strategy, THE strategy_engine SHALL inject Client_Strategy context (positioning, content_pillars, forbidden_zones) into the avatar strategy generation prompt.
2. THE StrategyDocument model SHALL include an optional client_strategy_id field referencing the Client_Strategy that was active at generation time.

### Requirement 8: Performance and Cost Constraints

**User Story:** As a platform operator, I want strategy generation to be fast and cheap, so that it doesn't block the handoff workflow or inflate operational costs.

#### Acceptance Criteria

1. THE Strategy_Generator SHALL complete the LLM call within a 30-second timeout (inclusive of retry).
2. THE Strategy_Generator SHALL produce output within approximately $0.002 per generation at current Gemini Flash pricing.
3. THE Strategy_Generator SHALL use only the already-computed Visibility Report content from the database as input, performing no additional Reddit API calls or research.
4. THE Strategy_Generator SHALL set max_tokens=2048 for the LLM request to stay within nginx proxy timeout limits.

### Requirement 9: Session Status Tracking

**User Story:** As an operator, I want to see which Discovery sessions have been handed off, so that I can track which prospects have progressed to active pipeline clients.

#### Acceptance Criteria

1. WHEN the handoff completes successfully, THE Handoff_Service SHALL update the Discovery session status to "handed_off".
2. THE Discovery session list view SHALL display a visual indicator (badge or status label) for sessions with "handed_off" status.
3. WHEN a session is in "handed_off" status, THE system SHALL disable the "Create Strategy" button for that session to prevent duplicate handoffs.
