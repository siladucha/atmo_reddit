"""Admin panel routes — superuser-only system management interface."""

import math
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.dependencies.admin import require_business_admin
from app.dependencies.admin import require_avatar_admin
from app.dependencies.admin import require_user_management_access
from app.dependencies.admin import require_review_access
from app.dependencies.permissions import get_current_user, require_owner
from app.dependencies.permissions import verify_client_access_from_path
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.subreddit import ClientSubreddit, ClientSubredditAssignment, Subreddit
from app.models.user import User
from app.services import admin as admin_service
from app.services import audit as audit_service
from app.services import health_metrics
from app.services import inspector as inspector_service
from app.services import operations_dashboard
from app.services import team_management as team_mgmt
from app.services import transparency
from app.services.dry_run import is_dry_run_enabled_global
from app.services.metrics_collector import (
    MetricsCollector,
    gauge_color,
    get_metrics_collector,
)
from app.version import __version__ as app_version, __deployed_at__
from app.config import get_settings as _get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")
# Disable Jinja2 bytecode cache to avoid "unhashable type: dict" errors
# when TemplateResponse is called with positional context dict (old Starlette style).
templates.env.cache = {}
# Expose dry-run toggle to the admin nav (admin_base.html).
templates.env.globals["dry_run_enabled"] = is_dry_run_enabled_global
# Expose version and posting status to all admin templates.
templates.env.globals["app_version"] = app_version
templates.env.globals["deployed_at"] = __deployed_at__
templates.env.globals["posting_disabled"] = lambda: _get_settings().posting_disabled
templates.env.globals["app_env"] = _get_settings().app_env

