"""
Comprehensive RBAC & Client Data Isolation test suite.

Covers all 8 manual testing scenarios:
1. Client creation and full setup
2. User creation and role assignment
3. Client deactivation cascade
4. Partner (Tzvi) access
5. QA (Jenny) access
6. client_admin access
7. Data isolation verification
8. Avatar Farm / Rentals

Uses the `db` fixture from conftest.py (PostgreSQL with transaction rollback).
Permission guards are tested directly (not via HTTP) since the app requires
Docker hostname "db" for full startup.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.user_role import UserRole
from app.models.client import Client
from app.models.avatar import Avatar
from app.models.avatar_rental import AvatarRental
from app.models.thread import RedditThread
from app.models.thread_score import ThreadScore
from app.models.activity_event import ActivityEvent
from app.models.comment_draft import CommentDraft
from app.models.subreddit import Subreddit, ClientSubredditAssignment
from app.services.auth import create_user, hash_password
from app.services.access_control import (
    check_avatar_limit,
    check_b2c_avatar_limit,
    can_approve_drafts,
    upgrade_b2c_to_b2b,
)
from app.services.team_management import validate_team_management, validate_user_deactivation
from app.services.query_scope import QueryScope, system_context, get_query_scope, SecurityError
from app.services.isolation import _avatar_accessible_by_client
from app.services.generation import _assert_context_isolation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(db: Session, name: str = "TestClient", **kwargs) -> Client:
    """Create a Client record with sensible defaults."""
    defaults = dict(
        client_name=name,
        brand_name=f"{name} Brand",
        is_active=True,
        max_avatars=3,
        plan_type="starter",
        draft_approval_enabled=False,
        keywords={"high": ["test"], "medium": [], "low": []},
    )
    defaults.update(kwargs)
    client = Client(**defaults)
    db.add(client)
    db.flush()
    return client


def _make_user(
    db: Session,
    email: str,
    role: UserRole,
    client_id: uuid.UUID | None = None,
    is_superuser: bool = False,
    is_active: bool = True,
) -> User:
    """Create a User record with explicit role."""
    user = User(
        email=email,
        hashed_password=hash_password("testpass123"),
        full_name=email.split("@")[0].title(),
        role=role.value,
        client_id=client_id,
        is_superuser=is_superuser,
        is_active=is_active,
    )
    db.add(user)
    db.flush()
    return user


def _make_avatar(
    db: Session,
    username: str,
    client_ids: list[str] | None = None,
    is_farm_avatar: bool = False,
    **kwargs,
) -> Avatar:
    """Create an Avatar record."""
    avatar = Avatar(
        reddit_username=username,
        client_ids=client_ids,
        active=True,
        is_farm_avatar=is_farm_avatar,
        **kwargs,
    )
    db.add(avatar)
    db.flush()
    return avatar


def _make_subreddit(db: Session, name: str) -> Subreddit:
    """Create a Subreddit record."""
    sub = Subreddit(subreddit_name=name, is_active=True)
    db.add(sub)
    db.flush()
    return sub


def _make_thread(db: Session, subreddit: Subreddit, client_id: uuid.UUID | None = None) -> RedditThread:
    """Create a RedditThread record."""
    thread = RedditThread(
        subreddit_id=subreddit.id,
        client_id=client_id,
        reddit_native_id=f"t3_{uuid.uuid4().hex[:8]}",
        subreddit=subreddit.subreddit_name,
        post_title="Test thread",
        post_body="Test body",
    )
    db.add(thread)
    db.flush()
    return thread


def _make_mock_request(user_id: str) -> MagicMock:
    """Create a mock Request with state.user_id set."""
    request = MagicMock()
    request.state.user_id = user_id
    return request


# ---------------------------------------------------------------------------
# Scenario 1: Client creation and full setup
# ---------------------------------------------------------------------------


class TestScenario1ClientCreationAndSetup:
    """Scenario 1: Client creation and full setup."""

    def test_create_client_with_all_fields(self, db: Session):
        """Create a client with all fields populated."""
        client = _make_client(
            db,
            name="XM Cyber",
            brand_name="XM Cyber",
            company_profile="Cybersecurity company",
            keywords={"high": ["xdr", "attack surface"], "medium": ["security"], "low": ["cyber"]},
            max_avatars=5,
            plan_type="growth",
        )
        assert client.id is not None
        assert client.client_name == "XM Cyber"
        assert client.brand_name == "XM Cyber"
        assert client.is_active is True
        assert client.max_avatars == 5
        assert client.plan_type == "growth"
        assert client.keywords["high"] == ["xdr", "attack surface"]

    def test_add_subreddits_to_client(self, db: Session):
        """Add subreddits to a client via ClientSubredditAssignment."""
        client = _make_client(db, name="SubClient")
        sub1 = _make_subreddit(db, f"cybersec_{uuid.uuid4().hex[:6]}")
        sub2 = _make_subreddit(db, f"netsec_{uuid.uuid4().hex[:6]}")

        assign1 = ClientSubredditAssignment(
            client_id=client.id, subreddit_id=sub1.id, type="professional"
        )
        assign2 = ClientSubredditAssignment(
            client_id=client.id, subreddit_id=sub2.id, type="professional"
        )
        db.add_all([assign1, assign2])
        db.flush()

        assignments = (
            db.query(ClientSubredditAssignment)
            .filter(ClientSubredditAssignment.client_id == client.id)
            .all()
        )
        assert len(assignments) == 2

    def test_create_avatars_for_client(self, db: Session):
        """Create avatars and verify client_ids contains client.id."""
        client = _make_client(db, name="AvatarClient")
        avatar = _make_avatar(db, "CyberExpert42", client_ids=[str(client.id)])

        assert avatar.client_ids is not None
        assert str(client.id) in avatar.client_ids

    def test_max_avatars_limit_blocks_creation(self, db: Session):
        """Verify max_avatars limit blocks creation for non-owner users."""
        client = _make_client(db, name="LimitClient", max_avatars=2)
        manager = _make_user(db, "mgr@limit.com", UserRole.client_manager, client_id=client.id)

        # Create 2 avatars (at limit)
        _make_avatar(db, "avatar_limit_1", client_ids=[str(client.id)])
        _make_avatar(db, "avatar_limit_2", client_ids=[str(client.id)])

        # Third should be blocked
        with pytest.raises(HTTPException) as exc_info:
            check_avatar_limit(db, client, manager)
        assert exc_info.value.status_code == 403
        assert "Maximum avatars reached" in exc_info.value.detail

    def test_owner_bypasses_avatar_limit(self, db: Session):
        """Verify owner bypasses the max_avatars limit."""
        client = _make_client(db, name="OwnerBypass", max_avatars=1)
        owner = _make_user(db, "owner@bypass.com", UserRole.owner, is_superuser=True)

        # Create 1 avatar (at limit)
        _make_avatar(db, "avatar_bypass_1", client_ids=[str(client.id)])

        # Owner should NOT be blocked
        check_avatar_limit(db, client, owner)  # Should not raise


# ---------------------------------------------------------------------------
# Scenario 2: User creation and role assignment
# ---------------------------------------------------------------------------


class TestScenario2UserCreationAndRoleAssignment:
    """Scenario 2: User creation and role assignment."""

    def test_owner_creates_all_roles(self, db: Session):
        """Owner can create users with all roles."""
        client = _make_client(db, name="RoleClient")
        owner = _make_user(db, "owner@roles.com", UserRole.owner, is_superuser=True)

        for target_role in [
            UserRole.client_admin,
            UserRole.client_manager,
            UserRole.client_viewer,
            UserRole.b2c_user,
        ]:
            # Should not raise
            validate_team_management(owner, target_role, client.id)

    def test_users_have_correct_role_and_client(self, db: Session):
        """Verify each created user has correct role and client_id."""
        client = _make_client(db, name="VerifyClient")

        admin = _make_user(db, "admin@verify.com", UserRole.client_admin, client_id=client.id)
        manager = _make_user(db, "mgr@verify.com", UserRole.client_manager, client_id=client.id)
        viewer = _make_user(db, "view@verify.com", UserRole.client_viewer, client_id=client.id)

        assert admin.user_role == UserRole.client_admin
        assert admin.client_id == client.id
        assert manager.user_role == UserRole.client_manager
        assert manager.client_id == client.id
        assert viewer.user_role == UserRole.client_viewer
        assert viewer.client_id == client.id

    def test_partner_can_create_users(self, db: Session):
        """Partner can also create users."""
        client = _make_client(db, name="PartnerCreate")
        partner = _make_user(db, "partner@create.com", UserRole.partner)

        # Should not raise for any role
        validate_team_management(partner, UserRole.client_admin, client.id)
        validate_team_management(partner, UserRole.client_manager, client.id)
        validate_team_management(partner, UserRole.client_viewer, client.id)

    def test_client_admin_creates_manager_and_viewer(self, db: Session):
        """client_admin can create client_manager and client_viewer within own company."""
        client = _make_client(db, name="AdminTeam")
        admin = _make_user(db, "admin@team.com", UserRole.client_admin, client_id=client.id)

        # Should not raise
        validate_team_management(admin, UserRole.client_manager, client.id)
        validate_team_management(admin, UserRole.client_viewer, client.id)

    def test_client_admin_cannot_create_client_admin(self, db: Session):
        """client_admin CANNOT create another client_admin."""
        client = _make_client(db, name="NoAdminCreate")
        admin = _make_user(db, "admin@noadmin.com", UserRole.client_admin, client_id=client.id)

        with pytest.raises(HTTPException) as exc_info:
            validate_team_management(admin, UserRole.client_admin, client.id)
        assert exc_info.value.status_code == 403

    def test_client_manager_cannot_create_users(self, db: Session):
        """client_manager CANNOT create users at all."""
        client = _make_client(db, name="NoMgrCreate")
        manager = _make_user(db, "mgr@nocreate.com", UserRole.client_manager, client_id=client.id)

        for target_role in [UserRole.client_manager, UserRole.client_viewer]:
            with pytest.raises(HTTPException) as exc_info:
                validate_team_management(manager, target_role, client.id)
            assert exc_info.value.status_code == 403

    def test_client_admin_cannot_manage_other_company(self, db: Session):
        """client_admin cannot manage users in another company."""
        client_a = _make_client(db, name="CompanyA")
        client_b = _make_client(db, name="CompanyB")
        admin_a = _make_user(db, "admin@a.com", UserRole.client_admin, client_id=client_a.id)

        with pytest.raises(HTTPException) as exc_info:
            validate_team_management(admin_a, UserRole.client_manager, client_b.id)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Scenario 3: Client deactivation cascade
# ---------------------------------------------------------------------------


class TestScenario3ClientDeactivationCascade:
    """Scenario 3: Client deactivation cascade."""

    def _simulate_get_current_user(self, db: Session, user: User) -> User:
        """Simulate get_current_user logic for a user.

        Checks is_active and client deactivation cascade.
        Returns user or raises HTTPException.
        """
        if not user.is_active:
            raise HTTPException(status_code=303, headers={"Location": "/login"})

        if user.user_role.is_client_scoped and user.client_id:
            client = db.query(Client).filter(Client.id == user.client_id).first()
            if not client or not client.is_active:
                raise HTTPException(status_code=403, detail="Access Denied")

        return user

    def test_active_client_users_can_authenticate(self, db: Session):
        """All users of an active client can authenticate."""
        client = _make_client(db, name="ActiveClient")
        admin = _make_user(db, "admin@active.com", UserRole.client_admin, client_id=client.id)
        manager = _make_user(db, "mgr@active.com", UserRole.client_manager, client_id=client.id)
        viewer = _make_user(db, "view@active.com", UserRole.client_viewer, client_id=client.id)

        # All should pass
        assert self._simulate_get_current_user(db, admin) == admin
        assert self._simulate_get_current_user(db, manager) == manager
        assert self._simulate_get_current_user(db, viewer) == viewer

    def test_deactivated_client_blocks_all_users(self, db: Session):
        """Deactivating client blocks all client-scoped users with 403."""
        client = _make_client(db, name="DeactivateClient")
        admin = _make_user(db, "admin@deact.com", UserRole.client_admin, client_id=client.id)
        manager = _make_user(db, "mgr@deact.com", UserRole.client_manager, client_id=client.id)
        viewer = _make_user(db, "view@deact.com", UserRole.client_viewer, client_id=client.id)

        # Deactivate client
        client.is_active = False
        db.flush()

        # All client-scoped users should get 403
        for user in [admin, manager, viewer]:
            with pytest.raises(HTTPException) as exc_info:
                self._simulate_get_current_user(db, user)
            assert exc_info.value.status_code == 403

    def test_owner_partner_still_have_access_after_deactivation(self, db: Session):
        """Owner/partner still have access when a client is deactivated."""
        client = _make_client(db, name="StillAccess")
        owner = _make_user(db, "owner@still.com", UserRole.owner, is_superuser=True)
        partner = _make_user(db, "partner@still.com", UserRole.partner)

        # Deactivate client
        client.is_active = False
        db.flush()

        # Owner and partner are NOT client-scoped, so they pass
        assert self._simulate_get_current_user(db, owner) == owner
        assert self._simulate_get_current_user(db, partner) == partner

    def test_reactivate_client_restores_access(self, db: Session):
        """Reactivating client restores user access."""
        client = _make_client(db, name="Reactivate")
        manager = _make_user(db, "mgr@react.com", UserRole.client_manager, client_id=client.id)

        # Deactivate
        client.is_active = False
        db.flush()

        with pytest.raises(HTTPException):
            self._simulate_get_current_user(db, manager)

        # Reactivate
        client.is_active = True
        db.flush()

        # Should pass again
        assert self._simulate_get_current_user(db, manager) == manager


# ---------------------------------------------------------------------------
# Scenario 4: Tzvi (partner) access
# ---------------------------------------------------------------------------


class TestScenario4PartnerAccess:
    """Scenario 4: Partner (Tzvi) access patterns."""

    def test_partner_role_properties(self, db: Session):
        """Partner has correct permission properties."""
        partner = _make_user(db, "tzvi@partner.com", UserRole.partner)
        role = partner.user_role

        assert role.is_admin_level is True
        assert role.can_manage_clients is True
        assert role.can_manage_users is True
        assert role.can_manage_avatars is True
        assert role.can_view_all_clients is True
        assert role.can_trigger_pipeline is True
        assert role.can_review is True
        assert role.is_client_scoped is False

    def test_partner_cannot_manage_system_settings(self, db: Session):
        """Partner CANNOT access system settings (require_owner -> 403)."""
        partner = _make_user(db, "tzvi@nosys.com", UserRole.partner)

        # can_manage_system is owner-only
        assert partner.user_role.can_manage_system is False

    def test_partner_sees_all_clients_data(self, db: Session):
        """Partner can see all clients' data (no scoping)."""
        client_a = _make_client(db, name="PartnerViewA")
        client_b = _make_client(db, name="PartnerViewB")
        partner = _make_user(db, "tzvi@viewall.com", UserRole.partner)

        scope = get_query_scope(partner)
        authorized = scope.get_authorized_client_ids()

        # None means full access (no filtering)
        assert authorized is None

    def test_partner_can_create_deactivate_any_user(self, db: Session):
        """Partner can create/deactivate any user."""
        client = _make_client(db, name="PartnerManage")
        partner = _make_user(db, "tzvi@manage.com", UserRole.partner)

        # Can create any role
        for role in [UserRole.client_admin, UserRole.client_manager, UserRole.client_viewer, UserRole.b2c_user]:
            validate_team_management(partner, role, client.id)

        # Can deactivate any user
        target = _make_user(db, "target@deact.com", UserRole.client_admin, client_id=client.id)
        validate_user_deactivation(partner, target)  # Should not raise

    def test_partner_query_scope_no_filtering(self, db: Session):
        """Partner QueryScope returns unfiltered queries."""
        client_a = _make_client(db, name="ScopeA")
        client_b = _make_client(db, name="ScopeB")
        partner = _make_user(db, "tzvi@scope.com", UserRole.partner)

        # Create activity events for both clients
        ev_a = ActivityEvent(client_id=client_a.id, event_type="test", message="Event A")
        ev_b = ActivityEvent(client_id=client_b.id, event_type="test", message="Event B")
        db.add_all([ev_a, ev_b])
        db.flush()

        scope = get_query_scope(partner)
        query = db.query(ActivityEvent)
        scoped = scope.scope_query(query, ActivityEvent)

        results = scoped.all()
        client_ids_in_results = {r.client_id for r in results}
        assert client_a.id in client_ids_in_results
        assert client_b.id in client_ids_in_results


