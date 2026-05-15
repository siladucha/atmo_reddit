"""Property-based tests for Query Scoping Layer.

Tests the core correctness properties of the QueryScope class:
- Property 2: Client-scoped users only see their own data
- Property 3: Owner/partner see all data (bypass scoping)
- Property 4: System context sees all data (bypass scoping)
- Property 5: Write operations to wrong client_id are rejected

Uses Hypothesis to generate random users, roles, and client_ids.
"""

import uuid
from dataclasses import dataclass
from typing import Optional

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.models.user_role import UserRole
from app.services.query_scope import QueryScope, SecurityError, system_context


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate random UUIDs for client_ids
uuid_strategy = st.uuids()

# Client-scoped roles (users bound to a single client)
CLIENT_SCOPED_ROLES = [
    UserRole.client_admin,
    UserRole.client_manager,
    UserRole.client_viewer,
    UserRole.b2c_user,
]

# Platform-wide roles (owner/partner — full access)
PLATFORM_ROLES = [UserRole.owner, UserRole.partner]

client_scoped_role_strategy = st.sampled_from(CLIENT_SCOPED_ROLES)
platform_role_strategy = st.sampled_from(PLATFORM_ROLES)
any_role_strategy = st.sampled_from(CLIENT_SCOPED_ROLES + PLATFORM_ROLES)


@dataclass
class FakeUser:
    """Minimal user object for testing QueryScope without DB dependency."""

    id: uuid.UUID
    role: str
    client_id: Optional[uuid.UUID]
    is_active: bool = True
    is_superuser: bool = False

    @property
    def user_role(self) -> UserRole:
        return UserRole(self.role)


# Strategy to generate a client-scoped user with a valid client_id
@st.composite
def client_scoped_user_strategy(draw):
    """Generate a user with a client-scoped role and a non-null client_id."""
    role = draw(client_scoped_role_strategy)
    user_id = draw(uuid_strategy)
    client_id = draw(uuid_strategy)
    return FakeUser(id=user_id, role=role.value, client_id=client_id)


# Strategy to generate a platform-wide user (owner or partner)
@st.composite
def platform_user_strategy(draw):
    """Generate a user with owner or partner role."""
    role = draw(platform_role_strategy)
    user_id = draw(uuid_strategy)
    # Platform users may or may not have a client_id (doesn't matter for scoping)
    client_id = draw(st.one_of(st.none(), uuid_strategy))
    return FakeUser(id=user_id, role=role.value, client_id=client_id)


# ---------------------------------------------------------------------------
# Property 2: Client-scoped users only see their own data
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(user=client_scoped_user_strategy())
def test_property_2_client_scoped_users_see_only_own_data(user: FakeUser):
    """**Validates: Requirements 4.1, 4.3, 4.4**

    For any client-scoped user (client_admin, client_manager, client_viewer, b2c_user)
    with client_id C, get_authorized_client_ids() returns a list containing exactly [C].
    """
    scope = QueryScope(user=user)
    authorized = scope.get_authorized_client_ids()

    # Must return a list (not None)
    assert authorized is not None, (
        f"Client-scoped user with role {user.role} should get a list, not None"
    )

    # Must contain exactly one element: the user's own client_id
    assert len(authorized) == 1, (
        f"Expected exactly 1 authorized client_id, got {len(authorized)}"
    )
    assert authorized[0] == user.client_id, (
        f"Expected client_id {user.client_id}, got {authorized[0]}"
    )


# ---------------------------------------------------------------------------
# Property 3: Owner/partner see all data
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(user=platform_user_strategy())
def test_property_3_owner_partner_see_all_data(user: FakeUser):
    """**Validates: Requirements 4.2, 4.3**

    For any owner or partner user, get_authorized_client_ids() returns None,
    indicating full access to all clients without filtering.
    """
    scope = QueryScope(user=user)
    authorized = scope.get_authorized_client_ids()

    # Must return None (no filtering — full access)
    assert authorized is None, (
        f"User with role {user.role} should get None (full access), "
        f"got {authorized}"
    )


# ---------------------------------------------------------------------------
# Property 4: System context sees all data
# ---------------------------------------------------------------------------


@settings(max_examples=50)
@given(caller_name=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N"))))
def test_property_4_system_context_sees_all_data(caller_name: str):
    """**Validates: Requirements 4.8**

    For any system_context() instance, get_authorized_client_ids() returns None,
    indicating full access to all clients without filtering.
    """
    scope = system_context(caller=caller_name)
    authorized = scope.get_authorized_client_ids()

    # System context must return None (full access)
    assert authorized is None, (
        f"System context should get None (full access), got {authorized}"
    )


@settings(max_examples=50)
@given(target_client_id=uuid_strategy)
def test_property_4_system_context_write_access_never_raises(target_client_id: uuid.UUID):
    """**Validates: Requirements 4.8**

    For any system_context() instance, assert_write_access(any_client_id) never raises,
    confirming system processes can write to any client.
    """
    scope = system_context(caller="test")
    # Should not raise for any client_id
    scope.assert_write_access(target_client_id)


# ---------------------------------------------------------------------------
# Property 5: Write operations to wrong client_id are rejected
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(user=client_scoped_user_strategy(), target_client_id=uuid_strategy)
def test_property_5_write_to_wrong_client_rejected(user: FakeUser, target_client_id: uuid.UUID):
    """**Validates: Requirements 4.9**

    For any client-scoped user with client_id C, assert_write_access(D) where D != C
    raises SecurityError.
    """
    # Ensure target is different from user's client_id
    assume(target_client_id != user.client_id)

    scope = QueryScope(user=user)

    try:
        scope.assert_write_access(target_client_id)
        # If we get here, the write was allowed — that's a violation
        assert False, (
            f"User with role {user.role} and client_id {user.client_id} "
            f"was allowed to write to client_id {target_client_id} — "
            f"should have been rejected"
        )
    except SecurityError:
        pass  # Expected — write correctly rejected


@settings(max_examples=200)
@given(user=client_scoped_user_strategy())
def test_property_5_write_to_own_client_allowed(user: FakeUser):
    """**Validates: Requirements 4.9**

    For any client-scoped user with client_id C, assert_write_access(C) does NOT raise,
    confirming users can write to their own client.
    """
    scope = QueryScope(user=user)
    # Should not raise — writing to own client is allowed
    scope.assert_write_access(user.client_id)


@settings(max_examples=200)
@given(user=platform_user_strategy(), target_client_id=uuid_strategy)
def test_property_5_owner_partner_write_to_any_client_allowed(user: FakeUser, target_client_id: uuid.UUID):
    """**Validates: Requirements 4.2, 4.9**

    For any owner or partner user, assert_write_access(any_client_id) never raises,
    confirming platform admins can write to any client.
    """
    scope = QueryScope(user=user)
    # Should not raise for any client_id
    scope.assert_write_access(target_client_id)
