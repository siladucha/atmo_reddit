"""Discovery Engine routes — admin panel UI for Reddit ecosystem research.

All routes require platform admin (owner/partner) role.
UI is HTMX-driven: single session page with partial swaps for each step.
"""

import uuid
from app.logging_config import get_logger
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.templating import Jinja2Templates

from app.database import get_db
from app.dependencies.permissions import require_platform_admin
from app.models.discovery_hypothesis import DiscoveryHypothesis
from app.models.discovery_session import DiscoverySession
from app.models.user import User
from app.services.discovery.entity_extractor import extract_entities
from app.services.discovery.hypothesis_engine import form_hypotheses
from app.services.discovery.report_generator import generate_visibility_report
from app.services.discovery.session_manager import SessionManager
from app.services.discovery.strategy_handoff import execute_handoff, prepare_handoff_context
from app.tasks.discovery import research_hypotheses_task

logger = get_logger(__name__)


# Maximum confirmed hypotheses per session — keeps reports focused and cost-effective
MAX_CONFIRMED_HYPOTHESES = 7

router = APIRouter(prefix="/admin/discovery", tags=["discovery"])
templates = Jinja2Templates(directory="app/templates")

from app.version import __version__ as app_version
from app.config import get_settings as _get_settings
templates.env.globals["app_version"] = app_version
templates.env.globals["posting_disabled"] = lambda: _get_settings().posting_disabled
templates.env.globals["app_env"] = _get_settings().app_env


# --- Pages ---


@router.get("/rate-limit", response_class=HTMLResponse)
def discovery_rate_limit(
    request: Request,
    current_user: User = Depends(require_platform_admin),
):
    """HTMX endpoint: Reddit API rate limit utilization widget."""
    try:
        from app.services.reddit import _get_global_rate_limiter
        from app.services.settings import get_setting
        from app.database import SessionLocal

        limiter = _get_global_rate_limiter()
        if limiter is None:
            return HTMLResponse('<span class="text-xs text-gray-500">Rate limiter unavailable</span>')

        db = SessionLocal()
        try:
            max_rpm_str = get_setting(db, "scrape_rate_limit_rpm")
            max_rpm = int(max_rpm_str) if max_rpm_str else 30
        finally:
            db.close()

        stats = limiter.get_utilization(max_rpm)

        # Color based on utilization
        if stats["utilization_pct"] >= 80:
            bar_color = "bg-red-500"
            text_color = "text-red-400"
        elif stats["utilization_pct"] >= 50:
            bar_color = "bg-amber-500"
            text_color = "text-amber-400"
        else:
            bar_color = "bg-green-500"
            text_color = "text-green-400"

        pct = min(100, stats["utilization_pct"])
        backoff_html = ""
        if stats["in_backoff"]:
            backoff_html = '<div class="mt-1.5 text-[10px] text-amber-400">⚠ Backoff mode (429 detected)</div>'

        html = (
            '<h3 class="text-xs font-medium text-gray-400 uppercase mb-2">Reddit API</h3>'
            '<div class="flex items-center justify-between mb-1.5">'
            f'<span class="text-xs text-gray-400">{stats["current_count"]} / {stats["effective_limit"]} rpm</span>'
            f'<span class="text-xs {text_color} font-mono">{stats["utilization_pct"]}%</span>'
            '</div>'
            '<div class="w-full bg-gray-700 rounded-full h-2">'
            f'<div class="h-2 rounded-full {bar_color} transition-all" style="width: {pct}%"></div>'
            '</div>'
            f'{backoff_html}'
        )
        return HTMLResponse(html)
    except Exception as e:
        return HTMLResponse(f'<span class="text-xs text-gray-500">Error: {str(e)[:50]}</span>')


