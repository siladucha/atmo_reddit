"""Admin panel routes — superuser-only system management interface."""

import math
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.subreddit import ClientSubreddit, ClientSubredditAssignment, Subreddit
from app.models.user import User
from app.services import admin as admin_service
from app.services import audit as audit_service
from app.services import health_metrics
from app.services import inspector as inspector_service
from app.services import operations_dashboard
from app.services import transparency
from app.services.dry_run import is_dry_run_enabled_global
from app.services.metrics_collector import (
    MetricsCollector,
    gauge_color,
    get_metrics_collector,
)

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")
# Expose dry-run toggle to the admin nav (admin_base.html).
templates.env.globals["dry_run_enabled"] = is_dry_run_enabled_global


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _paginate(page: int, per_page: int, total: int) -> dict:
    """Build pagination context dict."""
    total_pages = max(1, math.ceil(total / per_page))
    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
    }


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Operations Dashboard — unified daily-ops view at `/admin/`.

    The shell renders synchronously; client cards / freshness / run-history /
    avatar-health / schedule are filled in via HTMX partials so the page can
    auto-refresh without a full reload.
    """
    from app.services.settings import get_setting

    metrics = operations_dashboard.get_top_metrics(db)
    clients_list = operations_dashboard.list_active_clients(db)

    # Pipeline control settings for the toggle panel
    pipeline_controls = {
        "pipeline_enabled": get_setting(db, "pipeline_enabled").lower() == "true",
        "generation_enabled": get_setting(db, "generation_enabled").lower() == "true",
        "scrape_enabled": get_setting(db, "scrape_enabled").lower() == "true",
    }

    return templates.TemplateResponse(
        name="admin_dashboard.html",
        context={
            "request": request,
            "active_nav": "dashboard",
            "metrics": metrics,
            "clients": clients_list,
            "pipeline_controls": pipeline_controls,
        },
        request=request,
    )


@router.get("/activity-feed", response_class=HTMLResponse)
def admin_activity_feed(
    request: Request,
    client_id: str | None = None,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    cid = uuid.UUID(client_id) if client_id else None
    events = transparency.get_activity_events(db, client_id=cid, limit=50)
    return templates.TemplateResponse(
        name="partials/activity_feed.html",
        context={"request": request, "events": events, "now_utc": datetime.now(timezone.utc)},
        request=request,
    )


# ---------------------------------------------------------------------------
# Operations Dashboard — HTMX partials and bulk pipeline triggers
# ---------------------------------------------------------------------------

_PIPELINE_ACTIONS = {"scrape", "score", "generate", "full-pipeline"}


def _trigger_client_pipeline(action: str, client_id: uuid.UUID) -> str:
    """Dispatch a Celery pipeline task for a single client. Returns task id."""
    from app.tasks.scraping import scrape_professional_subreddits
    from app.tasks.ai_pipeline import score_threads, generate_comments

    cid = str(client_id)
    if action == "scrape":
        return scrape_professional_subreddits.delay(cid).id
    if action == "score":
        return score_threads.delay(cid).id
    if action == "generate":
        return generate_comments.delay(cid).id
    if action == "full-pipeline":
        chain = (
            scrape_professional_subreddits.si(cid)
            | score_threads.si(cid)
            | generate_comments.si(cid)
        )
        return chain.apply_async().id
    raise ValueError(f"Unknown pipeline action: {action}")


@router.get("/dashboard/clients", response_class=HTMLResponse)
def dashboard_client_cards(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    cards = operations_dashboard.get_client_status_cards(db)
    return templates.TemplateResponse(
        name="partials/dashboard_client_cards.html",
        context={"request": request, "cards": cards},
        request=request,
    )


@router.get("/dashboard/freshness", response_class=HTMLResponse)
def dashboard_freshness(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    groups = operations_dashboard.get_scrape_freshness_grouped(db)
    return templates.TemplateResponse(
        name="partials/dashboard_freshness.html",
        context={"request": request, "groups": groups},
        request=request,
    )


@router.get("/dashboard/run-history", response_class=HTMLResponse)
def dashboard_run_history(
    request: Request,
    client_id: str | None = None,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    cid = uuid.UUID(client_id) if client_id else None
    events = operations_dashboard.get_run_history(db, client_id=cid, limit=20)
    return templates.TemplateResponse(
        name="partials/dashboard_run_history.html",
        context={"request": request, "events": events},
        request=request,
    )


@router.get("/dashboard/avatar-health", response_class=HTMLResponse)
def dashboard_avatar_health(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    summary = operations_dashboard.get_avatar_health_summary(db)
    return templates.TemplateResponse(
        name="partials/dashboard_avatar_health.html",
        context={"request": request, "summary": summary},
        request=request,
    )


@router.get("/dashboard/schedule", response_class=HTMLResponse)
def dashboard_schedule(
    request: Request,
    current_user: User = Depends(require_superuser),
):
    schedule = operations_dashboard.get_schedule_display()
    return templates.TemplateResponse(
        name="partials/dashboard_schedule.html",
        context={"request": request, "schedule": schedule},
        request=request,
    )


@router.get("/dashboard/topology-panel", response_class=HTMLResponse)
def topology_panel(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Returns HTMX partial for the topology timeline panel."""
    from app.services.topology import get_topology_data

    topology_data = get_topology_data(db)
    return templates.TemplateResponse(
        name="partials/topology_panel.html",
        context={"request": request, "topology": topology_data},
        request=request,
    )


@router.get("/dashboard/topology")
def topology_json(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Returns topology data as JSON for programmatic access."""
    from dataclasses import asdict

    from app.services.topology import get_topology_data

    topology_data = get_topology_data(db)
    # Serialize dataclasses to JSON-compatible dict
    data = asdict(topology_data)
    # Convert datetime objects to ISO 8601 strings
    data["generated_at"] = topology_data.generated_at.isoformat()
    for node in data["nodes"]:
        if node["last_run_at"]:
            node["last_run_at"] = node["last_run_at"].isoformat()
    return JSONResponse(content=data)


@router.post("/dashboard/trigger/{action}/{client_id}", response_class=HTMLResponse)
def dashboard_trigger(
    request: Request,
    action: str,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX-friendly per-client pipeline trigger that returns a toast partial.

    Wraps the same Celery tasks that `/pipeline/*` exposes via JSON so the
    dashboard can render an inline confirmation without client-side glue.
    """
    if action not in _PIPELINE_ACTIONS:
        return templates.TemplateResponse(
            name="partials/dashboard_toast.html",
            context={"request": request, "error": f"Unknown action: {action}"},
            request=request,
            status_code=400,
        )

    try:
        task_id = _trigger_client_pipeline(action, client_id)
        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action="trigger_pipeline",
            entity_type="task",
            client_id=client_id,
            details={"action": action, "client_id": str(client_id), "task_id": task_id},
        )
        return templates.TemplateResponse(
            name="partials/dashboard_toast.html",
            context={
                "request": request,
                "success": f"Queued {action} (task {task_id[:8]}…)",
            },
            request=request,
        )
    except Exception as e:
        return templates.TemplateResponse(
            name="partials/dashboard_toast.html",
            context={"request": request, "error": str(e)},
            request=request,
            status_code=500,
        )


