"""Unit tests for feedback_loop service."""

import uuid
import sys
sys.path.insert(0, '.')

from unittest.mock import MagicMock
from app.services.feedback_loop import get_epg_subreddit_adjustment, get_all_epg_adjustments
from app.services.outcome_analysis import (
    SubredditSignal, AvatarOutcomeProfile, _compute_subreddit_adjustments,
)


class TestComputeSubredditAdjustments:
    def test_empty_profile(self):
        profile = AvatarOutcomeProfile(avatar_id=uuid.uuid4())
        adj = _compute_subreddit_adjustments(profile)
        assert adj == {}

    def test_prioritize_signal_gives_positive_delta(self):
        profile = AvatarOutcomeProfile(
            avatar_id=uuid.uuid4(),
            subreddit_signals=[
                SubredditSignal(subreddit="good_sub", total_comments=10, avg_karma=15.0, recommendation="prioritize", confidence=0.8),
            ],
        )
        adj = _compute_subreddit_adjustments(profile)
        assert "good_sub" in adj
        assert adj["good_sub"] > 0

    def test_exit_signal_gives_strong_negative_delta(self):
        profile = AvatarOutcomeProfile(
            avatar_id=uuid.uuid4(),
            subreddit_signals=[
                SubredditSignal(subreddit="bad_sub", total_comments=10, avg_karma=2.0, removal_rate=0.4, recommendation="exit", confidence=0.5),
            ],
        )
        adj = _compute_subreddit_adjustments(profile)
        assert "bad_sub" in adj
        assert adj["bad_sub"] < -0.5

    def test_low_confidence_ignored(self):
        profile = AvatarOutcomeProfile(
            avatar_id=uuid.uuid4(),
            subreddit_signals=[
                SubredditSignal(subreddit="maybe", total_comments=2, recommendation="prioritize", confidence=0.2),
            ],
        )
        adj = _compute_subreddit_adjustments(profile)
        assert adj == {}


class TestEPGAdjustmentRead:
    def test_returns_zero_for_unknown(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        result = get_epg_subreddit_adjustment(db, uuid.uuid4(), "unknown_sub")
        assert result == 0.0

    def test_returns_stored_value(self):
        db = MagicMock()
        setting = MagicMock()
        setting.value = "0.3"
        db.query.return_value.filter.return_value.first.return_value = setting
        result = get_epg_subreddit_adjustment(db, uuid.uuid4(), "good_sub")
        assert result == 0.3

    def test_handles_invalid_value(self):
        db = MagicMock()
        setting = MagicMock()
        setting.value = "not_a_number"
        db.query.return_value.filter.return_value.first.return_value = setting
        result = get_epg_subreddit_adjustment(db, uuid.uuid4(), "sub")
        assert result == 0.0


if __name__ == "__main__":
    import traceback
    test_classes = [TestComputeSubredditAdjustments, TestEPGAdjustmentRead]
    passed = 0; failed = 0
    for cls in test_classes:
        instance = cls()
        for method in dir(instance):
            if method.startswith("test_"):
                try:
                    getattr(instance, method)()
                    passed += 1; print(f"  ✓ {cls.__name__}.{method}")
                except Exception as e:
                    failed += 1; print(f"  ✗ {cls.__name__}.{method}: {e}"); traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    exit(1 if failed else 0)
