"""Cross-client data isolation tests.

Validates that the RBAC system enforces strict client boundaries:
- Task 12.1: API endpoint isolation (client_manager, client_admin, client_viewer, owner)
- Task 12.2: LLM context isolation integration test
- Task 12.3: Avatar rental isolation tests
- Task 12.4: B2C avatar limit test
- Task 12.5: Runtime assertion failure test

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 9.10, 9.11
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.activity_event import ActivityEvent
from app.models.avatar import Avatar
from app.models.avatar_rental import AvatarRental
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.correction_pattern import CorrectionPattern
from app.models.edit_record import EditRecord
from app.models.strategy_document import StrategyDocument
from app.models.subreddit import Subreddit
from app.models.thread import RedditThread
from app.models.thread_score import ThreadScore
from app.models.user import User
from app.models.user_role import UserRole
from app.services.query_scope import QueryScope
from app.services.isolation import _avatar_accessible_by_client
from app.services.access_control import check_b2c_avatar_limit
from app.services.generation import _assert_context_isolation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(db, name: str = "Client", **kwargs) -> Client:
    """Create a client record with sensible defaults."""
    defaults = {
        "client_name": f"{name}-{uuid.uuid4().hex[:6]}",
        "brand_name": f"Brand-{uuid.uuid4().hex[:6]}",
        "is_active": True,
    }
    defaults.update(kwargs)
    client = Client(**defaults)
    db.add(client)
    db.flush()
    return client


def _make_user(
    db, client: Client, role: UserRole = UserRole.client_manager
) -> User:
    """Create a user scoped to a client with the given role."""
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


def _make_owner(db) -> User:
    """Create a platform owner user (no client_id)."""
    user = User(
        email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        full_name="Platform Owner",
        is_active=True,
        is_superuser=True,
        role=UserRole.owner.value,
        client_id=None,
    )
    db.add(user)
    db.flush()
    return user


def _make_avatar(db, client_ids: list[str] | None = None, **kwargs) -> Avatar:
    """Create an avatar with given client_ids."""
    defaults = {
        "reddit_username": f"avatar_{uuid.uuid4().hex[:8]}",
        "active": True,
        "client_ids": client_ids,
    }
    defaults.update(kwargs)
    avatar = Avatar(**defaults)
    db.add(avatar)
    db.flush()
    return avatar


def _make_subreddit(db) -> Subreddit:
    """Create a subreddit record."""
    sub = Subreddit(
        subreddit_name=f"r/test_{uuid.uuid4().hex[:8]}",
        is_active=True,
    )
    db.add(sub)
    db.flush()
    return sub


def _make_thread(db, subreddit: Subreddit, client: Client | None = None) -> RedditThread:
    """Create a RedditThread record."""
    thread = RedditThread(
        subreddit_id=subreddit.id,
        client_id=client.id if client else None,
        reddit_native_id=f"t3_{uuid.uuid4().hex[:8]}",
        subreddit=subreddit.subreddit_name,
        post_title=f"Test post {uuid.uuid4().hex[:6]}",
        post_body="Test body content",
    )
    db.add(thread)
    db.flush()
    return thread


def _make_thread_score(db, thread: RedditThread, client: Client) -> ThreadScore:
    """Create a ThreadScore linking a thread to a client."""
    score = ThreadScore(
        thread_id=thread.id,
        client_id=client.id,
        tag="engage",
        relevance=8,
        quality=7,
        strategic=6,
        composite=21,
    )
    db.add(score)
    db.flush()
    return score


def _make_comment_draft(
    db, thread: RedditThread, avatar: Avatar, client: Client
) -> CommentDraft:
    """Create a CommentDraft for a given client."""
    draft = CommentDraft(
        thread_id=thread.id,
        avatar_id=avatar.id,
        client_id=client.id,
        ai_draft="Test AI draft content",
        status="pending",
    )
    db.add(draft)
    db.flush()
    return draft


def _make_activity_event(db, client: Client) -> ActivityEvent:
    """Create an ActivityEvent for a given client."""
    event = ActivityEvent(
        client_id=client.id,
        event_type="test_event",
        message=f"Test event for {client.client_name}",
    )
    db.add(event)
    db.flush()
    return event


def _make_edit_record(
    db, avatar: Avatar, client: Client, draft: CommentDraft, subreddit: str = "r/test"
) -> EditRecord:
    """Create an EditRecord for a given client."""
    record = EditRecord(
        comment_draft_id=draft.id,
        avatar_id=avatar.id,
        client_id=client.id,
        ai_draft="Original AI draft",
        edited_draft="Human edited draft",
        edit_summary="Made it shorter",
        subreddit=subreddit,
        engagement_mode="reframe_drop",
        post_title="Test post",
        final_status="approved",
    )
    db.add(record)
    db.flush()
    return record


def _make_correction_pattern(
    db, avatar: Avatar, client: Client
) -> CorrectionPattern:
    """Create a CorrectionPattern for a given client."""
    pattern = CorrectionPattern(
        avatar_id=avatar.id,
        client_id=client.id,
        pattern_type="tone_shift",
        rule_text="Be more casual",
        frequency=3,
        last_seen_at=datetime.now(timezone.utc),
    )
    db.add(pattern)
    db.flush()
    return pattern


def _make_strategy_document(db, avatar: Avatar) -> StrategyDocument:
    """Create a StrategyDocument for a given avatar."""
    doc = StrategyDocument(
        avatar_id=avatar.id,
        goals={"primary": "brand awareness"},
        subreddit_priorities={"r/test": "high"},
        tone_guidelines={"style": "casual"},
        cadence_rules={"max_per_day": 3},
        hook_inventory={"hooks": ["question", "story"]},
        document_md="# Strategy\nBe helpful.",
        version=1,
        is_current=True,
        is_approved=True,
    )
    db.add(doc)
    db.flush()
    return doc


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


def _get_scoped_results(db, user: User, model, query=None):
    """Run a scoped query and return results."""
    scope = QueryScope(user=user)
    if query is None:
        query = select(model)
    scoped_query = scope.scope_query(query, model)
    result = db.execute(scoped_query)
    return list(result.scalars().all())



# ===========================================================================
# Task 12.1: Cross-client isolation tests for API endpoints
# Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.7, 9.8
# ===========================================================================


class TestCrossClientIsolationClientManager:
    """Test that client_manager of Client_A cannot access Client_B's data."""

    def test_client_manager_cannot_access_other_clients_comment_drafts(self, db):
        """Validates: Requirement 9.1

        client_manager of A cannot see B's CommentDrafts via QueryScope.
        """
        # Setup: two clients with data
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        user_a = _make_user(db, client_a, UserRole.client_manager)

        subreddit = _make_subreddit(db)
        avatar_a = _make_avatar(db, client_ids=[str(client_a.id)])
        avatar_b = _make_avatar(db, client_ids=[str(client_b.id)])
        thread = _make_thread(db, subreddit)

        draft_a = _make_comment_draft(db, thread, avatar_a, client_a)
        draft_b = _make_comment_draft(db, thread, avatar_b, client_b)

        # Act: user_a queries CommentDrafts
        results = _get_scoped_results(db, user_a, CommentDraft)

        # Assert: only sees own client's drafts
        result_ids = [r.id for r in results]
        assert draft_a.id in result_ids
        assert draft_b.id not in result_ids

    def test_client_manager_cannot_access_other_clients_reddit_threads(self, db):
        """Validates: Requirement 9.2

        client_manager of A cannot see B's RedditThreads (via ThreadScore scoping).
        """
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        user_a = _make_user(db, client_a, UserRole.client_manager)

        subreddit = _make_subreddit(db)
        thread_a = _make_thread(db, subreddit)
        thread_b = _make_thread(db, subreddit)

        # Create ThreadScores to link threads to clients
        _make_thread_score(db, thread_a, client_a)
        _make_thread_score(db, thread_b, client_b)

        # Act: user_a queries RedditThreads
        results = _get_scoped_results(db, user_a, RedditThread)

        # Assert: only sees threads scored for own client
        result_ids = [r.id for r in results]
        assert thread_a.id in result_ids
        assert thread_b.id not in result_ids

    def test_client_manager_cannot_access_other_clients_avatars(self, db):
        """Validates: Requirement 9.3

        client_manager of A cannot see B's Avatars.
        """
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        user_a = _make_user(db, client_a, UserRole.client_manager)

        avatar_a = _make_avatar(db, client_ids=[str(client_a.id)])
        avatar_b = _make_avatar(db, client_ids=[str(client_b.id)])

        # Act
        results = _get_scoped_results(db, user_a, Avatar)

        # Assert
        result_ids = [r.id for r in results]
        assert avatar_a.id in result_ids
        assert avatar_b.id not in result_ids

    def test_client_manager_cannot_access_other_clients_activity_events(self, db):
        """Validates: Requirement 9.4

        client_manager of A cannot see B's ActivityEvents.
        """
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        user_a = _make_user(db, client_a, UserRole.client_manager)

        event_a = _make_activity_event(db, client_a)
        event_b = _make_activity_event(db, client_b)

        # Act
        results = _get_scoped_results(db, user_a, ActivityEvent)

        # Assert
        result_ids = [r.id for r in results]
        assert event_a.id in result_ids
        assert event_b.id not in result_ids


