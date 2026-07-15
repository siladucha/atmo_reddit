"""Stripe integration service — checkout, webhook handling, subscription management.

Handles:
- Checkout session creation (trial → paid plan upgrade)
- Webhook event processing (delegates to BillingStateMachine)
- Subscription lifecycle (cancel, update payment method)

All state transitions go through BillingStateMachine — this service only
translates Stripe events into BillingEvent objects.

Kill switch: billing_enabled system setting. When false, checkout still works
(client can pay) but plan enforcement is bypassed.
"""

from __future__ import annotations

import stripe
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.client import Client
from app.models.client_subscription import ClientSubscription
from app.models.plan_definition import PlanDefinition
from app.models.webhook_event import WebhookEvent
from app.services.billing.state_machine import BillingStateMachine, BillingEvent, TransitionResult

logger = get_logger(__name__)


def get_stripe_keys(db: Session) -> tuple[str, str]:
    """Get Stripe secret key and webhook secret from system settings.

    Returns (stripe_secret_key, webhook_signing_secret).
    """
    from app.services.settings import get_setting

    secret_key = get_setting(db, "stripe_secret_key") or ""
    webhook_secret = get_setting(db, "stripe_webhook_secret") or ""
    return secret_key, webhook_secret


def configure_stripe(db: Session) -> None:
    """Configure stripe module with API key from DB settings."""
    secret_key, _ = get_stripe_keys(db)
    if not secret_key:
        raise ValueError("stripe_secret_key not configured in system settings")
    stripe.api_key = secret_key


# ---------------------------------------------------------------------------
# Checkout Session Creation
# ---------------------------------------------------------------------------


def create_checkout_session(
    db: Session,
    client_id: UUID,
    target_plan: str,
    success_url: str,
    cancel_url: str,
) -> str:
    """Create a Stripe Checkout Session for plan upgrade.

    Args:
        db: SQLAlchemy session
        client_id: Client UUID upgrading
        target_plan: Plan type to upgrade to (seed/starter/growth/scale)
        success_url: Redirect URL after successful payment
        cancel_url: Redirect URL if user cancels

    Returns:
        Stripe Checkout Session URL (redirect client here)

    Raises:
        ValueError: If plan not found or no stripe_price_id configured
    """
    configure_stripe(db)

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise ValueError(f"Client {client_id} not found")

    plan_def = (
        db.query(PlanDefinition)
        .filter(PlanDefinition.plan_type == target_plan)
        .first()
    )
    if not plan_def:
        raise ValueError(f"Plan '{target_plan}' not found in plan_definitions")
    if not plan_def.stripe_price_id:
        raise ValueError(f"Plan '{target_plan}' has no stripe_price_id configured")

    # Get or create Stripe customer
    subscription = (
        db.query(ClientSubscription)
        .filter(ClientSubscription.client_id == client_id)
        .first()
    )

    customer_id = subscription.stripe_customer_id if subscription else None

    if not customer_id:
        # Create Stripe customer
        customer = stripe.Customer.create(
            name=client.client_name,
            metadata={
                "ramp_client_id": str(client_id),
                "brand_name": client.brand_name or "",
            },
        )
        customer_id = customer.id

        # Store customer ID
        if subscription:
            subscription.stripe_customer_id = customer_id
            db.flush()

    # Create checkout session
    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": plan_def.stripe_price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "ramp_client_id": str(client_id),
            "target_plan": target_plan,
        },
        subscription_data={
            "metadata": {
                "ramp_client_id": str(client_id),
                "plan_type": target_plan,
            },
        },
        allow_promotion_codes=True,
    )

    logger.info(
        "STRIPE_CHECKOUT_CREATED | client_id=%s | plan=%s | session=%s",
        client_id, target_plan, session.id,
    )

    return session.url


# ---------------------------------------------------------------------------
# Webhook Event Processing
# ---------------------------------------------------------------------------


def verify_webhook_signature(payload: bytes, sig_header: str, webhook_secret: str) -> dict:
    """Verify Stripe webhook signature and return the event object.

    Raises:
        stripe.error.SignatureVerificationError: If signature is invalid
    """
    event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    return event


