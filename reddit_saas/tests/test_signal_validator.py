"""Tests for signal_validator.normalize_probe_result().

Validates CQS extraction from various AutoModerator formats,
submission visibility normalization, and profile check parsing.
"""

import json

import pytest

from app.services.signal_validator import normalize_probe_result


# ---------------------------------------------------------------------------
# CQS Probe — Exact AutoModerator format (confidence 0.95)
# ---------------------------------------------------------------------------


class TestCQSExactFormat:
    """Tier 1: exact AutoModerator reply format — confidence 0.95."""

    def test_bold_low(self):
        result = normalize_probe_result("reddit_cqs", "Your current CQS is **LOW**.")
        assert result["cqs_level"] == "low"
        assert result["confidence"] == 0.95
        assert result["raw_text"] == "Your current CQS is **LOW**."

    def test_bold_medium(self):
        result = normalize_probe_result("reddit_cqs", "Your current CQS is **MEDIUM**.")
        assert result["cqs_level"] == "medium"
        assert result["confidence"] == 0.95

    def test_bold_high(self):
        result = normalize_probe_result("reddit_cqs", "Your current CQS is **HIGH**.")
        assert result["cqs_level"] == "high"
        assert result["confidence"] == 0.95

    def test_bold_lowest(self):
        result = normalize_probe_result("reddit_cqs", "Your current CQS is **LOWEST**.")
        assert result["cqs_level"] == "lowest"
        assert result["confidence"] == 0.95

    def test_no_bold(self):
        result = normalize_probe_result("reddit_cqs", "Your current CQS is LOW.")
        assert result["cqs_level"] == "low"
        assert result["confidence"] == 0.95

    def test_case_insensitive(self):
        result = normalize_probe_result("reddit_cqs", "your current cqs is high.")
        assert result["cqs_level"] == "high"
        assert result["confidence"] == 0.95

    def test_mixed_case(self):
        result = normalize_probe_result("reddit_cqs", "Your Current CQS is Medium")
        assert result["cqs_level"] == "medium"
        assert result["confidence"] == 0.95


# ---------------------------------------------------------------------------
# CQS Probe — Fuzzy format (confidence 0.7)
# ---------------------------------------------------------------------------


class TestCQSFuzzyFormat:
    """Tier 2: recognizable CQS formats — confidence 0.7."""

    def test_cqs_colon(self):
        result = normalize_probe_result("reddit_cqs", "CQS: Low")
        assert result["cqs_level"] == "low"
        assert result["confidence"] == 0.7

    def test_cqs_colon_no_space(self):
        result = normalize_probe_result("reddit_cqs", "CQS:High")
        assert result["cqs_level"] == "high"
        assert result["confidence"] == 0.7

    def test_cqs_level_colon(self):
        result = normalize_probe_result("reddit_cqs", "CQS level: MEDIUM")
        assert result["cqs_level"] == "medium"
        assert result["confidence"] == 0.7

    def test_cqs_level_no_colon(self):
        result = normalize_probe_result("reddit_cqs", "CQS level LOWEST")
        assert result["cqs_level"] == "lowest"
        assert result["confidence"] == 0.7

    def test_cqs_is(self):
        result = normalize_probe_result("reddit_cqs", "CQS is LOW")
        assert result["cqs_level"] == "low"
        assert result["confidence"] == 0.7


# ---------------------------------------------------------------------------
# CQS Probe — Ambiguous (confidence 0.3)
# ---------------------------------------------------------------------------


class TestCQSAmbiguous:
    """Tier 3: ambiguous match — CQS word near a level keyword — confidence 0.3."""

    def test_ambiguous_level_nearby(self):
        result = normalize_probe_result(
            "reddit_cqs",
            "Regarding your CQS we can see the result is medium now",
        )
        assert result["cqs_level"] == "medium"
        assert result["confidence"] == 0.3


# ---------------------------------------------------------------------------
# CQS Probe — Parse Failures
# ---------------------------------------------------------------------------


class TestCQSParseFailed:
    """Cases where no valid CQS level can be extracted."""

    def test_empty_input(self):
        result = normalize_probe_result("reddit_cqs", "")
        assert result["error"] == "parse_failed"
        assert result["confidence"] == 0.0

    def test_no_cqs_mention(self):
        result = normalize_probe_result("reddit_cqs", "Hello world, nothing relevant here")
        assert result["error"] == "parse_failed"
        assert result["confidence"] == 0.0

    def test_invalid_level_word(self):
        # "Your current CQS is BANANA" — not a valid level
        result = normalize_probe_result("reddit_cqs", "Your current CQS is BANANA.")
        assert result["error"] == "parse_failed"
        assert result["confidence"] == 0.0


# ---------------------------------------------------------------------------
# Submission Visibility Probe
# ---------------------------------------------------------------------------


