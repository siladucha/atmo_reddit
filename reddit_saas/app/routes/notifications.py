"""Notification feed API routes for the client portal.

Endpoints:
  GET  /clients/{client_id}/notifications       — list recent notifications
  GET  /clients/{client_id}/notifications/count  — unread count (for badge)
  POST /clients/{client_id}/notifications/read   — mark all as read
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import get_current_user, verify_client_access_from_path
from app.logging_config import get_logger
from app.models.user import User
from app.services.notifications import get_notifications, get_unread_count, mark_all_read

logger = get_logger(__name__)

router = APIRouter(
    dependencies=[Depends(verify_client_access_from_path)],
    tags=["notifications"],
)


@router.get("/clients/{client_id}/notifications")
def list_notifications(
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get recent notifications for the client."""
    notifs = get_notifications(db, client_id, limit=30)
    return JSONResponse(content={
        "notifications": [
            {
                "id": str(n.id),
                "type": n.type,
                "title": n.title,
                "body": n.body,
                "link": n.link,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in notifs
        ]
    })


@router.get("/clients/{client_id}/notifications/count")
def notification_count(
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get unread notification count (for bell badge)."""
    count = get_unread_count(db, client_id)
    return JSONResponse(content={"unread": count})


@router.post("/clients/{client_id}/notifications/read")
def mark_notifications_read(
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark all notifications as read for this client."""
    count = mark_all_read(db, client_id)
    return JSONResponse(content={"ok": True, "marked": count})
