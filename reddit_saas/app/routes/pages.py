"""Server-side rendered pages — full UI flow."""

from datetime import datetime, timezone, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.database import get_db
from app.models.client import Client
from app.models.avatar import Avatar
from app.models.subreddit import ClientSubreddit
from app.models.thread import RedditThread
from app.models.comment_draft import CommentDraft
from app.models.post_draft import PostDraft
from app.models.ai_usage import AIUsageLog
from app.models.user import User
from app.services.auth import authenticate_user, create_user, create_access_token, get_user_by_email
from app.services.cookies import set_auth_cookie, delete_auth_cookie
from app.services import audit as audit_service

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

ALLOWED_TABS = ("overview", "subreddits", "avatars", "threads", "review", "reports")


def _resolve_tab(tab: str) -> str:
    """Return *tab* if it is a valid hub tab name, otherwise fall back to ``"overview"``."""
    return tab if tab in ALLOWED_TABS else "overview"


def _freshness_color(last_scraped_at: datetime | None) -> str:
    """Return a colour token indicating how recently a subreddit was scraped.

    * ``"green"``  — scraped within the last 24 hours
    * ``"yellow"`` — scraped within the last 72 hours
    * ``"red"``    — older than 72 hours **or** never scraped (``None``)
    """
    if last_scraped_at is None:
        return "red"
    now = datetime.now(timezone.utc)
    # Ensure we compare offset-aware datetimes
    if last_scraped_at.tzinfo is None:
        last_scraped_at = last_scraped_at.replace(tzinfo=timezone.utc)
    age = now - last_scraped_at
    if age <= timedelta(hours=24):
        return "green"
    if age <= timedelta(hours=72):
        return "yellow"
    return "red"


def _truncate_voice_profile(text: str | None, max_len: int = 200) -> str:
    """Return the first *max_len* characters of *text*, or ``""`` if *text* is ``None``."""
    if text is None:
        return ""
    return text[:max_len]


# ---------------------------------------------------------------------------
# Tab data loaders
# ---------------------------------------------------------------------------


def _tab_overview(client_id: UUID, db: Session) -> dict:
    """Return context dict with overview metrics and company profile fields."""
    client = db.query(Client).filter(Client.id == client_id).first()

    subreddits_count = (
        db.query(func.count(ClientSubreddit.id))
        .filter(ClientSubreddit.client_id == client_id, ClientSubreddit.is_active.is_(True))
        .scalar()
    )

    avatars_count = (
        db.query(func.count(Avatar.id))
        .filter(Avatar.active.is_(True), Avatar.client_ids.any(str(client_id)))
        .scalar()
    )

    threads_count = (
        db.query(func.count(RedditThread.id))
        .filter(RedditThread.client_id == client_id)
        .scalar()
    )

    engage_count = (
        db.query(func.count(RedditThread.id))
        .filter(RedditThread.client_id == client_id, RedditThread.tag == "engage")
        .scalar()
    )

    pending_comments = (
        db.query(func.count(CommentDraft.id))
        .filter(CommentDraft.client_id == client_id, CommentDraft.status == "pending")
        .scalar()
    )

    return {
        "subreddits_count": subreddits_count,
        "avatars_count": avatars_count,
        "threads_count": threads_count,
        "engage_count": engage_count,
        "pending_comments": pending_comments,
        "company_worldview": client.company_worldview if client else None,
        "company_problem": client.company_problem if client else None,
        "competitive_landscape": client.competitive_landscape if client else None,
    }


def _tab_subreddits(client_id: UUID, db: Session) -> dict:
    """Return active subreddits for the client with freshness colours."""
    rows = (
        db.query(ClientSubreddit)
        .filter(ClientSubreddit.client_id == client_id, ClientSubreddit.is_active.is_(True))
        .all()
    )

    subreddits = [
        {
            "name": r.subreddit_name,
            "type": r.type,
            "last_scraped_at": r.last_scraped_at,
            "freshness": _freshness_color(r.last_scraped_at),
        }
        for r in rows
    ]

    return {"subreddits": subreddits}


