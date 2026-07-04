"""Tests for signal_validator.handle_cqs_improvement().

Validates CQS improvement detection, avatar state updates, activity event
creation, and recovery candidate flagging.
"""

import uuid

import pytest

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.activity_event import ActivityEvent
from app.services.signal_validator import handle_cqs_improvement


def _make_client(db):
    """Create a test client for FK references."""
    client = Client(
        id=uuid.uuid4(),
        client_name=f"test_client_{uuid.uuid4().hex[:6]}",
        brand_name=f"test_brand_{uuid.uuid4().hex[:6]}",
    )
    db.add(client)
    db.flush()
    return client


def _make_avatar(db, cqs_level="lowest", is_frozen=False, is_shadowbanned=False, client=None):
    """Create a test avatar with given CQS state."""
    if client is None:
        client = _make_client(db)
    avatar = Avatar(
        id=uuid.uuid4(),
        reddit_username=f"test_user_{uuid.uuid4().hex[:8]}",
        cqs_level=cqs_level,
        is_frozen=is_frozen,
        is_shadowbanned=is_shadowbanned,
        client_ids=[str(client.id)],
    )
    db.add(avatar)
    db.flush()
    return avatar


class TestCQSImprovementDetection:
    """Test that improvements are correctly detected based on level ordering."""

    def test_lowest_to_low_is_improvement(self, db):
        avatar = _make_avatar(db, cqs_level="lowest")
        result = handle_cqs_improvement(db, avatar.id, "lowest", "low", "Your current CQS is **LOW**.")
        assert result["improved"] is True
        assert result["recovery_candidate"] is True
        assert result["old_level"] == "lowest"
        assert result["new_level"] == "low"

    def test_low_to_medium_is_improvement(self, db):
        avatar = _make_avatar(db, cqs_level="low")
        result = handle_cqs_improvement(db, avatar.id, "low", "medium", "CQS: Medium")
        assert result["improved"] is True
        assert result["recovery_candidate"] is True

    def test_medium_to_high_is_improvement(self, db):
        avatar = _make_avatar(db, cqs_level="medium")
        result = handle_cqs_improvement(db, avatar.id, "medium", "high", "CQS is HIGH")
        assert result["improved"] is True
        assert result["recovery_candidate"] is True

    def test_lowest_to_high_is_improvement(self, db):
        avatar = _make_avatar(db, cqs_level="lowest")
        result = handle_cqs_improvement(db, avatar.id, "lowest", "high", "CQS: High")
        assert result["improved"] is True
        assert result["recovery_candidate"] is True


class TestCQSNoImprovement:
    """Test that same/worse CQS levels are correctly identified as non-improvements."""

    def test_same_level_not_improvement(self, db):
        avatar = _make_avatar(db, cqs_level="low")
        result = handle_cqs_improvement(db, avatar.id, "low", "low", "CQS: Low")
        assert result["improved"] is False
        assert result["recovery_candidate"] is False

    def test_high_to_low_is_not_improvement(self, db):
        avatar = _make_avatar(db, cqs_level="high")
        result = handle_cqs_improvement(db, avatar.id, "high", "low", "CQS: Low")
        assert result["improved"] is False
        assert result["recovery_candidate"] is False

    def test_medium_to_lowest_is_not_improvement(self, db):
        avatar = _make_avatar(db, cqs_level="medium")
        result = handle_cqs_improvement(db, avatar.id, "medium", "lowest", "CQS: Lowest")
        assert result["improved"] is False
        assert result["recovery_candidate"] is False


class TestAvatarStateUpdate:
    """Test that avatar cqs_level is always updated to the new level."""

    def test_improvement_updates_cqs_level(self, db):
        avatar = _make_avatar(db, cqs_level="lowest")
        handle_cqs_improvement(db, avatar.id, "lowest", "low", "CQS: Low")
        db.refresh(avatar)
        assert avatar.cqs_level == "low"
        assert avatar.cqs_checked_at is not None

    def test_non_improvement_still_updates_cqs_level(self, db):
        avatar = _make_avatar(db, cqs_level="high")
        handle_cqs_improvement(db, avatar.id, "high", "low", "CQS: Low")
        db.refresh(avatar)
        assert avatar.cqs_level == "low"
        assert avatar.cqs_checked_at is not None

    def test_same_level_still_updates_checked_at(self, db):
        avatar = _make_avatar(db, cqs_level="medium")
        handle_cqs_improvement(db, avatar.id, "medium", "medium", "CQS: Medium")
        db.refresh(avatar)
        assert avatar.cqs_level == "medium"
        assert avatar.cqs_checked_at is not None


