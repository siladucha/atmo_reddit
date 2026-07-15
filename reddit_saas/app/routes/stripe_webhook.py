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
    """
    # 1. Read raw body (must be raw bytes for signature verification)
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature", "")

    if not sig_header:
        logger.warning("STRIPE_WEBHOOK_NO_SIGNATURE | ip=%s", request.client.host)
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    # 2. Get webhook secret from DB
    db = SessionLocal()
    try:
        _, webhook_secret = get_stripe_keys(db)
    finally:
        db.close()

    if not webhook_secret:
        logger.error("STRIPE_WEBHOOK_NOT_CONFIGURED | stripe_webhook_secret is empty")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    # 3. Verify signature
    try:
        event = verify_webhook_signature(payload, sig_header, webhook_secret)
    except stripe.error.SignatureVerificationError as e:
        logger.warning("STRIPE_WEBHOOK_INVALID_SIG | error=%s", str(e))
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error("STRIPE_WEBHOOK_VERIFY_ERROR | error=%s", str(e))
        raise HTTPException(status_code=400, detail="Signature verification failed")

    # 4. Process event
    db = SessionLocal()
    try:
        result = handle_webhook_event(db, event)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("STRIPE_WEBHOOK_PROCESSING_ERROR | event=%s | error=%s", event.get("id"), str(e))
        # Return 200 anyway — don't let Stripe retry on processing errors
        # (we've already logged the event, can reprocess manually)
        return JSONResponse(
            status_code=200,
            content={"status": "error", "message": str(e)},
        )
    finally:
        db.close()

    return JSONResponse(status_code=200, content={"status": "ok", "result": result.get("status", "processed")})
