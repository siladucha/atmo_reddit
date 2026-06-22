"""Trial Intelligence RBAC guard — restricts access to Owner and Partner roles.

This dependency protects all trial intelligence endpoints (scoring, signals,
conversion analytics). Only platform-level roles (owner, partner) may access
trial conversion data.

Denied access attempts are logged both to the application logger and to the
AuditLog table for compliance visibility.

Usage:
    from app.dependencies.trial_intelligence import require_owner_or_partner

    @router.get("/api/admin/trial-intelligence/scores")
    async def get_scores(user: User = Depends(require_owner_or_partner)):
        ...

Security note — data isolation:
    Trial scoring data (trial_* tables) is never queried from portal routes.
    The portal uses query_scope which filters by client_id, and trial_*
    tables are internal-only analytics tables with no client-facing queries.
    This ensures trial conversion intelligence cannot leak to client users
    even without this RBAC guard.
"""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import get_current_user
from app.logging_config import get_logger
from app.models.user import User
from app.services import audit

logger = get_logger(__name__)


async def require_owner_or_partner(
    request: Request,
    user: User = Depends(get_current_user),
) -> User:
    """RBAC guard: restricts access to Owner and Partner roles only.

    Used on all trial intelligence endpoints.
    Logs denied access attempts to both application logger and AuditLog.

    Args:
        request: FastAPI request (for path/method logging).
        user: Authenticated user from get_current_user dependency.

    Returns:
        The authenticated User if role is owner or partner.

    Raises:
        HTTPException 403: If user role is not owner or partner.
    """
    if user.role not in ("owner", "partner"):
        # Log access denial to application logger
        logger.warning(
            "Trial intelligence access denied: user_id=%s role=%s path=%s",
            user.id,
            user.role,
            request.url.path,
        )

        # Also log to AuditLog table — never block on audit failure
        db: Session = next(get_db())
        try:
            audit.log_action(
                db=db,
                user_id=user.id,
                action="access_denied",
                entity_type="trial_intelligence",
                details={
                    "role": user.role,
                    "path": request.url.path,
                    "method": request.method,
                },
            )
        except Exception:
            pass  # Never block on audit failure
        finally:
            db.close()

        raise HTTPException(
            status_code=403,
            detail="Access restricted to Owner and Partner roles",
        )

    return user
