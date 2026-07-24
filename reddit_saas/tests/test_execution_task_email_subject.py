"""Test execution task email subject includes brand name.

Regression test: subject must be 'RAMP Task for {client_name}'.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.services.execution_tasks import compose_task_email


def _make_task(**overrides):
    """Create a minimal mock ExecutionTask for compose_task_email."""
    task = MagicMock()
    task.task_type = "comment"
    task.client_name = "XM Cyber"
    task.avatar_username = "Hot-Thought2408"
    task.subreddit = "cybersecurity"
    task.task_code = "TASK-20260724-001"
    task.executor_token = "abc123"
    task.deadline = datetime(2026, 7, 24, 14, 30, tzinfo=timezone.utc)
    task.generated_text = "Great insight on zero trust architecture."
    task.thread_url = "https://reddit.com/r/cybersecurity/comments/abc/test"
    task.thread_title = "Zero trust discussion"
    task.scheduled_at = datetime(2026, 7, 24, 14, 0, tzinfo=timezone.utc)
    for k, v in overrides.items():
        setattr(task, k, v)
    return task


class TestEmailSubjectContainsBrand:
    """Email subject must include client brand name."""

    @patch("app.services.execution_tasks.get_setting", return_value="production")
    def test_standard_task_subject_has_brand(self, _mock_gs):
        task = _make_task(client_name="XM Cyber")
        subject, _, _ = compose_task_email(task)
        assert subject == "RAMP Task for XM Cyber"

    @patch("app.services.execution_tasks.get_setting", return_value="production")
    def test_subject_with_different_brand(self, _mock_gs):
        task = _make_task(client_name="NeuroYoga")
        subject, _, _ = compose_task_email(task)
        assert subject == "RAMP Task for NeuroYoga"

    def test_cqs_check_subject_unchanged(self):
        """CQS check emails have their own format — not affected."""
        task = _make_task(task_type="cqs_check")
        subject, _, _ = compose_task_email(task)
        assert "CQS Check" in subject
        assert task.avatar_username in subject
