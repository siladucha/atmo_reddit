# Implementation Plan: PRD Expansion — Tzvi Questions

## Overview

This implementation plan covers the formalization of 12 requirements spanning avatar lifecycle management, client compliance, client portal, content intelligence, Phase 2 modules, and budget/billing enforcement. Tasks are grouped by domain, with migrations first within each domain, following the existing project patterns (thin routes, services layer, HTMX partials).

## Tasks

- [ ] 1. Database migrations and core configuration
  - [ ] 1.1 Create Alembic migration for Client model new fields
    - Add `plan_tier`, `monthly_fee`, `compliance_accepted`, `compliance_version`, `compliance_accepted_at`, `pipeline_suspended`, `pipeline_suspended_reason` to `clients` table
    - Update `app/models/client.py` with new mapped_column fields
    - _Requirements: 3.1, 3.4, 11.2, 12.1_

  - [ ] 1.2 Create Alembic migration for Avatar model new fields
    - Add `inventory_tier`, `tier_evaluated_at`, `avatar_type`, `brand_mention_ratio_7d`, `ratio_updated_at` to `avatars` table
    - Update `app/models/avatar.py` with new mapped_column fields and `InventoryTierEnum`
    - _Requirements: 1.5, 2.1, 2.6, 10.5_

  - [ ] 1.3 Create Alembic migration for ComplianceAcceptance model
    - Create `compliance_acceptances` table (append-only, no updated_at)
    - Create `app/models/compliance_acceptance.py`
    - _Requirements: 3.2, 3.3_

  - [ ] 1.4 Create Alembic migration for GuardrailOverride model
    - Create `guardrail_overrides` table with all status lifecycle fields
    - Create `app/models/guardrail_override.py`
    - _Requirements: 4.1, 4.3_

  - [ ] 1.5 Create Alembic migration for SubredditIntelligence model
    - Create `subreddit_intelligence` table with tone fingerprint and historical intelligence fields
    - Create `app/models/subreddit_intelligence.py`
    - _Requirements: 7.2, 7.3_

  - [ ] 1.6 Create Alembic migration for ClientUsage model
    - Create `client_usage` table with unique constraint on (client_id, period_start)
    - Create `app/models/client_usage.py`
    - _Requirements: 11.1, 11.4_

  - [ ] 1.7 Create Alembic migration for ExternalIntelligence model
    - Create `external_intelligence` table
    - Create `app/models/external_intelligence.py`
    - _Requirements: 7.1, 7.4_

  - [ ] 1.8 Create Alembic migration for TrackedAvatar and TrackedActivity models
    - Create `tracked_avatars` table with unique constraint on (client_id, reddit_username)
    - Create `tracked_activities` table
    - Create `app/models/tracked_avatar.py` and `app/models/tracked_activity.py`
    - _Requirements: 10.1, 10.2_

  - [ ] 1.9 Create Alembic migration for PersonalBrandAccount model
    - Create `personal_brand_accounts` table
    - Create `app/models/personal_brand_account.py`
    - _Requirements: 9.1, 9.3_

  - [ ] 1.10 Create plan tier limits configuration module
    - Create `app/config/plan_limits.py` with `PLAN_LIMITS` dictionary
    - Include avatar, subreddit, comment, post, and tracked_avatar limits per tier
    - _Requirements: 11.2, 12.1, 12.2_

- [ ] 2. Checkpoint — Run migrations and verify models
  - Ensure all migrations apply cleanly, all models import without errors, and existing 187 tests still pass.

