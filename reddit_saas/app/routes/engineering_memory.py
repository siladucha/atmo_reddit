"""Engineering Memory routes — bug report form + QA admin dashboard."""

import time

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

from app.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.dependencies.permissions import require_platform_admin
from app.logging_config import get_logger
from app.models.bug_report import BugReport

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



@router.get("/admin/qa-board", response_class=HTMLResponse)
async def admin_qa_board(
    request: Request,
    status: str = "",
    category: str = "",
    risk_level: str = "",
    db: Session = Depends(get_db),
    _user=Depends(require_platform_admin),
):
    """QA Board — internal bug tracking dashboard (replaces Notion)."""
    query = db.query(BugReport)

    if status:
        query = query.filter(BugReport.status == status)
    if category:
        query = query.filter(BugReport.category == category)
    if risk_level:
        query = query.filter(BugReport.risk_level == risk_level)

    bugs = query.order_by(desc(BugReport.created_at)).all()

    # Stats
    total = db.query(BugReport).count()
    reported = db.query(BugReport).filter(BugReport.status == "Reported").count()
    investigating = db.query(BugReport).filter(BugReport.status == "Investigating").count()
    fixed = db.query(BugReport).filter(BugReport.status == "Fixed").count()
    verified = db.query(BugReport).filter(BugReport.status == "Verified").count()

    return templates.TemplateResponse(
        "admin_qa_board.html",
        {
            "request": request,
            "bugs": bugs,
            "total": total,
            "reported": reported,
            "investigating": investigating,
            "fixed": fixed,
            "verified": verified,
            "filter_status": status,
            "filter_category": category,
            "filter_risk_level": risk_level,
            "active_nav": "qa_board",
        },
        request=request,
    )


@router.post("/admin/qa-board/{bug_id}/status", response_class=HTMLResponse)
async def admin_qa_board_update_status(
    request: Request,
    bug_id: str,
    new_status: str = Form(...),
    verification_comment: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_platform_admin),
):
    """Update bug status from QA Board."""
    from datetime import datetime, timezone

    bug = db.query(BugReport).filter(BugReport.bug_id == bug_id).first()
    if not bug:
        return HTMLResponse("<div class='text-red-400'>Bug not found</div>", status_code=404)

    bug.status = new_status
    if new_status == "Fixed":
        bug.fixed_at = datetime.now(timezone.utc)
    elif new_status == "Verified":
        bug.verified_at = datetime.now(timezone.utc)
        bug.verified_by = getattr(_user, "full_name", None) or getattr(_user, "email", "Unknown")
        if verification_comment:
            bug.verification_comment = verification_comment

    db.commit()
    # Return updated row partial
    return HTMLResponse(f"""<span class="text-green-400">✓ {bug.bug_id} → {new_status}</span>""")
