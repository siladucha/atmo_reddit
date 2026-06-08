"""Unit tests for risk engine filtering and historical removal rate.

Tests for:
- filter_by_risk: partitioning opportunities by risk threshold
- compute_historical_removal_rate: querying posted drafts for removal ratio

Requirements: 2.4, 2.5
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.services.risk_engine import (
    RiskAssessment,
    compute_historical_removal_rate,
    filter_by_risk,
)


# ---------------------------------------------------------------------------
# Helpers — lightweight opportunity stub for filter_by_risk tests
# ---------------------------------------------------------------------------


@dataclass
class FakeOpportunity:
    """Minimal opportunity object with an id attribute for testing."""

    id: uuid.UUID
    subreddit: str = "test_sub"


def _make_assessment(final_score: int) -> RiskAssessment:
    """Create a minimal RiskAssessment with just the final_score set."""
    return RiskAssessment(
        base_score=final_score,
        account_age_factor=0,
        karma_factor=0,
        frequency_factor=0,
        moderation_factor=0,
        content_type_factor=0,
        health_modifier=0,
        phase_multiplier=1.0,
        final_score=final_score,
        flags=["high_risk"] if final_score > 70 else [],
    )


# ---------------------------------------------------------------------------
# filter_by_risk tests
# ---------------------------------------------------------------------------


class TestFilterByRisk:
    """Tests for filter_by_risk function."""

    def test_all_viable_when_below_threshold(self):
        """All opportunities pass when risk scores are below threshold."""
        opp1 = FakeOpportunity(id=uuid.uuid4())
        opp2 = FakeOpportunity(id=uuid.uuid4())
        opp3 = FakeOpportunity(id=uuid.uuid4())

        assessments = {
            opp1.id: _make_assessment(20),
            opp2.id: _make_assessment(30),
            opp3.id: _make_assessment(50),
        }

        viable, rejected = filter_by_risk([opp1, opp2, opp3], assessments, 60)

        assert len(viable) == 3
        assert len(rejected) == 0

    def test_all_rejected_when_above_threshold(self):
        """All opportunities rejected when risk scores exceed threshold."""
        opp1 = FakeOpportunity(id=uuid.uuid4())
        opp2 = FakeOpportunity(id=uuid.uuid4())

        assessments = {
            opp1.id: _make_assessment(80),
            opp2.id: _make_assessment(95),
        }

        viable, rejected = filter_by_risk([opp1, opp2], assessments, 60)

        assert len(viable) == 0
        assert len(rejected) == 2

    def test_mixed_partition(self):
        """Opportunities are correctly partitioned into viable and rejected."""
        opp_low = FakeOpportunity(id=uuid.uuid4())
        opp_high = FakeOpportunity(id=uuid.uuid4())
        opp_mid = FakeOpportunity(id=uuid.uuid4())

        assessments = {
            opp_low.id: _make_assessment(30),
            opp_high.id: _make_assessment(80),
            opp_mid.id: _make_assessment(55),
        }

        viable, rejected = filter_by_risk(
            [opp_low, opp_high, opp_mid], assessments, 60
        )

        assert len(viable) == 2
        assert opp_low in viable
        assert opp_mid in viable
        assert len(rejected) == 1
        assert rejected[0][0] is opp_high

    def test_score_at_threshold_is_viable(self):
        """Score exactly at the threshold is viable (not rejected)."""
        opp = FakeOpportunity(id=uuid.uuid4())
        assessments = {opp.id: _make_assessment(60)}

        viable, rejected = filter_by_risk([opp], assessments, 60)

        assert len(viable) == 1
        assert opp in viable
        assert len(rejected) == 0

    def test_score_one_above_threshold_is_rejected(self):
        """Score at threshold + 1 is rejected."""
        opp = FakeOpportunity(id=uuid.uuid4())
        assessments = {opp.id: _make_assessment(61)}

        viable, rejected = filter_by_risk([opp], assessments, 60)

        assert len(viable) == 0
        assert len(rejected) == 1

    def test_rejected_reason_contains_score_and_threshold(self):
        """Rejection reason includes the actual score and threshold values."""
        opp = FakeOpportunity(id=uuid.uuid4())
        assessments = {opp.id: _make_assessment(85)}

        _, rejected = filter_by_risk([opp], assessments, 60)

        reason = rejected[0][1]
        assert "85" in reason
        assert "60" in reason
        assert "exceeds threshold" in reason

    def test_empty_opportunity_list(self):
        """Empty input produces empty output."""
        viable, rejected = filter_by_risk([], {}, 50)

        assert viable == []
        assert rejected == []

    def test_missing_assessment_treated_as_viable(self):
        """Opportunity without assessment is included as viable."""
        opp = FakeOpportunity(id=uuid.uuid4())

        viable, rejected = filter_by_risk([opp], {}, 50)

        assert len(viable) == 1
        assert opp in viable
        assert len(rejected) == 0

    def test_threshold_zero_rejects_all_nonzero(self):
        """Threshold of 0 only accepts score == 0."""
        opp_zero = FakeOpportunity(id=uuid.uuid4())
        opp_one = FakeOpportunity(id=uuid.uuid4())

        assessments = {
            opp_zero.id: _make_assessment(0),
            opp_one.id: _make_assessment(1),
        }

        viable, rejected = filter_by_risk([opp_zero, opp_one], assessments, 0)

        assert len(viable) == 1
        assert opp_zero in viable
        assert len(rejected) == 1

    def test_threshold_100_accepts_all(self):
        """Threshold of 100 accepts all scores (max score is 100)."""
        opp = FakeOpportunity(id=uuid.uuid4())
        assessments = {opp.id: _make_assessment(100)}

        viable, rejected = filter_by_risk([opp], assessments, 100)

        assert len(viable) == 1
        assert len(rejected) == 0


# ---------------------------------------------------------------------------
# compute_historical_removal_rate tests (require DB)
# ---------------------------------------------------------------------------


class TestComputeHistoricalRemovalRate:
    """Integration tests for compute_historical_removal_rate.

    These require the DB fixture from conftest.py.
    """

    def _create_avatar(self, db: Session) -> uuid.UUID:
        """Create a minimal avatar for testing."""
        from app.models.avatar import Avatar

        avatar = Avatar(
            id=uuid.uuid4(),
            reddit_username=f"test_risk_user_{uuid.uuid4().hex[:8]}",
            warming_phase=2,
        )
        db.add(avatar)
        db.flush()
        return avatar.id

    def _create_subreddit(self, db: Session, name: str) -> uuid.UUID:
        """Create a subreddit record."""
        from app.models.subreddit import Subreddit

        sub = Subreddit(
            id=uuid.uuid4(),
            subreddit_name=name,
        )
        db.add(sub)
        db.flush()
        return sub.id

    def _create_thread(self, db: Session, subreddit_id: uuid.UUID, subreddit_name: str) -> uuid.UUID:
        """Create a RedditThread record."""
        from app.models.thread import RedditThread

        thread = RedditThread(
            id=uuid.uuid4(),
            subreddit_id=subreddit_id,
            subreddit=subreddit_name,
            reddit_native_id=f"t3_{uuid.uuid4().hex[:8]}",
            post_title="Test thread",
        )
        db.add(thread)
        db.flush()
        return thread.id

    def _create_posted_draft(
        self,
        db: Session,
        avatar_id: uuid.UUID,
        thread_id: uuid.UUID,
        is_deleted: bool = False,
        posted_at: datetime | None = None,
    ) -> uuid.UUID:
        """Create a CommentDraft in 'posted' status."""
        from app.models.comment_draft import CommentDraft

        if posted_at is None:
            posted_at = datetime.now(timezone.utc) - timedelta(days=10)

        draft = CommentDraft(
            id=uuid.uuid4(),
            avatar_id=avatar_id,
            thread_id=thread_id,
            status="posted",
            posted_at=posted_at,
            is_deleted=is_deleted,
            ai_draft="Test comment",
        )
        db.add(draft)
        db.flush()
        return draft.id

    def test_no_drafts_returns_zero(self, db: Session):
        """No posted drafts → removal rate 0.0."""
        avatar_id = self._create_avatar(db)

        rate = compute_historical_removal_rate(db, avatar_id, "nonexistent_sub")

        assert rate == 0.0

    def test_all_deleted_returns_one(self, db: Session):
        """All drafts deleted → removal rate 1.0."""
        avatar_id = self._create_avatar(db)
        sub_id = self._create_subreddit(db, "risky_sub")
        thread_id = self._create_thread(db, sub_id, "risky_sub")

        for _ in range(5):
            self._create_posted_draft(db, avatar_id, thread_id, is_deleted=True)

        rate = compute_historical_removal_rate(db, avatar_id, "risky_sub")

        assert rate == 1.0

    def test_none_deleted_returns_zero(self, db: Session):
        """No deletions → removal rate 0.0."""
        avatar_id = self._create_avatar(db)
        sub_id = self._create_subreddit(db, "safe_sub")
        thread_id = self._create_thread(db, sub_id, "safe_sub")

        for _ in range(3):
            self._create_posted_draft(db, avatar_id, thread_id, is_deleted=False)

        rate = compute_historical_removal_rate(db, avatar_id, "safe_sub")

        assert rate == 0.0

    def test_partial_deletion_rate(self, db: Session):
        """Mixed deletions → correct ratio."""
        avatar_id = self._create_avatar(db)
        sub_id = self._create_subreddit(db, "mixed_sub")
        thread_id = self._create_thread(db, sub_id, "mixed_sub")

        # 2 deleted out of 5 total
        for _ in range(2):
            self._create_posted_draft(db, avatar_id, thread_id, is_deleted=True)
        for _ in range(3):
            self._create_posted_draft(db, avatar_id, thread_id, is_deleted=False)

        rate = compute_historical_removal_rate(db, avatar_id, "mixed_sub")

        assert rate == pytest.approx(0.4)

    def test_respects_window_days(self, db: Session):
        """Only drafts within the window are counted."""
        avatar_id = self._create_avatar(db)
        sub_id = self._create_subreddit(db, "window_sub")
        thread_id = self._create_thread(db, sub_id, "window_sub")

        # Draft within window (30 days ago) — deleted
        self._create_posted_draft(
            db, avatar_id, thread_id,
            is_deleted=True,
            posted_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
        # Draft outside window (100 days ago) — deleted
        self._create_posted_draft(
            db, avatar_id, thread_id,
            is_deleted=True,
            posted_at=datetime.now(timezone.utc) - timedelta(days=100),
        )
        # Draft within window (10 days ago) — not deleted
        self._create_posted_draft(
            db, avatar_id, thread_id,
            is_deleted=False,
            posted_at=datetime.now(timezone.utc) - timedelta(days=10),
        )

        # With default 90-day window: 1 deleted + 1 not-deleted in window = 0.5
        rate = compute_historical_removal_rate(db, avatar_id, "window_sub", window_days=90)
        assert rate == pytest.approx(0.5)

        # With 20-day window: only the 10-days-ago draft counts = 0.0
        rate = compute_historical_removal_rate(db, avatar_id, "window_sub", window_days=20)
        assert rate == 0.0

    def test_filters_by_subreddit(self, db: Session):
        """Only drafts for the specified subreddit are counted."""
        avatar_id = self._create_avatar(db)
        sub_a_id = self._create_subreddit(db, "sub_a")
        sub_b_id = self._create_subreddit(db, "sub_b")
        thread_a = self._create_thread(db, sub_a_id, "sub_a")
        thread_b = self._create_thread(db, sub_b_id, "sub_b")

        # Deleted in sub_a
        self._create_posted_draft(db, avatar_id, thread_a, is_deleted=True)
        # Not deleted in sub_b
        self._create_posted_draft(db, avatar_id, thread_b, is_deleted=False)

        rate_a = compute_historical_removal_rate(db, avatar_id, "sub_a")
        rate_b = compute_historical_removal_rate(db, avatar_id, "sub_b")

        assert rate_a == 1.0
        assert rate_b == 0.0

    def test_filters_by_avatar_id(self, db: Session):
        """Only drafts for the specified avatar are counted."""
        avatar_1 = self._create_avatar(db)
        avatar_2 = self._create_avatar(db)
        sub_id = self._create_subreddit(db, "shared_sub")
        thread_id = self._create_thread(db, sub_id, "shared_sub")

        # Avatar 1 has a deleted draft
        self._create_posted_draft(db, avatar_1, thread_id, is_deleted=True)
        # Avatar 2 has a non-deleted draft
        self._create_posted_draft(db, avatar_2, thread_id, is_deleted=False)

        rate_1 = compute_historical_removal_rate(db, avatar_1, "shared_sub")
        rate_2 = compute_historical_removal_rate(db, avatar_2, "shared_sub")

        assert rate_1 == 1.0
        assert rate_2 == 0.0

    def test_ignores_non_posted_drafts(self, db: Session):
        """Only 'posted' status drafts are counted (pending/rejected excluded)."""
        from app.models.comment_draft import CommentDraft

        avatar_id = self._create_avatar(db)
        sub_id = self._create_subreddit(db, "status_sub")
        thread_id = self._create_thread(db, sub_id, "status_sub")

        # Posted and deleted
        self._create_posted_draft(db, avatar_id, thread_id, is_deleted=True)

        # Pending draft (should NOT be counted)
        pending_draft = CommentDraft(
            id=uuid.uuid4(),
            avatar_id=avatar_id,
            thread_id=thread_id,
            status="pending",
            is_deleted=True,
            ai_draft="Pending comment",
        )
        db.add(pending_draft)
        db.flush()

        rate = compute_historical_removal_rate(db, avatar_id, "status_sub")

        # Only 1 posted draft (deleted) → rate = 1.0
        assert rate == 1.0
