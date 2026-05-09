"""Unit tests for the review route learning hook (task 8.2).

Tests that LearningService.capture_edit_record is called correctly
on approve (with edits), approve (unchanged), and reject actions,
and that the review endpoint succeeds even if capture_edit_record raises.

Requirements: 1.1, 1.2, 1.3
"""

import uuid
from unittest.mock import patch, MagicMock

import pytest

from app.models.comment_draft import CommentDraft
from app.models.thread import RedditThread


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_comment(ai_draft: str, edited_draft: str | None, status: str = "pending"):
    """Create a mock CommentDraft with realistic attributes."""
    comment = MagicMock(spec=CommentDraft)
    comment.id = uuid.uuid4()
    comment.avatar_id = uuid.uuid4()
    comment.client_id = uuid.uuid4()
    comment.thread_id = uuid.uuid4()
    comment.ai_draft = ai_draft
    comment.edited_draft = edited_draft
    comment.status = status
    comment.engagement_mode = "helpful_peer"
    comment.posted_at = None
    comment.reddit_score = None

    # Mock thread relationship
    thread = MagicMock(spec=RedditThread)
    thread.post_title = "Test post about cybersecurity"
    thread.post_body = "This is a test post body."
    thread.subreddit = "cybersecurity"
    comment.thread = thread

    # Mock avatar relationship
    avatar = MagicMock()
    avatar.reddit_username = "test_avatar"
    comment.avatar = avatar

    return comment


def make_mock_db(comment):
    """Create a mock DB session that returns the given comment on query."""
    db = MagicMock()
    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.first.return_value = comment
    db.query.return_value = mock_query
    db.commit = MagicMock()
    db.refresh = MagicMock(side_effect=lambda c: None)
    return db


# ---------------------------------------------------------------------------
# Test: capture_edit_record called on approve with edits
# Validates: Requirement 1.1
# ---------------------------------------------------------------------------


class TestReviewLearningHookApproveWithEdits:
    """Test that capture_edit_record is called with status='approved' when
    the operator approves a draft that has edits (edited_draft != ai_draft).
    """

    @patch("app.services.learning.LearningService")
    @patch("app.routes.review.record_activity_event")
    @patch("app.routes.review.audit_service")
    def test_capture_called_on_approve_with_edits(
        self, mock_audit, mock_activity, mock_learning_cls
    ):
        """When approving a comment where edited_draft != ai_draft,
        capture_edit_record should be called with status='approved'."""
        from app.routes.review import update_comment, UpdateCommentRequest

        ai_text = "The original AI-generated draft."
        edited_text = "The human-edited version, much shorter."
        comment = make_mock_comment(ai_draft=ai_text, edited_draft=edited_text)
        db = make_mock_db(comment)

        mock_instance = MagicMock()
        mock_learning_cls.return_value = mock_instance

        request = UpdateCommentRequest(status="approved")
        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()

        result = update_comment(
            comment_id=comment.id,
            data=request,
            db=db,
            current_user=mock_user,
        )

        # Verify capture_edit_record was called
        mock_instance.capture_edit_record.assert_called_once()
        call_kwargs = mock_instance.capture_edit_record.call_args[1]
        assert call_kwargs["status"] == "approved"
        assert call_kwargs["draft"] == comment
        assert call_kwargs["thread"] == comment.thread


# ---------------------------------------------------------------------------
# Test: capture_edit_record called on approve unchanged
# Validates: Requirement 1.3
# ---------------------------------------------------------------------------


class TestReviewLearningHookApproveUnchanged:
    """Test that capture_edit_record is called with status='approved_unchanged'
    when the operator approves a draft without edits.
    """

    @patch("app.services.learning.LearningService")
    @patch("app.routes.review.record_activity_event")
    @patch("app.routes.review.audit_service")
    def test_capture_called_on_approve_unchanged_null_edited(
        self, mock_audit, mock_activity, mock_learning_cls
    ):
        """When approving a comment where edited_draft is None,
        capture_edit_record should be called with status='approved_unchanged'."""
        from app.routes.review import update_comment, UpdateCommentRequest

        ai_text = "The original AI-generated draft."
        comment = make_mock_comment(ai_draft=ai_text, edited_draft=None)
        db = make_mock_db(comment)

        mock_instance = MagicMock()
        mock_learning_cls.return_value = mock_instance

        request = UpdateCommentRequest(status="approved")
        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()

        result = update_comment(
            comment_id=comment.id,
            data=request,
            db=db,
            current_user=mock_user,
        )

        mock_instance.capture_edit_record.assert_called_once()
        call_kwargs = mock_instance.capture_edit_record.call_args[1]
        assert call_kwargs["status"] == "approved_unchanged"

    @patch("app.services.learning.LearningService")
    @patch("app.routes.review.record_activity_event")
    @patch("app.routes.review.audit_service")
    def test_capture_called_on_approve_unchanged_same_text(
        self, mock_audit, mock_activity, mock_learning_cls
    ):
        """When approving a comment where edited_draft == ai_draft,
        capture_edit_record should be called with status='approved_unchanged'."""
        from app.routes.review import update_comment, UpdateCommentRequest

        ai_text = "The original AI-generated draft."
        comment = make_mock_comment(ai_draft=ai_text, edited_draft=ai_text)
        db = make_mock_db(comment)

        mock_instance = MagicMock()
        mock_learning_cls.return_value = mock_instance

        request = UpdateCommentRequest(status="approved")
        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()

        result = update_comment(
            comment_id=comment.id,
            data=request,
            db=db,
            current_user=mock_user,
        )

        mock_instance.capture_edit_record.assert_called_once()
        call_kwargs = mock_instance.capture_edit_record.call_args[1]
        assert call_kwargs["status"] == "approved_unchanged"


