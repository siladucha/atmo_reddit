"""Dry-run mode helpers.

When the system_setting `dry_run_enabled` is "true", the pipeline UI lets the
operator manually mediate every LLM call: the prompt is rendered to the screen,
the operator runs it through an external LLM, and the response is pasted back.

This module provides the toggle check, the per-client backlog summary, and DB
session helpers used by routes/dry_run.py and templates.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.comment_draft import CommentDraft
from app.models.thread import RedditThread
from app.services.settings import get_setting


def is_dry_run_enabled(db: Session | None = None) -> bool:
    """Return True if dry-run mode is currently turned on.

    Accepts an existing session, or opens its own if None.
    """
    if db is not None:
        return get_setting(db, "dry_run_enabled") == "true"

    own = SessionLocal()
    try:
        return get_setting(own, "dry_run_enabled") == "true"
    finally:
        own.close()


def is_dry_run_enabled_global() -> bool:
    """Jinja2-callable shortcut. Opens its own session each call."""
    return is_dry_run_enabled(None)


def get_unscored_threads(db: Session, client_id: uuid.UUID, limit: int = 50) -> list[RedditThread]:
    """Threads waiting to be scored for a client."""
    stmt = (
        select(RedditThread)
        .where(
            RedditThread.client_id == client_id,
            RedditThread.tag.is_(None),
        )
        .order_by(RedditThread.created_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def get_engage_threads_without_drafts(
    db: Session, client_id: uuid.UUID, limit: int = 50
) -> list[RedditThread]:
    """Engage-tagged threads that have no comment draft yet (need persona+gen)."""
    drafted = (
        select(CommentDraft.thread_id)
        .where(CommentDraft.client_id == client_id)
    )
    stmt = (
        select(RedditThread)
        .where(
            RedditThread.client_id == client_id,
            RedditThread.tag == "engage",
            ~RedditThread.id.in_(drafted),
        )
        .order_by(
            RedditThread.alert.desc(),
            RedditThread.composite.desc(),
            RedditThread.created_at.desc(),
        )
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def get_backlog_counts(db: Session, client_id: uuid.UUID) -> dict:
    """Cheap counts for the dry-run hub page header."""
    unscored = (
        db.query(RedditThread)
        .filter(RedditThread.client_id == client_id, RedditThread.tag.is_(None))
        .count()
    )
    engage_without_drafts = (
        db.query(RedditThread)
        .filter(
            RedditThread.client_id == client_id,
            RedditThread.tag == "engage",
        )
        .count()
        - db.query(CommentDraft)
        .filter(CommentDraft.client_id == client_id)
        .count()
    )
    pending_drafts = (
        db.query(CommentDraft)
        .filter(CommentDraft.client_id == client_id, CommentDraft.status == "pending")
        .count()
    )
    return {
        "unscored": unscored,
        "engage_without_drafts": max(engage_without_drafts, 0),
        "pending_drafts": pending_drafts,
    }
