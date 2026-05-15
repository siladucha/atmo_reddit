import json
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.ab_test_assignment import ABTestAssignment
from app.schemas.marketing import (
    AnalyticsBatchRequest,
    RecordAssignmentsRequest,
    WaitlistSignupRequest,
)
from app.services.ab_tests import (
    get_default_variants,
    get_tests_for_page,
    is_valid_variant,
)
from app.services.analytics import store_events, validate_event
from app.services.waitlist import process_signup

router = APIRouter(tags=["api"])
templates = Jinja2Templates(directory="app/templates")

# Map source_page values to template names
SOURCE_PAGE_TEMPLATES = {
    "mobile": "marketing_mobile.html",
    "/mobile": "marketing_mobile.html",
    "proxy": "marketing_proxy.html",
    "/proxy": "marketing_proxy.html",
}


def _parse_visitor_id(request: Request) -> UUID | None:
    """Parse visitor_id from cookies, returning None if invalid or missing."""
    raw = request.cookies.get("visitor_id")
    if not raw:
        return None
    try:
        return UUID(raw)
    except (ValueError, AttributeError):
        return None


def _get_template_for_source(source_page: str | None, referer: str | None) -> str:
    """Determine which template to re-render based on source_page or Referer header."""
    if source_page:
        template = SOURCE_PAGE_TEMPLATES.get(source_page.strip().lower())
        if template:
            return template

    # Fallback to Referer header
    if referer:
        referer_lower = referer.lower()
        if "/proxy" in referer_lower:
            return "marketing_proxy.html"
        if "/mobile" in referer_lower:
            return "marketing_mobile.html"

    # Default to mobile page
    return "marketing_mobile.html"


def _get_page_name_from_template(template_name: str) -> str:
    """Extract page name (mobile/proxy) from template filename."""
    if "proxy" in template_name:
        return "proxy"
    return "mobile"


def _build_template_context(
    request: Request,
    page_name: str,
    form_data: dict | None = None,
    errors: dict | None = None,
    error_message: str | None = None,
) -> dict:
    """Build template context for re-rendering a page with errors and retained form data."""
    defaults = get_default_variants()
    tests = get_tests_for_page(page_name)
    variant_display = {}
    for test in tests:
        default_variant_name = defaults[test.test_name]
        for v in test.variants:
            if v.name == default_variant_name:
                variant_display[test.test_name] = v.display_value
                break

    context = {
        "variants": variant_display,
        "tests": tests,
    }

    if form_data:
        context["form_data"] = form_data
    if errors:
        context["errors"] = errors
    if error_message:
        context["error_message"] = error_message

    return context


@router.post("/waitlist/signup")
async def waitlist_signup(request: Request, db: Session = Depends(get_db)):
    """Process waitlist form submission.

    On success: redirect to /thank-you with 303 status.
    On validation error: re-render page with inline errors and retained form data.
    On DB error: re-render page with error message.
    """
    form = await request.form()
    form_dict = dict(form)

    # Determine source page for re-rendering on error
    source_page = form_dict.get("source_page")
    referer = request.headers.get("referer")
    template_name = _get_template_for_source(source_page, referer)
    page_name = _get_page_name_from_template(template_name)

    # Parse variant_shown from form (may be JSON string)
    variant_shown = form_dict.get("variant_shown")
    if isinstance(variant_shown, str):
        try:
            variant_shown = json.loads(variant_shown)
        except (json.JSONDecodeError, TypeError):
            variant_shown = None

    # Parse accounts_count to int if present
    accounts_count = form_dict.get("accounts_count")
    if accounts_count is not None and accounts_count != "":
        try:
            accounts_count = int(accounts_count)
        except (ValueError, TypeError):
            accounts_count = None
    else:
        accounts_count = None

    # Validate with Pydantic schema
    try:
        signup_data = WaitlistSignupRequest(
            email=form_dict.get("email", ""),
            company=form_dict.get("company") or None,
            role=form_dict.get("role") or None,
            accounts_count=accounts_count,
            price_tier=form_dict.get("price_tier") or None,
            feedback=form_dict.get("feedback") or None,
            variant_shown=variant_shown,
            source_page=source_page or None,
        )
    except ValidationError as e:
        # Extract field-level errors
        errors = {}
        for error in e.errors():
            field = error["loc"][-1] if error["loc"] else "general"
            errors[field] = error["msg"]

        context = _build_template_context(
            request, page_name, form_data=form_dict, errors=errors
        )
        return templates.TemplateResponse(
            request=request, name=template_name, context=context, status_code=422
        )

    # Read visitor_id from cookies for conversion marking
    visitor_id = _parse_visitor_id(request)

    # Process signup
    try:
        process_signup(
            db=db,
            email=signup_data.email,
            company=signup_data.company,
            role=signup_data.role,
            accounts_count=signup_data.accounts_count,
            price_tier=signup_data.price_tier,
            feedback=signup_data.feedback,
            variant_shown=signup_data.variant_shown,
            source_page=signup_data.source_page,
            visitor_id=visitor_id,
        )
    except SQLAlchemyError:
        db.rollback()
        context = _build_template_context(
            request,
            page_name,
            form_data=form_dict,
            error_message="We couldn't process your signup. Please try again.",
        )
        return templates.TemplateResponse(
            request=request, name=template_name, context=context, status_code=500
        )

    return RedirectResponse(url="/thank-you", status_code=303)


