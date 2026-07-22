"""Client Portal — Routes.

New dark-themed client-facing portal. Separate from admin panel.
All routes require client access (RBAC enforced).
"""

import re

from app.logging_config import get_logger
from datetime import datetime, timezone, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from app.templating import Jinja2Templates
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
from app.services.access_gate import AccessGate
from app.services.permission_context import get_permission_context

logger = get_logger(__name__)


def _check_trial_not_expired(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Dependency that blocks POST/mutating actions for expired trial clients.

    GET requests are allowed through — the portal renders with a blur overlay
    and upgrade popup instead of blocking access entirely.
    """
    if not user.client_id:
        return
    # Allow GET requests (read-only browsing with blur overlay)
    if request.method == "GET":
        return
    client = db.query(Client).filter(Client.id == user.client_id).first()
    if client:
        AccessGate.check_trial_expiry(client)
        if not AccessGate.can_execute_pipeline(client):
            db.commit()
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
templates.env.globals["app_env"] = _get_settings().app_env

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
    """Return client-facing name: display_name if set, else friendly version of reddit_username."""
    if avatar.display_name:
        return avatar.display_name
    # Generate a friendly name from reddit_username
    # e.g. "Flaky_Finder_13" -> "Flaky Finder", "Hot-Thought2408" -> "Hot Thought"
    import re
    name = avatar.reddit_username or "Voice"
    # Remove u/ prefix if present
    name = name.removeprefix("u/")
    # Replace underscores and hyphens with spaces
    name = name.replace("_", " ").replace("-", " ")
    # Remove trailing/leading numbers
    name = re.sub(r'\d+$', '', name).strip()
    # Title case
    name = name.title() if name else "Voice"
    return name



# --- Helpers ---


def _check_generation_degraded(client_id) -> str | None:
    """Check if generation is degraded for this client (Redis flag with 4h TTL)."""
    try:
        from app.services.ops_notifications import is_generation_degraded
        return is_generation_degraded(client_id)
    except Exception:
        return None


def _get_sidebar_context(client_id: UUID, db: Session) -> dict:
    """Build sidebar context: pending_count, has_shadowbanned, client_name."""
    client = db.query(Client).filter(Client.id == client_id).first()
    client_name = client.client_name if client else "Client"

    # Pending drafts count — only from active/unfrozen avatars, max 14 days old
    pending_count = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            CommentDraft.status == "pending",
            Avatar.client_ids.any(str(client_id)),
            Avatar.active.is_(True),
            Avatar.is_frozen.is_(False),
            CommentDraft.created_at >= datetime.now(timezone.utc) - timedelta(days=14),
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

    # Plan info for sidebar widget
    plan_name = client.plan_type if client else "starter"
    # Map plan_type to display name
    PLAN_DISPLAY = {"trial": "Free trial", "seed": "Seed plan", "starter": "Starter plan", "growth": "Growth plan", "scale": "Scale plan"}
    plan_display = PLAN_DISPLAY.get(plan_name, plan_name.title() + " plan") if plan_name else "Starter plan"

    # Action limit from plan
    PLAN_ACTION_LIMITS = {"trial": 30, "seed": 30, "starter": 60, "growth": 150, "scale": 400}
    action_limit = PLAN_ACTION_LIMITS.get(plan_name, 60)

    # Month usage (drafts generated this month)
    from datetime import date as _date
    month_start = datetime(datetime.now().year, datetime.now().month, 1, tzinfo=timezone.utc)
    month_generated = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.created_at >= month_start,
        )
        .scalar()
    ) or 0

    # Onboarding progress (for sidebar progress bar)
    onboarding_step = client.current_onboarding_step if client else 0
    onboarding_completed = client.onboarding_completed_at is not None if client else False
    if onboarding_completed:
        onboarding_pct = 100
    else:
        # Steps: 1=company, 2=ICP, 3=voice, 4=subreddits, 5=calibration, 6=done
        # Map step number to percentage (each step = 20%, step 6 = 100%)
        onboarding_pct = min(100, max(0, (onboarding_step - 1) * 20)) if onboarding_step > 0 else 0
    onboarding_steps = {
        "company": onboarding_step >= 2,
        "icp": onboarding_step >= 3,
        "voice": onboarding_step >= 4,
        "subreddits": onboarding_step >= 5,
        "calibration": onboarding_step >= 6 or onboarding_completed,
    }

    return {
        "client_id": str(client_id),
        "client_name": client_name,
        "pending_count": pending_count,
        "has_shadowbanned": has_shadowbanned,
        "is_trial": client.plan_type == "trial" if client else False,
        "trial_days_remaining": max(0, 14 - (datetime.now(timezone.utc) - client.created_at).days) if client and client.plan_type == "trial" else None,
        "plan_name": plan_display,
        "action_limit": action_limit,
        "month_generated": month_generated,
        "onboarding_pct": onboarding_pct,
        "onboarding_steps": onboarding_steps,
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

    # Trial expiration: allow browsing but flag for blur overlay
    client_obj = db.query(Client).filter(Client.id == client_id).first()
    trial_expired = False
    if client_obj and client_obj.plan_type == "trial":
        days_since_creation = (datetime.now(timezone.utc) - client_obj.created_at).days if client_obj.created_at else 0
        if days_since_creation > 14:
            trial_expired = True
    ctx["trial_expired"] = trial_expired
    # Sales calendar URL for expired trial CTA
    if trial_expired:
        from app.services.settings import get_setting
        ctx["sales_calendar_url"] = get_setting(db, "sales_calendar_url") or ""
    else:
        ctx["sales_calendar_url"] = ""
    ctx["request"] = request
    ctx["active_page"] = active_page

    # Inject user info from auth middleware
    ctx["user_name"] = getattr(request.state, "user_full_name", "") or ""
    ctx["user_email"] = getattr(request.state, "user_email", "") or ""
    ctx["user_role"] = getattr(request.state, "user_role", "") or ""

    # Inject usage/budget context for banners and upsells
    ctx.update(_get_usage_context(client_id, db))

    # Inject permission context (hidden_actions, approval_actions, pending_requests_count)
    user_role_str = ctx.get("user_role", "")
    try:
        user_role_enum = UserRole(user_role_str) if user_role_str else None
    except ValueError:
        user_role_enum = None
    if user_role_enum:
        perm_ctx = get_permission_context(db, client_id, user_role_enum)
        ctx.update(perm_ctx)
    else:
        # Fallback: no permission context available (should not happen in normal flow)
        ctx.setdefault("hidden_actions", set())
        ctx.setdefault("approval_actions", set())
        ctx.setdefault("pending_requests_count", 0)

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

    # Trial clients get a guided onboarding experience
    is_trial = client_obj and client_obj.plan_type == "trial"
    template = "client/home_trial.html" if is_trial else "client/home.html"

    return _portal_render(
        request,
        template,
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
            "onboarding_step": client_obj.current_onboarding_step if client_obj else 0,
            "subscription_status": client_obj.subscription_status if client_obj else "trial",
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

    # Count approved (ready to post) — today only (matches default view)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Pending count — today only (for tab badge; sidebar badge stays 14d for overall awareness)
    pending_count_today = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            CommentDraft.status == "pending",
            Avatar.client_ids.any(str(client_id)),
            Avatar.active.is_(True),
            Avatar.is_frozen.is_(False),
            CommentDraft.created_at >= today_start,
        )
        .scalar()
    ) or 0

    approved_count = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            CommentDraft.status == "approved",
            Avatar.client_ids.any(str(client_id)),
            Avatar.active.is_(True),
            Avatar.is_frozen.is_(False),
            CommentDraft.created_at >= today_start,
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

    expired_count = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            CommentDraft.status == "expired",
            Avatar.client_ids.any(str(client_id)),
            Avatar.active.is_(True),
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
            "pending_count": pending_count_today,
            "approved_count": approved_count,
            "posted_count": posted_count,
            "expired_count": expired_count,
            "can_review": can_review,
            "avatar_options": avatar_options,
            "generation_degraded": _check_generation_degraded(client_id),
        },
    )



@router.get("/clients/{client_id}/extension", response_class=HTMLResponse)
def portal_extension(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal extension download + setup page."""
    from app.models.execution_node import ExecutionNode

    # Get client's avatars with their extension status
    avatars_raw = (
        db.query(Avatar)
        .filter(Avatar.client_ids.any(str(client_id)), Avatar.active.is_(True))
        .order_by(Avatar.reddit_username.asc())
        .all()
    )

    avatars = []
    for a in avatars_raw:
        # Check if extension node exists and is online
        node = (
            db.query(ExecutionNode)
            .filter(ExecutionNode.active_reddit_username == a.reddit_username)
            .first()
        )
        extension_online = False
        if node and node.is_online:
            # Consider online if heartbeat within last 5 min
            if node.last_heartbeat:
                age = (datetime.now(timezone.utc) - node.last_heartbeat).total_seconds()
                extension_online = age < 300

        avatars.append({
            "id": str(a.id),
            "username": a.reddit_username,
            "delivery_channel": a.delivery_channel or "extension",
            "extension_online": extension_online,
        })

    return _portal_render(
        request,
        "client/extension.html",
        client_id,
        db,
        active_page="extension",
        extra_context={"avatars": avatars},
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

    # Voice limit from plan (for upsell logic)
    client_obj = db.query(Client).filter(Client.id == client_id).first()
    PLAN_VOICE_LIMITS = {"trial": 1, "seed": 1, "starter": 3, "growth": 7, "scale": 15}
    voice_limit = PLAN_VOICE_LIMITS.get(client_obj.plan_type, 3) if client_obj else 3
    at_voice_limit = len(avatars) >= voice_limit

    return _portal_render(
        request,
        "client/avatars.html",
        client_id,
        db,
        active_page="avatars",
        extra_context={
            "avatars": avatars,
            "can_onboard": can_onboard,
            "at_voice_limit": at_voice_limit,
            "voice_limit": voice_limit,
        },
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
        # Resolve subreddit from thread or hobby_post (relationship)
        subreddit_name = ""
        thread_title = ""
        if d.thread:
            subreddit_name = d.thread.subreddit or ""
            thread_title = (d.thread.post_title or "")[:60]
        elif d.hobby_post_id:
            hobby = d.hobby_post
            if not hobby:
                from app.models.hobby import HobbySubreddit
                hobby = db.query(HobbySubreddit).filter(HobbySubreddit.id == d.hobby_post_id).first()
            if hobby:
                subreddit_name = hobby.subreddit or ""
                thread_title = (hobby.post_title or "")[:60]

        # Clean subreddit name: strip r/ prefix, whitespace
        if subreddit_name:
            subreddit_name = subreddit_name.strip().removeprefix("r/").strip()

        # Fallback: extract subreddit from reddit_comment_url if available
        if not subreddit_name and d.reddit_comment_url:
            # URL format: https://reddit.com/r/SUBREDDIT/comments/...
            m = re.search(r"/r/([^/]+)", d.reddit_comment_url)
            if m:
                subreddit_name = m.group(1)

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
        "delivery_channel": avatar.delivery_channel or "extension",
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


@router.post("/clients/{client_id}/avatars/{avatar_id}/delivery-channel")
def portal_avatar_delivery_channel(
    request: Request,
    client_id: UUID,
    avatar_id: UUID,
    channel: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal: switch avatar delivery channel.
    Available to client_admin and client_manager."""
    if user.user_role == UserRole.client_viewer:
        return JSONResponse(status_code=403, content={"message": "Viewers cannot change delivery settings"})

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar or str(client_id) not in (avatar.client_ids or []):
        raise HTTPException(status_code=404, detail="Avatar not found")

    if channel not in ("email", "extension", "both"):
        raise HTTPException(status_code=400, detail="Channel must be 'email', 'extension', or 'both'")

    avatar.delivery_channel = channel
    db.commit()

    return RedirectResponse(
        url=f"/clients/{client_id}/avatars/{avatar_id}",
        status_code=303,
    )


@router.post("/clients/{client_id}/avatars/{avatar_id}/edit-persona")
def portal_edit_avatar_persona(
    request: Request,
    client_id: UUID,
    avatar_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    voice_profile_md: str = Form(""),
    tone_principles: str = Form(""),
    hill_i_die_on: str = Form(""),
    helpful_mode_topics: str = Form(""),
):
    """Client can edit avatar persona (limited to 1 edit per 30 days)."""
    from app.models.client_action_log import ClientActionLog

    if user.user_role == UserRole.client_viewer:
        return JSONResponse(status_code=403, content={"message": "Viewers cannot edit avatars"})

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar or str(client_id) not in (avatar.client_ids or []):
        return JSONResponse(status_code=404, content={"message": "Avatar not found"})

    # Rate limit: 1 persona edit per 30 days per avatar
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    recent_edit = (
        db.query(ClientActionLog)
        .filter(
            ClientActionLog.client_id == client_id,
            ClientActionLog.action_type == "edit_persona",
            ClientActionLog.avatar_id == avatar_id,
            ClientActionLog.triggered_at >= thirty_days_ago,
        )
        .first()
    )
    if recent_edit:
        days_left = 30 - (datetime.now(timezone.utc) - recent_edit.triggered_at).days
        return JSONResponse(
            status_code=429,
            content={"message": f"Persona can only be edited once per month. Next edit available in {max(1, days_left)} days."},
        )

    # Apply changes (only non-empty fields)
    changed_fields = []
    if voice_profile_md.strip():
        avatar.voice_profile_md = voice_profile_md.strip()
        changed_fields.append("voice_profile_md")
    if tone_principles.strip():
        avatar.tone_principles = tone_principles.strip()
        changed_fields.append("tone_principles")
    if hill_i_die_on.strip():
        avatar.hill_i_die_on = hill_i_die_on.strip()
        changed_fields.append("hill_i_die_on")
    if helpful_mode_topics.strip():
        avatar.helpful_mode_topics = helpful_mode_topics.strip()
        changed_fields.append("helpful_mode_topics")

    if not changed_fields:
        return JSONResponse(status_code=422, content={"message": "No changes provided"})

    # Log the edit action
    action_log = ClientActionLog(
        client_id=client_id,
        triggered_by=user.id,
        action_type="edit_persona",
        avatar_id=avatar_id,
    )
    db.add(action_log)
    db.commit()

    logger.info(
        "Portal: persona edited | avatar=%s | user=%s | fields=%s",
        avatar.reddit_username, user.email, changed_fields,
    )

    return JSONResponse(status_code=200, content={"ok": True, "message": "Persona updated successfully"})


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
    plan_limits = {"trial": 1, "seed": 2, "starter": 4, "growth": 8, "scale": 999}
    plan_type = client_obj.plan_type if client_obj else "starter"
    plan_limit = plan_limits.get(plan_type, 4)

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
            "user": user,
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


# --- Settings: Telegram Connect/Disconnect (client-facing) ---


@router.post("/clients/{client_id}/settings/telegram/connect", response_class=HTMLResponse)
def portal_telegram_connect(
    request: Request,
    client_id: UUID,
    chat_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Connect Telegram for current user (client_admin, client_manager, owner, partner)."""
    from datetime import datetime, timezone as tz

    if user.user_role not in (UserRole.client_admin, UserRole.client_manager, UserRole.owner, UserRole.partner):
        raise HTTPException(status_code=403, detail="Access denied")

    chat_id = chat_id.strip()
    if not chat_id or not chat_id.lstrip("-").isdigit():
        return HTMLResponse(
            '<span style="color:var(--color-red);font-size:var(--text-small);">Invalid Chat ID. Must be a number. Start the bot and use /start to get it.</span>'
        )

    user.telegram_chat_id = chat_id
    user.telegram_connected_at = datetime.now(tz.utc)
    if not user.telegram_notifications_level:
        user.telegram_notifications_level = "all"
    db.commit()

    # Send confirmation via bot (non-blocking)
    try:
        from app.services.telegram.bot_service import get_bot_service
        import asyncio

        bot = get_bot_service()
        if bot:
            confirm_msg = (
                f"✅ <b>Connected!</b>\n\n"
                f"Account: {user.email}\n"
                f"You'll receive draft review notifications here.\n\n"
                f"Use /help for commands."
            )
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(bot.send_message(chat_id, confirm_msg))
                else:
                    loop.run_until_complete(bot.send_message(chat_id, confirm_msg))
            except RuntimeError:
                asyncio.run(bot.send_message(chat_id, confirm_msg))
    except Exception:
        pass

    return HTMLResponse(
        '<span style="color:var(--color-green);font-size:var(--text-small);">✅ Telegram connected! Check your bot for confirmation.</span>'
    )


@router.post("/clients/{client_id}/settings/telegram/disconnect", response_class=HTMLResponse)
def portal_telegram_disconnect(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Disconnect Telegram for current user."""
    if user.user_role not in (UserRole.client_admin, UserRole.client_manager, UserRole.owner, UserRole.partner):
        raise HTTPException(status_code=403, detail="Access denied")

    user.telegram_chat_id = None
    user.telegram_connected_at = None
    db.commit()

    return HTMLResponse(
        '<span style="color:var(--color-muted);font-size:var(--text-small);">Disconnected. You won\'t receive Telegram notifications.</span>'
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
            "hidden_actions": get_permission_context(db, client_id, user.user_role).get("hidden_actions", set()),
            "approval_actions": get_permission_context(db, client_id, user.user_role).get("approval_actions", set()),
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
            "hidden_actions": get_permission_context(db, client_id, user.user_role).get("hidden_actions", set()),
            "approval_actions": get_permission_context(db, client_id, user.user_role).get("approval_actions", set()),
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
    plan_limits = {"trial": 1, "seed": 2, "starter": 4, "growth": 8, "scale": 999}
    plan_type = client_obj.plan_type if client_obj else "starter"
    plan_limit = plan_limits.get(plan_type, 4)

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
            "hidden_actions": get_permission_context(db, client_id, user.user_role).get("hidden_actions", set()),
            "approval_actions": get_permission_context(db, client_id, user.user_role).get("approval_actions", set()),
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

        # Get risk score from risk_profile relationship if available
        risk_score = None
        last_analysis = None
        next_analysis = None
        moderation_level = None
        dangerous_hours_display = None
        top_rules = []
        if sub and sub.risk_profile:
            rp = sub.risk_profile
            risk_score = rp.risk_score

            # Moderation aggressiveness (human-readable)
            mod_profile = rp.moderation_profile or {}
            aggr = mod_profile.get("aggressiveness")
            if aggr:
                moderation_level = aggr.capitalize()

            # Dangerous hours (formatted)
            if rp.dangerous_hours:
                hours_str = ", ".join(f"{h}:00" for h in sorted(rp.dangerous_hours)[:3])
                if len(rp.dangerous_hours) > 3:
                    hours_str += f" +{len(rp.dangerous_hours) - 3}"
                dangerous_hours_display = hours_str

            # Top rules (short descriptions for pills)
            if rp.extracted_rules:
                for rule in rp.extracted_rules[:6]:
                    if isinstance(rule, dict):
                        cat = (rule.get("category") or "").replace("_", " ").title()
                        val = rule.get("threshold_value") or rule.get("description", "")
                        if val and len(str(val)) < 30:
                            top_rules.append(f"{cat}: {val}")
                        else:
                            top_rules.append(cat)

            # Last analysis time
            if rp.last_rule_extraction_at:
                la = rp.last_rule_extraction_at
                la_age = (now_utc - la).total_seconds() / 86400
                if la_age < 1:
                    la_hours = (now_utc - la).total_seconds() / 3600
                    last_analysis = f"{int(la_hours)}h ago"
                elif la_age < 7:
                    last_analysis = f"{int(la_age)}d ago"
                else:
                    last_analysis = la.strftime("%b %d")

            # Next scheduled check
            if rp.next_check_at:
                nc = rp.next_check_at
                if nc <= now_utc:
                    next_analysis = "due now"
                else:
                    nc_days = (nc - now_utc).total_seconds() / 86400
                    if nc_days < 1:
                        next_analysis = f"in {int(nc_days * 24)}h"
                    else:
                        next_analysis = f"in {int(nc_days)}d"

        subreddits.append({
            "name": sub_name,
            "subreddit_id": str(a.subreddit_id) if a.subreddit_id else None,
            "type": a.type or "professional",
            "is_active": a.is_active,
            "status": status,
            "last_scraped": age_display,
            "last_result": last_result,
            "next_scrape": next_scrape,
            "risk_score": risk_score,
            "last_analysis": last_analysis,
            "next_analysis": next_analysis,
            "moderation_level": moderation_level,
            "dangerous_hours_display": dangerous_hours_display,
            "top_rules": top_rules,
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
    """Client portal strategy page — shows client-level strategy + per-avatar details."""
    from app.models.strategy_document import StrategyDocument

    # Load client for strategy_context
    client = db.query(Client).filter(Client.id == client_id).first()
    strategy_ctx = client.strategy_context if client else None

    # Parse client-level strategy sections
    client_strategy = None
    if strategy_ctx:
        positioning = strategy_ctx.get("positioning", {})
        subreddit_priorities = strategy_ctx.get("subreddit_priorities", [])
        content_pillars = strategy_ctx.get("content_pillars", [])
        forbidden_zones = strategy_ctx.get("forbidden_zones", [])
        aeo_targets = strategy_ctx.get("aeo_targets", [])
        phase_roadmap = strategy_ctx.get("phase_roadmap", {})
        metadata = strategy_ctx.get("metadata", {})

        # Determine current phase for the client (based on avatar phases)
        all_avatars_q = (
            db.query(Avatar)
            .filter(Avatar.client_ids.any(str(client_id)), Avatar.is_active.is_(True))
            .all()
        )
        phases_active = [a.warming_phase or 0 for a in all_avatars_q]
        current_phase_num = max(phases_active) if phases_active else 0

        client_strategy = {
            "positioning": positioning,
            "subreddit_priorities": subreddit_priorities,
            "content_pillars": content_pillars,
            "forbidden_zones": forbidden_zones,
            "aeo_targets": aeo_targets,
            "phase_roadmap": phase_roadmap,
            "metadata": metadata,
            "version": client.strategy_version or 0,
            "generated_at": _relative_time(client.strategy_generated_at),
            "current_phase": current_phase_num,
        }

    # Per-avatar strategies (collapsible detail section)
    all_avatars = (
        db.query(Avatar)
        .filter(Avatar.client_ids.any(str(client_id)))
        .order_by(Avatar.reddit_username.asc())
        .all()
    )
    avatar_options = [{"id": str(a.id), "name": _avatar_display_name(a)} for a in all_avatars]

    if avatar_id:
        avatars_with_strategy = [a for a in all_avatars if str(a.id) == avatar_id]
    else:
        avatars_with_strategy = all_avatars

    avatar_strategies = []
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
            avatar_strategies.append({
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
            "client_strategy": client_strategy,
            "avatar_strategies": avatar_strategies,
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

# --- Insights (Landscape, SOV, Competitive Gaps, High-Value Threads) ---


@router.get("/clients/{client_id}/insights", response_class=HTMLResponse)
def portal_insights(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal — Insights screen (Day 1 intelligence: landscape, SOV, gaps, threads)."""
    from app.models.discovery_session import DiscoverySession
    from app.models.geo_execution import GeoExecutionBatch, GeoQueryResult
    from app.models.geo_competitor import GeoCompetitor
    from app.models.subreddit import ClientSubredditAssignment, Subreddit

    client_obj = db.query(Client).filter(Client.id == client_id).first()
    if not client_obj:
        raise HTTPException(status_code=404, detail="Client not found")

    # 1. Landscape Report — from most recent completed Discovery session
    landscape_report = None
    landscape_date = None
    latest_discovery = (
        db.query(DiscoverySession)
        .filter(
            DiscoverySession.client_id == client_id,
            DiscoverySession.status.in_(["completed", "handed_off"]),
        )
        .order_by(DiscoverySession.completed_at.desc())
        .first()
    )
    if latest_discovery and latest_discovery.reports:
        # Get the most recent report content
        latest_report = latest_discovery.reports[-1] if latest_discovery.reports else None
        report_content = latest_report.content if latest_report else None
        if report_content and isinstance(report_content, dict):
            # Build markdown from structured JSONB content
            raw = report_content.get("executive_summary", "")
            if raw:
                import html as _html
                lines = []
                for line in raw.split("\n"):
                    line = _html.escape(line)
                    if line.startswith("### "):
                        line = f"<h4 style='color:var(--color-white);margin:12px 0 4px;font-size:13px;font-weight:600;'>{line[4:]}</h4>"
                    elif line.startswith("## "):
                        line = f"<h3 style='color:var(--color-white);margin:14px 0 6px;font-size:14px;font-weight:600;'>{line[3:]}</h3>"
                    elif line.startswith("# "):
                        line = f"<h2 style='color:var(--color-white);margin:16px 0 8px;font-size:15px;font-weight:600;'>{line[2:]}</h2>"
                    elif line.startswith("- "):
                        line = f"<li style='margin-left:16px;'>{line[2:]}</li>"
                    else:
                        line = f"<p>{line}</p>" if line.strip() else ""
                    lines.append(line)
                landscape_report = "\n".join(lines)
                landscape_date = latest_discovery.completed_at.strftime("%b %d, %Y") if latest_discovery.completed_at else "Day 1"

    # 2. Share of Voice — reuse visibility_report data
    from app.services.visibility_report import compute_visibility_report
    vis_data = compute_visibility_report(db, client_id, include_excerpts=False)
    competitors = vis_data.get("competitors", [])
    brand_rate = vis_data["summary"]["latest_brand_rate"] if vis_data.get("has_data") else 0
    client_brand = client_obj.client_name or "Your brand"

    # 3. Competitive Gaps — subreddits where competitors appear but client has no avatar activity
    competitive_gaps = []
    # Get client's active subreddits (used here and in section 4)
    client_sub_ids = {
        row.subreddit_id
        for row in db.query(ClientSubredditAssignment.subreddit_id)
        .filter(ClientSubredditAssignment.client_id == client_id, ClientSubredditAssignment.is_active.is_(True))
        .all()
    }
    if competitors:
        client_sub_names = set()
        if client_sub_ids:
            subs = db.query(Subreddit).filter(Subreddit.id.in_(client_sub_ids)).all()
            client_sub_names = {s.subreddit_name.lower() for s in subs if s.subreddit_name}

        # Find subreddits mentioned in GEO responses where competitors are active but client isn't
        # For now, derive from competitor data in GEO results
        latest_batch = (
            db.query(GeoExecutionBatch)
            .filter(
                GeoExecutionBatch.client_id == client_id,
                GeoExecutionBatch.status.in_(["completed", "partial"]),
            )
            .order_by(GeoExecutionBatch.started_at.desc())
            .first()
        )
        if latest_batch:
            results = (
                db.query(GeoQueryResult)
                .filter(
                    GeoQueryResult.execution_batch_id == latest_batch.id,
                    GeoQueryResult.status == "success",
                    GeoQueryResult.brand_mentioned.is_(False),
                    GeoQueryResult.competitors_mentioned.isnot(None),
                )
                .all()
            )
            # Aggregate: which competitors mentioned where brand wasn't
            gap_data: dict[str, dict] = {}  # category -> {competitor_names, mentions}
            for r in results:
                if r.competitors_mentioned and isinstance(r.competitors_mentioned, dict):
                    from app.models.geo_prompt import GeoPrompt
                    prompt = db.query(GeoPrompt).filter(GeoPrompt.id == r.prompt_id).first()
                    cat = (prompt.category or "general") if prompt else "general"
                    if cat not in gap_data:
                        gap_data[cat] = {"subreddit": cat, "competitor_names": set(), "competitor_mentions": 0}
                    for comp_name in r.competitors_mentioned.keys():
                        gap_data[cat]["competitor_names"].add(comp_name)
                        gap_data[cat]["competitor_mentions"] += 1

            competitive_gaps = [
                {
                    "subreddit": v["subreddit"],
                    "competitor_names": list(v["competitor_names"])[:3],
                    "competitor_mentions": v["competitor_mentions"],
                }
                for v in sorted(gap_data.values(), key=lambda x: -x["competitor_mentions"])
            ][:6]

    # 4. High-Value Threads — keyword-matching threads with high upvotes
    high_value_threads = []
    keywords_data = client_obj.keywords or {}
    all_keywords = []
    if isinstance(keywords_data, dict):
        for priority_list in keywords_data.values():
            if isinstance(priority_list, list):
                all_keywords.extend([kw.lower() for kw in priority_list])

    if all_keywords and client_sub_ids:
        # Get recent high-engagement threads in client's subreddits
        from app.models.thread import RedditThread
        from app.models.subreddit import ClientSubreddit

        # Get subreddit names for client
        sub_name_list = [s.subreddit_name for s in db.query(Subreddit).filter(Subreddit.id.in_(client_sub_ids)).all() if s.subreddit_name]

        if sub_name_list:
            threads = (
                db.query(RedditThread)
                .filter(
                    RedditThread.subreddit.in_(sub_name_list),
                    RedditThread.ups >= 50,
                    RedditThread.created_at >= datetime.now(timezone.utc) - timedelta(days=14),
                )
                .order_by(RedditThread.ups.desc())
                .limit(30)
                .all()
            )

            for t in threads:
                title_lower = (t.post_title or "").lower()
                body_lower = (t.post_body or "").lower()
                # Check keyword match
                if any(kw in title_lower or kw in body_lower for kw in all_keywords):
                    high_value_threads.append({
                        "title": (t.post_title or "")[:80],
                        "subreddit": t.subreddit or "",
                        "ups": t.ups or 0,
                        "permalink": t.url or "",
                        "competitor_present": False,  # TODO: cross-ref with competitor data
                    })
                    if len(high_value_threads) >= 8:
                        break

    # 5. Locked countdown cards (phase-gated sections)
    locked_sections = []
    # Find client's avatars and their phase info
    client_avatars = (
        db.query(Avatar)
        .filter(Avatar.client_ids.any(str(client_id)), Avatar.active.is_(True))
        .all()
    )
    max_phase = max((a.warming_phase or 0) for a in client_avatars) if client_avatars else 0

    if max_phase < 2:
        # Estimate days to Phase 2
        phase1_avatars = [a for a in client_avatars if (a.warming_phase or 0) == 1]
        avatar_names = [_avatar_display_name(a) for a in phase1_avatars[:2]]
        names_str = " + ".join(avatar_names) if avatar_names else "Your voices"

        # Rough estimate: Phase 1 takes ~30 days from creation
        earliest_created = min((a.created_at for a in client_avatars if a.created_at), default=datetime.now(timezone.utc))
        days_active = (datetime.now(timezone.utc) - earliest_created).days if earliest_created else 0
        days_remaining = max(0, 30 - days_active)

        locked_sections.append({
            "title": "High-Intent Appearances",
            "countdown": f"{names_str} reach Phase 2 in ~{days_remaining} days",
        })
        locked_sections.append({
            "title": "Brand Mention Tracking",
            "countdown": f"Unlocks at Phase 3 (~{max(0, 90 - days_active)} days)",
        })

    return _portal_render(
        request,
        "client/insights.html",
        client_id,
        db,
        active_page="insights",
        extra_context={
            "landscape_report": landscape_report,
            "landscape_date": landscape_date,
            "competitors": competitors,
            "brand_rate": brand_rate,
            "client_brand": client_brand,
            "competitive_gaps": competitive_gaps,
            "high_value_threads": high_value_threads,
            "locked_sections": locked_sections,
        },
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
    import json as _json
    import redis
    from app.config import get_settings
    from app.services.visibility_report import compute_visibility_report

    client_obj = db.query(Client).filter(Client.id == client_id).first()
    if not client_obj:
        raise HTTPException(status_code=404, detail="Client not found")

    # --- 24h Redis cache for visibility report ---
    cache_key = f"ramp:visibility_report:{client_id}"
    cached = None
    try:
        settings = get_settings()
        r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        cached = r.get(cache_key)
    except Exception:
        pass  # Redis down — compute fresh

    if cached:
        report = _json.loads(cached)
    else:
        # Compute full visibility report from GEO batch data
        report = compute_visibility_report(db, client_id, include_excerpts=True)
        try:
            r.setex(cache_key, 86400, _json.dumps(report, default=str))  # 24h TTL
        except Exception:
            pass  # Cache write failure non-blocking

    # Also compute high-intent thread participation (not part of GEO, Reddit-specific)
    from app.models.thread_score import ThreadScore

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

    # Build combined context
    visibility = {
        "geo_enabled": client_obj.geo_monitoring_enabled,
        "has_data": report["has_data"],
        "summary": report["summary"],
        "engines": report["engines"],
        "projected": report["projected"],
        "trend_history": report["trend_history"],
        "trend_chart": report["trend_chart"],
        "competitors": report["competitors"],
        "queries": report["queries"],
        "categories": report["categories"],
        "excerpts": report["excerpts"],
        # Legacy fields for backward compat
        "latest_brand_rate": report["summary"]["latest_brand_rate"],
        "baseline_brand_rate": report["summary"]["baseline_brand_rate"],
        "brand_rate_delta": report["summary"]["brand_rate_delta"],
        "latest_batch_date": report["summary"]["latest_batch_date"],
        "baseline_date": report["summary"]["baseline_date"],
        # High-intent data
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
    sort: str = "newest",
    date_filter: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return draft cards list for review queue (supports pending/approved/posted/expired tabs)."""
    valid_statuses = {"pending", "approved", "posted", "expired"}
    if status not in valid_statuses:
        status = "pending"

    query = (
        db.query(CommentDraft)
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            CommentDraft.status == status,
            Avatar.client_ids.any(str(client_id)),
            Avatar.active.is_(True),
        )
    )
    # For expired/posted, show regardless of avatar frozen state
    if status not in ("expired", "posted"):
        query = query.filter(Avatar.is_frozen.is_(False))
    if avatar_id:
        query = query.filter(CommentDraft.avatar_id == avatar_id)

    # Date filter (for pending/approved tabs)
    if date_filter == "today" and status in ("pending", "approved"):
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(CommentDraft.created_at >= today_start)
    elif date_filter == "7d" and status in ("pending", "approved"):
        query = query.filter(
            CommentDraft.created_at >= datetime.now(timezone.utc) - timedelta(days=7)
        )
    else:
        # Default time windows per tab (when no date_filter or date_filter=all)
        # For posted tab, limit to last 30 days
        if status == "posted":
            query = query.filter(
                CommentDraft.created_at >= datetime.now(timezone.utc) - timedelta(days=30)
            )
        # For pending tab, skip stale drafts older than 14 days — threads are dead by then
        elif status == "pending":
            query = query.filter(
                CommentDraft.created_at >= datetime.now(timezone.utc) - timedelta(days=14)
            )
        # For approved tab, limit to last 14 days (matches count in review header)
        elif status == "approved":
            query = query.filter(
                CommentDraft.created_at >= datetime.now(timezone.utc) - timedelta(days=14)
            )
        # For expired tab, limit to last 30 days
        elif status == "expired":
            query = query.filter(
                CommentDraft.created_at >= datetime.now(timezone.utc) - timedelta(days=30)
            )

    # Sort order
    if sort == "oldest":
        query = query.order_by(CommentDraft.created_at.asc())
    else:
        query = query.order_by(CommentDraft.created_at.desc())

    drafts_raw = query.limit(50).all()

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
            hobby_post = d.hobby_post
            if not hobby_post:
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
            "status": d.status,
            "stale_age_hours": (d.learning_metadata or {}).get("stale_age_hours") if d.learning_metadata else None,
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
            "hidden_actions": get_permission_context(db, client_id, user.user_role).get("hidden_actions", set()),
            "approval_actions": get_permission_context(db, client_id, user.user_role).get("approval_actions", set()),
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

        # Hard gate: plan enforcement — block if monthly limit reached
        try:
            from app.services.plan_enforcement import check_approval_allowed_for_client
            is_allowed, limit_msg = check_approval_allowed_for_client(db, client_id)
            if not is_allowed:
                return JSONResponse(status_code=422, content={"message": limit_msg, "code": "plan_limit_exceeded"})
        except ImportError:
            pass  # plan_enforcement not yet deployed — skip check

        draft.status = "approved"
        db.commit()

        # Sync EPG slot status + create ExecutionTask (so extension/email picks it up)
        try:
            from app.services.epg_executor import sync_slot_status
            sync_slot_status(db, draft.id, "approved")
            db.commit()
        except Exception:
            pass

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
        import traceback
        logger.error(
            "Portal approve UNHANDLED ERROR | draft_id=%s | client_id=%s | error=%s | type=%s | traceback=%s",
            draft_id, client_id, str(e), type(e).__name__, traceback.format_exc(),
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

        # Sync EPG slot status (frees budget slot)
        try:
            from app.services.epg_executor import sync_slot_status
            sync_slot_status(db, draft.id, "rejected")
            db.commit()
        except Exception:
            pass

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
            logger.warning("Portal mark-posted: draft not found | draft_id=%s", draft_id)
            return JSONResponse(status_code=404, content={"message": "Draft not found"})

        avatar = db.query(Avatar).filter(Avatar.id == draft.avatar_id).first()
        if not avatar or str(client_id) not in (avatar.client_ids or []):
            logger.warning(
                "Portal mark-posted: client_id mismatch | draft_id=%s | client_id=%s | avatar_client_ids=%s",
                draft_id, client_id, avatar.client_ids if avatar else None,
            )
            return JSONResponse(status_code=404, content={"message": "Draft not found"})

        if draft.status not in ("approved", "pending"):
            logger.warning(
                "Portal mark-posted: wrong status | draft_id=%s | status=%s",
                draft_id, draft.status,
            )
            return JSONResponse(status_code=422, content={"message": f"Draft is in '{draft.status}' state, expected 'approved'"})

        draft.status = "posted"
        draft.posted_at = datetime.now(timezone.utc)
        if reddit_url.strip():
            draft.reddit_comment_url = reddit_url.strip()

        db.commit()

        # Sync EPG slot status
        try:
            from app.services.epg_executor import sync_slot_status
            sync_slot_status(db, draft.id, "posted")
            db.commit()
        except Exception:
            pass

        # Audit log (best-effort, never blocks response)
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
            logger.warning("Failed to log audit event for mark-posted: %s", e)

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
        try:
            db.rollback()
        except Exception:
            pass
        return JSONResponse(status_code=500, content={"message": "Could not mark as posted. Server error."})


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

    # Hard gate: plan enforcement — block if monthly limit reached
    from app.services.plan_enforcement import check_approval_allowed_for_client
    is_allowed, limit_msg = check_approval_allowed_for_client(db, client_id)
    if not is_allowed:
        return JSONResponse(status_code=422, content={"message": limit_msg, "code": "plan_limit_exceeded"})

    draft.status = "approved"
    db.commit()

    # Sync EPG slot status + create ExecutionTask (so extension/email picks it up)
    try:
        from app.services.epg_executor import sync_slot_status
        sync_slot_status(db, draft.id, "approved")
        db.commit()
    except Exception:
        pass

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
            hobby_post = d.hobby_post
            if not hobby_post:
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
    """Day 1 Landscape Report — status-aware rendering with job tracking."""
    from app.services.onboarding.landscape_report import (
        get_job_status,
        generate_landscape_report_tracked,
    )

    # Check current job status
    status = get_job_status(db, client_id)

    if status["status"] == "completed" and status.get("completed_at"):
        # Check freshness (<24h) — data refreshes daily via scraping
        completed_at = datetime.fromisoformat(status["completed_at"])
        if (datetime.now(timezone.utc) - completed_at) < timedelta(hours=24):
            # Serve cached report
            report = status["report_data"]
            return _portal_render(
                request,
                "client/landscape.html",
                client_id,
                db,
                active_page="landscape",
                extra_context={"landscape": report, "landscape_status": "completed"},
            )
        else:
            # Stale — trigger fresh generation
            report = generate_landscape_report_tracked(db, client_id)
    elif status["status"] in ("pending", "processing"):
        # Already generating — render status page with HTMX poll
        return _portal_render(
            request,
            "client/landscape.html",
            client_id,
            db,
            active_page="landscape",
            extra_context={"landscape_status": "generating", "job_status": status},
        )
    elif status["status"] == "failed":
        # Show error with retry
        return _portal_render(
            request,
            "client/landscape.html",
            client_id,
            db,
            active_page="landscape",
            extra_context={"landscape_status": "failed", "job_status": status},
        )
    else:
        # No job exists — trigger generation
        report = generate_landscape_report_tracked(db, client_id)

    # If result is a processing/dedup response (dict with status key)
    if isinstance(report, dict) and report.get("status") == "processing":
        refreshed_status = get_job_status(db, client_id)
        return _portal_render(
            request,
            "client/landscape.html",
            client_id,
            db,
            active_page="landscape",
            extra_context={"landscape_status": "generating", "job_status": refreshed_status},
        )

    # If result is an error response
    if isinstance(report, dict) and report.get("error"):
        refreshed_status = get_job_status(db, client_id)
        return _portal_render(
            request,
            "client/landscape.html",
            client_id,
            db,
            active_page="landscape",
            extra_context={"landscape_status": "failed", "job_status": refreshed_status},
        )

    # Normal render with report data
    return _portal_render(
        request,
        "client/landscape.html",
        client_id,
        db,
        active_page="landscape",
        extra_context={"landscape": report, "landscape_status": "completed"},
    )


@router.get("/clients/{client_id}/landscape/status", response_class=HTMLResponse)
def portal_landscape_status(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """HTMX polling endpoint — returns partial HTML with current landscape report status."""
    from app.services.onboarding.landscape_report import get_job_status

    status = get_job_status(db, client_id)

    if status["status"] == "completed" and status.get("report_data"):
        # Report is ready — render the full landscape content
        return _portal_render(
            request,
            "client/landscape.html",
            client_id,
            db,
            active_page="landscape",
            extra_context={
                "landscape": status["report_data"],
                "landscape_status": "completed",
            },
        )
    elif status["status"] == "failed":
        # Generation failed — render error state
        return _portal_render(
            request,
            "client/landscape.html",
            client_id,
            db,
            active_page="landscape",
            extra_context={"landscape_status": "failed", "job_status": status},
        )
    else:
        # Still generating — render status page with continued HTMX poll
        return _portal_render(
            request,
            "client/landscape.html",
            client_id,
            db,
            active_page="landscape",
            extra_context={"landscape_status": "generating", "job_status": status},
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

    # Only show client-relevant event types (hide ops noise like scrape, system, pipeline)
    CLIENT_VISIBLE_TYPES = {
        "draft_approved", "draft_posted", "phase_promotion", "phase_demotion",
        "health_alert", "comment_deletion_detected", "karma_milestone",
        "client_onboarded", "avatar_onboarding_complete", "draft_auto_reconciled",
        "generate",
    }

    # Fetch recent events for this client
    events_raw = (
        db.query(ActivityEvent)
        .filter(
            ActivityEvent.client_id == client_id,
            ActivityEvent.created_at >= week_ago,
            ActivityEvent.event_type.in_(CLIENT_VISIBLE_TYPES),
        )
        .order_by(ActivityEvent.created_at.desc())
        .limit(12)
        .all()
    )

    # Build avatar username → display_name map for this client
    client_avatars = (
        db.query(Avatar.reddit_username, Avatar.display_name)
        .filter(Avatar.client_ids.any(str(client_id)))
        .all()
    )
    username_to_display = {
        a.reddit_username: (a.display_name or a.reddit_username.split("_")[0].title())
        for a in client_avatars
        if a.reddit_username
    }

    # Human-readable event formatting
    EVENT_CONFIG = {
        "draft_posted": {"icon": "📤", "tint": "#E6F1FB"},
        "draft_approved": {"icon": "✓", "tint": "#E1F5EE"},
        "phase_promotion": {"icon": "🚀", "tint": "#E6F1FB"},
        "phase_demotion": {"icon": "⚠️", "tint": "#FAEEDA"},
        "health_alert": {"icon": "🚨", "tint": "#FCEBEB"},
        "comment_deletion_detected": {"icon": "❌", "tint": "#FCEBEB"},
        "karma_milestone": {"icon": "⭐", "tint": "#FAECE7"},
        "client_onboarded": {"icon": "🎉", "tint": "#E6F1FB"},
        "avatar_onboarding_complete": {"icon": "✨", "tint": "#E1F5EE"},
        "draft_auto_reconciled": {"icon": "🔗", "tint": "#E6F1FB"},
        "generate": {"icon": "✍️", "tint": "#E1F5EE"},
    }

    def _sanitize_message(msg: str, avatar_username: str = "") -> str:
        """Replace reddit usernames with display names in event messages."""
        if not msg:
            return ""
        # Replace specific avatar username
        if avatar_username and avatar_username in username_to_display:
            display = username_to_display[avatar_username]
            msg = msg.replace(f"u/{avatar_username}", display)
            msg = msg.replace(avatar_username, display)
        # Replace any remaining u/username patterns
        for uname, dname in username_to_display.items():
            msg = msg.replace(f"u/{uname}", dname)
            msg = msg.replace(uname, dname)
        return msg

    events = []
    for ev in events_raw:
        meta = ev.event_metadata or {}
        avatar_username = meta.get("avatar_username", "")
        cfg = EVENT_CONFIG.get(ev.event_type, {"icon": "📡", "tint": "#E6F1FB"})

        events.append({
            "icon": cfg["icon"],
            "tint": cfg["tint"],
            "type": ev.event_type,
            "message": _sanitize_message(ev.message, avatar_username),
            "time": _relative_time(ev.created_at),
            "subreddit": meta.get("subreddit_name", ""),
            "avatar": username_to_display.get(avatar_username, ""),
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


@router.get("/clients/{client_id}/tasks", response_class=HTMLResponse)
def portal_tasks(
    request: Request,
    client_id: UUID,
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client-scoped execution tasks — shows only tasks for this client."""
    from app.models.execution_task import ExecutionTask

    query = (
        db.query(ExecutionTask)
        .filter(ExecutionTask.client_id == client_id)
        .order_by(ExecutionTask.created_at.desc())
    )

    if status:
        query = query.filter(ExecutionTask.status == status)

    tasks = query.limit(100).all()

    # Status counts
    base_q = db.query(ExecutionTask).filter(ExecutionTask.client_id == client_id)
    all_count = base_q.count()
    active_count = base_q.filter(
        ExecutionTask.status.in_(("generated", "emailed", "accepted", "submitted", "url_verified"))
    ).count()
    verified_count = base_q.filter(ExecutionTask.status == "verified").count()
    expired_count = base_q.filter(ExecutionTask.status == "expired").count()

    return _portal_render(
        request,
        "client/tasks.html",
        client_id,
        db,
        active_page="tasks",
        extra_context={
            "tasks": tasks,
            "current_status": status,
            "all_count": all_count,
            "active_count": active_count,
            "verified_count": verified_count,
            "expired_count": expired_count,
        },
    )


# ─── Team Management ─────────────────────────────────────────────────────────


@router.get("/clients/{client_id}/team", response_class=HTMLResponse)
def portal_team(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal team management page."""
    # Only client_admin+ can view team
    current_role = getattr(request.state, "user_role", "")
    can_manage = current_role in ("owner", "partner", "client_admin")

    # Get all users for this client
    team_members = (
        db.query(User)
        .filter(User.client_id == client_id, User.is_active.is_(True))
        .order_by(User.created_at.asc())
        .all()
    )

    members = []
    for m in team_members:
        members.append({
            "id": str(m.id),
            "email": m.email,
            "full_name": m.full_name or "",
            "role": m.role,
            "role_display": (m.role or "").replace("_", " ").title(),
            "email_verified": m.email_verified,
            "created_at": _relative_time(m.created_at),
            "is_current_user": m.id == user.id,
        })

    # Roles that can be invited (client_admin can only add manager/viewer)
    available_roles = []
    if current_role in ("owner", "partner"):
        available_roles = [
            {"value": "client_admin", "label": "Admin"},
            {"value": "client_manager", "label": "Manager"},
            {"value": "client_viewer", "label": "Viewer"},
        ]
    elif current_role == "client_admin":
        available_roles = [
            {"value": "client_manager", "label": "Manager"},
            {"value": "client_viewer", "label": "Viewer"},
        ]

    return _portal_render(
        request,
        "client/team.html",
        client_id,
        db,
        active_page="team",
        extra_context={
            "members": members,
            "can_manage": can_manage,
            "available_roles": available_roles,
        },
    )


@router.post("/clients/{client_id}/team/invite", response_class=HTMLResponse)
def portal_team_invite(
    request: Request,
    client_id: UUID,
    email: str = Form(...),
    role: str = Form(...),
    full_name: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Invite a new team member."""
    from app.services.team_management import validate_team_management
    from app.services.auth import hash_password
    import secrets

    # Validate permission
    try:
        target_role = UserRole(role)
    except ValueError:
        return HTMLResponse(
            content='<span class="text-red-400 text-sm">Invalid role</span>',
            status_code=400,
        )

    validate_team_management(user, target_role, client_id)

    # Check if email already exists
    existing = db.query(User).filter(User.email == email.strip().lower()).first()
    if existing:
        return HTMLResponse(
            content='<span class="text-red-400 text-sm">A user with this email already exists</span>',
            headers={"HX-Trigger": '{"showToast": {"type": "warning", "message": "Email already registered"}}'},
        )

    # Create user with temporary password (they'll reset via email)
    temp_password = secrets.token_urlsafe(16)
    new_user = User(
        email=email.strip().lower(),
        hashed_password=hash_password(temp_password),
        full_name=full_name.strip() or None,
        role=target_role.value,
        client_id=client_id,
        is_active=True,
        email_verified=False,
    )
    db.add(new_user)
    db.flush()

    # Send verification email
    try:
        from app.services.email_verification import send_verification_email
        send_verification_email(db, new_user)
    except Exception as e:
        logger.warning("Failed to send verification email to %s: %s", email, e)

    db.commit()

    logger.info(
        "Team invite: %s invited %s as %s for client %s",
        user.email, email, role, client_id,
    )

    # Return updated member row
    return HTMLResponse(
        content=f'<span class="text-green-400 text-sm">Invited {email} as {role.replace("_", " ")}</span>',
        headers={
            "HX-Trigger": '{"showToast": {"type": "success", "message": "Team member invited. Verification email sent."}, "refreshTeam": true}',
        },
    )


@router.post("/clients/{client_id}/team/{member_id}/remove", response_class=HTMLResponse)
def portal_team_remove(
    request: Request,
    client_id: UUID,
    member_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deactivate a team member."""
    from app.services.team_management import validate_user_deactivation

    target_user = db.query(User).filter(User.id == member_id, User.client_id == client_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Team member not found")

    if target_user.id == user.id:
        return HTMLResponse(
            content='<span class="text-red-400 text-sm">Cannot remove yourself</span>',
            status_code=400,
        )

    validate_user_deactivation(user, target_user)

    target_user.is_active = False
    db.commit()

    logger.info(
        "Team remove: %s deactivated %s from client %s",
        user.email, target_user.email, client_id,
    )

    return HTMLResponse(
        content=f'<span class="text-green-400 text-sm">{target_user.email} removed</span>',
        headers={
            "HX-Trigger": '{"showToast": {"type": "success", "message": "Team member removed."}, "refreshTeam": true}',
        },
    )


# ─── Plan & Billing ──────────────────────────────────────────────────────────


@router.get("/clients/{client_id}/billing", response_class=HTMLResponse)
def portal_billing(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal billing/plan page with Stripe integration."""
    from app.services.billing.billing_service import BillingService, PLAN_TIERS, PLAN_MAX_AVATARS

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    billing_service = BillingService(db)
    billing_configured = billing_service.is_configured()

    plan_type = client.plan_type or "trial"
    subscription_status = client.subscription_status or "trial"
    billing_period_end = client.billing_period_end
    has_stripe_customer = bool(client.stripe_customer_id)

    # Plan display info
    plan_price_cents = PLAN_TIERS.get(plan_type, 0)
    plan_price_display = f"${plan_price_cents // 100}" if plan_price_cents else "Free"

    # Build plan tiers for "Change Plan" section
    all_tiers = []
    for tier, price_cents in PLAN_TIERS.items():
        all_tiers.append({
            "name": tier,
            "display_name": tier.title(),
            "price_cents": price_cents,
            "price_display": f"${price_cents // 100}",
            "max_avatars": PLAN_MAX_AVATARS.get(tier, 1),
            "is_current": tier == plan_type,
        })

    # Get invoices
    invoices = []
    if billing_configured and has_stripe_customer:
        try:
            invoices = billing_service.get_recent_invoices(client_id, limit=12)
        except Exception as e:
            logger.warning("Failed to fetch invoices for client %s: %s", client_id, str(e))

    return _portal_render(
        request,
        "client/billing.html",
        client_id,
        db,
        active_page="billing",
        extra_context={
            "plan_type": plan_type,
            "plan_price_display": plan_price_display,
            "subscription_status": subscription_status,
            "billing_period_end": billing_period_end,
            "billing_configured": billing_configured,
            "has_stripe_customer": has_stripe_customer,
            "all_tiers": all_tiers,
            "invoices": invoices,
        },
    )


@router.post("/clients/{client_id}/billing/manage", response_class=RedirectResponse)
def portal_billing_manage(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create Stripe Customer Portal session and redirect for subscription management."""
    from app.services.billing.billing_service import BillingService

    billing_service = BillingService(db)
    if not billing_service.is_configured():
        raise HTTPException(status_code=400, detail="Billing is not configured")

    return_url = str(request.url_for("portal_billing", client_id=client_id))
    try:
        result = billing_service.create_portal_session(client_id, return_url=return_url)
        return RedirectResponse(url=result.portal_url, status_code=303)
    except (ValueError, RuntimeError) as e:
        logger.error("Portal session creation failed for client %s: %s", client_id, str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/clients/{client_id}/billing/change-plan", response_class=RedirectResponse)
def portal_billing_change_plan(
    request: Request,
    client_id: UUID,
    plan_tier: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create Stripe Checkout session for plan change with prorated billing."""
    from app.services.billing.billing_service import BillingService, PLAN_TIERS

    if plan_tier not in PLAN_TIERS:
        raise HTTPException(status_code=400, detail=f"Invalid plan tier: {plan_tier}")

    billing_service = BillingService(db)
    if not billing_service.is_configured():
        raise HTTPException(status_code=400, detail="Billing is not configured")

    success_url = str(request.url_for("portal_billing", client_id=client_id)) + "?plan_changed=1"
    cancel_url = str(request.url_for("portal_billing", client_id=client_id))

    try:
        result = billing_service.create_plan_change_session(
            client_id=client_id,
            new_plan_tier=plan_tier,
            success_url=success_url,
            cancel_url=cancel_url,
        )
        return RedirectResponse(url=result.session_url, status_code=303)
    except (ValueError, RuntimeError) as e:
        logger.error("Plan change session failed for client %s: %s", client_id, str(e))
        raise HTTPException(status_code=400, detail=str(e))
