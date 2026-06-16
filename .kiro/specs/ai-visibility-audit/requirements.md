# Requirements Document

## Introduction

The AI Visibility Audit is a standalone, one-time paid product ($750-$1,500) that packages existing RAMP capabilities (Discovery Engine + GEO/AEO Monitoring) into a sellable deliverable for prospects. The audit measures a client's current brand visibility across Reddit communities and AI search engines (ChatGPT, Gemini, Perplexity), provides competitive positioning analysis, and delivers a professional report with actionable recommendations. It serves as a sales funnel entry point — clients buy the audit, see results, and convert into the managed service subscription.

The Audit does NOT duplicate Discovery or GEO logic. It wraps existing services (`SessionManager`, `extract_entities`, `form_hypotheses`, `research_hypotheses_task`, `generate_visibility_report`, `run_geo_batch_for_client`) in an orchestration layer that replaces manual operator steps with automated sequencing. All data is stored in existing tables (`discovery_sessions`, `discovery_entities`, `discovery_hypotheses`, `geo_prompts`, `geo_query_results`, `geo_execution_batches`).

## Glossary

- **Audit_Session**: A self-contained workflow instance that orchestrates the full AI Visibility Audit for a single client/prospect, tracking progress through defined phases from creation to report delivery. Links to a DiscoverySession and GeoExecutionBatch via foreign keys.
- **Operator**: A platform admin (owner or partner role) who initiates and manages audit sessions on behalf of clients/prospects.
- **Prospect**: A potential client who purchases the audit before committing to a managed service subscription. May or may not have an existing Client record in the system.
- **Client_Portal**: The client-facing UI where prospects/clients can view audit progress and results.
- **Discovery_Phase**: The phase of the audit that calls existing Discovery Engine services (SessionManager, entity_extractor, hypothesis_engine, reddit_researcher, confidence_scorer) in automated sequence, creating a standard DiscoverySession with all its data artifacts.
- **GEO_Baseline_Phase**: The phase of the audit that generates GeoPrompt records and calls run_geo_batch_for_client() to measure brand/competitor visibility in AI search engine responses. Stores results in existing geo_query_results and geo_frequency_metrics tables.
- **Audit_Report**: The final deliverable combining Discovery findings and GEO baseline data into a professional, exportable document with recommendations. Extends the existing Visibility Report format with GEO data sections.
- **Visibility_Score**: A composite metric (0-100) representing how often a brand appears in AI engine responses relative to competitors for relevant industry queries. Computed from geo_frequency_metrics.brand_appearance_rate.
- **Competitive_Matrix**: A comparison table showing brand vs. competitor visibility across monitored prompts and AI platforms. Built from geo_frequency_metrics and geo_query_results.competitors_mentioned data.
- **Upsell_Path**: The conversion flow from completed audit to managed service subscription, including clear calls-to-action in the report and portal.
- **Audit_Orchestrator**: The service that coordinates the sequential execution of Discovery and GEO baseline phases, managing state transitions and error recovery. Implemented as a Celery task chain calling existing service functions.

## Requirements

### Requirement 1: Audit Session Lifecycle Management

**User Story:** As an Operator, I want to create and manage audit sessions for prospects, so that I can deliver the AI Visibility Audit product as a packaged service.

#### Acceptance Criteria

1. WHEN an Operator submits a new audit request with a prospect name, company brief (minimum 50 characters), brand name, brand domain, and competitor list (1-10 competitor names), THE Audit_Orchestrator SHALL create an Audit_Session with status "created" and persist all input data.
2. WHEN an Audit_Session is created, THE Audit_Orchestrator SHALL generate a unique token-based access URL for the prospect to view progress and results in the Client_Portal.
3. THE Audit_Session SHALL track the following statuses in order: "created", "discovery_running", "discovery_complete", "geo_running", "geo_complete", "report_generating", "completed", "delivered".
4. IF an Audit_Session encounters an unrecoverable error during any phase, THEN THE Audit_Orchestrator SHALL transition the session to status "failed" with an error description and notify the Operator via an ActivityEvent.
5. WHEN an Operator requests to abandon an Audit_Session, THE Audit_Orchestrator SHALL transition the session to status "abandoned" with an optional reason.
6. THE Audit_Session SHALL store a pricing tier ("standard" at $750 or "premium" at $1,500) selected by the Operator at creation time.
7. THE Audit_Session SHALL store foreign key references to the linked DiscoverySession and GeoExecutionBatch created during execution.

### Requirement 2: Automated Discovery Phase Execution

