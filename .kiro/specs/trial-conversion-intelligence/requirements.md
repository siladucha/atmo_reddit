# Requirements Document

## Introduction

Trial Conversion Intelligence is an internal layer for RAMP Owner/Partner roles (Tzvi and Max) that treats every trial account as a sales opportunity. The system continuously scores trial accounts on conversion likelihood using a deterministic scoring engine, generates AI-powered sales briefings, recommends next actions, and provides a unified dashboard for trial pipeline management. The goal is to help founders perform higher-quality manual sales conversations by surfacing actionable intelligence — not to automate sales outreach.

Architecture: Signals flow through a deterministic Scoring_Engine to produce score snapshots. LLM interpretation (summaries, outreach drafts) operates only on score snapshots — the LLM does NOT compute scores.

```
Signals → Deterministic Scoring Engine → Score Snapshot → LLM Interpretation (summary/outreach only)
```

## Glossary

- **Trial_Account**: A client record with `plan_type="trial"` and a 14-day active window
- **Conversion_Score**: A numeric probability (integer 0–100) representing likelihood of a trial user converting to a paid plan, computed deterministically from weighted signals
- **Opportunity_Value**: An estimated dollar value ($) of a trial account if converted, based on engagement signals and company profile
- **Priority_Score**: A composite score (integer 0–100) computed as f(Conversion_Score × Opportunity_Value × urgency), used for dashboard sorting and prioritization
- **Score_Explanation**: A structured breakdown of the top positive and negative signals contributing to Conversion_Score, including per-factor numeric contributions
- **Negative_Signal**: A measurable user inaction or negative behavior pattern that decreases the Conversion_Score (e.g., no_activity_72h, bounced_email, onboarding_abandoned)
- **Trial_Lifecycle_State**: One of: trial_started, onboarding_started, activated, engaged, high_intent, at_risk, expired, converted, reactivated — representing the funnel position of a Trial_Account
- **Signal**: A measurable user action, attribute, or inaction that contributes to the Conversion_Score calculation
- **Signal_Category**: A grouping of related signals (Engagement, Intent, Value_Realization, Conversion, Negative)
- **Scoring_Engine**: The deterministic service that computes Conversion_Score, Priority_Score, and Opportunity_Value from collected signals without any LLM involvement
- **Trial_Dashboard**: The Owner/Partner-facing page displaying all active trials with scores, actions, and status
- **Sales_Summary**: An AI-generated one-page briefing about a trial account covering activity, value discovered, and likely objections
- **Sales_Summary_Generator**: The LLM-based service that interprets score snapshots to produce human-readable Sales_Summary documents
- **Suggested_Outreach**: AI-generated communication drafts (email, LinkedIn message, follow-up) tailored to a specific trial account
- **Outreach_Generator**: The LLM-based service that produces Suggested_Outreach drafts from score snapshots
- **Trial_Failure_Classification**: A category assigned to expired trials explaining why conversion did not happen, enriched with reactivation intelligence
- **Recommended_Action**: A specific next step suggested by the system for a given trial account (e.g., "Send reactivation email", "Schedule discovery call")
- **Owner_Dashboard**: The admin interface accessible only to Owner and Partner roles
- **Reactivation_Candidate**: An expired trial account that the AI determines may be worth re-engaging at a future date
- **Intelligence_Event**: An auditable action taken within the trial intelligence system (e.g., generated_summary, copied_outreach, changed_score)

## Requirements

### Requirement 1: Trial Signal Collection

**User Story:** As an Owner, I want the system to automatically collect engagement, intent, and negative signals from trial accounts, so that I can understand trial user behavior without manual tracking.

#### Acceptance Criteria