- [ ] 3. Avatar Lifecycle Engine
  - [ ] 3.1 Implement phase gate service enhancements
    - Enhance `app/services/phase.py` (or create if not exists) with `evaluate_phase_transition()` function
    - Implement Phase 1→2 gate: karma >= 500 AND age >= 3 months
    - Implement Phase 2→3 gate: karma >= 2000 AND age >= 6 months AND removal_rate < 5%
    - Log transition events to activity feed on success
    - Log failed evaluation attempts with unmet criteria on failure
    - Implement karma drop detection (100+ in 24h → flag + pause)
    - _Requirements: 1.2, 1.3, 1.6, 1.7, 1.8_

  - [ ]* 3.2 Write property test for phase gate eligibility (Property 2)
    - **Property 2: Phase Gate Eligibility**
    - Test that for any (karma, account_age, removal_rate), eligibility returns True iff all thresholds met
    - File: `tests/properties/test_phase_gate_props.py`
    - **Validates: Requirements 1.2, 1.3**

  - [ ] 3.3 Implement phase policy content restriction service
    - Create content restriction checker in `app/services/phase.py` or `app/services/phase_policy.py`
    - Phase 1: block all brand mentions, restrict to hobby/general_professional subreddits
    - Phase 2: block explicit brand names and brand links, allow external citations
    - Phase 3: block brand mentions when Brand_Mention_Ratio >= 15% (trailing 7-day)
    - _Requirements: 1.1, 1.4, 1.5, 1.9_

  - [ ]* 3.4 Write property test for phase policy content restrictions (Property 1)
    - **Property 1: Phase Policy Content Restrictions**
    - Test that for any avatar phase and comment text, restrictions are correctly enforced
    - File: `tests/properties/test_phase_policy_props.py`
    - **Validates: Requirements 1.1, 1.4, 1.5, 1.9**

  - [ ]* 3.5 Write property test for brand ratio calculation (Property 14)
    - **Property 14: Brand Ratio Calculation**
    - Test that ratio = brand_comments / total_comments (0.0 when total is 0)
    - File: `tests/properties/test_brand_ratio_props.py`
    - **Validates: Requirements 1.5, 1.9**

  - [ ] 3.6 Implement inventory tier classification service
    - Create `app/services/inventory.py`
    - Implement `classify_tier(combined_karma, account_age_months)` → Gold/Silver/Unclassified
    - Implement `re_evaluate_tier(avatar)` for periodic re-classification
    - Implement tier downgrade logic with activity event logging
    - Implement assignment eligibility check (tier vs. client plan)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.7, 2.8_

  - [ ]* 3.7 Write property test for inventory tier classification (Property 3)
    - **Property 3: Inventory Tier Classification**
    - Test deterministic assignment: Gold (karma>=2000, age>=6), Silver (500-1999, 3-5), else Unclassified
    - File: `tests/properties/test_inventory_tier_props.py`
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.5**

  - [ ] 3.8 Add inventory tier display to admin avatar detail page
    - Update avatar detail template to show tier label, qualifying karma, and account age
    - _Requirements: 2.6_

- [ ] 4. Checkpoint — Avatar lifecycle tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Client Compliance Framework
  - [ ] 5.1 Implement compliance acceptance service
    - Create `app/services/compliance.py`
    - Implement `create_acceptance(client_id, user_id, ip_address, acknowledgment_items, document_version)` — append-only insert
    - Implement `check_compliance_status(client_id)` — returns whether client has accepted current version
    - Implement `mark_clients_for_reacceptance(new_version)` — bulk update on version change
    - Implement pipeline gate check: block pipeline if compliance not accepted
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [ ]* 5.2 Write property test for compliance gates pipeline (Property 4)
    - **Property 4: Compliance Gates Pipeline Activation**
    - Test that pipeline is blocked iff compliance_accepted=False or version mismatch
    - File: `tests/properties/test_compliance_gate_props.py` (or inline in `tests/properties/test_plan_limits_props.py`)
    - **Validates: Requirements 3.3, 3.4**

  - [ ] 5.3 Implement guardrail override service
    - Create `app/services/guardrail_override.py`
    - Implement override request creation with risk description
    - Implement acknowledgment flow (typed name confirmation)
    - Implement 30-minute expiry for unacknowledged requests
    - Implement 90-day max duration validation
    - Implement automatic revert on expiration
    - Implement early revocation with logging
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [ ]* 5.4 Write property test for override time validation (Property 12)
    - **Property 12: Override Time Validation**
    - Test that expiration > 90 days is rejected, and pending requests expire after 30 minutes
    - File: `tests/properties/test_override_time_props.py`
    - **Validates: Requirements 4.2, 4.4**

  - [ ] 5.5 Create compliance acceptance routes and templates
    - Create `app/routes/compliance.py` with `/portal/compliance` routes
    - Create compliance acceptance template with individual acknowledgment items
    - Create admin compliance status view template
    - Wire compliance gate into pipeline trigger (block if not accepted)
    - _Requirements: 3.1, 3.2, 3.4, 3.6_

  - [ ] 5.6 Create override expiry background task
    - Create `app/tasks/override_expiry.py`
    - Poll for expired overrides every 60 seconds, revert to defaults
    - Poll for unacknowledged requests older than 30 minutes, expire them
    - Register task in SQS consumer/scheduler
    - _Requirements: 4.2, 4.6_