class TestCrossClientIsolationClientAdmin:
    """Test that client_admin of Client_A cannot access Client_B's data.

    Validates: Requirement 9.5
    """

    def test_client_admin_cannot_access_other_clients_comment_drafts(self, db):
        """client_admin of A cannot see B's CommentDrafts."""
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        user_a = _make_user(db, client_a, UserRole.client_admin)

        subreddit = _make_subreddit(db)
        avatar_a = _make_avatar(db, client_ids=[str(client_a.id)])
        avatar_b = _make_avatar(db, client_ids=[str(client_b.id)])
        thread = _make_thread(db, subreddit)

        draft_a = _make_comment_draft(db, thread, avatar_a, client_a)
        draft_b = _make_comment_draft(db, thread, avatar_b, client_b)

        results = _get_scoped_results(db, user_a, CommentDraft)
        result_ids = [r.id for r in results]
        assert draft_a.id in result_ids
        assert draft_b.id not in result_ids

    def test_client_admin_cannot_access_other_clients_avatars(self, db):
        """client_admin of A cannot see B's Avatars."""
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        user_a = _make_user(db, client_a, UserRole.client_admin)

        avatar_a = _make_avatar(db, client_ids=[str(client_a.id)])
        avatar_b = _make_avatar(db, client_ids=[str(client_b.id)])

        results = _get_scoped_results(db, user_a, Avatar)
        result_ids = [r.id for r in results]
        assert avatar_a.id in result_ids
        assert avatar_b.id not in result_ids

    def test_client_admin_cannot_access_other_clients_activity_events(self, db):
        """client_admin of A cannot see B's ActivityEvents."""
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        user_a = _make_user(db, client_a, UserRole.client_admin)

        event_a = _make_activity_event(db, client_a)
        event_b = _make_activity_event(db, client_b)

        results = _get_scoped_results(db, user_a, ActivityEvent)
        result_ids = [r.id for r in results]
        assert event_a.id in result_ids
        assert event_b.id not in result_ids

    def test_client_admin_cannot_access_other_clients_threads(self, db):
        """client_admin of A cannot see B's RedditThreads."""
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        user_a = _make_user(db, client_a, UserRole.client_admin)

        subreddit = _make_subreddit(db)
        thread_a = _make_thread(db, subreddit)
        thread_b = _make_thread(db, subreddit)
        _make_thread_score(db, thread_a, client_a)
        _make_thread_score(db, thread_b, client_b)

        results = _get_scoped_results(db, user_a, RedditThread)
        result_ids = [r.id for r in results]
        assert thread_a.id in result_ids
        assert thread_b.id not in result_ids


