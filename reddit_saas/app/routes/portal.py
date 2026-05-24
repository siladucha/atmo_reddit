"""Client Portal — Routes.

New dark-themed client-facing portal. Separate from admin panel.
All routes require client access (RBAC enforced).
"""

import logging
from datetime import datetime, timezone, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import (
    get_current_user,
    verify_client_access_from_path,
)
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.subreddit import ClientSubreddit
from app.models.thread import RedditThread
from app.models.user import User
from app.models.user_role import UserRole
from app.schemas.client_portal import (
    ClientMetricsResponse,
    SafetyBlockResponse,
)
from app.services.safety_blocks import check_safety_blocks

logger = logging.getLogger(__name__)

router = APIRouter(
    dependencies=[Depends(verify_client_access_from_path)],
    tags=["client-portal"],
)
templates = Jinja2Templates(directory="app/templates")


# --- Helpers ---


def _get_sidebar_context(client_id: UUID, db: Session) -> dict:
    """Build sidebar context: pending_count, has_shadowbanned, client_name."""
    client = db.query(Client).filter(Client.id == client_id).first()
    client_name = client.client_name if client else "Client"

    # Pending drafts count
    pending_count = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            CommentDraft.status == "pending",
            Avatar.client_ids.any(str(client_id)),
        )
        .scalar()
    ) or 0

    # Any shadowbanned avatar?
    has_shadowbanned = (
        db.query(Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            Avatar.is_shadowbanned.is_(True),
        )
        .first()
        is not None
    )

    return {
        "client_id": str(client_id),
        "client_name": client_name,
        "pending_count": pending_count,
        "has_shadowbanned": has_shadowbanned,
    }


def _portal_render(
    request: Request,
    template: str,
    client_id: UUID,
    db: Session,
    active_page: str = "home",
    extra_context: dict | None = None,
) -> HTMLResponse:
    """Render a client portal template with sidebar context."""
    ctx = _get_sidebar_context(client_id, db)
    ctx["request"] = request
    ctx["active_page"] = active_page
    if extra_context:
        ctx.update(extra_context)
    return templates.TemplateResponse(name=template, context=ctx, request=request)


def _relative_time(dt: datetime | None) -> str:
    """Human-readable relative time string."""
    if not dt:
        return ""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt
    if diff < timedelta(minutes=1):
        return "just now"
    if diff < timedelta(hours=1):
        mins = int(diff.total_seconds() / 60)
        return f"{mins}m ago"
    if diff < timedelta(hours=24):
        hours = int(diff.total_seconds() / 3600)
        return f"{hours}h ago"
    days = diff.days
    if days == 1:
        return "yesterday"
    return f"{days}d ago"


# --- Page Routes ---


