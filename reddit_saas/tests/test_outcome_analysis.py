"""Unit tests for outcome_analysis service."""

import uuid
import sys
sys.path.insert(0, '.')

from unittest.mock import MagicMock
from app.services.outcome_analysis import (
    SubredditSignal,
    ApproachSignal,
    AvatarOutcomeProfile,
    _determine_recommendation,
    _compute_approach_signals,
    _build_performance_summary,
)


class TestDetermineRecommendation:
    def test_insufficient_data_returns_maintain(self):
        signal = SubredditSignal(subreddit="test", total_comments=2, avg_karma=50.0)
        assert _determine_recommendation(signal) == "maintain"

    def test_high_removal_rate_returns_exit(self):
        signal = SubredditSignal(subreddit="test", total_comments=5, avg_karma=10.0, removal_rate=0.4)
        assert _determine_recommendation(signal) == "exit"

    def test_negative_karma_returns_reduce(self):
        signal = SubredditSignal(subreddit="test", total_comments=5, avg_karma=-2.0, removal_rate=0.0)
        assert _determine_recommendation(signal) == "reduce"

    def test_good_karma_positive_trend_returns_prioritize(self):
        signal = SubredditSignal(subreddit="test", total_comments=5, avg_karma=8.0, karma_trend=0.1, confidence=0.5)
        assert _determine_recommendation(signal) == "prioritize"

    def test_declining_trend_returns_reduce(self):
        signal = SubredditSignal(subreddit="test", total_comments=5, avg_karma=3.0, karma_trend=-0.5, confidence=0.6)
        assert _determine_recommendation(signal) == "reduce"

    def test_moderate_karma_stable_returns_maintain(self):
        signal = SubredditSignal(subreddit="test", total_comments=5, avg_karma=3.0, karma_trend=0.0, confidence=0.5)
        assert _determine_recommendation(signal) == "maintain"


class TestComputeApproachSignals:
    def test_groups_by_approach(self):
        draft1 = MagicMock(); draft1.comment_approach = "reframe_drop"; draft1.id = uuid.uuid4(); draft1.reddit_score = 10; draft1.is_deleted = False
        draft2 = MagicMock(); draft2.comment_approach = "the_scar"; draft2.id = uuid.uuid4(); draft2.reddit_score = 20; draft2.is_deleted = False
        draft3 = MagicMock(); draft3.comment_approach = "reframe_drop"; draft3.id = uuid.uuid4(); draft3.reddit_score = 5; draft3.is_deleted = False

        signals = _compute_approach_signals([draft1, draft2, draft3], {})
        assert len(signals) == 2
        assert signals[0].approach == "the_scar"
        assert signals[0].avg_karma == 20.0
        assert signals[1].approach == "reframe_drop"
        assert signals[1].avg_karma == 7.5

    def test_none_approach_becomes_unknown(self):
        draft = MagicMock(); draft.comment_approach = None; draft.id = uuid.uuid4(); draft.reddit_score = 5; draft.is_deleted = False
        signals = _compute_approach_signals([draft], {})
        assert signals[0].approach == "unknown"


class TestBuildPerformanceSummary:
    def test_empty_profile(self):
        profile = AvatarOutcomeProfile(avatar_id=uuid.uuid4())
        summary = _build_performance_summary(profile)
        assert summary["total_posted_30d"] == 0
        assert summary["avg_karma_per_comment"] == 0

    def test_populated_profile(self):
        profile = AvatarOutcomeProfile(
            avatar_id=uuid.uuid4(),
            total_posted=10, total_karma=150, avg_karma=15.0,
            removal_rate=0.1, avg_reply_count=3.5, karma_velocity=5.0,
            top_performing_subreddits=["cybersecurity", "netsec"],
            underperforming_subreddits=["msp"],
            approach_signals=[
                ApproachSignal(approach="reframe_drop", total_comments=5, avg_karma=20.0),
                ApproachSignal(approach="the_scar", total_comments=3, avg_karma=10.0),
            ],
        )
        summary = _build_performance_summary(profile)
        assert summary["total_posted_30d"] == 10
        assert summary["total_karma_30d"] == 150
        assert summary["top_subreddits"] == ["cybersecurity", "netsec"]
        assert len(summary["best_approaches"]) == 2


if __name__ == "__main__":
    import traceback
    test_classes = [TestDetermineRecommendation, TestComputeApproachSignals, TestBuildPerformanceSummary]
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
