"""Admin LLM Quality Monitoring route — /admin/llm-quality."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.models.user import User
from app.routes.admin import templates

router = APIRouter()


@router.get("/admin/llm-quality")
def admin_llm_quality(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
    period: str = "24h",
):
    """LLM Quality Monitoring dashboard — shows model health, degradation events, and trends."""
    from app.services.llm_quality_monitor import get_quality_summary, get_degradation_alerts

    period_map = {"4h": 4, "12h": 12, "24h": 24, "7d": 168}
    hours = period_map.get(period, 24)

    summary = get_quality_summary(db, hours=hours)
    alerts = get_degradation_alerts(db, hours=hours)

    return templates.TemplateResponse(
        name="admin_llm_quality.html",
        context={
            "request": request,
            "active_nav": "llm-quality",
            "summary": summary,
            "alerts": alerts,
            "active_period": period,
        },
    )
