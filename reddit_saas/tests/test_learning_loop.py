"""Unit tests for LearningLoopService — store_edit and get_recent_edits."""

import uuid
from datetime import datetime, timezone, timedelta

import pytest

from app.models.analysis_edit import AnalysisEditRecord
from app.services.learning_loop import store_edit, get_recent_edits, _compute_diff_summary


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def avatar_id(db):
    """Create a real avatar and return its ID for FK constraint."""
    from app.models.avatar import Avatar
    avatar = Avatar(
        reddit_username="test_avatar_loop",
        active=True,
    )
    db.add(avatar)
    db.flush()
    return avatar.id


# ---------------------------------------------------------------------------
# store_edit tests
# ---------------------------------------------------------------------------

class TestStoreEdit:
    """Tests for store_edit function."""

    def test_stores_record_with_diff(self, db, avatar_id):
        """Valid distinct dicts produce a persisted record with non-empty diff_summary."""
        llm_output = {"summary": "Original summary", "topics": {"key_themes": ["ai"]}}
        human_edited = {"summary": "Corrected summary", "topics": {"key_themes": ["ai", "ml"]}}

        record = store_edit(db, avatar_id, llm_output, human_edited)

        assert record.id is not None
        assert record.avatar_id == avatar_id
        assert record.llm_output == llm_output
        assert record.human_edited == human_edited
        assert record.diff_summary != ""
        assert record.created_at is not None

    def test_raises_value_error_on_identical_edits(self, db, avatar_id):
        """Identical llm_output and human_edited raises ValueError."""
        data = {"summary": "Same", "topics": {"key_themes": ["ai"]}}

        with pytest.raises(ValueError, match="No changes detected"):
            store_edit(db, avatar_id, data, data)

    def test_no_record_created_on_identical_edits(self, db, avatar_id):
        """No record is persisted when edits are identical."""
        data = {"summary": "Same", "topics": {"key_themes": ["ai"]}}

        try:
            store_edit(db, avatar_id, data, data)
        except ValueError:
            pass

        records = get_recent_edits(db, avatar_id, limit=10)
        assert len(records) == 0

    def test_diff_summary_describes_changes(self, db, avatar_id):
        """diff_summary mentions the changed fields."""
        llm_output = {"summary": "Old", "behavior": {"uses_emoji": False}}
        human_edited = {"summary": "New", "behavior": {"uses_emoji": True}}

        record = store_edit(db, avatar_id, llm_output, human_edited)

        assert "summary" in record.diff_summary
        assert "behavior" in record.diff_summary

    def test_diff_summary_handles_added_keys(self, db, avatar_id):
        """diff_summary notes when keys are added."""
        llm_output = {"summary": "Test"}
        human_edited = {"summary": "Test", "new_field": "value"}

        record = store_edit(db, avatar_id, llm_output, human_edited)

        assert "Added" in record.diff_summary
        assert "new_field" in record.diff_summary

    def test_diff_summary_handles_removed_keys(self, db, avatar_id):
        """diff_summary notes when keys are removed."""
        llm_output = {"summary": "Test", "old_field": "value"}
        human_edited = {"summary": "Test"}

        record = store_edit(db, avatar_id, llm_output, human_edited)

        assert "Removed" in record.diff_summary
        assert "old_field" in record.diff_summary


# ---------------------------------------------------------------------------
# get_recent_edits tests
# ---------------------------------------------------------------------------

class TestGetRecentEdits:
    """Tests for get_recent_edits function."""

    def test_returns_empty_list_when_no_edits(self, db, avatar_id):
        """No edits returns empty list."""
        result = get_recent_edits(db, avatar_id)
        assert result == []

    def test_returns_edits_ordered_by_created_at_desc(self, db, avatar_id):
        """Records are returned most-recent first."""
        # Create 3 records with distinct timestamps
        for i in range(3):
            store_edit(
                db, avatar_id,
                {"summary": f"original_{i}"},
                {"summary": f"edited_{i}"},
            )

        records = get_recent_edits(db, avatar_id)

        assert len(records) == 3
        # Most recent first
        for i in range(len(records) - 1):
            assert records[i].created_at >= records[i + 1].created_at

    def test_respects_limit_parameter(self, db, avatar_id):
        """Only returns up to `limit` records."""
        for i in range(5):
            store_edit(
                db, avatar_id,
                {"summary": f"original_{i}"},
                {"summary": f"edited_{i}"},
            )

        records = get_recent_edits(db, avatar_id, limit=2)
        assert len(records) == 2

    def test_default_limit_is_3(self, db, avatar_id):
        """Default limit is 3."""
        for i in range(5):
            store_edit(
                db, avatar_id,
                {"summary": f"original_{i}"},
                {"summary": f"edited_{i}"},
            )

        records = get_recent_edits(db, avatar_id)
        assert len(records) == 3

    def test_filters_by_avatar_id(self, db):
        """Only returns edits for the specified avatar."""
        from app.models.avatar import Avatar

        avatar1 = Avatar(reddit_username="avatar_one", active=True)
        avatar2 = Avatar(reddit_username="avatar_two", active=True)
        db.add_all([avatar1, avatar2])
        db.flush()

        store_edit(db, avatar1.id, {"summary": "a"}, {"summary": "b"})
        store_edit(db, avatar2.id, {"summary": "c"}, {"summary": "d"})

        records_1 = get_recent_edits(db, avatar1.id)
        records_2 = get_recent_edits(db, avatar2.id)

        assert len(records_1) == 1
        assert records_1[0].avatar_id == avatar1.id
        assert len(records_2) == 1
        assert records_2[0].avatar_id == avatar2.id


# ---------------------------------------------------------------------------
# _compute_diff_summary unit tests
# ---------------------------------------------------------------------------

class TestComputeDiffSummary:
    """Tests for the diff computation helper."""

    def test_simple_value_change(self):
        assert "Changed 'summary'" in _compute_diff_summary(
            {"summary": "old"}, {"summary": "new"}
        )

    def test_nested_value_change(self):
        result = _compute_diff_summary(
            {"topics": {"key_themes": ["ai"]}},
            {"topics": {"key_themes": ["ai", "ml"]}},
        )
        assert "topics.key_themes" in result

    def test_added_top_level_key(self):
        result = _compute_diff_summary({}, {"new_key": "val"})
        assert "Added 'new_key'" in result

    def test_removed_top_level_key(self):
        result = _compute_diff_summary({"old_key": "val"}, {})
        assert "Removed 'old_key'" in result

    def test_empty_dicts_returns_empty(self):
        """Two empty dicts produce empty diff (shouldn't happen in practice)."""
        assert _compute_diff_summary({}, {}) == ""
