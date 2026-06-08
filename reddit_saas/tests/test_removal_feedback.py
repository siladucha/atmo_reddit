"""Unit tests for removal feedback and risk weight adjustment.

Tests for:
- get_removal_risk_adjustment: queries removal events and returns accumulated adjustment
- apply_removal_feedback: records removal and returns updated adjustment
- _compute_moderation_factor: now incorporates risk_adjustment from community_state

Requirements: 13.6
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.services.risk_engine import (
    _compute_moderation_factor,
    get_removal_risk_adjustment,
    apply_removal_feedback,
    _REMOVAL_RISK_ADJUSTMENT_PER_EVENT,
    _MAX_REMOVAL_RISK_ADJUSTMENT,
)


# ---------------------------------------------------------------------------
# _compute_moderation_factor tests (with risk_adjustment)
# ---------------------------------------------------------------------------


class TestComputeModerationFactorWithAdjustment:
    """Tests that moderation factor incorporates removal feedback adjustment."""

    def test_zero_removals_zero_adjustment(self):
        """No removals and no adjustment → factor is 0."""
        state = {"removal_count_30d": 0, "risk_adjustment": 0}
        assert _compute_moderation_factor(state) == 0

    def test_zero_removals_with_adjustment(self):
        """No recent removals but historical adjustment → factor equals adjustment."""
        state = {"removal_count_30d": 0, "risk_adjustment": 15}
        assert _compute_moderation_factor(state) == 15

    def test_one_removal_no_adjustment(self):
        """One removal, no feedback adjustment → factor is 10."""
        state = {"removal_count_30d": 1, "risk_adjustment": 0}
        assert _compute_moderation_factor(state) == 10

    def test_one_removal_with_adjustment(self):
        """One removal + 5 adjustment → factor is 15."""
        state = {"removal_count_30d": 1, "risk_adjustment": 5}
        assert _compute_moderation_factor(state) == 15

    def test_three_removals_no_adjustment(self):
        """3+ removals maxes base at 30, no adjustment → 30."""
        state = {"removal_count_30d": 3, "risk_adjustment": 0}
        assert _compute_moderation_factor(state) == 30

    def test_three_removals_with_adjustment_capped(self):
        """3+ removals + adjustment → still capped at 30."""
        state = {"removal_count_30d": 3, "risk_adjustment": 15}
        # 30 (base from 3+ removals) + 15 = 45 → capped at 30
        assert _compute_moderation_factor(state) == 30

    def test_two_removals_with_max_adjustment_capped(self):
        """2 removals (20) + max adjustment (30) → capped at 30."""
        state = {"removal_count_30d": 2, "risk_adjustment": 30}
        assert _compute_moderation_factor(state) == 30

    def test_missing_risk_adjustment_key(self):
        """Missing risk_adjustment key defaults to 0."""
        state = {"removal_count_30d": 1}
        assert _compute_moderation_factor(state) == 10

    def test_adjustment_per_event_is_five(self):
        """Verify the constant is 5 per removal event."""
        assert _REMOVAL_RISK_ADJUSTMENT_PER_EVENT == 5

    def test_max_adjustment_is_thirty(self):
        """Verify the max cap is 30."""
        assert _MAX_REMOVAL_RISK_ADJUSTMENT == 30


# ---------------------------------------------------------------------------
# get_removal_risk_adjustment (requires DB)
# ---------------------------------------------------------------------------


class TestGetRemovalRiskAdjustment:
    """Integration tests for get_removal_risk_adjustment."""

    def _create_avatar(self, db: Session) -> uuid.UUID:
        """Create a minimal avatar for testing."""
        from app.models.avatar import Avatar

        avatar = Avatar(
            id=uuid.uuid4(),
            reddit_username=f"feedback_user_{uuid.uuid4().hex[:8]}",
            warming_phase=2,
        )
        db.add(avatar)
        db.flush()
        return avatar.id

    def _create_opportunity(
        self,
        db: Session,
        avatar_id: uuid.UUID,
        subreddit: str,
        actual_removal: bool = False,
    ) -> uuid.UUID:
        """Create an Opportunity record."""
        from app.models.opportunity import Opportunity

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
            status="executed",
            actual_removal=actual_removal,
        )
        db.add(opp)
        db.flush()
        return opp.id

    def test_no_removals_returns_zero(self, db: Session):
        """No removal events → adjustment is 0."""
        avatar_id = self._create_avatar(db)
        # Create some opportunities without removal
        for _ in range(3):
            self._create_opportunity(db, avatar_id, "test_sub", actual_removal=False)

        adjustment = get_removal_risk_adjustment(db, avatar_id, "test_sub")
        assert adjustment == 0

    def test_one_removal_returns_five(self, db: Session):
        """One removal event → adjustment is 5."""
        avatar_id = self._create_avatar(db)
        self._create_opportunity(db, avatar_id, "risky_sub", actual_removal=True)
        self._create_opportunity(db, avatar_id, "risky_sub", actual_removal=False)

        adjustment = get_removal_risk_adjustment(db, avatar_id, "risky_sub")
        assert adjustment == 5

    def test_three_removals_returns_fifteen(self, db: Session):
        """Three removal events → adjustment is 15."""
        avatar_id = self._create_avatar(db)
        for _ in range(3):
            self._create_opportunity(db, avatar_id, "mod_sub", actual_removal=True)

        adjustment = get_removal_risk_adjustment(db, avatar_id, "mod_sub")
        assert adjustment == 15

    def test_six_removals_capped_at_thirty(self, db: Session):
        """Six removal events → capped at 30."""
        avatar_id = self._create_avatar(db)
        for _ in range(6):
            self._create_opportunity(db, avatar_id, "strict_sub", actual_removal=True)

        adjustment = get_removal_risk_adjustment(db, avatar_id, "strict_sub")
        assert adjustment == 30

    def test_ten_removals_still_capped(self, db: Session):
        """Many removals → still capped at 30."""
        avatar_id = self._create_avatar(db)
        for _ in range(10):
            self._create_opportunity(db, avatar_id, "max_sub", actual_removal=True)

        adjustment = get_removal_risk_adjustment(db, avatar_id, "max_sub")
        assert adjustment == 30

    def test_filters_by_subreddit(self, db: Session):
        """Only removals in the specified subreddit count."""
        avatar_id = self._create_avatar(db)
        self._create_opportunity(db, avatar_id, "sub_a", actual_removal=True)
        self._create_opportunity(db, avatar_id, "sub_a", actual_removal=True)
        self._create_opportunity(db, avatar_id, "sub_b", actual_removal=True)

        adjustment_a = get_removal_risk_adjustment(db, avatar_id, "sub_a")
        adjustment_b = get_removal_risk_adjustment(db, avatar_id, "sub_b")

        assert adjustment_a == 10  # 2 removals × 5
        assert adjustment_b == 5   # 1 removal × 5

    def test_filters_by_avatar(self, db: Session):
        """Only removals for the specified avatar count."""
        avatar_1 = self._create_avatar(db)
        avatar_2 = self._create_avatar(db)

        self._create_opportunity(db, avatar_1, "shared_sub", actual_removal=True)
        self._create_opportunity(db, avatar_1, "shared_sub", actual_removal=True)
        self._create_opportunity(db, avatar_2, "shared_sub", actual_removal=True)

        adj_1 = get_removal_risk_adjustment(db, avatar_1, "shared_sub")
        adj_2 = get_removal_risk_adjustment(db, avatar_2, "shared_sub")

        assert adj_1 == 10  # 2 × 5
        assert adj_2 == 5   # 1 × 5

    def test_nonexistent_avatar_returns_zero(self, db: Session):
        """Non-existent avatar → adjustment is 0."""
        fake_id = uuid.uuid4()
        adjustment = get_removal_risk_adjustment(db, fake_id, "any_sub")
        assert adjustment == 0


# ---------------------------------------------------------------------------
# apply_removal_feedback (requires DB)
# ---------------------------------------------------------------------------


class TestApplyRemovalFeedback:
    """Integration tests for apply_removal_feedback."""

    def _create_avatar(self, db: Session) -> uuid.UUID:
        """Create a minimal avatar for testing."""
        from app.models.avatar import Avatar

        avatar = Avatar(
            id=uuid.uuid4(),
            reddit_username=f"apply_fb_user_{uuid.uuid4().hex[:8]}",
            warming_phase=2,
        )
        db.add(avatar)
        db.flush()
        return avatar.id

    def _create_opportunity(
        self,
        db: Session,
        avatar_id: uuid.UUID,
        subreddit: str,
        actual_removal: bool = False,
    ) -> uuid.UUID:
        """Create an Opportunity record."""
        from app.models.opportunity import Opportunity

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
            status="executed",
            actual_removal=actual_removal,
        )
        db.add(opp)
        db.flush()
        return opp.id

    def test_marks_opportunity_as_removed(self, db: Session):
        """apply_removal_feedback sets actual_removal=True on the opportunity."""
        from app.models.opportunity import Opportunity

        avatar_id = self._create_avatar(db)
        opp_id = self._create_opportunity(db, avatar_id, "feedback_sub", actual_removal=False)

        apply_removal_feedback(db, avatar_id, "feedback_sub", opp_id)

        opp = db.query(Opportunity).filter(Opportunity.id == opp_id).first()
        assert opp.actual_removal is True

    def test_returns_accumulated_adjustment(self, db: Session):
        """apply_removal_feedback returns the new accumulated adjustment."""
        avatar_id = self._create_avatar(db)
        opp_id = self._create_opportunity(db, avatar_id, "accum_sub", actual_removal=False)

        adjustment = apply_removal_feedback(db, avatar_id, "accum_sub", opp_id)
        assert adjustment == 5  # First removal → 5

    def test_multiple_removals_accumulate(self, db: Session):
        """Multiple removal feedbacks accumulate correctly."""
        avatar_id = self._create_avatar(db)

        # First removal
        opp1 = self._create_opportunity(db, avatar_id, "multi_sub", actual_removal=False)
        adj1 = apply_removal_feedback(db, avatar_id, "multi_sub", opp1)
        assert adj1 == 5

        # Second removal
        opp2 = self._create_opportunity(db, avatar_id, "multi_sub", actual_removal=False)
        adj2 = apply_removal_feedback(db, avatar_id, "multi_sub", opp2)
        assert adj2 == 10

        # Third removal
        opp3 = self._create_opportunity(db, avatar_id, "multi_sub", actual_removal=False)
        adj3 = apply_removal_feedback(db, avatar_id, "multi_sub", opp3)
        assert adj3 == 15

    def test_does_not_double_mark(self, db: Session):
        """Calling apply_removal_feedback twice on same opportunity doesn't double-count."""
        from app.models.opportunity import Opportunity

        avatar_id = self._create_avatar(db)
        opp_id = self._create_opportunity(db, avatar_id, "double_sub", actual_removal=False)

        adj1 = apply_removal_feedback(db, avatar_id, "double_sub", opp_id)
        assert adj1 == 5

        # Call again — should not increase since opportunity is already marked
        adj2 = apply_removal_feedback(db, avatar_id, "double_sub", opp_id)
        assert adj2 == 5  # Still 5, not 10
