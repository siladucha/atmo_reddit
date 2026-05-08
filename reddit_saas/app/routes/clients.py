"""Client CRUD routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.models.client import Client
from app.models.avatar import Avatar
from app.models.subreddit import ClientSubreddit
from app.models.user import User
from app.services import admin as admin_service

router = APIRouter()


class ClientCreate(BaseModel):
    client_name: str
    brand_name: str
    company_profile: str | None = None
    company_worldview: str | None = None
    company_problem: str | None = None
    competitive_landscape: str | None = None
    brand_voice: str | None = None
    icp_profiles: str | None = None
    keywords: dict | None = None


class ClientUpdate(BaseModel):
    client_name: str | None = None
    brand_name: str | None = None
    company_profile: str | None = None
    company_worldview: str | None = None
    company_problem: str | None = None
    competitive_landscape: str | None = None
    brand_voice: str | None = None
    icp_profiles: str | None = None
    keywords: dict | None = None
    is_active: bool | None = None


class SubredditAdd(BaseModel):
    subreddit_name: str
    type: str = "professional"  # professional | hobby


@router.get("/")
def list_clients(
    active_only: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """List all clients."""
    query = db.query(Client)
    if active_only:
        query = query.filter(Client.is_active.is_(True))
    return query.order_by(Client.created_at.desc()).all()


@router.get("/{client_id}")
def get_client(
    client_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Get client details with avatars and subreddits."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Get avatars assigned to this client
    all_avatars = db.query(Avatar).filter(Avatar.active.is_(True)).all()
    client_avatars = [
        {
            "id": str(a.id),
            "reddit_username": a.reddit_username,
            "karma_comment": a.karma_comment,
            "karma_post": a.karma_post,
            "is_shadowbanned": a.is_shadowbanned,
        }
        for a in all_avatars
        if a.client_ids and str(client_id) in a.client_ids
    ]

    # Get subreddits
    subreddits = (
        db.query(ClientSubreddit)
        .filter(ClientSubreddit.client_id == client_id, ClientSubreddit.is_active.is_(True))
        .all()
    )

    return {
        "client": client,
        "avatars": client_avatars,
        "subreddits": [
            {"id": str(s.id), "name": s.subreddit_name, "type": s.type}
            for s in subreddits
        ],
    }


@router.post("/")
def create_client(
    data: ClientCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Create a new client."""
    client = Client(**data.model_dump())
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.patch("/{client_id}")
def update_client(
    client_id: UUID,
    data: ClientUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Update client details."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(client, field, value)

    db.commit()
    db.refresh(client)
    return client


@router.delete("/{client_id}")
def deactivate_client(
    client_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Deactivate a client (soft delete)."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    client.is_active = False
    db.commit()
    return {"status": "deactivated", "client_name": client.client_name}


# --- Subreddit management ---

@router.post("/{client_id}/subreddits")
def add_subreddit(
    client_id: UUID,
    data: SubredditAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Add a subreddit to monitor for a client.

    Creates a Subreddit record if needed, then creates or reactivates
    a ClientSubredditAssignment.
    """
    valid, err = admin_service.validate_subreddit_name(data.subreddit_name)
    if not valid:
        raise HTTPException(status_code=400, detail=err)
    try:
        assignment = admin_service.add_subreddit(
            db, client_id, data.subreddit_name, data.type, current_user_id=None
        )
        return {
            "id": str(assignment.id),
            "subreddit_id": str(assignment.subreddit_id),
            "subreddit_name": assignment.subreddit.subreddit_name,
            "type": assignment.type,
            "is_active": assignment.is_active,
        }
    except ValueError as e:
        msg = str(e)
        status = 404 if "Client not found" in msg else 409
        raise HTTPException(status_code=status, detail=msg)


@router.delete("/{client_id}/subreddits/{subreddit_id}")
def remove_subreddit(
    client_id: UUID,
    subreddit_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Remove a subreddit from monitoring (soft-delete assignment)."""
    from app.models.subreddit import ClientSubredditAssignment

    assignment = (
        db.query(ClientSubredditAssignment)
        .filter(
            ClientSubredditAssignment.id == subreddit_id,
            ClientSubredditAssignment.client_id == client_id,
        )
        .first()
    )
    if not assignment:
        # Fallback: try legacy ClientSubreddit table
        sub = (
            db.query(ClientSubreddit)
            .filter(ClientSubreddit.id == subreddit_id, ClientSubreddit.client_id == client_id)
            .first()
        )
        if not sub:
            raise HTTPException(status_code=404, detail="Subreddit not found")
        sub.is_active = False
        db.commit()
        return {"status": "removed", "subreddit": sub.subreddit_name}

    assignment.is_active = False
    db.commit()
    return {"status": "removed", "subreddit": assignment.subreddit.subreddit_name}


# --- Avatar assignment ---

@router.post("/{client_id}/avatars/{avatar_id}")
def assign_avatar(
    client_id: UUID,
    avatar_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Assign an avatar to a client."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    client_id_str = str(client_id)
    if not avatar.client_ids:
        avatar.client_ids = [client_id_str]
    elif client_id_str not in avatar.client_ids:
        avatar.client_ids = avatar.client_ids + [client_id_str]

    db.commit()
    return {"status": "assigned", "avatar": avatar.reddit_username, "client": client.client_name}


@router.delete("/{client_id}/avatars/{avatar_id}")
def unassign_avatar(
    client_id: UUID,
    avatar_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Block direct avatar detachment.

    Avatar assignments are released only by the client lifecycle path so an
    account cannot be accidentally orphaned outside client deletion/deactivation.
    """
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    raise HTTPException(
        status_code=409,
        detail="Avatar assignments are released only when the client is deleted or deactivated.",
    )
