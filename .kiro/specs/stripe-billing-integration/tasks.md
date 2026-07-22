# Implementation Plan: Stripe Billing Integration

## Overview

This plan implements Stripe as the billing engine for RAMP, replacing the placeholder billing page and static `plan_type` field with a full subscription lifecycle. The implementation follows an event-driven architecture where Stripe is the source of truth and RAMP synchronizes state via webhooks.

The approach is incremental: database schema first, then core services, then webhook processing, then UI integration, and finally onboarding wiring.

## Tasks

- [x] 1. Database schema and configuration
  - [x] 1.1 Create Alembic migration for billing schema
    - Add 3 new columns to `clients` table: `stripe_customer_id` (String 255, unique, nullable), `stripe_subscription_id` (String 255, unique, nullable), `stripe_price_id` (String 255, nullable), `subscription_canceled_at` (DateTime with tz, nullable)
    - Create `billing_events` table with columns: id (UUID PK), stripe_event_id (String 255, unique), event_type (String 100), client_id (FK to clients, nullable), payload (JSONB), processing_status (String 20, default "pending"), processed_at (DateTime nullable), error_message (Text nullable), created_at (DateTime server_default now)
    - Create `client_invoices` table with columns: id (UUID PK), client_id (FK to clients), stripe_invoice_id (String 255, unique), amount_cents (Integer), currency (String 3, default "usd"), status (String 20), period_start (DateTime), period_end (DateTime), invoice_pdf_url (Text nullable), hosted_invoice_url (Text nullable), created_at (DateTime server_default now)
    - Create `billing_coupons` table with columns: id (UUID PK), stripe_coupon_id (String 255, unique), code (String 50, unique), name (String 255), percent_off (Integer nullable), amount_off_cents (Integer nullable), duration_in_months (Integer), max_redemptions (Integer nullable), times_redeemed (Integer default 0), is_active (Boolean default True), created_at (DateTime server_default now)
    - Add indexes: `ix_billing_events_client_created` (client_id, created_at), `ix_billing_events_type` (event_type), `ix_client_invoices_client_created` (client_id, created_at)
    - Migration must be additive only (no destructive changes)
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [x] 1.2 Create SQLAlchemy models for billing tables
    - Create `app/models/billing_event.py` with `BillingEvent` model matching migration schema
    - Create `app/models/client_invoice.py` with `ClientInvoice` model matching migration schema
    - Create `app/models/billing_coupon.py` with `BillingCoupon` model matching migration schema
    - Extend `app/models/client.py` with 4 new mapped columns (stripe_customer_id, stripe_subscription_id, stripe_price_id, subscription_canceled_at)
    - Register all new models in `app/models/__init__.py`
    - _Requirements: 9.1, 9.2, 9.3_

  - [x] 1.3 Implement Stripe configuration layer
    - Read `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PUBLISHABLE_KEY` from environment variables
    - Add configuration validation: if any required Stripe env var is missing, log a warning at startup and disable all billing functionality without crashing
    - Support both test mode (`sk_test_`) and live mode (`sk_live_`) keys without code changes
    - Add `stripe` to project dependencies in `pyproject.toml`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

