---
inclusion: fileMatch
fileMatchPattern: "**/billing/**,**/subscription_manager*,**/access_gate*,**/webhooks*,**/billing*"
---

# Stripe Billing Integration — Operational Reference

## Status: DEPLOYED (code complete, pending production deploy)

## Architecture

```
Onboarding Step 6 → Stripe Checkout (14-day trial + card)
    ↓ (webhook: checkout.session.completed)
subscription_status = "trialing"
    ↓ (14 days later, webhook: customer.subscription.updated status=active)
subscription_status = "active" → pipeline runs
    ↓ (payment fails → webhook: invoice.payment_failed)
subscription_status = "past_due" → pipeline blocked, 30-day grace for portal
    ↓ (3 retries fail → webhook: customer.subscription.deleted)
subscription_status = "canceled" → is_active=false
```

## Keys (DB system_settings, group: billing)

| Setting | Description |
|---------|-------------|
| stripe_secret_key | rk_live_ restricted key (full API access) |
| stripe_webhook_secret | whsec_ signing secret for webhook verification |
| stripe_publishable_key | pk_live_ for client-side Checkout |
| stripe_price_id_seed | Stripe Price ID for Seed $149/mo |
| stripe_price_id_starter | Stripe Price ID for Starter $399/mo |
| stripe_price_id_growth | Stripe Price ID for Growth $799/mo |
| stripe_price_id_scale | Stripe Price ID for Scale $1,499/mo |

## Webhook Endpoint

- URL: `https://gorampit.com/api/webhooks/stripe`
- Route: `app/routes/webhooks.py`
- Auth: None (public, verified by Stripe signature)
- Processing: immediate 200 → Celery async `process_billing_event`
- Idempotency: `billing_events.stripe_event_id` unique constraint

## Access Gate (replaces trial_guard.py)

| Status | Pipeline | Portal | Notes |
|--------|----------|--------|-------|
| active | ✅ | ✅ | Paying customer |
| trialing | ✅ | ✅ | Stripe trial (card on file) |
| trial | ✅* | ✅ | Legacy trial (*until 14 days expire) |
| past_due | ❌ | 📖 read-only 30d | Payment failed |
| canceled | ❌ | 📖 read-only 30d | Subscription ended |
| trial_expired | ❌ | 📖 read-only 30d | Legacy trial, no card |

## Coupon System

- Create: `/admin/billing/coupons` or `BillingService.create_coupon()`
- Apply: passed to `create_checkout_session(coupon_id=...)`
- Stripe handles duration + auto-transition to full price
- ZoomREI coupon: GBL27Qgm (70% off, 3 months)

## Key Files

| File | Purpose |
|------|---------|
| `app/services/billing/billing_service.py` | Stripe API (checkout, portal, products, invoices, coupons) |
| `app/services/subscription_manager.py` | Webhook event → local state sync |
| `app/services/access_gate.py` | Pipeline gating by subscription_status |
| `app/routes/webhooks.py` | POST /api/webhooks/stripe |
| `app/tasks/billing.py` | Async event processing + product sync |
| `app/models/billing_event.py` | Webhook audit log |
| `app/models/client_invoice.py` | Cached invoices |
| `app/models/billing_coupon.py` | Coupon tracking |
| `app/templates/client/billing.html` | Portal billing page |
| `app/templates/admin_billing_coupons.html` | Admin coupon management |

## Stripe Dashboard Config

- Account: RAMP (Tzvi's account)
- Mode: Live
- Webhook: https://gorampit.com/api/webhooks/stripe (8 events)
- Products: 4 (RAMP Seed/Starter/Growth/Scale Plan)
- Customer Portal: needs to be enabled in Stripe Settings → Billing → Customer Portal

## Deploy Checklist

1. Push code to staging → verify billing page loads
2. Run migration: `alembic upgrade head` (stripe01)
3. Verify system_settings has stripe keys (seed_from_env or manual)
4. Verify /health returns OK
5. Test: POST /api/webhooks/stripe → 400 "Missing stripe-signature header"
6. Push to production
7. Verify Stripe webhook endpoint receives events (Stripe Dashboard → webhook → recent deliveries)
