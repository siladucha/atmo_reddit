"""Client Portal — Routes.

New dark-themed client-facing portal. Separate from admin panel.
All routes require client access (RBAC enforced).
"""

from app.logging_config import get_logger
from datetime import datetime, timezone, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
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
from app.services.trial_guard import is_trial_expired

logger = get_logger(__name__)


def _check_trial_not_expired(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Dependency that blocks POST actions for expired trial clients."""
    if not user.client_id:
        return
    client = db.query(Client).filter(Client.id == user.client_id).first()
    if client and is_trial_expired(client):
        raise HTTPException(
            status_code=403,
            detail="Trial expired. Please upgrade to continue using RAMP.",
        )


router = APIRouter(
    dependencies=[Depends(verify_client_access_from_path), Depends(_check_trial_not_expired)],
    tags=["client-portal"],
)
templates = Jinja2Templates(directory="app/templates")
from app.version import __version__ as app_version
from app.config import get_settings as _get_settings
templates.env.globals["app_version"] = app_version
templates.env.globals["posting_disabled"] = lambda: _get_settings().posting_disabled

from app.template_filters import register_filters
register_filters(templates.env)


def _karma_tier(karma: int) -> str:
    """Map raw karma to a named tier for client-facing display."""
    if karma >= 5000:
        return "Authority"
    elif karma >= 1000:
        return "Established"
    elif karma >= 200:
        return "Building"
    return "Newcomer"


def _avatar_display_name(avatar) -> str:
    """Return client-facing name: display_name if set, else reddit_username."""
    return avatar.display_name or avatar.reddit_username



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
        "is_trial": client.plan_type == "trial" if client else False,
        "trial_days_remaining": max(0, 14 - (datetime.now(timezone.utc) - client.created_at).days) if client and client.plan_type == "trial" else None,
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

    # Trial expiration enforcement: block access if trial > 14 days
    client_obj = db.query(Client).filter(Client.id == client_id).first()
    if client_obj and client_obj.plan_type == "trial":
        days_since_creation = (datetime.now(timezone.utc) - client_obj.created_at).days if client_obj.created_at else 0
        if days_since_creation > 14:
            return templates.TemplateResponse(
                name="client/trial_expired.html",
                context={"request": request, "client_id": str(client_id), "client_name": client_obj.client_name or ""},
                request=request,
            )
    ctx["request"] = request
    ctx["active_page"] = active_page

    # Inject user info from auth middleware
    ctx["user_name"] = getattr(request.state, "user_full_name", "") or ""
    ctx["user_email"] = getattr(request.state, "user_email", "") or ""
    ctx["user_role"] = getattr(request.state, "user_role", "") or ""

    # Inject usage/budget context for banners and upsells
    ctx.update(_get_usage_context(client_id, db))
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
    from app.models.comment_draft import CommentDraft
    from app.models.subreddit import ClientSubredditAssignment
    from app.models.strategy_document import StrategyDocument

    sidebar = _get_sidebar_context(client_id, db)

    # Quick counts for dashboard tiles
    avatars_total = (
        db.query(func.count(Avatar.id))
        .filter(Avatar.client_ids.any(str(client_id)))
        .scalar()
    ) or 0
    avatars_active = (
        db.query(func.count(Avatar.id))
        .filter(Avatar.client_ids.any(str(client_id)), Avatar.active.is_(True))
        .scalar()
    ) or 0

    subreddits_count = (
        db.query(func.count(ClientSubredditAssignment.id))
        .filter(ClientSubredditAssignment.client_id == client_id, ClientSubredditAssignment.is_active.is_(True))
        .scalar()
    ) or 0

    client_obj = db.query(Client).filter(Client.id == client_id).first()
    keywords_data = client_obj.keywords or {} if client_obj else {}
    keywords_count = sum(len(v) for v in keywords_data.values()) if isinstance(keywords_data, dict) else 0

    has_strategy = (
        db.query(StrategyDocument.id)
        .join(Avatar, StrategyDocument.avatar_id == Avatar.id)
        .filter(Avatar.client_ids.any(str(client_id)), StrategyDocument.is_current.is_(True))
        .first()
    ) is not None

    # This week stats
    now_utc = datetime.now(timezone.utc)
    week_start = now_utc - timedelta(days=7)
    week_posted = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
            CommentDraft.created_at >= week_start,
        )
        .scalar()
    ) or 0

    return _portal_render(
        request,
        "client/home.html",
        client_id,
        db,
        active_page="home",
        extra_context={
            "pending_count": sidebar["pending_count"],
            "avatars_total": avatars_total,
            "avatars_active": avatars_active,
            "subreddits_count": subreddits_count,
            "keywords_count": keywords_count,
            "has_strategy": has_strategy,
            "week_posted": week_posted,
        },
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
    can_review = user.user_role.can_review

    # Get avatars for filter selector
    avatars_for_filter = (
        db.query(Avatar)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            Avatar.active.is_(True),
            Avatar.is_frozen.is_(False),
        )
        .order_by(Avatar.reddit_username.asc())
        .all()
    )
    avatar_options = [{"id": str(a.id), "name": _avatar_display_name(a)} for a in avatars_for_filter]

    # Count approved (ready to post) and posted
    approved_count = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            CommentDraft.status == "approved",
            Avatar.client_ids.any(str(client_id)),
        )
        .scalar()
    ) or 0

    posted_count = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            CommentDraft.status == "posted",
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.created_at >= datetime.now(timezone.utc) - timedelta(days=30),
        )
        .scalar()
    ) or 0

    return _portal_render(
        request,
        "client/review.html",
        client_id,
        db,
        active_page="review",
        extra_context={
            "pending_count": sidebar["pending_count"],
            "approved_count": approved_count,
            "posted_count": posted_count,
            "can_review": can_review,
            "avatar_options": avatar_options,
        },
    )



@router.get("/clients/{client_id}/avatars", response_class=HTMLResponse)
def portal_avatars(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal avatars screen."""
    from app.services.safety import get_avatar_health
    from app.services.avatars_query import build_avatar_view

    avatars_raw = (
        db.query(Avatar)
        .filter(Avatar.client_ids.any(str(client_id)))
        .order_by(Avatar.active.desc(), Avatar.reddit_username.asc())
        .all()
    )

    # Batch-fetch clients for build_avatar_view
    all_client_ids: set[str] = set()
    for a in avatars_raw:
        for cid in (a.client_ids or []):
            if cid:
                all_client_ids.add(str(cid))
    client_by_id: dict = {}
    if all_client_ids:
        from app.models.client import Client as ClientModel
        clients_list = db.query(ClientModel).filter(ClientModel.id.in_(all_client_ids)).all()
        client_by_id = {str(c.id): c for c in clients_list}

    avatars = []
    for a in avatars_raw:
        health = get_avatar_health(db, a)
        view = build_avatar_view(a, health, client_by_id)
        # Client-facing overrides: hide reddit_username, show persona
        view["client_display_name"] = _avatar_display_name(a)
        view["display_name_is_fallback"] = not bool(a.display_name)
        view["client_persona_bio"] = a.persona_bio or ""
        view["karma_tier"] = _karma_tier((a.reddit_karma_comment or 0) + (a.reddit_karma_post or 0))
        avatars.append(view)
    # Check if user can onboard new avatars
    can_onboard = user.user_role in (
        UserRole.owner, UserRole.partner, UserRole.avatar_manager,
        UserRole.client_admin, UserRole.client_manager,
    )

    return _portal_render(
        request,
        "client/avatars.html",
        client_id,
        db,
        active_page="avatars",
        extra_context={"avatars": avatars, "can_onboard": can_onboard},
    )


@router.get("/clients/{client_id}/avatars/{avatar_id}", response_class=HTMLResponse)
def portal_avatar_detail(
    request: Request,
    client_id: UUID,
    avatar_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal avatar detail — voice profile, subreddits, activity."""
    from app.models.comment_draft import CommentDraft

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar or str(client_id) not in (avatar.client_ids or []):
        raise HTTPException(status_code=404, detail="Avatar not found")

    # Recent activity (last 30 days)
    now = datetime.now(timezone.utc)
    month_ago = now - timedelta(days=30)
    recent_drafts = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.created_at >= month_ago,
        )
        .order_by(CommentDraft.created_at.desc())
        .limit(20)
        .all()
    )

    activity = []
    for d in recent_drafts:
        # Resolve subreddit from thread or hobby_post
        subreddit_name = ""
        thread_title = ""
        if d.thread:
            subreddit_name = d.thread.subreddit or ""
            thread_title = (d.thread.post_title or "")[:60]
        elif d.hobby_post_id:
            from app.models.hobby import HobbySubreddit
            hobby = db.query(HobbySubreddit).filter(HobbySubreddit.id == d.hobby_post_id).first()
            if hobby:
                subreddit_name = hobby.subreddit or ""
                thread_title = (hobby.post_title or "")[:60]

        activity.append({
            "subreddit": subreddit_name,
            "thread_title": thread_title,
            "text": (d.edited_draft or d.ai_draft or "")[:120],
            "status": d.status,
            "reddit_score": d.reddit_score,
            "created_at": _relative_time(d.created_at),
            "posted_at": _relative_time(d.posted_at) if d.posted_at else "",
        })

    avatar_data = {
        "id": str(avatar.id),
        "display_name": _avatar_display_name(avatar),
        "display_name_is_fallback": not bool(avatar.display_name),
        "persona_bio": avatar.persona_bio or "",
        "karma_tier": _karma_tier((avatar.reddit_karma_comment or 0) + (avatar.reddit_karma_post or 0)),
        "active": avatar.active,
        "warming_phase": avatar.warming_phase,
        "is_frozen": avatar.is_frozen,
        "freeze_reason": avatar.freeze_reason,
        "voice_profile_md": avatar.voice_profile_md or "",
        "tone_principles": avatar.tone_principles or "",
        "speech_patterns": avatar.speech_patterns or "",
        "hill_i_die_on": avatar.hill_i_die_on or "",
        "helpful_mode_topics": avatar.helpful_mode_topics or "",
        "constraints": avatar.constraints or "",
        "vocabulary_lean": avatar.vocabulary_lean or "",
        "hobby_subreddits": avatar.hobby_subreddits or [],
        "business_subreddits": avatar.business_subreddits or [],
    }

    # Per-avatar karma sparkline (last 30 days)
    from sqlalchemy import cast, Date as SQLDate
    now_utc = datetime.now(timezone.utc)
    start_30d = now_utc - timedelta(days=30)

    avatar_daily = (
        db.query(
            cast(CommentDraft.posted_at, SQLDate).label("day"),
            func.count(CommentDraft.id).label("posted"),
            func.coalesce(func.sum(CommentDraft.reddit_score), 0).label("upvotes"),
        )
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
            CommentDraft.posted_at.isnot(None),
            CommentDraft.posted_at >= start_30d,
        )
        .group_by(cast(CommentDraft.posted_at, SQLDate))
        .order_by(cast(CommentDraft.posted_at, SQLDate))
        .all()
    )

    day_map_av = {r.day: {"posted": r.posted, "upvotes": int(r.upvotes)} for r in avatar_daily}
    avatar_karma_days = []
    for i in range(30):
        d = (now_utc - timedelta(days=29 - i)).date()
        entry = day_map_av.get(d, {"posted": 0, "upvotes": 0})
        avatar_karma_days.append({"date": d.strftime("%m/%d"), "posted": entry["posted"], "upvotes": entry["upvotes"]})

    avatar_total_30d = sum(d["upvotes"] for d in avatar_karma_days)
    avatar_posted_30d = sum(d["posted"] for d in avatar_karma_days)

    # Per-subreddit karma breakdown
    from app.models.subreddit_karma import SubredditKarma
    karma_rows = (
        db.query(SubredditKarma)
        .filter(SubredditKarma.avatar_id == avatar_id)
        .order_by(SubredditKarma.comment_karma.desc())
        .all()
    )
    subreddit_karma = [
        {
            "subreddit": sk.subreddit_name,
            "type": sk.subreddit_type,
            "comment_karma": sk.comment_karma,
            "post_karma": sk.post_karma,
            "total": sk.total_karma,
            "delta": sk.total_delta,
            "comment_count": sk.comment_count,
        }
        for sk in karma_rows
    ]

    return _portal_render(
        request,
        "client/avatar_detail.html",
        client_id,
        db,
        active_page="avatars",
        extra_context={
            "avatar": avatar_data,
            "activity": activity,
            "subreddit_karma": subreddit_karma,
            "karma_days": avatar_karma_days,
            "karma_total_30d": avatar_total_30d,
            "karma_posted_30d": avatar_posted_30d,
        },
    )



@router.get("/clients/{client_id}/activity", response_class=HTMLResponse)
def portal_activity_log(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal activity log — who did what and when."""
    from app.models.audit import AuditLog
    from app.models.user import User as UserModel

    now = datetime.now(timezone.utc)
    month_ago = now - timedelta(days=30)

    # Fetch audit logs for this client (last 30 days)
    logs_raw = (
        db.query(AuditLog)
        .filter(
            AuditLog.client_id == client_id,
            AuditLog.created_at >= month_ago,
        )
        .order_by(AuditLog.created_at.desc())
        .limit(100)
        .all()
    )

    # Also fetch logs where client_id is in details JSON (for portal actions)
    portal_logs = (
        db.query(AuditLog)
        .filter(
            AuditLog.details.isnot(None),
            AuditLog.details["client_id"].astext == str(client_id),
            AuditLog.created_at >= month_ago,
        )
        .order_by(AuditLog.created_at.desc())
        .limit(100)
        .all()
    )

    # Merge and deduplicate
    seen_ids = set()
    all_logs = []
    for log in logs_raw + portal_logs:
        if log.id not in seen_ids:
            seen_ids.add(log.id)
            all_logs.append(log)

    # Sort by time
    all_logs.sort(key=lambda x: x.created_at, reverse=True)
    all_logs = all_logs[:100]

    # Resolve user names
    user_ids = {log.user_id for log in all_logs if log.user_id}
    users_map = {}
    if user_ids:
        users = db.query(UserModel).filter(UserModel.id.in_(user_ids)).all()
        users_map = {u.id: u for u in users}

    # Format action labels
    action_labels = {
        "draft_approved": "Approved a draft",
        "draft_skipped": "Skipped a draft",
        "draft_marked_posted": "Marked as posted",
        "draft_edited": "Edited a draft",
        "mark_posted": "Marked as posted",
        "approve_draft": "Approved a draft",
        "reject_draft": "Rejected a draft",
        "create": "Created",
        "update": "Updated",
        "trigger_pipeline": "Triggered pipeline",
        "epg_rebuild": "Rebuilt EPG",
        "strategy_regenerate": "Regenerated strategy",
    }

    activity_items = []
    for log in all_logs:
        u = users_map.get(log.user_id)
        user_display = u.full_name or u.email if u else "System"
        details = log.details or {}

        activity_items.append({
            "action": action_labels.get(log.action, log.action.replace("_", " ").title()),
            "user": user_display,
            "entity_type": log.entity_type or "",
            "avatar": details.get("avatar", details.get("avatar_username", "")),
            "source": details.get("source", ""),
            "created_at": _relative_time(log.created_at),
            "created_at_full": log.created_at.strftime("%Y-%m-%d %H:%M") if log.created_at else "",
        })

    return _portal_render(
        request,
        "client/activity_log.html",
        client_id,
        db,
        active_page="activity",
        extra_context={"activity_items": activity_items},
    )


@router.get("/clients/{client_id}/settings", response_class=HTMLResponse)
def portal_settings(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal settings — ongoing campaign refinement."""
    from app.models.voice_feedback import VoiceFeedback
    from app.models.subreddit_request import SubredditRequest
    from app.models.subreddit import ClientSubredditAssignment, Subreddit

    client_obj = db.query(Client).filter(Client.id == client_id).first()

    # 1. Keywords from client JSONB
    keywords = client_obj.keywords or {} if client_obj else {}

    # 2. Build keyword → subreddit map
    # Get all active subreddit assignments for this client with their subreddit names
    assignments = (
        db.query(ClientSubredditAssignment)
        .join(Subreddit, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .filter(
            ClientSubredditAssignment.client_id == client_id,
            ClientSubredditAssignment.is_active.is_(True),
        )
        .all()
    )

    # For now, all keywords are considered monitored in all active subreddits
    all_subreddit_names = [a.subreddit.subreddit_name for a in assignments if a.subreddit]
    keyword_subreddit_map = {}
    for priority in ("high", "medium", "low"):
        for kw in keywords.get(priority, []):
            keyword_subreddit_map[kw] = all_subreddit_names

    # 3. Subreddits list (active assignments with name, type, status)
    subreddits = [
        {
            "name": a.subreddit.subreddit_name if a.subreddit else "",
            "type": a.type,
            "is_active": a.is_active,
        }
        for a in assignments
    ]

    # 4. Brand guardrails
    guardrails = client_obj.brand_guardrails or {} if client_obj else {}

    # 5. Voice feedback history (last 5)
    voice_feedback_history = (
        db.query(VoiceFeedback)
        .filter(VoiceFeedback.client_id == client_id)
        .order_by(VoiceFeedback.created_at.desc())
        .limit(5)
        .all()
    )

    # 6. Pending subreddit requests count
    pending_requests_count = (
        db.query(func.count(SubredditRequest.id))
        .filter(
            SubredditRequest.client_id == client_id,
            SubredditRequest.status == "pending",
        )
        .scalar()
    ) or 0

    # 7. Plan limit for subreddits
    plan_limits = {"seed": 3, "starter": 8, "growth": 15, "scale": 999}
    plan_type = client_obj.plan_type if client_obj else "starter"
    plan_limit = plan_limits.get(plan_type, 8)

    # 8. Current subreddit count
    current_subreddit_count = len(assignments)

    # 9. Can edit?
    can_edit = user.user_role in (UserRole.client_admin, UserRole.client_manager, UserRole.owner, UserRole.partner)

    return _portal_render(
        request,
        "client/settings.html",
        client_id,
        db,
        active_page="settings",
        extra_context={
            "keywords": keywords,
            "keyword_subreddit_map": keyword_subreddit_map,
            "subreddits": subreddits,
            "guardrails": guardrails,
            "voice_feedback_history": voice_feedback_history,
            "pending_requests_count": pending_requests_count,
            "plan_limit": plan_limit,
            "current_subreddit_count": current_subreddit_count,
            "can_edit": can_edit,
        },
    )


# --- Settings: Keywords Add/Remove ---


@router.post("/clients/{client_id}/settings/keywords/add", response_class=HTMLResponse)
def settings_keywords_add(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    keyword: str = Form(...),
    priority: str = Form("medium"),
):
    """Add a keyword to the client's keyword list."""
    from app.models.subreddit import ClientSubredditAssignment, Subreddit
    import json

    # RBAC check
    if user.user_role == UserRole.client_viewer:
        raise HTTPException(status_code=403, detail="Viewers cannot modify settings")

    client_obj = db.query(Client).filter(Client.id == client_id).first()
    if not client_obj:
        raise HTTPException(status_code=404, detail="Client not found")

    # Validate
    keyword = keyword.strip()
    error = None

    if not keyword:
        error = "Keyword cannot be empty."
    elif priority not in ("high", "medium", "low"):
        error = "Invalid priority level."
    else:
        # Check for duplicates across ALL priority levels
        keywords = client_obj.keywords or {}
        all_existing = []
        for p in ("high", "medium", "low"):
            all_existing.extend([k.lower() for k in keywords.get(p, [])])
        if keyword.lower() in all_existing:
            error = "This keyword already exists."

    # Build context for partial
    keywords = client_obj.keywords or {}

    if not error:
        # Add to correct priority list
        if priority not in keywords:
            keywords[priority] = []
        keywords[priority].append(keyword)
        client_obj.keywords = keywords
        # Force SQLAlchemy to detect JSONB mutation
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(client_obj, "keywords")
        db.commit()
        db.refresh(client_obj)
        keywords = client_obj.keywords or {}

    # Build keyword_subreddit_map
    assignments = (
        db.query(ClientSubredditAssignment)
        .join(Subreddit, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .filter(
            ClientSubredditAssignment.client_id == client_id,
            ClientSubredditAssignment.is_active.is_(True),
        )
        .all()
    )
    all_subreddit_names = [a.subreddit.subreddit_name for a in assignments if a.subreddit]
    keyword_subreddit_map = {}
    for p in ("high", "medium", "low"):
        for kw in keywords.get(p, []):
            keyword_subreddit_map[kw] = all_subreddit_names

    can_edit = user.user_role in (UserRole.client_admin, UserRole.client_manager, UserRole.owner, UserRole.partner)

    response = templates.TemplateResponse(
        name="partials/client/settings_keywords.html",
        context={
            "request": request,
            "keywords": keywords,
            "keyword_subreddit_map": keyword_subreddit_map,
            "can_edit": can_edit,
            "client_id": str(client_id),
            "error": error,
        },
        request=request,
    )

    if not error:
        response.headers["HX-Trigger"] = json.dumps({
            "showToast": {"type": "success", "message": "Keyword added \u2014 your avatars will now monitor this topic"}
        })

    return response


@router.post("/clients/{client_id}/settings/keywords/remove", response_class=HTMLResponse)
def settings_keywords_remove(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    keyword: str = Form(...),
    priority: str = Form(...),
):
    """Remove a keyword from the client's keyword list."""
    from app.models.subreddit import ClientSubredditAssignment, Subreddit
    import json

    # RBAC check
    if user.user_role == UserRole.client_viewer:
        raise HTTPException(status_code=403, detail="Viewers cannot modify settings")

    client_obj = db.query(Client).filter(Client.id == client_id).first()
    if not client_obj:
        raise HTTPException(status_code=404, detail="Client not found")

    # Remove keyword from specified priority list
    keywords = client_obj.keywords or {}
    if priority in keywords and keyword in keywords[priority]:
        keywords[priority].remove(keyword)
        client_obj.keywords = keywords
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(client_obj, "keywords")
        db.commit()
        db.refresh(client_obj)
        keywords = client_obj.keywords or {}

        # Trial signal: removed_keywords (negative)
        try:
            from app.services.trial_signal_hooks import record_trial_signal_background
            record_trial_signal_background(
                client_id=client_id,
                signal_type="removed_keywords",
                signal_category="negative",
                signal_value={"keyword": keyword, "priority": priority},
            )
        except Exception:
            pass


    # Build keyword_subreddit_map
    assignments = (
        db.query(ClientSubredditAssignment)
        .join(Subreddit, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .filter(
            ClientSubredditAssignment.client_id == client_id,
            ClientSubredditAssignment.is_active.is_(True),
        )
        .all()
    )
    all_subreddit_names = [a.subreddit.subreddit_name for a in assignments if a.subreddit]
    keyword_subreddit_map = {}
    for p in ("high", "medium", "low"):
        for kw in keywords.get(p, []):
            keyword_subreddit_map[kw] = all_subreddit_names

    can_edit = user.user_role in (UserRole.client_admin, UserRole.client_manager, UserRole.owner, UserRole.partner)

    response = templates.TemplateResponse(
        name="partials/client/settings_keywords.html",
        context={
            "request": request,
            "keywords": keywords,
            "keyword_subreddit_map": keyword_subreddit_map,
            "can_edit": can_edit,
            "client_id": str(client_id),
            "error": None,
        },
        request=request,
    )

    response.headers["HX-Trigger"] = json.dumps({
        "showToast": {"type": "success", "message": "Keyword removed"}
    })

    return response


# --- Settings: Subreddit Request ---


@router.post("/clients/{client_id}/settings/subreddits/request", response_class=HTMLResponse)
def settings_subreddit_request(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    subreddit_name: str = Form(...),
    note: str = Form(""),
    gotcha: str = Form(""),
):
    """Request to add a new subreddit (creates SubredditRequest record)."""
    # Honeypot check
    if gotcha:
        return HTMLResponse(content="<p>Request submitted.</p>", status_code=200)
    from app.models.subreddit_request import SubredditRequest
    from app.models.subreddit import ClientSubredditAssignment, Subreddit
    import json

    # RBAC check
    if user.user_role == UserRole.client_viewer:
        raise HTTPException(status_code=403, detail="Viewers cannot modify settings")

    client_obj = db.query(Client).filter(Client.id == client_id).first()
    if not client_obj:
        raise HTTPException(status_code=404, detail="Client not found")

    # Strip and clean subreddit name
    subreddit_name = subreddit_name.strip()
    if subreddit_name.startswith("r/"):
        subreddit_name = subreddit_name[2:]
    subreddit_name = subreddit_name.strip()

    # Plan limit check
    plan_limits = {"seed": 3, "starter": 8, "growth": 15, "scale": 999}
    plan_type = client_obj.plan_type if client_obj else "starter"
    plan_limit = plan_limits.get(plan_type, 8)

    assignments = (
        db.query(ClientSubredditAssignment)
        .join(Subreddit, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .filter(
            ClientSubredditAssignment.client_id == client_id,
            ClientSubredditAssignment.is_active.is_(True),
        )
        .all()
    )
    current_subreddit_count = len(assignments)

    error = None
    if not subreddit_name:
        error = "Subreddit name cannot be empty."
    elif current_subreddit_count >= plan_limit:
        error = "Subreddit limit reached. Add 5 more subreddits for $99/month — contact us to upgrade."

    # Build subreddits list for partial
    subreddits = [
        {
            "name": a.subreddit.subreddit_name if a.subreddit else "",
            "type": a.type,
            "is_active": a.is_active,
        }
        for a in assignments
    ]

    # Pending requests count
    pending_requests_count = (
        db.query(func.count(SubredditRequest.id))
        .filter(
            SubredditRequest.client_id == client_id,
            SubredditRequest.status == "pending",
        )
        .scalar()
    ) or 0

    if not error:
        # Create SubredditRequest record
        new_request = SubredditRequest(
            client_id=client_id,
            user_id=user.id,
            subreddit_name=subreddit_name,
            note=note.strip() if note else None,
            status="pending",
        )
        db.add(new_request)
        db.commit()
        pending_requests_count += 1

    can_edit = user.user_role in (UserRole.client_admin, UserRole.client_manager, UserRole.owner, UserRole.partner)

    response = templates.TemplateResponse(
        name="partials/client/settings_subreddits.html",
        context={
            "request": request,
            "subreddits": subreddits,
            "can_edit": can_edit,
            "client_id": str(client_id),
            "plan_limit": plan_limit,
            "current_subreddit_count": current_subreddit_count,
            "pending_requests_count": pending_requests_count,
            "error": error,
            "success": None,
        },
        request=request,
    )

    if not error:
        response.headers["HX-Trigger"] = json.dumps({
            "showToast": {"type": "success", "message": "Request sent \u2014 your account manager will review and add this subreddit"}
        })

    return response




# --- Settings: Brand Guardrails ---


@router.post("/clients/{client_id}/settings/guardrails", response_class=HTMLResponse)
def settings_guardrails_update(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    never_associate: str = Form(""),
    restricted_claims: str = Form(""),
    style_inspiration: str = Form(""),
):
    """Update brand guardrails for a client."""
    import json
    from sqlalchemy.orm.attributes import flag_modified

    # RBAC check
    if user.user_role == UserRole.client_viewer:
        raise HTTPException(status_code=403, detail="Viewers cannot modify settings")

    client_obj = db.query(Client).filter(Client.id == client_id).first()
    if not client_obj:
        raise HTTPException(status_code=404, detail="Client not found")

    # Parse never_associate: split by comma, strip each, remove empty, deduplicate
    tags_raw = [t.strip() for t in never_associate.split(",") if t.strip()]
    # Deduplicate preserving order
    seen = set()
    tags = []
    for t in tags_raw:
        if t.lower() not in seen:
            seen.add(t.lower())
            tags.append(t)

    # Build guardrails JSONB
    guardrails = {
        "never_associate": tags,
        "restricted_claims": restricted_claims.strip(),
        "style_inspiration": style_inspiration.strip(),
    }

    # Save to client
    client_obj.brand_guardrails = guardrails
    flag_modified(client_obj, "brand_guardrails")
    db.commit()
    db.refresh(client_obj)

    can_edit = user.user_role in (UserRole.client_admin, UserRole.client_manager, UserRole.owner, UserRole.partner)

    response = templates.TemplateResponse(
        name="partials/client/settings_guardrails.html",
        context={
            "request": request,
            "guardrails": guardrails,
            "can_edit": can_edit,
            "client_id": str(client_id),
            "error": None,
            "success": None,
        },
        request=request,
    )

    response.headers["HX-Trigger"] = json.dumps({
        "showToast": {"type": "success", "message": "Guardrails updated — we’ll apply these to all future drafts."}
    })

    return response


# --- Settings: Voice Feedback ---


@router.post("/clients/{client_id}/settings/voice-feedback", response_class=HTMLResponse)
def settings_voice_feedback(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    feedback_text: str = Form(...),
    gotcha: str = Form(""),
):
    """Submit voice/tone feedback for a client."""
    # Honeypot check
    if gotcha:
        return HTMLResponse(content="<p>Feedback submitted.</p>", status_code=200)
    import json
    from app.models.voice_feedback import VoiceFeedback

    # RBAC check
    if user.user_role == UserRole.client_viewer:
        raise HTTPException(status_code=403, detail="Viewers cannot modify settings")

    client_obj = db.query(Client).filter(Client.id == client_id).first()
    if not client_obj:
        raise HTTPException(status_code=404, detail="Client not found")

    can_edit = user.user_role in (UserRole.client_admin, UserRole.client_manager, UserRole.owner, UserRole.partner)

    # Strip and validate
    feedback_text = feedback_text.strip()
    error = None

    if not feedback_text:
        error = "Feedback cannot be empty."
    elif len(feedback_text) > 500:
        error = "Feedback must be 500 characters or less."

    if error:
        # Query history for re-render
        voice_feedback_history = (
            db.query(VoiceFeedback)
            .filter(VoiceFeedback.client_id == client_id)
            .order_by(VoiceFeedback.created_at.desc())
            .limit(5)
            .all()
        )
        return templates.TemplateResponse(
            name="partials/client/settings_voice_feedback.html",
            context={
                "request": request,
                "voice_feedback_history": voice_feedback_history,
                "can_edit": can_edit,
                "client_id": str(client_id),
                "error": error,
            },
            request=request,
        )

    # Create VoiceFeedback record
    new_feedback = VoiceFeedback(
        client_id=client_id,
        user_id=user.id,
        feedback_text=feedback_text,
    )
    db.add(new_feedback)
    db.commit()

    # Query last 5 feedback entries for history
    voice_feedback_history = (
        db.query(VoiceFeedback)
        .filter(VoiceFeedback.client_id == client_id)
        .order_by(VoiceFeedback.created_at.desc())
        .limit(5)
        .all()
    )

    response = templates.TemplateResponse(
        name="partials/client/settings_voice_feedback.html",
        context={
            "request": request,
            "voice_feedback_history": voice_feedback_history,
            "can_edit": can_edit,
            "client_id": str(client_id),
            "error": None,
        },
        request=request,
    )

    response.headers["HX-Trigger"] = json.dumps({
        "showToast": {"type": "success", "message": "Got it — we’ll apply this to future generations"}
    })

    return response


@router.get("/clients/{client_id}/subreddits", response_class=HTMLResponse)
def portal_subreddits(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal subreddits page."""
    from app.models.subreddit import ClientSubredditAssignment, Subreddit
    from app.models.scrape_log import ScrapeLog
    from app.services.settings import get_setting

    assignments = (
        db.query(ClientSubredditAssignment)
        .join(Subreddit, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .filter(ClientSubredditAssignment.client_id == client_id)
        .order_by(ClientSubredditAssignment.is_active.desc(), Subreddit.subreddit_name.asc())
        .all()
    )

    now_utc = datetime.now(timezone.utc)
    freshness_window_hours = int(get_setting(db, "scrape_freshness_window_hours") or "12")

    # Get last scrape logs
    all_sub_names = {a.subreddit.subreddit_name for a in assignments if a.subreddit}
    last_scrape_logs = {}
    for sub_name in all_sub_names:
        log = (
            db.query(ScrapeLog)
            .filter(ScrapeLog.subreddit_name == sub_name)
            .order_by(ScrapeLog.scraped_at.desc())
            .first()
        )
        if log:
            last_scrape_logs[sub_name] = log

    subreddits = []
    for a in assignments:
        sub = a.subreddit
        sub_name = sub.subreddit_name if sub else "unknown"
        last_scraped = sub.last_scraped_at if sub else None

        # Age display
        if last_scraped:
            age_seconds = (now_utc - last_scraped).total_seconds()
            age_hours = age_seconds / 3600
            if age_hours >= 24:
                age_display = f"{int(age_hours // 24)}d {int(age_hours % 24)}h ago"
            elif age_hours >= 1:
                age_display = f"{int(age_hours)}h {int((age_hours % 1) * 60)}m ago"
            else:
                age_display = f"{int(age_hours * 60)}m ago"
        else:
            age_hours = None
            age_display = "Never"

        # Last result
        scrape_log = last_scrape_logs.get(sub_name)
        last_result = None
        if scrape_log:
            last_result = {
                "posts_found": scrape_log.posts_found,
                "posts_new": scrape_log.posts_new,
                "error": scrape_log.errors,
            }

        # Next scrape
        next_scrape = None
        if a.is_active and last_scraped:
            next_at = last_scraped + timedelta(hours=freshness_window_hours)
            if next_at <= now_utc:
                next_scrape = "due now"
            else:
                remaining_hours = (next_at - now_utc).total_seconds() / 3600
                if remaining_hours >= 1:
                    next_scrape = f"in {int(remaining_hours)}h {int((remaining_hours % 1) * 60)}m"
                else:
                    next_scrape = f"in {int(remaining_hours * 60)}m"
        elif a.is_active and not last_scraped:
            next_scrape = "due now"

        # Status
        if not a.is_active:
            status = "paused"
        elif age_hours is not None and age_hours > freshness_window_hours:
            status = "stale"
        elif age_hours is not None:
            status = "fresh"
        else:
            status = "pending"

        subreddits.append({
            "name": sub_name,
            "type": a.type or "professional",
            "is_active": a.is_active,
            "status": status,
            "last_scraped": age_display,
            "last_result": last_result,
            "next_scrape": next_scrape,
        })

    can_edit = user.user_role in (UserRole.client_admin, UserRole.client_manager, UserRole.owner, UserRole.partner)

    return _portal_render(
        request,
        "client/subreddits.html",
        client_id,
        db,
        active_page="subreddits",
        extra_context={"subreddits": subreddits, "can_edit": can_edit},
    )


@router.get("/clients/{client_id}/keywords", response_class=HTMLResponse)
def portal_keywords(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal keywords page — with analytics like admin."""
    from app.services.keyword_analytics import get_keyword_stats_for_client

    keyword_stats = get_keyword_stats_for_client(db, client_id, days=90)

    can_edit = user.user_role in (UserRole.client_admin, UserRole.client_manager, UserRole.owner, UserRole.partner)

    return _portal_render(
        request,
        "client/keywords.html",
        client_id,
        db,
        active_page="keywords",
        extra_context={"keyword_stats": keyword_stats, "can_edit": can_edit},
    )


@router.get("/clients/{client_id}/strategy", response_class=HTMLResponse)
def portal_strategy(
    request: Request,
    client_id: UUID,
    avatar_id: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal current strategy page."""
    from app.models.strategy_document import StrategyDocument

    # Get all avatars for filter selector
    all_avatars = (
        db.query(Avatar)
        .filter(Avatar.client_ids.any(str(client_id)))
        .order_by(Avatar.reddit_username.asc())
        .all()
    )
    avatar_options = [{"id": str(a.id), "name": _avatar_display_name(a)} for a in all_avatars]

    # Filter avatars if selector used
    if avatar_id:
        avatars_with_strategy = [a for a in all_avatars if str(a.id) == avatar_id]
    else:
        avatars_with_strategy = all_avatars

    strategies = []
    for avatar in avatars_with_strategy:
        strategy = (
            db.query(StrategyDocument)
            .filter(
                StrategyDocument.avatar_id == avatar.id,
                StrategyDocument.is_current.is_(True),
            )
            .first()
        )
        if strategy:
            strategies.append({
                "avatar_id": str(avatar.id),
                "avatar_name": _avatar_display_name(avatar),
                "version": strategy.version,
                "is_approved": strategy.is_approved,
                "generated_at": _relative_time(strategy.generated_at),
                "document_md": strategy.document_md or "",
                "goals": strategy.goals or {},
            })

    return _portal_render(
        request,
        "client/strategy.html",
        client_id,
        db,
        active_page="strategy",
        extra_context={
            "strategies": strategies,
            "avatar_options": avatar_options,
            "selected_avatar_id": avatar_id,
        },
    )


@router.get("/clients/{client_id}/report", response_class=HTMLResponse)
def portal_report(
    request: Request,
    client_id: UUID,
    days: int = 30,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal report — full insights page with configurable period (30/60/90 days)."""
    from app.models.comment_draft import CommentDraft
    from app.models.thread import RedditThread
    from app.models.subreddit import ClientSubredditAssignment, Subreddit

    # Validate period
    if days not in (30, 60, 90):
        days = 30

    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=days)

    # --- Weekly stats ---
    week_generated = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(Avatar.client_ids.any(str(client_id)), CommentDraft.created_at >= week_start)
        .scalar()
    ) or 0

    week_approved = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status.in_(["approved", "posted"]),
            CommentDraft.created_at >= week_start,
        )
        .scalar()
    ) or 0

    week_posted = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
            CommentDraft.created_at >= week_start,
        )
        .scalar()
    ) or 0

    # --- Monthly stats ---
    month_posted = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
            CommentDraft.created_at >= month_start,
        )
        .scalar()
    ) or 0

    month_upvotes = (
        db.query(func.coalesce(func.sum(CommentDraft.reddit_score), 0))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
            CommentDraft.created_at >= month_start,
        )
        .scalar()
    ) or 0

    # --- Top performing comments (all time, sorted by score) ---
    top_comments_raw = (
        db.query(CommentDraft)
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
            CommentDraft.reddit_score.isnot(None),
            CommentDraft.reddit_score > 0,
        )
        .order_by(CommentDraft.reddit_score.desc())
        .limit(10)
        .all()
    )

    top_comments = []
    for c in top_comments_raw:
        draft_text = c.edited_draft or c.ai_draft or ""
        top_comments.append({
            "text": draft_text[:200],
            "score": c.reddit_score or 0,
            "subreddit": c.thread.subreddit if c.thread else "",
            "thread_title": (c.thread.post_title[:80] if c.thread else ""),
            "thread_url": c.thread.url if c.thread and c.thread.url else "",
            "avatar": _avatar_display_name(c.avatar) if c.avatar else "",
            "posted_at": _relative_time(c.posted_at),
            "reddit_url": c.reddit_comment_url or "",
        })

    # --- Subreddit performance ---
    # Get all client subreddits with activity counts
    client_subs = (
        db.query(ClientSubredditAssignment)
        .join(Subreddit, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .filter(ClientSubredditAssignment.client_id == client_id, ClientSubredditAssignment.is_active.is_(True))
        .all()
    )

    sub_performance = []
    for assignment in client_subs:
        sub_name = assignment.subreddit.subreddit_name if assignment.subreddit else ""
        # Count posted comments in this subreddit (last 30 days)
        activity_count = (
            db.query(func.count(CommentDraft.id))
            .join(Avatar, CommentDraft.avatar_id == Avatar.id)
            .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
            .filter(
                Avatar.client_ids.any(str(client_id)),
                RedditThread.subreddit == sub_name,
                CommentDraft.status == "posted",
                CommentDraft.created_at >= month_start,
            )
            .scalar()
        ) or 0

        total_upvotes = (
            db.query(func.coalesce(func.sum(CommentDraft.reddit_score), 0))
            .join(Avatar, CommentDraft.avatar_id == Avatar.id)
            .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
            .filter(
                Avatar.client_ids.any(str(client_id)),
                RedditThread.subreddit == sub_name,
                CommentDraft.status == "posted",
                CommentDraft.created_at >= month_start,
            )
            .scalar()
        ) or 0

        sub_performance.append({
            "name": sub_name,
            "type": assignment.type or "professional",
            "activity": activity_count,
            "upvotes": int(total_upvotes),
            "avg_score": round(total_upvotes / activity_count, 1) if activity_count > 0 else 0,
        })

    # Sort by activity descending
    sub_performance.sort(key=lambda x: x["activity"], reverse=True)

    # --- Threads scored (engagement funnel) ---
    threads_scored = (
        db.query(func.count(RedditThread.id))
        .filter(RedditThread.client_id == client_id, RedditThread.created_at >= month_start)
        .scalar()
    ) or 0

    threads_engage = (
        db.query(func.count(RedditThread.id))
        .filter(RedditThread.client_id == client_id, RedditThread.tag == "engage", RedditThread.created_at >= month_start)
        .scalar()
    ) or 0

    # --- Brand ratio ---
    # Count brand vs non-brand comments (hobby = non-brand, professional = potential brand)
    brand_comments = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
            CommentDraft.type == "professional",
            CommentDraft.created_at >= month_start,
        )
        .scalar()
    ) or 0

    non_brand_comments = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
            CommentDraft.type == "hobby",
            CommentDraft.created_at >= month_start,
        )
        .scalar()
    ) or 0

    total_period_comments = brand_comments + non_brand_comments
    brand_ratio = round(brand_comments / total_period_comments * 100) if total_period_comments > 0 else 0

    # --- Avg upvote per comment ---
    avg_upvote_report = round(int(month_upvotes) / month_posted, 1) if month_posted > 0 else 0

    # --- Period comparison (vs previous period) ---
    prev_start = month_start - timedelta(days=days)
    prev_posted = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
            CommentDraft.created_at >= prev_start,
            CommentDraft.created_at < month_start,
        )
        .scalar()
    ) or 0

    prev_upvotes_total = (
        db.query(func.coalesce(func.sum(CommentDraft.reddit_score), 0))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
            CommentDraft.created_at >= prev_start,
            CommentDraft.created_at < month_start,
        )
        .scalar()
    ) or 0

    posted_delta = month_posted - prev_posted
    posted_delta_pct = round(posted_delta / prev_posted * 100) if prev_posted > 0 else (100 if month_posted > 0 else 0)
    upvotes_delta = int(month_upvotes) - int(prev_upvotes_total)
    upvotes_delta_pct = round(upvotes_delta / int(prev_upvotes_total) * 100) if int(prev_upvotes_total) > 0 else (100 if int(month_upvotes) > 0 else 0)

    report = {
        "days": days,
        "week_generated": week_generated,
        "week_approved": week_approved,
        "week_posted": week_posted,
        "week_approval_rate": round(week_approved / week_generated * 100) if week_generated > 0 else 0,
        "month_posted": month_posted,
        "month_upvotes": int(month_upvotes),
        "threads_scored": threads_scored,
        "threads_engage": threads_engage,
        "engage_rate": round(threads_engage / threads_scored * 100) if threads_scored > 0 else 0,
        "top_comments": top_comments,
        "sub_performance": sub_performance,
        # New metrics
        "brand_comments": brand_comments,
        "non_brand_comments": non_brand_comments,
        "brand_ratio": brand_ratio,
        "avg_upvote": avg_upvote_report,
        "posted_delta": posted_delta,
        "posted_delta_pct": posted_delta_pct,
        "upvotes_delta": upvotes_delta,
        "upvotes_delta_pct": upvotes_delta_pct,
        "prev_posted": prev_posted,
    }

    # --- Day 1 Baseline ---
    client_obj = db.query(Client).filter(Client.id == client_id).first()
    baseline_date = client_obj.onboarding_completed_at or client_obj.created_at if client_obj else None
    days_since_start = (now - baseline_date).days if baseline_date else 0

    # All-time totals for "since Day 1" view
    alltime_posted = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
        )
        .scalar()
    ) or 0

    alltime_upvotes = (
        db.query(func.coalesce(func.sum(CommentDraft.reddit_score), 0))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
        )
        .scalar()
    ) or 0

    report["baseline_date"] = baseline_date.strftime("%b %d, %Y") if baseline_date else "—"
    report["days_since_start"] = days_since_start
    report["alltime_posted"] = alltime_posted
    report["alltime_upvotes"] = int(alltime_upvotes)

    # --- Thread Lifetime Visibility ---
    # Comments where 7d karma > 4h karma (still growing after initial spike)
    from app.models.karma_snapshot import KarmaSnapshot
    from sqlalchemy import and_

    # Subquery: comments with both 4h and 7d snapshots
    long_lived_raw = (
        db.query(
            KarmaSnapshot.comment_draft_id,
            KarmaSnapshot.check_window,
            KarmaSnapshot.karma_value,
            KarmaSnapshot.reply_count,
            KarmaSnapshot.subreddit,
        )
        .join(Avatar, KarmaSnapshot.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            KarmaSnapshot.check_window.in_(["4h", "7d"]),
            KarmaSnapshot.is_deleted.is_(False),
        )
        .all()
    )

    # Group by draft_id
    snapshot_by_draft: dict = {}
    for snap in long_lived_raw:
        draft_id = str(snap.comment_draft_id)
        if draft_id not in snapshot_by_draft:
            snapshot_by_draft[draft_id] = {}
        snapshot_by_draft[draft_id][snap.check_window] = {
            "karma": snap.karma_value,
            "replies": snap.reply_count,
            "subreddit": snap.subreddit,
        }

    # Find comments that grew between 4h and 7d
    growing_comments = []
    for draft_id, windows in snapshot_by_draft.items():
        if "4h" in windows and "7d" in windows:
            growth = windows["7d"]["karma"] - windows["4h"]["karma"]
            if growth > 0:
                growing_comments.append({
                    "draft_id": draft_id,
                    "karma_4h": windows["4h"]["karma"],
                    "karma_7d": windows["7d"]["karma"],
                    "growth": growth,
                    "replies_7d": windows["7d"]["replies"],
                    "subreddit": windows["7d"]["subreddit"] or "",
                })

    # Sort by growth and take top 5
    growing_comments.sort(key=lambda x: x["growth"], reverse=True)
    top_growing = growing_comments[:5]

    # Enrich with draft details
    long_lived_comments = []
    if top_growing:
        from uuid import UUID as UUIDType
        draft_ids = [UUIDType(c["draft_id"]) for c in top_growing]
        drafts_map = {
            str(d.id): d
            for d in db.query(CommentDraft).filter(CommentDraft.id.in_(draft_ids)).all()
        }
        for item in top_growing:
            draft = drafts_map.get(item["draft_id"])
            if draft:
                long_lived_comments.append({
                    "text": (draft.edited_draft or draft.ai_draft or "")[:150],
                    "subreddit": item["subreddit"],
                    "karma_4h": item["karma_4h"],
                    "karma_7d": item["karma_7d"],
                    "growth": item["growth"],
                    "replies": item["replies_7d"],
                    "thread_title": (draft.thread.post_title[:60] if draft.thread else ""),
                    "reddit_url": draft.reddit_comment_url or "",
                    "avatar": draft.avatar.display_name or draft.avatar.reddit_username if draft.avatar else "",
                })

    report["long_lived_comments"] = long_lived_comments
    report["total_growing"] = len(growing_comments)

    return _portal_render(
        request,
        "client/report.html",
        client_id,
        db,
        active_page="report",
        extra_context={"report": report},
    )

