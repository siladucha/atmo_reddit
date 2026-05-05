"""Test safety service — content checks, rate limits, and PhasePolicy integration."""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.activity_event import ActivityEvent
from app.services.safety import (
    check_avatar_can_post,
    check_comment_content,
    SafetyCheckResult,
    MAX_COMMENTS_PER_DAY,
)
from app.services.phase_types import PolicyStatus, PolicyResult


# --- Content check tests (unchanged) ---


def test_normal_comment_passes():
    result = check_comment_content("this is a normal comment about security practices")
    assert result.allowed


def test_promotional_link_blocked():
    result = check_comment_content("check out www.example.com for more info")
    assert not result.allowed
    assert "promotional" in result.reason.lower() or "www." in result.reason


def test_promotional_phrases_blocked():
    phrases = ["check out our platform", "visit our website", "sign up now", "free trial available"]
    for phrase in phrases:
        result = check_comment_content(phrase)
        assert not result.allowed, f"Should block: {phrase}"


def test_long_comment_blocked():
    result = check_comment_content("x" * 301)
    assert not result.allowed
    assert "long" in result.reason.lower()


def test_comment_at_limit_passes():
    result = check_comment_content("x" * 300)
    assert result.allowed


def test_empty_comment_passes():
    result = check_comment_content("")
    assert result.allowed


def test_safety_result_bool():
    ok = SafetyCheckResult(True)
    assert bool(ok) is True

    blocked = SafetyCheckResult(False, "test reason")
    assert bool(blocked) is False
    assert blocked.reason == "test reason"


# --- PhasePolicy integration tests ---


@pytest.fixture
def sample_client(db: Session) -> Client:
    """Create a sample client with brand_name and brand_domain."""
    c = Client(
        id=uuid.uuid4(),
        client_name="Test Corp",
        brand_name="TestBrand",
        brand_domain="testbrand.com",
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def sample_avatar(db: Session, sample_client: Client) -> Avatar:
    """Create a sample avatar with warming_phase=1 and phase_changed_at set."""
    a = Avatar(
        id=uuid.uuid4(),
        reddit_username=f"test_safety_avatar_{uuid.uuid4().hex[:8]}",
        active=True,
        is_shadowbanned=False,
        warming_phase=1,
        phase_changed_at=datetime.now(timezone.utc) - timedelta(days=30),
        client_ids=[str(sample_client.id)],
        hobby_subreddits=["python", "learnprogramming"],
        business_subreddits=["cybersecurity"],
        karma_comment=50,
        karma_post=10,
        reddit_karma_comment=50,
        reddit_karma_post=10,
        reddit_account_created=datetime.now(timezone.utc) - timedelta(days=30),
    )
    db.add(a)
    db.flush()
    return a


def test_phase_policy_called_before_rate_limits(db: Session, sample_avatar: Avatar, sample_client: Client):
    """PhasePolicy runs before rate limits when all parameters are provided.

    Verifies requirement 8.1: PhasePolicy is invoked before existing rate limit checks.
    """
    # Phase 1 avatar trying to post a professional comment should be blocked by PhasePolicy
    # (Phase 1 only allows hobby comments), regardless of rate limits.
    result = check_avatar_can_post(
        db=db,
        avatar=sample_avatar,
        comment_type="professional",
        target_subreddit="cybersecurity",
        comment_text="Great insights on network security",
        client=sample_client,
        thread_tag=None,
    )

    assert not result.allowed
    # The reason should mention Phase 1 restriction, not a rate limit
    assert "phase 1" in result.reason.lower() or "Phase 1" in result.reason


def test_backward_compat_no_phase_params(db: Session, sample_avatar: Avatar):
    """When optional params are not provided, only rate limits run (backward compat).

    Verifies requirement 8.3: The old calling convention still works.
    """
    # Without target_subreddit/comment_text/client, PhasePolicy is skipped.
    # A Phase 1 avatar with no comments today should pass rate limits.
    result = check_avatar_can_post(
        db=db,
        avatar=sample_avatar,
        comment_type="hobby",
    )

    # Should be allowed since rate limits are not exceeded
    assert result.allowed


def test_phase1_blocks_brand_mentions(db: Session, sample_avatar: Avatar, sample_client: Client):
    """Phase 1 blocks any comment containing brand mentions."""
    result = check_avatar_can_post(
        db=db,
        avatar=sample_avatar,
        comment_type="hobby",
        target_subreddit="python",
        comment_text="I really like TestBrand for this use case",
        client=sample_client,
    )

    assert not result.allowed
    assert "brand" in result.reason.lower() or "Phase 1" in result.reason


def test_phase1_allows_hobby_in_hobby_subreddit(db: Session, sample_avatar: Avatar, sample_client: Client):
    """Phase 1 allows hobby comments in hobby subreddits with no brand mentions."""
    result = check_avatar_can_post(
        db=db,
        avatar=sample_avatar,
        comment_type="hobby",
        target_subreddit="python",
        comment_text="I love working with decorators in Python",
        client=sample_client,
    )

    assert result.allowed


def test_inactive_avatar_blocked(db: Session, sample_avatar: Avatar):
    """Inactive avatars are always blocked regardless of phase."""
    sample_avatar.active = False
    db.flush()

    result = check_avatar_can_post(db=db, avatar=sample_avatar, comment_type="hobby")
    assert not result.allowed
    assert "deactivated" in result.reason.lower()


def test_shadowbanned_avatar_blocked(db: Session, sample_avatar: Avatar):
    """Shadowbanned avatars are always blocked regardless of phase."""
    sample_avatar.is_shadowbanned = True
    db.flush()

    result = check_avatar_can_post(db=db, avatar=sample_avatar, comment_type="hobby")
    assert not result.allowed
    assert "shadowbanned" in result.reason.lower()


def test_policy_block_logs_activity_event(db: Session, sample_avatar: Avatar, sample_client: Client):
    """When PhasePolicy blocks a comment, a policy_block ActivityEvent is logged.

    Verifies requirement 8.6.
    """
    # Phase 1 avatar trying professional comment → blocked by PhasePolicy
    result = check_avatar_can_post(
        db=db,
        avatar=sample_avatar,
        comment_type="professional",
        target_subreddit="cybersecurity",
        comment_text="Check out this security tool",
        client=sample_client,
    )

    assert not result.allowed

    # Check that a policy_block event was logged
    events = (
        db.query(ActivityEvent)
        .filter(ActivityEvent.event_type == "policy_block")
        .all()
    )
    assert len(events) >= 1
    event = events[-1]
    assert "Phase 1" in event.message or "phase" in event.message.lower()
    assert event.event_metadata is not None
    assert event.event_metadata["avatar_id"] == str(sample_avatar.id)
    assert event.event_metadata["phase"] == 1
