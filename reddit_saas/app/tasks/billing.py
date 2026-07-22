"""Celery tasks for Stripe billing event processing and product sync.

- process_billing_event: Routes webhook events to SubscriptionManager handlers.
  Retries with exponential backoff (60×2^attempt), max 3 retries.
- sync_stripe_products: Ensures Stripe Products/Prices exist for all plan tiers.
  Called at app startup (if Stripe is configured) and available on-demand.

Requirements: 6.3, 1.4
"""

from datetime import datetime, timezone

from app.tasks.worker import celery_app
from app.database import SessionLocal
from app.logging_config import get_logger

logger = get_logger(__name__)

# Event types routed to SubscriptionManager handlers
HANDLED_EVENT_TYPES = {
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "customer.subscription.trial_will_end",
    "invoice.paid",
    "invoice.payment_failed",
    "checkout.session.completed",
}


@celery_app.task(name="process_billing_event", bind=True, max_retries=3)
def process_billing_event(self, billing_event_id: str, event_type: str, event_data: dict):
    """Process a single billing webhook event asynchronously.

    Routes to appropriate SubscriptionManager handler based on event_type.
    Updates billing_events.processing_status to "processed" on success,
    "failed" on permanent error.

    Retries with exponential backoff: 60×2^attempt (60s, 120s, 240s).
    """
    from app.models.billing_event import BillingEvent
    from app.services.subscription_manager import SubscriptionManager

    db = SessionLocal()
    try:
        # Find the BillingEvent record
        billing_event = db.query(BillingEvent).filter(
            BillingEvent.id == billing_event_id
        ).first()

        if not billing_event:
            logger.error(
                "process_billing_event: BillingEvent not found id=%s",
                billing_event_id,
            )
            return {"status": "error", "reason": "event_not_found"}

        # Route to appropriate handler
        manager = SubscriptionManager(db)

        if event_type == "customer.subscription.updated":
            manager.handle_subscription_updated(event_data)
        elif event_type == "customer.subscription.deleted":
            manager.handle_subscription_deleted(event_data)
        elif event_type == "customer.subscription.trial_will_end":
            manager.handle_trial_will_end(event_data)
        elif event_type == "invoice.paid":
            manager.handle_invoice_paid(event_data)
        elif event_type == "invoice.payment_failed":
            manager.handle_invoice_payment_failed(event_data)
        elif event_type == "checkout.session.completed":
            manager.handle_checkout_completed(event_data)
        else:
            logger.warning(
                "process_billing_event: unhandled event_type=%s, id=%s",
                event_type,
                billing_event_id,
            )
            billing_event.processing_status = "skipped"
            billing_event.processed_at = datetime.now(timezone.utc)
            db.commit()
            return {"status": "skipped", "event_type": event_type}

        # Success — mark as processed
        billing_event.processing_status = "processed"
        billing_event.processed_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(
            "process_billing_event: processed event_type=%s, id=%s",
            event_type,
            billing_event_id,
        )
        return {"status": "processed", "event_type": event_type}

    except Exception as exc:
        # Mark as failed if max retries exhausted
        try:
            billing_event = db.query(BillingEvent).filter(
                BillingEvent.id == billing_event_id
            ).first()
            if billing_event:
                if self.request.retries >= self.max_retries:
                    billing_event.processing_status = "failed"
                    billing_event.error_message = str(exc)[:500]
                    billing_event.processed_at = datetime.now(timezone.utc)
                    db.commit()
                    logger.error(
                        "process_billing_event: permanently failed after %d retries, "
                        "event_type=%s, id=%s, error=%s",
                        self.max_retries,
                        event_type,
                        billing_event_id,
                        str(exc)[:200],
                    )
                    return {"status": "failed", "error": str(exc)[:200]}
                else:
                    db.rollback()
        except Exception:
            db.rollback()

        # Retry with exponential backoff: 60 * 2^attempt
        countdown = 60 * (2 ** self.request.retries)
        logger.warning(
            "process_billing_event: retrying (attempt %d/%d) in %ds, "
            "event_type=%s, id=%s, error=%s",
            self.request.retries + 1,
            self.max_retries,
            countdown,
            event_type,
            billing_event_id,
            str(exc)[:200],
        )
        raise self.retry(exc=exc, countdown=countdown)

    finally:
        db.close()


@celery_app.task(name="sync_stripe_products")
def sync_stripe_products():
    """Ensure Stripe Products and Prices exist for all plan tiers.

    Calls BillingService.ensure_products_exist() which creates Products/Prices
    in Stripe if they don't already exist, and stores price IDs in system_settings.

    Called at app startup (if Stripe configured) and available on-demand.
    """
    from app.services.billing import BillingService

    db = SessionLocal()
    try:
        service = BillingService(db)
        if not service.is_configured():
            logger.info("sync_stripe_products: Stripe not configured, skipping")
            return {"status": "skipped", "reason": "stripe_not_configured"}

        service.ensure_products_exist()
        logger.info("sync_stripe_products: products synced successfully")
        return {"status": "synced"}

    except Exception as e:
        logger.error("sync_stripe_products failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)[:200]}
    finally:
        db.close()
