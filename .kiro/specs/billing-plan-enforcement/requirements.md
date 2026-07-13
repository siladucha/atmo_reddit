# Requirements Document

## Introduction

Billing Plan Enforcement defines the business rules and policies governing plan limits, upsell triggers, plan transitions, payment failure handling, trial-to-paid conversion, and Stripe webhook processing for the RAMP platform. This spec codifies WHAT happens at each billing state transition — before any Stripe integration code is written.

The system currently has `plan_type` on clients (trial/seed/starter/growth/scale) with `max_comments_per_month` and `max_avatars` fields, but these limits are NOT enforced at runtime except for `trial_guard.py` (expired trial check). This spec closes that gap.

## Glossary

- **Plan_Enforcer**: The service responsible for checking and enforcing plan limits at runtime
- **Upsell_Controller**: The service responsible for detecting upsell conditions and presenting upgrade prompts
- **Plan_Transition_Manager**: The service responsible for orchestrating plan changes (upgrade/downgrade) and their cascading effects
- **Grace_Period_Manager**: The service responsible for handling failed payment states and access degradation
- **Billing_State_Machine**: The composite system governing all billing state transitions for a client
- **Action**: A billable unit of work — one comment OR one post counts as one action. A draft that was posted and later deleted by Reddit still counts (resource was consumed).
- **Monthly_Action_Counter**: A per-client counter tracking actions consumed in the current billing period
- **Billing_Period**: The subscription period as defined by Stripe (`current_period_start` to `current_period_end`). RAMP mirrors these timestamps from webhooks — never computes its own 30-day windows. For trial clients (no Stripe subscription), the period is `created_at` to `created_at + 14 days`.
- **Hard_Limit**: A plan limit that blocks further actions when reached (pipeline stops generating)
- **Soft_Limit**: A threshold that triggers warnings and upsell prompts but does not block actions
- **Grace_Period**: A 7-day window after payment failure during which service continues at reduced capacity
- **Dunning**: The process of notifying clients about failed payments and attempting recovery
- **Subscription_Status**: The Stripe-sourced state of a client's subscription (active/past_due/canceled/trialing/suspended/archived)
- **Plan_Tier**: One of trial, seed, starter, growth, scale, agency — each with defined limits
- **Per_Client_Override**: An explicit limit value set on a specific client by admin (custom deals). Takes precedence over plan_definitions for that client only.
- **Post_Sub_Limit**: The maximum number of actions that can be Reddit posts (as opposed to comments) within the total max_actions_per_month. Posts consume from the shared action pool but cannot exceed this sub-limit.

## Requirements

### Requirement 1: Plan Limit Enforcement at Runtime

**User Story:** As a platform operator, I want the pipeline to enforce plan limits in real time, so that clients cannot consume resources beyond what they pay for.

#### Acceptance Criteria

1. WHEN the Monthly_Action_Counter for a client reaches 80% of the plan hard limit, THE Plan_Enforcer SHALL emit a `plan_limit_approaching` notification to the client and record the event, and SHALL NOT emit this notification again until the counter crosses the next 10% threshold (90%, 100%)
2. WHEN the Monthly_Action_Counter for a client reaches 100% of the plan hard limit, THE Plan_Enforcer SHALL block all new EPG slot generation for that client until the next billing period starts
3. WHILE a client is at 100% of the plan hard limit, THE Plan_Enforcer SHALL allow already-generated and approved drafts to proceed to execution (no mid-flight cancellation)
4. WHEN a new EPG build is triggered for a client, THE Plan_Enforcer SHALL check remaining budget as `plan_limit - Monthly_Action_Counter` and pass this as a ceiling to the portfolio manager, capping per-avatar allocation accordingly
5. THE Plan_Enforcer SHALL increment the Monthly_Action_Counter by one when a draft transitions to `posted` status (the moment the comment or post is confirmed published), not at draft generation or approval time. A draft that was posted and later deleted by Reddit (is_deleted=true) SHALL still count toward the Monthly_Action_Counter (resource was consumed, removal is platform enforcement not a billing reversal).
6. WHEN Stripe sends a `customer.subscription.updated` or `invoice.paid` event indicating a new billing period has started (new `current_period_start`), THE Plan_Enforcer SHALL reset the Monthly_Action_Counter to zero and store the previous period's final count in a billing_period_history record. THE Plan_Enforcer SHALL mirror `current_period_start` and `current_period_end` from Stripe — never compute its own 30-day windows.
7. WHEN a client has more avatars assigned than the plan allows (max_avatars), THE Plan_Enforcer SHALL prevent new avatar assignment but SHALL NOT deactivate existing over-limit avatars
8. THE Plan_Enforcer SHALL run a daily reconciliation check (at 01:30 UTC) comparing the Monthly_Action_Counter value against the actual count of drafts with status='posted' and posted_at within the current billing period; IF drift exceeds 5%, THE Plan_Enforcer SHALL recompute the counter from source-of-truth and log the discrepancy as a `billing_counter_drift` activity event
9. WHEN `max_posts_per_month` (Post_Sub_Limit) for a client is reached, THE Plan_Enforcer SHALL block new post generation while still allowing comment generation up to the remaining action budget. Posts and comments share a single Monthly_Action_Counter, but posts cannot exceed their sub-limit.
10. IF a client has a Per_Client_Override for any limit field (set by admin), THE Plan_Enforcer SHALL use the override value instead of the plan_definitions value for that specific limit. All other limits still come from plan_definitions.

