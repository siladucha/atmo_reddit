"""JSON export endpoints — download page data as JSON files."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.models.user import User
from app.services import export as export_service

router = APIRouter(prefix="/export", tags=["export"])


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


@router.get("/threads")
def export_threads(
    client_id: str | None = Query(None),
    tag: str | None = Query(None),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    cid = uuid.UUID(client_id) if client_id else None
    data = export_service.export_threads(db, client_id=cid, tag=tag)
    suffix = f"_{client_id[:8]}" if client_id else ""
    return _json_download(data, f"threads{suffix}.json")


@router.get("/comments")
def export_comments(
    client_id: str | None = Query(None),
    status: str | None = Query(None),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    cid = uuid.UUID(client_id) if client_id else None
    data = export_service.export_comment_drafts(db, client_id=cid, status=status)
    suffix = f"_{client_id[:8]}" if client_id else ""
    return _json_download(data, f"comments{suffix}.json")


@router.get("/subreddits")
def export_subreddits(
    client_id: str | None = Query(None),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
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
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    cid = uuid.UUID(client_id) if client_id else None
    data = export_service.export_activity_events(db, client_id=cid)
    suffix = f"_{client_id[:8]}" if client_id else ""
    return _json_download(data, f"activity{suffix}.json")
