"""Trial Conversion Intelligence Dashboard — routes for trial monitoring and sales enablement.

Provides admin-facing views for tracking trial client activity, conversion scores,
and generating sales intelligence (summaries, outreach drafts).

All routes are protected by require_owner_or_partner dependency (Owner/Partner only).
"""

import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.trial_intelligence import require_owner_or_partner
from app.models.client import Client
from app.models.trial_failure import TrialFailure
from app.models.trial_score import TrialScore
from app.models.trial_signal import TrialSignal
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["trial-intelligence"])
templates = Jinja2Templates(directory="app/templates")

from app.version import __version__ as app_version
from app.config import get_settings as _get_settings

templates.env.globals["app_version"] = app_version
templates.env.globals["posting_disabled"] = lambda: _get_settings().posting_disabled


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_latest_scores(db: Session, client_ids: list[UUID]) -> dict[UUID, TrialScore]:
    """Get the latest TrialScore for each client_id using a subquery."""
    if not client_ids:
        return {}

    from sqlalchemy import and_

    # Subquery: max scored_at per client
    subq = (
        db.query(
            TrialScore.client_id,
            func.max(TrialScore.scored_at).label("max_scored_at"),
        )
        .filter(TrialScore.client_id.in_(client_ids))
        .group_by(TrialScore.client_id)
        .subquery()
    )

    scores = (
        db.query(TrialScore)
        .join(
            subq,
            and_(
                TrialScore.client_id == subq.c.client_id,
                TrialScore.scored_at == subq.c.max_scored_at,
            ),
        )
        .all()
    )

    return {s.client_id: s for s in scores}


def _days_remaining(client: Client) -> int:
    """Calculate trial days remaining (14-day trial)."""
    if not client.created_at:
        return 14
    now = datetime.now(client.created_at.tzinfo) if client.created_at.tzinfo else datetime.utcnow()
    elapsed = (now - client.created_at).days
    return max(0, 14 - elapsed)


# ---------------------------------------------------------------------------
# 13.2 — Main Dashboard
# ---------------------------------------------------------------------------

@router.get("/admin/trial-intelligence", response_class=HTMLResponse)
async def trial_dashboard(
    request: Request,
    sort_by: str = Query(
        "priority_score",
        pattern="^(priority_score|conversion_score|days_remaining|signup_date|opportunity_value)$",
    ),
    filter_activity: str | None = Query(None),
    filter_state: str | None = Query(None),
    days_min: int | None = Query(None),
    days_max: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_partner),
):
    """Main trial intelligence dashboard — shows all active trial clients sorted by priority."""
    # Load all active trial clients
    clients = (
        db.query(Client)
        .filter(Client.plan_type == "trial", Client.is_active.is_(True))
        .all()
    )

    client_ids = [c.id for c in clients]
    scores_map = _get_latest_scores(db, client_ids)

    # Build enriched client rows
    rows = []
    for client in clients:
        score = scores_map.get(client.id)
        days_left = _days_remaining(client)
        rows.append({
            "client": client,
            "score": score,
            "days_remaining": days_left,
            "priority_score": score.priority_score if score else 0,
            "conversion_score": score.conversion_score if score else 0,
            "opportunity_value": score.opportunity_value_cents if score else 0,
            "lifecycle_state": score.lifecycle_state if score else "unknown",
            "signup_date": client.created_at,
        })

    # Filter by activity level (from lifecycle_state mapping)
    if filter_activity:
        activity_map = {
            "high": ["activated", "engaged", "power_user"],
            "medium": ["exploring"],
            "low": ["onboarding", "dormant"],
            "none": ["unknown"],
        }
        allowed_states = activity_map.get(filter_activity, [])
        rows = [r for r in rows if r["lifecycle_state"] in allowed_states]

    # Filter by lifecycle state
    if filter_state:
        rows = [r for r in rows if r["lifecycle_state"] == filter_state]

    # Filter by days remaining range
    if days_min is not None:
        rows = [r for r in rows if r["days_remaining"] >= days_min]
    if days_max is not None:
        rows = [r for r in rows if r["days_remaining"] <= days_max]

    # Sort
    sort_key_map = {
        "priority_score": lambda r: r["priority_score"],
        "conversion_score": lambda r: r["conversion_score"],
        "days_remaining": lambda r: r["days_remaining"],
        "signup_date": lambda r: r["signup_date"] or datetime.min,
        "opportunity_value": lambda r: r["opportunity_value"],
    }
    sort_fn = sort_key_map.get(sort_by, sort_key_map["priority_score"])
    reverse = sort_by != "days_remaining"  # days_remaining: ascending (urgent first)
    rows.sort(key=sort_fn, reverse=reverse)

    # Summary stats
    total_active = len(rows)
    avg_conversion = (
        sum(r["conversion_score"] for r in rows) / total_active
        if total_active > 0
        else 0
    )
    total_pipeline_value = sum(r["opportunity_value"] for r in rows)  # in cents

    summary = {
        "total_active": total_active,
        "avg_conversion_score": round(avg_conversion, 1),
        "total_pipeline_value_dollars": total_pipeline_value / 100,
    }

    return templates.TemplateResponse(
        request,
        "admin_trial_intelligence.html",
        context={
            "request": request,
            "rows": rows,
            "summary": summary,
            "sort_by": sort_by,
            "filter_activity": filter_activity,
            "filter_state": filter_state,
            "days_min": days_min,
            "days_max": days_max,
            "current_user": current_user,
        },
    )


