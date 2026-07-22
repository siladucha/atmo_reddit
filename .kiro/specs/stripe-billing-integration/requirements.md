# Requirements Document

## Introduction

Stripe Billing Integration enables RAMP to transition from an internal tool with $0 MRR to a self-service SaaS product with automated subscription billing. The integration covers the full customer lifecycle: trial signup → payment card collection → subscription activation → recurring billing → plan changes → cancellation. It connects Stripe as the single source of truth for billing state, syncing subscription status back to RAMP to gate platform access and pipeline execution.

## Glossary

- **Billing_Service**: The backend service responsible for communicating with the Stripe API, processing webhook events, and synchronizing subscription state to the RAMP database.
- **Subscription_Manager**: The component that manages subscription lifecycle transitions (trial → active → past_due → canceled) based on Stripe webhook events.
- **Checkout_Flow**: The user-facing flow that redirects a client to Stripe Checkout to collect payment method and activate a subscription.
- **Portal_Billing_Page**: The client-facing billing page at `/clients/{id}/billing` showing current plan, payment status, invoices, and self-service management links.
- **Webhook_Handler**: The endpoint receiving and processing Stripe webhook events with signature verification.
- **Plan_Tier**: One of the defined subscription tiers (Seed $149, Starter $399, Growth $799, Scale $1,499 per month).
- **Trial_Period**: A 14-day free access window during which the client uses the platform without payment. Payment method is collected at trial start via Stripe Checkout.
- **Access_Gate**: The mechanism that restricts platform features (pipeline, EPG, generation) based on subscription status.
- **Client**: The RAMP Client model representing a paying or trial customer organization.
- **Stripe_Customer**: The corresponding customer object in Stripe linked 1:1 to a RAMP Client.
- **Payment_Method**: A card or other payment instrument stored on the Stripe Customer for recurring charges.

## Requirements

### Requirement 1: Stripe Customer and Subscription Creation

**User Story:** As a new client completing the onboarding wizard, I want my payment details collected securely via Stripe so that my subscription begins automatically after the trial period ends.

#### Acceptance Criteria

1. WHEN a client completes onboarding step 6 (review and activate), THE Checkout_Flow SHALL create a Stripe_Customer linked to the Client record and redirect the user to a Stripe Checkout session configured with a 14-day trial period for the selected Plan_Tier.
2. WHEN the Stripe Checkout session completes successfully, THE Billing_Service SHALL store the `stripe_customer_id` and `stripe_subscription_id` on the Client record and set `subscription_status` to "trialing".
3. IF the Stripe Checkout session is abandoned or payment method is declined, THEN THE Billing_Service SHALL leave the Client in `subscription_status = "trial"` (legacy trial without payment method) and emit an activity event `checkout_abandoned`.
4. THE Billing_Service SHALL create Stripe Products and Prices for each Plan_Tier (Seed $149/mo, Starter $399/mo, Growth $799/mo, Scale $1,499/mo) during system initialization if they do not already exist.
5. WHEN a Stripe_Customer is created, THE Billing_Service SHALL store the client's `brand_name` as the Stripe customer name and the client admin's email as the Stripe customer email.

### Requirement 2: Subscription Lifecycle Management via Webhooks

**User Story:** As a platform operator, I want subscription state changes from Stripe to automatically update client access in RAMP so that I never manually manage billing status.

#### Acceptance Criteria

1. WHEN a `customer.subscription.updated` webhook is received with `status = "active"`, THE Subscription_Manager SHALL set the Client `subscription_status` to "active", update `plan_type` to match the Stripe Price metadata, and update `billing_period_start` and `billing_period_end` from the subscription period.
2. WHEN a `customer.subscription.updated` webhook is received with `status = "past_due"`, THE Subscription_Manager SHALL set the Client `subscription_status` to "past_due" and emit an activity event `payment_past_due`.
3. WHEN a `customer.subscription.deleted` webhook is received, THE Subscription_Manager SHALL set the Client `subscription_status` to "canceled", set `is_active` to false, and emit an activity event `subscription_canceled`.
4. WHEN a `customer.subscription.trial_will_end` webhook is received (3 days before trial end), THE Billing_Service SHALL send a notification to the client admin email warning that billing will begin and emit an activity event `trial_ending_soon`.
5. WHEN a `invoice.payment_failed` webhook is received, THE Subscription_Manager SHALL set the Client `subscription_status` to "past_due" and send a notification to the client admin email with a link to update their payment method.
6. WHEN a `invoice.paid` webhook is received for a subscription that was `past_due`, THE Subscription_Manager SHALL set the Client `subscription_status` to "active" and restore `is_active` to true.
7. THE Webhook_Handler SHALL verify every incoming webhook request using the Stripe webhook signing secret and reject requests with invalid signatures by returning HTTP 400.
8. THE Webhook_Handler SHALL process webhook events idempotently by storing the Stripe event ID and skipping duplicate deliveries.