- [x] 2. Core Billing Service
  - [x] 2.1 Implement BillingService class (`app/services/billing.py`)
    - Implement `__init__`, `_get_stripe_client()`, `is_configured()` methods
    - Implement `ensure_products_exist()` — create Stripe Products + Prices for each plan tier (Seed $149, Starter $399, Growth $799, Scale $1,499) if not already present; store price IDs in system_settings
    - Implement `create_checkout_session()` — create Stripe Customer (brand_name + admin email) if not exists, configure Checkout session with 14-day trial, apply optional coupon, return redirect URL
    - Implement `create_plan_change_session()` — create Checkout session for plan upgrade/downgrade with prorated billing
    - Implement `create_portal_session()` — create Stripe Customer Portal session for self-service management
    - Implement `get_recent_invoices()` — fetch last 12 invoices from Stripe API and cache locally in client_invoices table
    - Implement `sync_subscription_from_stripe()` — admin "Sync from Stripe" fetches latest subscription state and updates local DB
    - Implement `create_coupon()` — create Stripe Coupon with percent_off or amount_off, duration_in_months, max_redemptions; store locally in billing_coupons table
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 4.2, 4.3, 4.5, 5.1, 5.3, 5.4, 7.4_

  - [ ]* 2.2 Write property tests for BillingService
    - **Property 10: Graceful Degradation on Missing Configuration**
    - For any combination of missing Stripe environment variables, BillingService.is_configured() returns False and app starts without crashing
    - **Validates: Requirements 10.4**

- [x] 3. Subscription Manager
  - [x] 3.1 Implement SubscriptionManager class (`app/services/subscription_manager.py`)
    - Implement `_resolve_client_from_event()` — find Client by stripe_customer_id from webhook event data
    - Implement `_map_plan_from_price()` — map Stripe Price ID to (plan_type, max_avatars): Seed→(seed,1), Starter→(starter,3), Growth→(growth,7), Scale→(scale,15)
    - Implement `handle_subscription_updated()` — map Stripe status to local subscription_status (active→active, past_due→past_due, trialing→trialing); update plan_type, billing_period_start/end, max_avatars; emit activity events
    - Implement `handle_subscription_deleted()` — set subscription_status=canceled, is_active=False, subscription_canceled_at=now; emit subscription_canceled activity event
    - Implement `handle_invoice_paid()` — if previously past_due restore to active with is_active=True; cache invoice data in client_invoices
    - Implement `handle_invoice_payment_failed()` — set subscription_status=past_due; send payment failure notification email to client admin
    - Implement `handle_trial_will_end()` — send notification email to client admin warning billing will begin; emit trial_ending_soon activity event
    - Implement `handle_checkout_completed()` — store stripe_customer_id, stripe_subscription_id on Client; set subscription_status=trialing
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 4.4, 8.1, 8.2, 8.4_

  - [ ]* 3.2 Write property test for webhook status synchronization
    - **Property 1: Webhook Status Synchronization**
    - For any valid Stripe webhook event, the resulting local subscription_status correctly reflects the Stripe-side state: active→active, past_due→past_due, trialing→trialing, deleted→canceled with is_active=False, invoice.paid on past_due→active with is_active=True
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.5, 2.6, 8.1, 8.2**

  - [ ]* 3.3 Write property test for checkout state persistence
    - **Property 2: Checkout State Persistence**
    - For any valid checkout.session.completed event with customer ID and subscription ID, Client record has stripe_customer_id, stripe_subscription_id stored and subscription_status="trialing"
    - **Validates: Requirements 1.2**

  - [ ]* 3.4 Write property test for plan tier mapping
    - **Property 6: Plan Tier Mapping**
    - For any Stripe price_id mapping to a known plan tier, SubscriptionManager sets plan_type and max_avatars correctly: Seed→(seed,1), Starter→(starter,3), Growth→(growth,7), Scale→(scale,15)
    - **Validates: Requirements 4.4**

