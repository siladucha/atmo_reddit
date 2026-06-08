"""Posting Dashboard — Operational Posting Calendar.

Day-based view: Date → Client → Avatar → Posts
Answers: What was posted? What is scheduled? What is expected?

Provides:
- GET /admin/posting-dashboard — page shell with day tabs (yesterday/today/tomorrow)
- GET /admin/posting-dashboard/day — day view partial (HTMX)
- GET /admin/posting-dashboard/posting-log — posting log secondary section (HTMX)
"""

from app.logging_config import get_logger
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, case, and_
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import require_platform_admin
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.epg_slot import EPGSlot
from app.models.posting_event import PostingEvent
from app.models.user import User

logger = get_logger(__name__)

router = APIRouter(prefix="/admin/posting-dashboard", tags=["posting-dashboard"])
templates = Jinja2Templates(directory="app/templates")
templates.env.cache = {}
from app.version import __version__ as app_version
from app.config import get_settings as _get_settings

templates.env.globals["app_version"] = app_version
templates.env.globals["posting_disabled"] = lambda: _get_settings().posting_disabled

from app.template_filters import register_filters
register_filters(templates.env)

TZ_JERUSALEM = ZoneInfo("Asia/Jerusalem")


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class AvatarDayView:
    """Per-avatar summary for a given day."""
    avatar_id: str
    reddit_username: str
    warming_phase: int
    daily_limit: int
    published: int = 0
    failed: int = 0
    scheduled: int = 0
    skipped: int = 0
    next_slot_time: str = ""
    is_healthy: bool = True
    health_note: str = ""
    issues: list[str] = field(default_factory=list)  # skip reasons / failure messages


@dataclass
class ClientDayView:
    """Per-client summary for a given day."""
    client_id: str
    client_name: str
    avatars: list[AvatarDayView] = field(default_factory=list)
    published: int = 0
    failed: int = 0
    scheduled: int = 0
    expected_today: int = 0


@dataclass
class DaySummary:
    """Top-level day summary."""
    date: date
    date_label: str  # "Today", "Yesterday", "Tomorrow", or formatted date
    published: int = 0
    failed: int = 0
    scheduled: int = 0
    expected_eod: int = 0  # Only for today
    clients: list[ClientDayView] = field(default_factory=list)
    is_today: bool = False
    is_tomorrow: bool = False
    no_schedule_message: str = ""  # For tomorrow when no schedule exists


# ============================================================================
# Helper: Phase daily limits
# ============================================================================

PHASE_DAILY_LIMITS = {0: 0, 1: 3, 2: 7, 3: 18}


def _get_avatar_daily_limit(avatar: Avatar) -> int:
    """Get daily posting limit for an avatar based on phase."""
    limit = PHASE_DAILY_LIMITS.get(avatar.warming_phase, 0)
    if avatar.warming_phase == 1 and getattr(avatar, 'cqs_level', None) == "lowest":
        limit = 1
    return limit


# ============================================================================
# Core Query: Build day view
# ============================================================================