# --- Visibility (Share of Voice) ---


@router.get("/clients/{client_id}/visibility", response_class=HTMLResponse)
def portal_visibility(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal — AI Search Visibility (Share of Voice, Competitor Comparison)."""
    from app.models.geo_execution import GeoExecutionBatch, GeoFrequencyMetric, GeoQueryResult
    from app.models.geo_competitor import GeoCompetitor
    from app.models.geo_prompt import GeoPrompt
    from app.models.thread_score import ThreadScore

    client_obj = db.query(Client).filter(Client.id == client_id).first()
    if not client_obj:
        raise HTTPException(status_code=404, detail="Client not found")

    # --- GEO: Share of Voice ---
    # Get baseline batch
    baseline_batch = (
        db.query(GeoExecutionBatch)
        .filter(
            GeoExecutionBatch.client_id == client_id,
            GeoExecutionBatch.is_baseline.is_(True),
            GeoExecutionBatch.status == "completed",
        )
        .order_by(GeoExecutionBatch.started_at.asc())
        .first()
    )

    # Get latest completed batch
    latest_batch = (
        db.query(GeoExecutionBatch)
        .filter(
            GeoExecutionBatch.client_id == client_id,
            GeoExecutionBatch.status == "completed",
        )
        .order_by(GeoExecutionBatch.started_at.desc())
        .first()
    )

    # Brand appearance rate from latest batch
    latest_brand_rate = 0.0
    baseline_brand_rate = 0.0
    brand_rate_history = []

    if latest_batch:
        metrics = (
            db.query(GeoFrequencyMetric)
            .filter(GeoFrequencyMetric.execution_batch_id == latest_batch.id)
            .all()
        )
        if metrics:
            total_runs = sum(m.total_runs for m in metrics)
            total_brand = sum(m.brand_appearances for m in metrics)
            latest_brand_rate = round(total_brand / total_runs * 100, 1) if total_runs > 0 else 0

    if baseline_batch:
        base_metrics = (
            db.query(GeoFrequencyMetric)
            .filter(GeoFrequencyMetric.execution_batch_id == baseline_batch.id)
            .all()
        )
        if base_metrics:
            total_runs = sum(m.total_runs for m in base_metrics)
            total_brand = sum(m.brand_appearances for m in base_metrics)
            baseline_brand_rate = round(total_brand / total_runs * 100, 1) if total_runs > 0 else 0

    # History: all completed batches for trend
    all_batches = (
        db.query(GeoExecutionBatch)
        .filter(
            GeoExecutionBatch.client_id == client_id,
            GeoExecutionBatch.status == "completed",
        )
        .order_by(GeoExecutionBatch.started_at.asc())
        .all()
    )

    for batch in all_batches:
        batch_metrics = (
            db.query(GeoFrequencyMetric)
            .filter(GeoFrequencyMetric.execution_batch_id == batch.id)
            .all()
        )
        if batch_metrics:
            total_runs = sum(m.total_runs for m in batch_metrics)
            total_brand = sum(m.brand_appearances for m in batch_metrics)
            rate = round(total_brand / total_runs * 100, 1) if total_runs > 0 else 0
            brand_rate_history.append({
                "date": batch.started_at.strftime("%m/%d"),
                "rate": rate,
                "is_baseline": batch.is_baseline,
            })

    brand_rate_delta = round(latest_brand_rate - baseline_brand_rate, 1)

    # --- Competitor Comparison ---
    competitors = (
        db.query(GeoCompetitor)
        .filter(GeoCompetitor.client_id == client_id, GeoCompetitor.is_active.is_(True))
        .all()
    )

    competitor_data = []
    if latest_batch and competitors:
        for comp in competitors:
            # Count how many results mentioned this competitor in latest batch
            comp_mentions = (
                db.query(func.count(GeoQueryResult.id))
                .filter(
                    GeoQueryResult.execution_batch_id == latest_batch.id,
                    GeoQueryResult.competitors_mentioned.has_key(comp.competitor_name),
                )
                .scalar()
            ) or 0

            total_results = (
                db.query(func.count(GeoQueryResult.id))
                .filter(GeoQueryResult.execution_batch_id == latest_batch.id)
                .scalar()
            ) or 1

            comp_rate = round(comp_mentions / total_results * 100, 1) if total_results > 0 else 0
            competitor_data.append({
                "name": comp.competitor_name,
                "domain": comp.competitor_domain or "",
                "appearance_rate": comp_rate,
            })

        # Sort by appearance rate
        competitor_data.sort(key=lambda x: x["appearance_rate"], reverse=True)

    # --- High-Intent Thread Participation ---
    now = datetime.now(timezone.utc)
    month_ago = now - timedelta(days=30)

    high_intent_types = ["comparison", "recommendation", "troubleshooting", "buying", "evaluation"]

    total_posted_30d = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
            CommentDraft.created_at >= month_ago,
        )
        .scalar()
    ) or 0

    # Count posted comments in high-intent threads
    high_intent_posted = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .join(ThreadScore, (ThreadScore.thread_id == RedditThread.id) & (ThreadScore.client_id == client_id))
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
            CommentDraft.created_at >= month_ago,
            ThreadScore.intent.in_(high_intent_types),
        )
        .scalar()
    ) or 0

    high_intent_rate = round(high_intent_posted / total_posted_30d * 100) if total_posted_30d > 0 else 0

    # Intent breakdown
    intent_breakdown = (
        db.query(
            ThreadScore.intent,
            func.count(CommentDraft.id).label("count"),
        )
        .join(RedditThread, ThreadScore.thread_id == RedditThread.id)
        .join(CommentDraft, CommentDraft.thread_id == RedditThread.id)
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
            CommentDraft.created_at >= month_ago,
            ThreadScore.client_id == client_id,
            ThreadScore.intent.isnot(None),
        )
        .group_by(ThreadScore.intent)
        .order_by(func.count(CommentDraft.id).desc())
        .all()
    )

    intent_data = [{"intent": r.intent, "count": r.count, "is_high": r.intent in high_intent_types} for r in intent_breakdown]

    # --- GEO monitoring status ---
    geo_enabled = client_obj.geo_monitoring_enabled
    prompts_count = (
        db.query(func.count(GeoPrompt.id))
        .filter(GeoPrompt.client_id == client_id, GeoPrompt.is_active.is_(True))
        .scalar()
    ) or 0

    visibility = {
        "geo_enabled": geo_enabled,
        "prompts_count": prompts_count,
        "latest_brand_rate": latest_brand_rate,
        "baseline_brand_rate": baseline_brand_rate,
        "brand_rate_delta": brand_rate_delta,
        "brand_rate_history": brand_rate_history,
        "competitors": competitor_data,
        "latest_batch_date": latest_batch.started_at.strftime("%b %d, %Y") if latest_batch else None,
        "baseline_date": baseline_batch.started_at.strftime("%b %d, %Y") if baseline_batch else None,
        "high_intent_rate": high_intent_rate,
        "high_intent_posted": high_intent_posted,
        "total_posted_30d": total_posted_30d,
        "intent_breakdown": intent_data,
    }

    return _portal_render(
        request,
        "client/visibility.html",
        client_id,
        db,
        active_page="visibility",
        extra_context={"visibility": visibility, "brand_name": client_obj.brand_name},
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

    # Avg upvote rate per comment
    avg_upvote = 0.0
    if comments_posted > 0:
        avg_upvote = round(int(total_upvotes) / comments_posted, 1)

    # Distinct subreddits with posted comments
    subreddits_penetrated = (
        db.query(func.count(func.distinct(RedditThread.subreddit)))
        .join(CommentDraft, CommentDraft.thread_id == RedditThread.id)
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            CommentDraft.status == "posted",
            Avatar.client_ids.any(str(client_id)),
        )
        .scalar()
    ) or 0

    metrics = {
        "comments_posted": comments_posted,
        "total_upvotes": int(total_upvotes),
        "active_subreddits": active_subreddits,
        "avg_upvote": avg_upvote,
        "subreddits_penetrated": subreddits_penetrated,
    }

    return templates.TemplateResponse(
        name="partials/client/metric_card.html",
        context={"request": request, "metrics": metrics},
        request=request,
    )


@router.get("/clients/{client_id}/partials/karma-growth", response_class=HTMLResponse)
def portal_karma_growth_partial(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return karma growth sparkline partial -- daily posted comments + upvotes over 30 days."""
    from sqlalchemy import cast, Date as SQLDate

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=30)

    # Daily aggregates: posted count + sum of upvotes
    daily_rows = (
        db.query(
            cast(CommentDraft.posted_at, SQLDate).label("day"),
            func.count(CommentDraft.id).label("posted"),
            func.coalesce(func.sum(CommentDraft.reddit_score), 0).label("upvotes"),
        )
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
            CommentDraft.posted_at.isnot(None),
            CommentDraft.posted_at >= start,
        )
        .group_by(cast(CommentDraft.posted_at, SQLDate))
        .order_by(cast(CommentDraft.posted_at, SQLDate))
        .all()
    )

    # Build a 30-day array (fill empty days with 0)
    day_map = {r.day: {"posted": r.posted, "upvotes": int(r.upvotes)} for r in daily_rows}
    days = []
    for i in range(30):
        d = (now - timedelta(days=29 - i)).date()
        entry = day_map.get(d, {"posted": 0, "upvotes": 0})
        days.append({"date": d.strftime("%m/%d"), "posted": entry["posted"], "upvotes": entry["upvotes"]})

    # Cumulative karma growth
    cumulative = 0
    for d in days:
        cumulative += d["upvotes"]
        d["cumulative"] = cumulative

    # Period comparison (this 30d vs previous 30d)
    prev_start = start - timedelta(days=30)
    prev_upvotes = (
        db.query(func.coalesce(func.sum(CommentDraft.reddit_score), 0))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
            CommentDraft.posted_at.isnot(None),
            CommentDraft.posted_at >= prev_start,
            CommentDraft.posted_at < start,
        )
        .scalar()
    ) or 0

    curr_upvotes = sum(d["upvotes"] for d in days)
    delta = curr_upvotes - int(prev_upvotes)
    delta_pct = round(delta / int(prev_upvotes) * 100) if int(prev_upvotes) > 0 else (100 if curr_upvotes > 0 else 0)

    return templates.TemplateResponse(
        name="partials/client/karma_growth.html",
        context={
            "request": request,
            "days": days,
            "total_upvotes_period": curr_upvotes,
            "delta": delta,
            "delta_pct": delta_pct,
        },
        request=request,
    )