### Requirement 3: Access Gating Based on Subscription Status

**User Story:** As a platform operator, I want pipeline tasks and platform features to be automatically restricted when a client's subscription is not active so that unpaying clients do not consume AI resources.

#### Acceptance Criteria

1. WHILE a Client has `subscription_status` in ("past_due", "canceled", "trial_expired"), THE Access_Gate SHALL prevent pipeline execution (scoring, generation, EPG) for that Client.
2. WHILE a Client has `subscription_status = "trialing"`, THE Access_Gate SHALL allow full platform access identical to an active subscription for the duration of the trial period.
3. WHEN the trial period ends without a successful payment transition, THE Access_Gate SHALL set `subscription_status` to "trial_expired" and restrict pipeline execution.
4. WHILE a Client has `subscription_status = "past_due"`, THE Portal_Billing_Page SHALL display a banner indicating payment failure with a link to the Stripe Customer Portal to update payment method.
5. THE Access_Gate SHALL allow read-only portal access (viewing existing data, reports, drafts) for clients with `subscription_status` in ("past_due", "canceled") for 30 days after status change.

### Requirement 4: Self-Service Plan Management

**User Story:** As a client admin, I want to view my current plan, upgrade or downgrade my subscription, and manage my payment method without contacting support so that I have full control of my billing.

#### Acceptance Criteria

1. THE Portal_Billing_Page SHALL display the current Plan_Tier name, monthly price, next billing date, and subscription status.
2. WHEN a client admin clicks "Manage Subscription", THE Portal_Billing_Page SHALL redirect to a Stripe Customer Portal session where the client can update payment method, view invoices, and cancel subscription.
3. WHEN a client admin clicks "Change Plan", THE Checkout_Flow SHALL present available Plan_Tiers and create a Stripe Checkout session configured to update the existing subscription to the selected tier with prorated billing.
4. WHEN a plan change is processed via Stripe, THE Subscription_Manager SHALL update the Client `plan_type` and `max_avatars` fields to match the new tier limits (Seed: 1, Starter: 3, Growth: 7, Scale: 15).
5. WHEN a client admin clicks "View Invoices", THE Portal_Billing_Page SHALL display the 12 most recent invoices with date, amount, status, and a link to the Stripe-hosted invoice PDF.

### Requirement 5: Pilot and Discounted Plan Support

**User Story:** As a business operator, I want to offer discounted pilot pricing to early design partners so that I can validate the product with real customers before full pricing.

#### Acceptance Criteria

1. WHERE a pilot discount is configured, THE Billing_Service SHALL apply a Stripe Coupon to the subscription at creation time reducing the monthly price by the specified percentage or fixed amount.
2. WHEN a pilot subscription reaches its configured duration (defined as coupon `duration_in_months`), THE Subscription_Manager SHALL allow Stripe to automatically transition billing to the standard Plan_Tier price without manual intervention.
3. THE Billing_Service SHALL support creating time-limited coupons via admin UI with parameters: discount percentage (10-100%), duration in months (1-12), and maximum redemption count.
4. WHEN an admin creates a coupon, THE Billing_Service SHALL create a corresponding Stripe Coupon object and store the coupon code in the RAMP database for tracking.

### Requirement 6: Webhook Endpoint Security and Reliability

**User Story:** As a platform engineer, I want the webhook endpoint to be secure, idempotent, and resilient to delivery failures so that billing state is never corrupted.

#### Acceptance Criteria

