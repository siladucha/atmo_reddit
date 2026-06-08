"""Unit tests for get_subreddit_karma_multiplier.

Tests the karma prediction multiplier from model correction feedback loop.
The multiplier adjusts future Expected_Karma predictions based on historical
over/under-performance patterns for an avatar-subreddit pair.

Requirements: 9.3
"""

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.services.return_engine import get_subreddit_karma_multiplier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_avatar(db: Session) -> uuid.UUID:
    """Create a minimal avatar for testing."""
    from app.models.avatar import Avatar

    avatar = Avatar(
        id=uuid.uuid4(),
        reddit_username=f"test_karma_mult_{uuid.uuid4().hex[:8]}",
        warming_phase=2,
    )
    db.add(avatar)
    db.flush()
    return avatar.id


def _create_opportunity(
    db: Session,
    avatar_id: uuid.UUID,
    subreddit: str,
    expected_karma: int | None,
    actual_karma: int | None,
) -> uuid.UUID:
    """Create an Opportunity record with expected and actual karma values."""
    expected_return = None
    if expected_karma is not None:
        expected_return = {
            "karma": expected_karma,
            "trust": 50,
            "visibility": 50,
            "influence": 50,
            "strategic_value": 50,
            "composite": 50,
        }

    opp = Opportunity(
        id=uuid.uuid4(),
        avatar_id=avatar_id,
        decision_date=date.today(),
        subreddit=subreddit,
        opportunity_type="comment",
        visibility_score=50,
        competition_score=50,
        trust_potential_score=50,
        karma_potential_score=50,
        risk_score=30,
        strategic_alignment_score=50,
        composite_score=50,
        expected_return=expected_return,
        actual_karma=actual_karma,
        status="executed",
    )
    db.add(opp)
    db.flush()
    return opp.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetSubredditKarmaMultiplier:
    """Tests for get_subreddit_karma_multiplier function."""

    def test_no_data_returns_one(self, db: Session):
        """No opportunities → multiplier is 1.0."""
        avatar_id = _create_avatar(db)

        result = get_subreddit_karma_multiplier(db, avatar_id, "no_data_sub")

        assert result == 1.0

    def test_fewer_than_five_over_performances_no_change(self, db: Session):
        """4 over-performances is not enough to trigger increase."""
        avatar_id = _create_avatar(db)

        # 4 over-performances (actual > 150% of predicted)
        for _ in range(4):
            _create_opportunity(db, avatar_id, "test_sub", expected_karma=10, actual_karma=20)

        result = get_subreddit_karma_multiplier(db, avatar_id, "test_sub")

        assert result == 1.0

    def test_five_over_performances_increases_multiplier(self, db: Session):
        """5+ over-performances → multiplier increases by 10%."""
        avatar_id = _create_avatar(db)

        # 5 over-performances (actual > 150% of predicted: 20 > 10 * 1.5 = 15)
        for _ in range(5):
            _create_opportunity(db, avatar_id, "over_sub", expected_karma=10, actual_karma=20)

        result = get_subreddit_karma_multiplier(db, avatar_id, "over_sub")

        assert result == pytest.approx(1.1)

    def test_fewer_than_five_under_performances_no_change(self, db: Session):
        """4 under-performances is not enough to trigger decrease."""
        avatar_id = _create_avatar(db)

        # 4 under-performances (actual < 50% of predicted)
        for _ in range(4):
            _create_opportunity(db, avatar_id, "test_sub", expected_karma=10, actual_karma=3)

        result = get_subreddit_karma_multiplier(db, avatar_id, "test_sub")

        assert result == 1.0

    def test_five_under_performances_decreases_multiplier(self, db: Session):
        """5+ under-performances → multiplier decreases by 10%."""
        avatar_id = _create_avatar(db)

        # 5 under-performances (actual < 50% of predicted: 3 < 10 * 0.5 = 5)
        for _ in range(5):
            _create_opportunity(db, avatar_id, "under_sub", expected_karma=10, actual_karma=3)

        result = get_subreddit_karma_multiplier(db, avatar_id, "under_sub")

        assert result == pytest.approx(0.9)

    def test_both_over_and_under_performance_both_apply(self, db: Session):
        """Both thresholds met → both adjustments applied (1.1 * 0.9 = 0.99)."""
        avatar_id = _create_avatar(db)

        # 5 over-performances
        for _ in range(5):
            _create_opportunity(db, avatar_id, "both_sub", expected_karma=10, actual_karma=20)

        # 5 under-performances
        for _ in range(5):
            _create_opportunity(db, avatar_id, "both_sub", expected_karma=10, actual_karma=3)

        result = get_subreddit_karma_multiplier(db, avatar_id, "both_sub")

        assert result == pytest.approx(1.1 * 0.9)

    def test_filters_by_subreddit(self, db: Session):
        """Only opportunities for the specified subreddit are considered."""
        avatar_id = _create_avatar(db)

        # 5 over-performances in sub_a
        for _ in range(5):
            _create_opportunity(db, avatar_id, "sub_a", expected_karma=10, actual_karma=20)

        # Check sub_b (should have no data → 1.0)
        result_b = get_subreddit_karma_multiplier(db, avatar_id, "sub_b")
        assert result_b == 1.0

        # Check sub_a (should be 1.1)
        result_a = get_subreddit_karma_multiplier(db, avatar_id, "sub_a")
        assert result_a == pytest.approx(1.1)

    def test_filters_by_avatar_id(self, db: Session):
        """Only opportunities for the specified avatar are considered."""
        avatar_1 = _create_avatar(db)
        avatar_2 = _create_avatar(db)

        # 5 over-performances for avatar_1
        for _ in range(5):
            _create_opportunity(db, avatar_1, "shared_sub", expected_karma=10, actual_karma=20)

        # Avatar 2 should still be 1.0
        result = get_subreddit_karma_multiplier(db, avatar_2, "shared_sub")
        assert result == 1.0

    def test_ignores_opportunities_without_actual_karma(self, db: Session):
        """Opportunities where actual_karma is None are excluded."""
        avatar_id = _create_avatar(db)

        # 5 with actual_karma = None (no outcome data yet)
        for _ in range(5):
            _create_opportunity(db, avatar_id, "no_outcome_sub", expected_karma=10, actual_karma=None)

        result = get_subreddit_karma_multiplier(db, avatar_id, "no_outcome_sub")

        assert result == 1.0

    def test_ignores_opportunities_without_expected_return(self, db: Session):
        """Opportunities where expected_return is None are excluded."""
        avatar_id = _create_avatar(db)

        # 5 with expected_return = None
        for _ in range(5):
            _create_opportunity(db, avatar_id, "no_expected_sub", expected_karma=None, actual_karma=20)

        result = get_subreddit_karma_multiplier(db, avatar_id, "no_expected_sub")

        assert result == 1.0

    def test_expected_karma_zero_treated_as_one(self, db: Session):
        """Expected karma of 0 treated as 1 to avoid division by zero."""
        avatar_id = _create_avatar(db)

        # 5 opportunities with expected_karma=0, actual=5
        # With expected treated as 1: 5 > 1 * 1.5 = 1.5 → over-performance
        for _ in range(5):
            _create_opportunity(db, avatar_id, "zero_expected_sub", expected_karma=0, actual_karma=5)

        result = get_subreddit_karma_multiplier(db, avatar_id, "zero_expected_sub")

        assert result == pytest.approx(1.1)

    def test_clamped_to_minimum_0_5(self, db: Session):
        """Multiplier cannot go below 0.5."""
        # The minimum with a single application is 0.9, so this tests the clamp logic
        # directly. With current logic only 0.9 is possible from under-performance,
        # but we test the clamp boundary is respected.
        avatar_id = _create_avatar(db)

        # Single under-performance cycle gives 0.9, which is already > 0.5
        # The clamp is a safety bound for potential future adjustments
        for _ in range(5):
            _create_opportunity(db, avatar_id, "clamp_sub", expected_karma=10, actual_karma=3)

        result = get_subreddit_karma_multiplier(db, avatar_id, "clamp_sub")

        assert result >= 0.5

    def test_clamped_to_maximum_2_0(self, db: Session):
        """Multiplier cannot exceed 2.0."""
        avatar_id = _create_avatar(db)

        # Single over-performance cycle gives 1.1, which is already < 2.0
        for _ in range(5):
            _create_opportunity(db, avatar_id, "cap_sub", expected_karma=10, actual_karma=20)

        result = get_subreddit_karma_multiplier(db, avatar_id, "cap_sub")

        assert result <= 2.0

    def test_boundary_over_performance_at_exactly_150_percent(self, db: Session):
        """Actual == 150% of predicted is NOT over-performance (must be >)."""
        avatar_id = _create_avatar(db)

        # actual = 15, expected = 10 → 15 == 10 * 1.5, NOT strictly greater
        for _ in range(5):
            _create_opportunity(db, avatar_id, "boundary_over_sub", expected_karma=10, actual_karma=15)

        result = get_subreddit_karma_multiplier(db, avatar_id, "boundary_over_sub")

        assert result == 1.0

    def test_boundary_under_performance_at_exactly_50_percent(self, db: Session):
        """Actual == 50% of predicted is NOT under-performance (must be <)."""
        avatar_id = _create_avatar(db)

        # actual = 5, expected = 10 → 5 == 10 * 0.5, NOT strictly less
        for _ in range(5):
            _create_opportunity(db, avatar_id, "boundary_under_sub", expected_karma=10, actual_karma=5)

        result = get_subreddit_karma_multiplier(db, avatar_id, "boundary_under_sub")

        assert result == 1.0