@router.get("/clients/{client_id}/partials/drafts", response_class=HTMLResponse)
def portal_drafts_partial(
    request: Request,
    client_id: UUID,
    status: str = "pending",
    avatar_id: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return draft cards list for review queue (supports pending/approved/posted tabs)."""
    valid_statuses = {"pending", "approved", "posted"}
    if status not in valid_statuses:
        status = "pending"

    query = (
        db.query(CommentDraft)
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            CommentDraft.status == status,
            Avatar.client_ids.any(str(client_id)),
            Avatar.active.is_(True),
            Avatar.is_frozen.is_(False),
        )
    )
    if avatar_id:
        query = query.filter(CommentDraft.avatar_id == avatar_id)

    # For posted tab, limit to last 30 days
    if status == "posted":
        query = query.filter(
            CommentDraft.created_at >= datetime.now(timezone.utc) - timedelta(days=30)
        )

    drafts_raw = query.order_by(CommentDraft.created_at.desc()).limit(50).all()

    client = db.query(Client).filter(Client.id == client_id).first()

    drafts = []
    for d in drafts_raw:
        avatar = db.query(Avatar).filter(Avatar.id == d.avatar_id).first()
        thread = (
            db.query(RedditThread).filter(RedditThread.id == d.thread_id).first()
            if d.thread_id
            else None
        )

        # For hobby drafts, get info from HobbySubreddit
        hobby_post = None
        if not thread and d.hobby_post_id:
            from app.models.hobby import HobbySubreddit
            hobby_post = db.query(HobbySubreddit).filter(HobbySubreddit.id == d.hobby_post_id).first()

        safety_block = None
        if avatar and client:
            safety_block = check_safety_blocks(d, avatar, client)

        if thread:
            thread_title = thread.post_title
            thread_body = thread.post_body or ""
            sub_name = thread.subreddit or ""
            thread_url = thread.url if thread.url else (f"https://reddit.com/r/{sub_name}/comments/{thread.reddit_native_id}" if sub_name else "")
        elif hobby_post:
            thread_title = hobby_post.post_title or "Hobby post"
            thread_body = hobby_post.post_body or ""
            sub_name = hobby_post.subreddit or ""
            thread_url = hobby_post.url or hobby_post.permalink or (f"https://reddit.com/r/{sub_name}/comments/{hobby_post.post_id}" if hobby_post.post_id else "")
        else:
            thread_title = "Unknown thread"
            thread_body = ""
            sub_name = ""
            thread_url = ""

        body_excerpt = (
            (thread_body[:120] + "...") if len(thread_body or "") > 120 else (thread_body or "")
        )

        # Use Reddit's actual post creation date (not when we scraped it)
        thread_date = None
        if thread:
            thread_date = thread.reddit_created_at or thread.created_at
        elif hobby_post:
            thread_date = getattr(hobby_post, "reddit_created_at", None) or getattr(hobby_post, "created_at", None)

        drafts.append({
            "id": str(d.id),
            "avatar_name": _avatar_display_name(avatar) if avatar else "Unknown",
            "avatar_phase": avatar.warming_phase if avatar else 1,
            "subreddit_name": sub_name,
            "thread_title": thread_title,
            "thread_url": thread_url,
            "thread_body_excerpt": body_excerpt,
            "comment_text": d.edited_draft or d.ai_draft or "",
            "comment_approach": getattr(d, "comment_approach", None),
            "created_at_relative": _relative_time(thread_date) if thread_date else _relative_time(d.created_at),
            "safety_block": safety_block,
            "is_hobby": d.type == "hobby",
            "reddit_comment_url": d.reddit_comment_url or "",
            "posted_at": _relative_time(d.posted_at) if d.posted_at else "",
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
            "can_review": user.user_role.can_review,
            "status": status,
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
    """Approve a draft. Returns JSON response."""
    try:
        if user.user_role == UserRole.client_viewer:
            return JSONResponse(status_code=403, content={"message": "Viewers cannot approve drafts"})

        draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
        if not draft:
            return JSONResponse(status_code=404, content={"message": "Draft not found"})

        avatar = db.query(Avatar).filter(Avatar.id == draft.avatar_id).first()
        if not avatar or str(client_id) not in (avatar.client_ids or []):
            return JSONResponse(status_code=404, content={"message": "Draft not found"})

        client = db.query(Client).filter(Client.id == client_id).first()
        if client:
            block = check_safety_blocks(draft, avatar, client)
            if block:
                return JSONResponse(status_code=422, content=block)

        draft.status = "approved"
        db.commit()

        # Audit log (best-effort)
        try:
            from app.services.audit import log_action
            log_action(
                db=db,
                user_id=user.id,
                action="draft_approved",
                entity_type="comment_draft",
                entity_id=draft_id,
                details={
                    "client_id": str(client_id),
                    "avatar": avatar.reddit_username if avatar else None,
                    "source": "client_portal",
                },
            )
        except Exception as e:
            logger.warning("Failed to log audit event: %s", e)

        logger.info(
            "Portal: draft approved | draft_id=%s | user=%s | client=%s",
            draft_id, user.email, client_id,
        )

        return JSONResponse(status_code=200, content={"ok": True, "message": "Approved"})

    except Exception as e:
        logger.error(
            "Portal approve UNHANDLED ERROR | draft_id=%s | client_id=%s | error=%s | type=%s",
            draft_id, client_id, str(e), type(e).__name__,
        )
        db.rollback()
        return JSONResponse(status_code=500, content={"message": "Server error. Please try again."})


@router.post("/clients/{client_id}/drafts/{draft_id}/skip")
def portal_skip_draft(
    request: Request,
    client_id: UUID,
    draft_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Skip (reject) a draft. Returns JSON response."""
    try:
        if user.user_role == UserRole.client_viewer:
            return JSONResponse(status_code=403, content={"message": "Viewers cannot skip drafts"})

        draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
        if not draft:
            return JSONResponse(status_code=404, content={"message": "Draft not found"})

        avatar = db.query(Avatar).filter(Avatar.id == draft.avatar_id).first()
        if not avatar or str(client_id) not in (avatar.client_ids or []):
            return JSONResponse(status_code=404, content={"message": "Draft not found"})

        draft.status = "rejected"
        db.commit()

        # Audit log (best-effort)
        try:
            from app.services.audit import log_action
            log_action(
                db=db,
                user_id=user.id,
                action="draft_skipped",
                entity_type="comment_draft",
                entity_id=draft_id,
                details={
                    "client_id": str(client_id),
                    "avatar": avatar.reddit_username if avatar else None,
                    "source": "client_portal",
                },
            )
        except Exception as e:
            logger.warning("Failed to log audit event: %s", e)

        logger.info(
            "Portal: draft skipped | draft_id=%s | user=%s | client=%s",
            draft_id, user.email, client_id,
        )

        return JSONResponse(status_code=200, content={"ok": True, "message": "Skipped"})

    except Exception as e:
        logger.error(
            "Portal skip UNHANDLED ERROR | draft_id=%s | client_id=%s | error=%s | type=%s",
            draft_id, client_id, str(e), type(e).__name__,
        )
        db.rollback()
        return JSONResponse(status_code=500, content={"message": "Server error. Please try again."})


@router.post("/clients/{client_id}/drafts/{draft_id}/mark-posted")
def portal_mark_posted(
    request: Request,
    client_id: UUID,
    draft_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    reddit_url: str = Form(""),
):
    """Mark an approved draft as posted on Reddit."""
    try:
        if user.user_role == UserRole.client_viewer:
            return JSONResponse(status_code=403, content={"message": "Viewers cannot mark drafts as posted"})

        draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
        if not draft:
            return JSONResponse(status_code=404, content={"message": "Draft not found"})

        avatar = db.query(Avatar).filter(Avatar.id == draft.avatar_id).first()
        if not avatar or str(client_id) not in (avatar.client_ids or []):
            logger.warning(
                "Portal mark-posted: client_id mismatch | draft_id=%s | client_id=%s | avatar_client_ids=%s",
                draft_id, client_id, avatar.client_ids if avatar else None,
            )
            return JSONResponse(status_code=404, content={"message": "Draft not found"})

        if draft.status not in ("approved", "pending"):
            return JSONResponse(status_code=422, content={"message": "Draft is not in approved state"})

        draft.status = "posted"
        draft.posted_at = datetime.now(timezone.utc)
        if reddit_url.strip():
            draft.reddit_comment_url = reddit_url.strip()
        db.commit()

        # Audit log (best-effort)
        try:
            from app.services.audit import log_action
            log_action(
                db=db,
                user_id=user.id,
                action="draft_marked_posted",
                entity_type="comment_draft",
                entity_id=draft_id,
                details={
                    "client_id": str(client_id),
                    "avatar": avatar.reddit_username if avatar else None,
                    "reddit_url": reddit_url.strip() or None,
                    "source": "client_portal",
                },
            )
        except Exception as e:
            logger.warning("Failed to log audit event: %s", e)

        logger.info(
            "Portal: draft marked posted | draft_id=%s | user=%s | client=%s",
            draft_id, user.email, client_id,
        )

        return JSONResponse(status_code=200, content={"ok": True, "message": "Marked as posted"})

    except Exception as e:
        logger.error(
            "Portal mark-posted UNHANDLED ERROR | draft_id=%s | client_id=%s | error=%s | type=%s",
            draft_id, client_id, str(e), type(e).__name__,
        )
        db.rollback()
        return JSONResponse(status_code=500, content={"message": "Server error. Please try again."})


@router.post("/clients/{client_id}/drafts/{draft_id}/edit")
def portal_edit_draft(
    request: Request,
    client_id: UUID,
    draft_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    edited_text: str = Form(""),
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

    # Save the edit
    if edited_text.strip():
        draft.edited_draft = edited_text.strip()

    # Safety check on the edited version
    if client:
        block = check_safety_blocks(draft, avatar, client)
        if block:
            return JSONResponse(status_code=422, content=block)

    draft.status = "approved"
    db.commit()

    # Capture edit for learning loop (trains AI to write better)
    try:
        from app.services.learning import LearningService
        thread = db.query(RedditThread).filter(RedditThread.id == draft.thread_id).first() if draft.thread_id else None
        if thread:
            learning_status = "approved" if (edited_text.strip() and edited_text.strip() != (draft.ai_draft or "")) else "approved_unchanged"
            LearningService().capture_edit_record(db=db, draft=draft, thread=thread, status=learning_status)
            db.commit()
    except Exception as e:
        logger.warning("Failed to capture edit record: %s", e)

    # Audit log
    try:
        from app.services.audit import log_action
        log_action(
            db=db,
            user_id=user.id,
            action="draft_edited_and_approved",
            entity_type="comment_draft",
            entity_id=draft_id,
            details={
                "client_id": str(client_id),
                "avatar": avatar.reddit_username,
                "edited": bool(edited_text.strip()),
                "source": "client_portal",
            },
        )
    except Exception as e:
        logger.warning("Failed to log audit event: %s", e)

    logger.info(
        "Portal: draft edited+approved | draft_id=%s | user=%s | client=%s",
        draft_id, user.email, client_id,
    )

    return HTMLResponse(
        content="",
        headers={
            "HX-Trigger": '{"showToast": {"type": "success", "message": "Got it - we\'ll remember this for future drafts"}}'
        },
    )


# --- EPG (Daily Publishing Program) ---


@router.get("/clients/{client_id}/epg", response_class=HTMLResponse)
def portal_epg(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal EPG — daily publishing program per avatar."""
    from app.services.epg import build_daily_epg
    from app.models.comment_draft import CommentDraft
    from collections import defaultdict
    from datetime import date as date_type

    # Get all active avatars for this client
    avatars_raw = (
        db.query(Avatar)
        .filter(Avatar.client_ids.any(str(client_id)), Avatar.active.is_(True))
        .order_by(Avatar.reddit_username.asc())
        .all()
    )

    client = db.query(Client).filter(Client.id == client_id).first()

    now = datetime.now(timezone.utc)

    # Build EPG for each avatar
    avatar_epgs = []
    for avatar in avatars_raw:
        epg = build_daily_epg(db, avatar, client)

        # Check draft status for each slot
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_drafts = (
            db.query(CommentDraft)
            .filter(
                CommentDraft.avatar_id == avatar.id,
                CommentDraft.created_at >= today_start,
            )
            .all()
        )
        # Map thread_id → draft status
        draft_status_map = {}
        for td in today_drafts:
            draft_status_map[str(td.thread_id)] = td.status

        # Enrich hobby slots with status
        enriched_hobby = []
        for slot in epg.hobby_slots:
            # hobby slots use hobby_post_id, not thread_id directly
            # Check if any draft exists for this subreddit today
            slot_status = "scheduled"  # default: not yet generated
            for td in today_drafts:
                if td.thread and td.thread.subreddit == slot.get("subreddit") and td.type == "hobby":
                    slot_status = td.status
                    break
            enriched_hobby.append({**slot, "draft_status": slot_status})

        enriched_business = []
        for slot in epg.business_slots:
            slot_status = "scheduled"
            thread_id = slot.get("thread_id", "")
            if thread_id and str(thread_id) in draft_status_map:
                slot_status = draft_status_map[str(thread_id)]
            enriched_business.append({**slot, "draft_status": slot_status})

        # Overall day status
        if epg.status != "ok":
            day_status = epg.status
        elif epg.remaining == 0 and epg.used_today >= epg.daily_budget:
            day_status = "complete"
        elif epg.total_slots == 0:
            day_status = "no_slots"
        else:
            day_status = "in_progress"

        avatar_epgs.append({
            "username": _avatar_display_name(avatar),
            "phase": avatar.warming_phase,
            "daily_budget": epg.daily_budget,
            "used_today": epg.used_today,
            "remaining": epg.remaining,
            "status": epg.status,
            "day_status": day_status,
            "message": epg.message,
            "hobby_slots": enriched_hobby,
            "business_slots": enriched_business,
            "total_slots": epg.total_slots,
        })

    # History: last 30 days of drafts grouped by date
    week_ago = now - timedelta(days=30)

    history_raw = (
        db.query(CommentDraft)
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.created_at >= week_ago,
        )
        .order_by(CommentDraft.created_at.desc())
        .all()
    )

    # Group by date
    history_by_day: dict[str, list] = defaultdict(list)
    for d in history_raw:
        day_key = d.created_at.strftime("%Y-%m-%d")
        draft_text = d.edited_draft or d.ai_draft or ""
        # Resolve subreddit: from thread (professional) or hobby_post (hobby)
        subreddit_name = ""
        thread_title = ""
        thread_url = ""
        if d.thread:
            subreddit_name = d.thread.subreddit or ""
            thread_title = (d.thread.post_title or "")[:60]
            thread_url = d.thread.url or ""
        elif d.hobby_post_id:
            from app.models.hobby import HobbySubreddit
            hobby_post = db.query(HobbySubreddit).filter(HobbySubreddit.id == d.hobby_post_id).first()
            if hobby_post:
                subreddit_name = hobby_post.subreddit or ""
                thread_title = (hobby_post.post_title or "")[:60]
                if hobby_post.permalink:
                    thread_url = f"https://www.reddit.com{hobby_post.permalink}" if not hobby_post.permalink.startswith("http") else hobby_post.permalink
                elif hobby_post.url:
                    thread_url = hobby_post.url
        history_by_day[day_key].append({
            "avatar": _avatar_display_name(d.avatar) if d.avatar else "?",
            "subreddit": subreddit_name,
            "thread_title": thread_title,
            "thread_url": thread_url,
            "text": draft_text[:100],
            "status": d.status,
            "reddit_score": d.reddit_score,
            "approach": d.comment_approach or "",
            "created_at": _relative_time(d.created_at),
        })

    # Convert to sorted list of days
    today_str = now.strftime("%Y-%m-%d")
    history_days = []
    for day_key in sorted(history_by_day.keys(), reverse=True):
        if day_key == today_str:
            label = "Today"
        else:
            d_obj = date_type.fromisoformat(day_key)
            label = d_obj.strftime("%a, %b %d")
        history_days.append({
            "label": label,
            "date": day_key,
            "drafts": history_by_day[day_key],
        })

    return _portal_render(
        request,
        "client/epg.html",
        client_id,
        db,
        active_page="epg",
        extra_context={
            "avatar_epgs": avatar_epgs,
            "history_days": history_days,
            "now_date": now.strftime("%A, %B %d, %Y"),
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


# --- Landscape Report (Day 1 Intelligence) ---


@router.get("/clients/{client_id}/landscape", response_class=HTMLResponse)
def portal_landscape(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Day 1 Landscape Report — competitive presence, opportunities, scored threads."""
    from app.services.onboarding.landscape_report import generate_landscape_report

    report = generate_landscape_report(db, client_id)

    return _portal_render(
        request,
        "client/landscape.html",
        client_id,
        db,
        active_page="report",
        extra_context={"landscape": report},
    )


# --- Momentum Events Feed (HTMX partial for home) ---


@router.get("/clients/{client_id}/partials/momentum", response_class=HTMLResponse)
def portal_momentum_partial(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return recent momentum events for the client — breakout comments, phase moves, alerts."""
    from app.models.activity_event import ActivityEvent

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    # Fetch recent events for this client
    events_raw = (
        db.query(ActivityEvent)
        .filter(
            ActivityEvent.client_id == client_id,
            ActivityEvent.created_at >= week_ago,
        )
        .order_by(ActivityEvent.created_at.desc())
        .limit(15)
        .all()
    )

    # Format events for display
    EVENT_ICONS = {
        "scrape": "🔍",
        "score": "📊",
        "generate": "✍",
        "draft_approved": "✓",
        "draft_posted": "📤",
        "phase_promotion": "🚀",
        "phase_demotion": "⚠",
        "health_alert": "🚨",
        "comment_deletion_detected": "❌",
        "karma_milestone": "⭐",
        "pipeline": "⚡",
        "system": "🔧",
        "client_onboarded": "🎉",
        "avatar_onboarding_complete": "👤",
    }

    events = []
    for ev in events_raw:
        icon = EVENT_ICONS.get(ev.event_type, "📡")
        meta = ev.event_metadata or {}

        events.append({
            "icon": icon,
            "type": ev.event_type,
            "message": ev.message,
            "time": _relative_time(ev.created_at),
            "subreddit": meta.get("subreddit_name", ""),
            "avatar": meta.get("avatar_username", ""),
            "score": meta.get("reddit_score", meta.get("upvotes", "")),
        })

    return templates.TemplateResponse(
        name="partials/client/momentum_feed.html",
        context={"request": request, "events": events, "client_id": str(client_id)},
        request=request,
    )


# --- Report PDF Download ---


@router.get("/clients/{client_id}/report/download", response_class=HTMLResponse)
def portal_report_download(
    request: Request,
    client_id: UUID,
    days: int = 30,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download report as a standalone HTML file (print-ready, PDF-friendly).

    Client can use browser Print → Save as PDF, or we serve as attachment.
    """
    from app.models.comment_draft import CommentDraft
    from app.models.thread import RedditThread
    from app.models.subreddit import ClientSubredditAssignment, Subreddit
    from starlette.responses import Response

    if days not in (30, 60, 90):
        days = 30

    now = datetime.now(timezone.utc)
    month_start = now - timedelta(days=days)
    week_start = now - timedelta(days=7)

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404)

    # Gather same stats as portal_report
    week_generated = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(Avatar.client_ids.any(str(client_id)), CommentDraft.created_at >= week_start)
        .scalar()
    ) or 0

    week_approved = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status.in_(["approved", "posted"]),
            CommentDraft.created_at >= week_start,
        )
        .scalar()
    ) or 0

    month_posted = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
            CommentDraft.created_at >= month_start,
        )
        .scalar()
    ) or 0

    month_upvotes = (
        db.query(func.coalesce(func.sum(CommentDraft.reddit_score), 0))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
            CommentDraft.created_at >= month_start,
        )
        .scalar()
    ) or 0

    # Top comments
    top_comments_raw = (
        db.query(CommentDraft)
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
            CommentDraft.reddit_score.isnot(None),
            CommentDraft.reddit_score > 0,
        )
        .order_by(CommentDraft.reddit_score.desc())
        .limit(5)
        .all()
    )

    top_comments = []
    for c in top_comments_raw:
        top_comments.append({
            "text": (c.edited_draft or c.ai_draft or "")[:150],
            "score": c.reddit_score or 0,
            "subreddit": c.thread.subreddit if c.thread else "",
            "thread_title": (c.thread.post_title[:60] if c.thread else ""),
        })

    # Subreddit performance
    client_subs = (
        db.query(ClientSubredditAssignment)
        .join(Subreddit, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .filter(ClientSubredditAssignment.client_id == client_id, ClientSubredditAssignment.is_active.is_(True))
        .all()
    )

    sub_perf = []
    for assignment in client_subs:
        sub_name = assignment.subreddit.subreddit_name if assignment.subreddit else ""
        activity = (
            db.query(func.count(CommentDraft.id))
            .join(Avatar, CommentDraft.avatar_id == Avatar.id)
            .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
            .filter(
                Avatar.client_ids.any(str(client_id)),
                RedditThread.subreddit == sub_name,
                CommentDraft.status == "posted",
                CommentDraft.created_at >= month_start,
            )
            .scalar()
        ) or 0
        if activity > 0:
            sub_perf.append({"name": sub_name, "comments": activity})

    # Generate standalone HTML report
    report_date = now.strftime("%B %d, %Y")
    brand = client.brand_name or client.client_name

    html = templates.TemplateResponse(
        name="client/report_pdf.html",
        context={
            "request": request,
            "brand": brand,
            "report_date": report_date,
            "days": days,
            "week_generated": week_generated,
            "week_approved": week_approved,
            "month_posted": month_posted,
            "month_upvotes": int(month_upvotes),
            "top_comments": top_comments,
            "sub_perf": sub_perf,
        },
        request=request,
    )

    # Serve as downloadable HTML (print to PDF in browser)
    filename = f"RAMP_Report_{brand}_{days}d_{now.strftime('%Y%m%d')}.html"
    html.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return html


# --- Budget & Usage Tracking ---


def _get_usage_context(client_id: UUID, db: Session) -> dict:
    """Calculate monthly usage vs plan limits for budget cap banners and upsell triggers."""
    from app.models.comment_draft import CommentDraft

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return {}

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Count comments generated this month
    month_generated = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.created_at >= month_start,
        )
        .scalar()
    ) or 0

    # Plan limits
    PLAN_ACTIONS = {
        "trial": 30, "seed": 30, "starter": 60,
        "growth": 150, "scale": 400,
    }
    PLAN_SUBREDDITS = {
        "trial": 3, "seed": 1, "starter": 2,
        "growth": 5, "scale": 999,
    }
    PLAN_AVATARS = {
        "trial": 0, "seed": 1, "starter": 3,
        "growth": 7, "scale": 15,
    }

    plan = client.plan_type or "starter"
    action_limit = client.max_comments_per_month or PLAN_ACTIONS.get(plan, 60)
    avatar_limit = client.max_avatars or PLAN_AVATARS.get(plan, 3)

    # Current counts
    avatar_count = (
        db.query(func.count(Avatar.id))
        .filter(Avatar.client_ids.any(str(client_id)), Avatar.active.is_(True))
        .scalar()
    ) or 0

    from app.models.subreddit import ClientSubredditAssignment
    sub_count = (
        db.query(func.count(ClientSubredditAssignment.id))
        .filter(
            ClientSubredditAssignment.client_id == client_id,
            ClientSubredditAssignment.is_active.is_(True),
        )
        .scalar()
    ) or 0

    sub_limit = PLAN_SUBREDDITS.get(plan, 2)

    # Usage percentage
    usage_pct = round(month_generated / action_limit * 100) if action_limit > 0 else 0

    return {
        "plan_type": plan,
        "action_limit": action_limit,
        "month_generated": month_generated,
        "usage_pct": min(usage_pct, 100),
        "budget_warning": usage_pct >= 80,
        "budget_exhausted": usage_pct >= 100,
        "avatar_count": avatar_count,
        "avatar_limit": avatar_limit,
        "avatar_at_limit": avatar_count >= avatar_limit,
        "sub_count": sub_count,
        "sub_limit": sub_limit,
        "sub_at_limit": sub_count >= sub_limit,
    }