**User Story:** As an Operator, I want the audit to automatically run market/niche discovery for the prospect's brand, so that I do not need to manually drive each step of the Discovery Engine.

#### Acceptance Criteria

1. WHEN an Operator triggers the audit execution, THE Audit_Orchestrator SHALL call SessionManager.create_session() to create a DiscoverySession linked to the Audit_Session, then call extract_entities() with the company brief.
2. WHEN entity extraction completes, THE Audit_Orchestrator SHALL mark all extracted entities as confirmed and call form_hypotheses() to trigger hypothesis formation without Operator intervention.
3. WHEN hypotheses are formed, THE Audit_Orchestrator SHALL dispatch research_hypotheses_task for all proposed hypotheses and poll for completion.
4. WHEN Reddit research completes for all hypotheses, THE Audit_Orchestrator SHALL confirm all hypotheses with confidence_score above 0.5, reject those at or below 0.5, and set decided_at timestamps.
5. WHEN hypothesis decisions are complete, THE Audit_Orchestrator SHALL transition the Audit_Session status to "discovery_complete" and proceed to the GEO baseline phase.
6. IF the Discovery phase fails after 3 retry attempts on any step, THEN THE Audit_Orchestrator SHALL mark the Audit_Session as "failed" with the error context and emit an ActivityEvent alert.

### Requirement 3: Automated GEO Baseline Measurement

**User Story:** As an Operator, I want the audit to automatically measure brand visibility across AI search engines, so that the prospect receives a quantified baseline of their current AI presence.

#### Acceptance Criteria

1. WHEN the Audit_Session transitions to "discovery_complete", THE Audit_Orchestrator SHALL call an LLM (Gemini Flash) to generate GEO prompt texts from the Discovery session's confirmed entities and hypotheses, scoped to the prospect's industry.
2. THE Audit_Orchestrator SHALL generate a minimum of 10 and maximum of 30 GeoPrompt records stored in the geo_prompts table, linked to a temporary Client record or the Audit_Session directly.
3. WHEN GEO prompts are created, THE Audit_Orchestrator SHALL call run_geo_batch_for_client() to execute a batch against Perplexity Sonar with 3 runs per prompt for statistical reliability.
4. WHEN the GEO batch completes, THE Audit_Orchestrator SHALL compute a Visibility_Score (0-100) for the prospect's brand based on the average brand_appearance_rate across all geo_frequency_metrics for the batch.
5. THE Audit_Orchestrator SHALL compute a Visibility_Score for each competitor and build a Competitive_Matrix comparing all brands as a sorted list by score.
6. WHEN GEO baseline measurement completes, THE Audit_Orchestrator SHALL transition the Audit_Session status to "geo_complete" and store the Visibility_Score and Competitive_Matrix in the Audit_Session metadata.
7. IF the GEO phase fails due to API rate limits or provider errors, THEN THE Audit_Orchestrator SHALL retry with exponential backoff (60s, 120s, 240s) before marking the phase as failed.

### Requirement 4: Audit Report Generation

**User Story:** As an Operator, I want the audit to produce a professional report combining all findings, so that the prospect receives a high-value deliverable they can share internally.

#### Acceptance Criteria