@router.get("/clients/{client_id}/home", response_class=HTMLResponse)
def portal_home(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal home screen."""
    sidebar = _get_sidebar_context(client_id, db)
    return _portal_render(
        request,
        "client/home.html",
        client_id,
        db,
        active_page="home",
        extra_context={"pending_count": sidebar["pending_count"]},
    )


@router.get("/clients/{client_id}/review", response_class=HTMLResponse)
def portal_review(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal review queue."""
    sidebar = _get_sidebar_context(client_id, db)
    return _portal_render(
        request,
        "client/review.html",
        client_id,
        db,
        active_page="review",
        extra_context={"pending_count": sidebar["pending_count"]},
    )



@router.get("/clients/{client_id}/avatars", response_class=HTMLResponse)
def portal_avatars(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal avatars screen."""
    avatars_raw = (
        db.query(Avatar)
        .filter(Avatar.client_ids.any(str(client_id)), Avatar.active.is_(True))
        .all()
    )
    avatars = []
    for a in avatars_raw:
        karma_total = (a.karma_post or 0) + (a.karma_comment or 0)
        if karma_total >= 1000:
            tier = "authority"
        elif karma_total >= 200:
            tier = "established"
        elif karma_total >= 50:
            tier = "building"
        else:
            tier = "newcomer"
        avatars.append({
            "id": str(a.id),
            "name": a.reddit_username,
            "bio": a.tone_principles or a.voice_profile_md or "",
            "warming_phase": a.warming_phase,
            "karma_tier": tier,
            "is_shadowbanned": a.is_shadowbanned,
            "last_active_at": _relative_time(a.last_health_check),
        })
    return _portal_render(
        request,
        "client/avatars.html",
        client_id,
        db,
        active_page="avatars",
        extra_context={"avatars": avatars},
    )


@router.get("/clients/{client_id}/settings", response_class=HTMLResponse)
def portal_settings(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal settings screen (placeholder)."""
    return _portal_render(
        request,
        "client/settings.html",
        client_id,
        db,
        active_page="settings",
    )

# --- HTMX Partials ---


@router.get("/clients/{client_id}/partials/metrics", response_class=HTMLResponse)
def portal_metrics_partial(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return metric cards partial with real data."""
    comments_posted = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            CommentDraft.status == "posted",
            Avatar.client_ids.any(str(client_id)),
        )
        .scalar()
    ) or 0

    total_upvotes = (
        db.query(func.coalesce(func.sum(CommentDraft.reddit_score), 0))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            CommentDraft.status == "posted",
            Avatar.client_ids.any(str(client_id)),
        )
        .scalar()
    ) or 0

    active_subreddits = (
        db.query(func.count(ClientSubreddit.id))
        .filter(
            ClientSubreddit.client_id == client_id,
            ClientSubreddit.is_active.is_(True),
        )
        .scalar()
    ) or 0

    metrics = {
        "comments_posted": comments_posted,
        "total_upvotes": int(total_upvotes),
        "active_subreddits": active_subreddits,
    }

    return templates.TemplateResponse(
        name="partials/client/metric_card.html",
        context={"request": request, "metrics": metrics},
        request=request,
    )


@router.get("/clients/{client_id}/partials/drafts", response_class=HTMLResponse)
def portal_drafts_partial(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return draft cards list for review queue."""
    drafts_raw = (
        db.query(CommentDraft)
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            CommentDraft.status == "pending",
            Avatar.client_ids.any(str(client_id)),
        )
        .order_by(CommentDraft.created_at.desc())
        .limit(50)
        .all()
    )

    client = db.query(Client).filter(Client.id == client_id).first()

    drafts = []
    for d in drafts_raw:
        avatar = db.query(Avatar).filter(Avatar.id == d.avatar_id).first()
        thread = (
            db.query(RedditThread).filter(RedditThread.id == d.thread_id).first()
            if d.thread_id
            else None
        )

        safety_block = None
        if avatar and client:
            safety_block = check_safety_blocks(d, avatar, client)

        thread_title = thread.title if thread else "Unknown thread"
        thread_body = thread.body if thread else ""
        body_excerpt = (
            (thread_body[:120] + "...") if len(thread_body or "") > 120 else (thread_body or "")
        )

        sub_name = ""
        if thread and thread.subreddit:
            sub_name = thread.subreddit
        elif hasattr(d, "subreddit_name") and d.subreddit_name:
            sub_name = d.subreddit_name

        drafts.append({
            "id": str(d.id),
            "avatar_name": avatar.reddit_username if avatar else "Unknown",
            "avatar_phase": avatar.warming_phase if avatar else 1,
            "subreddit_name": sub_name,
            "thread_title": thread_title,
            "thread_body_excerpt": body_excerpt,
            "comment_text": d.comment_text or "",
            "comment_approach": getattr(d, "comment_approach", None),
            "created_at_relative": _relative_time(d.created_at),
            "safety_block": safety_block,
        })

    last_draft_at = None
    if not drafts:
        last_draft = (
            db.query(CommentDraft.created_at)
            .join(Avatar, CommentDraft.avatar_id == Avatar.id)
            .filter(Avatar.client_ids.any(str(client_id)))
            .order_by(CommentDraft.created_at.desc())
            .first()
        )
        if last_draft:
            last_draft_at = _relative_time(last_draft[0])

    return templates.TemplateResponse(
        name="partials/client/drafts_list.html",
        context={
            "request": request,
            "drafts": drafts,
            "client_id": str(client_id),
            "last_draft_at": last_draft_at,
        },
        request=request,
    )


# --- API Actions ---


@router.post("/clients/{client_id}/drafts/{draft_id}/approve")
def portal_approve_draft(
    request: Request,
    client_id: UUID,
    draft_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Approve a draft. Returns empty HTML (card removed) or 422 on safety block."""
    if user.user_role == UserRole.client_viewer:
        raise HTTPException(status_code=403, detail="Viewers cannot approve drafts")

    draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    avatar = db.query(Avatar).filter(Avatar.id == draft.avatar_id).first()
    if not avatar or str(client_id) not in (avatar.client_ids or []):
        raise HTTPException(status_code=404, detail="Draft not found")

    client = db.query(Client).filter(Client.id == client_id).first()
    if client:
        block = check_safety_blocks(draft, avatar, client)
        if block:
            return JSONResponse(status_code=422, content=block)

    draft.status = "approved"
    draft.reviewed_at = datetime.now(timezone.utc)
    draft.reviewed_by = str(user.id)
    db.commit()

    logger.info(
        "Portal: draft approved | draft_id=%s | user=%s | client=%s",
        draft_id, user.email, client_id,
    )

    return HTMLResponse(
        content="",
        headers={"HX-Trigger": '{"showToast": {"type": "success", "message": "Approved"}}'},
    )


@router.post("/clients/{client_id}/drafts/{draft_id}/skip")
def portal_skip_draft(
    request: Request,
    client_id: UUID,
    draft_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Skip (reject) a draft. Returns empty HTML (card removed)."""
    if user.user_role == UserRole.client_viewer:
        raise HTTPException(status_code=403, detail="Viewers cannot skip drafts")

    draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    avatar = db.query(Avatar).filter(Avatar.id == draft.avatar_id).first()
    if not avatar or str(client_id) not in (avatar.client_ids or []):
        raise HTTPException(status_code=404, detail="Draft not found")

    draft.status = "rejected"
    draft.reviewed_at = datetime.now(timezone.utc)
    draft.reviewed_by = str(user.id)
    db.commit()

    logger.info(
        "Portal: draft skipped | draft_id=%s | user=%s | client=%s",
        draft_id, user.email, client_id,
    )

    return HTMLResponse(
        content="",
        headers={"HX-Trigger": '{"showToast": {"type": "success", "message": "Skipped"}}'},
    )


@router.post("/clients/{client_id}/drafts/{draft_id}/edit")
def portal_edit_draft(
    request: Request,
    client_id: UUID,
    draft_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edit + approve a draft. Captures edit diff for learning loop."""
    if user.user_role == UserRole.client_viewer:
        raise HTTPException(status_code=403, detail="Viewers cannot edit drafts")

    draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    avatar = db.query(Avatar).filter(Avatar.id == draft.avatar_id).first()
    if not avatar or str(client_id) not in (avatar.client_ids or []):
        raise HTTPException(status_code=404, detail="Draft not found")

    client = db.query(Client).filter(Client.id == client_id).first()
    if client:
        block = check_safety_blocks(draft, avatar, client)
        if block:
            return JSONResponse(status_code=422, content=block)

    draft.status = "approved"
    draft.reviewed_at = datetime.now(timezone.utc)
    draft.reviewed_by = str(user.id)
    db.commit()

    try:
        from app.services.learning import capture_edit_record
        capture_edit_record(db, draft, user_action="edit")
    except Exception as e:
        logger.warning("Failed to capture edit record: %s", e)

    logger.info(
        "Portal: draft edited+approved | draft_id=%s | user=%s | client=%s",
        draft_id, user.email, client_id,
    )

    return HTMLResponse(
        content="",
        headers={
            "HX-Trigger": '{"showToast": {"type": "success", "message": "Got it — we\'ll remember this for future drafts"}}'
        },
    )


# --- Redirect ---


@router.get("/clients/{client_id}", response_class=HTMLResponse)
def portal_redirect(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Redirect /clients/{id} to /clients/{id}/home for the new portal."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/clients/{client_id}/home", status_code=303)
