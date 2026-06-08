# Requirements Document

## Introduction

The Discovery Engine is the foundational pre-engagement layer of the RAMP platform. It precedes strategy, persona design, EPG, and execution in the client lifecycle. Unlike the existing onboarding wizard (which assumes Reddit activity decisions have already been made), Discovery answers the fundamental question: "What can Reddit potentially give this client in the next 6-12 months?"

Discovery operates in two modes:

**One-Shot Discovery (Phase 0):** The operator inputs a client description, the system extracts entities, forms hypotheses about Reddit relevance, researches the Reddit ecosystem, and presents findings for operator confirmation or rejection — limited to 3-5 iterations per session. The output is a Visibility Report that serves as a sales artifact justifying the $4K setup fee.

**Continuous Discovery (Phase 1-2):** Once a client is active, Discovery continuously monitors Reddit accounts (avatars and targets), profiles behavior from posting history, detects deception between claimed and observed attributes, tracks attribution across the recommendation-to-outcome lifecycle, and updates the account model as new evidence appears. Continuous Discovery ensures the system trusts Reddit reality over user self-reports.

Discovery does NOT only analyze the client's business — it also profiles Reddit accounts to understand interests, expertise, community participation, and behavioral patterns. This profiling capability enables blind discovery of unknown accounts, validation against known ground truth, and deception detection when user claims contradict observed behavior.

The MVP one-shot Discovery is an internal operator tool (used by Max/Tzvi during client onboarding). Continuous Discovery extends this to post-execution monitoring, strategy validation, and model evolution over 30+ days of operation. Client-facing self-service Discovery is deferred to a later phase (6-12 months).

The platform flow becomes: Client → Discovery → Strategy → Persona Design → EPG → Execution → Feedback Loop (with Continuous Discovery observing throughout).

## Glossary

- **Discovery_Engine**: The system module that orchestrates iterative Reddit ecosystem research for a prospective or existing client, producing a Visibility Report.
- **Discovery_Session**: A single bounded research session (3-5 iterations) for one client, tracking all hypotheses, research results, and operator decisions.
- **Discovery_Iteration**: One cycle within a session: extract entities → form hypotheses → research Reddit → present findings → get operator confirmation/rejection.
- **Hypothesis**: A testable proposition about a client's potential Reddit relevance (e.g., "Target audience actively discusses [topic] in [subreddit]"). Carries a confidence score, provenance data, and status (proposed/confirmed/rejected).
- **Entity**: A named concept extracted from the client description — products, audiences, problems, industries, competitors, or use cases that become research targets.
- **Visibility_Report**: The final deliverable of a Discovery Session — a structured assessment of Reddit's potential value for the client over 6-12 months, covering demand signals, relevant communities, discussion activity, entry points, and competitive landscape.
- **Visibility_Outcome**: A categorized potential benefit from Reddit presence: clients, partners, feedback, recognition, hiring, or market research.
- **Operator**: A platform admin (owner/partner role) who runs Discovery on behalf of a client. In MVP, this is Max or Tzvi.
- **Client_Brief**: The initial free-text input describing the client's business, goals, and what they want to achieve — provided by the operator.
- **Confidence_Score**: A numeric value (0-100) with reasoning text, indicating how strongly Reddit data supports a given hypothesis.
- **Hypothesis_Provenance**: Metadata stored with each hypothesis: which client signals led to it, which Reddit data was used, and the reasoning behind the confidence score.
- **Reddit_Signal**: A data point from Reddit that supports or contradicts a hypothesis — post volume, comment engagement, subscriber counts, sentiment indicators, or competitor mentions.
- **Fact**: An objective observation from Reddit data (e.g., "Market perceives you as X"). Not a choice.
- **Choice**: A strategic decision by the operator (e.g., "I want to build presence in this direction"). Not a fact.
- **No_Signal_Assessment**: An explicit determination that Reddit has insufficient relevant discussions for a given hypothesis, with suggested alternative channels.
- **Blind_Profile**: A comprehensive profile of a Reddit account's interests, expertise, communities, and participation style, generated solely from observed Reddit history without prior user input.
- **Ground_Truth_Document**: A reference document describing the known attributes of a Reddit account (interests, expertise, communities, style), used to validate Discovery profiling accuracy.
- **Deception_Risk_Score**: A numeric value (0-100) indicating the degree of mismatch between user-claimed attributes and observed Reddit behavior, where 0 means fully confirmed and 100 means fully contradicted.
- **Attribution_Record**: A four-layer tracking record linking a recommended action to its reported status, observed Reddit execution, and observed outcomes.
- **Profile_Snapshot**: A versioned point-in-time capture of a Reddit account's profile (interests, communities, expertise, style), stored to enable historical comparison and trend analysis.
- **Explainability_Chain**: A structured trace from a strategy recommendation or EPG slot back to the observed Reddit data and logical reasoning that produced it.
- **Source_of_Truth_Hierarchy**: The architectural rule that observed Reddit actions take precedence over reported actions, which take precedence over recommended actions, when building or updating the account model.

## Requirements

### Requirement 1: Discovery Session Creation and Client Brief Input