# ---------------------------------------------------------------------------
# Scenario 5: Jenny (qa) access
# ---------------------------------------------------------------------------


class TestScenario5QAAccess:
    """Scenario 5: QA (Jenny) access patterns."""

    def test_qa_role_properties(self, db: Session):
        """QA has correct permission properties."""
        qa = _make_user(db, "jenny@qa.com", UserRole.qa)
        role = qa.user_role

        assert role.can_view_all_clients is True
        assert role.can_review is True
        assert role.can_manage_system is False
        assert role.can_manage_users is False
        assert role.can_trigger_pipeline is False
        assert role.is_admin_level is False
        assert role.is_internal is True
        assert role.is_client_scoped is False

    def test_qa_can_view_all_clients_property(self, db: Session):
        """QA has can_view_all_clients=True (access enforced at route level, not QueryScope).

        Note: QueryScope only grants unfiltered access to owner/partner.
        QA's cross-client access is enforced at the route/dependency level,
        not via QueryScope.get_authorized_client_ids().
        """
        qa = _make_user(db, "jenny@viewall.com", UserRole.qa)
        assert qa.user_role.can_view_all_clients is True
        assert qa.user_role.is_internal is True

    def test_qa_cannot_manage_users(self, db: Session):
        """QA CANNOT manage users."""
        client = _make_client(db, name="QANoManage")
        qa = _make_user(db, "jenny@nomanage.com", UserRole.qa)

        with pytest.raises(HTTPException) as exc_info:
            validate_team_management(qa, UserRole.client_viewer, client.id)
        assert exc_info.value.status_code == 403

    def test_qa_cannot_trigger_pipeline(self, db: Session):
        """QA CANNOT trigger pipeline."""
        qa = _make_user(db, "jenny@nopipe.com", UserRole.qa)
        assert qa.user_role.can_trigger_pipeline is False

    def test_qa_cannot_access_admin_panel(self, db: Session):
        """QA CANNOT access admin panel (is_admin_level = False)."""
        qa = _make_user(db, "jenny@noadmin.com", UserRole.qa)
        assert qa.user_role.is_admin_level is False

    def test_qa_can_warm_avatars(self, db: Session):
        """QA can warm own avatars (farm)."""
        qa = _make_user(db, "jenny@warm.com", UserRole.qa)
        assert qa.user_role.can_warm_avatars is True