# ---------------------------------------------------------------------------
# Test: capture_edit_record called on reject
# Validates: Requirement 1.2
# ---------------------------------------------------------------------------


class TestReviewLearningHookReject:
    """Test that capture_edit_record is called with status='rejected'
    when the operator rejects a draft.
    """

    @patch("app.services.learning.LearningService")
    @patch("app.routes.review.record_activity_event")
    @patch("app.routes.review.audit_service")
    def test_capture_called_on_reject(
        self, mock_audit, mock_activity, mock_learning_cls
    ):
        """When rejecting a comment, capture_edit_record should be called
        with status='rejected'."""
        from app.routes.review import update_comment, UpdateCommentRequest

        ai_text = "The original AI-generated draft."
        comment = make_mock_comment(ai_draft=ai_text, edited_draft="Some edit")
        db = make_mock_db(comment)

        mock_instance = MagicMock()
        mock_learning_cls.return_value = mock_instance

        request = UpdateCommentRequest(status="rejected")
        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()

        result = update_comment(
            comment_id=comment.id,
            data=request,
            db=db,
            current_user=mock_user,
        )

        mock_instance.capture_edit_record.assert_called_once()
        call_kwargs = mock_instance.capture_edit_record.call_args[1]
        assert call_kwargs["status"] == "rejected"
        assert call_kwargs["draft"] == comment
        assert call_kwargs["thread"] == comment.thread


# ---------------------------------------------------------------------------
# Test: review succeeds even if capture_edit_record raises
# Validates: Requirements 1.1, 1.2, 1.3
# ---------------------------------------------------------------------------


class TestReviewLearningHookExceptionHandling:
    """Test that the review endpoint succeeds even if capture_edit_record
    raises an exception. Learning is non-critical.
    """

    @patch("app.services.learning.LearningService")
    @patch("app.routes.review.record_activity_event")
    @patch("app.routes.review.audit_service")
    def test_approve_succeeds_when_capture_raises(
        self, mock_audit, mock_activity, mock_learning_cls
    ):
        """If capture_edit_record raises an exception, the approve action
        should still succeed — learning must never block review."""
        from app.routes.review import update_comment, UpdateCommentRequest

        ai_text = "The original AI-generated draft."
        edited_text = "The human-edited version."
        comment = make_mock_comment(ai_draft=ai_text, edited_draft=edited_text)
        db = make_mock_db(comment)

        mock_instance = MagicMock()
        mock_instance.capture_edit_record.side_effect = RuntimeError(
            "Database connection lost"
        )
        mock_learning_cls.return_value = mock_instance

        request = UpdateCommentRequest(status="approved")
        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()

        # Should NOT raise — learning failure is caught
        result = update_comment(
            comment_id=comment.id,
            data=request,
            db=db,
            current_user=mock_user,
        )

        # The comment should still be returned (review succeeded)
        assert result == comment
        # Verify capture was attempted
        mock_instance.capture_edit_record.assert_called_once()

    @patch("app.services.learning.LearningService")
    @patch("app.routes.review.record_activity_event")
    @patch("app.routes.review.audit_service")
    def test_reject_succeeds_when_capture_raises(
        self, mock_audit, mock_activity, mock_learning_cls
    ):
        """If capture_edit_record raises on reject, the review action
        should still succeed."""
        from app.routes.review import update_comment, UpdateCommentRequest

        ai_text = "The original AI-generated draft."
        comment = make_mock_comment(ai_draft=ai_text, edited_draft=None)
        db = make_mock_db(comment)

        mock_instance = MagicMock()
        mock_instance.capture_edit_record.side_effect = Exception(
            "Unexpected error in learning service"
        )
        mock_learning_cls.return_value = mock_instance

        request = UpdateCommentRequest(status="rejected")
        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()

        # Should NOT raise — learning failure is caught
        result = update_comment(
            comment_id=comment.id,
            data=request,
            db=db,
            current_user=mock_user,
        )

        # The comment should still be returned (review succeeded)
        assert result == comment
        # Verify capture was attempted
        mock_instance.capture_edit_record.assert_called_once()
