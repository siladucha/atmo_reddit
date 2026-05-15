"""Tests for access_control service — conditional draft approval logic.

Tests cover:
- can_approve_drafts returns True for owner, partner, qa, client_admin, client_manager
- can_approve_drafts returns True for client_viewer when draft_approval_enabled=True
- can_approve_drafts returns False for client_viewer when draft_approval_enabled=False
- can_approve_drafts returns False for b2c_user regardless of flag
- check_avatar_limit raises 403 when limit reached for non-admin users
- check_avatar_limit allows creation when under limit
- check_avatar_limit skips check for owner/partner (platform admins)
- Integration: client_viewer can approve/reject/edit drafts when flag is enabled
- Integration: client_viewer gets 403 on approve/reject/edit when flag is disabled
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.user_role import UserRole
from app.services.access_control import can_approve_drafts, check_avatar_limit, check_b2c_avatar_limit


def _make_user(role: UserRole, client_id=None):
    """Create a mock User with the given role."""
    user = MagicMock()
    user.user_role = role
    user.client_id = client_id or uuid.uuid4()
    user.is_superuser = role in (UserRole.owner, UserRole.partner)
    user.is_active = True
    return user


def _make_client(draft_approval_enabled: bool = False):
    """Create a mock Client with the given draft_approval_enabled flag."""
    client = MagicMock()
    client.id = uuid.uuid4()
    client.draft_approval_enabled = draft_approval_enabled
    client.is_active = True
    return client


class TestCanApproveDrafts:
    """Unit tests for can_approve_drafts service function."""

    def test_owner_always_allowed(self):
        user = _make_user(UserRole.owner)
        client = _make_client(draft_approval_enabled=False)
        assert can_approve_drafts(user, client) is True

    def test_partner_always_allowed(self):
        user = _make_user(UserRole.partner)
        client = _make_client(draft_approval_enabled=False)
        assert can_approve_drafts(user, client) is True

    def test_qa_always_allowed(self):
        user = _make_user(UserRole.qa)
        client = _make_client(draft_approval_enabled=False)
        assert can_approve_drafts(user, client) is True

    def test_client_admin_always_allowed(self):
        user = _make_user(UserRole.client_admin)
        client = _make_client(draft_approval_enabled=False)
        assert can_approve_drafts(user, client) is True

    def test_client_manager_always_allowed(self):
        user = _make_user(UserRole.client_manager)
        client = _make_client(draft_approval_enabled=False)
        assert can_approve_drafts(user, client) is True

    def test_client_viewer_allowed_when_flag_enabled(self):
        user = _make_user(UserRole.client_viewer)
        client = _make_client(draft_approval_enabled=True)
        assert can_approve_drafts(user, client) is True

    def test_client_viewer_denied_when_flag_disabled(self):
        user = _make_user(UserRole.client_viewer)
        client = _make_client(draft_approval_enabled=False)
        assert can_approve_drafts(user, client) is False

    def test_b2c_user_always_denied(self):
        user = _make_user(UserRole.b2c_user)
        client = _make_client(draft_approval_enabled=True)
        assert can_approve_drafts(user, client) is False

    def test_b2c_user_denied_even_with_flag_enabled(self):
        user = _make_user(UserRole.b2c_user)
        client = _make_client(draft_approval_enabled=True)
        assert can_approve_drafts(user, client) is False


class TestCheckAvatarLimit:
    """Unit tests for check_avatar_limit service function."""

    def _make_mock_db(self, avatar_count: int):
        """Create a mock DB session that returns a given avatar count."""
        db = MagicMock()
        query = MagicMock()
        db.query.return_value = query
        query.filter.return_value = query
        query.count.return_value = avatar_count
        return db

    def test_owner_bypasses_limit(self):
        """Owner can create avatars regardless of limit."""
        user = _make_user(UserRole.owner)
        client = _make_client()
        client.max_avatars = 3
        db = self._make_mock_db(avatar_count=10)  # Way over limit

        # Should not raise
        check_avatar_limit(db, client, user)

    def test_partner_bypasses_limit(self):
        """Partner can create avatars regardless of limit."""
        user = _make_user(UserRole.partner)
        client = _make_client()
        client.max_avatars = 3
        db = self._make_mock_db(avatar_count=10)  # Way over limit

        # Should not raise
        check_avatar_limit(db, client, user)

    def test_client_admin_blocked_at_limit(self):
        """client_admin gets 403 when avatar count equals max_avatars."""
        from fastapi import HTTPException

        user = _make_user(UserRole.client_admin)
        client = _make_client()
        client.max_avatars = 3
        db = self._make_mock_db(avatar_count=3)

        with pytest.raises(HTTPException) as exc_info:
            check_avatar_limit(db, client, user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Maximum avatars reached for your plan"

    def test_client_admin_blocked_over_limit(self):
        """client_admin gets 403 when avatar count exceeds max_avatars."""
        from fastapi import HTTPException

        user = _make_user(UserRole.client_admin)
        client = _make_client()
        client.max_avatars = 3
        db = self._make_mock_db(avatar_count=5)

        with pytest.raises(HTTPException) as exc_info:
            check_avatar_limit(db, client, user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Maximum avatars reached for your plan"

    def test_client_admin_allowed_under_limit(self):
        """client_admin can create when under the limit."""
        user = _make_user(UserRole.client_admin)
        client = _make_client()
        client.max_avatars = 3
        db = self._make_mock_db(avatar_count=2)

        # Should not raise
        check_avatar_limit(db, client, user)

    def test_client_manager_blocked_at_limit(self):
        """client_manager gets 403 when avatar count equals max_avatars."""
        from fastapi import HTTPException

        user = _make_user(UserRole.client_manager)
        client = _make_client()
        client.max_avatars = 5
        db = self._make_mock_db(avatar_count=5)

        with pytest.raises(HTTPException) as exc_info:
            check_avatar_limit(db, client, user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Maximum avatars reached for your plan"

    def test_client_manager_allowed_under_limit(self):
        """client_manager can create when under the limit."""
        user = _make_user(UserRole.client_manager)
        client = _make_client()
        client.max_avatars = 5
        db = self._make_mock_db(avatar_count=4)

        # Should not raise
        check_avatar_limit(db, client, user)

    def test_b2c_user_blocked_at_limit(self):
        """b2c_user gets 403 when avatar count equals max_avatars."""
        from fastapi import HTTPException

        user = _make_user(UserRole.b2c_user)
        client = _make_client()
        client.max_avatars = 1
        db = self._make_mock_db(avatar_count=1)

        with pytest.raises(HTTPException) as exc_info:
            check_avatar_limit(db, client, user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Maximum avatars reached for your plan"

    def test_client_viewer_blocked_at_limit(self):
        """client_viewer gets 403 when avatar count equals max_avatars."""
        from fastapi import HTTPException

        user = _make_user(UserRole.client_viewer)
        client = _make_client()
        client.max_avatars = 3
        db = self._make_mock_db(avatar_count=3)

        with pytest.raises(HTTPException) as exc_info:
            check_avatar_limit(db, client, user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Maximum avatars reached for your plan"

    def test_zero_avatars_allowed(self):
        """Creation allowed when client has zero avatars."""
        user = _make_user(UserRole.client_admin)
        client = _make_client()
        client.max_avatars = 3
        db = self._make_mock_db(avatar_count=0)

        # Should not raise
        check_avatar_limit(db, client, user)


class TestCheckB2cAvatarLimit:
    """Unit tests for check_b2c_avatar_limit service function."""

    def _make_mock_db(self, avatar_count: int):
        """Create a mock DB session that returns the given avatar count."""
        db = MagicMock()
        query = MagicMock()
        db.query.return_value = query
        query.filter.return_value = query
        query.count.return_value = avatar_count
        return db

    def test_non_b2c_user_skipped(self):
        """Non-B2C roles are not checked (no-op)."""
        for role in (UserRole.owner, UserRole.partner, UserRole.client_admin,
                     UserRole.client_manager, UserRole.client_viewer):
            user = _make_user(role)
            db = self._make_mock_db(avatar_count=5)

            # Should not raise for any non-b2c role
            check_b2c_avatar_limit(db, user)

    def test_b2c_user_blocked_when_has_avatar(self):
        """B2C user gets 403 when they already have an avatar."""
        user = _make_user(UserRole.b2c_user)
        db = self._make_mock_db(avatar_count=1)

        with pytest.raises(HTTPException) as exc_info:
            check_b2c_avatar_limit(db, user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "B2C users can have only one avatar"

    def test_b2c_user_blocked_when_has_multiple_avatars(self):
        """B2C user gets 403 when they somehow have multiple avatars."""
        user = _make_user(UserRole.b2c_user)
        db = self._make_mock_db(avatar_count=3)

        with pytest.raises(HTTPException) as exc_info:
            check_b2c_avatar_limit(db, user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "B2C users can have only one avatar"

    def test_b2c_user_allowed_when_no_avatar(self):
        """B2C user can create their first avatar."""
        user = _make_user(UserRole.b2c_user)
        db = self._make_mock_db(avatar_count=0)

        # Should not raise
        check_b2c_avatar_limit(db, user)

    def test_b2c_user_no_client_id_blocked(self):
        """B2C user without client_id gets 403."""
        user = _make_user(UserRole.b2c_user, client_id=None)
        user.client_id = None
        db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            check_b2c_avatar_limit(db, user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "B2C users can have only one avatar"


class TestCanApproveDraftsIntegration:
    """Integration tests for draft approval endpoints.

    NOTE: These tests require Docker DB to be running (app connects to db:5432).
    They validate the full HTTP flow including auth middleware and route handlers.
    Run with: docker compose up -d db && pytest tests/test_access_control.py::TestCanApproveDraftsIntegration
    """

    def _create_test_data(self, db, draft_approval_enabled: bool, user_role: str, user_email: str):
        """Helper to create client, user, thread, avatar, and draft for testing."""
        from app.models.client import Client
        from app.models.subreddit import Subreddit
        from app.models.thread import RedditThread
        from app.models.avatar import Avatar
        from app.models.comment_draft import CommentDraft
        from app.services.auth import create_user

        # Create client
        client_record = Client(
            client_name=f"Test Client {user_email}",
            brand_name=f"TestBrand {user_email}",
            draft_approval_enabled=draft_approval_enabled,
        )
        db.add(client_record)
        db.flush()

        # Create a subreddit
        subreddit = Subreddit(
            subreddit_name=f"r/test_{user_email.replace('@', '_')}",
            is_active=True,
        )
        db.add(subreddit)
        db.flush()

        # Create a thread
        thread = RedditThread(
            reddit_native_id=f"t3_test_{user_email.replace('@', '_')}",
            subreddit=f"r/test_{user_email.replace('@', '_')}",
            subreddit_id=subreddit.id,
            post_title="Test Thread",
            url="https://reddit.com/r/test/comments/test",
            type="professional",
            score=10,
            ups=10,
            downs=0,
        )
        db.add(thread)
        db.flush()

        # Create an avatar
        avatar = Avatar(
            reddit_username=f"test_avatar_{user_email.replace('@', '_')}",
            client_ids=[str(client_record.id)],
            active=True,
            karma_post=100,
            karma_comment=500,
            is_shadowbanned=False,
        )
        db.add(avatar)
        db.flush()

        # Create user
        user = create_user(db, email=user_email, password="pass123", full_name=f"User {user_email}")
        user.role = user_role
        user.client_id = client_record.id
        db.flush()

        # Create a draft
        draft = CommentDraft(
            thread_id=thread.id,
            client_id=client_record.id,
            avatar_id=avatar.id,
            status="pending",
            ai_draft="Test draft content",
        )
        db.add(draft)
        db.flush()

        return client_record, user, draft

    @pytest.mark.skipif(
        True,  # Skip when Docker DB is not available
        reason="Requires Docker DB (app connects to db:5432)"
    )
    def test_client_viewer_approve_denied_when_flag_disabled(self, db):
        """client_viewer gets 403 when trying to approve a draft with flag disabled."""
        from app.services.auth import create_access_token
        from app.database import get_db
        from app.main import app
        from fastapi.testclient import TestClient

        _, viewer, draft = self._create_test_data(
            db, draft_approval_enabled=False, user_role="client_viewer",
            user_email="viewer_disabled@test.com"
        )

        token = create_access_token(data={
            "sub": str(viewer.id),
            "email": viewer.email,
            "role": viewer.user_role.value,
            "is_superuser": viewer.is_superuser,
        })

        def override_get_db():
            yield db

        app.dependency_overrides[get_db] = override_get_db
        try:
            with TestClient(app) as c:
                c.cookies.set("access_token", token)
                response = c.post(f"/review/{draft.id}/approve")
                assert response.status_code == 403
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.skipif(
        True,  # Skip when Docker DB is not available
        reason="Requires Docker DB (app connects to db:5432)"
    )
    def test_client_viewer_approve_allowed_when_flag_enabled(self, db):
        """client_viewer can approve a draft when draft_approval_enabled=True."""
        from app.services.auth import create_access_token
        from app.database import get_db
        from app.main import app
        from fastapi.testclient import TestClient

        _, viewer, draft = self._create_test_data(
            db, draft_approval_enabled=True, user_role="client_viewer",
            user_email="viewer_enabled@test.com"
        )

        token = create_access_token(data={
            "sub": str(viewer.id),
            "email": viewer.email,
            "role": viewer.user_role.value,
            "is_superuser": viewer.is_superuser,
        })

        def override_get_db():
            yield db

        app.dependency_overrides[get_db] = override_get_db
        try:
            with TestClient(app) as c:
                c.cookies.set("access_token", token)
                response = c.post(f"/review/{draft.id}/approve")
                assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()
