# Requirements Document

## Introduction

The Customer Pilot Configuration System enables RAMP operators to create structured, repeatable pilot programs for design partners. Each pilot defines the specific parameters a partner receives (number of avatars, comment limits, subreddit scope, duration, discount, and feature access) as a template that can be applied during client onboarding. This bridges the gap between ad-hoc manual configuration (current state) and the eventual self-service SaaS subscription flow (ZoomREI → Design Partner Pilot → Stripe → Repeatable SaaS onboarding).

## Glossary

- **Pilot_Configuration**: A named template defining the parameters for a design partner pilot program (avatar count, limits, subreddits, duration, discount, features).
- **Design_Partner**: A client participating in a pilot program before becoming a paying subscriber.
- **Pilot_Instance**: An active pilot assigned to a specific client, created from a Pilot_Configuration template with a defined start and end date.
- **Available_Features**: The set of platform capabilities enabled for a pilot (GEO monitoring, discovery engine, EPG portfolio, visibility reports, etc.).
- **Admin_Panel**: The operator-facing administrative interface at `/admin/*`.
- **Pilot_System**: The collection of services and models that manage pilot configuration, instantiation, and lifecycle.
- **Comment_Limit**: The maximum number of comments per month allocated to a pilot instance.
- **Subreddit_List**: A curated set of subreddits assigned to a pilot, overriding the client's default subreddit configuration.
- **Pilot_Duration**: The number of days a pilot program runs before expiration.
- **Pilot_Discount**: A percentage or fixed discount applied to the transition price when a pilot converts to a paid subscription.

## Requirements

### Requirement 1: Create Pilot Configuration Template

**User Story:** As an operator, I want to create named pilot configuration templates, so that I can repeatedly apply the same pilot setup to multiple design partners without manual reconfiguration.

#### Acceptance Criteria

1. WHEN an operator submits a new pilot configuration via the Admin_Panel, THE Pilot_System SHALL create a Pilot_Configuration record with: name (string, 1-100 characters), max_avatars (integer, 1-50), comment_limit_monthly (integer, 1-2000), subreddit_list (array of subreddit names, 1-50 entries), duration_days (integer, 7-365), discount_percent (integer, 0-100), and available_features (array of feature keys, 0-20 entries).
2. THE Pilot_System SHALL validate that max_avatars is between 1 and 50 inclusive.
3. THE Pilot_System SHALL validate that comment_limit_monthly is between 1 and 2000 inclusive.
4. THE Pilot_System SHALL validate that duration_days is between 7 and 365 inclusive.
5. THE Pilot_System SHALL validate that discount_percent is between 0 and 100 inclusive.
6. THE Pilot_System SHALL validate that each feature key in available_features matches a known feature identifier from the feature registry.
7. THE Pilot_System SHALL validate that name is between 1 and 100 characters, subreddit_list contains between 1 and 50 entries, and available_features contains between 0 and 20 entries.
8. IF any validation fails (including a duplicate name), THEN THE Pilot_System SHALL return a descriptive error indicating which field failed and the constraint violated, without creating the record.
9. WHEN the Pilot_Configuration is successfully created, THE Pilot_System SHALL return the created record with its generated identifier and creation timestamp.

### Requirement 2: List and Edit Pilot Configurations

**User Story:** As an operator, I want to view all pilot configuration templates and edit them, so that I can manage and adjust pilot offerings over time.

#### Acceptance Criteria

1. WHEN an operator navigates to the pilot configurations page in the Admin_Panel, THE Pilot_System SHALL display all non-archived Pilot_Configuration records sorted by creation date descending, showing: name, max_avatars, comment_limit_monthly, duration_days, discount_percent, number of available_features, and count of active Pilot_Instances using each template.
2. WHEN an operator edits a Pilot_Configuration, THE Pilot_System SHALL apply the same validation rules as creation (Requirement 1 criteria 1-8).
3. WHEN a Pilot_Configuration is edited, THE Pilot_System SHALL NOT retroactively modify any existing Pilot_Instance already created from the template; existing instances retain the parameter values captured at creation time.
4. WHEN an operator archives a Pilot_Configuration, THE Pilot_System SHALL set the configuration's status to "archived", preventing new Pilot_Instance creation from the archived template while preserving all existing active instances.
5. THE Pilot_System SHALL allow operators to view archived configurations via a filter toggle, displaying them visually distinct from active configurations.

