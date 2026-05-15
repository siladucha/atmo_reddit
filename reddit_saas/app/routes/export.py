"""JSON export endpoints — download page data as JSON files.

Permission model:
- Platform-wide exports (all clients, users, audit logs, AI costs): require_superuser (owner/partner)
- Client-scoped reports (client report, avatar report): require_report_access
  - owner/partner: always allowed
  - client_admin/client_manager: allowed for their own client only
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.dependencies.permissions import get_current_user
from app.models.user import User
from app.models.user_role import UserRole
from app.services import export as export_service

router = APIRouter(prefix="/export", tags=["export"])


async def require_report_access(user: User = Depends(get_current_user)) -> User:
    """Allow owner, partner, client_admin, and client_manager to access reports.

    - owner/partner: platform-wide access (all reports)
    - client_admin/client_manager: scoped to their own client (enforced per-endpoint)

    Raises 403 for client_viewer, b2c_user, or other roles.
    """
    allowed_roles = (UserRole.owner, UserRole.partner, UserRole.client_admin, UserRole.client_manager)
    if user.user_role not in allowed_roles and not user.is_superuser:
        raise HTTPException(status_code=403, detail="Access Denied")
    return user


def _verify_client_scope(user: User, client_id: uuid.UUID) -> None:
    """Verify that a client-scoped user can access the given client_id.

    Raises 403 if the user is client-scoped and client_id doesn't match.
    Owner/partner always pass.
    """
    if user.user_role in (UserRole.owner, UserRole.partner) or user.is_superuser:
        return
    if user.client_id != client_id:
        raise HTTPException(status_code=403, detail="Access Denied")


def _json_download(data: list | dict, filename: str) -> JSONResponse:
    """Return a JSONResponse with Content-Disposition header for download."""
    return JSONResponse(
        content={"exported_at": datetime.now(timezone.utc).isoformat(), "data": data},
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/clients")
def export_clients(
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    data = export_service.export_clients(db)
    return _json_download(data, "clients.json")


@router.get("/clients/{client_id}/report.md")
def export_client_markdown_report(
    client_id: uuid.UUID,
    current_user: User = Depends(require_report_access),
    db: Session = Depends(get_db),
):
    """Markdown client report for delivery — pipeline stats, avatar performance, recommendations."""
    _verify_client_scope(current_user, client_id)

    from fastapi.responses import Response
    from app.services.client_report import generate_client_report_md

    md_content = generate_client_report_md(db, client_id)
    if md_content is None:
        return JSONResponse(content={"error": "Client not found"}, status_code=404)

    from app.models.client import Client
    client = db.query(Client).filter(Client.id == client_id).first()
    name_slug = (client.client_name or "unknown").replace(" ", "_").lower()[:30]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")

    return Response(
        content=md_content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="client_report_{name_slug}_{ts}.md"'},
    )


@router.get("/clients/{client_id}/report")
def export_client_json_report(
    client_id: uuid.UUID,
    current_user: User = Depends(require_report_access),
    db: Session = Depends(get_db),
):
    """JSON client report — full pipeline data for programmatic use."""
    _verify_client_scope(current_user, client_id)
    from app.services.client_report import (
        _score_client_profile,
        _get_pipeline_stats,
        _get_avatar_summary,
        _get_subreddit_performance,
        _get_ai_cost_summary,
        _get_top_comments,
    )
    from app.models.client import Client

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return JSONResponse(content={"error": "Client not found"}, status_code=404)

    data = {
        "client": export_service.serialize_client(client),
        "profile_scores": _score_client_profile(client),
        "pipeline_stats": _get_pipeline_stats(db, client_id, days=30),
        "avatar_summary": _get_avatar_summary(db, client_id, days=30),
        "subreddit_performance": _get_subreddit_performance(db, client_id, days=30),
        "ai_costs": _get_ai_cost_summary(db, client_id, days=30),
        "top_comments": _get_top_comments(db, client_id, limit=10),
    }

    name_slug = (client.client_name or "unknown").replace(" ", "_").lower()[:30]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    return _json_download(data, f"client_report_{name_slug}_{ts}.json")


@router.get("/avatars")
def export_avatars(
    client_id: str | None = Query(None),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    cid = uuid.UUID(client_id) if client_id else None
    data = export_service.export_avatars(db, client_id=cid)
    suffix = f"_{client_id[:8]}" if client_id else ""
    return _json_download(data, f"avatars{suffix}.json")


@router.get("/avatars/{avatar_id}")
def export_single_avatar(
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_report_access),
    db: Session = Depends(get_db),
):
    """Export a single avatar with profile analytics as avatar_{username}.json."""
    # Client-scoped users: verify avatar belongs to their client
    if current_user.user_role not in (UserRole.owner, UserRole.partner) and not current_user.is_superuser:
        from app.models.avatar import Avatar
        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if not avatar or (current_user.client_id and str(current_user.client_id) not in (avatar.client_ids or [])):
            raise HTTPException(status_code=403, detail="Access Denied")

    data = export_service.export_single_avatar(db, avatar_id)
    if data is None:
        return JSONResponse(content={"error": "Avatar not found"}, status_code=404)
    username = data.get("reddit_username", "unknown")
    return _json_download(data, f"avatar_{username}.json")


@router.get("/avatars/{avatar_id}/report")
def export_avatar_client_report(
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_report_access),
    db: Session = Depends(get_db),
):
    """Full avatar report for client delivery — profile, stats, comments, subreddit activity."""
    # Client-scoped users: verify avatar belongs to their client
    if current_user.user_role not in (UserRole.owner, UserRole.partner) and not current_user.is_superuser:
        from app.models.avatar import Avatar
        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if not avatar or (current_user.client_id and str(current_user.client_id) not in (avatar.client_ids or [])):
            raise HTTPException(status_code=403, detail="Access Denied")

    data = export_service.export_avatar_client_report(db, avatar_id)
    if data is None:
        return JSONResponse(content={"error": "Avatar not found"}, status_code=404)
    username = data.get("reddit_username", "unknown")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    return _json_download(data, f"avatar_report_{username}_{ts}.json")


@router.get("/avatars/{avatar_id}/report.md")
def export_avatar_markdown_report(
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_report_access),
    db: Session = Depends(get_db),
):
    """Markdown avatar report for client delivery — quality scores, activity, recommendations."""
    # Client-scoped users: verify avatar belongs to their client
    if current_user.user_role not in (UserRole.owner, UserRole.partner) and not current_user.is_superuser:
        from app.models.avatar import Avatar
        avatar_check = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if not avatar_check or (current_user.client_id and str(current_user.client_id) not in (avatar_check.client_ids or [])):
            raise HTTPException(status_code=403, detail="Access Denied")

    from fastapi.responses import Response
    from app.services.avatar_report import generate_avatar_report_md

    md_content = generate_avatar_report_md(db, avatar_id)
    if md_content is None:
        return JSONResponse(content={"error": "Avatar not found"}, status_code=404)

    # Get username for filename
    from app.models.avatar import Avatar
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    username = avatar.reddit_username if avatar else "unknown"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")

    return Response(
        content=md_content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="avatar_report_{username}_{ts}.md"'},
    )


@router.get("/threads")
def export_threads(
    client_id: str | None = Query(None),
    tag: str | None = Query(None),
    current_user: User = Depends(require_report_access),
    db: Session = Depends(get_db),
):
    # Client-scoped users must provide their own client_id
    if current_user.user_role not in (UserRole.owner, UserRole.partner) and not current_user.is_superuser:
        if not client_id or uuid.UUID(client_id) != current_user.client_id:
            raise HTTPException(status_code=403, detail="Access Denied")

    cid = uuid.UUID(client_id) if client_id else None
    data = export_service.export_threads(db, client_id=cid, tag=tag)
    suffix = f"_{client_id[:8]}" if client_id else ""
    return _json_download(data, f"threads{suffix}.json")


@router.get("/comments")
def export_comments(
    client_id: str | None = Query(None),
    status: str | None = Query(None),
    current_user: User = Depends(require_report_access),
    db: Session = Depends(get_db),
):
    # Client-scoped users must provide their own client_id
    if current_user.user_role not in (UserRole.owner, UserRole.partner) and not current_user.is_superuser:
        if not client_id or uuid.UUID(client_id) != current_user.client_id:
            raise HTTPException(status_code=403, detail="Access Denied")

    cid = uuid.UUID(client_id) if client_id else None
    data = export_service.export_comment_drafts(db, client_id=cid, status=status)
    suffix = f"_{client_id[:8]}" if client_id else ""
    return _json_download(data, f"comments{suffix}.json")


@router.get("/subreddits")
def export_subreddits(
    client_id: str | None = Query(None),
    current_user: User = Depends(require_report_access),
    db: Session = Depends(get_db),
):
    # Client-scoped users must provide their own client_id
    if current_user.user_role not in (UserRole.owner, UserRole.partner) and not current_user.is_superuser:
        if not client_id or uuid.UUID(client_id) != current_user.client_id:
            raise HTTPException(status_code=403, detail="Access Denied")

    cid = uuid.UUID(client_id) if client_id else None
    data = export_service.export_subreddits(db, client_id=cid)
    suffix = f"_{client_id[:8]}" if client_id else ""
    return _json_download(data, f"subreddits{suffix}.json")


@router.get("/ai-costs")
def export_ai_costs(
    client_id: str | None = Query(None),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    cid = uuid.UUID(client_id) if client_id else None
    data = export_service.export_ai_usage(db, client_id=cid)
    suffix = f"_{client_id[:8]}" if client_id else ""
    return _json_download(data, f"ai_costs{suffix}.json")


@router.get("/audit-logs")
def export_audit_logs(
    client_id: str | None = Query(None),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    cid = uuid.UUID(client_id) if client_id else None
    data = export_service.export_audit_logs(db, client_id=cid)
    suffix = f"_{client_id[:8]}" if client_id else ""
    return _json_download(data, f"audit_logs{suffix}.json")


@router.get("/users")
def export_users(
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    data = export_service.export_users(db)
    return _json_download(data, "users.json")


@router.get("/activity")
def export_activity(
    client_id: str | None = Query(None),
    current_user: User = Depends(require_report_access),
    db: Session = Depends(get_db),
):
    # Client-scoped users must provide their own client_id
    if current_user.user_role not in (UserRole.owner, UserRole.partner) and not current_user.is_superuser:
        if not client_id or uuid.UUID(client_id) != current_user.client_id:
            raise HTTPException(status_code=403, detail="Access Denied")

    cid = uuid.UUID(client_id) if client_id else None
    data = export_service.export_activity_events(db, client_id=cid)
    suffix = f"_{client_id[:8]}" if client_id else ""
    return _json_download(data, f"activity{suffix}.json")
