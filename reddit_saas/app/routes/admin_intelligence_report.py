"""Admin Intelligence Report — HTMX partials for client detail page.

Provides:
  - Report status panel (latest report overview)
  - Manual "Generate Report Now" trigger (dispatches Celery task)
  - Raw JSONB viewer for debugging
  - Forecast accuracy dashboard (hit/miss rates over time)

RBAC: require_superuser (owner/partner).
"""

import json
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.logging_config import get_logger
from app.models.intelligence_report import ClientIntelligenceReport
from app.models.user import User

logger = get_logger(__name__)

router = APIRouter(
    dependencies=[Depends(require_superuser)],
    tags=["admin-intelligence-report"],
)
templates = Jinja2Templates(directory="app/templates")

from app.version import __version__ as app_version
from app.config import get_settings as _get_settings

templates.env.globals["app_version"] = app_version
templates.env.globals["posting_disabled"] = lambda: _get_settings().posting_disabled
templates.env.globals["app_env"] = _get_settings().app_env

from app.template_filters import register_filters

register_filters(templates.env)


@router.get("/admin/clients/{client_id}/report/panel", response_class=HTMLResponse)
async def admin_report_panel(
    request: Request,
    client_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_superuser),
):
    """HTMX partial: report status panel for admin client detail page."""
    latest_report = (
        db.query(ClientIntelligenceReport)
        .filter(ClientIntelligenceReport.client_id == client_id)
        .order_by(desc(ClientIntelligenceReport.generated_at))
        .first()
    )

    # Get accuracy summary
    accuracy = None
    try:
        from app.services.forecast.accuracy_tracker import get_accuracy_summary

        accuracy = get_accuracy_summary(db, client_id)
    except Exception as e:
        logger.debug("Accuracy summary unavailable: %s", e)

    return templates.TemplateResponse(
        name="partials/admin_report_panel.html",
        context={
            "request": request,
            "client_id": str(client_id),
            "latest_report": latest_report,
            "accuracy": accuracy,
        },
        request=request,
    )


@router.post("/admin/clients/{client_id}/report/generate", response_class=HTMLResponse)
async def admin_generate_report(
    request: Request,
    client_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_superuser),
):
    """Trigger intelligence report generation (dispatches Celery task)."""
    from app.tasks.intelligence_report import generate_intelligence_report_for_client

    generate_intelligence_report_for_client.delay(str(client_id))

    logger.info(
        "Admin report generation triggered | client_id=%s | user=%s",
        client_id,
        user.email,
    )

    # Return a success toast + re-fetch the panel via HTMX
    return HTMLResponse(
        content="""
        <div id="report-panel"
             hx-get="/admin/clients/{client_id}/report/panel"
             hx-trigger="load delay:3s"
             hx-swap="outerHTML">
            <div class="bg-green-900/40 border border-green-700 rounded-lg p-3 text-sm text-green-300">
                ✓ Report generation dispatched. Refresh in a few seconds...
            </div>
        </div>
        """.replace("{client_id}", str(client_id)),
    )


@router.get("/admin/clients/{client_id}/report/json", response_class=HTMLResponse)
async def admin_report_json_view(
    request: Request,
    client_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_superuser),
):
    """View raw JSONB for the latest report (debugging)."""
    latest_report = (
        db.query(ClientIntelligenceReport)
        .filter(ClientIntelligenceReport.client_id == client_id)
        .order_by(desc(ClientIntelligenceReport.generated_at))
        .first()
    )

    if not latest_report:
        return HTMLResponse(
            content='<p class="text-gray-500 text-sm italic">No report available.</p>'
        )

    # Format each JSONB field
    json_sections = {
        "observed_json": json.dumps(latest_report.observed_json, indent=2, default=str),
        "planned_json": json.dumps(latest_report.planned_json, indent=2, default=str),
        "forecasted_json": json.dumps(latest_report.forecasted_json, indent=2, default=str),
        "risks_json": json.dumps(latest_report.risks_json, indent=2, default=str),
        "business_impact_json": json.dumps(latest_report.business_impact_json, indent=2, default=str),
    }

    return templates.TemplateResponse(
        name="partials/admin_report_json.html",
        context={
            "request": request,
            "client_id": str(client_id),
            "json_sections": json_sections,
            "report": latest_report,
        },
        request=request,
    )


@router.get("/admin/clients/{client_id}/report/accuracy", response_class=HTMLResponse)
async def admin_accuracy_dashboard(
    request: Request,
    client_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_superuser),
):
    """Forecast accuracy dashboard partial."""
    from app.services.forecast.accuracy_tracker import get_accuracy_summary

    accuracy = get_accuracy_summary(db, client_id)

    return templates.TemplateResponse(
        name="partials/admin_report_accuracy.html",
        context={
            "request": request,
            "client_id": str(client_id),
            "accuracy": accuracy,
        },
        request=request,
    )
