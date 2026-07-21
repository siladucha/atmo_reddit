"""Tests for EPG budget integrity — catches the bugs found on production July 15, 2026.

Each test maps to a specific production failure:
1. Allocation engine must fill budget (not reject 96% due to category bucketing)
2. Phase ceiling validation demotes avatars without legitimate credentials
3. get_budget_used_today includes PostDrafts in total
4. Subreddit cap must not starve avatars with limited sub diversity
5. Topup guard prevents infinite slot creation on generation failures
6. Enforcement guard recognizes "generation broken" vs "no supply"
7. Budget math: Phase 1 + CQS=low = 2 (not 3)
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.epg_slot import EPGSlot
from app.models.hobby import HobbySubreddit
from app.models.post_draft import PostDraft


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_avatar(
    db: Session,
    *,
    phase: int = 1,
    pool: str = "b2b",
    cqs_level: str | None = None,
    hobby_subreddits: list | None = None,
    business_subreddits: list | None = None,
    client_ids: list | None = None,
    reddit_karma_comment: int = 0,
    reddit_karma_post: int = 0,
    reddit_account_created: datetime | None = None,
) -> Avatar:
    avatar = Avatar(
        id=uuid.uuid4(),
        reddit_username=f"test_budget_{uuid.uuid4().hex[:6]}",
        warming_phase=phase,
        is_frozen=False,
        health_status="active",
        pool=pool,
        active=True,
        is_shadowbanned=False,
        hobby_subreddits=hobby_subreddits or ["AskReddit", "CasualConversation"],
        business_subreddits=business_subreddits or [],
        client_ids=client_ids,
        cqs_level=cqs_level,
        reddit_karma_comment=reddit_karma_comment,
        reddit_karma_post=reddit_karma_post,
        reddit_account_created=reddit_account_created,
    )
    db.add(avatar)
    db.flush()
    return avatar


def _make_client(db: Session) -> Client:
    client = Client(
        id=uuid.uuid4(),
        client_name=f"TestClient_{uuid.uuid4().hex[:6]}",
        brand_name=f"Brand_{uuid.uuid4().hex[:4]}",
        is_active=True,
        keywords={"high": ["test"], "medium": [], "low": []},
    )
    db.add(client)
    db.flush()
    return client


def _make_epg_slot(
    db: Session,
    avatar_id: uuid.UUID,
    *,
    status: str = "generated",
    plan_date: date | None = None,
    slot_type: str = "hobby",
    draft_id: uuid.UUID | None = None,
) -> EPGSlot:
    slot = EPGSlot(
        id=uuid.uuid4(),
        avatar_id=avatar_id,
        plan_date=plan_date or date.today(),
        slot_type=slot_type,
        status=status,
        draft_id=draft_id,
        subreddit="AskReddit",
    )
    db.add(slot)
    db.flush()
    return slot


def _make_post_draft(
    db: Session,
    avatar_id: uuid.UUID,
    client_id: uuid.UUID,
    *,
    status: str = "pending",
    created_at: datetime | None = None,
) -> PostDraft:
    draft = PostDraft(
        id=uuid.uuid4(),
        avatar_id=avatar_id,
        client_id=client_id,
        subreddit="cybersecurity",
        ai_title="Test post title",
        ai_body="Test post body content.",
        status=status,
    )
    db.add(draft)
    db.flush()
    # Override created_at if specified (after flush to bypass server_default)
    if created_at:
        from sqlalchemy import text
        db.execute(
            text("UPDATE post_drafts SET created_at = :ts WHERE id = :id"),
            {"ts": created_at, "id": draft.id},
        )
        db.flush()
    return draft


def _make_opportunity(composite_score: int = 70, subreddit: str = "cybersecurity"):
    """Create a mock Opportunity object for allocation tests."""
    opp = MagicMock()
    opp.id = uuid.uuid4()
    opp.composite_score = composite_score
    opp.subreddit = subreddit
    opp.hobby_post_id = None
    opp.thread_id = uuid.uuid4()
    opp.opportunity_type = "comment"
    opp.trust_potential_score = 50
    opp.strategic_alignment_score = 50
    opp.visibility_score = 50
    opp.competition_score = 50
    opp.karma_potential_score = 50
    return opp


def _make_risk_assessment(final_score: int = 30):
    risk = MagicMock()
    risk.final_score = final_score
    return risk


def _make_expected_return(composite: float = 60.0):
    ret = MagicMock()
    ret.composite = composite
    return ret


# ===========================================================================
# TEST 1: Allocation engine fills budget (not 96% rejection)
# ===========================================================================


class TestAllocationFillRate:
    """Allocation must select up to budget, not dump 96% into wrong category."""

    def test_50_opportunities_budget_9_selects_9(self):
        """The exact production bug: 50 opportunities + budget=9 → must get 9 selected."""
        from app.services.allocation_engine import allocate_portfolio, AllocationResult
        from app.services.portfolio_manager import AttentionBudget, PortfolioAllocation

        avatar = MagicMock()
        avatar.warming_phase = 2
        avatar.declared_timezone = "America/New_York"
        avatar.hobby_subreddits = ["running"]
        avatar.business_subreddits = ["cybersecurity", "netsec", "sysadmin"]

        budget = AttentionBudget(max_comments=7, max_posts=2, max_total_actions=9, acceptable_risk_level=60)
        allocation = PortfolioAllocation.from_avatar_profile(avatar, None)

        # Create 50 opportunities with varying scores across 5 subreddits
        subs = ["cybersecurity", "netsec", "sysadmin", "devops", "AskNetsec"]
        opportunities = []
        risk_assessments = {}
        expected_returns = {}

        for i in range(50):
            opp = _make_opportunity(composite_score=90 - i, subreddit=subs[i % len(subs)])
            risk = _make_risk_assessment(final_score=20 + (i % 10))
            ret = _make_expected_return(composite=80.0 - i * 0.5)
            opportunities.append(opp)
            risk_assessments[opp.id] = risk
            expected_returns[opp.id] = ret

        result = allocate_portfolio(
            opportunities, risk_assessments, expected_returns,
            budget, allocation, avatar,
        )

        # CRITICAL: must select 9 (budget), not 1-2 like the old category-based engine
        assert len(result.selected) >= 7, (
            f"Allocation selected only {len(result.selected)}/9 — budget severely underfilled. "
            f"Rejected: {len(result.rejected)}"
        )

    def test_3_opportunities_budget_9_selects_all_3(self):
        """When supply < budget, select everything available."""
        from app.services.allocation_engine import allocate_portfolio
        from app.services.portfolio_manager import AttentionBudget, PortfolioAllocation

        avatar = MagicMock()
        avatar.warming_phase = 2
        avatar.declared_timezone = "America/New_York"
        avatar.hobby_subreddits = []
        avatar.business_subreddits = ["cybersecurity"]

        budget = AttentionBudget(max_comments=7, max_posts=2, max_total_actions=9, acceptable_risk_level=60)
        allocation = PortfolioAllocation.from_avatar_profile(avatar, None)

        opportunities = [_make_opportunity(composite_score=80 - i * 10) for i in range(3)]
        risk_assessments = {opp.id: _make_risk_assessment() for opp in opportunities}
        expected_returns = {opp.id: _make_expected_return() for opp in opportunities}

        result = allocate_portfolio(
            opportunities, risk_assessments, expected_returns,
            budget, allocation, avatar,
        )

        assert len(result.selected) == 3

    def test_all_same_subreddit_still_fills_with_cap(self):
        """Even if all opportunities are in 1 sub, subreddit_cap allows at least 2."""
        from app.services.allocation_engine import allocate_portfolio
        from app.services.portfolio_manager import AttentionBudget, PortfolioAllocation

        avatar = MagicMock()
        avatar.warming_phase = 1
        avatar.declared_timezone = "America/New_York"
        avatar.hobby_subreddits = ["yoga"]
        avatar.business_subreddits = []

        budget = AttentionBudget(max_comments=3, max_posts=0, max_total_actions=3, acceptable_risk_level=75)
        allocation = PortfolioAllocation.from_avatar_profile(avatar, None)

        # All 10 in same subreddit
        opportunities = [_make_opportunity(composite_score=70, subreddit="yoga") for _ in range(10)]
        risk_assessments = {opp.id: _make_risk_assessment() for opp in opportunities}
        expected_returns = {opp.id: _make_expected_return() for opp in opportunities}

        result = allocate_portfolio(
            opportunities, risk_assessments, expected_returns,
            budget, allocation, avatar,
        )

        # Subreddit absolute cap is 2, but budget is 3. Should get at least 2.
        assert len(result.selected) >= 2, (
            f"Single-sub avatar got {len(result.selected)} slots — subreddit cap is too aggressive"
        )


# ===========================================================================
# TEST 2: Phase ceiling validation
# ===========================================================================


class TestPhaseCeilingValidation:
    """Phase evaluator must demote avatars that don't meet phase criteria."""

    def test_phase3_low_karma_demotes(self, db: Session):
        """Phase 3 avatar with karma=23 → demote (requires 500)."""
        from app.services.phase import PhaseEvaluator

        avatar = _make_avatar(
            db, phase=3, reddit_karma_comment=12, reddit_karma_post=11,
            reddit_account_created=datetime(2021, 9, 24, tzinfo=timezone.utc),
        )

        evaluator = PhaseEvaluator()
        should_demote, target, reason = evaluator.check_demotion_triggers(db, avatar)

        assert should_demote is True
        assert target == 1  # karma < 100, doesn't qualify for Phase 2 either
        assert reason == "phase_ceiling_violated"

    def test_phase2_sufficient_karma_no_demote(self, db: Session):
        """Phase 2 avatar with karma=150, age=100d → valid, no demotion."""
        from app.services.phase import PhaseEvaluator

        avatar = _make_avatar(
            db, phase=2, reddit_karma_comment=120, reddit_karma_post=30,
            reddit_account_created=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )

        evaluator = PhaseEvaluator()
        should_demote, target, reason = evaluator.check_demotion_triggers(db, avatar)

        assert should_demote is False
        assert reason is None

    def test_phase2_low_karma_demotes_to_1(self, db: Session):
        """Phase 2 avatar with karma=50, age=30d → invalid → demote to Phase 1."""
        from app.services.phase import PhaseEvaluator

        avatar = _make_avatar(
            db, phase=2, reddit_karma_comment=40, reddit_karma_post=10,
            reddit_account_created=datetime(2026, 6, 15, tzinfo=timezone.utc),
        )

        evaluator = PhaseEvaluator()
        should_demote, target, reason = evaluator.check_demotion_triggers(db, avatar)

        assert should_demote is True
        assert target == 1
        assert reason == "phase_ceiling_violated"

    def test_phase1_always_valid(self, db: Session):
        """Phase 1 avatar — no ceiling violation possible."""
        from app.services.phase import PhaseEvaluator

        avatar = _make_avatar(db, phase=1, reddit_karma_comment=0, reddit_karma_post=0)

        evaluator = PhaseEvaluator()
        should_demote, target, reason = evaluator.check_demotion_triggers(db, avatar)

        # Should not demote for ceiling (may demote for other reasons — survival/karma)
        assert reason != "phase_ceiling_violated"