class TestSubmissionVisibility:
    """Submission visibility probe normalization."""

    def test_present(self):
        result = normalize_probe_result("submission_visibility", "present")
        assert result["visible"] is True
        assert result["confidence"] == 0.9

    def test_absent(self):
        result = normalize_probe_result("submission_visibility", "absent")
        assert result["visible"] is False
        assert result["confidence"] == 0.9

    def test_present_with_whitespace(self):
        result = normalize_probe_result("submission_visibility", "  present  ")
        assert result["visible"] is True
        assert result["confidence"] == 0.9

    def test_absent_uppercase(self):
        result = normalize_probe_result("submission_visibility", "ABSENT")
        assert result["visible"] is False
        assert result["confidence"] == 0.9

    def test_invalid_value(self):
        result = normalize_probe_result("submission_visibility", "maybe")
        assert result["error"] == "parse_failed"
        assert result["confidence"] == 0.0

    def test_empty_input(self):
        result = normalize_probe_result("submission_visibility", "")
        assert result["error"] == "parse_failed"
        assert result["confidence"] == 0.0


# ---------------------------------------------------------------------------
# Profile Check Probe
# ---------------------------------------------------------------------------


class TestProfileCheck:
    """Profile check probe normalization."""

    def test_full_profile(self):
        raw = json.dumps({
            "comment_karma": 150,
            "link_karma": 42,
            "ban_indicators": ["profile_restricted"],
        })
        result = normalize_probe_result("profile_check", raw)
        assert result["comment_karma"] == 150
        assert result["link_karma"] == 42
        assert result["ban_indicators"] == ["profile_restricted"]
        assert result["confidence"] == 0.85

    def test_profile_without_ban_indicators(self):
        raw = json.dumps({"comment_karma": 10, "link_karma": 0})
        result = normalize_probe_result("profile_check", raw)
        assert result["comment_karma"] == 10
        assert result["link_karma"] == 0
        assert result["ban_indicators"] == []
        assert result["confidence"] == 0.85

    def test_profile_empty_ban_indicators(self):
        raw = json.dumps({
            "comment_karma": 500,
            "link_karma": 20,
            "ban_indicators": [],
        })
        result = normalize_probe_result("profile_check", raw)
        assert result["ban_indicators"] == []
        assert result["confidence"] == 0.85

    def test_string_karma_values(self):
        """Karma values as strings should be coerced to int."""
        raw = json.dumps({"comment_karma": "100", "link_karma": "5"})
        result = normalize_probe_result("profile_check", raw)
        assert result["comment_karma"] == 100
        assert result["link_karma"] == 5

    def test_missing_comment_karma(self):
        raw = json.dumps({"link_karma": 10})
        result = normalize_probe_result("profile_check", raw)
        assert result["error"] == "parse_failed"
        assert result["confidence"] == 0.0

    def test_missing_link_karma(self):
        raw = json.dumps({"comment_karma": 10})
        result = normalize_probe_result("profile_check", raw)
        assert result["error"] == "parse_failed"
        assert result["confidence"] == 0.0

    def test_invalid_json(self):
        result = normalize_probe_result("profile_check", "not json at all")
        assert result["error"] == "parse_failed"
        assert result["confidence"] == 0.0

    def test_empty_input(self):
        result = normalize_probe_result("profile_check", "")
        assert result["error"] == "parse_failed"
        assert result["confidence"] == 0.0

    def test_ban_indicators_non_list(self):
        """ban_indicators not a list should default to empty list."""
        raw = json.dumps({
            "comment_karma": 50,
            "link_karma": 10,
            "ban_indicators": "not_a_list",
        })
        result = normalize_probe_result("profile_check", raw)
        assert result["ban_indicators"] == []
        assert result["confidence"] == 0.85


# ---------------------------------------------------------------------------
# Unknown Probe Type
# ---------------------------------------------------------------------------


class TestUnknownProbeType:
    """Unknown probe type should return error with confidence 0.0."""

    def test_unknown_type(self):
        result = normalize_probe_result("unknown_type", "some data")
        assert result["error"] == "unknown_probe_type"
        assert result["confidence"] == 0.0

    def test_empty_type(self):
        result = normalize_probe_result("", "data")
        assert result["error"] == "unknown_probe_type"
        assert result["confidence"] == 0.0


# ---------------------------------------------------------------------------
# Health Signal Processing — process_health_signal()
# ---------------------------------------------------------------------------

import uuid
from datetime import datetime, timezone

from app.models.activity_event import ActivityEvent
from app.services.signal_validator import (
    process_health_signal,
    SIGNAL_TRUST_WEIGHTS,
    SIGNAL_DECAY_HOURS,
    DEFAULT_TRUST_WEIGHT,
    DEFAULT_DECAY_HOURS,
)


