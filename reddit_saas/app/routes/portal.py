"""Client Portal — Routes.

New dark-themed client-facing portal. Separate from admin panel.
All routes require client access (RBAC enforced).
"""

import logging
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

    # Inject user info from auth middleware
    ctx["user_name"] = getattr(request.state, "user_full_name", "") or ""
    ctx["user_email"] = getattr(request.state, "user_email", "") or ""
    ctx["user_role"] = getattr(request.state, "user_role", "") or ""

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
        .filter(Avatar.client_ids.any(str(client_id)))
        .order_by(Avatar.reddit_username.asc())
        .all()
    )
    avatar_options = [{"id": str(a.id), "name": a.reddit_username} for a in avatars_for_filter]

    return _portal_render(
        request,
        "client/review.html",
        client_id,
        db,
        active_page="review",
        extra_context={
            "pending_count": sidebar["pending_count"],
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
        avatars.append(view)
    return _portal_render(
        request,
        "client/avatars.html",
        client_id,
        db,
        active_page="avatars",
        extra_context={"avatars": avatars},
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
        activity.append({
            "subreddit": d.thread.subreddit if d.thread else "",
            "thread_title": (d.thread.post_title[:60] if d.thread else ""),
            "text": (d.edited_draft or d.ai_draft or "")[:120],
            "status": d.status,
            "reddit_score": d.reddit_score,
            "created_at": _relative_time(d.created_at),
        })

    avatar_data = {
        "id": str(avatar.id),
        "username": avatar.reddit_username,
        "active": avatar.active,
        "warming_phase": avatar.warming_phase,
        "is_frozen": avatar.is_frozen,
        "freeze_reason": avatar.freeze_reason,
        "reddit_karma_comment": avatar.reddit_karma_comment or 0,
        "reddit_karma_post": avatar.reddit_karma_post or 0,
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

    return _portal_render(
        request,
        "client/avatar_detail.html",
        client_id,
        db,
        active_page="avatars",
        extra_context={"avatar": avatar_data, "activity": activity},
    )


@router.get("/clients/{client_id}/settings", response_class=HTMLResponse)
def portal_settings(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal settings — company profile and configuration."""
    client_obj = db.query(Client).filter(Client.id == client_id).first()

    profile = {
        "company_profile": client_obj.company_profile or "",
        "company_worldview": client_obj.company_worldview or "",
        "company_problem": client_obj.company_problem or "",
        "competitive_landscape": client_obj.competitive_landscape or "",
        "brand_voice": client_obj.brand_voice or "",
        "icp_profiles": client_obj.icp_profiles or "",
        "case_studies": client_obj.case_studies or "",
        "brand_domain": client_obj.brand_domain or "",
    } if client_obj else {}

    can_edit = user.user_role in (UserRole.client_admin, UserRole.client_manager, UserRole.owner, UserRole.partner)

    return _portal_render(
        request,
        "client/settings.html",
        client_id,
        db,
        active_page="settings",
        extra_context={"profile": profile, "can_edit": can_edit},
    )


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
    avatar_options = [{"id": str(a.id), "name": a.reddit_username} for a in all_avatars]

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
                "avatar_name": avatar.reddit_username,
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
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Client portal report — full insights page."""
    from app.models.comment_draft import CommentDraft
    from app.models.thread import RedditThread
    from app.models.subreddit import ClientSubredditAssignment, Subreddit

    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)

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
            "avatar": c.avatar.reddit_username if c.avatar else "",
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

    report = {
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
    }

    return _portal_render(
        request,
        "client/report.html",
        client_id,
        db,
        active_page="report",
        extra_context={"report": report},
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
    avatar_id: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return draft cards list for review queue."""
    query = (
        db.query(CommentDraft)
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            CommentDraft.status == "pending",
            Avatar.client_ids.any(str(client_id)),
        )
    )
    if avatar_id:
        query = query.filter(CommentDraft.avatar_id == avatar_id)

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

        drafts.append({
            "id": str(d.id),
            "avatar_name": avatar.reddit_username if avatar else "Unknown",
            "avatar_phase": avatar.warming_phase if avatar else 1,
            "subreddit_name": sub_name,
            "thread_title": thread_title,
            "thread_url": thread_url,
            "thread_body_excerpt": body_excerpt,
            "comment_text": d.edited_draft or d.ai_draft or "",
            "comment_approach": getattr(d, "comment_approach", None),
            "created_at_relative": _relative_time(d.created_at),
            "safety_block": safety_block,
            "is_hobby": d.type == "hobby",
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
    db.commit()

    # Audit log
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
                "avatar": avatar.reddit_username,
                "source": "client_portal",
            },
        )
    except Exception as e:
        logger.warning("Failed to log audit event: %s", e)

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
    db.commit()

    # Audit log
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
                "avatar": avatar.reddit_username,
                "source": "client_portal",
            },
        )
    except Exception as e:
        logger.warning("Failed to log audit event: %s", e)

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
        from app.services.learning import capture_edit_record
        capture_edit_record(db, draft, user_action="edit")
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
            "HX-Trigger": '{"showToast": {"type": "success", "message": "Got it — we\'ll remember this for future drafts"}}'
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
            "username": avatar.reddit_username,
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
            "avatar": d.avatar.reddit_username if d.avatar else "?",
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
