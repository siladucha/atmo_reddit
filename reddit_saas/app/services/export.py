"""JSON export service — serializes SQLAlchemy models to JSON-safe dicts."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.activity_event import ActivityEvent
from app.models.ai_usage import AIUsageLog
from app.models.audit import AuditLog
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.post_draft import PostDraft
from app.models.subreddit import ClientSubreddit, ClientSubredditAssignment, Subreddit
from app.models.thread import RedditThread
from app.models.user import User


def _serialize_value(val: Any) -> Any:
    """Convert a single value to a JSON-safe type."""
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return str(val)
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, (list, tuple)):
        return [_serialize_value(v) for v in val]
    if isinstance(val, dict):
        return {k: _serialize_value(v) for k, v in val.items()}
    return val


# ---------------------------------------------------------------------------
# Entity serializers
# ---------------------------------------------------------------------------


def serialize_client(client: Client) -> dict:
    return {
        "id": str(client.id),
        "client_name": client.client_name,
        "brand_name": client.brand_name,
        "company_profile": client.company_profile,
        "company_worldview": client.company_worldview,
        "company_problem": client.company_problem,
        "competitive_landscape": client.competitive_landscape,
        "brand_voice": client.brand_voice,
        "case_studies": client.case_studies,
        "icp_profiles": client.icp_profiles,
        "keywords": client.keywords,
        "brand_domain": client.brand_domain,
        "is_active": client.is_active,
        "created_at": _serialize_value(client.created_at),
    }


def serialize_avatar(avatar: Avatar, profile_snapshot=None) -> dict:
    data = {
        "id": str(avatar.id),
        "reddit_username": avatar.reddit_username,
        "active": avatar.active,
        "client_ids": avatar.client_ids,
        "voice_profile_md": avatar.voice_profile_md,
        "tone_principles": avatar.tone_principles,
        "speech_patterns": avatar.speech_patterns,
        "hill_i_die_on": avatar.hill_i_die_on,
        "helpful_mode_topics": avatar.helpful_mode_topics,
        "constraints": avatar.constraints,
        "vocabulary_lean": avatar.vocabulary_lean,
        "hobby_subreddits": avatar.hobby_subreddits,
        "business_subreddits": avatar.business_subreddits,
        "karma_post": avatar.karma_post,
        "karma_comment": avatar.karma_comment,
        "is_shadowbanned": avatar.is_shadowbanned,
        "reddit_status": avatar.reddit_status,
        "reddit_karma_comment": avatar.reddit_karma_comment,
        "reddit_karma_post": avatar.reddit_karma_post,
        "reddit_account_created": _serialize_value(avatar.reddit_account_created),
        "warming_phase": avatar.warming_phase,
        "phase_changed_at": _serialize_value(avatar.phase_changed_at),
        "created_at": _serialize_value(avatar.created_at),
    }

    # Include profile analytics snapshot if available
    if profile_snapshot:
        data["profile_analytics"] = {
            "fetched_at": _serialize_value(profile_snapshot.fetched_at),
            "comment_karma": profile_snapshot.comment_karma,
            "post_karma": profile_snapshot.post_karma,
            "total_karma": profile_snapshot.total_karma,
            "account_age_days": profile_snapshot.account_age_days,
            "account_created": _serialize_value(profile_snapshot.account_created),
            "has_verified_email": profile_snapshot.has_verified_email,
            "is_gold": profile_snapshot.is_gold,
            "is_mod": profile_snapshot.is_mod,
            "total_comments": profile_snapshot.total_comments,
            "total_posts": profile_snapshot.total_posts,
            "avg_comments_per_week": profile_snapshot.avg_comments_per_week,
            "avg_posts_per_week": profile_snapshot.avg_posts_per_week,
            "most_active_hour_utc": profile_snapshot.most_active_hour_utc,
            "most_active_day": profile_snapshot.most_active_day,
            "days_since_last_comment": profile_snapshot.days_since_last_comment,
            "days_since_last_post": profile_snapshot.days_since_last_post,
            "avg_comment_length": profile_snapshot.avg_comment_length,
            "avg_post_length": profile_snapshot.avg_post_length,
            "uses_emoji": profile_snapshot.uses_emoji,
            "uses_links": profile_snapshot.uses_links,
            "avg_comment_score": profile_snapshot.avg_comment_score,
            "avg_post_score": profile_snapshot.avg_post_score,
            "top_comment_score": profile_snapshot.top_comment_score,
            "top_post_score": profile_snapshot.top_post_score,
            "subreddits": profile_snapshot.subreddits_data,
            "recent_comments": profile_snapshot.recent_comments_data,
            "recent_posts": profile_snapshot.recent_posts_data,
        }

    return data


def serialize_thread(thread: RedditThread) -> dict:
    return {
        "id": str(thread.id),
        "client_id": _serialize_value(thread.client_id),
        "subreddit": thread.subreddit,
        "post_title": thread.post_title,
        "post_body": thread.post_body,
        "url": thread.url,
        "author": thread.author,
        "score": thread.score,
        "tag": thread.tag,
        "composite": thread.composite,
        "scraped_at": _serialize_value(thread.scraped_at),
        "created_at": _serialize_value(thread.created_at),
    }


def serialize_comment_draft(draft: CommentDraft) -> dict:
    return {
        "id": str(draft.id),
        "thread_id": str(draft.thread_id),
        "client_id": str(draft.client_id),
        "avatar_id": str(draft.avatar_id),
        "type": draft.type,
        "ai_draft": draft.ai_draft,
        "edited_draft": draft.edited_draft,
        "comment_to": draft.comment_to,
        "comment_approach": draft.comment_approach,
        "strategic_angle": draft.strategic_angle,
        "engagement_mode": draft.engagement_mode,
        "status": draft.status,
        "reddit_score": draft.reddit_score,
        "posted_at": _serialize_value(draft.posted_at),
        "created_at": _serialize_value(draft.created_at),
    }


def serialize_subreddit_assignment(assignment: ClientSubredditAssignment) -> dict:
    sub = assignment.subreddit
    return {
        "id": str(assignment.id),
        "client_id": str(assignment.client_id),
        "subreddit_name": sub.subreddit_name if sub else None,
        "type": assignment.type,
        "is_active": assignment.is_active,
        "last_scraped_at": _serialize_value(sub.last_scraped_at) if sub else None,
        "created_at": _serialize_value(assignment.created_at),
    }


def serialize_ai_usage(log: AIUsageLog) -> dict:
    return {
        "id": str(log.id),
        "client_id": _serialize_value(log.client_id),
        "operation": log.operation,
        "model": log.model,
        "input_tokens": log.input_tokens,
        "output_tokens": log.output_tokens,
        "cost_usd": float(log.cost_usd) if log.cost_usd else 0,
        "duration_ms": log.duration_ms,
        "created_at": _serialize_value(log.created_at),
    }


def serialize_audit_log(log: AuditLog) -> dict:
    return {
        "id": str(log.id),
        "user_id": _serialize_value(log.user_id),
        "client_id": _serialize_value(log.client_id),
        "action": log.action,
        "entity_type": log.entity_type,
        "entity_id": _serialize_value(log.entity_id),
        "details": log.details,
        "created_at": _serialize_value(log.created_at),
    }


def serialize_user(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": getattr(user, "full_name", None),
        "is_superuser": user.is_superuser,
        "is_active": user.is_active,
        "client_id": _serialize_value(getattr(user, "client_id", None)),
        "created_at": _serialize_value(user.created_at),
    }


def serialize_activity_event(event: ActivityEvent) -> dict:
    return {
        "id": str(event.id),
        "client_id": _serialize_value(event.client_id),
        "event_type": event.event_type,
        "message": event.message,
        "metadata": event.event_metadata,
        "created_at": _serialize_value(event.created_at),
    }


# ---------------------------------------------------------------------------
# Bulk export functions
# ---------------------------------------------------------------------------


def export_clients(db: Session) -> list[dict]:
    clients = db.query(Client).order_by(Client.client_name).all()
    return [serialize_client(c) for c in clients]


def export_avatars(db: Session, client_id: uuid.UUID | None = None) -> list[dict]:
    from app.models.avatar_profile_snapshot import AvatarProfileSnapshot

    q = db.query(Avatar).order_by(Avatar.reddit_username)
    if client_id:
        q = q.filter(Avatar.client_ids.any(str(client_id)))
    avatars = q.all()

    # Batch-load latest snapshots for all avatars
    avatar_ids = [a.id for a in avatars]
    snapshots_map: dict[uuid.UUID, AvatarProfileSnapshot] = {}
    if avatar_ids:
        # Subquery to get the latest snapshot per avatar
        from sqlalchemy import desc
        from sqlalchemy.orm import aliased

        for avatar_id in avatar_ids:
            snapshot = (
                db.query(AvatarProfileSnapshot)
                .filter(AvatarProfileSnapshot.avatar_id == avatar_id)
                .order_by(desc(AvatarProfileSnapshot.fetched_at))
                .first()
            )
            if snapshot:
                snapshots_map[avatar_id] = snapshot

    return [
        serialize_avatar(a, profile_snapshot=snapshots_map.get(a.id))
        for a in avatars
    ]


def export_single_avatar(db: Session, avatar_id: uuid.UUID) -> dict | None:
    """Export a single avatar with its latest profile analytics snapshot."""
    from app.models.avatar_profile_snapshot import AvatarProfileSnapshot
    from sqlalchemy import desc

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return None

    snapshot = (
        db.query(AvatarProfileSnapshot)
        .filter(AvatarProfileSnapshot.avatar_id == avatar_id)
        .order_by(desc(AvatarProfileSnapshot.fetched_at))
        .first()
    )

    return serialize_avatar(avatar, profile_snapshot=snapshot)


def export_threads(
    db: Session,
    client_id: uuid.UUID | None = None,
    tag: str | None = None,
) -> list[dict]:
    q = db.query(RedditThread).order_by(RedditThread.created_at.desc())
    if client_id:
        q = q.filter(RedditThread.client_id == client_id)
    if tag:
        q = q.filter(RedditThread.tag == tag)
    return [serialize_thread(t) for t in q.limit(5000).all()]


def export_comment_drafts(
    db: Session,
    client_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[dict]:
    q = db.query(CommentDraft).order_by(CommentDraft.created_at.desc())
    if client_id:
        q = q.filter(CommentDraft.client_id == client_id)
    if status:
        q = q.filter(CommentDraft.status == status)
    return [serialize_comment_draft(d) for d in q.limit(5000).all()]


def export_subreddits(
    db: Session,
    client_id: uuid.UUID | None = None,
) -> list[dict]:
    q = (
        db.query(ClientSubredditAssignment)
        .join(Subreddit, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .order_by(Subreddit.subreddit_name)
    )
    if client_id:
        q = q.filter(ClientSubredditAssignment.client_id == client_id)
    return [serialize_subreddit_assignment(a) for a in q.all()]


def export_ai_usage(
    db: Session,
    client_id: uuid.UUID | None = None,
) -> list[dict]:
    q = db.query(AIUsageLog).order_by(AIUsageLog.created_at.desc())
    if client_id:
        q = q.filter(AIUsageLog.client_id == client_id)
    return [serialize_ai_usage(log) for log in q.limit(5000).all()]


def export_audit_logs(
    db: Session,
    client_id: uuid.UUID | None = None,
) -> list[dict]:
    q = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if client_id:
        q = q.filter(AuditLog.client_id == client_id)
    return [serialize_audit_log(log) for log in q.limit(5000).all()]


def export_users(db: Session) -> list[dict]:
    users = db.query(User).order_by(User.email).all()
    return [serialize_user(u) for u in users]


def export_activity_events(
    db: Session,
    client_id: uuid.UUID | None = None,
) -> list[dict]:
    q = db.query(ActivityEvent).order_by(ActivityEvent.created_at.desc())
    if client_id:
        q = q.filter(ActivityEvent.client_id == client_id)
    return [serialize_activity_event(e) for e in q.limit(5000).all()]