def handle_webhook_event(db: Session, event: dict) -> dict:
    """Process a verified Stripe webhook event.

    Routes to appropriate handler based on event type.
    Returns dict with processing result for logging.
    """
    event_type = event["type"]
    event_id = event["id"]
    event_ts = datetime.fromtimestamp(event["created"], tz=timezone.utc)

    logger.info("STRIPE_WEBHOOK | type=%s | id=%s", event_type, event_id)

    # Idempotency check (fast path)
    existing = (
        db.query(WebhookEvent)
        .filter(WebhookEvent.stripe_event_id == event_id)
        .first()
    )
    if existing:
        return {"status": "duplicate", "event_id": event_id}

    # Route to handler
    handlers = {
        "checkout.session.completed": _handle_checkout_completed,
        "invoice.paid": _handle_invoice_paid,
        "invoice.payment_failed": _handle_payment_failed,
        "customer.subscription.updated": _handle_subscription_updated,
        "customer.subscription.deleted": _handle_subscription_deleted,
    }

    handler = handlers.get(event_type)
    if not handler:
        # Log unhandled event type (but don't error)
        _log_webhook_event(db, event_id, event_type, None, event_ts, "skipped_unhandled", event)
        return {"status": "skipped_unhandled", "event_type": event_type}

    try:
        result = handler(db, event, event_id, event_ts)
        return result
    except Exception as e:
        logger.error(
            "STRIPE_WEBHOOK_ERROR | type=%s | id=%s | error=%s",
            event_type, event_id, str(e),
        )
        _log_webhook_event(db, event_id, event_type, None, event_ts, "error", event, str(e))
        raise


def _handle_checkout_completed(db: Session, event: dict, event_id: str, event_ts: datetime) -> dict:
    """Handle checkout.session.completed — trial → active transition.

    This fires when a client completes payment for the first time.
    """
    session = event["data"]["object"]
    metadata = session.get("metadata", {})
    client_id_str = metadata.get("ramp_client_id")
    target_plan = metadata.get("target_plan")
    stripe_customer_id = session.get("customer")
    stripe_subscription_id = session.get("subscription")

    if not client_id_str:
        _log_webhook_event(db, event_id, "checkout.session.completed", None, event_ts, "skipped_no_client_id", event)
        return {"status": "skipped", "reason": "no ramp_client_id in metadata"}

    client_id = UUID(client_id_str)

    # Update subscription record with Stripe IDs
    subscription = (
        db.query(ClientSubscription)
        .filter(ClientSubscription.client_id == client_id)
        .first()
    )
    if subscription:
        subscription.stripe_customer_id = stripe_customer_id
        subscription.stripe_subscription_id = stripe_subscription_id

    # Update client plan_type
    client = db.query(Client).filter(Client.id == client_id).first()
    if client and target_plan:
        client.plan_type = target_plan

    # Transition: trial → active (or trial_expired → active)
    fsm = BillingStateMachine()
    billing_event = BillingEvent(
        event_id=event_id,
        event_type="checkout_completed",
        stripe_timestamp=event_ts,
        payload={"target_plan": target_plan, "stripe_subscription_id": stripe_subscription_id},
    )
    result = fsm.transition(db, client_id, "active", billing_event)

    _log_webhook_event(db, event_id, "checkout.session.completed", client_id, event_ts, "processed", event)

    logger.info(
        "STRIPE_CHECKOUT_DONE | client_id=%s | plan=%s | subscription=%s | transition=%s→%s",
        client_id, target_plan, stripe_subscription_id, result.from_state, result.to_state,
    )

    return {"status": "processed", "client_id": str(client_id), "plan": target_plan, "transition": result}


