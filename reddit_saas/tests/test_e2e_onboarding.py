"""End-to-end test: full onboarding → score → generate → review pipeline.

Uses mocked LLM responses. Requires only the test database (no Redis, no Reddit API).

Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9
"""

import json
import uuid
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.avatar import Avatar
from app.models.subreddit import Subreddit, ClientSubredditAssignment
from app.models.thread import RedditThread
from app.models.thread_score import ThreadScore
from app.models.comment_draft import CommentDraft
from app.services.scoring import score_unscored_threads_for_client
from app.services.generation import select_persona, generate_comment


# --- Mock LLM responses ---

SCORING_DATA = {
    "alert": True,
    "tag": "engage",
    "relevance": 3,
    "quality": 3,
    "strategic": 3,
    "composite": 9,
    "intent": "help_seeking",
    "reason": "Direct hit",
}

MOCK_SCORING_RESPONSE = {
    "content": json.dumps(SCORING_DATA),
    "input_tokens": 100,
    "output_tokens": 50,
    "cost_usd": 0.001,
    "duration_ms": 200,
    "model": "test-model",
    "data": SCORING_DATA,
}

PERSONA_DATA = {
    "persona_username": "test_avatar",
    "mode": "helpful_peer",
    "audience": "developers",
    "thread_angle": "share experience",
    "pov_opportunity": "worldview fit",
    "selection_reasoning": "best fit",
}

MOCK_PERSONA_RESPONSE = {
    "content": json.dumps(PERSONA_DATA),
    "input_tokens": 100,
    "output_tokens": 50,
    "cost_usd": 0.001,
    "duration_ms": 200,
    "model": "test-model",
    "data": PERSONA_DATA,
}

COMMENT_DATA = {
    "comment": "great point, been there",
    "comment_to": "post",
    "location_depth": 0,
    "location_reasoning": "top level",
    "comment_approach": "yeah_and",
    "strategic_angle": "karma_play",
}

MOCK_COMMENT_RESPONSE = {
    "content": json.dumps(COMMENT_DATA),
    "input_tokens": 100,
    "output_tokens": 50,
    "cost_usd": 0.001,
    "duration_ms": 200,
    "model": "test-model",
    "data": COMMENT_DATA,
}

MOCK_EDIT_RESPONSE = {
    "content": "great point, been there",
    "input_tokens": 50,
    "output_tokens": 30,
    "cost_usd": 0.0005,
    "duration_ms": 100,
    "model": "test-model",
}


def test_e2e_onboarding_pipeline(db: Session):
    """Full pipeline: create client → assign sub → insert thread → score → generate → review."""

    # ---------------------------------------------------------------
    # 1. Create a Client (Req 8.1)
    # ---------------------------------------------------------------
    client = Client(
        client_name="E2E Test Corp",
        brand_name="E2E Brand",
        is_active=True,
        company_profile="Test company profile",
        company_worldview="Test worldview",
        company_problem="Test problem",
        competitive_landscape="Competitor A, Competitor B",
        keywords={"high": ["test"], "medium": [], "low": []},
    )
    db.add(client)
    db.flush()

    # ---------------------------------------------------------------
    # 2. Assign a Subreddit (Req 8.2)
    # ---------------------------------------------------------------
    subreddit = Subreddit(subreddit_name="test_subreddit", is_active=True)
    db.add(subreddit)
    db.flush()

    assignment = ClientSubredditAssignment(
        client_id=client.id,
        subreddit_id=subreddit.id,
        type="professional",
        is_active=True,
    )
    db.add(assignment)
    db.flush()

    # ---------------------------------------------------------------
    # 3. Insert a mock RedditThread (Req 8.3)
    # ---------------------------------------------------------------
    thread = RedditThread(
        subreddit_id=subreddit.id,
        subreddit="test_subreddit",
        type="professional",
        reddit_native_id=f"t3_e2e_{uuid.uuid4().hex[:8]}",
        post_title="How do you handle X in production?",
        post_body="Looking for advice on handling X at scale...",
        url="https://reddit.com/r/test_subreddit/comments/abc123",
        author="someone",
    )
    db.add(thread)
    db.flush()

    # ---------------------------------------------------------------
    # 4. Create an Avatar for this client
    # ---------------------------------------------------------------
    avatar = Avatar(
        reddit_username=f"test_avatar_{uuid.uuid4().hex[:6]}",
        active=True,
        client_ids=[str(client.id)],
        voice_profile_md="Casual dev voice. Speaks from experience.",
    )
    db.add(avatar)
    db.commit()

    # ---------------------------------------------------------------
    # 5. Score the thread (mocked LLM) (Req 8.4, 8.7)
    # ---------------------------------------------------------------
    with patch("app.services.scoring.call_llm_json", return_value=MOCK_SCORING_RESPONSE):
        result = score_unscored_threads_for_client(db, client)

    scored_count = result.get("scored", 0) if isinstance(result, dict) else result
    assert scored_count == 1, f"Expected 1 thread scored, got {scored_count}"

    # Verify ThreadScore record was created
    thread_score = (
        db.query(ThreadScore)
        .filter(
            ThreadScore.thread_id == thread.id,
            ThreadScore.client_id == client.id,
        )
        .first()
    )
    assert thread_score is not None, "ThreadScore record should exist after scoring"
    assert thread_score.tag == "engage"
    assert thread_score.composite == 9
    assert thread_score.alert is True

    # ---------------------------------------------------------------
    # 6. Generate a comment (mocked LLM) (Req 8.5, 8.7)
    # ---------------------------------------------------------------
    # We call select_persona + generate_comment directly (service layer)
    # to avoid needing Celery infrastructure.

    def mock_call_llm_json_side_effect(*args, **kwargs):
        """Route mock responses based on whether schema is passed."""
        schema = kwargs.get("schema")
        if schema is not None:
            # CommentOutput schema → comment generation
            return MOCK_COMMENT_RESPONSE
        else:
            # No schema → persona selection
            return MOCK_PERSONA_RESPONSE

    with patch("app.services.generation.call_llm_json", side_effect=mock_call_llm_json_side_effect), \
         patch("app.services.generation.call_llm", return_value=MOCK_EDIT_RESPONSE), \
         patch("app.services.generation.get_config", return_value="test-model"):

        # Update avatar username to match mock persona response
        avatar.reddit_username = "test_avatar"
        db.commit()

        # Select persona
        selection = select_persona(db, thread, client, [avatar])
        assert selection["persona_username"] == "test_avatar"
        assert selection["mode"] == "helpful_peer"

        # Generate comment
        draft = generate_comment(
            db, thread, client, avatar, selection, previous_comments=[]
        )

    assert draft is not None, "CommentDraft should be created"
    assert isinstance(draft, CommentDraft)
    assert draft.client_id == client.id
    assert draft.thread_id == thread.id
    assert draft.avatar_id == avatar.id
    assert draft.status == "pending"
    assert draft.ai_draft is not None

    # ---------------------------------------------------------------
    # 7. Verify review queue visibility (Req 8.6)
    # ---------------------------------------------------------------
    review_drafts = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.client_id == client.id,
            CommentDraft.status == "pending",
        )
        .all()
    )
    assert len(review_drafts) >= 1, "CommentDraft should appear in review queue"
    assert any(d.id == draft.id for d in review_drafts), (
        "The generated draft should be visible in the client's review queue"
    )
