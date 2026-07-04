"""Tests for POST /api/extension/report endpoint."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.execution_task import ExecutionTask
from app.services.auth import create_access_token


@pytest.fixture
def executor_user(db):
    """Create an executor user for extension tests."""
    from app.services.auth import create_user
    user = create_user(db, email="executor@test.com", password="exec123", full_name="Executor")
    user.is_active = True
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def ext_client(db, executor_user):
    """TestClient authenticated via Bearer token (extension-style auth)."""
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    token = create_access_token(data={
        "sub": str(executor_user.id),
        "email": executor_user.email,
        "role": executor_user.user_role.value if hasattr(executor_user, 'user_role') and executor_user.user_role else "owner",
        "is_superuser": getattr(executor_user, 'is_superuser', False),
    })
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def sample_task(db):
    """Create a sample ExecutionTask with extension lifecycle fields."""
    from datetime import datetime, timezone

    task = ExecutionTask(
        id=uuid.uuid4(),
        task_code="TASK-TEST-001",
        executor_token=uuid.uuid4(),
        executor_contact="executor@test.com",
        executor_type="admin",
        delivery_channel="extension",
        task_type="comment",
        subreddit="test",
        thread_url="https://reddit.com/r/test/comments/abc/test",
        thread_title="Test Thread",
        avatar_username="test_avatar",
        client_name="TestClient",
        generated_text="Test comment",
        deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
        status="generated",
        task_lifecycle_status="ASSIGNED",
        idempotency_key="idem-key-123",
        task_hash="fake-hmac-hash",
        priority="content",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


class TestPostReport:
    """Tests for POST /api/extension/report."""

    def test_successful_report(self, ext_client, sample_task, db):
        """First valid report sets task to REPORTED and stores data."""
        resp = ext_client.post("/api/extension/report", json={
            "task_id": str(sample_task.id),
            "idempotency_key": "idem-key-123",
            "result_type": "task_completed",
            "status": "posted",
            "permalink": "https://reddit.com/r/test/comments/abc/test/xyz",
            "comment_id": "xyz",
            "posted_at": "2026-06-28T10:00:00Z",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["task_id"] == str(sample_task.id)

        # Verify DB state
        db.refresh(sample_task)
        assert sample_task.task_lifecycle_status == "REPORTED"
        assert sample_task.verification_result is not None
        assert sample_task.verification_result["result_type"] == "task_completed"
        assert sample_task.verification_result["permalink"] == "https://reddit.com/r/test/comments/abc/test/xyz"

    def test_duplicate_report_returns_noop(self, ext_client, sample_task, db):
        """Duplicate report on already-reported task returns 200 NOOP."""
        # First report
        sample_task.task_lifecycle_status = "REPORTED"
        db.commit()

        resp = ext_client.post("/api/extension/report", json={
            "task_id": str(sample_task.id),
            "idempotency_key": "idem-key-123",
            "result_type": "task_completed",
            "status": "posted",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "noop"
        assert data["message"] == "Already reported"

    def test_finalized_task_returns_noop(self, ext_client, sample_task, db):
        """Report on finalized task returns 200 NOOP."""
        sample_task.task_lifecycle_status = "FINALIZED"
        db.commit()

        resp = ext_client.post("/api/extension/report", json={
            "task_id": str(sample_task.id),
            "idempotency_key": "idem-key-123",
            "result_type": "task_completed",
            "status": "posted",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "noop"

    def test_idempotency_key_mismatch_returns_400(self, ext_client, sample_task):
        """Wrong idempotency_key returns 400."""
        resp = ext_client.post("/api/extension/report", json={
            "task_id": str(sample_task.id),
            "idempotency_key": "wrong-key",
            "result_type": "task_completed",
            "status": "posted",
        })
        assert resp.status_code == 400
        assert "mismatch" in resp.json()["detail"].lower()

    def test_task_not_found_returns_404(self, ext_client):
        """Unknown task_id returns 404."""
        fake_id = str(uuid.uuid4())
        resp = ext_client.post("/api/extension/report", json={
            "task_id": fake_id,
            "idempotency_key": "some-key",
            "result_type": "task_completed",
            "status": "posted",
        })
        assert resp.status_code == 404

    def test_invalid_task_id_returns_404(self, ext_client):
        """Invalid UUID in task_id returns 404."""
        resp = ext_client.post("/api/extension/report", json={
            "task_id": "not-a-uuid",
            "idempotency_key": "some-key",
            "result_type": "task_completed",
        })
        assert resp.status_code == 404

    def test_probe_result_report(self, ext_client, sample_task, db):
        """Probe result is stored correctly."""
        resp = ext_client.post("/api/extension/report", json={
            "task_id": str(sample_task.id),
            "idempotency_key": "idem-key-123",
            "result_type": "probe_result",
            "probe_type": "reddit_cqs",
            "raw_output": "Your current CQS is **LOW**.",
            "execution_metadata": {"duration_ms": 45000, "reddit_variant": "shreddit"},
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

        db.refresh(sample_task)
        assert sample_task.verification_result["result_type"] == "probe_result"
        assert sample_task.verification_result["probe_type"] == "reddit_cqs"
        assert sample_task.verification_result["raw_output"] == "Your current CQS is **LOW**."

    def test_task_failed_report(self, ext_client, sample_task, db):
        """Failed task report stores error details."""
        resp = ext_client.post("/api/extension/report", json={
            "task_id": str(sample_task.id),
            "idempotency_key": "idem-key-123",
            "result_type": "task_failed",
            "error_code": "account_switch_error",
            "error_details": "Account changed from test_avatar to other_user",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

        db.refresh(sample_task)
        assert sample_task.verification_result["result_type"] == "task_failed"
        assert sample_task.verification_result["error_code"] == "account_switch_error"

    def test_unauthenticated_returns_401(self, db):
        """Request without Bearer token returns 401."""
        def override_get_db():
            yield db
        app.dependency_overrides[get_db] = override_get_db
        try:
            with TestClient(app) as c:
                resp = c.post("/api/extension/report", json={
                    "task_id": str(uuid.uuid4()),
                    "idempotency_key": "key",
                    "result_type": "task_completed",
                })
                assert resp.status_code in (401, 403)
        finally:
            app.dependency_overrides.clear()
