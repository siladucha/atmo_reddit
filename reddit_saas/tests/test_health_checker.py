"""Unit tests for the health checker classify_health_status function."""

import pytest

from app.services.health_checker import classify_health_status


class TestClassifyHealthStatus:
    """Tests for classify_health_status pure function."""

    def test_ratio_zero_returns_shadowbanned(self):
        """Visibility ratio of 0 means all comments are invisible."""
        assert classify_health_status(0.0, 0.5) == "shadowbanned"

    def test_ratio_below_threshold_returns_limited(self):
        """Ratio above 0 but below threshold means reduced visibility."""
        assert classify_health_status(0.3, 0.5) == "limited"

    def test_ratio_equal_to_threshold_returns_active(self):
        """Ratio exactly at threshold is classified as ACTIVE."""
        assert classify_health_status(0.5, 0.5) == "active"

    def test_ratio_above_threshold_returns_active(self):
        """Ratio above threshold is classified as ACTIVE."""
        assert classify_health_status(0.8, 0.5) == "active"

    def test_ratio_one_returns_active(self):
        """Full visibility (ratio=1.0) is always ACTIVE."""
        assert classify_health_status(1.0, 0.5) == "active"

    def test_small_ratio_above_zero_returns_limited(self):
        """Even a tiny non-zero ratio below threshold is LIMITED, not SHADOWBANNED."""
        assert classify_health_status(0.01, 0.5) == "limited"

    def test_threshold_at_one_only_full_visibility_is_active(self):
        """With threshold=1.0, only ratio=1.0 is ACTIVE."""
        assert classify_health_status(0.99, 1.0) == "limited"
        assert classify_health_status(1.0, 1.0) == "active"

    def test_very_low_threshold(self):
        """With a very low threshold, most ratios are ACTIVE."""
        assert classify_health_status(0.1, 0.1) == "active"
        assert classify_health_status(0.05, 0.1) == "limited"
        assert classify_health_status(0.0, 0.1) == "shadowbanned"


from unittest.mock import patch, MagicMock
import time as time_module
from datetime import datetime, timezone, timedelta

from prawcore.exceptions import NotFound, Forbidden, RequestException, ServerError

from app.services.health_checker import check_comment_visibility, HealthCheckError


def _make_mock_comment(body: str, created_utc: float) -> MagicMock:
    """Create a mock PRAW comment object."""
    comment = MagicMock()
    comment.body = body
    comment.created_utc = created_utc
    return comment


