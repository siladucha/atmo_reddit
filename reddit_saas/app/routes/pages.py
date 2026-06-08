"""Server-side rendered pages — full UI flow."""

from app.logging_config import get_logger
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
from app.services.access_control import can_approve_drafts
from app.version import __version__ as app_version
from app.config import get_settings as _get_settings

logger = get_logger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["app_version"] = app_version
templates.env.globals["posting_disabled"] = lambda: _get_settings().posting_disabled
templates.env.globals["app_env"] = _get_settings().app_env

from app.template_filters import register_filters
register_filters(templates.env)

ALLOWED_TABS = ("overview", "subreddits", "keywords", "avatars", "threads", "review", "reports")


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
    from app.models.subreddit import ClientSubredditAssignment

    client = db.query(Client).filter(Client.id == client_id).first()

    subreddits_count = (
        db.query(func.count(ClientSubredditAssignment.id))
        .filter(ClientSubredditAssignment.client_id == client_id, ClientSubredditAssignment.is_active.is_(True))
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
    from app.models.subreddit import ClientSubredditAssignment, Subreddit

    rows = (
        db.query(ClientSubredditAssignment)
        .join(Subreddit, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .filter(
            ClientSubredditAssignment.client_id == client_id,
            ClientSubredditAssignment.is_active.is_(True),
        )
        .all()
    )

    subreddits = [
        {
            "name": r.subreddit.subreddit_name,
            "type": r.type,
            "last_scraped_at": r.subreddit.last_scraped_at,
            "freshness": _freshness_color(r.subreddit.last_scraped_at),
        }
        for r in rows
    ]

    return {"subreddits": subreddits}


def _tab_keywords(client_id: UUID, db: Session) -> dict:
    """Return keywords for the client grouped by priority."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client or not client.keywords:
        return {"keywords": [], "keywords_by_priority": {"high": [], "medium": [], "low": [], "competitor": []}}

    keywords_by_priority = {
        "high": client.keywords.get("high", []),
        "medium": client.keywords.get("medium", []),
        "low": client.keywords.get("low", []),
        "competitor": client.keywords.get("competitor", []),
    }

    # Flat list for total count
    keywords_flat = []
    for priority in ("high", "medium", "low", "competitor"):
        for name in client.keywords.get(priority, []):
            keywords_flat.append({"name": name, "priority": priority})

    return {"keywords": keywords_flat, "keywords_by_priority": keywords_by_priority}


def _tab_avatars(client_id: UUID, db: Session, is_admin: bool) -> dict:
    """Return client avatars (all, not just active) enriched via build_avatar_view."""
    from app.services.avatars_query import build_avatar_view
    from app.services.safety import get_avatar_health

    raw_avatars = (
        db.query(Avatar)
        .filter(Avatar.client_ids.any(str(client_id)))
        .all()
    )

    # Batch-fetch related clients (same pattern as avatars page)
    all_client_ids: set[str] = set()
    for a in raw_avatars:
        for cid in (a.client_ids or []):
            if cid:
                all_client_ids.add(str(cid))
    client_by_id: dict = {}
    if all_client_ids:
        clients = db.query(Client).filter(Client.id.in_(all_client_ids)).all()
        client_by_id = {str(c.id): c for c in clients}

    # Enrich each avatar through the canonical path
    all_avatars = [build_avatar_view(a, get_avatar_health(db, a), client_by_id) for a in raw_avatars]
    client_avatars = all_avatars  # Show ALL avatars (active + inactive/frozen) to client

    unassigned_avatars: list = []
    if is_admin:
        all_active = db.query(Avatar).filter(Avatar.active.is_(True)).all()
        unassigned_avatars = [
            a for a in all_active
            if not a.client_ids or str(client_id) not in a.client_ids
        ]

    return {
        "all_avatars": all_avatars,
        "client_avatars": client_avatars,
        "unassigned_avatars": unassigned_avatars,
        "now_utc": datetime.now(timezone.utc),
    }


def _tab_threads(client_id: UUID, db: Session, tag: str | None = None) -> dict:
    """Return recent threads for the client, optionally filtered by tag."""
    from datetime import datetime, timezone

    query = db.query(RedditThread).filter(RedditThread.client_id == client_id)

    if tag and tag != "all":
        query = query.filter(RedditThread.tag == tag)

    threads = (
        query.order_by(RedditThread.created_at.desc())
        .limit(100)
        .all()
    )

    # Batch-fetch avatar assignments for "engage" threads (from CommentDraft)
    thread_ids = [t.id for t in threads]
    avatar_map: dict = {}
    if thread_ids:
        from app.models.avatar import Avatar
        avatar_assignments = (
            db.query(CommentDraft.thread_id, Avatar.reddit_username)
            .join(Avatar, Avatar.id == CommentDraft.avatar_id)
            .filter(
                CommentDraft.thread_id.in_(thread_ids),
                CommentDraft.client_id == client_id,
            )
            .all()
        )
        # Take first avatar per thread (most recent assignment)
        for tid, username in avatar_assignments:
            if tid not in avatar_map:
                avatar_map[tid] = username

    now = datetime.now(timezone.utc)
    thread_list = []
    for t in threads:
        # Calculate age in days from Reddit post date (or fallback to created_at)
        thread_date = t.reddit_created_at or t.created_at
        age_days = None
        if thread_date:
            age_days = int((now - thread_date).total_seconds() / 86400)

        thread_list.append({
            "title": t.post_title,
            "subreddit": t.subreddit,
            "tag": t.tag,
            "composite": t.composite,
            "url": t.url,
            "assigned_avatar": avatar_map.get(t.id),
            "reddit_created_at": t.reddit_created_at.strftime("%b %d, %H:%M") if t.reddit_created_at else None,
            "created_at": t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else None,
            "age_days": age_days,
        })

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
    ``current_client_name``, ``current_client_id``, and ``user_role_enum``
    into the template context for the nav bar.
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
        user_role_value = ""
        if db is not None:
            user_id = getattr(request.state, "user_id", None)
            if user_id:
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    is_superuser = user.is_superuser
                    current_user_name = user.full_name or user.email
                    user_role_value = user.user_role.value
                    if user.user_role.is_admin_level:
                        current_user_role = "Admin"
                    elif user.user_role.is_internal:
                        current_user_role = "Internal"
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
        ctx["user_role"] = user_role_value

    return templates.TemplateResponse(name=template, context=ctx, request=request)


# --- Guide ---

@router.get("/guide", response_class=HTMLResponse)
def guide_page(request: Request):
    return _render(request, "guide.html")


# --- Auth Pages ---

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str | None = None):
    context = {}
    if error == "no_access":
        context["error"] = "Your account is not configured yet. Please contact your administrator."
    return _render(request, "login.html", context)


@router.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = authenticate_user(db, email, password)
    if not user:
        return _render(request, "login.html", {"error": "Invalid credentials"})
    token = create_access_token(data={
        "sub": str(user.id),
        "email": user.email,
        "full_name": user.full_name or "",
        "role": user.user_role.value,
        "is_superuser": user.is_superuser,
    })
    response = RedirectResponse(url="/home", status_code=303)
    set_auth_cookie(response, token)
    return response


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    """Registration is disabled. Users are created by admins via /admin/users."""
    return RedirectResponse(url="/login", status_code=303)


@router.post("/register", response_class=HTMLResponse)
def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(""),
    db: Session = Depends(get_db),
):
    """Registration is disabled. Users are created by admins via /admin/users."""
    return RedirectResponse(url="/login", status_code=303)


@router.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    delete_auth_cookie(response)
    return response


# --- Root entry ---

@router.get("/", response_class=HTMLResponse)
def root_redirect(request: Request, db: Session = Depends(get_db)):
    """Route the authenticated user to the right home.

    - owner/partner → admin panel
    - qa → admin review queue (cross-client)
    - client_admin/client_manager → admin panel (role-specific dashboard)
    - client_viewer/b2c_user → their Client Hub
    """
    current_user = _get_current_user(request, db)

    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    role = current_user.user_role

    # Avatar manager goes directly to avatars section
    from app.models.user_role import UserRole
    if role == UserRole.avatar_manager:
        return RedirectResponse(url="/admin/avatars", status_code=303)

    # Admin-level roles go to admin panel
    if role.is_admin_level:
        return RedirectResponse(url="/admin/", status_code=303)

    # QA goes to admin review (cross-client)
    if role.is_internal:
        return RedirectResponse(url="/admin/", status_code=303)

    # Client admin/manager go to their Client Hub (not admin panel)
    if role in (UserRole.client_admin, UserRole.client_manager) and current_user.client_id:
        return RedirectResponse(url=f"/clients/{current_user.client_id}", status_code=303)

    # Client-scoped users (viewer, b2c) go to their hub
    if current_user.client_id:
        return RedirectResponse(url=f"/clients/{current_user.client_id}", status_code=303)

    # Authenticated but no client assigned — send to login error path.
    return RedirectResponse(url="/login", status_code=303)


@router.get("/home", response_class=HTMLResponse)
def home_redirect(request: Request, db: Session = Depends(get_db)):
    """Post-login entry point. Routes user to their role-appropriate dashboard."""
    current_user = _get_current_user(request, db)

    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    role = current_user.user_role

    # Avatar manager goes directly to avatars section
    from app.models.user_role import UserRole as _UR
    if role == _UR.avatar_manager:
        return RedirectResponse(url="/admin/avatars", status_code=303)

    if role.is_admin_level or role.is_internal:
        return RedirectResponse(url="/admin/", status_code=303)

    # Client admin/manager go to their Client Hub
    if role in (_UR.client_admin, _UR.client_manager) and current_user.client_id:
        return RedirectResponse(url=f"/clients/{current_user.client_id}", status_code=303)

    if current_user.client_id:
        return RedirectResponse(url=f"/clients/{current_user.client_id}", status_code=303)

    # User has no client assignment — cannot route anywhere meaningful
    logger.warning(
        "HOME_NO_DESTINATION | user_id=%s | email=%s | role=%s | client_id=%s",
        current_user.id, current_user.email, role.value, current_user.client_id,
    )
    return RedirectResponse(url="/login?error=no_access", status_code=303)


# --- Client Create ---

@router.get("/clients/new", response_class=HTMLResponse)
def client_new_page(request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    if current_user and not current_user.user_role.can_manage_clients:
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
    if current_user and not current_user.user_role.can_manage_clients:
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

    # Internal roles (owner, partner, qa) can view any client
    # Client-scoped users can only view their own client
    if current_user and not current_user.user_role.can_view_all_clients:
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

    # Internal roles can view any client; client-scoped users only their own
    if current_user and not current_user.user_role.can_view_all_clients:
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
    elif tab_name == "keywords":
        tab_context = _tab_keywords(client_id, db)
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


# --- Keywords Management (Client Hub) ---

@router.post("/clients/{client_id}/keywords/add", response_class=HTMLResponse)
def client_hub_add_keyword(
    client_id: UUID,
    request: Request,
    keyword: str = Form(...),
    priority: str = Form("medium"),
    db: Session = Depends(get_db),
):
    """Add a keyword from the Client Hub keywords tab."""
    from app.services import admin as admin_service

    current_user = _get_current_user(request, db)
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404)

    # Permission check: superuser or own client
    if current_user and not current_user.is_superuser:
        if current_user.client_id != client.id:
            raise HTTPException(status_code=403)

    flash = None
    name = keyword.strip()
    prio = priority.upper()

    valid, err = admin_service.validate_keyword(name, prio)
    if not valid:
        flash = {"level": "error", "message": err}
    else:
        try:
            user_id = current_user.id if current_user else None
            admin_service.add_keyword(db, client_id, name, prio, user_id)
            flash = {"level": "success", "message": f"Added keyword '{name}' ({priority})."}
        except ValueError as e:
            flash = {"level": "error", "message": str(e)}

    tab_context = _tab_keywords(client_id, db)
    tab_context["client"] = client
    tab_context["flash"] = flash
    return _render(request, "partials/client_hub_keywords.html", tab_context, db=db)


@router.post("/clients/{client_id}/keywords/remove", response_class=HTMLResponse)
def client_hub_remove_keyword(
    client_id: UUID,
    request: Request,
    keyword: str = Form(...),
    priority: str = Form(...),
    db: Session = Depends(get_db),
):
    """Remove a keyword from the Client Hub keywords tab."""
    current_user = _get_current_user(request, db)
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404)

    # Permission check: superuser or own client
    if current_user and not current_user.is_superuser:
        if current_user.client_id != client.id:
            raise HTTPException(status_code=403)

    # Remove keyword from JSONB
    if client.keywords and priority in client.keywords:
        kw_list = client.keywords.get(priority, [])
        if keyword in kw_list:
            kw_list.remove(keyword)
            # Force SQLAlchemy to detect JSONB change
            updated = dict(client.keywords)
            updated[priority] = kw_list
            client.keywords = updated
            db.commit()

    tab_context = _tab_keywords(client_id, db)
    tab_context["client"] = client
    tab_context["flash"] = {"level": "success", "message": f"Removed keyword '{keyword}'."}
    return _render(request, "partials/client_hub_keywords.html", tab_context, db=db)


@router.post("/clients/{client_id}/keywords/update", response_class=HTMLResponse)
def client_hub_update_keyword(
    client_id: UUID,
    request: Request,
    keyword: str = Form(...),
    old_priority: str = Form(...),
    new_priority: str = Form(...),
    db: Session = Depends(get_db),
):
    """Update keyword priority from the Client Hub keywords tab."""
    current_user = _get_current_user(request, db)
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404)

    # Permission check: superuser or own client
    if current_user and not current_user.is_superuser:
        if current_user.client_id != client.id:
            raise HTTPException(status_code=403)

    # Move keyword from old_priority to new_priority
    if client.keywords and old_priority != new_priority:
        updated = dict(client.keywords)
        old_list = updated.get(old_priority, [])
        if keyword in old_list:
            old_list.remove(keyword)
            updated[old_priority] = old_list
            new_list = updated.get(new_priority, [])
            new_list.append(keyword)
            updated[new_priority] = new_list
            client.keywords = updated
            db.commit()

    tab_context = _tab_keywords(client_id, db)
    tab_context["client"] = client
    tab_context["flash"] = {"level": "success", "message": f"Updated '{keyword}' to {new_priority.upper()}."}
    return _render(request, "partials/client_hub_keywords.html", tab_context, db=db)


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
    # Client-scoped users can only approve their own client's drafts
    if not current_user.user_role.can_view_all_clients:
        if current_user.client_id != draft.client_id:
            raise HTTPException(status_code=403)
    # Check draft approval permission (role-based + client flag for client_viewer)
    client = db.query(Client).filter(Client.id == draft.client_id).first()
    if not client or not can_approve_drafts(current_user, client):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
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

    # Self-learning loop: capture edit record
    try:
        from app.services.learning import LearningService

        thread = draft.thread
        if thread:
            if draft.edited_draft and draft.edited_draft != draft.ai_draft:
                learning_status = "approved"
            else:
                learning_status = "approved_unchanged"
            LearningService().capture_edit_record(db=db, draft=draft, thread=thread, status=learning_status)
            db.commit()
    except Exception:
        logger.warning("Learning capture failed for comment %s — review unaffected", comment_id, exc_info=True)

    # Return inline "posting mode" panel so user can mark as posted without switching tabs
    thread_url = ""
    if draft.thread and draft.thread.url:
        thread_url = draft.thread.url
    return HTMLResponse(f'''
    <div id="action-panel-{comment_id}" class="px-4 py-3 border-t border-green-700/50 bg-green-900/10">
        <div class="flex items-center gap-2 mb-2">
            <span class="text-green-400 text-xs font-medium">✓ Approved</span>
            <span class="text-gray-500 text-xs">— post to Reddit, then mark as posted:</span>
        </div>
        <form hx-post="/review/{comment_id}/posted" hx-target="#action-panel-{comment_id}" hx-swap="outerHTML"
              class="flex flex-wrap gap-2 items-center">
            <input type="url" name="reddit_comment_url" placeholder="Paste Reddit comment URL (optional)"
                   class="flex-1 min-w-[200px] px-3 py-1.5 bg-slate-night border border-slate-600 text-gray-200 rounded text-sm focus:outline-none focus:border-indigo-500">
            <button type="submit"
                    class="bg-purple-600 hover:bg-purple-500 text-white px-3 py-1.5 rounded text-sm font-medium">
                📤 Mark as Posted
            </button>
            {"<a href='" + thread_url + "' target='_blank' rel='noopener' class='text-xs text-indigo-400 hover:text-indigo-300'>Open thread ↗</a>" if thread_url else ""}
        </form>
    </div>
    ''')


@router.post("/review/{comment_id}/reject", response_class=HTMLResponse)
def reject_comment(comment_id: UUID, request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    if not current_user:
        raise HTTPException(status_code=403, detail="Authentication required")
    draft = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if not draft:
        raise HTTPException(status_code=404)
    if not current_user.user_role.can_view_all_clients:
        if current_user.client_id != draft.client_id:
            raise HTTPException(status_code=403)
    # Check draft approval permission (role-based + client flag for client_viewer)
    client = db.query(Client).filter(Client.id == draft.client_id).first()
    if not client or not can_approve_drafts(current_user, client):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
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

    # Self-learning loop: capture rejected draft
    try:
        from app.services.learning import LearningService

        thread = draft.thread
        if thread:
            LearningService().capture_edit_record(db=db, draft=draft, thread=thread, status="rejected")
            db.commit()
    except Exception:
        logger.warning("Learning capture failed for comment %s — review unaffected", comment_id, exc_info=True)

    return HTMLResponse(f'<div id="action-panel-{comment_id}" class="px-3 py-2 border-t border-red-700/30 bg-red-900/10 flex items-center gap-2"><span class="text-red-400 text-xs font-medium">✗ Rejected</span></div>')


@router.post("/review/{comment_id}/revert", response_class=HTMLResponse)
def revert_comment(comment_id: UUID, request: Request, db: Session = Depends(get_db)):
    """Revert a rejected/approved draft back to pending for re-review."""
    current_user = _get_current_user(request, db)
    if not current_user:
        raise HTTPException(status_code=403, detail="Authentication required")
    draft = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if not draft:
        raise HTTPException(status_code=404)
    if not current_user.is_superuser:
        if current_user.client_id != draft.client_id:
            raise HTTPException(status_code=403)
    # Check draft approval permission (role-based + client flag for client_viewer)
    client = db.query(Client).filter(Client.id == draft.client_id).first()
    if not client or not can_approve_drafts(current_user, client):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if draft.status == "posted":
        return HTMLResponse('<span class="text-amber-400 font-medium">Cannot revert posted comments</span>')
    old_status = draft.status
    draft.status = "pending"
    db.commit()
    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="revert_to_pending",
        entity_type="comment_draft",
        entity_id=draft.id,
        client_id=draft.client_id,
        details={"from_status": old_status, "avatar_username": draft.avatar.reddit_username if draft.avatar else None},
    )
    return HTMLResponse('<span class="text-indigo-400 font-medium">↩ Reverted to pending</span>')


@router.post("/review/{comment_id}/set-status", response_class=HTMLResponse)
def set_comment_status(
    comment_id: UUID,
    request: Request,
    new_status: str = Form(...),
    reason: str = Form(""),
    db: Session = Depends(get_db),
):
    """Universal status transition — any direction, with mandatory reason for backward moves."""
    current_user = _get_current_user(request, db)
    if not current_user:
        raise HTTPException(status_code=403, detail="Authentication required")
    draft = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if not draft:
        raise HTTPException(status_code=404)
    # Platform roles (owner, partner, avatar_manager, qa) can review any draft
    if not current_user.is_superuser and current_user.user_role.value not in ('owner', 'partner', 'avatar_manager', 'qa'):
        if current_user.client_id != draft.client_id:
            raise HTTPException(status_code=403)
    # Check draft approval permission (role-based + client flag for client_viewer)
    client = db.query(Client).filter(Client.id == draft.client_id).first()
    if not client or not can_approve_drafts(current_user, client):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    allowed_statuses = {"pending", "approved", "rejected", "posted"}
    if new_status not in allowed_statuses:
        return HTMLResponse(
            f'<span class="text-red-400 text-xs">Invalid status: {new_status}</span>',
            status_code=422,
        )

    old_status = draft.status
    if old_status == new_status:
        return HTMLResponse('<span class="text-gray-400 text-xs">Status unchanged</span>')

    # Determine if this is a backward transition (requires reason)
    status_order = {"pending": 0, "approved": 1, "rejected": 1, "posted": 2}
    is_backward = status_order.get(new_status, 0) < status_order.get(old_status, 0)

    if is_backward and not reason.strip():
        return HTMLResponse(
            '<span class="text-red-400 text-xs">Reason is required when moving status backward</span>',
            status_code=422,
        )

    # Apply transition
    draft.status = new_status
    if new_status == "posted" and old_status != "posted":
        draft.posted_at = datetime.now(timezone.utc)
    elif new_status != "posted" and old_status == "posted":
        # Clearing posted_at when reverting from posted
        draft.posted_at = None

    db.commit()

    # Audit log with full transition details
    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="status_transition",
        entity_type="comment_draft",
        entity_id=draft.id,
        client_id=draft.client_id,
        details={
            "old_status": old_status,
            "new_status": new_status,
            "reason": reason.strip() if reason.strip() else None,
            "is_backward": is_backward,
            "avatar_username": draft.avatar.reddit_username if draft.avatar else None,
            "thread_title": draft.thread.post_title if draft.thread else None,
        },
    )

    # Activity event
    try:
        from app.services.transparency import record_activity_event

        direction = "⬅ backward" if is_backward else "➡ forward"
        reason_text = f" — {reason.strip()}" if reason.strip() else ""
        message = f"Status {old_status}→{new_status} ({direction}){reason_text}"
        record_activity_event(db, "review", message, draft.client_id, {
            "draft_id": str(draft.id),
            "old_status": old_status,
            "new_status": new_status,
            "reason": reason.strip() if reason.strip() else None,
        })
    except Exception:
        pass

    # Color coding for response
    color_map = {
        "pending": ("indigo", "↩ Pending"),
        "approved": ("green", "✓ Approved"),
        "rejected": ("red", "✗ Rejected"),
        "posted": ("purple", "📤 Posted"),
    }
    color, label = color_map.get(new_status, ("gray", new_status))
    reason_html = f'<span class="text-gray-500 text-xs ml-2">({reason.strip()})</span>' if reason.strip() else ""

    # Self-learning loop: capture on approve/reject transitions
    if new_status in ("approved", "rejected"):
        try:
            from app.services.learning import LearningService

            thread = draft.thread
            if thread:
                if new_status == "rejected":
                    learning_status = "rejected"
                elif draft.edited_draft and draft.edited_draft != draft.ai_draft:
                    learning_status = "approved"
                else:
                    learning_status = "approved_unchanged"
                LearningService().capture_edit_record(db=db, draft=draft, thread=thread, status=learning_status)
                db.commit()
        except Exception:
            logger.warning("Learning capture failed for comment %s — review unaffected", comment_id, exc_info=True)

    return HTMLResponse(
        f'<div class="px-3 py-2 border-t border-{color}-700/30 bg-{color}-900/10 flex items-center gap-2">'
        f'<span class="text-{color}-400 text-xs font-medium">{label}</span>'
        f'<span class="text-gray-600 text-xs">was: {old_status}</span>'
        f'{reason_html}'
        f'</div>'
    )


@router.post("/review/{comment_id}/edit", response_class=HTMLResponse)
def edit_comment_text(comment_id: UUID, request: Request, edited_text: str = Form(...), db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    if not current_user:
        return HTMLResponse(
            '<span class="text-red-400 font-medium">✗ Not authenticated — please refresh the page</span>',
            status_code=200,
        )
    # Input validation: limit comment length
    if len(edited_text) > 2000:
        return HTMLResponse(
            '<span class="text-red-400 font-medium">✗ Text too long (max 2000 chars)</span>',
            status_code=200,
        )
    draft = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if not draft:
        return HTMLResponse(
            '<span class="text-red-400 font-medium">✗ Draft not found</span>',
            status_code=200,
        )
    if not current_user.is_superuser:
        if current_user.client_id != draft.client_id:
            return HTMLResponse(
                '<span class="text-red-400 font-medium">✗ Access denied</span>',
                status_code=200,
            )
    # Check draft approval permission (role-based + client flag for client_viewer)
    # Skip permission check for superusers or when draft has no client (hobby drafts)
    client = None
    if draft.client_id:
        client = db.query(Client).filter(Client.id == draft.client_id).first()
        if not current_user.is_superuser and (not client or not can_approve_drafts(current_user, client)):
            return HTMLResponse(
                '<span class="text-red-400 font-medium">✗ Insufficient permissions</span>',
                status_code=200,
            )

    # Safety check: brand mention protection (Phase 1/2 avatars cannot mention brand)
    from app.services.safety_blocks import check_safety_blocks
    avatar = draft.avatar
    if avatar and client:
        # Temporarily set edited_draft to check the new text
        original_edited = draft.edited_draft
        draft.edited_draft = edited_text
        block = check_safety_blocks(draft, avatar, client)
        draft.edited_draft = original_edited  # restore before potential abort
        if block:
            return HTMLResponse(
                f'<span class="text-red-400 font-medium">⚠ {block["message"]}</span>',
                status_code=200,
            )

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
    return HTMLResponse('<span class="text-green-400 font-medium">✓ Saved</span>')


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
    # Check draft approval permission (role-based + client flag for client_viewer)
    client = db.query(Client).filter(Client.id == draft.client_id).first()
    if not client or not can_approve_drafts(current_user, client):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

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

    return HTMLResponse(f'<div id="action-panel-{comment_id}" class="px-3 py-2 border-t border-purple-700/30 bg-purple-900/10 flex items-center gap-2"><span class="text-purple-400 text-xs font-medium">✓ Posted</span><span class="text-gray-500 text-xs">— karma tracking will update automatically</span></div>')


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
        from app.services.sanitize import ensure_username_bare

        reddit = get_reddit_client()
        redditor = reddit.redditor(ensure_username_bare(avatar.reddit_username))

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
    from app.services.avatars_query import build_avatar_view, batch_get_health_for_list

    # Collect all avatars across items + groups for a single batch health query
    all_avatars_set: dict[str, object] = {}
    for a in page.items:
        all_avatars_set[str(a.id)] = a
    for g in page.groups:
        for a in g.avatars:
            all_avatars_set[str(a.id)] = a

    all_avatars = list(all_avatars_set.values())
    health_by_id = batch_get_health_for_list(db, all_avatars)

    def _to_view(a):
        health = health_by_id.get(str(a.id), {})
        return build_avatar_view(a, health, page.client_by_id)

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
    from app.services.reddit_freshness import is_reddit_status_fresh
    from app.services.safety import get_avatar_health
    from app.models.client import Client as _Client

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    force = request.query_params.get("force") == "1"
    if force or not is_reddit_status_fresh(db, avatar):
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
    from app.services.reddit_freshness import reddit_status_manual_batch_limit
    from app.services.reddit_status import check_all_reddit_statuses

    current_user = _get_current_user(request, db)
    is_admin = bool(current_user and current_user.is_superuser)
    viewer_client_id = current_user.client_id if current_user else None

    f = AvatarFilter(q=q.strip(), status=status, client_id=client_id, sort=sort, view=view, group=group, page=page)
    page_data = list_avatars_page(db, f, viewer_client_id)

    force = request.query_params.get("force") == "1"
    batch_limit = reddit_status_manual_batch_limit(db)
    check_all_reddit_statuses(db, page_data.items[:batch_limit], force=force)

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

@router.get("/settings")
def settings_page_redirect():
    """Legacy /settings → redirect to admin settings."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin/settings", status_code=301)


@router.post("/settings")
def settings_save_redirect():
    """Legacy POST /settings → redirect to admin settings."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin/settings", status_code=301)


@router.post("/settings-save")
def settings_save_async_redirect():
    """Legacy POST /settings-save → redirect to admin settings."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin/settings", status_code=301)


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