# ---------------------------------------------------------------------------
# Scenario 6: client_admin access
# ---------------------------------------------------------------------------


class TestScenario6ClientAdminAccess:
    """Scenario 6: client_admin access patterns."""

    def test_client_admin_scoped_to_own_client(self, db: Session):
        """client_admin can only see own client's data."""
        client_a = _make_client(db, name="AdminClientA")
        client_b = _make_client(db, name="AdminClientB")
        admin_a = _make_user(db, "admin@a.com", UserRole.client_admin, client_id=client_a.id)

        scope = get_query_scope(admin_a)
        authorized = scope.get_authorized_client_ids()

        assert authorized == [client_a.id]
        assert client_b.id not in authorized

    def test_client_admin_cannot_see_other_clients_events(self, db: Session):
        """client_admin CANNOT see other clients' activity events."""
        client_a = _make_client(db, name="EventClientA")
        client_b = _make_client(db, name="EventClientB")
        admin_a = _make_user(db, "admin@eventa.com", UserRole.client_admin, client_id=client_a.id)

        ev_a = ActivityEvent(client_id=client_a.id, event_type="test", message="A event")
        ev_b = ActivityEvent(client_id=client_b.id, event_type="test", message="B event")
        db.add_all([ev_a, ev_b])
        db.flush()

        scope = get_query_scope(admin_a)
        query = db.query(ActivityEvent)
        scoped = scope.scope_query(query, ActivityEvent)
        results = scoped.all()

        result_client_ids = {r.client_id for r in results}
        assert client_a.id in result_client_ids
        assert client_b.id not in result_client_ids

    def test_client_admin_cannot_see_other_clients_avatars(self, db: Session):
        """client_admin CANNOT see other clients' avatars."""
        client_a = _make_client(db, name="AvatarClientA")
        client_b = _make_client(db, name="AvatarClientB")
        admin_a = _make_user(db, "admin@avatara.com", UserRole.client_admin, client_id=client_a.id)

        avatar_a = _make_avatar(db, "avatar_a_only", client_ids=[str(client_a.id)])
        avatar_b = _make_avatar(db, "avatar_b_only", client_ids=[str(client_b.id)])

        scope = get_query_scope(admin_a)
        query = db.query(Avatar)
        scoped = scope.scope_query(query, Avatar)
        results = scoped.all()

        result_ids = {r.id for r in results}
        assert avatar_a.id in result_ids
        assert avatar_b.id not in result_ids

    def test_client_admin_can_manage_team(self, db: Session):
        """client_admin CAN manage team (create client_manager/viewer in own company)."""
        client = _make_client(db, name="TeamClient")
        admin = _make_user(db, "admin@team2.com", UserRole.client_admin, client_id=client.id)

        assert admin.user_role.can_manage_team is True
        validate_team_management(admin, UserRole.client_manager, client.id)
        validate_team_management(admin, UserRole.client_viewer, client.id)

    def test_client_admin_cannot_create_client_admin(self, db: Session):
        """client_admin CANNOT create client_admin."""
        client = _make_client(db, name="NoAdminTeam")
        admin = _make_user(db, "admin@noadminteam.com", UserRole.client_admin, client_id=client.id)

        with pytest.raises(HTTPException) as exc_info:
            validate_team_management(admin, UserRole.client_admin, client.id)
        assert exc_info.value.status_code == 403

    def test_client_admin_write_access_own_client(self, db: Session):
        """client_admin can write to own client."""
        client = _make_client(db, name="WriteClient")
        admin = _make_user(db, "admin@write.com", UserRole.client_admin, client_id=client.id)

        scope = get_query_scope(admin)
        scope.assert_write_access(client.id)  # Should not raise

    def test_client_admin_cannot_write_other_client(self, db: Session):
        """client_admin CANNOT write to another client."""
        client_a = _make_client(db, name="WriteA")
        client_b = _make_client(db, name="WriteB")
        admin_a = _make_user(db, "admin@writea.com", UserRole.client_admin, client_id=client_a.id)

        scope = get_query_scope(admin_a)
        with pytest.raises(SecurityError):
            scope.assert_write_access(client_b.id)