@router.post("/dashboard/run-all/{action}", response_class=HTMLResponse)
def dashboard_run_all(
    request: Request,
    action: str,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Fan out a pipeline action across every active client."""
    if action not in _PIPELINE_ACTIONS:
        return templates.TemplateResponse(
            name="partials/dashboard_toast.html",
            context={"request": request, "error": f"Unknown action: {action}"},
            request=request,
            status_code=400,
        )

    clients_list = operations_dashboard.list_active_clients(db)
    triggered = 0
    failures: list[str] = []
    for client in clients_list:
        try:
            _trigger_client_pipeline(action, client.id)
            triggered += 1
        except Exception as e:
            failures.append(f"{client.client_name}: {e}")

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="trigger_pipeline_all",
        entity_type="task",
        details={"action": action, "triggered": triggered, "failures": failures},
    )

    if failures:
        return templates.TemplateResponse(
            name="partials/dashboard_toast.html",
            context={
                "request": request,
                "success": f"Queued {action} for {triggered} client(s)",
                "error": f"{len(failures)} failed: " + "; ".join(failures[:3]),
            },
            request=request,
        )
    return templates.TemplateResponse(
        name="partials/dashboard_toast.html",
        context={
            "request": request,
            "success": f"Queued {action} for {triggered} client(s)",
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# User management (6.2)
# ---------------------------------------------------------------------------

@router.get("/users", response_class=HTMLResponse)
def admin_users(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    users, total = admin_service.list_users(db, page, per_page)
    pagination = _paginate(page, per_page, total)
    clients_list = db.query(Client).filter(Client.is_active.is_(True)).order_by(Client.client_name).all()

    return templates.TemplateResponse(
        name="admin_users.html",
        context={
            "request": request,
            "active_nav": "users",
            "users": users,
            "pagination": pagination,
            "current_user": current_user,
            "clients": clients_list,
            "error": None,
        },
        request=request,
    )


@router.post("/users", response_class=HTMLResponse)
def admin_create_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(""),
    is_superuser: bool = Form(False),
    user_client_id: str = Form(""),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    error = None
    try:
        new_user = admin_service.create_admin_user(
            db,
            email=email,
            password=password,
            full_name=full_name or None,
            is_superuser=is_superuser,
            current_user_id=current_user.id,
        )
        # Link user to client if specified
        if user_client_id and user_client_id.strip() and not is_superuser:
            try:
                new_user.client_id = uuid.UUID(user_client_id)
                db.commit()
            except ValueError:
                pass
    except ValueError as e:
        error = str(e)

    users, total = admin_service.list_users(db)
    pagination = _paginate(1, 20, total)
    clients_list = db.query(Client).filter(Client.is_active.is_(True)).order_by(Client.client_name).all()

    return templates.TemplateResponse(
        name="admin_users.html",
        context={
            "request": request,
            "active_nav": "users",
            "users": users,
            "pagination": pagination,
            "current_user": current_user,
            "clients": clients_list,
            "error": error,
        },
        request=request,
    )


@router.post("/users/{user_id}/toggle-active", response_class=HTMLResponse)
def admin_toggle_user_active(
    request: Request,
    user_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    try:
        user = admin_service.toggle_user_active(db, user_id, current_user.id)
    except ValueError:
        user = db.query(User).filter(User.id == user_id).first()

    return templates.TemplateResponse(
        name="partials/admin_user_row.html",
        context={"request": request, "user": user, "current_user": current_user},
        request=request,
    )


@router.post("/users/{user_id}/toggle-superuser", response_class=HTMLResponse)
def admin_toggle_user_superuser(
    request: Request,
    user_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    try:
        user = admin_service.toggle_user_superuser(db, user_id, current_user.id)
    except ValueError:
        user = db.query(User).filter(User.id == user_id).first()

    return templates.TemplateResponse(
        name="partials/admin_user_row.html",
        context={"request": request, "user": user, "current_user": current_user},
        request=request,
    )


@router.post("/users/{user_id}/delete", response_class=HTMLResponse)
def admin_delete_user(
    request: Request,
    user_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    try:
        admin_service.toggle_user_active(db, user_id, current_user.id)
    except ValueError:
        pass

    # Re-fetch user to show updated state
    user = db.query(User).filter(User.id == user_id).first()
    return templates.TemplateResponse(
        name="partials/admin_user_row.html",
        context={"request": request, "user": user, "current_user": current_user},
        request=request,
    )


@router.post("/users/{user_id}/reset-password", response_class=HTMLResponse)
def admin_reset_password(
    request: Request,
    user_id: uuid.UUID,
    new_password: str = Form(...),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Admin resets a user's password."""
    try:
        admin_service.reset_user_password(db, user_id, new_password, current_user.id)
    except ValueError:
        pass

    user = db.query(User).filter(User.id == user_id).first()
    return templates.TemplateResponse(
        name="partials/admin_user_row.html",
        context={"request": request, "user": user, "current_user": current_user},
        request=request,
    )


# ---------------------------------------------------------------------------
# Client management (6.3)
# ---------------------------------------------------------------------------

@router.get("/clients", response_class=HTMLResponse)
def admin_clients(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    clients, total = admin_service.list_clients_paginated(db, page, per_page)
    pagination = _paginate(page, per_page, total)

    return templates.TemplateResponse(
        name="admin_clients.html",
        context={
            "request": request,
            "active_nav": "clients",
            "clients": clients,
            "pagination": pagination,
        },
        request=request,
    )


@router.get("/clients/new", response_class=HTMLResponse)
def admin_client_new(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        name="admin_client_new.html",
        context={
            "request": request,
            "active_nav": "clients",
            "error": None,
        },
        request=request,
    )


@router.post("/clients/new", response_class=HTMLResponse)
def admin_client_create(
    request: Request,
    client_name: str = Form(...),
    brand_name: str = Form(...),
    company_profile: str = Form(""),
    company_worldview: str = Form(""),
    company_problem: str = Form(""),
    competitive_landscape: str = Form(""),
    brand_voice: str = Form(""),
    icp_profiles: str = Form(""),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    client = admin_service.create_client(
        db,
        current_user_id=current_user.id,
        client_name=client_name,
        brand_name=brand_name,
        company_profile=company_profile or None,
        company_worldview=company_worldview or None,
        company_problem=company_problem or None,
        competitive_landscape=competitive_landscape or None,
        brand_voice=brand_voice or None,
        icp_profiles=icp_profiles or None,
    )
    return RedirectResponse(url=f"/admin/clients/{client.id}", status_code=303)


@router.get("/clients/{client_id}/transparency", response_class=HTMLResponse)
def client_transparency(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return HTMLResponse("Client not found", status_code=404)

    stats = transparency.get_pipeline_stats(db, client_id)
    freshness = transparency.get_scrape_freshness(db, client_id)
    events = transparency.get_activity_events(db, client_id=client_id, limit=100)

    return templates.TemplateResponse(
        name="admin_client_transparency.html",
        context={
            "request": request,
            "client": client,
            "stats": stats,
            "freshness": freshness,
            "events": events,
            "active_nav": "clients",
            "now_utc": datetime.now(timezone.utc),
        },
        request=request,
    )


@router.get("/clients/{client_id}/activity-feed", response_class=HTMLResponse)
def client_activity_feed(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    events = transparency.get_activity_events(db, client_id=client_id, limit=100)
    return templates.TemplateResponse(
        name="partials/activity_feed.html",
        context={"request": request, "events": events, "now_utc": datetime.now(timezone.utc)},
        request=request,
    )


@router.get("/clients/{client_id}", response_class=HTMLResponse)
def admin_client_detail(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return HTMLResponse("Client not found", status_code=404)

    subreddits = admin_service.list_client_subreddits(db, client_id)
    avatars = (
        db.query(Avatar)
        .filter(Avatar.client_ids.any(str(client_id)))
        .all()
    )
    keywords = admin_service.get_client_keywords(db, client_id)

    return templates.TemplateResponse(
        name="admin_client_detail.html",
        context={
            "request": request,
            "active_nav": "clients",
            "client": client,
            "subreddits": subreddits,
            "avatars": avatars,
            "keywords": keywords,
            "error": None,
        },
        request=request,
    )


@router.post("/clients/{client_id}", response_class=HTMLResponse)
def admin_client_update(
    request: Request,
    client_id: uuid.UUID,
    client_name: str = Form(...),
    brand_name: str = Form(...),
    company_profile: str = Form(""),
    company_worldview: str = Form(""),
    company_problem: str = Form(""),
    competitive_landscape: str = Form(""),
    brand_voice: str = Form(""),
    icp_profiles: str = Form(""),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    try:
        admin_service.update_client(
            db,
            client_id=client_id,
            current_user_id=current_user.id,
            client_name=client_name,
            brand_name=brand_name,
            company_profile=company_profile or None,
            company_worldview=company_worldview or None,
            company_problem=company_problem or None,
            competitive_landscape=competitive_landscape or None,
            brand_voice=brand_voice or None,
            icp_profiles=icp_profiles or None,
        )
    except ValueError as e:
        return HTMLResponse(str(e), status_code=404)

    return RedirectResponse(url=f"/admin/clients/{client_id}", status_code=303)


@router.post("/clients/{client_id}/deactivate", response_class=HTMLResponse)
def admin_client_deactivate(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    try:
        admin_service.deactivate_client(db, client_id, current_user.id)
    except ValueError:
        pass
    return RedirectResponse(url="/admin/clients", status_code=303)


# ---------------------------------------------------------------------------
# Keyword management (6.5)
# ---------------------------------------------------------------------------

@router.get("/keywords/{client_id}", response_class=HTMLResponse)
def admin_keywords(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return HTMLResponse("Client not found", status_code=404)

    keywords = admin_service.get_client_keywords(db, client_id)

    return templates.TemplateResponse(
        name="admin_keywords.html",
        context={
            "request": request,
            "active_nav": "keywords",
            "client": client,
            "keywords": keywords,
            "error": None,
        },
        request=request,
    )


def _keyword_response(
    request: Request,
    client: Client,
    keywords,
    error: str | None = None,
):
    """Return either the per-client keywords page or the keyword section
    partial, depending on whether this is an HTMX request.

    HTMX clients get the inline partial so the global keywords page can swap
    the affected client's section without a full page reload.
    """
    is_htmx = request.headers.get("HX-Request", "").lower() == "true"
    template_name = (
        "partials/admin_keyword_section.html" if is_htmx else "admin_keywords.html"
    )
    return templates.TemplateResponse(
        name=template_name,
        context={
            "request": request,
            "active_nav": "keywords",
            "client": client,
            "keywords": keywords,
            "error": error,
        },
        request=request,
    )


@router.post("/keywords/{client_id}/add", response_class=HTMLResponse)
def admin_add_keyword(
    request: Request,
    client_id: uuid.UUID,
    name: str = Form(...),
    priority: str = Form("MEDIUM"),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    valid, err = admin_service.validate_keyword(name, priority)
    client = db.query(Client).filter(Client.id == client_id).first()
    if not valid:
        keywords = admin_service.get_client_keywords(db, client_id)
        return _keyword_response(request, client, keywords, error=err)

    admin_service.add_keyword(db, client_id, name, priority, current_user.id)
    keywords = admin_service.get_client_keywords(db, client_id)
    return _keyword_response(request, client, keywords)


@router.post("/keywords/{client_id}/{index}/remove", response_class=HTMLResponse)
def admin_remove_keyword(
    request: Request,
    client_id: uuid.UUID,
    index: int,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    try:
        admin_service.remove_keyword(db, client_id, index, current_user.id)
    except ValueError:
        pass

    keywords = admin_service.get_client_keywords(db, client_id)
    client = db.query(Client).filter(Client.id == client_id).first()
    return _keyword_response(request, client, keywords)


@router.post("/keywords/{client_id}/{index}/update", response_class=HTMLResponse)
def admin_update_keyword(
    request: Request,
    client_id: uuid.UUID,
    index: int,
    priority: str = Form(...),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    try:
        admin_service.update_keyword_priority(db, client_id, index, priority, current_user.id)
    except ValueError:
        pass

    keywords = admin_service.get_client_keywords(db, client_id)
    client = db.query(Client).filter(Client.id == client_id).first()
    return _keyword_response(request, client, keywords)


# ---------------------------------------------------------------------------
# Subreddit management (6.6)
# ---------------------------------------------------------------------------

@router.get("/subreddits", response_class=HTMLResponse)
def admin_subreddits_all(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
    client_id: Optional[str] = None,
    type: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
    per_page: int = 25,
):
    """Global subreddits management page — all clients, with pause/resume and pagination."""
    from sqlalchemy import func as sa_func

    # Build query with filters
    query = (
        db.query(ClientSubredditAssignment)
        .join(Subreddit, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .join(Client, Client.id == ClientSubredditAssignment.client_id)
    )

    # Filter by client
    if client_id:
        try:
            cid = uuid.UUID(client_id)
            query = query.filter(ClientSubredditAssignment.client_id == cid)
        except ValueError:
            pass

    # Filter by type (professional / hobby)
    if type and type in ("professional", "hobby"):
        query = query.filter(ClientSubredditAssignment.type == type)

    # Filter by status (active / paused)
    if status == "active":
        query = query.filter(ClientSubredditAssignment.is_active.is_(True))
    elif status == "paused":
        query = query.filter(ClientSubredditAssignment.is_active.is_(False))

    # Search by subreddit name (case-insensitive)
    if q and q.strip():
        search_term = q.strip().lower()
        query = query.filter(sa_func.lower(Subreddit.subreddit_name).contains(search_term))

    # Total count before pagination
    total = query.count()
    active_count = query.filter(ClientSubredditAssignment.is_active.is_(True)).count()
    # Reset filter for the actual query (active_count filter modified the query object)
    # Rebuild to avoid side effects
    query = (
        db.query(ClientSubredditAssignment)
        .join(Subreddit, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .join(Client, Client.id == ClientSubredditAssignment.client_id)
    )
    if client_id:
        try:
            cid = uuid.UUID(client_id)
            query = query.filter(ClientSubredditAssignment.client_id == cid)
        except ValueError:
            pass
    if type and type in ("professional", "hobby"):
        query = query.filter(ClientSubredditAssignment.type == type)
    if status == "active":
        query = query.filter(ClientSubredditAssignment.is_active.is_(True))
    elif status == "paused":
        query = query.filter(ClientSubredditAssignment.is_active.is_(False))
    if q and q.strip():
        search_term = q.strip().lower()
        query = query.filter(sa_func.lower(Subreddit.subreddit_name).contains(search_term))

    paused_count = total - active_count

    # Pagination
    total_pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page

    assignments = query.order_by(
        ClientSubredditAssignment.is_active.desc(),
        Subreddit.last_scraped_at.asc().nulls_first(),
        Subreddit.subreddit_name.asc(),
    ).offset(offset).limit(per_page).all()

    enriched = []
    now_utc = datetime.now(timezone.utc)
    for assignment in assignments:
        sub = assignment.subreddit
        last_scraped = sub.last_scraped_at
        if last_scraped:
            age_seconds = (now_utc - last_scraped).total_seconds()
            age_hours = age_seconds / 3600
            if age_hours >= 24:
                age_display = f"{int(age_hours // 24)}d {int(age_hours % 24)}h ago"
            elif age_hours >= 1:
                age_display = f"{int(age_hours)}h {int((age_hours % 1) * 60)}m ago"
            else:
                age_display = f"{int(age_hours * 60)}m ago"
        else:
            age_hours = None
            age_display = "Never"

        enriched.append({
            "sub": assignment,
            "subreddit_name": sub.subreddit_name,
            "is_active": assignment.is_active,
            "type": assignment.type,
            "last_scraped_at": last_scraped,
            "created_at": assignment.created_at,
            "client_name": assignment.client.client_name,
            "client_id": assignment.client_id,
            "age_hours": age_hours,
            "age_display": age_display,
        })

    # Get all clients for filter dropdown (include inactive — they may have subreddit assignments)
    clients = db.query(Client).order_by(Client.client_name).all()

    # Build pagination query string
    def _build_qs(**overrides):
        params = {}
        if client_id:
            params["client_id"] = client_id
        if type:
            params["type"] = type
        if status:
            params["status"] = status
        if q:
            params["q"] = q
        params.update(overrides)
        return "&".join(f"{k}={v}" for k, v in params.items() if v)

    return templates.TemplateResponse(
        name="admin_subreddits_all.html",
        context={
            "request": request,
            "active_nav": "subreddits",
            "subreddits": enriched,
            "total": total,
            "active_count": active_count,
            "paused_count": paused_count,
            "now_utc": now_utc,
            "clients": clients,
            "filter_client_id": client_id or "",
            "filter_type": type or "",
            "filter_status": status or "",
            "filter_q": q or "",
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "build_qs": _build_qs,
        },
        request=request,
    )


@router.get("/subreddits/detail/{subreddit_name}", response_class=HTMLResponse)
def admin_subreddit_detail(
    request: Request,
    subreddit_name: str,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Subreddit zoom-in detail page — intelligence, avatar monitoring, leaders."""
    from app.services import subreddit_intel

    overview = subreddit_intel.get_subreddit_overview(db, subreddit_name)
    if not overview:
        return RedirectResponse(url="/admin/subreddits", status_code=303)

    scrape_history = subreddit_intel.get_scrape_history(db, subreddit_name, limit=15)
    avatar_performance = subreddit_intel.get_avatar_performance(db, subreddit_name)
    community_leaders = subreddit_intel.get_top_community_users(db, subreddit_name, limit=15)
    recent_threads = subreddit_intel.get_recent_threads(db, subreddit_name, limit=15)
    timeline = subreddit_intel.get_engagement_timeline(db, subreddit_name, days=14)
    ai_costs = subreddit_intel.get_ai_costs(db, subreddit_name, limit=20)

    now_utc = datetime.now(timezone.utc)
    sub = overview["subreddit"]
    last_scraped = sub.last_scraped_at
    if last_scraped:
        age_hours = (now_utc - last_scraped).total_seconds() / 3600
    else:
        age_hours = None

    return templates.TemplateResponse(
        name="admin_subreddit_detail.html",
        context={
            "request": request,
            "active_nav": "subreddits",
            "subreddit_name": subreddit_name,
            "overview": overview,
            "scrape_history": scrape_history,
            "avatar_performance": avatar_performance,
            "community_leaders": community_leaders,
            "recent_threads": recent_threads,
            "timeline": timeline,
            "ai_costs": ai_costs,
            "age_hours": age_hours,
            "now_utc": now_utc,
        },
        request=request,
    )


@router.post("/subreddits/{subreddit_id}/toggle-active", response_class=HTMLResponse)
def admin_toggle_subreddit_active(
    request: Request,
    subreddit_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Toggle assignment is_active (pause/resume scraping for this client)."""
    assignment = db.query(ClientSubredditAssignment).filter(ClientSubredditAssignment.id == subreddit_id).first()
    if assignment:
        assignment.is_active = not assignment.is_active
        db.commit()
        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action="toggle_active",
            entity_type="subreddit_assignment",
            entity_id=assignment.id,
            details={"subreddit_name": assignment.subreddit.subreddit_name, "is_active": assignment.is_active},
        )

    # Check referer to redirect back to correct page
    referer = request.headers.get("referer", "")
    if assignment and f"/subreddits/{assignment.client_id}" in referer:
        return RedirectResponse(url=f"/admin/subreddits/{assignment.client_id}", status_code=303)
    return RedirectResponse(url="/admin/subreddits", status_code=303)


@router.get("/avatars", response_class=HTMLResponse)
def admin_avatars(
    request: Request,
    q: str = "",
    status: str = "",
    client_id: str = "",
    sort: str = "username",
    view: str = "table",
    group: str = "client",
    page: int = 1,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Admin avatars page — filtering, sorting, grouping, grid/table toggle.

    Reuses the same ``list_avatars_page`` service as the legacy
    ``/avatars-page`` route, but renders in the admin (dark) theme. Returns
    just the results region for HTMX requests so filter changes don't reload
    the whole shell.
    """
    from app.services.avatars_query import (
        AvatarFilter,
        GROUP_OPTIONS,
        SORT_OPTIONS,
        STATUS_OPTIONS,
        VIEW_OPTIONS,
        list_avatars_page,
    )
    from app.services.safety import get_avatar_health
    from app.services.avatars_query import build_avatar_view
    from app.services import karma_tracker

    f = AvatarFilter(
        q=q.strip(),
        status=status,
        client_id=client_id,
        sort=sort,
        view=view if view in ("grid", "table") else "table",
        group=group if group in ("client", "none") else "client",
        page=page,
    )
    avatar_page = list_avatars_page(db, f, viewer_client_id=None)

    # Batch-fetch top-3 subreddits for all visible avatars (Req 5).
    visible_ids = [a.id for a in avatar_page.items]
    for g in avatar_page.groups:
        visible_ids.extend(a.id for a in g.avatars)
    top_by_avatar = karma_tracker.top_subreddits_for_avatars(db, visible_ids, limit=3)

    # Batch-fetch AI costs per avatar (uses avatar_id column added in migration)
    from app.models.ai_usage import AIUsageLog
    from sqlalchemy import func as sa_func
    ai_costs_by_avatar: dict = {}
    if visible_ids:
        cost_rows = (
            db.query(
                AIUsageLog.avatar_id,
                sa_func.count(AIUsageLog.id).label("calls"),
                sa_func.coalesce(sa_func.sum(AIUsageLog.cost_usd), 0).label("cost"),
            )
            .filter(AIUsageLog.avatar_id.in_(visible_ids))
            .group_by(AIUsageLog.avatar_id)
            .all()
        )
        ai_costs_by_avatar = {str(r.avatar_id): {"calls": r.calls, "cost": float(r.cost)} for r in cost_rows}

    def _to_view(a):
        view_dict = build_avatar_view(
            a,
            get_avatar_health(db, a),
            avatar_page.client_by_id,
            top_subreddits=top_by_avatar.get(str(a.id), []),
        )
        ai = ai_costs_by_avatar.get(str(a.id), {"calls": 0, "cost": 0.0})
        view_dict["ai_calls"] = ai["calls"]
        view_dict["ai_cost"] = ai["cost"]
        return view_dict

    flat = [_to_view(a) for a in avatar_page.items]
    grouped = []
    for g in avatar_page.groups:
        grouped.append({
            "key": g.key,
            "title": g.title,
            "brand": g.brand,
            "client_id": str(g.client.id) if g.client else None,
            "counts": g.counts,
            "avatars": [_to_view(a) for a in g.avatars],
        })

    ctx = {
        "request": request,
        "active_nav": "avatars",
        "avatars": flat,
        "groups": grouped,
        "f": f,
        "page_obj": avatar_page,
        "is_admin": True,
        "sort_options": SORT_OPTIONS,
        "status_options": STATUS_OPTIONS,
        "group_options": GROUP_OPTIONS,
        "view_options": VIEW_OPTIONS,
    }

    is_htmx = request.headers.get("HX-Request", "").lower() == "true"
    template = "partials/admin_avatars_results.html" if is_htmx else "admin_avatars.html"
    return templates.TemplateResponse(name=template, context=ctx, request=request)


@router.post("/avatars/check-visible", response_class=HTMLResponse)
def admin_avatars_check_visible(
    request: Request,
    q: str = "",
    status: str = "",
    client_id: str = "",
    sort: str = "username",
    view: str = "table",
    group: str = "client",
    page: int = 1,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX: Check Reddit status for avatars matching the current filter, then
    return the refreshed results partial."""
    from app.services.avatars_query import (
        AvatarFilter,
        GROUP_OPTIONS,
        SORT_OPTIONS,
        STATUS_OPTIONS,
        VIEW_OPTIONS,
        build_avatar_view,
        list_avatars_page,
    )
    from app.services.reddit_status import check_all_reddit_statuses
    from app.services.safety import get_avatar_health
    from app.services import karma_tracker

    f = AvatarFilter(q=q.strip(), status=status, client_id=client_id, sort=sort,
                     view=view, group=group, page=page)
    page_data = list_avatars_page(db, f, viewer_client_id=None)
    check_all_reddit_statuses(db, page_data.items)

    page_data = list_avatars_page(db, f, viewer_client_id=None)

    visible_ids = [a.id for a in page_data.items]
    for g in page_data.groups:
        visible_ids.extend(a.id for a in g.avatars)
    top_by_avatar = karma_tracker.top_subreddits_for_avatars(db, visible_ids, limit=3)

    def _to_view(a):
        return build_avatar_view(
            a,
            get_avatar_health(db, a),
            page_data.client_by_id,
            top_subreddits=top_by_avatar.get(str(a.id), []),
        )

    flat = [_to_view(a) for a in page_data.items]
    grouped = []
    for g in page_data.groups:
        grouped.append({
            "key": g.key,
            "title": g.title,
            "brand": g.brand,
            "client_id": str(g.client.id) if g.client else None,
            "counts": g.counts,
            "avatars": [_to_view(a) for a in g.avatars],
        })

    ctx = {
        "request": request,
        "active_nav": "avatars",
        "avatars": flat,
        "groups": grouped,
        "f": f,
        "page_obj": page_data,
        "is_admin": True,
        "sort_options": SORT_OPTIONS,
        "status_options": STATUS_OPTIONS,
        "group_options": GROUP_OPTIONS,
        "view_options": VIEW_OPTIONS,
    }
    return templates.TemplateResponse(
        name="partials/admin_avatars_results.html", context=ctx, request=request,
    )


@router.get("/avatars/new", response_class=HTMLResponse)
def admin_avatar_new_page(
    request: Request,
    client_id: str = "",
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Admin page to create a new avatar."""
    client = None
    if client_id:
        try:
            client = db.query(Client).filter(Client.id == uuid.UUID(client_id)).first()
        except (ValueError, AttributeError):
            pass
    return templates.TemplateResponse(
        name="admin_avatar_new.html",
        context={"request": request, "active_nav": "avatars", "client_id": client_id, "client": client},
        request=request,
    )


@router.post("/avatars/new", response_class=HTMLResponse)
def admin_avatar_create_submit(
    request: Request,
    reddit_username: str = Form(...),
    email_address: str = Form(""),
    voice_profile_md: str = Form(""),
    tone_principles: str = Form(""),
    hill_i_die_on: str = Form(""),
    helpful_mode_topics: str = Form(""),
    constraints: str = Form(""),
    hobby_subreddits: str = Form(""),
    client_id: str = Form(""),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Create a new avatar from the admin panel. Auto-assigns to client if client_id provided."""
    hobby_list = [s.strip() for s in hobby_subreddits.split(",") if s.strip()] if hobby_subreddits else []
    avatar = Avatar(
        reddit_username=reddit_username,
        email_address=email_address or None,
        voice_profile_md=voice_profile_md or None,
        tone_principles=tone_principles or None,
        hill_i_die_on=hill_i_die_on or None,
        helpful_mode_topics=helpful_mode_topics or None,
        constraints=constraints or None,
        hobby_subreddits=hobby_list,
        active=True,
    )
    db.add(avatar)
    db.commit()
    db.refresh(avatar)
    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="create",
        entity_type="avatar",
        entity_id=avatar.id,
        details={"reddit_username": reddit_username},
    )

    # Auto-assign to client if created from client context
    redirect_url = "/admin/avatars"
    if client_id:
        try:
            cid = uuid.UUID(client_id)
            admin_service.assign_avatars_to_client(db, cid, [avatar.id], current_user.id)
            redirect_url = f"/admin/avatars?client_id={client_id}"
        except (ValueError, Exception):
            pass

    return RedirectResponse(url=redirect_url, status_code=303)


@router.post("/avatars/assign-to-client", response_class=HTMLResponse)
def admin_assign_avatar_to_client(
    request: Request,
    avatar_id: uuid.UUID = Form(...),
    client_id: uuid.UUID = Form(...),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Assign an avatar to a client from the avatars list page."""
    from app.services import admin as admin_service

    try:
        admin_service.assign_avatars_to_client(db, client_id, [avatar_id], current_user.id)
    except ValueError:
        pass

    return RedirectResponse(
        url=f"/admin/avatars?client_id={client_id}",
        status_code=303,
    )


@router.get("/avatars/available-for-client/{client_id}", response_class=HTMLResponse)
def admin_available_avatars_for_client(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Return a partial with unassigned avatars that can be assigned to this client."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return HTMLResponse("<p class='text-red-400 text-sm'>Client not found.</p>", status_code=404)

    # Get all active avatars not assigned to this client
    all_avatars = db.query(Avatar).filter(Avatar.active.is_(True)).order_by(Avatar.reddit_username.asc()).all()
    available = []
    for av in all_avatars:
        is_assigned = av.client_ids and str(client_id) in av.client_ids
        if not is_assigned:
            available.append(av)

    return templates.TemplateResponse(
        name="partials/admin_avatars_available.html",
        context={
            "request": request,
            "client": client,
            "available_avatars": available,
        },
        request=request,
    )


@router.get("/avatars/{avatar_id}", response_class=HTMLResponse)
def admin_avatar_detail(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Avatar detail page with phase information, progress, history, and pipeline results."""
    from app.models.activity_event import ActivityEvent
    from app.models.comment_draft import CommentDraft
    from app.models.hobby import HobbySubreddit
    from app.models.thread import RedditThread
    from app.services.safety import get_avatar_health
    from sqlalchemy import func, or_

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    # Get health data (includes phase progress and eligibility)
    health = get_avatar_health(db, avatar)

    # Query phase transition history
    phase_history = (
        db.query(ActivityEvent)
        .filter(
            ActivityEvent.event_type.in_(("phase_promotion", "auto_downgrade", "phase_override")),
            or_(
                ActivityEvent.event_metadata["avatar_id"].astext == str(avatar.id),
                ActivityEvent.message.ilike(f"%{avatar.reddit_username}%"),
            ),
        )
        .order_by(ActivityEvent.created_at.desc())
        .all()
    )

    # --- Pipeline Results ---

    # Professional comment drafts for this avatar
    pro_drafts = (
        db.query(CommentDraft)
        .filter(CommentDraft.avatar_id == avatar.id)
        .order_by(CommentDraft.created_at.desc())
        .limit(20)
        .all()
    )

    # Enrich drafts with thread data
    pro_drafts_enriched = []
    for draft in pro_drafts:
        thread = db.query(RedditThread).filter(RedditThread.id == draft.thread_id).first()
        pro_drafts_enriched.append({"draft": draft, "thread": thread})

    # Hobby comments for this avatar
    hobby_comments = (
        db.query(HobbySubreddit)
        .filter(HobbySubreddit.avatar_username == avatar.reddit_username)
        .order_by(HobbySubreddit.created_at.desc())
        .limit(20)
        .all()
    )

    # Stats
    hobby_total = db.query(func.count(HobbySubreddit.id)).filter(
        HobbySubreddit.avatar_username == avatar.reddit_username
    ).scalar() or 0
    hobby_pending = db.query(func.count(HobbySubreddit.id)).filter(
        HobbySubreddit.avatar_username == avatar.reddit_username,
        HobbySubreddit.status == "pending",
    ).scalar() or 0
    pro_pending = db.query(func.count(CommentDraft.id)).filter(
        CommentDraft.avatar_id == avatar.id,
        CommentDraft.status == "pending",
    ).scalar() or 0
    pro_approved = db.query(func.count(CommentDraft.id)).filter(
        CommentDraft.avatar_id == avatar.id,
        CommentDraft.status == "approved",
    ).scalar() or 0
    pro_posted = db.query(func.count(CommentDraft.id)).filter(
        CommentDraft.avatar_id == avatar.id,
        CommentDraft.status == "posted",
    ).scalar() or 0

    # AI costs for this avatar (via client_ids)
    # NOTE: AIUsageLog tracks costs at client level, not avatar level.
    # We show client costs here only as context — these are NOT avatar-specific costs.
    # TODO: Add avatar_id to AIUsageLog for accurate per-avatar billing.
    ai_costs = []
    assigned_clients = []
    if avatar.client_ids:
        for cid in avatar.client_ids:
            c = db.query(Client).filter(Client.id == uuid.UUID(cid)).first()
            if c:
                assigned_clients.append(c)

    # All clients for the assign dropdown (include inactive — avatar can belong to any client)
    all_clients = db.query(Client).order_by(Client.client_name).all()
    unassigned_clients = [c for c in all_clients if str(c.id) not in (avatar.client_ids or [])]

    # Karma history (30 days)
    from app.services.karma_history import get_karma_history
    karma_history = get_karma_history(db, avatar.id, days=30)

    return templates.TemplateResponse(
        name="admin_avatar_detail.html",
        context={
            "request": request,
            "active_nav": "avatars",
            "avatar": avatar,
            "health": health,
            "phase_history": phase_history,
            "pro_drafts": pro_drafts_enriched,
            "hobby_comments": hobby_comments,
            "stats": {
                "hobby_total": hobby_total,
                "hobby_pending": hobby_pending,
                "pro_pending": pro_pending,
                "pro_approved": pro_approved,
                "pro_posted": pro_posted,
            },
            "ai_costs": ai_costs,
            "assigned_clients": assigned_clients,
            "unassigned_clients": unassigned_clients,
            "karma_history": karma_history,
        },
        request=request,
    )


@router.get("/avatars/{avatar_id}/refresh", response_class=HTMLResponse)
def admin_avatar_refresh(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Refresh Reddit data for a single avatar (karma, status) and redirect back."""
    from app.services.reddit_status import check_reddit_status

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    try:
        check_reddit_status(db, avatar)
        db.commit()
    except Exception:
        pass  # Non-critical — page will still load with stale data

    return RedirectResponse(url=f"/admin/avatars/{avatar_id}", status_code=303)


@router.post("/avatars/{avatar_id}/toggle-active", response_class=HTMLResponse)
def admin_toggle_avatar_active(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Toggle avatar active status (pause/resume all activity for this avatar)."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if avatar:
        avatar.active = not avatar.active
        db.commit()
        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action="toggle_active",
            entity_type="avatar",
            details={"reddit_username": avatar.reddit_username, "active": avatar.active},
        )

    referer = request.headers.get("referer", "")
    if "/admin/avatars" in referer:
        return RedirectResponse(url="/admin/avatars", status_code=303)
    return RedirectResponse(url=request.headers.get("referer", "/admin/"), status_code=303)


@router.post("/avatars/{avatar_id}/unassign-from-client", response_class=HTMLResponse)
def admin_unassign_avatar_from_client(
    request: Request,
    avatar_id: uuid.UUID,
    client_id: uuid.UUID = Form(...),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Block direct avatar detachment outside the client lifecycle path."""
    return HTMLResponse(
        "Avatar assignments are released only when the client is deleted or deactivated.",
        status_code=409,
    )


@router.post("/avatars/{avatar_id}/phase-override", response_class=HTMLResponse)
def admin_avatar_phase_override(
    request: Request,
    avatar_id: uuid.UUID,
    target_phase: int = Form(...),
    reason: str = Form(...),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Admin override to set an avatar's warming phase manually."""
    import redis

    from app.config import get_settings
    from app.services.phase import PhaseTransitionManager
    from app.services.phase_lock import PhaseTransitionLock

    # Validate target_phase
    if target_phase not in {1, 2, 3}:
        return JSONResponse(
            status_code=422,
            content={"detail": "target_phase must be 1, 2, or 3"},
        )

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)
    previous_phase = avatar.warming_phase

    # Create Redis client and lock
    settings = get_settings()
    redis_client = redis.from_url(settings.redis_url)
    lock = PhaseTransitionLock(redis_client)

    try:
        PhaseTransitionManager(lock).admin_override(
            db=db,
            avatar=avatar,
            target_phase=target_phase,
            admin_user_id=str(current_user.id),
            reason=reason,
        )
    except ValueError as e:
        return JSONResponse(
            status_code=422,
            content={"detail": str(e)},
        )

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="phase_override",
        entity_type="avatar",
        entity_id=avatar.id,
        details={
            "reddit_username": avatar.reddit_username,
            "previous_phase": previous_phase,
            "target_phase": target_phase,
            "reason": reason,
        },
    )

    # Redirect back to the referring page
    referer = request.headers.get("referer", "")
    if f"/admin/avatars" in referer:
        return RedirectResponse(url=referer, status_code=303)
    return RedirectResponse(url="/admin/avatars", status_code=303)


@router.post("/avatars/{avatar_id}/freeze", response_class=HTMLResponse)
def admin_freeze_avatar(
    request: Request,
    avatar_id: uuid.UUID,
    freeze_reason: str = Form(...),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Freeze an avatar — sets is_frozen=True, records reason and timestamp."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    avatar.is_frozen = True
    avatar.freeze_reason = freeze_reason
    avatar.frozen_at = datetime.now(timezone.utc)
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="freeze",
        entity_type="avatar",
        entity_id=avatar.id,
        details={"reason": freeze_reason},
    )

    return RedirectResponse(url=f"/admin/avatars/{avatar_id}", status_code=303)


@router.post("/avatars/{avatar_id}/unfreeze", response_class=HTMLResponse)
def admin_unfreeze_avatar(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Unfreeze an avatar — clears frozen state."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    avatar.is_frozen = False
    avatar.freeze_reason = None
    avatar.frozen_at = None
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="unfreeze",
        entity_type="avatar",
        entity_id=avatar.id,
    )

    return RedirectResponse(url=f"/admin/avatars/{avatar_id}", status_code=303)


@router.post("/settings/pipeline-controls", response_class=HTMLResponse)
def admin_toggle_pipeline_control(
    request: Request,
    setting_key: str = Form(...),
    setting_value: str = Form(...),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Toggle a pipeline control setting (pipeline_enabled, generation_enabled, scrape_enabled)."""
    allowed_keys = {"pipeline_enabled", "generation_enabled", "scrape_enabled"}
    if setting_key not in allowed_keys:
        return HTMLResponse("Invalid setting", status_code=400)

    from app.services.settings import get_setting, set_setting
    set_setting(db, setting_key, setting_value, user_id=current_user.id)

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="toggle_kill_switch",
        entity_type="system_setting",
        details={"key": setting_key, "value": setting_value},
    )

    # If HTMX request, return the updated pipeline controls partial
    if request.headers.get("HX-Request", "").lower() == "true":
        pipeline_controls = {
            "pipeline_enabled": get_setting(db, "pipeline_enabled").lower() == "true",
            "generation_enabled": get_setting(db, "generation_enabled").lower() == "true",
            "scrape_enabled": get_setting(db, "scrape_enabled").lower() == "true",
        }
        return templates.TemplateResponse(
            name="partials/pipeline_controls.html",
            context={"request": request, "pipeline_controls": pipeline_controls},
            request=request,
        )

    return RedirectResponse(url="/admin/", status_code=303)


def _client_subreddit_counts(subreddits: list[dict]) -> dict:
    """Summarize assigned subreddit coverage for a client page."""
    return {
        "total": len(subreddits),
        "active": sum(1 for sub in subreddits if sub.get("is_active")),
        "paused": sum(1 for sub in subreddits if not sub.get("is_active")),
        "scraped": sum(1 for sub in subreddits if sub.get("last_scraped_at")),
        "never_scraped": sum(1 for sub in subreddits if not sub.get("last_scraped_at")),
        "shared": sum(1 for sub in subreddits if sub.get("shared")),
    }


@router.get("/subreddits/{client_id}", response_class=HTMLResponse)
def admin_subreddits(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    from app.models.ai_usage import AIUsageLog
    from sqlalchemy import func as sa_func

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return HTMLResponse("Client not found", status_code=404)

    subreddits = admin_service.list_client_subreddits(db, client_id)
    subreddit_counts = _client_subreddit_counts(subreddits)

    # AI costs for this client
    ai_costs_by_op = (
        db.query(
            AIUsageLog.operation,
            sa_func.count(AIUsageLog.id).label("calls"),
            sa_func.coalesce(sa_func.sum(AIUsageLog.cost_usd), 0).label("cost"),
            sa_func.coalesce(sa_func.sum(AIUsageLog.input_tokens), 0).label("input_tokens"),
            sa_func.coalesce(sa_func.sum(AIUsageLog.output_tokens), 0).label("output_tokens"),
        )
        .filter(AIUsageLog.client_id == client_id)
        .group_by(AIUsageLog.operation)
        .all()
    )
    ai_total_cost = sum(float(r.cost) for r in ai_costs_by_op)
    ai_total_calls = sum(r.calls for r in ai_costs_by_op)

    return templates.TemplateResponse(
        name="admin_subreddits.html",
        context={
            "request": request,
            "active_nav": "subreddits",
            "client": client,
            "subreddits": subreddits,
            "subreddit_counts": subreddit_counts,
            "error": None,
            "now_utc": datetime.now(timezone.utc),
            "ai_costs_by_op": ai_costs_by_op,
            "ai_total_cost": ai_total_cost,
            "ai_total_calls": ai_total_calls,
        },
        request=request,
    )


@router.post("/subreddits/{client_id}/add", response_class=HTMLResponse)
def admin_add_subreddit(
    request: Request,
    client_id: uuid.UUID,
    subreddit_name: str = Form(...),
    subreddit_type: str = Form("professional"),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    valid, err = admin_service.validate_subreddit_name(subreddit_name)
    if not valid:
        client = db.query(Client).filter(Client.id == client_id).first()
        subreddits = admin_service.list_client_subreddits(db, client_id)
        subreddit_counts = _client_subreddit_counts(subreddits)
        return templates.TemplateResponse(
            name="admin_subreddits.html",
            context={
                "request": request,
                "active_nav": "subreddits",
                "client": client,
                "subreddits": subreddits,
                "subreddit_counts": subreddit_counts,
                "error": err,
                "now_utc": datetime.now(timezone.utc),
            },
            request=request,
        )

    try:
        admin_service.add_subreddit(db, client_id, subreddit_name, subreddit_type, current_user.id)
    except ValueError as e:
        client = db.query(Client).filter(Client.id == client_id).first()
        subreddits = admin_service.list_client_subreddits(db, client_id)
        subreddit_counts = _client_subreddit_counts(subreddits)
        return templates.TemplateResponse(
            name="admin_subreddits.html",
            context={
                "request": request,
                "active_nav": "subreddits",
                "client": client,
                "subreddits": subreddits,
                "subreddit_counts": subreddit_counts,
                "error": str(e),
                "now_utc": datetime.now(timezone.utc),
            },
            request=request,
        )

    # Immediate scrape — fetch data right away so user doesn't wait for queue
    try:
        from app.services.scrape_queue import scrape_subreddit_immediate
        scrape_subreddit_immediate(db, subreddit_name, str(client_id))
    except Exception:
        pass  # Non-critical — subreddit was added, scrape will happen on next tick

    return RedirectResponse(url=f"/admin/subreddits/{client_id}", status_code=303)


@router.post("/subreddits/{client_id}/{subreddit_id}/remove", response_class=HTMLResponse)
def admin_remove_subreddit(
    request: Request,
    client_id: uuid.UUID,
    subreddit_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    try:
        admin_service.remove_subreddit(db, subreddit_id, current_user.id)
    except ValueError:
        pass

    return RedirectResponse(url=f"/admin/subreddits/{client_id}", status_code=303)


# ---------------------------------------------------------------------------
# Celery task monitoring (6.7)
# ---------------------------------------------------------------------------

@router.get("/tasks", response_class=HTMLResponse)
def admin_tasks(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    schedule = operations_dashboard.get_schedule_with_history(db)
    run_history = operations_dashboard.get_run_history(
        db, limit=30, event_types=operations_dashboard._ALL_EVENT_TYPES
    )
    clients_list = db.query(Client).filter(Client.is_active.is_(True)).order_by(Client.client_name).all()

    return templates.TemplateResponse(
        name="admin_tasks.html",
        context={
            "request": request,
            "active_nav": "tasks",
            "schedule": schedule,
            "run_history": run_history,
            "clients": clients_list,
            "error": None,
        },
        request=request,
    )


@router.post("/tasks/trigger/{pipeline_type}/{entity_id}", response_class=HTMLResponse)
def admin_trigger_pipeline(
    request: Request,
    pipeline_type: str,
    entity_id: str,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    error = None
    task_id = None
    try:
        from app.tasks.worker import celery_app
        task_id = admin_service.trigger_pipeline(celery_app, pipeline_type, entity_id)
        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action="trigger_pipeline",
            entity_type="task",
            details={"pipeline_type": pipeline_type, "entity_id": entity_id, "task_id": task_id},
        )
    except Exception as e:
        error = str(e)

    schedule = operations_dashboard.get_schedule_with_history(db)
    run_history = operations_dashboard.get_run_history(
        db, limit=30, event_types=operations_dashboard._ALL_EVENT_TYPES
    )
    clients_list = db.query(Client).filter(Client.is_active.is_(True)).order_by(Client.client_name).all()

    return templates.TemplateResponse(
        name="admin_tasks.html",
        context={
            "request": request,
            "active_nav": "tasks",
            "schedule": schedule,
            "run_history": run_history,
            "clients": clients_list,
            "error": error,
            "success": f"Pipeline triggered (task: {task_id})" if task_id else None,
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# System health (6.8)
# ---------------------------------------------------------------------------

def _get_collector(request: Request) -> MetricsCollector:
    """Resolve the process-wide MetricsCollector (falls back to singleton)."""
    return getattr(request.app.state, "metrics_collector", None) or get_metrics_collector()


def _rate_limit_context(request: Request) -> dict:
    state = _get_collector(request).get_rate_limit()
    return {
        "request": request,
        "rate_limit": state,
        "color": gauge_color(state.usage_pct),
    }


@router.get("/health", response_class=HTMLResponse)
def admin_health(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Render health page shell instantly; heavy checks load via HTMX."""
    db_stats = admin_service.get_db_statistics(db)
    collector = _get_collector(request)
    window_minutes = collector.get_window_minutes()

    # Service names for lazy-loaded cards
    services = ["postgresql", "redis", "celery", "reddit", "llm"]

    return templates.TemplateResponse(
        name="admin_health.html",
        context={
            "request": request,
            "active_nav": "health",
            "services": services,
            "db_stats": db_stats,
            "window_minutes": window_minutes,
        },
        request=request,
    )


@router.get("/health/service/{service_name}", response_class=HTMLResponse)
def admin_health_service_card(
    service_name: str,
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX endpoint: lazy-load a single service health card."""
    info = admin_service.check_single_service(service_name, db)
    return templates.TemplateResponse(
        name="partials/admin_health_card.html",
        context={
            "request": request,
            "service": service_name,
            "info": info,
        },
        request=request,
    )


@router.post("/health/test/{service_name}", response_class=HTMLResponse)
def admin_health_test_service(
    service_name: str,
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX endpoint: re-test a single service and return updated card HTML."""
    result = admin_service.check_single_service(service_name, db)
    return templates.TemplateResponse(
        name="partials/admin_health_card.html",
        context={
            "request": request,
            "service": service_name,
            "info": result,
        },
        request=request,
    )


# --- API health metrics widgets (Reddit API Health Dashboard) ---------------


@router.get("/health/metrics")
def admin_health_metrics_json(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """JSON snapshot of Reddit + LLM API metrics and rate limit state."""
    collector = _get_collector(request)
    snapshot = health_metrics.get_metrics_snapshot(db, collector)
    return JSONResponse(snapshot)


@router.get("/health/widget/rate-limit", response_class=HTMLResponse)
def admin_health_widget_rate_limit(
    request: Request,
    current_user: User = Depends(require_superuser),
):
    return templates.TemplateResponse(
        name="partials/health_rate_limit.html",
        context=_rate_limit_context(request),
        request=request,
    )


@router.get("/health/widget/reddit-metrics", response_class=HTMLResponse)
def admin_health_widget_reddit_metrics(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    collector = _get_collector(request)
    metrics = health_metrics.get_reddit_api_metrics(
        db, window_minutes=collector.get_window_minutes()
    )
    return templates.TemplateResponse(
        name="partials/health_reddit_metrics.html",
        context={"request": request, "metrics": metrics},
        request=request,
    )


@router.get("/health/widget/llm-metrics", response_class=HTMLResponse)
def admin_health_widget_llm_metrics(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    collector = _get_collector(request)
    metrics = health_metrics.get_llm_api_metrics(
        db, window_minutes=collector.get_window_minutes()
    )
    return templates.TemplateResponse(
        name="partials/health_llm_metrics.html",
        context={"request": request, "metrics": metrics},
        request=request,
    )


@router.get("/health/widget/scrape-freshness", response_class=HTMLResponse)
def admin_health_widget_scrape_freshness(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    freshness = health_metrics.get_all_scrape_freshness(db)
    return templates.TemplateResponse(
        name="partials/health_scrape_freshness.html",
        context={
            "request": request,
            "freshness": freshness,
            "now_utc": datetime.now(timezone.utc),
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# AI cost tracking (6.9)
# ---------------------------------------------------------------------------

@router.get("/ai-costs", response_class=HTMLResponse)
def admin_ai_costs(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
    client_id: str | None = None,
):
    summary = admin_service.get_ai_cost_summary(db)
    by_client = admin_service.get_ai_costs_by_client(db)
    by_operation = admin_service.get_ai_costs_by_operation(db)
    by_model = admin_service.get_ai_costs_by_model(db)
    timeline = admin_service.get_ai_costs_daily_timeline(db, days=14)
    recent_calls = admin_service.get_ai_costs_recent_calls(db, limit=30, client_id=client_id)
    efficiency = admin_service.get_ai_cost_efficiency(db)

    # Budget from settings or default
    from app.services.settings import get_setting
    budget_str = get_setting(db, "monthly_budget_usd")
    budget = float(budget_str) if budget_str else 100.0
    budget_pct = (summary["total_cost"] / budget * 100) if budget > 0 else 0

    # Clients for filter dropdown (include inactive — they have cost history)
    clients = db.query(Client).order_by(Client.client_name).all()

    return templates.TemplateResponse(
        name="admin_ai_costs.html",
        context={
            "request": request,
            "active_nav": "ai-costs",
            "summary": summary,
            "by_client": by_client,
            "by_operation": by_operation,
            "by_model": by_model,
            "timeline": timeline,
            "recent_calls": recent_calls,
            "efficiency": efficiency,
            "budget": budget,
            "budget_pct": budget_pct,
            "clients": clients,
            "filter_client_id": client_id or "",
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Audit logs (6.10)
# ---------------------------------------------------------------------------

@router.get("/audit-logs", response_class=HTMLResponse)
def admin_audit_logs(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    user_id: str | None = None,
    client_id: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    search: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    filter_user_id = None
    filter_client_id = None
    filter_date_from = None
    filter_date_to = None

    if user_id:
        try:
            filter_user_id = uuid.UUID(user_id)
        except ValueError:
            pass
    if client_id:
        try:
            filter_client_id = uuid.UUID(client_id)
        except ValueError:
            pass
    if date_from:
        try:
            filter_date_from = datetime.fromisoformat(date_from)
        except ValueError:
            pass
    if date_to:
        try:
            filter_date_to = datetime.fromisoformat(date_to)
        except ValueError:
            pass

    logs, total = audit_service.query_audit_logs(
        db,
        page=page,
        per_page=per_page,
        user_id=filter_user_id,
        client_id=filter_client_id,
        action=action if action else None,
        entity_type=entity_type if entity_type else None,
        search=search if search else None,
        date_from=filter_date_from,
        date_to=filter_date_to,
    )
    pagination = _paginate(page, per_page, total)

    # Get users and clients for filter dropdowns
    users_list = db.query(User).order_by(User.email).all()
    clients_list = db.query(Client).order_by(Client.client_name).all()
    entity_types = audit_service.get_distinct_entity_types(db)
    actions_list = audit_service.get_distinct_actions(db)

    return templates.TemplateResponse(
        name="admin_audit_logs.html",
        context={
            "request": request,
            "active_nav": "audit-logs",
            "logs": logs,
            "pagination": pagination,
            "users": users_list,
            "clients": clients_list,
            "entity_types": entity_types,
            "actions_list": actions_list,
            "filters": {
                "user_id": user_id or "",
                "client_id": client_id or "",
                "action": action or "",
                "entity_type": entity_type or "",
                "search": search or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
            },
        },
        request=request,
    )


@router.post("/audit-logs/delete-all")
def admin_audit_logs_delete_all(
    request: Request,
    user_id: str | None = Form(None),
    client_id: str | None = Form(None),
    action: str | None = Form(None),
    entity_type: str | None = Form(None),
    search: str | None = Form(None),
    date_from: str | None = Form(None),
    date_to: str | None = Form(None),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Delete all audit logs, or filtered subset if filters are provided."""
    filter_user_id = None
    filter_client_id = None
    filter_date_from = None
    filter_date_to = None

    if user_id:
        try:
            filter_user_id = uuid.UUID(user_id)
        except ValueError:
            pass
    if client_id:
        try:
            filter_client_id = uuid.UUID(client_id)
        except ValueError:
            pass
    if date_from:
        try:
            filter_date_from = datetime.fromisoformat(date_from)
        except ValueError:
            pass
    if date_to:
        try:
            filter_date_to = datetime.fromisoformat(date_to)
        except ValueError:
            pass

    has_filters = any([filter_user_id, filter_client_id, action, entity_type, search, filter_date_from, filter_date_to])

    if has_filters:
        deleted = audit_service.delete_filtered_audit_logs(
            db,
            user_id=filter_user_id,
            client_id=filter_client_id,
            action=action if action else None,
            entity_type=entity_type if entity_type else None,
            search=search if search else None,
            date_from=filter_date_from,
            date_to=filter_date_to,
        )
    else:
        deleted = audit_service.delete_all_audit_logs(db)

    return RedirectResponse(url="/admin/audit-logs", status_code=303)


# ---------------------------------------------------------------------------
# Onboarding wizard (8.x)
# ---------------------------------------------------------------------------

WIZARD_STEP_NAMES = {
    1: "Profile",
    2: "Subreddits",
    3: "Keywords",
    4: "Avatars",
    5: "Review",
    6: "Test Run",
}
WIZARD_TOTAL_STEPS = 6


def _wizard_context(
    request: Request,
    step: int,
    client: Client | None,
    **extra,
) -> dict:
    """Build common context dict for wizard step templates."""
    return {
        "request": request,
        "active_nav": "clients",
        "step": step,
        "total_steps": WIZARD_TOTAL_STEPS,
        "step_names": WIZARD_STEP_NAMES,
        "client": client,
        **extra,
    }


@router.get("/clients/{client_id}/onboard/step/{step_num}", response_class=HTMLResponse)
def onboard_step_get(
    request: Request,
    client_id: str,
    step_num: int,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Render wizard step n (1-7)."""
    if step_num < 1 or step_num > WIZARD_TOTAL_STEPS:
        return RedirectResponse(url="/admin/clients", status_code=303)

    # Step 1 supports "new" as client_id for creating a new client
    client = None
    if client_id != "new":
        try:
            cid = uuid.UUID(client_id)
            client = db.query(Client).filter(Client.id == cid).first()
        except ValueError:
            pass
        if not client and step_num > 1:
            return RedirectResponse(url="/admin/clients", status_code=303)

    # Step 1: Client Profile
    if step_num == 1:
        return templates.TemplateResponse(
            name="admin_onboard_step1.html",
            context=_wizard_context(request, 1, client, error=None),
            request=request,
        )

    # For steps 2-7, client must exist
    if not client:
        return RedirectResponse(url="/admin/clients/new/onboard/step/1", status_code=303)

    # Step 2: Subreddits
    if step_num == 2:
        subreddits = (
            db.query(ClientSubredditAssignment)
            .filter(ClientSubredditAssignment.client_id == client.id, ClientSubredditAssignment.is_active.is_(True))
            .order_by(ClientSubredditAssignment.created_at.desc())
            .all()
        )
        return templates.TemplateResponse(
            name="admin_onboard_step2.html",
            context=_wizard_context(request, 2, client, subreddits=subreddits, error=None),
            request=request,
        )

    # Step 3: Keywords
    if step_num == 3:
        keywords = admin_service.get_client_keywords(db, client.id)
        return templates.TemplateResponse(
            name="admin_onboard_step3.html",
            context=_wizard_context(request, 3, client, keywords=keywords, error=None),
            request=request,
        )

    # Step 4: Avatars
    if step_num == 4:
        all_avatars = db.query(Avatar).filter(Avatar.active.is_(True)).all()
        assigned_ids = set()
        # Show only avatars that are: assigned to THIS client, or not assigned to any client
        visible_avatars = []
        for av in all_avatars:
            is_assigned_here = av.client_ids and str(client.id) in av.client_ids
            is_unassigned = not av.client_ids or len(av.client_ids) == 0
            if is_assigned_here:
                assigned_ids.add(str(av.id))
                visible_avatars.append(av)
            elif is_unassigned:
                visible_avatars.append(av)
        return templates.TemplateResponse(
            name="admin_onboard_step4.html",
            context=_wizard_context(
                request, 4, client,
                avatars=visible_avatars,
                assigned_ids=assigned_ids,
                error=None,
            ),
            request=request,
        )

    # Step 5: Review
    if step_num == 5:
        subreddits = (
            db.query(ClientSubredditAssignment)
            .filter(ClientSubredditAssignment.client_id == client.id, ClientSubredditAssignment.is_active.is_(True))
            .all()
        )
        keywords = admin_service.get_client_keywords(db, client.id)
        avatars = db.query(Avatar).filter(Avatar.client_ids.any(str(client.id))).all()
        return templates.TemplateResponse(
            name="admin_onboard_step6.html",
            context=_wizard_context(
                request, 5, client,
                subreddits=subreddits,
                keywords=keywords,
                avatars=avatars,
            ),
            request=request,
        )

    # Step 6: Test Run
    if step_num == 6:
        return templates.TemplateResponse(
            name="admin_onboard_step7.html",
            context=_wizard_context(request, 6, client, error=None, task_id=None),
            request=request,
        )

    return RedirectResponse(url="/admin/clients", status_code=303)


@router.post("/clients/{client_id}/onboard/step/{step_num}", response_class=HTMLResponse)
def onboard_step_post(
    request: Request,
    client_id: str,
    step_num: int,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
    # Step 1 fields
    client_name: Optional[str] = Form(None),
    brand_name: Optional[str] = Form(None),
    company_profile: Optional[str] = Form(None),
    company_worldview: Optional[str] = Form(None),
    company_problem: Optional[str] = Form(None),
    competitive_landscape: Optional[str] = Form(None),
    brand_voice: Optional[str] = Form(None),
    icp_profiles: Optional[str] = Form(None),
    # Step 2 fields
    subreddit_name: Optional[str] = Form(None),
    subreddit_type: Optional[str] = Form(None),
    remove_subreddit_id: Optional[str] = Form(None),
    # Step 3 fields
    keyword_name: Optional[str] = Form(None),
    keyword_priority: Optional[str] = Form(None),
    remove_keyword_index: Optional[str] = Form(None),
    # Step 4 fields (avatar_ids handled via getlist)
    # Step 6 fields
    trigger_pipeline: Optional[str] = Form(None),
):
    """Process wizard step n form submission."""
    if step_num < 1 or step_num > WIZARD_TOTAL_STEPS:
        return RedirectResponse(url="/admin/clients", status_code=303)

    client = None
    if client_id != "new":
        try:
            cid = uuid.UUID(client_id)
            client = db.query(Client).filter(Client.id == cid).first()
        except ValueError:
            pass

    # --- Step 1: Create or update client ---
    if step_num == 1:
        if not client_name or not client_name.strip():
            return templates.TemplateResponse(
                name="admin_onboard_step1.html",
                context=_wizard_context(request, 1, client, error="Client name is required"),
                request=request,
            )
        if not brand_name or not brand_name.strip():
            return templates.TemplateResponse(
                name="admin_onboard_step1.html",
                context=_wizard_context(request, 1, client, error="Brand name is required"),
                request=request,
            )

        if client:
            # Update existing client
            admin_service.update_client(
                db,
                client_id=client.id,
                current_user_id=current_user.id,
                client_name=client_name,
                brand_name=brand_name,
                company_profile=company_profile or None,
                company_worldview=company_worldview or None,
                company_problem=company_problem or None,
                competitive_landscape=competitive_landscape or None,
                brand_voice=brand_voice or None,
                icp_profiles=icp_profiles or None,
            )
            return RedirectResponse(
                url=f"/admin/clients/{client.id}/onboard/step/2",
                status_code=303,
            )
        else:
            # Create new client
            new_client = admin_service.create_client(
                db,
                current_user_id=current_user.id,
                client_name=client_name,
                brand_name=brand_name,
                company_profile=company_profile or None,
                company_worldview=company_worldview or None,
                company_problem=company_problem or None,
                competitive_landscape=competitive_landscape or None,
                brand_voice=brand_voice or None,
                icp_profiles=icp_profiles or None,
            )
            return RedirectResponse(
                url=f"/admin/clients/{new_client.id}/onboard/step/2",
                status_code=303,
            )

    # For steps 2-7, client must exist
    if not client:
        return RedirectResponse(url="/admin/clients/new/onboard/step/1", status_code=303)

    # --- Step 2: Add/remove subreddits ---
    if step_num == 2:
        error = None

        # Handle remove action
        if remove_subreddit_id:
            try:
                sub_id = uuid.UUID(remove_subreddit_id)
                admin_service.remove_subreddit(db, sub_id, current_user.id)
            except ValueError:
                pass
            return RedirectResponse(
                url=f"/admin/clients/{client.id}/onboard/step/2",
                status_code=303,
            )

        # Handle add action
        if subreddit_name and subreddit_name.strip():
            valid, err = admin_service.validate_subreddit_name(subreddit_name.strip())
            if not valid:
                error = err
            else:
                try:
                    admin_service.add_subreddit(
                        db, client.id, subreddit_name.strip(),
                        subreddit_type or "professional", current_user.id,
                    )
                except ValueError as e:
                    error = str(e)

            if error:
                subreddits = (
                    db.query(ClientSubredditAssignment)
                    .filter(ClientSubredditAssignment.client_id == client.id, ClientSubredditAssignment.is_active.is_(True))
                    .order_by(ClientSubredditAssignment.created_at.desc())
                    .all()
                )
                return templates.TemplateResponse(
                    name="admin_onboard_step2.html",
                    context=_wizard_context(request, 2, client, subreddits=subreddits, error=error),
                    request=request,
                )

            return RedirectResponse(
                url=f"/admin/clients/{client.id}/onboard/step/2",
                status_code=303,
            )

        # No action — just redirect to next step (user clicked "Next")
        return RedirectResponse(
            url=f"/admin/clients/{client.id}/onboard/step/3",
            status_code=303,
        )

    # --- Step 3: Add/remove keywords ---
    if step_num == 3:
        error = None

        # Handle remove action
        if remove_keyword_index is not None and remove_keyword_index != "":
            try:
                idx = int(remove_keyword_index)
                admin_service.remove_keyword(db, client.id, idx, current_user.id)
            except (ValueError, IndexError):
                pass
            return RedirectResponse(
                url=f"/admin/clients/{client.id}/onboard/step/3",
                status_code=303,
            )

        # Handle add action
        if keyword_name and keyword_name.strip():
            priority = keyword_priority or "MEDIUM"
            valid, err = admin_service.validate_keyword(keyword_name.strip(), priority)
            if not valid:
                error = err
            else:
                admin_service.add_keyword(
                    db, client.id, keyword_name.strip(), priority, current_user.id,
                )

            if error:
                keywords = admin_service.get_client_keywords(db, client.id)
                return templates.TemplateResponse(
                    name="admin_onboard_step3.html",
                    context=_wizard_context(request, 3, client, keywords=keywords, error=error),
                    request=request,
                )

            return RedirectResponse(
                url=f"/admin/clients/{client.id}/onboard/step/3",
                status_code=303,
            )

        # No action — next step
        return RedirectResponse(
            url=f"/admin/clients/{client.id}/onboard/step/4",
            status_code=303,
        )

    # --- Step 4: Assign avatars (handled by dedicated async route below) ---
    if step_num == 4:
        # This case is handled by the dedicated async route below
        # If we somehow get here, redirect to step 5
        return RedirectResponse(
            url=f"/admin/clients/{client.id}/onboard/step/5",
            status_code=303,
        )

    # --- Step 5: Review — just redirect to step 6 ---
    if step_num == 5:
        return RedirectResponse(
            url=f"/admin/clients/{client.id}/onboard/step/6",
            status_code=303,
        )

    # --- Step 6: Trigger test run ---
    if step_num == 6:
        error = None
        task_id = None
        try:
            from app.tasks.worker import celery_app
            task_id = admin_service.trigger_pipeline(celery_app, "full", str(client.id))
            audit_service.log_action(
                db=db,
                user_id=current_user.id,
                action="trigger_pipeline",
                entity_type="task",
                client_id=client.id,
                details={"pipeline_type": "full", "client_id": str(client.id), "task_id": task_id},
            )
        except Exception as e:
            error = str(e)

        return templates.TemplateResponse(
            name="admin_onboard_step7.html",
            context=_wizard_context(request, 6, client, error=error, task_id=task_id),
            request=request,
        )

    return RedirectResponse(url="/admin/clients", status_code=303)


async def _get_form(request: Request):
    """Helper to get form data from request asynchronously."""
    return await request.form()


@router.post("/clients/{client_id}/onboard/step/4/avatars", response_class=HTMLResponse)
async def onboard_step4_avatars(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Process avatar assignment from wizard step 4 (async to handle multi-value form)."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return RedirectResponse(url="/admin/clients", status_code=303)

    form_data = await request.form()
    selected_avatar_ids = form_data.getlist("avatar_ids")

    # First, unassign all avatars from this client
    all_avatars = db.query(Avatar).filter(Avatar.active.is_(True)).all()
    for av in all_avatars:
        if av.client_ids and str(client.id) in av.client_ids:
            admin_service.unassign_avatar_from_client(db, client.id, av.id, current_user.id)

    # Then assign selected ones
    if selected_avatar_ids:
        avatar_uuids = []
        for aid in selected_avatar_ids:
            try:
                avatar_uuids.append(uuid.UUID(aid))
            except ValueError:
                pass
        if avatar_uuids:
            admin_service.assign_avatars_to_client(db, client.id, avatar_uuids, current_user.id)

    return RedirectResponse(
        url=f"/admin/clients/{client.id}/onboard/step/5",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# System settings (admin UI)
# ---------------------------------------------------------------------------

@router.get("/settings", response_class=HTMLResponse)
def admin_settings(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Display all system settings grouped by category."""
    from app.services.settings import get_all_settings, init_defaults, seed_from_env
    from app.config import get_settings as get_bootstrap_settings

    # Ensure all default settings exist in DB and metadata is synced
    init_defaults(db)
    # Seed values from .env for any empty settings (one-time migration)
    seed_from_env(db)

    all_settings = get_all_settings(db)

    # Group settings by their group field
    grouped: dict[str, list[dict]] = {}
    for s in all_settings:
        grouped.setdefault(s["group"], []).append(s)

    # Include DATABASE_URL as a read-only informational row in the database group
    bootstrap = get_bootstrap_settings()
    db_url_row = {
        "key": "database_url",
        "value": bootstrap.database_url,
        "is_secret": False,
        "description": "Database connection URL (read-only, change in .env file)",
        "group": "database",
        "is_set": True,
        "updated_at": None,
        "read_only": True,
    }
    grouped.setdefault("database", []).insert(0, db_url_row)

    return templates.TemplateResponse(
        name="admin_system_settings.html",
        context={
            "request": request,
            "active_nav": "settings",
            "grouped_settings": grouped,
        },
        request=request,
    )


@router.post("/settings/bulk-save", response_class=HTMLResponse)
async def admin_bulk_save_settings(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Bulk-save multiple settings from form data (HTMX partial response)."""
    from app.services.settings import bulk_save_settings

    form_data = await request.form()
    updates: dict[str, str] = {}
    for field_key, field_value in form_data.items():
        if field_key.startswith("setting_"):
            setting_key = field_key[len("setting_"):]
            updates[setting_key] = field_value

    if updates:
        bulk_save_settings(db, updates, user_id=current_user.id)

    return HTMLResponse(
        content=(
            '<span class="inline-flex items-center text-green-400 text-sm">'
            '<svg class="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">'
            '<path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>'
            "</svg>"
            f"{len(updates)} setting(s) saved"
            "</span>"
        )
    )


@router.post("/settings/test/reddit", response_class=HTMLResponse)
def admin_test_reddit(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Test Reddit API connection and return HTMX partial with result."""
    from app.services.settings import test_reddit_connection

    result = test_reddit_connection(db)

    if result["success"]:
        html = (
            '<span class="inline-flex items-center text-green-400 text-sm">'
            '<svg class="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">'
            '<path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>'
            "</svg>"
            "Connected"
            "</span>"
        )
    else:
        msg = result["message"]
        html = (
            '<span class="inline-flex items-center text-red-400 text-sm">'
            '<svg class="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">'
            '<path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>'
            "</svg>"
            f"{msg}"
            "</span>"
        )

    return HTMLResponse(content=html)


@router.post("/settings/test/llm", response_class=HTMLResponse)
def admin_test_llm(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Test LLM API connection and return HTMX partial with result."""
    from app.services.settings import test_llm_connection

    result = test_llm_connection(db)

    if result["success"]:
        html = (
            '<span class="inline-flex items-center text-green-400 text-sm">'
            '<svg class="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">'
            '<path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>'
            "</svg>"
            "Connected"
            "</span>"
        )
    else:
        msg = result["message"]
        html = (
            '<span class="inline-flex items-center text-red-400 text-sm">'
            '<svg class="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">'
            '<path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>'
            "</svg>"
            f"{msg}"
            "</span>"
        )

    return HTMLResponse(content=html)


@router.post("/settings/{key}", response_class=HTMLResponse)
def admin_update_setting(
    request: Request,
    key: str,
    value: str = Form(...),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Save a single setting value (HTMX partial response)."""
    from app.services.settings import set_setting, invalidate_cache

    set_setting(db, key, value, user_id=current_user.id)
    invalidate_cache(key)

    return HTMLResponse(
        content=(
            '<span class="inline-flex items-center text-green-400 text-sm">'
            '<svg class="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">'
            '<path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>'
            "</svg>"
            "Saved"
            "</span>"
        )
    )


# ---------------------------------------------------------------------------
# Billing placeholder (6.11)
# ---------------------------------------------------------------------------

@router.get("/billing", response_class=HTMLResponse)
def admin_billing(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    ai_costs = admin_service.get_ai_cost_summary(db)

    from app.services.settings import get_setting
    budget_str = get_setting(db, "monthly_budget_usd")
    budget = float(budget_str) if budget_str else 100.0

    return templates.TemplateResponse(
        name="admin_billing.html",
        context={
            "request": request,
            "active_nav": "billing",
            "ai_costs": ai_costs,
            "budget": budget,
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Scrape Queue Dashboard
# ---------------------------------------------------------------------------

@router.get("/scrape-queue", response_class=HTMLResponse)
def admin_scrape_queue(
    request: Request,
    toast: str | None = None,
    toast_type: str | None = None,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Full scrape queue dashboard page."""
    import redis as redis_lib
    from app.config import get_settings
    from app.services.settings import get_setting
    from app.services import scrape_queue as sq_service

    settings = get_settings()
    redis_client = redis_lib.Redis.from_url(settings.redis_url, decode_responses=True)

    freshness_hours = int(get_setting(db, "scrape_freshness_window_hours") or "12")
    max_rpm = int(get_setting(db, "scrape_rate_limit_rpm") or "30")
    tick_interval = int(get_setting(db, "scrape_tick_interval_seconds") or "60")
    scrape_enabled = get_setting(db, "scrape_enabled") != "false"

    status = sq_service.get_queue_status(db, redis_client, freshness_hours, max_rpm)
    waiting_list = sq_service.get_waiting_list(db, redis_client, freshness_hours, limit=30)
    metrics = sq_service.get_pipeline_metrics(db, freshness_hours)

    return templates.TemplateResponse(
        name="admin_scrape_queue.html",
        context={
            "request": request,
            "active_nav": "scrape-queue",
            "status": status,
            "waiting_list": waiting_list,
            "metrics": metrics,
            "scrape_enabled": scrape_enabled,
            "settings": {
                "tick_interval": tick_interval,
                "freshness_hours": freshness_hours,
                "max_rpm": max_rpm,
            },
            "toast": toast,
            "toast_type": toast_type or "info",
        },
        request=request,
    )


@router.get("/scrape-queue/status", response_class=HTMLResponse)
def admin_scrape_queue_status(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial — queue stats cards."""
    import redis as redis_lib
    from app.config import get_settings
    from app.services.settings import get_setting
    from app.services import scrape_queue as sq_service

    settings = get_settings()
    redis_client = redis_lib.Redis.from_url(settings.redis_url, decode_responses=True)

    freshness_hours = int(get_setting(db, "scrape_freshness_window_hours") or "12")
    max_rpm = int(get_setting(db, "scrape_rate_limit_rpm") or "30")
    scrape_enabled = get_setting(db, "scrape_enabled") != "false"

    status = sq_service.get_queue_status(db, redis_client, freshness_hours, max_rpm)

    return templates.TemplateResponse(
        name="partials/scrape_queue_status.html",
        context={
            "request": request,
            "status": status,
            "scrape_enabled": scrape_enabled,
        },
        request=request,
    )


@router.get("/scrape-queue/waiting-list", response_class=HTMLResponse)
def admin_scrape_queue_waiting_list(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial — waiting subreddits table."""
    import redis as redis_lib
    from app.config import get_settings
    from app.services.settings import get_setting
    from app.services import scrape_queue as sq_service

    settings = get_settings()
    redis_client = redis_lib.Redis.from_url(settings.redis_url, decode_responses=True)

    freshness_hours = int(get_setting(db, "scrape_freshness_window_hours") or "12")
    waiting_list = sq_service.get_waiting_list(db, redis_client, freshness_hours, limit=30)

    return templates.TemplateResponse(
        name="partials/scrape_queue_waiting_list.html",
        context={
            "request": request,
            "waiting_list": waiting_list,
        },
        request=request,
    )


@router.post("/scrape-queue/toggle", response_class=HTMLResponse)
def admin_scrape_queue_toggle(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Toggle scrape_enabled setting on/off."""
    from app.services.settings import get_setting, set_setting

    current = get_setting(db, "scrape_enabled")
    new_value = "false" if current != "false" else "true"
    set_setting(db, "scrape_enabled", new_value, user_id=current_user.id)

    # Return updated status partial
    return RedirectResponse(url="/admin/scrape-queue", status_code=303)


@router.post("/scrape-queue/settings", response_class=HTMLResponse)
def admin_scrape_queue_settings(
    request: Request,
    tick_interval: int = Form(...),
    freshness_hours: int = Form(...),
    max_rpm: int = Form(...),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Update scrape queue settings with validation."""
    from app.services.settings import set_setting

    errors = []

    # Validate tick_interval (30-300)
    if tick_interval < 30 or tick_interval > 300:
        errors.append("Tick interval must be between 30 and 300 seconds")

    # Validate freshness_hours (1-168)
    if freshness_hours < 1 or freshness_hours > 168:
        errors.append("Freshness window must be between 1 and 168 hours")

    # Validate max_rpm (1-60)
    if max_rpm < 1 or max_rpm > 60:
        errors.append("Rate limit must be between 1 and 60 requests per minute")

    if errors:
        # Return error response
        return HTMLResponse(
            content=f'<div class="text-red-400 text-sm">{"<br>".join(errors)}</div>',
            status_code=422,
        )

    # Save settings
    set_setting(db, "scrape_tick_interval_seconds", str(tick_interval), user_id=current_user.id)
    set_setting(db, "scrape_freshness_window_hours", str(freshness_hours), user_id=current_user.id)
    set_setting(db, "scrape_rate_limit_rpm", str(max_rpm), user_id=current_user.id)

    return RedirectResponse(url="/admin/scrape-queue", status_code=303)


@router.post("/scrape-queue/trigger", response_class=HTMLResponse)
def admin_scrape_queue_trigger(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Manually trigger a synchronous scrape of the most stale subreddit.

    Runs the scrape directly in the HTTP request (no Celery worker needed).
    Takes 5-15 seconds depending on Reddit API response time.
    Returns a toast with results showing what was scraped and the outcome.
    """
    import time
    import uuid
    from datetime import datetime, timezone
    from urllib.parse import urlencode

    from app.models.scrape_log import ScrapeLog
    from app.models.subreddit import ClientSubreddit, Subreddit
    from app.models.thread import RedditThread
    from app.services.reddit import scrape_subreddit, deduplicate_posts
    from app.services.transparency import record_activity_event

    # Query next stale subreddit (using shared registry)
    candidates = (
        db.query(
            ClientSubreddit.subreddit_name,
            ClientSubreddit.client_id,
            Client.client_name,
        )
        .join(Client, Client.id == ClientSubreddit.client_id)
        .filter(
            ClientSubreddit.is_active.is_(True),
            Client.is_active.is_(True),
        )
        .order_by(
            ClientSubreddit.last_scraped_at.asc().nulls_first(),
            ClientSubreddit.subreddit_name.asc(),
        )
        .limit(1)
        .all()
    )

    if not candidates:
        params = urlencode({"toast": "No active subreddits to scrape", "toast_type": "warning"})
        return RedirectResponse(url=f"/admin/scrape-queue?{params}", status_code=303)

    candidate = candidates[0]
    subreddit_name = candidate.subreddit_name
    client_id = str(candidate.client_id)
    client_uuid = uuid.UUID(client_id)
    start_time = time.time()

    # Resolve subreddit_id from shared registry
    subreddit_record = (
        db.query(Subreddit)
        .filter(Subreddit.subreddit_name.ilike(subreddit_name))
        .first()
    )
    if not subreddit_record:
        # Create subreddit in shared registry if missing
        subreddit_record = Subreddit(subreddit_name=subreddit_name, is_active=True)
        db.add(subreddit_record)
        db.flush()

    subreddit_id = subreddit_record.id

    try:
        # Record start event
        record_activity_event(
            db, "scrape",
            f"Manual scrape started: r/{subreddit_name} for {candidate.client_name}",
            client_uuid,
            {"subreddit_name": subreddit_name, "phase": "start", "trigger": "manual"},
        )

        # Scrape subreddit
        posts = scrape_subreddit(subreddit_name, limit=50, max_age_hours=24)

        # Deduplicate against ALL threads for this subreddit (not just per-client)
        existing_ids = set(
            row[0]
            for row in db.query(RedditThread.reddit_native_id)
            .filter(RedditThread.subreddit_id == subreddit_id)
            .all()
        )
        new_posts = deduplicate_posts(posts, existing_ids)

        # Save new threads
        for post in new_posts:
            thread = RedditThread(
                client_id=client_uuid,
                subreddit_id=subreddit_id,
                type="professional",
                reddit_native_id=post["reddit_native_id"],
                subreddit=post["subreddit"],
                post_title=post["post_title"],
                post_body=post["post_body"],
                comments_json=post["comments_json"],
                url=post["url"],
                author=post["author"],
                score=post["score"],
                ups=post["ups"],
                downs=post["downs"],
                scraped_at=datetime.now(timezone.utc),
            )
            db.add(thread)
        db.commit()

        # Update last_scraped_at on both legacy and shared models
        sub_record = (
            db.query(ClientSubreddit)
            .filter(
                ClientSubreddit.client_id == client_id,
                ClientSubreddit.subreddit_name == subreddit_name,
            )
            .first()
        )
        if sub_record:
            sub_record.last_scraped_at = datetime.now(timezone.utc)

        subreddit_record.last_scraped_at = datetime.now(timezone.utc)

        # Record ScrapeLog
        duration_ms = int((time.time() - start_time) * 1000)
        scrape_log = ScrapeLog(
            client_id=client_uuid,
            subreddit_id=subreddit_id,
            subreddit_name=subreddit_name,
            posts_found=len(posts),
            posts_new=len(new_posts),
            duration_ms=duration_ms,
            errors=None,
        )
        db.add(scrape_log)
        db.commit()

        # Record completion event
        record_activity_event(
            db, "scrape",
            f"Manual scrape done: r/{subreddit_name} — {len(posts)} found, {len(new_posts)} new ({duration_ms}ms)",
            client_uuid,
            {"subreddit_name": subreddit_name, "posts_found": len(posts), "posts_new": len(new_posts), "duration_ms": duration_ms, "trigger": "manual"},
        )

        # Redirect with success toast
        msg = f"✅ r/{subreddit_name} → {len(posts)} found, {len(new_posts)} new ({duration_ms}ms) — client: {candidate.client_name}"
        params = urlencode({"toast": msg, "toast_type": "success"})
        return RedirectResponse(url=f"/admin/scrape-queue?{params}", status_code=303)

    except Exception as e:
        db.rollback()
        # Record error
        record_activity_event(
            db, "system",
            f"Manual scrape failed: r/{subreddit_name} — {str(e)[:200]}",
            client_uuid,
            {"subreddit_name": subreddit_name, "error": str(e)[:500], "trigger": "manual"},
        )
        db.commit()

        msg = f"❌ r/{subreddit_name} failed: {str(e)[:100]}"
        params = urlencode({"toast": msg, "toast_type": "error"})
        return RedirectResponse(url=f"/admin/scrape-queue?{params}", status_code=303)


# ---------------------------------------------------------------------------
# Threads (admin) — Req 3
# ---------------------------------------------------------------------------

@router.get("/threads", response_class=HTMLResponse)
def admin_threads(
    request: Request,
    client_id: str | None = None,
    tag: str | None = None,
    page: int = 1,
    sort: str = "relevance",
    order: str = "desc",
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Admin threads list — filterable by client and tag (engage/monitor/skip)."""
    from app.models.thread import RedditThread
    from app.models.thread_score import ThreadScore
    from app.models.ai_usage import AIUsageLog
    from app.services.scoring import get_client_threads_with_scores
    from sqlalchemy import func as sa_func
    from sqlalchemy.orm import selectinload

    per_page = 50
    filter_client_uuid = None
    threads_data = []

    if client_id:
        try:
            filter_client_uuid = uuid.UUID(client_id)
        except ValueError:
            pass

    if filter_client_uuid:
        results = get_client_threads_with_scores(db, filter_client_uuid, tag=tag if tag in ("engage", "monitor", "skip") else None)
        for thread, score in results:
            threads_data.append({
                "thread": thread,
                "score": score,
            })
    else:
        query = (
            db.query(RedditThread, ThreadScore)
            .outerjoin(ThreadScore, ThreadScore.thread_id == RedditThread.id)
        )
        if tag and tag in ("engage", "monitor", "skip"):
            query = query.filter(ThreadScore.tag == tag)

        rows = query.order_by(RedditThread.created_at.desc()).limit(1000).all()
        for thread, score in rows:
            threads_data.append({
                "thread": thread,
                "score": score,
            })

    # Sorting
    _tag_priority = {"engage": 0, "monitor": 1, "skip": 2}
    is_desc = order == "desc"

    if sort == "relevance":
        def _sort_key(item):
            score = item.get("score")
            t = item.get("thread")
            tag_val = score.tag if score else None
            priority = _tag_priority.get(tag_val, 3)
            composite = -(score.composite or 0) if score else 0
            created = t.created_at if t else datetime.min
            return (priority, composite, -created.timestamp() if created else 0)
        threads_data.sort(key=_sort_key, reverse=not is_desc)  # desc is default for relevance
    elif sort == "tag":
        threads_data.sort(
            key=lambda i: _tag_priority.get((i["score"].tag if i["score"] else None), 3),
            reverse=is_desc,
        )
    elif sort == "title":
        threads_data.sort(
            key=lambda i: (i["thread"].post_title or "").lower(),
            reverse=is_desc,
        )
    elif sort == "subreddit":
        threads_data.sort(
            key=lambda i: (i["thread"].subreddit or "").lower(),
            reverse=is_desc,
        )
    elif sort == "composite":
        threads_data.sort(
            key=lambda i: (i["score"].composite or 0) if i["score"] else 0,
            reverse=is_desc,
        )
    elif sort == "ups":
        threads_data.sort(
            key=lambda i: i["thread"].ups or 0,
            reverse=is_desc,
        )
    elif sort == "scraped":
        threads_data.sort(
            key=lambda i: i["thread"].scraped_at or datetime.min,
            reverse=is_desc,
        )
    elif sort == "author":
        threads_data.sort(
            key=lambda i: (i["thread"].author or "").lower(),
            reverse=is_desc,
        )

    # Pagination
    total = len(threads_data)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    threads_page = threads_data[start:end]

    clients_list = (
        db.query(Client)
        .filter(Client.is_active.is_(True))
        .order_by(Client.client_name)
        .all()
    )
    client_map = {str(c.id): c.client_name for c in clients_list}

    # AI usage stats — last scoring run and recent costs
    last_scoring_log = (
        db.query(AIUsageLog)
        .filter(AIUsageLog.operation == "scoring")
        .order_by(AIUsageLog.created_at.desc())
        .first()
    )
    # Total AI cost in last 24h
    from datetime import timedelta
    day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    ai_cost_24h = (
        db.query(sa_func.coalesce(sa_func.sum(AIUsageLog.cost_usd), 0))
        .filter(AIUsageLog.created_at >= day_ago)
        .scalar()
    )

    return templates.TemplateResponse(
        name="admin_threads.html",
        context={
            "request": request,
            "active_nav": "threads",
            "threads": threads_page,
            "clients": clients_list,
            "client_map": client_map,
            "filter_client_id": client_id or "",
            "filter_tag": tag or "",
            "sort": sort,
            "order": order,
            "last_scoring_log": last_scoring_log,
            "ai_cost_24h": float(ai_cost_24h),
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "per_page": per_page,
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Review queue (admin) — Req 4
# ---------------------------------------------------------------------------

@router.get("/review", response_class=HTMLResponse)
def admin_review(
    request: Request,
    status: str = "pending",
    client_id: str | None = None,
    sort: str = "score",
    subreddit: str | None = None,
    avatar_id: str | None = None,
    age: str | None = None,
    content_type: str = "comments",
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Admin review queue — approve / reject / edit comment and post drafts.

    Filters: status, client, subreddit, avatar, age, content_type.
    Sort: score (highest composite first), newest, oldest.
    """
    from datetime import timedelta
    from app.models.comment_draft import CommentDraft
    from app.models.post_draft import PostDraft
    from app.models.thread import RedditThread
    from app.models.thread_score import ThreadScore
    from sqlalchemy.orm import joinedload

    if status not in ("pending", "approved", "posted", "rejected"):
        status = "pending"
    if content_type not in ("comments", "posts", "all"):
        content_type = "comments"

    now = datetime.now(timezone.utc)

    # --- Post drafts query (when content_type == "posts") ---
    if content_type == "posts":
        post_query = (
            db.query(PostDraft)
            .options(joinedload(PostDraft.avatar))
            .filter(PostDraft.status == status)
        )

        filter_client_uuid = None
        if client_id:
            try:
                filter_client_uuid = uuid.UUID(client_id)
                post_query = post_query.filter(PostDraft.client_id == filter_client_uuid)
            except ValueError:
                pass

        if subreddit:
            post_query = post_query.filter(PostDraft.subreddit == subreddit)

        if avatar_id:
            try:
                post_query = post_query.filter(PostDraft.avatar_id == uuid.UUID(avatar_id))
            except ValueError:
                pass

        if age == "fresh":
            post_query = post_query.filter(PostDraft.created_at >= now - timedelta(hours=4))
        elif age == "today":
            post_query = post_query.filter(PostDraft.created_at >= now - timedelta(hours=24))
        elif age == "stale":
            post_query = post_query.filter(PostDraft.created_at < now - timedelta(hours=24))

        if sort == "newest":
            post_query = post_query.order_by(PostDraft.created_at.desc())
        elif sort == "oldest":
            post_query = post_query.order_by(PostDraft.created_at.asc())
        else:
            post_query = post_query.order_by(PostDraft.created_at.desc())

        post_drafts = post_query.limit(100).all()

        enriched = []
        for draft in post_drafts:
            enriched.append({
                "draft": draft,
                "thread": None,
                "avatar": draft.avatar,
                "score": None,
                "karma_summary": None,
                "is_post": True,
            })

        subreddit_options = sorted(set(
            d.subreddit for d in post_drafts if d.subreddit
        ))
        avatar_options = sorted(
            set((str(d.avatar.id), d.avatar.reddit_username) for d in post_drafts if d.avatar),
            key=lambda x: x[1],
        )

        total_pending = db.query(PostDraft).filter(PostDraft.status == "pending").count()
        oldest_pending = (
            db.query(PostDraft.created_at)
            .filter(PostDraft.status == "pending")
            .order_by(PostDraft.created_at.asc())
            .first()
        )
        oldest_age_hours = None
        if oldest_pending and oldest_pending.created_at:
            oldest_age_hours = int((now - oldest_pending.created_at).total_seconds() / 3600)

        avg_score = None
        avatar_breakdown = []

        # Counts for tab badges
        pending_posts_count = db.query(PostDraft).filter(PostDraft.status == "pending").count()
        pending_comments_count = db.query(CommentDraft).filter(CommentDraft.status == "pending").count()

        clients_list = (
            db.query(Client)
            .filter(Client.is_active.is_(True))
            .order_by(Client.client_name)
            .all()
        )

        return templates.TemplateResponse(
            name="admin_review.html",
            context={
                "request": request,
                "active_nav": "review",
                "drafts": enriched,
                "status": status,
                "clients": clients_list,
                "selected_client": client_id or "",
                "sort": sort,
                "subreddit_filter": subreddit or "",
                "avatar_filter": avatar_id or "",
                "age_filter": age or "",
                "content_type": content_type,
                "subreddit_options": subreddit_options,
                "avatar_options": avatar_options,
                "stats": {
                    "total_pending": total_pending,
                    "oldest_age_hours": oldest_age_hours,
                    "avg_score": avg_score,
                    "showing": len(enriched),
                    "pending_posts": pending_posts_count,
                    "pending_comments": pending_comments_count,
                },
                "avatar_breakdown": avatar_breakdown,
            },
            request=request,
        )

    # --- Comment drafts query (default) ---
    query = (
        db.query(CommentDraft)
        .options(joinedload(CommentDraft.thread), joinedload(CommentDraft.avatar))
        .filter(CommentDraft.status == status)
    )

    filter_client_uuid = None
    if client_id:
        try:
            filter_client_uuid = uuid.UUID(client_id)
            query = query.filter(CommentDraft.client_id == filter_client_uuid)
        except ValueError:
            pass

    # Subreddit filter
    if subreddit:
        query = query.join(CommentDraft.thread).filter(RedditThread.subreddit == subreddit)

    # Avatar filter
    if avatar_id:
        try:
            query = query.filter(CommentDraft.avatar_id == uuid.UUID(avatar_id))
        except ValueError:
            pass

    # Age filter
    if age == "fresh":
        query = query.filter(CommentDraft.created_at >= now - timedelta(hours=4))
    elif age == "today":
        query = query.filter(CommentDraft.created_at >= now - timedelta(hours=24))
    elif age == "stale":
        query = query.filter(CommentDraft.created_at < now - timedelta(hours=24))

    # Sorting
    if sort == "newest":
        query = query.order_by(CommentDraft.created_at.desc())
    elif sort == "oldest":
        query = query.order_by(CommentDraft.created_at.asc())
    else:
        # Default: sort by score (highest first) — need to join ThreadScore
        query = query.order_by(CommentDraft.created_at.desc())  # fallback ordering

    drafts = query.limit(100).all()

    # Batch-fetch ThreadScores for all drafts in one query
    thread_client_pairs = [
        (draft.thread_id, draft.client_id)
        for draft in drafts
        if draft.thread_id and draft.client_id
    ]
    scores_map: dict = {}
    if thread_client_pairs:
        from sqlalchemy import tuple_
        scores = (
            db.query(ThreadScore)
            .filter(
                tuple_(ThreadScore.thread_id, ThreadScore.client_id).in_(thread_client_pairs)
            )
            .all()
        )
        scores_map = {(s.thread_id, s.client_id): s for s in scores}

    enriched = []
    for draft in drafts:
        thread = draft.thread
        avatar = draft.avatar
        score = scores_map.get((draft.thread_id, draft.client_id))

        # Compute comment count from comments_json
        if thread and thread.comments_json:
            try:
                import json as _json
                _comments = _json.loads(thread.comments_json)
                thread.comment_count = len(_comments) if isinstance(_comments, list) else 0
            except Exception:
                thread.comment_count = 0
        elif thread:
            thread.comment_count = 0

        item = {"draft": draft, "thread": thread, "avatar": avatar, "score": score}

        # For posted status, include karma summary per avatar
        if status == "posted" and avatar:
            from app.services.karma_feedback import get_avatar_karma_summary
            item["karma_summary"] = get_avatar_karma_summary(db, avatar.id)
        else:
            item["karma_summary"] = None

        enriched.append(item)

    # Sort in Python (since join is complex with joinedload)
    if sort == "newest":
        enriched.sort(key=lambda x: x["draft"].created_at, reverse=True)
    elif sort == "oldest":
        enriched.sort(key=lambda x: x["draft"].created_at)
    else:
        # Default "score" = karma potential:
        # Prioritize fresh posts with high engagement potential.
        # Formula: composite_score + freshness_bonus + popularity_bonus - competition_penalty
        def _karma_potential(x):
            composite = x["score"].composite if x["score"] and x["score"].composite else 0
            thread = x["thread"]
            if not thread:
                return composite

            # Freshness: posts < 4h get full bonus, 4-12h partial, >12h zero
            age_hours = (now - thread.created_at).total_seconds() / 3600 if thread.created_at else 24
            if age_hours < 4:
                freshness = 20
            elif age_hours < 8:
                freshness = 10
            elif age_hours < 12:
                freshness = 5
            else:
                freshness = 0

            # Popularity: more upvotes = more visibility for our comment
            ups = thread.ups or thread.score or 0
            popularity = min(ups, 30)  # cap at 30 bonus points

            # Competition: more comments = harder to stand out
            comment_count = getattr(thread, 'comment_count', 0) or 0
            competition = min(comment_count * 2, 20)  # penalty up to 20

            return composite + freshness + popularity - competition

        enriched.sort(key=_karma_potential, reverse=True)

    # Collect filter options from current status (for dropdowns)
    all_pending = (
        db.query(CommentDraft)
        .options(joinedload(CommentDraft.thread), joinedload(CommentDraft.avatar))
        .filter(CommentDraft.status == status)
    )
    if filter_client_uuid:
        all_pending = all_pending.filter(CommentDraft.client_id == filter_client_uuid)

    # Get unique subreddits and avatars for filter dropdowns
    subreddit_options = sorted(set(
        d.thread.subreddit for d in drafts if d.thread and d.thread.subreddit
    ))
    avatar_options = sorted(
        set((str(d.avatar.id), d.avatar.reddit_username) for d in drafts if d.avatar),
        key=lambda x: x[1],
    )

    # Quick stats
    total_pending = db.query(CommentDraft).filter(CommentDraft.status == "pending").count()
    oldest_pending = (
        db.query(CommentDraft.created_at)
        .filter(CommentDraft.status == "pending")
        .order_by(CommentDraft.created_at.asc())
        .first()
    )
    oldest_age_hours = None
    if oldest_pending and oldest_pending.created_at:
        oldest_age_hours = int((now - oldest_pending.created_at).total_seconds() / 3600)

    avg_score = None
    if enriched:
        scores_list = [x["score"].composite for x in enriched if x["score"] and x["score"].composite]
        if scores_list:
            avg_score = round(sum(scores_list) / len(scores_list), 1)

    # Avatar breakdown for decision-making header
    avatar_breakdown = []
    if status == "pending":
        from sqlalchemy import func as sa_func_local
        avatar_stats = (
            db.query(
                Avatar.id,
                Avatar.reddit_username,
                Avatar.warming_phase,
                sa_func_local.count(CommentDraft.id).label("pending_count"),
            )
            .join(CommentDraft, CommentDraft.avatar_id == Avatar.id)
            .filter(CommentDraft.status == "pending")
            .group_by(Avatar.id, Avatar.reddit_username, Avatar.warming_phase)
            .order_by(sa_func_local.count(CommentDraft.id).desc())
            .all()
        )
        # Also get today's approved count per avatar
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        approved_today = (
            db.query(
                CommentDraft.avatar_id,
                sa_func_local.count(CommentDraft.id),
            )
            .filter(
                CommentDraft.status.in_(["approved", "posted"]),
                CommentDraft.created_at >= today_start,
            )
            .group_by(CommentDraft.avatar_id)
            .all()
        )
        approved_map = {row[0]: row[1] for row in approved_today}

        for av_id, username, phase, pending_count in avatar_stats:
            avatar_breakdown.append({
                "avatar_id": str(av_id),
                "username": username,
                "phase": phase,
                "pending": pending_count,
                "approved_today": approved_map.get(av_id, 0),
            })

    clients_list = (
        db.query(Client)
        .filter(Client.is_active.is_(True))
        .order_by(Client.client_name)
        .all()
    )

    # Counts for tab badges
    pending_posts_count = db.query(PostDraft).filter(PostDraft.status == "pending").count()
    pending_comments_count = db.query(CommentDraft).filter(CommentDraft.status == "pending").count()

    # Mark items as comments (not posts)
    for item in enriched:
        item["is_post"] = False

    return templates.TemplateResponse(
        name="admin_review.html",
        context={
            "request": request,
            "active_nav": "review",
            "drafts": enriched,
            "status": status,
            "clients": clients_list,
            "selected_client": client_id or "",
            "sort": sort,
            "subreddit_filter": subreddit or "",
            "avatar_filter": avatar_id or "",
            "age_filter": age or "",
            "content_type": content_type,
            "subreddit_options": subreddit_options,
            "avatar_options": avatar_options,
            "stats": {
                "total_pending": total_pending,
                "oldest_age_hours": oldest_age_hours,
                "avg_score": avg_score,
                "showing": len(enriched),
                "pending_posts": pending_posts_count,
                "pending_comments": pending_comments_count,
            },
            "avatar_breakdown": avatar_breakdown,
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Global keywords overview (admin) — Req 6
# ---------------------------------------------------------------------------

@router.get("/keywords", response_class=HTMLResponse)
def admin_keywords_global(
    request: Request,
    client_id: str = "",
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Global keywords page — keywords per client with analytics."""
    from app.services.keyword_analytics import get_keyword_stats_for_client

    clients_list = (
        db.query(Client)
        .filter(Client.is_active.is_(True))
        .order_by(Client.client_name)
        .all()
    )

    # Only load analytics when a specific client is selected
    groups = []
    selected_client = None
    if client_id:
        selected_client = next((c for c in clients_list if str(c.id) == client_id), None)
        if selected_client:
            kws = admin_service.get_client_keywords(db, selected_client.id)
            kw_stats = get_keyword_stats_for_client(db, selected_client.id, days=90)
            groups.append({"client": selected_client, "keywords": kws, "keyword_stats": kw_stats})

    return templates.TemplateResponse(
        name="admin_keywords_global.html",
        context={
            "request": request,
            "active_nav": "keywords",
            "groups": groups,
            "clients_list": clients_list,
            "selected_client_id": client_id,
        },
        request=request,
    )

# ---------------------------------------------------------------------------
# System Inspector — diagnostics + controls
# ---------------------------------------------------------------------------


def _inspector_context(db: Session, last_action: dict | None = None) -> dict:
    """Build the full context dict for the inspector page/partial."""
    from app.services.settings import get_setting

    report = inspector_service.run_all_checks(db)
    funnel = inspector_service.get_pipeline_funnel(db)
    client_breakdown = inspector_service.get_client_breakdown(db)

    # Pipeline switch states
    pipeline_enabled = get_setting(db, "pipeline_enabled").lower() == "true"
    generation_enabled = get_setting(db, "generation_enabled").lower() == "true"
    scrape_enabled = get_setting(db, "scrape_enabled").lower() == "true"

    # Recommendations
    recommendations = inspector_service.get_recommendations(
        db, report, funnel, pipeline_enabled, generation_enabled, scrape_enabled
    )

    return {
        "report": report,
        "funnel": funnel,
        "client_breakdown": client_breakdown,
        "recommendations": recommendations,
        "pipeline_enabled": pipeline_enabled,
        "generation_enabled": generation_enabled,
        "scrape_enabled": scrape_enabled,
        "last_action": last_action,
    }


def _inspector_export_payload(db: Session, current_user: User) -> dict:
    """Build a JSON-safe system inspector export snapshot."""
    ctx = _inspector_context(db)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": current_user.email,
        "report": ctx["report"],
        "funnel": ctx["funnel"],
        "client_breakdown": ctx["client_breakdown"],
        "recommendations": ctx["recommendations"],
        "settings": {
            "pipeline_enabled": ctx["pipeline_enabled"],
            "generation_enabled": ctx["generation_enabled"],
            "scrape_enabled": ctx["scrape_enabled"],
        },
    }


@router.get("/inspector", response_class=HTMLResponse)
def admin_inspector(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """System Inspector — diagnostics, data integrity, pipeline controls."""
    ctx = _inspector_context(db)
    ctx["request"] = request
    ctx["active_nav"] = "inspector"

    return templates.TemplateResponse(
        name="admin_inspector.html",
        context=ctx,
        request=request,
    )


@router.get("/inspector/refresh", response_class=HTMLResponse)
def admin_inspector_refresh(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: re-run checks and return only the content div."""
    ctx = _inspector_context(db)
    ctx["request"] = request

    return templates.TemplateResponse(
        name="partials/inspector_content.html",
        context=ctx,
        request=request,
    )


@router.post("/inspector/action/{action_id}", response_class=HTMLResponse)
def admin_inspector_action(
    action_id: str,
    request: Request,
    enabled: str = "",
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Execute a corrective action (including toggle switches) and return updated partial."""
    # Handle toggle actions
    if action_id == "toggle-pipeline":
        is_enabled = enabled.lower() == "true"
        result = inspector_service.action_toggle_pipeline(db, is_enabled)
        audit_service.log_action(db=db, user_id=current_user.id, action="toggle_pipeline",
                                 entity_type="system", details={"enabled": is_enabled})
    elif action_id == "toggle-generation":
        is_enabled = enabled.lower() == "true"
        result = inspector_service.action_toggle_generation(db, is_enabled)
        audit_service.log_action(db=db, user_id=current_user.id, action="toggle_generation",
                                 entity_type="system", details={"enabled": is_enabled})
    elif action_id == "toggle-scraping":
        is_enabled = enabled.lower() == "true"
        result = inspector_service.action_toggle_scraping(db, is_enabled)
        audit_service.log_action(db=db, user_id=current_user.id, action="toggle_scraping",
                                 entity_type="system", details={"enabled": is_enabled})
    else:
        result = inspector_service.execute_action(db, action_id)
        audit_service.log_action(db=db, user_id=current_user.id, action="inspector_action",
                                 entity_type="system", details={"action_id": action_id, "result": result})

    ctx = _inspector_context(db, last_action=result)
    ctx["request"] = request

    return templates.TemplateResponse(
        name="partials/inspector_content.html",
        context=ctx,
        request=request,
    )


@router.get("/inspector/json")
def admin_inspector_json(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """JSON API for inspector results (for programmatic access)."""
    return JSONResponse(_inspector_export_payload(db, current_user))


@router.get("/inspector/export.json")
def admin_inspector_export_json(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Download the full inspector snapshot as a JSON file."""
    exported_at = datetime.now(timezone.utc)
    filename = f"inspector_{exported_at.strftime('%Y%m%d_%H%M%SZ')}.json"
    return JSONResponse(
        content={
            "exported_at": exported_at.isoformat(),
            "data": _inspector_export_payload(db, current_user),
        },
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
