"""Unit tests for avatar scoping (owned + rented).

Tests that the QueryScope.scope_query() method correctly filters avatars based on
ownership (via client_ids ARRAY) and rental state (via avatar_rentals table).

Validates: Requirements 4.10, 7.5, 7.9
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.avatar import Avatar
from app.models.avatar_rental import AvatarRental
from app.models.client import Client
from app.models.user import User
from app.models.user_role import UserRole
from app.services.query_scope import QueryScope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(db, **kwargs) -> Client:
    """Create a client record."""
    defaults = {
        "client_name": f"Client-{uuid.uuid4().hex[:6]}",
        "brand_name": f"Brand-{uuid.uuid4().hex[:6]}",
        "is_active": True,
    }
    defaults.update(kwargs)
    client = Client(**defaults)
    db.add(client)
    db.flush()
    return client


def _make_user(db, client: Client, role: UserRole = UserRole.client_manager) -> User:
    """Create a user scoped to a client."""
    user = User(
        email=f"user-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        full_name="Test User",
        is_active=True,
        is_superuser=False,
        role=role.value,
        client_id=client.id,
    )
    db.add(user)
    db.flush()
    return user


def _make_avatar(db, client_ids: list[str] | None = None) -> Avatar:
    """Create an avatar with given client_ids."""
    avatar = Avatar(
        reddit_username=f"avatar_{uuid.uuid4().hex[:8]}",
        active=True,
        client_ids=client_ids,
    )
    db.add(avatar)
    db.flush()
    return avatar


def _make_rental(
    db,
    avatar: Avatar,
    client: Client,
    is_active: bool = True,
    expires_at: datetime | None = None,
) -> AvatarRental:
    """Create an avatar rental record."""
    rental = AvatarRental(
        avatar_id=avatar.id,
        client_id=client.id,
        is_active=is_active,
        expires_at=expires_at,
    )
    db.add(rental)
    db.flush()
    return rental


def _get_scoped_avatars(db, user: User) -> list[Avatar]:
    """Run a scoped avatar query and return results."""
    scope = QueryScope(user=user)
    query = select(Avatar)
    scoped_query = scope.scope_query(query, Avatar)
    result = db.execute(scoped_query)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAvatarScopingOwned:
    """Test that owned avatars are visible to the owning client."""

    def test_owned_avatar_visible_to_client(self, db):
        """An avatar with client_id in its client_ids ARRAY is visible to that client's user."""
        client = _make_client(db)
        user = _make_user(db, client)
        avatar = _make_avatar(db, client_ids=[str(client.id)])

        results = _get_scoped_avatars(db, user)

        assert avatar.id in [a.id for a in results]

    def test_owned_avatar_with_multiple_clients(self, db):
        """An avatar shared across multiple clients is visible to each."""
        client_a = _make_client(db)
        client_b = _make_client(db)
        user_a = _make_user(db, client_a)
        user_b = _make_user(db, client_b)
        avatar = _make_avatar(db, client_ids=[str(client_a.id), str(client_b.id)])

        results_a = _get_scoped_avatars(db, user_a)
        results_b = _get_scoped_avatars(db, user_b)

        assert avatar.id in [a.id for a in results_a]
        assert avatar.id in [a.id for a in results_b]


class TestAvatarScopingRentedActive:
    """Test that actively rented avatars are visible to the renting client."""

    def test_rented_avatar_active_no_expiry_visible(self, db):
        """A rented avatar with is_active=True and no expiry is visible."""
        client = _make_client(db)
        user = _make_user(db, client)
        # Avatar not owned by this client
        avatar = _make_avatar(db, client_ids=[])
        _make_rental(db, avatar, client, is_active=True, expires_at=None)

        results = _get_scoped_avatars(db, user)

        assert avatar.id in [a.id for a in results]

    def test_rented_avatar_active_future_expiry_visible(self, db):
        """A rented avatar with is_active=True and future expires_at is visible."""
        client = _make_client(db)
        user = _make_user(db, client)
        avatar = _make_avatar(db, client_ids=[])
        future = datetime.now(timezone.utc) + timedelta(days=30)
        _make_rental(db, avatar, client, is_active=True, expires_at=future)

        results = _get_scoped_avatars(db, user)

        assert avatar.id in [a.id for a in results]