1. WHEN the Audit_Session transitions to "geo_complete", THE Audit_Orchestrator SHALL call an LLM (Claude Sonnet) with structured data from both Discovery and GEO phases to generate the Audit_Report narrative content.
2. THE Audit_Report SHALL contain the following sections: Executive Summary, Market/Niche Discovery (subreddits found, entities, community engagement volumes), AI Visibility Baseline (Visibility_Score, Competitive_Matrix, per-prompt brand appearance breakdown), Subreddit Strategy Recommendations (which communities to target and why), Competitive Positioning Analysis (who dominates and where), and Recommended Next Steps (upsell to managed service).
3. THE Audit_Report SHALL be renderable as a standalone branded HTML page with print-friendly CSS for browser-native PDF export (Ctrl+P).
4. WHEN report generation completes, THE Audit_Orchestrator SHALL transition the Audit_Session status to "completed".
5. THE Audit_Report SHALL include data visualizations for the Visibility_Score (gauge/donut chart) and Competitive_Matrix (horizontal bar chart) rendered as inline HTML/CSS without external JavaScript dependencies.
6. THE Audit_Report SHALL display RAMP brand identity (configurable logo, brand colors #1a1a2e primary, #16213e secondary, #0f3460 accent) and include a footer with audit date, session reference ID, and "Powered by RAMP" attribution.

### Requirement 5: Client Portal Audit View

**User Story:** As a Prospect, I want to view my audit progress and results in a portal, so that I can track delivery and access findings without waiting for email attachments.

#### Acceptance Criteria

1. WHEN a Prospect accesses the audit portal URL with a valid token, THE Client_Portal SHALL display the current Audit_Session status with a visual step-by-step progress indicator showing completed, active, and pending phases.
2. WHILE the Audit_Session status is "discovery_running" or "geo_running", THE Client_Portal SHALL auto-refresh every 30 seconds via HTMX polling and display the current phase name with a brief explanation of what the system is doing.
3. WHEN the Audit_Session status is "completed" or "delivered", THE Client_Portal SHALL display the full Audit_Report inline with all sections, visualizations, and a "Download Report" button that opens the export view.
4. THE Client_Portal audit view SHALL be accessible via a URL containing a cryptographically secure token (UUID v4 + HMAC signature), valid for 90 days after audit completion, without requiring login or account creation.
5. THE Client_Portal audit view SHALL display a prominent call-to-action card for the managed service on the results page with text "Ready to improve these numbers?" and a "Schedule a Strategy Call" button linking to the Operator's configurable calendar URL.
6. IF a Prospect accesses an expired or invalid token URL, THEN THE Client_Portal SHALL display a branded error page with contact information for the Operator.

### Requirement 6: Operator Audit Management Dashboard

**User Story:** As an Operator, I want a dashboard to manage all audit sessions across prospects, so that I can track delivery status and intervene when needed.

#### Acceptance Criteria

1. THE Operator dashboard (at /admin/audits) SHALL display all Audit_Sessions in a table with columns: prospect name, brand name, status badge, pricing tier, created date, and completion date.
2. WHEN an Operator clicks an Audit_Session row, THE dashboard SHALL navigate to a detail page showing: Discovery findings summary, GEO results with Visibility_Score and Competitive_Matrix, report preview, total AI cost, and the Prospect's portal access link (copyable).
3. THE Operator dashboard SHALL allow filtering Audit_Sessions by status using tab-style filters: "All", "Running", "Completed", "Failed", "Abandoned".
4. WHEN an Operator views a completed Audit_Session detail, THE dashboard SHALL display the total AI cost as a formatted USD amount and the computed gross margin percentage.
5. THE Operator dashboard SHALL provide a "Re-run GEO" button on completed audit detail pages that triggers a new GEO batch execution without re-running Discovery, updating the Visibility_Score and Competitive_Matrix.

### Requirement 7: Audit Pricing and Cost Tracking

**User Story:** As an Operator, I want to track the cost and margin of each audit, so that I can ensure the product is profitable at scale.

#### Acceptance Criteria

1. THE Audit_Session SHALL accumulate total_ai_cost_usd (Decimal) by summing all ai_usage_log entries where triggered_by contains the Audit_Session ID.
2. WHEN an Audit_Session transitions to "completed", THE Audit_Orchestrator SHALL compute and store gross_margin_pct as: ((pricing_tier_amount - total_ai_cost_usd) / pricing_tier_amount) * 100.
3. THE Operator dashboard list view SHALL display summary metrics at the top: total audits completed, average AI cost per audit, average gross margin, and total revenue (sum of pricing_tier_amount for completed audits).
4. IF the cumulative AI cost of a running Audit_Session exceeds $15, THEN THE Audit_Orchestrator SHALL emit an ActivityEvent with event_type "audit_cost_warning" but continue execution without interruption.

### Requirement 8: Upsell Path Integration

**User Story:** As an Operator, I want completed audits to clearly present the path to managed service, so that prospects naturally convert after seeing their audit results.

#### Acceptance Criteria

1. THE Audit_Report "Recommended Next Steps" section SHALL include 3-5 specific, data-backed action items that reference actual findings from the audit (naming specific subreddits discovered, visibility gaps with percentages, competitor brand names and their scores).
2. WHEN the Audit_Session status transitions to "completed", THE Audit_Orchestrator SHALL set a flag "is_warm_lead" on the Audit_Session and preserve all structured data (entities, hypotheses, subreddits, competitors, GEO prompts) for potential future client onboarding.
3. WHEN an Operator triggers "Convert to Client" on a completed Audit_Session, THE system SHALL create a new Client record pre-populated with: brand_name, brand_domain, company_profile (from brief), competitive_landscape (from competitors), and create ClientSubredditAssignment records from discovered subreddits and GeoPrompt records from the audit batch.
4. THE Client_Portal audit results page SHALL include a "What Managed Service Delivers" section with 3 comparison rows: "Current AI Visibility" vs. "Projected with Active Management", showing the prospect's Visibility_Score alongside a target improvement range based on the standard uplift (20-40% increase).