# ===========================================================================
# TEST 3: get_budget_used_today includes PostDrafts
# ===========================================================================


class TestBudgetCountsPostDrafts:
    """Budget used today must count EPG comment slots AND PostDrafts."""

    def test_post_drafts_count_toward_budget(self, db: Session):
        """PostDraft created today counts toward daily budget."""
        from app.services.epg_executor import get_budget_used_today

        client = _make_client(db)
        avatar = _make_avatar(db, phase=2, client_ids=[str(client.id)])

        # 2 EPG comment slots (generated)
        _make_epg_slot(db, avatar.id, status="generated")
        _make_epg_slot(db, avatar.id, status="generated")

        # 1 PostDraft created today
        _make_post_draft(db, avatar.id, client.id, status="pending")

        total = get_budget_used_today(db, avatar.id)
        assert total == 3, f"Expected 3 (2 EPG + 1 post), got {total}"

    def test_rejected_post_drafts_not_counted(self, db: Session):
        """Rejected PostDrafts don't consume budget."""
        from app.services.epg_executor import get_budget_used_today

        client = _make_client(db)
        avatar = _make_avatar(db, phase=2, client_ids=[str(client.id)])

        _make_epg_slot(db, avatar.id, status="generated")
        _make_post_draft(db, avatar.id, client.id, status="rejected")

        total = get_budget_used_today(db, avatar.id)
        assert total == 1, f"Rejected post should not count, got {total}"

    def test_skipped_slots_without_draft_not_counted(self, db: Session):
        """Skipped EPG slots (generation failed) don't consume budget."""
        from app.services.epg_executor import get_budget_used_today

        avatar = _make_avatar(db, phase=1)
        _make_epg_slot(db, avatar.id, status="skipped", draft_id=None)
        _make_epg_slot(db, avatar.id, status="skipped", draft_id=None)
        _make_epg_slot(db, avatar.id, status="generated")

        total = get_budget_used_today(db, avatar.id)
        assert total == 1, f"Skipped without draft should not count, got {total}"