- [x] 4. Access Gate
  - [x] 4.1 Implement AccessGate class (`app/services/access_gate.py`)
    - Define PIPELINE_BLOCKED = {"past_due", "canceled", "trial_expired"}
    - Define FULL_ACCESS = {"active", "trialing"}
    - Define READ_ONLY_GRACE = {"past_due", "canceled"} with GRACE_PERIOD_DAYS = 30
    - Implement `can_execute_pipeline(client)` — returns True for active/trialing, False for past_due/canceled/trial_expired
    - Implement `can_access_portal(client)` — returns True for all except trial_expired past 30 days
    - Implement `is_read_only(client)` — returns True for past_due/canceled within 30-day grace period
    - Implement `check_trial_expiry(client)` — for legacy trials (no Stripe checkout), check 14-day expiry and set subscription_status=trial_expired if expired
    - Replace `trial_guard.py` usage in pipeline tasks with AccessGate.can_execute_pipeline()
    - _Requirements: 3.1, 3.2, 3.3, 3.5_

  - [ ]* 4.2 Write property test for access gate classification
    - **Property 3: Access Gate Classification**
    - For any Client with a given subscription_status, AccessGate classifies: full access for {"active", "trialing"}, pipeline-blocked for {"past_due", "canceled", "trial_expired"}, read-only portal for {"past_due", "canceled"} within 30 days of subscription_canceled_at
    - **Validates: Requirements 3.1, 3.2, 3.5**

- [x] 5. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Webhook Handler and Celery Tasks
  - [x] 6.1 Implement webhook endpoint (`app/routes/webhooks.py`)
    - Create `POST /api/webhooks/stripe` endpoint
    - Read raw body and verify Stripe signature using STRIPE_WEBHOOK_SECRET; return HTTP 400 for invalid signatures
    - Check idempotency: query billing_events by stripe_event_id, skip if already exists (return 200)
    - For handled event types, enqueue to Celery task `process_billing_event` and return HTTP 200 immediately
    - For unhandled event types, log to billing_events with status="skipped" and return HTTP 200
    - Log every received webhook event to billing_events audit table (event_type, event_id, timestamp, payload)
    - Ensure response is returned within 5 seconds (enqueue for async processing)
    - Return HTTP 500 on transient errors to trigger Stripe retry
    - Register router in `app/main.py`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 2.7, 2.8_

  - [x] 6.2 Implement billing Celery tasks (`app/tasks/billing.py`)
    - Create `process_billing_event` task with bind=True, max_retries=3, countdown=60×2^attempt
    - Route events to SubscriptionManager handlers by event_type: customer.subscription.updated, customer.subscription.deleted, customer.subscription.trial_will_end, invoice.paid, invoice.payment_failed, checkout.session.completed
    - Update billing_events.processing_status to "processed" on success, "failed" on error
    - Create `sync_stripe_products` task — calls BillingService.ensure_products_exist(); call at app startup via lifespan event
    - Add `app.tasks.billing` to worker.py includes
    - Add `sync-stripe-products` to beat_app.py (run once at startup or on demand)
    - _Requirements: 6.3, 1.4_

  - [ ]* 6.3 Write property tests for webhook handler
    - **Property 4: Webhook Signature Verification**
    - For any request with invalid Stripe-Signature header, endpoint returns HTTP 400 and does not modify database state
    - **Validates: Requirements 2.7**

  - [ ]* 6.4 Write property test for webhook idempotency
    - **Property 5: Webhook Idempotency**
    - Processing a Stripe event N times (N≥1) produces same final state as processing once; billing_events table contains exactly one record per unique stripe_event_id
    - **Validates: Requirements 2.8**

  - [ ]* 6.5 Write property test for webhook audit logging
    - **Property 7: Webhook Audit Logging**
    - For any webhook that passes signature verification, a record is created in billing_events with stripe_event_id, event_type, payload, and processing_status
    - **Validates: Requirements 6.4, 9.2**

  - [ ]* 6.6 Write property test for unhandled event pass-through
    - **Property 8: Unhandled Event Pass-Through**
    - For any event type not in the handled set, Webhook Handler returns HTTP 200 and does not modify Client, subscription, or invoice state
    - **Validates: Requirements 6.6**