class TestCrossClientIsolationClientViewer:
    """Test that client_viewer of Client_A cannot access Client_B's data.

    Validates: Requirement 9.8
    """

    def test_client_viewer_cannot_access_other_clients_comment_drafts(self, db):
        """client_viewer of A cannot see B's CommentDrafts."""
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        user_a = _make_user(db, client_a, UserRole.client_viewer)

        subreddit = _make_subreddit(db)
        avatar_a = _make_avatar(db, client_ids=[str(client_a.id)])
        avatar_b = _make_avatar(db, client_ids=[str(client_b.id)])
        thread = _make_thread(db, subreddit)

        draft_a = _make_comment_draft(db, thread, avatar_a, client_a)
        draft_b = _make_comment_draft(db, thread, avatar_b, client_b)

        results = _get_scoped_results(db, user_a, CommentDraft)
        result_ids = [r.id for r in results]
        assert draft_a.id in result_ids
        assert draft_b.id not in result_ids

    def test_client_viewer_cannot_access_other_clients_avatars(self, db):
        """client_viewer of A cannot see B's Avatars."""
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        user_a = _make_user(db, client_a, UserRole.client_viewer)

        avatar_a = _make_avatar(db, client_ids=[str(client_a.id)])
        avatar_b = _make_avatar(db, client_ids=[str(client_b.id)])

        results = _get_scoped_results(db, user_a, Avatar)
        result_ids = [r.id for r in results]
        assert avatar_a.id in result_ids
        assert avatar_b.id not in result_ids

    def test_client_viewer_cannot_access_other_clients_activity_events(self, db):
        """client_viewer of A cannot see B's ActivityEvents."""
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        user_a = _make_user(db, client_a, UserRole.client_viewer)

        event_a = _make_activity_event(db, client_a)
        event_b = _make_activity_event(db, client_b)

        results = _get_scoped_results(db, user_a, ActivityEvent)
        result_ids = [r.id for r in results]
        assert event_a.id in result_ids
        assert event_b.id not in result_ids

    def test_client_viewer_cannot_access_other_clients_threads(self, db):
        """client_viewer of A cannot see B's RedditThreads."""
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        user_a = _make_user(db, client_a, UserRole.client_viewer)

        subreddit = _make_subreddit(db)
        thread_a = _make_thread(db, subreddit)
        thread_b = _make_thread(db, subreddit)
        _make_thread_score(db, thread_a, client_a)
        _make_thread_score(db, thread_b, client_b)

        results = _get_scoped_results(db, user_a, RedditThread)
        result_ids = [r.id for r in results]
        assert thread_a.id in result_ids
        assert thread_b.id not in result_ids