### Requirement 2: Upsell Trigger Detection and Prompt Delivery

**User Story:** As a platform operator, I want the system to detect when clients are approaching or hitting limits and present contextual upgrade prompts, so that clients upgrade before they experience service degradation.

#### Acceptance Criteria

1. WHEN the Monthly_Action_Counter reaches 80% of the plan hard limit, THE Upsell_Controller SHALL display an upgrade prompt in the client portal header with usage percentage and next tier benefits, and IF the client is already on the highest plan tier (Scale), THE Upsell_Controller SHALL not display an upgrade prompt
2. WHEN a client attempts to add an avatar beyond max_avatars for the current plan, THE Upsell_Controller SHALL display an inline upgrade prompt showing the next tier that allows more avatars and the price difference
3. WHEN a client on Seed plan requests more than 1 professional subreddit, THE Upsell_Controller SHALL display a contextual prompt explaining Starter tier subreddit allowance
4. WHEN a trial client reaches day 10 of the 14-day trial AND has at least 1 posted draft, THE Upsell_Controller SHALL send a conversion email with plan comparison and trial results summary (total drafts generated, total posted, karma earned)
5. WHEN a trial client's first draft transitions to `posted` status, THE Upsell_Controller SHALL display a one-time conversion prompt showing the posted comment, its karma outcome (if available), and subscription options
6. THE Upsell_Controller SHALL record every upsell prompt impression (prompt_type, client_id, timestamp) and click-through (prompt_type, client_id, clicked_plan, timestamp) in a `upsell_events` table for conversion funnel analysis
7. WHILE a client has dismissed an upsell prompt, THE Upsell_Controller SHALL not show the same prompt_type again for 72 hours, where prompt_type is one of: `usage_limit`, `avatar_limit`, `subreddit_limit`, `trial_conversion`, `trial_first_post`

### Requirement 3: Plan Transition Orchestration (Upgrade)

**User Story:** As a client administrator, I want to upgrade my plan and immediately receive expanded limits, so that I can scale my Reddit marketing without interruption.

#### Acceptance Criteria

1. WHEN a client upgrades to a higher plan tier, THE Plan_Transition_Manager SHALL update max_comments_per_month and max_avatars to the new plan values within 5 seconds of the upgrade confirmation
2. WHEN a client upgrades mid-period, THE Plan_Transition_Manager SHALL NOT reset the Monthly_Action_Counter but SHALL raise the ceiling to the new plan's max_actions_per_month. The client's remaining budget becomes `new_limit - current_counter` (effectively granting the difference in limits as additional capacity).
3. WHEN a client upgrades, THE Plan_Transition_Manager SHALL immediately allow new avatar assignments up to the new max_avatars ceiling without requiring existing avatars to be reconfigured
4. WHEN a client upgrades from Seed to Starter or higher, THE Plan_Transition_Manager SHALL unlock professional subreddit scoring and generation for all of that client's Phase 2+ avatars and trigger an EPG rebuild for each affected avatar within 30 minutes of the upgrade
5. WHEN a client upgrades, THE Plan_Transition_Manager SHALL emit a `plan_upgraded` activity event containing the previous plan, new plan, and effective timestamp, and send a confirmation notification to all client_admin and client_manager users of that client
6. IF the plan upgrade transaction fails due to a payment processing error or database error, THEN THE Plan_Transition_Manager SHALL retain the client's current plan limits unchanged, log the failure reason, and return an error message indicating the upgrade could not be completed
7. WHEN a client upgrades, THE Plan_Transition_Manager SHALL unfreeze any avatars that were frozen with reason `plan_downgrade_excess` (from a previous downgrade) up to the new plan's max_avatars limit