class TestCheckCommentVisibility:
    """Tests for check_comment_visibility function."""

    @patch("app.services.health_checker.get_reddit_client")
    def test_all_comments_visible(self, mock_get_client):
        """All recent comments are visible — returns full counts."""
        now = datetime.now(timezone.utc)
        recent_ts = (now - timedelta(days=1)).timestamp()

        comments = [
            _make_mock_comment("Hello world", recent_ts),
            _make_mock_comment("Another comment", recent_ts),
            _make_mock_comment("Third one", recent_ts),
        ]

        mock_reddit = MagicMock()
        mock_get_client.return_value = mock_reddit
        mock_reddit.redditor.return_value.comments.new.return_value = comments

        total, visible = check_comment_visibility("testuser", max_comments=10, lookback_days=7)

        assert total == 3
        assert visible == 3

    @patch("app.services.health_checker.get_reddit_client")
    def test_some_comments_removed(self, mock_get_client):
        """Some comments have [removed] or [deleted] body — not counted as visible."""
        now = datetime.now(timezone.utc)
        recent_ts = (now - timedelta(days=1)).timestamp()

        comments = [
            _make_mock_comment("Visible comment", recent_ts),
            _make_mock_comment("[removed]", recent_ts),
            _make_mock_comment("[deleted]", recent_ts),
            _make_mock_comment("Also visible", recent_ts),
        ]

        mock_reddit = MagicMock()
        mock_get_client.return_value = mock_reddit
        mock_reddit.redditor.return_value.comments.new.return_value = comments

        total, visible = check_comment_visibility("testuser", max_comments=10, lookback_days=7)

        assert total == 4
        assert visible == 2

    @patch("app.services.health_checker.get_reddit_client")
    def test_old_comments_excluded(self, mock_get_client):
        """Comments older than lookback_days are not counted."""
        now = datetime.now(timezone.utc)
        recent_ts = (now - timedelta(days=2)).timestamp()
        old_ts = (now - timedelta(days=10)).timestamp()

        comments = [
            _make_mock_comment("Recent comment", recent_ts),
            _make_mock_comment("Old comment", old_ts),
            _make_mock_comment("Very old comment", old_ts),
        ]

        mock_reddit = MagicMock()
        mock_get_client.return_value = mock_reddit
        mock_reddit.redditor.return_value.comments.new.return_value = comments

        total, visible = check_comment_visibility("testuser", max_comments=10, lookback_days=7)

        assert total == 1
        assert visible == 1

    @patch("app.services.health_checker.get_reddit_client")
    def test_no_comments_returns_zero(self, mock_get_client):
        """No comments at all returns (0, 0)."""
        mock_reddit = MagicMock()
        mock_get_client.return_value = mock_reddit
        mock_reddit.redditor.return_value.comments.new.return_value = []

        total, visible = check_comment_visibility("testuser", max_comments=10, lookback_days=7)

        assert total == 0
        assert visible == 0

    @patch("app.services.health_checker.get_reddit_client")
    def test_not_found_raises_health_check_error(self, mock_get_client):
        """NotFound exception is wrapped in HealthCheckError."""
        mock_reddit = MagicMock()
        mock_get_client.return_value = mock_reddit
        mock_reddit.redditor.return_value.comments.new.side_effect = NotFound(
            MagicMock(status_code=404)
        )

        with pytest.raises(HealthCheckError) as exc_info:
            check_comment_visibility("testuser", max_comments=10, lookback_days=7)

        assert "not found" in str(exc_info.value).lower()

    @patch("app.services.health_checker.get_reddit_client")
    def test_forbidden_raises_health_check_error(self, mock_get_client):
        """Forbidden exception is wrapped in HealthCheckError."""
        mock_reddit = MagicMock()
        mock_get_client.return_value = mock_reddit
        mock_reddit.redditor.return_value.comments.new.side_effect = Forbidden(
            MagicMock(status_code=403)
        )

        with pytest.raises(HealthCheckError) as exc_info:
            check_comment_visibility("testuser", max_comments=10, lookback_days=7)

        assert "forbidden" in str(exc_info.value).lower()

    @patch("app.services.health_checker.get_reddit_client")
    def test_comment_with_no_body_attribute(self, mock_get_client):
        """Comment without body attribute is not counted as visible."""
        now = datetime.now(timezone.utc)
        recent_ts = (now - timedelta(days=1)).timestamp()

        comment_no_body = MagicMock(spec=[])  # No attributes at all
        comment_no_body.created_utc = recent_ts
        # getattr(comment_no_body, "body", None) will return None

        comments = [
            _make_mock_comment("Visible", recent_ts),
            comment_no_body,
        ]

        mock_reddit = MagicMock()
        mock_get_client.return_value = mock_reddit
        mock_reddit.redditor.return_value.comments.new.return_value = comments

        total, visible = check_comment_visibility("testuser", max_comments=10, lookback_days=7)

        assert total == 2
        assert visible == 1


# ---------------------------------------------------------------------------
# Profile Accessibility Check Tests
# ---------------------------------------------------------------------------

from unittest.mock import patch, MagicMock

from prawcore.exceptions import (
    NotFound,
    Forbidden,
    RequestException,
    ResponseException,
    ServerError,
)

from app.services.health_checker import check_profile_accessibility, HealthCheckError