class TestOwnerAccessBothClients:
    """Test that owner CAN access both Client_A and Client_B data.

    Validates: Requirement 9.7
    """

    def test_owner_can_access_all_comment_drafts(self, db):
        """Owner sees CommentDrafts from all clients."""
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        owner = _make_owner(db)

        subreddit = _make_subreddit(db)
        avatar_a = _make_avatar(db, client_ids=[str(client_a.id)])
        avatar_b = _make_avatar(db, client_ids=[str(client_b.id)])
        thread = _make_thread(db, subreddit)

        draft_a = _make_comment_draft(db, thread, avatar_a, client_a)
        draft_b = _make_comment_draft(db, thread, avatar_b, client_b)

        results = _get_scoped_results(db, owner, CommentDraft)
        result_ids = [r.id for r in results]
        assert draft_a.id in result_ids
        assert draft_b.id in result_ids

    def test_owner_can_access_all_avatars(self, db):
        """Owner sees Avatars from all clients."""
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        owner = _make_owner(db)

        avatar_a = _make_avatar(db, client_ids=[str(client_a.id)])
        avatar_b = _make_avatar(db, client_ids=[str(client_b.id)])

        results = _get_scoped_results(db, owner, Avatar)
        result_ids = [r.id for r in results]
        assert avatar_a.id in result_ids
        assert avatar_b.id in result_ids

    def test_owner_can_access_all_activity_events(self, db):
        """Owner sees ActivityEvents from all clients."""
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        owner = _make_owner(db)

        event_a = _make_activity_event(db, client_a)
        event_b = _make_activity_event(db, client_b)

        results = _get_scoped_results(db, owner, ActivityEvent)
        result_ids = [r.id for r in results]
        assert event_a.id in result_ids
        assert event_b.id in result_ids

    def test_owner_can_access_all_reddit_threads(self, db):
        """Owner sees RedditThreads from all clients."""
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        owner = _make_owner(db)

        subreddit = _make_subreddit(db)
        thread_a = _make_thread(db, subreddit)
        thread_b = _make_thread(db, subreddit)
        _make_thread_score(db, thread_a, client_a)
        _make_thread_score(db, thread_b, client_b)

        results = _get_scoped_results(db, owner, RedditThread)
        result_ids = [r.id for r in results]
        assert thread_a.id in result_ids
        assert thread_b.id in result_ids



# ===========================================================================
# Task 12.2: LLM context isolation integration test
# Validates: Requirement 9.6
# ===========================================================================