### Requirement 4: Plan Transition Orchestration (Downgrade)

**User Story:** As a platform operator, I want downgrades to be handled gracefully without data loss, so that clients who reduce their plan retain their configuration even if limits tighten.

#### Acceptance Criteria

1. WHEN a client downgrades to a lower plan tier (where tier ordering from lowest to highest is: trial, seed, starter, growth, scale), THE Plan_Transition_Manager SHALL schedule the effective date to the end of the current billing cycle (not immediate) and record the pending downgrade with target plan type and scheduled effective date
2. WHILE a downgrade is pending (scheduled but not yet effective), THE Plan_Transition_Manager SHALL continue enforcing the current higher plan limits until the effective date and allow the client to cancel the pending downgrade at any time before the effective date
3. WHEN a downgrade becomes effective, THE Plan_Transition_Manager SHALL update all plan-governed limits (max_avatars, max_comments_per_month, max_subreddits, max_professional_subreddits, max_posts_per_month, geo_monitoring_enabled, geo_prompts_limit) to the new plan values
4. WHEN a downgrade results in more active avatars than the new plan allows, THE Plan_Transition_Manager SHALL freeze the most recently created excess avatars with reason `plan_downgrade_excess`, cancel any pending EPG slots and execution tasks for those frozen avatars, and send a notification to client admins to choose which avatars to keep within 14 days
5. IF a client has not selected which avatars to keep within 14 days of a plan downgrade freeze, THEN THE Plan_Transition_Manager SHALL retain the frozen state on the most recently created avatars (no data deletion) and emit a `downgrade_avatar_choice_expired` activity event
6. WHEN a downgrade results in more active subreddit assignments than the new plan allows, THE Plan_Transition_Manager SHALL mark the lowest-priority excess assignments (ordered by the `priority` field, then by most recently added) as `over_limit` and exclude them from new EPG generation while keeping all assignment records and historical data intact
7. WHEN a downgrade becomes effective, THE Plan_Transition_Manager SHALL emit a `plan_downgraded` activity event containing previous plan, new plan, and a list of affected resources, and send a notification to all client admins listing capacity reductions and any resources frozen or marked as over_limit

### Requirement 5: Grace Period on Payment Failure

**User Story:** As a platform operator, I want failed payments to degrade service gradually rather than cut access immediately, so that clients have time to fix payment issues without losing their avatar warming progress.

#### Acceptance Criteria

1. WHEN a payment fails (Stripe `invoice.payment_failed` event), THE Grace_Period_Manager SHALL set the client subscription_status to `past_due` and begin a 7-calendar-day grace period starting from the moment the event is processed (not delayed to next day)
2. WHILE a client is in grace period (days 1-3), THE Grace_Period_Manager SHALL continue full service but display a payment failure banner in the client portal with an "Update Payment" link
3. WHILE a client is in grace period (days 4-7), THE Grace_Period_Manager SHALL reduce the daily EPG budget to 50% of the plan allocation (rounded down to the nearest whole number), cancel any planned-but-not-yet-generated slots exceeding the reduced budget, and display an urgent payment failure banner
4. WHEN the grace period expires (day 8) without successful payment, THE Grace_Period_Manager SHALL freeze all avatars for the client with reason `payment_failed`, stop all pipeline generation, and set client subscription_status to `suspended`
5. WHEN a suspended client's payment is recovered (Stripe `invoice.paid` event after past_due), THE Grace_Period_Manager SHALL unfreeze all avatars and restore full plan limits within 60 seconds of event receipt, and resume pipeline operations (next EPG build cycle) within 5 minutes
6. WHILE a client is in grace period, THE Grace_Period_Manager SHALL send dunning emails to all client_admin and client_manager users with verified email on day 1 (informational: payment failed, action needed), day 3 (warning: service reduction approaching), and day 6 (final notice: suspension in 48 hours)
7. IF a payment fails and the client has already had a previous grace period within the last 60 days, THEN THE Grace_Period_Manager SHALL shorten the grace period to 3 days with full service on day 1, reduced budget (50%, rounded down) on days 2-3, and suspension on day 4
8. IF a second Stripe `invoice.payment_failed` event is received while the client is already in an active grace period, THEN THE Grace_Period_Manager SHALL ignore the duplicate event and continue the existing grace period without resetting the timer
9. WHILE a client is in grace period, THE Grace_Period_Manager SHALL preserve all avatar karma, warming phase, activation routes, and posted comment history without modification

