"""GEO/AEO Prompt Monitoring admin routes.

Provides UI for managing prompts, competitors, viewing execution history,
and triggering manual runs. All routes require superuser access.
"""

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.models.client import Client
from app.models.geo_competitor import GeoCompetitor
from app.models.geo_execution import GeoExecutionBatch, GeoFrequencyMetric, GeoQueryResult
from app.models.geo_prompt import GeoPrompt
from app.models.user import User
from app.services import audit as audit_service

router = APIRouter(prefix="/admin/clients", tags=["admin-geo"])
templates = Jinja2Templates(directory="app/templates")


# ---------------------------------------------------------------------------
# Main GEO page
# ---------------------------------------------------------------------------


@router.get("/{client_id}/geo", response_class=HTMLResponse)
def geo_main_page(
    request: Request,
    client_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Main GEO monitoring page for a client."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    prompts = (
        db.query(GeoPrompt)
        .filter(GeoPrompt.client_id == client_id)
        .order_by(desc(GeoPrompt.created_at))
        .all()
    )

    competitors = (
        db.query(GeoCompetitor)
        .filter(GeoCompetitor.client_id == client_id)
        .order_by(desc(GeoCompetitor.created_at))
        .all()
    )

    batches = (
        db.query(GeoExecutionBatch)
        .filter(GeoExecutionBatch.client_id == client_id)
        .order_by(desc(GeoExecutionBatch.started_at))
        .limit(20)
        .all()
    )

    return templates.TemplateResponse("admin_geo.html", {
        "request": request,
        "user": current_user,
        "client": client,
        "prompts": prompts,
        "competitors": competitors,
        "batches": batches,
    })


# ---------------------------------------------------------------------------
# Prompt CRUD (HTMX partials)
# ---------------------------------------------------------------------------


