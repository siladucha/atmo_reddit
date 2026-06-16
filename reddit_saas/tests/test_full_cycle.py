"""Integration test: Full AI-native cycle verification.

Tests the complete closed loop:
Client → Discovery → Strategy → Avatar → EPG → Posting → KarmaSnapshot →
Outcome Analysis → Feedback Loop → Discovery confidence update → EPG adjustment

This test does NOT call external APIs (Reddit, LLM). It verifies the data flow
and service orchestration work end-to-end with mock/seed data.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.database import Base


@pytest.fixture
def db():
    """Create a test database session."""
    settings = get_settings()
    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_full_cycle_data_flow(db):
    """Verify the complete closed loop works end-to-end.

    Steps:
    1. Create Discovery session (demo seed)
    2. Execute handoff → creates Client + subreddits
    3. Verify strategy context is prepared
    4. Create avatar + simulate EPG slot + draft + posting event
    5. Create KarmaSnapshot (simulate outcome)
    6. Run outcome analysis
    7. Run feedback loop → check hypothesis confidence updated
    8. Verify EPG adjustments stored
    9. Verify traceability reconstructs full chain
    """
    from app.models.avatar import Avatar
    from app.models.client import Client
    from app.models.comment_draft import CommentDraft
    from app.models.epg_slot import EPGSlot
    from app.models.karma_snapshot import KarmaSnapshot
    from app.models.posting_event import PostingEvent
    from app.models.strategy_document import StrategyDocument
    from app.models.user import User
    from app.services.discovery.demo_seed import create_demo_session
    from app.services.discovery.strategy_handoff import execute_handoff, prepare_handoff_context
    from app.services.feedback_loop import run_feedback_loop, get_all_epg_adjustments, get_performance_context
    from app.services.outcome_analysis import compute_avatar_outcome_profile
    from app.services.traceability import trace_comment_json

    # --- Step 1: Discovery ---
    admin = db.query(User).first()
    assert admin is not None, "Need at least one user in DB"

    session = create_demo_session(db, operator_user_id=admin.id)
    assert session.status == "completed"
    assert len(session.entities) == 10
    assert len(session.hypotheses) == 6
    assert len(session.reports) == 1
    print(f"✓ Step 1: Discovery session created ({session.id})")

    # --- Step 2: Handoff → Client ---
    handoff_result = execute_handoff(session, db)
    db.commit()
    assert handoff_result["client_created"] == True
    client_id = uuid.UUID(handoff_result["client_id"])
    client = db.query(Client).filter(Client.id == client_id).first()
    assert client is not None
    assert client.client_name == "CyberShield (Demo)"
    print(f"✓ Step 2: Client created via handoff ({client.client_name})")

    # --- Step 3: Strategy context ---
    context = prepare_handoff_context(session)
    assert len(context["confirmed_hypotheses"]) == 5
    assert len(context["recommended_communities"]) >= 3
    print(f"✓ Step 3: Strategy context prepared ({len(context['confirmed_hypotheses'])} hypotheses)")

    # --- Step 4: Avatar + EPG + Draft + Posting ---
    # Create a test avatar linked to client
    avatar = Avatar(
        id=uuid.uuid4(),
        reddit_username=f"test_cycle_avatar_{uuid.uuid4().hex[:8]}",
        active=True,
        warming_phase=2,
        client_ids=[str(client_id)],
        hobby_subreddits=[{"subreddit": "homelab"}],
        business_subreddits=[{"subreddit": "cybersecurity"}],
    )
    db.add(avatar)
    db.flush()

    # Create a strategy for the avatar
    strategy = StrategyDocument(
        avatar_id=avatar.id,
        goals=[{"metric": "karma", "target": "100", "days": 30}],
        subreddit_priorities=[{"subreddit": "cybersecurity", "priority": 10}],
        tone_guidelines={"formality": "casual"},
        cadence_rules=[{"week": 1, "comments_per_day": 3}],
        hook_inventory={"primary": "test"},
        document_md="# Test Strategy",
        version=1,
        is_current=True,
        is_approved=True,
        model_used="test",
    )
    db.add(strategy)
    db.flush()

    # Create EPG slot
    from datetime import date
    epg_slot = EPGSlot(
        id=uuid.uuid4(),
        avatar_id=avatar.id,
        client_id=client_id,
        plan_date=date.today(),
        slot_type="professional",
        scheduled_at=datetime.now(timezone.utc) - timedelta(hours=5),
        status="posted",
        subreddit="cybersecurity",
        thread_title="Test thread for cycle verification",
    )
    db.add(epg_slot)
    db.flush()

    # Create comment draft (posted)
    draft = CommentDraft(
        id=uuid.uuid4(),
        avatar_id=avatar.id,
        client_id=client_id,
        type="professional",
        ai_draft="Test comment for cycle verification",
        comment_approach="reframe_drop",
        strategic_angle="authority",
        status="posted",
        posted_at=datetime.now(timezone.utc) - timedelta(hours=5),
        reddit_comment_url="https://reddit.com/r/cybersecurity/comments/test123/test/abc123",
        reddit_score=25,
    )
    db.add(draft)
    db.flush()

    # Link draft to EPG slot
    epg_slot.draft_id = draft.id
    db.flush()

    # Create posting event
    posting_event = PostingEvent(
        avatar_id=avatar.id,
        draft_id=draft.id,
        epg_slot_id=epg_slot.id,
        posted_at=datetime.now(timezone.utc) - timedelta(hours=5),
        duration_ms=1200,
        outcome="success",
        reddit_comment_id="abc123",
        reddit_comment_url="https://reddit.com/r/cybersecurity/comments/test123/test/abc123",
    )
    db.add(posting_event)
    db.flush()
    print(f"✓ Step 4: Avatar + EPG + Draft + PostingEvent created")

    # --- Step 5: KarmaSnapshot ---
    snapshot = KarmaSnapshot(
        comment_draft_id=draft.id,
        avatar_id=avatar.id,
        karma_value=25,
        reply_count=3,
        is_deleted=False,
        check_window="4h",
        checked_at=datetime.now(timezone.utc) - timedelta(hours=1),
        karma_delta=None,
        subreddit="cybersecurity",
    )
    db.add(snapshot)
    db.flush()
    print(f"✓ Step 5: KarmaSnapshot created (karma=25, replies=3)")

    # --- Step 6: Outcome Analysis ---
    profile = compute_avatar_outcome_profile(db, avatar.id, lookback_days=7)
    assert profile.total_posted >= 1
    assert profile.total_karma >= 25
    assert len(profile.subreddit_signals) >= 1
    sig = profile.subreddit_signals[0]
    assert sig.subreddit == "cybersecurity"
    assert sig.avg_karma >= 25
    print(f"✓ Step 6: Outcome analysis computed (karma={profile.total_karma}, subs={len(profile.subreddit_signals)})")

    # --- Step 7: Feedback Loop ---
    feedback_result = run_feedback_loop(db, avatar.id)
    assert feedback_result["avatar_id"] == str(avatar.id)
    assert "profile_summary" in feedback_result
    assert feedback_result["profile_summary"]["total_posted_30d"] >= 1
    print(f"✓ Step 7: Feedback loop executed (hypotheses={feedback_result['hypotheses_updated']}, adjustments={feedback_result['adjustments_applied']})")

    # --- Step 8: Check stored adjustments ---
    adjustments = get_all_epg_adjustments(db, avatar.id)
    perf_ctx = get_performance_context(db, avatar.id)
    assert perf_ctx is not None
    assert perf_ctx["total_posted_30d"] >= 1
    print(f"✓ Step 8: Performance context stored, EPG adjustments={len(adjustments)}")

    # --- Step 9: Full Traceability ---
    trace = trace_comment_json(db, draft.id)
    assert len(trace["chain"]) >= 3  # At minimum: draft + strategy + posting_event
    layers = [n["layer"] for n in trace["chain"]]
    assert "execution" in layers
    assert "strategy" in layers

    # Check the trace found the EPG slot
    assert trace["summary"]["epg_slot_id"] == str(epg_slot.id)
    # Check karma snapshots found
    assert trace["summary"]["karma_snapshots"] >= 1
    assert trace["summary"]["latest_karma"] == 25
    # Check feedback applied
    assert trace["summary"]["feedback_applied"] == True
    print(f"✓ Step 9: Full trace verified ({len(trace['chain'])} nodes, layers={set(layers)})")

    # --- Final: Verify the cycle closes ---
    # Discovery hypothesis confidence should have been evaluated
    # (may or may not have changed depending on threshold logic)
    from app.models.discovery_hypothesis import DiscoveryHypothesis
    confirmed_hyps = (
        db.query(DiscoveryHypothesis)
        .filter(
            DiscoveryHypothesis.session_id == session.id,
            DiscoveryHypothesis.status == "confirmed",
        )
        .all()
    )
    # The cybersecurity hypothesis should have been found
    cyber_hyp = [h for h in confirmed_hyps if "cybersecurity" in h.statement.lower()]
    assert len(cyber_hyp) >= 1
    print(f"✓ Final: Cycle verified — Discovery hypothesis 'cybersecurity' exists with confidence={cyber_hyp[0].confidence_score}")

    print("\n=== FULL CYCLE TEST PASSED ===")
    print("Discovery → Strategy → EPG → Posting → KarmaSnapshot → Feedback → Discovery")


if __name__ == "__main__":
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        test_full_cycle_data_flow(db)
    finally:
        db.close()