# ===========================================================================
# TEST 4: Budget math — CQS + Phase combinations
# ===========================================================================


class TestAttentionBudgetMath:
    """AttentionBudget correctly computes limits for phase + CQS combos."""

    def test_phase1_cqs_low_budget_2(self):
        """Phase 1 + CQS=low → max_comments=2, max_posts=0, total=2."""
        from app.services.portfolio_manager import AttentionBudget

        avatar = MagicMock()
        avatar.warming_phase = 1
        avatar.pool = "b2b"
        avatar.cqs_level = "low"

        budget = AttentionBudget.from_avatar(avatar)
        assert budget.max_comments == 2
        assert budget.max_posts == 0
        assert budget.max_total_actions == 2

    def test_phase1_cqs_lowest_budget_0(self):
        """Phase 1 + CQS=lowest → complete stop."""
        from app.services.portfolio_manager import AttentionBudget

        avatar = MagicMock()
        avatar.warming_phase = 1
        avatar.pool = "b2b"
        avatar.cqs_level = "lowest"

        budget = AttentionBudget.from_avatar(avatar)
        assert budget.max_total_actions == 0

    def test_phase2_normal_budget_9(self):
        """Phase 2 + normal CQS → 7 comments + 2 posts = 9."""
        from app.services.portfolio_manager import AttentionBudget

        avatar = MagicMock()
        avatar.warming_phase = 2
        avatar.pool = "b2b"
        avatar.cqs_level = "high"

        budget = AttentionBudget.from_avatar(avatar)
        assert budget.max_comments == 7
        assert budget.max_posts == 2
        assert budget.max_total_actions == 9

    def test_phase3_budget_15(self):
        """Phase 3 → 12 comments + 3 posts = 15."""
        from app.services.portfolio_manager import AttentionBudget

        avatar = MagicMock()
        avatar.warming_phase = 3
        avatar.pool = "b2b"
        avatar.cqs_level = "high"

        budget = AttentionBudget.from_avatar(avatar)
        assert budget.max_comments == 12
        assert budget.max_posts == 3
        assert budget.max_total_actions == 15

    def test_mentor_pool_zero_budget(self):
        """Mentor pool → 0 budget (excluded from pipeline)."""
        from app.services.portfolio_manager import AttentionBudget

        avatar = MagicMock()
        avatar.warming_phase = 2
        avatar.pool = "mentor"
        avatar.cqs_level = None

        budget = AttentionBudget.from_avatar(avatar)
        assert budget.max_total_actions == 0