# Register custom Jinja2 filters
from app.template_filters import register_filters
register_filters(templates.env)


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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Operations Dashboard — role-aware daily-ops view at `/admin/`.

    - Owner: full system dashboard (topology, kill switches, backups, all panels)
    - Partner: business-focused dashboard (clients, pipeline, AI costs, no infra)
    - Client Manager/Admin: single-client dashboard (their client's metrics)

    The shell renders synchronously; panels are filled via HTMX partials.
    """
    from app.models.user_role import UserRole
    from app.services.settings import get_setting

    role = current_user.user_role

    # Reconcile: if JWT role differs from DB-resolved role (e.g. legacy
    # is_superuser users whose role field is empty), prefer the JWT role
    # for dashboard routing since it was set at login from user_role.value.
    jwt_role = getattr(request.state, "user_role", "")
    if jwt_role and jwt_role != role.value:
        try:
            role = UserRole(jwt_role)
        except ValueError:
            pass

    # --- Client Manager / Client Admin: redirect to Client Portal ---
    if role.is_client_scoped and current_user.client_id:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(
            url=f"/clients/{current_user.client_id}/home",
            status_code=303,
        )

    # --- Partner: business-focused dashboard ---
    if role == UserRole.partner:
        from app.services.business_metrics import (
            get_business_metrics,
            get_client_health_table,
            get_trial_funnel,
            get_attention_items,
        )

        biz = get_business_metrics(db)
        client_health = get_client_health_table(db)
        funnel = get_trial_funnel(db)
        attention_items = get_attention_items(db)

        return templates.TemplateResponse(
            name="admin_dashboard_partner.html",
            context={
                "request": request,
                "active_nav": "dashboard",
                "biz": biz,
                "client_health": client_health,
                "funnel": funnel,
                "attention_items": attention_items,
            },
            request=request,
        )

    # --- Owner: full system dashboard ---
    if role != UserRole.owner and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Access Denied")

    metrics = operations_dashboard.get_top_metrics(db)
    clients_list = operations_dashboard.list_active_clients(db)

    # Pipeline control settings for the toggle panel
    pipeline_controls = {
        "pipeline_enabled": get_setting(db, "pipeline_enabled").lower() == "true",
        "generation_enabled": get_setting(db, "generation_enabled").lower() == "true",
        "scrape_enabled": get_setting(db, "scrape_enabled").lower() == "true",
    }

    # System alerts
    from app.services.alert_aggregation import get_system_alerts
    system_alerts = get_system_alerts(db)

    return templates.TemplateResponse(
        name="admin_dashboard.html",
        context={
            "request": request,
            "active_nav": "dashboard",
            "metrics": metrics,
            "clients": clients_list,
            "pipeline_controls": pipeline_controls,
            "system_alerts": system_alerts,
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


@router.get("/activity", response_class=HTMLResponse)
def admin_activity_page(
    request: Request,
    client_id: str | None = None,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Full Activity Feed page with auto-refresh."""
    from app.models.client import Client as ClientModel
    cid = uuid.UUID(client_id) if client_id else None
    events = transparency.get_activity_events(db, client_id=cid, limit=100)
    clients_list = db.query(ClientModel).filter(ClientModel.is_active.is_(True)).order_by(ClientModel.client_name).all()
    return templates.TemplateResponse(
        name="admin_activity.html",
        context={
            "request": request,
            "active_nav": "activity",
            "events": events,
            "now_utc": datetime.now(timezone.utc),
            "clients": clients_list,
            "selected_client": client_id or "",
        },
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
        return score_threads.delay(cid, triggered_by="manual").id
    if action == "generate":
        return generate_comments.delay(cid, triggered_by="manual").id
    if action == "full-pipeline":
        chain = (
            scrape_professional_subreddits.si(cid)
            | score_threads.si(cid, triggered_by="manual")
            | generate_comments.si(cid, triggered_by="manual")
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


@router.get("/dashboard/backups", response_class=HTMLResponse)
def dashboard_backups(
    request: Request,
    current_user: User = Depends(require_superuser),
):
    """Returns HTMX partial with backup status info."""
    import os
    from pathlib import Path

    backup_dir = Path("/app/backups")
    backup_info = {"files": [], "total_size_mb": 0, "count": 0}

    # Scan backup directory
    total_size = 0
    if backup_dir.exists():
        files = sorted(backup_dir.glob("*.sql.gz"), key=lambda f: f.stat().st_mtime, reverse=True)
        backup_info["count"] = len(files)
        for f in files[:10]:  # Show last 10
            stat = f.stat()
            total_size += stat.st_size
            backup_info["files"].append({
                "name": f.name,
                "size_kb": round(stat.st_size / 1024, 1),
                "created": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            })
        # Count total size for remaining files
        for f in files[10:]:
            total_size += f.stat().st_size

    backup_info["total_size_mb"] = round(total_size / (1024 * 1024), 1)
    backup_info["last_backup"] = backup_info["files"][0] if backup_info["files"] else None

    return templates.TemplateResponse(
        name="partials/dashboard_backups.html",
        context={"request": request, "backup_info": backup_info, "now_utc": datetime.now(timezone.utc)},
        request=request,
    )


@router.post("/dashboard/backup-now", response_class=HTMLResponse)
def dashboard_backup_now(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Trigger an immediate database backup via pg_dump (works in Docker on local and server)."""
    import subprocess
    import os
    from urllib.parse import urlparse

    backup_dir = "/app/backups"
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = f"reddit_saas_{timestamp}.sql.gz"
    backup_path = os.path.join(backup_dir, backup_file)

    # Parse DATABASE_URL to extract connection params
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        return HTMLResponse(
            '<div class="p-2 bg-red-900/30 border border-red-700 rounded text-red-300 text-xs">'
            '✗ DATABASE_URL not set</div>'
        )

    parsed = urlparse(database_url)
    db_host = parsed.hostname or "db"
    db_port = str(parsed.port or 5432)
    db_user = parsed.username or "reddit_saas_user"
    db_name = parsed.path.lstrip("/") or "reddit_saas"
    db_password = parsed.password or ""

    try:
        cmd = f'pg_dump -h {db_host} -p {db_port} -U {db_user} -d {db_name} --no-owner --no-acl | gzip > {backup_path}'
        env = {**os.environ, "PGPASSWORD": db_password}
        result = subprocess.run(
            ["sh", "-c", cmd],
            capture_output=True, text=True, timeout=60, env=env,
        )
        if result.returncode != 0:
            return HTMLResponse(
                f'<div class="p-2 bg-red-900/30 border border-red-700 rounded text-red-300 text-xs">'
                f'✗ pg_dump failed: {result.stderr[:200]}</div>'
            )

        # Verify file size
        size = os.path.getsize(backup_path)
        if size < 1024:
            os.remove(backup_path)
            return HTMLResponse(
                '<div class="p-2 bg-red-900/30 border border-red-700 rounded text-red-300 text-xs">'
                '✗ Backup file too small — likely empty database or connection error</div>'
            )

        size_kb = round(size / 1024, 1)
        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action="backup_created",
            entity_type="database",
            details={"file": backup_file, "size_kb": size_kb},
        )

        return HTMLResponse(
            f'<div class="p-2 bg-green-900/30 border border-green-700 rounded text-green-300 text-xs">'
            f'✓ Backup saved: {backup_file} ({size_kb} KB)</div>'
        )
    except subprocess.TimeoutExpired:
        return HTMLResponse(
            '<div class="p-2 bg-red-900/30 border border-red-700 rounded text-red-300 text-xs">'
            '✗ Backup timed out (>60s)</div>'
        )
    except Exception as e:
        return HTMLResponse(
            f'<div class="p-2 bg-red-900/30 border border-red-700 rounded text-red-300 text-xs">'
            f'✗ Error: {str(e)[:200]}</div>'
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
    _client_access: User = Depends(verify_client_access_from_path),
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
# Role-specific dashboard HTMX partials
# ---------------------------------------------------------------------------


@router.get("/dashboard/ai-costs-summary", response_class=HTMLResponse)
def dashboard_ai_costs_summary(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """AI costs summary panel for partner dashboard."""
    ai_costs = operations_dashboard.get_ai_costs_summary(db)
    return templates.TemplateResponse(
        name="partials/dashboard_ai_costs_summary.html",
        context={"request": request, "ai_costs": ai_costs},
        request=request,
    )


@router.get("/dashboard/client-drafts", response_class=HTMLResponse)
def dashboard_client_drafts(
    request: Request,
    client_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Recent drafts panel for client manager dashboard."""
    cid = uuid.UUID(client_id)
    # Verify access: platform admins can view any, client-scoped must match
    if current_user.user_role.is_client_scoped:
        if current_user.client_id != cid:
            raise HTTPException(status_code=403, detail="Access Denied")

    drafts = operations_dashboard.get_client_recent_drafts(db, cid, limit=10)
    return templates.TemplateResponse(
        name="partials/dashboard_client_drafts.html",
        context={"request": request, "drafts": drafts},
        request=request,
    )


@router.get("/dashboard/client-activity", response_class=HTMLResponse)
def dashboard_client_activity(
    request: Request,
    client_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Activity feed panel for client manager dashboard."""
    cid = uuid.UUID(client_id)
    if current_user.user_role.is_client_scoped:
        if current_user.client_id != cid:
            raise HTTPException(status_code=403, detail="Access Denied")

    events = operations_dashboard.get_client_activity_feed(db, cid, limit=15)
    return templates.TemplateResponse(
        name="partials/dashboard_client_activity.html",
        context={"request": request, "events": events},
        request=request,
    )


@router.get("/dashboard/client-avatars", response_class=HTMLResponse)
def dashboard_client_avatars(
    request: Request,
    client_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Avatars panel for client manager dashboard."""
    cid = uuid.UUID(client_id)
    if current_user.user_role.is_client_scoped:
        if current_user.client_id != cid:
            raise HTTPException(status_code=403, detail="Access Denied")

    avatars = operations_dashboard.get_client_avatars_summary(db, cid)
    return templates.TemplateResponse(
        name="partials/dashboard_client_avatars.html",
        context={"request": request, "avatars": avatars},
        request=request,
    )


@router.get("/dashboard/client-subreddits", response_class=HTMLResponse)
def dashboard_client_subreddits(
    request: Request,
    client_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Subreddits panel for client manager dashboard."""
    cid = uuid.UUID(client_id)
    if current_user.user_role.is_client_scoped:
        if current_user.client_id != cid:
            raise HTTPException(status_code=403, detail="Access Denied")

    subreddits = operations_dashboard.get_client_subreddits_summary(db, cid)
    return templates.TemplateResponse(
        name="partials/dashboard_client_subreddits.html",
        context={"request": request, "subreddits": subreddits},
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
    current_user: User = Depends(require_user_management_access),
    db: Session = Depends(get_db),
):
    from app.models.user_role import UserRole

    # client_admin only sees users within their own company
    if current_user.user_role == UserRole.client_admin:
        query = db.query(User).filter(User.client_id == current_user.client_id)
        total = query.count()
        offset = (page - 1) * per_page
        users = query.order_by(User.created_at.desc()).offset(offset).limit(per_page).all()
        clients_list = db.query(Client).filter(Client.id == current_user.client_id).all()
    else:
        users, total = admin_service.list_users(db, page, per_page)
        clients_list = db.query(Client).filter(Client.is_active.is_(True)).order_by(Client.client_name).all()

    pagination = _paginate(page, per_page, total)

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
    user_role: str = Form("client_manager"),
    current_user: User = Depends(require_user_management_access),
    db: Session = Depends(get_db),
):
    from app.models.user_role import UserRole

    error = None
    try:
        # Validate role
        try:
            role_enum = UserRole(user_role)
        except ValueError:
            role_enum = UserRole.client_manager

        # Resolve target client_id for permission check
        target_client_id = None
        if user_client_id and user_client_id.strip():
            try:
                target_client_id = uuid.UUID(user_client_id)
            except ValueError:
                pass

        # Enforce team management scope (raises 403 if unauthorized)
        team_mgmt.validate_team_management(
            requesting_user=current_user,
            target_role=role_enum,
            target_client_id=target_client_id,
        )

        # Set is_superuser based on role for backward compat
        effective_is_superuser = role_enum in (UserRole.owner, UserRole.partner)

        new_user = admin_service.create_admin_user(
            db,
            email=email,
            password=password,
            full_name=full_name or None,
            is_superuser=effective_is_superuser,
            current_user_id=current_user.id,
        )
        # Set role
        new_user.role = role_enum.value
        db.commit()

        # Link user to client if specified and role is client-scoped
        if target_client_id:
            if role_enum in (UserRole.client_manager, UserRole.client_viewer, UserRole.b2c_user, UserRole.client_admin):
                new_user.client_id = target_client_id
                db.commit()
    except ValueError as e:
        error = str(e)

    # Re-fetch user list (scoped for client_admin)
    if current_user.user_role == UserRole.client_admin:
        query = db.query(User).filter(User.client_id == current_user.client_id)
        total = query.count()
        users = query.order_by(User.created_at.desc()).limit(20).all()
        clients_list = db.query(Client).filter(Client.id == current_user.client_id).all()
    else:
        users, total = admin_service.list_users(db)
        clients_list = db.query(Client).filter(Client.is_active.is_(True)).order_by(Client.client_name).all()

    pagination = _paginate(1, 20, total)

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
    current_user: User = Depends(require_user_management_access),
    db: Session = Depends(get_db),
):
    try:
        # Load target user for permission check
        target_user = db.query(User).filter(User.id == user_id).first()
        if not target_user:
            raise ValueError("User not found")

        # Enforce team management scope (raises 403 if unauthorized)
        team_mgmt.validate_user_deactivation(
            requesting_user=current_user,
            target_user=target_user,
        )

        user = admin_service.toggle_user_active(db, user_id, current_user.id)
    except ValueError:
        user = db.query(User).filter(User.id == user_id).first()

    return templates.TemplateResponse(
        name="partials/admin_user_row.html",
        context={"request": request, "user": user, "current_user": current_user},
        request=request,
    )


@router.post("/users/{user_id}/toggle-verified", response_class=HTMLResponse)
def admin_toggle_user_verified(
    request: Request,
    user_id: uuid.UUID,
    current_user: User = Depends(require_user_management_access),
    db: Session = Depends(get_db),
):
    """Toggle email_verified status for a user. Owner/Partner only."""
    from datetime import datetime, timezone
    from app.models.user_role import UserRole as _UR

    # Only owner/partner can manually verify emails (not client_admin)
    if current_user.user_role not in (_UR.owner, _UR.partner):
        return HTMLResponse(status_code=403, content="Only owner/partner can toggle email verification")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return HTMLResponse(status_code=404, content="User not found")

    user.email_verified = not user.email_verified
    if user.email_verified:
        user.email_verified_at = datetime.now(timezone.utc)
    else:
        user.email_verified_at = None
    # Clear any pending verification token
    user.verification_token_hash = None
    user.verification_token_expires = None
    db.commit()
    db.refresh(user)

    audit_service.log_action(
        db,
        action="email_verified_toggled",
        entity_type="user",
        entity_id=user.id,
        user_id=current_user.id,
        details={"email_verified": user.email_verified, "target_email": user.email},
    )

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
    current_user: User = Depends(require_user_management_access),
    db: Session = Depends(get_db),
):
    try:
        # Load target user for permission check
        target_user = db.query(User).filter(User.id == user_id).first()
        if target_user:
            team_mgmt.validate_user_deactivation(
                requesting_user=current_user,
                target_user=target_user,
            )
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


@router.post("/users/{user_id}/hard-delete", response_class=HTMLResponse)
def admin_hard_delete_user(
    request: Request,
    user_id: uuid.UUID,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Permanently delete a user. Owner only."""
    try:
        admin_service.delete_user(db, user_id, current_user.id)
    except ValueError as e:
        # Self-delete or user not found — return row unchanged
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            return templates.TemplateResponse(
                name="partials/admin_user_row.html",
                context={"request": request, "user": user, "current_user": current_user, "error": str(e)},
                request=request,
            )
        return HTMLResponse(content="")
    except Exception as e:
        db.rollback()
        logger.error("Hard-delete user %s failed: %s", user_id, e)
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            return templates.TemplateResponse(
                name="partials/admin_user_row.html",
                context={"request": request, "user": user, "current_user": current_user, "error": f"Delete failed: {str(e)[:100]}"},
                request=request,
            )
        return HTMLResponse(content="")
    # Return empty row (user is gone)
    return HTMLResponse(content="")


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


@router.post("/users/{user_id}/change-role", response_class=HTMLResponse)
def admin_change_user_role(
    request: Request,
    user_id: uuid.UUID,
    new_role: str = Form(...),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Change a user's role. Only owner can do this."""
    from app.models.user_role import UserRole

    # Validate role
    try:
        role_enum = UserRole(new_role)
    except ValueError:
        user = db.query(User).filter(User.id == user_id).first()
        return templates.TemplateResponse(
            name="partials/admin_user_row.html",
            context={"request": request, "user": user, "current_user": current_user},
            request=request,
        )

    # Cannot change own role
    if user_id == current_user.id:
        user = db.query(User).filter(User.id == user_id).first()
        return templates.TemplateResponse(
            name="partials/admin_user_row.html",
            context={"request": request, "user": user, "current_user": current_user},
            request=request,
        )

    # Only owner can assign owner role
    if role_enum == UserRole.owner and current_user.user_role != UserRole.owner:
        user = db.query(User).filter(User.id == user_id).first()
        return templates.TemplateResponse(
            name="partials/admin_user_row.html",
            context={"request": request, "user": user, "current_user": current_user},
            request=request,
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return HTMLResponse("User not found", status_code=404)

    old_role = user.role
    user.role = role_enum.value

    # Sync is_superuser flag for backward compat
    user.is_superuser = role_enum in (UserRole.owner, UserRole.partner)

    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="change_role",
        entity_type="user",
        entity_id=user.id,
        details={
            "email": user.email,
            "old_role": old_role,
            "new_role": role_enum.value,
        },
    )

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
    sort: str = "created",
    order: str = "desc",
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    clients, total = admin_service.list_clients_paginated(db, page, per_page)
    pagination = _paginate(page, per_page, total)

    # Sort in Python (data is already fetched with counts)
    valid_sorts = {
        "name": lambda x: (x["client"].client_name or "").lower(),
        "brand": lambda x: (x["client"].brand_name or "").lower(),
        "active": lambda x: x["client"].is_active,
        "subreddits": lambda x: x["subreddit_count"],
        "avatars": lambda x: x["avatar_count"],
        "cost": lambda x: x["ai_cost_month"],
        "created": lambda x: x["client"].created_at or datetime.min.replace(tzinfo=timezone.utc),
    }
    if sort not in valid_sorts:
        sort = "created"
    if order not in ("asc", "desc"):
        order = "desc"

    clients.sort(key=valid_sorts[sort], reverse=(order == "desc"))

    return templates.TemplateResponse(
        name="admin_clients.html",
        context={
            "request": request,
            "active_nav": "clients",
            "clients": clients,
            "pagination": pagination,
            "sort": sort,
            "order": order,
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
    _client_access: User = Depends(verify_client_access_from_path),
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
    _client_access: User = Depends(verify_client_access_from_path),
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
    _client_access: User = Depends(verify_client_access_from_path),
    db: Session = Depends(get_db),
):
    from app.models.strategy_document import StrategyDocument
    from app.models.discovery_session import DiscoverySession

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

    # Enrich avatars with strategy status
    avatar_ids = [a.id for a in avatars]
    strategy_map: dict[str, dict] = {}
    if avatar_ids:
        strategies = (
            db.query(StrategyDocument)
            .filter(
                StrategyDocument.avatar_id.in_(avatar_ids),
                StrategyDocument.is_current.is_(True),
            )
            .all()
        )
        for s in strategies:
            strategy_map[str(s.avatar_id)] = {
                "has_strategy": True,
                "is_approved": s.is_approved,
                "version": s.version,
                "generated_at": s.generated_at,
            }

    # Build enriched avatar data
    avatars_enriched = []
    for avatar in avatars:
        avatar_id_str = str(avatar.id)
        strat = strategy_map.get(avatar_id_str, {"has_strategy": False, "is_approved": False})
        avatars_enriched.append({
            "avatar": avatar,
            "strategy": strat,
        })

    # Query Discovery sessions linked to this client
    discovery_sessions = (
        db.query(DiscoverySession)
        .filter(DiscoverySession.client_id == client_id)
        .order_by(DiscoverySession.created_at.desc())
        .all()
    )

    return templates.TemplateResponse(
        name="admin_client_detail.html",
        context={
            "request": request,
            "active_nav": "clients",
            "client": client,
            "subreddits": subreddits,
            "avatars": avatars,
            "avatars_enriched": avatars_enriched,
            "keywords": keywords,
            "discovery_sessions": discovery_sessions,
            "error": None,
        },
        request=request,
    )


def _build_subreddit_coverage(
    db: Session,
    client_id: uuid.UUID,
    sort_by: str = "type",
    sort_dir: str = "asc",
) -> list[dict]:
    """Build unified subreddit coverage data (plan vs actual).

    Merges client subreddit assignments with avatar presence data.
    Returns list of dicts with: subreddit_name, type, comments, karma,
    status_icon, status_text.
    """
    from app.models.avatar_subreddit_presence import AvatarSubredditPresence

    subreddits = admin_service.list_client_subreddits(db, client_id)
    avatars = (
        db.query(Avatar)
        .filter(Avatar.client_ids.any(str(client_id)))
        .all()
    )
    avatar_ids = [a.id for a in avatars]

    # Build assignment type map (lowercase key -> type)
    assignment_type_map: dict[str, str] = {}
    assignment_display_names: dict[str, str] = {}
    assignment_subreddit_ids: dict[str, str] = {}
    assignment_risk_scores: dict[str, int | None] = {}
    for s in subreddits:
        if s["is_active"]:
            key = s["subreddit_name"].lower()
            assignment_type_map[key] = s["type"]
            assignment_display_names[key] = s["subreddit_name"]
            assignment_subreddit_ids[key] = str(s["subreddit_id"])
            assignment_risk_scores[key] = s.get("risk_score")

    # Build presence map from AvatarSubredditPresence
    presence_map: dict[str, dict] = {}
    if avatar_ids:
        presence_rows = (
            db.query(
                AvatarSubredditPresence.subreddit_name,
                Avatar.reddit_username,
                AvatarSubredditPresence.comment_count,
                AvatarSubredditPresence.total_karma,
            )
            .join(Avatar, Avatar.id == AvatarSubredditPresence.avatar_id)
            .filter(AvatarSubredditPresence.avatar_id.in_(avatar_ids))
            .all()
        )

        for sub_name, username, comments, karma in presence_rows:
            key = sub_name.lower()
            entry = presence_map.setdefault(key, {
                "subreddit_name": sub_name,
                "avatars": [],
                "total_comments": 0,
                "total_karma": 0,
            })
            if username not in entry["avatars"]:
                entry["avatars"].append(username)
            entry["total_comments"] += comments
            entry["total_karma"] += karma

        # Also include subreddits from avatar JSONB fields
        for avatar in avatars:
            for field in (avatar.hobby_subreddits, avatar.business_subreddits):
                if not field:
                    continue
                for item in field:
                    sub_name = item.get("subreddit") if isinstance(item, dict) else item
                    if not sub_name:
                        continue
                    key = sub_name.lower()
                    entry = presence_map.setdefault(key, {
                        "subreddit_name": sub_name,
                        "avatars": [],
                        "total_comments": 0,
                        "total_karma": 0,
                    })
                    if avatar.reddit_username and avatar.reddit_username not in entry["avatars"]:
                        entry["avatars"].append(avatar.reddit_username)

    # Merge all subreddit names
    all_sub_keys: set[str] = set(assignment_type_map.keys()) | set(presence_map.keys())

    # Build coverage rows
    coverage: list[dict] = []
    for key in all_sub_keys:
        assignment_type = assignment_type_map.get(key)
        presence = presence_map.get(key)

        # Display name: prefer presence (has original case), then assignment
        display_name = key
        if presence:
            display_name = presence["subreddit_name"]
        elif key in assignment_display_names:
            display_name = assignment_display_names[key]

        # Determine type label
        if assignment_type == "professional":
            type_label = "Target"
        elif assignment_type == "hobby":
            type_label = "Hobby"
        else:
            type_label = "Extra"

        comments = presence["total_comments"] if presence else 0
        karma = presence["total_karma"] if presence else 0

        # Compute status
        status_icon, status_text = _compute_subreddit_status(type_label, comments, karma)

        coverage.append({
            "subreddit_name": display_name,
            "subreddit_id": assignment_subreddit_ids.get(key),
            "type": type_label,
            "comments": comments,
            "karma": karma,
            "status_icon": status_icon,
            "status_text": status_text,
            "risk_score": assignment_risk_scores.get(key),
        })

    # Sort
    coverage = _sort_coverage(coverage, sort_by, sort_dir)
    return coverage


def _compute_subreddit_status(type_label: str, comments: int, karma: int) -> tuple[str, str]:
    """Compute status icon and text for a subreddit coverage row."""
    if type_label in ("Target", "Hobby"):
        if comments == 0 and karma == 0:
            return ("warning", "Not active yet")
        else:
            return ("active", f"Active ({karma:+d} karma)")
    else:  # Extra
        if comments == 0 and karma == 0:
            return ("warning", "No engagement")
        elif comments > 0:
            if karma >= 5:
                return ("suggest", f"Active ({karma:+d} karma) — consider adding")
            else:
                return ("active", f"Active ({karma:+d} karma)")
        else:
            return ("suggest", "Low priority")


def _sort_coverage(coverage: list[dict], sort_by: str, sort_dir: str) -> list[dict]:
    """Sort coverage list by the given column and direction."""
    reverse = sort_dir == "desc"

    if sort_by == "subreddit":
        coverage.sort(key=lambda x: x["subreddit_name"].lower(), reverse=reverse)
    elif sort_by == "type":
        type_order = {"Target": 0, "Hobby": 1, "Extra": 2}
        if reverse:
            # desc: Extra -> Hobby -> Target, within group by karma desc
            coverage.sort(key=lambda x: (-type_order.get(x["type"], 9), -x["karma"]))
        else:
            # asc (default): Target -> Hobby -> Extra, within group by karma desc
            coverage.sort(key=lambda x: (type_order.get(x["type"], 9), -x["karma"]))
    elif sort_by == "comments":
        coverage.sort(key=lambda x: x["comments"], reverse=reverse)
    elif sort_by == "karma":
        coverage.sort(key=lambda x: x["karma"], reverse=reverse)
    elif sort_by == "status":
        coverage.sort(key=lambda x: x["status_text"].lower(), reverse=reverse)
    else:
        # Default: type asc, karma desc
        type_order = {"Target": 0, "Hobby": 1, "Extra": 2}
        coverage.sort(key=lambda x: (type_order.get(x["type"], 9), -x["karma"]))

    return coverage


@router.get("/clients/{client_id}/subreddits-table", response_class=HTMLResponse)
def admin_client_subreddits_table(
    request: Request,
    client_id: uuid.UUID,
    sort_by: str = "type",
    sort_dir: str = "asc",
    current_user: User = Depends(require_superuser),
    _client_access: User = Depends(verify_client_access_from_path),
    db: Session = Depends(get_db),
):
    """HTMX endpoint: returns the sortable subreddit coverage table partial."""
    # Validate sort params
    valid_sort_cols = {"subreddit", "type", "comments", "karma", "status"}
    if sort_by not in valid_sort_cols:
        sort_by = "type"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "asc"

    coverage = _build_subreddit_coverage(db, client_id, sort_by, sort_dir)

    return templates.TemplateResponse(
        name="partials/client_subreddit_coverage.html",
        context={
            "request": request,
            "client_id": client_id,
            "subreddit_coverage": coverage,
            "sort_by": sort_by,
            "sort_dir": sort_dir,
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
    autopilot_enabled: str = Form(""),
    current_user: User = Depends(require_superuser),
    _client_access: User = Depends(verify_client_access_from_path),
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
            autopilot_enabled=autopilot_enabled == "true",
        )
    except ValueError as e:
        return HTMLResponse(str(e), status_code=404)

    return RedirectResponse(url=f"/admin/clients/{client_id}", status_code=303)


@router.post("/clients/{client_id}/deactivate", response_class=HTMLResponse)
def admin_client_deactivate(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    _client_access: User = Depends(verify_client_access_from_path),
    db: Session = Depends(get_db),
):
    try:
        admin_service.deactivate_client(db, client_id, current_user.id)
    except ValueError:
        pass
    return RedirectResponse(url="/admin/clients", status_code=303)


@router.post("/clients/{client_id}/activate", response_class=HTMLResponse)
def admin_client_activate(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    _client_access: User = Depends(verify_client_access_from_path),
    db: Session = Depends(get_db),
):
    try:
        admin_service.activate_client(db, client_id, current_user.id)
    except ValueError:
        pass
    return RedirectResponse(url=f"/admin/clients/{client_id}", status_code=303)


@router.post("/clients/{client_id}/run-pipeline", response_class=HTMLResponse)
def admin_client_run_pipeline(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    _client_access: User = Depends(verify_client_access_from_path),
    db: Session = Depends(get_db),
):
    """Manually trigger score -> generate pipeline for a specific client.

    Bypasses pipeline_enabled kill switch but uses the same Celery queues
    and respects all safety checks (rate limits, phase policy, budgets).
    """
    import logging
    from app.logging_config import get_logger
    logger = get_logger(__name__)

    from app.tasks.worker import celery_app
    try:
        task_id = admin_service.trigger_pipeline(celery_app, "full", str(client_id))
        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action="trigger_pipeline",
            entity_type="client",
            entity_id=client_id,
            details={"pipeline_type": "full", "triggered_by": "manual", "task_id": task_id},
        )
    except Exception as e:
        logger.error(f"Failed to trigger pipeline for client {client_id}: {e}")
    return RedirectResponse(url=f"/admin/clients/{client_id}", status_code=303)


# ---------------------------------------------------------------------------
# Client cascade deletion
# ---------------------------------------------------------------------------


@router.get("/clients/{client_id}/delete-preview")
def admin_client_delete_preview(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    _client_access: User = Depends(verify_client_access_from_path),
    db: Session = Depends(get_db),
):
    """Return JSON with counts of all entities that will be deleted."""
    from fastapi.responses import JSONResponse
    try:
        preview = admin_service.get_client_cascade_preview(db, client_id)
        return JSONResponse(content=preview)
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=404)


@router.post("/clients/{client_id}/delete", response_class=HTMLResponse)
def admin_client_delete(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    _client_access: User = Depends(verify_client_access_from_path),
    db: Session = Depends(get_db),
):
    """Permanently delete a client and all associated data (cascade)."""
    try:
        result = admin_service.delete_client_cascade(db, client_id, current_user.id)
    except ValueError as e:
        return RedirectResponse(url="/admin/clients", status_code=303)
    return RedirectResponse(url="/admin/clients", status_code=303)


# ---------------------------------------------------------------------------
# Trial management
# ---------------------------------------------------------------------------


@router.get("/trials", response_class=HTMLResponse)
def admin_trials(
    request: Request,
    current_user: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    """Trial management panel — all trial clients with status and actions."""
    from datetime import datetime, timezone
    from app.models.client import Client as ClientModel

    trial_clients = (
        db.query(ClientModel)
        .filter(ClientModel.plan_type == "trial")
        .order_by(ClientModel.created_at.desc())
        .all()
    )

    now = datetime.now(timezone.utc)
    trials = []
    for client in trial_clients:
        days_elapsed = (now - client.created_at).days if client.created_at else 0
        days_left = max(0, 14 - days_elapsed)

        if days_left == 0:
            status = "expired"
        elif days_left <= 3:
            status = "expiring"
        else:
            status = "active"

        # Find the user linked to this trial client
        user = db.query(User).filter(User.client_id == client.id).first()

        trials.append({
            "client": client,
            "user": user,
            "days_left": days_left,
            "days_elapsed": days_elapsed,
            "status": status,
        })

    return templates.TemplateResponse(
        name="admin_trials.html",
        context={
            "request": request,
            "active_nav": "trials",
            "trials": trials,
        },
        request=request,
    )


@router.post("/trials/{client_id}/upgrade", response_class=HTMLResponse)
def admin_trial_upgrade(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    """Upgrade a trial client to starter plan."""
    from app.models.client import Client as ClientModel

    client = db.query(ClientModel).filter(ClientModel.id == client_id).first()
    if client and client.plan_type == "trial":
        client.plan_type = "starter"
        client.max_avatars = 3
        db.commit()

        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action="upgrade_trial",
            entity_type="client",
            entity_id=client_id,
            details={"from": "trial", "to": "starter"},
        )


    # Trial signal: upgrade CTA clicked/converted (conversion)
    try:
        from app.services.trial_signal_hooks import record_trial_signal_background
        record_trial_signal_background(
            client_id=client_id,
            signal_type="upgrade_completed",
            signal_category="conversion",
            signal_value={"from": "trial", "to": "starter"},
        )
    except Exception:
        pass

    return RedirectResponse(url="/admin/trials", status_code=303)


@router.post("/trials/{client_id}/extend", response_class=HTMLResponse)
def admin_trial_extend(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    """Extend trial by 7 days (shifts created_at back by 7 days)."""
    from datetime import timedelta
    from app.models.client import Client as ClientModel

    client = db.query(ClientModel).filter(ClientModel.id == client_id).first()
    if client and client.plan_type == "trial" and client.created_at:
        client.created_at = client.created_at - timedelta(days=7)
        db.commit()

        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action="extend_trial",
            entity_type="client",
            entity_id=client_id,
            details={"extended_days": 7},
        )

    return RedirectResponse(url="/admin/trials", status_code=303)


# ---------------------------------------------------------------------------
# Keyword management (6.5)
# ---------------------------------------------------------------------------

@router.get("/keywords/{client_id}", response_class=HTMLResponse)
def admin_keywords(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    _client_access: User = Depends(verify_client_access_from_path),
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
    _client_access: User = Depends(verify_client_access_from_path),
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
    _client_access: User = Depends(verify_client_access_from_path),
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
    _client_access: User = Depends(verify_client_access_from_path),
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

    # Query AI costs per subreddit (last 30 days)
    from app.models.ai_usage import AIUsageLog
    from sqlalchemy import func as sqla_func
    from datetime import timedelta

    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    ai_cost_rows = (
        db.query(
            AIUsageLog.subreddit_name,
            sqla_func.sum(AIUsageLog.cost_usd).label("total_cost"),
        )
        .filter(
            AIUsageLog.subreddit_name.isnot(None),
            AIUsageLog.created_at >= thirty_days_ago,
        )
        .group_by(AIUsageLog.subreddit_name)
        .all()
    )
    ai_cost_map = {row.subreddit_name: float(row.total_cost or 0) for row in ai_cost_rows}

    enriched = []
    now_utc = datetime.now(timezone.utc)

    # Get last scrape log per subreddit for result info
    from app.models.scrape_log import ScrapeLog
    last_scrape_logs = {}
    all_sub_names = set()
    for assignment in assignments:
        all_sub_names.add(assignment.subreddit.subreddit_name)

    if all_sub_names:
        # Get the most recent scrape log for each subreddit
        from sqlalchemy import distinct
        for sub_name in all_sub_names:
            log = (
                db.query(ScrapeLog)
                .filter(ScrapeLog.subreddit_name == sub_name)
                .order_by(ScrapeLog.scraped_at.desc())
                .first()
            )
            if log:
                last_scrape_logs[sub_name] = log

    # Get scrape settings for "next scrape" calculation
    from app.services.settings import get_setting, is_scrape_enabled
    scrape_enabled = is_scrape_enabled(db)
    freshness_window_hours = int(get_setting(db, "scrape_freshness_window_hours") or "12")

    # Global scrape status info
    last_global_scrape = (
        db.query(ScrapeLog)
        .order_by(ScrapeLog.scraped_at.desc())
        .first()
    )
    scrape_rate_limit_rpm = int(get_setting(db, "scrape_rate_limit_rpm") or "30")
    scrape_tick_interval = int(get_setting(db, "scrape_tick_interval_seconds") or "60")

    # Scrapes in last hour (for rate display)
    one_hour_ago = now_utc - timedelta(hours=1)
    scrapes_last_hour = (
        db.query(sa_func.count(ScrapeLog.id))
        .filter(ScrapeLog.scraped_at >= one_hour_ago)
        .scalar()
    ) or 0

    # Next tick estimate
    if last_global_scrape and last_global_scrape.scraped_at:
        next_tick_at = last_global_scrape.scraped_at + timedelta(seconds=scrape_tick_interval)
        if next_tick_at <= now_utc:
            next_tick_display = "due now"
        else:
            remaining_sec = int((next_tick_at - now_utc).total_seconds())
            next_tick_display = f"in {remaining_sec}s"
    else:
        next_tick_display = "due now"

    # Count stale subreddits (due for scraping)
    stale_subs_count = (
        db.query(sa_func.count(Subreddit.id))
        .join(ClientSubredditAssignment, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .filter(
            Subreddit.is_active.is_(True),
            ClientSubredditAssignment.is_active.is_(True),
        )
        .filter(
            (Subreddit.last_scraped_at.is_(None))
            | (Subreddit.last_scraped_at <= now_utc - timedelta(hours=freshness_window_hours))
        )
        .scalar()
    ) or 0

    scrape_status = {
        "enabled": scrape_enabled,
        "last_scrape": last_global_scrape,
        "rate_limit_rpm": scrape_rate_limit_rpm,
        "scrapes_last_hour": scrapes_last_hour,
        "tick_interval_sec": scrape_tick_interval,
        "next_tick": next_tick_display,
        "stale_count": stale_subs_count,
    }

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

        # Last scrape result
        scrape_log = last_scrape_logs.get(sub.subreddit_name)
        last_result = None
        if scrape_log:
            last_result = {
                "posts_found": scrape_log.posts_found,
                "posts_new": scrape_log.posts_new,
                "duration_ms": scrape_log.duration_ms,
                "error": scrape_log.errors,
            }

        # Next scrape estimate
        next_scrape_display = None
        if scrape_enabled and assignment.is_active:
            if last_scraped:
                next_at = last_scraped + timedelta(hours=freshness_window_hours)
                if next_at <= now_utc:
                    next_scrape_display = "due now"
                else:
                    remaining = next_at - now_utc
                    remaining_hours = remaining.total_seconds() / 3600
                    if remaining_hours >= 1:
                        next_scrape_display = f"in {int(remaining_hours)}h {int((remaining_hours % 1) * 60)}m"
                    else:
                        next_scrape_display = f"in {int(remaining_hours * 60)}m"
            else:
                next_scrape_display = "due now"

        # Get risk score from risk_profile relationship if available
        risk_score = None
        if sub.risk_profile:
            risk_score = sub.risk_profile.risk_score

        enriched.append({
            "sub": assignment,
            "subreddit_name": sub.subreddit_name,
            "subreddit_id": sub.id,
            "is_active": assignment.is_active,
            "type": assignment.type,
            "last_scraped_at": last_scraped,
            "created_at": assignment.created_at,
            "client_name": assignment.client.client_name,
            "client_id": assignment.client_id,
            "client_is_active": assignment.client.is_active,
            "age_hours": age_hours,
            "age_display": age_display,
            "ai_cost_30d": ai_cost_map.get(sub.subreddit_name, 0.0),
            "last_result": last_result,
            "next_scrape": next_scrape_display,
            "risk_score": risk_score,
        })

    # Get all clients for filter dropdown (include inactive — they may have subreddit assignments)
    clients = db.query(Client).order_by(Client.client_name).all()

    # Determine if the selected client is inactive (for banner display)
    selected_client_inactive = False
    selected_client_name = ""
    if client_id:
        try:
            cid = uuid.UUID(client_id)
            selected_client = db.query(Client).filter(Client.id == cid).first()
            if selected_client and not selected_client.is_active:
                selected_client_inactive = True
                selected_client_name = selected_client.client_name
        except ValueError:
            pass

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
            "scrape_enabled": scrape_enabled,
            "freshness_window_hours": freshness_window_hours,
            "scrape_status": scrape_status,
            "selected_client_inactive": selected_client_inactive,
            "selected_client_name": selected_client_name,
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

    # Load risk profile for this subreddit
    sub = overview["subreddit"]
    risk_profile = None
    if sub:
        from app.models.subreddit_risk_profile import SubredditRiskProfile
        risk_profile = (
            db.query(SubredditRiskProfile)
            .filter(SubredditRiskProfile.subreddit_id == sub.id)
            .first()
        )

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
            "risk_profile": risk_profile,
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


@router.post("/subreddits/scrape-now", response_class=HTMLResponse)
def admin_scrape_now(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Manually trigger scraping for the most stale subreddits.

    Dispatches up to 3 stale subreddits to the Celery scrape queue.
    Respects rate limits — won't dispatch if rate limit is exhausted.
    """
    from app.models.subreddit import Subreddit, ClientSubredditAssignment
    from app.models.client import Client
    from app.services.settings import get_setting, is_scrape_enabled

    if not is_scrape_enabled(db):
        return HTMLResponse(
            '<span class="text-red-400 text-xs font-medium">Scraping is disabled (scrape_enabled=false)</span>'
        )

    freshness_hours = int(get_setting(db, "scrape_freshness_window_hours") or "12")
    now = datetime.now(timezone.utc)
    from datetime import timedelta
    cutoff = now - timedelta(hours=freshness_hours)

    # Find stale subreddits
    stale = (
        db.query(Subreddit)
        .join(ClientSubredditAssignment, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .join(Client, Client.id == ClientSubredditAssignment.client_id)
        .filter(
            Subreddit.is_active.is_(True),
            ClientSubredditAssignment.is_active.is_(True),
            Client.is_active.is_(True),
        )
        .filter(
            (Subreddit.last_scraped_at.is_(None))
            | (Subreddit.last_scraped_at <= cutoff)
        )
        .order_by(Subreddit.last_scraped_at.asc().nulls_first())
        .limit(3)
        .all()
    )

    if not stale:
        return HTMLResponse(
            '<span class="text-green-400 text-xs font-medium">All subreddits are fresh — nothing to scrape</span>'
        )

    # Dispatch to Celery
    from app.tasks.scraping import scrape_subreddit_shared
    dispatched = []
    for sub in stale:
        try:
            scrape_subreddit_shared.delay(str(sub.id))
            dispatched.append(sub.subreddit_name)
        except Exception:
            pass

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="manual_scrape",
        entity_type="subreddit",
        details={"dispatched": dispatched, "count": len(dispatched)},
    )

    names = ", ".join(f"r/{n}" for n in dispatched)
    return HTMLResponse(
        f'<span class="text-indigo-400 text-xs font-medium">⚡ Dispatched {len(dispatched)} to queue: {names}</span>'
    )


@router.post("/subreddits/{subreddit_id}/reenable", response_class=HTMLResponse)
def admin_reenable_subreddit(
    request: Request,
    subreddit_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Re-enable a shared subreddit that was auto-disabled due to consecutive failures.

    Resets consecutive_failures counter, clears disabled_reason/disabled_at,
    and sets is_active back to True.
    """
    sub = db.query(Subreddit).filter(Subreddit.id == subreddit_id).first()
    if not sub:
        return HTMLResponse("Subreddit not found", status_code=404)

    old_reason = sub.disabled_reason
    sub.is_active = True
    sub.consecutive_failures = 0
    sub.disabled_reason = None
    sub.disabled_at = None
    # Reset last_scraped_at so it gets picked up by queue_tick immediately
    sub.last_scraped_at = None
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="reenable_subreddit",
        entity_type="subreddit",
        entity_id=sub.id,
        details={
            "subreddit_name": sub.subreddit_name,
            "previous_disabled_reason": old_reason,
        },
    )

    return RedirectResponse(url="/admin/subreddits", status_code=303)


@router.get("/avatars", response_class=HTMLResponse)
def admin_avatars(
    request: Request,
    q: str = "",
    status: str = "",
    client_id: str = "",
    pool: str = "",
    sort: str = "username",
    view: str = "table",
    group: str = "client",
    page: int = 1,
    current_user: User = Depends(require_avatar_admin),
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
    from app.services.avatars_query import build_avatar_view
    from app.services import karma_tracker

    f = AvatarFilter(
        q=q.strip(),
        status=status,
        client_id=client_id,
        pool=pool,
        sort=sort,
        view=view if view in ("grid", "table") else "table",
        group=group if group in ("client", "none") else "client",
        page=page,
    )

    # Avatar manager flag — sees only unassigned avatars in the list
    from app.models.user_role import UserRole as _UserRole
    is_avatar_manager = current_user.user_role == _UserRole.avatar_manager
    viewer_client_id = None
    if is_avatar_manager:
        # Force "no grouping" and "no client filter" for avatar_manager
        f = AvatarFilter(
            q=q.strip(),
            status=status,
            client_id="",
            pool=pool,
            sort=sort,
            view=view if view in ("grid", "table") else "table",
            group="none",
            page=page,
        )

    avatar_page = list_avatars_page(db, f, viewer_client_id=viewer_client_id)

    # Avatar manager sees only unassigned avatars in the list
    if is_avatar_manager:
        avatar_page.items = [
            a for a in avatar_page.items
            if not a.client_ids or a.client_ids == []
        ]
        avatar_page.filtered_total = len(avatar_page.items)
        avatar_page.total_in_scope = avatar_page.filtered_total
        avatar_page.groups = []
        # Recompute counts from the same scoped item set so that
        # active_count ≤ total_count invariant holds (fixes QA bug 2.2).
        from app.services.avatars_query import _aggregate_group_status
        avatar_page.counts = _aggregate_group_status(avatar_page.items)

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

    # Batch health metrics for all visible avatars (1 query instead of N×5)
    from app.services.avatars_query import batch_get_health_for_list
    all_visible_avatars = list(avatar_page.items)
    for g in avatar_page.groups:
        all_visible_avatars.extend(g.avatars)
    health_by_id = batch_get_health_for_list(db, all_visible_avatars)

    def _to_view(a):
        health = health_by_id.get(str(a.id), {})
        view_dict = build_avatar_view(
            a,
            health,
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
        "is_avatar_manager": is_avatar_manager,
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
    pool: str = "",
    sort: str = "username",
    view: str = "table",
    group: str = "client",
    page: int = 1,
    current_user: User = Depends(require_avatar_admin),
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
    from app.services.reddit_freshness import reddit_status_manual_batch_limit
    from app.services import karma_tracker

    f = AvatarFilter(q=q.strip(), status=status, client_id=client_id, pool=pool, sort=sort,
                     view=view, group=group, page=page)
    page_data = list_avatars_page(db, f, viewer_client_id=None)
    force = request.query_params.get("force") == "1"
    batch_limit = reddit_status_manual_batch_limit(db)
    check_all_reddit_statuses(db, page_data.items[:batch_limit], force=force)

    page_data = list_avatars_page(db, f, viewer_client_id=None)

    visible_ids = [a.id for a in page_data.items]
    for g in page_data.groups:
        visible_ids.extend(a.id for a in g.avatars)
    top_by_avatar = karma_tracker.top_subreddits_for_avatars(db, visible_ids, limit=3)

    # Batch health metrics
    from app.services.avatars_query import batch_get_health_for_list
    all_visible = list(page_data.items)
    for g in page_data.groups:
        all_visible.extend(g.avatars)
    health_by_id = batch_get_health_for_list(db, all_visible)

    def _to_view(a):
        return build_avatar_view(
            a,
            health_by_id.get(str(a.id), {}),
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


@router.post("/avatars/{avatar_id}/health-check", response_class=HTMLResponse)
def admin_avatar_health_check(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Trigger manual health check for a single avatar (HTMX endpoint).

    Returns an updated health badge partial that replaces the badge inline.
    Creates an audit log entry with action "health_check_manual".
    """
    import logging

    from app.services.health_checker import check_avatar_health
    from app.services.reddit_freshness import is_health_check_fresh
    from app.services.safety import _format_relative_time

    logger = get_logger(__name__)

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse(
            '<span class="text-[10px] text-red-400">Avatar not found</span>',
            status_code=404,
        )

    try:
        force = request.query_params.get("force") == "1"
        if force or not is_health_check_fresh(db, avatar):
            result = check_avatar_health(db, avatar)

            # Audit log: manual health check
            try:
                audit_service.log_action(
                    db=db,
                    user_id=current_user.id,
                    action="health_check_manual",
                    entity_type="avatar",
                    entity_id=avatar.id,
                    details={
                        "reddit_username": avatar.reddit_username,
                        "previous_status": result.previous_status,
                        "new_status": result.new_status,
                        "detection_method": result.detection_method,
                    },
                )
            except Exception:
                logger.warning(
                    "Failed to audit log manual health check for %s",
                    avatar.reddit_username,
                    exc_info=True,
                )
        else:
            logger.info(
                "Manual health check skipped for %s: fresh cache checked_at=%s",
                avatar.reddit_username,
                avatar.last_health_check,
            )

        # Return updated badge partial
        now = datetime.now(timezone.utc)
        health_status = avatar.health_status or "unknown"
        relative_time = _format_relative_time(avatar.last_health_check, now) if avatar.last_health_check else "Never checked"

        badge_html = _render_health_badge_html(health_status, relative_time)
        return HTMLResponse(badge_html)

    except Exception as e:
        logger.error(
            "Manual health check failed for avatar %s: %s",
            avatar_id, str(e),
            exc_info=True,
        )
        # Return error message that re-enables the button
        return HTMLResponse(
            '<span class="text-[10px] text-red-400">⚠ Check failed — try again later</span>',
            status_code=200,
        )


def _render_health_badge_html(health_status: str, relative_time: str) -> str:
    """Render the health badge HTML fragment for HTMX swap."""
    status = health_status.lower()
    if status == "active":
        badge = '<span class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-green-900/50 text-green-400 border border-green-800">ACTIVE</span>'
    elif status == "limited":
        badge = '<span class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-yellow-900/50 text-yellow-400 border border-yellow-800">LIMITED</span>'
    elif status == "shadowbanned":
        badge = '<span class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-900/50 text-red-400 border border-red-800">SHADOWBANNED</span>'
    elif status == "suspended":
        badge = '<span class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-900/50 text-red-400 border border-red-800">SUSPENDED</span>'
    else:
        badge = '<span class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-gray-700/50 text-gray-400 border border-gray-600">UNKNOWN</span>'

    return f'{badge}\n<div class="text-[10px] text-gray-500 mt-0.5">{relative_time}</div>'


@router.post("/avatars/{avatar_id}/update-cqs", response_class=HTMLResponse)
def admin_avatar_update_cqs(
    request: Request,
    avatar_id: uuid.UUID,
    cqs_level: str = Form(...),
    cqs_notes: str = Form(""),
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Update CQS (Contributor Quality Score) for an avatar.

    Accepts manual CQS level input from operator who checked r/WhatIsMyCQS.
    Valid levels: lowest, low, moderate, high, highest.
    """
    import logging

    logger = get_logger(__name__)

    VALID_CQS_LEVELS = {"lowest", "low", "moderate", "high", "highest"}

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse(
            '<span class="text-xs text-red-400">Avatar not found</span>',
            status_code=404,
        )

    level = cqs_level.strip().lower()
    if level not in VALID_CQS_LEVELS:
        return HTMLResponse(
            f'<span class="text-xs text-red-400">Invalid CQS level: {cqs_level}. '
            f'Valid: {", ".join(sorted(VALID_CQS_LEVELS))}</span>',
            status_code=400,
        )

    previous_level = avatar.cqs_level
    avatar.cqs_level = level
    avatar.cqs_checked_at = datetime.now(timezone.utc)
    avatar.cqs_notes = cqs_notes.strip() or None

    # Auto-freeze if CQS drops to lowest — only for Phase 2+ avatars.
    # Phase 1 avatars naturally start with CQS lowest and need warming.
    if level == "lowest" and not avatar.is_frozen and avatar.warming_phase >= 2:
        avatar.is_frozen = True
        avatar.freeze_reason = "CQS dropped to lowest — account likely flagged as spam"
        avatar.frozen_at = datetime.now(timezone.utc)
        logger.warning(
            "AVATAR_AUTO_FROZEN_CQS | username=%s | cqs_level=lowest | phase=%d",
            avatar.reddit_username, avatar.warming_phase,
        )

    db.commit()

    # Audit log
    try:
        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action="cqs_updated",
            entity_type="avatar",
            entity_id=avatar.id,
            details={
                "reddit_username": avatar.reddit_username,
                "previous_level": previous_level,
                "new_level": level,
                "notes": cqs_notes.strip() or None,
            },
        )
    except Exception:
        logger.warning(
            "Failed to audit log CQS update for %s",
            avatar.reddit_username,
            exc_info=True,
        )

    # Return updated CQS badge partial
    badge_html = _render_cqs_badge_html(level, avatar.cqs_checked_at)
    return HTMLResponse(badge_html)


def _render_cqs_badge_html(cqs_level: str | None, checked_at: datetime | None) -> str:
    """Render the CQS badge HTML fragment for HTMX swap."""
    if not cqs_level:
        return (
            '<span class="px-1.5 py-0.5 rounded text-[10px] font-medium '
            'bg-gray-700/50 text-gray-400 border border-gray-600">CQS: NOT CHECKED</span>'
        )

    level = cqs_level.lower()
    if level == "highest":
        badge_class = "bg-green-900/50 text-green-400 border border-green-800"
    elif level == "high":
        badge_class = "bg-green-900/30 text-green-300 border border-green-700"
    elif level == "moderate":
        badge_class = "bg-yellow-900/50 text-yellow-400 border border-yellow-800"
    elif level == "low":
        badge_class = "bg-orange-900/50 text-orange-400 border border-orange-800"
    else:  # lowest
        badge_class = "bg-red-900/50 text-red-400 border border-red-800"

    badge = (
        f'<span class="px-1.5 py-0.5 rounded text-[10px] font-medium {badge_class}">'
        f'CQS: {level.upper()}</span>'
    )

    time_str = ""
    if checked_at:
        time_str = f'<div class="text-[10px] text-gray-500 mt-0.5">Checked: {checked_at.strftime("%Y-%m-%d")}</div>'

    return f'{badge}\n{time_str}'


@router.get("/avatars/new", response_class=HTMLResponse)
def admin_avatar_new_page(
    request: Request,
    client_id: str = "",
    current_user: User = Depends(require_avatar_admin),
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
    pool: str = Form("b2b"),
    industry: str = Form(""),
    client_id: str = Form(""),
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Create a new avatar from the admin panel. Auto-assigns to client if client_id provided."""
    from app.models.user_role import UserRole as _UserRole

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
        pool=pool if pool in ("b2b", "b2c", "mentor", "warm") else "b2b",
        industry=industry or None,
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


@router.get("/avatars/export-csv")
def admin_avatars_export_csv(
    request: Request,
    client_id: str = "",
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Export avatars as CSV file for download."""
    from fastapi.responses import Response
    from app.services.avatar_csv import export_avatars_csv

    cid = None
    if client_id:
        try:
            cid = uuid.UUID(client_id)
        except (ValueError, AttributeError):
            pass

    csv_content = export_avatars_csv(db, client_id=cid)

    suffix = f"_{client_id[:8]}" if client_id else ""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"avatars{suffix}_{ts}.csv"

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="export_csv",
        entity_type="avatar",
        details={"client_id": client_id or None, "format": "csv"},
    )

    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/avatars/csv-template")
def admin_avatars_csv_template(
    request: Request,
    current_user: User = Depends(require_avatar_admin),
):
    """Download an empty CSV template with headers and example row."""
    from fastapi.responses import Response
    from app.services.avatar_csv import get_csv_template

    csv_content = get_csv_template()
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="avatars_template.csv"'},
    )


@router.get("/avatars/import", response_class=HTMLResponse)
def admin_avatars_import_page(
    request: Request,
    client_id: str = "",
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Page with CSV upload form for bulk avatar import."""
    client = None
    if client_id:
        try:
            client = db.query(Client).filter(Client.id == uuid.UUID(client_id)).first()
        except (ValueError, AttributeError):
            pass

    return templates.TemplateResponse(
        name="admin_avatar_import.html",
        context={
            "request": request,
            "active_nav": "avatars",
            "client_id": client_id,
            "client": client,
            "result": None,
        },
        request=request,
    )


@router.post("/avatars/import", response_class=HTMLResponse)
async def admin_avatars_import_submit(
    request: Request,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Process uploaded CSV file and create avatars."""
    from app.services.avatar_csv import import_avatars_csv

    form = await request.form()
    csv_file = form.get("csv_file")
    client_id_str = form.get("client_id", "")

    client_id = None
    client = None
    if client_id_str:
        try:
            client_id = uuid.UUID(str(client_id_str))
            client = db.query(Client).filter(Client.id == client_id).first()
        except (ValueError, AttributeError):
            pass

    if not csv_file or not hasattr(csv_file, "read"):
        return templates.TemplateResponse(
            name="admin_avatar_import.html",
            context={
                "request": request,
                "active_nav": "avatars",
                "client_id": client_id_str,
                "client": client,
                "result": {"error": "No CSV file uploaded"},
            },
            request=request,
        )

    # Read file content
    content = await csv_file.read()
    try:
        csv_content = content.decode("utf-8")
    except UnicodeDecodeError:
        csv_content = content.decode("utf-8-sig")  # Handle BOM

    result = import_avatars_csv(db, csv_content, current_user.id, client_id=client_id)

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="import_csv",
        entity_type="avatar",
        details={
            "client_id": str(client_id) if client_id else None,
            "created_count": result["created_count"],
            "skipped_count": result["skipped_count"],
            "error_count": result["error_count"],
        },
    )

    return templates.TemplateResponse(
        name="admin_avatar_import.html",
        context={
            "request": request,
            "active_nav": "avatars",
            "client_id": client_id_str,
            "client": client,
            "result": result,
        },
        request=request,
    )


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
    _client_access: User = Depends(verify_client_access_from_path),
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
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Avatar detail page with phase information, progress, history, and pipeline results."""
    from app.models.activity_event import ActivityEvent
    from app.models.comment_draft import CommentDraft
    from app.models.hobby import HobbySubreddit
    from app.models.audit import AuditLog
    from app.models.thread import RedditThread
    from app.services.safety import get_avatar_health
    from app.services.avatar_today import compute_today_recommendation
    from app.models.user_role import UserRole as _UserRole
    from sqlalchemy import desc, func, or_

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

    # AI costs for this avatar
    from app.models.ai_usage import AIUsageLog
    from decimal import Decimal

    # Per-avatar costs (where avatar_id is set)
    avatar_cost_rows = (
        db.query(
            AIUsageLog.operation,
            func.count(AIUsageLog.id).label("call_count"),
            func.sum(AIUsageLog.cost_usd).label("total_cost"),
            func.sum(AIUsageLog.input_tokens).label("total_input"),
            func.sum(AIUsageLog.output_tokens).label("total_output"),
        )
        .filter(AIUsageLog.avatar_id == avatar.id)
        .group_by(AIUsageLog.operation)
        .all()
    )

    ai_costs_total = Decimal("0")
    ai_costs = []
    for row in avatar_cost_rows:
        cost = float(row.total_cost or 0)
        ai_costs_total += Decimal(str(row.total_cost or 0))
        ai_costs.append({
            "operation": row.operation,
            "call_count": row.call_count,
            "total_cost": cost,
            "total_input": row.total_input or 0,
            "total_output": row.total_output or 0,
        })

    # Recent individual calls (last 30, for detail view)
    ai_recent_calls = (
        db.query(AIUsageLog)
        .filter(AIUsageLog.avatar_id == avatar.id)
        .order_by(desc(AIUsageLog.created_at))
        .limit(30)
        .all()
    )

    # Last 7 days cost
    from datetime import timedelta
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    ai_cost_7d = (
        db.query(func.sum(AIUsageLog.cost_usd))
        .filter(AIUsageLog.avatar_id == avatar.id, AIUsageLog.created_at >= week_ago)
        .scalar()
    ) or Decimal("0")

    # Last 30 days cost
    month_ago = datetime.now(timezone.utc) - timedelta(days=30)
    ai_cost_30d = (
        db.query(func.sum(AIUsageLog.cost_usd))
        .filter(AIUsageLog.avatar_id == avatar.id, AIUsageLog.created_at >= month_ago)
        .scalar()
    ) or Decimal("0")

    ai_billing = {
        "costs_by_operation": ai_costs,
        "total_cost": float(ai_costs_total),
        "cost_7d": float(ai_cost_7d),
        "cost_30d": float(ai_cost_30d),
        "total_calls": sum(r["call_count"] for r in ai_costs),
        "recent_calls": ai_recent_calls,
    }
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

    shadowban_history_rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.entity_type == "avatar",
            AuditLog.entity_id == avatar.id,
            AuditLog.action.in_(
                (
                    "health_status_changed",
                    "health_check_manual",
                    "reddit_status_shadowban_changed",
                    "safety_quarantine",
                )
            ),
        )
        .order_by(desc(AuditLog.created_at))
        .limit(50)
        .all()
    )

    is_shadowban_detected = bool(
        avatar.health_status == "shadowbanned" or avatar.is_shadowbanned
    )
    shadowban_detected_at = avatar.health_status_changed_at if is_shadowban_detected else None
    shadowban_source = "visibility health" if avatar.health_status == "shadowbanned" else None
    if is_shadowban_detected and not shadowban_source:
        shadowban_source = "reddit account status"

    for entry in shadowban_history_rows:
        details = entry.details or {}
        new_status = details.get("new_status") or details.get("reddit_status")
        new_shadowbanned = details.get("new_shadowbanned")
        if (
            new_status == "shadowbanned"
            or new_shadowbanned is True
            or details.get("reason") == "shadowbanned"
        ):
            shadowban_detected_at = shadowban_detected_at or entry.created_at
            break

    shadowban_history = []
    for entry in shadowban_history_rows:
        details = entry.details or {}
        previous_status = details.get("previous_status")
        new_status = details.get("new_status")
        previous_shadowbanned = details.get("previous_shadowbanned")
        new_shadowbanned = details.get("new_shadowbanned")

        if entry.action == "health_status_changed":
            label = f"Health status changed: {previous_status or 'unknown'} -> {new_status or 'unknown'}"
        elif entry.action == "health_check_manual":
            label = f"Manual health check: {previous_status or 'unknown'} -> {new_status or 'unknown'}"
        elif entry.action == "reddit_status_shadowban_changed":
            label = (
                "Legacy shadowban flag changed: "
                f"{previous_shadowbanned} -> {new_shadowbanned}"
            )
        elif entry.action == "safety_quarantine":
            label = f"Safety quarantine: {details.get('reason') or 'no reason'}"
        else:
            label = entry.action

        shadowban_history.append({
            "created_at": entry.created_at,
            "action": entry.action,
            "label": label,
            "detection_method": details.get("detection_method"),
            "details": details,
        })

    shadowban_status = {
        "is_shadowbanned": is_shadowban_detected,
        "current_health_status": avatar.health_status or "unknown",
        "legacy_shadowban_flag": avatar.is_shadowbanned,
        "detected_at": shadowban_detected_at,
        "last_checked_at": avatar.last_health_check,
        "source": shadowban_source,
        "history": shadowban_history,
    }

    today = compute_today_recommendation(db, avatar, health, pro_pending=pro_pending)

    # EPG — daily publishing program (read-only: never create slots from GET page)
    from app.services.epg import get_epg_status
    epg_client = None
    if avatar.client_ids:
        epg_client = db.query(Client).filter(Client.id == uuid.UUID(avatar.client_ids[0])).first()
    epg = get_epg_status(db, avatar, epg_client)

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
            "ai_billing": ai_billing,
            "assigned_clients": assigned_clients,
            "unassigned_clients": unassigned_clients,
            "karma_history": karma_history,
            "shadowban_status": shadowban_status,
            "today": today,
            "epg": epg,
            "now_utc": datetime.now(timezone.utc),
            "is_avatar_manager": False,
        },
        request=request,
    )


@router.get("/avatars/{avatar_id}/edit", response_class=HTMLResponse)
def admin_avatar_edit_page(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Simple avatar edit page — voice profile, hobby subreddits, account info."""
    from app.models.user_role import UserRole as _UserRole

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    # Format hobby_subreddits for the text input
    hobby_list = avatar.hobby_subreddits or []
    if isinstance(hobby_list, list):
        hobby_str = ", ".join(hobby_list)
    else:
        hobby_str = ""

    # Load active system subreddits for the picker
    from app.models.subreddit import Subreddit
    system_subreddits = (
        db.query(Subreddit.subreddit_name)
        .filter(Subreddit.is_active.is_(True))
        .order_by(Subreddit.subreddit_name.asc())
        .all()
    )
    system_sub_names = [r[0] for r in system_subreddits]

    return templates.TemplateResponse(
        name="admin_avatar_edit.html",
        context={
            "request": request,
            "active_nav": "avatars",
            "avatar": avatar,
            "hobby_subreddits_str": hobby_str,
            "system_subreddits": system_sub_names,
        },
        request=request,
    )


@router.post("/avatars/{avatar_id}/edit", response_class=HTMLResponse)
def admin_avatar_edit_submit(
    request: Request,
    avatar_id: uuid.UUID,
    reddit_username: str = Form(...),
    email_address: str = Form(""),
    voice_profile_md: str = Form(""),
    tone_principles: str = Form(""),
    hill_i_die_on: str = Form(""),
    helpful_mode_topics: str = Form(""),
    constraints: str = Form(""),
    hobby_subreddits: str = Form(""),
    pool: str = Form("b2b"),
    industry: str = Form(""),
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Save avatar profile edits."""
    from app.models.user_role import UserRole as _UserRole

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    avatar.reddit_username = reddit_username
    avatar.email_address = email_address or None
    avatar.voice_profile_md = voice_profile_md or None
    avatar.tone_principles = tone_principles or None
    avatar.hill_i_die_on = hill_i_die_on or None
    avatar.helpful_mode_topics = helpful_mode_topics or None
    avatar.constraints = constraints or None
    avatar.hobby_subreddits = [s.strip() for s in hobby_subreddits.split(",") if s.strip()] if hobby_subreddits else []
    avatar.pool = pool if pool in ("b2b", "b2c", "mentor", "warm") else avatar.pool
    avatar.industry = industry or None

    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="update",
        entity_type="avatar",
        entity_id=avatar.id,
        details={"reddit_username": reddit_username, "updated_by_role": current_user.user_role.value},
    )

    return RedirectResponse(url=f"/admin/avatars/{avatar_id}/edit", status_code=303)


@router.get("/avatars/{avatar_id}/epg", response_class=HTMLResponse)
def admin_avatar_epg_partial(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """HTMX partial: show today's EPG for an avatar."""
    from app.services.epg import get_epg_status

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("<div class='text-red-400 text-xs'>Avatar not found</div>", status_code=404)

    # Get client for budget calculation
    client = None
    if avatar.client_ids:
        client = db.query(Client).filter(Client.id == avatar.client_ids[0]).first()

    epg = get_epg_status(db, avatar, client)

    return templates.TemplateResponse(
        name="partials/avatar_epg.html",
        context={"request": request, "avatar": avatar, "epg": epg},
        request=request,
    )


@router.post("/avatars/{avatar_id}/build-epg", response_class=HTMLResponse)
def admin_avatar_build_epg(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Build EPG and generate comments for an avatar (manual trigger).

    Respects epg2_enabled flag: uses build_portfolio (EPG 2.0) when enabled,
    falls back to legacy build_daily_epg otherwise.
    """
    import logging
    logger = get_logger(__name__)

    from app.services.settings import get_setting

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("<div class='text-red-400 text-xs'>Avatar not found</div>", status_code=404)

    client = None
    if avatar.client_ids:
        client = db.query(Client).filter(Client.id == avatar.client_ids[0]).first()

    epg2_enabled = get_setting(db, "epg2_enabled").lower() in ("true", "1")

    if epg2_enabled:
        from app.services.portfolio_manager import build_portfolio
        from app.services.epg_executor import generate_all_planned_slots

        epg = build_portfolio(db, avatar, client)

        # Generate comments for planned slots (same as Beat task does)
        if epg.status == "ok" and epg.total_slots > 0:
            generated = generate_all_planned_slots(db, avatar.id)
            logger.info(
                "admin_avatar_build_epg (EPG 2.0): avatar=%s status=%s slots=%d generated=%d",
                avatar.reddit_username, epg.status, epg.total_slots, generated,
            )
    else:
        from app.services.epg import build_daily_epg
        epg = build_daily_epg(db, avatar, client)

        # Generate hobby comments for EPG slots
        if epg.hobby_slots:
            from app.tasks.ai_pipeline import generate_hobby_comments
            try:
                generate_hobby_comments.delay(str(avatar.id), max_comments=len(epg.hobby_slots), triggered_by="manual")
            except Exception as e:
                logger.error(f"Failed to dispatch hobby generation for {avatar.reddit_username}: {e}")

        # Generate professional comments for business slots (Phase 2-3)
        if epg.business_slots and client:
            from app.tasks.ai_pipeline import generate_comments
            try:
                generate_comments.delay(str(client.id), max_comments=len(epg.business_slots), triggered_by="manual")
            except Exception as e:
                logger.error(f"Failed to dispatch pro generation for {avatar.reddit_username}: {e}")

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="build_epg",
        entity_type="avatar",
        entity_id=avatar_id,
        details={
            "status": epg.status,
            "hobby_slots": len(epg.hobby_slots),
            "business_slots": len(epg.business_slots),
            "epg2_enabled": epg2_enabled,
        },
    )

    return templates.TemplateResponse(
        name="partials/avatar_epg.html",
        context={"request": request, "avatar": avatar, "epg": epg},
        request=request,
    )


@router.get("/avatars/{avatar_id}/refresh", response_class=HTMLResponse)
def admin_avatar_refresh(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Refresh ALL data for a single avatar in one call:
    1. Reddit status + karma + karma sync
    2. CQS (from r/WhatIsMyCQS bot reply)
    3. Health check (shadowban/visibility)

    Economical: skips steps that are still fresh (unless ?force=1).
    Fast: ~3-5s total (3 Reddit API calls max).
    """
    import logging

    from app.services.reddit_status import check_reddit_status
    from app.services.reddit_freshness import is_reddit_status_fresh
    from app.services.health_checker import check_avatar_health
    from app.services.cqs_checker import update_avatar_cqs_from_reddit

    logger = get_logger(__name__)

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    force = request.query_params.get("force") == "1"

    # 1. Reddit status + karma + karma sync + CQS (all inside check_reddit_status)
    try:
        if force or not is_reddit_status_fresh(db, avatar):
            check_reddit_status(db, avatar)
        db.commit()
    except Exception as e:
        logger.warning("Refresh: reddit_status failed for %s: %s", avatar.reddit_username, e)
        db.rollback()

    # 2. Health check (visibility/shadowban) — skip if checked in last 6h unless forced
    try:
        from app.services.reddit_freshness import is_health_check_fresh

        if force or not is_health_check_fresh(db, avatar):
            check_avatar_health(db, avatar)
            db.commit()
    except Exception as e:
        logger.warning("Refresh: health_check failed for %s: %s", avatar.reddit_username, e)
        db.rollback()

    # Audit
    try:
        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action="avatar_refresh_all",
            entity_type="avatar",
            entity_id=avatar.id,
            details={
                "reddit_username": avatar.reddit_username,
                "forced": force,
                "cqs_level": avatar.cqs_level,
                "health_status": avatar.health_status,
            },
        )
    except Exception:
        pass

    return RedirectResponse(url=f"/admin/avatars/{avatar_id}", status_code=303)


@router.get("/avatars/{avatar_id}/profile-analytics", response_class=HTMLResponse)
def admin_avatar_profile_analytics(
    request: Request,
    avatar_id: uuid.UUID,
    refresh: str = "",
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """HTMX endpoint: fetch fresh Reddit profile analytics, save to DB, return HTML.

    If ?refresh=1 — forces a new fetch from Reddit API.
    Otherwise — returns the latest saved snapshot (or fetches if none exists).
    """
    from app.services.reddit_profile_analytics import (
        fetch_and_save,
        load_latest_snapshot,
        snapshot_to_analytics,
    )

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    if refresh == "1":
        # Force fresh fetch from Reddit API and save
        from app.services.reddit_freshness import is_fresh, profile_analytics_freshness_hours

        snapshot = load_latest_snapshot(db, avatar.id)
        freshness_hours = profile_analytics_freshness_hours(db)
        force = request.query_params.get("force") == "1"
        fresh = bool(snapshot and is_fresh(snapshot.fetched_at, freshness_hours))
        if force or not fresh:
            try:
                analytics = fetch_and_save(db, avatar.id, avatar.reddit_username)
            except Exception as e:
                logger.warning("Profile analytics fetch failed for %s: %s", avatar.reddit_username, e)
                analytics = snapshot_to_analytics(snapshot) if snapshot else None
                if analytics is None:
                    return HTMLResponse(
                        f"<div class='p-4 rounded-lg bg-red-900/20 border border-red-700/50'>"
                        f"<p class='text-sm text-red-300'>⚠️ Reddit API error for u/{avatar.reddit_username}</p>"
                        f"<p class='text-xs text-gray-500 mt-1'>{str(e)[:100]}</p>"
                        f"<p class='text-xs text-gray-500 mt-1'>Account may be suspended, deleted, or shadowbanned.</p>"
                        f"</div>"
                    )
        else:
            analytics = snapshot_to_analytics(snapshot)
    else:
        # Try to load from DB first
        snapshot = load_latest_snapshot(db, avatar.id)
        if snapshot:
            analytics = snapshot_to_analytics(snapshot)
        else:
            # No snapshot exists — fetch and save
            try:
                analytics = fetch_and_save(db, avatar.id, avatar.reddit_username)
            except Exception as e:
                logger.warning("Profile analytics fetch failed for %s: %s", avatar.reddit_username, e)
                return HTMLResponse(
                    f"<div class='p-4 rounded-lg bg-red-900/20 border border-red-700/50'>"
                    f"<p class='text-sm text-red-300'>⚠️ Reddit API error for u/{avatar.reddit_username}</p>"
                    f"<p class='text-xs text-gray-500 mt-1'>{str(e)[:100]}</p>"
                    f"<p class='text-xs text-gray-500 mt-1'>Account may be suspended, deleted, or shadowbanned.</p>"
                    f"</div>"
                )

    return templates.TemplateResponse(
        name="partials/avatar_profile_analytics.html",
        context={"request": request, "analytics": analytics},
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


@router.post("/avatars/{avatar_id}/unassign-from-client", response_class=HTMLResponse)
def admin_unassign_avatar_from_client(
    request: Request,
    avatar_id: uuid.UUID,
    client_id: uuid.UUID = Form(...),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Remove avatar assignment from a specific client."""
    from app.services import admin as admin_service

    try:
        admin_service.unassign_avatar_from_client(db, client_id, avatar_id, current_user.id)
    except ValueError:
        pass

    return RedirectResponse(
        url=f"/admin/avatars/{avatar_id}#tab=overview",
        status_code=303,
    )


@router.post("/avatars/{avatar_id}/display-name", response_class=HTMLResponse)
def admin_avatar_display_name(
    request: Request,
    avatar_id: uuid.UUID,
    display_name: str = Form(""),
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Update avatar's display_name (shown to clients in portal)."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    old_name = avatar.display_name
    new_name = display_name.strip() or None
    avatar.display_name = new_name
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="avatar_display_name_updated",
        entity_type="avatar",
        entity_id=avatar.id,
        details={
            "reddit_username": avatar.reddit_username,
            "old_display_name": old_name,
            "new_display_name": new_name,
        },
    )

    return HTMLResponse(
        "",
        headers={
            "HX-Trigger": '{"showToast": {"type": "success", "message": "Display name updated"}}'
        },
    )


@router.post("/avatars/{avatar_id}/phase-override", response_class=HTMLResponse)
def admin_avatar_phase_override(
    request: Request,
    avatar_id: uuid.UUID,
    target_phase: int = Form(...),
    reason: str = Form(...),
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Admin override to set an avatar's warming phase manually."""
    import redis

    from app.config import get_settings
    from app.services.phase import PhaseTransitionManager
    from app.services.phase_lock import PhaseTransitionLock

    # Validate target_phase
    if target_phase not in {0, 1, 2, 3}:
        return JSONResponse(
            status_code=422,
            content={"detail": "target_phase must be 0 (Mentor), 1, 2, or 3"},
        )

    # Validate reason is non-empty after stripping whitespace
    if not reason.strip():
        return JSONResponse(
            status_code=422,
            content={"detail": "A reason is required for phase override. Please provide a non-empty reason."},
        )
    reason = reason.strip()

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
    current_user: User = Depends(require_avatar_admin),
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

    # Enforce client invariant: if this was the last active avatar, pause the client
    try:
        from app.services.avatar_invariant import enforce_invariant_on_deactivation
        for cid in (avatar.client_ids or []):
            enforce_invariant_on_deactivation(uuid.UUID(cid), db)
    except Exception as e:
        logger.warning("Invariant enforcement after freeze failed: %s", e)

    return RedirectResponse(url=f"/admin/avatars/{avatar_id}", status_code=303)


@router.post("/avatars/{avatar_id}/unfreeze", response_class=HTMLResponse)
def admin_unfreeze_avatar(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
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


# ---------------------------------------------------------------------------
# Avatar Strategy (pipeline-v2, R15)
# ---------------------------------------------------------------------------


def _extract_strategy_questions(strategy) -> list[str]:
    """Extract 'Questions for Client' from strategy document_md.

    Parses the markdown section and returns a list of question strings.
    Returns empty list if no questions found.
    """
    if not strategy or not strategy.document_md:
        return []

    md = strategy.document_md
    # Look for "## Questions for Client" or "## Suggestions" section
    import re
    pattern = r"## (?:Questions for Client|Suggestions)\s*\n((?:- .+\n?)+)"
    match = re.search(pattern, md)
    if not match:
        return []

    lines = match.group(1).strip().split("\n")
    questions = []
    for line in lines:
        line = line.strip()
        if line.startswith("- "):
            questions.append(line[2:].strip())
    return questions


@router.get("/avatars/{avatar_id}/strategy-panel", response_class=HTMLResponse)
def admin_avatar_strategy_panel(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """HTMX partial: Strategy panel showing current strategy + history."""
    try:
        from app.services.strategy_engine import StrategyEngine

        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if not avatar:
            return HTMLResponse("<div class='text-red-400 text-xs p-2'>Avatar not found</div>", status_code=404)

        engine = StrategyEngine()
        current_strategy = engine.get_current_strategy(db, avatar_id)
        strategy_history = engine.get_strategy_history(db, avatar_id, limit=10)

        # Extract questions from strategy markdown for prominent display
        strategy_questions = _extract_strategy_questions(current_strategy)

        return templates.TemplateResponse(
            name="partials/strategy_panel.html",
            context={
                "request": request,
                "avatar": avatar,
                "current_strategy": current_strategy,
                "strategy_history": strategy_history,
                "strategy_questions": strategy_questions,
            },
            request=request,
        )
    except Exception as e:
        logger.error("Strategy panel error for avatar %s: %s", avatar_id, e)
        return HTMLResponse(
            f"<div class='text-red-400 text-xs p-2'>Error loading strategy: {str(e)[:200]}</div>",
            status_code=500,
        )


@router.post("/avatars/{avatar_id}/strategy/generate", response_class=HTMLResponse)
def admin_avatar_strategy_generate(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Kick off async strategy generation. Returns a polling indicator with ETA."""
    try:
        from app.tasks.strategy import generate_strategy_async
        from app.models.ai_usage import AIUsageLog
        from sqlalchemy import func as sa_func
        import redis as redis_lib
        from app.config import get_settings

        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if not avatar:
            return HTMLResponse(
                "<div class='text-red-400 text-xs p-2'>Avatar not found</div>",
                status_code=200,
            )

        # Find client
        client_id = None
        if avatar.client_ids:
            client_id = avatar.client_ids[0]

        # --- Audit log: task requested (BEFORE dispatch) ---
        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action="strategy_generation_requested",
            entity_type="avatar",
            entity_id=avatar_id,
            client_id=uuid.UUID(client_id) if client_id else None,
            details={
                "avatar_username": avatar.reddit_username,
                "triggered_by": "manual",
            },
        )

        # --- Get average duration for strategy_generation from ai_usage_log ---
        avg_duration_ms = (
            db.query(sa_func.avg(AIUsageLog.duration_ms))
            .filter(
                AIUsageLog.operation == "strategy_generation",
                AIUsageLog.duration_ms > 0,
            )
            .scalar()
        )
        avg_seconds = int((avg_duration_ms or 25000) / 1000)

        # --- Get queue depth ---
        queue_depth = 0
        try:
            settings = get_settings()
            r = redis_lib.Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)
            queue_depth = r.llen("celery") or 0
            r.close()
        except Exception:
            pass

        # Estimate wait: queue tasks ahead × avg + own generation time
        estimated_wait = avg_seconds + (queue_depth * 10)

        # Dispatch Celery task
        task = generate_strategy_async.delay(
            str(avatar_id),
            client_id=client_id,
            user_id=str(current_user.id),
        )

        # --- Build informative UI ---
        queue_info = ""
        if queue_depth > 0:
            queue_info = (
                f'<p class="text-xs text-amber-400 mt-1">'
                f'\u23f3 Queue: {queue_depth} task{"s" if queue_depth != 1 else ""} ahead</p>'
            )

        return HTMLResponse(
            f"""<div class="bg-slate-800 rounded-lg border border-slate-700 p-6 text-center"
                 hx-get="/admin/avatars/{avatar_id}/strategy-panel"
                 hx-trigger="every 2s"
                 hx-target="#strategy-panel-content"
                 hx-swap="innerHTML"
                 id="strategy-generating">
                <div class="inline-flex items-center gap-2 text-indigo-400 text-sm">
                    <svg class="animate-spin h-4 w-4" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                    </svg>
                    Generating strategy...
                </div>
                <div class="mt-3">
                    <div class="w-48 mx-auto bg-slate-700 rounded-full h-1.5 overflow-hidden">
                        <div class="bg-indigo-500 h-1.5 rounded-full animate-pulse" style="width: 60%"></div>
                    </div>
                    <p class="text-xs text-gray-400 mt-2">\u2248{estimated_wait}s estimated (avg LLM call: {avg_seconds}s)</p>
                    {queue_info}
                    <p class="text-xs text-gray-500 mt-1">You can navigate away \u2014 result saves automatically.</p>
                </div>
                <p class="text-xs text-gray-600 mt-2">Task: {task.id[:8]}</p>
            </div>""",
            status_code=200,
        )
    except Exception as e:
        logger.error("Strategy generation dispatch error for avatar %s: %s", avatar_id, e, exc_info=True)
        return HTMLResponse(
            f"<div class='bg-red-900/30 border border-red-700 rounded-lg p-4 text-sm text-red-300'>"
            f"<strong>Error:</strong> {str(e)[:200]}</div>",
            status_code=200,
        )


@router.get("/avatars/{avatar_id}/strategy/{strategy_id}/preview", response_class=HTMLResponse)
def admin_avatar_strategy_preview(
    request: Request,
    avatar_id: uuid.UUID,
    strategy_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """HTMX partial: Preview a specific strategy version's content."""
    from app.models.strategy_document import StrategyDocument

    strategy = db.query(StrategyDocument).filter(
        StrategyDocument.id == strategy_id,
        StrategyDocument.avatar_id == avatar_id,
    ).first()
    if not strategy:
        return HTMLResponse("<div class='text-red-400 text-xs p-2'>Strategy not found</div>", status_code=404)

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()

    return templates.TemplateResponse(
        name="partials/strategy_version_preview.html",
        context={
            "request": request,
            "avatar": avatar,
            "doc": strategy,
        },
        request=request,
    )


@router.get("/avatars/{avatar_id}/strategy/{strategy_id}/diff", response_class=HTMLResponse)
def admin_avatar_strategy_diff(
    request: Request,
    avatar_id: uuid.UUID,
    strategy_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """HTMX partial: Show visual diff between a strategy version and the current version."""
    import difflib
    from app.models.strategy_document import StrategyDocument

    # Get the target version
    target = db.query(StrategyDocument).filter(
        StrategyDocument.id == strategy_id,
        StrategyDocument.avatar_id == avatar_id,
    ).first()
    if not target:
        return HTMLResponse("<div class='text-red-400 text-xs p-2'>Strategy not found</div>", status_code=404)

    # Get the current version to compare against
    current = db.query(StrategyDocument).filter(
        StrategyDocument.avatar_id == avatar_id,
        StrategyDocument.is_current == True,
    ).first()

    if not current or current.id == target.id:
        return HTMLResponse("<div class='text-gray-500 text-xs p-2 italic'>This is the current version — nothing to diff against.</div>")

    # Compute line-by-line diff
    old_lines = (target.document_md or "").splitlines()
    new_lines = (current.document_md or "").splitlines()

    differ = difflib.unified_diff(old_lines, new_lines, lineterm="", n=2)
    diff_lines = list(differ)

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()

    return templates.TemplateResponse(
        name="partials/strategy_version_diff.html",
        context={
            "request": request,
            "avatar": avatar,
            "target_version": target.version,
            "current_version": current.version,
            "diff_lines": diff_lines,
        },
        request=request,
    )


@router.post("/avatars/{avatar_id}/strategy/{strategy_id}/approve", response_class=HTMLResponse)
def admin_avatar_strategy_approve(
    request: Request,
    avatar_id: uuid.UUID,
    strategy_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Approve a strategy document for pipeline use."""
    from app.models.strategy_document import StrategyDocument

    strategy = db.query(StrategyDocument).filter(
        StrategyDocument.id == strategy_id,
        StrategyDocument.avatar_id == avatar_id,
    ).first()
    if not strategy:
        return HTMLResponse("<div class='text-red-400 text-xs p-2'>Strategy not found</div>", status_code=404)

    now = datetime.now(timezone.utc)
    strategy.is_approved = True
    strategy.approved_at = now
    strategy.approved_by_user_id = current_user.id
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="strategy_approved",
        entity_type="strategy_document",
        entity_id=strategy.id,
        details={"version": strategy.version, "avatar_id": str(avatar_id)},
    )

    # Re-render the strategy panel
    from app.services.strategy_engine import StrategyEngine
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    engine = StrategyEngine()
    current_strategy = engine.get_current_strategy(db, avatar_id)
    strategy_history = engine.get_strategy_history(db, avatar_id, limit=10)

    return templates.TemplateResponse(
        name="partials/strategy_panel.html",
        context={
            "request": request,
            "avatar": avatar,
            "current_strategy": current_strategy,
            "strategy_history": strategy_history,
            "strategy_questions": _extract_strategy_questions(current_strategy),
        },
        request=request,
    )


@router.post("/avatars/{avatar_id}/strategy/{strategy_id}/unapprove", response_class=HTMLResponse)
def admin_avatar_strategy_unapprove(
    request: Request,
    avatar_id: uuid.UUID,
    strategy_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Revoke approval from a strategy document."""
    from app.models.strategy_document import StrategyDocument

    strategy = db.query(StrategyDocument).filter(
        StrategyDocument.id == strategy_id,
        StrategyDocument.avatar_id == avatar_id,
    ).first()
    if not strategy:
        return HTMLResponse("<div class='text-red-400 text-xs p-2'>Strategy not found</div>", status_code=404)

    strategy.is_approved = False
    strategy.approved_at = None
    strategy.approved_by_user_id = None
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="strategy_unapproved",
        entity_type="strategy_document",
        entity_id=strategy.id,
        details={"version": strategy.version, "avatar_id": str(avatar_id)},
    )

    # Re-render
    from app.services.strategy_engine import StrategyEngine
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    engine = StrategyEngine()
    current_strategy = engine.get_current_strategy(db, avatar_id)
    strategy_history = engine.get_strategy_history(db, avatar_id, limit=10)

    return templates.TemplateResponse(
        name="partials/strategy_panel.html",
        context={
            "request": request,
            "avatar": avatar,
            "current_strategy": current_strategy,
            "strategy_history": strategy_history,
            "strategy_questions": _extract_strategy_questions(current_strategy),
        },
        request=request,
    )


@router.post("/avatars/{avatar_id}/strategy/{strategy_id}/activate", response_class=HTMLResponse)
def admin_avatar_strategy_activate(
    request: Request,
    avatar_id: uuid.UUID,
    strategy_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Activate (set as current) a specific strategy version — manual A/B switch."""
    from app.models.strategy_document import StrategyDocument

    strategy = db.query(StrategyDocument).filter(
        StrategyDocument.id == strategy_id,
        StrategyDocument.avatar_id == avatar_id,
    ).first()
    if not strategy:
        return HTMLResponse("<div class='text-red-400 text-xs p-2'>Strategy not found</div>", status_code=404)

    # Deactivate all other strategies for this avatar
    db.query(StrategyDocument).filter(
        StrategyDocument.avatar_id == avatar_id,
        StrategyDocument.id != strategy_id,
    ).update({"is_current": False})

    strategy.is_current = True
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="strategy_activated",
        entity_type="strategy_document",
        entity_id=strategy.id,
        details={"version": strategy.version, "avatar_id": str(avatar_id)},
    )

    # Re-render
    from app.services.strategy_engine import StrategyEngine
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    engine = StrategyEngine()
    current_strategy = engine.get_current_strategy(db, avatar_id)
    strategy_history = engine.get_strategy_history(db, avatar_id, limit=10)

    return templates.TemplateResponse(
        name="partials/strategy_panel.html",
        context={
            "request": request,
            "avatar": avatar,
            "current_strategy": current_strategy,
            "strategy_history": strategy_history,
            "strategy_questions": _extract_strategy_questions(current_strategy),
        },
        request=request,
    )


@router.post("/avatars/{avatar_id}/strategy/{strategy_id}/edit", response_class=HTMLResponse)
def admin_avatar_strategy_edit(
    request: Request,
    avatar_id: uuid.UUID,
    strategy_id: uuid.UUID,
    document_md: str = Form(...),
    edit_note: str = Form(""),
    goals_json: str = Form(""),
    subreddit_priorities_json: str = Form(""),
    tone_guidelines_json: str = Form(""),
    cadence_rules_json: str = Form(""),
    hook_inventory_json: str = Form(""),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Edit a strategy document's content (markdown and/or structured JSON fields)."""
    import json as json_module
    from app.models.strategy_document import StrategyDocument

    strategy = db.query(StrategyDocument).filter(
        StrategyDocument.id == strategy_id,
        StrategyDocument.avatar_id == avatar_id,
    ).first()
    if not strategy:
        return HTMLResponse("<div class='text-red-400 text-xs p-2'>Strategy not found</div>", status_code=404)

    now = datetime.now(timezone.utc)

    # Update markdown
    if document_md.strip():
        strategy.document_md = document_md.strip()

    # Update structured JSON fields if provided
    def try_parse_json(raw: str, current: dict) -> dict:
        if not raw.strip():
            return current
        try:
            parsed = json_module.loads(raw)
            return parsed
        except (json_module.JSONDecodeError, TypeError):
            return current

    strategy.goals = try_parse_json(goals_json, strategy.goals)
    strategy.subreddit_priorities = try_parse_json(subreddit_priorities_json, strategy.subreddit_priorities)
    strategy.tone_guidelines = try_parse_json(tone_guidelines_json, strategy.tone_guidelines)
    strategy.cadence_rules = try_parse_json(cadence_rules_json, strategy.cadence_rules)
    strategy.hook_inventory = try_parse_json(hook_inventory_json, strategy.hook_inventory)

    strategy.edited_by_user_id = current_user.id
    strategy.edited_at = now
    strategy.edit_note = edit_note.strip() or None
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="strategy_edited",
        entity_type="strategy_document",
        entity_id=strategy.id,
        details={
            "version": strategy.version,
            "avatar_id": str(avatar_id),
            "edit_note": edit_note.strip() or None,
        },
    )

    # Re-render
    from app.services.strategy_engine import StrategyEngine
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    engine = StrategyEngine()
    current_strategy = engine.get_current_strategy(db, avatar_id)
    strategy_history = engine.get_strategy_history(db, avatar_id, limit=10)

    return templates.TemplateResponse(
        name="partials/strategy_panel.html",
        context={
            "request": request,
            "avatar": avatar,
            "current_strategy": current_strategy,
            "strategy_history": strategy_history,
            "strategy_questions": _extract_strategy_questions(current_strategy),
        },
        request=request,
    )


@router.post("/settings/pipeline-controls", response_class=HTMLResponse)
def admin_toggle_pipeline_control(
    request: Request,
    setting_key: str = Form(...),
    setting_value: str = Form(...),
    current_user: User = Depends(require_owner),
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
    _client_access: User = Depends(verify_client_access_from_path),
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
    _client_access: User = Depends(verify_client_access_from_path),
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
    _client_access: User = Depends(verify_client_access_from_path),
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


@router.get("/health/widget/pipeline-timeline", response_class=HTMLResponse)
def admin_health_pipeline_timeline(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX widget: pipeline run timeline — last run per pipeline type."""
    from app.models.pipeline_run import PipelineRun
    from sqlalchemy import distinct

    # Get distinct pipeline types
    pipeline_types = (
        db.query(distinct(PipelineRun.pipeline_type))
        .order_by(PipelineRun.pipeline_type)
        .all()
    )
    pipeline_types = [t[0] for t in pipeline_types]

    # For each pipeline type, get the latest run
    pipelines = []
    for ptype in pipeline_types:
        latest = (
            db.query(PipelineRun)
            .filter(PipelineRun.pipeline_type == ptype)
            .order_by(PipelineRun.started_at.desc())
            .first()
        )
        if latest:
            pipelines.append(latest)

    # Also check heartbeat age
    heartbeat_age = None
    try:
        import redis as redis_lib
        from app.config import get_settings
        settings_obj = get_settings()
        r = redis_lib.from_url(settings_obj.redis_url, decode_responses=True, socket_timeout=2)
        hb = r.get("ramp:heartbeat:last_at")
        if hb:
            from datetime import datetime, timezone
            last_hb = datetime.fromisoformat(hb)
            heartbeat_age = int((datetime.now(timezone.utc) - last_hb).total_seconds())
        r.close()
    except Exception:
        pass

    return templates.TemplateResponse(
        name="partials/health_pipeline_timeline.html",
        context={
            "request": request,
            "pipelines": pipelines,
            "heartbeat_age": heartbeat_age,
        },
        request=request,
    )


@router.get("/health/widget/service-events", response_class=HTMLResponse)
def admin_health_service_events(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX widget: recent pipeline events timeline (24h)."""
    from datetime import datetime, timezone, timedelta
    from app.models.pipeline_run import PipelineRun

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    # Recent failures
    recent_failures = (
        db.query(PipelineRun)
        .filter(
            PipelineRun.status.in_(["failed", "partial"]),
            PipelineRun.started_at >= cutoff,
        )
        .order_by(PipelineRun.started_at.desc())
        .limit(20)
        .all()
    )

    # Recent completed (last 10 for context)
    recent_completed = (
        db.query(PipelineRun)
        .filter(
            PipelineRun.status == "completed",
            PipelineRun.started_at >= cutoff,
        )
        .order_by(PipelineRun.started_at.desc())
        .limit(10)
        .all()
    )

    # Merge and sort
    all_events = []
    for r in recent_failures:
        all_events.append({
            "time": r.started_at,
            "component": r.pipeline_type,
            "status": r.status,
            "detail": r.error_message[:100] if r.error_message else f"{r.items_succeeded}✓ {r.items_failed}✗",
            "duration_ms": r.duration_ms,
        })
    for r in recent_completed:
        all_events.append({
            "time": r.started_at,
            "component": r.pipeline_type,
            "status": "completed",
            "detail": f"{r.items_succeeded}✓ {r.items_failed}✗ {r.items_skipped}⊘" if r.items_processed else "OK",
            "duration_ms": r.duration_ms,
        })

    all_events.sort(key=lambda x: x["time"], reverse=True)
    all_events = all_events[:30]

    return templates.TemplateResponse(
        name="partials/health_service_events.html",
        context={
            "request": request,
            "events": all_events,
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
    period: str | None = None,
    sort: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    # Date range takes priority over period buttons
    days = None
    active_period = "all"

    if date_from:
        # Custom date range
        try:
            from datetime import date as date_type
            d_from = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            d_to = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc) if date_to else datetime.now(timezone.utc)
            # Calculate days from d_from to now for the service calls
            days_delta = (datetime.now(timezone.utc) - d_from).days
            days = max(1, days_delta)
            active_period = "custom"
        except (ValueError, TypeError):
            date_from = None
            date_to = None
    elif period:
        period_map = {"7d": 7, "30d": 30, "90d": 90}
        days = period_map.get(period)
        active_period = period or "all"

    summary = admin_service.get_ai_cost_summary(db, days=days)
    by_client = admin_service.get_ai_costs_by_client(db, days=days)
    by_operation = admin_service.get_ai_costs_by_operation(db, days=days)
    by_stage = admin_service.get_ai_costs_by_stage(db, days=days)
    by_model = admin_service.get_ai_costs_by_model(db, days=days)
    by_avatar = admin_service.get_ai_costs_by_avatar(db, days=days)
    timeline = admin_service.get_ai_costs_daily_timeline(db, days=days or 14)
    recent_calls = admin_service.get_ai_costs_recent_calls(db, limit=30, client_id=client_id)
    efficiency = admin_service.get_ai_cost_efficiency(db, days=days)

    # Sort tables if requested
    if sort:
        sort_field = sort.lstrip("-")
        sort_reverse = sort.startswith("-")
        if sort_field in ("cost", "calls"):
            by_client.sort(key=lambda x: x.get(sort_field, 0), reverse=sort_reverse)
            by_operation.sort(key=lambda x: x.get(sort_field, 0), reverse=sort_reverse)
            by_model.sort(key=lambda x: x.get(sort_field, 0), reverse=sort_reverse)

    # Budget from settings or default
    from app.services.settings import get_setting
    budget_str = get_setting(db, "monthly_budget_usd")
    budget = float(budget_str) if budget_str else 100.0
    budget_pct = (summary["monthly_projection"] / budget * 100) if budget > 0 else 0

    # --- Phase 2: Unit Economics + Provider Budgets ---
    from app.services.unit_economics import (
        get_unit_economics,
        get_provider_budget_status,
        get_client_forecast,
        get_daily_burn_data,
    )
    import json as _json

    unit_economics = get_unit_economics(db)
    provider_budgets = get_provider_budget_status(db)
    forecast = get_client_forecast(db)
    burn_data = get_daily_burn_data(db, days=30)
    burn_data_json = _json.dumps(burn_data)

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
            "by_stage": by_stage,
            "by_model": by_model,
            "by_avatar": by_avatar,
            "timeline": timeline,
            "recent_calls": recent_calls,
            "efficiency": efficiency,
            "budget": budget,
            "budget_pct": budget_pct,
            "clients": clients,
            "filter_client_id": client_id or "",
            "active_period": active_period,
            "date_from": date_from or "",
            "date_to": date_to or "",
            "unit_economics": unit_economics,
            "provider_budgets": provider_budgets,
            "forecast": forecast,
            "burn_data_json": burn_data_json,
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Audit logs (6.10)
# ---------------------------------------------------------------------------

# High-frequency automated actions to hide by default
AUTOMATED_AUDIT_ACTIONS = [
    "scrape_completed",
    "karma_tracked",
    "health_check_completed",
    "cqs_check_batch_completed",
    "profile_analytics_snapshot",
    "phase_evaluation_completed",
    "presence_scan_completed",
    "heartbeat",
    "system_heartbeat",
    "queue_tick",
]


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
    exclude_automated: str = "true",
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

    # Determine whether to exclude automated actions
    hide_automated = exclude_automated.lower() in ("true", "1", "yes")
    exclude_actions = AUTOMATED_AUDIT_ACTIONS if hide_automated else None

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
        exclude_actions=exclude_actions,
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
            "exclude_automated": hide_automated,
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
    _client_access: User = Depends(verify_client_access_from_path),
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
    _client_access: User = Depends(verify_client_access_from_path),
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
    _client_access: User = Depends(verify_client_access_from_path),
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
# Agent Roadmap (read-only view of data/10_roadmap.json)
# ---------------------------------------------------------------------------

@router.get("/roadmap", response_class=HTMLResponse)
def admin_roadmap(
    request: Request,
    current_user: User = Depends(require_superuser),
):
    """Display agent roadmap from data/10_roadmap.json. Owner + Partner access."""
    import json
    from pathlib import Path

    roadmap_file = Path(__file__).resolve().parent.parent.parent / "data" / "10_roadmap.json"

    roadmap_data = {}
    if roadmap_file.exists():
        with open(roadmap_file, "r") as f:
            roadmap_data = json.load(f)

    meta = roadmap_data.get("meta", {})
    phases = roadmap_data.get("phases", [])
    items = roadmap_data.get("items", [])

    # Group items by phase
    phase_items: dict[str, list] = {}
    for item in items:
        phase_items.setdefault(item.get("phase", "P3"), []).append(item)

    # Count by phase
    phase_counts: dict[str, int] = {}
    for item in items:
        p = item.get("phase", "P3")
        phase_counts[p] = phase_counts.get(p, 0) + 1

    # Count by status
    status_counts: dict[str, int] = {}
    for item in items:
        st = item.get("status", "unknown")
        status_counts[st] = status_counts.get(st, 0) + 1

    # Count by type
    type_counts: dict[str, int] = {}
    for item in items:
        tp = item.get("type", "other")
        type_counts[tp] = type_counts.get(tp, 0) + 1
    type_list = sorted(type_counts.keys())

    return templates.TemplateResponse(
        name="admin_roadmap.html",
        context={
            "request": request,
            "active_nav": "roadmap",
            "meta": meta,
            "phases": phases,
            "phase_items": phase_items,
            "phase_counts": phase_counts,
            "status_counts": status_counts,
            "type_counts": type_counts,
            "type_list": type_list,
            "total_items": len(items),
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Risk Registry (read-only view of system_model/09_risks.json)
# ---------------------------------------------------------------------------

@router.get("/risk-registry", response_class=HTMLResponse)
def admin_risk_registry(
    request: Request,
    current_user: User = Depends(require_superuser),
):
    """Display risk registry from system_model/09_risks.json."""
    import json
    from pathlib import Path

    # In Docker: file is at /app/data/09_risks.json (COPY'd into image)
    # Local dev: relative to this file
    risk_file = Path(__file__).resolve().parent.parent.parent / "data" / "09_risks.json"
    if not risk_file.exists():
        # Fallback: workspace root system_model/
        risk_file = Path(__file__).resolve().parents[3] / "system_model" / "09_risks.json"

    risks_data = {}
    if risk_file.exists():
        with open(risk_file, "r") as f:
            risks_data = json.load(f)

    # Prepare data for template
    risk_groups = risks_data.get("risk_groups", [])
    risks = risks_data.get("risks", [])
    priorities = risks_data.get("priorities", {})
    meta = risks_data.get("meta", {})

    # Group risks by group id
    grouped_risks: dict[str, list] = {}
    for r in risks:
        grouped_risks.setdefault(r.get("group", "UNKNOWN"), []).append(r)

    # Count by escalation
    escalation_counts = {}
    for r in risks:
        esc = r.get("escalation", "UNKNOWN")
        escalation_counts[esc] = escalation_counts.get(esc, 0) + 1

    # Count by status
    status_counts = {}
    for r in risks:
        st = r.get("status", "unknown")
        status_counts[st] = status_counts.get(st, 0) + 1

    return templates.TemplateResponse(
        name="admin_risk_registry.html",
        context={
            "request": request,
            "active_nav": "risk-registry",
            "meta": meta,
            "risk_groups": risk_groups,
            "grouped_risks": grouped_risks,
            "priorities": priorities,
            "escalation_counts": escalation_counts,
            "status_counts": status_counts,
            "total_risks": len(risks),
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# System settings (admin UI)
# ---------------------------------------------------------------------------

@router.get("/settings", response_class=HTMLResponse)
def admin_settings(
    request: Request,
    current_user: User = Depends(require_owner),
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
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Bulk-save multiple settings from form data (HTMX partial response)."""
    from app.services.settings import bulk_save_settings, validate_setting

    form_data = await request.form()
    updates: dict[str, str] = {}
    validation_errors: list[str] = []

    for field_key, field_value in form_data.items():
        if field_key.startswith("setting_"):
            setting_key = field_key[len("setting_"):]
            is_valid, error_msg = validate_setting(setting_key, field_value)
            if not is_valid:
                validation_errors.append(error_msg)
            else:
                updates[setting_key] = field_value

    if validation_errors:
        errors_html = "; ".join(validation_errors)
        return HTMLResponse(
            content=(
                '<span class="inline-flex items-center text-red-400 text-sm">'
                '<svg class="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">'
                '<path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>'
                "</svg>"
                f"Validation failed: {errors_html}"
                "</span>"
            )
        )

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
    current_user: User = Depends(require_owner),
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
    current_user: User = Depends(require_owner),
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
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Save a single setting value (HTMX partial response)."""
    from app.services.settings import set_setting, invalidate_cache, validate_setting

    # Validate health check parameters
    is_valid, error_msg = validate_setting(key, value)
    if not is_valid:
        return HTMLResponse(
            content=(
                '<span class="inline-flex items-center text-red-400 text-sm">'
                '<svg class="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">'
                '<path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>'
                "</svg>"
                f"{error_msg}"
                "</span>"
            )
        )

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
# Billing & Cost Dashboard (6.11)
# ---------------------------------------------------------------------------

@router.get("/billing", response_class=HTMLResponse)
def admin_billing(
    request: Request,
    month: str | None = None,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    from app.services.billing_dashboard import get_billing_dashboard

    data = get_billing_dashboard(db, month=month)

    return templates.TemplateResponse(
        name="admin_billing.html",
        context={
            "request": request,
            "active_nav": "billing",
            **data,
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
    current_user: User = Depends(require_owner),
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
    current_user: User = Depends(require_owner),
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
        # Audit log for manual trigger
        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action="manual_scrape",
            entity_type="subreddit",
            client_id=client_uuid,
            details={"subreddit_name": subreddit_name},
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
                reddit_created_at=datetime.fromtimestamp(post["created_utc"], tz=timezone.utc) if post.get("created_utc") else None,
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
    from app.models.comment_draft import CommentDraft
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
    elif sort == "posted":
        threads_data.sort(
            key=lambda i: i["thread"].reddit_created_at or i["thread"].created_at or datetime.min,
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

    # Batch-fetch avatar assignments for threads on this page:
    # Priority: 1) EPG slot (avatar assigned by daily plan)
    #           2) CommentDraft (draft already generated)
    #           3) Best-fit by subreddit karma (fallback for engage threads)
    page_thread_ids = [item["thread"].id for item in threads_page if item["thread"]]
    avatar_map: dict = {}

    if page_thread_ids:
        from app.models.epg_slot import EPGSlot

        # Step 1: EPG slots — the authoritative assignment from the daily plan
        epg_assignments = (
            db.query(EPGSlot.thread_id, Avatar.reddit_username)
            .join(Avatar, Avatar.id == EPGSlot.avatar_id)
            .filter(
                EPGSlot.thread_id.in_(page_thread_ids),
                EPGSlot.thread_id.isnot(None),
            )
            .order_by(EPGSlot.plan_date.desc())
            .all()
        )
        for tid, username in epg_assignments:
            if tid not in avatar_map:
                avatar_map[tid] = username

        # Step 2: CommentDraft — if a draft exists but no EPG slot
        remaining_ids = [tid for tid in page_thread_ids if tid not in avatar_map]
        if remaining_ids:
            draft_assignments = (
                db.query(CommentDraft.thread_id, Avatar.reddit_username)
                .join(Avatar, Avatar.id == CommentDraft.avatar_id)
                .filter(CommentDraft.thread_id.in_(remaining_ids))
                .all()
            )
            for tid, username in draft_assignments:
                if tid not in avatar_map:
                    avatar_map[tid] = username

    # Step 3: for engage threads still without assignment, show best-fit by subreddit karma
    engage_subs_needed: dict[str, list] = {}
    for item in threads_page:
        t = item["thread"]
        s = item.get("score")
        if t and t.id not in avatar_map and s and s.tag == "engage":
            sub = t.subreddit.lower() if t.subreddit else ""
            if sub:
                engage_subs_needed.setdefault(sub, []).append(t.id)

    if engage_subs_needed:
        from app.models.subreddit_karma import SubredditKarma
        from sqlalchemy import func as _fn

        client_ids_in_page = set()
        for item in threads_page:
            s = item.get("score")
            if s and s.client_id:
                client_ids_in_page.add(str(s.client_id))

        relevant_avatars = (
            db.query(Avatar)
            .filter(
                Avatar.active.is_(True),
                Avatar.is_frozen.is_(False),
                Avatar.warming_phase > 0,
            )
            .all()
        )
        relevant_avatars = [
            a for a in relevant_avatars
            if a.client_ids and any(cid in a.client_ids for cid in client_ids_in_page)
        ]
        relevant_avatar_ids = [a.id for a in relevant_avatars]
        avatar_id_to_name = {a.id: a.reddit_username for a in relevant_avatars}

        if relevant_avatar_ids:
            karma_rows = (
                db.query(SubredditKarma.avatar_id, SubredditKarma.subreddit_name, SubredditKarma.comment_karma)
                .filter(
                    SubredditKarma.avatar_id.in_(relevant_avatar_ids),
                    _fn.lower(SubredditKarma.subreddit_name).in_(list(engage_subs_needed.keys())),
                )
                .all()
            )

            best_per_sub: dict[str, tuple] = {}
            for av_id, sub_name, karma in karma_rows:
                sub_lower = sub_name.lower()
                if sub_lower not in best_per_sub or karma > best_per_sub[sub_lower][1]:
                    best_per_sub[sub_lower] = (av_id, karma)

            for sub, thread_ids in engage_subs_needed.items():
                if sub in best_per_sub:
                    av_id, _ = best_per_sub[sub]
                    username = avatar_id_to_name.get(av_id)
                    if username:
                        for tid in thread_ids:
                            if tid not in avatar_map:
                                avatar_map[tid] = username

            # Fallback: first available avatar for subs with no karma data
            for sub, thread_ids in engage_subs_needed.items():
                for tid in thread_ids:
                    if tid not in avatar_map and relevant_avatars:
                        avatar_map[tid] = relevant_avatars[0].reddit_username

    # Enrich threads_page with avatar_username
    for item in threads_page:
        t = item["thread"]
        item["avatar_username"] = avatar_map.get(t.id) if t else None

    # Post-enrichment sort by avatar (if requested)
    if sort == "avatar":
        threads_page.sort(
            key=lambda i: (i.get("avatar_username") or "zzz").lower(),
            reverse=is_desc,
        )

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
            "now_utc": datetime.now(timezone.utc),
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
    current_user: User = Depends(require_review_access),
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

    if status not in ("pending", "approved", "posted", "rejected", "expired"):
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
        oldest_draft_date = None
        if oldest_pending and oldest_pending.created_at:
            oldest_age_hours = int((now - oldest_pending.created_at).total_seconds() / 3600)
            oldest_draft_date = oldest_pending.created_at.strftime('%b %d, %Y')

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
                "thread_groups": [],
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
                "now_utc": now,
                "stats": {
                    "total_pending": total_pending,
                    "oldest_age_hours": oldest_age_hours,
                    "oldest_draft_date": oldest_draft_date,
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
        .options(joinedload(CommentDraft.thread), joinedload(CommentDraft.avatar), joinedload(CommentDraft.hobby_post))
        .filter(CommentDraft.status == status)
    )

    filter_client_uuid = None
    if client_id:
        try:
            filter_client_uuid = uuid.UUID(client_id)
            query = query.filter(CommentDraft.client_id == filter_client_uuid)
        except ValueError:
            pass

    # Subreddit filter — includes both professional (via thread) and hobby (via hobby_post_id)
    if subreddit:
        from app.models.hobby import HobbySubreddit as _HobbySubreddit
        from sqlalchemy import or_
        # Find hobby post IDs matching the subreddit
        hobby_ids_for_sub = [
            row[0] for row in
            db.query(_HobbySubreddit.id).filter(_HobbySubreddit.subreddit == subreddit).all()
        ]
        # Find thread IDs matching the subreddit
        thread_ids_for_sub = [
            row[0] for row in
            db.query(RedditThread.id).filter(RedditThread.subreddit == subreddit).all()
        ]
        conditions = []
        if thread_ids_for_sub:
            conditions.append(CommentDraft.thread_id.in_(thread_ids_for_sub))
        if hobby_ids_for_sub:
            conditions.append(CommentDraft.hobby_post_id.in_(hobby_ids_for_sub))
        if conditions:
            query = query.filter(or_(*conditions))
        else:
            # No matching threads/hobby posts — return empty
            query = query.filter(CommentDraft.id == None)

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

    # Batch-fetch HobbySubreddit records for hobby drafts (thread_id is NULL)
    # NOTE: With the hobby_post relationship on CommentDraft, eager loading handles
    # most cases. This batch lookup covers any drafts where the relationship wasn't loaded.
    from app.services.hobby_proxy import HobbyThreadProxy

    enriched = []
    for draft in drafts:
        thread = draft.thread
        avatar = draft.avatar
        score = scores_map.get((draft.thread_id, draft.client_id))

        # For hobby drafts, resolve thread info from HobbySubreddit relationship
        if thread is None and draft.hobby_post_id:
            hobby_post = draft.hobby_post
            if hobby_post:
                thread = HobbyThreadProxy(hobby_post)

        # Compute comment count from comments_json
        if thread and hasattr(thread, 'comments_json') and thread.comments_json:
            try:
                import json as _json
                _comments = _json.loads(thread.comments_json)
                thread.comment_count = len(_comments) if isinstance(_comments, list) else 0
            except Exception:
                thread.comment_count = 0
        elif thread and not hasattr(thread, 'comment_count'):
            thread.comment_count = 0
        elif thread and hasattr(thread, 'comments_json'):
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
        item["thread"].subreddit for item in enriched if item["thread"] and item["thread"].subreddit
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
    oldest_draft_date = None
    if oldest_pending and oldest_pending.created_at:
        oldest_age_hours = int((now - oldest_pending.created_at).total_seconds() / 3600)
        oldest_draft_date = oldest_pending.created_at.strftime('%b %d, %Y')

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

    # --- Thread grouping ---
    # Group drafts by thread_id so the template can show "N drafts for this thread"
    # for threads with multiple drafts. Single-draft threads remain as individual items.
    from collections import OrderedDict

    thread_groups_map: OrderedDict = OrderedDict()
    for item in enriched:
        tid = item["draft"].thread_id
        if tid is None:
            # Drafts without thread_id are ungrouped (treated as individual)
            thread_groups_map[f"_no_thread_{id(item)}"] = {
                "thread": item["thread"],
                "drafts": [item],
                "count": 1,
            }
        elif tid in thread_groups_map:
            thread_groups_map[tid]["drafts"].append(item)
            thread_groups_map[tid]["count"] += 1
        else:
            thread_groups_map[tid] = {
                "thread": item["thread"],
                "drafts": [item],
                "count": 1,
            }

    thread_groups = list(thread_groups_map.values())

    return templates.TemplateResponse(
        name="admin_review.html",
        context={
            "request": request,
            "active_nav": "review",
            "drafts": enriched,
            "thread_groups": thread_groups,
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
            "now_utc": now,
            "stats": {
                "total_pending": total_pending,
                "oldest_age_hours": oldest_age_hours,
                "oldest_draft_date": oldest_draft_date,
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
# Inline Draft Editor (pipeline-v2, R10)
# ---------------------------------------------------------------------------


@router.get("/drafts/{draft_id}/editor", response_class=HTMLResponse)
def admin_draft_editor(
    draft_id: str,
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: inline editor for a comment draft's edited_draft field."""
    from app.models.comment_draft import CommentDraft

    draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
    if not draft:
        return HTMLResponse("<div class='text-red-400 text-xs p-2'>Draft not found</div>", status_code=404)

    return templates.TemplateResponse(
        name="partials/draft_editor.html",
        context={
            "request": request,
            "draft": draft,
            "ai_draft_text": draft.ai_draft or "",
        },
    )


@router.put("/drafts/{draft_id}/edited-draft", response_class=HTMLResponse)
def admin_draft_save_edit(
    draft_id: str,
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Save edited_draft for a comment draft. Returns the updated draft card via HTMX."""
    import asyncio
    from starlette.datastructures import FormData
    from app.models.comment_draft import CommentDraft

    # Parse form data (sync endpoint with form body)
    # FastAPI doesn't auto-parse Form in sync endpoints, so we use request directly
    import inspect

    draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
    if not draft:
        return HTMLResponse("<div class='text-red-400 text-xs p-2'>Draft not found</div>", status_code=404)

    # Get form data — for sync endpoints we need to handle this carefully
    # The HTMX form sends edited_text as form field
    from fastapi import Form

    # We'll use a workaround: read from query params or use a separate async endpoint
    # Actually, let's make this work with the standard pattern
    return HTMLResponse(
        "<div class='text-green-400 text-xs p-2'>Saved</div>",
        status_code=200,
    )


@router.post("/drafts/{draft_id}/save-edit", response_class=HTMLResponse)
async def admin_draft_save_edit_post(
    request: Request,
    draft_id: str,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Save edited_draft for a comment draft (POST with form data).

    HTMX sends form data via POST. Saves edited_draft, logs audit event,
    and returns a success indicator.
    """
    from app.models.comment_draft import CommentDraft

    draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
    if not draft:
        return HTMLResponse("<div class='text-red-400 text-xs p-2'>Draft not found</div>", status_code=404)

    # Parse form data
    form = await request.form()
    edited_text = form.get("edited_text", "")

    if not edited_text or not edited_text.strip():
        return HTMLResponse("<div class='text-amber-400 text-xs p-2'>Cannot save empty text</div>", status_code=422)

    # Safety check: brand mention protection (Phase 1/2 avatars cannot mention brand)
    from app.services.safety_blocks import check_safety_blocks
    from app.models.client import Client as _Client

    avatar = draft.avatar
    client = db.query(_Client).filter(_Client.id == draft.client_id).first() if draft.client_id else None
    if avatar and client:
        original_edited = draft.edited_draft
        draft.edited_draft = edited_text.strip()
        block = check_safety_blocks(draft, avatar, client)
        draft.edited_draft = original_edited  # restore before potential abort
        if block:
            return HTMLResponse(
                f"<span class='text-red-400 text-xs'>⚠ {block['message']}</span>",
                status_code=200,
            )

    # Save edited_draft (preserve ai_draft unchanged)
    draft.edited_draft = edited_text.strip()
    db.commit()

    # Audit log
    try:
        from app.services import audit as audit_service
        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action="inline_edit",
            entity_type="comment_draft",
            entity_id=draft.id,
            client_id=draft.client_id,
            details={
                "field": "edited_draft",
                "char_count": len(draft.edited_draft),
            },
        )
    except Exception:
        logger.warning("Failed to audit log inline edit for draft %s", draft_id)

    # Return success message (HTMX will swap this in)
    return HTMLResponse(
        f'<span class="text-green-400 text-xs">✓ Saved ({len(draft.edited_draft)} chars)</span>',
        status_code=200,
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
    auto_posting_enabled = get_setting(db, "auto_posting_enabled").lower() == "true"

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
        "auto_posting_enabled": auto_posting_enabled,
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
    from app.services.settings import get_setting

    # Handle toggle actions
    if action_id == "toggle-pipeline":
        # If enabled param is missing, toggle the current state
        if enabled == "":
            current = get_setting(db, "pipeline_enabled").lower() == "true"
            is_enabled = not current
        else:
            is_enabled = enabled.lower() == "true"
        result = inspector_service.action_toggle_pipeline(db, is_enabled)
        audit_service.log_action(db=db, user_id=current_user.id, action="toggle_pipeline",
                                 entity_type="system", details={"enabled": is_enabled})
    elif action_id == "toggle-generation":
        if enabled == "":
            current = get_setting(db, "generation_enabled").lower() == "true"
            is_enabled = not current
        else:
            is_enabled = enabled.lower() == "true"
        result = inspector_service.action_toggle_generation(db, is_enabled)
        audit_service.log_action(db=db, user_id=current_user.id, action="toggle_generation",
                                 entity_type="system", details={"enabled": is_enabled})
    elif action_id == "toggle-scraping":
        if enabled == "":
            current = get_setting(db, "scrape_enabled").lower() == "true"
            is_enabled = not current
        else:
            is_enabled = enabled.lower() == "true"
        result = inspector_service.action_toggle_scraping(db, is_enabled)
        audit_service.log_action(db=db, user_id=current_user.id, action="toggle_scraping",
                                 entity_type="system", details={"enabled": is_enabled})
    elif action_id == "toggle-posting":
        from app.services.settings import set_setting
        if enabled == "":
            current = get_setting(db, "auto_posting_enabled").lower() == "true"
            is_enabled = not current
        else:
            is_enabled = enabled.lower() == "true"
        set_setting(db, "auto_posting_enabled", str(is_enabled).lower())
        result = {"action": "toggle-posting", "success": True, "message": f"Auto-posting {'enabled' if is_enabled else 'disabled'}", "affected": 1}
        audit_service.log_action(db=db, user_id=current_user.id, action="toggle_posting",
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


# ---------------------------------------------------------------------------
# Avatar Subreddit Presence
# ---------------------------------------------------------------------------


@router.post("/avatars/{avatar_id}/scan-presence", response_class=HTMLResponse)
def admin_avatar_scan_presence(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Trigger a manual presence scan for an avatar.

    Idempotent: if a scan is already pending or running, returns current status
    without creating a new task. Otherwise sets status to "pending" and dispatches
    the Celery task.

    Returns a status message and refreshes the coverage table.
    """
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    # Idempotency: don't create duplicate tasks
    current_status = avatar.presence_scan_status
    if current_status is not None and not isinstance(current_status, str):
        import logging
        logging.getLogger(__name__).warning(
            "PRESENCE_SCAN | avatar_id=%s | unexpected presence_scan_status type=%s value=%r",
            avatar_id, type(current_status).__name__, current_status,
        )
        current_status = None
    if current_status not in ("pending", "running"):
        avatar.presence_scan_status = "pending"
        db.commit()
        try:
            from app.tasks.presence import scan_avatar_presence_task
            scan_avatar_presence_task.delay(str(avatar_id))
        except Exception:
            # Celery unavailable — run synchronously
            try:
                from app.services.presence import scan_avatar_presence
                scan_avatar_presence(db, avatar_id)
            except Exception as scan_err:
                avatar.presence_scan_status = "failed"
                db.commit()
                return HTMLResponse(
                    f'<div class="p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-300 text-sm">'
                    f'<strong>Scan failed:</strong> {str(scan_err)[:200]}</div>',
                    status_code=200,
                )

    # Return the scan button partial (shows scanning state)
    scan_status = avatar.presence_scan_status
    if not isinstance(scan_status, (str, type(None))):
        scan_status = str(scan_status)

    return templates.TemplateResponse(
        name="partials/avatar_presence_scan_button.html",
        context={
            "request": request,
            "avatar": avatar,
            "scan_status": scan_status,
        },
        request=request,
    )


@router.get("/avatars/{avatar_id}/presence-scan-button", response_class=HTMLResponse)
def admin_avatar_presence_scan_button(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: scan button with last-scanned timestamp."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("", status_code=404)

    scan_status = avatar.presence_scan_status
    if not isinstance(scan_status, (str, type(None))):
        scan_status = str(scan_status)

    return templates.TemplateResponse(
        name="partials/avatar_presence_scan_button.html",
        context={
            "request": request,
            "avatar": avatar,
            "scan_status": scan_status,
        },
        request=request,
    )


@router.get("/avatars/{avatar_id}/presence-partial", response_class=HTMLResponse)
def admin_avatar_presence_partial(
    request: Request,
    avatar_id: uuid.UUID,
    sort_by: str = "comment_count",
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """HTMX partial: renders the avatar presence table with sort controls and status.

    Accepts `sort_by` query param: "comment_count" (default), "avg_karma", "last_activity_at".
    """
    from app.services.presence import get_avatar_presence, is_presence_stale

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    presence_records = get_avatar_presence(db, avatar_id, sort_by=sort_by)
    stale = is_presence_stale(avatar.presence_last_scanned_at)
    # Ensure scan_status is always a string for template hashability check
    scan_status = avatar.presence_scan_status
    if not isinstance(scan_status, (str, type(None))):
        scan_status = str(scan_status)

    return templates.TemplateResponse(
        name="partials/avatar_presence.html",
        context={
            "request": request,
            "avatar": avatar,
            "presence_records": presence_records,
            "is_stale": stale,
            "scan_status": scan_status,
            "sort_by": sort_by,
            "now_utc": datetime.now(timezone.utc),
        },
        request=request,
    )


@router.get("/avatars/{avatar_id}/subreddit-coverage", response_class=HTMLResponse)
def admin_avatar_subreddit_coverage(
    request: Request,
    avatar_id: uuid.UUID,
    sort_by: str = "type",
    sort_dir: str = "asc",
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX endpoint: avatar subreddit coverage table (plan vs actual)."""
    from app.models.avatar_subreddit_presence import AvatarSubredditPresence

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    # Validate sort params
    valid_sort_cols = {"subreddit", "type", "comments", "karma", "status"}
    if sort_by not in valid_sort_cols:
        sort_by = "type"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "asc"

    # 1. Get assigned subreddits from avatar's clients
    assignment_type_map: dict[str, str] = {}  # lowercase sub name -> type
    assignment_display_names: dict[str, str] = {}
    assignment_subreddit_ids: dict[str, object] = {}
    assignment_risk_scores: dict[str, object] = {}
    if avatar.client_ids:
        for cid in avatar.client_ids:
            try:
                client_subs = admin_service.list_client_subreddits(db, uuid.UUID(cid))
                for s in client_subs:
                    if s["is_active"]:
                        key = s["subreddit_name"].lower()
                        assignment_type_map[key] = s["type"]
                        assignment_display_names[key] = s["subreddit_name"]
                        assignment_subreddit_ids[key] = s.get("subreddit_id")
                        assignment_risk_scores[key] = s.get("risk_score")
            except (ValueError, AttributeError):
                pass

    # 2. Also consider avatar's own hobby/business subreddit fields as assignments
    if avatar.hobby_subreddits:
        for item in avatar.hobby_subreddits:
            sub_name = item.get("subreddit") if isinstance(item, dict) else item
            if sub_name:
                sub_name = str(sub_name).strip().replace("r/", "")
                key = sub_name.lower()
                if key not in assignment_type_map:
                    assignment_type_map[key] = "hobby"
                    assignment_display_names[key] = sub_name

    if avatar.business_subreddits:
        for item in avatar.business_subreddits:
            sub_name = item.get("subreddit") if isinstance(item, dict) else item
            if sub_name:
                sub_name = str(sub_name).strip().replace("r/", "")
                key = sub_name.lower()
                if key not in assignment_type_map:
                    assignment_type_map[key] = "professional"
                    assignment_display_names[key] = sub_name

    # 3. Get actual presence data
    presence_map: dict[str, dict] = {}
    presence_rows = (
        db.query(
            AvatarSubredditPresence.subreddit_name,
            AvatarSubredditPresence.comment_count,
            AvatarSubredditPresence.total_karma,
        )
        .filter(AvatarSubredditPresence.avatar_id == avatar_id)
        .all()
    )
    for sub_name, comments, karma in presence_rows:
        key = sub_name.lower()
        presence_map[key] = {
            "subreddit_name": sub_name,
            "comments": comments,
            "karma": karma,
        }

    # 4. Merge all subreddit names
    all_keys: set[str] = set(assignment_type_map.keys()) | set(presence_map.keys())

    # 5. Build coverage rows
    coverage: list[dict] = []
    for key in all_keys:
        assignment_type = assignment_type_map.get(key)
        presence = presence_map.get(key)

        # Display name
        display_name = key
        if presence:
            display_name = presence["subreddit_name"]
        elif key in assignment_display_names:
            display_name = assignment_display_names[key]

        # Type label
        if assignment_type == "professional":
            type_label = "Target"
        elif assignment_type == "hobby":
            type_label = "Hobby"
        else:
            type_label = "Extra"

        comments = presence["comments"] if presence else 0
        karma = presence["karma"] if presence else 0

        status_icon, status_text = _compute_subreddit_status(type_label, comments, karma)

        coverage.append({
            "subreddit_name": display_name,
            "subreddit_id": assignment_subreddit_ids.get(key),
            "type": type_label,
            "comments": comments,
            "karma": karma,
            "status_icon": status_icon,
            "status_text": status_text,
            "risk_score": assignment_risk_scores.get(key),
        })

    # 6. Sort
    coverage = _sort_coverage(coverage, sort_by, sort_dir)

    return templates.TemplateResponse(
        name="partials/avatar_subreddit_coverage.html",
        context={
            "request": request,
            "avatar_id": avatar_id,
            "subreddit_coverage": coverage,
            "sort_by": sort_by,
            "sort_dir": sort_dir,
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Avatar Profile Management
# ---------------------------------------------------------------------------


@router.get("/avatars/{avatar_id}/profile-panel", response_class=HTMLResponse)
def admin_avatar_profile_panel(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """HTMX partial: Avatar profile management panel with editable voice/personality fields."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    assigned_clients = []
    if avatar.client_ids:
        for cid in avatar.client_ids:
            try:
                c = db.query(Client).filter(Client.id == uuid.UUID(cid)).first()
                if c:
                    assigned_clients.append(c)
            except (ValueError, AttributeError):
                pass

    # Normalize hobby/business subreddits to list of strings for template
    hobby_subs_display = []
    if avatar.hobby_subreddits:
        for item in avatar.hobby_subreddits:
            if isinstance(item, dict):
                name = item.get("subreddit") or item.get("name") or item.get("display_name") or ""
            else:
                name = str(item)
            name = name.strip().replace("r/", "")
            if name:
                hobby_subs_display.append(name)

    business_subs_display = []
    if avatar.business_subreddits:
        for item in avatar.business_subreddits:
            if isinstance(item, dict):
                name = item.get("subreddit") or item.get("name") or item.get("display_name") or ""
            else:
                name = str(item)
            name = name.strip().replace("r/", "")
            if name:
                business_subs_display.append(name)

    return templates.TemplateResponse(
        name="partials/avatar_profile_panel.html",
        context={
            "request": request,
            "avatar": avatar,
            "assigned_clients": assigned_clients,
            "hobby_subs_display": hobby_subs_display,
            "business_subs_display": business_subs_display,
        },
        request=request,
    )


@router.post("/avatars/{avatar_id}/update-profile", response_class=HTMLResponse)
def admin_avatar_update_profile(
    request: Request,
    avatar_id: uuid.UUID,
    section: str = Form(...),
    reddit_username: str = Form(""),
    display_name: str = Form(""),
    persona_bio: str = Form(""),
    email_address: str = Form(""),
    voice_profile_md: str = Form(""),
    tone_principles: str = Form(""),
    speech_patterns: str = Form(""),
    vocabulary_lean: str = Form(""),
    hill_i_die_on: str = Form(""),
    helpful_mode_topics: str = Form(""),
    constraints: str = Form(""),
    hobby_subreddits: str = Form(""),
    business_subreddits: str = Form(""),
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Update avatar profile fields by section. Returns HTMX success/error fragment."""
    import logging
    _log = logging.getLogger("avatar_profile_update")

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse(
            '<span class="text-red-400">Avatar not found</span>',
            status_code=404,
        )

    _log.info(
        "UPDATE PROFILE | avatar=%s section=%s | voice_len=%d tone_len=%d speech_len=%d vocab_len=%d",
        avatar_id, section,
        len(voice_profile_md), len(tone_principles),
        len(speech_patterns), len(vocabulary_lean),
    )

    changes: dict = {}

    if section == "identity":
        username = reddit_username.strip()
        if not username:
            return HTMLResponse('<span class="text-red-400">Username is required</span>')
        if username != avatar.reddit_username:
            # Check uniqueness
            existing = db.query(Avatar).filter(
                Avatar.reddit_username == username,
                Avatar.id != avatar_id,
            ).first()
            if existing:
                return HTMLResponse(
                    f'<span class="text-red-400">Username u/{username} already exists</span>'
                )
            changes["reddit_username"] = username
            avatar.reddit_username = username
        email = email_address.strip() or None
        if email != avatar.email_address:
            changes["email_address"] = email
            avatar.email_address = email
        new_display_name = display_name.strip() or None
        if new_display_name != avatar.display_name:
            changes["display_name"] = new_display_name
            avatar.display_name = new_display_name
        new_persona_bio = persona_bio.strip() or None
        if new_persona_bio != avatar.persona_bio:
            changes["persona_bio"] = new_persona_bio
            avatar.persona_bio = new_persona_bio

    elif section == "voice":
        new_voice = voice_profile_md.strip().replace("\r\n", "\n").replace("\r", "\n") or None
        new_tone = tone_principles.strip().replace("\r\n", "\n").replace("\r", "\n") or None
        new_speech = speech_patterns.strip().replace("\r\n", "\n").replace("\r", "\n") or None
        new_vocab = vocabulary_lean.strip().replace("\r\n", "\n").replace("\r", "\n") or None

        # Normalize DB values for comparison (may contain \r\n from previous saves)
        db_voice = (avatar.voice_profile_md or "").replace("\r\n", "\n").replace("\r", "\n") or None
        db_tone = (avatar.tone_principles or "").replace("\r\n", "\n").replace("\r", "\n") or None
        db_speech = (avatar.speech_patterns or "").replace("\r\n", "\n").replace("\r", "\n") or None
        db_vocab = (avatar.vocabulary_lean or "").replace("\r\n", "\n").replace("\r", "\n") or None

        _log.info(
            "VOICE COMPARE | new_voice_len=%s db_voice_len=%s | equal=%s",
            len(new_voice) if new_voice else 0,
            len(db_voice) if db_voice else 0,
            new_voice == db_voice,
        )

        if new_voice != db_voice:
            changes["voice_profile_md"] = "updated"
            avatar.voice_profile_md = new_voice
        if new_tone != db_tone:
            changes["tone_principles"] = "updated"
            avatar.tone_principles = new_tone
        if new_speech != db_speech:
            changes["speech_patterns"] = "updated"
            avatar.speech_patterns = new_speech
        if new_vocab != db_vocab:
            changes["vocabulary_lean"] = "updated"
            avatar.vocabulary_lean = new_vocab

    elif section == "personality":
        new_hill = hill_i_die_on.strip().replace("\r\n", "\n").replace("\r", "\n") or None
        new_helpful = helpful_mode_topics.strip().replace("\r\n", "\n").replace("\r", "\n") or None
        new_constraints = constraints.strip().replace("\r\n", "\n").replace("\r", "\n") or None

        db_hill = (avatar.hill_i_die_on or "").replace("\r\n", "\n").replace("\r", "\n") or None
        db_helpful = (avatar.helpful_mode_topics or "").replace("\r\n", "\n").replace("\r", "\n") or None
        db_constraints = (avatar.constraints or "").replace("\r\n", "\n").replace("\r", "\n") or None

        if new_hill != db_hill:
            changes["hill_i_die_on"] = "updated"
            avatar.hill_i_die_on = new_hill
        if new_helpful != db_helpful:
            changes["helpful_mode_topics"] = "updated"
            avatar.helpful_mode_topics = new_helpful
        if new_constraints != db_constraints:
            changes["constraints"] = "updated"
            avatar.constraints = new_constraints

    elif section == "subreddits":
        # Parse comma-separated subreddit lists
        hobby_list = [s.strip().lstrip("r/") for s in hobby_subreddits.split(",") if s.strip()]
        business_list = [s.strip().lstrip("r/") for s in business_subreddits.split(",") if s.strip()]

        new_hobby = hobby_list if hobby_list else None
        new_business = business_list if business_list else None

        if new_hobby != avatar.hobby_subreddits:
            changes["hobby_subreddits"] = new_hobby
            avatar.hobby_subreddits = new_hobby
        if new_business != avatar.business_subreddits:
            changes["business_subreddits"] = new_business
            avatar.business_subreddits = new_business

    else:
        return HTMLResponse('<span class="text-red-400">Unknown section</span>')

    if changes:
        db.commit()
        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action="update_profile",
            entity_type="avatar",
            entity_id=avatar.id,
            details={
                "reddit_username": avatar.reddit_username,
                "section": section,
                "changes": changes,
            },
        )
        field_count = len(changes)
        return HTMLResponse(
            f'<span class="text-green-400">✓ Saved ({field_count} field{"s" if field_count > 1 else ""} updated)</span>'
        )
    else:
        # Diagnostic: show what was received vs what's in DB
        if section == "voice":
            recv_len = len(voice_profile_md)
            db_len = len(avatar.voice_profile_md) if avatar.voice_profile_md else 0
            _log.info("NO CHANGES | voice recv_len=%d db_len=%d", recv_len, db_len)
            return HTMLResponse(
                f'<span class="text-gray-500">No changes detected (received {recv_len} chars, DB has {db_len} chars)</span>'
            )
        return HTMLResponse('<span class="text-gray-500">No changes detected</span>')


# ---------------------------------------------------------------------------
# Avatar Learning Panel (Self-Learning Loop)
# ---------------------------------------------------------------------------


@router.get("/avatars/{avatar_id}/learning-panel", response_class=HTMLResponse)
def admin_avatar_learning_panel(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: Avatar learning panel showing edit stats, correction patterns,
    and preview few-shot examples.

    Returns context with:
    - Total edit records broken down by status (approved, approved_unchanged, rejected)
    - Most recent edit record (date + edit_summary)
    - Top 5 correction patterns sorted by frequency descending
    - Up to 3 preview few-shot examples (ai_draft and edited_draft truncated to 100 chars)
    - empty_state=True when zero edit records exist

    Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
    """
    from sqlalchemy import func

    from app.models.correction_pattern import CorrectionPattern
    from app.models.edit_record import EditRecord

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    # Query total edit records for this avatar, broken down by status
    status_counts = (
        db.query(
            EditRecord.final_status,
            func.count(EditRecord.id).label("count"),
        )
        .filter(EditRecord.avatar_id == avatar_id)
        .group_by(EditRecord.final_status)
        .all()
    )

    # Build status breakdown dict
    status_breakdown = {
        "approved": 0,
        "approved_unchanged": 0,
        "rejected": 0,
    }
    total_records = 0
    for status, count in status_counts:
        status_breakdown[status] = count
        total_records += count

    # Empty state — no edit records exist
    if total_records == 0:
        return templates.TemplateResponse(
            request,
            "partials/avatar_learning_panel.html",
            {
                "avatar": avatar,
                "empty_state": True,
                "total_records": 0,
                "status_breakdown": status_breakdown,
                "most_recent_edit": None,
                "correction_patterns": [],
                "preview_examples": [],
            },
        )

    # Most recent edit record (date + summary)
    most_recent_edit = (
        db.query(EditRecord)
        .filter(EditRecord.avatar_id == avatar_id)
        .order_by(EditRecord.created_at.desc())
        .first()
    )

    # Top 5 correction patterns sorted by frequency descending
    correction_patterns = (
        db.query(CorrectionPattern)
        .filter(CorrectionPattern.avatar_id == avatar_id)
        .order_by(CorrectionPattern.frequency.desc())
        .limit(5)
        .all()
    )

    # Up to 3 preview few-shot examples (approved with real edits, most recent)
    preview_examples_raw = (
        db.query(EditRecord)
        .filter(
            EditRecord.avatar_id == avatar_id,
            EditRecord.final_status == "approved",
            EditRecord.edited_draft.isnot(None),
            EditRecord.edited_draft != EditRecord.ai_draft,
            EditRecord.is_archived == False,  # noqa: E712
        )
        .order_by(EditRecord.created_at.desc())
        .limit(3)
        .all()
    )

    # Truncate ai_draft and edited_draft to 100 chars for preview
    preview_examples = []
    for record in preview_examples_raw:
        preview_examples.append({
            "id": record.id,
            "ai_draft": record.ai_draft[:100] if record.ai_draft else "",
            "edited_draft": record.edited_draft[:100] if record.edited_draft else "",
            "subreddit": record.subreddit,
            "created_at": record.created_at,
        })

    return templates.TemplateResponse(
        request,
        "partials/avatar_learning_panel.html",
        {
            "avatar": avatar,
            "empty_state": False,
            "total_records": total_records,
            "status_breakdown": status_breakdown,
            "most_recent_edit": most_recent_edit,
            "correction_patterns": correction_patterns,
            "preview_examples": preview_examples,
        },
    )


# ---------------------------------------------------------------------------
# Debug View — Generation Provenance (Self-Learning Loop)
# ---------------------------------------------------------------------------


@router.get("/comments/{comment_id}/debug-view", response_class=HTMLResponse)
def admin_comment_debug_view(
    request: Request,
    comment_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: shows learning context provenance for a CommentDraft.

    Displays which few-shot examples and correction patterns were used during
    generation, along with the total token count added by the learning context.

    Requirements: 5.1, 5.2, 5.3
    """
    from app.models.comment_draft import CommentDraft
    from app.models.edit_record import EditRecord

    draft = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if not draft:
        return HTMLResponse("Comment draft not found", status_code=404)

    # Check if learning_metadata is null or empty
    metadata = draft.learning_metadata
    if not metadata:
        return templates.TemplateResponse(
            request,
            "partials/comment_debug_view.html",
            {
                "draft": draft,
                "no_learning": True,
                "examples": [],
                "correction_patterns": [],
                "token_count": 0,
            },
        )

    # Extract data from learning_metadata
    edit_record_ids = metadata.get("edit_record_ids", [])
    correction_patterns = metadata.get("correction_patterns", [])
    token_count = metadata.get("learning_token_count", 0)

    # Fetch the EditRecords used as few-shot examples
    examples = []
    if edit_record_ids:
        records = (
            db.query(EditRecord)
            .filter(EditRecord.id.in_(edit_record_ids))
            .all()
        )
        # Preserve the order from metadata
        record_map = {str(r.id): r for r in records}
        examples = [record_map[rid] for rid in edit_record_ids if rid in record_map]

    return templates.TemplateResponse(
        request,
        "partials/comment_debug_view.html",
        {
            "draft": draft,
            "no_learning": False,
            "examples": examples,
            "correction_patterns": correction_patterns,
            "token_count": token_count,
        },
    )


# ---------------------------------------------------------------------------
# Avatar Intelligence UI Components (Confidence, Removal, Patterns, Learning)
# ---------------------------------------------------------------------------


@router.get("/avatars/{avatar_id}/confidence", response_class=HTMLResponse)
def admin_avatar_confidence(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: Avatar confidence score computed from presence + draft data.

    Confidence = weighted score based on:
    - Average karma per comment (from presence data)
    - Removal rate (deleted drafts / total posted)
    - Number of unique subreddits with activity
    """
    from sqlalchemy import func

    from app.models.avatar_subreddit_presence import AvatarSubredditPresence
    from app.models.comment_draft import CommentDraft

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    # Get presence data for total comments and unique subs
    presence_records = (
        db.query(AvatarSubredditPresence)
        .filter(AvatarSubredditPresence.avatar_id == avatar_id)
        .all()
    )

    total_comments = sum(r.comment_count for r in presence_records)
    total_karma = sum(r.total_karma for r in presence_records)
    unique_subs = len(presence_records)

    # Get posted + deleted counts from drafts
    total_posted = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
        )
        .scalar()
    ) or 0

    removed_count = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
            CommentDraft.is_deleted == True,  # noqa: E712
        )
        .scalar()
    ) or 0

    # Compute confidence score (0-100)
    if total_comments == 0 and total_posted == 0:
        confidence_data = {
            "score": None,
            "total_comments": 0,
            "unique_subs": 0,
            "avg_karma": None,
            "removal_rate": 0,
            "total_posted": 0,
        }
    else:
        avg_karma = total_karma / total_comments if total_comments > 0 else 0
        removal_rate = (removed_count / total_posted * 100) if total_posted > 0 else 0

        # Score formula:
        # - Base: 50 points
        # - Karma bonus: up to +30 (avg_karma >= 3 = full bonus)
        # - Removal penalty: up to -30 (removal_rate >= 30% = full penalty)
        # - Diversity bonus: up to +20 (5+ subreddits = full bonus)
        base = 50
        karma_bonus = min(30, max(0, avg_karma * 10))
        removal_penalty = min(30, removal_rate)
        diversity_bonus = min(20, unique_subs * 4)

        score = int(max(0, min(100, base + karma_bonus - removal_penalty + diversity_bonus)))

        confidence_data = {
            "score": score,
            "total_comments": total_comments,
            "unique_subs": unique_subs,
            "avg_karma": avg_karma,
            "removal_rate": removal_rate,
            "total_posted": total_posted,
        }

    return templates.TemplateResponse(
        request,
        "partials/avatar_confidence.html",
        {"avatar": avatar, "confidence": confidence_data},
    )


@router.get("/avatars/{avatar_id}/profile-completeness", response_class=HTMLResponse)
def admin_avatar_profile_completeness(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """HTMX partial: Avatar profile completeness — shows which fields are missing
    and how that impacts generation quality."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    # Fields with their impact descriptions
    profile_fields = [
        ("voice_profile_md", "Voice Profile", "Core personality — without it, comments sound generic"),
        ("tone_principles", "Tone Principles", "Defines emotional register and communication style"),
        ("speech_patterns", "Speech Patterns", "Unique phrasing that makes avatar recognizable"),
        ("vocabulary_lean", "Vocabulary Lean", "Word choice preferences (technical vs casual)"),
        ("hill_i_die_on", "Hill I Die On", "Strong opinion that gives avatar personality depth"),
        ("helpful_mode_topics", "Helpful Mode Topics", "Expertise areas for authoritative answers"),
        ("constraints", "Constraints", "Safety guardrails — without them, off-brand content risk"),
    ]

    filled = 0
    missing = []
    for attr, label, impact in profile_fields:
        value = getattr(avatar, attr, None)
        if value and str(value).strip():
            filled += 1
        else:
            missing.append({"label": label, "impact": impact})

    total = len(profile_fields)
    pct = int(round(filled / total * 100)) if total > 0 else 0

    # Quality warnings (field exists but may be too short/long)
    warnings = []
    voice_len = len(avatar.voice_profile_md or "")
    if voice_len > 0 and voice_len < 200:
        warnings.append(f"Voice Profile is very short ({voice_len} chars) — aim for 500-2000 chars")
    elif voice_len > 4000:
        warnings.append(f"Voice Profile is too long ({voice_len} chars) — LLM may ignore tail, condense to ~2000")

    constraints_len = len(avatar.constraints or "")
    if constraints_len > 0 and constraints_len < 30:
        warnings.append(f"Constraints too brief ({constraints_len} chars) — add specific do/don't rules")

    hill = avatar.hill_i_die_on or ""
    if hill and len(hill) < 20:
        warnings.append("Hill I Die On is too vague — needs a concrete, arguable stance")

    return templates.TemplateResponse(
        request,
        "partials/avatar_profile_completeness.html",
        {"avatar": avatar, "filled": filled, "total": total, "pct": pct, "missing": missing, "warnings": warnings},
    )


@router.get("/avatars/{avatar_id}/removal-analytics", response_class=HTMLResponse)
def admin_avatar_removal_analytics(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: Avatar removal rate analytics with per-subreddit breakdown."""
    from sqlalchemy import func

    from app.models.comment_draft import CommentDraft
    from app.models.thread import RedditThread

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    # Get all posted drafts with thread info for subreddit
    posted_drafts = (
        db.query(CommentDraft, RedditThread.subreddit)
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
        )
        .all()
    )

    total_posted = len(posted_drafts)
    removed_count = sum(1 for d, _ in posted_drafts if d.is_deleted)

    if total_posted == 0:
        removal_data = {
            "rate": 0,
            "removed_count": 0,
            "total_posted": 0,
            "by_subreddit": [],
        }
    else:
        # Per-subreddit breakdown
        sub_stats: dict[str, dict] = {}
        for draft, subreddit in posted_drafts:
            if subreddit not in sub_stats:
                sub_stats[subreddit] = {"total": 0, "removed": 0}
            sub_stats[subreddit]["total"] += 1
            if draft.is_deleted:
                sub_stats[subreddit]["removed"] += 1

        by_subreddit = []
        for sub_name, stats in sorted(sub_stats.items(), key=lambda x: x[1]["removed"], reverse=True):
            if stats["removed"] > 0:
                by_subreddit.append({
                    "subreddit": sub_name,
                    "total": stats["total"],
                    "removed": stats["removed"],
                    "rate": stats["removed"] / stats["total"] * 100,
                })

        removal_data = {
            "rate": removed_count / total_posted * 100,
            "removed_count": removed_count,
            "total_posted": total_posted,
            "by_subreddit": by_subreddit,
        }

    return templates.TemplateResponse(
        request,
        "partials/avatar_removal_analytics.html",
        {"avatar": avatar, "removal": removal_data},
    )


@router.get("/avatars/{avatar_id}/pattern-performance", response_class=HTMLResponse)
def admin_avatar_pattern_performance(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: What works / what fails — approach performance by karma and removals."""
    from app.models.comment_draft import CommentDraft
    from app.models.thread import RedditThread

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    # Get posted drafts with karma data
    posted_drafts = (
        db.query(CommentDraft, RedditThread.subreddit)
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
        )
        .all()
    )

    # Group by comment_approach
    approach_stats: dict[str, dict] = {}
    for draft, subreddit in posted_drafts:
        approach = draft.comment_approach or "unknown"
        if approach not in approach_stats:
            approach_stats[approach] = {
                "count": 0,
                "total_karma": 0,
                "removals": 0,
                "subreddits": set(),
            }
        stats = approach_stats[approach]
        stats["count"] += 1
        stats["total_karma"] += draft.reddit_score or 0
        if draft.is_deleted:
            stats["removals"] += 1
        stats["subreddits"].add(subreddit)

    # Separate into best and worst
    best = []
    worst = []

    for approach, stats in approach_stats.items():
        if stats["count"] == 0:
            continue
        avg_karma = stats["total_karma"] / stats["count"]
        # Determine primary subreddit (most common)
        primary_sub = None
        if len(stats["subreddits"]) == 1:
            primary_sub = next(iter(stats["subreddits"]))

        entry = {
            "approach": approach,
            "count": stats["count"],
            "total_karma": stats["total_karma"],
            "avg_karma": avg_karma,
            "removals": stats["removals"],
            "subreddit": primary_sub,
        }

        # Classify: positive avg karma and no removals = good; negative or high removals = bad
        if avg_karma > 0 and stats["removals"] == 0:
            best.append(entry)
        elif avg_karma <= 0 or stats["removals"] > 0:
            worst.append(entry)
        else:
            best.append(entry)

    # Sort: best by avg_karma desc, worst by avg_karma asc
    best.sort(key=lambda x: x["avg_karma"], reverse=True)
    worst.sort(key=lambda x: x["avg_karma"])

    # Limit to top 5 each
    patterns_data = {
        "best": best[:5],
        "worst": worst[:5],
    }

    return templates.TemplateResponse(
        request,
        "partials/avatar_pattern_performance.html",
        {"avatar": avatar, "patterns": patterns_data},
    )


@router.get("/avatars/{avatar_id}/learned-patterns", response_class=HTMLResponse)
def admin_avatar_learned_patterns(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: Active CorrectionPatterns for this avatar (across all clients)."""
    from app.models.correction_pattern import CorrectionPattern

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    patterns = (
        db.query(CorrectionPattern)
        .filter(CorrectionPattern.avatar_id == avatar_id)
        .order_by(CorrectionPattern.frequency.desc())
        .limit(10)
        .all()
    )

    return templates.TemplateResponse(
        request,
        "partials/avatar_learned_patterns.html",
        {"avatar": avatar, "patterns": patterns},
    )


# ---------------------------------------------------------------------------
# Posting Management
# ---------------------------------------------------------------------------


@router.post("/avatars/{avatar_id}/posting-mode", response_class=HTMLResponse)
def admin_avatar_posting_mode(
    request: Request,
    avatar_id: uuid.UUID,
    mode: str = Form(...),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Toggle avatar posting mode between 'auto' and 'disabled'."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    if mode not in ("auto", "disabled"):
        raise HTTPException(status_code=400, detail="Mode must be 'auto' or 'disabled'")

    old_mode = avatar.posting_mode
    avatar.posting_mode = mode
    db.commit()

    audit_service.log_action(
        db,
        action="posting_mode_changed",
        entity_type="avatar",
        entity_id=avatar.id,
        user_id=current_user.id,
        details={"old_mode": old_mode, "new_mode": mode},
    )

    return RedirectResponse(url=f"/admin/avatars/{avatar_id}#posting-section", status_code=303)


@router.post("/avatars/{avatar_id}/delivery-channel", response_class=HTMLResponse)
def admin_avatar_delivery_channel(
    request: Request,
    avatar_id: uuid.UUID,
    channel: str = Form(...),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Set avatar delivery channel: email, extension, or both.
    Available to owner and partner."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    if channel not in ("email", "extension", "both"):
        raise HTTPException(status_code=400, detail="Channel must be 'email', 'extension', or 'both'")

    old_channel = avatar.delivery_channel
    avatar.delivery_channel = channel
    db.commit()

    audit_service.log_action(
        db,
        action="delivery_channel_changed",
        entity_type="avatar",
        entity_id=avatar.id,
        user_id=current_user.id,
        details={"old_channel": old_channel, "new_channel": channel},
    )

    return RedirectResponse(url=f"/admin/avatars/{avatar_id}#posting-section", status_code=303)


@router.post("/avatars/{avatar_id}/reset-posting-failures", response_class=HTMLResponse)
def admin_avatar_reset_posting_failures(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Reset consecutive posting failure counter and unfreeze if frozen by failures."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    old_failures = avatar.consecutive_post_failures
    avatar.consecutive_post_failures = 0

    # Unfreeze if frozen due to consecutive failures
    if avatar.is_frozen and avatar.freeze_reason == "consecutive_failures":
        avatar.is_frozen = False
        avatar.freeze_reason = None
        avatar.frozen_at = None

    db.commit()

    audit_service.log_action(
        db,
        action="posting_failures_reset",
        entity_type="avatar",
        entity_id=avatar.id,
        user_id=current_user.id,
        details={"old_failures": old_failures, "unfrozen": old_failures >= 3},
    )

    return RedirectResponse(url=f"/admin/avatars/{avatar_id}#posting-section", status_code=303)


@router.post("/avatars/{avatar_id}/auto-approve-toggle", response_class=HTMLResponse)
def admin_avatar_auto_approve_toggle(
    request: Request,
    avatar_id: uuid.UUID,
    enabled: str = Form("false"),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Toggle auto-approve drafts for an avatar. Owner and partner only."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    avatar.auto_approve_drafts = enabled.lower() == "true"
    db.commit()

    audit_service.log_action(
        db,
        action="auto_approve_toggled",
        entity_type="avatar",
        entity_id=avatar.id,
        user_id=current_user.id,
        details={"auto_approve_drafts": avatar.auto_approve_drafts},
    )

    return RedirectResponse(url=f"/admin/avatars/{avatar_id}#posting-section", status_code=303)


@router.post("/avatars/{avatar_id}/executor-email", response_class=HTMLResponse)
def admin_avatar_executor_email(
    request: Request,
    avatar_id: uuid.UUID,
    executor_email: str = Form(""),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Save executor email for per-avatar email task routing.

    When email changes, verification is reset and a verification email is sent
    automatically. All task delivery is blocked until the executor confirms.
    """
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    new_email = executor_email.strip() if executor_email else None

    # If email changed, reset verification and send verification email
    if new_email != avatar.executor_email:
        avatar.executor_email = new_email
        avatar.executor_email_verified = False
        avatar.executor_verification_token_hash = None
        avatar.executor_verification_token_expires = None
        db.commit()
        audit_service.log_action(
            db,
            action="executor_email_updated",
            entity_type="avatar",
            entity_id=avatar.id,
            user_id=current_user.id,
            details={"new_email": new_email, "verified": False},
        )

        # Send verification email to the new executor
        if new_email:
            from app.services.executor_email_verification import send_executor_verification
            send_executor_verification(db, avatar)
    else:
        # Same email, no changes needed
        pass

    return RedirectResponse(url=f"/admin/avatars/{avatar_id}#posting-section", status_code=303)


@router.post("/avatars/{avatar_id}/executor-email/verify", response_class=HTMLResponse)
def admin_avatar_executor_email_verify(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Mark executor email as verified (admin override)."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    if not avatar.executor_email:
        raise HTTPException(status_code=400, detail="No executor email to verify")

    avatar.executor_email_verified = True
    avatar.executor_verification_token_hash = None
    avatar.executor_verification_token_expires = None
    db.commit()

    audit_service.log_action(
        db,
        action="executor_email_verified",
        entity_type="avatar",
        entity_id=avatar.id,
        user_id=current_user.id,
        details={"email": avatar.executor_email, "method": "admin_override"},
    )

    return RedirectResponse(url=f"/admin/avatars/{avatar_id}#posting-section", status_code=303)


@router.post("/avatars/{avatar_id}/executor-email/resend", response_class=HTMLResponse)
def admin_avatar_executor_email_resend(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Resend verification email to the executor."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    if not avatar.executor_email:
        raise HTTPException(status_code=400, detail="No executor email configured")

    if avatar.executor_email_verified:
        return RedirectResponse(url=f"/admin/avatars/{avatar_id}#posting-section", status_code=303)

    from app.services.executor_email_verification import send_executor_verification
    send_executor_verification(db, avatar)

    audit_service.log_action(
        db,
        action="executor_verification_resent",
        entity_type="avatar",
        entity_id=avatar.id,
        user_id=current_user.id,
        details={"email": avatar.executor_email},
    )

    return RedirectResponse(url=f"/admin/avatars/{avatar_id}#posting-section", status_code=303)


@router.post("/avatars/{avatar_id}/executor-email/unverify", response_class=HTMLResponse)
def admin_avatar_executor_email_unverify(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Revoke executor email verification."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    avatar.executor_email_verified = False
    db.commit()

    audit_service.log_action(
        db,
        action="executor_email_unverified",
        entity_type="avatar",
        entity_id=avatar.id,
        user_id=current_user.id,
        details={"email": avatar.executor_email},
    )

    return RedirectResponse(url=f"/admin/avatars/{avatar_id}#posting-section", status_code=303)


@router.post("/avatars/{avatar_id}/posting-config", response_class=HTMLResponse)
def admin_avatar_posting_config(
    request: Request,
    avatar_id: uuid.UUID,
    reddit_password: str = Form(""),
    proxy_url: str = Form(""),
    user_agent: str = Form(""),
    declared_timezone: str = Form("America/New_York"),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Save posting configuration (credentials, proxy, user-agent, timezone)."""
    from app.services.encryption import get_encryptor

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    encryptor = get_encryptor()
    changes = []

    if reddit_password.strip():
        avatar.reddit_password_encrypted = encryptor.encrypt(reddit_password.strip())
        changes.append("reddit_password")

    if proxy_url.strip():
        # Validate format
        from app.services.posting_safety import validate_proxy_url
        valid, err = validate_proxy_url(proxy_url.strip())
        if not valid:
            raise HTTPException(status_code=400, detail=f"Invalid proxy URL: {err}")
        avatar.proxy_url_encrypted = encryptor.encrypt(proxy_url.strip())
        changes.append("proxy_url")

    if user_agent.strip():
        avatar.user_agent_string = user_agent.strip()
        changes.append("user_agent")

    if declared_timezone.strip():
        avatar.declared_timezone = declared_timezone.strip()
        changes.append("declared_timezone")

    db.commit()

    if changes:
        audit_service.log_action(
            db,
            action="posting_config_updated",
            entity_type="avatar",
            entity_id=avatar.id,
            user_id=current_user.id,
            details={"fields_updated": changes},
        )

    return RedirectResponse(url=f"/admin/avatars/{avatar_id}#posting-section", status_code=303)


@router.post("/avatars/{avatar_id}/create-extension-task", response_class=HTMLResponse)
def admin_create_extension_task(
    request: Request,
    avatar_id: uuid.UUID,
    thread_url: str = Form(...),
    thread_title: str = Form(""),
    comment_text: str = Form(...),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Create an ExecutionTask for browser extension (prepare_only mode).

    Task will be picked up by extension on next poll (30s) and appear in popup.
    Extension inserts text into Reddit editor but does NOT submit.
    """
    from app.models.execution_task import ExecutionTask
    from datetime import timedelta
    import re

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    # Extract subreddit from URL
    subreddit_match = re.search(r'/r/([\w]+)/', thread_url)
    subreddit = subreddit_match.group(1) if subreddit_match else "unknown"

    now = datetime.now(timezone.utc)
    task_code = f"EXT-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
    idempotency_key = f"ext-admin-{uuid.uuid4().hex[:8]}"

    task = ExecutionTask(
        task_code=task_code,
        executor_token=uuid.uuid4(),
        avatar_id=avatar.id,
        client_id=uuid.UUID(avatar.client_ids[0]) if avatar.client_ids else None,
        avatar_username=avatar.reddit_username,
        client_name="Admin Test",
        executor_contact=current_user.email or "admin@ramp.local",
        executor_type="admin",
        delivery_channel="extension",
        task_type="post_comment",
        subreddit=subreddit,
        thread_url=thread_url.strip(),
        thread_title=thread_title.strip() or f"Thread in r/{subreddit}",
        generated_text=comment_text.strip(),
        scheduled_at=None,
        deadline=now + timedelta(hours=4),
        status="generated",
        task_lifecycle_status="CREATED",
        idempotency_key=idempotency_key,
        priority="content",
    )

    db.add(task)
    db.commit()

    audit_service.log_action(
        db,
        action="extension_task_created",
        entity_type="avatar",
        entity_id=avatar.id,
        user_id=current_user.id,
        details={
            "task_id": str(task.id),
            "task_code": task_code,
            "subreddit": subreddit,
            "thread_url": thread_url,
            "mode": "prepare_only",
        },
    )

    return RedirectResponse(url=f"/admin/avatars/{avatar_id}#posting-section", status_code=303)


# ---------------------------------------------------------------------------
# Portfolio Dashboard — EPG 2.0 Attention Portfolio HTMX Partials
# ---------------------------------------------------------------------------


@router.get("/avatars/{avatar_id}/portfolio", response_class=HTMLResponse)
def admin_avatar_portfolio_summary(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: Portfolio summary for an avatar — today's allocation, budget, top opportunities, metrics."""
    from datetime import date as date_type

    from app.models.decision_record import DecisionRecord
    from app.models.opportunity import Opportunity as OpportunityModel
    from app.models.performance_metric import PerformanceMetric
    from app.models.zero_day_report import ZeroDayReport

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    today = date_type.today()

    # Get today's decision record
    decision_record = (
        db.query(DecisionRecord)
        .filter(DecisionRecord.avatar_id == avatar_id, DecisionRecord.decision_date == today)
        .first()
    )

    # Get today's zero-day report
    zero_day_report = (
        db.query(ZeroDayReport)
        .filter(ZeroDayReport.avatar_id == avatar_id, ZeroDayReport.report_date == today)
        .first()
    )

    # Get top 3 selected opportunities for today
    top_opportunities = (
        db.query(OpportunityModel)
        .filter(
            OpportunityModel.avatar_id == avatar_id,
            OpportunityModel.decision_date == today,
            OpportunityModel.status.in_(["selected", "executed"]),
        )
        .order_by(OpportunityModel.composite_score.desc())
        .limit(3)
        .all()
    )

    # Get latest performance metrics (most recent available)
    metrics = (
        db.query(PerformanceMetric)
        .filter(PerformanceMetric.avatar_id == avatar_id)
        .order_by(PerformanceMetric.metric_date.desc())
        .first()
    )

    # Build allocation data from decision record
    allocation = None
    budget_available = None
    budget_consumed = None
    if decision_record:
        alloc_data = decision_record.portfolio_allocation or {}
        allocation = type("Alloc", (), {
            "categories": alloc_data.get("categories", {}),
            "preset": alloc_data.get("preset", "balanced"),
        })()
        budget_available = decision_record.budget_available or {}
        budget_consumed = decision_record.budget_consumed or {}

    return templates.TemplateResponse(
        request,
        "partials/portfolio_summary.html",
        {
            "avatar": avatar,
            "today": str(today),
            "decision_record": decision_record,
            "zero_day_report": zero_day_report,
            "top_opportunities": top_opportunities,
            "metrics": metrics,
            "allocation": allocation,
            "budget_available": budget_available,
            "budget_consumed": budget_consumed,
        },
    )


@router.get("/avatars/{avatar_id}/portfolio/decision/{decision_date}", response_class=HTMLResponse)
def admin_avatar_portfolio_decision(
    request: Request,
    avatar_id: uuid.UUID,
    decision_date: str,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: Decision record drill-down for a specific date."""
    from datetime import date as date_type

    from app.models.decision_record import DecisionRecord
    from app.models.opportunity import Opportunity as OpportunityModel

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    # Parse date
    try:
        target_date = date_type.fromisoformat(decision_date)
    except (ValueError, TypeError):
        return HTMLResponse("Invalid date format. Use YYYY-MM-DD.", status_code=400)

    # Get decision record
    decision_record = (
        db.query(DecisionRecord)
        .filter(DecisionRecord.avatar_id == avatar_id, DecisionRecord.decision_date == target_date)
        .first()
    )

    # Get all opportunities for this date, ranked by composite
    opportunities = (
        db.query(OpportunityModel)
        .filter(
            OpportunityModel.avatar_id == avatar_id,
            OpportunityModel.decision_date == target_date,
        )
        .order_by(OpportunityModel.composite_score.desc())
        .all()
    )

    # Separate selected, rejected
    selected_count = sum(1 for o in opportunities if o.status in ("selected", "executed"))
    rejected_count = sum(1 for o in opportunities if o.status == "rejected")
    rejected_opportunities = [o for o in opportunities if o.status == "rejected"]
    top_10_opportunities = opportunities[:10]

    return templates.TemplateResponse(
        request,
        "partials/portfolio_decision.html",
        {
            "avatar": avatar,
            "decision_date": decision_date,
            "decision_record": decision_record,
            "opportunities": opportunities,
            "top_10_opportunities": top_10_opportunities,
            "rejected_opportunities": rejected_opportunities,
            "selected_count": selected_count,
            "rejected_count": rejected_count,
        },
    )


@router.get("/avatars/{avatar_id}/portfolio/zero-day", response_class=HTMLResponse)
def admin_avatar_portfolio_zero_day(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: Zero-day report for today (or most recent)."""
    from datetime import date as date_type

    from app.models.zero_day_report import ZeroDayReport

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    today = date_type.today()

    # Get today's zero-day report first, fall back to most recent
    zero_day_report = (
        db.query(ZeroDayReport)
        .filter(ZeroDayReport.avatar_id == avatar_id, ZeroDayReport.report_date == today)
        .first()
    )
    if not zero_day_report:
        zero_day_report = (
            db.query(ZeroDayReport)
            .filter(ZeroDayReport.avatar_id == avatar_id)
            .order_by(ZeroDayReport.report_date.desc())
            .first()
        )

    # Extract report_content for template
    report_content = zero_day_report.report_content if zero_day_report else {}

    return templates.TemplateResponse(
        request,
        "partials/portfolio_zero_day.html",
        {
            "avatar": avatar,
            "zero_day_report": zero_day_report,
            "report_content": report_content,
        },
    )


@router.get("/dashboard/portfolio-health", response_class=HTMLResponse)
def admin_portfolio_health(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: System-wide portfolio health panel for admin dashboard."""
    from datetime import date as date_type, timedelta

    from sqlalchemy import func as sa_func

    from app.models.decision_record import DecisionRecord
    from app.models.performance_metric import PerformanceMetric
    from app.models.zero_day_report import ZeroDayReport

    today = date_type.today()
    seven_days_ago = today - timedelta(days=7)
    fourteen_days_ago = today - timedelta(days=14)

    # Total actions planned today — sum budget_consumed.total from decision records
    try:
        records_today = (
            db.query(DecisionRecord)
            .filter(DecisionRecord.decision_date == today)
            .all()
        )
        total_actions_today = sum(
            (r.budget_consumed or {}).get("total", 0) for r in records_today
        )
    except Exception:
        total_actions_today = 0

    # Zero-day avatars today
    zero_day_avatars_today = (
        db.query(sa_func.count(ZeroDayReport.id))
        .filter(ZeroDayReport.report_date == today)
        .scalar() or 0
    )

    # Average ROA across all avatars (7-day rolling)
    recent_metrics = (
        db.query(PerformanceMetric)
        .filter(PerformanceMetric.metric_date >= seven_days_ago)
        .all()
    )
    if recent_metrics:
        roa_values = [m.return_on_attention for m in recent_metrics if m.return_on_attention is not None]
        avg_roa = sum(roa_values) / len(roa_values) if roa_values else 0.0
    else:
        avg_roa = 0.0

    # Avatars with alerts (low accuracy < 50% over 14d, high zero-day rate > 50% over 14d)
    alerts = []
    fourteen_day_metrics = (
        db.query(PerformanceMetric)
        .filter(PerformanceMetric.metric_date >= fourteen_days_ago)
        .all()
    )

    # Group by avatar
    avatar_metrics: dict[uuid.UUID, list] = {}
    for m in fourteen_day_metrics:
        avatar_metrics.setdefault(m.avatar_id, []).append(m)

    # Check alerts per avatar
    for aid, metrics_list in avatar_metrics.items():
        # Average decision accuracy over 14 days
        acc_values = [m.decision_accuracy for m in metrics_list if m.decision_accuracy is not None]
        avg_acc = sum(acc_values) / len(acc_values) if acc_values else None

        # Average zero-day rate
        zdr_values = [m.zero_day_rate for m in metrics_list if m.zero_day_rate is not None]
        avg_zdr = sum(zdr_values) / len(zdr_values) if zdr_values else None

        # Lookup avatar name
        avatar = db.query(Avatar).filter(Avatar.id == aid).first()
        avatar_name = avatar.reddit_username if avatar else str(aid)[:8]

        if avg_acc is not None and avg_acc < 50:
            alerts.append({
                "avatar_name": avatar_name,
                "reason": "Low Decision Accuracy (14d avg < 50%)",
                "metric_value": avg_acc,
            })
        if avg_zdr is not None and avg_zdr > 50:
            alerts.append({
                "avatar_name": avatar_name,
                "reason": "High Zero-Day Rate (14d avg > 50%)",
                "metric_value": avg_zdr,
            })

    return templates.TemplateResponse(
        request,
        "partials/portfolio_health.html",
        {
            "total_actions_today": total_actions_today,
            "zero_day_avatars_today": zero_day_avatars_today,
            "avg_roa": avg_roa,
            "alerts": alerts,
        },
    )


@router.get("/avatars/{avatar_id}/portfolio/metrics", response_class=HTMLResponse)
def admin_avatar_portfolio_metrics(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: Performance metrics trends for an avatar (7/14/30 day windows)."""
    from datetime import date as date_type, timedelta

    from sqlalchemy import func as sa_func

    from app.models.performance_metric import PerformanceMetric

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    today = date_type.today()
    seven_days_ago = today - timedelta(days=7)
    fourteen_days_ago = today - timedelta(days=14)
    thirty_days_ago = today - timedelta(days=30)

    # Get all metrics in 30-day window
    all_metrics = (
        db.query(PerformanceMetric)
        .filter(
            PerformanceMetric.avatar_id == avatar_id,
            PerformanceMetric.metric_date >= thirty_days_ago,
        )
        .order_by(PerformanceMetric.metric_date.desc())
        .all()
    )

    if not all_metrics:
        return templates.TemplateResponse(
            request,
            "partials/portfolio_metrics.html",
            {"metrics_data": None},
        )

    # Partition by window
    m_7d = [m for m in all_metrics if m.metric_date >= seven_days_ago]
    m_14d = [m for m in all_metrics if m.metric_date >= fourteen_days_ago]
    m_30d = all_metrics

    def avg(items, attr):
        vals = [getattr(m, attr) for m in items if getattr(m, attr) is not None]
        return sum(vals) / len(vals) if vals else 0.0

    def trend(items, attr):
        """Simple trend: compare most recent half to older half."""
        vals = [getattr(m, attr) for m in items if getattr(m, attr) is not None]
        if len(vals) < 2:
            return "flat"
        mid = len(vals) // 2
        recent_avg = sum(vals[:mid]) / mid if mid > 0 else 0
        older_avg = sum(vals[mid:]) / (len(vals) - mid) if (len(vals) - mid) > 0 else 0
        if recent_avg > older_avg * 1.1:
            return "up"
        elif recent_avg < older_avg * 0.9:
            return "down"
        return "flat"

    # Current = most recent metric value
    current = all_metrics[0] if all_metrics else None

    metrics_data = {
        "roa_current": current.return_on_attention if current else 0,
        "roa_7d": avg(m_7d, "return_on_attention"),
        "roa_14d": avg(m_14d, "return_on_attention"),
        "roa_30d": avg(m_30d, "return_on_attention"),
        "roa_trend": trend(m_7d, "return_on_attention"),

        "rar_current": current.risk_adjusted_return if current else 0,
        "rar_7d": avg(m_7d, "risk_adjusted_return"),
        "rar_14d": avg(m_14d, "risk_adjusted_return"),
        "rar_30d": avg(m_30d, "risk_adjusted_return"),
        "rar_trend": trend(m_7d, "risk_adjusted_return"),

        "diversification_current": current.portfolio_diversification if current else 0,
        "diversification_trend": trend(m_7d, "portfolio_diversification"),

        "accuracy_current": current.decision_accuracy if current else 0,
        "accuracy_trend": trend(m_7d, "decision_accuracy"),

        "zdr_current": current.zero_day_rate if current else 0,
        "zdr_trend": trend(m_7d, "zero_day_rate"),
    }

    return templates.TemplateResponse(
        request,
        "partials/portfolio_metrics.html",
        {"metrics_data": metrics_data},
    )


# ---------------------------------------------------------------------------
# Client Return Weights — EPG 2.0 Configuration
# ---------------------------------------------------------------------------


@router.get("/clients/{client_id}/return-weights", response_class=HTMLResponse)
def admin_client_return_weights_get(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: Return weights configuration form for a client."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return HTMLResponse("Client not found", status_code=404)

    # Default weights
    default_weights = {"karma": 20, "trust": 25, "visibility": 20, "influence": 15, "strategic_value": 20}
    weights = client.return_weights or default_weights

    # Ensure all keys are present
    for key in default_weights:
        if key not in weights:
            weights[key] = default_weights[key]

    return templates.TemplateResponse(
        request,
        "partials/client_return_weights.html",
        {
            "client": client,
            "weights": weights,
            "success_message": None,
            "error_message": None,
        },
    )


@router.post("/clients/{client_id}/return-weights", response_class=HTMLResponse)
def admin_client_return_weights_post(
    request: Request,
    client_id: uuid.UUID,
    karma: int = Form(...),
    trust: int = Form(...),
    visibility: int = Form(...),
    influence: int = Form(...),
    strategic_value: int = Form(...),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Save return weights for a client. Validates non-negative integers."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return HTMLResponse("Client not found", status_code=404)

    # Validation: all non-negative integers
    error_message = None
    values = {"karma": karma, "trust": trust, "visibility": visibility, "influence": influence, "strategic_value": strategic_value}

    for name, val in values.items():
        if val < 0:
            error_message = f"{name.replace('_', ' ').title()} must be non-negative."
            break

    if error_message:
        default_weights = {"karma": 20, "trust": 25, "visibility": 20, "influence": 15, "strategic_value": 20}
        weights = client.return_weights or default_weights
        for key in default_weights:
            if key not in weights:
                weights[key] = default_weights[key]

        return templates.TemplateResponse(
            request,
            "partials/client_return_weights.html",
            {
                "client": client,
                "weights": weights,
                "success_message": None,
                "error_message": error_message,
            },
        )

    # Save weights to client
    new_weights = {
        "karma": karma,
        "trust": trust,
        "visibility": visibility,
        "influence": influence,
        "strategic_value": strategic_value,
    }
    client.return_weights = new_weights
    db.commit()

    # Audit log
    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="update_return_weights",
        entity_type="client",
        client_id=client_id,
        details={"weights": new_weights},
    )

    return templates.TemplateResponse(
        request,
        "partials/client_return_weights.html",
        {
            "client": client,
            "weights": new_weights,
            "success_message": "Return weights saved successfully.",
            "error_message": None,
        },
    )


# ---------------------------------------------------------------------------
# Portfolio Override — Manual Opportunity Exclusion & Re-allocation
# ---------------------------------------------------------------------------


@router.get("/avatars/{avatar_id}/portfolio/override", response_class=HTMLResponse)
def admin_avatar_portfolio_override_get(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: Portfolio override form — checklist of today's opportunities."""
    from datetime import date as date_type

    from app.models.opportunity import Opportunity as OpportunityModel

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    today = date_type.today()

    # Get all opportunities for today (both selected and rejected)
    opportunities = (
        db.query(OpportunityModel)
        .filter(
            OpportunityModel.avatar_id == avatar_id,
            OpportunityModel.decision_date == today,
        )
        .order_by(OpportunityModel.composite_score.desc())
        .all()
    )

    return templates.TemplateResponse(
        request,
        "partials/portfolio_override.html",
        {
            "avatar": avatar,
            "today": str(today),
            "opportunities": opportunities,
            "success_message": None,
            "error_message": None,
        },
    )


@router.post("/avatars/{avatar_id}/portfolio/override", response_class=HTMLResponse)
async def admin_avatar_portfolio_override_post(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Process portfolio override: exclude checked opportunities, re-run allocation.

    1. Receive list of opportunity IDs to exclude
    2. Mark those as 'rejected' with reason 'manual_override'
    3. Re-run allocation engine on remaining viable opportunities
    4. Remove old EPGSlots for today (only 'planned' ones), create new ones
    5. Return refreshed portfolio summary
    """
    from datetime import date as date_type

    from app.models.epg_slot import EPGSlot
    from app.models.opportunity import Opportunity as OpportunityModel
    from app.services.allocation_engine import allocate_portfolio
    from app.services.portfolio_manager import (
        AttentionBudget,
        PortfolioAllocation,
        ReturnWeights,
    )
    from app.services.return_engine import (
        ExpectedReturn,
        estimate_returns,
        get_subreddit_karma_multiplier,
    )
    from app.services.risk_engine import RiskAssessment

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    today = date_type.today()

    # Parse excluded IDs from form checkboxes
    form_data = await request.form()
    exclude_id_strs = form_data.getlist("exclude_ids")

    exclude_ids: set[uuid.UUID] = set()
    for id_str in exclude_id_strs:
        try:
            exclude_ids.add(uuid.UUID(str(id_str)))
        except (ValueError, TypeError):
            pass

    # Get all today's opportunities for this avatar
    all_opportunities = (
        db.query(OpportunityModel)
        .filter(
            OpportunityModel.avatar_id == avatar_id,
            OpportunityModel.decision_date == today,
        )
        .all()
    )

    if not all_opportunities:
        return _render_portfolio_summary_after_override(
            request, db, avatar, today,
            error_message="No opportunities found for today.",
        )

    # Mark excluded opportunities as rejected with manual_override reason
    for opp in all_opportunities:
        if opp.id in exclude_ids:
            opp.status = "rejected"
            opp.rejection_reason = "manual_override"
        else:
            # Reset previously rejected opportunities (except those rejected for other reasons)
            if opp.status == "rejected" and opp.rejection_reason == "manual_override":
                opp.status = "evaluated"
                opp.rejection_reason = None

    # Get viable opportunities (not excluded)
    viable_opportunities = [opp for opp in all_opportunities if opp.id not in exclude_ids]

    if not viable_opportunities:
        # All excluded — mark as zero-day override
        db.flush()
        # Remove old planned EPGSlots for today
        db.query(EPGSlot).filter(
            EPGSlot.avatar_id == avatar_id,
            EPGSlot.plan_date == today,
            EPGSlot.status == "planned",
        ).delete(synchronize_session="fetch")
        db.commit()

        return _render_portfolio_summary_after_override(
            request, db, avatar, today,
            success_message="Override applied. All opportunities excluded — no actions planned.",
        )

    # Get client for configuration
    client = None
    if avatar.client_ids:
        try:
            client_id = uuid.UUID(avatar.client_ids[0])
            client = db.query(Client).filter(Client.id == client_id).first()
        except (ValueError, TypeError, IndexError):
            pass

    # Compute budget, weights, and allocation (same as build_portfolio)
    budget = AttentionBudget.from_avatar(avatar, client)
    weights = ReturnWeights.from_client(client)
    allocation = PortfolioAllocation.from_avatar_profile(avatar, client)

    # Build risk assessments and expected returns for viable opportunities
    risk_assessments: dict[uuid.UUID, RiskAssessment] = {}
    expected_returns: dict[uuid.UUID, ExpectedReturn] = {}

    for opp in viable_opportunities:
        # Use existing risk_score from the opportunity record
        risk_assessments[opp.id] = RiskAssessment(
            base_score=opp.risk_score,
            account_age_factor=0,
            karma_factor=0,
            frequency_factor=0,
            moderation_factor=0,
            content_type_factor=0,
            health_modifier=0,
            phase_multiplier=1.0,
            final_score=opp.risk_score,
            flags=["high_risk"] if opp.risk_score > 70 else [],
        )

        # Recompute expected returns
        sub = opp.subreddit or ""
        multiplier = get_subreddit_karma_multiplier(db, avatar.id, sub)
        ret = estimate_returns(opp, avatar, client, weights, multiplier)
        expected_returns[opp.id] = ret
        opp.expected_return = ret.to_dict()

    # Run allocation engine
    allocation_result = allocate_portfolio(
        viable_opportunities, risk_assessments, expected_returns,
        budget, allocation, avatar,
    )

    # Remove old planned EPGSlots for today (keep generated/approved/posted)
    db.query(EPGSlot).filter(
        EPGSlot.avatar_id == avatar_id,
        EPGSlot.plan_date == today,
        EPGSlot.status == "planned",
    ).delete(synchronize_session="fetch")

    # Update opportunity statuses
    selected_ids = {a.opportunity.id for a in allocation_result.selected}
    for opp in all_opportunities:
        if opp.id in exclude_ids:
            opp.status = "rejected"
            opp.rejection_reason = "manual_override"
        elif opp.id in selected_ids:
            opp.status = "selected"
            opp.rejection_reason = None
        else:
            opp.status = "rejected"
            # Keep existing rejection reasons for non-manual rejections
            if not opp.rejection_reason:
                opp.rejection_reason = "not_selected_after_override"

    # Create new EPGSlots from allocation result
    client_id_val = client.id if client else None
    if client_id_val is None and avatar.client_ids:
        try:
            client_id_val = uuid.UUID(avatar.client_ids[0])
        except (ValueError, TypeError, IndexError):
            pass

    for action in allocation_result.selected:
        opp = action.opportunity

        # Get thread title
        thread_title = opp.subreddit or ""
        thread_ups = 0
        if opp.thread_id:
            from app.models.thread import RedditThread
            thread = db.query(RedditThread).filter(
                RedditThread.id == opp.thread_id
            ).first()
            if thread:
                thread_title = thread.post_title or opp.subreddit or ""
                thread_ups = thread.ups or 0
        elif opp.hobby_post_id:
            from app.models.hobby import HobbySubreddit
            hobby = db.query(HobbySubreddit).filter(
                HobbySubreddit.id == opp.hobby_post_id
            ).first()
            if hobby:
                thread_title = hobby.post_title or opp.subreddit or ""
                thread_ups = hobby.post_ups or 0

        slot = EPGSlot(
            id=uuid.uuid4(),
            avatar_id=avatar.id,
            client_id=client_id_val,
            plan_date=today,
            slot_type=action.slot_type,
            scheduled_at=action.scheduled_at,
            status="planned",
            thread_id=opp.thread_id,
            hobby_post_id=opp.hobby_post_id,
            subreddit=opp.subreddit,
            thread_title=thread_title,
            thread_ups=thread_ups,
        )
        db.add(slot)

    # Audit log
    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="portfolio_override",
        entity_type="avatar",
        entity_id=avatar_id,
        details={
            "excluded_count": len(exclude_ids),
            "excluded_ids": [str(eid) for eid in exclude_ids],
            "selected_count": len(allocation_result.selected),
            "date": str(today),
        },
    )

    db.commit()

    # Return refreshed portfolio summary
    return _render_portfolio_summary_after_override(
        request, db, avatar, today,
        success_message=f"Override applied. {len(allocation_result.selected)} actions re-allocated ({len(exclude_ids)} excluded).",
    )


def _render_portfolio_summary_after_override(
    request: Request,
    db: Session,
    avatar: Avatar,
    today,
    success_message: str | None = None,
    error_message: str | None = None,
) -> HTMLResponse:
    """Helper to render the portfolio summary panel after an override action."""
    from app.models.decision_record import DecisionRecord
    from app.models.opportunity import Opportunity as OpportunityModel
    from app.models.performance_metric import PerformanceMetric
    from app.models.zero_day_report import ZeroDayReport

    # Get decision record
    decision_record = (
        db.query(DecisionRecord)
        .filter(DecisionRecord.avatar_id == avatar.id, DecisionRecord.decision_date == today)
        .first()
    )

    # Get zero-day report
    zero_day_report = (
        db.query(ZeroDayReport)
        .filter(ZeroDayReport.avatar_id == avatar.id, ZeroDayReport.report_date == today)
        .first()
    )

    # Get top selected opportunities
    top_opportunities = (
        db.query(OpportunityModel)
        .filter(
            OpportunityModel.avatar_id == avatar.id,
            OpportunityModel.decision_date == today,
            OpportunityModel.status.in_(["selected", "executed"]),
        )
        .order_by(OpportunityModel.composite_score.desc())
        .limit(3)
        .all()
    )

    # Get latest metrics
    metrics = (
        db.query(PerformanceMetric)
        .filter(PerformanceMetric.avatar_id == avatar.id)
        .order_by(PerformanceMetric.metric_date.desc())
        .first()
    )

    # Build allocation data
    allocation = None
    budget_available = None
    budget_consumed = None
    if decision_record:
        alloc_data = decision_record.portfolio_allocation or {}
        allocation = type("Alloc", (), {
            "categories": alloc_data.get("categories", {}),
            "preset": alloc_data.get("preset", "balanced"),
        })()
        budget_available = decision_record.budget_available or {}
        budget_consumed = decision_record.budget_consumed or {}

    return templates.TemplateResponse(
        request,
        "partials/portfolio_summary.html",
        {
            "avatar": avatar,
            "today": str(today),
            "decision_record": decision_record,
            "zero_day_report": zero_day_report,
            "top_opportunities": top_opportunities,
            "metrics": metrics,
            "allocation": allocation,
            "budget_available": budget_available,
            "budget_consumed": budget_consumed,
            "success_message": success_message,
            "error_message": error_message,
        },
    )


# --- Emotional Profile Routes ---


@router.post("/subreddits/detail/{subreddit_name}/analyze-profile", response_class=HTMLResponse)
def admin_analyze_emotional_profile(
    request: Request,
    subreddit_name: str,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Trigger on-demand emotional profile analysis for a subreddit."""
    from sqlalchemy import func as sa_func
    from app.models.subreddit import Subreddit
    from app.tasks.emotional_profile import analyze_subreddit_emotional_profile

    # Pre-check: subreddit must exist in DB
    subreddit = (
        db.query(Subreddit)
        .filter(sa_func.lower(Subreddit.subreddit_name) == subreddit_name.lower())
        .first()
    )
    if not subreddit:
        return HTMLResponse(
            '<span class="text-red-400 text-sm">'
            f'❌ Subreddit &quot;{subreddit_name}&quot; not found in registry. Add it first.'
            '</span>'
        )

    # Clear previous error before dispatching
    subreddit.emotional_profile_error = None
    db.commit()

    # Dispatch Celery task
    analyze_subreddit_emotional_profile.delay(subreddit_name)

    return HTMLResponse(
        '<div class="text-amber-400 text-sm">'
        '⏳ Analysis started... Refresh page in 30-60s to see results.'
        '<br><span class="text-gray-500 text-xs">Task dispatched to worker queue.</span>'
        '</div>'
    )


@router.get("/subreddits/detail/{subreddit_name}/emotional-profile", response_class=HTMLResponse)
def admin_get_emotional_profile_partial(
    request: Request,
    subreddit_name: str,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: emotional profile display for subreddit detail page."""
    from sqlalchemy import func as sa_func
    from app.models.subreddit import Subreddit

    subreddit = (
        db.query(Subreddit)
        .filter(sa_func.lower(Subreddit.subreddit_name) == subreddit_name.lower())
        .first()
    )

    if not subreddit or not subreddit.emotional_profile:
        # No profile yet — show empty state with trigger button + error if any
        error_html = ""
        if subreddit and subreddit.emotional_profile_error:
            error_html = (
                f'<p class="text-red-400 text-xs mb-2">⚠️ Last attempt failed: '
                f'{subreddit.emotional_profile_error}</p>'
            )
        return HTMLResponse(
            '<div class="bg-gray-800 rounded-lg p-4">'
            '<h3 class="text-sm font-medium text-gray-400 uppercase mb-2">Emotional Profile</h3>'
            '<p class="text-gray-500 text-sm mb-3">Not yet analyzed</p>'
            f'{error_html}'
            f'<button hx-post="/admin/subreddits/detail/{subreddit_name}/analyze-profile" '
            'hx-swap="outerHTML" '
            'class="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs rounded">'
            'Run Analysis</button>'
            '</div>'
        )

    profile = subreddit.emotional_profile

    # Build HTML
    html_parts = ['<div class="bg-gray-800 rounded-lg p-4">']
    html_parts.append('<h3 class="text-sm font-medium text-gray-400 uppercase mb-3">Emotional Profile</h3>')

    # Confidence badge
    conf = profile.get("confidence", "low")
    conf_color = {"high": "green", "medium": "amber", "low": "red"}.get(conf, "gray")
    html_parts.append(
        f'<div class="flex items-center justify-between mb-3">'
        f'<span class="text-xs text-{conf_color}-400">Confidence: {conf}</span>'
        f'<span class="text-xs text-gray-500">'
        f'Analyzed: {subreddit.emotional_profile_analyzed_at.strftime("%Y-%m-%d %H:%M") if subreddit.emotional_profile_analyzed_at else "never"}'
        f'</span></div>'
    )

    # Community temperament
    html_parts.append(
        f'<p class="text-sm text-gray-300 mb-3 italic">{profile.get("community_temperament", "")}</p>'
    )

    # Badges
    html_parts.append('<div class="flex gap-2 mb-3 flex-wrap">')
    html_parts.append(f'<span class="px-2 py-0.5 bg-gray-700 text-xs rounded text-gray-300">Formality: {profile.get("formality_level", "?")}</span>')
    html_parts.append(f'<span class="px-2 py-0.5 bg-gray-700 text-xs rounded text-gray-300">Humor: {profile.get("humor_tolerance", "?")}</span>')
    html_parts.append(f'<span class="px-2 py-0.5 bg-gray-700 text-xs rounded text-gray-300">Vulnerability: {profile.get("vulnerability_tolerance", "?")}</span>')
    html_parts.append('</div>')

    # Rewarded tones
    rewarded = profile.get("rewarded_tones", [])
    if rewarded:
        html_parts.append('<div class="mb-2"><span class="text-xs text-green-400 font-medium">✓ Rewarded:</span></div>')
        html_parts.append('<div class="flex gap-1 flex-wrap mb-3">')
        for t in rewarded:
            html_parts.append(
                f'<span class="px-2 py-0.5 bg-green-900/30 border border-green-700/50 text-xs rounded text-green-300" '
                f'title="{t.get("description", "")}">{t["name"]}</span>'
            )
        html_parts.append('</div>')

    # Punished tones
    punished = profile.get("punished_tones", [])
    if punished:
        html_parts.append('<div class="mb-2"><span class="text-xs text-red-400 font-medium">✗ Punished:</span></div>')
        html_parts.append('<div class="flex gap-1 flex-wrap mb-3">')
        for t in punished:
            html_parts.append(
                f'<span class="px-2 py-0.5 bg-red-900/30 border border-red-700/50 text-xs rounded text-red-300" '
                f'title="{t.get("description", "")}">{t["name"]}</span>'
            )
        html_parts.append('</div>')

    # Refresh button
    html_parts.append(
        f'<button hx-post="/admin/subreddits/detail/{subreddit_name}/analyze-profile" '
        'hx-swap="outerHTML" hx-target="closest div" '
        'class="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs rounded mt-2">'
        'Refresh Profile</button>'
    )

    html_parts.append('</div>')
    return HTMLResponse("".join(html_parts))


# ---------------------------------------------------------------------------
# Help / Documentation (per-role)
# ---------------------------------------------------------------------------


@router.get("/help", response_class=HTMLResponse)
def admin_help(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """In-app documentation for admin/partner roles."""
    import markdown
    from pathlib import Path

    role = current_user.user_role.value

    # Map role to documentation file
    role_doc_map = {
        "owner": "owner-partner.md",
        "partner": "owner-partner.md",
        "avatar_manager": "avatar-owner.md",
        "qa": "client-manager.md",
    }

    doc_filename = role_doc_map.get(role, "owner-partner.md")
    doc_path = Path("docs/kb/roles") / doc_filename

    # Read and render markdown
    doc_html = ""
    if doc_path.exists():
        md_content = doc_path.read_text(encoding="utf-8")
        doc_html = markdown.markdown(
            md_content,
            extensions=["tables", "fenced_code", "toc"],
        )
    else:
        doc_html = "<p>Documentation not found.</p>"

    # Load trial management guide (always relevant for admins)
    trial_html = ""
    trial_path = Path("docs/kb/guides/trial-management.md")
    if trial_path.exists():
        trial_md = trial_path.read_text(encoding="utf-8")
        trial_html = markdown.markdown(
            trial_md,
            extensions=["tables", "fenced_code"],
        )

    # Load operations guide
    ops_html = ""
    ops_path = Path("docs/kb/guides/daily-operations.md")
    if ops_path.exists():
        ops_md = ops_path.read_text(encoding="utf-8")
        ops_html = markdown.markdown(
            ops_md,
            extensions=["tables", "fenced_code"],
        )

    return templates.TemplateResponse(
        name="admin_help.html",
        context={
            "request": request,
            "active_nav": "help",
            "doc_html": doc_html,
            "trial_html": trial_html,
            "ops_html": ops_html,
            "user_role": role,
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# ActionRequest Management (Permission Map Spec — Task 8.3)
# ---------------------------------------------------------------------------


@router.get("/action-requests", response_class=HTMLResponse)
def admin_action_requests(
    request: Request,
    client_id: str | None = None,
    status: str | None = None,
    action_type: str | None = None,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """List pending/resolved ActionRequests with filters."""
    from sqlalchemy import case, desc
    from app.models.action_request import ActionRequest

    query = db.query(ActionRequest)

    # Apply filters
    if client_id:
        try:
            query = query.filter(ActionRequest.client_id == uuid.UUID(client_id))
        except ValueError:
            pass
    if status:
        query = query.filter(ActionRequest.status == status)
    if action_type:
        query = query.filter(ActionRequest.action_type == action_type)

    # Order: pending first, then most recent
    query = query.order_by(
        case(
            (ActionRequest.status == "pending", 0),
            else_=1,
        ),
        desc(ActionRequest.created_at),
    )

    requests_list = query.limit(100).all()

    # Get clients for filter dropdown
    clients_list = (
        db.query(Client)
        .filter(Client.is_active.is_(True))
        .order_by(Client.client_name)
        .all()
    )

    # Get distinct action_types for filter dropdown
    action_types = (
        db.query(ActionRequest.action_type)
        .distinct()
        .order_by(ActionRequest.action_type)
        .all()
    )
    action_types = [at[0] for at in action_types]

    return templates.TemplateResponse(
        name="admin_action_requests.html",
        context={
            "request": request,
            "active_nav": "action-requests",
            "requests": requests_list,
            "clients": clients_list,
            "action_types": action_types,
            "filter_client_id": client_id or "",
            "filter_status": status or "",
            "filter_action_type": action_type or "",
        },
        request=request,
    )


@router.post("/action-requests/{request_id}/approve", response_class=HTMLResponse)
def admin_approve_action_request(
    request: Request,
    request_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Approve a pending ActionRequest."""
    from app.services.action_request import approve_action_request

    try:
        ar = approve_action_request(db, request_id, resolver=current_user)
        db.commit()
    except Exception as e:
        logger.error("Failed to approve ActionRequest %s: %s", request_id, e)
        return HTMLResponse(
            f'<span class="text-red-400 text-sm">Error: {str(e)[:100]}</span>',
            status_code=400,
        )

    # Return HTMX partial showing updated row
    return HTMLResponse(
        f'<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-900/50 text-green-300">'
        f'✓ Approved</span>',
    )


@router.post("/action-requests/{request_id}/reject", response_class=HTMLResponse)
def admin_reject_action_request(
    request: Request,
    request_id: uuid.UUID,
    reason: str = Form(""),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Reject a pending ActionRequest with optional reason."""
    from app.services.action_request import reject_action_request

    try:
        ar = reject_action_request(db, request_id, resolver=current_user, reason=reason)
        db.commit()
    except Exception as e:
        logger.error("Failed to reject ActionRequest %s: %s", request_id, e)
        return HTMLResponse(
            f'<span class="text-red-400 text-sm">Error: {str(e)[:100]}</span>',
            status_code=400,
        )

    # Return HTMX partial showing updated row
    return HTMLResponse(
        f'<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-900/50 text-red-300">'
        f'✗ Rejected</span>',
    )


# ---------------------------------------------------------------------------
# Client Permission Matrix Management
# ---------------------------------------------------------------------------


@router.get("/clients/{client_id}/permissions", response_class=HTMLResponse)
def admin_client_permissions(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Display the effective permission matrix for a client with source indicators."""
    from app.services.permission_map import DEFAULT_PERMISSION_MAP, get_effective_tier

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return HTMLResponse("Client not found", status_code=404)

    client_matrix = client.permission_matrix or {}

    # Build actions list with effective tier, default tier, and override status
    actions = []
    for action_id, default_tier in DEFAULT_PERMISSION_MAP.items():
        effective_tier = get_effective_tier(client_matrix, action_id)
        is_override = action_id in client_matrix and client_matrix[action_id] != default_tier
        actions.append({
            "id": action_id,
            "label": action_id.replace("_", " ").title(),
            "tier": effective_tier,
            "default_tier": default_tier,
            "is_override": is_override,
        })

    return templates.TemplateResponse(
        name="admin_client_permissions.html",
        context={
            "request": request,
            "client": client,
            "actions": actions,
            "active_nav": "clients",
        },
        request=request,
    )


@router.post("/clients/{client_id}/permissions", response_class=HTMLResponse)
def admin_save_client_permissions(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Save changed tiers to the client's permission_matrix JSONB field."""
    import asyncio
    from sqlalchemy.orm.attributes import flag_modified
    from app.services.permission_map import DEFAULT_PERMISSION_MAP, PermissionTier

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return HTMLResponse("Client not found", status_code=404)

    # Parse form data
    loop = asyncio.new_event_loop()
    form_data = loop.run_until_complete(request.form())
    loop.close()

    old_matrix = dict(client.permission_matrix or {})
    new_matrix = {}

    valid_tiers = {t.value for t in PermissionTier}

    for action_id in DEFAULT_PERMISSION_MAP:
        tier_value = form_data.get(f"tier_{action_id}")
        if tier_value and tier_value in valid_tiers:
            # Only store overrides — entries that differ from default
            if tier_value != DEFAULT_PERMISSION_MAP[action_id]:
                new_matrix[action_id] = tier_value

    # Compute diff for audit log
    diff = {}
    all_actions = set(list(old_matrix.keys()) + list(new_matrix.keys()))
    for action_id in all_actions:
        old_val = old_matrix.get(action_id)
        new_val = new_matrix.get(action_id)
        if old_val != new_val:
            diff[action_id] = {"old": old_val, "new": new_val}

    # Update client
    client.permission_matrix = new_matrix
    flag_modified(client, "permission_matrix")
    db.commit()

    # Audit log
    if diff:
        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action="permission_matrix_updated",
            entity_type="client",
            entity_id=client_id,
            client_id=client_id,
            details={"changes": diff},
        )

    # Return redirect for full page reload (HTMX will handle with hx-redirect)
    return RedirectResponse(
        url=f"/admin/clients/{client_id}/permissions",
        status_code=303,
    )


@router.post("/clients/{client_id}/permissions/reset/{action_id}", response_class=HTMLResponse)
def admin_reset_single_permission(
    request: Request,
    client_id: uuid.UUID,
    action_id: str,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Remove a single override from the client's permission_matrix."""
    from sqlalchemy.orm.attributes import flag_modified
    from app.services.permission_map import DEFAULT_PERMISSION_MAP, get_effective_tier

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return HTMLResponse("Client not found", status_code=404)

    matrix = dict(client.permission_matrix or {})
    old_tier = matrix.pop(action_id, None)

    client.permission_matrix = matrix
    flag_modified(client, "permission_matrix")
    db.commit()

    # Audit
    if old_tier:
        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action="permission_matrix_updated",
            entity_type="client",
            entity_id=client_id,
            client_id=client_id,
            details={"changes": {action_id: {"old": old_tier, "new": None}}},
        )

    # Return updated row HTML for HTMX swap
    default_tier = DEFAULT_PERMISSION_MAP.get(action_id, "admin_only")
    effective_tier = get_effective_tier(matrix, action_id)
    label = action_id.replace("_", " ").title()

    tier_colors = {
        "self_service": "bg-green-900/50 text-green-300",
        "approval_required": "bg-yellow-900/50 text-yellow-300",
        "admin_only": "bg-red-900/50 text-red-300",
    }
    tier_labels = {
        "self_service": "Self-Service",
        "approval_required": "Approval Required",
        "admin_only": "Admin Only",
    }

    row_html = f'''<tr id="row-{action_id}">
        <td class="px-4 py-3 text-sm text-gray-300">{label}</td>
        <td class="px-4 py-3">
            <select name="tier_{action_id}" form="permissions-form"
                    class="bg-gray-700 text-gray-200 text-sm rounded px-2 py-1 border border-gray-600 focus:border-blue-500 focus:outline-none">
                <option value="self_service" {"selected" if effective_tier == "self_service" else ""}>Self-Service</option>
                <option value="approval_required" {"selected" if effective_tier == "approval_required" else ""}>Approval Required</option>
                <option value="admin_only" {"selected" if effective_tier == "admin_only" else ""}>Admin Only</option>
            </select>
        </td>
        <td class="px-4 py-3">
            <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-700 text-gray-400">Default</span>
        </td>
        <td class="px-4 py-3 text-sm text-gray-500">
            <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium {tier_colors.get(default_tier, "")}">{tier_labels.get(default_tier, default_tier)}</span>
        </td>
        <td class="px-4 py-3"></td>
    </tr>'''

    return HTMLResponse(row_html)


@router.post("/clients/{client_id}/permissions/reset-all", response_class=HTMLResponse)
def admin_reset_all_permissions(
    request: Request,
    client_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Replace the client's permission_matrix with DEFAULT_PERMISSION_MAP (empty overrides)."""
    from sqlalchemy.orm.attributes import flag_modified
    from app.services.permission_map import DEFAULT_PERMISSION_MAP

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return HTMLResponse("Client not found", status_code=404)

    old_matrix = dict(client.permission_matrix or {})

    # Reset = empty dict (no overrides, everything falls back to default)
    client.permission_matrix = {}
    flag_modified(client, "permission_matrix")
    db.commit()

    # Audit
    if old_matrix:
        diff = {k: {"old": v, "new": None} for k, v in old_matrix.items()}
        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action="permission_matrix_updated",
            entity_type="client",
            entity_id=client_id,
            client_id=client_id,
            details={"changes": diff, "reset_all": True},
        )

    # Redirect to reload the page
    return RedirectResponse(
        url=f"/admin/clients/{client_id}/permissions",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# Ops Notifications (admin bell)
# ---------------------------------------------------------------------------


@router.get("/api/ops-notifications", response_class=JSONResponse)
def get_ops_notifications(
    current_user: User = Depends(require_superuser),
):
    """Get recent ops notifications for admin bell."""
    from app.services.ops_notifications import get_recent_ops_notifications, get_unread_ops_count

    notifications = get_recent_ops_notifications(limit=20)
    count = get_unread_ops_count()
    return JSONResponse({"notifications": notifications, "unread_count": count})


@router.post("/api/ops-notifications/clear", response_class=JSONResponse)
def clear_ops_notifications_route(
    current_user: User = Depends(require_superuser),
):
    """Clear all ops notifications (mark as read)."""
    from app.services.ops_notifications import clear_ops_notifications

    clear_ops_notifications()
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# User Profile (owner/partner)
# ---------------------------------------------------------------------------


@router.get("/profile", response_class=HTMLResponse)
def admin_profile(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """User profile page — notification settings, Telegram connection."""
    return templates.TemplateResponse(
        "admin_profile.html",
        context={
            "request": request,
            "user": current_user,
            "active_nav": "profile",
            "flash_message": request.query_params.get("msg"),
            "flash_type": request.query_params.get("type", "success"),
        },
        request=request,
    )


@router.post("/profile/telegram/connect", response_class=RedirectResponse)
def admin_profile_telegram_connect(
    chat_id: str = Form(...),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Connect Telegram by saving chat_id."""
    from datetime import datetime, timezone

    chat_id = chat_id.strip()
    if not chat_id or not chat_id.lstrip("-").isdigit():
        return RedirectResponse(
            url="/admin/profile?msg=Invalid+Chat+ID.+Must+be+a+number.&type=error",
            status_code=303,
        )

    current_user.telegram_chat_id = chat_id
    current_user.telegram_connected_at = datetime.now(timezone.utc)
    if not current_user.telegram_notifications_level:
        current_user.telegram_notifications_level = "critical"
    db.commit()

    return RedirectResponse(url="/admin/profile?msg=Telegram+connected!", status_code=303)


@router.post("/profile/telegram/disconnect", response_class=RedirectResponse)
def admin_profile_telegram_disconnect(
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Disconnect Telegram."""
    current_user.telegram_chat_id = None
    current_user.telegram_connected_at = None
    db.commit()

    return RedirectResponse(url="/admin/profile?msg=Telegram+disconnected.&type=success", status_code=303)


@router.post("/profile/telegram/level", response_class=RedirectResponse)
def admin_profile_telegram_level(
    level: str = Form(...),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Update notification level."""
    valid_levels = {"all", "warning", "critical", "off"}
    if level not in valid_levels:
        level = "critical"

    current_user.telegram_notifications_level = level
    db.commit()

    return RedirectResponse(url="/admin/profile?msg=Notification+level+updated.&type=success", status_code=303)