# ---------------------------------------------------------------------------
# Scenario 7: Data isolation verification
# ---------------------------------------------------------------------------


class TestScenario7DataIsolation:
    """Scenario 7: Data isolation verification across clients."""

    def test_client_manager_sees_only_own_data(self, db: Session):
        """client_manager of A queries -> sees only A's data."""
        client_a = _make_client(db, name="IsoClientA")
        client_b = _make_client(db, name="IsoClientB")
        manager_a = _make_user(db, "mgr@isoa.com", UserRole.client_manager, client_id=client_a.id)

        # Create events for both
        ev_a = ActivityEvent(client_id=client_a.id, event_type="test", message="A")
        ev_b = ActivityEvent(client_id=client_b.id, event_type="test", message="B")
        db.add_all([ev_a, ev_b])
        db.flush()

        scope = get_query_scope(manager_a)
        results = scope.scope_query(db.query(ActivityEvent), ActivityEvent).all()

        assert all(r.client_id == client_a.id for r in results)
        assert not any(r.client_id == client_b.id for r in results)

    def test_client_manager_does_not_see_other_clients_drafts(self, db: Session):
        """client_manager of A does NOT see B's drafts."""
        client_a = _make_client(db, name="DraftIsoA")
        client_b = _make_client(db, name="DraftIsoB")
        manager_a = _make_user(db, "mgr@draftisoa.com", UserRole.client_manager, client_id=client_a.id)

        sub = _make_subreddit(db, "testsub_iso")
        thread = _make_thread(db, sub)
        avatar_a = _make_avatar(db, "iso_avatar_a", client_ids=[str(client_a.id)])
        avatar_b = _make_avatar(db, "iso_avatar_b", client_ids=[str(client_b.id)])

        draft_a = CommentDraft(
            thread_id=thread.id, client_id=client_a.id, avatar_id=avatar_a.id,
            ai_draft="Draft for A", status="pending",
        )
        draft_b = CommentDraft(
            thread_id=thread.id, client_id=client_b.id, avatar_id=avatar_b.id,
            ai_draft="Draft for B", status="pending",
        )
        db.add_all([draft_a, draft_b])
        db.flush()

        scope = get_query_scope(manager_a)
        results = scope.scope_query(db.query(CommentDraft), CommentDraft).all()

        result_client_ids = {r.client_id for r in results}
        assert client_a.id in result_client_ids
        assert client_b.id not in result_client_ids

    def test_client_manager_does_not_see_other_clients_threads(self, db: Session):
        """client_manager of A does NOT see B's threads (via ThreadScore scoping)."""
        client_a = _make_client(db, name="ThreadIsoA")
        client_b = _make_client(db, name="ThreadIsoB")
        manager_a = _make_user(db, "mgr@threadisoa.com", UserRole.client_manager, client_id=client_a.id)

        sub = _make_subreddit(db, "threadsub_iso")
        thread_a = _make_thread(db, sub)
        thread_b = _make_thread(db, sub)

        # Create ThreadScores linking threads to clients
        score_a = ThreadScore(thread_id=thread_a.id, client_id=client_a.id, tag="engage")
        score_b = ThreadScore(thread_id=thread_b.id, client_id=client_b.id, tag="engage")
        db.add_all([score_a, score_b])
        db.flush()

        scope = get_query_scope(manager_a)
        results = scope.scope_query(db.query(RedditThread), RedditThread).all()

        result_ids = {r.id for r in results}
        assert thread_a.id in result_ids
        assert thread_b.id not in result_ids

    def test_owner_sees_all_data(self, db: Session):
        """Owner queries -> sees both A and B data."""
        client_a = _make_client(db, name="OwnerSeeA")
        client_b = _make_client(db, name="OwnerSeeB")
        owner = _make_user(db, "owner@seeall.com", UserRole.owner, is_superuser=True)

        ev_a = ActivityEvent(client_id=client_a.id, event_type="test", message="A")
        ev_b = ActivityEvent(client_id=client_b.id, event_type="test", message="B")
        db.add_all([ev_a, ev_b])
        db.flush()

        scope = get_query_scope(owner)
        results = scope.scope_query(db.query(ActivityEvent), ActivityEvent).all()

        client_ids_in_results = {r.client_id for r in results}
        assert client_a.id in client_ids_in_results
        assert client_b.id in client_ids_in_results

    def test_context_isolation_passes_for_correct_data(self, db: Session):
        """_assert_context_isolation passes when all data belongs to correct client."""
        client = _make_client(db, name="ContextOK")
        avatar = _make_avatar(db, "ctx_ok_avatar", client_ids=[str(client.id)])

        # Mock strategy, examples, patterns with correct client_id
        strategy = MagicMock()
        strategy.id = uuid.uuid4()

        example = MagicMock()
        example.id = uuid.uuid4()
        example.client_id = client.id

        pattern = MagicMock()
        pattern.id = uuid.uuid4()
        pattern.client_id = client.id

        # Should not raise
        _assert_context_isolation(client, avatar, strategy, [example], [pattern])

    def test_context_isolation_fails_for_cross_client(self, db: Session):
        """_assert_context_isolation fails for cross-client data."""
        client_a = _make_client(db, name="ContextA")
        client_b = _make_client(db, name="ContextB")
        avatar = _make_avatar(db, "ctx_cross_avatar", client_ids=[str(client_a.id)])

        # Example belongs to client_b (wrong!)
        example = MagicMock()
        example.id = uuid.uuid4()
        example.client_id = client_b.id

        with pytest.raises(RuntimeError, match="Context isolation violation"):
            _assert_context_isolation(client_a, avatar, None, [example], [])

    def test_context_isolation_fails_for_wrong_pattern(self, db: Session):
        """_assert_context_isolation fails when pattern belongs to wrong client."""
        client_a = _make_client(db, name="PatternA")
        client_b = _make_client(db, name="PatternB")
        avatar = _make_avatar(db, "ctx_pat_avatar", client_ids=[str(client_a.id)])

        pattern = MagicMock()
        pattern.id = uuid.uuid4()
        pattern.client_id = client_b.id

        with pytest.raises(RuntimeError, match="Context isolation violation"):
            _assert_context_isolation(client_a, avatar, None, [], [pattern])

    def test_context_isolation_fails_for_wrong_avatar(self, db: Session):
        """_assert_context_isolation fails when avatar doesn't belong to client."""
        client_a = _make_client(db, name="AvatarWrongA")
        client_b = _make_client(db, name="AvatarWrongB")
        # Avatar belongs to client_b, not client_a
        avatar = _make_avatar(db, "ctx_wrong_avatar", client_ids=[str(client_b.id)])

        strategy = MagicMock()
        strategy.id = uuid.uuid4()

        with pytest.raises(RuntimeError, match="Context isolation violation"):
            _assert_context_isolation(client_a, avatar, strategy, [], [])


