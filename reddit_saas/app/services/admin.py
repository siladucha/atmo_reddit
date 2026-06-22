"""Admin service layer — business logic for admin panel operations.

This module is extended incrementally by later tasks with client, keyword,
subreddit, avatar, health, AI cost, and task monitoring functions.
"""

import logging
import re
import uuid

from sqlalchemy import desc, func, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.ai_usage import AIUsageLog
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.subreddit import ClientSubreddit, ClientSubredditAssignment, Subreddit
from app.models.thread import RedditThread
from app.models.user import User
from app.services import audit
from app.services.auth import hash_password


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


def list_users(
    db: Session,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[User], int]:
    """Return a paginated list of users sorted by created_at descending.

    Args:
        db: SQLAlchemy database session.
        page: Page number (1-indexed).
        per_page: Number of users per page.

    Returns:
        A tuple of (users, total_count).
    """
    query = db.query(User)
    total = query.count()

    offset = (page - 1) * per_page
    users = (
        query
        .order_by(desc(User.created_at))
        .offset(offset)
        .limit(per_page)
        .all()
    )

    return users, total


def create_admin_user(
    db: Session,
    email: str,
    password: str,
    full_name: str | None = None,
    is_superuser: bool = False,
    current_user_id: uuid.UUID | None = None,
) -> User:
    """Create a new User record via the admin panel.

    Args:
        db: SQLAlchemy database session.
        email: Email address for the new user.
        password: Plain-text password (will be hashed).
        full_name: Optional display name.
        is_superuser: Whether the new user should be a superuser.
        current_user_id: The admin performing the action (for audit logging).

    Returns:
        The newly created User.

    Raises:
        ValueError: If a user with the given email already exists.
    """
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise ValueError("Email already registered")

    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name,
        is_superuser=is_superuser,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    audit.log_action(
        db=db,
        user_id=current_user_id,
        action="create",
        entity_type="user",
        entity_id=user.id,
        details={"email": email, "is_superuser": is_superuser},
    )

    return user


def toggle_user_active(
    db: Session,
    user_id: uuid.UUID,
    current_user_id: uuid.UUID,
) -> User:
    """Flip the ``is_active`` flag on a user.

    Args:
        db: SQLAlchemy database session.
        user_id: The target user to toggle.
        current_user_id: The admin performing the action.

    Returns:
        The updated User.

    Raises:
        ValueError: If the admin tries to deactivate their own account.
        ValueError: If the target user is not found.
    """
    if user_id == current_user_id:
        raise ValueError("Cannot deactivate your own account")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("User not found")

    user.is_active = not user.is_active
    db.commit()
    db.refresh(user)

    audit.log_action(
        db=db,
        user_id=current_user_id,
        action="toggle_active",
        entity_type="user",
        entity_id=user.id,
        details={"is_active": user.is_active},
    )

    return user


def toggle_user_superuser(
    db: Session,
    user_id: uuid.UUID,
    current_user_id: uuid.UUID,
) -> User:
    """Flip the ``is_superuser`` flag on a user.

    Args:
        db: SQLAlchemy database session.
        user_id: The target user to toggle.
        current_user_id: The admin performing the action.

    Returns:
        The updated User.

    Raises:
        ValueError: If the target user is not found.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("User not found")

    user.is_superuser = not user.is_superuser
    db.commit()
    db.refresh(user)

    audit.log_action(
        db=db,
        user_id=current_user_id,
        action="toggle_superuser",
        entity_type="user",
        entity_id=user.id,
        details={"is_superuser": user.is_superuser},
    )

    return user


def reset_user_password(
    db: Session,
    user_id: uuid.UUID,
    new_password: str,
    current_user_id: uuid.UUID,
) -> User:
    """Reset a user's password (admin action).

    Args:
        db: SQLAlchemy database session.
        user_id: The target user.
        new_password: The new plain-text password (will be hashed).
        current_user_id: The admin performing the action.

    Returns:
        The updated User.

    Raises:
        ValueError: If the user is not found or password is empty.
    """
    if not new_password or not new_password.strip():
        raise ValueError("Password cannot be empty")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("User not found")

    user.hashed_password = hash_password(new_password)
    db.commit()
    db.refresh(user)

    audit.log_action(
        db=db,
        user_id=current_user_id,
        action="reset_password",
        entity_type="user",
        entity_id=user.id,
    )

    return user


def delete_user(
    db: Session,
    user_id: uuid.UUID,
    current_user_id: uuid.UUID,
) -> None:
    """Permanently delete a user from the database.

    Clears all FK dependencies before deletion. Preserves audit trail
    by nullifying user_id references rather than deleting log entries.

    Args:
        db: SQLAlchemy database session.
        user_id: The target user to delete.
        current_user_id: The admin performing the action.

    Raises:
        ValueError: If the user is not found or admin tries to delete themselves.
    """
    if user_id == current_user_id:
        raise ValueError("Cannot delete your own account")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("User not found")

    email = user.email

    # Clear ALL FK dependencies that block deletion
    from app.models.audit import AuditLog
    db.query(AuditLog).filter(AuditLog.user_id == user_id).update(
        {"user_id": None}, synchronize_session=False
    )

    # Nullify geo_prompts.created_by
    try:
        from app.models.geo_prompt import GeoPrompt
        db.query(GeoPrompt).filter(GeoPrompt.created_by == user_id).update(
            {"created_by": None}, synchronize_session=False
        )
    except Exception:
        pass

    # Delete user_client_assignments
    try:
        from app.models.user_client_assignment import UserClientAssignment
        db.query(UserClientAssignment).filter(
            UserClientAssignment.user_id == user_id
        ).delete(synchronize_session=False)
    except Exception:
        pass

    # Nullify discovery_sessions.operator_user_id (preserve sessions)
    try:
        from app.models.discovery_session import DiscoverySession
        db.query(DiscoverySession).filter(
            DiscoverySession.operator_user_id == user_id
        ).update({"operator_user_id": None}, synchronize_session=False)
    except Exception:
        pass

    db.delete(user)
    db.commit()

    audit.log_action(
        db=db,
        user_id=current_user_id,
        action="delete_user",
        entity_type="user",
        entity_id=user_id,
        details={"email": email},
    )


# ---------------------------------------------------------------------------
# Client management
# ---------------------------------------------------------------------------


def list_clients_paginated(
    db: Session,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[dict], int]:
    """Return a paginated list of clients with subreddit and avatar counts.

    Each client dict contains the Client object plus ``subreddit_count`` and
    ``avatar_count`` fields.  Results are sorted by ``created_at`` descending.

    Args:
        db: SQLAlchemy database session.
        page: Page number (1-indexed).
        per_page: Number of clients per page.

    Returns:
        A tuple of (client_dicts, total_count).
    """
    query = db.query(Client)
    total = query.count()

    offset = (page - 1) * per_page
    clients = (
        query
        .order_by(desc(Client.created_at))
        .offset(offset)
        .limit(per_page)
        .all()
    )

    result: list[dict] = []
    for client in clients:
        subreddit_count = (
            db.query(func.count(ClientSubredditAssignment.id))
            .filter(
                ClientSubredditAssignment.client_id == client.id,
                ClientSubredditAssignment.is_active.is_(True),
            )
            .scalar()
        )

        avatar_count = (
            db.query(func.count(Avatar.id))
            .filter(Avatar.client_ids.any(str(client.id)))
            .scalar()
        )

        # AI costs for this client (total + this month)
        ai_cost_total = float(
            db.query(func.coalesce(func.sum(AIUsageLog.cost_usd), 0))
            .filter(AIUsageLog.client_id == client.id)
            .scalar()
        )

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ai_cost_month = float(
            db.query(func.coalesce(func.sum(AIUsageLog.cost_usd), 0))
            .filter(
                AIUsageLog.client_id == client.id,
                AIUsageLog.created_at >= month_start,
            )
            .scalar()
        )

        ai_calls_month = (
            db.query(func.count(AIUsageLog.id))
            .filter(
                AIUsageLog.client_id == client.id,
                AIUsageLog.created_at >= month_start,
            )
            .scalar()
        )

        result.append({
            "client": client,
            "subreddit_count": subreddit_count,
            "avatar_count": avatar_count,
            "ai_cost_total": ai_cost_total,
            "ai_cost_month": ai_cost_month,
            "ai_calls_month": ai_calls_month,
        })

    return result, total


def create_client(
    db: Session,
    current_user_id: uuid.UUID,
    **fields,
) -> Client:
    """Create a new Client record.

    Args:
        db: SQLAlchemy database session.
        current_user_id: The admin performing the action (for audit logging).
        **fields: Client fields — ``client_name``, ``brand_name``,
            ``company_profile``, ``company_worldview``, ``company_problem``,
            ``competitive_landscape``, ``brand_voice``, ``icp_profiles``,
            ``keywords``.

    Returns:
        The newly created Client.
    """
    client = Client(**fields)
    db.add(client)
    db.commit()
    db.refresh(client)

    audit.log_action(
        db=db,
        user_id=current_user_id,
        action="create",
        entity_type="client",
        entity_id=client.id,
        details={"client_name": client.client_name},
    )

    return client


def update_client(
    db: Session,
    client_id: uuid.UUID,
    current_user_id: uuid.UUID,
    **fields,
) -> Client:
    """Partial update of a Client record.

    Only fields that are provided (non-None) are updated; all other fields
    are preserved.

    Args:
        db: SQLAlchemy database session.
        client_id: The ID of the client to update.
        current_user_id: The admin performing the action (for audit logging).
        **fields: Fields to update.  Keys should match Client column names.

    Returns:
        The updated Client.

    Raises:
        ValueError: If the client is not found.
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise ValueError("Client not found")

    updated_fields: list[str] = []
    for key, value in fields.items():
        if value is not None:
            setattr(client, key, value)
            updated_fields.append(key)

    db.commit()
    db.refresh(client)

    audit.log_action(
        db=db,
        user_id=current_user_id,
        action="update",
        entity_type="client",
        entity_id=client.id,
        client_id=client.id,
        details={"updated_fields": updated_fields},
    )

    return client


