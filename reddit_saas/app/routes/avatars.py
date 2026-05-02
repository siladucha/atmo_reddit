"""Avatar CRUD and health monitoring routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models.avatar import Avatar
from app.services.safety import get_avatar_health, quarantine_avatar

router = APIRouter()


class AvatarCreate(BaseModel):
    reddit_username: str
    email_address: str | None = None
    client_ids: list[str] | None = None
    voice_profile_md: str | None = None
    tone_principles: str | None = None
    speech_patterns: str | None = None
    hill_i_die_on: str | None = None
    helpful_mode_topics: str | None = None
    constraints: str | None = None
    vocabulary_lean: str | None = None
    hobby_subreddits: list[str] | None = None
    business_subreddits: list[str] | None = None


class AvatarUpdate(BaseModel):
    reddit_username: str | None = None
    email_address: str | None = None
    voice_profile_md: str | None = None
    tone_principles: str | None = None
    speech_patterns: str | None = None
    hill_i_die_on: str | None = None
    helpful_mode_topics: str | None = None
    constraints: str | None = None
    vocabulary_lean: str | None = None
    hobby_subreddits: list[str] | None = None
    business_subreddits: list[str] | None = None
    active: bool | None = None


# --- CRUD ---

@router.get("/")
def list_avatars(active_only: bool = True, client_id: UUID | None = None, db: Session = Depends(get_db)):
    """List all avatars with health status."""
    query = db.query(Avatar)
    if active_only:
        query = query.filter(Avatar.active.is_(True))
    avatars = query.all()

    # Filter by client if specified
    if client_id:
        cid = str(client_id)
        avatars = [a for a in avatars if a.client_ids and cid in a.client_ids]

    return [get_avatar_health(db, a) for a in avatars]


@router.get("/{avatar_id}")
def get_avatar(avatar_id: UUID, db: Session = Depends(get_db)):
    """Get full avatar details."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")
    return {
        "avatar": avatar,
        "health": get_avatar_health(db, avatar),
    }


@router.post("/")
def create_avatar(data: AvatarCreate, db: Session = Depends(get_db)):
    """Create a new avatar."""
    # Check username uniqueness
    existing = db.query(Avatar).filter(Avatar.reddit_username == data.reddit_username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Reddit username already exists")

    avatar = Avatar(
        reddit_username=data.reddit_username,
        email_address=data.email_address,
        client_ids=data.client_ids,
        voice_profile_md=data.voice_profile_md,
        tone_principles=data.tone_principles,
        speech_patterns=data.speech_patterns,
        hill_i_die_on=data.hill_i_die_on,
        helpful_mode_topics=data.helpful_mode_topics,
        constraints=data.constraints,
        vocabulary_lean=data.vocabulary_lean,
        hobby_subreddits=data.hobby_subreddits,
        business_subreddits=data.business_subreddits,
        active=True,
    )
    db.add(avatar)
    db.commit()
    db.refresh(avatar)
    return avatar


@router.patch("/{avatar_id}")
def update_avatar(avatar_id: UUID, data: AvatarUpdate, db: Session = Depends(get_db)):
    """Update avatar details."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(avatar, field, value)

    db.commit()
    db.refresh(avatar)
    return avatar


# --- Health & Safety ---

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