def _tab_avatars(client_id: UUID, db: Session, is_admin: bool) -> dict:
    """Return client avatars and (for admins) unassigned avatars."""
    client_avatars = (
        db.query(Avatar)
        .filter(Avatar.active.is_(True), Avatar.client_ids.any(str(client_id)))
        .all()
    )

    unassigned_avatars: list = []
    if is_admin:
        all_active = db.query(Avatar).filter(Avatar.active.is_(True)).all()
        unassigned_avatars = [
            a for a in all_active
            if not a.client_ids or str(client_id) not in a.client_ids
        ]

    return {
        "client_avatars": client_avatars,
        "unassigned_avatars": unassigned_avatars,
    }


def _tab_threads(client_id: UUID, db: Session, tag: str | None = None) -> dict:
    """Return recent threads for the client, optionally filtered by tag."""
    query = db.query(RedditThread).filter(RedditThread.client_id == client_id)

    if tag and tag != "all":
        query = query.filter(RedditThread.tag == tag)

    threads = (
        query.order_by(RedditThread.created_at.desc())
        .limit(100)
        .all()
    )

    thread_list = [
        {
            "title": t.post_title,
            "subreddit": t.subreddit,
            "tag": t.tag,
            "composite": t.composite,
            "url": t.url,
        }
        for t in threads
    ]

    return {"threads": thread_list}


def _tab_review(client_id: UUID, db: Session, status: str = "pending") -> dict:
    """Return enriched comment drafts for the client filtered by status."""
    from sqlalchemy.orm import joinedload

    drafts = (
        db.query(CommentDraft)
        .options(joinedload(CommentDraft.thread), joinedload(CommentDraft.avatar))
        .filter(CommentDraft.client_id == client_id, CommentDraft.status == status)
        .order_by(CommentDraft.created_at.desc())
        .limit(50)
        .all()
    )

    enriched: list[dict] = []
    for d in drafts:
        thread = d.thread  # already loaded via joinedload
        avatar = d.avatar  # already loaded via joinedload
        enriched.append({
            "draft": d,
            "thread_title": thread.post_title if thread else "",
            "thread_url": thread.url if thread else "",
            "thread_subreddit": thread.subreddit if thread else "",
            "thread_composite": thread.composite if thread else 0,
            "thread_alert": thread.alert if thread else False,
            "avatar_username": avatar.reddit_username if avatar else "",
            "engagement_mode": d.engagement_mode,
            "ai_draft": d.ai_draft or "",
        })

    return {"drafts": enriched, "review_status": status}


def _tab_reports(client_id: UUID, db: Session) -> dict:
    """Return aggregated stats for the client's reports tab."""
    # Comment draft counts by status
    status_rows = (
        db.query(CommentDraft.status, func.count(CommentDraft.id))
        .filter(CommentDraft.client_id == client_id)
        .group_by(CommentDraft.status)
        .all()
    )
    drafts_by_status = {row[0]: row[1] for row in status_rows}

    # Total AI cost
    total_ai_cost = (
        db.query(func.sum(AIUsageLog.cost_usd))
        .filter(AIUsageLog.client_id == client_id)
        .scalar()
    ) or 0

    # Thread counts by tag
    tag_rows = (
        db.query(RedditThread.tag, func.count(RedditThread.id))
        .filter(RedditThread.client_id == client_id)
        .group_by(RedditThread.tag)
        .all()
    )
    threads_by_tag = {row[0]: row[1] for row in tag_rows}

    # Active avatars count
    active_avatars = (
        db.query(func.count(Avatar.id))
        .filter(Avatar.active.is_(True), Avatar.client_ids.any(str(client_id)))
        .scalar()
    )

    return {
        "drafts_by_status": drafts_by_status,
        "total_ai_cost": float(total_ai_cost),
        "threads_by_tag": threads_by_tag,
        "active_avatars": active_avatars,
    }


