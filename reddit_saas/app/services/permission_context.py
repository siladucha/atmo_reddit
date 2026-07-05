"""Permission context helper — builds template variables for tier-aware rendering.

Used by portal routes to inject permission visibility into Jinja2 templates:
- hidden_actions: controls that should not appear (admin_only tier)
- approval_actions: controls that show "Requires Approval" badge
- pending_requests_count: sidebar badge for pending ActionRequests
"""

import uuid

from sqlalchemy.orm import Session

from app.models.action_request import ActionRequest
from app.models.client import Client
from app.models.user_role import UserRole
from app.services.permission_map import DEFAULT_PERMISSION_MAP, get_effective_tier

# Actions that are read-only (client_viewer is allowed to see these)
READ_ONLY_ACTIONS: frozenset[str] = frozenset([
    "view_avatars",
    "view_avatar_detail",
    "view_report",
    "view_activity_log",
    "view_settings",
    "view_subreddits",
    "view_keywords",
    "view_epg_schedule",
])


def get_permission_context(
    db: Session, client_id: uuid.UUID, user_role: UserRole
) -> dict:
    """Build permission context dict for Jinja2 templates.

    Args:
        db: SQLAlchemy session.
        client_id: The client whose permission matrix to evaluate.
        user_role: The current user's role (determines viewer restrictions).

    Returns:
        {
            "hidden_actions": set[str],       # admin_only → hide controls
            "approval_actions": set[str],     # approval_required → show badge
            "pending_requests_count": int,    # sidebar badge
        }
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    try:
        matrix = client.permission_matrix if client else {}
    except Exception:
        matrix = {}

    hidden: set[str] = set()
    approval: set[str] = set()

    for action_id in DEFAULT_PERMISSION_MAP:
        tier = get_effective_tier(matrix, action_id)
        if tier == "admin_only":
            hidden.add(action_id)
        elif tier == "approval_required":
            approval.add(action_id)

    # Viewers are read-only: hide ALL non-read actions regardless of tier
    if user_role == UserRole.client_viewer:
        hidden.update(
            action_id
            for action_id in DEFAULT_PERMISSION_MAP
            if action_id not in READ_ONLY_ACTIONS
        )

    # Count pending requests for the client
    pending_count = 0
    if client:
        try:
            pending_count = (
                db.query(ActionRequest)
                .filter(
                    ActionRequest.client_id == client_id,
                    ActionRequest.status == "pending",
                )
                .count()
            )
        except Exception:
            # Table may not exist yet (migration not applied) — degrade gracefully
            db.rollback()
            pending_count = 0

    return {
        "hidden_actions": hidden,
        "approval_actions": approval,
        "pending_requests_count": pending_count,
    }