def build_day_view(db: Session, target_date: date) -> DaySummary:
    """Build the full day view: Client → Avatar → Posts breakdown."""
    now = datetime.now(TZ_JERUSALEM)
    today = now.date()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    # Determine label
    if target_date == today:
        label = "Today"
        is_today = True
        is_tomorrow = False
    elif target_date == yesterday:
        label = "Yesterday"
        is_today = False
        is_tomorrow = False
    elif target_date == tomorrow:
        label = "Tomorrow"
        is_today = False
        is_tomorrow = True
    else:
        label = target_date.strftime("%B %d, %Y")
        is_today = False
        is_tomorrow = False

    summary = DaySummary(
        date=target_date,
        date_label=label,
        is_today=is_today,
        is_tomorrow=is_tomorrow,
    )

    # --- Get EPG slots for this date ---
    slots = (
        db.query(EPGSlot)
        .filter(EPGSlot.plan_date == target_date)
        .order_by(EPGSlot.scheduled_at.asc().nullslast())
        .all()
    )

    if not slots and is_tomorrow:
        summary.no_schedule_message = "Tomorrow schedule not generated yet"
        return summary

    # --- Get posting events for this date ---
    day_start_utc = datetime.combine(target_date, time.min).replace(tzinfo=TZ_JERUSALEM)
    day_end_utc = datetime.combine(target_date + timedelta(days=1), time.min).replace(tzinfo=TZ_JERUSALEM)

    posting_events = (
        db.query(PostingEvent)
        .filter(
            PostingEvent.posted_at >= day_start_utc,
            PostingEvent.posted_at < day_end_utc,
        )
        .all()
    )

    # Index events by avatar_id
    events_by_avatar: dict[uuid.UUID, list[PostingEvent]] = {}
    for ev in posting_events:
        events_by_avatar.setdefault(ev.avatar_id, []).append(ev)

    # --- Load avatars and clients ---
    avatar_ids = set(s.avatar_id for s in slots) | set(ev.avatar_id for ev in posting_events)
    if not avatar_ids:
        if is_tomorrow:
            summary.no_schedule_message = "Tomorrow schedule not generated yet"
        return summary

    avatars = db.query(Avatar).filter(Avatar.id.in_(avatar_ids)).all()
    avatar_map = {a.id: a for a in avatars}

    # Collect client IDs from slots and avatars
    client_ids = set()
    for s in slots:
        if s.client_id:
            client_ids.add(s.client_id)
    for a in avatars:
        if a.client_ids:
            for cid in a.client_ids:
                try:
                    client_ids.add(uuid.UUID(cid))
                except (ValueError, TypeError):
                    pass

    clients = db.query(Client).filter(Client.id.in_(client_ids)).all() if client_ids else []
    client_map = {c.id: c for c in clients}

    # --- Build per-avatar data ---
    # Group slots by (client_id, avatar_id)
    slot_groups: dict[tuple[uuid.UUID | None, uuid.UUID], list[EPGSlot]] = {}
    for s in slots:
        key = (s.client_id, s.avatar_id)
        slot_groups.setdefault(key, []).append(s)

    # Also ensure avatars with posting events but no slots are included
    for avatar_id, evts in events_by_avatar.items():
        avatar = avatar_map.get(avatar_id)
        if avatar and avatar.client_ids:
            try:
                cid = uuid.UUID(avatar.client_ids[0])
            except (ValueError, TypeError, IndexError):
                cid = None
            key = (cid, avatar_id)
            if key not in slot_groups:
                slot_groups[key] = []

    # --- Build client views ---
    client_views: dict[uuid.UUID | None, ClientDayView] = {}

    for (client_id, avatar_id), avatar_slots in slot_groups.items():
        avatar = avatar_map.get(avatar_id)
        if not avatar:
            continue

        # Get or create client view
        if client_id not in client_views:
            client = client_map.get(client_id)
            client_views[client_id] = ClientDayView(
                client_id=str(client_id) if client_id else "",
                client_name=client.client_name if client else "No Client",
            )

        cv = client_views[client_id]

        # Count published/failed from posting events
        avatar_events = events_by_avatar.get(avatar_id, [])
        published = sum(1 for e in avatar_events if e.outcome == "success")
        failed = sum(1 for e in avatar_events if e.outcome == "failure")

        # Collect issues: skip reasons from EPG slots + error messages from posting events
        issues: list[str] = []
        skipped = 0
        for s in avatar_slots:
            if s.status == "skipped" and s.skip_reason:
                skipped += 1
                reason = s.skip_reason[:80]
                if reason not in issues:
                    issues.append(reason)
        for e in avatar_events:
            if e.outcome == "failure" and e.error_message:
                msg = e.error_message[:80]
                if msg not in issues:
                    issues.append(msg)

        # Count scheduled (approved slots with scheduled_at in the future for today)
        scheduled = 0
        next_slot_time = ""
        for s in avatar_slots:
            if s.status in ("approved", "generated") and s.scheduled_at:
                if is_today and s.scheduled_at > now:
                    scheduled += 1
                    if not next_slot_time:
                        local_time = s.scheduled_at.astimezone(TZ_JERUSALEM)
                        next_slot_time = local_time.strftime("%H:%M")
                elif is_tomorrow:
                    scheduled += 1
                    if not next_slot_time:
                        local_time = s.scheduled_at.astimezone(TZ_JERUSALEM)
                        next_slot_time = local_time.strftime("%H:%M")

        # For historical days, scheduled = 0 (they either posted or didn't)
        if not is_today and not is_tomorrow:
            scheduled = 0

        # Health
        is_healthy = not avatar.is_frozen and avatar.health_status not in ("shadowbanned", "suspended")
        health_note = ""
        if avatar.is_frozen:
            health_note = f"Frozen: {avatar.freeze_reason or 'unknown'}"
        elif avatar.health_status in ("shadowbanned", "suspended"):
            health_note = avatar.health_status

        daily_limit = _get_avatar_daily_limit(avatar)

        av = AvatarDayView(
            avatar_id=str(avatar_id),
            reddit_username=avatar.reddit_username,
            warming_phase=avatar.warming_phase,
            daily_limit=daily_limit,
            published=published,
            failed=failed,
            scheduled=scheduled,
            skipped=skipped,
            next_slot_time=next_slot_time,
            is_healthy=is_healthy,
            health_note=health_note,
            issues=issues,
        )
        cv.avatars.append(av)
        cv.published += published
        cv.failed += failed
        cv.scheduled += scheduled

    # Compute expected_today for each client (for today view only)
    if is_today:
        for cv in client_views.values():
            cv.expected_today = cv.published + cv.scheduled

    # Sort clients by name, avatars by username
    sorted_clients = sorted(client_views.values(), key=lambda c: c.client_name)
    for cv in sorted_clients:
        cv.avatars.sort(key=lambda a: a.reddit_username)

    summary.clients = sorted_clients
    summary.published = sum(cv.published for cv in sorted_clients)
    summary.failed = sum(cv.failed for cv in sorted_clients)
    summary.scheduled = sum(cv.scheduled for cv in sorted_clients)
    summary.expected_eod = summary.published + summary.scheduled if is_today else 0

    return summary


