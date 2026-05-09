"""Unit tests for the avatar learning panel endpoint (task 11.1).

Tests the GET /admin/avatars/{id}/learning-panel endpoint which returns
learning stats, correction patterns, and preview few-shot examples.

Uses mocked database to avoid requiring PostgreSQL connection.
Calls the endpoint function directly (same pattern as test_review_learning_hook.py).
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from starlette.testclient import TestClient as StarletteTestClient
from starlette.requests import Request as StarletteRequest
from starlette.datastructures import Headers

from app.models.avatar import Avatar
from app.models.correction_pattern import CorrectionPattern
from app.models.edit_record import EditRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_avatar(avatar_id):
    """Create a mock Avatar object."""
    avatar = MagicMock(spec=Avatar)
    avatar.id = avatar_id
    avatar.reddit_username = "test_avatar"
    avatar.active = True
    return avatar


def _make_edit_record(
    avatar_id,
    client_id,
    ai_draft="draft text",
    edited_draft="edited text",
    edit_summary="shortened 50→30 words",
    subreddit="cybersecurity",
    post_title="Test post",
    final_status="approved",
    is_archived=False,
    created_at=None,
    comment_draft_id=None,
):
    """Create a mock EditRecord."""
    record = MagicMock(spec=EditRecord)
    record.id = uuid.uuid4()
    record.comment_draft_id = comment_draft_id or uuid.uuid4()
    record.avatar_id = avatar_id
    record.client_id = client_id
    record.ai_draft = ai_draft
    record.edited_draft = edited_draft
    record.edit_summary = edit_summary
    record.subreddit = subreddit
    record.post_title = post_title
    record.final_status = final_status
    record.is_archived = is_archived
    record.created_at = created_at or datetime.now(timezone.utc)
    return record


def _make_pattern(avatar_id, client_id, pattern_type, rule_text, frequency, last_seen_at=None):
    """Create a mock CorrectionPattern."""
    pattern = MagicMock(spec=CorrectionPattern)
    pattern.id = uuid.uuid4()
    pattern.avatar_id = avatar_id
    pattern.client_id = client_id
    pattern.pattern_type = pattern_type
    pattern.rule_text = rule_text
    pattern.frequency = frequency
    pattern.last_seen_at = last_seen_at or datetime.now(timezone.utc)
    return pattern


def _build_mock_db(avatar, status_counts, most_recent_edit=None, correction_patterns=None, preview_examples=None):
    """Build a mock DB session that returns the expected data for the learning panel endpoint.

    The endpoint makes these queries in order:
    1. db.query(Avatar).filter(...).first() -> avatar
    2. db.query(EditRecord.final_status, func.count(...)).filter(...).group_by(...).all() -> status_counts
    3. db.query(EditRecord).filter(...).order_by(...).first() -> most_recent_edit
    4. db.query(CorrectionPattern).filter(...).order_by(...).limit(5).all() -> patterns
    5. db.query(EditRecord).filter(...).order_by(...).limit(3).all() -> preview_examples
    """
    mock_db = MagicMock()
    call_count = {"n": 0}

    def query_side_effect(*args):
        call_count["n"] += 1
        n = call_count["n"]

        mock_q = MagicMock()
        mock_q.filter.return_value = mock_q

        if n == 1:
            # Avatar query
            mock_q.first.return_value = avatar
        elif n == 2:
            # Status counts query (uses group_by)
            mock_q.group_by.return_value = mock_q
            mock_q.all.return_value = status_counts
        elif n == 3:
            # Most recent edit query (uses order_by + first)
            mock_q.order_by.return_value = mock_q
            mock_q.first.return_value = most_recent_edit
        elif n == 4:
            # Correction patterns query (uses order_by + limit + all)
            order_q = MagicMock()
            order_q.limit.return_value = order_q
            order_q.all.return_value = correction_patterns or []
            mock_q.order_by.return_value = order_q
        elif n == 5:
            # Preview examples query (uses order_by + limit + all)
            order_q = MagicMock()
            order_q.limit.return_value = order_q
            order_q.all.return_value = preview_examples or []
            mock_q.order_by.return_value = order_q

        return mock_q

    mock_db.query.side_effect = query_side_effect
    return mock_db


def _call_learning_panel(avatar_id, db):
    """Call the admin_avatar_learning_panel endpoint function directly."""
    from app.routes.admin import admin_avatar_learning_panel

    # Create a proper Starlette Request object for template rendering
    scope = {
        "type": "http",
        "method": "GET",
        "path": f"/admin/avatars/{avatar_id}/learning-panel",
        "query_string": b"",
        "headers": [],
    }
    request = StarletteRequest(scope)

    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    mock_user.is_superuser = True

    return admin_avatar_learning_panel(
        request=request,
        avatar_id=avatar_id,
        current_user=mock_user,
        db=db,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_avatar_id():
    return uuid.uuid4()


@pytest.fixture
def test_client_id():
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLearningPanelEmptyState:
    """Tests for the empty state when no edit records exist."""

    def test_empty_state_returns_200(self, test_avatar_id):
        """Endpoint returns 200 with empty state when no edit records exist."""
        avatar = _make_avatar(test_avatar_id)
        mock_db = _build_mock_db(avatar=avatar, status_counts=[])

        result = _call_learning_panel(test_avatar_id, mock_db)
        assert result.status_code == 200

    def test_empty_state_message(self, test_avatar_id):
        """Empty state shows 'no learning data' message."""
        avatar = _make_avatar(test_avatar_id)
        mock_db = _build_mock_db(avatar=avatar, status_counts=[])

        result = _call_learning_panel(test_avatar_id, mock_db)
        assert result.status_code == 200
        assert "No learning data available yet" in result.body.decode()

    def test_nonexistent_avatar_returns_404(self):
        """Requesting learning panel for non-existent avatar returns 404."""
        fake_id = uuid.uuid4()
        mock_db = _build_mock_db(avatar=None, status_counts=[])

        result = _call_learning_panel(fake_id, mock_db)
        assert result.status_code == 404


class TestLearningPanelWithData:
    """Tests for the learning panel with edit records present."""

    def test_status_breakdown_displayed(self, test_avatar_id, test_client_id):
        """Panel shows edit records broken down by status."""
        now = datetime.now(timezone.utc)
        avatar = _make_avatar(test_avatar_id)

        most_recent = _make_edit_record(
            test_avatar_id, test_client_id,
            final_status="approved",
            created_at=now - timedelta(hours=1),
        )

        mock_db = _build_mock_db(
            avatar=avatar,
            status_counts=[
                ("approved", 1),
                ("approved_unchanged", 1),
                ("rejected", 1),
            ],
            most_recent_edit=most_recent,
        )

        result = _call_learning_panel(test_avatar_id, mock_db)
        assert result.status_code == 200
        body = result.body.decode()
        # Template shows "X approved", "X unchanged", "X rejected" in text
        assert "1 approved" in body
        assert "1 unchanged" in body
        assert "1 rejected" in body

    def test_most_recent_edit_displayed(self, test_avatar_id, test_client_id):
        """Panel shows the most recent edit date and summary."""
        now = datetime.now(timezone.utc)
        avatar = _make_avatar(test_avatar_id)

        most_recent = _make_edit_record(
            test_avatar_id, test_client_id,
            ai_draft="original text here",
            edited_draft="modified text here",
            edit_summary="shortened 10→5 words; removed 'here'",
            final_status="approved",
            created_at=now,
        )

        mock_db = _build_mock_db(
            avatar=avatar,
            status_counts=[("approved", 1)],
            most_recent_edit=most_recent,
        )

        result = _call_learning_panel(test_avatar_id, mock_db)
        assert result.status_code == 200
        body = result.body.decode()
        assert "Last edit:" in body

    def test_correction_patterns_displayed(self, test_avatar_id, test_client_id):
        """Panel shows top correction patterns with frequencies."""
        now = datetime.now(timezone.utc)
        avatar = _make_avatar(test_avatar_id)

        most_recent = _make_edit_record(
            test_avatar_id, test_client_id,
            final_status="approved",
            created_at=now,
        )

        patterns = [
            _make_pattern(
                test_avatar_id, test_client_id,
                "length_adjustment", "Keep responses under 50 words", 8, now,
            ),
            _make_pattern(
                test_avatar_id, test_client_id,
                "tone_shift", "Use casual conversational tone", 5, now,
            ),
        ]

        mock_db = _build_mock_db(
            avatar=avatar,
            status_counts=[("approved", 1)],
            most_recent_edit=most_recent,
            correction_patterns=patterns,
        )

        result = _call_learning_panel(test_avatar_id, mock_db)
        assert result.status_code == 200
        body = result.body.decode()
        assert "Keep responses under 50 words" in body
        assert "Use casual conversational tone" in body
        # Template uses ×{frequency} format
        assert "×8" in body
        assert "×5" in body

    def test_preview_examples_truncated(self, test_avatar_id, test_client_id):
        """Preview examples have ai_draft and edited_draft truncated to 100 chars."""
        now = datetime.now(timezone.utc)
        avatar = _make_avatar(test_avatar_id)

        long_ai_draft = "A" * 200
        long_edited_draft = "B" * 200

        most_recent = _make_edit_record(
            test_avatar_id, test_client_id,
            ai_draft=long_ai_draft,
            edited_draft=long_edited_draft,
            final_status="approved",
            created_at=now,
        )

        # Preview examples are the raw records from DB; truncation happens in the endpoint
        preview_record = _make_edit_record(
            test_avatar_id, test_client_id,
            ai_draft=long_ai_draft,
            edited_draft=long_edited_draft,
            final_status="approved",
            created_at=now,
        )

        mock_db = _build_mock_db(
            avatar=avatar,
            status_counts=[("approved", 1)],
            most_recent_edit=most_recent,
            preview_examples=[preview_record],
        )

        result = _call_learning_panel(test_avatar_id, mock_db)
        assert result.status_code == 200
        body = result.body.decode()
        # The full 200-char string should NOT appear
        assert long_ai_draft not in body
        # But the truncated 100-char version should
        assert "A" * 100 in body

    def test_max_3_preview_examples(self, test_avatar_id, test_client_id):
        """At most 3 preview examples are returned."""
        now = datetime.now(timezone.utc)
        avatar = _make_avatar(test_avatar_id)

        most_recent = _make_edit_record(
            test_avatar_id, test_client_id,
            ai_draft="draft_0_original",
            edited_draft="draft_0_edited",
            final_status="approved",
            created_at=now,
        )

        # The endpoint limits to 3 in the DB query, so we simulate
        # the DB returning only 3 records (as it would with .limit(3))
        preview_records = []
        for i in range(3):
            record = _make_edit_record(
                test_avatar_id, test_client_id,
                ai_draft=f"draft_{i}_original",
                edited_draft=f"draft_{i}_edited",
                edit_summary=f"change_{i}",
                final_status="approved",
                created_at=now - timedelta(hours=i),
            )
            preview_records.append(record)

        mock_db = _build_mock_db(
            avatar=avatar,
            status_counts=[("approved", 5)],
            most_recent_edit=most_recent,
            preview_examples=preview_records,
        )

        result = _call_learning_panel(test_avatar_id, mock_db)
        assert result.status_code == 200
        body = result.body.decode()
        # Should show the 3 most recent examples
        assert "draft_0_original" in body
        assert "draft_1_original" in body
        assert "draft_2_original" in body
        # 4th and 5th should NOT appear (DB query limits to 3)
        assert "draft_3_original" not in body
        assert "draft_4_original" not in body