# ---------------------------------------------------------------------------
# 13.3 — Expired Trials Tab
# ---------------------------------------------------------------------------

@router.get("/admin/trial-intelligence/expired", response_class=HTMLResponse)
async def trial_expired(
    request: Request,
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_partner),
):
    """Expired trials — TrialFailure records with AI analysis and reactivation intel."""
    per_page = 25
    offset = (page - 1) * per_page

    total = db.query(func.count(TrialFailure.id)).scalar() or 0

    failures = (
        db.query(TrialFailure, Client)
        .join(Client, TrialFailure.client_id == Client.id)
        .order_by(TrialFailure.classified_at.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )

    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse(
        request,
        "admin_trial_expired.html",
        context={
            "request": request,
            "failures": failures,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "current_user": current_user,
        },
    )


# ---------------------------------------------------------------------------
# 13.4 — Funnel Partial (HTMX)
# ---------------------------------------------------------------------------

@router.get("/admin/trial-intelligence/funnel", response_class=HTMLResponse)
async def trial_funnel(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_partner),
):
    """HTMX partial: count trials per lifecycle state for funnel visualization."""
    # Get active trial client IDs
    client_ids = (
        db.query(Client.id)
        .filter(Client.plan_type == "trial", Client.is_active.is_(True))
        .all()
    )
    client_ids = [cid[0] for cid in client_ids]

    if not client_ids:
        return templates.TemplateResponse(
            request,
            "partials/trial_funnel.html",
            context={"request": request, "funnel": {}},
        )

    scores_map = _get_latest_scores(db, client_ids)

    # Count per lifecycle state
    funnel: dict[str, int] = {}
    for score in scores_map.values():
        state = score.lifecycle_state
        funnel[state] = funnel.get(state, 0) + 1

    return templates.TemplateResponse(
        request,
        "partials/trial_funnel.html",
        context={"request": request, "funnel": funnel},
    )


# ---------------------------------------------------------------------------
# 13.5 — Trial Detail View
# ---------------------------------------------------------------------------

