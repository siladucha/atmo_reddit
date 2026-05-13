"""Bug Condition Exploration Test — Audit Log Gaps in Background Tasks.

**Property 1: Bug Condition** — Audit Log Gaps in Background Tasks

This test MUST FAIL on unfixed code — failure confirms the bug exists.
DO NOT attempt to fix the test or the code when it fails.

GOAL: Surface counterexamples that demonstrate background tasks complete
without creating AuditLog entries.

Scoped PBT Approach: Tests the 10 concrete task executions identified in the design.

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.subreddit import Subreddit
from app.models.thread import RedditThread
from app.models.thread_score import ThreadScore


# --- Strategies ---

st_client_count = st.integers(min_value=1, max_value=5)
st_avatar_count = st.integers(min_value=1, max_value=5)
st_subreddit_name = st.sampled_from([
    "cybersecurity", "netsec", "programming", "python", "devops",
    "sysadmin", "machinelearning", "datascience", "technology", "linux",
])
st_posts_found = st.integers(min_value=0, max_value=50)
st_posts_new = st.integers(min_value=0, max_value=25)


def _create_test_clients(db: Session, count: int) -> list[Client]:
    """Create test client records."""
    clients = []
    for i in range(count):
        client = Client(
            client_name=f"TestClient_{i}_{uuid.uuid4().hex[:6]}",
            brand_name=f"Brand_{i}",
            is_active=True,
        )
        db.add(client)
        clients.append(client)
    db.flush()
    return clients


def _create_test_avatars(db: Session, count: int) -> list[Avatar]:
    """Create test avatar records."""
    avatars = []
    for i in range(count):
        avatar = Avatar(
            reddit_username=f"test_avatar_{i}_{uuid.uuid4().hex[:6]}",
            active=True,
            is_shadowbanned=False,
            is_frozen=False,
            health_status="active",
            warming_phase=1,
        )
        db.add(avatar)
        avatars.append(avatar)
    db.flush()
    return avatars


def _create_test_subreddit(db: Session, name: str) -> Subreddit:
    """Create a test subreddit record."""
    sub = Subreddit(
        subreddit_name=name,
        is_active=True,
    )
    db.add(sub)
    db.flush()
    return sub


def _get_audit_logs_by_action(db: Session, action: str) -> list[AuditLog]:
    """Query AuditLog entries by action."""
    return db.query(AuditLog).filter(AuditLog.action == action).all()


# =============================================================================
# Test 1: run_full_pipeline_all_clients creates AuditLog entries
# =============================================================================

class TestPipelineAuditLogs:
    """Test that run_full_pipeline_all_clients creates AuditLog entries
    with actions 'pipeline_run_started' and 'pipeline_run_completed'.

    **Validates: Requirements 1.1**
    """

    @given(client_count=st_client_count)
    @settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_pipeline_creates_started_audit_log(self, db, client_count):
        """run_full_pipeline_all_clients MUST create AuditLog with action='pipeline_run_started'.

        **Validates: Requirements 1.1**
        """
        clients = _create_test_clients(db, client_count)

        with patch("app.tasks.orchestrator.SessionLocal", return_value=db), \
             patch("app.tasks.ai_pipeline.score_threads") as mock_score, \
             patch("app.tasks.ai_pipeline.generate_comments") as mock_gen, \
             patch("app.tasks.ai_pipeline.generate_posts") as mock_posts:

            # Mock Celery chain
            mock_chain = MagicMock()
            mock_score.si.return_value = mock_chain
            mock_chain.__or__ = MagicMock(return_value=mock_chain)
            mock_chain.apply_async = MagicMock()

            from app.tasks.orchestrator import run_full_pipeline_all_clients
            run_full_pipeline_all_clients()

        # Assert: AuditLog entry with action='pipeline_run_started' must exist
        logs = _get_audit_logs_by_action(db, "pipeline_run_started")
        assert len(logs) >= 1, (
            f"COUNTEREXAMPLE: run_full_pipeline_all_clients completed for {client_count} clients "
            f"but AuditLog has 0 rows with action='pipeline_run_started'. "
            f"Expected at least 1 entry with details containing client_count={client_count}."
        )
        # Verify details contain expected keys
        entry = logs[0]
        assert entry.entity_type == "pipeline"
        assert entry.details is not None
        assert "client_count" in entry.details

    @given(client_count=st_client_count)
    @settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_pipeline_creates_completed_audit_log(self, db, client_count):
        """run_full_pipeline_all_clients MUST create AuditLog with action='pipeline_run_completed'.

        **Validates: Requirements 1.1**
        """
        clients = _create_test_clients(db, client_count)

        with patch("app.tasks.orchestrator.SessionLocal", return_value=db), \
             patch("app.tasks.ai_pipeline.score_threads") as mock_score, \
             patch("app.tasks.ai_pipeline.generate_comments") as mock_gen, \
             patch("app.tasks.ai_pipeline.generate_posts") as mock_posts:

            mock_chain = MagicMock()
            mock_score.si.return_value = mock_chain
            mock_chain.__or__ = MagicMock(return_value=mock_chain)
            mock_chain.apply_async = MagicMock()

            from app.tasks.orchestrator import run_full_pipeline_all_clients
            run_full_pipeline_all_clients()

        logs = _get_audit_logs_by_action(db, "pipeline_run_completed")
        assert len(logs) >= 1, (
            f"COUNTEREXAMPLE: run_full_pipeline_all_clients completed for {client_count} clients "
            f"but AuditLog has 0 rows with action='pipeline_run_completed'. "
            f"Expected at least 1 entry with details containing client_count and clients_queued."
        )
        entry = logs[0]
        assert entry.entity_type == "pipeline"
        assert entry.details is not None
        assert "client_count" in entry.details


# =============================================================================
# Test 2: run_hobby_pipeline_all_avatars creates AuditLog entry
# =============================================================================

class TestHobbyPipelineAuditLog:
    """Test that run_hobby_pipeline_all_avatars creates AuditLog entry
    with action 'hobby_pipeline_run'.

    **Validates: Requirements 1.2**
    """

    @given(avatar_count=st_avatar_count)
    @settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_hobby_pipeline_creates_audit_log(self, db, avatar_count):
        """run_hobby_pipeline_all_avatars MUST create AuditLog with action='hobby_pipeline_run'.

        **Validates: Requirements 1.2**
        """
        avatars = _create_test_avatars(db, avatar_count)

        with patch("app.tasks.orchestrator.SessionLocal", return_value=db), \
             patch("app.tasks.scraping.scrape_hobby_subreddits") as mock_scrape, \
             patch("app.tasks.ai_pipeline.generate_hobby_comments") as mock_gen:

            mock_chain = MagicMock()
            mock_scrape.si.return_value = mock_chain
            mock_chain.__or__ = MagicMock(return_value=mock_chain)
            mock_chain.apply_async = MagicMock()

            from app.tasks.orchestrator import run_hobby_pipeline_all_avatars
            run_hobby_pipeline_all_avatars()

        logs = _get_audit_logs_by_action(db, "hobby_pipeline_run")
        assert len(logs) >= 1, (
            f"COUNTEREXAMPLE: run_hobby_pipeline_all_avatars completed for {avatar_count} avatars "
            f"but AuditLog has 0 rows with action='hobby_pipeline_run'. "
            f"Expected at least 1 entry with details containing avatar_count={avatar_count}."
        )
        entry = logs[0]
        assert entry.entity_type == "pipeline"
        assert entry.details is not None
        assert "avatar_count" in entry.details


# =============================================================================
# Test 3: scrape_subreddit_shared creates AuditLog entries
# =============================================================================

class TestScrapeAuditLog:
    """Test that scrape_subreddit_shared creates AuditLog entry with action
    'scrape_completed' on success and 'scrape_failed' on failure.

    **Validates: Requirements 1.3**
    """

    @given(
        subreddit_name=st_subreddit_name,
        posts_found=st_posts_found,
        posts_new=st_posts_new,
    )
    @settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_scrape_success_creates_audit_log(self, db, subreddit_name, posts_found, posts_new):
        """scrape_subreddit_shared on success MUST create AuditLog with action='scrape_completed'.

        **Validates: Requirements 1.3**
        """
        sub = _create_test_subreddit(db, subreddit_name)

        mock_posts = [
            {
                "reddit_native_id": f"t3_{uuid.uuid4().hex[:6]}",
                "subreddit": subreddit_name,
                "post_title": f"Test post {i}",
                "post_body": "Test body",
                "comments_json": [],
                "url": f"https://reddit.com/r/{subreddit_name}/test_{i}",
                "author": "test_user",
                "score": 10,
                "ups": 10,
                "downs": 0,
                "is_locked": False,
            }
            for i in range(min(posts_found, posts_new))
        ]

        with patch("app.tasks.scraping.SessionLocal", return_value=db), \
             patch("app.tasks.scraping.scrape_subreddit", return_value=mock_posts), \
             patch("app.tasks.scraping.deduplicate_posts", return_value=mock_posts[:posts_new]), \
             patch("app.services.settings.get_setting_int", return_value=0):

            # Create a mock self for the bound task
            mock_self = MagicMock()
            mock_self.request = MagicMock()
            mock_self.request.retries = 0

            from app.tasks.scraping import scrape_subreddit_shared
            # Call the underlying function (unwrap Celery task)
            scrape_subreddit_shared(mock_self, str(sub.id))

        logs = _get_audit_logs_by_action(db, "scrape_completed")
        assert len(logs) >= 1, (
            f"COUNTEREXAMPLE: scrape_subreddit_shared completed successfully for r/{subreddit_name} "
            f"({posts_found} found, {posts_new} new) but AuditLog has 0 rows with "
            f"action='scrape_completed'. Expected at least 1 entry."
        )
        entry = logs[0]
        assert entry.entity_type == "subreddit"
        assert entry.details is not None
        assert "subreddit_name" in entry.details

    @given(subreddit_name=st_subreddit_name)
    @settings(max_examples=3, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_scrape_failure_creates_audit_log(self, db, subreddit_name):
        """scrape_subreddit_shared on failure MUST create AuditLog with action='scrape_failed'.

        **Validates: Requirements 1.3**
        """
        sub = _create_test_subreddit(db, subreddit_name)

        with patch("app.tasks.scraping.SessionLocal", return_value=db), \
             patch("app.tasks.scraping.scrape_subreddit", side_effect=Exception("Reddit API error")), \
             patch("app.services.settings.get_setting_int", return_value=0):

            mock_self = MagicMock()
            mock_self.request = MagicMock()
            mock_self.request.retries = 0

            from app.tasks.scraping import scrape_subreddit_shared
            scrape_subreddit_shared(mock_self, str(sub.id))

        logs = _get_audit_logs_by_action(db, "scrape_failed")
        assert len(logs) >= 1, (
            f"COUNTEREXAMPLE: scrape_subreddit_shared failed for r/{subreddit_name} "
            f"but AuditLog has 0 rows with action='scrape_failed'. "
            f"Expected at least 1 entry with error details."
        )
        entry = logs[0]
        assert entry.entity_type == "subreddit"
        assert entry.details is not None
        assert "error" in entry.details


# =============================================================================
# Test 4: track_karma_all_avatars creates AuditLog entry
# =============================================================================

class TestKarmaTrackingAuditLog:
    """Test that track_karma_all_avatars creates AuditLog entry with action
    'karma_tracking_batch_completed'.

    **Validates: Requirements 1.4**
    """

    @given(avatar_count=st_avatar_count)
    @settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_karma_tracking_creates_audit_log(self, db, avatar_count):
        """track_karma_all_avatars MUST create AuditLog with action='karma_tracking_batch_completed'.

        **Validates: Requirements 1.4**
        """
        avatars = _create_test_avatars(db, avatar_count)

        with patch("app.tasks.karma_tracking.SessionLocal", return_value=db), \
             patch("app.tasks.karma_tracking._track_single_avatar", return_value={
                 "comments_updated": 2,
                 "posts_updated": 1,
                 "deletions_detected": 0,
                 "demotions_triggered": 0,
             }), \
             patch("app.tasks.karma_tracking.time.sleep"):

            from app.tasks.karma_tracking import track_karma_all_avatars
            track_karma_all_avatars()

        logs = _get_audit_logs_by_action(db, "karma_tracking_batch_completed")
        assert len(logs) >= 1, (
            f"COUNTEREXAMPLE: track_karma_all_avatars completed for {avatar_count} avatars "
            f"but AuditLog has 0 rows with action='karma_tracking_batch_completed'. "
            f"Expected at least 1 entry with details containing avatars_processed count."
        )
        entry = logs[0]
        assert entry.entity_type == "karma"
        assert entry.details is not None
        assert "avatars_processed" in entry.details


# =============================================================================
# Test 5: scan_avatar_presence_task creates AuditLog entry
# =============================================================================

class TestPresenceScanAuditLog:
    """Test that scan_avatar_presence_task creates AuditLog entry with action
    'presence_scan_completed'.

    **Validates: Requirements 1.5**
    """

    @given(subreddit_count=st.integers(min_value=1, max_value=10))
    @settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_presence_scan_creates_audit_log(self, db, subreddit_count):
        """scan_avatar_presence_task MUST create AuditLog with action='presence_scan_completed'.

        **Validates: Requirements 1.5**
        """
        avatars = _create_test_avatars(db, 1)
        avatar = avatars[0]

        # Mock presence records
        mock_records = [MagicMock() for _ in range(subreddit_count)]

        with patch("app.tasks.presence.SessionLocal", return_value=db), \
             patch("app.services.presence.scan_avatar_presence", return_value=mock_records):

            mock_self = MagicMock()
            mock_self.request = MagicMock()
            mock_self.request.retries = 0
            mock_self.retry = MagicMock(side_effect=Exception("retry"))
            mock_self.MaxRetriesExceededError = Exception

            from app.tasks.presence import scan_avatar_presence_task
            scan_avatar_presence_task(mock_self, str(avatar.id))

        logs = _get_audit_logs_by_action(db, "presence_scan_completed")
        assert len(logs) >= 1, (
            f"COUNTEREXAMPLE: scan_avatar_presence_task completed for avatar "
            f"{avatar.reddit_username} (found {subreddit_count} subreddits) "
            f"but AuditLog has 0 rows with action='presence_scan_completed'. "
            f"Expected at least 1 entry with details containing subreddits_found."
        )
        entry = logs[0]
        assert entry.entity_type == "avatar"
        assert entry.details is not None
        assert "subreddits_found" in entry.details


# =============================================================================
# Test 6: snapshot_profile_analytics_all_avatars creates AuditLog entry
# =============================================================================

class TestProfileAnalyticsAuditLog:
    """Test that snapshot_profile_analytics_all_avatars creates AuditLog entry
    with action 'profile_analytics_batch_completed'.

    **Validates: Requirements 1.6**
    """

    @given(avatar_count=st_avatar_count)
    @settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_profile_analytics_creates_audit_log(self, db, avatar_count):
        """snapshot_profile_analytics_all_avatars MUST create AuditLog with
        action='profile_analytics_batch_completed'.

        **Validates: Requirements 1.6**
        """
        avatars = _create_test_avatars(db, avatar_count)

        # Mock the analytics fetch to return a successful result
        mock_analytics = MagicMock()
        mock_analytics.error = None
        mock_analytics.total_karma = 1000

        with patch("app.tasks.profile_analytics.SessionLocal", return_value=db), \
             patch("app.services.reddit_profile_analytics.fetch_and_save", return_value=mock_analytics), \
             patch("app.services.reddit_freshness.profile_analytics_freshness_hours", return_value=0), \
             patch("app.services.reddit_freshness.profile_analytics_batch_limit", return_value=100), \
             patch("app.tasks.profile_analytics.profile_analytics_freshness_hours", return_value=0), \
             patch("app.tasks.profile_analytics.profile_analytics_batch_limit", return_value=100), \
             patch("time.sleep"):

            from app.tasks.profile_analytics import snapshot_profile_analytics_all_avatars
            snapshot_profile_analytics_all_avatars(delay_seconds=0)

        logs = _get_audit_logs_by_action(db, "profile_analytics_batch_completed")
        assert len(logs) >= 1, (
            f"COUNTEREXAMPLE: snapshot_profile_analytics_all_avatars completed for {avatar_count} "
            f"avatars but AuditLog has 0 rows with action='profile_analytics_batch_completed'. "
            f"Expected at least 1 entry with details containing processed count."
        )
        entry = logs[0]
        assert entry.entity_type == "avatar"
        assert entry.details is not None


# =============================================================================
# Test 7: evaluate_all_avatar_phases creates AuditLog entry
# =============================================================================

class TestPhaseEvaluationAuditLog:
    """Test that evaluate_all_avatar_phases creates AuditLog entry with action
    'phase_evaluation_completed'.

    **Validates: Requirements 1.7**
    """

    @given(avatar_count=st_avatar_count)
    @settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_phase_evaluation_creates_audit_log(self, db, avatar_count):
        """evaluate_all_avatar_phases MUST create AuditLog with action='phase_evaluation_completed'.

        **Validates: Requirements 1.7**
        """
        avatars = _create_test_avatars(db, avatar_count)

        # Mock phase evaluator
        mock_result = MagicMock()
        mock_result.action = "none"  # No promotion/demotion

        mock_evaluator = MagicMock()
        mock_evaluator.evaluate.return_value = mock_result

        mock_redis = MagicMock()

        with patch("app.tasks.ai_pipeline.SessionLocal", return_value=db), \
             patch("app.tasks.ai_pipeline.redis.from_url", return_value=mock_redis), \
             patch("app.services.phase.PhaseEvaluator", return_value=mock_evaluator), \
             patch("app.services.phase.PhaseTransitionManager"):

            from app.tasks.ai_pipeline import evaluate_all_avatar_phases
            evaluate_all_avatar_phases()

        logs = _get_audit_logs_by_action(db, "phase_evaluation_completed")
        assert len(logs) >= 1, (
            f"COUNTEREXAMPLE: evaluate_all_avatar_phases completed for {avatar_count} avatars "
            f"but AuditLog has 0 rows with action='phase_evaluation_completed'. "
            f"Expected at least 1 entry with details containing evaluated/promoted/demoted/errors."
        )
        entry = logs[0]
        assert entry.entity_type == "avatar"
        assert entry.details is not None
        assert "evaluated" in entry.details
        assert "promoted" in entry.details
        assert "demoted" in entry.details


# =============================================================================
# Test 8: score_threads batch creates AuditLog entry
# =============================================================================

class TestScoringAuditLog:
    """Test that score_threads batch completion creates AuditLog entry with action
    'scoring_batch_completed'.

    **Validates: Requirements 1.8**
    """

    @given(threads_scored=st.integers(min_value=1, max_value=20))
    @settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_scoring_creates_audit_log(self, db, threads_scored):
        """score_threads MUST create AuditLog with action='scoring_batch_completed'.

        **Validates: Requirements 1.8**
        """
        clients = _create_test_clients(db, 1)
        client = clients[0]

        with patch("app.tasks.ai_pipeline.SessionLocal", return_value=db), \
             patch("app.services.settings.is_pipeline_enabled", return_value=True), \
             patch("app.services.scoring.score_unscored_threads_for_client", return_value={"scored": threads_scored}):

            # Mock the tag distribution query
            mock_self = MagicMock()
            mock_self.request = MagicMock()
            mock_self.request.retries = 0

            from app.tasks.ai_pipeline import score_threads
            # We need to call the underlying function with the mock self
            score_threads(mock_self, str(client.id), triggered_by="test")

        logs = _get_audit_logs_by_action(db, "scoring_batch_completed")
        assert len(logs) >= 1, (
            f"COUNTEREXAMPLE: score_threads completed scoring {threads_scored} threads "
            f"for client {client.client_name} but AuditLog has 0 rows with "
            f"action='scoring_batch_completed'. Expected at least 1 entry with "
            f"details containing threads_scored and tag distribution."
        )
        entry = logs[0]
        assert entry.entity_type == "thread"
        assert entry.details is not None
        assert "threads_scored" in entry.details