class TestLLMContextIsolation:
    """Test that LLM context assembly never includes cross-client data.

    Creates two clients with avatars, strategies, edit records, and correction
    patterns, then verifies that _assert_context_isolation correctly validates
    that no Client_B data leaks into Client_A's context.
    """

    def test_context_isolation_passes_with_correct_client_data(self, db):
        """_assert_context_isolation succeeds when all context items belong to target client."""
        client_a = _make_client(db, name="ClientA")
        avatar_a = _make_avatar(db, client_ids=[str(client_a.id)])
        strategy_a = _make_strategy_document(db, avatar_a)
        pattern_a = _make_correction_pattern(db, avatar_a, client_a)

        # Create a mock edit record (using a simple object with client_id)
        class FakeEditRecord:
            def __init__(self, client_id):
                self.id = uuid.uuid4()
                self.client_id = client_id

        examples_a = [FakeEditRecord(client_a.id)]

        # Should NOT raise — all data belongs to client_a
        _assert_context_isolation(
            client=client_a,
            avatar=avatar_a,
            strategy=strategy_a,
            examples=examples_a,
            patterns=[pattern_a],
        )

    def test_context_isolation_rejects_cross_client_edit_records(self, db):
        """_assert_context_isolation raises when an EditRecord belongs to another client."""
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        avatar_a = _make_avatar(db, client_ids=[str(client_a.id)])

        class FakeEditRecord:
            def __init__(self, client_id):
                self.id = uuid.uuid4()
                self.client_id = client_id

        # Inject a Client_B edit record into Client_A's context
        examples_with_leak = [FakeEditRecord(client_a.id), FakeEditRecord(client_b.id)]

        with pytest.raises(RuntimeError, match="Context isolation violation"):
            _assert_context_isolation(
                client=client_a,
                avatar=avatar_a,
                strategy=None,
                examples=examples_with_leak,
                patterns=[],
            )

    def test_context_isolation_rejects_cross_client_correction_patterns(self, db):
        """_assert_context_isolation raises when a CorrectionPattern belongs to another client."""
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        avatar_a = _make_avatar(db, client_ids=[str(client_a.id)])
        avatar_b = _make_avatar(db, client_ids=[str(client_b.id)])

        pattern_a = _make_correction_pattern(db, avatar_a, client_a)
        pattern_b = _make_correction_pattern(db, avatar_b, client_b)

        with pytest.raises(RuntimeError, match="Context isolation violation"):
            _assert_context_isolation(
                client=client_a,
                avatar=avatar_a,
                strategy=None,
                examples=[],
                patterns=[pattern_a, pattern_b],
            )

    def test_context_isolation_rejects_strategy_from_wrong_avatar(self, db):
        """_assert_context_isolation raises when strategy's avatar doesn't belong to client."""
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        # Avatar belongs to client_b, not client_a
        avatar_b = _make_avatar(db, client_ids=[str(client_b.id)])
        strategy_b = _make_strategy_document(db, avatar_b)

        with pytest.raises(RuntimeError, match="Context isolation violation"):
            _assert_context_isolation(
                client=client_a,
                avatar=avatar_b,
                strategy=strategy_b,
                examples=[],
                patterns=[],
            )

    def test_no_cross_client_data_in_assembled_context(self, db):
        """Full integration: create multi-client data, verify isolation holds.

        Creates two complete client setups and verifies that assembling context
        for Client_A with correct data passes, while any Client_B data causes failure.
        """
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")

        avatar_a = _make_avatar(db, client_ids=[str(client_a.id)])
        avatar_b = _make_avatar(db, client_ids=[str(client_b.id)])

        strategy_a = _make_strategy_document(db, avatar_a)
        strategy_b = _make_strategy_document(db, avatar_b)

        pattern_a = _make_correction_pattern(db, avatar_a, client_a)
        pattern_b = _make_correction_pattern(db, avatar_b, client_b)

        class FakeEditRecord:
            def __init__(self, client_id):
                self.id = uuid.uuid4()
                self.client_id = client_id

        # Correct context for client_a — should pass
        _assert_context_isolation(
            client=client_a,
            avatar=avatar_a,
            strategy=strategy_a,
            examples=[FakeEditRecord(client_a.id)],
            patterns=[pattern_a],
        )

        # Mixing client_b pattern into client_a context — should fail
        with pytest.raises(RuntimeError, match="Context isolation violation"):
            _assert_context_isolation(
                client=client_a,
                avatar=avatar_a,
                strategy=strategy_a,
                examples=[FakeEditRecord(client_a.id)],
                patterns=[pattern_a, pattern_b],
            )



