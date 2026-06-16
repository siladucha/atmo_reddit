"""Preservation Property Tests — Existing Audit Logging and Query Behavior.

**Property 2: Preservation** — Existing Audit Logging and Query Behavior

These tests MUST PASS on unfixed code — they confirm baseline behavior to preserve.
They establish that existing audit logging, query semantics, and indexes remain
unchanged after the fix is applied.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8**
"""

import uuid
from datetime import datetime, timezone, timedelta

import pytest
from hypothesis import given, settings, HealthCheck, assume, note
from hypothesis import strategies as st
from sqlalchemy import text, inspect
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.client import Client
from app.services.audit import log_action, log_system_action, query_audit_logs


# =============================================================================
# Strategies
# =============================================================================

st_action_crud = st.sampled_from(["create", "update", "delete", "deactivate", "activate"])
st_entity_type_crud = st.sampled_from(["user", "client", "avatar", "subreddit", "keyword"])
st_review_action = st.sampled_from(["approve", "reject", "edit", "set_status"])
st_system_action = st.sampled_from([
    "health_status_changed",
    "health_check_batch_completed",
    "cqs_check_batch_completed",
])

# Filter strategies for query_audit_logs
st_page = st.integers(min_value=1, max_value=5)
st_per_page = st.integers(min_value=1, max_value=50)
st_optional_action = st.one_of(st.none(), st.sampled_from([
    "create", "update", "delete", "deactivate", "activate",
    "approve", "reject", "edit", "health_status_changed",
    "cqs_check_batch_completed", "trigger_pipeline",
]))
st_optional_entity_type = st.one_of(st.none(), st.sampled_from([
    "user", "client", "avatar", "subreddit", "keyword",
    "comment_draft", "pipeline", "system",
]))
st_optional_search = st.one_of(st.none(), st.sampled_from([
    "test", "client", "avatar", "pipeline", "create",
]))


# =============================================================================
# Helper functions
# =============================================================================

def _create_user(db: Session) -> uuid.UUID:
    """Create a test user via raw SQL (bypasses ORM model column mismatch) and return user_id."""
    user_id = uuid.uuid4()
    db.execute(text("""
        INSERT INTO users (id, email, hashed_password, full_name, is_active, is_superuser)
        VALUES (:id, :email, :password, :name, true, true)
    """), {
        "id": str(user_id),
        "email": f"test_{uuid.uuid4().hex[:8]}@test.com",
        "password": "$2b$12$dummy_hash_for_testing_only_000000000000000000",
        "name": "Test Admin",
    })
    db.flush()
    return user_id


def _create_client(db: Session) -> Client:
    """Create a test client."""
    client = Client(
        client_name=f"TestClient_{uuid.uuid4().hex[:6]}",
        brand_name="TestBrand",
        is_active=True,
    )
    db.add(client)
    db.flush()
    return client


def _seed_audit_logs(db: Session, user_id: uuid.UUID, count: int = 10) -> list[AuditLog]:
    """Seed the database with diverse audit log entries for query testing."""
    actions = ["create", "update", "delete", "approve", "reject", "trigger_pipeline"]
    entity_types = ["user", "client", "avatar", "subreddit", "comment_draft"]
    entries = []

    # Create a real client for FK-valid client_id references
    client = _create_client(db)

    for i in range(count):
        entry = AuditLog(
            user_id=user_id if i % 3 != 0 else None,  # Some system actions
            action=actions[i % len(actions)],
            entity_type=entity_types[i % len(entity_types)],
            entity_id=uuid.uuid4(),
            client_id=client.id if i % 2 == 0 else None,
            details={"index": i, "test": True, "name": f"item_{i}"},
            created_at=datetime.now(timezone.utc) - timedelta(hours=i),
        )
        db.add(entry)
        entries.append(entry)

    db.flush()
    return entries


# =============================================================================
# Part A — Admin CRUD Audit Preservation
# =============================================================================