class TestAvatarScopingRentedExpired:
    """Test that expired rentals hide the avatar from the client."""

    def test_rented_avatar_expired_not_visible(self, db):
        """A rented avatar with expires_at in the past is NOT visible."""
        client = _make_client(db)
        user = _make_user(db, client)
        avatar = _make_avatar(db, client_ids=[])
        past = datetime.now(timezone.utc) - timedelta(days=1)
        _make_rental(db, avatar, client, is_active=True, expires_at=past)

        results = _get_scoped_avatars(db, user)

        assert avatar.id not in [a.id for a in results]


class TestAvatarScopingRentedInactive:
    """Test that inactive rentals hide the avatar from the client."""

    def test_rented_avatar_inactive_not_visible(self, db):
        """A rented avatar with is_active=False is NOT visible."""
        client = _make_client(db)
        user = _make_user(db, client)
        avatar = _make_avatar(db, client_ids=[])
        _make_rental(db, avatar, client, is_active=False, expires_at=None)

        results = _get_scoped_avatars(db, user)

        assert avatar.id not in [a.id for a in results]

    def test_rented_avatar_inactive_with_future_expiry_not_visible(self, db):
        """A rented avatar with is_active=False even with future expiry is NOT visible."""
        client = _make_client(db)
        user = _make_user(db, client)
        avatar = _make_avatar(db, client_ids=[])
        future = datetime.now(timezone.utc) + timedelta(days=30)
        _make_rental(db, avatar, client, is_active=False, expires_at=future)

        results = _get_scoped_avatars(db, user)

        assert avatar.id not in [a.id for a in results]


class TestAvatarScopingNotOwnedNotRented:
    """Test that avatars not owned and not rented are NOT visible."""

    def test_avatar_not_owned_not_rented_not_visible(self, db):
        """An avatar with no ownership or rental link to the client is NOT visible."""
        client = _make_client(db)
        other_client = _make_client(db)
        user = _make_user(db, client)
        # Avatar owned by a different client
        avatar_other = _make_avatar(db, client_ids=[str(other_client.id)])
        # Avatar with no client_ids at all
        avatar_orphan = _make_avatar(db, client_ids=[])

        results = _get_scoped_avatars(db, user)

        assert avatar_other.id not in [a.id for a in results]
        assert avatar_orphan.id not in [a.id for a in results]

    def test_avatar_rented_to_different_client_not_visible(self, db):
        """An avatar rented to a different client is NOT visible to this client."""
        client = _make_client(db)
        other_client = _make_client(db)
        user = _make_user(db, client)
        avatar = _make_avatar(db, client_ids=[])
        # Rental is for the OTHER client
        _make_rental(db, avatar, other_client, is_active=True, expires_at=None)

        results = _get_scoped_avatars(db, user)

        assert avatar.id not in [a.id for a in results]


class TestAvatarScopingCombined:
    """Test combined scenarios with owned and rented avatars."""

    def test_client_sees_both_owned_and_rented(self, db):
        """A client sees both owned avatars and actively rented avatars."""
        client = _make_client(db)
        user = _make_user(db, client)

        # Owned avatar
        owned = _make_avatar(db, client_ids=[str(client.id)])
        # Rented avatar (active, no expiry)
        rented = _make_avatar(db, client_ids=[])
        _make_rental(db, rented, client, is_active=True, expires_at=None)
        # Not accessible avatar
        other_client = _make_client(db)
        inaccessible = _make_avatar(db, client_ids=[str(other_client.id)])

        results = _get_scoped_avatars(db, user)
        result_ids = [a.id for a in results]

        assert owned.id in result_ids
        assert rented.id in result_ids
        assert inaccessible.id not in result_ids

    def test_mixed_rental_states(self, db):
        """Only active, non-expired rentals are visible alongside owned avatars."""
        client = _make_client(db)
        user = _make_user(db, client)

        # Owned
        owned = _make_avatar(db, client_ids=[str(client.id)])
        # Active rental (no expiry)
        active_rental = _make_avatar(db, client_ids=[])
        _make_rental(db, active_rental, client, is_active=True, expires_at=None)
        # Expired rental
        expired_rental = _make_avatar(db, client_ids=[])
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        _make_rental(db, expired_rental, client, is_active=True, expires_at=past)
        # Inactive rental
        inactive_rental = _make_avatar(db, client_ids=[])
        _make_rental(db, inactive_rental, client, is_active=False, expires_at=None)

        results = _get_scoped_avatars(db, user)
        result_ids = [a.id for a in results]

        assert owned.id in result_ids
        assert active_rental.id in result_ids
        assert expired_rental.id not in result_ids
        assert inactive_rental.id not in result_ids
