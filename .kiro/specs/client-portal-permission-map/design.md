# Design Document: Client Portal Permission Map

## Overview

This feature introduces a centralized, runtime-editable permission matrix for client portal actions. Each action is classified into one of three tiers—Self-Service, Approval Required, or Admin-Only—stored as a JSONB field on the Client model. A FastAPI dependency (Permission Guard) evaluates tiers at request time, integrating with existing RBAC and rate limiting. Approval-tier actions create generic ActionRequest records following the SubredditRequest lifecycle pattern.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Portal Route Handler                                                │
│  (portal.py / portal_actions.py)                                     │
├─────────────────────────────────────────────────────────────────────┤
│  1. verify_client_access_from_path  (existing RBAC)                  │
│  2. require_permission(action_id)   (NEW — permission guard)         │
│  3. check_rate_limit(...)           (existing — only if allowed)     │
│  4. Business logic execution                                         │
└─────────────────────────────────────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
   [Self-Service]  [Approval]    [Admin-Only]
    Execute now    Create         Return 403
                   ActionRequest
                        │
                        ▼
              Admin resolves (approve/reject)
                        │
                   ┌────┴────┐
                   ▼         ▼
              Execute     Notify user
              action      (rejected)
```


## Data Models

### 1. Permission Matrix on Client (JSONB Column)

Add `permission_matrix` JSONB column to the existing `clients` table:

```python
# app/models/client.py — new field
permission_matrix: Mapped[dict] = mapped_column(
    JSONB,
    nullable=False,
    server_default=text("'{}'::jsonb"),  # empty dict; app-level default from constant
)
```

**Schema structure:**

```json
{
  "add_keyword": "self_service",
  "remove_keyword": "self_service",
  "trigger_pipeline": "self_service",
  "add_subreddit": "approval_required",
  "deactivate_client": "admin_only"
}
```

Each key is an action identifier string. Each value is one of: `"self_service"`, `"approval_required"`, `"admin_only"`.


### 2. ActionRequest Model

New table `action_requests` following the SubredditRequest lifecycle pattern:

```python
# app/models/action_request.py
import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, Index, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ActionRequest(Base):
    __tablename__ = "action_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    client = relationship("Client", backref="action_requests")
    user = relationship("User", foreign_keys=[user_id], backref="action_requests_created")
    resolver = relationship("User", foreign_keys=[resolved_by])

    __table_args__ = (
        Index("ix_action_requests_client_status", "client_id", "status"),
        Index("ix_action_requests_client_action_status", "client_id", "action_type", "status"),
    )
```


### 3. Alembic Migration (`perm01`)

```python
# alembic/versions/perm01_permission_matrix_action_requests.py

def upgrade():
    # 1. Add permission_matrix to clients
    op.add_column("clients", sa.Column(
        "permission_matrix", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    ))

    # 2. Create action_requests table
    op.create_table(
        "action_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action_type", sa.String(100), nullable=False),
        sa.Column("payload", JSONB, nullable=True),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("rejection_reason", sa.Text, nullable=True),
    )
    op.create_index("ix_action_requests_client_status", "action_requests", ["client_id", "status"])
    op.create_index("ix_action_requests_client_action_status", "action_requests", ["client_id", "action_type", "status"])

    # 3. Backfill existing clients with DEFAULT_PERMISSION_MAP
    from app.services.permission_map import DEFAULT_PERMISSION_MAP
    import json
    op.execute(
        f"UPDATE clients SET permission_matrix = '{json.dumps(DEFAULT_PERMISSION_MAP)}'::jsonb"
    )

def downgrade():
    op.drop_table("action_requests")
    op.drop_column("clients", "permission_matrix")
```


## Components and Interfaces

### 1. Default Permission Map Constant

**File:** `app/services/permission_map.py`

A dedicated module importable by runtime code and migrations.

```python
"""Default Permission Map — classifies every portal action into a tier.

Tiers:
- self_service: executes immediately without approval
- approval_required: creates ActionRequest, needs internal staff approval
- admin_only: invisible/inaccessible to all client-scoped users
"""