**User Story:** As an operator, I want to start a Discovery session by describing a client and their goals in free text, so that the system can begin researching their Reddit fit without needing Reddit account details.

#### Acceptance Criteria

1. THE Discovery_Engine SHALL provide a form that accepts a free-text Client_Brief with the prompt "Tell us about yourself and what you want to achieve" (minimum 50, maximum 5000 characters with a live character counter), an optional client name field (maximum 200 characters), and an optional dropdown to link the session to an existing Client record.
2. WHEN the operator submits a Client_Brief with at least 50 characters, THE Discovery_Engine SHALL create a new Discovery_Session record with status "in_progress", linked to the operator's user account, and navigate the operator to the entity extraction step.
3. IF the operator submits a Client_Brief with fewer than 50 characters, THEN THE Discovery_Engine SHALL display an inline validation error below the text field indicating the minimum character requirement and how many characters are still needed.
4. THE Discovery_Engine SHALL allow linking a Discovery_Session to an existing Client record at creation time via the form, or creating it as a standalone prospect session when no client is selected.
5. THE Discovery_Engine SHALL store the original Client_Brief text immutably within the Discovery_Session for reference throughout the process.
6. IF the session creation fails due to a server error, THEN THE Discovery_Engine SHALL display an error message indicating the session could not be created and preserve the operator's entered text in the form. Error messages SHALL only be displayed when session creation actually fails, regardless of other transient server issues during the process.

### Requirement 2: Entity Extraction from Client Brief

**User Story:** As an operator, I want the system to automatically identify key business entities from the client description, so that research targets are clearly defined before Reddit analysis begins.

#### Acceptance Criteria

1. WHEN a Client_Brief is submitted, THE Discovery_Engine SHALL extract named entities using LLM analysis (Gemini Flash model) and categorize each entity as one of: products, audiences, problems, industries, competitors, or use_cases.
2. WHEN entity extraction completes, THE Discovery_Engine SHALL present the extracted entities grouped by category to the operator for review, displaying each entity's name and assigned category.
3. WHEN the operator modifies, removes, or adds entities, THE Discovery_Engine SHALL update the entity list and use the revised set for hypothesis formation.
4. WHEN a Client_Brief is submitted, THE Discovery_Engine SHALL extract between 3 and 20 entities, completing LLM extraction within 30 seconds.
5. IF LLM extraction returns fewer than 3 entities, THEN THE Discovery_Engine SHALL display a message indicating that the brief lacks sufficient detail for entity extraction and prompt the operator to add entities manually or revise the Client_Brief.
6. WHEN the operator confirms the entity list, THE Discovery_Engine SHALL store all entities with their category labels in the Discovery_Session record and proceed to hypothesis formation.
7. THE Discovery_Engine SHALL allow the operator to add entities manually up to a maximum of 30 total entities per Discovery_Session.

### Requirement 3: Hypothesis Formation

**User Story:** As an operator, I want the system to generate testable hypotheses about the client's Reddit relevance, so that research has clear objectives.

#### Acceptance Criteria

1. WHEN entities are confirmed by the operator, THE Discovery_Engine SHALL generate 3-7 hypotheses per iteration about the client's potential Reddit relevance within 30 seconds of the operator's confirmation.
2. THE Discovery_Engine SHALL formulate each Hypothesis as a testable statement that includes at least one quantifiable Reddit metric (subscriber count, post volume, engagement level, or comment frequency) that can be verified via Reddit API research.
3. THE Discovery_Engine SHALL assign each Hypothesis an initial Confidence_Score of 50 (neutral) before Reddit research.
4. THE Discovery_Engine SHALL store Hypothesis_Provenance for each hypothesis: which client entities (by ID) triggered it and a reasoning chain of no more than 500 characters explaining the logical connection.
5. THE Discovery_Engine SHALL categorize hypotheses by Visibility_Outcome type: clients, partners, feedback, recognition, hiring, or market_research.
6. IF the LLM returns fewer than 3 hypotheses, THEN THE Discovery_Engine SHALL retry the generation once with an expanded prompt; IF the retry also returns fewer than 3, THEN THE Discovery_Engine SHALL present the available hypotheses to the operator with a message indicating that fewer hypotheses than expected were generated.
7. IF hypothesis generation fails due to LLM timeout or API error, THEN THE Discovery_Engine SHALL display a generic "generation failed" error indication to the operator (regardless of whether the cause was timeout, rate limit, or API error) and allow retrying generation without losing the confirmed entities.
8. WHILE a Discovery_Session has prior iterations, THE Discovery_Engine SHALL exclude previously proposed hypothesis statements from new generation output to prevent duplicates across iterations.

### Requirement 4: Reddit Ecosystem Research

**User Story:** As an operator, I want the system to research Reddit for evidence supporting or contradicting each hypothesis, so that recommendations are data-driven.

#### Acceptance Criteria

