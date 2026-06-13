"""Tests for EPG responsibility boundaries.

Validates the architectural contract:
- Discovery supplies the market (opportunity pool)
- EPG makes the investment decision (capital allocation)
- Generation executes only approved decisions
- Posting is just delivery

Key properties tested:
1. EPG never calls LLM / generates content
2. EPG can output zero actions (inaction is valid strategy)
3. EPG respects budget constraints
4. EPG deduplicates (never re-invests in same thread)
5. Discovery is independent from EPG (separate data supply)
6. Generation only acts on EPG-approved slots
7. Phase gates constrain opportunity eligibility
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.epg_slot import EPGSlot
from app.models.hobby import HobbySubreddit
from app.models.thread import RedditThread
from app.models.subreddit import Subreddit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_avatar(
    db: Session,
    *,
    phase: int = 1,
    frozen: bool = False,
    health: str = "healthy",
    pool: str = "warm",
    hobby_subreddits: list | None = None,
    client_ids: list | None = None,
) -> Avatar:
    """Create a test avatar."""
    avatar = Avatar(
        id=uuid.uuid4(),
        reddit_username=f"test_epg_{uuid.uuid4().hex[:6]}",
        warming_phase=phase,
        is_frozen=frozen,
        health_status=health,
        pool=pool,
        active=True,
        is_shadowbanned=False,
        hobby_subreddits=hobby_subreddits or [],
        client_ids=client_ids,
    )
    db.add(avatar)
    db.flush()
    return avatar


def _make_client(db: Session, *, active: bool = True) -> Client:
    """Create a test client."""
    client = Client(
        id=uuid.uuid4(),
        client_name=f"TestClient_{uuid.uuid4().hex[:6]}",
        brand_name=f"TestBrand_{uuid.uuid4().hex[:4]}",
        is_active=active,
        keywords={"high": ["test"], "medium": [], "low": []},
    )
    db.add(client)
    db.flush()
    return client


def _make_hobby_post(
    db: Session,
    avatar_username: str,
    *,
    subreddit: str = "CasualConversation",
    status: str = "new",
    has_body: bool = True,
) -> HobbySubreddit:
    """Create a hobby post in the opportunity pool."""
    post = HobbySubreddit(
        id=uuid.uuid4(),
        subreddit=subreddit,
        post_id=f"t3_{uuid.uuid4().hex[:8]}",
        post_title=f"Test hobby post {uuid.uuid4().hex[:4]}",
        post_body="This is a meaningful test post body with enough content for EPG to select it." if has_body else "",
        avatar_username=avatar_username,
        post_ups=25,
        status=status,
        ai_comment=None,
    )
    db.add(post)
    db.flush()
    return post


def _make_thread(
    db: Session,
    subreddit_id: uuid.UUID,
    *,
    subreddit_name: str = "Python",
    locked: bool = False,
) -> RedditThread:
    """Create a thread in the opportunity pool."""
    thread = RedditThread(
        id=uuid.uuid4(),
        subreddit_id=subreddit_id,
        subreddit=subreddit_name,
        reddit_native_id=f"t3_{uuid.uuid4().hex[:8]}",
        post_title=f"Test thread {uuid.uuid4().hex[:4]}",
        post_body="Meaningful test thread body with sufficient length for EPG selection criteria.",
        ups=15,
        is_locked=locked,
    )
    db.add(thread)
    db.flush()
    return thread


def _make_subreddit(db: Session, name: str) -> Subreddit:
    """Create a subreddit record."""
    sub = Subreddit(
        id=uuid.uuid4(),
        subreddit_name=name,
    )
    db.add(sub)
    db.flush()
    return sub


# ---------------------------------------------------------------------------
# 1. EPG never generates content (separation of concerns)
# ---------------------------------------------------------------------------


class TestEPGNeverGeneratesContent:
    """EPG is a decision engine. It never calls LLM or produces text."""

    @patch("app.services.ai.call_llm_json")
    @patch("app.services.ai.call_llm")
    def test_build_daily_epg_never_calls_llm(self, mock_llm, mock_llm_json, db: Session):
        """build_daily_epg must never invoke any LLM service."""
        from app.services.epg import build_daily_epg

        avatar = _make_avatar(db, phase=1)
        # Provide hobby posts so EPG has material to select
        for _ in range(5):
            _make_hobby_post(db, avatar.reddit_username)

        result = build_daily_epg(db, avatar, client=None)

        # EPG selected slots but never called LLM
        mock_llm.assert_not_called()
        mock_llm_json.assert_not_called()

    @patch("app.services.ai.call_llm_json")
    @patch("app.services.ai.call_llm")
    def test_epg_with_business_threads_never_calls_llm(self, mock_llm, mock_llm_json, db: Session):
        """Even with Phase 2-3 business slots, EPG itself never calls LLM."""
        from app.services.epg import build_daily_epg
        from app.models.thread_score import ThreadScore

        client = _make_client(db)
        avatar = _make_avatar(db, phase=2, client_ids=[str(client.id)])

        # Create hobby posts
        for _ in range(3):
            _make_hobby_post(db, avatar.reddit_username)

        # Create scored business threads
        sub = _make_subreddit(db, "Python")
        for _ in range(5):
            thread = _make_thread(db, sub.id, subreddit_name="Python")
            score = ThreadScore(
                id=uuid.uuid4(),
                thread_id=thread.id,
                client_id=client.id,
                tag="engage",
                composite=75,
            )
            db.add(score)
        db.flush()

        result = build_daily_epg(db, avatar, client=client)

        # EPG selected both hobby and business slots
        assert result.total_slots > 0
        # But never called LLM
        mock_llm.assert_not_called()
        mock_llm_json.assert_not_called()

    def test_epg_output_is_decisions_not_content(self, db: Session):
        """EPG output contains thread references and timing, not generated text."""
        from app.services.epg import build_daily_epg

        avatar = _make_avatar(db, phase=1)
        for _ in range(3):
            _make_hobby_post(db, avatar.reddit_username)

        result = build_daily_epg(db, avatar, client=None)

        # Check that slots contain metadata (where/when) not content (what to write)
        for slot in result.hobby_slots:
            assert "subreddit" in slot
            assert "scheduled_at" in slot
            assert "title" in slot
            # No generated comment text in EPG output
            assert "ai_comment" not in slot
            assert "comment_text" not in slot
            assert "generated_text" not in slot


# ---------------------------------------------------------------------------
# 2. Inaction is a valid strategic output (Zero-Day)
# ---------------------------------------------------------------------------


class TestInactionIsValidOutput:
    """EPG can decide that doing nothing is the best strategy."""

    def test_empty_pool_returns_no_content(self, db: Session):
        """No opportunity pool → EPG returns no_content (not an error)."""
        from app.services.epg import build_daily_epg

        avatar = _make_avatar(db, phase=1)
        # No hobby posts in DB — empty pool

        result = build_daily_epg(db, avatar, client=None)

        assert result.total_slots == 0
        assert result.status == "no_content"
        # This is a strategic decision, not a failure
        assert "error" not in result.status

    def test_frozen_avatar_is_intentional_inaction(self, db: Session):
        """Frozen avatar → EPG decides not to invest (preserve capital)."""
        from app.services.epg import build_daily_epg

        avatar = _make_avatar(db, phase=2, frozen=True)
        # Even with material available
        for _ in range(5):
            _make_hobby_post(db, avatar.reddit_username)

        result = build_daily_epg(db, avatar, client=None)

        assert result.total_slots == 0
        assert result.status == "frozen"

    def test_shadowbanned_avatar_inaction(self, db: Session):
        """Shadowbanned avatar → capital preservation mode."""
        from app.services.epg import build_daily_epg

        avatar = _make_avatar(db, phase=2, health="shadowbanned")

        result = build_daily_epg(db, avatar, client=None)

        assert result.total_slots == 0
        assert result.status == "excluded"

    def test_budget_exhausted_is_not_error(self, db: Session):
        """Exhausted budget → EPG correctly reports budget_exhausted, not error."""
        from app.services.epg import build_daily_epg

        avatar = _make_avatar(db, phase=1)
        today = date.today()

        # Fill budget with existing generated slots
        for _ in range(5):
            slot = EPGSlot(
                id=uuid.uuid4(),
                avatar_id=avatar.id,
                plan_date=today,
                slot_type="hobby",
                status="generated",
                subreddit="CasualConversation",
            )
            db.add(slot)
        db.flush()

        result = build_daily_epg(db, avatar, client=None)

        assert result.status == "budget_exhausted"
        assert "error" not in result.status

    def test_mentor_excluded_is_strategic(self, db: Session):
        """Phase 0 (Mentor) excluded — these assets are preserved, not invested."""
        from app.services.epg import build_daily_epg

        avatar = _make_avatar(db, phase=0)

        result = build_daily_epg(db, avatar, client=None)

        assert result.status == "excluded"
        assert "Mentor" in result.message


# ---------------------------------------------------------------------------
# 3. Budget is a hard constraint (never exceeded)
# ---------------------------------------------------------------------------


class TestBudgetConstraints:
    """EPG never allocates more attention than the budget allows."""

    def test_phase1_budget_cap(self, db: Session):
        """Phase 1 avatar never gets more than MAX_COMMENTS_PER_DAY_PHASE1 slots."""
        from app.services.epg import build_daily_epg
        from app.services.phase import MAX_COMMENTS_PER_DAY_PHASE1

        avatar = _make_avatar(db, phase=1)
        # Provide more posts than budget allows
        for _ in range(20):
            _make_hobby_post(db, avatar.reddit_username)

        result = build_daily_epg(db, avatar, client=None)

        assert result.total_slots <= MAX_COMMENTS_PER_DAY_PHASE1

    def test_existing_slots_reduce_available_budget(self, db: Session):
        """Pre-existing generated slots reduce remaining budget."""
        from app.services.epg import build_daily_epg
        from app.services.phase import MAX_COMMENTS_PER_DAY_PHASE1

        avatar = _make_avatar(db, phase=1)
        today = date.today()

        # Pre-fill with 2 generated slots
        for _ in range(2):
            slot = EPGSlot(
                id=uuid.uuid4(),
                avatar_id=avatar.id,
                plan_date=today,
                slot_type="hobby",
                status="generated",
                subreddit="CasualConversation",
            )
            db.add(slot)
        db.flush()

        # Provide plenty of material
        for _ in range(10):
            _make_hobby_post(db, avatar.reddit_username)

        result = build_daily_epg(db, avatar, client=None)

        # Total including existing should not exceed budget
        total_today = result.used_today + len([
            s for s in result.hobby_slots + result.business_slots
            if s.get("status") == "planned"
        ])
        assert total_today <= MAX_COMMENTS_PER_DAY_PHASE1


# ---------------------------------------------------------------------------
# 4. Deduplication — never re-invest in same opportunity
# ---------------------------------------------------------------------------


class TestDeduplication:
    """EPG never selects a thread/post that was already acted upon."""

    def test_used_hobby_posts_excluded(self, db: Session):
        """Hobby posts with existing drafts are never re-selected."""
        from app.services.epg import build_daily_epg

        avatar = _make_avatar(db, phase=1)

        # Create a hobby post that was already used (status=pending)
        used_post = _make_hobby_post(db, avatar.reddit_username, status="pending")
        # Create a fresh unused post
        fresh_post = _make_hobby_post(db, avatar.reddit_username, status="new")

        result = build_daily_epg(db, avatar, client=None)

        # Only the fresh post should be selected
        selected_post_ids = [s.get("hobby_post_id") for s in result.hobby_slots]
        assert str(used_post.id) not in selected_post_ids

    def test_threads_with_existing_drafts_excluded(self, db: Session):
        """Threads where avatar already has a draft are excluded."""
        from app.services.epg import build_daily_epg
        from app.models.thread_score import ThreadScore

        client = _make_client(db)
        avatar = _make_avatar(db, phase=3, client_ids=[str(client.id)])
        sub = _make_subreddit(db, "Python")

        # Thread with existing draft
        used_thread = _make_thread(db, sub.id, subreddit_name="Python")
        draft = CommentDraft(
            id=uuid.uuid4(),
            avatar_id=avatar.id,
            thread_id=used_thread.id,
            status="posted",
            ai_draft="Already commented",
        )
        db.add(draft)

        # Score the used thread as engage
        score_used = ThreadScore(
            id=uuid.uuid4(),
            thread_id=used_thread.id,
            client_id=client.id,
            tag="engage",
            composite=80,
        )
        db.add(score_used)

        # Fresh thread without draft
        fresh_thread = _make_thread(db, sub.id, subreddit_name="Python")
        score_fresh = ThreadScore(
            id=uuid.uuid4(),
            thread_id=fresh_thread.id,
            client_id=client.id,
            tag="engage",
            composite=80,
        )
        db.add(score_fresh)
        db.flush()

        # Also add hobby posts for the hobby portion of budget
        for _ in range(3):
            _make_hobby_post(db, avatar.reddit_username)

        result = build_daily_epg(db, avatar, client=client)

        # Used thread should not appear in business slots
        selected_thread_ids = [s.get("thread_id") for s in result.business_slots]
        assert str(used_thread.id) not in selected_thread_ids


# ---------------------------------------------------------------------------
# 5. Discovery is independent (separate data supply)
# ---------------------------------------------------------------------------


class TestDiscoveryIndependence:
    """Discovery populates opportunity pool independently of EPG decisions."""

    def test_epg_reads_from_existing_pool_only(self, db: Session):
        """EPG only reads from what Discovery has already provided."""
        from app.services.epg import build_daily_epg

        avatar = _make_avatar(db, phase=1)

        # EPG with empty pool → no content
        result_empty = build_daily_epg(db, avatar, client=None)
        assert result_empty.total_slots == 0

        # After Discovery populates pool
        for _ in range(5):
            _make_hobby_post(db, avatar.reddit_username)

        # EPG now finds material
        result_full = build_daily_epg(db, avatar, client=None)
        assert result_full.total_slots > 0

    @patch("app.services.reddit.scrape_subreddit")
    def test_epg_never_calls_reddit_api(self, mock_scrape, db: Session):
        """EPG never scrapes Reddit directly — that's Discovery's job."""
        from app.services.epg import build_daily_epg

        avatar = _make_avatar(db, phase=1)
        for _ in range(3):
            _make_hobby_post(db, avatar.reddit_username)

        build_daily_epg(db, avatar, client=None)

        mock_scrape.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Generation only executes EPG-approved decisions
# ---------------------------------------------------------------------------


class TestGenerationOnlyExecutesApproved:
    """Generation layer only acts on slots EPG has planned/approved."""

    def test_generate_only_planned_slots(self, db: Session):
        """generate_all_planned_slots only processes status='planned'."""
        from app.services.epg_executor import generate_all_planned_slots

        avatar = _make_avatar(db, phase=1)
        today = date.today()

        # Planned slot (should be processed)
        planned = EPGSlot(
            id=uuid.uuid4(),
            avatar_id=avatar.id,
            plan_date=today,
            slot_type="hobby",
            status="planned",
            subreddit="CasualConversation",
        )
        # Already generated slot (should NOT be re-processed)
        generated = EPGSlot(
            id=uuid.uuid4(),
            avatar_id=avatar.id,
            plan_date=today,
            slot_type="hobby",
            status="generated",
            subreddit="CasualConversation",
        )
        # Skipped slot (should NOT be processed)
        skipped = EPGSlot(
            id=uuid.uuid4(),
            avatar_id=avatar.id,
            plan_date=today,
            slot_type="hobby",
            status="skipped",
            skip_reason="risk_too_high",
            subreddit="CasualConversation",
        )
        db.add_all([planned, generated, skipped])
        db.flush()

        # Mock the actual generation to avoid LLM calls
        with patch("app.services.epg_executor.generate_epg_slot") as mock_gen:
            mock_gen.return_value = None
            generate_all_planned_slots(db, avatar.id)

        # Only the planned slot should trigger generation
        assert mock_gen.call_count == 1
        call_slot_id = mock_gen.call_args[0][1]  # (db, slot_id)
        assert call_slot_id == planned.id

    def test_generate_skips_non_planned_status(self, db: Session):
        """generate_epg_slot immediately returns None for non-planned slots."""
        from app.services.epg_executor import generate_epg_slot

        avatar = _make_avatar(db, phase=1)
        today = date.today()

        slot = EPGSlot(
            id=uuid.uuid4(),
            avatar_id=avatar.id,
            plan_date=today,
            slot_type="hobby",
            status="generated",  # Already generated — not planned
            subreddit="CasualConversation",
        )
        db.add(slot)
        db.flush()

        result = generate_epg_slot(db, slot.id)
        assert result is None


# ---------------------------------------------------------------------------
# 7. Phase gates constrain opportunity eligibility
# ---------------------------------------------------------------------------


class TestPhaseGates:
    """Avatar phase determines which opportunity types are eligible."""

    def test_phase1_only_hobby(self, db: Session):
        """Phase 1 avatars get only hobby slots, regardless of available business threads."""
        from app.services.epg import build_daily_epg
        from app.models.thread_score import ThreadScore

        client = _make_client(db)
        avatar = _make_avatar(db, phase=1, client_ids=[str(client.id)])

        # Provide both hobby and business material
        for _ in range(5):
            _make_hobby_post(db, avatar.reddit_username)

        sub = _make_subreddit(db, "BusinessSub")
        for _ in range(5):
            thread = _make_thread(db, sub.id, subreddit_name="BusinessSub")
            score = ThreadScore(
                id=uuid.uuid4(),
                thread_id=thread.id,
                client_id=client.id,
                tag="engage",
                composite=90,
            )
            db.add(score)
        db.flush()

        result = build_daily_epg(db, avatar, client=client)

        # Phase 1 = 100% hobby, no business
        assert len(result.business_slots) == 0
        assert len(result.hobby_slots) > 0

    def test_phase2_mixed_allocation(self, db: Session):
        """Phase 2 avatars get both hobby and business slots."""
        from app.services.epg import build_daily_epg
        from app.models.thread_score import ThreadScore

        client = _make_client(db)
        avatar = _make_avatar(db, phase=2, client_ids=[str(client.id)])

        # Provide hobby material
        for _ in range(5):
            _make_hobby_post(db, avatar.reddit_username)

        # Provide business material
        sub = _make_subreddit(db, "TechSub")
        for _ in range(5):
            thread = _make_thread(db, sub.id, subreddit_name="TechSub")
            score = ThreadScore(
                id=uuid.uuid4(),
                thread_id=thread.id,
                client_id=client.id,
                tag="engage",
                composite=80,
            )
            db.add(score)
        db.flush()

        result = build_daily_epg(db, avatar, client=client)

        # Phase 2 = 50/50 split
        assert len(result.hobby_slots) > 0
        assert len(result.business_slots) > 0

    def test_phase3_business_heavy(self, db: Session):
        """Phase 3 avatars get mostly business slots (70/30)."""
        from app.services.epg import build_daily_epg
        from app.models.thread_score import ThreadScore

        client = _make_client(db)
        avatar = _make_avatar(db, phase=3, client_ids=[str(client.id)])

        # Provide hobby material
        for _ in range(10):
            _make_hobby_post(db, avatar.reddit_username)

        # Provide business material
        sub = _make_subreddit(db, "GrowthSub")
        for _ in range(15):
            thread = _make_thread(db, sub.id, subreddit_name="GrowthSub")
            score = ThreadScore(
                id=uuid.uuid4(),
                thread_id=thread.id,
                client_id=client.id,
                tag="engage",
                composite=85,
            )
            db.add(score)
        db.flush()

        result = build_daily_epg(db, avatar, client=client)

        # Phase 3 = 70% business, 30% hobby
        if result.total_slots > 2:
            assert len(result.business_slots) >= len(result.hobby_slots)


# ---------------------------------------------------------------------------
# 8. EPG persists decisions (immutable audit trail)
# ---------------------------------------------------------------------------


class TestDecisionPersistence:
    """EPG decisions are persisted as EPGSlots — immutable plan records."""

    def test_planned_slots_persisted_to_db(self, db: Session):
        """EPG writes planned slots to epg_slots table."""
        from app.services.epg import build_daily_epg

        avatar = _make_avatar(db, phase=1)
        for _ in range(3):
            _make_hobby_post(db, avatar.reddit_username)

        result = build_daily_epg(db, avatar, client=None)
        assert result.total_slots > 0

        # Verify slots exist in DB
        db_slots = (
            db.query(EPGSlot)
            .filter(
                EPGSlot.avatar_id == avatar.id,
                EPGSlot.plan_date == date.today(),
            )
            .all()
        )
        assert len(db_slots) == result.total_slots

    def test_rebuild_replaces_planned_preserves_generated(self, db: Session):
        """Re-running EPG replaces 'planned' slots but preserves 'generated' ones."""
        from app.services.epg import build_daily_epg

        avatar = _make_avatar(db, phase=1)
        today = date.today()

        # Simulate a previously generated slot
        generated_slot = EPGSlot(
            id=uuid.uuid4(),
            avatar_id=avatar.id,
            plan_date=today,
            slot_type="hobby",
            status="generated",
            subreddit="AskReddit",
            thread_title="Previously generated",
        )
        db.add(generated_slot)
        db.flush()

        # Provide fresh material for re-plan
        for _ in range(3):
            _make_hobby_post(db, avatar.reddit_username)

        build_daily_epg(db, avatar, client=None)

        # Generated slot is preserved
        preserved = db.query(EPGSlot).filter(EPGSlot.id == generated_slot.id).first()
        assert preserved is not None
        assert preserved.status == "generated"

    def test_epg_slots_have_scheduling_metadata(self, db: Session):
        """Each EPG slot includes when and where (scheduling metadata)."""
        from app.services.epg import build_daily_epg

        avatar = _make_avatar(db, phase=1)
        for _ in range(3):
            _make_hobby_post(db, avatar.reddit_username)

        result = build_daily_epg(db, avatar, client=None)

        for slot in result.hobby_slots:
            assert slot.get("subreddit") is not None
            assert slot.get("scheduled_at") is not None
            assert slot.get("status") == "planned"
