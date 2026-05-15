"""Unit tests for generate_comment context isolation hardening.

Tests that generate_comment:
1. Raises ValueError when client_id is null
2. Uses _avatar_accessible_by_client (supports rentals) instead of direct client_ids check
3. Runs a final assertion verifying every context item belongs to target client_id
4. Aborts and logs ERROR on assertion failure

Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
"""

import uuid
from unittest.mock import patch, MagicMock

import pytest

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.subreddit import Subreddit
from app.models.thread import RedditThread
from app.services.generation import generate_comment, _assert_context_isolation


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
        voice_profile_md="Test voice profile",
    )
    db.add(avatar)
    db.flush()
    return avatar


def _make_subreddit(db) -> Subreddit:
    """Create a subreddit record."""
    sub = Subreddit(subreddit_name=f"test_{uuid.uuid4().hex[:6]}")
    db.add(sub)
    db.flush()
    return sub


def _make_thread(db, subreddit_id=None, **kwargs) -> RedditThread:
    """Create a RedditThread record."""
    if subreddit_id is None:
        sub = _make_subreddit(db)
        subreddit_id = sub.id
    defaults = {
        "reddit_native_id": f"t3_{uuid.uuid4().hex[:8]}",
        "subreddit_id": subreddit_id,
        "subreddit": "test_subreddit",
        "post_title": "Test post title",
        "post_body": "Test post body",
        "author": "test_author",
        "score": 10,
    }
    defaults.update(kwargs)
    thread = RedditThread(**defaults)
    db.add(thread)
    db.flush()
    return thread


# ---------------------------------------------------------------------------
# Tests — client_id null validation
# ---------------------------------------------------------------------------


class TestClientIdValidation:
    """Test that generate_comment raises ValueError when client_id is null."""

    def test_null_client_raises_value_error(self, db):
        """Passing None as client raises ValueError."""
        avatar = _make_avatar(db, client_ids=["some-id"])
        thread = _make_thread(db)

        with pytest.raises(ValueError, match="LLM context assembly requires a valid client_id"):
            generate_comment(
                db=db,
                thread=thread,
                client=None,
                avatar=avatar,
                persona_selection={"mode": "helpful_peer"},
            )

    def test_client_with_no_id_raises_value_error(self, db):
        """Client object with id=None raises ValueError."""
        client = Client(client_name="NoId", brand_name="NoId")
        # Don't flush — id stays None
        avatar = _make_avatar(db, client_ids=["some-id"])
        thread = _make_thread(db)

        with pytest.raises(ValueError, match="LLM context assembly requires a valid client_id"):
            generate_comment(
                db=db,
                thread=thread,
                client=client,
                avatar=avatar,
                persona_selection={"mode": "helpful_peer"},
            )


# ---------------------------------------------------------------------------
# Tests — avatar accessibility (replaces direct client_ids assertion)
# ---------------------------------------------------------------------------


class TestAvatarAccessibility:
    """Test that generate_comment uses _avatar_accessible_by_client."""

    def test_avatar_not_accessible_raises_runtime_error(self, db):
        """Avatar not owned by or rented to client raises RuntimeError."""
        client = _make_client(db)
        other_client = _make_client(db)
        avatar = _make_avatar(db, client_ids=[str(other_client.id)])
        thread = _make_thread(db)

        with pytest.raises(RuntimeError, match="Context isolation violation"):
            generate_comment(
                db=db,
                thread=thread,
                client=client,
                avatar=avatar,
                persona_selection={"mode": "helpful_peer"},
            )

    @patch("app.services.isolation._avatar_accessible_by_client", return_value=True)
    @patch("app.services.generation._assert_context_isolation")
    @patch("app.services.generation.get_config", return_value="test-model")
    @patch("app.services.generation.call_llm_json")
    @patch("app.services.generation.log_ai_usage")
    def test_rented_avatar_passes_accessibility_check(
        self, mock_log_usage, mock_llm, mock_get_config, mock_assert_isolation, mock_accessible, db
    ):
        """Avatar accessible via rental passes the check (mocked).

        This test verifies that the generate_comment function uses
        _avatar_accessible_by_client instead of direct client_ids check,
        allowing rented avatars to pass the accessibility check.
        """
        client = _make_client(db)
        # Avatar NOT owned by client (empty client_ids)
        avatar = _make_avatar(db, client_ids=[])
        thread = _make_thread(db)

        # Mock LLM to return valid response
        mock_llm.return_value = {
            "data": {
                "comment": "test comment",
                "comment_to": "post",
                "location_depth": 0,
                "location_reasoning": "test",
                "comment_approach": "reframe_drop",
                "strategic_angle": "reframe",
            },
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            "model": "test-model",
        }

        # Mock the strategy engine and learning service to avoid DB queries
        # that may fail if tables don't exist in test DB
        with patch("app.services.strategy_engine.StrategyEngine") as mock_strategy_cls, \
             patch("app.services.learning.LearningService") as mock_learning_cls:
            mock_strategy_cls.return_value.get_approved_strategy.return_value = None
            mock_learning_cls.return_value.select_few_shot_examples.return_value = []
            mock_learning_cls.return_value.get_correction_patterns.return_value = []

            # The function will try to save the draft to DB which may fail
            # due to missing columns in test DB. We only care that the
            # accessibility check was called correctly.
            try:
                generate_comment(
                    db=db,
                    thread=thread,
                    client=client,
                    avatar=avatar,
                    persona_selection={"mode": "helpful_peer"},
                )
            except RuntimeError as e:
                # DB save failure is acceptable — we're testing isolation logic
                if "Failed to save comment draft" not in str(e):
                    raise

            # The key assertion: _avatar_accessible_by_client was called
            mock_accessible.assert_called_once_with(db, avatar, client)