# ============================================================================
# Endpoints
# ============================================================================


@router.get("", response_class=HTMLResponse)
def posting_dashboard_page(
    request: Request,
    current_user: User = Depends(require_platform_admin),
):
    """Render the posting dashboard page shell with day navigation."""
    today = datetime.now(TZ_JERUSALEM).date()
    return templates.TemplateResponse(
        name="admin_posting_dashboard.html",
        context={
            "request": request,
            "current_user": current_user,
            "active_nav": "posting-dashboard",
            "now_jerusalem_date": today,
            "timedelta": timedelta,
        },
        request=request,
    )


@router.get("/day", response_class=HTMLResponse)
def posting_dashboard_day(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
    target_date: date | None = None,
):
    """Return a single day view as HTMX partial.

    If target_date not provided, defaults to today (Asia/Jerusalem).
    """
    if target_date is None:
        target_date = datetime.now(TZ_JERUSALEM).date()

    day_view = build_day_view(db, target_date)

    return templates.TemplateResponse(
        name="partials/posting_dashboard_day.html",
        context={
            "request": request,
            "day": day_view,
        },
        request=request,
    )


@router.get("/posting-log", response_class=HTMLResponse)
def posting_dashboard_posting_log(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
    limit: int = Query(default=30),
):
    """Return posting log as secondary HTMX partial (last N events)."""
    events = (
        db.query(PostingEvent, Avatar.reddit_username)
        .join(Avatar, Avatar.id == PostingEvent.avatar_id)
        .order_by(PostingEvent.posted_at.desc())
        .limit(limit)
        .all()
    )

    log_rows = []
    for ev, username in events:
        posted_local = ev.posted_at.astimezone(TZ_JERUSALEM).strftime("%m/%d %H:%M") if ev.posted_at else "—"
        log_rows.append({
            "avatar": username,
            "outcome": ev.outcome,
            "posted_at": posted_local,
            "duration_ms": ev.duration_ms,
            "url": ev.reddit_comment_url,
            "error": ev.error_message,
        })

    return templates.TemplateResponse(
        name="partials/posting_dashboard_log.html",
        context={
            "request": request,
            "log_rows": log_rows,
        },
        request=request,
    )