# ---------------------------------------------------------------------------
# Scenario 8: Avatar Farm / Rentals
# ---------------------------------------------------------------------------


class TestScenario8AvatarFarmRentals:
    """Scenario 8: Avatar Farm / Rentals."""

    def test_create_farm_avatar(self, db: Session):
        """Create farm avatar (is_farm_avatar=True)."""
        avatar = _make_avatar(db, "farm_avatar_1", is_farm_avatar=True, rent_price=199.00)
        assert avatar.is_farm_avatar is True
        assert float(avatar.rent_price) == 199.00

    def test_active_rental_makes_avatar_visible(self, db: Session):
        """ClientA user sees the farm avatar via QueryScope when rental is active."""
        client_a = _make_client(db, name="RentalClientA")
        client_b = _make_client(db, name="RentalClientB")
        manager_a = _make_user(db, "mgr@rentala.com", UserRole.client_manager, client_id=client_a.id)

        # Farm avatar not owned by anyone
        farm_avatar = _make_avatar(db, "farm_rental_avatar", client_ids=[], is_farm_avatar=True)

        # Create active rental for ClientA
        rental = AvatarRental(
            avatar_id=farm_avatar.id,
            client_id=client_a.id,
            is_active=True,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            price=199.00,
        )
        db.add(rental)
        db.flush()

        # ClientA should see the farm avatar
        scope = get_query_scope(manager_a)
        results = scope.scope_query(db.query(Avatar), Avatar).all()
        result_ids = {r.id for r in results}
        assert farm_avatar.id in result_ids

    def test_client_b_does_not_see_client_a_rental(self, db: Session):
        """ClientB user does NOT see the farm avatar rented to ClientA."""
        client_a = _make_client(db, name="RentalOnlyA")
        client_b = _make_client(db, name="RentalOnlyB")
        manager_b = _make_user(db, "mgr@rentalb.com", UserRole.client_manager, client_id=client_b.id)

        farm_avatar = _make_avatar(db, "farm_only_a", client_ids=[], is_farm_avatar=True)

        # Rental only for ClientA
        rental = AvatarRental(
            avatar_id=farm_avatar.id,
            client_id=client_a.id,
            is_active=True,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(rental)
        db.flush()

        # ClientB should NOT see it
        scope = get_query_scope(manager_b)
        results = scope.scope_query(db.query(Avatar), Avatar).all()
        result_ids = {r.id for r in results}
        assert farm_avatar.id not in result_ids

    def test_expired_rental_hides_avatar(self, db: Session):
        """Expired rental -> ClientA no longer sees the avatar."""
        client_a = _make_client(db, name="ExpiredRentalA")
        manager_a = _make_user(db, "mgr@expired.com", UserRole.client_manager, client_id=client_a.id)

        farm_avatar = _make_avatar(db, "farm_expired", client_ids=[], is_farm_avatar=True)

        # Expired rental
        rental = AvatarRental(
            avatar_id=farm_avatar.id,
            client_id=client_a.id,
            is_active=True,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),  # expired yesterday
        )
        db.add(rental)
        db.flush()

        scope = get_query_scope(manager_a)
        results = scope.scope_query(db.query(Avatar), Avatar).all()
        result_ids = {r.id for r in results}
        assert farm_avatar.id not in result_ids

    def test_deactivated_rental_hides_avatar(self, db: Session):
        """Deactivated rental -> ClientA no longer sees the avatar."""
        client_a = _make_client(db, name="DeactRentalA")
        manager_a = _make_user(db, "mgr@deactrental.com", UserRole.client_manager, client_id=client_a.id)

        farm_avatar = _make_avatar(db, "farm_deact", client_ids=[], is_farm_avatar=True)

        # Deactivated rental (is_active=False)
        rental = AvatarRental(
            avatar_id=farm_avatar.id,
            client_id=client_a.id,
            is_active=False,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(rental)
        db.flush()

        scope = get_query_scope(manager_a)
        results = scope.scope_query(db.query(Avatar), Avatar).all()
        result_ids = {r.id for r in results}
        assert farm_avatar.id not in result_ids

    def test_owner_sees_all_avatars_regardless(self, db: Session):
        """Owner sees all avatars regardless of rental status."""
        client_a = _make_client(db, name="OwnerSeesAll")
        owner = _make_user(db, "owner@seesall.com", UserRole.owner, is_superuser=True)

        farm_avatar = _make_avatar(db, "farm_owner_sees", client_ids=[], is_farm_avatar=True)
        owned_avatar = _make_avatar(db, "owned_by_a", client_ids=[str(client_a.id)])

        scope = get_query_scope(owner)
        results = scope.scope_query(db.query(Avatar), Avatar).all()
        result_ids = {r.id for r in results}

        assert farm_avatar.id in result_ids
        assert owned_avatar.id in result_ids

    def test_avatar_accessible_by_client_via_ownership(self, db: Session):
        """_avatar_accessible_by_client returns True for owned avatar."""
        client = _make_client(db, name="AccessOwned")
        avatar = _make_avatar(db, "access_owned", client_ids=[str(client.id)])

        assert _avatar_accessible_by_client(db, avatar, client) is True

    def test_avatar_accessible_by_client_via_rental(self, db: Session):
        """_avatar_accessible_by_client returns True for actively rented avatar."""
        client = _make_client(db, name="AccessRented")
        avatar = _make_avatar(db, "access_rented", client_ids=[], is_farm_avatar=True)

        rental = AvatarRental(
            avatar_id=avatar.id,
            client_id=client.id,
            is_active=True,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(rental)
        db.flush()

        assert _avatar_accessible_by_client(db, avatar, client) is True

    def test_avatar_not_accessible_without_ownership_or_rental(self, db: Session):
        """_avatar_accessible_by_client returns False when no ownership or rental."""
        client = _make_client(db, name="NoAccess")
        avatar = _make_avatar(db, "no_access_avatar", client_ids=[], is_farm_avatar=True)

        assert _avatar_accessible_by_client(db, avatar, client) is False

    def test_avatar_not_accessible_with_expired_rental(self, db: Session):
        """_avatar_accessible_by_client returns False for expired rental."""
        client = _make_client(db, name="ExpiredAccess")
        avatar = _make_avatar(db, "expired_access", client_ids=[], is_farm_avatar=True)

        rental = AvatarRental(
            avatar_id=avatar.id,
            client_id=client.id,
            is_active=True,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.add(rental)
        db.flush()

        assert _avatar_accessible_by_client(db, avatar, client) is False

    def test_avatar_not_accessible_with_inactive_rental(self, db: Session):
        """_avatar_accessible_by_client returns False for inactive rental."""
        client = _make_client(db, name="InactiveAccess")
        avatar = _make_avatar(db, "inactive_access", client_ids=[], is_farm_avatar=True)

        rental = AvatarRental(
            avatar_id=avatar.id,
            client_id=client.id,
            is_active=False,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(rental)
        db.flush()

        assert _avatar_accessible_by_client(db, avatar, client) is False
