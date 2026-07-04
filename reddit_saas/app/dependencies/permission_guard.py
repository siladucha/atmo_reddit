"""Permission Guard — FastAPI dependency that enforces the permission matrix.

Usage:
    @router.post("/clients/{client_id}/actions/pipeline")
    def trigger_pipeline(
        ...,
        user: User = Depends(require_permission("trigger_pipeline")),
    ):
        ...  # only reached for self_service tier

For approval_required tier, the guard raises PermissionRequiresApproval
which the route handler catches to create an ActionRequest instead.
"""

import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import get_current_user
from app.logging_config import get_logger
from app.models.client import Client
from app.models.user import User
from app.models.user_role import UserRole
from app.services.permission_map import PermissionTier, get_effective_tier

logger = get_logger(__name__)


class PermissionRequiresApproval(Exception):
    """Raised when the action needs an ActionRequest instead of immediate execution."""

    def __init__(self, action_id: str, client_id: uuid.UUID, user: User):
        self.action_id = action_id
        self.client_id = client_id
        self.user = user


# Actions that are read-only (client_viewer is allowed to perform these)
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


def require_permission(action_id: str):
    """Factory: returns a dependency that enforces the permission tier for action_id.

    Pipeline order:
    1. Internal role bypass (owner/partner/superuser → return user)
    2. Must be client-scoped
    3. client_viewer + write → 403 + log
    4. Resolve client_id from path or user
    5. Load client permission_matrix
    6. get_effective_tier
    7. self_service → return user
    8. approval_required + is_write → raise PermissionRequiresApproval
    9. admin_only → 403 + log
    """

    async def _guard(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        # (1) Internal roles bypass permission matrix entirely
        if user.user_role in (UserRole.owner, UserRole.partner):
            return user
        if user.is_superuser:
            return user

        # (2) Must be client-scoped to proceed
        if not user.user_role.is_client_scoped:
            raise HTTPException(status_code=403, detail="Access Denied")

        # (3) client_viewer: deny all write actions
        is_write = action_id not in READ_ONLY_ACTIONS
        if user.user_role == UserRole.client_viewer and is_write:
            _log_denial(db, user, action_id, "viewer_restricted")
            raise HTTPException(status_code=403, detail="Access Denied")

        # (4) Resolve client_id from path or user
        client_id = _resolve_client_id(request, user)
        if not client_id:
            raise HTTPException(status_code=403, detail="Access Denied")

        # (5) Load client permission_matrix
        client = db.query(Client).filter(Client.id == client_id).first()
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        matrix = client.permission_matrix or {}

        # (6) Resolve effective tier
        tier = get_effective_tier(matrix, action_id)

        # (7) self_service → allow
        if tier == PermissionTier.self_service:
            return user

        # (8) approval_required + write → raise for ActionRequest creation
        if tier == PermissionTier.approval_required:
            if is_write:
                raise PermissionRequiresApproval(action_id, client_id, user)
            # Read-only approval-tier actions are still viewable
            return user

        # (9) admin_only → deny + log
        _log_denial(db, user, action_id, "admin_only")
        raise HTTPException(status_code=403, detail="Access Denied")

    return _guard


def _resolve_client_id(request: Request, user: User) -> uuid.UUID | None:
    """Extract client_id from path params or fall back to user's assigned client."""
    raw = request.path_params.get("client_id")
    if raw:
        try:
            return uuid.UUID(str(raw))
        except (ValueError, AttributeError):
            pass
    return user.client_id


def _log_denial(db: Session, user: User, action_id: str, reason: str) -> None:
    """Log permission denial to AuditLog. Failure is swallowed to not block the 403."""
    from app.services.audit.audit_logging import log_action

    try:
        log_action(
            db=db,
            user_id=user.id,
            action="permission_denied",
            entity_type="permission",
            client_id=user.client_id,
            details={"action_type": action_id, "reason": reason},
        )
    except Exception:
        logger.warning(
            "Failed to log permission denial | user_id=%s | action=%s | reason=%s",
            user.id,
            action_id,
            reason,
        )