# --- Help / Documentation ---


@router.get("/clients/{client_id}/help", response_class=HTMLResponse)
def portal_help(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """In-app help page — renders role-appropriate documentation as HTML."""
    import markdown
    from pathlib import Path

    role = user.user_role.value

    # Map role to documentation file
    role_doc_map = {
        "client_admin": "client-admin.md",
        "client_manager": "client-manager.md",
        "client_viewer": "client-viewer.md",
        "b2c_user": "client-admin.md",  # fallback
    }

    doc_filename = role_doc_map.get(role, "client-admin.md")
    doc_path = Path("docs/kb/roles") / doc_filename

    # Read and render markdown
    doc_html = ""
    if doc_path.exists():
        md_content = doc_path.read_text(encoding="utf-8")
        doc_html = markdown.markdown(
            md_content,
            extensions=["tables", "fenced_code", "toc"],
        )
    else:
        doc_html = "<p>Documentation not found. Please contact support.</p>"

    # Also load the trial management guide for trial users
    trial_guide_html = ""
    client = db.query(Client).filter(Client.id == client_id).first()
    if client and client.plan_type == "trial":
        trial_path = Path("docs/kb/guides/trial-management.md")
        if trial_path.exists():
            # Only render sections 2 and 3 (portal + onboarding)
            trial_md = trial_path.read_text(encoding="utf-8")
            # Extract sections relevant to client
            sections = []
            current = []
            for line in trial_md.split("\n"):
                if line.startswith("## ") and current:
                    sections.append("\n".join(current))
                    current = [line]
                else:
                    current.append(line)
            if current:
                sections.append("\n".join(current))
            # Keep sections about portal access and onboarding
            relevant = [s for s in sections if any(k in s for k in ["Client Portal", "Onboarding Wizard", "Trial Limits"])]
            if relevant:
                trial_guide_html = markdown.markdown(
                    "\n\n".join(relevant),
                    extensions=["tables", "fenced_code"],
                )

    ctx = _get_sidebar_context(client_id, db)
    return templates.TemplateResponse(
        name="client/help.html",
        context={
            "request": request,
            **ctx,
            "active_page": "help",
            "doc_html": doc_html,
            "trial_guide_html": trial_guide_html,
            "user_role": role,
            "user_name": user.full_name or user.email,
            "user_email": user.email,
        },
        request=request,
    )