1. WHEN hypotheses are formed, THE Discovery_Engine SHALL research Reddit for supporting or contradicting evidence using subreddit search, keyword analysis, and post/comment volume metrics.
2. THE Discovery_Engine SHALL collect Reddit_Signals for each hypothesis: up to 10 relevant subreddit names, subscriber counts, recent post volume (30-day), average engagement (upvotes/comments), and topic relevance scores on a 0-100 integer scale where 0 means no keyword overlap and 100 means exact topic match.
3. THE Discovery_Engine SHALL execute Reddit research as a background Celery task and display per-hypothesis progress to the operator showing each hypothesis status as queued, researching, or complete.
4. THE Discovery_Engine SHALL update each Hypothesis Confidence_Score based on Reddit evidence: increase by 10-30 points when a hypothesis has 20 or more relevant posts in 30 days with average engagement of 10 or more upvotes, and decrease by 10-30 points when a hypothesis has fewer than 5 relevant posts in 30 days or average engagement below 3 upvotes.
5. THE Discovery_Engine SHALL store the full Hypothesis_Provenance: which Reddit data points were used, how they affected confidence, and the reasoning.
6. THE Discovery_Engine SHALL complete Reddit research for all hypotheses in a single iteration within 120 seconds.
7. IF the Reddit API is unavailable or returns errors during research, THEN THE Discovery_Engine SHALL mark affected hypotheses with a research_failed status, display an error indication to the operator identifying which hypotheses could not be researched, and allow the operator to retry the failed hypotheses without restarting the entire iteration. This failure handling SHALL only trigger when the Reddit API is entirely unavailable or returns error responses, not for individual request-level failures within an otherwise available API.

### Requirement 5: No-Signal Handling

**User Story:** As an operator, I want the system to honestly report when Reddit has no relevant discussions for a hypothesis, so that I can set realistic expectations with the client.

#### Acceptance Criteria

1. WHEN Reddit research finds fewer than 5 posts matching the hypothesis search terms with a topic relevance score of 50 or above in the last 90 days, THE Discovery_Engine SHALL mark that hypothesis with a No_Signal_Assessment and reduce its Confidence_Score to 15 or below.
2. THE Discovery_Engine SHALL include in the No_Signal_Assessment: the search terms used, the subreddits searched, the number of posts found (including those below the relevance threshold), and a one-sentence explanation of why the results indicate low Reddit relevance for that hypothesis.
3. IF broader related search terms (parent category, synonyms, or adjacent problem keywords) return 10 or more relevant posts but the hypothesis-specific terms return fewer than 5, THEN THE Discovery_Engine SHALL classify the no-signal cause as "search_too_narrow" and suggest up to 3 adjacent Reddit topics or rephrased angles derived from the broader terms that did return results.
4. IF both the hypothesis-specific search terms and broader related terms return fewer than 5 relevant posts across all searched subreddits, THEN THE Discovery_Engine SHALL classify the no-signal cause as "topic_absent" and suggest up to 3 alternative platforms or communities outside Reddit (e.g., LinkedIn groups, Quora spaces, industry forums) where the topic may have more traction.
5. WHEN a no-signal cause is classified as "search_too_narrow", THE Discovery_Engine SHALL recommend the operator refine the hypothesis with the discovered broader terms and re-run research in the next iteration.
6. WHEN a no-signal cause is classified as "topic_absent", THE Discovery_Engine SHALL recommend the operator consider excluding this angle from the Visibility_Report or noting it as a gap in the "Risks and Limitations" section.

### Requirement 6: Discovery Iteration Loop with Operator Feedback

**User Story:** As an operator, I want to confirm or reject hypotheses after seeing research results, so that the system refines its understanding with each iteration.

#### Acceptance Criteria

1. THE Discovery_Engine SHALL present research findings grouped by hypothesis, showing: hypothesis statement, confidence score (0-100) with signed delta from previous iteration, supporting Reddit_Signals, and a Fact vs Choice classification.
2. WHEN the operator confirms a hypothesis, THE Discovery_Engine SHALL mark it as confirmed and include it in the final Visibility_Report.
3. WHEN the operator rejects a hypothesis, THE Discovery_Engine SHALL mark it as rejected, store a required rejection reason (minimum 10 characters), and exclude it from the Visibility_Report.
4. WHEN the operator has confirmed or rejected all hypotheses in the current iteration, THE Discovery_Engine SHALL generate 3-7 refined hypotheses for the next iteration based on confirmed directions and rejection reasons.
5. IF the Discovery_Session reaches the maximum of 5 iterations, THEN THE Discovery_Engine SHALL display the current iteration as "Iteration 5 of 5 (Final)", disable further iteration generation, and prompt the operator to generate the Visibility_Report or end the session.
6. THE Discovery_Engine SHALL display the current iteration count (e.g., "Iteration 2 of 5") throughout the session.
7. THE Discovery_Engine SHALL allow the operator to end the session early at any point after the first iteration is complete.
8. THE Discovery_Engine SHALL require a minimum of 1 completed iteration (all hypotheses in that iteration confirmed or rejected, including iterations where all hypotheses were rejected) before allowing Visibility_Report generation.
9. IF the operator ends the session with unresolved hypotheses in the current iteration, THEN THE Discovery_Engine SHALL exclude those unresolved hypotheses from the Visibility_Report and mark them as abandoned.

### Requirement 7: Fact vs Choice Classification

