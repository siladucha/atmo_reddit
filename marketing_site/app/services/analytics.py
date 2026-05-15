from uuid import UUID
from datetime import datetime
from dataclasses import dataclass
from sqlalchemy.orm import Session
from app.models.analytics_event import AnalyticsEvent


@dataclass
class EventPayload:
    visitor_id: UUID
    event_type: str
    event_data: dict | None
    page_path: str
    timestamp: datetime


def validate_event(payload: dict) -> EventPayload | None:
    """Validate an event payload. Returns None if invalid."""
    if not isinstance(payload, dict):
        return None

    # Validate visitor_id (required, must be valid UUID)
    raw_visitor_id = payload.get("visitor_id")
    if raw_visitor_id is None:
        return None
    if isinstance(raw_visitor_id, UUID):
        visitor_id = raw_visitor_id
    else:
        try:
            visitor_id = UUID(str(raw_visitor_id))
        except (ValueError, AttributeError):
            return None

    # Validate event_type (required, non-empty string)
    event_type = payload.get("event_type")
    if not event_type or not isinstance(event_type, str) or not event_type.strip():
        return None

    # Validate timestamp (required, valid datetime or ISO string)
    raw_timestamp = payload.get("timestamp")
    if raw_timestamp is None:
        return None
    if isinstance(raw_timestamp, datetime):
        timestamp = raw_timestamp
    else:
        try:
            timestamp = datetime.fromisoformat(str(raw_timestamp))
        except (ValueError, TypeError):
            return None

    # Optional fields
    event_data = payload.get("event_data")
    if event_data is not None and not isinstance(event_data, dict):
        event_data = None

    page_path = payload.get("page_path", "")
    if not isinstance(page_path, str):
        page_path = str(page_path) if page_path is not None else ""

    return EventPayload(
        visitor_id=visitor_id,
        event_type=event_type.strip(),
        event_data=event_data,
        page_path=page_path,
        timestamp=timestamp,
    )


def store_events(db: Session, events: list[EventPayload]) -> int:
    """Bulk insert validated events. Returns count of stored events."""
    if not events:
        return 0

    records = [
        AnalyticsEvent(
            visitor_id=event.visitor_id,
            event_type=event.event_type,
            event_data=event.event_data,
            page_path=event.page_path,
            timestamp=event.timestamp,
        )
        for event in events
    ]
    db.add_all(records)
    db.commit()
    return len(records)
