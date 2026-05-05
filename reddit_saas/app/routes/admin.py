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
from app.models.subreddit import ClientSubreddit
from app.models.user import User
from app.services import admin as admin_service
from app.services import audit as audit_service
from app.services import health_metrics
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
    stats = admin_service.get_db_statistics(db)
    ai_costs = admin_service.get_ai_cost_summary(db)
    clients_list = db.query(Client).filter(Client.is_active.is_(True)).order_by(Client.client_name).all()

    return templates.TemplateResponse(
        name="admin_dashboard.html",
        context={
            "request": request,
            "active_nav": "dashboard",
            "stats": stats,
            "ai_costs": ai_costs,
            "clients": clients_list,
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

    subreddits = (
        db.query(ClientSubreddit)
        .filter(ClientSubreddit.client_id == client_id, ClientSubreddit.is_active.is_(True))
        .all()
    )
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
):
    """Global subreddits management page — all clients, with pause/resume."""
    subreddits = (
        db.query(ClientSubreddit)
        .join(Client, Client.id == ClientSubreddit.client_id)
        .order_by(
            ClientSubreddit.is_active.desc(),
            ClientSubreddit.last_scraped_at.asc().nulls_first(),
            ClientSubreddit.subreddit_name.asc(),
        )
        .all()
    )

    # Build enriched list with client names
    clients_map = {}
    for sub in subreddits:
        if sub.client_id not in clients_map:
            c = db.query(Client).filter(Client.id == sub.client_id).first()
            clients_map[sub.client_id] = c.client_name if c else "Unknown"

    enriched = []
    now_utc = datetime.now(timezone.utc)
    for sub in subreddits:
        if sub.last_scraped_at:
            age_seconds = (now_utc - sub.last_scraped_at).total_seconds()
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
            "sub": sub,
            "client_name": clients_map.get(sub.client_id, "Unknown"),
            "age_hours": age_hours,
            "age_display": age_display,
        })

    # Stats
    total = len(subreddits)
    active_count = sum(1 for s in subreddits if s.is_active)
    paused_count = total - active_count

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
    """Toggle subreddit is_active (pause/resume scraping)."""
    sub = db.query(ClientSubreddit).filter(ClientSubreddit.id == subreddit_id).first()
    if sub:
        sub.is_active = not sub.is_active
        db.commit()
        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action="toggle_active",
            entity_type="subreddit",
            details={"subreddit_name": sub.subreddit_name, "is_active": sub.is_active},
        )

    # Check referer to redirect back to correct page
    referer = request.headers.get("referer", "")
    if f"/subreddits/{sub.client_id}" in referer:
        return RedirectResponse(url=f"/admin/subreddits/{sub.client_id}", status_code=303)
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

    def _to_view(a):
        return build_avatar_view(a, get_avatar_health(db, a), avatar_page.client_by_id)

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

    f = AvatarFilter(q=q.strip(), status=status, client_id=client_id, sort=sort,
                     view=view, group=group, page=page)
    page_data = list_avatars_page(db, f, viewer_client_id=None)
    check_all_reddit_statuses(db, page_data.items)

    page_data = list_avatars_page(db, f, viewer_client_id=None)

    def _to_view(a):
        return build_avatar_view(a, get_avatar_health(db, a), page_data.client_by_id)

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
    from app.models.ai_usage import AIUsageLog
    from app.services.safety import get_avatar_health
    from sqlalchemy import func

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
            ActivityEvent.event_metadata["avatar_id"].astext == str(avatar.id),
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
    ai_costs = []
    if avatar.client_ids:
        for cid in avatar.client_ids:
            costs = db.query(
                AIUsageLog.operation,
                func.count(AIUsageLog.id).label("calls"),
                func.sum(AIUsageLog.cost_usd).label("total_cost"),
                func.sum(AIUsageLog.input_tokens).label("input_tokens"),
                func.sum(AIUsageLog.output_tokens).label("output_tokens"),
            ).filter(
                AIUsageLog.client_id == cid,
            ).group_by(AIUsageLog.operation).all()
            ai_costs = costs

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
        },
        request=request,
    )


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

    # Redirect back to the referring page
    referer = request.headers.get("referer", "")
    if f"/admin/avatars" in referer:
        return RedirectResponse(url=referer, status_code=303)
    return RedirectResponse(url="/admin/avatars", status_code=303)


