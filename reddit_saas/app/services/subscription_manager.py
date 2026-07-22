"""Subscription Manager — handles Stripe webhook events and syncs
subscription state to local Client records.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 4.4, 8.1, 8.2, 8.4
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.client_invoice import ClientInvoice
from app.services.billing import PLAN_TIERS, PLAN_MAX_AVATARS
from app.services.settings import get_setting
from app.services.transparency import record_activity_event

logger = logging.getLogger(__name__)


class SubscriptionManager:
    """Processes Stripe webhook events and updates local subscription state."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_client_from_event(self, event_data: dict) -> Client | None:
        """Find Client by stripe_customer_id from webhook event data.

        Handles both top-level 'customer' field (checkout.session.completed)
        and nested 'object.customer' field (subscription/invoice events).
        """
        # Try top-level customer field first (checkout events)
        customer_id = event_data.get("customer")

        # For subscription/invoice events, data is nested in 'object'
        if not customer_id:
            obj = event_data.get("object", {})
            customer_id = obj.get("customer")

        if not customer_id:
            logger.warning("No customer ID found in event data")
            return None

        client = (
            self.db.query(Client)
            .filter(Client.stripe_customer_id == customer_id)
            .first()
        )

        if not client:
            logger.warning(
                "No client found for stripe_customer_id=%s", customer_id
            )

        return client

    def _map_plan_from_price(self, stripe_price_id: str) -> tuple[str, int]:
        """Map a Stripe Price ID to (plan_type, max_avatars).

        Looks up system_settings for stored price IDs:
            stripe_price_id_seed, stripe_price_id_starter, etc.

        Returns:
            Tuple of (plan_type, max_avatars). Defaults to ("starter", 3)
            if no mapping found.
        """
        for tier in PLAN_TIERS:
            setting_key = f"stripe_price_id_{tier}"
            stored_price_id = get_setting(self.db, setting_key)
            if stored_price_id and stored_price_id == stripe_price_id:
                return tier, PLAN_MAX_AVATARS[tier]

        logger.warning(
            "Unknown stripe_price_id=%s, defaulting to starter", stripe_price_id
        )
        return "starter", 3

    # ------------------------------------------------------------------
    # Webhook event handlers
    # ------------------------------------------------------------------

    def handle_subscription_updated(self, event_data: dict) -> None:
        """Handle customer.subscription.updated webhook.

        Maps Stripe status to local subscription_status:
            active → active, past_due → past_due, trialing → trialing

        Updates plan_type, billing_period_start/end, max_avatars.
        Emits activity events for status changes.
        """
        client = self._resolve_client_from_event(event_data)
        if not client:
            return

        subscription = event_data.get("object", event_data)
        stripe_status = subscription.get("status", "")

        # Map Stripe status to local status
        status_map = {
            "active": "active",
            "past_due": "past_due",
            "trialing": "trialing",
            "incomplete": "past_due",
            "incomplete_expired": "canceled",
            "canceled": "canceled",
            "unpaid": "past_due",
        }
        new_status = status_map.get(stripe_status)
        if not new_status:
            logger.warning(
                "Unknown Stripe subscription status: %s", stripe_status
            )
            return

        old_status = client.subscription_status

        # Update subscription status
        client.subscription_status = new_status

        # If transitioning to active, ensure is_active
        if new_status == "active":
            client.is_active = True

        # Update plan from price ID
        items = subscription.get("items", {})
        items_data = items.get("data", [])
        if items_data:
            price_obj = items_data[0].get("price", {})
            price_id = price_obj.get("id")
            if price_id:
                plan_type, max_avatars = self._map_plan_from_price(price_id)
                client.plan_type = plan_type
                client.max_avatars = max_avatars
                client.stripe_price_id = price_id

        # Update billing period
        period_start = subscription.get("current_period_start")
        period_end = subscription.get("current_period_end")
        if period_start:
            client.billing_period_start = datetime.fromtimestamp(
                period_start, tz=timezone.utc
            )
        if period_end:
            client.billing_period_end = datetime.fromtimestamp(
                period_end, tz=timezone.utc
            )

        self.db.commit()

        # Emit activity events for notable transitions
        if old_status != new_status:
            if new_status == "active" and old_status == "trialing":
                record_activity_event(
                    self.db,
                    event_type="billing",
                    message=f"Subscription activated for {client.brand_name} ({client.plan_type})",
                    client_id=client.id,
                    metadata={
                        "action": "subscription_activated",
                        "plan_type": client.plan_type,
                        "old_status": old_status,
                    },
                )
                # Send welcome email on trial-to-paid transition (Requirement 8.4)
                try:
                    from app.services.client_emails import send_trial_to_paid_welcome_email

                    # Get first invoice amount from subscription items
                    items = subscription.get("items", {})
                    items_data = items.get("data", [])
                    amount_cents = 0
                    if items_data:
                        price_obj = items_data[0].get("price", {})
                        amount_cents = price_obj.get("unit_amount", 0)

                    send_trial_to_paid_welcome_email(
                        client_id=client.id,
                        plan_type=client.plan_type,
                        amount_cents=amount_cents,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to send trial-to-paid welcome email for client=%s: %s",
                        client.id, e,
                    )
            elif new_status == "active" and old_status == "past_due":
                record_activity_event(
                    self.db,
                    event_type="billing",
                    message=f"Payment recovered for {client.brand_name}",
                    client_id=client.id,
                    metadata={
                        "action": "payment_recovered",
                        "plan_type": client.plan_type,
                    },
                )
            elif new_status == "past_due":
                record_activity_event(
                    self.db,
                    event_type="billing",
                    message=f"Payment past due for {client.brand_name}",
                    client_id=client.id,
                    metadata={"action": "payment_past_due"},
                )

        logger.info(
            "Subscription updated: client=%s, status=%s→%s, plan=%s",
            client.id,
            old_status,
            new_status,
            client.plan_type,
        )

    def handle_subscription_deleted(self, event_data: dict) -> None:
        """Handle customer.subscription.deleted webhook.

        Sets subscription_status=canceled, is_active=False,
        subscription_canceled_at=now. Emits subscription_canceled activity event.
        """
        client = self._resolve_client_from_event(event_data)
        if not client:
            return

        client.subscription_status = "canceled"
        client.is_active = False
        client.subscription_canceled_at = datetime.now(timezone.utc)

        self.db.commit()

        record_activity_event(
            self.db,
            event_type="billing",
            message=f"Subscription canceled for {client.brand_name}",
            client_id=client.id,
            metadata={"action": "subscription_canceled"},
        )

        logger.info("Subscription deleted: client=%s", client.id)

    def handle_invoice_paid(self, event_data: dict) -> None:
        """Handle invoice.paid webhook.

        If previously past_due, restores to active with is_active=True.
        Caches invoice data in client_invoices table.
        """
        client = self._resolve_client_from_event(event_data)
        if not client:
            return

        invoice = event_data.get("object", event_data)

        # If client was past_due, restore to active
        if client.subscription_status == "past_due":
            client.subscription_status = "active"
            client.is_active = True
            self.db.commit()

            record_activity_event(
                self.db,
                event_type="billing",
                message=f"Payment recovered for {client.brand_name} — subscription restored to active",
                client_id=client.id,
                metadata={"action": "payment_recovered_via_invoice"},
            )

        # Cache invoice data
        stripe_invoice_id = invoice.get("id")
        if stripe_invoice_id:
            # Check if invoice already cached (idempotency)
            existing = (
                self.db.query(ClientInvoice)
                .filter(ClientInvoice.stripe_invoice_id == stripe_invoice_id)
                .first()
            )
            if not existing:
                period_start = invoice.get("period_start")
                period_end = invoice.get("period_end")

                new_invoice = ClientInvoice(
                    client_id=client.id,
                    stripe_invoice_id=stripe_invoice_id,
                    amount_cents=invoice.get("amount_due", 0),
                    currency=invoice.get("currency", "usd"),
                    status="paid",
                    period_start=datetime.fromtimestamp(
                        period_start, tz=timezone.utc
                    ) if period_start else datetime.now(timezone.utc),
                    period_end=datetime.fromtimestamp(
                        period_end, tz=timezone.utc
                    ) if period_end else datetime.now(timezone.utc),
                    invoice_pdf_url=invoice.get("invoice_pdf"),
                    hosted_invoice_url=invoice.get("hosted_invoice_url"),
                )
                self.db.add(new_invoice)
                self.db.commit()

        logger.info("Invoice paid: client=%s, invoice=%s", client.id, stripe_invoice_id)

    def handle_invoice_payment_failed(self, event_data: dict) -> None:
        """Handle invoice.payment_failed webhook.

        Sets subscription_status=past_due. Sends payment failure notification
        email to client admin.
        """
        client = self._resolve_client_from_event(event_data)
        if not client:
            return

        client.subscription_status = "past_due"
        self.db.commit()

        record_activity_event(
            self.db,
            event_type="billing",
            message=f"Invoice payment failed for {client.brand_name}",
            client_id=client.id,
            metadata={"action": "invoice_payment_failed"},
        )

        # Send payment failure notification email
        logger.info(
            "TODO: send payment failure email to client admin for client=%s",
            client.id,
        )

        logger.info("Invoice payment failed: client=%s", client.id)

    def handle_trial_will_end(self, event_data: dict) -> None:
        """Handle customer.subscription.trial_will_end webhook.

        Sends notification email to client admin warning billing will begin.
        Emits trial_ending_soon activity event.
        """
        client = self._resolve_client_from_event(event_data)
        if not client:
            return

        subscription = event_data.get("object", event_data)
        trial_end = subscription.get("trial_end")
        trial_end_dt = (
            datetime.fromtimestamp(trial_end, tz=timezone.utc)
            if trial_end
            else None
        )

        record_activity_event(
            self.db,
            event_type="billing",
            message=f"Trial ending soon for {client.brand_name}",
            client_id=client.id,
            metadata={
                "action": "trial_ending_soon",
                "trial_end": trial_end_dt.isoformat() if trial_end_dt else None,
            },
        )

        # Send trial ending notification email
        logger.info(
            "TODO: send trial ending notification email to client admin for client=%s, trial_end=%s",
            client.id,
            trial_end_dt,
        )

        logger.info(
            "Trial will end: client=%s, trial_end=%s", client.id, trial_end_dt
        )

    def handle_checkout_completed(self, event_data: dict) -> None:
        """Handle checkout.session.completed webhook.

        Stores stripe_customer_id, stripe_subscription_id on Client.
        Sets subscription_status=trialing.
        """
        session = event_data.get("object", event_data)

        # Get customer and subscription IDs from session
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")

        if not customer_id:
            logger.warning("checkout.session.completed missing customer ID")
            return

        # Find client — try metadata first (client_id passed during checkout creation)
        metadata = session.get("metadata", {})
        client_id_str = metadata.get("client_id")

        client = None
        if client_id_str:
            from uuid import UUID
            try:
                client = (
                    self.db.query(Client)
                    .filter(Client.id == UUID(client_id_str))
                    .first()
                )
            except (ValueError, TypeError):
                pass

        # Fallback: resolve by customer ID if already linked
        if not client:
            client = (
                self.db.query(Client)
                .filter(Client.stripe_customer_id == customer_id)
                .first()
            )

        if not client:
            logger.warning(
                "checkout.session.completed: cannot resolve client. "
                "customer=%s, metadata=%s",
                customer_id,
                metadata,
            )
            return

        # Store Stripe identifiers
        client.stripe_customer_id = customer_id
        if subscription_id:
            client.stripe_subscription_id = subscription_id
        client.subscription_status = "trialing"

        self.db.commit()

        record_activity_event(
            self.db,
            event_type="billing",
            message=f"Checkout completed for {client.brand_name} — trial started",
            client_id=client.id,
            metadata={
                "action": "checkout_completed",
                "stripe_customer_id": customer_id,
                "stripe_subscription_id": subscription_id,
            },
        )

        logger.info(
            "Checkout completed: client=%s, customer=%s, subscription=%s",
            client.id,
            customer_id,
            subscription_id,
        )
