import uuid
from datetime import datetime

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def log_action(
    db: Session,
    user_id: uuid.UUID,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    details: dict | None = None,
) -> AuditLog:
    """Create an audit log entry for an admin action.

    Args:
        db: SQLAlchemy database session.
        user_id: The admin user performing the action.
        action: Action performed, e.g. "create", "update", "deactivate", "trigger_pipeline".
        entity_type: Type of entity affected, e.g. "client", "user", "persona", "keyword", "subreddit".
        entity_id: ID of the affected entity (optional).
        client_id: Client context for the action (optional).
        details: Additional JSON details about the action (optional).

    Returns:
        The created AuditLog record.
    """
    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        client_id=client_id,
        details=details,
    )
    db.add(entry)
    db.flush()
    db.commit()
    db.refresh(entry)
    return entry


def log_system_action(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    details: dict | None = None,
) -> AuditLog:
    """Create an audit log entry for a system/background action (no user).

    Used by background tasks, error handlers, and automated processes.
    """
    entry = AuditLog(
        user_id=None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        client_id=client_id,
        details=details,
    )
    db.add(entry)
    db.flush()
    db.commit()
    db.refresh(entry)
    return entry


def query_audit_logs(
    db: Session,
    page: int = 1,
    per_page: int = 20,
    user_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    search: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[list[AuditLog], int]:
    """Query audit log entries with pagination and optional filters.

    Args:
        db: SQLAlchemy database session.
        page: Page number (1-indexed).
        per_page: Number of entries per page.
        user_id: Filter by the admin user who performed the action.
        client_id: Filter by client context.
        action: Filter by action type (e.g. "create", "update").
        entity_type: Filter by entity type (e.g. "avatar", "client", "comment_draft").
        search: Free-text search in details JSONB (case-insensitive).
        date_from: Include only entries created at or after this datetime.
        date_to: Include only entries created at or before this datetime.

    Returns:
        A tuple of (entries, total_count) where entries is the paginated list
        and total_count is the total number of matching records.
    """
    query = db.query(AuditLog)

    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if client_id is not None:
        query = query.filter(AuditLog.client_id == client_id)
    if action is not None:
        query = query.filter(AuditLog.action == action)
    if entity_type is not None:
        query = query.filter(AuditLog.entity_type == entity_type)
    if search:
        # Search across action, entity_type, and details JSONB (case-insensitive)
        from sqlalchemy import cast, String as SAString, or_
        search_filter = or_(
            AuditLog.action.ilike(f"%{search}%"),
            AuditLog.entity_type.ilike(f"%{search}%"),
            cast(AuditLog.details, SAString).ilike(f"%{search}%"),
        )
        query = query.filter(search_filter)
    if date_from is not None:
        query = query.filter(AuditLog.created_at >= date_from)
    if date_to is not None:
        query = query.filter(AuditLog.created_at <= date_to)

    total = query.count()

    offset = (page - 1) * per_page
    entries = (
        query
        .order_by(desc(AuditLog.created_at))
        .offset(offset)
        .limit(per_page)
        .all()
    )

    return entries, total


def get_distinct_entity_types(db: Session) -> list[str]:
    """Return all distinct entity_type values from audit logs."""
    from sqlalchemy import distinct
    rows = (
        db.query(distinct(AuditLog.entity_type))
        .filter(AuditLog.entity_type.isnot(None))
        .order_by(AuditLog.entity_type)
        .all()
    )
    return [r[0] for r in rows]


def get_distinct_actions(db: Session) -> list[str]:
    """Return all distinct action values from audit logs."""
    from sqlalchemy import distinct
    rows = (
        db.query(distinct(AuditLog.action))
        .filter(AuditLog.action.isnot(None))
        .order_by(AuditLog.action)
        .all()
    )
    return [r[0] for r in rows]


def delete_all_audit_logs(db: Session) -> int:
    """Delete all audit log entries.

    Returns:
        The number of deleted records.
    """
    count = db.query(AuditLog).count()
    db.query(AuditLog).delete()
    db.commit()
    return count


def delete_filtered_audit_logs(
    db: Session,
    user_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    search: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> int:
    """Delete audit log entries matching the given filters.

    Returns:
        The number of deleted records.
    """
    query = db.query(AuditLog)

    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if client_id is not None:
        query = query.filter(AuditLog.client_id == client_id)
    if action is not None:
        query = query.filter(AuditLog.action == action)
    if entity_type is not None:
        query = query.filter(AuditLog.entity_type == entity_type)
    if search:
        from sqlalchemy import cast, String as SAString, or_
        search_filter = or_(
            AuditLog.action.ilike(f"%{search}%"),
            AuditLog.entity_type.ilike(f"%{search}%"),
            cast(AuditLog.details, SAString).ilike(f"%{search}%"),
        )
        query = query.filter(search_filter)
    if date_from is not None:
        query = query.filter(AuditLog.created_at >= date_from)
    if date_to is not None:
        query = query.filter(AuditLog.created_at <= date_to)

    count = query.count()
    query.delete(synchronize_session=False)
    db.commit()
    return count