@pytest.fixture
def mock_reddit():
    """Mock the get_reddit_client to return a controlled Reddit instance."""
    with patch("app.services.health_checker.get_reddit_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        yield mock_client


class TestCheckProfileAccessibility:
    """Tests for check_profile_accessibility function."""

    def test_accessible_profile_returns_none(self, mock_reddit):
        """Active profile → (None, 'profile_check') to proceed to visibility check."""
        mock_redditor = MagicMock()
        mock_redditor.is_suspended = False
        mock_reddit.redditor.return_value = mock_redditor

        status, method = check_profile_accessibility("active_user")

        assert status is None
        assert method == "profile_check"
        mock_reddit.redditor.assert_called_once_with("active_user")

    def test_suspended_flag_returns_suspended(self, mock_reddit):
        """Profile with is_suspended=True → ('suspended', 'profile_check')."""
        mock_redditor = MagicMock()
        mock_redditor.is_suspended = True
        mock_reddit.redditor.return_value = mock_redditor

        status, method = check_profile_accessibility("suspended_user")

        assert status == "suspended"
        assert method == "profile_check"

    def test_404_not_found_returns_suspended(self, mock_reddit):
        """404 response → ('suspended', 'profile_check')."""
        mock_redditor = MagicMock()
        mock_reddit.redditor.return_value = mock_redditor

        # NotFound is raised when accessing redditor attributes (the API call)
        type(mock_redditor).is_suspended = property(
            lambda self: (_ for _ in ()).throw(NotFound(MagicMock(status_code=404)))
        )

        status, method = check_profile_accessibility("deleted_user")

        assert status == "suspended"
        assert method == "profile_check"

    def test_403_forbidden_returns_suspended(self, mock_reddit):
        """403 response → ('suspended', 'profile_check')."""
        mock_redditor = MagicMock()
        mock_reddit.redditor.return_value = mock_redditor

        type(mock_redditor).is_suspended = property(
            lambda self: (_ for _ in ()).throw(Forbidden(MagicMock(status_code=403)))
        )

        status, method = check_profile_accessibility("banned_user")

        assert status == "suspended"
        assert method == "profile_check"

    def test_network_error_raises_health_check_error(self, mock_reddit):
        """Network error → HealthCheckError raised."""
        mock_redditor = MagicMock()
        mock_reddit.redditor.return_value = mock_redditor

        type(mock_redditor).is_suspended = property(
            lambda self: (_ for _ in ()).throw(
                RequestException(MagicMock(), None, None)
            )
        )

        with pytest.raises(HealthCheckError) as exc_info:
            check_profile_accessibility("network_error_user")

        assert exc_info.value.original_error is not None

    def test_server_error_raises_health_check_error(self, mock_reddit):
        """Server error (5xx) → HealthCheckError raised."""
        mock_redditor = MagicMock()
        mock_reddit.redditor.return_value = mock_redditor

        type(mock_redditor).is_suspended = property(
            lambda self: (_ for _ in ()).throw(
                ServerError(MagicMock(status_code=500))
            )
        )

        with pytest.raises(HealthCheckError) as exc_info:
            check_profile_accessibility("server_error_user")

        assert exc_info.value.original_error is not None

    def test_response_exception_raises_health_check_error(self, mock_reddit):
        """ResponseException → HealthCheckError raised."""
        mock_redditor = MagicMock()
        mock_reddit.redditor.return_value = mock_redditor

        type(mock_redditor).is_suspended = property(
            lambda self: (_ for _ in ()).throw(
                ResponseException(MagicMock(status_code=429))
            )
        )

        with pytest.raises(HealthCheckError) as exc_info:
            check_profile_accessibility("rate_limited_user")

        assert exc_info.value.original_error is not None

    def test_unexpected_error_raises_health_check_error(self, mock_reddit):
        """Unexpected exception → HealthCheckError raised."""
        mock_redditor = MagicMock()
        mock_reddit.redditor.return_value = mock_redditor

        type(mock_redditor).is_suspended = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("something broke"))
        )

        with pytest.raises(HealthCheckError) as exc_info:
            check_profile_accessibility("broken_user")

        assert "something broke" in str(exc_info.value)

    def test_redditor_called_with_correct_username(self, mock_reddit):
        """Verify the username is passed correctly to reddit.redditor()."""
        mock_redditor = MagicMock()
        mock_redditor.is_suspended = False
        mock_reddit.redditor.return_value = mock_redditor

        check_profile_accessibility("test_username_123")

        mock_reddit.redditor.assert_called_once_with("test_username_123")


