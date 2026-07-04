"""Intelligence Report — Portal Routes.

Client-facing routes for viewing weekly intelligence reports (5-layer forecast
& reporting), report history, and triggering report regeneration.

RBAC:
  - View (weekly + history): client_viewer+ (via verify_client_access_from_path)
  - Regenerate: client_admin+ (explicit role check)
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc
from sqlalchemy.orm import Session
from uuid import UUID

from app.database import get_db
from app.dependencies.permissions import get_current_user, verify_client_access_from_path
from app.logging_config import get_logger
from app.models.client import Client
from app.models.intelligence_report import ClientIntelligenceReport
from app.models.user import User
from app.models.user_role import UserRole

logger = get_logger(__name__)

router = APIRouter(
    dependencies=[Depends(verify_client_access_from_path)],
    tags=["intelligence-report"],
)
templates = Jinja2Templates(directory="app/templates")

from app.version import __version__ as app_version
from app.config import get_settings as _get_settings

templates.env.globals["app_version"] = app_version
templates.env.globals["posting_disabled"] = lambda: _get_settings().posting_disabled
templates.env.globals["app_env"] = _get_settings().app_env

from app.template_filters import register_filters

register_filters(templates.env)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _get_client_or_404(db: Session, client_id: UUID) -> Client:
    """Load client by ID or raise 404."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _require_client_admin_role(user: User) -> None:
    """Check user has client_admin+ role (owner, partner, client_admin).

    Raises 403 if user does not have sufficient privileges.
    """
    allowed = (UserRole.owner, UserRole.partner, UserRole.client_admin)
    if user.user_role not in allowed and not user.is_superuser:
        raise HTTPException(status_code=403, detail="Access Denied")


# ─── Routes ─────────────────────────────────────────────────────────────────


@router.get("/clients/{client_id}/report/weekly", response_class=HTMLResponse)
async def view_weekly_report(
    request: Request,
    client_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Render the latest published (or draft) intelligence report.

    RBAC: client_viewer+ can view (enforced by verify_client_access_from_path).
    """
    client = _get_client_or_404(db, client_id)

    # Query latest report: prefer published, fall back to draft
    report = (
        db.query(ClientIntelligenceReport)
        .filter(
            ClientIntelligenceReport.client_id == client_id,
            ClientIntelligenceReport.status.in_(["published", "draft"]),
        )
        .order_by(desc(ClientIntelligenceReport.generated_at))
        .first()
    )

    if not report:
        # No report yet — render empty state
        return templates.TemplateResponse(
            name="client/intelligence_report_empty.html",
            context={
                "request": request,
                "client": client,
                "client_id": str(client_id),
                "active_page": "report_weekly",
            },
            request=request,
        )

    return templates.TemplateResponse(
        name="client/intelligence_report.html",
        context={
            "request": request,
            "client": client,
            "client_id": str(client_id),
            "report": report,
            "active_page": "report_weekly",
        },
        request=request,
    )


@router.get("/clients/{client_id}/report/history", response_class=HTMLResponse)
async def report_history(
    request: Request,
    client_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all intelligence reports for this client, ordered by most recent.

    RBAC: client_viewer+ can view (enforced by verify_client_access_from_path).
    """
    client = _get_client_or_404(db, client_id)

    reports = (
        db.query(ClientIntelligenceReport)
        .filter(ClientIntelligenceReport.client_id == client_id)
        .order_by(desc(ClientIntelligenceReport.generated_at))
        .all()
    )

    return templates.TemplateResponse(
        name="client/report_history.html",
        context={
            "request": request,
            "client": client,
            "client_id": str(client_id),
            "reports": reports,
            "active_page": "report_history",
        },
        request=request,
    )


@router.post("/clients/{client_id}/report/generate", response_class=HTMLResponse)
async def trigger_report_generation(
    request: Request,
    client_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Trigger regeneration of the intelligence report for this client.

    RBAC: client_admin+ required (owner, partner, client_admin).
    """
    _require_client_admin_role(user)
    client = _get_client_or_404(db, client_id)

    try:
        from app.services.forecast.report_composer import ReportComposer

        composer = ReportComposer()
        report = composer.compose_full_report(db, client_id)
        logger.info(
            "Intelligence report generated | client_id=%s | report_id=%s | period=%s",
            client_id,
            report.id,
            report.report_period,
        )
    except Exception as e:
        logger.error(
            "Intelligence report generation failed | client_id=%s | error=%s",
            client_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Report generation failed: {str(e)}",
        )

    # Return HTMX-friendly redirect or fallback
    if request.headers.get("HX-Request"):
        # HTMX request — redirect via HX-Redirect header
        return HTMLResponse(
            content="<p>Report generated successfully. Redirecting...</p>",
            headers={"HX-Redirect": f"/clients/{client_id}/report/weekly"},
        )

    # Non-HTMX — standard redirect
    from fastapi.responses import RedirectResponse

    return RedirectResponse(
        url=f"/clients/{client_id}/report/weekly", status_code=303
    )


# ─── HTMX Lazy-Load Partials (Chart Sections) ──────────────────────────────
# These endpoints return just the chart HTML + script for lazy-loading via
# hx-get with hx-trigger="load". Currently renders inline (v1), but the
# HTMX attributes are ready for future extraction.


@router.get(
    "/clients/{client_id}/report/chart/trend", response_class=HTMLResponse
)
async def chart_trend_partial(
    request: Request,
    client_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """HTMX partial: trend chart (measured vs projected visibility over time).

    Returns a <canvas> + <script> fragment for lazy-loading.
    """
    report = (
        db.query(ClientIntelligenceReport)
        .filter(
            ClientIntelligenceReport.client_id == client_id,
            ClientIntelligenceReport.status.in_(["published", "draft"]),
        )
        .order_by(desc(ClientIntelligenceReport.generated_at))
        .first()
    )

    if not report:
        return HTMLResponse(
            content='<p style="color: var(--color-muted); text-align: center;">No data available</p>'
        )

    return templates.TemplateResponse(
        name="client/partials/report_trend_chart.html",
        context={
            "request": request,
            "report": report,
            "client_id": str(client_id),
        },
        request=request,
    )


@router.get(
    "/clients/{client_id}/report/chart/competitors", response_class=HTMLResponse
)
async def chart_competitors_partial(
    request: Request,
    client_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """HTMX partial: competitor bar chart.

    Returns a <canvas> + <script> fragment for lazy-loading.
    """
    report = (
        db.query(ClientIntelligenceReport)
        .filter(
            ClientIntelligenceReport.client_id == client_id,
            ClientIntelligenceReport.status.in_(["published", "draft"]),
        )
        .order_by(desc(ClientIntelligenceReport.generated_at))
        .first()
    )

    if not report:
        return HTMLResponse(
            content='<p style="color: var(--color-muted); text-align: center;">No competitor data available</p>'
        )

    return templates.TemplateResponse(
        name="client/partials/report_competitor_chart.html",
        context={
            "request": request,
            "report": report,
            "client_id": str(client_id),
        },
        request=request,
    )