@router.get("", response_class=HTMLResponse)
def discovery_list(
    request: Request,
    page: int = 1,
    status: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Discovery session list page."""
    sessions, total = SessionManager.list_sessions(db, page=page, per_page=25, status_filter=status)
    total_pages = (total + 24) // 25

    return templates.TemplateResponse(
        request,
        "admin_discovery.html",
        {
            "sessions": sessions,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "status_filter": status,
            "current_user": current_user,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def discovery_new(
    request: Request,
    client_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """New Discovery session form."""
    from app.models.client import Client

    clients = db.query(Client).filter(Client.is_active == True).order_by(Client.client_name).all()

    # Support pre-filling client dropdown via query param
    default_client_id = client_id.strip() if client_id else ""

    return templates.TemplateResponse(
        request,
        "admin_discovery_new.html",
        {
            "clients": clients,
            "current_user": current_user,
            "default_client_id": default_client_id,
        },
    )


@router.post("/demo", response_class=HTMLResponse)
def discovery_create_demo(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Create a pre-built demo Discovery session (no Reddit API needed).

    Instantly creates a completed session with realistic data for Zoom demos.
    Redirects to the results page.
    """
    from app.services.discovery.demo_seed import create_demo_session

    session = create_demo_session(db, operator_user_id=current_user.id)

    from fastapi.responses import RedirectResponse
    return RedirectResponse(
        url=f"/admin/discovery/{session.id}/results",
        status_code=303,
    )


@router.post("/{session_id}/create-avatar", response_class=HTMLResponse)
def discovery_create_avatar(
    request: Request,
    session_id: uuid.UUID,
    reddit_username: str = Form(...),
    hobby_subreddits: str = Form(""),
    voice_profile_md: str = Form(""),
    hill_i_die_on: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Create an avatar from Discovery context — pre-configured with recommended subreddits.

    This is the bridge: Discovery Results → "Create Avatar" button → Avatar ready for EPG.
    Business subreddits auto-populated from Discovery's recommended communities.
    """
    from app.services.avatar_onboarding import create_avatar_from_context

    session = SessionManager.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.client_id:
        raise HTTPException(status_code=400, detail="Session must be linked to a client first (run handoff)")

    # Parse hobby subs from comma-separated string
    hobby_list = [s.strip() for s in hobby_subreddits.split(",") if s.strip()] if hobby_subreddits else None

    try:
        avatar = create_avatar_from_context(
            db=db,
            reddit_username=reddit_username.strip(),
            client_id=session.client_id,
            discovery_session_id=session_id,
            hobby_subreddits=hobby_list,
            voice_profile_md=voice_profile_md.strip(),
            hill_i_die_on=hill_i_die_on.strip(),
            operator_user_id=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    from fastapi.responses import RedirectResponse
    return RedirectResponse(
        url=f"/admin/avatars/{avatar.id}",
        status_code=303,
    )


@router.post("/new", response_class=HTMLResponse)
async def discovery_create(
    request: Request,
    client_brief: str = Form(...),
    prospect_name: str = Form(None),
    client_id: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Create session + extract entities → redirect to session page."""
    # Validate brief length
    if len(client_brief.strip()) < 50:
        return templates.TemplateResponse(
            request,
            "partials/discovery_brief_form.html",
            {
                "error": f"Brief must be at least 50 characters. Currently: {len(client_brief.strip())}.",
                "client_brief": client_brief,
                "prospect_name": prospect_name,
            },
            status_code=422,
        )

    # Create session
    parsed_client_id = uuid.UUID(client_id) if client_id and client_id.strip() else None
    session = SessionManager.create_session(
        db=db,
        operator_id=current_user.id,
        client_brief=client_brief.strip(),
        prospect_name=prospect_name.strip() if prospect_name else None,
        client_id=parsed_client_id,
    )

    # Extract entities (async LLM call)
    try:
        entities = await extract_entities(client_brief.strip(), db, session.id)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Entity extraction failed: {e}")
        return templates.TemplateResponse(
            request,
            "partials/discovery_brief_form.html",
            {
                "error": f"Entity extraction failed: {str(e)[:200]}. Please try again.",
                "client_brief": client_brief,
                "prospect_name": prospect_name,
            },
            status_code=500,
        )

    # Audit log: session created
    try:
        from app.services.audit import log_action
        log_action(
            db=db,
            user_id=current_user.id,
            action="discovery_session_created",
            entity_type="discovery_session",
            entity_id=session.id,
            details={
                "prospect_name": prospect_name,
                "client_id": str(parsed_client_id) if parsed_client_id else None,
                "entities_extracted": entities.get("count", 0),
            },
        )
        db.commit()
    except Exception:
        pass

    # Redirect to session page (HTMX will swap content)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(
        url=f"/admin/discovery/{session.id}",
        status_code=303,
    )


@router.get("/{session_id}", response_class=HTMLResponse)
def discovery_session_page(
    request: Request,
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Active session page — renders appropriate step based on state."""
    session = SessionManager.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    current_step = SessionManager.get_current_step(session)

    # Build context needed by all partials
    current_hypos = [
        h for h in session.hypotheses
        if h.iteration_number == session.current_iteration
    ]

    return templates.TemplateResponse(
        request,
        "admin_discovery_session.html",
        {
            "session": session,
            "current_step": current_step,
            "current_user": current_user,
            "can_generate_report": SessionManager.can_generate_report(session),
            "is_max_iterations": SessionManager.is_at_max_iterations(session),
            "max_confirmed": MAX_CONFIRMED_HYPOTHESES,
            "total_confirmed": len([h for h in session.hypotheses if h.status == "confirmed"]),
            "hypotheses": current_hypos,
            "entities": list(session.entities),
        },
    )


@router.get("/{session_id}/results", response_class=HTMLResponse)
def discovery_results_page(
    request: Request,
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Stable results page — shareable URL showing complete session data.

    Shows: entities, hypotheses (with confidence + signals), report content,
    AI costs, full audit trail of prompts/responses/decisions.
    This is the "Day 1 Report" page Tzvi shares with prospects.
    """
    session = SessionManager.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get latest report
    report = None
    if session.reports:
        report = sorted(session.reports, key=lambda r: r.report_version, reverse=True)[0]

    # Get all entities grouped by category
    entities_by_category = {}
    for entity in session.entities:
        cat = entity.category or "other"
        entities_by_category.setdefault(cat, []).append(entity)

    # Get hypotheses grouped by status
    confirmed = [h for h in session.hypotheses if h.status == "confirmed"]
    rejected = [h for h in session.hypotheses if h.status == "rejected"]
    proposed = [h for h in session.hypotheses if h.status == "proposed"]

    # Get AI usage logs for this session
    from app.models.ai_usage import AIUsageLog
    ai_logs = (
        db.query(AIUsageLog)
        .filter(AIUsageLog.triggered_by == f"discovery:{session_id}")
        .order_by(AIUsageLog.created_at.asc())
        .all()
    )

    # Get activity events related to this session
    from app.models.activity_event import ActivityEvent
    events = (
        db.query(ActivityEvent)
        .filter(
            ActivityEvent.event_type.like("discovery%"),
            ActivityEvent.event_metadata["session_id"].astext == str(session_id),
        )
        .order_by(ActivityEvent.created_at.asc())
        .all()
    )

    # Get handoff context if session is completed and linked to a client
    handoff_context = None
    if session.status == "completed" and session.client_id:
        try:
            handoff_context = prepare_handoff_context(session)
        except Exception:
            pass

    return templates.TemplateResponse(
        request,
        "admin_discovery_results.html",
        {
            "session": session,
            "report": report,
            "report_content": report.content if report else {},
            "entities_by_category": entities_by_category,
            "confirmed_hypotheses": confirmed,
            "rejected_hypotheses": rejected,
            "proposed_hypotheses": proposed,
            "ai_logs": ai_logs,
            "activity_events": events,
            "handoff_context": handoff_context,
            "total_ai_cost": session.total_ai_cost_usd,
            "current_user": current_user,
        },
    )


@router.get("/{session_id}/results/json")
def discovery_results_json(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """API: Full session results as JSON — for programmatic access and traceability."""
    session = SessionManager.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    report = None
    if session.reports:
        report = sorted(session.reports, key=lambda r: r.report_version, reverse=True)[0]

    return {
        "session_id": str(session.id),
        "status": session.status,
        "prospect_name": session.prospect_name,
        "client_id": str(session.client_id) if session.client_id else None,
        "client_brief": session.client_brief,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "total_ai_cost_usd": float(session.total_ai_cost_usd),
        "iterations": session.current_iteration,
        "entities": [
            {
                "id": str(e.id),
                "name": e.name,
                "category": e.category,
                "source": e.source,
            }
            for e in session.entities
        ],
        "hypotheses": [
            {
                "id": str(h.id),
                "statement": h.statement,
                "category": h.category,
                "status": h.status,
                "confidence_score": h.confidence_score,
                "reddit_signals": h.reddit_signals,
                "provenance": h.provenance,
                "created_at": h.created_at.isoformat() if h.created_at else None,
                "decided_at": h.decided_at.isoformat() if h.decided_at else None,
            }
            for h in session.hypotheses
        ],
        "report": {
            "content": report.content if report else None,
            "generated_at": report.generated_at.isoformat() if report else None,
            "model_used": report.model_used if report else None,
            "cost_usd": float(report.generation_cost_usd) if report else None,
            "operator_notes": report.operator_notes if report else None,
        },
        "metadata": session.session_metadata,
    }


# --- Iteration Flow ---


@router.post("/{session_id}/entities", response_class=HTMLResponse)
async def confirm_entities(
    request: Request,
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Operator confirms entities → trigger hypothesis formation."""
    session = SessionManager.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Form hypotheses (async LLM call)
    prior = [h for h in session.hypotheses if h.iteration_number < session.current_iteration]

    try:
        hypotheses = await form_hypotheses(
            entities=list(session.entities),
            session=session,
            db=db,
            prior_hypotheses=prior if prior else None,
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Hypothesis formation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Hypothesis formation failed: {e}")

    # Return hypotheses partial
    return templates.TemplateResponse(
        request,
        "partials/discovery_hypotheses.html",
        {
            "session": session,
            "hypotheses": hypotheses,
        },
    )


@router.post("/{session_id}/research", response_class=HTMLResponse)
def trigger_research(
    request: Request,
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Trigger Reddit research as Celery background task."""
    session = SessionManager.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get current iteration hypotheses
    current_hypos = [
        h for h in session.hypotheses
        if h.iteration_number == session.current_iteration and h.status == "proposed"
    ]

    if not current_hypos:
        raise HTTPException(status_code=400, detail="No hypotheses to research")

    hypothesis_ids = [str(h.id) for h in current_hypos]

    # Dispatch Celery task
    research_hypotheses_task.delay(str(session_id), hypothesis_ids)

    # Audit log: research started
    try:
        from app.services.audit import log_action
        log_action(
            db=db,
            user_id=current_user.id,
            action="discovery_research_started",
            entity_type="discovery_session",
            entity_id=session_id,
            details={"hypothesis_count": len(hypothesis_ids), "iteration": session.current_iteration},
        )
        db.commit()
    except Exception:
        pass

    # Return progress partial
    return templates.TemplateResponse(
        request,
        "partials/discovery_research_progress.html",
        {
            "session": session,
            "hypotheses": current_hypos,
        },
    )


@router.post("/{session_id}/stop-research", response_class=HTMLResponse)
def stop_research(
    request: Request,
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Stop ongoing research — mark remaining hypotheses as skipped."""
    session = SessionManager.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Mark all queued/researching as complete in progress metadata
    progress = (session.session_metadata or {}).get("research_progress", {})
    for hid, status in progress.items():
        if status in ("queued", "researching"):
            progress[hid] = "complete"
            # Mark the hypothesis as skipped
            hypothesis = db.query(DiscoveryHypothesis).filter(
                DiscoveryHypothesis.id == uuid.UUID(hid)
            ).first()
            if hypothesis and not hypothesis.reddit_signals:
                hypothesis.status = "research_failed"

    session.session_metadata = {
        **(session.session_metadata or {}),
        "research_progress": progress,
        "research_stopped_by": str(current_user.id),
    }
    db.commit()

    # Revoke the Celery task if possible
    try:
        from app.tasks.worker import celery_app as celery
        celery.control.revoke(f"discovery_research_{session_id}", terminate=True)
    except Exception:
        pass  # Best-effort revocation

    # Return updated progress (all_done will be true)
    current_hypos = [
        h for h in session.hypotheses
        if h.iteration_number == session.current_iteration
    ]

    # Refresh from DB
    db.refresh(session)
    for h in current_hypos:
        db.refresh(h)

    return templates.TemplateResponse(
        request,
        "partials/discovery_research_progress.html",
        {
            "session": session,
            "hypotheses": current_hypos,
        },
    )


@router.get("/{session_id}/progress", response_class=HTMLResponse)
def research_progress(
    request: Request,
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """HTMX poll endpoint: returns research progress per hypothesis."""
    session = db.query(DiscoverySession).filter(DiscoverySession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    progress = (session.session_metadata or {}).get("research_progress", {})
    all_done = all(v == "complete" for v in progress.values()) if progress else False

    current_hypos = (
        db.query(DiscoveryHypothesis)
        .filter(
            DiscoveryHypothesis.session_id == session_id,
            DiscoveryHypothesis.iteration_number == session.current_iteration,
        )
        .all()
    )

    if all_done:
        # Research complete — return results partial
        return templates.TemplateResponse(
            request,
            "partials/discovery_results.html",
            {
                "session": session,
                "hypotheses": current_hypos,
                "can_generate_report": SessionManager.can_generate_report(session),
                "is_max_iterations": SessionManager.is_at_max_iterations(session),
                "max_confirmed": MAX_CONFIRMED_HYPOTHESES,
                "total_confirmed": len([h for h in session.hypotheses if h.status == "confirmed"]),
            },
        )

    # Still in progress — return progress partial (will be polled again)
    return templates.TemplateResponse(
        request,
        "partials/discovery_research_progress.html",
        {
            "session": session,
            "hypotheses": current_hypos,
            "progress": progress,
        },
    )


@router.post("/{session_id}/decide", response_class=HTMLResponse)
async def decide_hypotheses(
    request: Request,
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Process operator confirm/reject decisions on hypotheses."""
    session = SessionManager.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Parse form data
    form = await request.form()

    current_hypos = [
        h for h in session.hypotheses
        if h.iteration_number == session.current_iteration
    ]

    # Count already confirmed across ALL iterations (session-wide limit)
    already_confirmed = len([
        h for h in session.hypotheses if h.status == "confirmed"
    ])

    decisions_made = 0
    confirmed_count = 0
    rejected_count = 0
    limit_hit = False

    for h in current_hypos:
        if h.status != "proposed":
            continue

        decision = form.get(f"decision_{h.id}")
        if not decision:
            continue

        if decision == "confirm":
            # Enforce session-wide cap
            if already_confirmed + confirmed_count >= MAX_CONFIRMED_HYPOTHESES:
                limit_hit = True
                continue
            h.status = "confirmed"
            h.decided_at = datetime.now(timezone.utc)
            decisions_made += 1
            confirmed_count += 1
        elif decision == "reject":
            reason = form.get(f"reject_reason_{h.id}", "").strip()
            h.status = "rejected"
            h.rejection_reason = reason[:500] if reason else None
            h.decided_at = datetime.now(timezone.utc)
            decisions_made += 1
            rejected_count += 1

    if decisions_made > 0:
        # Audit log
        try:
            from app.services.audit import log_action
            log_action(
                db=db,
                user_id=current_user.id,
                action="discovery_decisions_submitted",
                entity_type="discovery_session",
                entity_id=session_id,
                details={
                    "confirmed": confirmed_count,
                    "rejected": rejected_count,
                    "limit_hit": limit_hit,
                    "iteration": session.current_iteration,
                },
            )
        except Exception:
            pass

        db.commit()
        # Refresh session to get updated relationships
        db.refresh(session)
        current_hypos = [
            h for h in session.hypotheses
            if h.iteration_number == session.current_iteration
        ]

    return templates.TemplateResponse(
        request,
        "partials/discovery_results.html",
        {
            "session": session,
            "hypotheses": current_hypos,
            "can_generate_report": SessionManager.can_generate_report(session),
            "is_max_iterations": SessionManager.is_at_max_iterations(session),
            "max_confirmed": MAX_CONFIRMED_HYPOTHESES,
            "total_confirmed": already_confirmed + confirmed_count,
            "limit_hit": limit_hit,
        },
    )


@router.post("/{session_id}/report", response_class=HTMLResponse)
async def generate_report(
    request: Request,
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Generate Visibility Report from confirmed hypotheses."""
    session = SessionManager.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not SessionManager.can_generate_report(session):
        raise HTTPException(status_code=400, detail="Cannot generate report: need at least 1 confirmed hypothesis")

    try:
        report = await generate_visibility_report(session, db)
        # generate_visibility_report already commits; no double-commit needed
    except Exception as e:
        db.rollback()
        logger.error(f"Report generation failed: {e}")
        # Return inline error HTML so HTMX shows it to the user
        error_html = (
            '<div class="p-4 bg-red-900/30 border border-red-700 rounded-lg">'
            '<h3 class="text-red-300 font-medium mb-1">Report Generation Failed</h3>'
            f'<p class="text-red-400 text-sm">{str(e)[:500]}</p>'
            '<p class="text-gray-400 text-xs mt-2">Try again — if the issue persists, check LLM logs.</p>'
            '</div>'
        )
        return HTMLResponse(error_html, status_code=200)

    # Refresh session to ensure reports relationship is loaded
    db.refresh(session)

    return templates.TemplateResponse(
        request,
        "partials/discovery_report.html",
        {
            "session": session,
            "report": report,
        },
    )


@router.get("/{session_id}/report/export", response_class=HTMLResponse)
def export_report(
    request: Request,
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Render branded HTML report for print/PDF export."""
    session = SessionManager.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.reports:
        raise HTTPException(status_code=400, detail="No report generated yet")

    report = sorted(session.reports, key=lambda r: r.report_version, reverse=True)[0]

    return templates.TemplateResponse(
        request,
        "partials/discovery_report_export.html",
        {
            "session": session,
            "report": report,
            "content": report.content or {},
        },
    )


@router.post("/{session_id}/report/edit", response_class=HTMLResponse)
def edit_report_notes(
    request: Request,
    session_id: uuid.UUID,
    operator_notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Save operator notes on the report."""
    session = SessionManager.get_session(db, session_id)
    if not session or not session.reports:
        raise HTTPException(status_code=404, detail="Session or report not found")

    report = sorted(session.reports, key=lambda r: r.report_version, reverse=True)[0]
    report.operator_notes = operator_notes[:5000]
    db.commit()

    return HTMLResponse('<span class="text-green-400">✓ Notes saved</span>')


@router.post("/{session_id}/handoff", response_class=HTMLResponse)
def handoff_to_strategy(
    request: Request,
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Execute Discovery → Client Strategy handoff (with LLM generation)."""
    session = SessionManager.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status == "handed_off":
        raise HTTPException(status_code=400, detail="Session already handed off")

    if session.status != "completed":
        raise HTTPException(status_code=400, detail="Session must be completed before handoff")

    if not session.reports:
        raise HTTPException(status_code=400, detail="No visibility report generated yet")

    try:
        client = execute_handoff(session, db)
        db.commit()
    except ValueError as e:
        db.rollback()
        logger.error(f"Strategy generation failed: {e}")
        raise HTTPException(status_code=422, detail=f"Strategy generation failed: {e}")
    except Exception as e:
        db.rollback()
        logger.error(f"Handoff failed: {e}")
        raise HTTPException(status_code=500, detail=f"Handoff failed: {e}")

    # Redirect to client detail page
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/admin/clients/{client.id}", status_code=303)


@router.post("/{session_id}/abandon", response_class=HTMLResponse)
def abandon_session(
    request: Request,
    session_id: uuid.UUID,
    reason: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Mark session as abandoned."""
    session = SessionManager.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        SessionManager.abandon_session(db, session, reason)
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin/discovery", status_code=303)


# --- Entity Management ---


@router.post("/{session_id}/entities/add", response_class=HTMLResponse)
def add_entity(
    request: Request,
    session_id: uuid.UUID,
    name: str = Form(...),
    category: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Add a manual entity to the session."""
    from app.models.discovery_entity import DiscoveryEntity

    session = SessionManager.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check max entities (30)
    if len(session.entities) >= 30:
        raise HTTPException(status_code=400, detail="Maximum 30 entities per session")

    valid_categories = {"product", "audience", "problem", "industry", "competitor", "use_case"}
    if category not in valid_categories:
        raise HTTPException(status_code=400, detail=f"Invalid category: {category}")

    entity = DiscoveryEntity(
        session_id=session.id,
        name=name[:200],
        category=category,
        source="operator_added",
    )
    db.add(entity)
    db.commit()

    # Re-fetch session with updated entities
    session = SessionManager.get_session(db, session_id)

    return templates.TemplateResponse(
        request,
        "partials/discovery_entities.html",
        {
            "session": session,
            "entities": list(session.entities),
        },
    )


@router.delete("/{session_id}/entities/{entity_id}", response_class=HTMLResponse)
def remove_entity(
    request: Request,
    session_id: uuid.UUID,
    entity_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Remove an entity from the session."""
    from app.models.discovery_entity import DiscoveryEntity

    entity = db.query(DiscoveryEntity).filter(
        DiscoveryEntity.id == entity_id,
        DiscoveryEntity.session_id == session_id,
    ).first()

    if entity:
        db.delete(entity)
        db.commit()

    session = SessionManager.get_session(db, session_id)
    return templates.TemplateResponse(
        request,
        "partials/discovery_entities.html",
        {
            "session": session,
            "entities": list(session.entities) if session else [],
        },
    )