# ===========================================================================
# Task 12.3: Avatar rental isolation tests
# Validates: Requirement 9.10
# ===========================================================================


class TestAvatarRentalIsolation:
    """Test that avatar rental access is properly isolated between clients."""

    def test_b2b_client_can_access_owned_and_rented_farm_avatars(self, db):
        """B2B client sees both owned avatars and actively rented farm avatars."""
        client = _make_client(db, name="B2BClient")
        user = _make_user(db, client, UserRole.client_manager)

        # Owned avatar
        owned_avatar = _make_avatar(db, client_ids=[str(client.id)])

        # Farm avatar rented to this client (active, no expiry)
        farm_avatar = _make_avatar(db, client_ids=[], is_farm_avatar=True)
        _make_rental(db, farm_avatar, client, is_active=True, expires_at=None)

        results = _get_scoped_results(db, user, Avatar)
        result_ids = [r.id for r in results]

        assert owned_avatar.id in result_ids
        assert farm_avatar.id in result_ids

    def test_b2b_client_cannot_access_another_clients_rented_avatars(self, db):
        """B2B client cannot see avatars rented to a different client."""
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        user_a = _make_user(db, client_a, UserRole.client_manager)

        # Farm avatar rented to client_b only
        farm_avatar = _make_avatar(db, client_ids=[], is_farm_avatar=True)
        _make_rental(db, farm_avatar, client_b, is_active=True, expires_at=None)

        # Client_a's own avatar
        own_avatar = _make_avatar(db, client_ids=[str(client_a.id)])

        results = _get_scoped_results(db, user_a, Avatar)
        result_ids = [r.id for r in results]

        assert own_avatar.id in result_ids
        assert farm_avatar.id not in result_ids

    def test_expired_rental_hides_avatar(self, db):
        """An expired rental makes the avatar invisible to the client."""
        client = _make_client(db, name="B2BClient")
        user = _make_user(db, client, UserRole.client_manager)

        # Farm avatar with expired rental
        farm_avatar = _make_avatar(db, client_ids=[], is_farm_avatar=True)
        past = datetime.now(timezone.utc) - timedelta(days=1)
        _make_rental(db, farm_avatar, client, is_active=True, expires_at=past)

        results = _get_scoped_results(db, user, Avatar)
        result_ids = [r.id for r in results]

        assert farm_avatar.id not in result_ids

    def test_inactive_rental_hides_avatar(self, db):
        """An inactive rental (is_active=False) makes the avatar invisible."""
        client = _make_client(db, name="B2BClient")
        user = _make_user(db, client, UserRole.client_manager)

        farm_avatar = _make_avatar(db, client_ids=[], is_farm_avatar=True)
        _make_rental(db, farm_avatar, client, is_active=False, expires_at=None)

        results = _get_scoped_results(db, user, Avatar)
        result_ids = [r.id for r in results]

        assert farm_avatar.id not in result_ids



# ===========================================================================
# Task 12.4: B2C avatar limit test
# Validates: Requirement 9.11
# ===========================================================================


class TestB2CAvatarLimit:
    """Test that b2c_user cannot create more than one avatar."""

    def test_b2c_user_cannot_create_second_avatar(self, db):
        """B2C user with an existing avatar is blocked from creating another."""
        client = _make_client(db, name="B2CClient")
        user = _make_user(db, client, UserRole.b2c_user)

        # User already has one avatar
        _make_avatar(db, client_ids=[str(client.id)])

        # Attempt to create a second avatar should raise 403
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            check_b2c_avatar_limit(db, user)

        assert exc_info.value.status_code == 403
        assert "B2C users can have only one avatar" in exc_info.value.detail

    def test_b2c_user_can_create_first_avatar(self, db):
        """B2C user with no existing avatar is allowed to create one."""
        client = _make_client(db, name="B2CClient")
        user = _make_user(db, client, UserRole.b2c_user)

        # No existing avatars — should not raise
        check_b2c_avatar_limit(db, user)

    def test_non_b2c_user_bypasses_limit(self, db):
        """Non-B2C users (e.g., client_manager) are not subject to the B2C limit."""
        client = _make_client(db, name="B2BClient")
        user = _make_user(db, client, UserRole.client_manager)

        # Even with existing avatars, non-B2C users pass
        _make_avatar(db, client_ids=[str(client.id)])
        _make_avatar(db, client_ids=[str(client.id)])

        # Should not raise
        check_b2c_avatar_limit(db, user)