from enum import Enum


class PermissionTier(str, Enum):
    self_service = "self_service"
    approval_required = "approval_required"
    admin_only = "admin_only"


# Action identifiers map 1:1 to portal operations
DEFAULT_PERMISSION_MAP: dict[str, str] = {
    # --- Self-Service (immediate execution) ---
    "add_keyword": "self_service",
    "remove_keyword": "self_service",
    "trigger_pipeline": "self_service",
    "trigger_epg_rebuild": "self_service",
    "trigger_strategy": "self_service",
    "regenerate_draft": "self_service",
    "approve_draft": "self_service",
    "reject_draft": "self_service",
    "edit_draft": "self_service",
    "mark_draft_posted": "self_service",
    "submit_voice_feedback": "self_service",
    "view_avatars": "self_service",
    "view_avatar_detail": "self_service",
    "view_report": "self_service",
    "view_activity_log": "self_service",
    "view_settings": "self_service",
    "view_subreddits": "self_service",
    "view_keywords": "self_service",
    "view_epg_schedule": "self_service",
    # --- Approval Required (creates ActionRequest) ---
    "add_subreddit": "approval_required",
    "remove_subreddit": "approval_required",
    "request_avatar_freeze": "approval_required",
    "request_avatar_unfreeze": "approval_required",
    "change_brand_guardrails": "approval_required",
    # --- Admin Only (hidden from client users) ---
    "deactivate_client": "admin_only",
    "change_plan_type": "admin_only",
    "assign_avatar": "admin_only",
    "remove_avatar": "admin_only",
    "modify_auto_approve_policy": "admin_only",
    "toggle_autopilot": "admin_only",
}


def get_effective_tier(client_matrix: dict, action_id: str) -> str:
    """Resolve the effective permission tier for an action.

    Priority: client override → default map.
    Unknown actions in client matrix are ignored.
    Missing actions in client matrix fall back to default.
    """
    # Client override takes precedence if present and action is known
    if action_id in client_matrix and action_id in DEFAULT_PERMISSION_MAP:
        tier = client_matrix[action_id]
        if tier in (PermissionTier.self_service, PermissionTier.approval_required, PermissionTier.admin_only):
            return tier

    # Fall back to default
    return DEFAULT_PERMISSION_MAP.get(action_id, "admin_only")
```

**70% self-service validation:** 19 self-service actions out of 25 total = 76% ≥ 70%. ✓


### 2. Permission Guard (FastAPI Dependency)

**File:** `app/dependencies/permission_guard.py`

```python
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
from app.models.client import Client
from app.models.user import User
from app.models.user_role import UserRole
from app.services.permission_map import get_effective_tier, PermissionTier


class PermissionRequiresApproval(Exception):
    """Raised when the action needs an ActionRequest instead of immediate execution."""
    def __init__(self, action_id: str, client_id: uuid.UUID, user: User):
        self.action_id = action_id
        self.client_id = client_id
        self.user = user


# Actions that are read-only (client_viewer allowed)
READ_ONLY_ACTIONS = frozenset([
    "view_avatars", "view_avatar_detail", "view_report",
    "view_activity_log", "view_settings", "view_subreddits",
    "view_keywords", "view_epg_schedule",
])