def _handle_invoice_paid(db: Session, event: dict, event_id: str, event_ts: datetime) -> dict:
    """Handle invoice.paid — payment recovered or recurring renewal.

    If subscription was past_due → transitions to active.
    Also updates billing period dates.
    """
    invoice = event["data"]["object"]
    subscription_id = invoice.get("subscription")
    period_start = invoice.get("period_start")
    period_end = invoice.get("period_end")

    subscription = (
        db.query(ClientSubscription)
        .filter(ClientSubscription.stripe_subscription_id == subscription_id)
        .first()
    )
    if not subscription:
        _log_webhook_event(db, event_id, "invoice.paid", None, event_ts, "skipped_no_subscription", event)
        return {"status": "skipped", "reason": "subscription not found"}

    client_id = subscription.client_id

    # Update billing period
    if period_start:
        subscription.billing_period_start = datetime.fromtimestamp(period_start, tz=timezone.utc)
    if period_end:
        subscription.billing_period_end = datetime.fromtimestamp(period_end, tz=timezone.utc)

    # Reset counters on new period (period_start changed = new billing cycle)
    if period_start and subscription.billing_period_start:
        subscription.monthly_action_counter = 0
        subscription.monthly_post_counter = 0
        subscription.last_notified_threshold = 0

    # Also sync to Client denormalized fields
    client = db.query(Client).filter(Client.id == client_id).first()
    if client:
        client.billing_period_start = subscription.billing_period_start
        client.billing_period_end = subscription.billing_period_end

    # If past_due → active (payment recovered)
    if subscription.status == "past_due":
        fsm = BillingStateMachine()
        billing_event = BillingEvent(
            event_id=event_id,
            event_type="payment_recovered",
            stripe_timestamp=event_ts,
            payload={"invoice_id": invoice.get("id")},
        )
        result = fsm.transition(db, client_id, "active", billing_event)

        # Clear grace period
        subscription.grace_period_start = None
    else:
        result = None

    _log_webhook_event(db, event_id, "invoice.paid", client_id, event_ts, "processed", event)

    logger.info(
        "STRIPE_INVOICE_PAID | client_id=%s | subscription=%s | recovery=%s",
        client_id, subscription_id, result.to_state if result else "n/a (already active)",
    )

    return {"status": "processed", "client_id": str(client_id), "recovered": result is not None}


def _handle_payment_failed(db: Session, event: dict, event_id: str, event_ts: datetime) -> dict:
    """Handle invoice.payment_failed — active → past_due transition.

    Starts grace period. Client retains service for grace_period_days.
    """
    invoice = event["data"]["object"]
    subscription_id = invoice.get("subscription")

    subscription = (
        db.query(ClientSubscription)
        .filter(ClientSubscription.stripe_subscription_id == subscription_id)
        .first()
    )
    if not subscription:
        _log_webhook_event(db, event_id, "invoice.payment_failed", None, event_ts, "skipped_no_subscription", event)
        return {"status": "skipped", "reason": "subscription not found"}

    client_id = subscription.client_id

    # Only transition if currently active
    if subscription.status != "active":
        _log_webhook_event(db, event_id, "invoice.payment_failed", client_id, event_ts, "skipped_not_active", event)
        return {"status": "skipped", "reason": f"already {subscription.status}"}

    # Transition active → past_due
    fsm = BillingStateMachine()
    billing_event = BillingEvent(
        event_id=event_id,
        event_type="payment_failed",
        stripe_timestamp=event_ts,
        payload={"invoice_id": invoice.get("id"), "attempt_count": invoice.get("attempt_count", 1)},
    )
    result = fsm.transition(db, client_id, "past_due", billing_event)

    # Start grace period
    if result.success:
        from app.services.settings import get_setting

        # Check for repeat offender (previous grace within 60 days)
        grace_days = int(get_setting(db, "grace_period_default_days") or "7")
        if subscription.previous_grace_ended_at:
            days_since = (datetime.now(timezone.utc) - subscription.previous_grace_ended_at).days
            if days_since < 60:
                grace_days = int(get_setting(db, "grace_period_repeat_days") or "5")

        subscription.grace_period_start = datetime.now(timezone.utc)
        subscription.grace_period_days = grace_days

    _log_webhook_event(db, event_id, "invoice.payment_failed", client_id, event_ts, "processed", event)

    logger.info(
        "STRIPE_PAYMENT_FAILED | client_id=%s | subscription=%s | grace=%d days",
        client_id, subscription_id, subscription.grace_period_days if result.success else 0,
    )

    return {"status": "processed", "client_id": str(client_id), "grace_days": subscription.grace_period_days}