@router.get("/admin/trial-intelligence/{client_id}", response_class=HTMLResponse)
async def trial_detail(
    request: Request,
    client_id: UUID,
    signals_page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_partner),
):
    """Trial detail view — client score, signals, intelligence events."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return HTMLResponse("<h2>Client not found</h2>", status_code=404)

    # Latest score
    latest_score = (
        db.query(TrialScore)
        .filter(TrialScore.client_id == client_id)
        .order_by(TrialScore.scored_at.desc())
        .first()
    )

    # Signals (paginated)
    signals_per_page = 20
    signals_offset = (signals_page - 1) * signals_per_page
    total_signals = (
        db.query(func.count(TrialSignal.id))
        .filter(TrialSignal.client_id == client_id)
        .scalar()
    ) or 0

    signals = (
        db.query(TrialSignal)
        .filter(TrialSignal.client_id == client_id)
        .order_by(TrialSignal.created_at.desc())
        .offset(signals_offset)
        .limit(signals_per_page)
        .all()
    )

    signals_total_pages = max(1, (total_signals + signals_per_page - 1) // signals_per_page)

    # Intelligence events (latest 20)
    from app.services.trial_events import IntelligenceEventLogger

    events = IntelligenceEventLogger.get_events(db, client_id, limit=20)

    # Log "opened_trial" event
    IntelligenceEventLogger.log_trial_opened(db, client_id, current_user.id)

    days_left = _days_remaining(client)

    return templates.TemplateResponse(
        request,
        "admin_trial_detail.html",
        context={
            "request": request,
            "client": client,
            "score": latest_score,
            "signals": signals,
            "signals_page": signals_page,
            "signals_total_pages": signals_total_pages,
            "total_signals": total_signals,
            "events": events,
            "days_remaining": days_left,
            "current_user": current_user,
        },
    )


# ---------------------------------------------------------------------------
# 13.6 — Generate Sales Summary (POST, HTMX)
# ---------------------------------------------------------------------------

@router.post("/admin/trial-intelligence/{client_id}/summary", response_class=HTMLResponse)
async def generate_sales_summary(
    request: Request,
    client_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_partner),
):
    """Generate or retrieve cached sales summary for a trial client."""
    from app.services.trial_summary import SalesSummaryGenerator
    from app.services.trial_events import IntelligenceEventLogger, IntelligenceEventType

    try:
        generator = SalesSummaryGenerator()
        result = generator.get_or_generate_summary(db, client_id)

        # Log event
        IntelligenceEventLogger.log_event(
            db,
            client_id,
            current_user.id,
            event_type=IntelligenceEventType.generated_summary,
            metadata={"source": "dashboard"},
        )
    except Exception as e:
        logger.exception("Failed to generate sales summary for client %s", client_id)
        result = {"status": "error", "message": str(e)}

    return templates.TemplateResponse(
        request,
        "partials/trial_summary_result.html",
        context={"request": request, "result": result, "client_id": client_id},
    )


# ---------------------------------------------------------------------------
# 13.7 — Generate Outreach (POST, HTMX)
# ---------------------------------------------------------------------------

@router.post("/admin/trial-intelligence/{client_id}/outreach", response_class=HTMLResponse)
async def generate_outreach(
    request: Request,
    client_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_partner),
):
    """Generate personalized outreach drafts for a trial client."""
    from app.services.trial_outreach import OutreachGenerator
    from app.services.trial_events import IntelligenceEventLogger, IntelligenceEventType

    # Get latest score to pass to generator
    latest_score = (
        db.query(TrialScore)
        .filter(TrialScore.client_id == client_id)
        .order_by(TrialScore.scored_at.desc())
        .first()
    )

    if not latest_score:
        return templates.TemplateResponse(
            request,
            "partials/trial_outreach_result.html",
            context={
                "request": request,
                "error": "No score available — cannot generate outreach.",
                "drafts": None,
                "client_id": client_id,
            },
        )

    try:
        generator = OutreachGenerator()
        drafts = generator.generate_outreach(db, client_id, latest_score.id)

        # Log event
        IntelligenceEventLogger.log_outreach_generated(
            db, client_id, current_user.id, outreach_type="all",
        )

        return templates.TemplateResponse(
            request,
            "partials/trial_outreach_result.html",
            context={
                "request": request,
                "drafts": drafts,
                "error": None,
                "client_id": client_id,
            },
        )
    except Exception as e:
        logger.exception("Failed to generate outreach for client %s", client_id)
        return templates.TemplateResponse(
            request,
            "partials/trial_outreach_result.html",
            context={
                "request": request,
                "error": f"Generation failed: {e}",
                "drafts": None,
                "client_id": client_id,
            },
        )


# ---------------------------------------------------------------------------
# 13.8 — Action Endpoints
# ---------------------------------------------------------------------------

@router.post("/admin/trial-intelligence/{client_id}/mark-contacted", response_class=HTMLResponse)
async def mark_contacted(
    request: Request,
    client_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_partner),
):
    """Mark a trial client as contacted — logs event and returns updated row partial."""
    from app.services.trial_events import IntelligenceEventLogger

    IntelligenceEventLogger.log_marked_contacted(db, client_id, current_user.id)

    # Reload client + score for updated row
    client = db.query(Client).filter(Client.id == client_id).first()
    latest_score = (
        db.query(TrialScore)
        .filter(TrialScore.client_id == client_id)
        .order_by(TrialScore.scored_at.desc())
        .first()
    )

    row = {
        "client": client,
        "score": latest_score,
        "days_remaining": _days_remaining(client) if client else 0,
        "priority_score": latest_score.priority_score if latest_score else 0,
        "conversion_score": latest_score.conversion_score if latest_score else 0,
        "opportunity_value": latest_score.opportunity_value_cents if latest_score else 0,
        "lifecycle_state": latest_score.lifecycle_state if latest_score else "unknown",
        "contacted": True,
    }

    return templates.TemplateResponse(
        request,
        "partials/trial_row.html",
        context={"request": request, "row": row},
    )


@router.post("/admin/trial-intelligence/{client_id}/schedule-followup", response_class=HTMLResponse)
async def schedule_followup(
    request: Request,
    client_id: UUID,
    date: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_partner),
):
    """Schedule a follow-up for a trial client."""
    from app.services.trial_events import IntelligenceEventLogger

    IntelligenceEventLogger.log_followup_scheduled(db, client_id, current_user.id, date)

    return HTMLResponse(
        f'<span class="text-green-400 text-sm">Follow-up scheduled for {date}</span>'
    )


@router.post("/admin/trial-intelligence/{client_id}/copy-outreach", response_class=HTMLResponse)
async def copy_outreach(
    request: Request,
    client_id: UUID,
    draft_type: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_partner),
):
    """Log that an outreach draft was copied to clipboard."""
    from app.services.trial_events import IntelligenceEventLogger

    IntelligenceEventLogger.log_outreach_copied(db, client_id, current_user.id, draft_type)

    return HTMLResponse(
        '<span class="text-green-400 text-sm">Copied!</span>'
    )