def _get_current_user(request: Request, db: Session) -> User | None:
    """Look up the current authenticated user from request.state."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


def _render(request: Request, template: str, context: dict | None = None, db: Session | None = None) -> HTMLResponse:
    """Render a Jinja2 template with user context injected.

    Injects ``is_superuser``, ``current_user_name``, ``current_user_role``,
    ``current_client_name``, and ``current_client_id`` into the template
    context for the nav bar.
    """
    ctx = context or {}
    ctx["request"] = request

    # Inject user info for the base.html nav
    if "is_superuser" not in ctx:
        is_superuser = False
        current_user_name = ""
        current_user_role = ""
        current_client_name = ""
        current_client_id = None
        if db is not None:
            user_id = getattr(request.state, "user_id", None)
            if user_id:
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    is_superuser = user.is_superuser
                    current_user_name = user.full_name or user.email
                    if user.is_superuser:
                        current_user_role = "Admin"
                    elif user.client_id:
                        client = db.query(Client).filter(Client.id == user.client_id).first()
                        current_user_role = "Client"
                        current_client_name = client.client_name if client else ""
                        current_client_id = str(user.client_id)
                    else:
                        current_user_role = "User"
        ctx["is_superuser"] = is_superuser
        ctx["current_user_name"] = current_user_name
        ctx["current_user_role"] = current_user_role
        ctx["current_client_name"] = current_client_name
        ctx["current_client_id"] = current_client_id

    return templates.TemplateResponse(name=template, context=ctx, request=request)


# --- Guide ---

@router.get("/guide", response_class=HTMLResponse)
def guide_page(request: Request):
    return _render(request, "guide.html")


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
    set_auth_cookie(response, token)
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
    set_auth_cookie(response, token)
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    delete_auth_cookie(response)
    return response


# --- Root entry ---

@router.get("/", response_class=HTMLResponse)
def root_redirect(request: Request, db: Session = Depends(get_db)):
    """Route the authenticated user to the right home.

    Superusers go to the admin panel (single source of truth for system
    overview). Client users land directly on their Client_Hub.
    """
    current_user = _get_current_user(request, db)

    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    if current_user.is_superuser:
        return RedirectResponse(url="/admin/", status_code=303)

    if current_user.client_id:
        return RedirectResponse(url=f"/clients/{current_user.client_id}", status_code=303)

    # Authenticated but no client assigned — send to login error path.
    return RedirectResponse(url="/login", status_code=303)


# --- Client Create ---

@router.get("/clients/new", response_class=HTMLResponse)
def client_new_page(request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    if current_user and not current_user.is_superuser:
        raise HTTPException(status_code=403)
    return _render(request, "client_new.html", db=db)


@router.post("/clients/new", response_class=HTMLResponse)
def client_create_submit(
    request: Request,
    client_name: str = Form(...),
    brand_name: str = Form(...),
    company_profile: str = Form(""),
    company_worldview: str = Form(""),
    company_problem: str = Form(""),
    competitive_landscape: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if current_user and not current_user.is_superuser:
        raise HTTPException(status_code=403)
    client = Client(
        client_name=client_name,
        brand_name=brand_name,
        company_profile=company_profile or None,
        company_worldview=company_worldview or None,
        company_problem=company_problem or None,
        competitive_landscape=competitive_landscape or None,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return RedirectResponse(url=f"/clients/{client.id}", status_code=303)


# --- Client Hub ---

@router.get("/clients/{client_id}", response_class=HTMLResponse)
def client_hub(client_id: UUID, request: Request, tab: str = "overview", db: Session = Depends(get_db)):
    """Render the Client Hub shell page with the specified tab active."""
    current_user = _get_current_user(request, db)
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404)

    # Non-admin users can only view their own client
    if current_user and not current_user.is_superuser:
        if current_user.client_id != client.id:
            raise HTTPException(status_code=403)

    active_tab = _resolve_tab(tab)

    return _render(request, "client_hub.html", {
        "client": client,
        "active_tab": active_tab,
    }, db=db)


@router.get("/clients/{client_id}/tab/{tab_name}", response_class=HTMLResponse)
def client_hub_tab(
    client_id: UUID,
    tab_name: str,
    request: Request,
    tag: str | None = None,
    status: str = "pending",
    db: Session = Depends(get_db),
):
    """Return a tab's HTML partial (HTMX) or redirect to the hub page (non-HTMX)."""
    current_user = _get_current_user(request, db)
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404)

    # Non-admin users can only view their own client
    if current_user and not current_user.is_superuser:
        if current_user.client_id != client.id:
            raise HTTPException(status_code=403)

    if tab_name not in ALLOWED_TABS:
        raise HTTPException(status_code=404)

    # Non-HTMX requests get redirected to the full hub page
    if not _is_htmx(request):
        return RedirectResponse(url=f"/clients/{client_id}?tab={tab_name}", status_code=303)

    # Dispatch to the appropriate tab data loader
    is_admin = bool(current_user and current_user.is_superuser)

    if tab_name == "overview":
        tab_context = _tab_overview(client_id, db)
    elif tab_name == "subreddits":
        tab_context = _tab_subreddits(client_id, db)
    elif tab_name == "avatars":
        tab_context = _tab_avatars(client_id, db, is_admin)
    elif tab_name == "threads":
        tab_context = _tab_threads(client_id, db, tag=tag)
    elif tab_name == "review":
        tab_context = _tab_review(client_id, db, status=status)
    elif tab_name == "reports":
        tab_context = _tab_reports(client_id, db)
    else:
        tab_context = {}

    tab_context["client"] = client
    template_name = f"partials/client_hub_{tab_name}.html"

    return _render(request, template_name, tab_context, db=db)