# ---------------------------------------------------------------------------
# check_avatar_health Orchestrator Tests
# ---------------------------------------------------------------------------

import uuid
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

from app.services.health_checker import check_avatar_health, HealthCheckError, HealthCheckResult
from app.models.avatar import Avatar


def _make_avatar(
    username: str = "test_avatar",
    health_status: str = "unknown",
    consecutive_check_failures: int = 0,
) -> Avatar:
    """Create a minimal Avatar instance for testing."""
    avatar = Avatar(
        id=uuid.uuid4(),
        reddit_username=username,
        health_status=health_status,
        consecutive_check_failures=consecutive_check_failures,
        active=True,
    )
    return avatar


class TestCheckAvatarHealth:
    """Tests for the check_avatar_health orchestrator function."""

    @patch("app.services.health_checker.check_comment_visibility")
    @patch("app.services.health_checker.check_profile_accessibility")
    @patch("app.services.health_checker.get_setting")
    def test_profile_suspended_sets_status(
        self, mock_get_setting, mock_profile, mock_visibility, db
    ):
        """Profile check returns suspended → avatar status becomes suspended."""
        mock_get_setting.side_effect = lambda _db, key: {
            "health_check_min_comments": "3",
            "health_check_visibility_threshold": "0.5",
            "health_check_max_comments_to_sample": "10",
            "health_check_comment_lookback_days": "7",
            "health_check_max_failures_before_limited": "3",
            "health_check_max_failures_before_unknown": "5",
        }[key]

        mock_profile.return_value = ("suspended", "profile_check")

        avatar = _make_avatar(health_status="active")
        db.add(avatar)
        db.flush()

        result = check_avatar_health(db, avatar)

        assert result.new_status == "suspended"
        assert result.detection_method == "profile_check"
        assert result.previous_status == "active"
        assert result.status_changed is True
        assert avatar.health_status == "suspended"
        assert avatar.consecutive_check_failures == 0
        assert avatar.health_status_changed_at is not None
        mock_visibility.assert_not_called()

    @patch("app.services.health_checker.check_comment_visibility")
    @patch("app.services.health_checker.check_profile_accessibility")
    @patch("app.services.health_checker.get_setting")
    def test_visibility_check_active(
        self, mock_get_setting, mock_profile, mock_visibility, db
    ):
        """Profile accessible + high visibility ratio → ACTIVE."""
        mock_get_setting.side_effect = lambda _db, key: {
            "health_check_min_comments": "3",
            "health_check_visibility_threshold": "0.5",
            "health_check_max_comments_to_sample": "10",
            "health_check_comment_lookback_days": "7",
            "health_check_max_failures_before_limited": "3",
            "health_check_max_failures_before_unknown": "5",
        }[key]

        mock_profile.return_value = (None, "profile_check")
        mock_visibility.return_value = (8, 7)  # 7/8 = 0.875 > 0.5

        avatar = _make_avatar(health_status="unknown", consecutive_check_failures=2)
        db.add(avatar)
        db.flush()

        result = check_avatar_health(db, avatar)

        assert result.new_status == "active"
        assert result.detection_method == "visibility_check"
        assert result.visibility_ratio == 7 / 8
        assert result.comments_sampled == 8
        assert result.comments_visible == 7
        assert avatar.health_status == "active"
        assert avatar.consecutive_check_failures == 0
        assert avatar.last_health_check is not None

    @patch("app.services.health_checker.check_comment_visibility")
    @patch("app.services.health_checker.check_profile_accessibility")
    @patch("app.services.health_checker.get_setting")
    def test_visibility_check_shadowbanned(
        self, mock_get_setting, mock_profile, mock_visibility, db
    ):
        """Profile accessible + zero visibility → SHADOWBANNED."""
        mock_get_setting.side_effect = lambda _db, key: {
            "health_check_min_comments": "3",
            "health_check_visibility_threshold": "0.5",
            "health_check_max_comments_to_sample": "10",
            "health_check_comment_lookback_days": "7",
            "health_check_max_failures_before_limited": "3",
            "health_check_max_failures_before_unknown": "5",
        }[key]

        mock_profile.return_value = (None, "profile_check")
        mock_visibility.return_value = (5, 0)  # 0/5 = 0.0

        avatar = _make_avatar(health_status="active")
        db.add(avatar)
        db.flush()

        result = check_avatar_health(db, avatar)

        assert result.new_status == "shadowbanned"
        assert result.visibility_ratio == 0.0
        assert avatar.health_status == "shadowbanned"

    @patch("app.services.health_checker.check_comment_visibility")
    @patch("app.services.health_checker.check_profile_accessibility")
    @patch("app.services.health_checker.get_setting")
    def test_visibility_check_limited(
        self, mock_get_setting, mock_profile, mock_visibility, db
    ):
        """Profile accessible + low visibility ratio → LIMITED."""
        mock_get_setting.side_effect = lambda _db, key: {
            "health_check_min_comments": "3",
            "health_check_visibility_threshold": "0.5",
            "health_check_max_comments_to_sample": "10",
            "health_check_comment_lookback_days": "7",
            "health_check_max_failures_before_limited": "3",
            "health_check_max_failures_before_unknown": "5",
        }[key]

        mock_profile.return_value = (None, "profile_check")
        mock_visibility.return_value = (10, 3)  # 3/10 = 0.3 < 0.5

        avatar = _make_avatar(health_status="active")
        db.add(avatar)
        db.flush()

        result = check_avatar_health(db, avatar)

        assert result.new_status == "limited"
        assert result.visibility_ratio == 0.3
        assert avatar.health_status == "limited"

    @patch("app.services.health_checker.check_comment_visibility")
    @patch("app.services.health_checker.check_profile_accessibility")
    @patch("app.services.health_checker.get_setting")
    def test_insufficient_comments_retains_previous_status(
        self, mock_get_setting, mock_profile, mock_visibility, db
    ):
        """Fewer than min_comments → retain previous status."""
        mock_get_setting.side_effect = lambda _db, key: {
            "health_check_min_comments": "3",
            "health_check_visibility_threshold": "0.5",
            "health_check_max_comments_to_sample": "10",
            "health_check_comment_lookback_days": "7",
            "health_check_max_failures_before_limited": "3",
            "health_check_max_failures_before_unknown": "5",
        }[key]

        mock_profile.return_value = (None, "profile_check")
        mock_visibility.return_value = (2, 1)  # 2 < min_comments(3)

        avatar = _make_avatar(health_status="active")
        db.add(avatar)
        db.flush()

        result = check_avatar_health(db, avatar)

        assert result.new_status == "active"  # retained
        assert result.previous_status == "active"
        assert result.status_changed is False
        assert avatar.health_status == "active"
        assert avatar.consecutive_check_failures == 0

    @patch("app.services.health_checker.check_profile_accessibility")
    @patch("app.services.health_checker.get_setting")
    def test_api_error_retains_status_and_increments_failures(
        self, mock_get_setting, mock_profile, db
    ):
        """HealthCheckError → retain previous status, increment failures."""
        mock_get_setting.side_effect = lambda _db, key: {
            "health_check_min_comments": "3",
            "health_check_visibility_threshold": "0.5",
            "health_check_max_comments_to_sample": "10",
            "health_check_comment_lookback_days": "7",
            "health_check_max_failures_before_limited": "3",
            "health_check_max_failures_before_unknown": "5",
        }[key]

        mock_profile.side_effect = HealthCheckError("Network timeout")

        avatar = _make_avatar(health_status="active", consecutive_check_failures=1)
        db.add(avatar)
        db.flush()

        result = check_avatar_health(db, avatar)

        assert result.new_status == "active"  # retained
        assert result.detection_method == "api_error"
        assert result.error is not None
        assert avatar.consecutive_check_failures == 2
        assert avatar.health_status == "active"

    @patch("app.services.health_checker.check_profile_accessibility")
    @patch("app.services.health_checker.get_setting")
    def test_failures_reach_limited_threshold(
        self, mock_get_setting, mock_profile, db
    ):
        """Failures reaching max_failures_before_limited → status becomes LIMITED."""
        mock_get_setting.side_effect = lambda _db, key: {
            "health_check_min_comments": "3",
            "health_check_visibility_threshold": "0.5",
            "health_check_max_comments_to_sample": "10",
            "health_check_comment_lookback_days": "7",
            "health_check_max_failures_before_limited": "3",
            "health_check_max_failures_before_unknown": "5",
        }[key]

        mock_profile.side_effect = HealthCheckError("Network timeout")

        # Already at 2 failures, this will be the 3rd (= max_failures_before_limited)
        avatar = _make_avatar(health_status="active", consecutive_check_failures=2)
        db.add(avatar)
        db.flush()

        result = check_avatar_health(db, avatar)

        assert result.new_status == "limited"
        assert avatar.consecutive_check_failures == 3
        assert avatar.health_status == "limited"

    @patch("app.services.health_checker.check_profile_accessibility")
    @patch("app.services.health_checker.get_setting")
    def test_failures_reach_unknown_threshold(
        self, mock_get_setting, mock_profile, db
    ):
        """Failures reaching max_failures_before_unknown → status becomes UNKNOWN."""
        mock_get_setting.side_effect = lambda _db, key: {
            "health_check_min_comments": "3",
            "health_check_visibility_threshold": "0.5",
            "health_check_max_comments_to_sample": "10",
            "health_check_comment_lookback_days": "7",
            "health_check_max_failures_before_limited": "3",
            "health_check_max_failures_before_unknown": "5",
        }[key]

        mock_profile.side_effect = HealthCheckError("Network timeout")

        # Already at 4 failures, this will be the 5th (= max_failures_before_unknown)
        avatar = _make_avatar(health_status="active", consecutive_check_failures=4)
        db.add(avatar)
        db.flush()

        result = check_avatar_health(db, avatar)

        assert result.new_status == "unknown"
        assert avatar.consecutive_check_failures == 5
        assert avatar.health_status == "unknown"

    @patch("app.services.health_checker.check_comment_visibility")
    @patch("app.services.health_checker.check_profile_accessibility")
    @patch("app.services.health_checker.get_setting")
    def test_successful_check_resets_failures(
        self, mock_get_setting, mock_profile, mock_visibility, db
    ):
        """Successful check resets consecutive_check_failures to 0."""
        mock_get_setting.side_effect = lambda _db, key: {
            "health_check_min_comments": "3",
            "health_check_visibility_threshold": "0.5",
            "health_check_max_comments_to_sample": "10",
            "health_check_comment_lookback_days": "7",
            "health_check_max_failures_before_limited": "3",
            "health_check_max_failures_before_unknown": "5",
        }[key]

        mock_profile.return_value = (None, "profile_check")
        mock_visibility.return_value = (5, 5)  # 5/5 = 1.0

        avatar = _make_avatar(health_status="limited", consecutive_check_failures=3)
        db.add(avatar)
        db.flush()

        result = check_avatar_health(db, avatar)

        assert result.new_status == "active"
        assert avatar.consecutive_check_failures == 0

    @patch("app.services.health_checker.check_comment_visibility")
    @patch("app.services.health_checker.check_profile_accessibility")
    @patch("app.services.health_checker.get_setting")
    def test_health_check_details_persisted(
        self, mock_get_setting, mock_profile, mock_visibility, db
    ):
        """Health check details JSON is persisted to avatar."""
        mock_get_setting.side_effect = lambda _db, key: {
            "health_check_min_comments": "3",
            "health_check_visibility_threshold": "0.5",
            "health_check_max_comments_to_sample": "10",
            "health_check_comment_lookback_days": "7",
            "health_check_max_failures_before_limited": "3",
            "health_check_max_failures_before_unknown": "5",
        }[key]

        mock_profile.return_value = (None, "profile_check")
        mock_visibility.return_value = (6, 4)  # 4/6 ≈ 0.667

        avatar = _make_avatar(health_status="unknown")
        db.add(avatar)
        db.flush()

        result = check_avatar_health(db, avatar)

        details = avatar.health_check_details
        assert details is not None
        assert details["comments_sampled"] == 6
        assert details["comments_visible"] == 4
        assert details["visibility_ratio"] == 4 / 6
        assert details["classification"] == "active"
        assert details["detection_method"] == "visibility_check"
        assert details["error"] is None
        assert "checked_at" in details
        assert "duration_ms" in details

    @patch("app.services.health_checker.check_comment_visibility")
    @patch("app.services.health_checker.check_profile_accessibility")
    @patch("app.services.health_checker.get_setting")
    def test_no_status_change_does_not_update_changed_at(
        self, mock_get_setting, mock_profile, mock_visibility, db
    ):
        """If status doesn't change, health_status_changed_at is not updated."""
        mock_get_setting.side_effect = lambda _db, key: {
            "health_check_min_comments": "3",
            "health_check_visibility_threshold": "0.5",
            "health_check_max_comments_to_sample": "10",
            "health_check_comment_lookback_days": "7",
            "health_check_max_failures_before_limited": "3",
            "health_check_max_failures_before_unknown": "5",
        }[key]

        mock_profile.return_value = (None, "profile_check")
        mock_visibility.return_value = (5, 5)  # 5/5 = 1.0 → active

        avatar = _make_avatar(health_status="active")
        avatar.health_status_changed_at = None
        db.add(avatar)
        db.flush()

        result = check_avatar_health(db, avatar)

        assert result.status_changed is False
        assert avatar.health_status_changed_at is None

    @patch("app.services.health_checker.check_comment_visibility")
    @patch("app.services.health_checker.check_profile_accessibility")
    @patch("app.services.health_checker.get_setting")
    def test_unknown_threshold_takes_precedence_over_limited(
        self, mock_get_setting, mock_profile, mock_visibility, db
    ):
        """When failures exceed both thresholds, UNKNOWN takes precedence."""
        mock_get_setting.side_effect = lambda _db, key: {
            "health_check_min_comments": "3",
            "health_check_visibility_threshold": "0.5",
            "health_check_max_comments_to_sample": "10",
            "health_check_comment_lookback_days": "7",
            "health_check_max_failures_before_limited": "3",
            "health_check_max_failures_before_unknown": "5",
        }[key]

        mock_profile.side_effect = HealthCheckError("Network timeout")

        # At 5 failures (after increment), both thresholds are met
        # UNKNOWN (>= 5) should take precedence over LIMITED (>= 3)
        avatar = _make_avatar(health_status="active", consecutive_check_failures=4)
        db.add(avatar)
        db.flush()

        result = check_avatar_health(db, avatar)

        assert result.new_status == "unknown"
        assert avatar.health_status == "unknown"

    @patch("app.services.health_checker.check_comment_visibility")
    @patch("app.services.health_checker.check_profile_accessibility")
    @patch("app.services.health_checker.get_setting")
    def test_visibility_error_after_profile_success(
        self, mock_get_setting, mock_profile, mock_visibility, db
    ):
        """Profile accessible but visibility check fails → retain status, increment failures."""
        mock_get_setting.side_effect = lambda _db, key: {
            "health_check_min_comments": "3",
            "health_check_visibility_threshold": "0.5",
            "health_check_max_comments_to_sample": "10",
            "health_check_comment_lookback_days": "7",
            "health_check_max_failures_before_limited": "3",
            "health_check_max_failures_before_unknown": "5",
        }[key]

        mock_profile.return_value = (None, "profile_check")
        mock_visibility.side_effect = HealthCheckError("Reddit API 500")

        avatar = _make_avatar(health_status="active", consecutive_check_failures=0)
        db.add(avatar)
        db.flush()

        result = check_avatar_health(db, avatar)

        assert result.new_status == "active"  # retained
        assert result.detection_method == "api_error"
        assert avatar.consecutive_check_failures == 1


