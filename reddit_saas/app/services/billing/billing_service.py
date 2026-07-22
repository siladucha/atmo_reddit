"""Stripe Billing Service — manages Products, Prices, Checkout Sessions,
Customer Portal, Invoices, Coupons, and subscription synchronization.

Requirements: 1.1, 1.2, 1.4, 1.5, 4.2, 4.3, 4.5, 5.1, 5.3, 5.4, 7.4
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import stripe
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.settings import get_setting, set_setting
from app.models.billing_coupon import BillingCoupon
from app.models.client import Client
from app.models.client_invoice import ClientInvoice
from app.models.user import User

logger = logging.getLogger(__name__)

# Plan tier → price in cents (monthly)
PLAN_TIERS = {
    "seed": 14900,
    "starter": 39900,
    "growth": 79900,
    "scale": 149900,
}

# Plan tier → max_avatars
PLAN_MAX_AVATARS = {
    "seed": 1,
    "starter": 3,
    "growth": 7,
    "scale": 15,
}


@dataclass
class CheckoutResult:
    session_url: str
    session_id: str


@dataclass
class PortalResult:
    portal_url: str


class BillingService:
    """Central service for all Stripe billing operations."""

    def __init__(self, db: Session):
        self.db = db

    def _get_stripe_client(self):
        """Configure stripe with the secret key from DB system_settings."""
        secret_key = get_setting(self.db, "stripe_secret_key")
        if secret_key:
            stripe.api_key = secret_key
        return stripe

    def is_configured(self) -> bool:
        """Return True if Stripe is fully configured (all 3 keys present in DB)."""
        return all([
            get_setting(self.db, "stripe_secret_key"),
            get_setting(self.db, "stripe_webhook_secret"),
            get_setting(self.db, "stripe_publishable_key"),
        ])

    # ------------------------------------------------------------------
    # Product / Price management
    # ------------------------------------------------------------------

    def ensure_products_exist(self) -> None:
        """Create Stripe Products + Prices for each plan tier if not present.

        Stores the resulting price IDs in system_settings as:
            stripe_price_id_seed, stripe_price_id_starter, etc.
        """
        if not self.is_configured():
            logger.warning("Stripe not configured — skipping product creation")
            return

        client = self._get_stripe_client()

        for tier, amount_cents in PLAN_TIERS.items():
            setting_key = f"stripe_price_id_{tier}"
            existing_price_id = get_setting(self.db, setting_key)

            if existing_price_id:
                # Verify the price still exists in Stripe
                try:
                    client.Price.retrieve(existing_price_id)
                    logger.debug("Price for %s already exists: %s", tier, existing_price_id)
                    continue
                except stripe.error.InvalidRequestError:
                    logger.warning("Stored price %s for %s not found in Stripe — recreating", existing_price_id, tier)

            # Create product + price
            try:
                product = client.Product.create(
                    name=f"RAMP {tier.capitalize()} Plan",
                    metadata={"plan_tier": tier},
                )
                price = client.Price.create(
                    product=product.id,
                    unit_amount=amount_cents,
                    currency="usd",
                    recurring={"interval": "month"},
                    metadata={"plan_tier": tier},
                )
                set_setting(self.db, setting_key, price.id)
                logger.info("Created Stripe product+price for %s: %s", tier, price.id)
            except stripe.error.StripeError as e:
                logger.error("Failed to create Stripe product for %s: %s", tier, str(e))
                raise

    # ------------------------------------------------------------------
    # Checkout Sessions
    # ------------------------------------------------------------------

    def create_checkout_session(
        self,
        client_id: UUID,
        plan_tier: str,
        success_url: str,
        cancel_url: str,
        coupon_id: str | None = None,
    ) -> CheckoutResult:
        """Create a Stripe Checkout session with 14-day trial.

        Creates or reuses the Stripe Customer linked to the RAMP Client.
        """
        if not self.is_configured():
            raise RuntimeError("Stripe is not configured")

        client_obj = self.db.get(Client, client_id)
        if not client_obj:
            raise ValueError(f"Client {client_id} not found")

        stripe_client = self._get_stripe_client()

        # Get or create Stripe Customer
        stripe_customer_id = self._ensure_stripe_customer(client_obj, stripe_client)

        # Get price ID for the plan tier
        price_id = self._get_price_id(plan_tier)
        if not price_id:
            raise ValueError(f"No Stripe price configured for plan tier: {plan_tier}")

        # Build checkout session params
        session_params = {
            "customer": stripe_customer_id,
            "payment_method_types": ["card"],
            "line_items": [{"price": price_id, "quantity": 1}],
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "subscription_data": {
                "trial_period_days": 14,
                "metadata": {"client_id": str(client_id), "plan_tier": plan_tier},
            },
            "metadata": {"client_id": str(client_id), "plan_tier": plan_tier},
        }

        # Apply coupon if provided
        if coupon_id:
            session_params["discounts"] = [{"coupon": coupon_id}]

        try:
            session = stripe_client.checkout.Session.create(**session_params)
            return CheckoutResult(session_url=session.url, session_id=session.id)
        except stripe.error.StripeError as e:
            logger.error("Failed to create checkout session for client %s: %s", client_id, str(e))
            raise RuntimeError(f"Stripe checkout error: {e.user_message or str(e)}")

    def create_plan_change_session(
        self,
        client_id: UUID,
        new_plan_tier: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutResult:
        """Create a Checkout session for plan upgrade/downgrade with prorated billing."""
        if not self.is_configured():
            raise RuntimeError("Stripe is not configured")

        client_obj = self.db.get(Client, client_id)
        if not client_obj:
            raise ValueError(f"Client {client_id} not found")

        if not client_obj.stripe_customer_id:
            raise ValueError("Client has no Stripe customer — cannot change plan")

        stripe_client = self._get_stripe_client()

        price_id = self._get_price_id(new_plan_tier)
        if not price_id:
            raise ValueError(f"No Stripe price configured for plan tier: {new_plan_tier}")

        try:
            session = stripe_client.checkout.Session.create(
                customer=client_obj.stripe_customer_id,
                payment_method_types=["card"],
                line_items=[{"price": price_id, "quantity": 1}],
                mode="subscription",
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={"client_id": str(client_id), "plan_tier": new_plan_tier, "plan_change": "true"},
            )
            return CheckoutResult(session_url=session.url, session_id=session.id)
        except stripe.error.StripeError as e:
            logger.error("Failed to create plan change session for client %s: %s", client_id, str(e))
            raise RuntimeError(f"Stripe plan change error: {e.user_message or str(e)}")

    # ------------------------------------------------------------------
    # Customer Portal
    # ------------------------------------------------------------------

    def create_portal_session(self, client_id: UUID, return_url: str) -> PortalResult:
        """Create a Stripe Customer Portal session for self-service management."""
        if not self.is_configured():
            raise RuntimeError("Stripe is not configured")

        client_obj = self.db.get(Client, client_id)
        if not client_obj:
            raise ValueError(f"Client {client_id} not found")

        if not client_obj.stripe_customer_id:
            raise ValueError("Client has no Stripe customer — cannot open portal")

        stripe_client = self._get_stripe_client()

        try:
            session = stripe_client.billing_portal.Session.create(
                customer=client_obj.stripe_customer_id,
                return_url=return_url,
            )
            return PortalResult(portal_url=session.url)
        except stripe.error.StripeError as e:
            logger.error("Failed to create portal session for client %s: %s", client_id, str(e))
            raise RuntimeError(f"Stripe portal error: {e.user_message or str(e)}")

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------

    def get_recent_invoices(self, client_id: UUID, limit: int = 12) -> list[dict]:
        """Fetch last N invoices from Stripe API and cache locally in client_invoices."""
        if not self.is_configured():
            return []

        client_obj = self.db.get(Client, client_id)
        if not client_obj or not client_obj.stripe_customer_id:
            return []

        stripe_client = self._get_stripe_client()

        try:
            invoices = stripe_client.Invoice.list(
                customer=client_obj.stripe_customer_id,
                limit=limit,
            )
        except stripe.error.StripeError as e:
            logger.error("Failed to fetch invoices for client %s: %s", client_id, str(e))
            return self._get_cached_invoices(client_id, limit)

        # Cache invoices locally
        result = []
        for inv in invoices.data:
            self._cache_invoice(client_id, inv)
            result.append({
                "id": inv.id,
                "amount_cents": inv.amount_due,
                "currency": inv.currency,
                "status": inv.status,
                "period_start": datetime.fromtimestamp(inv.period_start, tz=timezone.utc).isoformat() if inv.period_start else None,
                "period_end": datetime.fromtimestamp(inv.period_end, tz=timezone.utc).isoformat() if inv.period_end else None,
                "invoice_pdf_url": inv.invoice_pdf,
                "hosted_invoice_url": inv.hosted_invoice_url,
                "created_at": datetime.fromtimestamp(inv.created, tz=timezone.utc).isoformat() if inv.created else None,
            })

        self.db.commit()
        return result

    # ------------------------------------------------------------------
    # Subscription sync
    # ------------------------------------------------------------------

    def sync_subscription_from_stripe(self, client_id: UUID) -> None:
        """Admin 'Sync from Stripe' — fetch latest subscription state and update local DB."""
        if not self.is_configured():
            logger.warning("Stripe not configured — cannot sync")
            return

        client_obj = self.db.get(Client, client_id)
        if not client_obj:
            raise ValueError(f"Client {client_id} not found")

        if not client_obj.stripe_subscription_id:
            logger.info("Client %s has no subscription to sync", client_id)
            return

        stripe_client = self._get_stripe_client()

        try:
            subscription = stripe_client.Subscription.retrieve(client_obj.stripe_subscription_id)
        except stripe.error.InvalidRequestError:
            logger.warning("Subscription %s not found in Stripe for client %s", client_obj.stripe_subscription_id, client_id)
            client_obj.subscription_status = "canceled"
            self.db.commit()
            return
        except stripe.error.StripeError as e:
            logger.error("Failed to sync subscription for client %s: %s", client_id, str(e))
            raise RuntimeError(f"Stripe sync error: {e.user_message or str(e)}")

        # Update local state from Stripe subscription
        status_map = {
            "active": "active",
            "past_due": "past_due",
            "trialing": "trialing",
            "canceled": "canceled",
            "unpaid": "past_due",
            "incomplete": "past_due",
            "incomplete_expired": "canceled",
        }
        client_obj.subscription_status = status_map.get(subscription.status, subscription.status)

        # Update price and plan from subscription items
        if subscription.get("items") and subscription["items"].data:
            item = subscription["items"].data[0]
            client_obj.stripe_price_id = item.price.id
            # Determine plan_tier from price metadata
            plan_tier = item.price.metadata.get("plan_tier")
            if plan_tier and plan_tier in PLAN_TIERS:
                client_obj.plan_type = plan_tier
                client_obj.max_avatars = PLAN_MAX_AVATARS[plan_tier]

        # Update billing period
        if subscription.current_period_start:
            client_obj.billing_period_start = datetime.fromtimestamp(
                subscription.current_period_start, tz=timezone.utc
            )
        if subscription.current_period_end:
            client_obj.billing_period_end = datetime.fromtimestamp(
                subscription.current_period_end, tz=timezone.utc
            )

        # Handle canceled_at
        if subscription.canceled_at:
            client_obj.subscription_canceled_at = datetime.fromtimestamp(
                subscription.canceled_at, tz=timezone.utc
            )

        # Update is_active based on status
        if client_obj.subscription_status in ("canceled", "trial_expired"):
            client_obj.is_active = False
        elif client_obj.subscription_status in ("active", "trialing"):
            client_obj.is_active = True

        self.db.commit()
        logger.info("Synced subscription for client %s — status: %s", client_id, client_obj.subscription_status)

    # ------------------------------------------------------------------
    # Coupons
    # ------------------------------------------------------------------

    def create_coupon(
        self,
        name: str,
        percent_off: int | None = None,
        amount_off: int | None = None,
        duration_in_months: int = 3,
        max_redemptions: int | None = None,
    ) -> str:
        """Create a Stripe Coupon and store it locally. Returns the coupon ID."""
        if not self.is_configured():
            raise RuntimeError("Stripe is not configured")

        if not percent_off and not amount_off:
            raise ValueError("Must provide either percent_off or amount_off")

        stripe_client = self._get_stripe_client()

        coupon_params: dict = {
            "name": name,
            "duration": "repeating",
            "duration_in_months": duration_in_months,
        }

        if percent_off:
            coupon_params["percent_off"] = percent_off
        elif amount_off:
            coupon_params["amount_off"] = amount_off
            coupon_params["currency"] = "usd"

        if max_redemptions:
            coupon_params["max_redemptions"] = max_redemptions

        try:
            stripe_coupon = stripe_client.Coupon.create(**coupon_params)
        except stripe.error.StripeError as e:
            logger.error("Failed to create Stripe coupon '%s': %s", name, str(e))
            raise RuntimeError(f"Stripe coupon error: {e.user_message or str(e)}")

        # Store locally
        local_coupon = BillingCoupon(
            stripe_coupon_id=stripe_coupon.id,
            code=stripe_coupon.id,  # Use Stripe coupon ID as the code
            name=name,
            percent_off=percent_off,
            amount_off_cents=amount_off,
            duration_in_months=duration_in_months,
            max_redemptions=max_redemptions,
        )
        self.db.add(local_coupon)
        self.db.commit()

        logger.info("Created coupon '%s': %s", name, stripe_coupon.id)
        return stripe_coupon.id

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_stripe_customer(self, client_obj: Client, stripe_client) -> str:
        """Get existing or create new Stripe Customer for the RAMP Client."""
        if client_obj.stripe_customer_id:
            return client_obj.stripe_customer_id

        # Find admin email for this client
        admin_email = self._get_client_admin_email(client_obj)

        try:
            customer = stripe_client.Customer.create(
                name=client_obj.brand_name,
                email=admin_email,
                metadata={"client_id": str(client_obj.id)},
            )
        except stripe.error.StripeError as e:
            logger.error("Failed to create Stripe customer for client %s: %s", client_obj.id, str(e))
            raise RuntimeError(f"Stripe customer creation error: {e.user_message or str(e)}")

        client_obj.stripe_customer_id = customer.id
        self.db.commit()
        return customer.id

    def _get_client_admin_email(self, client_obj: Client) -> str | None:
        """Find the admin user's email for a client."""
        stmt = (
            select(User.email)
            .where(User.client_id == client_obj.id)
            .where(User.role.in_(["client_admin", "owner"]))
            .where(User.is_active.is_(True))
            .order_by(User.created_at.asc())
            .limit(1)
        )
        result = self.db.execute(stmt).scalar_one_or_none()
        return result

    def _get_price_id(self, plan_tier: str) -> str | None:
        """Get the Stripe Price ID for a plan tier from system_settings."""
        if plan_tier not in PLAN_TIERS:
            return None
        setting_key = f"stripe_price_id_{plan_tier}"
        return get_setting(self.db, setting_key) or None

    def _cache_invoice(self, client_id: UUID, invoice) -> None:
        """Cache a Stripe Invoice object in the local client_invoices table."""
        existing = (
            self.db.query(ClientInvoice)
            .filter(ClientInvoice.stripe_invoice_id == invoice.id)
            .first()
        )

        if existing:
            # Update mutable fields
            existing.status = invoice.status
            existing.invoice_pdf_url = invoice.invoice_pdf
            existing.hosted_invoice_url = invoice.hosted_invoice_url
        else:
            new_invoice = ClientInvoice(
                client_id=client_id,
                stripe_invoice_id=invoice.id,
                amount_cents=invoice.amount_due,
                currency=invoice.currency,
                status=invoice.status,
                period_start=datetime.fromtimestamp(invoice.period_start, tz=timezone.utc) if invoice.period_start else datetime.now(timezone.utc),
                period_end=datetime.fromtimestamp(invoice.period_end, tz=timezone.utc) if invoice.period_end else datetime.now(timezone.utc),
                invoice_pdf_url=invoice.invoice_pdf,
                hosted_invoice_url=invoice.hosted_invoice_url,
            )
            self.db.add(new_invoice)

    def _get_cached_invoices(self, client_id: UUID, limit: int) -> list[dict]:
        """Fallback: return locally cached invoices when Stripe API is unavailable."""
        stmt = (
            select(ClientInvoice)
            .where(ClientInvoice.client_id == client_id)
            .order_by(ClientInvoice.created_at.desc())
            .limit(limit)
        )
        invoices = self.db.execute(stmt).scalars().all()
        return [
            {
                "id": inv.stripe_invoice_id,
                "amount_cents": inv.amount_cents,
                "currency": inv.currency,
                "status": inv.status,
                "period_start": inv.period_start.isoformat() if inv.period_start else None,
                "period_end": inv.period_end.isoformat() if inv.period_end else None,
                "invoice_pdf_url": inv.invoice_pdf_url,
                "hosted_invoice_url": inv.hosted_invoice_url,
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
            }
            for inv in invoices
        ]