@router.post("/api/analytics/events")
async def record_analytics(request: Request, db: Session = Depends(get_db)):
    """Accept a batch of analytics events.

    Validates each event, stores valid ones, returns count.
    """
    try:
        body = await request.json()
        batch = AnalyticsBatchRequest(**body)
    except ValidationError as e:
        errors = []
        for error in e.errors():
            errors.append({
                "loc": list(error["loc"]),
                "msg": error["msg"],
                "type": error["type"],
            })
        return JSONResponse(
            status_code=422,
            content={"detail": errors},
        )
    except Exception:
        return JSONResponse(
            status_code=422,
            content={"detail": "Invalid JSON body"},
        )

    # Validate each event using the analytics service
    valid_events = []
    for event in batch.events:
        validated = validate_event(event.model_dump())
        if validated is not None:
            valid_events.append(validated)

    # Store valid events
    stored_count = 0
    if valid_events:
        stored_count = store_events(db, valid_events)

    return JSONResponse(
        status_code=200,
        content={"stored": stored_count, "total": len(batch.events)},
    )


@router.post("/api/ab/record")
async def record_ab_assignment(request: Request, db: Session = Depends(get_db)):
    """Record A/B test variant assignments to the database.

    Accepts: {visitor_id, assignments: [{test_name, variant_name}]}
    Idempotent: skips if assignment already exists for visitor+test.
    Returns: {"recorded": count_new, "skipped": count_existing}
    """
    try:
        body = await request.json()
        data = RecordAssignmentsRequest(**body)
    except ValidationError as e:
        errors = []
        for error in e.errors():
            errors.append({
                "loc": list(error["loc"]),
                "msg": error["msg"],
                "type": error["type"],
            })
        return JSONResponse(
            status_code=422,
            content={"detail": errors},
        )
    except Exception:
        return JSONResponse(
            status_code=422,
            content={"detail": "Invalid JSON body"},
        )

    count_new = 0
    count_existing = 0

    for assignment in data.assignments:
        # Validate variant is valid for the test
        if not is_valid_variant(assignment.test_name, assignment.variant_name):
            continue  # Skip invalid variants silently

        # Check if (visitor_id, test_name) already exists
        existing = (
            db.query(ABTestAssignment)
            .filter(
                ABTestAssignment.visitor_id == data.visitor_id,
                ABTestAssignment.test_name == assignment.test_name,
            )
            .first()
        )

        if existing:
            count_existing += 1
        else:
            # Insert new assignment
            new_assignment = ABTestAssignment(
                visitor_id=data.visitor_id,
                test_name=assignment.test_name,
                variant_name=assignment.variant_name,
            )
            db.add(new_assignment)
            count_new += 1

    if count_new > 0:
        db.commit()

    return JSONResponse(
        status_code=200,
        content={"recorded": count_new, "skipped": count_existing},
    )