- [ ] 6. Checkpoint — Compliance framework tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Client Portal — Performance Dashboard & ROI
  - [ ] 7.1 Create portal authentication dependency
    - Create `app/dependencies/portal.py` with `require_client_user` dependency
    - Validate JWT + `client_id IS NOT NULL` + `is_superuser=False`
    - Enforce client data isolation at dependency level
    - _Requirements: 5.7_

  - [ ]* 7.2 Write property test for client data isolation (Property 5)
    - **Property 5: Client Data Isolation**
    - Test that portal queries never return data from a different client_id
    - File: `tests/properties/test_data_isolation_props.py`
    - **Validates: Requirements 5.7**

  - [ ] 7.3 Implement portal metrics service
    - Create `app/services/portal_metrics.py`
    - Implement per-avatar metrics: total karma, comments posted, avg karma/comment, survival rate
    - Implement per-subreddit metrics: threads engaged, avg comment score, top 5 comments
    - Implement campaign-level metrics: total engagements, brand mention count, estimated reach
    - Implement weekly summary with week-over-week trend indicators
    - Implement avatar health indicators: phase, tier, days until next phase, flags
    - Handle empty state (no data for current period)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.8_

  - [ ] 7.4 Implement ROI metrics service
    - Create `app/services/roi_metrics.py`
    - Implement cost-per-engagement: monthly_fee / successful_engagements (30-day rolling)
    - Handle zero engagements edge case (display full fee)
    - Implement engagement quality score: avg_karma / subreddit_median_karma
    - Implement brand visibility metrics (Phase 3 only): impressions + sentiment
    - Implement 6-month growth chart data: cumulative karma, engagement count, avatar maturity
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ] 7.5 Create portal routes and base template
    - Create `app/routes/portal.py` with `/portal` routes (dashboard, avatars, performance)
    - Create `app/routes/portal_api.py` with `/api/portal` HTMX endpoints
    - Create `app/templates/portal_base.html` (light theme, client-branded)
    - Create portal dashboard template with metrics cards
    - Create portal performance detail templates
    - _Requirements: 5.1, 5.2, 5.3, 6.1, 6.5_

  - [ ] 7.6 Register portal routes in FastAPI app
    - Add portal router and portal_api router to `app/main.py`
    - Add compliance router to `app/main.py`
    - _Requirements: 5.1_

- [ ] 8. Checkpoint — Portal metrics and ROI tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Content Intelligence System
  - [ ] 9.1 Implement content intelligence service
    - Create `app/services/content_intelligence.py`
    - Implement `assemble_context(avatar, subreddit, thread, client)` — combines 4 input layers
    - Implement Historical Intelligence assembly (top 50 comments, topic clusters, argument patterns)
    - Implement Tone Fingerprint assembly (median length, formality, humor, jargon, citations)
    - Implement External Intelligence Layer integration (keyword matching for Phase 2+ only)
    - Handle incomplete layers (< 10 comments → proceed with warning log)
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ] 9.2 Implement GCM scoring service
    - Create `app/services/gcm_scoring.py`
    - Implement 5-dimension scoring via Gemini Flash: natural language flow, topic relevance, length appropriateness, absence of promotional framing, factual accuracy
    - Implement overall score as unweighted mean of 5 dimensions
    - Implement rejection logic: score < 7.0 → regenerate (temperature +0.1 per attempt, max 3)
    - Implement failure handling: 3 failed attempts → discard + log
    - _Requirements: 7.5, 7.6_

  - [ ]* 9.3 Write property test for GCM score calculation (Property 7)
    - **Property 7: Genuine Community Member Score Calculation**
    - Test that score = mean of 5 dimensions, and rejection iff score < 7.0
    - File: `tests/properties/test_gcm_score_props.py`
    - **Validates: Requirements 7.5, 7.6**

  - [ ] 9.4 Implement content output rules in safety service
    - Enhance `app/services/safety.py` with new output rules
    - Implement comment length calibration: ±20% of tone fingerprint median (or 50-200 words if < 10 samples)
    - Implement Phase 1/2 brand name/promotional framing rejection
    - Implement competitor factual claims rejection (no unattributed claims)
    - Implement direct link rejection (Phase 3 only, ratio < 15%)
    - Log all rejections with rule identifier and original content
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [ ]* 9.5 Write property test for comment length calibration (Property 8)
    - **Property 8: Comment Length Calibration**
    - Test that acceptance is within ±20% of median (or 50-200 words when sample_count < 10)
    - File: `tests/properties/test_length_calibration_props.py`
    - **Validates: Requirements 8.1**

  - [ ] 9.6 Create intelligence refresh background task
    - Create `app/tasks/intelligence.py`
    - Implement subreddit intelligence refresh (every 7 days per subreddit)
    - Scrape top comments, compute tone fingerprint metrics, extract topic clusters
    - Register task in SQS scheduler
    - _Requirements: 7.2, 7.3_

