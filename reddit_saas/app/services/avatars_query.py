"""Avatars listing service — search, filter, sort, group, paginate, batch enrichment.

Built to scale to hundreds of avatars without N+1 queries on client
lookups. Used by the /avatars-page route and its HTMX partials.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, case, literal
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft

logger = logging.getLogger(__name__)


PAGE_SIZE_GRID = 24
PAGE_SIZE_TABLE = 50


def _profile_completeness_pct(avatar: Avatar) -> int:
    """Return profile completeness as integer percentage (0-100)."""
    fields = [
        avatar.voice_profile_md,
        avatar.tone_principles,
        avatar.speech_patterns,
        avatar.vocabulary_lean,
        avatar.hill_i_die_on,
        avatar.helpful_mode_topics,
        avatar.constraints,
    ]
    filled = sum(1 for f in fields if f and str(f).strip())
    return int(round(filled / len(fields) * 100))

SORT_OPTIONS: list[tuple[str, str]] = [
    ("username", "Username A→Z"),
    ("username_desc", "Username Z→A"),
    ("client", "Client A→Z"),
    ("client_desc", "Client Z→A"),
    ("karma_desc", "Karma (high→low)"),
    ("karma_asc", "Karma (low→high)"),
    ("phase_desc", "Phase (high→low)"),
    ("phase_asc", "Phase (low→high)"),
    ("checked_desc", "Recently checked"),
    ("checked_asc", "Stalest first"),
    ("created_desc", "Newest first"),
    ("created_asc", "Oldest first"),
]

STATUS_OPTIONS: list[tuple[str, str]] = [
    ("", "All statuses"),
    ("active", "Active"),
    ("suspended", "Suspended"),
    ("limited", "Limited"),
    ("shadowbanned", "Shadowbanned"),
    ("not_found", "Not Found"),
    ("unknown", "Unknown"),
    ("stale", "Stale (>24h)"),
    ("never_checked", "Never checked"),
]

GROUP_OPTIONS: list[tuple[str, str]] = [
    ("client", "Group by client"),
    ("none", "Flat list"),
]

VIEW_OPTIONS: list[tuple[str, str]] = [
    ("grid", "Grid"),
    ("table", "Table"),
]


@dataclass
class AvatarFilter:
    q: str = ""
    status: str = ""
    client_id: str = ""
    pool: str = ""
    sort: str = "username"
    view: str = "grid"
    group: str = "client"
    page: int = 1

    def with_(self, **kw: Any) -> "AvatarFilter":
        d = self.__dict__.copy()
        d.update(kw)
        return AvatarFilter(**d)

    def query_string(self, **override: Any) -> str:
        from urllib.parse import urlencode
        params = self.__dict__.copy()
        params.update(override)
        # Defaults that don't need to appear in the URL
        defaults = {"q": "", "status": "", "client_id": "", "pool": "", "sort": "username",
                    "view": "grid", "group": "client", "page": 1}
        clean = {k: v for k, v in params.items() if v not in ("", None) and v != defaults.get(k)}
        return urlencode(clean)

    @property
    def has_active_filters(self) -> bool:
        return bool(self.q or self.status or self.client_id or self.pool)


@dataclass
class AvatarGroup:
    """Avatars belonging to a single client (or None = unassigned)."""
    client: Client | None
    avatars: list[Avatar]
    counts: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return str(self.client.id) if self.client else "unassigned"

    @property
    def title(self) -> str:
        return self.client.client_name if self.client else "Unassigned"

    @property
    def brand(self) -> str | None:
        if not self.client:
            return None
        return self.client.brand_name if self.client.brand_name != self.client.client_name else None


@dataclass
class AvatarPage:
    items: list[Avatar]
    page: int
    page_size: int
    filtered_total: int
    total_in_scope: int
    counts: dict
    client_by_id: dict[str, Client]
    available_clients: list[Client]
    filter: AvatarFilter
    groups: list[AvatarGroup] = field(default_factory=list)

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 1
        return max(1, (self.filtered_total + self.page_size - 1) // self.page_size)

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def range_from(self) -> int:
        if self.filtered_total == 0:
            return 0
        return (self.page - 1) * self.page_size + 1

    @property
    def range_to(self) -> int:
        return min(self.filtered_total, self.page * self.page_size)


def _apply_sort(query, sort: str):
    if sort == "username":
        return query.order_by(Avatar.reddit_username.asc())
    if sort == "username_desc":
        return query.order_by(Avatar.reddit_username.desc())
    if sort == "client":
        # Sort by first client_id (alphabetical grouping by client)
        return query.order_by(Avatar.client_ids.asc().nullslast(), Avatar.reddit_username.asc())
    if sort == "client_desc":
        return query.order_by(Avatar.client_ids.desc().nullsfirst(), Avatar.reddit_username.asc())
    if sort == "karma_desc":
        return query.order_by(Avatar.reddit_karma_comment.desc(), Avatar.reddit_username.asc())
    if sort == "karma_asc":
        return query.order_by(Avatar.reddit_karma_comment.asc(), Avatar.reddit_username.asc())
    if sort == "phase_desc":
        return query.order_by(Avatar.warming_phase.desc(), Avatar.reddit_username.asc())
    if sort == "phase_asc":
        return query.order_by(Avatar.warming_phase.asc(), Avatar.reddit_username.asc())
    if sort == "checked_desc":
        return query.order_by(Avatar.reddit_status_checked_at.desc().nullslast(), Avatar.reddit_username.asc())
    if sort == "checked_asc":
        return query.order_by(Avatar.reddit_status_checked_at.asc().nullsfirst(), Avatar.reddit_username.asc())
    if sort == "created_desc":
        return query.order_by(Avatar.created_at.desc())
    if sort == "created_asc":
        return query.order_by(Avatar.created_at.asc())
    return query.order_by(Avatar.reddit_username.asc())


def _apply_status_filter(query, status: str):
    if status == "stale":
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        return query.filter(or_(
            Avatar.reddit_status_checked_at.is_(None),
            Avatar.reddit_status_checked_at < cutoff,
        ))
    if status == "never_checked":
        return query.filter(Avatar.reddit_status_checked_at.is_(None))
    if status in ("limited", "shadowbanned"):
        return query.filter(Avatar.health_status == status)
    if status == "suspended":
        return query.filter(or_(Avatar.reddit_status == status, Avatar.health_status == status))
    if status == "unknown":
        return query.filter(or_(Avatar.reddit_status == status, Avatar.health_status == status))
    if status in ("active", "not_found"):
        return query.filter(Avatar.reddit_status == status)
    return query


def _scope_for_viewer(query, viewer_client_id):
    if viewer_client_id:
        return query.filter(Avatar.client_ids.any(str(viewer_client_id)))
    return query


def get_status_counts(db: Session, viewer_client_id) -> dict:
    """Aggregate counts (in-scope, ignoring filters) — used in stats bar."""
    q = db.query(Avatar.reddit_status, func.count(Avatar.id))
    q = _scope_for_viewer(q, viewer_client_id)
    rows = q.group_by(Avatar.reddit_status).all()

    counts = {"total": 0, "active": 0, "suspended": 0, "not_found": 0, "unknown": 0}
    for status, count in rows:
        counts["total"] += count
        if status in counts:
            counts[status] = count

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    stale_q = db.query(func.count(Avatar.id))
    stale_q = _scope_for_viewer(stale_q, viewer_client_id)
    counts["stale"] = stale_q.filter(or_(
        Avatar.reddit_status_checked_at.is_(None),
        Avatar.reddit_status_checked_at < cutoff,
    )).scalar() or 0

    return counts


def list_available_clients(db: Session, viewer_client_id) -> list[Client]:
    """List clients for filter dropdown. Includes inactive clients since avatars can belong to any."""
    if viewer_client_id:
        return db.query(Client).filter(Client.id == viewer_client_id).all()
    return db.query(Client).order_by(Client.client_name.asc()).all()


def list_avatars_page(
    db: Session,
    f: AvatarFilter,
    viewer_client_id: UUID | None,
) -> AvatarPage:
    """Run filter+sort+paginate and batch-fetch related entities.

    When `f.group == "client"`, all matching avatars are returned (no pagination)
    and grouped by client; per-group collapse is a UI concern.
    When `f.group == "none"`, results are paginated.
    """
    is_grouped = f.group == "client"
    page_size = PAGE_SIZE_TABLE if f.view == "table" else PAGE_SIZE_GRID
    page = max(1, f.page or 1)

    # Total in scope (ignores filters) — for stats
    total_q = db.query(func.count(Avatar.id))
    total_q = _scope_for_viewer(total_q, viewer_client_id)
    total_in_scope = total_q.scalar() or 0

    # Filtered query
    base = db.query(Avatar)
    base = _scope_for_viewer(base, viewer_client_id)

    if f.client_id:
        base = base.filter(Avatar.client_ids.any(f.client_id))

    if f.pool:
        base = base.filter(Avatar.pool == f.pool)

    base = _apply_status_filter(base, f.status)

    if f.q:
        like = f"%{f.q.strip()}%"
        base = base.filter(or_(
            Avatar.reddit_username.ilike(like),
            Avatar.email_address.ilike(like),
        ))

    filtered_total = base.with_entities(func.count(Avatar.id)).scalar() or 0

    if is_grouped:
        # No pagination when grouped — render everything matching, in sort order
        items = _apply_sort(base, f.sort).all()
    else:
        total_pages = max(1, (filtered_total + page_size - 1) // page_size)
        if page > total_pages:
            page = total_pages
        items = (
            _apply_sort(base, f.sort)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

    client_by_id = _batch_fetch_related(db, items, viewer_client_id)
    counts = get_status_counts(db, viewer_client_id)
    available_clients = list_available_clients(db, viewer_client_id)

    groups: list[AvatarGroup] = []
    if is_grouped:
        groups = _group_by_client(items, client_by_id)

    return AvatarPage(
        items=items,
        page=page,
        page_size=page_size if not is_grouped else len(items),
        filtered_total=filtered_total,
        total_in_scope=total_in_scope,
        counts=counts,
        client_by_id=client_by_id,
        available_clients=available_clients,
        filter=f.with_(page=page),
        groups=groups,
    )


def _group_by_client(
    avatars: list[Avatar],
    client_by_id: dict,
) -> list[AvatarGroup]:
    """Bucket avatars by their first client_id (or 'unassigned'), preserve sort order."""
    bucket_order: list[str] = []
    buckets: dict[str, list[Avatar]] = {}

    for a in avatars:
        primary = None
        for cid in (a.client_ids or []):
            if cid and str(cid) in client_by_id:
                primary = str(cid)
                break
        key = primary or "unassigned"
        if key not in buckets:
            buckets[key] = []
            bucket_order.append(key)
        buckets[key].append(a)

    # Sort groups: real clients alphabetically by name, then unassigned at end
    def group_sort_key(key: str) -> tuple[int, str]:
        if key == "unassigned":
            return (1, "")
        client = client_by_id.get(key)
        return (0, (client.client_name if client else "").lower())

    bucket_order.sort(key=group_sort_key)

    groups: list[AvatarGroup] = []
    for key in bucket_order:
        client = client_by_id.get(key) if key != "unassigned" else None
        avatar_list = buckets[key]
        counts = _aggregate_group_status(avatar_list)
        groups.append(AvatarGroup(client=client, avatars=avatar_list, counts=counts))
    return groups


def _aggregate_group_status(avatars: list[Avatar]) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    out = {
        "total": len(avatars),
        "active": 0,
        "suspended": 0,
        "limited": 0,
        "shadowbanned": 0,
        "not_found": 0,
        "unknown": 0,
        "stale": 0,
    }
    for a in avatars:
        if a.reddit_status in out:
            out[a.reddit_status] += 1
        if a.health_status in ("limited", "shadowbanned"):
            out[a.health_status] += 1
        elif a.health_status == "suspended" and a.reddit_status != "suspended":
            out["suspended"] += 1
        if not a.reddit_status_checked_at or a.reddit_status_checked_at < cutoff:
            out["stale"] += 1
    return out


def _batch_fetch_related(
    db: Session,
    avatars: list[Avatar],
    viewer_client_id,
) -> dict:
    """Fetch all referenced clients in 1 query."""
    all_client_ids: set[str] = set()
    for a in avatars:
        for cid in (a.client_ids or []):
            if cid:
                all_client_ids.add(str(cid))

    if not all_client_ids:
        return {}

    clients = db.query(Client).filter(Client.id.in_(all_client_ids)).all()
    client_by_id = {str(c.id): c for c in clients}

    return client_by_id


def _is_cqs_stale(cqs_checked_at: datetime | None) -> bool:
    """Return True if CQS was checked more than 14 days ago or never."""
    if not cqs_checked_at:
        return False  # Never checked — show as "—", not stale
    age = datetime.now(timezone.utc) - cqs_checked_at
    return age > timedelta(days=14)


# --- Batched health metrics (eliminates N+1 queries) ---

MAX_BRAND_RATIO = 0.3  # mirror from safety.py


def _format_relative_time(when: datetime | None, now: datetime) -> str | None:
    """Format `when` as a relative-time string (e.g. '5 min ago')."""
    if not when:
        return None
    delta = now - when
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    years = days // 365
    return f"{years}y ago"


def _health_status_to_color(health_status: str | None) -> str:
    if health_status == "healthy":
        return "green"
    elif health_status == "limited":
        return "yellow"
    elif health_status in ("shadowbanned", "suspended"):
        return "red"
    return "grey"


def batch_get_health_for_list(db: Session, avatars: list[Avatar]) -> dict[str, dict]:
    """Batch-compute health metrics for a list of avatars in 1 DB query.

    Returns a dict keyed by avatar.id (str) with the same shape as
    get_avatar_health() from safety.py, minus the expensive
    check_promotion_eligibility call (not needed on list views).

    Instead of N × 2 COUNT queries, runs a single GROUP BY.
    """
    if not avatars:
        return {}

    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)

    avatar_ids = [a.id for a in avatars]

    # Single query: count week_comments and week_professional per avatar
    try:
        rows = (
            db.query(
                CommentDraft.avatar_id,
                func.count(CommentDraft.id).label("week_comments"),
                func.sum(
                    case(
                        (CommentDraft.type == "professional", literal(1)),
                        else_=literal(0),
                    )
                ).label("week_professional"),
            )
            .filter(
                CommentDraft.avatar_id.in_(avatar_ids),
                CommentDraft.status.in_(["approved", "posted"]),
                CommentDraft.created_at >= week_start,
            )
            .group_by(CommentDraft.avatar_id)
            .all()
        )
        stats_by_id = {
            str(r.avatar_id): {
                "week_comments": r.week_comments or 0,
                "week_professional": int(r.week_professional or 0),
            }
            for r in rows
        }
    except Exception as e:
        logger.error(f"batch_get_health_for_list DB error: {e}")
        stats_by_id = {}

    # Build health dict per avatar from in-memory data + batch stats
    result: dict[str, dict] = {}
    phase_labels = {
        0: "Mentor",
        1: "Credibility Building",
        2: "Content Seeding",
        3: "Brand Integration",
    }

    for avatar in avatars:
        aid = str(avatar.id)
        stats = stats_by_id.get(aid, {"week_comments": 0, "week_professional": 0})
        week_comments = stats["week_comments"]
        week_professional = stats["week_professional"]
        brand_ratio = week_professional / week_comments if week_comments > 0 else 0
        account_age = (now - avatar.created_at).days if avatar.created_at else 0

        checked_at = avatar.reddit_status_checked_at
        reddit_status_stale = bool(checked_at and (now - checked_at) > timedelta(hours=24))

        karma_discrepancy = False
        if avatar.reddit_status == "active" and avatar.karma_comment > 0:
            diff = abs(avatar.reddit_karma_comment - avatar.karma_comment)
            if diff / max(avatar.karma_comment, 1) > 0.1:
                karma_discrepancy = True

        reddit_account_age_days = None
        if avatar.reddit_account_created:
            reddit_account_age_days = (now - avatar.reddit_account_created).days

        result[aid] = {
            "id": aid,
            "username": avatar.reddit_username,
            "active": avatar.active,
            "shadowbanned": avatar.is_shadowbanned,
            "account_age_days": account_age,
            "warming_phase": avatar.warming_phase,
            "phase_label": phase_labels.get(avatar.warming_phase, "Unknown"),
            "phase_progress": {},  # Skip on list view — too expensive per avatar
            "phase_eligible_for_next": False,  # Skip on list view
            "karma_comment": avatar.karma_comment,
            "karma_post": avatar.karma_post,
            "week_comments": week_comments,
            "week_professional": week_professional,
            "brand_ratio": round(brand_ratio, 2),
            "brand_ratio_ok": brand_ratio <= MAX_BRAND_RATIO,
            "last_health_check": avatar.last_health_check.isoformat() if avatar.last_health_check else None,
            "health_status": avatar.health_status or "unknown",
            "health_color": _health_status_to_color(avatar.health_status),
            "health_check_relative": _format_relative_time(avatar.last_health_check, now) or "Never checked",
            # Reddit status cache
            "reddit_status": avatar.reddit_status,
            "reddit_karma_comment": avatar.reddit_karma_comment,
            "reddit_karma_post": avatar.reddit_karma_post,
            "reddit_account_created": avatar.reddit_account_created,
            "reddit_account_age_days": reddit_account_age_days,
            "reddit_icon_url": avatar.reddit_icon_url,
            "reddit_status_checked_at": avatar.reddit_status_checked_at,
            "reddit_status_checked_relative": _format_relative_time(checked_at, now),
            "reddit_status_stale": reddit_status_stale,
            "karma_discrepancy": karma_discrepancy,
        }

    return result


def build_avatar_view(
    avatar: Avatar,
    health: dict,
    client_by_id: dict,
    top_subreddits: list | None = None,
) -> dict:
    """Merge get_avatar_health + batched related entities into a template dict.

    `top_subreddits` is an optional list of SubredditKarma rows to surface as
    a compact summary on cards/rows (Req 5). Caller is responsible for
    batch-fetching them via karma_tracker.top_subreddits_for_avatars.
    """
    client_ids = [str(cid) for cid in (avatar.client_ids or []) if cid]
    clients = [client_by_id[cid] for cid in client_ids if cid in client_by_id]

    top_summary: list[dict] = []
    for r in (top_subreddits or []):
        total = (r.comment_karma or 0) + (r.post_karma or 0)
        top_summary.append({
            "subreddit_name": r.subreddit_name,
            "total_karma": total,
            "comment_karma": r.comment_karma or 0,
            "post_karma": r.post_karma or 0,
            "type": r.subreddit_type or "unknown",
        })

    out = dict(health)
    out.update({
        "email_address": avatar.email_address,
        "active_flag": avatar.active,
        "pool": getattr(avatar, "pool", "b2b"),
        "industry": getattr(avatar, "industry", None),
        "is_frozen": avatar.is_frozen,
        "freeze_reason": avatar.freeze_reason,
        "frozen_at": avatar.frozen_at,
        "voice_profile_md": avatar.voice_profile_md,
        "tone_principles": avatar.tone_principles,
        "speech_patterns": avatar.speech_patterns,
        "hill_i_die_on": avatar.hill_i_die_on,
        "helpful_mode_topics": avatar.helpful_mode_topics,
        "constraints": avatar.constraints,
        "vocabulary_lean": avatar.vocabulary_lean,
        "hobby_subreddits": avatar.hobby_subreddits or [],
        "business_subreddits": avatar.business_subreddits or [],
        "created_at": avatar.created_at,
        "clients": [{"id": str(c.id), "name": c.client_name, "brand": c.brand_name} for c in clients],
        "top_subreddits": top_summary,
        # CQS (Contributor Quality Score)
        "cqs_level": avatar.cqs_level,
        "cqs_checked_at": avatar.cqs_checked_at,
        "cqs_stale": _is_cqs_stale(avatar.cqs_checked_at),
        # Profile completeness (7 voice/personality fields)
        "profile_pct": _profile_completeness_pct(avatar),
        # Posting
        "posting_mode": avatar.posting_mode or "disabled",
        "last_posted_at": avatar.last_posted_at,
        "consecutive_post_failures": avatar.consecutive_post_failures or 0,
        "has_proxy": bool(avatar.proxy_url_encrypted),
        "has_credentials": bool(avatar.reddit_password_encrypted or avatar.refresh_token_encrypted),
    })
    return out
