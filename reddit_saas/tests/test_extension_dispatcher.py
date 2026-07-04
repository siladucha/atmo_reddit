"""Tests for extension_dispatcher service — assign_task_to_node, get_available_tasks_for_node, get_pending_tasks_for_node."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.execution_node import ExecutionNode
from app.models.execution_task import ExecutionTask
from app.services.extension_dispatcher import (
    assign_task_to_node,
    get_available_tasks_for_node,
    get_pending_tasks_for_node,
    validate_report,
)


@pytest.fixture
def executor_user(db):
    """Create a user to satisfy FK constraint on execution_nodes."""
    from app.services.auth import create_user
    user = create_user(db, email="ext-dispatcher-test@test.com", password="test123", full_name="Executor")
    user.is_active = True
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def online_node(db, executor_user):
    """Create an online execution node with active Reddit username."""
    node = ExecutionNode(
        id=uuid.uuid4(),
        executor_id=executor_user.id,
        is_online=True,
        active_reddit_username="test_avatar",
        tasks_in_queue=0,
        extension_version="1.0.0",
        last_heartbeat=datetime.now(timezone.utc),
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


@pytest.fixture
def offline_node(db, executor_user):
    """Create an offline execution node."""
    node = ExecutionNode(
        id=uuid.uuid4(),
        executor_id=executor_user.id,
        is_online=False,
        active_reddit_username="test_avatar",
        tasks_in_queue=0,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


@pytest.fixture
def created_task(db):
    """Create an ExecutionTask in CREATED state for extension delivery."""
    task = ExecutionTask(
        id=uuid.uuid4(),
        task_code="EXT-TEST-001",
        executor_token=uuid.uuid4(),
        executor_contact="extension",
        executor_type="admin",
        delivery_channel="extension",
        task_type="post_comment",
        subreddit="test",
        thread_url="https://reddit.com/r/test/comments/abc/test",
        thread_title="Test Thread",
        avatar_username="test_avatar",
        client_name="TestClient",
        generated_text="Test comment text",
        deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
        status="generated",
        task_lifecycle_status="CREATED",
        idempotency_key=str(uuid.uuid4()),
        task_hash="fake-hmac-hash",
        priority="content",
        scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


class TestAssignTaskToNode:
    """Tests for assign_task_to_node()."""

    def test_successful_assignment(self, db, online_node, created_task):
        """Task transitions from CREATED to ASSIGNED with correct fields set."""
        result = assign_task_to_node(db, created_task.id, online_node.id)

        assert result.task_lifecycle_status == "ASSIGNED"
        assert result.execution_node_id == online_node.id
        assert result.lease_expires_at is not None
        # Lease should be ~30 min from now
        expected_lease = datetime.now(timezone.utc) + timedelta(minutes=30)
        assert abs((result.lease_expires_at - expected_lease).total_seconds()) < 5

    def test_task_not_found_raises_error(self, db, online_node):
        """Non-existent task raises ValueError."""
        fake_id = uuid.uuid4()
        with pytest.raises(ValueError, match="not found"):
            assign_task_to_node(db, fake_id, online_node.id)

    def test_task_wrong_state_raises_error(self, db, online_node, created_task):
        """Task not in CREATED state raises ValueError."""
        created_task.task_lifecycle_status = "ASSIGNED"
        db.commit()

        with pytest.raises(ValueError, match="expected 'CREATED'"):
            assign_task_to_node(db, created_task.id, online_node.id)

    def test_node_not_found_raises_error(self, db, created_task):
        """Non-existent node raises ValueError."""
        fake_node_id = uuid.uuid4()
        with pytest.raises(ValueError, match="not found"):
            assign_task_to_node(db, created_task.id, fake_node_id)

    def test_node_offline_raises_error(self, db, offline_node, created_task):
        """Offline node raises ValueError."""
        with pytest.raises(ValueError, match="offline"):
            assign_task_to_node(db, created_task.id, offline_node.id)

    def test_account_mismatch_raises_error(self, db, online_node, created_task):
        """Node username != task avatar_username raises ValueError."""
        online_node.active_reddit_username = "different_user"
        db.commit()

        with pytest.raises(ValueError, match="Account mismatch"):
            assign_task_to_node(db, created_task.id, online_node.id)

    def test_case_insensitive_username_match(self, db, online_node, created_task):
        """Username matching is case-insensitive."""
        online_node.active_reddit_username = "Test_Avatar"
        created_task.avatar_username = "test_avatar"
        db.commit()

        result = assign_task_to_node(db, created_task.id, online_node.id)
        assert result.task_lifecycle_status == "ASSIGNED"

    def test_node_no_username_raises_error(self, db, executor_user, created_task):
        """Node with no active_reddit_username raises ValueError."""
        node = ExecutionNode(
            id=uuid.uuid4(),
            executor_id=executor_user.id,
            is_online=True,
            active_reddit_username=None,
            tasks_in_queue=0,
        )
        db.add(node)
        db.commit()

        with pytest.raises(ValueError, match="no active Reddit username"):
            assign_task_to_node(db, created_task.id, node.id)


class TestGetAvailableTasksForNode:
    """Tests for get_available_tasks_for_node()."""

    def test_returns_matching_tasks(self, db, online_node, created_task):
        """Returns tasks matching node's active_reddit_username."""
        tasks = get_available_tasks_for_node(db, online_node.id)
        assert len(tasks) == 1
        assert tasks[0].id == created_task.id

    def test_node_not_found_raises_error(self, db):
        """Non-existent node raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            get_available_tasks_for_node(db, uuid.uuid4())

    def test_excludes_non_created_tasks(self, db, online_node, created_task):
        """Tasks not in CREATED state are excluded."""
        created_task.task_lifecycle_status = "ASSIGNED"
        db.commit()

        tasks = get_available_tasks_for_node(db, online_node.id)
        assert len(tasks) == 0

    def test_excludes_non_extension_delivery(self, db, online_node, created_task):
        """Tasks with delivery_channel != 'extension' are excluded."""
        created_task.delivery_channel = "email"
        db.commit()

        tasks = get_available_tasks_for_node(db, online_node.id)
        assert len(tasks) == 0

    def test_excludes_different_username(self, db, online_node, created_task):
        """Tasks for different avatar_username are excluded."""
        created_task.avatar_username = "other_avatar"
        db.commit()

        tasks = get_available_tasks_for_node(db, online_node.id)
        assert len(tasks) == 0

    def test_diagnostic_priority_ordering(self, db, online_node):
        """Diagnostic tasks come before content tasks."""
        content_task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="EXT-TEST-C01",
            executor_token=uuid.uuid4(),
            executor_contact="extension",
            delivery_channel="extension",
            task_type="post_comment",
            subreddit="test",
            thread_url="https://reddit.com/r/test/comments/c01/t",
            thread_title="Content Task",
            avatar_username="test_avatar",
            client_name="Client",
            generated_text="Content",
            deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
            status="generated",
            task_lifecycle_status="CREATED",
            idempotency_key=str(uuid.uuid4()),
            priority="content",
            scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        diag_task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="EXT-TEST-D01",
            executor_token=uuid.uuid4(),
            executor_contact="extension",
            delivery_channel="extension",
            task_type="diagnostic_probe",
            probe_type="reddit_cqs",
            subreddit="WhatIsMyCQS",
            thread_url="",
            thread_title="",
            avatar_username="test_avatar",
            client_name="Client",
            generated_text="What is my CQS?",
            deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
            status="generated",
            task_lifecycle_status="CREATED",
            idempotency_key=str(uuid.uuid4()),
            priority="diagnostic",
            scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        db.add_all([content_task, diag_task])
        db.commit()

        tasks = get_available_tasks_for_node(db, online_node.id)
        assert len(tasks) == 2
        assert tasks[0].priority == "diagnostic"
        assert tasks[1].priority == "content"

    def test_scheduled_at_ordering_within_priority(self, db, online_node):
        """Within same priority, tasks are ordered by scheduled_at asc."""
        later = ExecutionTask(
            id=uuid.uuid4(),
            task_code="EXT-TEST-L01",
            executor_token=uuid.uuid4(),
            executor_contact="extension",
            delivery_channel="extension",
            task_type="post_comment",
            subreddit="test",
            thread_url="https://reddit.com/r/test/l01",
            thread_title="Later",
            avatar_username="test_avatar",
            client_name="Client",
            generated_text="Later",
            deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
            status="generated",
            task_lifecycle_status="CREATED",
            idempotency_key=str(uuid.uuid4()),
            priority="content",
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )
        earlier = ExecutionTask(
            id=uuid.uuid4(),
            task_code="EXT-TEST-E01",
            executor_token=uuid.uuid4(),
            executor_contact="extension",
            delivery_channel="extension",
            task_type="post_comment",
            subreddit="test",
            thread_url="https://reddit.com/r/test/e01",
            thread_title="Earlier",
            avatar_username="test_avatar",
            client_name="Client",
            generated_text="Earlier",
            deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
            status="generated",
            task_lifecycle_status="CREATED",
            idempotency_key=str(uuid.uuid4()),
            priority="content",
            scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        db.add_all([later, earlier])
        db.commit()

        tasks = get_available_tasks_for_node(db, online_node.id)
        assert len(tasks) == 2
        assert tasks[0].task_code == "EXT-TEST-E01"
        assert tasks[1].task_code == "EXT-TEST-L01"

    def test_no_username_on_node_returns_empty(self, db, executor_user):
        """Node with no active_reddit_username returns empty list."""
        node = ExecutionNode(
            id=uuid.uuid4(),
            executor_id=executor_user.id,
            is_online=True,
            active_reddit_username=None,
            tasks_in_queue=0,
        )
        db.add(node)
        db.commit()

        tasks = get_available_tasks_for_node(db, node.id)
        assert tasks == []

    def test_case_insensitive_username_matching(self, db, online_node):
        """Username matching for task filtering is case-insensitive."""
        task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="EXT-TEST-CI1",
            executor_token=uuid.uuid4(),
            executor_contact="extension",
            delivery_channel="extension",
            task_type="post_comment",
            subreddit="test",
            thread_url="https://reddit.com/r/test/ci1",
            thread_title="Case Test",
            avatar_username="Test_Avatar",  # Mixed case
            client_name="Client",
            generated_text="Test",
            deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
            status="generated",
            task_lifecycle_status="CREATED",
            idempotency_key=str(uuid.uuid4()),
            priority="content",
            scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db.add(task)
        db.commit()

        # Node has lowercase "test_avatar"
        tasks = get_available_tasks_for_node(db, online_node.id)
        assert len(tasks) == 1


class TestValidateReport:
    """Tests for validate_report()."""

    @pytest.fixture
    def reported_task(self, db):
        """Create an ExecutionTask in REPORTED state."""
        from app.services.extension_dispatcher import validate_report  # noqa: F401

        idem_key = str(uuid.uuid4())
        task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="EXT-RPT-001",
            executor_token=uuid.uuid4(),
            executor_contact="extension",
            executor_type="admin",
            delivery_channel="extension",
            task_type="post_comment",
            subreddit="test",
            thread_url="https://reddit.com/r/test/comments/abc/test",
            thread_title="Test Thread",
            avatar_username="test_avatar",
            client_name="TestClient",
            generated_text="Test comment text",
            deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
            status="generated",
            task_lifecycle_status="REPORTED",
            idempotency_key=idem_key,
            task_hash="fake-hmac-hash",
            priority="content",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    def test_successful_finalization(self, db, reported_task):
        """Task transitions from REPORTED to FINALIZED with report_data stored."""
        from app.services.extension_dispatcher import validate_report

        report_data = {"permalink": "https://reddit.com/r/test/comments/abc/test/xyz"}
        result = validate_report(db, reported_task.id, reported_task.idempotency_key, report_data)

        assert result.task_lifecycle_status == "FINALIZED"
        assert result.verification_result == report_data

    def test_idempotent_when_already_finalized(self, db, reported_task):
        """If task is already FINALIZED, returns it as-is (idempotent)."""
        from app.services.extension_dispatcher import validate_report

        reported_task.task_lifecycle_status = "FINALIZED"
        reported_task.verification_result = {"previous": "data"}
        db.commit()

        result = validate_report(db, reported_task.id, reported_task.idempotency_key, {"new": "data"})
        assert result.task_lifecycle_status == "FINALIZED"
        # Should NOT merge new data — just return as-is
        assert result.verification_result == {"previous": "data"}

    def test_task_not_found_raises_error(self, db):
        """Non-existent task raises ValueError."""
        from app.services.extension_dispatcher import validate_report

        with pytest.raises(ValueError, match="not found"):
            validate_report(db, uuid.uuid4(), "some-key", {})

    def test_wrong_state_raises_error(self, db, reported_task):
        """Task not in REPORTED or FINALIZED state raises ValueError."""
        from app.services.extension_dispatcher import validate_report

        reported_task.task_lifecycle_status = "ASSIGNED"
        db.commit()

        with pytest.raises(ValueError, match="expected 'REPORTED'"):
            validate_report(db, reported_task.id, reported_task.idempotency_key, {})

    def test_key_mismatch_raises_error(self, db, reported_task):
        """Mismatched idempotency_key raises ValueError."""
        from app.services.extension_dispatcher import validate_report

        with pytest.raises(ValueError, match="Idempotency key mismatch"):
            validate_report(db, reported_task.id, "wrong-key", {})

    def test_merges_with_existing_verification_result(self, db, reported_task):
        """report_data is merged with existing verification_result."""
        from app.services.extension_dispatcher import validate_report

        reported_task.verification_result = {"existing_field": "value1"}
        db.commit()

        report_data = {"new_field": "value2"}
        result = validate_report(db, reported_task.id, reported_task.idempotency_key, report_data)

        assert result.verification_result == {"existing_field": "value1", "new_field": "value2"}

    def test_report_data_overwrites_conflicting_keys(self, db, reported_task):
        """When merge has conflicting keys, report_data wins."""
        from app.services.extension_dispatcher import validate_report

        reported_task.verification_result = {"status": "partial", "old_key": "keep"}
        db.commit()

        report_data = {"status": "complete", "new_key": "added"}
        result = validate_report(db, reported_task.id, reported_task.idempotency_key, report_data)

        assert result.verification_result == {"status": "complete", "old_key": "keep", "new_key": "added"}



class TestExpireStaleLeases:
    """Tests for expire_stale_leases()."""

    def test_expires_assigned_task_past_lease(self, db, online_node):
        """ASSIGNED task with lease_expires_at in the past gets expired."""
        from app.services.extension_dispatcher import expire_stale_leases

        task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="EXT-EXP-001",
            executor_token=uuid.uuid4(),
            executor_contact="extension",
            delivery_channel="extension",
            task_type="post_comment",
            subreddit="test",
            thread_url="https://reddit.com/r/test/comments/exp/test",
            thread_title="Expire Test",
            avatar_username="test_avatar",
            client_name="TestClient",
            generated_text="Test comment",
            deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
            status="generated",
            task_lifecycle_status="ASSIGNED",
            idempotency_key=str(uuid.uuid4()),
            task_hash="fake-hmac",
            priority="content",
            execution_node_id=online_node.id,
            lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        db.add(task)
        db.commit()

        expired = expire_stale_leases(db)

        assert len(expired) == 1
        assert expired[0].id == task.id
        assert expired[0].task_lifecycle_status == "EXPIRED"
        assert expired[0].execution_node_id is None

    def test_expires_executing_task_past_lease(self, db, online_node):
        """EXECUTING task with lease_expires_at in the past gets expired."""
        from app.services.extension_dispatcher import expire_stale_leases

        task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="EXT-EXP-002",
            executor_token=uuid.uuid4(),
            executor_contact="extension",
            delivery_channel="extension",
            task_type="diagnostic_probe",
            probe_type="reddit_cqs",
            subreddit="WhatIsMyCQS",
            thread_url="",
            thread_title="",
            avatar_username="test_avatar",
            client_name="TestClient",
            generated_text="What is my CQS?",
            deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
            status="generated",
            task_lifecycle_status="EXECUTING",
            idempotency_key=str(uuid.uuid4()),
            task_hash="fake-hmac",
            priority="diagnostic",
            execution_node_id=online_node.id,
            lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db.add(task)
        db.commit()

        expired = expire_stale_leases(db)

        assert len(expired) == 1
        assert expired[0].task_lifecycle_status == "EXPIRED"
        assert expired[0].execution_node_id is None

    def test_does_not_expire_task_with_future_lease(self, db, online_node):
        """Task with lease_expires_at in the future is not expired."""
        from app.services.extension_dispatcher import expire_stale_leases

        task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="EXT-EXP-003",
            executor_token=uuid.uuid4(),
            executor_contact="extension",
            delivery_channel="extension",
            task_type="post_comment",
            subreddit="test",
            thread_url="https://reddit.com/r/test/comments/noexp/test",
            thread_title="No Expire",
            avatar_username="test_avatar",
            client_name="TestClient",
            generated_text="Test",
            deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
            status="generated",
            task_lifecycle_status="ASSIGNED",
            idempotency_key=str(uuid.uuid4()),
            task_hash="fake-hmac",
            priority="content",
            execution_node_id=online_node.id,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=25),
        )
        db.add(task)
        db.commit()

        expired = expire_stale_leases(db)

        assert len(expired) == 0
        db.refresh(task)
        assert task.task_lifecycle_status == "ASSIGNED"
        assert task.execution_node_id == online_node.id

    def test_does_not_expire_tasks_in_other_states(self, db, online_node):
        """Tasks in CREATED, REPORTED, FINALIZED, FAILED states are not expired."""
        from app.services.extension_dispatcher import expire_stale_leases

        past_lease = datetime.now(timezone.utc) - timedelta(minutes=10)
        for i, status in enumerate(["CREATED", "REPORTED", "FINALIZED", "FAILED"]):
            task = ExecutionTask(
                id=uuid.uuid4(),
                task_code=f"EXT-EXP-S{i}",
                executor_token=uuid.uuid4(),
                executor_contact="extension",
                delivery_channel="extension",
                task_type="post_comment",
                subreddit="test",
                thread_url=f"https://reddit.com/r/test/s{i}",
                thread_title="State Test",
                avatar_username="test_avatar",
                client_name="TestClient",
                generated_text="Test",
                deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
                status="generated",
                task_lifecycle_status=status,
                idempotency_key=str(uuid.uuid4()),
                task_hash="fake-hmac",
                priority="content",
                execution_node_id=online_node.id,
                lease_expires_at=past_lease,
            )
            db.add(task)
        db.commit()

        expired = expire_stale_leases(db)

        assert len(expired) == 0

    def test_returns_empty_list_when_no_stale_tasks(self, db):
        """Returns empty list when no tasks match the criteria."""
        from app.services.extension_dispatcher import expire_stale_leases

        expired = expire_stale_leases(db)
        assert expired == []

    def test_expires_multiple_stale_tasks(self, db, online_node):
        """Multiple stale tasks are all expired in one call."""
        from app.services.extension_dispatcher import expire_stale_leases

        past_lease = datetime.now(timezone.utc) - timedelta(minutes=10)
        tasks = []
        for i in range(3):
            task = ExecutionTask(
                id=uuid.uuid4(),
                task_code=f"EXT-EXP-M{i}",
                executor_token=uuid.uuid4(),
                executor_contact="extension",
                delivery_channel="extension",
                task_type="post_comment",
                subreddit="test",
                thread_url=f"https://reddit.com/r/test/m{i}",
                thread_title=f"Multi {i}",
                avatar_username="test_avatar",
                client_name="TestClient",
                generated_text="Test",
                deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
                status="generated",
                task_lifecycle_status="ASSIGNED" if i % 2 == 0 else "EXECUTING",
                idempotency_key=str(uuid.uuid4()),
                task_hash="fake-hmac",
                priority="content",
                execution_node_id=online_node.id,
                lease_expires_at=past_lease,
            )
            tasks.append(task)
            db.add(task)
        db.commit()

        expired = expire_stale_leases(db)

        assert len(expired) == 3
        for t in expired:
            assert t.task_lifecycle_status == "EXPIRED"
            assert t.execution_node_id is None



class TestRouteTask:
    """Tests for route_task()."""

    def test_routes_to_extension_when_online_node_matches(self, db, online_node, created_task):
        """Returns 'extension' when an online node with matching username exists."""
        from app.services.extension_dispatcher import route_task

        result = route_task(db, created_task)

        assert result == "extension"
        # Task should now be ASSIGNED
        db.refresh(created_task)
        assert created_task.task_lifecycle_status == "ASSIGNED"
        assert created_task.execution_node_id == online_node.id

    def test_returns_hold_when_no_online_node_and_task_recent(self, db, created_task):
        """Returns 'hold' when no matching node exists and task is recent (<30 min)."""
        from app.services.extension_dispatcher import route_task

        # Task was just created — no node available
        result = route_task(db, created_task)

        assert result == "hold"
        # Task remains in CREATED
        db.refresh(created_task)
        assert created_task.task_lifecycle_status == "CREATED"

    def test_returns_email_fallback_when_task_old(self, db, created_task):
        """Returns 'email_fallback' when task in CREATED for >30 min and no node online."""
        from app.services.extension_dispatcher import route_task

        # Make task old (created 31+ min ago)
        created_task.created_at = datetime.now(timezone.utc) - timedelta(minutes=31)
        db.commit()

        result = route_task(db, created_task)

        assert result == "email_fallback"

    def test_ignores_offline_node(self, db, offline_node, created_task):
        """Offline nodes are not considered even if username matches."""
        from app.services.extension_dispatcher import route_task

        result = route_task(db, created_task)
        assert result == "hold"

    def test_ignores_stale_heartbeat_node(self, db, executor_user, created_task):
        """Nodes with heartbeat >30 min old are treated as offline."""
        from app.services.extension_dispatcher import route_task

        # Node is is_online=True but heartbeat is stale
        stale_node = ExecutionNode(
            id=uuid.uuid4(),
            executor_id=executor_user.id,
            is_online=True,
            active_reddit_username="test_avatar",
            tasks_in_queue=0,
            last_heartbeat=datetime.now(timezone.utc) - timedelta(minutes=31),
        )
        db.add(stale_node)
        db.commit()

        result = route_task(db, created_task)
        assert result == "hold"

    def test_case_insensitive_username_matching(self, db, executor_user, created_task):
        """Username matching is case-insensitive."""
        from app.services.extension_dispatcher import route_task

        # Node has different casing
        node = ExecutionNode(
            id=uuid.uuid4(),
            executor_id=executor_user.id,
            is_online=True,
            active_reddit_username="Test_Avatar",  # Mixed case
            tasks_in_queue=0,
            last_heartbeat=datetime.now(timezone.utc),
        )
        db.add(node)
        db.commit()

        # Task has lowercase "test_avatar"
        result = route_task(db, created_task)
        assert result == "extension"

    def test_ignores_node_with_different_username(self, db, executor_user, created_task):
        """Node with different username is not considered."""
        from app.services.extension_dispatcher import route_task

        node = ExecutionNode(
            id=uuid.uuid4(),
            executor_id=executor_user.id,
            is_online=True,
            active_reddit_username="other_user",
            tasks_in_queue=0,
            last_heartbeat=datetime.now(timezone.utc),
        )
        db.add(node)
        db.commit()

        result = route_task(db, created_task)
        assert result == "hold"

    def test_ignores_node_with_no_username(self, db, executor_user, created_task):
        """Node with NULL active_reddit_username is not considered."""
        from app.services.extension_dispatcher import route_task

        node = ExecutionNode(
            id=uuid.uuid4(),
            executor_id=executor_user.id,
            is_online=True,
            active_reddit_username=None,
            tasks_in_queue=0,
            last_heartbeat=datetime.now(timezone.utc),
        )
        db.add(node)
        db.commit()

        result = route_task(db, created_task)
        assert result == "hold"

    def test_email_fallback_boundary_exactly_30_min(self, db, created_task):
        """Task at exactly 30 min boundary does NOT trigger email_fallback (needs >30 min)."""
        from app.services.extension_dispatcher import route_task

        # Set created_at to exactly 30 min ago
        created_task.created_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        db.commit()

        result = route_task(db, created_task)
        # At exactly 30 min, created_at <= threshold should be True (<=)
        # The check is: task.created_at <= created_threshold where threshold = now - 30min
        # If created_at == now - 30min and threshold == now - 30min, it's <=, so email_fallback
        assert result == "email_fallback"


class TestGetPendingTasksForNode:
    """Tests for get_pending_tasks_for_node()."""

    def test_returns_created_tasks_for_node_username(self, db, online_node):
        """Returns CREATED tasks matching node's active_reddit_username."""
        task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="EXT-PEND-001",
            executor_token=uuid.uuid4(),
            executor_contact="extension",
            delivery_channel="extension",
            task_type="post_comment",
            subreddit="test",
            thread_url="https://reddit.com/r/test/comments/abc/test",
            thread_title="Test",
            avatar_username="test_avatar",
            client_name="Client",
            generated_text="Hello",
            deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
            status="generated",
            task_lifecycle_status="CREATED",
            idempotency_key=str(uuid.uuid4()),
            priority="content",
            scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        db.add(task)
        db.commit()

        tasks = get_pending_tasks_for_node(db, online_node)
        assert len(tasks) == 1
        assert tasks[0].id == task.id

    def test_diagnostic_tasks_ordered_before_content(self, db, online_node):
        """Diagnostic tasks (priority='diagnostic') come before content tasks."""
        content_task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="EXT-PEND-C01",
            executor_token=uuid.uuid4(),
            executor_contact="extension",
            delivery_channel="extension",
            task_type="post_comment",
            subreddit="test",
            thread_url="https://reddit.com/r/test/c01",
            thread_title="Content",
            avatar_username="test_avatar",
            client_name="Client",
            generated_text="Content comment",
            deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
            status="generated",
            task_lifecycle_status="CREATED",
            idempotency_key=str(uuid.uuid4()),
            priority="content",
            scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        diag_task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="EXT-PEND-D01",
            executor_token=uuid.uuid4(),
            executor_contact="extension",
            delivery_channel="extension",
            task_type="diagnostic_probe",
            probe_type="reddit_cqs",
            subreddit="WhatIsMyCQS",
            thread_url="",
            thread_title="",
            avatar_username="test_avatar",
            client_name="Client",
            generated_text="What is my CQS?",
            deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
            status="generated",
            task_lifecycle_status="CREATED",
            idempotency_key=str(uuid.uuid4()),
            priority="diagnostic",
            # Scheduled LATER, but should still come first due to priority
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )
        db.add_all([content_task, diag_task])
        db.commit()

        tasks = get_pending_tasks_for_node(db, online_node)
        assert len(tasks) == 2
        assert tasks[0].priority == "diagnostic"
        assert tasks[1].priority == "content"

    def test_null_scheduled_at_treated_as_immediate(self, db, online_node):
        """Tasks with NULL scheduled_at are sorted before those with a future scheduled_at."""
        future_task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="EXT-PEND-F01",
            executor_token=uuid.uuid4(),
            executor_contact="extension",
            delivery_channel="extension",
            task_type="post_comment",
            subreddit="test",
            thread_url="https://reddit.com/r/test/f01",
            thread_title="Future",
            avatar_username="test_avatar",
            client_name="Client",
            generated_text="Future",
            deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
            status="generated",
            task_lifecycle_status="CREATED",
            idempotency_key=str(uuid.uuid4()),
            priority="content",
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        immediate_task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="EXT-PEND-I01",
            executor_token=uuid.uuid4(),
            executor_contact="extension",
            delivery_channel="extension",
            task_type="post_comment",
            subreddit="test",
            thread_url="https://reddit.com/r/test/i01",
            thread_title="Immediate",
            avatar_username="test_avatar",
            client_name="Client",
            generated_text="Immediate",
            deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
            status="generated",
            task_lifecycle_status="CREATED",
            idempotency_key=str(uuid.uuid4()),
            priority="content",
            scheduled_at=None,  # NULL = immediate
        )
        db.add_all([future_task, immediate_task])
        db.commit()

        tasks = get_pending_tasks_for_node(db, online_node)
        assert len(tasks) == 2
        assert tasks[0].task_code == "EXT-PEND-I01"  # NULL scheduled_at first
        assert tasks[1].task_code == "EXT-PEND-F01"

    def test_scheduled_at_ascending_within_same_priority(self, db, online_node):
        """Within the same priority, tasks ordered by scheduled_at ascending."""
        later = ExecutionTask(
            id=uuid.uuid4(),
            task_code="EXT-PEND-L01",
            executor_token=uuid.uuid4(),
            executor_contact="extension",
            delivery_channel="extension",
            task_type="post_comment",
            subreddit="test",
            thread_url="https://reddit.com/r/test/l01",
            thread_title="Later",
            avatar_username="test_avatar",
            client_name="Client",
            generated_text="Later",
            deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
            status="generated",
            task_lifecycle_status="CREATED",
            idempotency_key=str(uuid.uuid4()),
            priority="content",
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=3),
        )
        earlier = ExecutionTask(
            id=uuid.uuid4(),
            task_code="EXT-PEND-E01",
            executor_token=uuid.uuid4(),
            executor_contact="extension",
            delivery_channel="extension",
            task_type="post_comment",
            subreddit="test",
            thread_url="https://reddit.com/r/test/e01",
            thread_title="Earlier",
            avatar_username="test_avatar",
            client_name="Client",
            generated_text="Earlier",
            deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
            status="generated",
            task_lifecycle_status="CREATED",
            idempotency_key=str(uuid.uuid4()),
            priority="content",
            scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        db.add_all([later, earlier])
        db.commit()

        tasks = get_pending_tasks_for_node(db, online_node)
        assert len(tasks) == 2
        assert tasks[0].task_code == "EXT-PEND-E01"
        assert tasks[1].task_code == "EXT-PEND-L01"

    def test_excludes_non_created_tasks(self, db, online_node):
        """Only CREATED tasks are returned; ASSIGNED, EXPIRED, etc. are excluded."""
        assigned_task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="EXT-PEND-A01",
            executor_token=uuid.uuid4(),
            executor_contact="extension",
            delivery_channel="extension",
            task_type="post_comment",
            subreddit="test",
            thread_url="https://reddit.com/r/test/a01",
            thread_title="Assigned",
            avatar_username="test_avatar",
            client_name="Client",
            generated_text="Assigned",
            deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
            status="generated",
            task_lifecycle_status="ASSIGNED",
            idempotency_key=str(uuid.uuid4()),
            priority="content",
        )
        db.add(assigned_task)
        db.commit()

        tasks = get_pending_tasks_for_node(db, online_node)
        assert len(tasks) == 0

    def test_case_insensitive_username_match(self, db, online_node):
        """Username matching is case-insensitive."""
        task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="EXT-PEND-CI1",
            executor_token=uuid.uuid4(),
            executor_contact="extension",
            delivery_channel="extension",
            task_type="post_comment",
            subreddit="test",
            thread_url="https://reddit.com/r/test/ci1",
            thread_title="Case",
            avatar_username="Test_Avatar",  # Mixed case
            client_name="Client",
            generated_text="Case test",
            deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
            status="generated",
            task_lifecycle_status="CREATED",
            idempotency_key=str(uuid.uuid4()),
            priority="content",
        )
        db.add(task)
        db.commit()

        # online_node has active_reddit_username="test_avatar" (lowercase)
        tasks = get_pending_tasks_for_node(db, online_node)
        assert len(tasks) == 1

    def test_no_active_username_returns_empty(self, db, executor_user):
        """Node with no active_reddit_username returns empty list."""
        node = ExecutionNode(
            id=uuid.uuid4(),
            executor_id=executor_user.id,
            is_online=True,
            active_reddit_username=None,
            tasks_in_queue=0,
        )
        db.add(node)
        db.commit()

        tasks = get_pending_tasks_for_node(db, node)
        assert tasks == []

    def test_respects_limit_parameter(self, db, online_node):
        """Returns at most `limit` tasks."""
        for i in range(5):
            task = ExecutionTask(
                id=uuid.uuid4(),
                task_code=f"EXT-PEND-LIM{i:02d}",
                executor_token=uuid.uuid4(),
                executor_contact="extension",
                delivery_channel="extension",
                task_type="post_comment",
                subreddit="test",
                thread_url=f"https://reddit.com/r/test/lim{i}",
                thread_title=f"Limit {i}",
                avatar_username="test_avatar",
                client_name="Client",
                generated_text=f"Task {i}",
                deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
                status="generated",
                task_lifecycle_status="CREATED",
                idempotency_key=str(uuid.uuid4()),
                priority="content",
                scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=i * 5),
            )
            db.add(task)
        db.commit()

        tasks = get_pending_tasks_for_node(db, online_node, limit=3)
        assert len(tasks) == 3

    def test_does_not_filter_by_delivery_channel(self, db, online_node):
        """Unlike get_available_tasks_for_node, this does NOT filter by delivery_channel."""
        email_task = ExecutionTask(
            id=uuid.uuid4(),
            task_code="EXT-PEND-EM1",
            executor_token=uuid.uuid4(),
            executor_contact="email@test.com",
            delivery_channel="email",  # email channel, not extension
            task_type="post_comment",
            subreddit="test",
            thread_url="https://reddit.com/r/test/em1",
            thread_title="Email Task",
            avatar_username="test_avatar",
            client_name="Client",
            generated_text="Email task",
            deadline=datetime(2099, 12, 31, tzinfo=timezone.utc),
            status="generated",
            task_lifecycle_status="CREATED",
            idempotency_key=str(uuid.uuid4()),
            priority="content",
        )
        db.add(email_task)
        db.commit()

        tasks = get_pending_tasks_for_node(db, online_node)
        assert len(tasks) == 1