- [ ] 10. Checkpoint — Content intelligence tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Budget, Usage & Billing Tier Enforcement
  - [ ] 11.1 Implement budget and usage tracking service
    - Create `app/services/budget.py`
    - Implement `increment_usage(client_id, metric_type)` — Valkey atomic increment + PG sync
    - Implement `check_limit(client_id, action_type)` — returns allowed/blocked
    - Implement 80% threshold alert generation (within 5 minutes)
    - Implement 100% limit pause (block new generation/posting, allow health checks)
    - Implement dispatched-task overage handling (allow completion, log overage)
    - Implement usage dashboard data: current vs. limits, daily bar chart, projection, days remaining
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [ ]* 11.2 Write property test for budget alert threshold (Property 10)
    - **Property 10: Budget Alert Threshold**
    - Test that alert triggers at U >= 0.8*L and not when U < 0.8*L
    - File: `tests/properties/test_budget_alert_props.py`
    - **Validates: Requirements 11.3**

  - [ ]* 11.3 Write property test for plan limit enforcement (Property 6)
    - **Property 6: Plan Limit Enforcement**
    - Test resource rejection at limit, comment blocking at monthly cap, correct tier lookup
    - File: `tests/properties/test_plan_limits_props.py`
    - **Validates: Requirements 11.2, 11.4, 12.1, 12.2**

  - [ ] 11.4 Implement billing tier enforcement service
    - Create `app/services/billing_tier.py`
    - Implement `validate_resource_addition(client_id, resource_type)` — check avatar/subreddit counts vs. plan
    - Implement upgrade logic: apply new limits within 60 seconds, preserve usage
    - Implement downgrade logic: enforce at next billing cycle, notify 7 days before, deactivate excess (most recent first)
    - Implement pipeline action rejection when monthly limit exceeded
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7_

  - [ ] 11.5 Create usage reset background task
    - Create `app/tasks/usage_reset.py`
    - Reset all client usage counters at 00:00 UTC on 1st of each month
    - Lift any active pauses on month boundary
    - Register task in SQS scheduler
    - _Requirements: 11.1, 11.7_

  - [ ]* 11.6 Write property test for usage counter month reset (Property 11)
    - **Property 11: Usage Counter Month Reset**
    - Test that counters reset to zero and pauses are lifted on month boundary
    - File: `tests/properties/test_month_reset_props.py` (or inline in budget tests)
    - **Validates: Requirements 11.1, 11.7**

  - [ ] 11.7 Create budget alerts background task
    - Create `app/tasks/budget_alerts.py`
    - Inline check on usage increment: if crosses 80% threshold, emit alert
    - Send notification to client and account manager
    - _Requirements: 11.3_

  - [ ] 11.8 Add usage dashboard to client portal
    - Create portal usage template showing current period usage vs. limits
    - Add daily usage bar chart, projected end-of-period usage, days remaining
    - Wire into portal routes
    - _Requirements: 11.6_

- [ ] 12. Checkpoint — Budget and billing tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 13. Phase 2 — Competitor & Mentor Intelligence
  - [ ] 13.1 Implement mentor intelligence service
    - Create `app/services/mentor_intelligence.py`
    - Implement `create_tracked_avatar(client_id, reddit_username, label)` with tier limit check
    - Implement `poll_tracked_avatar(tracked_avatar_id)` — fetch public activity via PRAW
    - Implement `record_activity(tracked_avatar_id, activity_data)` — store in tracked_activities
    - Implement `generate_weekly_digest(client_id)` — activity count, topics, avg karma, overlap
    - Implement opportunity alert generation (keyword match in thread title/body)
    - Implement inactive detection (30 days no activity → mark inactive)
    - Enforce read-only invariant (reject any post/comment attempt)
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8_

  - [ ]* 13.2 Write property test for tracked avatar read-only invariant (Property 9)
    - **Property 9: Tracked Avatar Read-Only Invariant**
    - Test that all post/comment operations are rejected for tracked avatars
    - File: `tests/properties/test_tracked_avatar_readonly_props.py` (or `tests/properties/test_data_isolation_props.py`)
    - **Validates: Requirements 10.5**

  - [ ]* 13.3 Write property test for keyword opportunity alert (Property 13)
    - **Property 13: Keyword Opportunity Alert Generation**
    - Test that alert is generated iff client keyword appears in thread title/body
    - File: `tests/properties/test_opportunity_alert_props.py` (or inline in mentor tests)
    - **Validates: Requirements 10.4**

  - [ ] 13.4 Create mentor polling background task
    - Create `app/tasks/mentor_poll.py`
    - Poll each active tracked avatar every 6 hours via PRAW
    - Record new activities, check for keyword matches, generate alerts
    - Handle rate limiting with backoff
    - Register task in SQS scheduler
    - _Requirements: 10.1, 10.2, 10.4_