**User Story:** As an operator, I want findings clearly labeled as objective facts or subjective strategic choices, so that clients understand what is market reality versus what is a deliberate positioning decision.

#### Acceptance Criteria

1. THE Discovery_Engine SHALL classify each research finding presented in the iteration results as either a Fact (an objective observation derivable from Reddit data, e.g., "Market perceives you as X — this is observable in Reddit discussions") or a Choice (a strategic positioning option requiring operator decision, e.g., "Building presence in this direction is a strategic option").
2. THE Discovery_Engine SHALL derive Fact classifications only from Reddit data evidence (post content, comment sentiment, community descriptions, discussion patterns), and SHALL include at least one supporting Reddit_Signal reference per Fact.
3. THE Discovery_Engine SHALL derive Choice classifications from the intersection of confirmed client goals (from the Client_Brief or confirmed hypotheses) and available Reddit opportunities identified during research.
4. IF a research finding contains both an observable Reddit data point and a strategic recommendation, THEN THE Discovery_Engine SHALL split it into a separate Fact statement and a separate Choice statement.
5. THE Discovery_Engine SHALL display Facts and Choices with distinct visual labels and styling (different label text and background color per classification type) in the iteration results view, such that the classification is identifiable without relying on color alone.
6. WHEN the operator clicks on a Fact or Choice classification label, THE Discovery_Engine SHALL allow the operator to reclassify it (Fact → Choice or Choice → Fact), storing the override with a timestamp in the hypothesis provenance.

### Requirement 8: Visibility Report Generation

**User Story:** As an operator, I want to generate a structured Visibility Report from Discovery findings, so that I have a professional sales artifact for the client.

#### Acceptance Criteria

1. WHEN the operator triggers report generation after at least 1 completed iteration with at least 1 confirmed hypothesis, THE Discovery_Engine SHALL produce a Visibility_Report within 60 seconds containing: executive summary (200-500 words), demand assessment, relevant communities list (3-15 communities), discussion activity analysis, potential entry points, competitive landscape, and recommended Visibility_Outcomes.
2. IF the operator triggers report generation but the session has 0 confirmed hypotheses, THEN THE Discovery_Engine SHALL display a message indicating that at least 1 confirmed hypothesis is required and prompt the operator to return to the iteration loop.
3. THE Visibility_Report SHALL answer the question "What can Reddit potentially give this client in the next 6-12 months?" with projections that each cite at least 1 Reddit_Signal as supporting evidence.
4. THE Visibility_Report SHALL include for each recommended community: subreddit name, subscriber count, average daily posts, relevance score (0-100 scale), and suggested engagement approach.
5. THE Visibility_Report SHALL categorize potential outcomes by type (clients, partners, feedback, recognition, hiring, market_research) with estimated probability (high/medium/low) and 1-3 sentences of reasoning per outcome.
6. THE Visibility_Report SHALL include a "Risks and Limitations" section noting any No_Signal_Assessments and areas where fewer than 5 relevant posts were found in the last 90 days.
7. THE Discovery_Engine SHALL store the Visibility_Report as a structured record linked to the Discovery_Session.
8. THE Discovery_Engine SHALL generate the Visibility_Report using the Claude Sonnet model for high-quality prose.
9. IF report generation fails or exceeds 60 seconds, THEN THE Discovery_Engine SHALL display an error message indicating the failure and allow the operator to retry.

### Requirement 9: Visibility Report Export

**User Story:** As an operator, I want to export the Visibility Report in a client-presentable format, so that I can deliver it as a sales artifact.

#### Acceptance Criteria

1. THE Discovery_Engine SHALL render the Visibility_Report as a formatted HTML page with RAMP branding suitable for client presentation.
2. THE Discovery_Engine SHALL provide a print-friendly CSS layout for the Visibility_Report HTML page, suitable for PDF export via browser print.
3. THE Visibility_Report HTML page SHALL include: report date, client name (or prospect name), and a table of contents linking to each section.
4. THE Discovery_Engine SHALL allow the operator to add custom notes or edits to the Visibility_Report before export.

### Requirement 10: Discovery Session Management

**User Story:** As an operator, I want to view, resume, and manage past Discovery sessions, so that I can track client research history and update findings.

#### Acceptance Criteria

1. THE Discovery_Engine SHALL display a paginated list (25 sessions per page) of all Discovery_Sessions showing: client/prospect name, creation date, status (in_progress/completed/abandoned), iteration count, and operator name, sorted by creation date descending (newest first).
2. WHEN the operator opens a completed Discovery_Session, THE Discovery_Engine SHALL display the full session history in read-only non-resumable mode: all iterations, confirmed/rejected hypotheses, and the generated Visibility_Report.
3. WHEN the operator opens an in-progress Discovery_Session, THE Discovery_Engine SHALL allow resuming from the last completed iteration, where a completed iteration is one in which the operator has submitted confirm/reject decisions on all presented hypotheses.
4. THE Discovery_Engine SHALL allow the operator to mark an in_progress Discovery_Session as abandoned with an optional reason (maximum 500 characters), and SHALL NOT allow changing a completed or abandoned session back to in_progress.
5. IF a user without owner or partner role attempts to access the Discovery_Session list or any session detail, THEN THE Discovery_Engine SHALL deny access and display an error message indicating insufficient permissions.
6. WHEN the operator opens an abandoned Discovery_Session, THE Discovery_Engine SHALL display the session history up to the last completed iteration in read-only mode, including the abandonment reason if provided.