### Requirement 6: Trial to Paid Conversion Flow

**User Story:** As a trial client, I want a clear path from trial to paid subscription with my data and avatar progress preserved, so that I can continue without starting over.

#### Acceptance Criteria

1. WHEN a trial client selects a paid plan, THE Billing_State_Machine SHALL create a Stripe checkout session with the selected plan price and redirect the client to the Stripe-hosted payment page within 5 seconds of plan selection
2. WHEN Stripe confirms payment (checkout.session.completed webhook), THE Billing_State_Machine SHALL update the client plan_type from `trial` to the selected plan, set subscription_status to `active`, and record the Stripe subscription_id and customer_id
3. WHEN a trial converts to paid, THE Billing_State_Machine SHALL preserve all existing avatars (including phase, karma, voice, and health_status), drafts, subreddit assignments, strategy documents, and EPG configuration without modification to any field values
4. WHEN a trial converts to paid, THE Billing_State_Machine SHALL set billing_period_start and billing_period_end from the Stripe subscription's `current_period_start` and `current_period_end`, and reset the Monthly_Action_Counter to zero
5. WHEN a trial client's created_at timestamp exceeds 14 calendar days without conversion, THE Billing_State_Machine SHALL set all avatars to is_frozen=true with freeze_reason=`trial_expired`, stop pipeline generation for that client, and display a "Trial Expired — Choose a Plan" interstitial page on every authenticated portal route for that client
6. WHEN an expired trial client completes payment (within 90 days of expiry), THE Billing_State_Machine SHALL set all avatars to is_frozen=false, set health_status to `unknown` (forcing a fresh health check on next cycle), and resume pipeline generation within one scheduling cycle
7. IF an expired trial client has no authenticated login for 90 consecutive days after expiry, THEN THE Billing_State_Machine SHALL mark the client as `archived`, retain all data, and permanently set all avatars to is_frozen=true with freeze_reason `trial_archived`
8. IF the Stripe checkout session expires or payment fails, THEN THE Billing_State_Machine SHALL retain the client's current trial status unchanged and display an error message indicating payment was not completed with a prompt to retry
9. WHILE a trial is active (days 1-14), THE Billing_State_Machine SHALL allow the client to generate and post up to max_actions_per_month as defined in plan_definitions for the `trial` tier (currently 30 actions). The trial is NOT zero-action — it demonstrates value.

### Requirement 7: Stripe Webhook Event Processing

**User Story:** As a platform operator, I want all billing state changes to flow through verified Stripe webhooks, so that the system state is always consistent with Stripe's source of truth.

#### Acceptance Criteria

1. THE Billing_State_Machine SHALL verify Stripe webhook signatures using the webhook signing secret before processing any event
2. WHEN a `checkout.session.completed` event is received, THE Billing_State_Machine SHALL create the subscription record and activate the client plan
3. WHEN a `customer.subscription.updated` event is received with a plan change, THE Billing_State_Machine SHALL compare the new plan's tier to the current plan's tier and trigger an upgrade transition if the new tier is higher or a downgrade transition if the new tier is lower
4. WHEN a `customer.subscription.deleted` event is received, THE Billing_State_Machine SHALL schedule client deactivation at the subscription's `current_period_end` timestamp and notify the client via email within 5 minutes of event processing
5. WHEN an `invoice.payment_failed` event is received, THE Billing_State_Machine SHALL trigger the grace period flow as defined in Requirement 5
6. WHEN an `invoice.paid` event is received for a past_due subscription, THE Billing_State_Machine SHALL trigger payment recovery and restore full service as defined in Requirement 5 criterion 5
7. IF a webhook event is received with an event_id that has already been processed, THEN THE Billing_State_Machine SHALL skip processing and return HTTP 200 (idempotency)
8. IF webhook processing fails with a transient error (network timeout, database connection failure, or lock contention), THEN THE Billing_State_Machine SHALL return HTTP 500 to trigger Stripe's automatic retry, and IF the error is permanent (invalid payload structure, unknown client mapping, or business rule violation), THEN THE Billing_State_Machine SHALL log the error, return HTTP 200, and emit an operator alert
9. THE Billing_State_Machine SHALL log every webhook event (event_id, event_type, client_id, timestamp, processing_result) in a dedicated webhook_events table for audit and debugging
10. IF a webhook event arrives with a Stripe API timestamp older than the most recently processed event of the same type for the same subscription, THEN THE Billing_State_Machine SHALL skip processing to prevent out-of-order state corruption and log the skip reason
11. IF a webhook event of an unrecognized type is received, THEN THE Billing_State_Machine SHALL log the event in the webhook_events table with processing_result indicating the type is unhandled and return HTTP 200

