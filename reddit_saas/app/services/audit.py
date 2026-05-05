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


def query_audit_logs(
    db: Session,
    page: int = 1,
    per_page: int = 20,
    user_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    action: str | None = None,
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