# ---------------------------------------------------------------------------
# flag_pending_drafts_for_avatar Tests
# ---------------------------------------------------------------------------

from app.services.health_checker import flag_pending_drafts_for_avatar
from app.models.comment_draft import CommentDraft


class TestFlagPendingDraftsForAvatar:
    """Tests for flag_pending_drafts_for_avatar function."""

    def test_returns_count_of_pending_drafts(self, db):
        """Returns the number of pending drafts for the avatar."""
        avatar = _make_avatar(health_status="shadowbanned")
        db.add(avatar)
        db.flush()

        # Create pending drafts for this avatar
        from app.models.thread import RedditThread
        from app.models.client import Client

        client = Client(name="Test Client", keywords={"high": ["test"]})
        db.add(client)
        db.flush()

        thread = RedditThread(
            subreddit="test_sub",
            title="Test Thread",
            reddit_id="abc123",
            url="https://reddit.com/r/test/abc123",
        )
        db.add(thread)
        db.flush()

        draft1 = CommentDraft(
            thread_id=thread.id,
            client_id=client.id,
            avatar_id=avatar.id,
            status="pending",
            ai_draft="Draft 1",
        )
        draft2 = CommentDraft(
            thread_id=thread.id,
            client_id=client.id,
            avatar_id=avatar.id,
            status="pending",
            ai_draft="Draft 2",
        )
        db.add_all([draft1, draft2])
        db.flush()

        count = flag_pending_drafts_for_avatar(db, avatar.id, "shadowbanned")

        assert count == 2

    def test_ignores_non_pending_drafts(self, db):
        """Only counts drafts with status='pending', not approved/rejected/posted."""
        avatar = _make_avatar(health_status="suspended")
        db.add(avatar)
        db.flush()

        from app.models.thread import RedditThread
        from app.models.client import Client

        client = Client(name="Test Client 2", keywords={"high": ["test"]})
        db.add(client)
        db.flush()

        thread = RedditThread(
            subreddit="test_sub2",
            title="Test Thread 2",
            reddit_id="def456",
            url="https://reddit.com/r/test/def456",
        )
        db.add(thread)
        db.flush()

        pending_draft = CommentDraft(
            thread_id=thread.id,
            client_id=client.id,
            avatar_id=avatar.id,
            status="pending",
            ai_draft="Pending draft",
        )
        approved_draft = CommentDraft(
            thread_id=thread.id,
            client_id=client.id,
            avatar_id=avatar.id,
            status="approved",
            ai_draft="Approved draft",
        )
        posted_draft = CommentDraft(
            thread_id=thread.id,
            client_id=client.id,
            avatar_id=avatar.id,
            status="posted",
            ai_draft="Posted draft",
        )
        db.add_all([pending_draft, approved_draft, posted_draft])
        db.flush()

        count = flag_pending_drafts_for_avatar(db, avatar.id, "suspended")

        assert count == 1

    def test_returns_zero_when_no_pending_drafts(self, db):
        """Returns 0 when avatar has no pending drafts."""
        avatar = _make_avatar(health_status="shadowbanned")
        db.add(avatar)
        db.flush()

        count = flag_pending_drafts_for_avatar(db, avatar.id, "shadowbanned")

        assert count == 0

    def test_only_flags_drafts_for_specified_avatar(self, db):
        """Does not flag drafts belonging to other avatars."""
        avatar1 = _make_avatar(username="avatar1", health_status="shadowbanned")
        avatar2 = _make_avatar(username="avatar2", health_status="active")
        db.add_all([avatar1, avatar2])
        db.flush()

        from app.models.thread import RedditThread
        from app.models.client import Client

        client = Client(name="Test Client 3", keywords={"high": ["test"]})
        db.add(client)
        db.flush()

        thread = RedditThread(
            subreddit="test_sub3",
            title="Test Thread 3",
            reddit_id="ghi789",
            url="https://reddit.com/r/test/ghi789",
        )
        db.add(thread)
        db.flush()

        # Draft for avatar1 (should be flagged)
        draft_a1 = CommentDraft(
            thread_id=thread.id,
            client_id=client.id,
            avatar_id=avatar1.id,
            status="pending",
            ai_draft="Avatar 1 draft",
        )
        # Draft for avatar2 (should NOT be flagged)
        draft_a2 = CommentDraft(
            thread_id=thread.id,
            client_id=client.id,
            avatar_id=avatar2.id,
            status="pending",
            ai_draft="Avatar 2 draft",
        )
        db.add_all([draft_a1, draft_a2])
        db.flush()

        count = flag_pending_drafts_for_avatar(db, avatar1.id, "shadowbanned")

        assert count == 1
