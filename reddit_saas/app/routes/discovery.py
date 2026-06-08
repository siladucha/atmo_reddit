"""Discovery Engine routes — admin panel UI for Reddit ecosystem research.

All routes require platform admin (owner/partner) role.
UI is HTMX-driven: single session page with partial swaps for each step.
"""

import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from fastapi.templating import Jinja2Templates

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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/discovery", tags=["discovery"])
templates = Jinja2Templates(directory="app/templates")


# --- Pages ---


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
        "admin_discovery.html",
        {
            "request": request,
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
        "admin_discovery_new.html",
        {
            "request": request,
            "clients": clients,
            "current_user": current_user,
            "default_client_id": default_client_id,
        },
    )


@router.post("/new", response_class=HTMLResponse)
def discovery_create(
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
            "partials/discovery_brief_form.html",
            {
                "request": request,
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

    # Extract entities
    try:
        entities = extract_entities(client_brief.strip(), db, session.id)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Entity extraction failed: {e}")
        return templates.TemplateResponse(
            "partials/discovery_brief_form.html",
            {
                "request": request,
                "error": f"Entity extraction failed: {str(e)[:200]}. Please try again.",
                "client_brief": client_brief,
                "prospect_name": prospect_name,
            },
            status_code=500,
        )

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

    return templates.TemplateResponse(
        "admin_discovery_session.html",
        {
            "request": request,
            "session": session,
            "current_step": current_step,
            "current_user": current_user,
            "can_generate_report": SessionManager.can_generate_report(session),
            "is_max_iterations": SessionManager.is_at_max_iterations(session),
        },
    )


# --- Iteration Flow ---


@router.post("/{session_id}/entities", response_class=HTMLResponse)
def confirm_entities(
    request: Request,
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Operator confirms entities → trigger hypothesis formation."""
    session = SessionManager.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Form hypotheses
    prior = [h for h in session.hypotheses if h.iteration_number < session.current_iteration]

    try:
        hypotheses = form_hypotheses(
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
        "partials/discovery_hypotheses.html",
        {
            "request": request,
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

    # Return progress partial
    return templates.TemplateResponse(
        "partials/discovery_research_progress.html",
        {
            "request": request,
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
            "partials/discovery_results.html",
            {
                "request": request,
                "session": session,
                "hypotheses": current_hypos,
            },
        )

    # Still in progress — return progress partial (will be polled again)
    return templates.TemplateResponse(
        "partials/discovery_research_progress.html",
        {
            "request": request,
            "session": session,
            "hypotheses": current_hypos,
            "progress": progress,
        },
    )


@router.post("/{session_id}/decide", response_class=HTMLResponse)
def decide_hypotheses(
    request: Request,
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Process operator confirm/reject decisions on hypotheses."""
    session = SessionManager.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Parse form data (multiple hypothesis decisions)
    # Form fields: decision_{hypothesis_id} = confirm|reject
    # rejection_reason_{hypothesis_id} = text (if rejected)
    import asyncio
    from starlette.datastructures import FormData

    # We'll handle this synchronously via request form
    # Note: In actual implementation, use Form(...) parameters or parse body

    # For now, return results — actual decision parsing will be in template form
    current_hypos = [
        h for h in session.hypotheses
        if h.iteration_number == session.current_iteration
    ]

    return templates.TemplateResponse(
        "partials/discovery_results.html",
        {
            "request": request,
            "session": session,
            "hypotheses": current_hypos,
            "can_generate_report": SessionManager.can_generate_report(session),
            "is_max_iterations": SessionManager.is_at_max_iterations(session),
        },
    )


@router.post("/{session_id}/report", response_class=HTMLResponse)
def generate_report(
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
        report = generate_visibility_report(session, db)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Report generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")

    return templates.TemplateResponse(
        "partials/discovery_report.html",
        {
            "request": request,
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
        "partials/discovery_report_export.html",
        {
            "request": request,
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
    """Execute Discovery → Strategy handoff."""
    session = SessionManager.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        client = execute_handoff(session, db)
        db.commit()
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
        "partials/discovery_entities.html",
        {
            "request": request,
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
        "partials/discovery_entities.html",
        {
            "request": request,
            "session": session,
            "entities": list(session.entities) if session else [],
        },
    )
