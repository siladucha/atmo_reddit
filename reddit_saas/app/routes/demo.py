"""Demo Report — Public Routes.

Publicly accessible demo-style intelligence reports for sales calls.
URL shared manually with prospects. No authentication required.

Features:
  - noindex, nofollow (not indexed by search engines)
  - No auth dependency (public access)
  - Standalone page (no portal navigation)
  - Same data structure as the client portal report
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from app.templating import Jinja2Templates
from sqlalchemy import desc
from sqlalchemy.orm import Session
from uuid import UUID

from app.database import get_db
from app.logging_config import get_logger
from app.models.client import Client
from app.models.intelligence_report import ClientIntelligenceReport

logger = get_logger(__name__)

router = APIRouter(tags=["demo"])
templates = Jinja2Templates(directory="app/templates")

from app.template_filters import register_filters

register_filters(templates.env)


# ─── Demo Report Route ──────────────────────────────────────────────────────


@router.get("/demo/report/{client_id}", response_class=HTMLResponse)
async def demo_report(
    request: Request,
    client_id: UUID,
    db: Session = Depends(get_db),
):
    """Render a demo-style intelligence report for sales calls.

    Publicly accessible, noindex. URL shared manually with prospects.
    Shows the same data as the client portal report but in a standalone page
    (no portal navigation, no login required).
    """
    # Load client
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return templates.TemplateResponse(
            name="demo/report_not_available.html",
            context={"request": request, "reason": "Client not found."},
            request=request,
        )

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
        return templates.TemplateResponse(
            name="demo/report_not_available.html",
            context={"request": request, "reason": "Report not yet available."},
            request=request,
        )

    return templates.TemplateResponse(
        name="demo/intelligence_report_demo.html",
        context={
            "request": request,
            "client": client,
            "report": report,
        },
        request=request,
    )