### Requirement 3: Apply Pilot Configuration to a Client

**User Story:** As an operator, I want to apply a pilot configuration template to a design partner client, so that the client receives the correct limits, subreddits, features, and duration without manual field-by-field setup.

#### Acceptance Criteria

1. WHEN an operator applies a Pilot_Configuration to a client, THE Pilot_System SHALL create a Pilot_Instance record linking the client_id, the source pilot_configuration_id, the start_date (defaulting to current date if not specified), and computed end_date (start_date + duration_days from the configuration).
2. THE Pilot_System SHALL execute the following changes atomically (all succeed or all roll back): set the client's max_avatars to the pilot's max_avatars value, set the client's max_comments_per_month to the pilot's comment_limit_monthly value, assign the pilot's subreddit_list to the client's subreddit assignments (replacing existing assignments), set the client's plan_type to "pilot", and store the available_features list on the Pilot_Instance record.
3. IF the client already has an active Pilot_Instance (status "active"), THEN THE Pilot_System SHALL reject the new assignment and return an error indicating the client already has an active pilot.
4. IF the Pilot_Configuration has status "archived", THEN THE Pilot_System SHALL reject the assignment and return an error indicating the configuration is archived.
5. IF the operator specifies a start_date, THE Pilot_System SHALL validate that the start_date is not in the past (before current date).
6. IF any step of the atomic operation fails, THEN THE Pilot_System SHALL roll back all changes and return an error describing the failure.

### Requirement 4: Feature Gating Based on Pilot Configuration

**User Story:** As an operator, I want pilot feature access to be enforced at runtime, so that design partners only access the features included in their specific pilot program.

#### Acceptance Criteria

1. WHILE a client has an active Pilot_Instance (status "active" and current date between start_date and end_date inclusive), THE Pilot_System SHALL hide portal navigation links for features not in the instance's available_features array AND block API endpoint access for those features with HTTP 403 response.
2. WHEN a feature-gated Celery task is invoked for a pilot client, THE Pilot_System SHALL check the client's active Pilot_Instance available_features and skip execution for features not listed, emitting an activity event "pilot_feature_blocked" with the feature key.
3. THE Pilot_System SHALL support the following feature keys: "geo_monitoring", "discovery_engine", "epg_portfolio", "visibility_reports", "risk_profiles", "voice_feedback", "autopilot".
4. IF a client has no active Pilot_Instance and plan_type is "pilot", THEN THE Pilot_System SHALL treat the client as having zero available features (expired pilot), blocking all gated endpoints and tasks.
5. IF a client's plan_type is NOT "pilot" (e.g., "seed", "starter", "growth", "scale"), THEN THE Pilot_System SHALL bypass pilot feature gating entirely and grant access to all features per the plan tier.

### Requirement 5: Pilot Lifecycle and Expiration

**User Story:** As an operator, I want pilots to have a defined duration that is automatically enforced, so that design partners transition to paid subscriptions or are deactivated after their pilot period ends.

#### Acceptance Criteria

1. THE Pilot_System SHALL check active Pilot_Instance expiration daily via a scheduled Celery task.
2. WHEN the scheduled expiration check runs and a Pilot_Instance has an end_date less than or equal to the current date, THE Pilot_System SHALL set the instance status to "expired".
3. WHEN a Pilot_Instance status is set to "expired", THE Pilot_System SHALL set the client's subscription_status to "pilot_expired".
4. WHEN a Pilot_Instance status is set to "expired", THE Pilot_System SHALL block pipeline execution for the client by preventing new scoring, generation, and EPG slot creation for that client while preserving existing posted content and historical data.
5. WHEN an operator manually extends a Pilot_Instance, THE Pilot_System SHALL validate that the new end_date is later than the current date, update the end_date, set the instance status to "active", restore the client's subscription_status to "active", and unblock pipeline execution for the client.
6. IF an operator submits an extension with a new end_date that is not later than the current date, THEN THE Pilot_System SHALL reject the extension and return an error indicating the new end_date must be in the future.
7. WHEN a Pilot_Instance status is set to "expired", THE Pilot_System SHALL emit an activity event "pilot_expired" for the client.
8. WHEN the scheduled expiration check runs and a Pilot_Instance has an end_date within 3 calendar days from the current date and no "pilot_expiring_soon" activity event has been emitted for that instance, THE Pilot_System SHALL emit a single activity event "pilot_expiring_soon" for the client.