### Requirement 11: Hypothesis Provenance and Audit Trail

**User Story:** As an operator, I want full traceability of how each hypothesis was formed and evaluated, so that I can explain the reasoning to clients and refine the process.

#### Acceptance Criteria

1. THE Discovery_Engine SHALL store for each Hypothesis: the triggering client entity IDs and category labels, the full LLM prompt text used to generate it, the collected Reddit_Signals (subreddit names, subscriber counts, post volume, engagement metrics, and topic relevance scores), the confidence calculation reasoning text with the signal values that produced the Confidence_Score, and all operator decisions (confirm/reject with timestamp and optional rejection reason).
2. WHEN the operator clicks on a hypothesis detail view, THE Discovery_Engine SHALL display the full provenance chain from client brief → entities → hypothesis → Reddit signals → confidence score within 3 seconds, rendering each stage as a distinct section with the stored data for that stage.
3. THE Discovery_Engine SHALL log all LLM calls made during Discovery (entity extraction, hypothesis formation, research analysis, report generation) in the AIUsageLog with operation value "discovery" and triggered_by indicating the Discovery_Session ID.
4. IF provenance data for a hypothesis is partially unavailable due to a failed LLM call or timed-out Reddit research, THEN THE Discovery_Engine SHALL indicate which stages have missing data with the reason for unavailability. Display of available provenance stages is optional when data is incomplete.

### Requirement 12: Discovery-to-Strategy Handoff

**User Story:** As an operator, I want Discovery findings to flow into the Strategy phase, so that strategy recommendations are grounded in validated Reddit ecosystem data.

#### Acceptance Criteria

1. WHEN a Visibility_Report is completed and the operator initiates strategy creation, THE Discovery_Engine SHALL inject into the strategy generation prompt: all confirmed hypotheses (statement + confidence score), recommended communities (subreddit name + relevance score + suggested engagement approach), identified entry points, and competitive landscape data extracted from the Visibility_Report content JSONB.
2. WHEN the operator initiates strategy creation from a prospect-only Discovery_Session (client_id is NULL), THE Discovery_Engine SHALL create a new Client record populated with: client_name from the session's client name field, company_profile from the Client_Brief text, and competitive_landscape from the Visibility_Report's competitive landscape section, then link the Discovery_Session to the new Client record by setting its client_id foreign key.
3. WHEN the operator initiates strategy creation from a Discovery_Session already linked to an existing Client record, THE Discovery_Engine SHALL use the existing Client record without modification.
4. WHEN Discovery identifies recommended subreddits in the Visibility_Report, THE Discovery_Engine SHALL present them as pre-selected options in the client's subreddit configuration step of the onboarding wizard, excluding any subreddits already assigned to the client via ClientSubredditAssignment.
5. IF a Discovery_Session has zero confirmed hypotheses when the operator initiates strategy creation, THEN THE Discovery_Engine SHALL display a warning indicating that strategy generation will proceed without validated hypothesis data, and require operator confirmation before continuing.
6. THE Discovery_Engine SHALL store the Discovery_Session ID as a foreign key reference on each StrategyDocument generated from Discovery findings, preserving the link between Discovery research and resulting strategy decisions.
7. THE Discovery_Engine SHALL log a "discovery_handoff" activity event recording: session_id, client_id, count of confirmed hypotheses passed, count of recommended subreddits imported, and whether a new Client record was created.

### Requirement 13: Discovery Session Data Model

**User Story:** As a developer, I want a well-structured data model for Discovery, so that sessions, hypotheses, and reports are stored reliably and support future features.

#### Acceptance Criteria

1. THE Discovery_Engine SHALL store Discovery_Sessions in a dedicated PostgreSQL table with columns: id (UUID primary key), client_id (nullable FK to clients with ON DELETE SET NULL), operator_user_id (FK to users with ON DELETE RESTRICT), client_brief (text, max 5000 characters), prospect_name (text, max 200 characters, nullable), status (enum: in_progress/completed/abandoned), created_at (timestamptz), updated_at (timestamptz), completed_at (timestamptz nullable), abandon_reason (text, max 500 characters, nullable), and session_metadata (JSONB, default empty object).
2. THE Discovery_Engine SHALL store Hypotheses in a dedicated table with columns: id (UUID primary key), session_id (FK to discovery_sessions with ON DELETE CASCADE), iteration_number (integer, 1-5), statement (text, max 1000 characters), category (enum: clients/partners/feedback/recognition/hiring/market_research), confidence_score (integer 0-100, default 50), status (enum: proposed/confirmed/rejected/abandoned/research_failed), provenance (JSONB), reddit_signals (JSONB), rejection_reason (text, max 500 characters, nullable), created_at (timestamptz), and decided_at (timestamptz nullable).
3. THE Discovery_Engine SHALL store Entities in a dedicated table with columns: id (UUID primary key), session_id (FK to discovery_sessions with ON DELETE CASCADE), name (text, max 200 characters), category (enum: product/audience/problem/industry/competitor/use_case), source (enum: extracted/operator_added), and created_at (timestamptz).
4. THE Discovery_Engine SHALL store Visibility_Reports in a dedicated table with columns: id (UUID primary key), session_id (FK to discovery_sessions with ON DELETE CASCADE), content (JSONB), generated_at (timestamptz), operator_notes (text, max 5000 characters, nullable), and report_version (integer, starting at 1, incrementing on regeneration).
5. THE Discovery_Engine SHALL create Alembic migrations for all new tables with: indexes on session_id (all child tables), index on client_id (discovery_sessions), unique constraint on (session_id, iteration_number, statement) for hypotheses to prevent duplicates, and a composite index on (session_id, status) for hypotheses to support filtered queries.