### Requirement 8: Plan Limits Definition (Source of Truth)

**User Story:** As a platform operator, I want plan limits defined in a single authoritative location, so that enforcement, UI, and billing all reference the same values.

#### Acceptance Criteria

1. THE Billing_State_Machine SHALL define plan limits in a database table (plan_definitions) rather than hardcoded constants, allowing runtime modification without deploy
2. WHEN the system starts, THE Billing_State_Machine SHALL validate that all 6 plan tiers (trial, seed, starter, growth, scale, agency) have a non-null value for each of the 8 limit fields defined in criterion 7
3. IF startup validation detects a plan tier with one or more missing limit definitions, THEN THE Billing_State_Machine SHALL refuse to start and log an error message indicating which plan tier and which fields are incomplete
4. THE Plan_Enforcer SHALL read limits exclusively from plan_definitions (or Per_Client_Override when set), never from hardcoded constants in service code
5. WHEN an operator modifies plan_definitions, THE Billing_State_Machine SHALL apply new limits to all clients on that plan at the start of their next billing period (not mid-period), and for trial clients (which have no Stripe billing period) SHALL apply new limits immediately
6. IF an operator attempts to delete a plan_definitions row while one or more active clients are assigned to that plan tier, THEN THE Billing_State_Machine SHALL reject the deletion and return an error message indicating the number of active clients on that plan
7. THE Billing_State_Machine SHALL define the following limits per plan: max_actions_per_month, max_avatars, max_subreddits, max_professional_subreddits, max_posts_per_month (Post_Sub_Limit), max_keywords, geo_monitoring_enabled, geo_prompts_limit
8. THE Billing_State_Machine SHALL support Per_Client_Override: admin can set explicit values on individual clients (e.g., custom deals, enterprise arrangements) that take precedence over plan_definitions for that client only. Override fields are stored on the client record itself (existing pattern: `client.max_comments_per_month`, `client.max_avatars`).

### Requirement 9: Billing State Machine Testability

**User Story:** As a developer, I want the billing state machine to be deterministic and property-testable, so that complex state transitions can be verified without end-to-end Stripe integration.

#### Acceptance Criteria

1. THE Billing_State_Machine SHALL separate state transition logic from Stripe API calls, so that all transitions can be invoked programmatically with mock events without network dependencies
2. THE Billing_State_Machine SHALL maintain a complete audit log of all state transitions (from_state, to_state, trigger_event, event_id, timestamp, client_id, actor) enabling full replay of any client's billing history
3. WHEN a valid event is processed by the Billing_State_Machine and the same event (identified by event_id) is submitted again, THE Billing_State_Machine SHALL produce the same final state and not create a duplicate audit log entry
4. WHEN a state transition modifies client plan_type or subscription_status, THE Billing_State_Machine SHALL emit an activity event that includes the previous value, new value, trigger_event, and event_id
5. THE Billing_State_Machine SHALL enforce that only valid transitions are possible: trial→active, active→past_due, past_due→active, past_due→suspended, suspended→active, active→canceled, any→archived
6. IF an event would trigger an invalid state transition, THEN THE Billing_State_Machine SHALL reject the event, log the rejection with the attempted from_state, to_state, and event_id, and leave the client state unchanged

### Requirement 10: SBM Property Preservation During Billing Operations

**User Story:** As a platform architect, I want billing enforcement to respect existing system behavior model properties, so that billing changes never violate safety invariants.

#### Acceptance Criteria