@router.post("/clients/{client_id}/subreddits", response_class=HTMLResponse)
def client_hub_add_subreddit(
    client_id: UUID,
    request: Request,
    subreddit_name: str = Form(...),
    type: str = Form("professional"),
    db: Session = Depends(get_db),
):
    """Add a subreddit from the Client Hub form, then return the refreshed tab.

    On success, kicks off an immediate (synchronous) scrape so the user sees
    fresh threads in the same session. Errors (invalid name, duplicate, Reddit
    not found) are surfaced as a flash message inside the tab.
    """
    from app.services import admin as admin_service
    from app.services.scrape_queue import scrape_subreddit_immediate

    current_user = _get_current_user(request, db)
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404)

    if current_user and not current_user.is_superuser:
        if current_user.client_id != client.id:
            raise HTTPException(status_code=403)

    flash: dict | None = None
    name = subreddit_name.strip().lstrip("r/").lstrip("/")

    valid, err = admin_service.validate_subreddit_name(name)
    if not valid:
        flash = {"level": "error", "message": err}
    else:
        try:
            user_id = current_user.id if current_user else None
            admin_service.add_subreddit(db, client_id, name, type, user_id)
        except ValueError as e:
            flash = {"level": "error", "message": str(e)}
        else:
            # Subreddit row exists. Try a synchronous scrape so the tab
            # shows fresh data immediately. If Reddit says the sub doesn't
            # exist or is private, surface that — but the row stays added
            # (matches existing admin-panel behaviour).
            result = scrape_subreddit_immediate(db, name, str(client_id))
            if result.get("status") == "success":
                flash = {
                    "level": "success",
                    "message": (
                        f"Added r/{name} — scraped {result['posts_found']} posts "
                        f"({result['posts_new']} new)."
                    ),
                }
            else:
                flash = {
                    "level": "warning",
                    "message": (
                        f"Added r/{name}, but the initial scrape failed: "
                        f"{result.get('error', 'unknown error')}"
                    ),
                }

    tab_context = _tab_subreddits(client_id, db)
    tab_context["client"] = client
    tab_context["flash"] = flash
    return _render(request, "partials/client_hub_subreddits.html", tab_context, db=db)


# --- Review Comments ---

@router.get("/review", response_class=HTMLResponse)
def review_comments(
    request: Request,
    status: str = "pending",
    client_id: str | None = None,
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)

    # Superusers are routed through the admin panel for the unified review queue.
    if current_user and current_user.is_superuser:
        target = f"/admin/review?status={status}"
        if client_id:
            target += f"&client_id={client_id}"
        return RedirectResponse(url=target, status_code=303)

    query = (
        db.query(CommentDraft)
        .options(joinedload(CommentDraft.thread), joinedload(CommentDraft.avatar))
        .filter(CommentDraft.status == status)
    )

    # Non-admin: force filter to own client
    if current_user and not current_user.is_superuser and current_user.client_id:
        query = query.filter(CommentDraft.client_id == current_user.client_id)
    elif client_id:
        query = query.filter(CommentDraft.client_id == client_id)

    drafts = query.order_by(CommentDraft.created_at.desc()).limit(50).all()

    enriched = []
    for draft in drafts:
        enriched.append({"draft": draft, "thread": draft.thread, "avatar": draft.avatar})

    # Non-admin: only show own client in filter dropdown
    if current_user and not current_user.is_superuser and current_user.client_id:
        clients = db.query(Client).filter(Client.id == current_user.client_id, Client.is_active.is_(True)).all()
    else:
        clients = db.query(Client).filter(Client.is_active.is_(True)).all()

    return _render(request, "review.html", {
        "drafts": enriched,
        "status": status,
        "clients": clients,
        "selected_client": client_id,
    }, db=db)


