"""Tests for CQS task dispatch pipeline integration (Task 5).

Verifies:
1. dispatch_due_email_tasks skips liveness check for CQS tasks (thread_id=NULL)
2. Health gate cancels tasks when avatar is frozen at dispatch time
3. expire_overdue_execution_tasks handles 48h deadlines correctly
4. _cancel_task_as_locked handles NULL epg_slot_id gracefully

Requirements: R6, R8
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.avatar import Avatar
from app.models.execution_task import ExecutionTask
from app.services.execution_tasks import expire_overdue_tasks, cancel_task
from app.tasks.execution_tasks import _cancel_task_as_locked


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_avatar(db, **kwargs) -> Avatar:
    """Helper to create a test avatar with sensible defaults."""
    defaults = {
        "id": uuid.uuid4(),
        "reddit_username": f"test_user_{uuid.uuid4().hex[:8]}",
        "active": True,
        "is_frozen": False,
        "is_shadowbanned": False,
        "health_status": "active",
        "executor_email": "exec@example.com",
        "executor_email_verified": True,
        "cqs_level": "lowest",
        "created_at": datetime.now(timezone.utc) - timedelta(days=30),
    }
    defaults.update(kwargs)
    avatar = Avatar(**defaults)
    db.add(avatar)
    db.flush()
    return avatar


def _make_cqs_task(db, avatar: Avatar, **kwargs) -> ExecutionTask:
    """Create a CQS check execution task (thread_id=NULL, epg_slot_id=NULL)."""
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid.uuid4(),
        "task_code": f"TASK-TEST-{uuid.uuid4().hex[:6]}",
        "executor_token": uuid.uuid4(),
        "epg_slot_id": None,
        "draft_id": None,
        "avatar_id": avatar.id,
        "client_id": None,
        "thread_id": None,
        "executor_contact": avatar.executor_email or "test@example.com",
        "executor_type": "avatar_owner",
        "delivery_channel": "email",
        "task_type": "cqs_check",
        "subreddit": "WhatIsMyCQS",
        "thread_url": "https://reddit.com/r/WhatIsMyCQS/submit",
        "thread_title": "CQS Health Check",
        "avatar_username": avatar.reddit_username,
        "client_name": "",
        "generated_text": "What is my cqs?",
        "scheduled_at": now + timedelta(minutes=10),
        "deadline": now + timedelta(hours=48),
        "status": "generated",
        "status_history": [{"status": "generated", "at": now.isoformat(), "by": "cqs_task_generator"}],
        "delivery_count": 0,
    }
    defaults.update(kwargs)
    task = ExecutionTask(**defaults)
    db.add(task)
    db.flush()
    return task


# ---------------------------------------------------------------------------
# 1. Liveness check skip for CQS tasks (thread_id=NULL)
# ---------------------------------------------------------------------------


class TestLivenessCheckSkip:
    """CQS tasks have thread_id=NULL - liveness check must be skipped."""

    def test_dispatch_skips_liveness_when_thread_id_null(self, db):
        """CQS task with thread_id=None dispatches without liveness check.

        Uses the dispatch logic directly via patched SessionLocal to verify
        the liveness check code path is not entered when thread_id is None.
        """
        avatar = _make_avatar(db)
        task = _make_cqs_task(
            db, avatar,
            scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        )

        # Patch SessionLocal so dispatch_due_email_tasks uses our test session
        with patch("app.tasks.execution_tasks.SessionLocal", return_value=db):
            with patch("app.tasks.execution_tasks.deliver_execution_task.delay") as mock_deliver:
                from app.tasks.execution_tasks import dispatch_due_email_tasks
                result = dispatch_due_email_tasks()

        # Task should be dispatched (thread_id=None means liveness check skipped)
        assert result.get("dispatched", 0) >= 1
        # Delivery should have been triggered
        mock_deliver.assert_called()

    def test_dispatch_does_not_crash_on_null_thread_id(self, db):
        """Ensure no NoneType errors when CQS task has thread_id=NULL."""
        avatar = _make_avatar(db)
        _make_cqs_task(
            db, avatar,
            scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )

        with patch("app.tasks.execution_tasks.SessionLocal", return_value=db):
            with patch("app.tasks.execution_tasks.deliver_execution_task.delay"):
                from app.tasks.execution_tasks import dispatch_due_email_tasks
                result = dispatch_due_email_tasks()

        assert "error" not in result
        assert result.get("dispatched", 0) >= 1


# ---------------------------------------------------------------------------
# 2. Health gate cancels if avatar frozen
# ---------------------------------------------------------------------------


class TestHealthGate:
    """Avatar health is checked before dispatch - frozen avatars get cancelled."""

    def test_frozen_avatar_task_cancelled(self, db):
        """Task for frozen avatar is cancelled at dispatch time."""
        avatar = _make_avatar(db, is_frozen=True)
        _make_cqs_task(
            db, avatar,
            scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        )

        with patch("app.tasks.execution_tasks.SessionLocal", return_value=db):
            with patch("app.tasks.execution_tasks.deliver_execution_task.delay") as mock_deliver:
                from app.tasks.execution_tasks import dispatch_due_email_tasks
                result = dispatch_due_email_tasks()

        # Should cancel, not dispatch
        assert result.get("cancelled_health", 0) >= 1
        assert result.get("dispatched", 0) == 0
        mock_deliver.assert_not_called()

    def test_shadowbanned_avatar_task_cancelled(self, db):
        """Task for shadowbanned avatar is cancelled at dispatch time."""
        avatar = _make_avatar(db, is_shadowbanned=True, health_status="shadowbanned")
        _make_cqs_task(
            db, avatar,
            scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        )

        with patch("app.tasks.execution_tasks.SessionLocal", return_value=db):
            with patch("app.tasks.execution_tasks.deliver_execution_task.delay") as mock_deliver:
                from app.tasks.execution_tasks import dispatch_due_email_tasks
                result = dispatch_due_email_tasks()

        assert result.get("cancelled_health", 0) >= 1
        assert result.get("dispatched", 0) == 0
        mock_deliver.assert_not_called()

    def test_healthy_avatar_task_dispatched(self, db):
        """Task for healthy avatar passes health gate and gets dispatched."""
        avatar = _make_avatar(db, is_frozen=False, health_status="active")
        _make_cqs_task(
            db, avatar,
            scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        )

        with patch("app.tasks.execution_tasks.SessionLocal", return_value=db):
            with patch("app.tasks.execution_tasks.deliver_execution_task.delay") as mock_deliver:
                from app.tasks.execution_tasks import dispatch_due_email_tasks
                result = dispatch_due_email_tasks()

        assert result.get("dispatched", 0) >= 1
        mock_deliver.assert_called()


# ---------------------------------------------------------------------------
# 3. expire_overdue handles 48h deadline
# ---------------------------------------------------------------------------


class TestExpireOverdue:
    """expire_overdue_execution_tasks works correctly with CQS 48h deadlines."""

    def test_expires_task_past_48h_deadline(self, db):
        """CQS task past its 48h deadline is correctly expired."""
        avatar = _make_avatar(db)
        # Create a task with deadline 1 hour ago (past due)
        task = _make_cqs_task(
            db, avatar,
            deadline=datetime.now(timezone.utc) - timedelta(hours=1),
            scheduled_at=datetime.now(timezone.utc) - timedelta(hours=49),
            status="generated",
        )

        count = expire_overdue_tasks(db)
        assert count == 1

        db.refresh(task)
        assert task.status == "expired"

    def test_does_not_expire_task_within_deadline(self, db):
        """CQS task still within its 48h window is not expired."""
        avatar = _make_avatar(db)
        task = _make_cqs_task(
            db, avatar,
            deadline=datetime.now(timezone.utc) + timedelta(hours=24),
            status="generated",
        )

        count = expire_overdue_tasks(db)
        assert count == 0

        db.refresh(task)
        assert task.status == "generated"

    def test_does_not_expire_submitted_task(self, db):
        """Task with submitted_url is not expired even if past deadline."""
        avatar = _make_avatar(db)
        task = _make_cqs_task(
            db, avatar,
            deadline=datetime.now(timezone.utc) - timedelta(hours=1),
            status="accepted",
        )
        task.submitted_url = "https://reddit.com/r/WhatIsMyCQS/comments/abc123"
        db.flush()

        count = expire_overdue_tasks(db)
        assert count == 0

    def test_expires_emailed_task_past_deadline(self, db):
        """Emailed CQS task past deadline is expired."""
        avatar = _make_avatar(db)
        task = _make_cqs_task(
            db, avatar,
            deadline=datetime.now(timezone.utc) - timedelta(hours=2),
            status="emailed",
        )

        count = expire_overdue_tasks(db)
        assert count == 1

        db.refresh(task)
        assert task.status == "expired"

    def test_deadline_agnostic_of_duration(self, db):
        """Expire logic just compares deadline < now, no assumption on duration."""
        avatar = _make_avatar(db)
        # Task with short deadline (already past)
        task_4h = _make_cqs_task(
            db, avatar,
            deadline=datetime.now(timezone.utc) - timedelta(minutes=30),
            status="generated",
        )
        # Task with 48h deadline (also past)
        avatar2 = _make_avatar(db)
        task_48h = _make_cqs_task(
            db, avatar2,
            deadline=datetime.now(timezone.utc) - timedelta(minutes=30),
            status="emailed",
        )

        count = expire_overdue_tasks(db)
        assert count == 2


# ---------------------------------------------------------------------------
# 4. _cancel_task_as_locked handles NULL epg_slot_id gracefully
# ---------------------------------------------------------------------------


class TestCancelTaskAsLocked:
    """_cancel_task_as_locked must not crash when epg_slot_id=NULL."""

    def test_cancel_with_null_epg_slot_id(self, db):
        """CQS task (epg_slot_id=None) can be cancelled without error."""
        avatar = _make_avatar(db)
        task = _make_cqs_task(db, avatar)
        assert task.epg_slot_id is None

        # Should not raise
        _cancel_task_as_locked(db, task, "test_cancellation")

        db.refresh(task)
        assert task.status == "cancelled"
        assert task.cancel_reason == "test_cancellation"

    def test_cancel_with_null_draft_id(self, db):
        """CQS task (draft_id=None) can be cancelled without error."""
        avatar = _make_avatar(db)
        task = _make_cqs_task(db, avatar)
        assert task.draft_id is None

        # Should not raise (no draft to reject)
        _cancel_task_as_locked(db, task, "no_draft_test")

        db.refresh(task)
        assert task.status == "cancelled"

    def test_cancel_with_all_nulls(self, db):
        """CQS task with all nullable fields NULL handles gracefully."""
        avatar = _make_avatar(db)
        task = _make_cqs_task(db, avatar)
        assert task.epg_slot_id is None
        assert task.draft_id is None
        assert task.thread_id is None

        # Should not raise any AttributeError or NoneType errors
        _cancel_task_as_locked(db, task, "full_null_test")

        db.refresh(task)
        assert task.status == "cancelled"
        assert task.cancel_reason == "full_null_test"