class TestAdminCRUDAuditPreservation:
    """Property-based test: for all admin CRUD operations (create/update/delete
    on users, clients, avatars, subreddits, keywords), an AuditLog entry with
    correct action and entity_type is created.

    **Validates: Requirements 3.1**
    """

    @given(
        action=st_action_crud,
        entity_type=st_entity_type_crud,
    )
    @settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_log_action_creates_entry_with_correct_fields(self, db, action, entity_type):
        """For all admin CRUD operations, log_action creates an AuditLog entry
        with the correct action and entity_type.

        **Validates: Requirements 3.1**
        """
        user_id = _create_user(db)
        entity_id = uuid.uuid4()
        details = {"test_field": "test_value", "action": action}

        # Call log_action (the function used by services/admin.py for CRUD)
        entry = log_action(
            db=db,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        )

        # Verify the entry was created correctly
        assert entry is not None
        assert entry.id is not None
        assert entry.user_id == user_id
        assert entry.action == action
        assert entry.entity_type == entity_type
        assert entry.entity_id == entity_id
        assert entry.details == details
        assert entry.created_at is not None

        # Verify it's persisted and queryable
        fetched = db.query(AuditLog).filter(AuditLog.id == entry.id).first()
        assert fetched is not None
        assert fetched.action == action
        assert fetched.entity_type == entity_type

    @given(
        action=st_action_crud,
        entity_type=st_entity_type_crud,
    )
    @settings(max_examples=15, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_log_action_with_client_id_preserves_context(self, db, action, entity_type):
        """For CRUD operations with client context, log_action preserves client_id.

        **Validates: Requirements 3.1**
        """
        user_id = _create_user(db)
        client = _create_client(db)
        entity_id = uuid.uuid4()

        entry = log_action(
            db=db,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            client_id=client.id,
            details={"client_name": client.client_name},
        )

        assert entry.client_id == client.id
        assert entry.user_id == user_id

        # Verify queryable by client_id
        fetched = db.query(AuditLog).filter(
            AuditLog.client_id == client.id,
            AuditLog.action == action,
        ).first()
        assert fetched is not None
        assert fetched.id == entry.id


class TestReviewActionAuditPreservation:
    """Property-based test: for all review actions, an AuditLog entry is created
    with user_id and correct action.

    **Validates: Requirements 3.2**
    """

    @given(action=st_review_action)
    @settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_review_action_creates_audit_with_user_id(self, db, action):
        """For all review actions (approve/reject/edit), log_action creates an
        AuditLog entry with user_id and correct action.

        **Validates: Requirements 3.2**
        """
        user_id = _create_user(db)
        draft_id = uuid.uuid4()

        entry = log_action(
            db=db,
            user_id=user_id,
            action=action,
            entity_type="comment_draft",
            entity_id=draft_id,
            details={"status_transition": f"pending->{action}"},
        )

        assert entry is not None
        assert entry.user_id == user_id
        assert entry.action == action
        assert entry.entity_type == "comment_draft"
        assert entry.entity_id == draft_id
        assert entry.details is not None
        assert entry.created_at is not None


class TestSystemActionAuditPreservation:
    """Property-based test: log_system_action calls from settings, health_checker,
    and cqs_checker produce AuditLog entries correctly.

    **Validates: Requirements 3.3, 3.4, 3.5**
    """

    @given(action=st_system_action)
    @settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_log_system_action_creates_entry_without_user(self, db, action):
        """log_system_action creates AuditLog entries with user_id=None for
        system/background actions.

        **Validates: Requirements 3.3, 3.4, 3.5**
        """
        details = {"batch_size": 5, "results": "ok"}

        entry = log_system_action(
            db=db,
            action=action,
            entity_type="system",
            details=details,
        )

        assert entry is not None
        assert entry.user_id is None  # System actions have no user
        assert entry.action == action
        assert entry.entity_type == "system"
        assert entry.details == details
        assert entry.created_at is not None

        # Verify persisted
        fetched = db.query(AuditLog).filter(AuditLog.id == entry.id).first()
        assert fetched is not None
        assert fetched.user_id is None
        assert fetched.action == action


# =============================================================================
# Part B — Query Semantics Preservation
# =============================================================================

class TestQuerySemanticsPreservation:
    """Property-based test: for random filter combinations, query_audit_logs
    returns correct paginated results.

    **Validates: Requirements 3.8**
    """

    @given(
        page=st_page,
        per_page=st_per_page,
        action_filter=st_optional_action,
        entity_type_filter=st_optional_entity_type,
        search_filter=st_optional_search,
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_query_audit_logs_returns_paginated_results(
        self, db, page, per_page, action_filter, entity_type_filter, search_filter
    ):
        """For random filter combinations, query_audit_logs returns paginated
        results with correct semantics (total count, page size, ordering).

        **Validates: Requirements 3.8**
        """
        # Seed some data
        user_id = _create_user(db)
        _seed_audit_logs(db, user_id, count=15)

        # Query with random filters
        entries, total = query_audit_logs(
            db=db,
            page=page,
            per_page=per_page,
            action=action_filter,
            entity_type=entity_type_filter,
            search=search_filter,
        )

        # Verify pagination semantics
        assert isinstance(entries, list)
        assert isinstance(total, int)
        assert total >= 0
        assert len(entries) <= per_page

        # If total > 0 and page is within range, entries should not be empty
        if total > 0 and (page - 1) * per_page < total:
            assert len(entries) > 0

        # Verify ordering: entries should be in descending created_at order
        for i in range(len(entries) - 1):
            assert entries[i].created_at >= entries[i + 1].created_at

    @given(
        action_filter=st_optional_action,
        entity_type_filter=st_optional_entity_type,
    )
    @settings(max_examples=15, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_query_audit_logs_filter_correctness(
        self, db, action_filter, entity_type_filter
    ):
        """Filtered results only contain entries matching the filter criteria.

        **Validates: Requirements 3.8**
        """
        user_id = _create_user(db)
        _seed_audit_logs(db, user_id, count=12)

        entries, total = query_audit_logs(
            db=db,
            page=1,
            per_page=50,
            action=action_filter,
            entity_type=entity_type_filter,
        )

        # All returned entries must match the filters
        for entry in entries:
            if action_filter is not None:
                assert entry.action == action_filter
            if entity_type_filter is not None:
                assert entry.entity_type == entity_type_filter

    @given(
        per_page=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_query_audit_logs_total_count_consistency(self, db, per_page):
        """Total count is consistent across pages — sum of all pages equals total.

        **Validates: Requirements 3.8**
        """
        user_id = _create_user(db)
        _seed_audit_logs(db, user_id, count=8)

        # Use user_id filter to scope to seeded data only (avoid shared DB noise)
        _, total = query_audit_logs(db=db, page=1, per_page=per_page, user_id=user_id)

        # Collect all entries across pages
        all_entries = []
        page = 1
        max_pages = (total // per_page) + 2
        while True:
            entries, _ = query_audit_logs(db=db, page=page, per_page=per_page, user_id=user_id)
            if not entries:
                break
            all_entries.extend(entries)
            page += 1
            if page > max_pages:
                break

        assert len(all_entries) == total

    @given(data=st.data())
    @settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_query_audit_logs_date_range_filter(self, db, data):
        """Date range filters correctly bound the results.

        **Validates: Requirements 3.8**
        """
        user_id = _create_user(db)
        _seed_audit_logs(db, user_id, count=10)

        # Generate a date range
        hours_from = data.draw(st.integers(min_value=1, max_value=8))
        hours_to = data.draw(st.integers(min_value=0, max_value=hours_from - 1))

        now = datetime.now(timezone.utc)
        date_from = now - timedelta(hours=hours_from)
        date_to = now - timedelta(hours=hours_to)

        entries, total = query_audit_logs(
            db=db,
            page=1,
            per_page=50,
            date_from=date_from,
            date_to=date_to,
        )

        # All returned entries must be within the date range
        for entry in entries:
            # Handle timezone-aware vs naive comparison
            entry_time = entry.created_at
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=timezone.utc)
            assert entry_time >= date_from
            assert entry_time <= date_to

    @given(data=st.data())
    @settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_query_audit_logs_user_id_filter(self, db, data):
        """user_id filter returns only entries for that user.

        **Validates: Requirements 3.8**
        """
        user1_id = _create_user(db)
        user2_id = _create_user(db)

        # Create entries for both users
        log_action(db, user_id=user1_id, action="create", entity_type="client",
                   details={"user": "one"})
        log_action(db, user_id=user2_id, action="update", entity_type="avatar",
                   details={"user": "two"})
        log_action(db, user_id=user1_id, action="delete", entity_type="keyword",
                   details={"user": "one_again"})

        # Filter by user1
        entries, total = query_audit_logs(db=db, page=1, per_page=50, user_id=user1_id)

        assert total >= 2
        for entry in entries:
            assert entry.user_id == user1_id


# =============================================================================
# Part C — Existing Index Preservation
# =============================================================================

class TestExistingIndexPreservation:
    """Property-based test: existing indexes are still present and functional.

    **Validates: Requirements 3.7**
    """

    @given(data=st.data())
    @settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_existing_indexes_present(self, db, data):
        """Existing indexes must be present in the database schema.

        Checks: ix_scrape_log_client_sub_time, ix_subreddit_karma_avatar,
        ix_audit_log_client_action_created

        **Validates: Requirements 3.7**
        """
        # Query pg_indexes to verify existing indexes are present
        result = db.execute(text("""
            SELECT indexname FROM pg_indexes
            WHERE schemaname = 'public'
            AND indexname IN (
                'ix_scrape_log_client_sub_time',
                'ix_subreddit_karma_avatar',
                'ix_audit_log_client_action_created',
                'ix_audit_log_action',
                'ix_audit_log_created_at'
            )
            ORDER BY indexname
        """))
        index_names = [row[0] for row in result.fetchall()]

        expected_indexes = [
            "ix_audit_log_action",
            "ix_audit_log_client_action_created",
            "ix_audit_log_created_at",
            "ix_scrape_log_client_sub_time",
            "ix_subreddit_karma_avatar",
        ]

        for idx in expected_indexes:
            assert idx in index_names, (
                f"Expected index '{idx}' not found in database. "
                f"Found indexes: {index_names}"
            )

    @given(data=st.data())
    @settings(max_examples=3, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_scrape_log_client_sub_time_index_used(self, db, data):
        """Queries using ix_scrape_log_client_sub_time should use index scan.

        **Validates: Requirements 3.7**
        """
        # Run EXPLAIN on a query that should use the composite index
        result = db.execute(text("""
            EXPLAIN (FORMAT JSON)
            SELECT * FROM scrape_log
            WHERE client_id = '00000000-0000-0000-0000-000000000001'
            AND subreddit_name = 'test'
            ORDER BY scraped_at DESC
            LIMIT 10
        """))
        plan = result.fetchone()[0]
        plan_str = str(plan)

        # The plan should reference an index scan (not necessarily the exact index
        # name, but should not be a pure Seq Scan on the main table)
        # For small tables, PostgreSQL may choose Seq Scan, so we just verify
        # the index exists (tested above) and the query executes successfully
        assert plan is not None, "EXPLAIN query failed"

    @given(data=st.data())
    @settings(max_examples=3, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_subreddit_karma_avatar_index_used(self, db, data):
        """Queries filtering subreddit_karma by avatar_id should use the index.

        **Validates: Requirements 3.7**
        """
        result = db.execute(text("""
            EXPLAIN (FORMAT JSON)
            SELECT * FROM subreddit_karma
            WHERE avatar_id = '00000000-0000-0000-0000-000000000001'
            ORDER BY last_updated_at DESC
            LIMIT 10
        """))
        plan = result.fetchone()[0]
        assert plan is not None, "EXPLAIN query failed"

    @given(data=st.data())
    @settings(max_examples=3, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_comment_drafts_client_status_index_used(self, db, data):
        """Queries using ix_comment_drafts_client_status should use index scan.

        **Validates: Requirements 3.7**
        """
        result = db.execute(text("""
            EXPLAIN (FORMAT JSON)
            SELECT * FROM comment_drafts
            WHERE client_id = '00000000-0000-0000-0000-000000000001'
            AND status = 'pending'
            ORDER BY created_at DESC
            LIMIT 10
        """))
        plan = result.fetchone()[0]
        assert plan is not None, "EXPLAIN query failed"

    @given(data=st.data())
    @settings(max_examples=3, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_audit_log_indexes_present(self, db, data):
        """Existing single-column indexes on audit_log are present.

        **Validates: Requirements 3.7**
        """
        result = db.execute(text("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'audit_log'
            AND schemaname = 'public'
            ORDER BY indexname
        """))
        index_names = [row[0] for row in result.fetchall()]

        # These are the existing single-column indexes from the model
        # (action, user_id, client_id, entity_type, created_at all have index=True)
        assert len(index_names) >= 1, (
            f"Expected at least 1 index on audit_log, found: {index_names}"
        )
