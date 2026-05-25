"""Query scoping layer for automatic client_id filtering on tenant-owned entities.

Provides the QueryScope class that enforces client data isolation at the query level.
All tenant-owned entity queries must go through this layer to prevent cross-client
data leakage.

Usage:
    # For authenticated user requests:
    scope = QueryScope(user=current_user)
    scoped = scope.scope_query(query, MyModel)
    client_ids = scope.get_authorized_client_ids()
    scope.assert_write_access(target_client_id)

    # For background tasks (Celery workers):
    scope = system_context()

    # Convenience:
    scope = get_query_scope(user)
"""

import inspect
import logging
import uuid

from sqlalchemy import select, or_, func

from app.config import get_settings
from app.models.user_role import UserRole

logger = logging.getLogger(__name__)


class SecurityError(Exception):
    """Raised when a user attempts an unauthorized operation on client data.

    This exception indicates a client data isolation boundary violation —
    the user does not have permission to access or modify the target client's data.
    """

    pass


class QueryScope:
    """Provides automatic client_id filtering for tenant-owned entities.

    Determines what client data a user (or system process) is authorized to access
    based on their role:
    - owner/partner: full access to all clients (returns None for client_ids)
    - system context: full access (background tasks)
    - client_admin/client_manager/client_viewer/b2c_user: scoped to own client_id only
    """

    def __init__(self, user=None, system: bool = False):
        """Initialize a QueryScope.

        Args:
            user: The authenticated User object, or None for system context.
            system: If True, this is a system-level scope (Celery workers, background tasks)
                    that bypasses user-based scoping.
        """
        self.user = user
        self.system = system

    def get_authorized_client_ids(self) -> list[uuid.UUID] | None:
        """Returns list of client_ids the user can access, or None for full access.

        Returns:
            None — for owner, partner, or system context (full access, no filtering needed)
            list[uuid.UUID] — for client-scoped users, containing their single client_id

        Raises:
            SecurityError: If a client-scoped user has no client_id assigned.
        """
        # System context — full access
        if self.system:
            return None

        # No user — this shouldn't happen in normal flow
        if self.user is None:
            logger.warning("SECURITY: get_authorized_client_ids called without user or system context")
            return []

        role = self.user.user_role

        # Owner and partner have full access to all clients
        if role in (UserRole.owner, UserRole.partner):
            return None

        # Client-scoped users: return their single client_id
        client_id = self.user.client_id
        if client_id is None:
            logger.warning(
                "SECURITY: Client-scoped user %s (role=%s) has no client_id assigned",
                self.user.id,
                role.value,
            )
            raise SecurityError(
                f"User {self.user.id} has role {role.value} but no client_id assigned"
            )

        return [client_id]

    def assert_write_access(self, client_id: uuid.UUID) -> None:
        """Raises SecurityError if user cannot write to the specified client_id.

        Write access rules:
        - owner/partner/system: always allowed (any client_id)
        - client_admin/client_manager/client_viewer/b2c_user: only if client_id
          matches their own user.client_id

        Args:
            client_id: The target client_id for the write operation.

        Raises:
            SecurityError: If the user is not authorized to write to the target client.
        """
        # System context — always allowed
        if self.system:
            return

        # No user context — deny
        if self.user is None:
            logger.error(
                "SECURITY: Write access attempted without user or system context, "
                "target client_id=%s",
                client_id,
            )
            raise SecurityError("Write operation requires user or system context")

        role = self.user.user_role

        # Owner and partner can write to any client
        if role in (UserRole.owner, UserRole.partner):
            return

        # Client-scoped users: verify client_id matches
        user_client_id = self.user.client_id
        if user_client_id is None:
            logger.error(
                "SECURITY: Client-scoped user %s (role=%s) attempted write with no client_id, "
                "target client_id=%s",
                self.user.id,
                role.value,
                client_id,
            )
            raise SecurityError(
                f"User {self.user.id} has role {role.value} but no client_id assigned"
            )

        if user_client_id != client_id:
            logger.error(
                "SECURITY: User %s (role=%s, client_id=%s) attempted write to "
                "client_id=%s — ACCESS DENIED",
                self.user.id,
                role.value,
                user_client_id,
                client_id,
            )
            raise SecurityError(
                f"User {self.user.id} cannot write to client {client_id} "
                f"(authorized for client {user_client_id} only)"
            )

    def scope_query(self, query, model):
        """Apply client_id filter to a query based on user's authorized clients.

        Args:
            query: A SQLAlchemy query object to filter.
            model: The SQLAlchemy model class being queried.

        Returns:
            The filtered query (or unfiltered for owner/partner/system).

        Raises:
            RuntimeError: In development mode, if called without user or system context.
        """
        if self.system:
            return query  # System context — no filter

        if self.user is None:
            # No user context — fail-closed
            settings = get_settings()
            if settings.app_env == "development":
                raise RuntimeError(
                    f"Query on {model.__tablename__} without user context. "
                    "Use system_context() for background tasks."
                )
            else:
                logger.warning(
                    "SECURITY: Query on %s without user context — returning empty",
                    model.__tablename__,
                )
                return query.filter(False)  # Return empty result

        if self.user.user_role in (UserRole.owner, UserRole.partner):
            return query  # Full access

        # Avatar manager: special scoping — only unassigned avatars
        if self.user.user_role == UserRole.avatar_manager:
            from app.models.avatar import Avatar
            if model is Avatar:
                return self._scope_avatar_query_unassigned(query)
            # Avatar manager cannot access other models
            logger.warning(
                "SECURITY: avatar_manager user %s attempted query on %s — returning empty",
                self.user.id,
                model.__tablename__,
            )
            return query.filter(False)

        # Client-scoped user
        client_id = self.user.client_id
        if client_id is None:
            logger.warning("SECURITY: User %s has no client_id", self.user.id)
            return query.filter(False)

        return self._apply_client_filter(query, model, client_id)

    def _apply_client_filter(self, query, model, client_id: uuid.UUID):
        """Route to the appropriate filter strategy based on model type.

        Args:
            query: The SQLAlchemy query to filter.
            model: The model class being queried.
            client_id: The client_id to filter by.

        Returns:
            The filtered query.
        """
        from app.models.avatar import Avatar
        from app.models.client import Client
        from app.models.thread import RedditThread
        from app.models.strategy_document import StrategyDocument

        # Special cases
        if model is Avatar:
            return self._scope_avatar_query(query, client_id)
        if model is RedditThread:
            return self._scope_reddit_thread_query(query, client_id)
        if model is StrategyDocument:
            return self._scope_strategy_document_query(query, client_id)
        if model is Client:
            return query.filter(model.id == client_id)

        # Default: direct client_id column filter
        if hasattr(model, "client_id"):
            return query.filter(model.client_id == client_id)

        # Model has no client_id — log warning and return empty for safety
        logger.warning(
            "SECURITY: Model %s has no client_id column and no special scoping — "
            "returning empty result",
            model.__tablename__,
        )
        return query.filter(False)

    def _scope_avatar_query_unassigned(self, query):
        """Filter avatars to only those NOT assigned to any client.

        Used by avatar_manager role — they can only see/manage avatars
        that have no client_ids (empty array or NULL).
        """
        from app.models.avatar import Avatar

        return query.filter(
            or_(
                Avatar.client_ids == None,  # noqa: E711
                Avatar.client_ids == [],
                Avatar.client_ids == "{}",
            )
        )

    def _scope_avatar_query(self, query, client_id: uuid.UUID):
        """Filter avatars to owned + actively rented by the client.

        Owned: Avatar.client_ids ARRAY contains the client_id string.
        Rented: Active, non-expired rental in avatar_rentals table.
        """
        from app.models.avatar import Avatar
        from app.models.avatar_rental import AvatarRental

        owned = Avatar.client_ids.any(str(client_id))
        rented = Avatar.id.in_(
            select(AvatarRental.avatar_id).where(
                AvatarRental.client_id == client_id,
                AvatarRental.is_active == True,  # noqa: E712
                or_(
                    AvatarRental.expires_at == None,  # noqa: E711
                    AvatarRental.expires_at > func.now(),
                ),
            )
        )
        return query.filter(or_(owned, rented))

    def _scope_reddit_thread_query(self, query, client_id: uuid.UUID):
        """Filter RedditThreads to those with a ThreadScore for this client.

        Threads are shared across clients; the per-client relationship is
        established through the ThreadScore table.
        """
        from app.models.thread import RedditThread
        from app.models.thread_score import ThreadScore

        return query.filter(
            RedditThread.id.in_(
                select(ThreadScore.thread_id).where(
                    ThreadScore.client_id == client_id
                )
            )
        )

    def _scope_strategy_document_query(self, query, client_id: uuid.UUID):
        """Filter StrategyDocuments to those belonging to the client's avatars.

        StrategyDocuments are linked to avatars; we scope by checking that the
        avatar's client_ids ARRAY contains the client_id.
        """
        from app.models.avatar import Avatar
        from app.models.strategy_document import StrategyDocument

        return query.filter(
            StrategyDocument.avatar_id.in_(
                select(Avatar.id).where(
                    Avatar.client_ids.any(str(client_id))
                )
            )
        )


def system_context(caller: str | None = None) -> QueryScope:
    """Create a system-level scope for background tasks.

    Bypasses user-based scoping. Logs the caller for audit trail.
    Use this in Celery workers and other background processes that need
    to query tenant-owned data without a user context.

    Args:
        caller: Optional explicit caller identifier. If None, the caller
                is determined automatically from the call stack.

    Returns:
        A QueryScope with system=True.
    """
    if caller is None:
        frame = inspect.stack()[1]
        caller = f"{frame.filename}:{frame.lineno} ({frame.function})"
    logger.info("SYSTEM_CONTEXT: Created by %s", caller)
    return QueryScope(system=True)


def get_query_scope(user) -> QueryScope:
    """Create a user-level scope from the authenticated user.

    Convenience shorthand for QueryScope(user=user).

    Args:
        user: The authenticated User object.

    Returns:
        A QueryScope scoped to the user's permissions.
    """
    return QueryScope(user=user)
