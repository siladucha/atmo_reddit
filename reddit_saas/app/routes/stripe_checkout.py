"""Stripe checkout routes — client-facing upgrade/payment flows.

Routes:
- POST /clients/{client_id}/checkout — create checkout session → redirect to Stripe
- GET /clients/{client_id}/checkout/success — post-payment success page
- GET /clients/{client_id}/checkout/cancel — user cancelled checkout

Auth: client_admin, client_manager, owner, partner (anyone who can manage billing)
"""

from uuid import UUID

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import get_current_user
from app.logging_config import get_logger
from app.models.client import Client
from app.models.user import User
from app.services.stripe_service import create_checkout_session

logger = get_logger(__name__)

router = APIRouter(tags=["billing"])


@router.post("/clients/{client_id}/checkout")
def initiate_checkout(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create Stripe Checkout Session and redirect client to payment page.

    Form data: plan (target plan type string)
    """
    # Only client_admin, client_manager, owner, partner can initiate payment
    if user.role not in ("owner", "partner", "client_admin", "client_manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions for billing actions")

    # Get target plan from query params (form submits as ?plan=X)
    target_plan = request.query_params.get("plan")
    if not target_plan:
        raise HTTPException(status_code=400, detail="Missing 'plan' parameter")

    valid_plans = ("seed", "starter", "growth", "scale")
    if target_plan not in valid_plans:
        raise HTTPException(status_code=400, detail=f"Invalid plan: {target_plan}. Valid: {valid_plans}")

    # Check current plan — can only upgrade (or same for restart)
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Build success/cancel URLs
    base_url = str(request.base_url).rstrip("/")
    success_url = f"{base_url}/clients/{client_id}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base_url}/clients/{client_id}/billing"

    try:
        checkout_url = create_checkout_session(
            db=db,
            client_id=client_id,
            target_plan=target_plan,
            success_url=success_url,
            cancel_url=cancel_url,
        )
        db.commit()
    except ValueError as e:
        # Configuration errors (missing stripe_price_id, missing key, etc.)
        logger.error("CHECKOUT_CONFIG_ERROR | client_id=%s | error=%s", client_id, str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except stripe.error.CardError as e:
        # Card declined by Stripe (shouldn't happen at checkout creation, but defensive)
        logger.warning("CHECKOUT_CARD_ERROR | client_id=%s | error=%s", client_id, str(e))
        raise HTTPException(status_code=402, detail="Card was declined. Please try a different payment method.")
    except stripe.error.RateLimitError:
        logger.error("CHECKOUT_RATE_LIMIT | client_id=%s", client_id)
        raise HTTPException(status_code=503, detail="Payment service is busy. Please try again in a moment.")
    except stripe.error.InvalidRequestError as e:
        # Invalid parameters sent to Stripe (bad price_id, etc.)
        logger.error("CHECKOUT_INVALID_REQUEST | client_id=%s | error=%s", client_id, str(e))
        raise HTTPException(status_code=400, detail="Payment configuration error. Please contact support.")
    except stripe.error.AuthenticationError:
        # API key is invalid
        logger.critical("CHECKOUT_AUTH_ERROR | client_id=%s | Stripe API key invalid!", client_id)
        raise HTTPException(status_code=500, detail="Payment service configuration error. Please contact support.")
    except stripe.error.APIConnectionError:
        # Network issue connecting to Stripe
        logger.error("CHECKOUT_CONNECTION_ERROR | client_id=%s | Cannot reach Stripe API", client_id)
        raise HTTPException(status_code=503, detail="Payment service temporarily unavailable. Please try again.")
    except stripe.error.StripeError as e:
        # Catch-all for other Stripe errors
        logger.error("CHECKOUT_STRIPE_ERROR | client_id=%s | type=%s | error=%s", client_id, type(e).__name__, str(e))
        raise HTTPException(status_code=500, detail="An error occurred with the payment service. Please try again.")
    except Exception as e:
        # Unexpected errors
        logger.error("CHECKOUT_UNEXPECTED_ERROR | client_id=%s | error=%s", client_id, str(e))
        db.rollback()
        raise HTTPException(status_code=500, detail="An unexpected error occurred. Please try again or contact support.")

    return RedirectResponse(url=checkout_url, status_code=303)


@router.get("/clients/{client_id}/checkout/success", response_class=HTMLResponse)
def checkout_success(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Post-payment success page. Stripe redirects here after successful checkout."""
    client = db.query(Client).filter(Client.id == client_id).first()
    plan_name = client.plan_type.title() if client and client.plan_type else "Active"

    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Payment Successful — RAMP</title>
        <meta http-equiv="refresh" content="5;url=/clients/{client_id}/billing">
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-900 min-h-screen flex items-center justify-center">
        <div class="bg-slate-800 border border-slate-700 p-10 rounded-xl text-center max-w-md">
            <div class="text-5xl mb-4">✅</div>
            <h1 class="text-2xl font-semibold text-white mb-3">Payment Successful!</h1>
            <p class="text-gray-400 mb-4">
                Your plan has been upgraded to <strong class="text-white">{plan_name}</strong>.
            </p>
            <p class="text-gray-500 text-sm">Redirecting to billing page in 5 seconds...</p>
            <a href="/clients/{client_id}/billing" class="mt-4 inline-block text-indigo-400 hover:text-indigo-300 text-sm">
                Click here if not redirected
            </a>
        </div>
    </body>
    </html>
    """)


@router.get("/clients/{client_id}/checkout/cancel", response_class=HTMLResponse)
def checkout_cancel(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """User cancelled the checkout. Redirect back to billing page."""
    return RedirectResponse(url=f"/clients/{client_id}/billing", status_code=303)