# --- HTMX partials ---

@router.post("/review/{comment_id}/approve", response_class=HTMLResponse)
def approve_comment(comment_id: UUID, request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    if not current_user:
        raise HTTPException(status_code=403, detail="Authentication required")
    draft = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if not draft:
        raise HTTPException(status_code=404)
    # Non-admin users can only approve their own client's drafts
    if not current_user.is_superuser:
        if current_user.client_id != draft.client_id:
            raise HTTPException(status_code=403)
    draft.status = "approved"
    db.commit()
    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="approve",
        entity_type="comment_draft",
        entity_id=draft.id,
        client_id=draft.client_id,
        details={"avatar_username": draft.avatar.reddit_username if draft.avatar else None},
    )
    return HTMLResponse('<span class="text-green-600 font-medium">✓ Approved</span>')


@router.post("/review/{comment_id}/reject", response_class=HTMLResponse)
def reject_comment(comment_id: UUID, request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    if not current_user:
        raise HTTPException(status_code=403, detail="Authentication required")
    draft = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if not draft:
        raise HTTPException(status_code=404)
    if not current_user.is_superuser:
        if current_user.client_id != draft.client_id:
            raise HTTPException(status_code=403)
    draft.status = "rejected"
    db.commit()
    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="reject",
        entity_type="comment_draft",
        entity_id=draft.id,
        client_id=draft.client_id,
        details={"avatar_username": draft.avatar.reddit_username if draft.avatar else None},
    )
    return HTMLResponse('<span class="text-red-600 font-medium">✗ Rejected</span>')


@router.post("/review/{comment_id}/edit", response_class=HTMLResponse)
def edit_comment_text(comment_id: UUID, request: Request, edited_text: str = Form(...), db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    if not current_user:
        raise HTTPException(status_code=403, detail="Authentication required")
    # Input validation: limit comment length
    if len(edited_text) > 2000:
        return HTMLResponse(
            '<span class="text-red-600 font-medium">✗ Text too long (max 2000 chars)</span>',
            status_code=400,
        )
    draft = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if not draft:
        raise HTTPException(status_code=404)
    if not current_user.is_superuser:
        if current_user.client_id != draft.client_id:
            raise HTTPException(status_code=403)
    draft.edited_draft = edited_text
    db.commit()
    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="edit",
        entity_type="comment_draft",
        entity_id=draft.id,
        client_id=draft.client_id,
        details={"avatar_username": draft.avatar.reddit_username if draft.avatar else None},
    )
    return HTMLResponse('<span class="text-blue-600 font-medium">✓ Saved</span>')


@router.post("/review/{comment_id}/posted", response_class=HTMLResponse)
def mark_posted(
    comment_id: UUID,
    request: Request,
    reddit_comment_url: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if not current_user:
        raise HTTPException(status_code=403, detail="Authentication required")
    draft = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if not draft:
        raise HTTPException(status_code=404)
    if not current_user.is_superuser:
        if current_user.client_id != draft.client_id:
            raise HTTPException(status_code=403)

    from datetime import datetime, timezone
    draft.status = "posted"
    draft.posted_at = datetime.now(timezone.utc)
    if reddit_comment_url.strip():
        draft.reddit_comment_url = reddit_comment_url.strip()
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="mark_posted",
        entity_type="comment_draft",
        entity_id=draft.id,
        client_id=draft.client_id,
        details={"avatar_username": draft.avatar.reddit_username if draft.avatar else None},
    )

    # Piggyback phase evaluation after posting
    try:
        from app.services.phase import PhaseEvaluator, PhaseTransitionManager
        from app.services.phase_lock import PhaseTransitionLock
        from app.config import get_settings
        import redis

        avatar = draft.avatar
        if avatar and PhaseEvaluator().should_piggyback(avatar):
            result = PhaseEvaluator().evaluate(db, avatar)
            if result.action == "promote":
                redis_client = redis.from_url(get_settings().redis_url)
                lock = PhaseTransitionLock(redis_client)
                PhaseTransitionManager(lock).promote(db, avatar, result.criteria_values)
            elif result.action == "demote":
                redis_client = redis.from_url(get_settings().redis_url)
                lock = PhaseTransitionLock(redis_client)
                PhaseTransitionManager(lock).demote(db, avatar, result.target_phase, result.trigger_reason)
    except Exception:
        pass  # Never break the posting flow

    return HTMLResponse('<span class="text-purple-600 font-medium">✓ Posted</span>')


