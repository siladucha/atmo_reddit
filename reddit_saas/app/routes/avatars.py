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

    # Immediate scrape of hobby subreddits for the new avatar
    # Uses a separate DB session to avoid interfering with the main transaction
    if data.hobby_subreddits:
        try:
            from app.database import SessionLocal
            from app.services.reddit import scrape_subreddit
            from app.models.hobby import HobbySubreddit
            from app.services.transparency import record_activity_event

            scrape_db = SessionLocal()
            try:
                hobby_subs = data.hobby_subreddits
                if isinstance(hobby_subs, str):
                    hobby_subs = [s.strip() for s in hobby_subs.split(",")]

                for sub_name in hobby_subs[:3]:  # Limit to 3 to avoid long wait
                    sub_name = sub_name.strip().replace("r/", "")
                    if not sub_name:
                        continue
                    try:
                        posts = scrape_subreddit(sub_name, limit=20, max_age_hours=24, sort="hot")
                        for post in posts:
                            exists = scrape_db.query(HobbySubreddit).filter(
                                HobbySubreddit.post_id == post["reddit_native_id"]
                            ).first()
                            if exists:
                                continue
                            hobby = HobbySubreddit(
                                subreddit=post["subreddit"],
                                post_id=post["reddit_native_id"],
                                post_title=post["post_title"],
                                post_body=post["post_body"],
                                comments=post["comments_json"],
                                url=post["url"],
                                author=post["author"],
                                avatar_username=avatar.reddit_username,
                                post_ups=post["ups"],
                                post_downs=post["downs"],
                                status="new",
                            )
                            scrape_db.add(hobby)
                        scrape_db.commit()
                        record_activity_event(
                            scrape_db, "scrape",
                            f"Immediate hobby scrape: r/{sub_name} for {avatar.reddit_username}",
                            client_id=None,
                            metadata={"subreddit_name": sub_name, "avatar_username": avatar.reddit_username, "trigger": "immediate"},
                        )
                    except Exception:
                        scrape_db.rollback()
                        continue  # Non-critical
            finally:
                scrape_db.close()
        except Exception:
            pass  # Non-critical — avatar was created

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


# --- Reddit Status (JSON API) ---

@router.post("/{avatar_id}/check-reddit-status")
def check_reddit_status_api(avatar_id: UUID, db: Session = Depends(get_db)):
    """Trigger a Reddit status check for one avatar; return cached fields as JSON."""
    from app.services.reddit_status import check_reddit_status

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    status = check_reddit_status(db, avatar)
    return {
        "avatar_id": str(avatar.id),
        "username": avatar.reddit_username,
        "result": status.to_dict(),
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
def check_reddit_status_all_api(db: Session = Depends(get_db)):
    """Trigger Reddit status check for all active avatars; return summary."""
    from app.services.reddit_status import check_all_reddit_statuses

    avatars = db.query(Avatar).filter(Avatar.active.is_(True)).all()
    results = check_all_reddit_statuses(db, avatars)
    summary = {"checked": len(results), "by_status": {}}
    for r in results:
        summary["by_status"][r["status"]] = summary["by_status"].get(r["status"], 0) + 1
    return {"summary": summary, "results": results}