1. WHEN a trial user completes a session action (login, page view, report view, discovery run), THE Scoring_Engine SHALL record the action as a Signal with timestamp, signal type, and trial account reference
2. WHEN a trial user completes the onboarding wizard, THE Scoring_Engine SHALL record an onboarding_completed Signal for that Trial_Account
3. THE Scoring_Engine SHALL collect signals in five categories: Engagement (sessions, time spent, reports viewed, discovery runs, return visits), Intent (email domain, company size, industry, competitor usage, monitored subreddits, tracked keywords), Value_Realization (landscape report generated, opportunity report generated, high-intent conversations discovered, strategic insights viewed), Conversion (pricing page viewed, upgrade screen opened, upgrade CTA clicked, support contacted, email replied), and Negative (no_activity_72h, bounced_email, multiple_short_sessions, viewed_pricing_without_upgrade, onboarding_abandoned, removed_keywords, export_without_return, report_open_no_scroll)
4. WHEN a signal is recorded, THE Scoring_Engine SHALL store the signal with created_at timestamp in Asia/Jerusalem timezone context
5. IF a Signal cannot be recorded due to a database error, THEN THE Scoring_Engine SHALL log the failure and retry once before discarding
6. WHEN a trial user has no activity for 72 consecutive hours, THE Scoring_Engine SHALL record a no_activity_72h Negative_Signal
7. WHEN a trial user completes 3 or more sessions under 30 seconds within a 24-hour window, THE Scoring_Engine SHALL record a multiple_short_sessions Negative_Signal
8. WHEN a trial user views the pricing page without returning within 24 hours, THE Scoring_Engine SHALL record a viewed_pricing_without_upgrade Negative_Signal
9. WHEN a trial user starts the onboarding wizard but does not complete it within 48 hours, THE Scoring_Engine SHALL record an onboarding_abandoned Negative_Signal
10. WHEN a trial user removes previously configured keywords, THE Scoring_Engine SHALL record a removed_keywords Negative_Signal
11. WHEN a trial user exports data but does not return within 48 hours, THE Scoring_Engine SHALL record an export_without_return Negative_Signal
12. WHEN a trial user opens a report but scrolls less than 10% of the content, THE Scoring_Engine SHALL record a report_open_no_scroll Negative_Signal

### Requirement 2: Trial Conversion Scoring

**User Story:** As an Owner, I want each trial account to have an automatically calculated conversion score, priority score, and explainability layer, so that I can prioritize which trials to focus on with full context.

#### Acceptance Criteria

1. THE Scoring_Engine SHALL compute a Conversion_Score (integer 0–100) for each active Trial_Account representing conversion probability only, based on weighted signals from all five Signal_Categories
2. THE Scoring_Engine SHALL compute an Opportunity_Value (dollar estimate) for each active Trial_Account based on company size, industry, and engagement depth
3. THE Scoring_Engine SHALL compute a Priority_Score (integer 0–100) for each active Trial_Account as a function of Conversion_Score, Opportunity_Value, and urgency (days remaining in trial)
4. WHEN a new Signal is recorded for a Trial_Account while the user is on the dashboard, THE Scoring_Engine SHALL recompute the Conversion_Score within 30 seconds (interactive scoring)
5. WHEN a new Signal is recorded for a Trial_Account and no user is on the dashboard, THE Scoring_Engine SHALL recompute the Conversion_Score within 5 minutes (background reconciliation)
6. WHEN multiple signals are recorded for a Trial_Account within a 60-second window, THE Scoring_Engine SHALL debounce recomputation and process the batch as a single scoring event
7. THE Scoring_Engine SHALL assign configurable weights to each Signal_Category: Engagement (20%), Intent (25%), Value_Realization (25%), Conversion (20%), Negative (-10% to -30% depending on signal severity)
8. THE Scoring_Engine SHALL produce a Recommended_Action for each Trial_Account based on the Conversion_Score, days remaining in trial, Trial_Lifecycle_State, and recent activity patterns
9. WHEN the Conversion_Score changes by more than 10 points, THE Scoring_Engine SHALL emit an activity event recording the score change
10. THE Scoring_Engine SHALL expose a Score_Explanation for each Trial_Account containing the top 5 positive signals and top 5 negative signals contributing to the Conversion_Score, with numeric contribution values per signal
11. THE Scoring_Engine SHALL apply Negative_Signal penalties that decrease the Conversion_Score (score can go down, not only up)
12. THE Scoring_Engine SHALL compute all scores deterministically without any LLM involvement in the scoring loop

### Requirement 3: Trial Lifecycle State Machine

**User Story:** As an Owner, I want each trial account to have a clear lifecycle state, so that I can visualize the funnel and understand where each trial stands.