1. THE Webhook_Handler SHALL expose a public endpoint at `/api/webhooks/stripe` that accepts POST requests with `Content-Type: application/json`.
2. THE Webhook_Handler SHALL return HTTP 200 within 5 seconds of receiving a webhook to prevent Stripe retry escalation.
3. IF webhook processing requires more than 5 seconds (database operations, notifications), THEN THE Webhook_Handler SHALL enqueue the event to a Celery task for async processing and return HTTP 200 immediately.
4. THE Webhook_Handler SHALL log every received webhook event (event type, event ID, timestamp, processing result) to an audit table for debugging and reconciliation.
5. IF the Webhook_Handler encounters a transient error during processing, THEN THE Webhook_Handler SHALL rely on Stripe automatic retry delivery (up to 3 days) by returning HTTP 500.
6. THE Webhook_Handler SHALL ignore webhook event types that are not explicitly handled and return HTTP 200 for unhandled types.

### Requirement 7: Admin Billing Visibility

**User Story:** As a platform operator, I want to see billing status for all clients in the admin panel so that I can monitor revenue and identify payment issues.

#### Acceptance Criteria

1. THE Admin_Panel SHALL display `subscription_status` as a color-coded badge on the client list page (green=active, blue=trialing, amber=past_due, red=canceled, gray=trial_expired).
2. THE Admin_Panel SHALL display current MRR (Monthly Recurring Revenue) calculated from all active and trialing subscriptions on the admin dashboard.
3. WHEN an admin views a client detail page, THE Admin_Panel SHALL display: Stripe Customer link, current plan, subscription status, next billing date, payment method last 4 digits, and recent invoice history.
4. THE Admin_Panel SHALL provide a "Sync from Stripe" button per client that fetches the latest subscription state from Stripe API and updates the local database.

### Requirement 8: Trial-to-Paid Transition

**User Story:** As a trial client with a payment method on file, I want my subscription to activate seamlessly after the trial ends so that there is no interruption to my service.

#### Acceptance Criteria

1. WHEN the 14-day trial period ends and a valid payment method exists on the Stripe_Customer, THE Subscription_Manager SHALL allow Stripe to charge the first invoice automatically and transition `subscription_status` from "trialing" to "active".
2. IF the first charge after trial fails, THEN THE Subscription_Manager SHALL set `subscription_status` to "past_due" and send a payment failure notification to the client admin.
3. WHEN a trial client has NOT provided a payment method (legacy trial without Stripe Checkout), THE Access_Gate SHALL set `subscription_status` to "trial_expired" after 14 days and restrict pipeline execution.
4. THE Billing_Service SHALL send a welcome email to the client admin upon successful trial-to-paid transition confirming plan activation and first charge amount.

### Requirement 9: Database Schema for Billing State

**User Story:** As a platform engineer, I want billing state stored in well-structured database tables so that subscription queries are fast and billing history is preserved.

#### Acceptance Criteria

1. THE Billing_Service SHALL store Stripe identifiers on the Client model: `stripe_customer_id` (String, unique, nullable), `stripe_subscription_id` (String, unique, nullable), and `stripe_price_id` (String, nullable).
2. THE Billing_Service SHALL maintain a `billing_events` table logging every webhook event with columns: id, stripe_event_id (unique), event_type, client_id (FK), payload (JSONB), processed_at, processing_status.
3. THE Billing_Service SHALL maintain a `client_invoices` table caching recent invoice data with columns: id, client_id (FK), stripe_invoice_id (unique), amount_cents, currency, status, period_start, period_end, invoice_pdf_url, created_at.
4. THE Billing_Service SHALL create an Alembic migration for all new billing columns and tables that is additive (no destructive changes to existing schema).

### Requirement 10: Configuration and Environment Setup

**User Story:** As a platform engineer, I want Stripe API keys and webhook secrets managed via environment variables so that secrets are never committed to source code.

#### Acceptance Criteria

1. THE Billing_Service SHALL read `STRIPE_SECRET_KEY` from environment variables for all Stripe API calls.
2. THE Billing_Service SHALL read `STRIPE_WEBHOOK_SECRET` from environment variables for webhook signature verification.
3. THE Billing_Service SHALL read `STRIPE_PUBLISHABLE_KEY` from environment variables for client-side Checkout session creation.
4. IF any required Stripe environment variable is missing, THEN THE Billing_Service SHALL log a warning at startup and disable all billing functionality without crashing the application.
5. THE Billing_Service SHALL support both Stripe test mode and live mode keys determined by the key prefix (`sk_test_` vs `sk_live_`), with no code changes required to switch between modes.