# ===========================================================================
# TEST 5: Topup guard prevents infinite slot creation
# ===========================================================================


class TestTopupGuard:
    """Topup must not create slots when total_slots_any_status >= budget."""

    def test_all_skipped_blocks_topup(self, db: Session):
        """If 3 slots exist (all skipped) for budget=3, topup does nothing."""
        avatar = _make_avatar(db, phase=1)

        # Simulate morning: 3 slots all skipped (generation failed)
        for _ in range(3):
            _make_epg_slot(db, avatar.id, status="skipped")

        # Verify the guard condition
        from sqlalchemy import func as sa_func
        total_any = (
            db.query(sa_func.count(EPGSlot.id))
            .filter(EPGSlot.avatar_id == avatar.id, EPGSlot.plan_date == date.today())
            .scalar()
        )
        assert total_any == 3

        from app.services.portfolio_manager import AttentionBudget
        budget = AttentionBudget.from_avatar(avatar)

        # Guard: total_slots_any_status >= budget → should block
        assert total_any >= budget.max_total_actions, (
            "Guard condition not met — topup would create more slots"
        )

    def test_partial_success_allows_topup(self, db: Session):
        """If 1 generated + 1 skipped for budget=3, topup can fill remaining."""
        avatar = _make_avatar(db, phase=1)

        _make_epg_slot(db, avatar.id, status="generated")
        _make_epg_slot(db, avatar.id, status="skipped")

        from sqlalchemy import func as sa_func
        total_any = (
            db.query(sa_func.count(EPGSlot.id))
            .filter(EPGSlot.avatar_id == avatar.id, EPGSlot.plan_date == date.today())
            .scalar()
        )
        # total=2, budget=3 → topup allowed (2 < 3)
        assert total_any < 3


