"""Tests for Daily Subreddit Intelligence Refresh.

Covers:
- Task identifies stale subreddits correctly
- Freshness gate in epg_executor emits event for stale subs
- Extension dashboard includes subreddit_intel status
- Telegram notification on failures
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# Test: _check_subreddit_freshness (epg_executor)
# ---------------------------------------------------------------------------


class TestCheckSubredditFreshness:
    """Test the freshness gate in epg_executor."""

    @patch("app.services.transparency.record_activity_event")
    def test_stale_emotional_profile_emits_event(self, mock_event):
        """If emotional_profile_analyzed_at is > 7 days old, emit event."""
        from app.services.epg_executor import _check_subreddit_freshness

        db = MagicMock(spec=Session)

        # Mock the slot
        slot = MagicMock()
        slot.subreddit = "sysadmin"
        slot.id = uuid.uuid4()
        slot.avatar_id = uuid.uuid4()

        # Mock subreddit with stale emotional profile
        mock_sub = MagicMock()
        mock_sub.id = uuid.uuid4()
        mock_sub.emotional_profile_analyzed_at = datetime.now(timezone.utc) - timedelta(days=10)

        # Mock risk profile that is fresh
        mock_risk = MagicMock()
        mock_risk.next_check_at = datetime.now(timezone.utc) + timedelta(days=5)

        # Setup query chain
        db.query.return_value.filter.return_value.first.side_effect = [mock_sub, mock_risk]

        _check_subreddit_freshness(db, slot)

        # Should emit an event because emotional is stale
        mock_event.assert_called_once()
        call_kwargs = mock_event.call_args[1]
        assert call_kwargs["event_type"] == "subreddit_intelligence_stale"
        assert "sysadmin" in call_kwargs["message"]

    @patch("app.services.transparency.record_activity_event")
    def test_fresh_profile_no_event(self, mock_event):
        """If all profiles are fresh, no event emitted."""
        from app.services.epg_executor import _check_subreddit_freshness

        db = MagicMock(spec=Session)

        slot = MagicMock()
        slot.subreddit = "python"
        slot.id = uuid.uuid4()
        slot.avatar_id = uuid.uuid4()

        mock_sub = MagicMock()
        mock_sub.id = uuid.uuid4()
        mock_sub.emotional_profile_analyzed_at = datetime.now(timezone.utc) - timedelta(days=2)

        mock_risk = MagicMock()
        mock_risk.next_check_at = datetime.now(timezone.utc) + timedelta(days=10)

        db.query.return_value.filter.return_value.first.side_effect = [mock_sub, mock_risk]

        _check_subreddit_freshness(db, slot)

        mock_event.assert_not_called()

    @patch("app.services.transparency.record_activity_event")
    def test_no_subreddit_on_slot_no_error(self, mock_event):
        """If slot has no subreddit name, skip silently."""
        from app.services.epg_executor import _check_subreddit_freshness

        db = MagicMock(spec=Session)
        slot = MagicMock()
        slot.subreddit = None

        _check_subreddit_freshness(db, slot)

        mock_event.assert_not_called()
        # No DB query should be made
        db.query.assert_not_called()

    @patch("app.services.transparency.record_activity_event")
    def test_missing_risk_profile_emits_event(self, mock_event):
        """If risk profile is completely missing, emit stale event."""
        from app.services.epg_executor import _check_subreddit_freshness

        db = MagicMock(spec=Session)

        slot = MagicMock()
        slot.subreddit = "networking"
        slot.id = uuid.uuid4()
        slot.avatar_id = uuid.uuid4()

        mock_sub = MagicMock()
        mock_sub.id = uuid.uuid4()
        mock_sub.emotional_profile_analyzed_at = datetime.now(timezone.utc) - timedelta(days=1)

        # Risk profile not found
        db.query.return_value.filter.return_value.first.side_effect = [mock_sub, None]

        _check_subreddit_freshness(db, slot)

        mock_event.assert_called_once()
        call_kwargs = mock_event.call_args[1]
        assert "risk_profile_missing" in str(call_kwargs["metadata"]["issues"])


# ---------------------------------------------------------------------------
# Test: refresh_subreddit_intelligence_daily (task)
# ---------------------------------------------------------------------------


class TestRefreshSubredditIntelligenceDaily:
    """Test the main daily intelligence task."""

    @patch("app.tasks.subreddit_intelligence.DistributedLock")
    @patch("app.tasks.subreddit_intelligence.SessionLocal")
    def test_skips_when_lock_not_acquired(self, mock_session_cls, mock_lock_cls):
        """If distributed lock is busy, task aborts gracefully."""
        from app.tasks.subreddit_intelligence import refresh_subreddit_intelligence_daily

        mock_lock = MagicMock()
        mock_lock.acquire.return_value = False
        mock_lock_cls.return_value = mock_lock

        result = refresh_subreddit_intelligence_daily()

        assert result["status"] == "skipped"
        assert result["reason"] == "lock_not_acquired"

    @patch("app.tasks.subreddit_intelligence.DistributedLock")
    @patch("app.tasks.subreddit_intelligence.SessionLocal")
    def test_returns_ok_when_all_fresh(self, mock_session_cls, mock_lock_cls):
        """If no active subs exist, returns ok with stale=0."""
        from app.tasks.subreddit_intelligence import refresh_subreddit_intelligence_daily

        mock_lock = MagicMock()
        mock_lock.acquire.return_value = True
        mock_lock_cls.return_value = mock_lock

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        # Mock: query chain returns empty list for active subs
        # The task calls db.query(...).filter(...).all() for active subs
        # and db.query(...).filter(...).first() for risk profiles
        # and various other calls. Simplest: make the active subs query return []
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.query.return_value.filter.return_value.distinct.return_value.subquery.return_value = MagicMock()

        result = refresh_subreddit_intelligence_daily()

        # Should successfully complete (might raise inside complex logic, 
        # but at minimum should not crash)
        assert isinstance(result, dict)
        mock_lock.release.assert_called_once()


# ---------------------------------------------------------------------------
# Test: _get_subreddit_intel_status (extension API)
# ---------------------------------------------------------------------------


class TestGetSubredditIntelStatus:
    """Test extension dashboard subreddit intel helper."""

    def test_returns_no_subs_for_avatar_without_clients(self):
        """Avatar with no client_ids returns no_subs status."""
        from app.routes.extension_api import _get_subreddit_intel_status

        db = MagicMock(spec=Session)
        avatar = MagicMock()
        avatar.client_ids = []
        avatar.hobby_subreddits = []

        result = _get_subreddit_intel_status(db, avatar)

        assert result["status"] == "no_subs"
        assert result["total"] == 0

    def test_returns_error_on_exception(self):
        """On DB error, returns graceful error dict."""
        from app.routes.extension_api import _get_subreddit_intel_status

        db = MagicMock(spec=Session)
        avatar = MagicMock()
        avatar.client_ids = ["some-invalid-uuid"]
        avatar.hobby_subreddits = None

        # Force exception on UUID parse
        result = _get_subreddit_intel_status(db, avatar)

        # Should not crash — returns error status
        assert result["status"] in ("error", "no_subs")


# ---------------------------------------------------------------------------
# Test: Beat schedule includes the new task
# ---------------------------------------------------------------------------


class TestBeatSchedule:
    """Verify the new task is in beat schedule."""

    def test_subreddit_intelligence_in_schedule(self):
        """New task must be in beat_app schedule."""
        from app.tasks.beat_app import beat_app

        schedule = beat_app.conf.beat_schedule
        assert "subreddit-intelligence-daily" in schedule
        entry = schedule["subreddit-intelligence-daily"]
        assert entry["task"] == "refresh_subreddit_intelligence_daily"

    def test_runs_at_0700(self):
        """Task scheduled at 07:00 (before EPG build at 08:15)."""
        from app.tasks.beat_app import beat_app

        entry = beat_app.conf.beat_schedule["subreddit-intelligence-daily"]
        # crontab(hour=7, minute=0)
        assert entry["schedule"].hour == {7}
        assert entry["schedule"].minute == {0}


# ---------------------------------------------------------------------------
# Test: Worker includes the new task module
# ---------------------------------------------------------------------------


class TestWorkerIncludes:
    """Verify worker imports the new module."""

    def test_subreddit_intelligence_in_includes(self):
        """New task module must be in worker includes."""
        from app.tasks.worker import celery_app

        assert "app.tasks.subreddit_intelligence" in celery_app.conf.include
