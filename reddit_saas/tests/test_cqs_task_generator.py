"""Tests for CQS Task Generator service.

Tests cover:
- _get_cqs_check_interval logic (7d vs 30d)
- generate_cqs_check_tasks eligibility filters
- Task creation with correct fields
- Anti-spam (pending tasks, interval)
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.avatar import Avatar
from app.models.execution_task import ExecutionTask
from app.services.cqs_task_generator import (
    INTERVAL_RECOVERY,
    INTERVAL_STABLE,
    CQS_POST_TEXT,
    CQS_SUBREDDIT,
    CQS_THREAD_URL,
    CQS_TASK_DEADLINE_HOURS,
    YOUNG_ACCOUNT_DAYS,
    _get_cqs_check_interval,
    _has_pending_cqs_task,
    _get_last_cqs_task_date,
    generate_cqs_check_tasks,
)


# ---------------------------------------------------------------------------
# _get_cqs_check_interval tests
# ---------------------------------------------------------------------------


class TestGetCqsCheckInterval:
    """Test interval logic: 7d for lowest/young, 30d for mature."""

    def test_lowest_cqs_returns_7_days(self):
        """CQS=lowest always gets 7-day interval regardless of account age."""
        avatar = MagicMock()
        avatar.cqs_level = "lowest"
        avatar.created_at = datetime.now(timezone.utc) - timedelta(days=365)
        assert _get_cqs_check_interval(avatar) == INTERVAL_RECOVERY

    def test_young_account_returns_7_days(self):
        """Account < 90 days old gets 7-day interval even with good CQS."""
        avatar = MagicMock()
        avatar.cqs_level = "moderate"
        avatar.created_at = datetime.now(timezone.utc) - timedelta(days=30)
        assert _get_cqs_check_interval(avatar) == INTERVAL_RECOVERY

    def test_mature_account_good_cqs_returns_30_days(self):
        """Account >= 90 days with CQS above lowest gets 30-day interval."""
        avatar = MagicMock()
        avatar.cqs_level = "moderate"
        avatar.created_at = datetime.now(timezone.utc) - timedelta(days=180)
        assert _get_cqs_check_interval(avatar) == INTERVAL_STABLE

    def test_high_cqs_mature_returns_30_days(self):
        """CQS=high + mature account = 30 days."""
        avatar = MagicMock()
        avatar.cqs_level = "high"
        avatar.created_at = datetime.now(timezone.utc) - timedelta(days=200)
        assert _get_cqs_check_interval(avatar) == INTERVAL_STABLE

    def test_none_cqs_level_treated_as_above_lowest(self):
        """Avatars with no CQS level set (None) use account age logic."""
        avatar = MagicMock()
        avatar.cqs_level = None
        avatar.created_at = datetime.now(timezone.utc) - timedelta(days=200)
        assert _get_cqs_check_interval(avatar) == INTERVAL_STABLE

    def test_none_cqs_level_young_account(self):
        """Young account with None CQS level gets 7 days."""
        avatar = MagicMock()
        avatar.cqs_level = None
        avatar.created_at = datetime.now(timezone.utc) - timedelta(days=50)
        assert _get_cqs_check_interval(avatar) == INTERVAL_RECOVERY

    def test_exactly_90_days_is_mature(self):
        """Account exactly at 90-day boundary is considered mature."""
        avatar = MagicMock()
        avatar.cqs_level = "low"
        avatar.created_at = datetime.now(timezone.utc) - timedelta(days=90)
        assert _get_cqs_check_interval(avatar) == INTERVAL_STABLE

    def test_89_days_is_young(self):
        """Account at 89 days is still considered young."""
        avatar = MagicMock()
        avatar.cqs_level = "low"
        avatar.created_at = datetime.now(timezone.utc) - timedelta(days=89)
        assert _get_cqs_check_interval(avatar) == INTERVAL_RECOVERY

    def test_no_created_at_defaults_to_mature(self):
        """If created_at is None, default to 999 days (mature)."""
        avatar = MagicMock()
        avatar.cqs_level = "moderate"
        avatar.created_at = None
        assert _get_cqs_check_interval(avatar) == INTERVAL_STABLE


# ---------------------------------------------------------------------------
# generate_cqs_check_tasks integration tests (with DB)
# ---------------------------------------------------------------------------


class TestGenerateCqsCheckTasks:
    """Integration tests for the main generator function."""

    def _make_avatar(self, db, **kwargs):
        """Helper to create a test avatar."""
        defaults = {
            "id": uuid.uuid4(),
            "reddit_username": f"test_user_{uuid.uuid4().hex[:8]}",
            "active": True,
            "is_frozen": False,
            "health_status": "active",
            "executor_email": "test@example.com",
            "executor_email_verified": True,
            "cqs_level": "lowest",
            "created_at": datetime.now(timezone.utc) - timedelta(days=30),
        }
        defaults.update(kwargs)
        avatar = Avatar(**defaults)
        db.add(avatar)
        db.flush()
        return avatar

    def test_creates_task_for_eligible_avatar(self, db):
        """Eligible avatar (active, not frozen, verified email, no pending) gets a task."""
        avatar = self._make_avatar(db)
        result = generate_cqs_check_tasks(db)
        assert result["created"] == 1
        assert result["errors"] == 0

        # Verify task in DB — new tasks use diagnostic_probe type
        task = db.query(ExecutionTask).filter(
            ExecutionTask.avatar_id == avatar.id,
            ExecutionTask.task_type == "diagnostic_probe",
            ExecutionTask.probe_type == "reddit_cqs",
        ).first()
        assert task is not None
        assert task.subreddit == CQS_SUBREDDIT
        assert task.generated_text == CQS_POST_TEXT
        assert task.thread_url == CQS_THREAD_URL
        assert task.epg_slot_id is None
        assert task.draft_id is None
        assert task.thread_id is None
        assert task.status == "generated"
        # Task 4.1: delivery_channel prefers extension
        assert task.delivery_channel == "extension"
        # Task 4.2: diagnostic_probe fields
        assert task.task_type == "diagnostic_probe"
        assert task.probe_type == "reddit_cqs"
        assert task.priority == "diagnostic"
        assert task.task_lifecycle_status == "CREATED"

    def test_includes_frozen_avatar(self, db):
        """Frozen avatars ARE included (June 27, 2026 fix — CQS deadlock).

        Frozen/shadowbanned avatars need CQS checks to detect recovery.
        Previously they were skipped, creating a deadlock where recovery
        was impossible without manual intervention.
        """
        avatar = self._make_avatar(db, is_frozen=True)
        result = generate_cqs_check_tasks(db)
        # Frozen avatar SHOULD get a CQS task now
        task = db.query(ExecutionTask).filter(
            ExecutionTask.avatar_id == avatar.id,
            ExecutionTask.task_type == "diagnostic_probe",
            ExecutionTask.probe_type == "reddit_cqs",
        ).first()
        assert task is not None
        assert result["skipped_frozen"] == 0

    def test_includes_shadowbanned_avatar(self, db):
        """Shadowbanned avatars ARE included (June 27 fix — CQS deadlock)."""
        avatar = self._make_avatar(db, health_status="shadowbanned")
        result = generate_cqs_check_tasks(db)
        task = db.query(ExecutionTask).filter(
            ExecutionTask.avatar_id == avatar.id,
            ExecutionTask.task_type == "diagnostic_probe",
            ExecutionTask.probe_type == "reddit_cqs",
        ).first()
        assert task is not None
        assert result["skipped_health"] == 0

    def test_includes_suspended_avatar(self, db):
        """Suspended avatars ARE included (June 27 fix — CQS deadlock)."""
        avatar = self._make_avatar(db, health_status="suspended")
        result = generate_cqs_check_tasks(db)
        task = db.query(ExecutionTask).filter(
            ExecutionTask.avatar_id == avatar.id,
            ExecutionTask.task_type == "diagnostic_probe",
            ExecutionTask.probe_type == "reddit_cqs",
        ).first()
        assert task is not None
        assert result["skipped_health"] == 0

    def test_skips_no_email(self, db):
        """Avatars without verified email are skipped."""
        avatar = self._make_avatar(db, executor_email=None)
        result = generate_cqs_check_tasks(db)
        # No-email avatar should never get a CQS task
        assert result["skipped_no_email"] >= 1
        task = db.query(ExecutionTask).filter(
            ExecutionTask.avatar_id == avatar.id,
            ExecutionTask.task_type == "diagnostic_probe",
            ExecutionTask.probe_type == "reddit_cqs",
        ).first()
        assert task is None

    def test_skips_unverified_email(self, db):
        """Avatars with unverified email are skipped."""
        avatar = self._make_avatar(db, executor_email_verified=False)
        result = generate_cqs_check_tasks(db)
        # Unverified email avatar should never get a CQS task
        assert result["skipped_no_email"] >= 1
        task = db.query(ExecutionTask).filter(
            ExecutionTask.avatar_id == avatar.id,
            ExecutionTask.task_type == "diagnostic_probe",
            ExecutionTask.probe_type == "reddit_cqs",
        ).first()
        assert task is None

    def test_skips_pending_task(self, db):
        """Avatar with existing pending CQS task is skipped."""
        avatar = self._make_avatar(db)
        # Create a pending CQS task manually
        pending_task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="TASK-TEST-001",
            executor_token=uuid.uuid4(),
            avatar_id=avatar.id,
            executor_contact="test@example.com",
            task_type="cqs_check",
            subreddit=CQS_SUBREDDIT,
            thread_url=CQS_THREAD_URL,
            thread_title="CQS Health Check",
            avatar_username=avatar.reddit_username,
            client_name="",
            generated_text=CQS_POST_TEXT,
            deadline=datetime.now(timezone.utc) + timedelta(hours=48),
            status="generated",
        )
        db.add(pending_task)
        db.flush()

        result = generate_cqs_check_tasks(db)
        assert result["created"] == 0
        assert result["skipped_pending"] == 1

    def test_skips_interval_not_reached(self, db):
        """Avatar with recent CQS task within interval is skipped."""
        avatar = self._make_avatar(db, cqs_level="lowest")  # 7-day interval
        # Create a completed CQS task from 3 days ago
        recent_task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="TASK-TEST-002",
            executor_token=uuid.uuid4(),
            avatar_id=avatar.id,
            executor_contact="test@example.com",
            task_type="cqs_check",
            subreddit=CQS_SUBREDDIT,
            thread_url=CQS_THREAD_URL,
            thread_title="CQS Health Check",
            avatar_username=avatar.reddit_username,
            client_name="",
            generated_text=CQS_POST_TEXT,
            deadline=datetime.now(timezone.utc) + timedelta(hours=48),
            status="verified",  # Terminal status
            created_at=datetime.now(timezone.utc) - timedelta(days=3),
        )
        db.add(recent_task)
        db.flush()

        result = generate_cqs_check_tasks(db)
        assert result["created"] == 0
        assert result["skipped_interval"] == 1

    def test_creates_after_interval_passed(self, db):
        """Avatar with old CQS task beyond interval gets a new task."""
        avatar = self._make_avatar(db, cqs_level="lowest")  # 7-day interval
        # Create a completed CQS task from 8 days ago
        old_task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="TASK-TEST-003",
            executor_token=uuid.uuid4(),
            avatar_id=avatar.id,
            executor_contact="test@example.com",
            task_type="cqs_check",
            subreddit=CQS_SUBREDDIT,
            thread_url=CQS_THREAD_URL,
            thread_title="CQS Health Check",
            avatar_username=avatar.reddit_username,
            client_name="",
            generated_text=CQS_POST_TEXT,
            deadline=datetime.now(timezone.utc) - timedelta(days=6),
            status="expired",  # Terminal status
            created_at=datetime.now(timezone.utc) - timedelta(days=8),
        )
        db.add(old_task)
        db.flush()

        result = generate_cqs_check_tasks(db)
        assert result["created"] == 1

    def test_no_duplicate_on_second_run(self, db):
        """Running generator twice doesn\'t create duplicate tasks."""
        self._make_avatar(db)
        result1 = generate_cqs_check_tasks(db)
        assert result1["created"] == 1

        result2 = generate_cqs_check_tasks(db)
        assert result2["created"] == 0
        assert result2["skipped_pending"] == 1

    def test_deadline_is_48_hours_from_scheduled(self, db):
        """Task deadline is scheduled_at + 48 hours."""
        avatar = self._make_avatar(db)
        generate_cqs_check_tasks(db)

        task = db.query(ExecutionTask).filter(
            ExecutionTask.avatar_id == avatar.id,
            ExecutionTask.task_type == "diagnostic_probe",
            ExecutionTask.probe_type == "reddit_cqs",
        ).first()
        assert task is not None
        # Deadline should be approximately scheduled_at + 48h
        delta = task.deadline - task.scheduled_at
        assert abs(delta.total_seconds() - CQS_TASK_DEADLINE_HOURS * 3600) < 1

    def test_inactive_avatar_excluded(self, db):
        """Inactive avatars (active=False) are not queried at all."""
        avatar = self._make_avatar(db, active=False)
        result = generate_cqs_check_tasks(db)
        # Inactive avatar should never get a CQS task (filtered at query level)
        task = db.query(ExecutionTask).filter(
            ExecutionTask.avatar_id == avatar.id,
            ExecutionTask.task_type == "diagnostic_probe",
            ExecutionTask.probe_type == "reddit_cqs",
        ).first()
        assert task is None

    def test_skips_submitted_task_as_pending(self, db):
        """Task in 'submitted' state is still active — no new task should be created."""
        avatar = self._make_avatar(db)
        submitted_task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="TASK-TEST-SUB-001",
            executor_token=uuid.uuid4(),
            avatar_id=avatar.id,
            executor_contact="test@example.com",
            task_type="cqs_check",
            subreddit=CQS_SUBREDDIT,
            thread_url=CQS_THREAD_URL,
            thread_title="CQS Health Check",
            avatar_username=avatar.reddit_username,
            client_name="",
            generated_text=CQS_POST_TEXT,
            deadline=datetime.now(timezone.utc) + timedelta(hours=48),
            status="submitted",
        )
        db.add(submitted_task)
        db.flush()

        result = generate_cqs_check_tasks(db)
        # Should be blocked by the submitted task (non-terminal)
        tasks = db.query(ExecutionTask).filter(
            ExecutionTask.avatar_id == avatar.id,
            ExecutionTask.task_type == "cqs_check",
        ).all()
        assert len(tasks) == 1  # Only the pre-existing one
        assert result["skipped_pending"] >= 1

    def test_skips_url_verified_task_as_pending(self, db):
        """Task in 'url_verified' state is still active — no new task should be created."""
        avatar = self._make_avatar(db)
        task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="TASK-TEST-UV-001",
            executor_token=uuid.uuid4(),
            avatar_id=avatar.id,
            executor_contact="test@example.com",
            task_type="cqs_check",
            subreddit=CQS_SUBREDDIT,
            thread_url=CQS_THREAD_URL,
            thread_title="CQS Health Check",
            avatar_username=avatar.reddit_username,
            client_name="",
            generated_text=CQS_POST_TEXT,
            deadline=datetime.now(timezone.utc) + timedelta(hours=48),
            status="url_verified",
        )
        db.add(task)
        db.flush()

        result = generate_cqs_check_tasks(db)
        tasks = db.query(ExecutionTask).filter(
            ExecutionTask.avatar_id == avatar.id,
            ExecutionTask.task_type == "cqs_check",
        ).all()
        assert len(tasks) == 1
        assert result["skipped_pending"] >= 1

    def test_does_not_skip_for_failed_task(self, db):
        """Task in 'failed' terminal state does NOT block new task creation."""
        avatar = self._make_avatar(db, cqs_level="lowest")
        failed_task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="TASK-TEST-FAIL-001",
            executor_token=uuid.uuid4(),
            avatar_id=avatar.id,
            executor_contact="test@example.com",
            task_type="cqs_check",
            subreddit=CQS_SUBREDDIT,
            thread_url=CQS_THREAD_URL,
            thread_title="CQS Health Check",
            avatar_username=avatar.reddit_username,
            client_name="",
            generated_text=CQS_POST_TEXT,
            deadline=datetime.now(timezone.utc) - timedelta(hours=48),
            status="failed",
            created_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        db.add(failed_task)
        db.flush()

        result = generate_cqs_check_tasks(db)
        # Failed task is terminal — should allow new task creation (interval also passed)
        new_task = db.query(ExecutionTask).filter(
            ExecutionTask.avatar_id == avatar.id,
            ExecutionTask.task_type == "diagnostic_probe",
            ExecutionTask.probe_type == "reddit_cqs",
            ExecutionTask.status == "generated",
        ).first()
        assert new_task is not None
        assert result["created"] >= 1

    def test_does_not_skip_for_cancelled_task(self, db):
        """Task in 'cancelled' terminal state does NOT block new task creation."""
        avatar = self._make_avatar(db, cqs_level="lowest")
        cancelled_task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="TASK-TEST-CANC-001",
            executor_token=uuid.uuid4(),
            avatar_id=avatar.id,
            executor_contact="test@example.com",
            task_type="cqs_check",
            subreddit=CQS_SUBREDDIT,
            thread_url=CQS_THREAD_URL,
            thread_title="CQS Health Check",
            avatar_username=avatar.reddit_username,
            client_name="",
            generated_text=CQS_POST_TEXT,
            deadline=datetime.now(timezone.utc) - timedelta(hours=48),
            status="cancelled",
            created_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        db.add(cancelled_task)
        db.flush()

        result = generate_cqs_check_tasks(db)
        # Cancelled is terminal — new task should be created (interval also passed)
        new_task = db.query(ExecutionTask).filter(
            ExecutionTask.avatar_id == avatar.id,
            ExecutionTask.task_type == "diagnostic_probe",
            ExecutionTask.probe_type == "reddit_cqs",
            ExecutionTask.status == "generated",
        ).first()
        assert new_task is not None
        assert result["created"] >= 1

    def test_30_day_interval_respected_for_mature(self, db):
        """Mature account (>90d) with CQS above lowest: 30-day interval enforced."""
        avatar = self._make_avatar(
            db,
            cqs_level="moderate",
            created_at=datetime.now(timezone.utc) - timedelta(days=200),
        )
        # Task from 20 days ago — within 30-day interval
        recent_task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="TASK-TEST-30D-001",
            executor_token=uuid.uuid4(),
            avatar_id=avatar.id,
            executor_contact="test@example.com",
            task_type="cqs_check",
            subreddit=CQS_SUBREDDIT,
            thread_url=CQS_THREAD_URL,
            thread_title="CQS Health Check",
            avatar_username=avatar.reddit_username,
            client_name="",
            generated_text=CQS_POST_TEXT,
            deadline=datetime.now(timezone.utc) - timedelta(days=18),
            status="verified",
            created_at=datetime.now(timezone.utc) - timedelta(days=20),
        )
        db.add(recent_task)
        db.flush()

        result = generate_cqs_check_tasks(db)
        # 20 days < 30-day interval → skip
        new_task = db.query(ExecutionTask).filter(
            ExecutionTask.avatar_id == avatar.id,
            ExecutionTask.task_type == "diagnostic_probe",
            ExecutionTask.probe_type == "reddit_cqs",
            ExecutionTask.status == "generated",
        ).first()
        assert new_task is None
        assert result["skipped_interval"] >= 1

    def test_30_day_interval_allows_after_expiry(self, db):
        """Mature account after 30+ days gets a new task."""
        avatar = self._make_avatar(
            db,
            cqs_level="moderate",
            created_at=datetime.now(timezone.utc) - timedelta(days=200),
        )
        # Task from 31 days ago — past 30-day interval
        old_task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="TASK-TEST-30D-002",
            executor_token=uuid.uuid4(),
            avatar_id=avatar.id,
            executor_contact="test@example.com",
            task_type="cqs_check",
            subreddit=CQS_SUBREDDIT,
            thread_url=CQS_THREAD_URL,
            thread_title="CQS Health Check",
            avatar_username=avatar.reddit_username,
            client_name="",
            generated_text=CQS_POST_TEXT,
            deadline=datetime.now(timezone.utc) - timedelta(days=29),
            status="expired",
            created_at=datetime.now(timezone.utc) - timedelta(days=31),
        )
        db.add(old_task)
        db.flush()

        result = generate_cqs_check_tasks(db)
        # 31 days >= 30-day interval → new task created
        new_task = db.query(ExecutionTask).filter(
            ExecutionTask.avatar_id == avatar.id,
            ExecutionTask.task_type == "diagnostic_probe",
            ExecutionTask.probe_type == "reddit_cqs",
            ExecutionTask.status == "generated",
        ).first()
        assert new_task is not None
        assert result["created"] >= 1