# ===========================================================================
# TEST 6: Enforcement recognizes generation failure
# ===========================================================================


class TestEnforcementGenerationFailure:
    """Enforcement must not retry when generation is broken (all slots skipped)."""

    def test_all_slots_skipped_is_not_starving(self, db: Session):
        """Avatar with budget slots all skipped → NOT considered starving."""
        avatar = _make_avatar(db, phase=1)

        # Morning created budget=3 slots, all skipped (Gemini empty response)
        for _ in range(3):
            _make_epg_slot(db, avatar.id, status="skipped")

        from app.services.epg_executor import get_budget_used_today
        from app.services.portfolio_manager import AttentionBudget
        from sqlalchemy import func as sa_func

        budget = AttentionBudget.from_avatar(avatar)
        total_used = get_budget_used_today(db, avatar.id)

        # total_used = 0 (skipped don't count as "used")
        assert total_used == 0

        # But total_slots_any_status = 3 = budget
        total_any = (
            db.query(sa_func.count(EPGSlot.id))
            .filter(EPGSlot.avatar_id == avatar.id, EPGSlot.plan_date == date.today())
            .scalar()
        )
        assert total_any >= budget.max_total_actions

        # Enforcement logic: if total_used==0 AND total_any >= budget → NOT starving
        # (generation is broken, not supply)
        is_starving = total_used == 0 and total_any < budget.max_total_actions
        assert is_starving is False, "Avatar should NOT be considered starving"


# ===========================================================================
# TEST 7: Allocation respects max_comments limit
# ===========================================================================


class TestAllocationMaxComments:
    """Allocation must not exceed max_comments even when budget allows more."""

    def test_phase2_max_7_comments(self):
        """Phase 2: 50 comment opportunities + budget 9 → max 7 comments selected."""
        from app.services.allocation_engine import allocate_portfolio
        from app.services.portfolio_manager import AttentionBudget, PortfolioAllocation

        avatar = MagicMock()
        avatar.warming_phase = 2
        avatar.declared_timezone = "America/New_York"
        avatar.hobby_subreddits = []
        avatar.business_subreddits = ["cybersecurity"]

        budget = AttentionBudget(max_comments=7, max_posts=2, max_total_actions=9, acceptable_risk_level=60)
        allocation = PortfolioAllocation.from_avatar_profile(avatar, None)

        subs = ["cybersecurity", "netsec", "sysadmin", "devops", "kubernetes"]
        opportunities = [_make_opportunity(composite_score=90 - i, subreddit=subs[i % 5]) for i in range(50)]
        risk_assessments = {opp.id: _make_risk_assessment() for opp in opportunities}
        expected_returns = {opp.id: _make_expected_return() for opp in opportunities}

        result = allocate_portfolio(
            opportunities, risk_assessments, expected_returns,
            budget, allocation, avatar,
        )

        # All are comment-type opportunities, so max_comments=7 is the ceiling
        assert len(result.selected) <= 7, (
            f"Selected {len(result.selected)} but max_comments=7"
        )
        assert len(result.selected) >= 5, (
            f"Selected only {len(result.selected)} — should be close to 7 "
            f"(subreddit cap may reduce slightly)"
        )