1. WHILE the Plan_Enforcer blocks new EPG generation due to plan limit, THE Plan_Enforcer SHALL NOT interfere with scheduled health checks (shadowban/suspension detection at 07:30 and 13:30), karma tracking (every 4 hours), CQS monitoring (daily at 06:30), or comment outcome snapshots (every 4 hours) for the client's avatars
2. WHILE a client is in grace period or suspended due to non-payment, THE Plan_Enforcer SHALL preserve each avatar's current warming_phase value and activation_zone value unchanged — avatars receive no new EPG slots but their phase and zone state are not demoted or reset
3. WHEN service is restored after grace period or suspension ends, THE Plan_Enforcer SHALL resume EPG generation for all previously active avatars using their preserved warming_phase and activation_zone values, with the first new EPG slots appearing no later than the next scheduled EPG build (08:15 or 14:15, whichever occurs first after restoration)
4. THE Plan_Enforcer SHALL enforce plan limits scoped to a single client_id — one client reaching 100% of their monthly action limit SHALL NOT reduce EPG slot generation, draft approval capacity, or pipeline execution for any other client_id
5. WHILE a client has reached 100% of their monthly action limit, THE Plan_Enforcer SHALL continue allowing the client's users to authenticate, view the client portal, access existing draft history, view avatar status, and read historical karma and activity data without modification

### Requirement 11: Agency Tier and Custom Deals

**User Story:** As a platform operator, I want agency clients and custom enterprise deals to operate without standard plan constraints while maintaining billing transparency, so that high-value clients are never blocked by self-serve plan limits.

#### Acceptance Criteria

1. THE Billing_State_Machine SHALL support a 6th plan tier `agency` with limits significantly higher than Scale (max_avatars=999, max_actions_per_month=9999, max_subreddits=999), representing effectively unlimited usage within system safety bounds
2. WHEN a client is on the `agency` tier, THE Plan_Enforcer SHALL still track Monthly_Action_Counter for cost visibility and reporting, but SHALL NOT block pipeline generation when counter reaches max_actions_per_month (soft enforcement: alert operator at 80%, never hard-block)
3. WHEN an admin sets a Per_Client_Override on a client (e.g., custom max_avatars=5 on a Seed plan), THE Plan_Enforcer SHALL use the override value for that limit and the plan_definitions value for all other limits
4. WHEN a client with Per_Client_Override upgrades or downgrades their plan, THE Plan_Transition_Manager SHALL clear all Per_Client_Overrides and apply the new plan's standard limits, UNLESS the admin explicitly marks the override as `persistent` (survives plan changes)
5. THE Billing_State_Machine SHALL support `agency` clients with annual billing (not monthly) — Stripe subscription with `interval=year`. Billing period resets annually. Monthly_Action_Counter still resets per Stripe billing period.
6. WHEN an agency client's subscription is managed externally (invoice-based, not card), THE Grace_Period_Manager SHALL extend the grace period to 14 days (vs 7 for self-serve) before suspension

### Requirement 12: Downgrade Initiation and Stripe Proration

**User Story:** As a platform operator, I want clear rules for how downgrades are initiated and what happens financially, so that there is no ambiguity about billing treatment.

#### Acceptance Criteria

1. A downgrade MAY be initiated via: (a) client self-serve through Stripe Customer Portal, (b) admin action in RAMP admin panel, or (c) Stripe `customer.subscription.updated` webhook (from external Stripe Dashboard action)
2. WHEN a downgrade is initiated via Stripe Customer Portal or Stripe Dashboard, THE Billing_State_Machine SHALL detect the plan change via `customer.subscription.updated` webhook and trigger the downgrade flow (Req 4) automatically
3. WHEN a downgrade is initiated via RAMP admin panel, THE Plan_Transition_Manager SHALL update the Stripe subscription via Stripe API (`subscription.update(proration_behavior='none', ...)`) to take effect at period end, then trigger the downgrade flow (Req 4)
4. THE Billing_State_Machine SHALL use Stripe's `proration_behavior='none'` for downgrades — client pays the full current period at the old rate, new (lower) rate starts at next period. No mid-period credits or refunds.
5. THE Billing_State_Machine SHALL use Stripe's `proration_behavior='always_invoice'` for upgrades — client is immediately charged the prorated difference for the remainder of the current period at the new rate
6. WHEN a client cancels their subscription (not downgrade, full cancel), THE Billing_State_Machine SHALL allow service to continue until `current_period_end` (already paid), then trigger suspension flow. No refund for remaining days.
