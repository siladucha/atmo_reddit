"""Tests for client portal review queue date filter.

Covers:
- GET /clients/{id}/partials/drafts?status=pending&date_filter=today — only today's drafts
- GET /clients/{id}/partials/drafts?status=pending&date_filter=7d — last 7 days
- GET /clients/{id}/partials/drafts?status=pending (no date_filter) — default 14 days
- GET /clients/{id}/partials/drafts?status=approved&date_filter=today — only today's approved
- GET /clients/{id}/review — page renders with date filter UI and today's counts
"""

import uuid
from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import get_db
from app.main import app
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.user import User
from app.models.user_role import UserRole
from app.services.auth import create_access_token


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_client(db: Session) -> Client:
    c = Client(
        client_name=f"DateFilter-Test-{uuid.uuid4().hex[:6]}",
        brand_name=f"Brand-{uuid.uuid4().hex[:6]}",
        is_active=True,
        keywords={"high": [], "medium": [], "low": []},
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_avatar(db: Session, client_id: uuid.UUID) -> Avatar:
    a = Avatar(
        reddit_username=f"test_avatar_{uuid.uuid4().hex[:6]}",
        client_ids=[str(client_id)],
        active=True,
        is_frozen=False,
        warming_phase=2,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _make_draft(db: Session, avatar_id: uuid.UUID, status: str = "pending", created_at: datetime = None) -> CommentDraft:
    d = CommentDraft(
        avatar_id=avatar_id,
        ai_draft=f"Test comment {uuid.uuid4().hex[:8]}",
        status=status,
        type="professional",
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    # Update created_at directly (bypassing default)
    if created_at:
        db.execute(
            CommentDraft.__table__.update()
            .where(CommentDraft.__table__.c.id == d.id)
            .values(created_at=created_at)
        )
        db.commit()
        db.refresh(d)
    return d


def _make_user(db: Session, role: UserRole, client_id=None) -> User:
    user = User(
        email=f"datefilter-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        full_name="Date Filter Test User",
        is_active=True,
        is_superuser=role == UserRole.owner,
        role=role.value,
        client_id=client_id,
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _authenticated_client(db: Session, user: User) -> TestClient:
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    token = create_access_token(data={
        "sub": str(user.id),
        "email": user.email,
        "role": user.user_role.value,
        "is_superuser": user.is_superuser,
    })
    tc = TestClient(app)
    tc.cookies.set("access_token", token)
    return tc


# ---------------------------------------------------------------------------
# Tests: Date filter on drafts partial
# ---------------------------------------------------------------------------


class TestDateFilterDraftsPartial:
    """Test date_filter parameter on /clients/{id}/partials/drafts."""

    def test_today_filter_shows_only_today(self, db):
        """date_filter=today returns only drafts from today."""
        client_obj = _make_client(db)
        avatar = _make_avatar(db, client_obj.id)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)

        # Create draft today (default created_at = now)
        draft_today = _make_draft(db, avatar.id, status="pending")

        # Create draft 3 days ago
        three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
        draft_old = _make_draft(db, avatar.id, status="pending", created_at=three_days_ago)

        tc = _authenticated_client(db, user)
        try:
            r = tc.get(f"/clients/{client_obj.id}/partials/drafts?status=pending&date_filter=today")
            assert r.status_code == 200
            # Today's draft should be present
            assert str(draft_today.id) in r.text
            # Old draft should NOT be present
            assert str(draft_old.id) not in r.text
        finally:
            app.dependency_overrides.clear()

    def test_7d_filter_shows_last_week(self, db):
        """date_filter=7d returns drafts from last 7 days."""
        client_obj = _make_client(db)
        avatar = _make_avatar(db, client_obj.id)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)

        # Create draft 3 days ago (within 7d)
        three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
        draft_recent = _make_draft(db, avatar.id, status="pending", created_at=three_days_ago)

        # Create draft 10 days ago (outside 7d)
        ten_days_ago = datetime.now(timezone.utc) - timedelta(days=10)
        draft_old = _make_draft(db, avatar.id, status="pending", created_at=ten_days_ago)

        tc = _authenticated_client(db, user)
        try:
            r = tc.get(f"/clients/{client_obj.id}/partials/drafts?status=pending&date_filter=7d")
            assert r.status_code == 200
            assert str(draft_recent.id) in r.text
            assert str(draft_old.id) not in r.text
        finally:
            app.dependency_overrides.clear()

    def test_no_filter_defaults_to_14d(self, db):
        """No date_filter (or date_filter=all) uses default 14-day window."""
        client_obj = _make_client(db)
        avatar = _make_avatar(db, client_obj.id)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)

        # Create draft 10 days ago (within 14d)
        ten_days_ago = datetime.now(timezone.utc) - timedelta(days=10)
        draft_10d = _make_draft(db, avatar.id, status="pending", created_at=ten_days_ago)

        tc = _authenticated_client(db, user)
        try:
            # No date_filter param
            r = tc.get(f"/clients/{client_obj.id}/partials/drafts?status=pending")
            assert r.status_code == 200
            assert str(draft_10d.id) in r.text
        finally:
            app.dependency_overrides.clear()

    def test_today_filter_approved_tab(self, db):
        """date_filter=today works for approved status too."""
        client_obj = _make_client(db)
        avatar = _make_avatar(db, client_obj.id)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)

        # Create approved draft today
        draft_today = _make_draft(db, avatar.id, status="approved")

        # Create approved draft 5 days ago
        five_days_ago = datetime.now(timezone.utc) - timedelta(days=5)
        draft_old = _make_draft(db, avatar.id, status="approved", created_at=five_days_ago)

        tc = _authenticated_client(db, user)
        try:
            r = tc.get(f"/clients/{client_obj.id}/partials/drafts?status=approved&date_filter=today")
            assert r.status_code == 200
            assert str(draft_today.id) in r.text
            assert str(draft_old.id) not in r.text
        finally:
            app.dependency_overrides.clear()

    def test_date_filter_ignored_for_posted_tab(self, db):
        """date_filter is ignored for posted status (always uses 30d window)."""
        client_obj = _make_client(db)
        avatar = _make_avatar(db, client_obj.id)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)

        # Create posted draft 10 days ago
        ten_days_ago = datetime.now(timezone.utc) - timedelta(days=10)
        draft_posted = _make_draft(db, avatar.id, status="posted", created_at=ten_days_ago)

        tc = _authenticated_client(db, user)
        try:
            # Even with date_filter=today, posted tab should show 30d window
            r = tc.get(f"/clients/{client_obj.id}/partials/drafts?status=posted&date_filter=today")
            assert r.status_code == 200
            assert str(draft_posted.id) in r.text
        finally:
            app.dependency_overrides.clear()


class TestReviewPageDateUI:
    """Test that review page renders date filter UI."""

    def test_review_page_has_date_filter_chips(self, db):
        """Review page HTML contains date filter buttons."""
        client_obj = _make_client(db)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            r = tc.get(f"/clients/{client_obj.id}/review")
            assert r.status_code == 200
            assert 'id="date-filter-row"' in r.text
            assert 'id="date-today"' in r.text
            assert 'id="date-7d"' in r.text
            assert 'id="date-all"' in r.text
            assert "setDateFilter" in r.text
        finally:
            app.dependency_overrides.clear()

    def test_initial_load_uses_today_filter(self, db):
        """Initial HTMX load URL includes date_filter=today."""
        client_obj = _make_client(db)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            r = tc.get(f"/clients/{client_obj.id}/review")
            assert r.status_code == 200
            assert "date_filter=today" in r.text
        finally:
            app.dependency_overrides.clear()
