"""Avatar CRUD and health monitoring routes."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.models.avatar import Avatar
from app.models.user import User
from app.models.user_role import UserRole
from app.services.safety import get_avatar_health, quarantine_avatar

logger = logging.getLogger(__name__)
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
def list_avatars(
    active_only: bool = True,
    client_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
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
def get_avatar(
    avatar_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Get full avatar details."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")
    return {
        "avatar": avatar,
        "health": get_avatar_health(db, avatar),
    }


@router.post("/")
def create_avatar(
    data: AvatarCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
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

    # Dispatch hobby scrape asynchronously — POST shouldn't block on Reddit I/O.
    if data.hobby_subreddits:
        try:
            from app.tasks.scraping import scrape_hobby_subreddits
            scrape_hobby_subreddits.delay(str(avatar.id))
        except Exception:
            logger.warning(
                "Failed to dispatch hobby scrape for avatar %s",
                avatar.reddit_username, exc_info=True,
            )

    return avatar


@router.patch("/{avatar_id}")
def update_avatar(
    avatar_id: UUID,
    data: AvatarUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
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
def avatar_health(
    avatar_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Get detailed health metrics for an avatar."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")
    return get_avatar_health(db, avatar)


@router.post("/{avatar_id}/quarantine")
def quarantine(
    avatar_id: UUID,
    reason: str = "manual",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Quarantine (deactivate) an avatar."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")
    quarantine_avatar(db, avatar, reason)
    return {"status": "quarantined", "username": avatar.reddit_username}


@router.post("/{avatar_id}/reactivate")
def reactivate(
    avatar_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Reactivate a quarantined avatar."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")
    avatar.active = True
    avatar.is_shadowbanned = False
    db.commit()
    return {"status": "reactivated", "username": avatar.reddit_username}


# --- Reddit Status (JSON API) ---

@router.post("/{avatar_id}/check-reddit-status")
def check_reddit_status_api(
    avatar_id: UUID,
    force: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Trigger a Reddit status check for one avatar; return cached fields as JSON."""
    from app.services.reddit_status import check_reddit_status
    from app.services.reddit_freshness import is_reddit_status_fresh

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    skipped = False
    if force or not is_reddit_status_fresh(db, avatar):
        status = check_reddit_status(db, avatar)
    else:
        skipped = True
        status = None
    return {
        "avatar_id": str(avatar.id),
        "username": avatar.reddit_username,
        "result": status.to_dict() if status else {"status": avatar.reddit_status, "skipped": "fresh_cache"},
        "skipped": skipped,
        "cached": {
            "reddit_status": avatar.reddit_status,
            "reddit_karma_comment": avatar.reddit_karma_comment,
            "reddit_karma_post": avatar.reddit_karma_post,
            "reddit_account_created": (
                avatar.reddit_account_created.isoformat()
                if avatar.reddit_account_created else None
            ),
            "reddit_icon_url": avatar.reddit_icon_url,
            "reddit_status_checked_at": (
                avatar.reddit_status_checked_at.isoformat()
                if avatar.reddit_status_checked_at else None
            ),
            "is_shadowbanned": avatar.is_shadowbanned,
        },
    }


@router.post("/check-reddit-status-all")
def check_reddit_status_all_api(
    force: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Trigger Reddit status check for all active avatars; return summary."""
    from app.services.reddit_status import check_all_reddit_statuses
    from app.services.reddit_freshness import reddit_status_manual_batch_limit

    avatars = db.query(Avatar).filter(Avatar.active.is_(True)).all()
    results = check_all_reddit_statuses(
        db,
        avatars[:reddit_status_manual_batch_limit(db)],
        force=force,
    )
    summary = {"checked": len(results), "by_status": {}}
    for r in results:
        summary["by_status"][r["status"]] = summary["by_status"].get(r["status"], 0) + 1
    return {"summary": summary, "results": results}


# --- EPG (Daily Publishing Program) ---

@router.get("/{avatar_id}/epg")
def get_avatar_epg(
    avatar_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Get today's EPG (publishing program) for an avatar.

    Returns the daily schedule: which threads to comment on,
    when, and what type (hobby/professional).
    """
    from app.models.client import Client
    from app.services.epg import build_daily_epg

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    client = None
    if avatar.client_ids:
        client = db.query(Client).filter(Client.id == avatar.client_ids[0]).first()

    epg = build_daily_epg(db, avatar, client)
    return {
        "avatar_id": str(avatar.id),
        "avatar_username": avatar.reddit_username,
        "phase": avatar.warming_phase,
        "daily_budget": epg.daily_budget,
        "used_today": epg.used_today,
        "remaining": epg.remaining,
        "status": epg.status,
        "message": epg.message,
        "total_slots": epg.total_slots,
        "hobby_slots": epg.hobby_slots,
        "business_slots": epg.business_slots,
    }


@router.post("/{avatar_id}/epg/build")
def build_avatar_epg(
    avatar_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Build EPG and trigger comment generation for an avatar.

    Dispatches Celery tasks to generate comments for the EPG slots.
    Bypasses pipeline_enabled kill switch (manual trigger).
    """
    from app.models.client import Client
    from app.services.epg import build_daily_epg

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    client = None
    if avatar.client_ids:
        client = db.query(Client).filter(Client.id == avatar.client_ids[0]).first()

    epg = build_daily_epg(db, avatar, client)

    tasks_dispatched = []

    if epg.hobby_slots:
        from app.tasks.ai_pipeline import generate_hobby_comments
        try:
            result = generate_hobby_comments.delay(
                str(avatar.id), max_comments=len(epg.hobby_slots), triggered_by="manual"
            )
            tasks_dispatched.append({"type": "hobby", "task_id": str(result.id), "slots": len(epg.hobby_slots)})
        except Exception as e:
            tasks_dispatched.append({"type": "hobby", "error": str(e)})

    if epg.business_slots and client:
        from app.tasks.ai_pipeline import generate_comments
        try:
            result = generate_comments.delay(
                str(client.id), max_comments=len(epg.business_slots), triggered_by="manual"
            )
            tasks_dispatched.append({"type": "professional", "task_id": str(result.id), "slots": len(epg.business_slots)})
        except Exception as e:
            tasks_dispatched.append({"type": "professional", "error": str(e)})

    return {
        "epg": epg.to_dict(),
        "tasks_dispatched": tasks_dispatched,
    }
