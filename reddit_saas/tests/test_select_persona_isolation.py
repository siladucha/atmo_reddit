"""Unit tests for select_persona context isolation (task 7.3).

Verifies that select_persona:
1. Uses _avatar_accessible_by_client (supports rentals) instead of direct client_ids check
2. Logs WARNING and excludes inaccessible avatars from candidates (doesn't abort)
3. Raises ValueError if ALL candidates are excluded

Validates: Requirements 5.1, 5.6
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.avatar import Avatar
from app.models.avatar_rental import AvatarRental
from app.models.client import Client
from app.models.subreddit import Subreddit
from app.models.thread import RedditThread
from app.services.generation import select_persona


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(db, **kwargs) -> Client:
    defaults = {
        "client_name": f"Client-{uuid.uuid4().hex[:6]}",
        "brand_name": f"Brand-{uuid.uuid4().hex[:6]}",
        "company_worldview": "We believe in testing",
        "company_problem": "Bugs exist",
        "is_active": True,
    }
    defaults.update(kwargs)
    client = Client(**defaults)
    db.add(client)
    db.flush()
    return client


def _make_avatar(db, client_ids: list[str] | None = None, username: str | None = None) -> Avatar:
    avatar = Avatar(
        reddit_username=username or f"avatar_{uuid.uuid4().hex[:8]}",
        active=True,
        client_ids=client_ids,
        voice_profile_md="Test voice",
        karma_comment=100,
    )
    db.add(avatar)
    db.flush()
    return avatar


def _make_subreddit(db, name: str = "test_sub") -> Subreddit:
    sub = Subreddit(subreddit_name=name)
    db.add(sub)
    db.flush()
    return sub


def _make_thread(db, subreddit: str = "test_sub") -> RedditThread:
    sub = _make_subreddit(db, name=subreddit)
    thread = RedditThread(
        reddit_native_id=f"t3_{uuid.uuid4().hex[:8]}",
        subreddit_id=sub.id,
        subreddit=subreddit,
        post_title="Test thread for persona selection",
        post_body="Some test content",
    )
    db.add(thread)
    db.flush()
    return thread


def _make_rental(db, avatar: Avatar, client: Client, is_active: bool = True, expires_at=None):
    rental = AvatarRental(
        avatar_id=avatar.id,
        client_id=client.id,
        is_active=is_active,
        expires_at=expires_at,
    )
    db.add(rental)
    db.flush()
    return rental


# Mock LLM response for persona selection
MOCK_PERSONA_RESPONSE = {
    "data": {
        "persona_username": "test_avatar",
        "mode": "helpful_peer",
        "audience": "developers",
        "thread_angle": "testing angle",
        "pov_opportunity": None,
        "selection_reasoning": "best fit",
    },
    "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    "model": "test-model",
}


# ---------------------------------------------------------------------------
# Tests — Owned avatars pass the check
# ---------------------------------------------------------------------------


class TestOwnedAvatarsPass:
    """Owned avatars should pass the accessibility check and proceed to LLM."""

    @patch("app.services.generation.get_config", return_value="test-model")
    @patch("app.services.generation.call_llm_json")
    @patch("app.services.generation.log_ai_usage")
    def test_owned_avatar_proceeds_to_selection(self, mock_log, mock_llm, mock_config, db):
        """Avatar owned by client passes check and LLM is called."""
        client = _make_client(db)
        avatar = _make_avatar(db, client_ids=[str(client.id)], username="owned_avatar")
        thread = _make_thread(db)

        mock_llm.return_value = {
            **MOCK_PERSONA_RESPONSE,
            "data": {**MOCK_PERSONA_RESPONSE["data"], "persona_username": "owned_avatar"},
        }

        result = select_persona(db, thread, client, [avatar])

        assert result["persona_username"] == "owned_avatar"
        mock_llm.assert_called_once()


# ---------------------------------------------------------------------------
# Tests — Rented avatars pass the check
# ---------------------------------------------------------------------------


class TestRentedAvatarsPass:
    """Rented avatars (active, not expired) should pass the accessibility check."""

    @patch("app.services.generation.get_config", return_value="test-model")
    @patch("app.services.generation.call_llm_json")
    @patch("app.services.generation.log_ai_usage")
    def test_rented_avatar_proceeds_to_selection(self, mock_log, mock_llm, mock_config, db):
        """Avatar rented to client passes check and LLM is called."""
        client = _make_client(db)
        # Avatar NOT owned by client (empty client_ids)
        avatar = _make_avatar(db, client_ids=[], username="rented_avatar")
        # But actively rented
        _make_rental(db, avatar, client, is_active=True, expires_at=None)
        thread = _make_thread(db)

        mock_llm.return_value = {
            **MOCK_PERSONA_RESPONSE,
            "data": {**MOCK_PERSONA_RESPONSE["data"], "persona_username": "rented_avatar"},
        }

        result = select_persona(db, thread, client, [avatar])

        assert result["persona_username"] == "rented_avatar"
        mock_llm.assert_called_once()


# ---------------------------------------------------------------------------
# Tests — Inaccessible avatars are excluded with WARNING
# ---------------------------------------------------------------------------


class TestInaccessibleAvatarsExcluded:
    """Avatars not accessible by client should be excluded with a WARNING log."""

    @patch("app.services.generation.get_config", return_value="test-model")
    @patch("app.services.generation.call_llm_json")
    @patch("app.services.generation.log_ai_usage")
    def test_inaccessible_avatar_excluded_from_candidates(self, mock_log, mock_llm, mock_config, db, caplog):
        """Avatar not owned/rented is excluded; remaining avatars proceed."""
        client = _make_client(db)
        # One accessible avatar
        good_avatar = _make_avatar(db, client_ids=[str(client.id)], username="good_avatar")
        # One inaccessible avatar (belongs to different client)
        other_client = _make_client(db)
        bad_avatar = _make_avatar(db, client_ids=[str(other_client.id)], username="bad_avatar")
        thread = _make_thread(db)

        mock_llm.return_value = {
            **MOCK_PERSONA_RESPONSE,
            "data": {**MOCK_PERSONA_RESPONSE["data"], "persona_username": "good_avatar"},
        }

        with caplog.at_level(logging.WARNING, logger="app.services.generation"):
            result = select_persona(db, thread, client, [good_avatar, bad_avatar])

        # Good avatar selected
        assert result["persona_username"] == "good_avatar"
        # WARNING logged for bad avatar
        assert "bad_avatar" in caplog.text
        assert "excluded from persona candidates" in caplog.text

    @patch("app.services.generation.get_config", return_value="test-model")
    @patch("app.services.generation.call_llm_json")
    @patch("app.services.generation.log_ai_usage")
    def test_expired_rental_avatar_excluded(self, mock_log, mock_llm, mock_config, db, caplog):
        """Avatar with expired rental is excluded from candidates."""
        client = _make_client(db)
        good_avatar = _make_avatar(db, client_ids=[str(client.id)], username="good_avatar")
        # Avatar with expired rental
        expired_avatar = _make_avatar(db, client_ids=[], username="expired_rental")
        past = datetime.now(timezone.utc) - timedelta(days=1)
        _make_rental(db, expired_avatar, client, is_active=True, expires_at=past)
        thread = _make_thread(db)

        mock_llm.return_value = {
            **MOCK_PERSONA_RESPONSE,
            "data": {**MOCK_PERSONA_RESPONSE["data"], "persona_username": "good_avatar"},
        }

        with caplog.at_level(logging.WARNING, logger="app.services.generation"):
            result = select_persona(db, thread, client, [good_avatar, expired_avatar])

        assert result["persona_username"] == "good_avatar"
        assert "expired_rental" in caplog.text


# ---------------------------------------------------------------------------
# Tests — All candidates excluded raises ValueError
# ---------------------------------------------------------------------------


class TestAllCandidatesExcluded:
    """If ALL candidate avatars fail the check, raise ValueError."""

    def test_all_candidates_inaccessible_raises_value_error(self, db):
        """ValueError raised when no avatars pass the accessibility check."""
        client = _make_client(db)
        other_client = _make_client(db)
        # All avatars belong to a different client
        avatar1 = _make_avatar(db, client_ids=[str(other_client.id)], username="alien1")
        avatar2 = _make_avatar(db, client_ids=[str(other_client.id)], username="alien2")
        thread = _make_thread(db)

        with pytest.raises(ValueError, match="All candidate avatars failed accessibility check"):
            select_persona(db, thread, client, [avatar1, avatar2])

    def test_empty_avatars_list_raises_value_error(self, db):
        """ValueError raised when avatars list is empty."""
        client = _make_client(db)
        thread = _make_thread(db)

        with pytest.raises(ValueError, match="All candidate avatars failed accessibility check"):
            select_persona(db, thread, client, [])