@router.get("/{client_id}/geo/prompts", response_class=HTMLResponse)
def get_prompts_partial(
    request: Request,
    client_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """HTMX partial: prompt list."""
    prompts = (
        db.query(GeoPrompt)
        .filter(GeoPrompt.client_id == client_id)
        .order_by(desc(GeoPrompt.created_at))
        .all()
    )
    return templates.TemplateResponse("partials/geo_prompts.html", {
        "request": request,
        "prompts": prompts,
        "client_id": str(client_id),
    })


@router.post("/{client_id}/geo/prompts", response_class=HTMLResponse)
def create_prompt(
    request: Request,
    client_id: uuid.UUID,
    prompt_text: str = Form(...),
    category: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Create a new GEO prompt."""
    # Validate length
    prompt_text = prompt_text.strip()
    if len(prompt_text) < 10 or len(prompt_text) > 1000:
        raise HTTPException(status_code=400, detail="Prompt must be 10-1000 characters")

    # Check limit (50 active prompts)
    active_count = (
        db.query(func.count(GeoPrompt.id))
        .filter(GeoPrompt.client_id == client_id, GeoPrompt.is_active == True)
        .scalar()
    )
    if active_count >= 50:
        raise HTTPException(status_code=400, detail="Maximum 50 active prompts reached")

    # Check duplicate
    existing = (
        db.query(GeoPrompt)
        .filter(GeoPrompt.client_id == client_id, GeoPrompt.prompt_text == prompt_text)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Duplicate prompt text")

    prompt = GeoPrompt(
        client_id=client_id,
        prompt_text=prompt_text,
        category=category.strip() or None,
        created_by=current_user.id,
    )
    db.add(prompt)
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="create",
        entity_type="geo_prompt",
        entity_id=prompt.id,
        client_id=client_id,
        details={"prompt_text": prompt_text[:100]},
    )

    # Return updated prompt list
    prompts = (
        db.query(GeoPrompt)
        .filter(GeoPrompt.client_id == client_id)
        .order_by(desc(GeoPrompt.created_at))
        .all()
    )
    return templates.TemplateResponse("partials/geo_prompts.html", {
        "request": request,
        "prompts": prompts,
        "client_id": str(client_id),
    })


@router.post("/{client_id}/geo/prompts/{prompt_id}/toggle", response_class=HTMLResponse)
def toggle_prompt(
    request: Request,
    client_id: uuid.UUID,
    prompt_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Toggle a prompt active/inactive."""
    prompt = db.query(GeoPrompt).filter(GeoPrompt.id == prompt_id, GeoPrompt.client_id == client_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    prompt.is_active = not prompt.is_active
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="toggle",
        entity_type="geo_prompt",
        entity_id=prompt.id,
        client_id=client_id,
        details={"is_active": prompt.is_active},
    )

    prompts = (
        db.query(GeoPrompt)
        .filter(GeoPrompt.client_id == client_id)
        .order_by(desc(GeoPrompt.created_at))
        .all()
    )
    return templates.TemplateResponse("partials/geo_prompts.html", {
        "request": request,
        "prompts": prompts,
        "client_id": str(client_id),
    })


@router.delete("/{client_id}/geo/prompts/{prompt_id}", response_class=HTMLResponse)
def delete_prompt(
    request: Request,
    client_id: uuid.UUID,
    prompt_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Soft-delete a prompt (deactivate)."""
    prompt = db.query(GeoPrompt).filter(GeoPrompt.id == prompt_id, GeoPrompt.client_id == client_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    prompt.is_active = False
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="deactivate",
        entity_type="geo_prompt",
        entity_id=prompt.id,
        client_id=client_id,
    )

    prompts = (
        db.query(GeoPrompt)
        .filter(GeoPrompt.client_id == client_id)
        .order_by(desc(GeoPrompt.created_at))
        .all()
    )
    return templates.TemplateResponse("partials/geo_prompts.html", {
        "request": request,
        "prompts": prompts,
        "client_id": str(client_id),
    })


# ---------------------------------------------------------------------------
# Competitor CRUD (HTMX partials)
# ---------------------------------------------------------------------------


@router.get("/{client_id}/geo/competitors", response_class=HTMLResponse)
def get_competitors_partial(
    request: Request,
    client_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """HTMX partial: competitor list."""
    competitors = (
        db.query(GeoCompetitor)
        .filter(GeoCompetitor.client_id == client_id)
        .order_by(desc(GeoCompetitor.created_at))
        .all()
    )
    return templates.TemplateResponse("partials/geo_competitors.html", {
        "request": request,
        "competitors": competitors,
        "client_id": str(client_id),
    })


@router.post("/{client_id}/geo/competitors", response_class=HTMLResponse)
def create_competitor(
    request: Request,
    client_id: uuid.UUID,
    competitor_name: str = Form(...),
    competitor_domain: str = Form(""),
    aliases: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Create a new competitor entity."""
    competitor_name = competitor_name.strip()
    if not competitor_name:
        raise HTTPException(status_code=400, detail="Competitor name is required")

    # Check limit (30 active)
    active_count = (
        db.query(func.count(GeoCompetitor.id))
        .filter(GeoCompetitor.client_id == client_id, GeoCompetitor.is_active == True)
        .scalar()
    )
    if active_count >= 30:
        raise HTTPException(status_code=400, detail="Maximum 30 active competitors reached")

    # Check duplicate name
    existing = (
        db.query(GeoCompetitor)
        .filter(GeoCompetitor.client_id == client_id, GeoCompetitor.competitor_name == competitor_name)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Duplicate competitor name")

    # Parse aliases (comma-separated)
    alias_list = [a.strip() for a in aliases.split(",") if a.strip()] if aliases else []

    comp = GeoCompetitor(
        client_id=client_id,
        competitor_name=competitor_name,
        competitor_domain=competitor_domain.strip() or None,
        aliases=alias_list,
    )
    db.add(comp)
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="create",
        entity_type="geo_competitor",
        entity_id=comp.id,
        client_id=client_id,
        details={"name": competitor_name},
    )

    competitors = (
        db.query(GeoCompetitor)
        .filter(GeoCompetitor.client_id == client_id)
        .order_by(desc(GeoCompetitor.created_at))
        .all()
    )
    return templates.TemplateResponse("partials/geo_competitors.html", {
        "request": request,
        "competitors": competitors,
        "client_id": str(client_id),
    })


@router.post("/{client_id}/geo/competitors/{comp_id}/toggle", response_class=HTMLResponse)
def toggle_competitor(
    request: Request,
    client_id: uuid.UUID,
    comp_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Toggle a competitor active/inactive."""
    comp = db.query(GeoCompetitor).filter(GeoCompetitor.id == comp_id, GeoCompetitor.client_id == client_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail="Competitor not found")

    comp.is_active = not comp.is_active
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="toggle",
        entity_type="geo_competitor",
        entity_id=comp.id,
        client_id=client_id,
        details={"is_active": comp.is_active},
    )

    competitors = (
        db.query(GeoCompetitor)
        .filter(GeoCompetitor.client_id == client_id)
        .order_by(desc(GeoCompetitor.created_at))
        .all()
    )
    return templates.TemplateResponse("partials/geo_competitors.html", {
        "request": request,
        "competitors": competitors,
        "client_id": str(client_id),
    })


# ---------------------------------------------------------------------------
# Execution history + Run Now
# ---------------------------------------------------------------------------


@router.get("/{client_id}/geo/history", response_class=HTMLResponse)
def get_history_partial(
    request: Request,
    client_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """HTMX partial: execution history."""
    batches = (
        db.query(GeoExecutionBatch)
        .filter(GeoExecutionBatch.client_id == client_id)
        .order_by(desc(GeoExecutionBatch.started_at))
        .limit(20)
        .all()
    )
    return templates.TemplateResponse("partials/geo_history.html", {
        "request": request,
        "batches": batches,
        "client_id": str(client_id),
    })


@router.get("/{client_id}/geo/batch/{batch_id}", response_class=HTMLResponse)
def get_batch_detail(
    request: Request,
    client_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """HTMX partial: batch detail view with per-prompt results."""
    batch = (
        db.query(GeoExecutionBatch)
        .filter(GeoExecutionBatch.id == batch_id, GeoExecutionBatch.client_id == client_id)
        .first()
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Get frequency metrics for this batch
    metrics = (
        db.query(GeoFrequencyMetric)
        .filter(GeoFrequencyMetric.execution_batch_id == batch_id)
        .all()
    )

    # Get prompts for display
    prompt_ids = list(set(m.prompt_id for m in metrics))
    prompts_map = {}
    if prompt_ids:
        prompts_list = db.query(GeoPrompt).filter(GeoPrompt.id.in_(prompt_ids)).all()
        prompts_map = {p.id: p for p in prompts_list}

    return templates.TemplateResponse("partials/geo_batch_detail.html", {
        "request": request,
        "batch": batch,
        "metrics": metrics,
        "prompts_map": prompts_map,
        "client_id": str(client_id),
    })


@router.post("/{client_id}/geo/run-now", response_class=HTMLResponse)
def run_now(
    request: Request,
    client_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Trigger an immediate GEO execution batch for a client."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    from app.services.geo_query_runner import run_geo_batch_for_client

    batch = run_geo_batch_for_client(
        db=db,
        client=client,
        triggered_by="manual",
        user_id=current_user.id,
    )

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="trigger",
        entity_type="geo_batch",
        entity_id=batch.id if batch else None,
        client_id=client_id,
        details={"triggered_by": "manual", "status": batch.status if batch else "no_prompts"},
    )

    # Return updated history
    batches = (
        db.query(GeoExecutionBatch)
        .filter(GeoExecutionBatch.client_id == client_id)
        .order_by(desc(GeoExecutionBatch.started_at))
        .limit(20)
        .all()
    )
    return templates.TemplateResponse("partials/geo_history.html", {
        "request": request,
        "batches": batches,
        "client_id": str(client_id),
    })


# ---------------------------------------------------------------------------
# GEO monitoring toggle
# ---------------------------------------------------------------------------


@router.post("/{client_id}/geo/toggle", response_class=HTMLResponse)
def toggle_geo_monitoring(
    request: Request,
    client_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Toggle GEO monitoring on/off for a client."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    client.geo_monitoring_enabled = not client.geo_monitoring_enabled
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="toggle",
        entity_type="geo_monitoring",
        client_id=client_id,
        details={"geo_monitoring_enabled": client.geo_monitoring_enabled},
    )

    # Re-render the full page via redirect header for HTMX
    return HTMLResponse(
        content="",
        headers={"HX-Redirect": f"/admin/clients/{client_id}/geo"},
    )