# ===========================================================================
# Task 12.5: Runtime assertion failure test
# Validates: Requirement 9.9
# ===========================================================================


class TestRuntimeAssertionFailure:
    """Test that runtime assertions abort operations when avatar doesn't belong to client."""

    def test_avatar_not_belonging_to_client_aborts_operation(self, db):
        """If avatar doesn't belong to client, _avatar_accessible_by_client returns False."""
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")

        # Avatar belongs to client_b only
        avatar_b = _make_avatar(db, client_ids=[str(client_b.id)])

        # Check: avatar_b is NOT accessible by client_a
        assert _avatar_accessible_by_client(db, avatar_b, client_a) is False

    def test_avatar_belonging_to_client_passes(self, db):
        """If avatar belongs to client, _avatar_accessible_by_client returns True."""
        client_a = _make_client(db, name="ClientA")
        avatar_a = _make_avatar(db, client_ids=[str(client_a.id)])

        assert _avatar_accessible_by_client(db, avatar_a, client_a) is True

    def test_rented_avatar_accessible_by_renting_client(self, db):
        """A rented avatar is accessible by the renting client."""
        client_a = _make_client(db, name="ClientA")
        farm_avatar = _make_avatar(db, client_ids=[], is_farm_avatar=True)
        _make_rental(db, farm_avatar, client_a, is_active=True, expires_at=None)

        assert _avatar_accessible_by_client(db, farm_avatar, client_a) is True

    def test_expired_rental_makes_avatar_inaccessible(self, db):
        """An expired rental means the avatar is no longer accessible."""
        client_a = _make_client(db, name="ClientA")
        farm_avatar = _make_avatar(db, client_ids=[], is_farm_avatar=True)
        past = datetime.now(timezone.utc) - timedelta(days=1)
        _make_rental(db, farm_avatar, client_a, is_active=True, expires_at=past)

        assert _avatar_accessible_by_client(db, farm_avatar, client_a) is False

    def test_context_isolation_assertion_aborts_on_cross_client_avatar(self, db):
        """_assert_context_isolation raises RuntimeError when avatar doesn't belong to client."""
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        avatar_b = _make_avatar(db, client_ids=[str(client_b.id)])

        # Attempting to use client_b's avatar in client_a's context should fail
        with pytest.raises(RuntimeError, match="Context isolation violation"):
            _assert_context_isolation(
                client=client_a,
                avatar=avatar_b,
                strategy=_make_strategy_document(db, avatar_b),
                examples=[],
                patterns=[],
            )

    def test_no_cross_client_data_returned_via_query_scope(self, db):
        """QueryScope ensures no cross-client data is returned or processed."""
        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        user_a = _make_user(db, client_a, UserRole.client_manager)

        # Create data for both clients
        avatar_a = _make_avatar(db, client_ids=[str(client_a.id)])
        avatar_b = _make_avatar(db, client_ids=[str(client_b.id)])
        event_a = _make_activity_event(db, client_a)
        event_b = _make_activity_event(db, client_b)

        # Verify no cross-client data in any scoped query
        avatars = _get_scoped_results(db, user_a, Avatar)
        events = _get_scoped_results(db, user_a, ActivityEvent)

        avatar_ids = [a.id for a in avatars]
        event_ids = [e.id for e in events]

        # Client_B data must never appear
        assert avatar_b.id not in avatar_ids
        assert event_b.id not in event_ids

        # Client_A data must be present
        assert avatar_a.id in avatar_ids
        assert event_a.id in event_ids

    def test_write_access_denied_for_cross_client_operation(self, db):
        """QueryScope.assert_write_access raises SecurityError for cross-client writes."""
        from app.services.query_scope import SecurityError

        client_a = _make_client(db, name="ClientA")
        client_b = _make_client(db, name="ClientB")
        user_a = _make_user(db, client_a, UserRole.client_manager)

        scope = QueryScope(user=user_a)

        # Writing to own client — allowed
        scope.assert_write_access(client_a.id)

        # Writing to another client — denied
        with pytest.raises(SecurityError):
            scope.assert_write_access(client_b.id)
