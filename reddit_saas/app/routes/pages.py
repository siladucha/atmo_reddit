"""Server-side rendered pages — full UI flow."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.client import Client
from app.models.avatar import Avatar
from app.models.subreddit import ClientSubreddit
from app.models.thread import RedditThread
from app.models.comment_draft import CommentDraft
from app.models.post_draft import PostDraft
from app.models.ai_usage import AIUsageLog
from app.services.auth import authenticate_user, create_user, create_access_token, get_user_by_email

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _render(request: Request, template: str, context: dict | None = None) -> HTMLResponse:
    """Render a Jinja2 template — compatible with all Starlette versions."""
    ctx = context or {}
    ctx["request"] = request
    return templates.TemplateResponse(name=template, context=ctx, request=request)


# --- Auth Pages ---

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return _render(request, "login.html")


@router.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = authenticate_user(db, email, password)
    if not user:
        return _render(request, "login.html", {"error": "Invalid credentials"})
    token = create_access_token(data={"sub": str(user.id), "email": user.email})
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="access_token", value=token, httponly=True, max_age=86400)
    return response


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return _render(request, "register.html")


@router.post("/register", response_class=HTMLResponse)
def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(""),
    db: Session = Depends(get_db),
):
    if get_user_by_email(db, email):
        return _render(request, "register.html", {"error": "Email already registered"})
    user = create_user(db, email=email, password=password, full_name=full_name or None)
    token = create_access_token(data={"sub": str(user.id), "email": user.email})
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="access_token", value=token, httponly=True, max_age=86400)
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("access_token")
    return response


# --- Dashboard ---

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    clients = db.query(Client).filter(Client.is_active.is_(True)).all()
    total_avatars = db.query(func.count(Avatar.id)).filter(Avatar.active.is_(True)).scalar()
    pending_comments = db.query(func.count(CommentDraft.id)).filter(CommentDraft.status == "pending").scalar()
    pending_posts = db.query(func.count(PostDraft.id)).filter(PostDraft.status == "pending").scalar()
    ai_cost = db.query(func.sum(AIUsageLog.cost_usd)).scalar() or 0

    return _render(request, "dashboard.html", {
        "clients": clients,
        "total_avatars": total_avatars,
        "pending_comments": pending_comments,
        "pending_posts": pending_posts,
        "ai_cost": float(ai_cost),
    })


# --- Client Detail ---

@router.get("/clients/{client_id}", response_class=HTMLResponse)
def client_detail(client_id: UUID, request: Request, db: Session = Depends(get_db)):
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404)

    all_avatars = db.query(Avatar).filter(Avatar.active.is_(True)).all()
    client_avatars = [a for a in all_avatars if a.client_ids and str(client_id) in a.client_ids]
    unassigned_avatars = [a for a in all_avatars if not a.client_ids or str(client_id) not in a.client_ids]

    subreddits = (
        db.query(ClientSubreddit)
        .filter(ClientSubreddit.client_id == client_id, ClientSubreddit.is_active.is_(True))
        .all()
    )

    threads_count = db.query(func.count(RedditThread.id)).filter(RedditThread.client_id == client_id).scalar()
    engage_count = db.query(func.count(RedditThread.id)).filter(
        RedditThread.client_id == client_id, RedditThread.tag == "engage"
    ).scalar()

    return _render(request, "client_detail.html", {
        "client": client,
        "avatars": client_avatars,
        "unassigned_avatars": unassigned_avatars,
        "subreddits": subreddits,
        "threads_count": threads_count,
        "engage_count": engage_count,
    })


# --- Review Comments ---

@router.get("/review", response_class=HTMLResponse)
def review_comments(
    request: Request,
    status: str = "pending",
    client_id: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(CommentDraft).filter(CommentDraft.status == status)
    if client_id:
        query = query.filter(CommentDraft.client_id == client_id)

    drafts = query.order_by(CommentDraft.created_at.desc()).limit(50).all()

    enriched = []
    for draft in drafts:
        thread = db.query(RedditThread).filter(RedditThread.id == draft.thread_id).first()
        avatar = db.query(Avatar).filter(Avatar.id == draft.avatar_id).first()
        enriched.append({"draft": draft, "thread": thread, "avatar": avatar})

    clients = db.query(Client).filter(Client.is_active.is_(True)).all()

    return _render(request, "review.html", {
        "drafts": enriched,
        "status": status,
        "clients": clients,
        "selected_client": client_id,
    })


# --- HTMX partials ---

@router.post("/review/{comment_id}/approve", response_class=HTMLResponse)
def approve_comment(comment_id: UUID, db: Session = Depends(get_db)):
    draft = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if draft:
        draft.status = "approved"
        db.commit()
    return HTMLResponse('<span class="text-green-600 font-medium">✓ Approved</span>')


@router.post("/review/{comment_id}/reject", response_class=HTMLResponse)
def reject_comment(comment_id: UUID, db: Session = Depends(get_db)):
    draft = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if draft:
        draft.status = "rejected"
        db.commit()
    return HTMLResponse('<span class="text-red-600 font-medium">✗ Rejected</span>')


@router.post("/review/{comment_id}/edit", response_class=HTMLResponse)
def edit_comment_text(comment_id: UUID, edited_text: str = Form(...), db: Session = Depends(get_db)):
    draft = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if draft:
        draft.edited_draft = edited_text
        db.commit()
    return HTMLResponse('<span class="text-blue-600 font-medium">✓ Saved</span>')


@router.post("/review/{comment_id}/posted", response_class=HTMLResponse)
def mark_posted(comment_id: UUID, db: Session = Depends(get_db)):
    from datetime import datetime, timezone
    draft = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if draft:
        draft.status = "posted"
        draft.posted_at = datetime.now(timezone.utc)
        db.commit()
    return HTMLResponse('<span class="text-purple-600 font-medium">✓ Posted</span>')


# --- Threads ---

@router.get("/threads/{client_id}", response_class=HTMLResponse)
def threads_list(client_id: UUID, request: Request, tag: str | None = None, db: Session = Depends(get_db)):
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404)

    query = db.query(RedditThread).filter(RedditThread.client_id == client_id)
    if tag:
        query = query.filter(RedditThread.tag == tag)
    threads = query.order_by(RedditThread.created_at.desc()).limit(100).all()

    return _render(request, "threads.html", {
        "client": client,
        "threads": threads,
        "selected_tag": tag,
    })


# --- Avatars Page ---

@router.get("/avatars-page", response_class=HTMLResponse)
def avatars_page(request: Request, db: Session = Depends(get_db)):
    from app.services.safety import get_avatar_health
    avatars = db.query(Avatar).all()
    health_data = [get_avatar_health(db, a) for a in avatars]
    return _render(request, "avatars.html", {"avatars": health_data})


# --- Admin ---

@router.get("/admin-page", response_class=HTMLResponse)
def admin_page(request: Request, db: Session = Depends(get_db)):
    total_cost = db.query(func.sum(AIUsageLog.cost_usd)).scalar() or 0
    total_calls = db.query(func.count(AIUsageLog.id)).scalar()
    total_input = db.query(func.sum(AIUsageLog.input_tokens)).scalar() or 0
    total_output = db.query(func.sum(AIUsageLog.output_tokens)).scalar() or 0

    by_client = (
        db.query(
            Client.client_name,
            func.count(AIUsageLog.id).label("calls"),
            func.sum(AIUsageLog.cost_usd).label("cost"),
        )
        .join(AIUsageLog, AIUsageLog.client_id == Client.id)
        .group_by(Client.client_name)
        .all()
    )

    return _render(request, "admin.html", {
        "total_cost": float(total_cost),
        "total_calls": total_calls,
        "total_input": total_input,
        "total_output": total_output,
        "by_client": by_client,
    })