#### Acceptance Criteria

1. THE Scoring_Engine SHALL assign each Trial_Account exactly one Trial_Lifecycle_State from: trial_started, onboarding_started, activated, engaged, high_intent, at_risk, expired, converted, reactivated
2. WHEN a new trial signup occurs, THE Scoring_Engine SHALL assign the trial_started state
3. WHEN a trial user begins the onboarding wizard, THE Scoring_Engine SHALL transition the state to onboarding_started
4. WHEN a trial user completes onboarding and has valid configuration, THE Scoring_Engine SHALL transition the state to activated
5. WHEN a trial user produces meaningful usage signals (reports viewed, discovery runs, keywords configured), THE Scoring_Engine SHALL transition the state to engaged
6. WHEN a trial user triggers conversion signals (pricing viewed, upgrade CTA clicked, support contacted), THE Scoring_Engine SHALL transition the state to high_intent
7. WHEN a trial user has no activity for 72 or more hours OR Negative_Signals dominate the score, THE Scoring_Engine SHALL transition the state to at_risk
8. WHEN 14 days elapse without conversion, THE Scoring_Engine SHALL transition the state to expired
9. WHEN a trial user upgrades to a paid plan, THE Scoring_Engine SHALL transition the state to converted
10. WHEN an expired trial user re-engages (new login or activity after expiry), THE Scoring_Engine SHALL transition the state to reactivated
11. THE Trial_Dashboard SHALL display Trial_Lifecycle_State for each trial and support filtering by state
12. THE Trial_Dashboard SHALL display a funnel visualization showing count of trials in each lifecycle state

### Requirement 4: Trial Opportunity Dashboard

**User Story:** As an Owner or Partner, I want a single dashboard showing all active trials with conversion intelligence sorted by priority, so that I can decide which trial to engage and what to say.

#### Acceptance Criteria

1. THE Trial_Dashboard SHALL display all active Trial_Accounts in a sortable table with columns: client name, company domain, signup date, days remaining, Trial_Lifecycle_State, activity level (high/medium/low/none), Conversion_Score, Priority_Score, Opportunity_Value, and Recommended_Action
2. THE Trial_Dashboard SHALL be accessible only to users with Owner or Partner roles
3. WHEN an Owner or Partner loads the Trial_Dashboard, THE Trial_Dashboard SHALL display data current within the last 5 minutes
4. THE Trial_Dashboard SHALL sort by Priority_Score by default and allow sorting by Conversion_Score, Priority_Score, days remaining, signup date, and Opportunity_Value
5. THE Trial_Dashboard SHALL allow filtering by activity level (high, medium, low, none), by days remaining range, and by Trial_Lifecycle_State
6. WHEN a Trial_Account has zero signals recorded in the last 5 days, THE Trial_Dashboard SHALL display an "inactive" indicator with a "Recommend reactivation email" action
7. THE Trial_Dashboard SHALL display a summary row showing total active trials, average Conversion_Score, estimated total pipeline value, and funnel state distribution
8. WHEN an Owner expands a trial row, THE Trial_Dashboard SHALL display the Score_Explanation showing top positive and negative signal contributions

### Requirement 5: AI Sales Summary Generation

**User Story:** As an Owner, I want to generate an AI-powered sales briefing for any trial account that is cached and deterministic per score snapshot, so that I can prepare for a sales conversation in under 2 minutes.

#### Acceptance Criteria

1. WHEN an Owner requests a Sales_Summary for a Trial_Account, THE Sales_Summary_Generator SHALL produce a structured briefing containing: client identity (name, company, industry, domain), activity summary (what the user did during the trial), value discovered (reports generated, insights viewed, opportunities found), problems being solved (inferred from onboarding data and usage patterns), and likely objections (inferred from engagement gaps and industry context)
2. THE Sales_Summary_Generator SHALL use Claude Sonnet via LiteLLM for generation
3. THE Sales_Summary_Generator SHALL complete generation within 15 seconds
4. THE Sales_Summary_Generator SHALL include specific data points from the trial (e.g., "Viewed competitor report 4 times", "Generated 2 landscape reports") rather than generic statements
5. IF the Trial_Account has fewer than 3 recorded signals, THEN THE Sales_Summary_Generator SHALL indicate insufficient data and list what is known
6. THE Sales_Summary_Generator SHALL store each generated summary with a sales_summary_version, generated_from_score_id (linking to the trial_scores record used), and cached_until timestamp
7. THE Sales_Summary_Generator SHALL return the cached result when the underlying score_id has not changed since the last generation
8. WHEN the score_id differs from the cached version, THE Sales_Summary_Generator SHALL regenerate the summary from the new score snapshot