class TestProcessHealthSignal:
    """process_health_signal() records health signals with correct weights."""

    def test_comment_removed_signal(self, db):
        ts = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)
        result = process_health_signal(
            db=db,
            avatar_username="test_avatar_123",
            signal_type="comment_removed",
            raw_value={"comment_id": "abc123", "subreddit": "sysadmin"},
            timestamp=ts,
        )
        assert result == {
            "trust_weight": 0.6,
            "decay_hours": 72,
            "signal_type": "comment_removed",
            "recorded": True,
        }

    def test_ban_notice_signal(self, db):
        ts = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)
        result = process_health_signal(
            db=db,
            avatar_username="banned_user",
            signal_type="ban_notice",
            raw_value={"page": "profile", "message": "suspended"},
            timestamp=ts,
        )
        assert result["trust_weight"] == 0.9
        assert result["decay_hours"] == 168
        assert result["recorded"] is True

    def test_profile_restricted_signal(self, db):
        ts = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)
        result = process_health_signal(
            db=db,
            avatar_username="restricted_user",
            signal_type="profile_restricted",
            raw_value={},
            timestamp=ts,
        )
        assert result["trust_weight"] == 0.8
        assert result["decay_hours"] == 120

    def test_cqs_degraded_signal(self, db):
        ts = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)
        result = process_health_signal(
            db=db,
            avatar_username="cqs_user",
            signal_type="cqs_degraded",
            raw_value={"previous": "medium", "current": "low"},
            timestamp=ts,
        )
        assert result["trust_weight"] == 0.7
        assert result["decay_hours"] == 48  # default decay for cqs_degraded

    def test_unknown_signal_type_gets_defaults(self, db):
        ts = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)
        result = process_health_signal(
            db=db,
            avatar_username="some_user",
            signal_type="weird_unknown_signal",
            raw_value={"detail": "something"},
            timestamp=ts,
        )
        assert result["trust_weight"] == DEFAULT_TRUST_WEIGHT  # 0.5
        assert result["decay_hours"] == DEFAULT_DECAY_HOURS    # 48
        assert result["signal_type"] == "weird_unknown_signal"
        assert result["recorded"] is True

    def test_creates_activity_event(self, db):
        ts = datetime(2026, 6, 28, 14, 30, 0, tzinfo=timezone.utc)
        process_health_signal(
            db=db,
            avatar_username="event_check_user",
            signal_type="ban_notice",
            raw_value={"source": "profile_page"},
            timestamp=ts,
        )

        event = (
            db.query(ActivityEvent)
            .filter(ActivityEvent.event_type == "health_signal_received")
            .filter(ActivityEvent.event_metadata["avatar_username"].astext == "event_check_user")
            .first()
        )
        assert event is not None
        assert event.event_metadata["signal_type"] == "ban_notice"
        assert event.event_metadata["trust_weight"] == 0.9
        assert event.event_metadata["decay_hours"] == 168
        assert event.event_metadata["raw_value"] == {"source": "profile_page"}

    def test_activity_event_links_to_avatar_client(self, db):
        """When avatar exists with client_ids, event gets client_id."""
        from app.models.avatar import Avatar
        from app.models.client import Client

        # Create client and avatar
        client_id = uuid.uuid4()
        client = Client(id=client_id, client_name="Test Client", brand_name="TestBrand", keywords={})
        db.add(client)
        db.flush()

        avatar = Avatar(
            id=uuid.uuid4(),
            reddit_username="linked_avatar",
            client_ids=[str(client_id)],
        )
        db.add(avatar)
        db.flush()

        ts = datetime(2026, 6, 28, 15, 0, 0, tzinfo=timezone.utc)
        process_health_signal(
            db=db,
            avatar_username="linked_avatar",
            signal_type="comment_removed",
            raw_value={},
            timestamp=ts,
        )

        event = (
            db.query(ActivityEvent)
            .filter(ActivityEvent.event_type == "health_signal_received")
            .filter(ActivityEvent.event_metadata["avatar_username"].astext == "linked_avatar")
            .first()
        )
        assert event is not None
        assert event.client_id == client_id

    def test_unknown_avatar_gets_null_client_id(self, db):
        """When avatar_username doesn't exist, client_id is None."""
        ts = datetime(2026, 6, 28, 15, 0, 0, tzinfo=timezone.utc)
        process_health_signal(
            db=db,
            avatar_username="nonexistent_avatar_xyz",
            signal_type="ban_notice",
            raw_value={},
            timestamp=ts,
        )

        event = (
            db.query(ActivityEvent)
            .filter(ActivityEvent.event_type == "health_signal_received")
            .filter(ActivityEvent.event_metadata["avatar_username"].astext == "nonexistent_avatar_xyz")
            .first()
        )
        assert event is not None
        assert event.client_id is None