### Requirement 14: Admin UI Integration

**User Story:** As an operator, I want Discovery accessible from the admin panel, so that it integrates naturally with the existing client management workflow.

#### Acceptance Criteria

1. THE Admin_Panel sidebar SHALL include a "Discovery" navigation item between "Dashboard" and "Clients".
2. WHEN the operator navigates to the Discovery section, THE Admin_Panel SHALL display the Discovery_Session list with a "New Discovery" action button. The "New Discovery" button SHALL only appear when the session list has loaded successfully.
3. THE Discovery_Engine UI SHALL follow the existing admin panel design: dark theme (admin_base.html), HTMX partials for step transitions, Tailwind CSS styling.
4. THE Discovery_Engine SHALL provide an HTMX-driven iteration flow where each step (brief input → entity review → hypothesis review → research results → report) loads as a partial without full page reload.
5. WHEN viewing a Client detail page, THE Admin_Panel SHALL display a "Discovery History" section showing linked Discovery_Sessions with links to their reports.

### Requirement 15: Economic Model Support

**User Story:** As an operator, I want Discovery AI costs tracked separately, so that I can validate the economic model of Discovery as a paid service.

#### Acceptance Criteria

1. THE Discovery_Engine SHALL log all LLM API calls with operation_type "discovery" and sub-types: "entity_extraction", "hypothesis_formation", "research_analysis", and "report_generation" in the AIUsageLog, storing the Discovery_Session ID in the triggered_by field.
2. THE Admin_Panel AI Costs page SHALL display Discovery costs as a separate line item in the breakdown by operation type, with the ability to drill down by session.
3. THE Discovery_Engine SHALL display estimated AI cost for the current session on the session page as a running total updated after each LLM call completes, formatted as "$X.XX".

### Requirement 16: Reddit Account Blind Profiling

**User Story:** As an operator, I want Discovery to analyze an unknown Reddit account and produce a comprehensive profile of interests, expertise, communities, and participation style without any prior user input, so that I can validate avatar quality or assess a prospect's Reddit presence.

#### Acceptance Criteria

1. WHEN the operator provides a Reddit username, THE Discovery_Engine SHALL retrieve the account's posting history (up to 1000 most recent posts and comments) via Reddit API and produce a structured profile within 60 seconds.
2. THE Discovery_Engine SHALL extract and categorize the account's interests into a ranked list (maximum 20 interests), where each interest includes a confidence weight (0.0-1.0) derived from post frequency, comment depth, and recency.
3. THE Discovery_Engine SHALL identify the account's active communities (subreddits) with per-community metrics: post count, comment count, average karma per contribution, and estimated activity period (first seen to last seen).
4. THE Discovery_Engine SHALL assess the account's expertise areas by analyzing technical depth, vocabulary complexity, and community recognition (karma concentration in specific topics), producing up to 10 expertise labels each with a proficiency level (novice/intermediate/advanced/expert).
5. THE Discovery_Engine SHALL characterize the account's participation style by classifying posting behavior along dimensions: frequency (daily/weekly/sporadic), tone (helpful/combative/neutral/humorous), contribution type (original_content/replies/questions/link_sharing), and engagement depth (surface/moderate/deep).
6. THE Discovery_Engine SHALL produce the blind profile with a minimum accuracy of 70% on interests, communities, expertise, and participation style when validated against known ground truth for test accounts.
7. IF the Reddit account has fewer than 10 posts and comments combined, THEN THE Discovery_Engine SHALL mark the profile as "insufficient_data" and report only the available metrics without extrapolation, regardless of account suspension status.
8. IF the Reddit API returns a 404 or suspended status for the username, THEN THE Discovery_Engine SHALL display an error indicating the account does not exist or is suspended.

### Requirement 17: Known Avatar Validation Scoring

**User Story:** As an operator, I want to validate Discovery's profiling accuracy against known avatar ground truth, so that I can measure and improve the system's understanding of Reddit accounts over time.

#### Acceptance Criteria