class TestActivityEventCreation:
    """Test that activity events are created only on improvement."""

    def test_improvement_creates_activity_event(self, db):
        avatar = _make_avatar(db, cqs_level="lowest")
        handle_cqs_improvement(db, avatar.id, "lowest", "low", "Your current CQS is **LOW**.")

        event = (
            db.query(ActivityEvent)
            .filter(ActivityEvent.event_type == "cqs_recovery_detected")
            .order_by(ActivityEvent.created_at.desc())
            .first()
        )
        assert event is not None
        assert avatar.reddit_username in event.message
        assert "lowest" in event.message
        assert "low" in event.message
        assert event.event_metadata["recovery_candidate"] is True
        assert event.event_metadata["source"] == "browser_extension"
        assert event.event_metadata["avatar_id"] == str(avatar.id)

    def test_no_activity_event_on_non_improvement(self, db):
        avatar = _make_avatar(db, cqs_level="high")
        # Count existing events
        count_before = (
            db.query(ActivityEvent)
            .filter(ActivityEvent.event_type == "cqs_recovery_detected")
            .count()
        )
        handle_cqs_improvement(db, avatar.id, "high", "low", "CQS: Low")
        count_after = (
            db.query(ActivityEvent)
            .filter(ActivityEvent.event_type == "cqs_recovery_detected")
            .count()
        )
        assert count_after == count_before


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_invalid_avatar_id(self, db):
        fake_id = uuid.uuid4()
        result = handle_cqs_improvement(db, fake_id, "lowest", "low", "CQS: Low")
        assert result["error"] == "avatar_not_found"
        assert result["improved"] is False
        assert result["recovery_candidate"] is False

    def test_invalid_old_level(self, db):
        avatar = _make_avatar(db, cqs_level="low")
        result = handle_cqs_improvement(db, avatar.id, "invalid", "low", "CQS: Low")
        assert result["error"] == "invalid_level"
        assert result["improved"] is False

    def test_invalid_new_level(self, db):
        avatar = _make_avatar(db, cqs_level="low")
        result = handle_cqs_improvement(db, avatar.id, "low", "banana", "CQS: Banana")
        assert result["error"] == "invalid_level"
        assert result["improved"] is False

    def test_case_insensitive_levels(self, db):
        avatar = _make_avatar(db, cqs_level="lowest")
        result = handle_cqs_improvement(db, avatar.id, "LOWEST", "LOW", "CQS: LOW")
        assert result["improved"] is True
        assert result["old_level"] == "lowest"
        assert result["new_level"] == "low"

    def test_whitespace_in_levels(self, db):
        avatar = _make_avatar(db, cqs_level="lowest")
        result = handle_cqs_improvement(db, avatar.id, "  lowest  ", "  low  ", "CQS: Low")
        assert result["improved"] is True
        assert result["old_level"] == "lowest"
        assert result["new_level"] == "low"

    def test_frozen_avatar_still_processed(self, db):
        """Frozen avatars should still get CQS improvement handled (SBM P9)."""
        avatar = _make_avatar(db, cqs_level="lowest", is_frozen=True)
        result = handle_cqs_improvement(db, avatar.id, "lowest", "low", "CQS: Low")
        assert result["improved"] is True
        assert result["recovery_candidate"] is True
        # Activity event includes frozen state info
        event = (
            db.query(ActivityEvent)
            .filter(ActivityEvent.event_type == "cqs_recovery_detected")
            .order_by(ActivityEvent.created_at.desc())
            .first()
        )
        assert event.event_metadata["is_frozen"] is True

    def test_shadowbanned_avatar_still_processed(self, db):
        """Shadowbanned avatars should still get CQS improvement handled."""
        avatar = _make_avatar(db, cqs_level="lowest", is_shadowbanned=True)
        result = handle_cqs_improvement(db, avatar.id, "lowest", "medium", "CQS: Medium")
        assert result["improved"] is True
        assert result["recovery_candidate"] is True
        event = (
            db.query(ActivityEvent)
            .filter(ActivityEvent.event_type == "cqs_recovery_detected")
            .order_by(ActivityEvent.created_at.desc())
            .first()
        )
        assert event.event_metadata["is_shadowbanned"] is True

    def test_empty_raw_text(self, db):
        """Empty raw text should still work (just won't be stored meaningfully)."""
        avatar = _make_avatar(db, cqs_level="lowest")
        result = handle_cqs_improvement(db, avatar.id, "lowest", "low", "")
        assert result["improved"] is True
        assert result["recovery_candidate"] is True