@router.post("/review/{comment_id}/update-score", response_class=HTMLResponse)
def update_comment_karma_score(
    comment_id: UUID,
    request: Request,
    reddit_score: int = Form(...),
    db: Session = Depends(get_db),
):
    """Update reddit_score for a posted comment and evaluate karma-based demotion."""
    current_user = _get_current_user(request, db)
    if not current_user:
        raise HTTPException(status_code=403, detail="Authentication required")

    from app.services.karma_feedback import update_comment_score, evaluate_and_demote_if_needed

    comment = update_comment_score(db, comment_id, reddit_score)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found or not posted")

    # Evaluate karma-based demotion
    demotion_result = None
    avatar = comment.avatar
    if avatar:
        demotion_result = evaluate_and_demote_if_needed(db, avatar)

    # Build response HTML
    score_color = "text-green-400" if reddit_score > 0 else ("text-red-400" if reddit_score < 0 else "text-gray-400")
    score_icon = "↑" if reddit_score > 0 else ("↓" if reddit_score < 0 else "·")

    html = f'<span class="{score_color} font-medium">{score_icon} {reddit_score}</span>'

    if demotion_result and demotion_result.get("demoted"):
        html += (
            f' <span class="text-red-400 text-xs ml-2">'
            f'⚠ Phase demoted → {demotion_result["new_phase"]}'
            f'</span>'
        )
    elif demotion_result and demotion_result.get("at_risk", False):
        html += (
            ' <span class="text-amber-400 text-xs ml-2">'
            '⚠ Karma at risk</span>'
        )

    return HTMLResponse(html)


@router.post("/review/{comment_id}/check-karma", response_class=HTMLResponse)
def check_karma_now(
    comment_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    """Manually trigger karma check for a single posted comment via Reddit API."""
    current_user = _get_current_user(request, db)
    if not current_user:
        raise HTTPException(status_code=403, detail="Authentication required")

    from app.models.comment_draft import CommentDraft

    comment = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if not comment or comment.status != "posted":
        return HTMLResponse('<span class="text-red-400 text-xs">Not found or not posted</span>')

    avatar = comment.avatar
    if not avatar or not avatar.reddit_username:
        return HTMLResponse('<span class="text-red-400 text-xs">No avatar linked</span>')

    # Try to fetch karma from Reddit
    try:
        from app.services.reddit import get_reddit_client

        reddit = get_reddit_client()
        redditor = reddit.redditor(avatar.reddit_username)

        draft_text = (comment.edited_draft or comment.ai_draft or "").strip()[:80].lower()
        found = False

        for reddit_comment in redditor.comments.new(limit=50):
            body_key = (reddit_comment.body or "").strip()[:80].lower()
            if body_key and body_key == draft_text:
                # Found the comment
                new_score = reddit_comment.score
                comment.reddit_score = new_score
                comment.last_karma_check_at = datetime.now(timezone.utc)

                # Also save the permalink if we don't have it
                if not comment.reddit_comment_url:
                    comment.reddit_comment_url = f"https://www.reddit.com{reddit_comment.permalink}"

                # Check if deleted
                if reddit_comment.body in ("[removed]", "[deleted]"):
                    comment.is_deleted = True
                    comment.deleted_detected_at = datetime.now(timezone.utc)

                db.commit()
                found = True

                score_color = "text-green-400" if new_score > 0 else ("text-red-400" if new_score < 0 else "text-gray-400")
                score_icon = "↑" if new_score > 0 else ("↓" if new_score < 0 else "·")
                html = f'<span class="{score_color} font-medium">{score_icon} {new_score}</span> <span class="text-gray-500 text-xs">checked now</span>'
                return HTMLResponse(html)

        if not found:
            comment.last_karma_check_at = datetime.now(timezone.utc)
            comment.is_deleted = True
            comment.deleted_detected_at = datetime.now(timezone.utc)
            db.commit()
            return HTMLResponse('<span class="text-amber-400 text-xs">⚠ Comment not found on Reddit (may be deleted)</span>')

    except Exception as e:
        return HTMLResponse(f'<span class="text-red-400 text-xs">Error: {str(e)[:60]}</span>')


# --- Threads ---

@router.get("/threads/{client_id}", response_class=HTMLResponse)
def threads_list(client_id: UUID, request: Request, tag: str | None = None, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)

    # Superusers go to the unified admin threads page (filtered to this client).
    if current_user and current_user.is_superuser:
        target = f"/admin/threads?client_id={client_id}"
        if tag:
            target += f"&tag={tag}"
        return RedirectResponse(url=target, status_code=303)

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404)

    # Non-admin: can only view own client's threads
    if current_user and not current_user.is_superuser:
        if current_user.client_id != client.id:
            raise HTTPException(status_code=403)

    query = db.query(RedditThread).filter(RedditThread.client_id == client_id)
    if tag:
        query = query.filter(RedditThread.tag == tag)
    threads = query.order_by(RedditThread.created_at.desc()).limit(100).all()

    return _render(request, "threads.html", {
        "client": client,
        "threads": threads,
        "selected_tag": tag,
    }, db=db)


