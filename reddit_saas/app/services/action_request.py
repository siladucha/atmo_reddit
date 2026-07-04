"""ActionRequest service — create, approve, reject approval-tier portal actions.

Handles the full lifecycle of ActionRequest records:
- create_action_request: deduplication + creation + audit
- approve_action_request: state transition + action execution + audit + notification
- reject_action_request: state transition + audit + notification
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.action_request import ActionRequest
from app.models.user import User
from app.services.audit.audit_logging import log_action
from app.services.notifications import notify_client

logger = get_logger(__name__)


def create_action_request(
    db: Session,
    client_id: uuid.UUID,
    user_id: uuid.UUID,
    action_type: str,
    payload: dict | None = None,
) -> ActionRequest | None:
    """Create an ActionRequest with deduplication.

    Returns None if a duplicate pending request exists (same client_id +
    action_type + matching payload). Otherwise creates and returns the new
    ActionRequest with status='pending'.
    """
    # Deduplication: check for existing pending with same client + action_type + payload
    existing = (
        db.query(ActionRequest)
        .filter(
            ActionRequest.client_id == client_id,
            ActionRequest.action_type == action_type,
            ActionRequest.status == "pending",
        )
        .all()
    )

    for req in existing:
        if _payloads_match(req.payload, payload):
            logger.debug(
                "Duplicate pending ActionRequest found: client=%s action=%s",
                client_id,
                action_type,
            )
            return None

    # Create new request
    ar = ActionRequest(
        id=uuid.uuid4(),
        client_id=client_id,
        user_id=user_id,
        action_type=action_type,
        payload=payload,
        status="pending",
    )
    db.add(ar)
    db.flush()

    # Audit log
    log_action(
        db,
        user_id,
        "action_request_created",
        entity_type="action_request",
        entity_id=ar.id,
        client_id=client_id,
        details={"action_type": action_type},
    )

    return ar


def approve_action_request(
    db: Session,
    request_id: uuid.UUID,
    resolver: User,
) -> ActionRequest:
    """Approve an ActionRequest: execute the action, audit, and notify.

    Sets status='approved', resolved_at=now, resolved_by=resolver.id.
    Calls the appropriate action executor. Logs audit and sends notification.
    """
    ar = db.query(ActionRequest).filter(ActionRequest.id == request_id).one()

    ar.status = "approved"
    ar.resolved_at = datetime.now(timezone.utc)
    ar.resolved_by = resolver.id
    db.flush()

    # Execute the action
    _execute_action(db, ar)

    # Audit log
    log_action(
        db,
        resolver.id,
        "action_request_resolved",
        entity_type="action_request",
        entity_id=ar.id,
        client_id=ar.client_id,
        details={"action_type": ar.action_type, "outcome": "approved"},
    )

    # Notify requesting user
    notify_client(
        db,
        ar.client_id,
        user_id=ar.user_id,
        type="success",
        title=f"Request approved: {ar.action_type}",
        body=f"Your request to {ar.action_type.replace('_', ' ')} has been approved and executed.",
        link=f"/clients/{ar.client_id}/requests",
    )

    return ar


def reject_action_request(
    db: Session,
    request_id: uuid.UUID,
    resolver: User,
    reason: str = "",
) -> ActionRequest:
    """Reject an ActionRequest: set status, audit, and notify.

    Sets status='rejected', resolved_at=now, resolved_by=resolver.id,
    rejection_reason=reason. Does NOT execute the action.
    """
    ar = db.query(ActionRequest).filter(ActionRequest.id == request_id).one()

    ar.status = "rejected"
    ar.resolved_at = datetime.now(timezone.utc)
    ar.resolved_by = resolver.id
    ar.rejection_reason = reason
    db.flush()

    # Audit log
    log_action(
        db,
        resolver.id,
        "action_request_resolved",
        entity_type="action_request",
        entity_id=ar.id,
        client_id=ar.client_id,
        details={
            "action_type": ar.action_type,
            "outcome": "rejected",
            "reason": reason,
        },
    )

    # Notify requesting user
    notify_client(
        db,
        ar.client_id,
        user_id=ar.user_id,
        type="warning",
        title=f"Request rejected: {ar.action_type}",
        body=reason or f"Your request to {ar.action_type.replace('_', ' ')} was not approved.",
        link=f"/clients/{ar.client_id}/requests",
    )

    return ar


def _execute_action(db: Session, ar: ActionRequest) -> None:
    """Dispatch the approved action to its executor."""
    from app.services.action_executors import ACTION_EXECUTORS

    executor = ACTION_EXECUTORS.get(ar.action_type)
    if executor is None:
        logger.warning(
            "No executor registered for action_type=%s (request_id=%s)",
            ar.action_type,
            ar.id,
        )
        return

    try:
        executor(db, ar.client_id, ar.user_id, ar.payload)
    except Exception as e:
        logger.error(
            "Action executor failed for %s (request_id=%s): %s",
            ar.action_type,
            ar.id,
            e,
        )
        raise


def _payloads_match(existing: dict | None, new: dict | None) -> bool:
    """Compare two payloads for deduplication purposes.

    Both None = match. One None + one empty dict = match.
    Otherwise deep equality check.
    """
    # Normalize None ↔ empty dict
    a = existing if existing else {}
    b = new if new else {}
    return a == b