### Requirement 6: AI Suggested Outreach Generation

**User Story:** As an Owner, I want the system to generate draft outreach messages for a trial account with hard safeguards against automation, so that I can initiate high-quality sales conversations faster while maintaining full human control.

#### Acceptance Criteria

1. WHEN an Owner requests Suggested_Outreach for a Trial_Account, THE Outreach_Generator SHALL produce four drafts: email, LinkedIn message, follow-up message, and discovery call preparation notes
2. THE Outreach_Generator SHALL personalize each draft using the trial user's name, company, industry, specific actions taken during the trial, and value signals observed
3. THE Outreach_Generator SHALL use Claude Sonnet via LiteLLM for generation
4. THE Outreach_Generator SHALL complete generation of all four drafts within 20 seconds
5. THE Outreach_Generator SHALL present drafts as editable text that can be copied to clipboard
6. THE Outreach_Generator SHALL tailor messaging tone based on Conversion_Score: high score (>70) uses urgency and value confirmation, medium score (40–70) uses curiosity and additional value proposition, low score (<40) uses soft re-engagement and question-based approach
7. THE System SHALL NOT send outreach automatically under any circumstances
8. THE System SHALL require explicit human review before any outreach is sent
9. THE System SHALL record who copied or exported outreach drafts in the Intelligence_Event audit trail with user identity and timestamp

### Requirement 7: Trial Failure Analysis with Reactivation Intelligence

**User Story:** As an Owner, I want expired trials to be automatically classified by failure reason and enriched with reactivation intelligence, so that I can identify patterns, improve the trial experience, and win back promising leads.

#### Acceptance Criteria

1. WHEN a Trial_Account expires (14 days elapsed without conversion), THE Scoring_Engine SHALL classify the failure into one of these categories: no_engagement, wrong_icp, budget_issue, no_urgency, no_value_discovered, product_confusion, unknown
2. THE Scoring_Engine SHALL assign the failure classification based on signal patterns: no_engagement (fewer than 2 sessions), wrong_icp (free email domain or mismatched industry signals), no_value_discovered (no reports generated, no opportunities reviewed), product_confusion (started onboarding but did not complete, or completed but no subsequent usage)
3. WHEN a Trial_Account is classified as expired, THE Scoring_Engine SHALL generate an AI analysis proposing what could have been done differently and whether the lead should be reactivated later
4. THE Trial_Dashboard SHALL include an "Expired Trials" tab showing classified failures with AI analysis
5. THE Trial_Dashboard SHALL display aggregate failure statistics (count per category, trend over time)
6. WHEN a Trial_Account is classified, THE Scoring_Engine SHALL produce reactivation intelligence containing: win_back_window_days (estimated best time in days to re-engage), next_best_action (specific action for reactivation), and confidence (0.0–1.0)
7. THE Scoring_Engine SHALL store reactivation intelligence as structured JSON alongside the failure classification

### Requirement 8: Trial Data Model and Storage

**User Story:** As a developer, I want trial intelligence data stored in PostgreSQL with proper schema, so that scoring and reporting queries perform efficiently.

#### Acceptance Criteria