@router.get("/subreddits/{client_id}", response_class=HTMLResponse)
def admin_subreddits(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return HTMLResponse("Client not found", status_code=404)

    subreddits = (
        db.query(ClientSubreddit)
        .filter(ClientSubreddit.client_id == client_id)
        .order_by(ClientSubreddit.is_active.desc(), ClientSubreddit.created_at.desc())
        .all()
    )

    return templates.TemplateResponse(
        name="admin_subreddits.html",
        context={
            "request": request,
            "active_nav": "subreddits",
            "client": client,
            "subreddits": subreddits,
            "error": None,
            "now_utc": datetime.now(timezone.utc),
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
        subreddits = (
            db.query(ClientSubreddit)
            .filter(ClientSubreddit.client_id == client_id, ClientSubreddit.is_active.is_(True))
            .order_by(ClientSubreddit.created_at.desc())
            .all()
        )
        return templates.TemplateResponse(
            name="admin_subreddits.html",
            context={
                "request": request,
                "active_nav": "subreddits",
                "client": client,
                "subreddits": subreddits,
                "error": err,
                "now_utc": datetime.now(timezone.utc),
            },
            request=request,
        )

    try:
        admin_service.add_subreddit(db, client_id, subreddit_name, subreddit_type, current_user.id)
    except ValueError as e:
        client = db.query(Client).filter(Client.id == client_id).first()
        subreddits = (
            db.query(ClientSubreddit)
            .filter(ClientSubreddit.client_id == client_id, ClientSubreddit.is_active.is_(True))
            .order_by(ClientSubreddit.created_at.desc())
            .all()
        )
        return templates.TemplateResponse(
            name="admin_subreddits.html",
            context={
                "request": request,
                "active_nav": "subreddits",
                "client": client,
                "subreddits": subreddits,
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
    try:
        from app.tasks.worker import celery_app
        tasks = admin_service.get_recent_tasks(celery_app)
    except Exception:
        tasks = []

    clients_list = db.query(Client).filter(Client.is_active.is_(True)).order_by(Client.client_name).all()

    return templates.TemplateResponse(
        name="admin_tasks.html",
        context={
            "request": request,
            "active_nav": "tasks",
            "tasks": tasks,
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

    try:
        from app.tasks.worker import celery_app
        tasks = admin_service.get_recent_tasks(celery_app)
    except Exception:
        tasks = []

    clients_list = db.query(Client).filter(Client.is_active.is_(True)).order_by(Client.client_name).all()

    return templates.TemplateResponse(
        name="admin_tasks.html",
        context={
            "request": request,
            "active_nav": "tasks",
            "tasks": tasks,
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
    health = admin_service.check_system_health(db)
    db_stats = admin_service.get_db_statistics(db)
    collector = _get_collector(request)
    window_minutes = collector.get_window_minutes()

    rate_limit_state = collector.get_rate_limit()
    reddit_metrics = health_metrics.get_reddit_api_metrics(db, window_minutes=window_minutes)
    llm_metrics = health_metrics.get_llm_api_metrics(db, window_minutes=window_minutes)
    freshness = health_metrics.get_all_scrape_freshness(db)

    return templates.TemplateResponse(
        name="admin_health.html",
        context={
            "request": request,
            "active_nav": "health",
            "health": health,
            "db_stats": db_stats,
            "rate_limit": rate_limit_state,
            "rate_limit_color": gauge_color(rate_limit_state.usage_pct),
            "reddit_metrics": reddit_metrics,
            "llm_metrics": llm_metrics,
            "freshness": freshness,
            "window_minutes": window_minutes,
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
):
    summary = admin_service.get_ai_cost_summary(db)
    by_client = admin_service.get_ai_costs_by_client(db)
    by_operation = admin_service.get_ai_costs_by_operation(db)
    by_model = admin_service.get_ai_costs_by_model(db)

    # Budget from settings or default
    from app.services.settings import get_setting
    budget_str = get_setting(db, "monthly_budget_usd")
    budget = float(budget_str) if budget_str else 100.0
    budget_pct = (summary["total_cost"] / budget * 100) if budget > 0 else 0

    return templates.TemplateResponse(
        name="admin_ai_costs.html",
        context={
            "request": request,
            "active_nav": "ai-costs",
            "summary": summary,
            "by_client": by_client,
            "by_operation": by_operation,
            "by_model": by_model,
            "budget": budget,
            "budget_pct": budget_pct,
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
        date_from=filter_date_from,
        date_to=filter_date_to,
    )
    pagination = _paginate(page, per_page, total)

    # Get users and clients for filter dropdowns
    users_list = db.query(User).order_by(User.email).all()
    clients_list = db.query(Client).order_by(Client.client_name).all()

    return templates.TemplateResponse(
        name="admin_audit_logs.html",
        context={
            "request": request,
            "active_nav": "audit-logs",
            "logs": logs,
            "pagination": pagination,
            "users": users_list,
            "clients": clients_list,
            "filters": {
                "user_id": user_id or "",
                "client_id": client_id or "",
                "action": action or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
            },
        },
        request=request,
    )


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
            db.query(ClientSubreddit)
            .filter(ClientSubreddit.client_id == client.id, ClientSubreddit.is_active.is_(True))
            .order_by(ClientSubreddit.created_at.desc())
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
            db.query(ClientSubreddit)
            .filter(ClientSubreddit.client_id == client.id, ClientSubreddit.is_active.is_(True))
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
                    db.query(ClientSubreddit)
                    .filter(ClientSubreddit.client_id == client.id, ClientSubreddit.is_active.is_(True))
                    .order_by(ClientSubreddit.created_at.desc())
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
    """
    import time
    import uuid
    from datetime import datetime, timezone

    from app.models.scrape_log import ScrapeLog
    from app.models.subreddit import ClientSubreddit
    from app.models.thread import RedditThread
    from app.services.reddit import scrape_subreddit, deduplicate_posts
    from app.services.transparency import record_activity_event

    # Query next stale subreddit
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
        return RedirectResponse(url="/admin/scrape-queue", status_code=303)

    candidate = candidates[0]
    subreddit_name = candidate.subreddit_name
    client_id = str(candidate.client_id)
    client_uuid = uuid.UUID(client_id)
    start_time = time.time()

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

        # Deduplicate
        existing_ids = set(
            row[0]
            for row in db.query(RedditThread.reddit_native_id)
            .filter(RedditThread.client_id == client_id)
            .all()
        )
        new_posts = deduplicate_posts(posts, existing_ids)

        # Save new threads
        for post in new_posts:
            thread = RedditThread(
                client_id=client_id,
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

        # Update last_scraped_at
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

        # Record ScrapeLog
        duration_ms = int((time.time() - start_time) * 1000)
        scrape_log = ScrapeLog(
            client_id=client_uuid,
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

    except Exception as e:
        # Record error
        record_activity_event(
            db, "system",
            f"Manual scrape failed: r/{subreddit_name} — {str(e)[:200]}",
            client_uuid,
            {"subreddit_name": subreddit_name, "error": str(e)[:500], "trigger": "manual"},
        )

    return RedirectResponse(url="/admin/scrape-queue", status_code=303)


# ---------------------------------------------------------------------------
# Threads (admin) — Req 3
# ---------------------------------------------------------------------------

@router.get("/threads", response_class=HTMLResponse)
def admin_threads(
    request: Request,
    client_id: str | None = None,
    tag: str | None = None,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Admin threads list — filterable by client and tag (engage/monitor/skip)."""
    from app.models.thread import RedditThread

    query = db.query(RedditThread)

    filter_client_uuid = None
    if client_id:
        try:
            filter_client_uuid = uuid.UUID(client_id)
            query = query.filter(RedditThread.client_id == filter_client_uuid)
        except ValueError:
            pass

    if tag in ("engage", "monitor", "skip"):
        query = query.filter(RedditThread.tag == tag)

    threads = (
        query.order_by(RedditThread.created_at.desc())
        .limit(200)
        .all()
    )

    clients_list = (
        db.query(Client)
        .filter(Client.is_active.is_(True))
        .order_by(Client.client_name)
        .all()
    )
    client_map = {str(c.id): c.client_name for c in clients_list}

    return templates.TemplateResponse(
        name="admin_threads.html",
        context={
            "request": request,
            "active_nav": "threads",
            "threads": threads,
            "clients": clients_list,
            "client_map": client_map,
            "filter_client_id": client_id or "",
            "filter_tag": tag or "",
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
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Admin review queue — approve / reject / edit comment drafts."""
    from app.models.comment_draft import CommentDraft
    from app.models.thread import RedditThread

    if status not in ("pending", "approved", "posted", "rejected"):
        status = "pending"

    query = db.query(CommentDraft).filter(CommentDraft.status == status)

    filter_client_uuid = None
    if client_id:
        try:
            filter_client_uuid = uuid.UUID(client_id)
            query = query.filter(CommentDraft.client_id == filter_client_uuid)
        except ValueError:
            pass

    drafts = query.order_by(CommentDraft.created_at.desc()).limit(50).all()

    enriched = []
    for draft in drafts:
        thread = (
            db.query(RedditThread).filter(RedditThread.id == draft.thread_id).first()
        )
        avatar = db.query(Avatar).filter(Avatar.id == draft.avatar_id).first()
        enriched.append({"draft": draft, "thread": thread, "avatar": avatar})

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
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Global keywords overview (admin) — Req 6
# ---------------------------------------------------------------------------

@router.get("/keywords", response_class=HTMLResponse)
def admin_keywords_global(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Global keywords page — keywords for every client at a glance."""
    clients_list = (
        db.query(Client)
        .filter(Client.is_active.is_(True))
        .order_by(Client.client_name)
        .all()
    )

    groups = []
    for c in clients_list:
        kws = admin_service.get_client_keywords(db, c.id)
        groups.append({"client": c, "keywords": kws})

    return templates.TemplateResponse(
        name="admin_keywords_global.html",
        context={
            "request": request,
            "active_nav": "keywords",
            "groups": groups,
        },
        request=request,
    )