### Requirement 6: Pilot-to-Subscription Conversion

**User Story:** As an operator, I want to convert a pilot client to a paid subscription, so that the design partner transitions smoothly into the SaaS billing model with the agreed discount applied.

#### Acceptance Criteria

1. WHEN an operator triggers pilot conversion for a client, THE Pilot_System SHALL validate that the client has a Pilot_Instance with status "active" or "expired", and record the conversion intent with the target plan_type (one of "seed", "starter", "growth", "scale") and the discount_percent from the Pilot_Instance.
2. WHEN pilot conversion is triggered and Stripe billing is configured (system setting `stripe_enabled` is "true"), THE Pilot_System SHALL create a Stripe Checkout session with the pilot's discount_percent applied as a percentage coupon, and redirect the operator to the Stripe-hosted payment page.
3. WHEN pilot conversion is triggered and Stripe billing is NOT configured, THE Pilot_System SHALL update the client's plan_type to the target plan, set subscription_status to "active", and update max_avatars and max_comments_per_month to match the target plan tier limits (manual billing path).
4. WHEN a pilot successfully converts (Stripe webhook confirms payment OR manual path completes), THE Pilot_System SHALL set the Pilot_Instance status to "converted" and record the conversion_date as the current timestamp.
5. WHEN a pilot successfully converts, THE Pilot_System SHALL update the client's max_avatars and max_comments_per_month to match the target plan tier limits, and unblock pipeline execution if the pilot was expired.
6. IF an operator triggers conversion for a client with no Pilot_Instance or a Pilot_Instance with status "converted", THEN THE Pilot_System SHALL reject the conversion and return an error indicating the pilot state is invalid for conversion.

### Requirement 7: Admin Dashboard Visibility

**User Story:** As an operator, I want to see all active pilots, their expiration dates, and conversion status at a glance, so that I can manage the design partner pipeline efficiently.

#### Acceptance Criteria

1. WHEN an operator views the pilot dashboard in the Admin_Panel, THE Pilot_System SHALL display all Pilot_Instance records grouped into four sections in this order: expiring_soon (active instances with 7 or fewer days remaining, sorted by end_date ascending), active (remaining active instances, sorted by end_date ascending), expired (instances with status "expired" that have not been converted, sorted by end_date descending), converted (instances with status "converted", sorted by conversion_date descending).
2. THE Pilot_System SHALL display for each instance: client name, pilot configuration name, start date, end date, days remaining (displayed as a non-negative integer for active and expiring_soon instances, omitted for expired and converted instances), avatar count (max_avatars), comment limit (comment_limit_monthly), and feature count (number of entries in available_features array).
3. WHEN a Pilot_Instance has 7 or fewer days remaining and status "active", THE Pilot_System SHALL display it with a visual "expiring soon" indicator (amber badge) distinct from the normal active state (green badge).
4. THE Pilot_System SHALL display a count summary showing: active pilots (status "active" with more than 7 days remaining), expiring soon (status "active" with 7 or fewer days remaining), expired pending conversion (status "expired"), and converted total (status "converted").

### Requirement 8: Audit Trail for Pilot Operations

**User Story:** As an operator, I want all pilot configuration and lifecycle changes to be logged, so that I can trace who configured what and when for any design partner.

#### Acceptance Criteria

1. WHEN a Pilot_Configuration is created, edited, or archived, THE Pilot_System SHALL create an audit log entry containing the operator's user_id, the action type (one of "created", "edited", "archived"), and a details JSONB field that includes the list of changed field names with their previous and new values.
2. WHEN a Pilot_Instance is created, extended, expired, or converted, THE Pilot_System SHALL create an audit log entry containing the operator's user_id, the action type (one of "created", "extended", "expired", "converted"), and a details JSONB field that includes the previous and new state values of the instance.
3. IF a lifecycle change is triggered by an automated process (e.g., scheduled expiration task) rather than a human operator, THEN THE Pilot_System SHALL record the audit log entry with user_id set to NULL and include a "triggered_by" key in the details JSONB indicating the automated source.
4. THE Pilot_System SHALL store audit entries using the existing AuditLog model with entity_type set to "pilot_configuration" or "pilot_instance", entity_id set to the identifier of the affected record, and client_id set to the associated design partner's client identifier.
5. IF the audit log entry fails to persist, THEN THE Pilot_System SHALL still complete the primary operation and log the audit failure as a warning.