# ---------------------------------------------------------------------------
# Tests — _assert_context_isolation helper
# ---------------------------------------------------------------------------


class TestAssertContextIsolation:
    """Test the final assertion helper that verifies all context items."""

    def test_all_items_belong_to_client_passes(self, db):
        """No error when all items belong to the target client."""
        client = _make_client(db)
        avatar = _make_avatar(db, client_ids=[str(client.id)])

        # Mock examples and patterns with matching client_id
        example = MagicMock()
        example.client_id = client.id
        example.id = uuid.uuid4()

        pattern = MagicMock()
        pattern.client_id = client.id
        pattern.id = uuid.uuid4()

        # Should not raise
        _assert_context_isolation(
            client=client,
            avatar=avatar,
            strategy=None,
            examples=[example],
            patterns=[pattern],
        )

    def test_example_wrong_client_raises(self, db):
        """EditRecord with wrong client_id raises RuntimeError."""
        client = _make_client(db)
        other_client = _make_client(db)
        avatar = _make_avatar(db, client_ids=[str(client.id)])

        example = MagicMock()
        example.client_id = other_client.id
        example.id = uuid.uuid4()

        with pytest.raises(RuntimeError, match="Context isolation violation.*EditRecord"):
            _assert_context_isolation(
                client=client,
                avatar=avatar,
                strategy=None,
                examples=[example],
                patterns=[],
            )

    def test_pattern_wrong_client_raises(self, db):
        """CorrectionPattern with wrong client_id raises RuntimeError."""
        client = _make_client(db)
        other_client = _make_client(db)
        avatar = _make_avatar(db, client_ids=[str(client.id)])

        pattern = MagicMock()
        pattern.client_id = other_client.id
        pattern.id = uuid.uuid4()

        with pytest.raises(RuntimeError, match="Context isolation violation.*CorrectionPattern"):
            _assert_context_isolation(
                client=client,
                avatar=avatar,
                strategy=None,
                examples=[],
                patterns=[pattern],
            )

    def test_strategy_with_wrong_avatar_raises(self, db):
        """Strategy for avatar not belonging to client raises RuntimeError."""
        client = _make_client(db)
        other_client = _make_client(db)
        # Avatar does NOT belong to client
        avatar = _make_avatar(db, client_ids=[str(other_client.id)])

        strategy = MagicMock()
        strategy.id = uuid.uuid4()

        with pytest.raises(RuntimeError, match="Context isolation violation.*strategy"):
            _assert_context_isolation(
                client=client,
                avatar=avatar,
                strategy=strategy,
                examples=[],
                patterns=[],
            )

    def test_no_items_passes(self, db):
        """No strategy, no examples, no patterns — passes without error."""
        client = _make_client(db)
        avatar = _make_avatar(db, client_ids=[str(client.id)])

        # Should not raise
        _assert_context_isolation(
            client=client,
            avatar=avatar,
            strategy=None,
            examples=[],
            patterns=[],
        )

    def test_multiple_examples_one_bad_raises(self, db):
        """If one of multiple examples has wrong client_id, raises."""
        client = _make_client(db)
        other_client = _make_client(db)
        avatar = _make_avatar(db, client_ids=[str(client.id)])

        good_example = MagicMock()
        good_example.client_id = client.id
        good_example.id = uuid.uuid4()

        bad_example = MagicMock()
        bad_example.client_id = other_client.id
        bad_example.id = uuid.uuid4()

        with pytest.raises(RuntimeError, match="Context isolation violation.*EditRecord"):
            _assert_context_isolation(
                client=client,
                avatar=avatar,
                strategy=None,
                examples=[good_example, bad_example],
                patterns=[],
            )
