"""Stripe webhook endpoint — receives and processes Stripe events.

Security:
- Verifies webhook signature using stripe_webhook_secret from DB settings
- Raw body must be preserved (no JSON parsing before signature check)
- Idempotent: duplicate event IDs are skipped
- All events logged to webhook_events table regardless of outcome

Route: POST /api/stripe/webhook
Auth: None (public, signature-verified)
"""

import stripe
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from app.database import SessionLocal
from app.logging_config import get_logger
from app.services.stripe_service import (
    get_stripe_keys,
    handle_webhook_event,
    verify_webhook_signature,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/stripe", tags=["stripe"])


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Receive Stripe webhook events.

    Stripe sends POST with raw body + Stripe-Signature header.
    We verify the signature, then process the event.

    IMPORTANT: Always return 200 to Stripe unless signature is invalid.
    Returning 4xx/5xx causes Stripe to retry (up to 72h), which is only
    appropriate for genuine signature failures, not processing errors.
    """
    # 1. Read raw body (must be raw bytes for signature verification)
    try:
        payload = await request.body()
    except Exception as e:
        logger.error("STRIPE_WEBHOOK_BODY_READ_ERROR | error=%s", str(e))
        raise HTTPException(status_code=400, detail="Could not read request body")

    if not payload:
        raise HTTPException(status_code=400, detail="Empty request body")

    sig_header = request.headers.get("Stripe-Signature", "")

    if not sig_header:
        logger.warning("STRIPE_WEBHOOK_NO_SIGNATURE | ip=%s", request.client.host if request.client else "unknown")
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    # 2. Get webhook secret from DB
    db = SessionLocal()
    try:
        _, webhook_secret = get_stripe_keys(db)
    except Exception as e:
        logger.error("STRIPE_WEBHOOK_DB_ERROR | error=%s", str(e))
        db.close()
        # Return 500 — Stripe will retry later (DB might be temporarily down)
        raise HTTPException(status_code=500, detail="Internal configuration error")
    finally:
        db.close()

    if not webhook_secret:
        logger.error("STRIPE_WEBHOOK_NOT_CONFIGURED | stripe_webhook_secret is empty")
        # Return 200 to prevent Stripe retry spam while unconfigured
        return JSONResponse(
            status_code=200,
            content={"status": "error", "message": "Webhook secret not configured — event not processed"},
        )

    # 3. Verify signature
    try:
        event = verify_webhook_signature(payload, sig_header, webhook_secret)
    except stripe.error.SignatureVerificationError as e:
        logger.warning(
            "STRIPE_WEBHOOK_INVALID_SIG | ip=%s | error=%s",
            request.client.host if request.client else "unknown",
            str(e),
        )
        # 400 = Stripe will retry (correct behavior for bad signature — could be replay attack)
        raise HTTPException(status_code=400, detail="Invalid signature")
    except ValueError as e:
        # Payload is not valid JSON
        logger.warning("STRIPE_WEBHOOK_INVALID_PAYLOAD | error=%s", str(e))
        raise HTTPException(status_code=400, detail="Invalid payload format")
    except Exception as e:
        logger.error("STRIPE_WEBHOOK_VERIFY_ERROR | error=%s", str(e))
        raise HTTPException(status_code=400, detail="Signature verification failed")

    # 4. Process event — always return 200 after signature passes
    # (processing errors should not cause Stripe retries)
    db = SessionLocal()
    try:
        result = handle_webhook_event(db, event)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(
            "STRIPE_WEBHOOK_PROCESSING_ERROR | event_id=%s | event_type=%s | error=%s",
            event.get("id", "?"),
            event.get("type", "?"),
            str(e),
        )
        # Return 200 anyway — event is logged, we can reprocess manually.
        # Returning 5xx would cause Stripe to retry for 72 hours.
        return JSONResponse(
            status_code=200,
            content={"status": "processing_error", "message": str(e), "event_id": event.get("id")},
        )
    finally:
        db.close()

    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "result": result.get("status", "processed"),
            "event_id": event.get("id"),
        },
    )