def deactivate_client(
    db: Session,
    client_id: uuid.UUID,
    current_user_id: uuid.UUID,
) -> Client:
    """Deactivate (pause) a client. All pipeline tasks skip inactive clients.

    Avatars and subreddit assignments are preserved — the client is paused,
    not deleted. When reactivated, everything resumes without manual reassignment.

    Args:
        db: SQLAlchemy database session.
        client_id: The ID of the client to deactivate.
        current_user_id: The admin performing the action (for audit logging).

    Returns:
        The updated Client.

    Raises:
        ValueError: If the client is not found.
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise ValueError("Client not found")

    client.is_active = False

    db.commit()
    db.refresh(client)

    audit.log_action(
        db=db,
        user_id=current_user_id,
        action="deactivate",
        entity_type="client",
        entity_id=client.id,
        client_id=client.id,
        details={"paused": True},
    )

    return client


def activate_client(
    db: Session,
    client_id: uuid.UUID,
    current_user_id: uuid.UUID,
) -> Client:
    """Re-activate a previously paused client. Pipeline resumes automatically.

    Since deactivation only sets is_active=False (no cascade), reactivation
    simply flips the flag back. Avatars and subreddit assignments are intact.

    Args:
        db: SQLAlchemy database session.
        client_id: The ID of the client to activate.
        current_user_id: The admin performing the action (for audit logging).

    Returns:
        The updated Client.

    Raises:
        ValueError: If the client is not found or already active.
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise ValueError("Client not found")
    if client.is_active:
        raise ValueError("Client is already active")

    client.is_active = True

    db.commit()
    db.refresh(client)

    audit.log_action(
        db=db,
        user_id=current_user_id,
        action="activate",
        entity_type="client",
        entity_id=client.id,
        client_id=client.id,
    )

    return client


# ---------------------------------------------------------------------------
# Keyword management
# ---------------------------------------------------------------------------

_VALID_PRIORITIES = {"HIGH", "MEDIUM", "LOW", "COMPETITOR"}


def get_client_keywords(
    db: Session,
    client_id: uuid.UUID,
) -> list[dict]:
    """Return a flat list of keywords from the client's JSONB field.

    Each item is ``{"name": str, "priority": str}``.  The list order is
    HIGH → MEDIUM → LOW, preserving insertion order within each priority.

    Args:
        db: SQLAlchemy database session.
        client_id: The client whose keywords to retrieve.

    Returns:
        A flat list of keyword dicts, or an empty list if keywords is None.
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client or not client.keywords:
        return []

    result: list[dict] = []
    for priority in ("high", "medium", "low", "competitor"):
        for name in client.keywords.get(priority, []):
            result.append({"name": name, "priority": priority.upper()})
    return result


def validate_keyword(name: str, priority: str) -> tuple[bool, str]:
    """Validate a keyword name and priority.

    Args:
        name: The keyword text.
        priority: The priority level string.

    Returns:
        ``(True, "")`` if valid, ``(False, "error message")`` otherwise.
    """
    if not name or not name.strip():
        return False, "Keyword name cannot be empty"
    if priority.upper() not in _VALID_PRIORITIES:
        return False, f"Priority must be one of: {', '.join(sorted(_VALID_PRIORITIES))}"
    return True, ""


def add_keyword(
    db: Session,
    client_id: uuid.UUID,
    name: str,
    priority: str,
    current_user_id: uuid.UUID,
) -> dict:
    """Append a keyword to the client's JSONB keywords field.

    Args:
        db: SQLAlchemy database session.
        client_id: The client to add the keyword to.
        name: The keyword text.
        priority: Priority level (HIGH, MEDIUM, LOW).
        current_user_id: The admin performing the action.

    Returns:
        The added keyword as ``{"name": str, "priority": str}``.

    Raises:
        ValueError: If the client is not found.
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise ValueError("Client not found")
    if not client.is_active:
        raise ValueError("Cannot add keyword to inactive client")

    priority_key = priority.lower()

    if client.keywords is None:
        client.keywords = {"high": [], "medium": [], "low": []}

    # Ensure the priority key exists
    if priority_key not in client.keywords:
        client.keywords[priority_key] = []

    # Check for duplicate keyword (case-insensitive) across all priorities
    trimmed = name.strip()
    for pkey in ("high", "medium", "low", "competitor"):
        for existing_kw in client.keywords.get(pkey, []):
            if existing_kw.strip().lower() == trimmed.lower():
                raise ValueError(f"Keyword '{trimmed}' already exists (priority: {pkey.upper()})")

    client.keywords[priority_key].append(trimmed)
    flag_modified(client, "keywords")

    db.commit()
    db.refresh(client)

    audit.log_action(
        db=db,
        user_id=current_user_id,
        action="add_keyword",
        entity_type="keyword",
        client_id=client.id,
        details={"name": name.strip(), "priority": priority.upper()},
    )

    return {"name": name.strip(), "priority": priority.upper()}


def remove_keyword(
    db: Session,
    client_id: uuid.UUID,
    index: int,
    current_user_id: uuid.UUID,
) -> None:
    """Remove a keyword by its flat-list index.

    The index corresponds to the position in the list returned by
    :func:`get_client_keywords`.

    Args:
        db: SQLAlchemy database session.
        client_id: The client to remove the keyword from.
        index: Position in the flat keyword list.
        current_user_id: The admin performing the action.

    Raises:
        ValueError: If the client is not found or the index is out of range.
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise ValueError("Client not found")

    keywords = get_client_keywords(db, client_id)
    if index < 0 or index >= len(keywords):
        raise ValueError("Keyword index out of range")

    target = keywords[index]
    priority_key = target["priority"].lower()

    # Remove the keyword from the appropriate priority list
    plist = client.keywords.get(priority_key, [])
    # Find the keyword in the priority list by counting occurrences before this index
    # within the same priority group
    count_before = sum(
        1 for kw in keywords[:index] if kw["priority"] == target["priority"]
    )
    if count_before < len(plist):
        plist.pop(count_before)

    client.keywords[priority_key] = plist
    flag_modified(client, "keywords")

    db.commit()
    db.refresh(client)

    audit.log_action(
        db=db,
        user_id=current_user_id,
        action="remove_keyword",
        entity_type="keyword",
        client_id=client.id,
        details={"name": target["name"], "priority": target["priority"]},
    )


def update_keyword_priority(
    db: Session,
    client_id: uuid.UUID,
    index: int,
    new_priority: str,
    current_user_id: uuid.UUID,
) -> dict:
    """Move a keyword from its current priority list to a new one.

    Args:
        db: SQLAlchemy database session.
        client_id: The client whose keyword to update.
        index: Position in the flat keyword list.
        new_priority: The new priority level (HIGH, MEDIUM, LOW).
        current_user_id: The admin performing the action.

    Returns:
        The updated keyword as ``{"name": str, "priority": str}``.

    Raises:
        ValueError: If the client is not found or the index is out of range.
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise ValueError("Client not found")

    keywords = get_client_keywords(db, client_id)
    if index < 0 or index >= len(keywords):
        raise ValueError("Keyword index out of range")

    target = keywords[index]
    old_priority_key = target["priority"].lower()
    new_priority_key = new_priority.lower()

    # Remove from old priority list
    old_list = client.keywords.get(old_priority_key, [])
    count_before = sum(
        1 for kw in keywords[:index] if kw["priority"] == target["priority"]
    )
    if count_before < len(old_list):
        old_list.pop(count_before)
    client.keywords[old_priority_key] = old_list

    # Add to new priority list
    if new_priority_key not in client.keywords:
        client.keywords[new_priority_key] = []
    client.keywords[new_priority_key].append(target["name"])

    flag_modified(client, "keywords")

    db.commit()
    db.refresh(client)

    audit.log_action(
        db=db,
        user_id=current_user_id,
        action="update_keyword_priority",
        entity_type="keyword",
        client_id=client.id,
        details={
            "name": target["name"],
            "old_priority": target["priority"],
            "new_priority": new_priority.upper(),
        },
    )

    return {"name": target["name"], "priority": new_priority.upper()}