# --- Avatars Page ---

def _build_results_context(db: Session, page, is_admin: bool):
    """Convert an AvatarPage into the {avatars, groups, ...} context for templates."""
    from app.services.avatars_query import build_avatar_view
    from app.services.safety import get_avatar_health

    def _to_view(a):
        return build_avatar_view(a, get_avatar_health(db, a), page.client_by_id)

    flat = [_to_view(a) for a in page.items]

    # Group views
    grouped: list[dict] = []
    for g in page.groups:
        grouped.append({
            "key": g.key,
            "title": g.title,
            "brand": g.brand,
            "client_id": str(g.client.id) if g.client else None,
            "counts": g.counts,
            "avatars": [_to_view(a) for a in g.avatars],
        })

    return {
        "avatars": flat,
        "groups": grouped,
        "f": page.filter,
        "page_obj": page,
        "is_admin": is_admin,
        "sort_options": __import__("app.services.avatars_query", fromlist=["SORT_OPTIONS"]).SORT_OPTIONS,
        "status_options": __import__("app.services.avatars_query", fromlist=["STATUS_OPTIONS"]).STATUS_OPTIONS,
        "group_options": __import__("app.services.avatars_query", fromlist=["GROUP_OPTIONS"]).GROUP_OPTIONS,
        "view_options": __import__("app.services.avatars_query", fromlist=["VIEW_OPTIONS"]).VIEW_OPTIONS,
    }


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


@router.get("/avatars-page", response_class=HTMLResponse)
def avatars_page(
    request: Request,
    q: str = "",
    status: str = "",
    client_id: str = "",
    sort: str = "username",
    view: str = "grid",
    group: str = "client",
    page: int = 1,
    db: Session = Depends(get_db),
):
    from app.services.avatars_query import AvatarFilter, list_avatars_page

    current_user = _get_current_user(request, db)

    # Superusers are routed through the admin panel.
    if current_user and current_user.is_superuser:
        from urllib.parse import urlencode
        params = {
            "q": q, "status": status, "client_id": client_id,
            "sort": sort, "view": view, "group": group, "page": page,
        }
        params = {k: v for k, v in params.items() if v not in ("", None, 1)}
        target = "/admin/avatars"
        if params:
            target += "?" + urlencode(params)
        return RedirectResponse(url=target, status_code=303)

    is_admin = False
    viewer_client_id = current_user.client_id if current_user else None

    f = AvatarFilter(
        q=q.strip(),
        status=status,
        client_id=client_id,
        sort=sort,
        view=view if view in ("grid", "table") else "grid",
        group=group if group in ("client", "none") else "client",
        page=page,
    )
    avatar_page = list_avatars_page(db, f, viewer_client_id)
    ctx = _build_results_context(db, avatar_page, is_admin)

    template = "partials/avatars_results.html" if _is_htmx(request) else "avatars.html"
    return _render(request, template, ctx, db=db)


