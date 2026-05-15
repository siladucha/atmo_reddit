"""Unit tests for the _avatar_accessible_by_client isolation helper.

Tests that the helper correctly identifies avatar accessibility via ownership
(client_ids ARRAY) and rental (avatar_rentals table).

Validates: Requirements 5.7
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.avatar import Avatar
from app.models.avatar_rental import AvatarRental
from app.models.client import Client
from app.services.isolation import _avatar_accessible_by_client


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


# ---------------------------------------------------------------------------
# Tests — Ownership
# ---------------------------------------------------------------------------


class TestOwnership:
    """Test avatar accessibility via client_ids ARRAY ownership."""

    def test_owned_avatar_accessible(self, db):
        """Avatar with client.id in client_ids is accessible."""
        client = _make_client(db)
        avatar = _make_avatar(db, client_ids=[str(client.id)])

        assert _avatar_accessible_by_client(db, avatar, client) is True

    def test_owned_avatar_multiple_clients(self, db):
        """Avatar shared across multiple clients is accessible to each."""
        client_a = _make_client(db)
        client_b = _make_client(db)
        avatar = _make_avatar(db, client_ids=[str(client_a.id), str(client_b.id)])

        assert _avatar_accessible_by_client(db, avatar, client_a) is True
        assert _avatar_accessible_by_client(db, avatar, client_b) is True

    def test_not_owned_avatar_not_accessible(self, db):
        """Avatar owned by a different client is not accessible."""
        client_a = _make_client(db)
        client_b = _make_client(db)
        avatar = _make_avatar(db, client_ids=[str(client_b.id)])

        assert _avatar_accessible_by_client(db, avatar, client_a) is False

    def test_avatar_with_empty_client_ids_not_accessible(self, db):
        """Avatar with empty client_ids list is not accessible via ownership."""
        client = _make_client(db)
        avatar = _make_avatar(db, client_ids=[])

        assert _avatar_accessible_by_client(db, avatar, client) is False

    def test_avatar_with_null_client_ids_not_accessible(self, db):
        """Avatar with null client_ids is not accessible via ownership."""
        client = _make_client(db)
        avatar = _make_avatar(db, client_ids=None)

        assert _avatar_accessible_by_client(db, avatar, client) is False


# ---------------------------------------------------------------------------
# Tests — Active Rental
# ---------------------------------------------------------------------------


class TestActiveRental:
    """Test avatar accessibility via active rental records."""

    def test_active_rental_no_expiry_accessible(self, db):
        """Avatar with active rental and no expiry is accessible."""
        client = _make_client(db)
        avatar = _make_avatar(db, client_ids=[])
        _make_rental(db, avatar, client, is_active=True, expires_at=None)

        assert _avatar_accessible_by_client(db, avatar, client) is True

    def test_active_rental_future_expiry_accessible(self, db):
        """Avatar with active rental and future expiry is accessible."""
        client = _make_client(db)
        avatar = _make_avatar(db, client_ids=[])
        future = datetime.now(timezone.utc) + timedelta(days=30)
        _make_rental(db, avatar, client, is_active=True, expires_at=future)

        assert _avatar_accessible_by_client(db, avatar, client) is True


# ---------------------------------------------------------------------------
# Tests — Expired / Inactive Rental
# ---------------------------------------------------------------------------


class TestExpiredOrInactiveRental:
    """Test that expired or inactive rentals do NOT grant access."""

    def test_expired_rental_not_accessible(self, db):
        """Avatar with expired rental is not accessible."""
        client = _make_client(db)
        avatar = _make_avatar(db, client_ids=[])
        past = datetime.now(timezone.utc) - timedelta(days=1)
        _make_rental(db, avatar, client, is_active=True, expires_at=past)

        assert _avatar_accessible_by_client(db, avatar, client) is False

    def test_inactive_rental_not_accessible(self, db):
        """Avatar with is_active=False rental is not accessible."""
        client = _make_client(db)
        avatar = _make_avatar(db, client_ids=[])
        _make_rental(db, avatar, client, is_active=False, expires_at=None)

        assert _avatar_accessible_by_client(db, avatar, client) is False

    def test_inactive_rental_with_future_expiry_not_accessible(self, db):
        """Avatar with is_active=False even with future expiry is not accessible."""
        client = _make_client(db)
        avatar = _make_avatar(db, client_ids=[])
        future = datetime.now(timezone.utc) + timedelta(days=30)
        _make_rental(db, avatar, client, is_active=False, expires_at=future)

        assert _avatar_accessible_by_client(db, avatar, client) is False


# ---------------------------------------------------------------------------
# Tests — No Ownership and No Rental
# ---------------------------------------------------------------------------


class TestNoAccess:
    """Test that avatars with no ownership or rental link are not accessible."""

    def test_no_ownership_no_rental(self, db):
        """Avatar with no ownership or rental is not accessible."""
        client = _make_client(db)
        avatar = _make_avatar(db, client_ids=[])

        assert _avatar_accessible_by_client(db, avatar, client) is False

    def test_rental_to_different_client(self, db):
        """Avatar rented to a different client is not accessible."""
        client_a = _make_client(db)
        client_b = _make_client(db)
        avatar = _make_avatar(db, client_ids=[])
        _make_rental(db, avatar, client_b, is_active=True, expires_at=None)

        assert _avatar_accessible_by_client(db, avatar, client_a) is False
