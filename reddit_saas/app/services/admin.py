"""Admin service layer — business logic for admin panel operations.

This module is extended incrementally by later tasks with client, keyword,
subreddit, avatar, health, AI cost, and task monitoring functions.
"""

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
            db.query(func.count(ClientSubreddit.id))
            .filter(
                ClientSubreddit.client_id == client.id,
                ClientSubreddit.is_active.is_(True),
            )
            .scalar()
        )

        avatar_count = (
            db.query(func.count(Avatar.id))
            .filter(Avatar.client_ids.any(str(client.id)))
            .scalar()
        )

        result.append({
            "client": client,
            "subreddit_count": subreddit_count,
            "avatar_count": avatar_count,
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
    """Deactivate a client and cascade: unassign avatars and deactivate subreddits.

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

    # Cascade: deactivate all subreddits for this client
    db.query(ClientSubreddit).filter(
        ClientSubreddit.client_id == client_id,
        ClientSubreddit.is_active.is_(True),
    ).update({"is_active": False})

    # Cascade: unassign this client from all avatars
    client_id_str = str(client_id)
    avatars = db.query(Avatar).filter(Avatar.client_ids.any(client_id_str)).all()
    for avatar in avatars:
        avatar.client_ids = [cid for cid in avatar.client_ids if cid != client_id_str]
        flag_modified(avatar, "client_ids")

    db.commit()
    db.refresh(client)

    audit.log_action(
        db=db,
        user_id=current_user_id,
        action="deactivate",
        entity_type="client",
        entity_id=client.id,
        client_id=client.id,
        details={"cascaded": True},
    )

    return client


# ---------------------------------------------------------------------------
# Keyword management
# ---------------------------------------------------------------------------

_VALID_PRIORITIES = {"HIGH", "MEDIUM", "LOW"}


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
    for priority in ("high", "medium", "low"):
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
    for pkey in ("high", "medium", "low"):
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

    # Verify client exists and is active
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise ValueError("Client not found")
    if not client.is_active:
        raise ValueError("Cannot assign avatars to inactive client")

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
        health["llm"] = {
            "status": "ok",
            "message": f"Key configured",
            "detail": f"Scoring: {get_config('llm_scoring_model', db)}, Generation: {get_config('llm_generation_model', db)}",
        }

    return health


def check_single_service(service_name: str, db: Session) -> dict:
    """Run health check for a single service. Used by the HTMX test button."""
    full = check_system_health(db)
    return full.get(service_name, {"status": "critical", "message": "Unknown service"})


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


def get_ai_cost_summary(db: Session) -> dict:
    """Return aggregate AI usage statistics.

    Args:
        db: SQLAlchemy database session.

    Returns:
        A dict with ``total_cost``, ``total_calls``, ``total_input_tokens``,
        ``total_output_tokens``.
    """
    row = (
        db.query(
            func.coalesce(func.sum(AIUsageLog.cost_usd), 0).label("total_cost"),
            func.count(AIUsageLog.id).label("total_calls"),
            func.coalesce(func.sum(AIUsageLog.input_tokens), 0).label("total_input_tokens"),
            func.coalesce(func.sum(AIUsageLog.output_tokens), 0).label("total_output_tokens"),
        )
        .one()
    )
    return {
        "total_cost": float(row.total_cost),
        "total_calls": row.total_calls,
        "total_input_tokens": row.total_input_tokens,
        "total_output_tokens": row.total_output_tokens,
    }


def get_ai_costs_by_client(db: Session) -> list[dict]:
    """Return AI costs grouped by client.

    Args:
        db: SQLAlchemy database session.

    Returns:
        A list of dicts with ``client_name``, ``calls``, ``cost``,
        ``input_tokens``, ``output_tokens``.
    """
    rows = (
        db.query(
            Client.client_name,
            func.count(AIUsageLog.id).label("calls"),
            func.coalesce(func.sum(AIUsageLog.cost_usd), 0).label("cost"),
            func.coalesce(func.sum(AIUsageLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(AIUsageLog.output_tokens), 0).label("output_tokens"),
        )
        .join(Client, AIUsageLog.client_id == Client.id)
        .group_by(Client.client_name)
        .all()
    )
    return [
        {
            "client_name": row.client_name,
            "calls": row.calls,
            "cost": float(row.cost),
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
        }
        for row in rows
    ]


def get_ai_costs_by_operation(db: Session) -> list[dict]:
    """Return AI costs grouped by operation type.

    Args:
        db: SQLAlchemy database session.

    Returns:
        A list of dicts with ``operation``, ``calls``, ``cost``,
        ``input_tokens``, ``output_tokens``.
    """
    rows = (
        db.query(
            AIUsageLog.operation,
            func.count(AIUsageLog.id).label("calls"),
            func.coalesce(func.sum(AIUsageLog.cost_usd), 0).label("cost"),
            func.coalesce(func.sum(AIUsageLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(AIUsageLog.output_tokens), 0).label("output_tokens"),
        )
        .group_by(AIUsageLog.operation)
        .all()
    )
    return [
        {
            "operation": row.operation,
            "calls": row.calls,
            "cost": float(row.cost),
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
        }
        for row in rows
    ]


def get_ai_costs_by_model(db: Session) -> list[dict]:
    """Return AI costs grouped by model.

    Args:
        db: SQLAlchemy database session.

    Returns:
        A list of dicts with ``model``, ``calls``, ``cost``,
        ``input_tokens``, ``output_tokens``.
    """
    rows = (
        db.query(
            AIUsageLog.model,
            func.count(AIUsageLog.id).label("calls"),
            func.coalesce(func.sum(AIUsageLog.cost_usd), 0).label("cost"),
            func.coalesce(func.sum(AIUsageLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(AIUsageLog.output_tokens), 0).label("output_tokens"),
        )
        .group_by(AIUsageLog.model)
        .all()
    )
    return [
        {
            "model": row.model,
            "calls": row.calls,
            "cost": float(row.cost),
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
        }
        for row in rows
    ]


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

    task_map = {
        "full": "run_full_pipeline_all_clients",
        "hobby": "run_hobby_pipeline_all_avatars",
        "health": "check_all_avatars_health",
    }

    task_name = task_map.get(pipeline_type)
    if not task_name:
        raise ValueError(f"Unknown pipeline type: {pipeline_type}")

    result = celery_app.send_task(task_name, args=[entity_id])
    return str(result.id)
