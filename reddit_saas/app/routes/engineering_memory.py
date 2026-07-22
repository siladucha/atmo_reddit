"""Engineering Memory routes — bug report form + QA admin dashboard."""

import time

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

from app.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _get_user_context(request: Request) -> dict:
    """Try to extract logged-in user info from JWT cookie (non-blocking)."""
    try:
        from app.services.auth import decode_access_token
        token = request.cookies.get("access_token")
        if token:
            payload = decode_access_token(token)
            if payload:
                return {
                    "reporter_role": payload.get("role", ""),
                    "reporter_email": payload.get("email", ""),
                    "reporter_name": payload.get("full_name", ""),
                }
    except Exception:
        pass
    return {"reporter_role": "", "reporter_email": "", "reporter_name": ""}


@router.get("/report-issue", response_class=HTMLResponse)
async def report_issue_form(request: Request):
    """Render the public issue reporting form."""
    user_ctx = _get_user_context(request)
    return templates.TemplateResponse(
        name="report_issue.html",
        context={"request": request, **user_ctx},
        request=request,
    )


@router.post("/api/report-issue", response_class=HTMLResponse)
async def report_issue_submit(
    request: Request,
    what_happened: str = Form(""),
    where: str = Form(""),
    expected: str = Form(""),
    actual_result: str = Form(""),
    environment: str = Form("prod"),
    screenshot: UploadFile | None = File(None),
    email: str = Form(""),
    reporter_role: str = Form(""),
    reporter_name: str = Form(""),
    website: str = Form(""),
    form_ts: str = Form(""),
    human_check: str = Form(""),
    db: Session = Depends(get_db),
):
    """Process bug report — saves to PostgreSQL."""

    # === Anti-bot checks (3 layers) ===

    # Layer 1: Honeypot
    if website:
        logger.warning("BOT: honeypot from %s", request.client.host)
        return templates.TemplateResponse("report_issue.html", {"request": request, "success": True}, request=request)

    # Layer 2: JS challenge
    if human_check != "91":
        logger.warning("BOT: JS challenge failed from %s", request.client.host)
        return templates.TemplateResponse("report_issue.html", {"request": request, "success": True}, request=request)

    # Layer 3: Timing (>3 seconds)
    try:
        elapsed = int(time.time()) - int(form_ts)
        if elapsed < 3:
            logger.warning("BOT: too fast (%ds) from %s", elapsed, request.client.host)
            return templates.TemplateResponse("report_issue.html", {"request": request, "success": True}, request=request)
    except (ValueError, TypeError):
        logger.warning("BOT: no timestamp from %s", request.client.host)
        return templates.TemplateResponse("report_issue.html", {"request": request, "success": True}, request=request)

    # === Server-side validation ===
    errors = []
    if not what_happened.strip():
        errors.append("'What happened?' is required")
    if not where.strip():
        errors.append("'Where?' is required")
    if not expected.strip():
        errors.append("'Expected?' is required")
    if not actual_result.strip():
        errors.append("'Actual result?' is required")

    if errors:
        user_ctx = _get_user_context(request)
        return templates.TemplateResponse(
            "report_issue.html",
            {"request": request, "error": "; ".join(errors), **user_ctx},
            request=request,
        )

    # Save screenshot
    screenshot_url = None
    if screenshot and screenshot.filename:
        from app.services.engineering_memory import save_screenshot
        screenshot_url = await save_screenshot(screenshot)

    # Create bug report in DB
    form_data = {
        "what_happened": what_happened,
        "where": where,
        "expected": expected,
        "actual_result": actual_result,
        "email": email,
        "reporter_role": reporter_role,
        "reporter_name": reporter_name,
        "environment": environment,
        "screenshot_url": screenshot_url,
    }

    try:
        from app.services.engineering_memory import create_incident
        bug = create_incident(db, form_data)
        logger.info("Bug reported: %s", bug.bug_id)
        return templates.TemplateResponse(
            "report_issue.html",
            {"request": request, "success": True, "bug_id": bug.bug_id},
            request=request,
        )
    except Exception as e:
        import traceback
        logger.error("Failed to create bug report: %s\n%s", str(e), traceback.format_exc())
        user_ctx = _get_user_context(request)
        return templates.TemplateResponse(
            "report_issue.html",
            {"request": request, "error": "Something went wrong. Please try again.", **user_ctx},
            request=request,
        )