- [x] 7. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Portal Billing Page
  - [x] 8.1 Implement portal billing route and template (`app/routes/portal.py` + `app/templates/client/billing.html`)
    - Add `GET /clients/{id}/billing` route to portal
    - Display current plan tier name, monthly price, next billing date, subscription status
    - Display "Manage Subscription" button → creates Stripe Customer Portal session and redirects
    - Display "Change Plan" button → presents available plan tiers and creates Stripe Checkout session for plan change with prorated billing
    - Display "View Invoices" section — show 12 most recent invoices with date, amount, status, and link to Stripe-hosted invoice PDF
    - Display payment failure banner with link to Stripe Customer Portal when subscription_status="past_due"
    - Handle case where billing is not configured (show "not configured" message)
    - _Requirements: 4.1, 4.2, 4.3, 4.5, 3.4_

  - [ ]* 8.2 Write property test for invoice cache consistency
    - **Property 11: Invoice Cache Consistency**
    - For any invoice.paid webhook event with invoice data, a ClientInvoice record is created with matching fields; no duplicate created if stripe_invoice_id already exists
    - **Validates: Requirements 9.3**

- [x] 9. Admin Billing Views
  - [x] 9.1 Implement admin billing visibility
    - Add subscription_status color-coded badge on client list page (green=active, blue=trialing, amber=past_due, red=canceled, gray=trial_expired)
    - Add MRR calculation on admin dashboard: sum of plan prices for all clients with subscription_status in {"active", "trialing"} using plan price mapping (seed=149, starter=399, growth=799, scale=1499)
    - Add client detail billing section: Stripe Customer link, current plan, subscription status, next billing date, payment method last 4 digits, recent invoice history
    - Add "Sync from Stripe" button per client that calls BillingService.sync_subscription_from_stripe()
    - Add coupon management UI: create coupon form (name, discount percentage 10-100%, duration 1-12 months, max redemptions), list existing coupons
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 5.3, 5.4_

  - [ ]* 9.2 Write property test for MRR computation
    - **Property 9: MRR Computation**
    - For any set of Client records, computed MRR equals sum of plan prices for clients with subscription_status in {"active", "trialing"}: seed=149, starter=399, growth=799, scale=1499
    - **Validates: Requirements 7.2**

- [x] 10. Onboarding Integration
  - [x] 10.1 Wire Stripe Checkout into onboarding step 6
    - Modify onboarding step 6 (review and activate) to redirect to Stripe Checkout session with 14-day trial for selected plan tier
    - On successful checkout completion (webhook), store stripe_customer_id and stripe_subscription_id, set subscription_status="trialing"
    - On abandoned/failed checkout, leave subscription_status="trial" (legacy trial) and emit checkout_abandoned activity event
    - Apply pilot coupon if configured for the client
    - _Requirements: 1.1, 1.2, 1.3, 5.1, 5.2_

- [x] 11. Trial-to-Paid Transition
  - [x] 11.1 Implement trial-to-paid transition handling
    - Handle automatic Stripe charge after 14-day trial via webhook (subscription.updated status=active)
    - Handle first charge failure via webhook (invoice.payment_failed) — set past_due, send notification
    - Handle legacy trials without payment method — check_trial_expiry sets trial_expired after 14 days
    - Send welcome email on successful trial-to-paid transition confirming plan activation and first charge amount
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 12. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- All Stripe API calls must be mocked in tests (no real Stripe calls in CI)
- `trial_guard.py` is superseded by `access_gate.py` — existing pipeline task references should be updated in task 4.1
- The webhook endpoint must be added to auth middleware whitelist (public endpoint, no JWT required)
- Add `stripe` package to `pyproject.toml` dependencies

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.3"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1", "4.1"] },
    { "id": 3, "tasks": ["2.2", "3.1", "4.2"] },
    { "id": 4, "tasks": ["3.2", "3.3", "3.4", "6.1"] },
    { "id": 5, "tasks": ["6.2", "6.3", "6.4", "6.5", "6.6"] },
    { "id": 6, "tasks": ["8.1", "9.1"] },
    { "id": 7, "tasks": ["8.2", "9.2", "10.1"] },
    { "id": 8, "tasks": ["11.1"] }
  ]
}
```