# ---------------------------------------------------------------------------
# Subreddit management
# ---------------------------------------------------------------------------

_SUBREDDIT_RE = re.compile(r"^[a-zA-Z0-9_]{3,21}$")


def validate_subreddit_name(name: str) -> tuple[bool, str]:
    """Validate a subreddit name against Reddit's naming rules.

    Args:
        name: The subreddit name to validate.

    Returns:
        ``(True, "")`` if valid, ``(False, "error message")`` otherwise.
    """
    if not _SUBREDDIT_RE.match(name):
        return False, (
            "Subreddit name must be 3-21 characters long and contain "
            "only letters, numbers, and underscores"
        )
    return True, ""


def add_subreddit(
    db: Session,
    client_id: uuid.UUID,
    name: str,
    type: str,
    current_user_id: uuid.UUID | None,
) -> ClientSubredditAssignment:
    """Add a subreddit to a client. Creates Subreddit record if needed.

    No longer enforces global uniqueness — multiple clients can share the
    same subreddit.

    Args:
        db: SQLAlchemy database session.
        client_id: The client to add the subreddit to.
        name: The subreddit name (without ``r/`` prefix).
        type: Subreddit type — ``"professional"`` or ``"hobby"``.
        current_user_id: The admin performing the action.

    Returns:
        The created or reactivated ClientSubredditAssignment.

    Raises:
        ValueError: If the client is not found, is inactive, or the
            subreddit is already actively assigned to this client.
    """
    from app.services.sanitize import clean_subreddit

    # Sanitize subreddit name — strip r/ prefix, validate
    name = clean_subreddit(name) or ""
    if not name:
        raise ValueError("Invalid subreddit name")

    # 1. Verify client exists and is active
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise ValueError("Client not found")
    if not client.is_active:
        raise ValueError("Cannot add subreddit to inactive client")

    # 2. Get-or-create Subreddit record (case-insensitive lookup)
    subreddit = (
        db.query(Subreddit)
        .filter(func.lower(Subreddit.subreddit_name) == name.lower())
        .first()
    )
    if not subreddit:
        subreddit = Subreddit(subreddit_name=name)
        db.add(subreddit)
        db.flush()

    # 3. Check for existing assignment (active or inactive)
    existing_assignment = (
        db.query(ClientSubredditAssignment)
        .filter(
            ClientSubredditAssignment.client_id == client_id,
            ClientSubredditAssignment.subreddit_id == subreddit.id,
        )
        .first()
    )

    if existing_assignment:
        if existing_assignment.is_active:
            raise ValueError("Subreddit already added for this client")
        # Reactivate inactive assignment
        existing_assignment.is_active = True
        existing_assignment.type = type
        db.commit()
        db.refresh(existing_assignment)

        audit.log_action(
            db=db,
            user_id=current_user_id,
            action="reactivate_subreddit",
            entity_type="subreddit_assignment",
            entity_id=existing_assignment.id,
            client_id=client_id,
            details={"subreddit_name": name, "type": type},
        )
        db.refresh(existing_assignment)
        return existing_assignment

    # 4. Create new ClientSubredditAssignment
    assignment = ClientSubredditAssignment(
        client_id=client_id,
        subreddit_id=subreddit.id,
        type=type,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    # 5. Audit log
    audit.log_action(
        db=db,
        user_id=current_user_id,
        action="add_subreddit",
        entity_type="subreddit_assignment",
        entity_id=assignment.id,
        client_id=client_id,
        details={"subreddit_name": name, "type": type},
    )
    db.refresh(assignment)
    return assignment


def remove_subreddit(
    db: Session,
    assignment_id: uuid.UUID,
    current_user_id: uuid.UUID,
) -> None:
    """Soft-delete by setting ``is_active=False`` on the assignment only.

    Does not modify the Subreddit record or other clients' assignments.

    Args:
        db: SQLAlchemy database session.
        assignment_id: The ClientSubredditAssignment to deactivate.
        current_user_id: The admin performing the action.

    Raises:
        ValueError: If the assignment is not found.
    """
    assignment = (
        db.query(ClientSubredditAssignment)
        .filter(ClientSubredditAssignment.id == assignment_id)
        .first()
    )
    if not assignment:
        raise ValueError("Subreddit assignment not found")

    assignment.is_active = False
    db.commit()
    db.refresh(assignment)

    audit.log_action(
        db=db,
        user_id=current_user_id,
        action="remove_subreddit",
        entity_type="subreddit_assignment",
        entity_id=assignment.id,
        client_id=assignment.client_id,
        details={"subreddit_name": assignment.subreddit.subreddit_name},
    )


def list_client_subreddits(
    db: Session,
    client_id: uuid.UUID,
) -> list[dict]:
    """Return subreddits assigned to a client with assignment metadata.

    Queries ClientSubredditAssignment joined to Subreddit for the given
    client_id. Includes a ``shared`` flag indicating if the subreddit has
    multiple active assignments (i.e., is shared with other clients).

    Args:
        db: SQLAlchemy database session.
        client_id: The client whose subreddits to list.

    Returns:
        A list of dicts with: id (assignment id), subreddit_name, type,
        is_active, last_scraped_at, created_at, subreddit_id, shared.
    """
    assignments = (
        db.query(ClientSubredditAssignment)
        .join(Subreddit, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .filter(ClientSubredditAssignment.client_id == client_id)
        .all()
    )

    # Determine which subreddits are shared (have >1 active assignment)
    subreddit_ids = [a.subreddit_id for a in assignments]
    shared_subreddit_ids: set = set()
    if subreddit_ids:
        from sqlalchemy import and_
        shared_counts = (
            db.query(
                ClientSubredditAssignment.subreddit_id,
                func.count(ClientSubredditAssignment.id),
            )
            .filter(
                ClientSubredditAssignment.subreddit_id.in_(subreddit_ids),
                ClientSubredditAssignment.is_active.is_(True),
            )
            .group_by(ClientSubredditAssignment.subreddit_id)
            .all()
        )
        shared_subreddit_ids = {
            sid for sid, count in shared_counts if count > 1
        }

    result: list[dict] = []
    for assignment in assignments:
        result.append({
            "id": assignment.id,
            "subreddit_id": assignment.subreddit_id,
            "subreddit_name": assignment.subreddit.subreddit_name,
            "type": assignment.type,
            "is_active": assignment.is_active,
            "last_scraped_at": assignment.subreddit.last_scraped_at,
            "created_at": assignment.created_at,
            "shared": assignment.subreddit_id in shared_subreddit_ids,
        })

    return result


# ---------------------------------------------------------------------------
# Avatar assignment
# ---------------------------------------------------------------------------


def assign_avatars_to_client(
    db: Session,
    client_id: uuid.UUID,
    avatar_ids: list[uuid.UUID],
    current_user_id: uuid.UUID,
) -> None:
    """Assign one or more avatars to a client (idempotent).

    For each avatar, adds ``str(client_id)`` to the avatar's ``client_ids``
    array if not already present.

    Args:
        db: SQLAlchemy database session.
        client_id: The client to assign avatars to.
        avatar_ids: List of avatar IDs to assign.
        current_user_id: The admin performing the action.
    """
    client_id_str = str(client_id)

    # Verify client exists
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise ValueError("Client not found")

    for avatar_id in avatar_ids:
        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if not avatar:
            continue

        if avatar.client_ids is None:
            avatar.client_ids = []

        if client_id_str not in avatar.client_ids:
            avatar.client_ids = avatar.client_ids + [client_id_str]
            flag_modified(avatar, "client_ids")

    db.commit()

    audit.log_action(
        db=db,
        user_id=current_user_id,
        action="assign_avatars",
        entity_type="avatar",
        client_id=client_id,
        details={"avatar_ids": [str(aid) for aid in avatar_ids]},
    )

    # Auto-trigger avatar onboarding if client has completed onboarding
    if client.onboarding_completed_at:
        try:
            from app.tasks.onboarding import run_avatar_onboarding
            for avatar_id in avatar_ids:
                run_avatar_onboarding.delay(str(avatar_id), str(client_id))
            logger.info(
                "Avatar onboarding auto-triggered for %d avatars (client=%s)",
                len(avatar_ids), client.client_name,
            )
        except Exception as e:
            logger.warning("Failed to auto-trigger avatar onboarding: %s", e)


def unassign_avatar_from_client(
    db: Session,
    client_id: uuid.UUID,
    avatar_id: uuid.UUID,
    current_user_id: uuid.UUID,
) -> None:
    """Remove a client from an avatar's ``client_ids`` array.

    Args:
        db: SQLAlchemy database session.
        client_id: The client to unassign.
        avatar_id: The avatar to update.
        current_user_id: The admin performing the action.

    Raises:
        ValueError: If the avatar is not found.
    """
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise ValueError("Avatar not found")

    client_id_str = str(client_id)

    if avatar.client_ids and client_id_str in avatar.client_ids:
        avatar.client_ids = [cid for cid in avatar.client_ids if cid != client_id_str]
        flag_modified(avatar, "client_ids")
        db.commit()

    audit.log_action(
        db=db,
        user_id=current_user_id,
        action="unassign_avatar",
        entity_type="avatar",
        entity_id=avatar_id,
        client_id=client_id,
    )


# ---------------------------------------------------------------------------
# System health
# ---------------------------------------------------------------------------


def check_system_health(db: Session) -> dict[str, dict]:
    """Check the operational status of all system services.

    Returns a dict keyed by service name.  Each value is a dict with:
        - ``status``: ``"ok"`` | ``"warning"`` | ``"critical"``
        - ``message``: human-readable description
        - ``detail``: optional extra info (version, latency, error text)
        - ``action``: optional hint — e.g. ``"settings"`` to link to settings page

    This function never raises — all checks are wrapped in try/except.
    """
    import time
    from app.config import get_config, get_settings

    bootstrap = get_settings()
    health: dict[str, dict] = {}

    # ── PostgreSQL ──────────────────────────────────────────────
    try:
        t0 = time.monotonic()
        version = db.execute(text("SELECT version()")).scalar()
        latency = round((time.monotonic() - t0) * 1000)
        short_ver = version.split(",")[0] if version else "unknown"
        health["postgresql"] = {
            "status": "ok",
            "message": f"Connected — {short_ver}",
            "detail": f"Latency: {latency}ms",
        }
    except Exception as e:
        health["postgresql"] = {
            "status": "critical",
            "message": "Cannot connect",
            "detail": str(e)[:200],
        }

    # ── Redis ───────────────────────────────────────────────────
    try:
        import redis as redis_lib

        t0 = time.monotonic()
        r = redis_lib.from_url(bootstrap.redis_url, socket_timeout=3)
        r.ping()
        latency = round((time.monotonic() - t0) * 1000)
        info = r.info(section="memory")
        used_mem = info.get("used_memory_human", "?")
        health["redis"] = {
            "status": "ok",
            "message": f"Connected — memory {used_mem}",
            "detail": f"Latency: {latency}ms",
        }
    except Exception as e:
        health["redis"] = {
            "status": "critical",
            "message": "Cannot connect",
            "detail": str(e)[:200],
        }

    # ── Celery workers ──────────────────────────────────────────
    try:
        from app.tasks.worker import celery_app

        inspector = celery_app.control.inspect(timeout=2.0)
        active = inspector.active()
        if active:
            worker_names = list(active.keys())
            task_count = sum(len(tasks) for tasks in active.values())
            health["celery"] = {
                "status": "ok",
                "message": f"{len(worker_names)} worker(s) active",
                "detail": f"Running tasks: {task_count}. Workers: {', '.join(worker_names)}",
            }
        else:
            health["celery"] = {
                "status": "critical",
                "message": "No active workers — pipeline cannot run",
                "detail": "Start with: celery -A app.tasks.worker worker --loglevel=info",
            }
    except Exception as e:
        health["celery"] = {
            "status": "critical",
            "message": "Cannot inspect workers",
            "detail": str(e)[:200],
        }

    # ── Reddit API ──────────────────────────────────────────────
    reddit_client_id = get_config("reddit_client_id", db)
    reddit_client_secret = get_config("reddit_client_secret", db)
    if not reddit_client_id or not reddit_client_secret:
        health["reddit"] = {
            "status": "critical",
            "message": "API credentials not configured",
            "detail": "Set reddit_client_id and reddit_client_secret in Admin > System Settings",
            "action": "settings",
        }
    else:
        try:
            import praw

            t0 = time.monotonic()
            reddit = praw.Reddit(
                client_id=reddit_client_id,
                client_secret=reddit_client_secret,
                user_agent=get_config("reddit_user_agent", db),
            )
            # Real API test — fetch a subreddit title
            sub = reddit.subreddit("test")
            _ = sub.display_name
            latency = round((time.monotonic() - t0) * 1000)
            health["reddit"] = {
                "status": "ok",
                "message": "API connected",
                "detail": f"Latency: {latency}ms",
            }
        except Exception as e:
            health["reddit"] = {
                "status": "warning",
                "message": "Credentials set but API test failed",
                "detail": str(e)[:200],
                "action": "settings",
            }

    # ── LLM API ─────────────────────────────────────────────────
    llm_api_key = get_config("llm_api_key", db)
    if not llm_api_key:
        health["llm"] = {
            "status": "critical",
            "message": "API key not configured — scoring and generation disabled",
            "detail": "Set llm_api_key in Admin > System Settings",
            "action": "settings",
        }
    else:
        scoring_model = get_config("llm_scoring_model", db) or "not set"
        generation_model = get_config("llm_generation_model", db) or "not set"
        scoring_short = scoring_model.split("/")[-1] if "/" in scoring_model else scoring_model
        generation_short = generation_model.split("/")[-1] if "/" in generation_model else generation_model
        health["llm"] = {
            "status": "ok",
            "message": "API key configured — models active",
            "detail": f"Scoring: {scoring_short} · Generation: {generation_short}",
        }

    return health


def check_single_service(service_name: str, db: Session) -> dict:
    """Run health check for a single service only (avoids checking all services)."""
    import time
    from app.config import get_config, get_settings

    bootstrap = get_settings()

    if service_name == "postgresql":
        try:
            t0 = time.monotonic()
            version = db.execute(text("SELECT version()")).scalar()
            latency = round((time.monotonic() - t0) * 1000)
            short_ver = version.split(",")[0] if version else "unknown"
            return {
                "status": "ok",
                "message": f"Connected — {short_ver}",
                "detail": f"Latency: {latency}ms",
            }
        except Exception as e:
            return {"status": "critical", "message": "Cannot connect", "detail": str(e)[:200]}

    elif service_name == "redis":
        try:
            import redis as redis_lib

            t0 = time.monotonic()
            r = redis_lib.from_url(bootstrap.redis_url, socket_timeout=2)
            r.ping()
            latency = round((time.monotonic() - t0) * 1000)
            info = r.info(section="memory")
            used_mem = info.get("used_memory_human", "?")
            return {
                "status": "ok",
                "message": f"Connected — memory {used_mem}",
                "detail": f"Latency: {latency}ms",
            }
        except Exception as e:
            return {"status": "critical", "message": "Cannot connect", "detail": str(e)[:200]}

    elif service_name == "celery":
        try:
            from app.tasks.worker import celery_app

            inspector = celery_app.control.inspect(timeout=1.5)
            active = inspector.active()
            if active:
                worker_names = list(active.keys())
                task_count = sum(len(tasks) for tasks in active.values())
                return {
                    "status": "ok",
                    "message": f"{len(worker_names)} worker(s) active",
                    "detail": f"Running tasks: {task_count}. Workers: {', '.join(worker_names)}",
                }
            else:
                return {
                    "status": "critical",
                    "message": "No active workers — pipeline cannot run",
                    "detail": "Start with: celery -A app.tasks.worker worker --loglevel=info",
                }
        except Exception as e:
            return {"status": "critical", "message": "Cannot inspect workers", "detail": str(e)[:200]}

    elif service_name == "reddit":
        reddit_client_id = get_config("reddit_client_id", db)
        reddit_client_secret = get_config("reddit_client_secret", db)
        if not reddit_client_id or not reddit_client_secret:
            return {
                "status": "critical",
                "message": "API credentials not configured",
                "detail": "Set reddit_client_id and reddit_client_secret in Admin > System Settings",
                "action": "settings",
            }
        try:
            import praw

            t0 = time.monotonic()
            reddit = praw.Reddit(
                client_id=reddit_client_id,
                client_secret=reddit_client_secret,
                user_agent=get_config("reddit_user_agent", db),
            )
            sub = reddit.subreddit("test")
            _ = sub.display_name
            latency = round((time.monotonic() - t0) * 1000)
            return {"status": "ok", "message": "API connected", "detail": f"Latency: {latency}ms"}
        except Exception as e:
            return {
                "status": "warning",
                "message": "Credentials set but API test failed",
                "detail": str(e)[:200],
                "action": "settings",
            }

    elif service_name == "llm":
        llm_api_key = get_config("llm_api_key", db)
        if not llm_api_key:
            return {
                "status": "critical",
                "message": "API key not configured — scoring and generation disabled",
                "detail": "Set llm_api_key in Admin > System Settings",
                "action": "settings",
            }
        scoring_model = get_config("llm_scoring_model", db) or "not set"
        generation_model = get_config("llm_generation_model", db) or "not set"
        # Extract short model names for readability
        scoring_short = scoring_model.split("/")[-1] if "/" in scoring_model else scoring_model
        generation_short = generation_model.split("/")[-1] if "/" in generation_model else generation_model
        return {
            "status": "ok",
            "message": "API key configured — models active",
            "detail": f"Scoring: {scoring_short} · Generation: {generation_short}",
        }

    return {"status": "critical", "message": "Unknown service"}


def get_db_statistics(db: Session) -> dict:
    """Return basic database statistics.

    Args:
        db: SQLAlchemy database session.

    Returns:
        A dict with counts: ``total_clients``, ``total_avatars``,
        ``total_threads``, ``total_comment_drafts``, ``pending_reviews``.
    """
    return {
        "total_clients": db.query(func.count(Client.id)).scalar() or 0,
        "total_avatars": db.query(func.count(Avatar.id)).scalar() or 0,
        "total_threads": db.query(func.count(RedditThread.id)).scalar() or 0,
        "total_comment_drafts": db.query(func.count(CommentDraft.id)).scalar() or 0,
        "pending_reviews": (
            db.query(func.count(CommentDraft.id))
            .filter(CommentDraft.status == "pending")
            .scalar()
            or 0
        ),
    }


# ---------------------------------------------------------------------------
# AI cost tracking
# ---------------------------------------------------------------------------


def _ai_cost_cutoff(days: int | None):
    """Return a datetime cutoff for filtering AI usage logs by period."""
    if not days:
        return None
    from datetime import timedelta, timezone, datetime as dt
    return dt.now(timezone.utc) - timedelta(days=days)


def get_ai_cost_summary(db: Session, days: int | None = None) -> dict:
    """Return aggregate AI usage statistics.

    Args:
        db: SQLAlchemy database session.
        days: Optional period filter (7, 30, 90, or None for all-time).

    Returns:
        A dict with ``total_cost``, ``total_calls``, ``total_input_tokens``,
        ``total_output_tokens``, ``days_with_data``, ``daily_avg``, ``monthly_projection``.
    """
    query = db.query(
        func.coalesce(func.sum(AIUsageLog.cost_usd), 0).label("total_cost"),
        func.count(AIUsageLog.id).label("total_calls"),
        func.coalesce(func.sum(AIUsageLog.input_tokens), 0).label("total_input_tokens"),
        func.coalesce(func.sum(AIUsageLog.output_tokens), 0).label("total_output_tokens"),
    )
    cutoff = _ai_cost_cutoff(days)
    if cutoff:
        query = query.filter(AIUsageLog.created_at >= cutoff)
    row = query.one()

    total_cost = float(row.total_cost)

    # Calculate daily average and monthly projection
    if days:
        daily_avg = total_cost / days if days > 0 else 0
    else:
        # Count distinct days with data
        days_q = db.query(func.count(func.distinct(func.date_trunc("day", AIUsageLog.created_at))))
        days_with_data = days_q.scalar() or 1
        daily_avg = total_cost / days_with_data if days_with_data > 0 else 0

    monthly_projection = daily_avg * 30

    return {
        "total_cost": total_cost,
        "total_calls": row.total_calls,
        "total_input_tokens": row.total_input_tokens,
        "total_output_tokens": row.total_output_tokens,
        "daily_avg": daily_avg,
        "monthly_projection": monthly_projection,
    }


def get_ai_costs_by_client(db: Session, days: int | None = None) -> list[dict]:
    """Return AI costs grouped by client.

    Args:
        db: SQLAlchemy database session.
        days: Optional period filter.

    Returns:
        A list of dicts with ``client_name``, ``calls``, ``cost``,
        ``input_tokens``, ``output_tokens``, ``cost_per_day``.
    """
    query = (
        db.query(
            Client.client_name,
            func.count(AIUsageLog.id).label("calls"),
            func.coalesce(func.sum(AIUsageLog.cost_usd), 0).label("cost"),
            func.coalesce(func.sum(AIUsageLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(AIUsageLog.output_tokens), 0).label("output_tokens"),
        )
        .join(Client, AIUsageLog.client_id == Client.id)
    )
    cutoff = _ai_cost_cutoff(days)
    if cutoff:
        query = query.filter(AIUsageLog.created_at >= cutoff)
    rows = query.group_by(Client.client_name).all()

    period_days = days or 30  # default assumption for cost_per_day
    result = []
    for row in rows:
        cost = float(row.cost)
        result.append({
            "client_name": row.client_name,
            "calls": row.calls,
            "cost": cost,
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "cost_per_day": cost / period_days if period_days > 0 else 0,
        })
    # Sort by cost descending
    result.sort(key=lambda x: x["cost"], reverse=True)

    # Per-client per-operation breakdown
    op_query = (
        db.query(
            Client.client_name,
            AIUsageLog.operation,
            func.coalesce(func.sum(AIUsageLog.cost_usd), 0).label("cost"),
        )
        .join(Client, AIUsageLog.client_id == Client.id)
    )
    if cutoff:
        op_query = op_query.filter(AIUsageLog.created_at >= cutoff)
    op_rows = op_query.group_by(Client.client_name, AIUsageLog.operation).all()

    # Build lookup: client_name -> {operation: cost}
    client_ops: dict = {}
    for r in op_rows:
        if r.client_name not in client_ops:
            client_ops[r.client_name] = {}
        client_ops[r.client_name][r.operation] = float(r.cost)

    # Attach to results
    for item in result:
        ops = client_ops.get(item["client_name"], {})
        item["scoring"] = ops.get("scoring", 0) + ops.get("scoring_batch", 0)
        item["generation"] = ops.get("generation", 0) + ops.get("editing", 0) + ops.get("persona_select", 0)
        item["hobby"] = ops.get("hobby_comment", 0)
        item["strategy"] = ops.get("strategy_generation", 0)

    return result


def get_ai_costs_by_avatar(db: Session, days: int | None = None) -> list[dict]:
    """Return AI costs grouped by avatar with cost/day calculation.

    Shows how much each avatar costs to operate per day.
    """
    from app.models.avatar import Avatar

    query = (
        db.query(
            Avatar.reddit_username,
            Client.client_name,
            AIUsageLog.operation,
            func.count(AIUsageLog.id).label("calls"),
            func.coalesce(func.sum(AIUsageLog.cost_usd), 0).label("cost"),
        )
        .join(Avatar, AIUsageLog.avatar_id == Avatar.id)
        .outerjoin(Client, AIUsageLog.client_id == Client.id)
    )
    cutoff = _ai_cost_cutoff(days)
    if cutoff:
        query = query.filter(AIUsageLog.created_at >= cutoff)
    rows = query.group_by(Avatar.reddit_username, Client.client_name, AIUsageLog.operation).all()

    # Aggregate per avatar
    avatars: dict = {}
    for r in rows:
        name = r.reddit_username or "unknown"
        if name not in avatars:
            avatars[name] = {
                "avatar_name": name,
                "client_name": r.client_name or "—",
                "calls": 0,
                "cost": 0.0,
                "scoring": 0.0,
                "generation": 0.0,
                "hobby": 0.0,
                "strategy": 0.0,
            }
        cost = float(r.cost)
        avatars[name]["calls"] += r.calls
        avatars[name]["cost"] += cost
        if r.operation in ("scoring", "scoring_batch"):
            avatars[name]["scoring"] += cost
        elif r.operation in ("generation", "editing", "persona_select"):
            avatars[name]["generation"] += cost
        elif r.operation == "hobby_comment":
            avatars[name]["hobby"] += cost
        elif r.operation == "strategy_generation":
            avatars[name]["strategy"] += cost

    period_days = days or 30
    result = list(avatars.values())
    for item in result:
        item["cost_per_day"] = item["cost"] / period_days if period_days > 0 else 0
    result.sort(key=lambda x: x["cost"], reverse=True)
    return result


def get_ai_costs_by_operation(db: Session, days: int | None = None) -> list[dict]:
    """Return AI costs grouped by operation type.

    Args:
        db: SQLAlchemy database session.
        days: Optional period filter.

    Returns:
        A list of dicts with ``operation``, ``calls``, ``cost``,
        ``input_tokens``, ``output_tokens``, ``pct``, ``stage``.
    """
    query = (
        db.query(
            AIUsageLog.operation,
            func.count(AIUsageLog.id).label("calls"),
            func.coalesce(func.sum(AIUsageLog.cost_usd), 0).label("cost"),
            func.coalesce(func.sum(AIUsageLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(AIUsageLog.output_tokens), 0).label("output_tokens"),
        )
    )
    cutoff = _ai_cost_cutoff(days)
    if cutoff:
        query = query.filter(AIUsageLog.created_at >= cutoff)
    rows = query.group_by(AIUsageLog.operation).all()

    # Map operations to pipeline stages
    stage_map = {
        "scoring": "Scoring",
        "generation": "Content",
        "persona_select": "Content",
        "editing": "Content",
        "hobby_comment": "Hobby",
        "post_topic": "Posts",
        "post_brief": "Posts",
        "post_generation": "Posts",
        "discovery": "Discovery",
        "geo_query": "GEO/AEO",
    }

    total_cost = sum(float(r.cost) for r in rows) or 1.0
    result = []
    for row in rows:
        cost = float(row.cost)
        result.append({
            "operation": row.operation,
            "calls": row.calls,
            "cost": cost,
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "pct": (cost / total_cost * 100) if total_cost > 0 else 0,
            "stage": stage_map.get(row.operation, "Other"),
        })
    # Sort by cost descending
    result.sort(key=lambda x: x["cost"], reverse=True)
    return result


def get_ai_costs_by_stage(db: Session, days: int | None = None) -> list[dict]:
    """Return AI costs grouped by pipeline stage (higher-level grouping).

    Stages: Discovery (scoring), Content (generation+persona+editing),
    Hobby (hobby_comment), Posts (post_*).
    """
    by_op = get_ai_costs_by_operation(db, days=days)

    stages: dict = {}
    for op in by_op:
        stage = op["stage"]
        if stage not in stages:
            stages[stage] = {"stage": stage, "calls": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0}
        stages[stage]["calls"] += op["calls"]
        stages[stage]["cost"] += op["cost"]
        stages[stage]["input_tokens"] += op["input_tokens"]
        stages[stage]["output_tokens"] += op["output_tokens"]

    total_cost = sum(s["cost"] for s in stages.values()) or 1.0
    result = []
    for s in stages.values():
        s["pct"] = (s["cost"] / total_cost * 100) if total_cost > 0 else 0
        result.append(s)
    result.sort(key=lambda x: x["cost"], reverse=True)
    return result


def get_ai_costs_by_model(db: Session, days: int | None = None) -> list[dict]:
    """Return AI costs grouped by model.

    Args:
        db: SQLAlchemy database session.
        days: Optional period filter.

    Returns:
        A list of dicts with ``model``, ``calls``, ``cost``,
        ``input_tokens``, ``output_tokens``, ``pct``.
    """
    query = (
        db.query(
            AIUsageLog.model,
            func.count(AIUsageLog.id).label("calls"),
            func.coalesce(func.sum(AIUsageLog.cost_usd), 0).label("cost"),
            func.coalesce(func.sum(AIUsageLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(AIUsageLog.output_tokens), 0).label("output_tokens"),
        )
    )
    cutoff = _ai_cost_cutoff(days)
    if cutoff:
        query = query.filter(AIUsageLog.created_at >= cutoff)
    rows = query.group_by(AIUsageLog.model).all()

    total_cost = sum(float(r.cost) for r in rows) or 1.0
    result = []
    for row in rows:
        cost = float(row.cost)
        result.append({
            "model": row.model,
            "calls": row.calls,
            "cost": cost,
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "pct": (cost / total_cost * 100) if total_cost > 0 else 0,
        })
    result.sort(key=lambda x: x["cost"], reverse=True)
    return result


def get_ai_costs_daily_timeline(db: Session, days: int = 14) -> list[dict]:
    """Return daily AI cost breakdown for timeline visualization.

    Returns per-day totals with operation breakdown.
    """
    from datetime import timedelta, timezone, datetime as dt

    cutoff = dt.now(timezone.utc) - timedelta(days=days)

    rows = (
        db.query(
            func.date_trunc("day", AIUsageLog.created_at).label("day"),
            AIUsageLog.operation,
            func.count(AIUsageLog.id).label("calls"),
            func.coalesce(func.sum(AIUsageLog.cost_usd), 0).label("cost"),
        )
        .filter(AIUsageLog.created_at >= cutoff)
        .group_by("day", AIUsageLog.operation)
        .order_by("day")
        .all()
    )

    # Build per-day aggregation
    from collections import defaultdict
    daily: dict = defaultdict(lambda: {"total": 0.0, "calls": 0, "ops": {}})
    for row in rows:
        day_key = row.day.date()
        daily[day_key]["total"] += float(row.cost)
        daily[day_key]["calls"] += row.calls
        daily[day_key]["ops"][row.operation] = {
            "calls": row.calls,
            "cost": float(row.cost),
        }

    # Fill gaps
    result = []
    for i in range(days):
        day = (dt.now(timezone.utc) - timedelta(days=days - 1 - i)).date()
        entry = daily.get(day, {"total": 0.0, "calls": 0, "ops": {}})
        result.append({
            "date": day,
            "total": entry["total"],
            "calls": entry["calls"],
            "scoring": entry["ops"].get("scoring", {}).get("cost", 0),
            "generation": entry["ops"].get("generation", {}).get("cost", 0),
            "persona_select": entry["ops"].get("persona_select", {}).get("cost", 0),
            "editing": entry["ops"].get("editing", {}).get("cost", 0),
            "hobby_comment": entry["ops"].get("hobby_comment", {}).get("cost", 0),
            "discovery": entry["ops"].get("discovery", {}).get("cost", 0),
        })

    return result


def get_ai_costs_recent_calls(db: Session, limit: int = 30, client_id: str | None = None) -> list[dict]:
    """Return recent individual AI calls for drill-down analysis.

    Shows the last N calls with full detail so the operator can see
    exactly what was spent and when.
    """
    query = db.query(AIUsageLog).order_by(AIUsageLog.created_at.desc())

    if client_id:
        import uuid as _uuid
        try:
            cid = _uuid.UUID(client_id)
            query = query.filter(AIUsageLog.client_id == cid)
        except ValueError:
            pass

    rows = query.limit(limit).all()

    # Get client names for display
    client_ids = {r.client_id for r in rows if r.client_id}
    client_names = {}
    if client_ids:
        clients = db.query(Client.id, Client.client_name).filter(Client.id.in_(client_ids)).all()
        client_names = {c.id: c.client_name for c in clients}

    # Get avatar names for display
    avatar_ids = {r.avatar_id for r in rows if r.avatar_id}
    avatar_names = {}
    if avatar_ids:
        from app.models.avatar import Avatar
        avatars = db.query(Avatar.id, Avatar.reddit_username).filter(Avatar.id.in_(avatar_ids)).all()
        avatar_names = {a.id: a.reddit_username for a in avatars}

    # Get thread titles for display
    thread_ids = {r.thread_id for r in rows if r.thread_id}
    thread_titles = {}
    if thread_ids:
        from app.models.thread import RedditThread
        threads = db.query(RedditThread.id, RedditThread.post_title).filter(RedditThread.id.in_(thread_ids)).all()
        thread_titles = {t.id: t.post_title for t in threads}

    return [
        {
            "id": str(row.id)[:8],
            "client_name": client_names.get(row.client_id, "—") if row.client_id else "system",
            "operation": row.operation,
            "model": row.model,
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "cost_usd": float(row.cost_usd),
            "duration_ms": row.duration_ms,
            "created_at": row.created_at,
            "subreddit_name": row.subreddit_name,
            "avatar_name": avatar_names.get(row.avatar_id) if row.avatar_id else None,
            "thread_title": thread_titles.get(row.thread_id) if row.thread_id else None,
            "triggered_by": row.triggered_by,
        }
        for row in rows
    ]


def get_ai_cost_efficiency(db: Session, days: int | None = None) -> dict:
    """Calculate cost efficiency metrics.

    Returns cost-per-comment-posted, cost-per-thread-scored, etc.
    """
    from datetime import timedelta, timezone, datetime as dt
    from app.models.comment_draft import CommentDraft

    cutoff = _ai_cost_cutoff(days)

    # Total costs by operation
    scoring_q = db.query(func.coalesce(func.sum(AIUsageLog.cost_usd), 0)).filter(AIUsageLog.operation == "scoring")
    gen_q = db.query(func.coalesce(func.sum(AIUsageLog.cost_usd), 0)).filter(AIUsageLog.operation.in_(["generation", "persona_select", "editing"]))
    hobby_q = db.query(func.coalesce(func.sum(AIUsageLog.cost_usd), 0)).filter(AIUsageLog.operation == "hobby_comment")

    if cutoff:
        scoring_q = scoring_q.filter(AIUsageLog.created_at >= cutoff)
        gen_q = gen_q.filter(AIUsageLog.created_at >= cutoff)
        hobby_q = hobby_q.filter(AIUsageLog.created_at >= cutoff)

    total_scoring_cost = float(scoring_q.scalar())
    total_generation_cost = float(gen_q.scalar())
    total_hobby_cost = float(hobby_q.scalar())

    # Counts
    scored_q = db.query(func.count(AIUsageLog.id)).filter(AIUsageLog.operation == "scoring")
    generated_q = db.query(func.count(AIUsageLog.id)).filter(AIUsageLog.operation == "generation")
    hobby_gen_q = db.query(func.count(AIUsageLog.id)).filter(AIUsageLog.operation == "hobby_comment")
    posted_q = db.query(func.count(CommentDraft.id)).filter(CommentDraft.status == "posted")

    if cutoff:
        scored_q = scored_q.filter(AIUsageLog.created_at >= cutoff)
        generated_q = generated_q.filter(AIUsageLog.created_at >= cutoff)
        hobby_gen_q = hobby_gen_q.filter(AIUsageLog.created_at >= cutoff)
        posted_q = posted_q.filter(CommentDraft.created_at >= cutoff)

    threads_scored = scored_q.scalar() or 0
    comments_generated = generated_q.scalar() or 0
    comments_posted = posted_q.scalar() or 0
    hobby_generated = hobby_gen_q.scalar() or 0

    # Efficiency ratios
    cost_per_scored = total_scoring_cost / threads_scored if threads_scored > 0 else 0
    cost_per_generated = total_generation_cost / comments_generated if comments_generated > 0 else 0
    cost_per_posted = (total_generation_cost + total_scoring_cost) / comments_posted if comments_posted > 0 else 0
    cost_per_hobby = total_hobby_cost / hobby_generated if hobby_generated > 0 else 0

    return {
        "cost_per_scored_thread": cost_per_scored,
        "cost_per_generated_comment": cost_per_generated,
        "cost_per_posted_comment": cost_per_posted,
        "cost_per_hobby_comment": cost_per_hobby,
        "threads_scored": threads_scored,
        "comments_generated": comments_generated,
        "comments_posted": comments_posted,
        "hobby_generated": hobby_generated,
        "total_scoring_cost": total_scoring_cost,
        "total_generation_cost": total_generation_cost,
        "total_hobby_cost": total_hobby_cost,
    }


# ---------------------------------------------------------------------------
# Task monitoring
# ---------------------------------------------------------------------------


def get_recent_tasks(celery_app=None) -> list[dict]:
    """Return a list of recent Celery tasks.

    Attempts to read task information from Celery/Redis.  Returns an empty
    list if the backend is unavailable or ``celery_app`` is None.

    Uses a short timeout (0.5s) to avoid blocking the HTTP request when
    no workers are running.

    Args:
        celery_app: An optional Celery application instance.

    Returns:
        A list of task dicts with ``id``, ``name``, ``status``, ``worker``,
        and ``started`` fields.
    """
    if celery_app is None:
        return []

    try:
        # First do a quick ping to check if any workers are alive
        inspector = celery_app.control.inspect(timeout=0.5)
        ping_result = inspector.ping()
        if not ping_result:
            # No workers responding — skip expensive inspect calls
            return []

        tasks: list[dict] = []

        # Active tasks
        active = inspector.active() or {}
        for worker_name, worker_tasks in active.items():
            for t in worker_tasks:
                tasks.append({
                    "id": t.get("id", ""),
                    "name": t.get("name", ""),
                    "status": "started",
                    "worker": worker_name,
                    "started": t.get("time_start"),
                })

        # Reserved (queued) tasks
        reserved = inspector.reserved() or {}
        for worker_name, worker_tasks in reserved.items():
            for t in worker_tasks:
                tasks.append({
                    "id": t.get("id", ""),
                    "name": t.get("name", ""),
                    "status": "pending",
                    "worker": worker_name,
                    "started": None,
                })

        return tasks

    except Exception:
        return []


def trigger_pipeline(
    celery_app,
    pipeline_type: str,
    entity_id: str,
) -> str:
    """Dispatch a Celery pipeline task.

    Args:
        celery_app: The Celery application instance.
        pipeline_type: One of ``"full"``, ``"hobby"``, or ``"health"``.
        entity_id: The client or avatar ID to run the pipeline for.

    Returns:
        The dispatched Celery task ID.

    Raises:
        ValueError: If ``celery_app`` is None or ``pipeline_type`` is unknown.
    """
    if celery_app is None:
        raise ValueError("Celery app is not available")

    if pipeline_type == "full":
        # Chain: score → generate comments → generate posts for a specific client.
        # Uses triggered_by="manual" to bypass pipeline_enabled kill switch
        # while preserving all safety checks (rate limits, phase policy, budgets).
        from celery import chain
        result = chain(
            celery_app.signature("score_threads", args=[entity_id], kwargs={"triggered_by": "manual"}, immutable=True),
            celery_app.signature("generate_comments", args=[entity_id], kwargs={"triggered_by": "manual"}, immutable=True),
            celery_app.signature("generate_posts", args=[entity_id], kwargs={"triggered_by": "manual"}, immutable=True),
        ).apply_async()
        return str(result.id)

    task_map = {
        "hobby": "run_hobby_pipeline_all_avatars",
        "health": "check_all_avatars_health",
    }

    task_name = task_map.get(pipeline_type)
    if not task_name:
        raise ValueError(f"Unknown pipeline type: {pipeline_type}")

    result = celery_app.send_task(task_name, args=[entity_id])
    return str(result.id)


# ---------------------------------------------------------------------------
# Client cascade deletion
# ---------------------------------------------------------------------------


def get_client_cascade_preview(
    db: Session,
    client_id: uuid.UUID,
) -> dict:
    """Return counts of all related entities that will be deleted with the client."""
    from app.models.activity_event import ActivityEvent
    from app.models.ai_usage import AIUsageLog
    from app.models.audit import AuditLog
    from app.models.avatar_rental import AvatarRental
    from app.models.comment_draft import CommentDraft
    from app.models.correction_pattern import CorrectionPattern
    from app.models.edit_record import EditRecord
    from app.models.epg_slot import EPGSlot
    from app.models.geo_competitor import GeoCompetitor
    from app.models.geo_prompt import GeoPrompt
    from app.models.notification import Notification
    from app.models.post_draft import PostDraft
    from app.models.scrape_log import ScrapeLog
    from app.models.thread_score import ThreadScore
    from app.models.user_client_assignment import UserClientAssignment

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise ValueError("Client not found")

    users_count = db.query(func.count(User.id)).filter(User.client_id == client_id).scalar() or 0
    assignments_count = db.query(func.count(UserClientAssignment.id)).filter(
        UserClientAssignment.client_id == client_id
    ).scalar() or 0
    csa_count = db.query(func.count(ClientSubredditAssignment.id)).filter(
        ClientSubredditAssignment.client_id == client_id
    ).scalar() or 0
    cs_count = db.query(func.count(ClientSubreddit.id)).filter(
        ClientSubreddit.client_id == client_id
    ).scalar() or 0
    threads_count = db.query(func.count(RedditThread.id)).filter(
        RedditThread.client_id == client_id
    ).scalar() or 0
    scores_count = db.query(func.count(ThreadScore.id)).filter(
        ThreadScore.client_id == client_id
    ).scalar() or 0
    drafts_count = db.query(func.count(CommentDraft.id)).filter(
        CommentDraft.client_id == client_id
    ).scalar() or 0
    post_drafts_count = db.query(func.count(PostDraft.id)).filter(
        PostDraft.client_id == client_id
    ).scalar() or 0
    epg_count = db.query(func.count(EPGSlot.id)).filter(
        EPGSlot.client_id == client_id
    ).scalar() or 0
    edit_records_count = db.query(func.count(EditRecord.id)).filter(
        EditRecord.client_id == client_id
    ).scalar() or 0
    patterns_count = db.query(func.count(CorrectionPattern.id)).filter(
        CorrectionPattern.client_id == client_id
    ).scalar() or 0
    events_count = db.query(func.count(ActivityEvent.id)).filter(
        ActivityEvent.client_id == client_id
    ).scalar() or 0
    scrape_logs_count = db.query(func.count(ScrapeLog.id)).filter(
        ScrapeLog.client_id == client_id
    ).scalar() or 0
    ai_usage_count = db.query(func.count(AIUsageLog.id)).filter(
        AIUsageLog.client_id == client_id
    ).scalar() or 0
    audit_count = db.query(func.count(AuditLog.id)).filter(
        AuditLog.client_id == client_id
    ).scalar() or 0
    geo_prompts_count = db.query(func.count(GeoPrompt.id)).filter(
        GeoPrompt.client_id == client_id
    ).scalar() or 0
    geo_competitors_count = db.query(func.count(GeoCompetitor.id)).filter(
        GeoCompetitor.client_id == client_id
    ).scalar() or 0
    rentals_count = db.query(func.count(AvatarRental.id)).filter(
        AvatarRental.client_id == client_id
    ).scalar() or 0
    notifications_count = db.query(func.count(Notification.id)).filter(
        Notification.client_id == client_id
    ).scalar() or 0
    avatars_count = db.query(func.count(Avatar.id)).filter(
        Avatar.client_ids.any(str(client_id))
    ).scalar() or 0

    vf_count = 0
    try:
        from app.models.voice_feedback import VoiceFeedback
        vf_count = db.query(func.count(VoiceFeedback.id)).filter(
            VoiceFeedback.client_id == client_id
        ).scalar() or 0
    except Exception:
        pass

    sr_count = 0
    try:
        from app.models.subreddit_request import SubredditRequest
        sr_count = db.query(func.count(SubredditRequest.id)).filter(
            SubredditRequest.client_id == client_id
        ).scalar() or 0
    except Exception:
        pass

    cal_count = 0
    try:
        from app.models.client_action_log import ClientActionLog
        cal_count = db.query(func.count(ClientActionLog.id)).filter(
            ClientActionLog.client_id == client_id
        ).scalar() or 0
    except Exception:
        pass

    return {
        "client_name": client.client_name,
        "client_id": str(client_id),
        "counts": {
            "Users (will be deleted)": users_count,
            "User-Client Assignments": assignments_count,
            "Subreddit Assignments": csa_count,
            "Client Subreddits (legacy)": cs_count,
            "Reddit Threads": threads_count,
            "Thread Scores": scores_count,
            "Comment Drafts": drafts_count,
            "Post Drafts": post_drafts_count,
            "EPG Slots": epg_count,
            "Edit Records": edit_records_count,
            "Correction Patterns": patterns_count,
            "Activity Events": events_count,
            "Scrape Logs": scrape_logs_count,
            "AI Usage Logs (will be nullified)": ai_usage_count,
            "Audit Logs (will be nullified)": audit_count,
            "GEO Prompts": geo_prompts_count,
            "GEO Competitors": geo_competitors_count,
            "Avatar Rentals": rentals_count,
            "Notifications": notifications_count,
            "Avatars (will be unlinked)": avatars_count,
            "Voice Feedback": vf_count,
            "Subreddit Requests": sr_count,
            "Client Action Logs": cal_count,
        },
    }


def delete_client_cascade(
    db: Session,
    client_id: uuid.UUID,
    current_user_id: uuid.UUID,
) -> dict:
    """Permanently delete a client and all associated data.

    Avatars NOT deleted — only unlinked. Users NOT deleted — only unlinked.
    Audit/AI logs preserved with client_id=NULL.
    """
    from app.models.activity_event import ActivityEvent
    from app.models.ai_usage import AIUsageLog
    from app.models.audit import AuditLog
    from app.models.avatar_rental import AvatarRental
    from app.models.comment_draft import CommentDraft
    from app.models.correction_pattern import CorrectionPattern
    from app.models.edit_record import EditRecord
    from app.models.epg_slot import EPGSlot
    from app.models.geo_competitor import GeoCompetitor
    from app.models.geo_prompt import GeoPrompt
    from app.models.notification import Notification
    from app.models.post_draft import PostDraft
    from app.models.scrape_log import ScrapeLog
    from app.models.thread_score import ThreadScore
    from app.models.user_client_assignment import UserClientAssignment

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise ValueError("Client not found")

    client_name = client.client_name
    deleted = {}

    # 1. Delete users linked to this client (frees email for re-registration)
    #    Skip the current_user performing the deletion
    from app.models.audit import AuditLog as AuditLog2
    client_users = db.query(User).filter(
        User.client_id == client_id,
        User.id != current_user_id,
    ).all()
    deleted["users_deleted"] = len(client_users)
    for u in client_users:
        # Clear FK deps for each user before deletion
        db.query(AuditLog2).filter(AuditLog2.user_id == u.id).update(
            {"user_id": None}, synchronize_session=False
        )
        try:
            from app.models.geo_prompt import GeoPrompt as GP2
            db.query(GP2).filter(GP2.created_by == u.id).update(
                {"created_by": None}, synchronize_session=False
            )
        except Exception:
            pass
        try:
            from app.models.discovery_session import DiscoverySession as DS2
            db.query(DS2).filter(DS2.operator_user_id == u.id).update(
                {"operator_user_id": None}, synchronize_session=False
            )
        except Exception:
            pass
        db.delete(u)

    # 2. Delete user-client assignments
    deleted["user_client_assignments"] = db.query(UserClientAssignment).filter(
        UserClientAssignment.client_id == client_id
    ).delete(synchronize_session=False)

    # 3. Delete notifications
    try:
        deleted["notifications"] = db.query(Notification).filter(
            Notification.client_id == client_id
        ).delete(synchronize_session=False)
    except Exception:
        deleted["notifications"] = 0

    # 4. Delete voice feedback
    try:
        from app.models.voice_feedback import VoiceFeedback
        deleted["voice_feedback"] = db.query(VoiceFeedback).filter(
            VoiceFeedback.client_id == client_id
        ).delete(synchronize_session=False)
    except Exception:
        deleted["voice_feedback"] = 0

    # 5. Delete subreddit requests
    try:
        from app.models.subreddit_request import SubredditRequest
        deleted["subreddit_requests"] = db.query(SubredditRequest).filter(
            SubredditRequest.client_id == client_id
        ).delete(synchronize_session=False)
    except Exception:
        deleted["subreddit_requests"] = 0

    # 6. Delete client action logs
    try:
        from app.models.client_action_log import ClientActionLog
        deleted["client_action_logs"] = db.query(ClientActionLog).filter(
            ClientActionLog.client_id == client_id
        ).delete(synchronize_session=False)
    except Exception:
        deleted["client_action_logs"] = 0

    # 7. Delete GEO data
    deleted["geo_competitors"] = db.query(GeoCompetitor).filter(
        GeoCompetitor.client_id == client_id
    ).delete(synchronize_session=False)
    try:
        from app.models.geo_execution import GeoExecution
        prompt_ids = [p.id for p in db.query(GeoPrompt.id).filter(GeoPrompt.client_id == client_id).all()]
        if prompt_ids:
            deleted["geo_executions"] = db.query(GeoExecution).filter(
                GeoExecution.prompt_id.in_(prompt_ids)
            ).delete(synchronize_session=False)
        else:
            deleted["geo_executions"] = 0
    except Exception:
        deleted["geo_executions"] = 0
    deleted["geo_prompts"] = db.query(GeoPrompt).filter(
        GeoPrompt.client_id == client_id
    ).delete(synchronize_session=False)

    # 8. Delete EPG slots
    deleted["epg_slots"] = db.query(EPGSlot).filter(
        EPGSlot.client_id == client_id
    ).delete(synchronize_session=False)

    # 9. Delete correction patterns
    deleted["correction_patterns"] = db.query(CorrectionPattern).filter(
        CorrectionPattern.client_id == client_id
    ).delete(synchronize_session=False)

    # 10. Delete edit records
    deleted["edit_records"] = db.query(EditRecord).filter(
        EditRecord.client_id == client_id
    ).delete(synchronize_session=False)

    # 11. Delete post drafts
    deleted["post_drafts"] = db.query(PostDraft).filter(
        PostDraft.client_id == client_id
    ).delete(synchronize_session=False)

    # 12. Delete comment drafts
    deleted["comment_drafts"] = db.query(CommentDraft).filter(
        CommentDraft.client_id == client_id
    ).delete(synchronize_session=False)

    # 13. Delete thread scores
    deleted["thread_scores"] = db.query(ThreadScore).filter(
        ThreadScore.client_id == client_id
    ).delete(synchronize_session=False)

    # 14. Delete scrape logs
    deleted["scrape_logs"] = db.query(ScrapeLog).filter(
        ScrapeLog.client_id == client_id
    ).delete(synchronize_session=False)

    # 15. Delete activity events
    deleted["activity_events"] = db.query(ActivityEvent).filter(
        ActivityEvent.client_id == client_id
    ).delete(synchronize_session=False)

    # 16. Nullify AI usage logs (preserve for cost analytics)
    deleted["ai_usage_nullified"] = db.query(AIUsageLog).filter(
        AIUsageLog.client_id == client_id
    ).update({"client_id": None}, synchronize_session=False)

    # 17. Nullify audit logs (preserve audit trail)
    deleted["audit_logs_nullified"] = db.query(AuditLog).filter(
        AuditLog.client_id == client_id
    ).update({"client_id": None}, synchronize_session=False)

    # 18. Delete avatar rentals
    deleted["avatar_rentals"] = db.query(AvatarRental).filter(
        AvatarRental.client_id == client_id
    ).delete(synchronize_session=False)

    # 19. Unlink avatars (remove from client_ids array — avatars preserved)
    avatars = db.query(Avatar).filter(Avatar.client_ids.any(str(client_id))).all()
    deleted["avatars_unlinked"] = len(avatars)
    for avatar in avatars:
        if avatar.client_ids:
            avatar.client_ids = [cid for cid in avatar.client_ids if cid != str(client_id)]

    # 20. Delete subreddit assignments
    deleted["subreddit_assignments"] = db.query(ClientSubredditAssignment).filter(
        ClientSubredditAssignment.client_id == client_id
    ).delete(synchronize_session=False)
    deleted["client_subreddits"] = db.query(ClientSubreddit).filter(
        ClientSubreddit.client_id == client_id
    ).delete(synchronize_session=False)

    # 21. Delete threads (owned by this client)
    deleted["threads"] = db.query(RedditThread).filter(
        RedditThread.client_id == client_id
    ).delete(synchronize_session=False)

    # 22. Nullify discovery sessions (preserve research data)
    try:
        from app.models.discovery_session import DiscoverySession
        deleted["discovery_sessions_nullified"] = db.query(DiscoverySession).filter(
            DiscoverySession.client_id == client_id
        ).update({"client_id": None}, synchronize_session=False)
    except Exception:
        deleted["discovery_sessions_nullified"] = 0

    # 23. Nullify reddit_apps (shared pool)
    try:
        from app.models.reddit_app import RedditApp
        deleted["reddit_apps_nullified"] = db.query(RedditApp).filter(
            RedditApp.client_id == client_id
        ).update({"client_id": None}, synchronize_session=False)
    except Exception:
        deleted["reddit_apps_nullified"] = 0

    # 24. Finally, delete the client itself
    db.delete(client)
    db.commit()

    # Audit the deletion (client_id=None since client is gone)
    audit.log_action(
        db=db,
        user_id=current_user_id,
        action="delete_client_cascade",
        entity_type="client",
        entity_id=client_id,
        details={"client_name": client_name, "deleted_counts": deleted},
    )

    return {"client_name": client_name, "deleted": deleted}