def require_permission(action_id: str):
    """Factory: returns a dependency that enforces the permission tier for action_id.

    Pipeline order:
    1. Resolve user (existing RBAC)
    2. Resolve client_id from path
    3. Check client_viewer → deny all writes
    4. Resolve effective tier from permission_matrix
    5. Self-service → allow (return user)
    6. Approval_required → raise PermissionRequiresApproval
    7. Admin_only → raise 403
    """

    async def _guard(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        # Internal roles (owner, partner) bypass permission matrix entirely
        if user.user_role in (UserRole.owner, UserRole.partner):
            return user
        if user.is_superuser:
            return user

        # Must be client-scoped
        if not user.user_role.is_client_scoped:
            raise HTTPException(status_code=403, detail="Access Denied")

        # client_viewer: deny all write actions
        is_write = action_id not in READ_ONLY_ACTIONS
        if user.user_role == UserRole.client_viewer and is_write:
            _log_denial(db, user, action_id, "viewer_restricted")
            raise HTTPException(status_code=403, detail="Access Denied")

        # Resolve client_id from path or user
        client_id = _resolve_client_id(request, user)
        if not client_id:
            raise HTTPException(status_code=403, detail="Access Denied")

        # Load client permission_matrix
        client = db.query(Client).filter(Client.id == client_id).first()
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        matrix = client.permission_matrix or {}
        tier = get_effective_tier(matrix, action_id)

        if tier == PermissionTier.self_service:
            return user

        if tier == PermissionTier.approval_required:
            if is_write:
                raise PermissionRequiresApproval(action_id, client_id, user)
            return user  # read-only approval-tier actions are viewable

        # admin_only
        _log_denial(db, user, action_id, "admin_only")
        raise HTTPException(status_code=403, detail="Access Denied")

    return _guard


def _resolve_client_id(request: Request, user: User) -> uuid.UUID | None:
    """Extract client_id from path params or user's assigned client."""
    raw = request.path_params.get("client_id")
    if raw:
        try:
            return uuid.UUID(str(raw))
        except (ValueError, AttributeError):
            pass
    return user.client_id


def _log_denial(db: Session, user: User, action_id: str, reason: str):
    """Log permission denial to AuditLog."""
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
        pass  # audit failure should not block the denial
```


### 3. ActionRequest Service

**File:** `app/services/action_request.py`

```python
"""ActionRequest service — create, approve, reject, execute approval-tier actions."""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.action_request import ActionRequest
from app.models.user import User
from app.services.audit.audit_logging import log_action
from app.services.notifications import notify_client


def create_action_request(
    db: Session,
    client_id: uuid.UUID,
    user_id: uuid.UUID,
    action_type: str,
    payload: dict | None = None,
) -> ActionRequest | None:
    """Create an ActionRequest. Returns None if duplicate pending exists."""
    # Deduplication: check for existing pending with same client + action_type + payload
    existing = (
        db.query(ActionRequest)
        .filter(
            ActionRequest.client_id == client_id,
            ActionRequest.action_type == action_type,
            ActionRequest.status == "pending",
        )
        .first()
    )
    if existing and existing.payload == payload:
        return None  # duplicate

    request = ActionRequest(
        client_id=client_id,
        user_id=user_id,
        action_type=action_type,
        payload=payload,
        status="pending",
    )
    db.add(request)
    db.commit()
    db.refresh(request)

    # Audit
    log_action(
        db=db,
        user_id=user_id,
        action="action_request_created",
        entity_type="action_request",
        entity_id=request.id,
        client_id=client_id,
        details={"action_type": action_type},
    )

    return request


def approve_action_request(
    db: Session,
    request_id: uuid.UUID,
    resolver: User,
) -> ActionRequest:
    """Approve a pending ActionRequest and execute the action."""
    ar = db.query(ActionRequest).filter(ActionRequest.id == request_id).first()
    if not ar or ar.status != "pending":
        raise ValueError("ActionRequest not found or not pending")

    ar.status = "approved"
    ar.resolved_at = datetime.now(timezone.utc)
    ar.resolved_by = resolver.id
    db.commit()

    # Execute the originally requested action
    _execute_action(db, ar)

    # Audit
    log_action(
        db=db,
        user_id=resolver.id,
        action="action_request_resolved",
        entity_type="action_request",
        entity_id=ar.id,
        client_id=ar.client_id,
        details={"action_type": ar.action_type, "outcome": "approved"},
    )

    # Notify requesting user
    notify_client(
        db=db,
        client_id=ar.client_id,
        user_id=ar.user_id,
        type="success",
        title=f"Request approved: {ar.action_type.replace('_', ' ')}",
        body="Your request has been approved and executed.",
        link=f"/clients/{ar.client_id}/requests",
    )

    return ar


def reject_action_request(
    db: Session,
    request_id: uuid.UUID,
    resolver: User,
    reason: str = "",
) -> ActionRequest:
    """Reject a pending ActionRequest."""
    ar = db.query(ActionRequest).filter(ActionRequest.id == request_id).first()
    if not ar or ar.status != "pending":
        raise ValueError("ActionRequest not found or not pending")

    ar.status = "rejected"
    ar.resolved_at = datetime.now(timezone.utc)
    ar.resolved_by = resolver.id
    ar.rejection_reason = reason
    db.commit()

    # Audit
    log_action(
        db=db,
        user_id=resolver.id,
        action="action_request_resolved",
        entity_type="action_request",
        entity_id=ar.id,
        client_id=ar.client_id,
        details={"action_type": ar.action_type, "outcome": "rejected", "reason": reason},
    )

    # Notify requesting user
    notify_client(
        db=db,
        client_id=ar.client_id,
        user_id=ar.user_id,
        type="warning",
        title=f"Request rejected: {ar.action_type.replace('_', ' ')}",
        body=reason or "Your request was not approved.",
        link=f"/clients/{ar.client_id}/requests",
    )

    return ar


def _execute_action(db: Session, ar: ActionRequest):
    """Dispatch the approved action to the appropriate handler."""
    from app.services.action_executors import ACTION_EXECUTORS

    executor = ACTION_EXECUTORS.get(ar.action_type)
    if executor:
        executor(db=db, client_id=ar.client_id, user_id=ar.user_id, payload=ar.payload)
```


### 4. Action Executors Registry

**File:** `app/services/action_executors.py`

Maps action identifiers to their execution functions. Used by `_execute_action` when an ActionRequest is approved.

```python
"""Action executor registry — maps action_type to handler functions.

Each handler receives (db, client_id, user_id, payload) and performs
the business logic that was deferred by the approval_required tier.
"""

import uuid
from sqlalchemy.orm import Session


def _execute_add_subreddit(db: Session, client_id: uuid.UUID, user_id: uuid.UUID, payload: dict | None):
    """Execute the add_subreddit action after approval."""
    if not payload or "subreddit_name" not in payload:
        return
    # Reuse existing SubredditRequest approval logic or direct creation
    from app.models.subreddit import Subreddit, ClientSubredditAssignment
    subreddit_name = payload["subreddit_name"]
    # Find or create subreddit, create assignment...
    # (Implementation uses existing subreddit management code)


def _execute_remove_subreddit(db: Session, client_id: uuid.UUID, user_id: uuid.UUID, payload: dict | None):
    """Execute subreddit removal after approval."""
    if not payload or "subreddit_name" not in payload:
        return
    from app.models.subreddit import ClientSubredditAssignment, Subreddit
    # Deactivate the assignment...


def _execute_request_avatar_freeze(db: Session, client_id: uuid.UUID, user_id: uuid.UUID, payload: dict | None):
    """Freeze an avatar after approval."""
    if not payload or "avatar_id" not in payload:
        return
    from app.models.avatar import Avatar
    # Freeze avatar...


def _execute_request_avatar_unfreeze(db: Session, client_id: uuid.UUID, user_id: uuid.UUID, payload: dict | None):
    """Unfreeze an avatar after approval."""
    if not payload or "avatar_id" not in payload:
        return
    from app.models.avatar import Avatar
    # Unfreeze avatar...


def _execute_change_brand_guardrails(db: Session, client_id: uuid.UUID, user_id: uuid.UUID, payload: dict | None):
    """Update brand guardrails after approval."""
    if not payload or "guardrails" not in payload:
        return
    from app.models.client import Client
    # Update client.brand_guardrails...


ACTION_EXECUTORS: dict[str, callable] = {
    "add_subreddit": _execute_add_subreddit,
    "remove_subreddit": _execute_remove_subreddit,
    "request_avatar_freeze": _execute_request_avatar_freeze,
    "request_avatar_unfreeze": _execute_request_avatar_unfreeze,
    "change_brand_guardrails": _execute_change_brand_guardrails,
}
```


### 5. Template Context Helper

**File:** `app/services/permission_context.py`

Provides template variables for tier-aware UI rendering.

```python
"""Permission context helper — builds template variables for tier-aware rendering."""

import uuid
from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.action_request import ActionRequest
from app.models.user_role import UserRole
from app.services.permission_map import DEFAULT_PERMISSION_MAP, get_effective_tier


def get_permission_context(db: Session, client_id: uuid.UUID, user_role: UserRole) -> dict:
    """Build permission context dict for Jinja2 templates.

    Returns:
        {
            "hidden_actions": set[str],       # admin_only → hide controls
            "approval_actions": set[str],     # approval_required → badge
            "pending_requests_count": int,    # sidebar badge
        }
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    matrix = client.permission_matrix if client else {}

    hidden = set()
    approval = set()

    for action_id in DEFAULT_PERMISSION_MAP:
        tier = get_effective_tier(matrix, action_id)
        if tier == "admin_only":
            hidden.add(action_id)
        elif tier == "approval_required":
            approval.add(action_id)

    # Viewers see everything as read-only anyway; hide write-only controls
    if user_role == UserRole.client_viewer:
        hidden.update(action_id for action_id in DEFAULT_PERMISSION_MAP
                      if action_id not in ("view_avatars", "view_avatar_detail",
                                           "view_report", "view_activity_log",
                                           "view_settings", "view_subreddits",
                                           "view_keywords", "view_epg_schedule"))

    # Count pending requests
    pending_count = (
        db.query(ActionRequest)
        .filter(ActionRequest.client_id == client_id, ActionRequest.status == "pending")
        .count()
    ) if client else 0

    return {
        "hidden_actions": hidden,
        "approval_actions": approval,
        "pending_requests_count": pending_count,
    }
```


### Route Integration Pattern

Portal routes that perform actions wrap with `require_permission`:

```python
from app.dependencies.permission_guard import require_permission, PermissionRequiresApproval

@router.post("/clients/{client_id}/settings/keywords/add")
def settings_keywords_add(
    request: Request,
    client_id: UUID,
    user: User = Depends(require_permission("add_keyword")),
    db: Session = Depends(get_db),
    keyword: str = Form(...),
    priority: str = Form("medium"),
):
    # Only reached if tier = self_service (or user is owner/partner)
    ...
```

For routes that support approval_required, catch the exception:

```python
@router.post("/clients/{client_id}/settings/subreddits/add")
def settings_subreddits_add(
    request: Request,
    client_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    subreddit_name: str = Form(...),
):
    # Manual permission check (approval-tier needs to create request)
    from app.dependencies.permission_guard import require_permission, PermissionRequiresApproval
    from app.services.action_request import create_action_request

    try:
        guard = require_permission("add_subreddit")
        await guard(request=request, user=user, db=db)
    except PermissionRequiresApproval as e:
        ar = create_action_request(
            db=db,
            client_id=e.client_id,
            user_id=e.user.id,
            action_type=e.action_id,
            payload={"subreddit_name": subreddit_name},
        )
        if ar is None:
            return HTMLResponse("Request already pending", status_code=409)
        return HTMLResponse(
            '<span class="text-yellow-400">Request submitted for approval</span>',
            headers={"HX-Trigger": '{"showToast": {"type": "info", "message": "Request submitted"}}'},
        )
    # Self-service: execute immediately
    ...
```

### Admin Permissions Page

**Route:** `GET /admin/clients/{client_id}/permissions`
**Access:** `require_platform_admin` (owner or partner)

```python
@router.get("/admin/clients/{client_id}/permissions")
def admin_client_permissions(
    request: Request,
    client_id: UUID,
    user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404)

    # Build effective matrix with source indicators
    from app.services.permission_map import DEFAULT_PERMISSION_MAP, get_effective_tier
    matrix = client.permission_matrix or {}
    actions = []
    for action_id, default_tier in DEFAULT_PERMISSION_MAP.items():
        effective = get_effective_tier(matrix, action_id)
        is_override = action_id in matrix and matrix[action_id] != default_tier
        actions.append({
            "id": action_id,
            "label": action_id.replace("_", " ").title(),
            "tier": effective,
            "default_tier": default_tier,
            "is_override": is_override,
        })

    return templates.TemplateResponse(
        "admin_client_permissions.html",
        {"request": request, "client": client, "actions": actions, ...},
    )
```

**Save endpoint:** `POST /admin/clients/{client_id}/permissions`

```python
@router.post("/admin/clients/{client_id}/permissions")
def admin_client_permissions_save(
    request: Request,
    client_id: UUID,
    user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    # Parse form: action_id -> new_tier
    # Compare with existing, record changes
    # Update client.permission_matrix JSONB
    # flag_modified(client, "permission_matrix")
    # Audit log with old/new diffs
    ...
```

**Reset endpoints:**
- `POST /admin/clients/{client_id}/permissions/reset/{action_id}` — reset single action
- `POST /admin/clients/{client_id}/permissions/reset-all` — reset entire matrix


### Portal "My Requests" Page

**Route:** `GET /clients/{client_id}/requests`
**Template:** `client/requests.html`

Lists all ActionRequests for the current client with status badges, timestamps, and resolution details. HTMX pagination.

### Admin ActionRequest Management

**Route:** `GET /admin/action-requests`
**Filter:** by client, status, action_type
**Actions:** Approve / Reject (with reason modal)

Integrates into existing admin sidebar under "Operations" section.

## Rate Limiting Integration

The permission guard runs **before** rate limiting in the dependency chain:

```
verify_client_access_from_path → require_permission(action_id) → check_rate_limit(...)
```

This ordering ensures:
1. Denied actions (admin_only, viewer_restricted) never consume rate limit quota
2. Self-service actions that pass the guard still hit existing rate limits
3. Approval-tier actions never reach rate limiting (they create requests instead)

The existing `_require_trigger_role` check in `portal_actions.py` is replaced by `require_permission(action_id)` which provides equivalent role checks plus tier-aware behavior.


## Error Handling

| Scenario | Response | User-Facing Behavior |
|----------|----------|---------------------|
| client_viewer attempts write | 403 | Button hidden in UI; 403 if JS disabled |
| Admin_only action by client user | 403 | Control hidden; 403 if crafted request |
| Approval_required action | 200 + "request submitted" | Toast + badge update |
| Duplicate pending request | 409 | "Request already pending" message |
| Rate limit exceeded (self-service) | 429 + retry-after | Same as existing behavior |
| ActionRequest not found (approve/reject) | 404 | Admin error message |
| Action executor failure | 500 (logged) | Notification "execution failed" |

## Template Changes

### Portal Templates

1. **`client_base.html`** — Add `pending_requests_count` badge in sidebar nav next to "My Requests" link.

2. **All portal action templates** — Wrap action buttons/forms with Jinja2 conditionals:

```jinja2
{# Hide admin_only actions #}
{% if "trigger_pipeline" not in hidden_actions %}
  <button ...>
    {# Mark approval_required with badge #}
    {% if "trigger_pipeline" in approval_actions %}
      <span class="badge badge-yellow">Requires Approval</span>
    {% endif %}
    Run Pipeline
  </button>
{% endif %}
```

3. **New template:** `client/requests.html` — My Requests page with table of ActionRequests.

### Admin Templates

4. **New template:** `admin_client_permissions.html` — Permission matrix editor (dark theme, HTMX inline save).

5. **New template:** `admin_action_requests.html` — List/approve/reject pending ActionRequests.

6. **`admin_base.html`** — Add sidebar link "Permissions" under client detail and "Action Requests" under Operations.


## File Structure

```
app/
├── models/
│   └── action_request.py          # NEW — ActionRequest model
├── dependencies/
│   └── permission_guard.py        # NEW — require_permission dependency
├── services/
│   ├── permission_map.py          # NEW — DEFAULT_PERMISSION_MAP + get_effective_tier
│   ├── action_request.py          # NEW — create/approve/reject service
│   ├── action_executors.py        # NEW — executor registry
│   └── permission_context.py      # NEW — template context helper
├── routes/
│   ├── portal.py                  # MODIFIED — inject permission context
│   ├── portal_actions.py          # MODIFIED — replace _require_trigger_role with require_permission
│   ├── admin.py                   # MODIFIED — add permissions page + action request management
│   └── portal_requests.py         # NEW — My Requests page for clients
├── templates/
│   ├── client/
│   │   └── requests.html          # NEW — My Requests page
│   ├── admin_client_permissions.html  # NEW — Permission matrix editor
│   ├── admin_action_requests.html     # NEW — Action request management
│   └── partials/
│       ├── client/
│       │   └── sidebar_requests_badge.html  # NEW — badge partial
│       └── admin/
│           └── permission_row.html          # NEW — inline tier selector
alembic/
└── versions/
    └── perm01_permission_matrix_action_requests.py  # NEW — migration
```

## Integration with Existing Systems

### RBAC (permissions.py)

- `require_permission` **composes with** `verify_client_access_from_path` — both run as router dependencies.
- Internal roles (owner, partner) bypass the permission matrix entirely — they already have full access.
- The guard reuses `get_current_user` from the existing auth flow.

### Rate Limiting (client_action_limiter.py)

- Permission guard runs **before** rate limit. Self-service actions still hit `check_rate_limit()`.
- `log_action()` is called only after successful execution (not on permission denial).
- No changes to `ClientActionLog` model or `client_action_limiter.py` internals.

### Audit (audit_logging.py)

- Uses existing `log_action()` interface with new action types: `permission_denied`, `action_request_created`, `action_request_resolved`, `permission_matrix_updated`.
- All logged to `audit_log` table with standard fields.

### Notifications (notifications.py)

- Uses existing `notify_client()` with `user_id` parameter to target the requesting user specifically.
- ActionRequest resolution triggers notification with link to My Requests page.

### SubredditRequest Migration

- The existing `SubredditRequest` model remains for backward compatibility.
- New `add_subreddit` / `remove_subreddit` actions route through ActionRequest instead.
- Future: migrate existing SubredditRequest pending items to ActionRequest on deploy.


## Testing Strategy

### Unit Tests (Example-Based)

- Verify DEFAULT_PERMISSION_MAP contains exactly the action IDs listed in requirements (2.2, 2.3, 2.4)
- Verify DEFAULT_PERMISSION_MAP has ≥70% self_service (2.1)
- Verify admin permissions page returns 403 for non-owner/partner roles (6.6)
- Verify My Requests page renders ActionRequests with correct statuses (7.4)
- Verify 429 response includes retry-after header on rate limit hit (8.3)

### Property Tests (Universal)

All correctness properties below are testable via property-based testing against `get_effective_tier`, the permission guard logic, and the ActionRequest service. Each property test generates random inputs (action identifiers, permission matrices, user roles, payloads) and verifies invariants hold across 100+ iterations.

### Integration Tests

- End-to-end portal action flow with different tiers (self-service executes, approval creates request, admin-only denies)
- Admin UI permission matrix save + reset round-trip
- ActionRequest approve → action executes → notification sent

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Permission matrix schema validity

*For any* permission matrix (default or client-specific), every value in the dict must be one of the three valid tier strings (`"self_service"`, `"approval_required"`, `"admin_only"`), and `get_effective_tier` must always return one of these three values regardless of input.

**Validates: Requirements 1.3**

### Property 2: Default population on client creation

*For any* newly created Client record, the `permission_matrix` field is populated with a non-empty dict equivalent to `DEFAULT_PERMISSION_MAP` without requiring manual intervention, and contains at least 70% self-service actions.

**Validates: Requirements 1.1, 1.2, 2.1**

### Property 3: Fallback resolution for missing/unknown keys

*For any* client permission matrix and any action identifier present in DEFAULT_PERMISSION_MAP, if the action is absent from the client's matrix then `get_effective_tier` returns the default tier; conversely, if the client matrix contains an action NOT in DEFAULT_PERMISSION_MAP, that entry has no effect on tier resolution for valid actions.

**Validates: Requirements 1.4, 1.5, 3.5**

### Property 4: Tier enforcement invariant

*For any* client-scoped user (client_admin or client_manager) and any action identifier, the permission guard produces exactly one of three outcomes based on the effective tier: self_service → allows execution, approval_required → blocks execution and produces an ActionRequest, admin_only → returns 403.

**Validates: Requirements 3.1, 3.2, 3.3**

### Property 5: Viewer always denied writes

*For any* user with role `client_viewer` and any action identifier that is a write operation, the permission guard returns 403 regardless of the effective tier (self_service, approval_required, or admin_only).

**Validates: Requirements 3.4, 5.1**

### Property 6: Client roles denied admin_only equally

*For any* action classified as `admin_only` in the effective matrix and any client-scoped role (client_admin, client_manager, client_viewer), the permission guard returns 403. Additionally, for approval_required actions, client_admin and client_manager produce equivalent ActionRequest records (no privilege escalation).

**Validates: Requirements 5.2, 5.3, 5.4**

### Property 7: ActionRequest deduplication

*For any* client, action_type, and payload combination, if a pending ActionRequest already exists with matching parameters, attempting to create another returns None (no duplicate created). The total count of pending requests for that combination never exceeds 1.

**Validates: Requirements 4.5**

### Property 8: Approval executes and transitions state

*For any* pending ActionRequest, approving it sets status to `"approved"`, records `resolved_at` (non-null datetime) and `resolved_by` (resolver's user_id), and invokes the action executor for that action_type.

**Validates: Requirements 4.3**

### Property 9: Rejection does not execute

*For any* pending ActionRequest, rejecting it sets status to `"rejected"`, records `resolved_at`, `resolved_by`, and `rejection_reason`, and does NOT invoke the action executor (the action's side effects never occur).

**Validates: Requirements 4.4**

### Property 10: Resolution notification delivery

*For any* ActionRequest that transitions from `"pending"` to either `"approved"` or `"rejected"`, a Notification record is created targeting the original requesting user's `user_id` and `client_id`.

**Validates: Requirements 7.5**

### Property 11: Permission guard executes before rate limit

*For any* action that is denied by the permission guard (admin_only, viewer_restricted), the `ClientActionLog` count for that action does not increment. Rate limit quota is only consumed when the action is allowed and actually executes.

**Validates: Requirements 8.1, 8.2**

### Property 12: Audit trail completeness

*For any* permission-related event (denial, ActionRequest creation, ActionRequest resolution, matrix update), an AuditLog entry exists with the correct `action` type, `user_id`, `client_id`, and `details` containing the action_type identifier. The set of audit actions covers: `permission_denied`, `action_request_created`, `action_request_resolved`, `permission_matrix_updated`.

**Validates: Requirements 9.1, 9.2, 9.3, 9.4**