- [ ] 14. Phase 2 — Personal Brand Module
  - [ ] 14.1 Implement personal brand service
    - Create `app/services/personal_brand.py`
    - Implement Reddit OAuth connection (read + identity scopes) via httpx
    - Implement account configuration (expertise topics, tone, target subreddits, mentors)
    - Implement suggestion generation (match expertise to thread opportunities, draft responses)
    - Implement auto-publish logic: default OFF, daily cap of 5, 30-day re-confirmation
    - Implement weekly performance digest generation
    - Handle OAuth failure/retry without losing configuration
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8_

  - [ ] 14.2 Create personal brand routes and templates
    - Create `app/routes/personal_brand.py` with `/portal/brand` routes
    - Create OAuth connection flow template
    - Create configuration template (topics, tone, subreddits, mentors)
    - Create suggestions list template with draft responses
    - Create performance digest template
    - _Requirements: 9.1, 9.3, 9.4, 9.6_

  - [ ] 14.3 Create personal brand scan background task
    - Create `app/tasks/personal_brand_scan.py`
    - Scan every 6 hours for thread opportunities matching expertise
    - Generate up to 20 suggestions per day with draft responses
    - Include mentor-engaged threads in suggestions
    - Register task in SQS scheduler
    - _Requirements: 9.4, 9.5_

- [ ] 15. Integration and wiring
  - [ ] 15.1 Wire phase policy into generation pipeline
    - Integrate phase content restrictions into `app/services/generation.py`
    - Integrate GCM scoring into generation flow (score → reject/accept → regenerate)
    - Integrate content intelligence context assembly into generation prompt
    - Integrate budget limit check before generation dispatch
    - Integrate compliance gate check before pipeline activation
    - _Requirements: 1.1, 1.4, 1.5, 7.1, 7.5, 8.1, 11.4, 3.4_

  - [ ] 15.2 Wire billing tier validation into admin CRUD operations
    - Add tier limit checks to avatar creation/assignment endpoints
    - Add tier limit checks to subreddit addition endpoints
    - Add upgrade/downgrade handling to client edit endpoints
    - Display upgrade prompts when limits reached
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [ ] 15.3 Wire guardrail override indicators into portal and admin UI
    - Add persistent override indicator to client dashboard
    - Add override indicator to admin panel
    - Show override type and expiration date
    - _Requirements: 4.5_

  - [ ]* 15.4 Write integration tests for pipeline with budget limits
    - Test that generation is blocked when client reaches plan limit
    - Test that compliance gate blocks pipeline for non-accepted clients
    - Test that phase policy blocks brand mentions in Phase 1
    - File: `tests/integration/test_budget_pipeline.py`, `tests/integration/test_compliance_gate.py`
    - _Requirements: 11.4, 3.4, 1.1_

- [ ] 16. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- All services follow the existing pattern: thin routes delegate to services layer
- Migrations should be run sequentially (task group 1) before any service implementation
- Portal templates use a new `portal_base.html` (light theme) distinct from admin
- Valkey is used for real-time usage counters; PostgreSQL for durable history
- The Personal Brand Module (tasks 14.x) is Phase 2 and can be deferred

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8", "1.9", "1.10"] },
    { "id": 1, "tasks": ["3.1", "3.3", "3.6", "5.1", "5.3", "7.1"] },
    { "id": 2, "tasks": ["3.2", "3.4", "3.5", "3.7", "3.8", "5.2", "5.4", "5.5", "5.6", "7.2"] },
    { "id": 3, "tasks": ["7.3", "7.4", "9.1", "9.2", "11.1", "11.4", "13.1"] },
    { "id": 4, "tasks": ["7.5", "7.6", "9.3", "9.4", "9.5", "9.6", "11.2", "11.3", "11.5", "11.6", "11.7", "11.8", "13.2", "13.3", "13.4"] },
    { "id": 5, "tasks": ["14.1", "14.2", "14.3"] },
    { "id": 6, "tasks": ["15.1", "15.2", "15.3"] },
    { "id": 7, "tasks": ["15.4"] }
  ]
}
```
