"""Avatar management and health monitoring routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.avatar import Avatar
from app.services.safety import get_avatar_health, quarantine_avatar

router = APIRouter()


@router.get("/")
def list_avatars(active_only: bool = True, db: Session = Depends(get_db)):
    """List all avatars with health status."""
    query = db.query(Avatar)
    if active_only:
        query = query.filter(Avatar.active.is_(True))

    avatars = query.all()
    return [get_avatar_health(db, a) for a in avatars]


@router.get("/{avatar_id}/health")
def avatar_health(avatar_id: UUID, db: Session = Depends(get_db)):
    """Get detailed health metrics for an avatar."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")
    return get_avatar_health(db, avatar)


@router.post("/{avatar_id}/quarantine")
def quarantine(avatar_id: UUID, reason: str = "manual", db: Session = Depends(get_db)):
    """Quarantine (deactivate) an avatar."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")
    quarantine_avatar(db, avatar, reason)
    return {"status": "quarantined", "username": avatar.reddit_username}


@router.post("/{avatar_id}/reactivate")
def reactivate(avatar_id: UUID, db: Session = Depends(get_db)):
    """Reactivate a quarantined avatar."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")
    avatar.active = True
    avatar.is_shadowbanned = False
    db.commit()
    return {"status": "reactivated", "username": avatar.reddit_username}