1. WHEN a blind profile is generated for an account that has a linked ground truth document (stored as avatar metadata or operator-provided reference), THE Discovery_Engine SHALL produce a scored accuracy assessment comparing the generated profile against ground truth.
2. THE Discovery_Engine SHALL score accuracy per profile section (interests, communities, expertise, participation_style) on a 0-2 scale: 0 (incorrect or missing), 1 (partially correct), 2 (accurate and complete).
3. THE Discovery_Engine SHALL compute an overall accuracy average across all scored sections and flag profiles with an average score below 1.5 for operator review.
4. THE Discovery_Engine SHALL store each validation result with: profile_id, ground_truth_reference, per-section scores, overall average, validation_timestamp, and the specific mismatches identified. IF storage fails due to database errors, the validation process SHALL continue and display results to the operator immediately.
5. WHEN the overall accuracy average is below 1.5 (exclusive), THE Discovery_Engine SHALL generate a list of specific discrepancies between the generated profile and ground truth, identifying which profile claims were wrong and what the ground truth states. Profiles scoring exactly 1.5 SHALL NOT trigger discrepancy generation.
6. THE Discovery_Engine SHALL allow the operator to upload or link ground truth documents (structured JSON or free-text) for any profiled Reddit account.

### Requirement 18: Deception Detection and Mismatch Reporting

**User Story:** As an operator, I want Discovery to detect mismatches between what a user claims about themselves and what their Reddit behavior actually shows, so that I can identify unreliable self-reports and build an accurate model.

#### Acceptance Criteria

1. WHEN the operator provides user-claimed attributes (expertise areas, community involvement, posting frequency, or account age) alongside a Reddit username, THE Discovery_Engine SHALL compare each claimed attribute against observed Reddit behavior and produce a mismatch report.
2. THE Discovery_Engine SHALL classify each claimed attribute as: confirmed (observed behavior matches claim), partial_match (some evidence supports claim but with gaps), contradicted (observed behavior directly contradicts claim), or unverifiable (insufficient data to confirm or deny).
3. WHEN a claimed attribute is classified as contradicted, THE Discovery_Engine SHALL provide the specific observed evidence that contradicts the claim, including: the relevant Reddit data points (posts, comments, karma), the date range of observations, and a one-sentence explanation of the contradiction. Classification as contradicted is permitted even when complete evidence details are unavailable.
4. THE Discovery_Engine SHALL assign a deception_risk_score (0-100) to the overall set of claims, where 0 means all claims confirmed and 100 means all claims contradicted, weighted by the significance of each mismatch.
5. IF the deception_risk_score exceeds 50, THEN THE Discovery_Engine SHALL flag the account for operator review and display a prominent warning in the profile view indicating "Significant mismatch between claimed and observed attributes."
6. THE Discovery_Engine SHALL store all mismatch assessments as part of the account's Discovery record, preserving: claimed_attributes (input), observed_attributes (from Reddit), classification per attribute, evidence references, and the computed deception_risk_score.
7. THE Discovery_Engine SHALL detect attribution mismatches between recommended actions, reported actions, and observed actions, classifying each as: followed (recommended action was observed), claimed_not_observed (user reported completion but no Reddit evidence found), or unclaimed_observed (Reddit activity exists that was never recommended or reported).

### Requirement 19: Continuous Discovery Model Updates

**User Story:** As an operator, I want Discovery to continuously update its model of a Reddit account as new activity appears, so that the system maintains an accurate, evolving understanding rather than relying on a single-point-in-time snapshot.

#### Acceptance Criteria

1. WHILE a Reddit account is linked to an active client or avatar, THE Discovery_Engine SHALL re-scan the account's Reddit activity at a configurable interval (default: every 72 hours, minimum: 24 hours, maximum: 168 hours) and update the stored profile with new observations.
2. WHEN new Reddit activity is detected during a re-scan, THE Discovery_Engine SHALL compute deltas against the previous profile version: new interests detected, interest weights changed, new communities joined, communities abandoned (no activity in 30+ days), and expertise level changes.
3. THE Discovery_Engine SHALL store each profile update as a versioned snapshot with: version_number, scan_timestamp, delta_summary (structured JSON listing all changes), and the full updated profile. Snapshots SHALL be created for all scan attempts including failed scans, to maintain a complete audit trail.
4. WHEN a profile has accumulated 30 or more days of continuous observation, THE Discovery_Engine SHALL produce a trend analysis showing: interest trajectory (growing/stable/declining per interest), community migration patterns, and participation style shifts.
5. IF a re-scan detects a significant model change (3 or more interest weight shifts exceeding 0.2, or a new expertise area detected, or a community abandoned), THEN THE Discovery_Engine SHALL generate a notification for the operator describing the change and its potential impact on strategy.
6. THE Discovery_Engine SHALL retain at least 90 days of profile version history per account, enabling the operator to view the model at any historical point.
7. IF the Reddit API is unavailable during a scheduled re-scan, THEN THE Discovery_Engine SHALL retry after 4 hours and log the failed attempt without updating the profile.

### Requirement 20: Attribution Tracking Across Action Layers

**User Story:** As an operator, I want the system to track the full lifecycle of actions from recommendation through execution to outcome, so that I can determine whether strategy recommendations are being followed and whether they produce results.

#### Acceptance Criteria