@router.post("/avatars/{avatar_id}/check-reddit-status", response_class=HTMLResponse)
def check_avatar_reddit_status_htmx(avatar_id: UUID, request: Request, db: Session = Depends(get_db)):
    """HTMX endpoint: check one avatar, return refreshed card partial."""
    from app.services.avatars_query import build_avatar_view
    from app.services.reddit_status import check_reddit_status
    from app.services.safety import get_avatar_health
    from app.models.client import Client as _Client

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    check_reddit_status(db, avatar)

    current_user = _get_current_user(request, db)
    is_admin = bool(current_user and current_user.is_superuser)

    cids = [str(c) for c in (avatar.client_ids or []) if c]
    if cids:
        clients = db.query(_Client).filter(_Client.id.in_(cids)).all()
        client_by_id = {str(c.id): c for c in clients}
    else:
        client_by_id = {}

    enriched = build_avatar_view(avatar, get_avatar_health(db, avatar), client_by_id)

    template = "partials/avatar_row.html" if request.query_params.get("view") == "table" else "partials/avatar_card.html"
    return _render(request, template, {"a": enriched, "is_admin": is_admin})


@router.post("/avatars/check-reddit-status-all", response_class=HTMLResponse)
def check_all_avatars_reddit_status_htmx(
    request: Request,
    q: str = "",
    status: str = "",
    client_id: str = "",
    sort: str = "username",
    view: str = "grid",
    group: str = "client",
    page: int = 1,
    db: Session = Depends(get_db),
):
    """HTMX endpoint: check Reddit status for currently-filtered (and on flat view, currently-paged)
    avatars, then return the refreshed results partial."""
    from app.services.avatars_query import AvatarFilter, list_avatars_page
    from app.services.reddit_status import check_all_reddit_statuses

    current_user = _get_current_user(request, db)
    is_admin = bool(current_user and current_user.is_superuser)
    viewer_client_id = current_user.client_id if current_user else None

    f = AvatarFilter(q=q.strip(), status=status, client_id=client_id, sort=sort, view=view, group=group, page=page)
    page_data = list_avatars_page(db, f, viewer_client_id)

    check_all_reddit_statuses(db, page_data.items)

    # Re-run the page query so cached fields and counts reflect the new state
    page_data = list_avatars_page(db, f, viewer_client_id)
    ctx = _build_results_context(db, page_data, is_admin)
    return _render(request, "partials/avatars_results.html", ctx, db=db)


@router.get("/avatars/new", response_class=HTMLResponse)
def avatar_new_page(request: Request):
    """Redirect to admin avatar creation page."""
    return RedirectResponse(url="/admin/avatars/new", status_code=302)


@router.post("/avatars/new", response_class=HTMLResponse)
def avatar_create_submit(
    request: Request,
    reddit_username: str = Form(...),
    email_address: str = Form(""),
    voice_profile_md: str = Form(""),
    tone_principles: str = Form(""),
    hill_i_die_on: str = Form(""),
    helpful_mode_topics: str = Form(""),
    constraints: str = Form(""),
    hobby_subreddits: str = Form(""),
    db: Session = Depends(get_db),
):
    """Redirect POST to admin avatar creation."""
    return RedirectResponse(url="/admin/avatars/new", status_code=302)



# --- Admin ---

@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    from app.services.settings import get_all_settings, check_connections, init_defaults, seed_from_env
    init_defaults(db)
    seed_from_env(db)
    settings = get_all_settings(db)
    connections = check_connections(db)
    return _render(request, "settings.html", {
        "settings": settings,
        "connections": connections,
        "save_success": False,
    }, db=db)


@router.post("/settings", response_class=HTMLResponse)
def settings_save(request: Request, db: Session = Depends(get_db)):
    from app.services.settings import get_all_settings, set_setting, check_connections, DEFAULTS
    import asyncio

    # Get form data synchronously
    # FastAPI form parsing needs async, but we're in sync route
    # Use a workaround: read from the raw scope
    pass


# Use a separate async route for form handling
from starlette.requests import Request as StarletteRequest


@router.post("/settings-save", response_class=HTMLResponse)
async def settings_save_async(request: StarletteRequest, db: Session = Depends(get_db)):
    from app.services.settings import set_setting, get_all_settings, check_connections, DEFAULTS

    form = await request.form()
    for key in DEFAULTS:
        value = form.get(key, "")
        if isinstance(value, str) and value.strip():
            set_setting(db, key, value.strip())
        # Don't overwrite secrets with empty string (user left placeholder)

    settings = get_all_settings(db)
    connections = check_connections(db)
    return _render(request, "settings.html", {
        "settings": settings,
        "connections": connections,
        "save_success": True,
    }, db=db)


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
    }, db=db)
