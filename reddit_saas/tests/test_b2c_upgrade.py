"""Tests for B2C to B2B upgrade path (task 10.3)."""

import uuid

import pytest

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.user import User
from app.models.user_role import UserRole
from app.services.access_control import upgrade_b2c_to_b2b


@pytest.fixture
def b2c_user_with_avatar(db):
    """Create a B2C user with a personal avatar."""
    # Create a placeholder client record for the B2C user's personal context
    personal_client = Client(
        client_name="Personal",
        brand_name="Personal",
        is_active=True,
    )
    db.add(personal_client)
    db.flush()

    # Create the B2C user
    user = User(
        email="b2c_user@test.com",
        hashed_password="hashed",
        full_name="B2C User",
        is_active=True,
        role=UserRole.b2c_user.value,
        client_id=personal_client.id,
    )
    db.add(user)
    db.flush()

    # Create the personal avatar linked to the user's client_id
    avatar = Avatar(
        reddit_username=f"b2c_avatar_{uuid.uuid4().hex[:8]}",
        client_ids=[str(personal_client.id)],
        active=True,
    )
    db.add(avatar)
    db.flush()

    return user, avatar, personal_client


class TestUpgradeB2CToB2B:
    """Tests for the upgrade_b2c_to_b2b service function."""

    def test_successful_upgrade_creates_client(self, db, b2c_user_with_avatar):
        """Upgrade creates a new Client record with correct fields."""
        user, avatar, _ = b2c_user_with_avatar

        new_client = upgrade_b2c_to_b2b(db, user, "Acme Corp", "AcmeBrand")

        assert new_client is not None
        assert new_client.id is not None
        assert new_client.client_name == "Acme Corp"
        assert new_client.brand_name == "AcmeBrand"
        assert new_client.is_active is True
        assert new_client.max_avatars == 3
        assert new_client.plan_type == "starter"

    def test_successful_upgrade_updates_user_role(self, db, b2c_user_with_avatar):
        """Upgrade sets user role to client_admin."""
        user, avatar, _ = b2c_user_with_avatar

        new_client = upgrade_b2c_to_b2b(db, user, "Acme Corp", "AcmeBrand")

        db.refresh(user)
        assert user.role == UserRole.client_admin.value
        assert user.user_role == UserRole.client_admin

    def test_successful_upgrade_updates_user_client_id(self, db, b2c_user_with_avatar):
        """Upgrade sets user.client_id to the new client's ID."""
        user, avatar, _ = b2c_user_with_avatar

        new_client = upgrade_b2c_to_b2b(db, user, "Acme Corp", "AcmeBrand")

        db.refresh(user)
        assert user.client_id == new_client.id

    def test_successful_upgrade_reassigns_avatar(self, db, b2c_user_with_avatar):
        """Upgrade converts personal avatar to company avatar (new client_id in client_ids)."""
        user, avatar, old_client = b2c_user_with_avatar

        new_client = upgrade_b2c_to_b2b(db, user, "Acme Corp", "AcmeBrand")

        db.refresh(avatar)
        assert str(new_client.id) in avatar.client_ids
        assert str(old_client.id) not in avatar.client_ids

    def test_upgrade_allows_additional_avatars(self, db, b2c_user_with_avatar):
        """After upgrade, user can create up to (max_avatars - 1) additional avatars."""
        user, avatar, _ = b2c_user_with_avatar

        new_client = upgrade_b2c_to_b2b(db, user, "Acme Corp", "AcmeBrand")

        # User already has 1 avatar, so they can create (max_avatars - 1) more
        # Count existing avatars for this client
        existing_count = (
            db.query(Avatar)
            .filter(Avatar.client_ids.any(str(new_client.id)))
            .count()
        )
        assert existing_count == 1
        assert new_client.max_avatars - existing_count == 2  # Can create 2 more

    def test_upgrade_rejects_non_b2c_user(self, db):
        """Upgrade raises ValueError if user is not a b2c_user."""
        user = User(
            email="manager@test.com",
            hashed_password="hashed",
            full_name="Manager",
            is_active=True,
            role=UserRole.client_manager.value,
        )
        db.add(user)
        db.flush()

        with pytest.raises(ValueError, match="Only b2c_user accounts can be upgraded"):
            upgrade_b2c_to_b2b(db, user, "Acme Corp", "AcmeBrand")

    def test_upgrade_rejects_owner_role(self, db):
        """Upgrade raises ValueError for owner role."""
        user = User(
            email="owner@test.com",
            hashed_password="hashed",
            full_name="Owner",
            is_active=True,
            role=UserRole.owner.value,
        )
        db.add(user)
        db.flush()

        with pytest.raises(ValueError, match="Only b2c_user accounts can be upgraded"):
            upgrade_b2c_to_b2b(db, user, "Acme Corp", "AcmeBrand")

    def test_upgrade_rejects_client_admin_role(self, db):
        """Upgrade raises ValueError for client_admin role (already B2B)."""
        user = User(
            email="admin@test.com",
            hashed_password="hashed",
            full_name="Admin",
            is_active=True,
            role=UserRole.client_admin.value,
        )
        db.add(user)
        db.flush()

        with pytest.raises(ValueError, match="Only b2c_user accounts can be upgraded"):
            upgrade_b2c_to_b2b(db, user, "Acme Corp", "AcmeBrand")

    def test_upgrade_rejects_empty_company_name(self, db, b2c_user_with_avatar):
        """Upgrade raises ValueError if company_name is empty."""
        user, _, _ = b2c_user_with_avatar

        with pytest.raises(ValueError, match="company_name is required"):
            upgrade_b2c_to_b2b(db, user, "", "AcmeBrand")

    def test_upgrade_rejects_whitespace_company_name(self, db, b2c_user_with_avatar):
        """Upgrade raises ValueError if company_name is only whitespace."""
        user, _, _ = b2c_user_with_avatar

        with pytest.raises(ValueError, match="company_name is required"):
            upgrade_b2c_to_b2b(db, user, "   ", "AcmeBrand")

    def test_upgrade_rejects_empty_brand_name(self, db, b2c_user_with_avatar):
        """Upgrade raises ValueError if brand_name is empty."""
        user, _, _ = b2c_user_with_avatar

        with pytest.raises(ValueError, match="brand_name is required"):
            upgrade_b2c_to_b2b(db, user, "Acme Corp", "")

    def test_upgrade_strips_whitespace_from_names(self, db, b2c_user_with_avatar):
        """Upgrade strips leading/trailing whitespace from company and brand names."""
        user, _, _ = b2c_user_with_avatar

        new_client = upgrade_b2c_to_b2b(db, user, "  Acme Corp  ", "  AcmeBrand  ")

        assert new_client.client_name == "Acme Corp"
        assert new_client.brand_name == "AcmeBrand"

    def test_upgrade_handles_user_without_avatar(self, db):
        """Upgrade succeeds even if user has no personal avatar (edge case)."""
        # Create a B2C user with a client_id but no avatar
        personal_client = Client(
            client_name="Personal",
            brand_name="Personal",
            is_active=True,
        )
        db.add(personal_client)
        db.flush()

        user = User(
            email="no_avatar@test.com",
            hashed_password="hashed",
            full_name="No Avatar User",
            is_active=True,
            role=UserRole.b2c_user.value,
            client_id=personal_client.id,
        )
        db.add(user)
        db.flush()

        # Should succeed without error — just no avatar to reassign
        new_client = upgrade_b2c_to_b2b(db, user, "Acme Corp", "AcmeBrand")

        assert new_client is not None
        assert user.role == UserRole.client_admin.value
        assert user.client_id == new_client.id

    def test_upgrade_returns_client_record(self, db, b2c_user_with_avatar):
        """Upgrade returns the new Client record."""
        user, _, _ = b2c_user_with_avatar

        result = upgrade_b2c_to_b2b(db, user, "Acme Corp", "AcmeBrand")

        assert isinstance(result, Client)
        assert result.id is not None