1. THE System SHALL store trial signals in a dedicated `trial_signals` table with columns: id (UUID), client_id (FK to clients), signal_type (String), signal_category (String), signal_value (JSONB), created_at (DateTime with timezone)
2. THE System SHALL store trial scores in a dedicated `trial_scores` table with columns: id (UUID), client_id (FK to clients), conversion_score (Integer 0–100), priority_score (Integer 0–100), opportunity_value_cents (Integer), recommended_action (Text), score_explanation (JSONB), signal_snapshot (JSONB), lifecycle_state (String), scored_at (DateTime with timezone)
3. THE System SHALL store trial failure classifications in a dedicated `trial_failures` table with columns: id (UUID), client_id (FK to clients), failure_category (String), ai_analysis (Text), reactivation_recommended (Boolean), win_back_window_days (Integer), next_best_action (Text), reactivation_confidence (Float), classified_at (DateTime with timezone)
4. THE System SHALL create database indexes on client_id and created_at for the trial_signals table to support efficient time-range queries
5. THE System SHALL retain trial signal data for 180 days after trial expiration, then archive or delete
6. THE System SHALL store sales summaries in a dedicated `trial_sales_summaries` table with columns: id (UUID), client_id (FK to clients), score_id (FK to trial_scores), sales_summary_version (Integer), content (Text), cached_until (DateTime with timezone), generated_at (DateTime with timezone)
7. THE System SHALL store intelligence events in a dedicated `trial_intelligence_events` table with columns: id (UUID), client_id (FK to clients), user_id (FK to users), event_type (String: generated_summary, generated_outreach, changed_score, opened_trial, marked_contacted, scheduled_followup, copied_outreach), event_metadata (JSONB), created_at (DateTime with timezone)

### Requirement 9: Access Control and Security

**User Story:** As an Owner, I want trial conversion intelligence restricted to Owner and Partner roles only, so that client-facing users cannot see internal sales metrics.

#### Acceptance Criteria

1. THE System SHALL restrict all Trial_Dashboard routes to users with Owner or Partner role
2. THE System SHALL restrict Sales_Summary and Suggested_Outreach generation endpoints to users with Owner or Partner role
3. IF a user without Owner or Partner role attempts to access trial intelligence endpoints, THEN THE System SHALL return HTTP 403 and log the access attempt
4. THE System SHALL ensure trial scoring data is excluded from client-facing portal queries and API responses

### Requirement 10: Intelligence Event Audit Trail

**User Story:** As an Owner, I want all interactions with trial intelligence to be logged, so that I can track sales ops activity and measure system usage.

#### Acceptance Criteria

1. WHEN an Owner generates a Sales_Summary, THE System SHALL record a generated_summary Intelligence_Event with the client_id, user_id, and score_id used
2. WHEN an Owner generates Suggested_Outreach, THE System SHALL record a generated_outreach Intelligence_Event with the client_id, user_id, and outreach type
3. WHEN the Scoring_Engine changes a Conversion_Score by more than 5 points, THE System SHALL record a changed_score Intelligence_Event with old_score and new_score
4. WHEN an Owner opens a trial detail view, THE System SHALL record an opened_trial Intelligence_Event
5. WHEN an Owner marks a trial as contacted, THE System SHALL record a marked_contacted Intelligence_Event
6. WHEN an Owner schedules a followup for a trial, THE System SHALL record a scheduled_followup Intelligence_Event with the scheduled date
7. WHEN an Owner copies or exports an outreach draft, THE System SHALL record a copied_outreach Intelligence_Event with the draft type and user identity
8. THE Trial_Dashboard SHALL display a recent activity feed showing Intelligence_Events for the selected trial

### Requirement 11: Source of Truth Architecture

**User Story:** As a developer, I want the scoring architecture to enforce deterministic computation separate from LLM interpretation, so that scores are reproducible and auditable.

#### Acceptance Criteria

1. THE Scoring_Engine SHALL compute Conversion_Score, Priority_Score, and Opportunity_Value using only deterministic rules and weighted signal aggregation without any LLM API calls
2. THE Sales_Summary_Generator and Outreach_Generator SHALL operate exclusively on score snapshots (trial_scores records) and SHALL NOT access raw signals directly for interpretation
3. THE System SHALL store a complete signal_snapshot in each trial_scores record so that any score can be reproduced from the snapshot alone
4. WHEN a score is recomputed, THE Scoring_Engine SHALL produce an identical result given the same signal_snapshot input (deterministic reproducibility)
5. THE System SHALL clearly separate the scoring path (deterministic, fast, no external API calls) from the interpretation path (LLM-based, cached, operates on snapshots)