1. THE Discovery_Engine SHALL maintain a four-layer attribution record for each trackable action: recommended_action (what RAMP suggested via EPG or strategy), reported_action (what the user claimed was done), observed_action (what actually appeared on Reddit), and observed_outcome (karma delta, replies, removals, community reaction).
2. WHEN a recommended action is created (EPG slot or strategy directive), THE Discovery_Engine SHALL store it with: action_id, action_type (comment/post/engagement), target_subreddit, target_thread (if applicable), recommended_at timestamp, and the generating strategy_document_id.
3. WHEN a user reports an action as completed (draft status changed to "posted", or manual confirmation), THE Discovery_Engine SHALL record: reported_at timestamp, reported_by user_id, and reported_reddit_entity_id (if provided).
4. WHEN the Discovery observation layer detects a matching Reddit entity (comment or post by the avatar in the target context), THE Discovery_Engine SHALL link the observed_action to the recommendation with: observed_at timestamp, observed_reddit_entity_id, attribution_confidence (0.0-1.0 based on timing proximity, content similarity, and target match).
5. THE Discovery_Engine SHALL track observed_outcomes for each linked observed_action: karma_snapshot_4h, karma_snapshot_24h, karma_snapshot_48h, reply_count, is_removed (boolean), removal_detected_at, and thread_state (active/locked/removed).
6. THE Discovery_Engine SHALL classify each attribution record into one of: executed_as_recommended (observed matches recommendation), partially_executed (observed action in same context but different content or timing), not_executed (no observed action matching recommendation within 48 hours), and externally_initiated (observed action exists with no matching recommendation).
7. IF a reported_action has no matching observed_action within 48 hours of the reported timestamp, THEN THE Discovery_Engine SHALL flag it as "reported_not_observed" and notify the operator. This flagging SHALL only occur when users explicitly report actions as completed, not when the observation layer fails to detect expected entities for other reasons.
8. THE Discovery_Engine SHALL prioritize observed actions and observed outcomes over reported actions when updating the account model, following the source-of-truth hierarchy: Observed Actions > Reported Actions > Recommended Actions.

### Requirement 21: Strategy Explainability

**User Story:** As an operator, I want each generated strategy recommendation to be traceable to specific observed data and community reality, so that I can verify the reasoning and explain it to clients.

#### Acceptance Criteria

1. THE Discovery_Engine SHALL store for each strategy recommendation: the observed data points that triggered it (Reddit_Signals with subreddit, metric type, metric value, and observation date), the community context (subreddit rules, activity level, competitive presence), and the logical reasoning chain connecting observations to the recommendation.
2. WHEN the operator requests an explanation for a strategy recommendation, THE Discovery_Engine SHALL present: the triggering observations (with links to specific Reddit data), the inference steps (structured as premise → conclusion chains, maximum 5 steps), and any assumptions made where data was incomplete.
3. THE Discovery_Engine SHALL classify each strategy recommendation's evidence basis as: data_driven (supported by 3 or more independent Reddit observations), partially_supported (supported by 1-2 observations with inference), or extrapolated (based on pattern matching from similar communities without direct evidence from the target community).
4. IF a strategy recommendation is classified as extrapolated, THEN THE Discovery_Engine SHALL explicitly label it as "based on pattern inference" in the strategy document and include the analogous communities and signals that informed the extrapolation.
5. THE Discovery_Engine SHALL validate that each strategy recommendation logically follows from its cited observations — a recommendation to engage in a community must cite evidence of relevant discussion activity in that community, and a recommendation to avoid a community must cite evidence of hostile reception or rule violations.

### Requirement 22: EPG Recommendation Explainability

**User Story:** As an operator, I want each EPG slot (daily publishing recommendation) to be explainable by the strategy it implements, the observed data that supports it, or both, so that I can audit the publishing program's reasoning.

#### Acceptance Criteria

1. THE Discovery_Engine SHALL store for each EPG slot: the strategy_directive_id that generated it (FK to the strategy recommendation being implemented), the supporting_observations (list of Reddit_Signal IDs or observation records that justify this specific slot), and an explanation_text (maximum 500 characters) summarizing why this action was recommended at this time.
2. WHEN the operator views an EPG slot detail, THE Discovery_Engine SHALL display: the parent strategy recommendation (with link), the specific thread or community data that made this slot relevant now (freshness, engagement opportunity, topic alignment), and the timing rationale (why this time slot was chosen).
3. THE Discovery_Engine SHALL classify each EPG slot's justification as: strategy_driven (directly implements a strategy directive), opportunity_driven (responds to a detected engagement opportunity in real-time data), or maintenance_driven (sustains presence frequency requirements).
4. IF an EPG slot cannot be traced to either a strategy directive or a specific observation, THEN THE Discovery_Engine SHALL flag it as "unjustified" and require operator approval before the slot can proceed to posting.
5. THE Discovery_Engine SHALL compute an explainability_coverage metric per avatar per day: the percentage of EPG slots that have complete justification chains (strategy + observation). The target is 90% or above coverage.
6. WHEN explainability_coverage drops below 80% for an avatar over a 7-day rolling window, THE Discovery_Engine SHALL generate a notification to the operator indicating that the publishing program is operating without sufficient evidence basis and recommending a strategy review.