def _handle_subscription_updated(db: Session, event: dict, event_id: str, event_ts: datetime) -> dict:
    """Handle customer.subscription.updated — plan changes, cancellation scheduling.

    Covers: plan upgrades/downgrades initiated from Stripe portal,
    cancel_at_period_end toggled.
    """
    sub_data = event["data"]["object"]
    subscription_id = sub_data.get("id")
    cancel_at_period_end = sub_data.get("cancel_at_period_end", False)

    subscription = (
        db.query(ClientSubscription)
        .filter(ClientSubscription.stripe_subscription_id == subscription_id)
        .first()
    )
    if not subscription:
        _log_webhook_event(db, event_id, "customer.subscription.updated", None, event_ts, "skipped_no_subscription", event)
        return {"status": "skipped", "reason": "subscription not found"}

    client_id = subscription.client_id

    # Update cancel_at_period_end flag
    subscription.cancel_at_period_end = cancel_at_period_end

    # Check if plan changed (via Stripe-side upgrade)
    items = sub_data.get("items", {}).get("data", [])
    if items:
        price_id = items[0].get("price", {}).get("id")
        if price_id:
            # Look up plan by stripe_price_id
            plan_def = (
                db.query(PlanDefinition)
                .filter(PlanDefinition.stripe_price_id == price_id)
                .first()
            )
            if plan_def:
                client = db.query(Client).filter(Client.id == client_id).first()
                if client and client.plan_type != plan_def.plan_type:
                    logger.info(
                        "STRIPE_PLAN_CHANGE | client_id=%s | %s → %s",
                        client_id, client.plan_type, plan_def.plan_type,
                    )
                    client.plan_type = plan_def.plan_type

    _log_webhook_event(db, event_id, "customer.subscription.updated", client_id, event_ts, "processed", event)
    return {"status": "processed", "client_id": str(client_id)}


def _handle_subscription_deleted(db: Session, event: dict, event_id: str, event_ts: datetime) -> dict:
    """Handle customer.subscription.deleted — subscription fully canceled.

    Transitions active → canceled (will become archived at period end).
    """
    sub_data = event["data"]["object"]
    subscription_id = sub_data.get("id")

    subscription = (
        db.query(ClientSubscription)
        .filter(ClientSubscription.stripe_subscription_id == subscription_id)
        .first()
    )
    if not subscription:
        _log_webhook_event(db, event_id, "customer.subscription.deleted", None, event_ts, "skipped_no_subscription", event)
        return {"status": "skipped", "reason": "subscription not found"}

    client_id = subscription.client_id

    # Transition to canceled
    fsm = BillingStateMachine()
    billing_event = BillingEvent(
        event_id=event_id,
        event_type="subscription_deleted",
        stripe_timestamp=event_ts,
        payload={"subscription_id": subscription_id},
    )
    result = fsm.transition(db, client_id, "canceled", billing_event)

    _log_webhook_event(db, event_id, "customer.subscription.deleted", client_id, event_ts, "processed", event)

    logger.info(
        "STRIPE_SUBSCRIPTION_DELETED | client_id=%s | subscription=%s | %s→%s",
        client_id, subscription_id, result.from_state, result.to_state,
    )

    return {"status": "processed", "client_id": str(client_id)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log_webhook_event(
    db: Session,
    event_id: str,
    event_type: str,
    client_id: UUID | None,
    event_ts: datetime,
    result: str,
    event_data: dict,
    error: str | None = None,
) -> None:
    """Log webhook event to webhook_events table."""
    webhook_log = WebhookEvent(
        stripe_event_id=event_id,
        event_type=event_type,
        client_id=client_id,
        stripe_timestamp=event_ts,
        processing_result=result,
        error_detail=error,
        raw_payload=event_data if event_data else None,
    )
    db.add(webhook_log)
