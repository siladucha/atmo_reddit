"""Client CRUD routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models.client import Client
from app.models.avatar import Avatar
from app.models.subreddit import ClientSubreddit

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
def list_clients(active_only: bool = True, db: Session = Depends(get_db)):
    """List all clients."""
    query = db.query(Client)
    if active_only:
        query = query.filter(Client.is_active.is_(True))
    return query.order_by(Client.created_at.desc()).all()


@router.get("/{client_id}")
def get_client(client_id: UUID, db: Session = Depends(get_db)):
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
def create_client(data: ClientCreate, db: Session = Depends(get_db)):
    """Create a new client."""
    client = Client(**data.model_dump())
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.patch("/{client_id}")
def update_client(client_id: UUID, data: ClientUpdate, db: Session = Depends(get_db)):
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
def deactivate_client(client_id: UUID, db: Session = Depends(get_db)):
    """Deactivate a client (soft delete)."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    client.is_active = False
    db.commit()
    return {"status": "deactivated", "client_name": client.client_name}


# --- Subreddit management ---

@router.post("/{client_id}/subreddits")
def add_subreddit(client_id: UUID, data: SubredditAdd, db: Session = Depends(get_db)):
    """Add a subreddit to monitor for a client."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Check if already exists
    existing = (
        db.query(ClientSubreddit)
        .filter(
            ClientSubreddit.client_id == client_id,
            ClientSubreddit.subreddit_name == data.subreddit_name,
        )
        .first()
    )
    if existing:
        existing.is_active = True
        db.commit()
        return existing

    sub = ClientSubreddit(
        client_id=client_id,
        subreddit_name=data.subreddit_name,
        type=data.type,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


@router.delete("/{client_id}/subreddits/{subreddit_id}")
def remove_subreddit(client_id: UUID, subreddit_id: UUID, db: Session = Depends(get_db)):
    """Remove a subreddit from monitoring."""
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


# --- Avatar assignment ---

@router.post("/{client_id}/avatars/{avatar_id}")
def assign_avatar(client_id: UUID, avatar_id: UUID, db: Session = Depends(get_db)):
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
def unassign_avatar(client_id: UUID, avatar_id: UUID, db: Session = Depends(get_db)):
    """Remove an avatar from a client."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    client_id_str = str(client_id)
    if avatar.client_ids and client_id_str in avatar.client_ids:
        avatar.client_ids = [cid for cid in avatar.client_ids if cid != client_id_str]
        db.commit()

    return {"status": "unassigned", "avatar": avatar.reddit_username}
