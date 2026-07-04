"""Plan enforcement — hard gate for monthly comment limits.

Provides a reusable check that MUST be called before any draft approval
(portal, admin, decision center, auto-approve). This is the hard gate that
prevents exceeding max_comments_per_month regardless of how drafts are approved.

Architecture:
- Soft gate: portfolio_manager.py limits EPG GENERATION budget (preventive)
- Hard gate: THIS SERVICE blocks APPROVAL if monthly cap already reached (definitive)

Both gates must exist. The soft gate prevents generating more than needed.
The hard gate catches edge cases: manual approval, race conditions, direct API calls.
"""

from app.logging_config import get_logger
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft

logger = get_logger(__name__)


class PlanLimitExceeded(Exception):
    """Raised when a plan limit (monthly comments) is exceeded."""

    def __init__(self, message: str, current: int, limit: int):
        super().__init__(message)
        self.current = current
        self.limit = limit


def check_monthly_comment_limit(db: Session, client_id: UUID) -> tuple[bool, str]:
    """Check if a client has exceeded their monthly comment limit.

    Returns (is_allowed, message).
    - (True, "") — approval is permitted
    - (False, "Monthly limit reached (30/30)") — block approval

    This function is FAST (single COUNT query) and safe to call on every
    draft approval without performance concern.
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        # Client not found — allow (fail-open for orphan drafts)
        return True, ""

    # If no monthly limit configured, always allow
    max_comments = getattr(client, "max_comments_per_month", None)
    if not max_comments:
        return True, ""

    # Count approved + posted drafts this month for ALL avatars of this client
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Get all avatar IDs for this client
    avatar_ids = (
        db.query(Avatar.id)
        .filter(Avatar.client_ids.any(str(client_id)))
        .all()
    )
    avatar_id_list = [a.id for a in avatar_ids]

    if not avatar_id_list:
        return True, ""

    # Count drafts approved or posted this month
    monthly_used = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id.in_(avatar_id_list),
            CommentDraft.status.in_(["approved", "posted"]),
            CommentDraft.updated_at >= month_start,
        )
        .scalar() or 0
    )

    if monthly_used >= max_comments:
        msg = f"Monthly comment limit reached ({monthly_used}/{max_comments})"
        logger.warning(
            "PLAN_LIMIT_BLOCKED | client_id=%s | used=%d | limit=%d",
            client_id, monthly_used, max_comments,
        )
        return False, msg

    return True, ""


def check_draft_approval_allowed(db: Session, draft_id: UUID) -> tuple[bool, str]:
    """Check if a specific draft can be approved (plan limit check).

    Resolves client from draft → avatar → client_ids, then calls
    check_monthly_comment_limit.

    Returns (is_allowed, message).
    """
    draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
    if not draft:
        return True, ""  # Draft not found — let caller handle 404

    if not draft.avatar_id:
        return True, ""  # No avatar → no client → allow

    avatar = db.query(Avatar).filter(Avatar.id == draft.avatar_id).first()
    if not avatar or not avatar.client_ids:
        return True, ""  # No client association → allow

    # Check limit for the first (primary) client
    try:
        client_id = UUID(avatar.client_ids[0])
    except (ValueError, IndexError):
        return True, ""

    return check_monthly_comment_limit(db, client_id)


def check_approval_allowed_for_client(db: Session, client_id: UUID) -> tuple[bool, str]:
    """Convenience wrapper — check if client can approve more drafts.

    Same as check_monthly_comment_limit but with a clearer name for route handlers.
    """
    return check_monthly_comment_limit(db, client_id)
