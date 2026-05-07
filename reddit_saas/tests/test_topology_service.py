"""Unit tests for the topology service — aggregate_timeline function."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.activity_event import ActivityEvent
from app.models.ai_usage import AIUsageLog
from app.models.comment_draft import CommentDraft
from app.models.scrape_log import ScrapeLog
from app.services.topology import aggregate_timeline, HourBucket


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_activity_event(db, event_type: str, created_at: datetime, has_error: bool = False):
    """Insert an activity event into the test DB."""
    metadata = {"error": "something went wrong"} if has_error else None
    event = ActivityEvent(
        id=uuid.uuid4(),
        event_type=event_type,
        message=f"test {event_type}",
        event_metadata=metadata,
        created_at=created_at,
    )
    db.add(event)
    db.flush()
    return event


def _make_scrape_log(db, scraped_at: datetime, has_error: bool = False):
    """Insert a scrape_log entry into the test DB using raw SQL."""
    from sqlalchemy import text as sql_text
    # Get an existing client_id from the DB
    row = db.execute(sql_text("SELECT id FROM clients LIMIT 1")).fetchone()
    client_id = str(row[0]) if row else str(uuid.uuid4())
    entry_id = uuid.uuid4()
    db.execute(
        sql_text("""
            INSERT INTO scrape_log (id, client_id, subreddit_name, scraped_at, posts_found, posts_new, errors, duration_ms)
            VALUES (:id, :client_id, :subreddit_name, :scraped_at, :posts_found, :posts_new, :errors, :duration_ms)
        """),
        {
            "id": str(entry_id),
            "client_id": client_id,
            "subreddit_name": "test_topology_sub",
            "scraped_at": scraped_at,
            "posts_found": 10,
            "posts_new": 5,
            "errors": "timeout error" if has_error else None,
            "duration_ms": 1500,
        },
    )
    db.flush()


def _make_ai_usage(db, created_at: datetime, is_error: bool = False):
    """Insert an ai_usage_log entry into the test DB."""
    entry = AIUsageLog(
        id=uuid.uuid4(),
        operation="scoring",
        model="gemini-flash",
        input_tokens=0 if is_error else 1000,
        output_tokens=0 if is_error else 200,
        cost_usd=0 if is_error else 0.001,
        duration_ms=500,
        created_at=created_at,
    )
    db.add(entry)
    db.flush()
    return entry


def _make_comment_draft(db, created_at: datetime):
    """Insert a comment_draft entry into the test DB using raw SQL with valid FK references."""
    from sqlalchemy import text as sql_text
    # Get existing FK references from the DB
    thread_row = db.execute(sql_text("SELECT id FROM reddit_threads LIMIT 1")).fetchone()
    client_row = db.execute(sql_text("SELECT id FROM clients LIMIT 1")).fetchone()
    avatar_row = db.execute(sql_text("SELECT id FROM avatars LIMIT 1")).fetchone()

    if not all([thread_row, client_row, avatar_row]):
        pytest.skip("Need existing thread, client, and avatar records for comment_drafts test")

    entry_id = uuid.uuid4()
    db.execute(
        sql_text("""
            INSERT INTO comment_drafts (id, thread_id, client_id, avatar_id, type, status, created_at, is_deleted)
            VALUES (:id, :thread_id, :client_id, :avatar_id, :type, :status, :created_at, :is_deleted)
        """),
        {
            "id": str(entry_id),
            "thread_id": str(thread_row[0]),
            "client_id": str(client_row[0]),
            "avatar_id": str(avatar_row[0]),
            "type": "professional",
            "status": "pending",
            "created_at": created_at,
            "is_deleted": False,
        },
    )
    db.flush()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAggregateTimelineStructure:
    """Tests for the structure of aggregate_timeline output."""

    def test_returns_all_nine_nodes(self, db):
        """aggregate_timeline returns exactly 9 node keys."""
        result = aggregate_timeline(db)
        expected_keys = {
            "scrape", "score", "generate", "review",
            "reddit_api", "llm_api", "database", "queue", "safety",
        }
        assert set(result.keys()) == expected_keys

    def test_each_node_has_24_buckets(self, db):
        """Each node has exactly 24 HourBucket entries."""
        result = aggregate_timeline(db)
        for node_id, buckets in result.items():
            assert len(buckets) == 24, f"{node_id} has {len(buckets)} buckets, expected 24"

    def test_buckets_ordered_by_hour(self, db):
        """Buckets are ordered from hour 0 to hour 23."""
        result = aggregate_timeline(db)
        for node_id, buckets in result.items():
            hours = [b.hour for b in buckets]
            assert hours == list(range(24)), f"{node_id} hours not ordered: {hours}"

    def test_empty_db_returns_zero_counts(self, db):
        """With no data in the time window, all buckets have zero counts."""
        # Use a very short window (0 hours) to ensure no data matches
        result = aggregate_timeline(db, hours=0)
        for node_id, buckets in result.items():
            for bucket in buckets:
                assert bucket.event_count == 0, f"{node_id} hour {bucket.hour} has events"
                assert bucket.error_count == 0, f"{node_id} hour {bucket.hour} has errors"

    def test_database_node_always_zero(self, db):
        """Database node always returns 24 zero buckets."""
        # Add some data to other tables
        now = datetime.now(timezone.utc)
        _make_activity_event(db, "score", now - timedelta(hours=1))
        db.flush()

        result = aggregate_timeline(db)
        for bucket in result["database"]:
            assert bucket.event_count == 0
            assert bucket.error_count == 0


class TestAggregateTimelineActivityEvents:
    """Tests for activity_events aggregation (score, generate, queue, safety)."""

    def test_score_events_counted(self, db):
        """Score events appear in the 'score' node timeline."""
        now = datetime.now(timezone.utc)
        # Use 2 hours ago to avoid edge cases at hour boundaries
        target_time = (now - timedelta(hours=2)).replace(minute=30, second=0, microsecond=0)
        _make_activity_event(db, "score", target_time)
        _make_activity_event(db, "score", target_time + timedelta(minutes=10))
        db.flush()

        result = aggregate_timeline(db)
        bucket = result["score"][target_time.hour]
        assert bucket.event_count >= 2
        assert bucket.error_count == 0

    def test_score_errors_counted(self, db):
        """Score events with error metadata are counted as errors."""
        now = datetime.now(timezone.utc)
        target_time = (now - timedelta(hours=3)).replace(minute=30, second=0, microsecond=0)
        _make_activity_event(db, "score", target_time, has_error=True)
        _make_activity_event(db, "score", target_time + timedelta(minutes=5))
        db.flush()

        result = aggregate_timeline(db)
        bucket = result["score"][target_time.hour]
        assert bucket.event_count >= 2
        assert bucket.error_count >= 1

    def test_generate_events_counted(self, db):
        """Generate events appear in the 'generate' node timeline."""
        now = datetime.now(timezone.utc)
        target_time = (now - timedelta(hours=4)).replace(minute=15, second=0, microsecond=0)
        _make_activity_event(db, "generate", target_time)
        db.flush()

        result = aggregate_timeline(db)
        bucket = result["generate"][target_time.hour]
        assert bucket.event_count >= 1

    def test_heartbeat_events_in_queue_node(self, db):
        """Heartbeat events appear in the 'queue' node timeline."""
        now = datetime.now(timezone.utc)
        target_time = (now - timedelta(hours=5)).replace(minute=10, second=0, microsecond=0)
        _make_activity_event(db, "heartbeat", target_time)
        db.flush()

        result = aggregate_timeline(db)
        bucket = result["queue"][target_time.hour]
        assert bucket.event_count >= 1

    def test_safety_events_counted(self, db):
        """Safety events appear in the 'safety' node timeline."""
        now = datetime.now(timezone.utc)
        target_time = (now - timedelta(hours=6)).replace(minute=45, second=0, microsecond=0)
        _make_activity_event(db, "safety", target_time)
        _make_activity_event(db, "safety", target_time + timedelta(minutes=5), has_error=True)
        db.flush()

        result = aggregate_timeline(db)
        bucket = result["safety"][target_time.hour]
        assert bucket.event_count >= 2
        assert bucket.error_count >= 1


class TestAggregateTimelineScrapeLog:
    """Tests for scrape_log aggregation (scrape and reddit_api nodes)."""

    def test_scrape_events_counted(self, db):
        """Scrape log entries appear in the 'scrape' node timeline."""
        now = datetime.now(timezone.utc)
        target_time = (now - timedelta(hours=7)).replace(minute=20, second=0, microsecond=0)
        _make_scrape_log(db, target_time)
        _make_scrape_log(db, target_time + timedelta(minutes=10))
        db.flush()

        result = aggregate_timeline(db)
        bucket = result["scrape"][target_time.hour]
        assert bucket.event_count >= 2
        assert bucket.error_count == 0

    def test_scrape_errors_counted(self, db):
        """Scrape log entries with errors are counted."""
        now = datetime.now(timezone.utc)
        target_time = (now - timedelta(hours=8)).replace(minute=20, second=0, microsecond=0)
        _make_scrape_log(db, target_time, has_error=True)
        _make_scrape_log(db, target_time + timedelta(minutes=10))
        db.flush()

        result = aggregate_timeline(db)
        bucket = result["scrape"][target_time.hour]
        assert bucket.event_count >= 2
        assert bucket.error_count >= 1

    def test_reddit_api_mirrors_scrape_log(self, db):
        """Reddit API node uses scrape_log data."""
        now = datetime.now(timezone.utc)
        target_time = (now - timedelta(hours=9)).replace(minute=20, second=0, microsecond=0)
        _make_scrape_log(db, target_time, has_error=True)
        _make_scrape_log(db, target_time + timedelta(minutes=10))
        db.flush()

        result = aggregate_timeline(db)
        bucket = result["reddit_api"][target_time.hour]
        assert bucket.event_count >= 2
        assert bucket.error_count >= 1


class TestAggregateTimelineAIUsage:
    """Tests for ai_usage_log aggregation (llm_api node)."""

    def test_ai_usage_counted(self, db):
        """AI usage log entries appear in the 'llm_api' node timeline."""
        now = datetime.now(timezone.utc)
        target_time = (now - timedelta(hours=10)).replace(minute=10, second=0, microsecond=0)
        _make_ai_usage(db, target_time)
        _make_ai_usage(db, target_time + timedelta(minutes=15))
        db.flush()

        result = aggregate_timeline(db)
        bucket = result["llm_api"][target_time.hour]
        assert bucket.event_count >= 2
        assert bucket.error_count == 0

    def test_ai_usage_errors_counted(self, db):
        """AI usage entries with zero tokens/cost are counted as errors."""
        now = datetime.now(timezone.utc)
        target_time = (now - timedelta(hours=11)).replace(minute=10, second=0, microsecond=0)
        _make_ai_usage(db, target_time, is_error=True)
        _make_ai_usage(db, target_time + timedelta(minutes=15))
        db.flush()

        result = aggregate_timeline(db)
        bucket = result["llm_api"][target_time.hour]
        assert bucket.event_count >= 2
        assert bucket.error_count >= 1


class TestAggregateTimelineCommentDrafts:
    """Tests for comment_drafts aggregation (review node)."""

    def test_comment_drafts_counted(self, db):
        """Comment drafts appear in the 'review' node timeline."""
        now = datetime.now(timezone.utc)
        target_time = (now - timedelta(hours=12)).replace(minute=30, second=0, microsecond=0)
        _make_comment_draft(db, target_time)
        _make_comment_draft(db, target_time + timedelta(minutes=10))
        db.flush()

        result = aggregate_timeline(db)
        bucket = result["review"][target_time.hour]
        assert bucket.event_count >= 2
        assert bucket.error_count == 0


class TestAggregateTimelineFiltering:
    """Tests for time window filtering."""

    def test_events_outside_24h_excluded(self, db):
        """Events older than 24 hours are not included."""
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(hours=25)
        _make_activity_event(db, "score", old_time)
        db.flush()

        result = aggregate_timeline(db)
        total_events = sum(b.event_count for b in result["score"])
        assert total_events == 0
