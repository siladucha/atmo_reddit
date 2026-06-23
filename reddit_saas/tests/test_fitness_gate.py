"""Unit tests for the fitness_gate service.

Tests cover:
- evaluate_fitness() with each rule check in order
- Fail-open behavior when no profile exists
- Fitness score computation
- batch_evaluate_fitness() preloading
- Edge cases: NULL account_created, missing karma records
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.avatar import Avatar
from app.models.avatar_subreddit_compatibility import AvatarSubredditCompatibility
from app.models.comment_draft import CommentDraft
from app.models.subreddit import Subreddit
from app.models.subreddit_karma import SubredditKarma
from app.models.subreddit_risk_profile import SubredditRiskProfile
from app.models.thread import RedditThread
from app.services.fitness_gate import (
    DANGEROUS_HOURS_KARMA_THRESHOLD,
    EXTREME_AGGRESSIVENESS_KARMA_THRESHOLD,
    FITNESS_AGE_HEADROOM_MAX_DAYS,
    FITNESS_KARMA_HEADROOM_MAX,
    FitnessResult,
    _compute_fitness_score,
    _parse_days,
    _parse_frequency_limit,
    _parse_int,
    evaluate_fitness,
    batch_evaluate_fitness,
)


# ---------------------------------------------------------------------------
# Helper: create test data fixtures
# ---------------------------------------------------------------------------


def _create_subreddit(db, name: str = "testsub") -> Subreddit:
    """Create a test subreddit."""
    sub = Subreddit(subreddit_name=name, is_active=True)
    db.add(sub)
    db.flush()
    return sub


def _create_avatar(
    db,
    username: str = "TestAvatar1",
    account_created: datetime | None = None,
) -> Avatar:
    """Create a test avatar."""
    if account_created is None:
        account_created = datetime.now(timezone.utc) - timedelta(days=180)
    avatar = Avatar(
        reddit_username=username,
        reddit_account_created=account_created,
        active=True,
    )
    db.add(avatar)
    db.flush()
    return avatar


def _create_profile(
    db,
    subreddit: Subreddit,
    *,
    extracted_rules: list | None = None,
    moderation_profile: dict | None = None,
    dangerous_hours: list | None = None,
    dominant_timezone: str = "UTC",
) -> SubredditRiskProfile:
    """Create a SubredditRiskProfile for a subreddit."""
    profile = SubredditRiskProfile(
        subreddit_id=subreddit.id,
        extracted_rules=extracted_rules or [],
        moderation_profile=moderation_profile or {"removal_rate": 0.1, "aggressiveness": "low"},
        dangerous_hours=dangerous_hours or [],
        dominant_timezone=dominant_timezone,
        confidence_level="medium",
    )
    db.add(profile)
    db.flush()
    return profile


def _create_karma(db, avatar: Avatar, subreddit_name: str, karma: int = 100) -> SubredditKarma:
    """Create a SubredditKarma record."""
    record = SubredditKarma(
        avatar_id=avatar.id,
        subreddit_name=subreddit_name,
        comment_karma=karma,
    )
    db.add(record)
    db.flush()
    return record


# ---------------------------------------------------------------------------
# Tests: Parser helpers
# ---------------------------------------------------------------------------


class TestParseDays:
    def test_simple_number(self):
        assert _parse_days("30") == 30

    def test_days_suffix(self):
        assert _parse_days("30 days") == 30

    def test_day_suffix(self):
        assert _parse_days("1 day") == 1

    def test_none_value(self):
        assert _parse_days("") is None

    def test_no_digits(self):
        assert _parse_days("no number") is None


class TestParseInt:
    def test_simple_number(self):
        assert _parse_int("500") == 500

    def test_with_text(self):
        assert _parse_int("500 karma") == 500

    def test_empty(self):
        assert _parse_int("") is None


class TestParseFrequencyLimit:
    def test_per_day(self):
        assert _parse_frequency_limit("3 per day") == (3, 24)

    def test_slash_day(self):
        assert _parse_frequency_limit("5/day") == (5, 24)

    def test_per_week(self):
        assert _parse_frequency_limit("10 per week") == (10, 168)

    def test_posts_per_day(self):
        assert _parse_frequency_limit("3 posts per day") == (3, 24)

    def test_just_number(self):
        assert _parse_frequency_limit("3") == (3, 24)

    def test_empty(self):
        assert _parse_frequency_limit("") is None

    def test_none(self):
        assert _parse_frequency_limit(None) is None


# ---------------------------------------------------------------------------
# Tests: evaluate_fitness - fail-open (Req 3.10)
# ---------------------------------------------------------------------------


class TestFitnessGateFailOpen:
    """Req 3.10: If no profile exists, allow generation (fail-open)."""

    def test_no_profile_passes(self, db):
        avatar = _create_avatar(db, username="failopen_avatar1")
        result = evaluate_fitness(db, avatar, "nonexistent_subreddit_xyz")
        assert result.passed is True
        assert result.score == 50
        assert result.blocked_by is None

    def test_no_subreddit_record_passes(self, db):
        """Even if subreddit table has no record."""
        avatar = _create_avatar(db, username="failopen_avatar2")
        result = evaluate_fitness(db, avatar, "totally_unknown_sub")
        assert result.passed is True


# ---------------------------------------------------------------------------
# Tests: evaluate_fitness - min_karma (Req 3.2)
# ---------------------------------------------------------------------------


class TestFitnessGateMinKarma:
    """Req 3.2: Block if avatar karma < min_karma threshold."""

    def test_blocks_low_karma(self, db):
        sub = _create_subreddit(db, "karma_test_sub1")
        avatar = _create_avatar(db, username="lowkarma_avatar1")
        _create_karma(db, avatar, "karma_test_sub1", karma=100)
        _create_profile(db, sub, extracted_rules=[
            {"category": "min_karma", "description": "Need 500 karma", "threshold_value": "500"}
        ])

        result = evaluate_fitness(db, avatar, "karma_test_sub1")
        assert result.passed is False
        assert result.blocked_by == "min_karma"
        assert "100" in result.reason
        assert "500" in result.reason

    def test_passes_sufficient_karma(self, db):
        sub = _create_subreddit(db, "karma_test_sub2")
        avatar = _create_avatar(db, username="highkarma_avatar1")
        _create_karma(db, avatar, "karma_test_sub2", karma=600)
        _create_profile(db, sub, extracted_rules=[
            {"category": "min_karma", "description": "Need 500 karma", "threshold_value": "500"}
        ])

        result = evaluate_fitness(db, avatar, "karma_test_sub2")
        assert result.passed is True

    def test_passes_exact_threshold(self, db):
        sub = _create_subreddit(db, "karma_test_sub3")
        avatar = _create_avatar(db, username="exactkarma_avatar1")
        _create_karma(db, avatar, "karma_test_sub3", karma=500)
        _create_profile(db, sub, extracted_rules=[
            {"category": "min_karma", "description": "Need 500 karma", "threshold_value": "500"}
        ])

        result = evaluate_fitness(db, avatar, "karma_test_sub3")
        assert result.passed is True

    def test_zero_karma_no_record(self, db):
        """If no SubredditKarma record exists, karma defaults to 0."""
        sub = _create_subreddit(db, "karma_test_sub4")
        avatar = _create_avatar(db, username="nokarma_avatar1")
        _create_profile(db, sub, extracted_rules=[
            {"category": "min_karma", "description": "Need 100 karma", "threshold_value": "100"}
        ])

        result = evaluate_fitness(db, avatar, "karma_test_sub4")
        assert result.passed is False
        assert result.blocked_by == "min_karma"


# ---------------------------------------------------------------------------
# Tests: evaluate_fitness - min_account_age (Req 3.3, 3.4)
# ---------------------------------------------------------------------------


class TestFitnessGateMinAccountAge:
    """Req 3.3, 3.4: Block if account too young. Skip if NULL."""

    def test_blocks_young_account(self, db):
        sub = _create_subreddit(db, "age_test_sub1")
        avatar = _create_avatar(
            db, username="young_avatar1",
            account_created=datetime.now(timezone.utc) - timedelta(days=10),
        )
        _create_karma(db, avatar, "age_test_sub1", karma=1000)
        _create_profile(db, sub, extracted_rules=[
            {"category": "min_account_age", "description": "30 day minimum", "threshold_value": "30 days"}
        ])

        result = evaluate_fitness(db, avatar, "age_test_sub1")
        assert result.passed is False
        assert result.blocked_by == "min_account_age"

    def test_passes_old_account(self, db):
        sub = _create_subreddit(db, "age_test_sub2")
        avatar = _create_avatar(
            db, username="old_avatar1",
            account_created=datetime.now(timezone.utc) - timedelta(days=90),
        )
        _create_karma(db, avatar, "age_test_sub2", karma=1000)
        _create_profile(db, sub, extracted_rules=[
            {"category": "min_account_age", "description": "30 day minimum", "threshold_value": "30 days"}
        ])

        result = evaluate_fitness(db, avatar, "age_test_sub2")
        assert result.passed is True

    def test_skips_null_account_created(self, db):
        """Req 3.4: If reddit_account_created is NULL, skip age check."""
        sub = _create_subreddit(db, "age_test_sub3")
        avatar = Avatar(
            reddit_username="null_age_avatar1",
            reddit_account_created=None,
            active=True,
        )
        db.add(avatar)
        db.flush()
        _create_karma(db, avatar, "age_test_sub3", karma=1000)
        _create_profile(db, sub, extracted_rules=[
            {"category": "min_account_age", "description": "30 day minimum", "threshold_value": "30 days"}
        ])

        result = evaluate_fitness(db, avatar, "age_test_sub3")
        assert result.passed is True


# ---------------------------------------------------------------------------
# Tests: evaluate_fitness - extreme aggressiveness (Req 3.7)
# ---------------------------------------------------------------------------


class TestFitnessGateExtremeAggressiveness:
    """Req 3.7: Block if extreme aggressiveness + <50 karma."""

    def test_blocks_extreme_low_karma(self, db):
        sub = _create_subreddit(db, "extreme_sub1")
        avatar = _create_avatar(db, username="extreme_test_avatar1")
        _create_karma(db, avatar, "extreme_sub1", karma=30)
        _create_profile(
            db, sub,
            moderation_profile={"removal_rate": 0.6, "aggressiveness": "extreme"},
        )

        result = evaluate_fitness(db, avatar, "extreme_sub1")
        assert result.passed is False
        assert result.blocked_by == "extreme_aggressiveness"

    def test_passes_extreme_sufficient_karma(self, db):
        sub = _create_subreddit(db, "extreme_sub2")
        avatar = _create_avatar(db, username="extreme_test_avatar2")
        _create_karma(db, avatar, "extreme_sub2", karma=60)
        _create_profile(
            db, sub,
            moderation_profile={"removal_rate": 0.6, "aggressiveness": "extreme"},
        )

        result = evaluate_fitness(db, avatar, "extreme_sub2")
        assert result.passed is True

    def test_passes_non_extreme_low_karma(self, db):
        """High aggressiveness (not extreme) + low karma should pass."""
        sub = _create_subreddit(db, "extreme_sub3")
        avatar = _create_avatar(db, username="extreme_test_avatar3")
        _create_karma(db, avatar, "extreme_sub3", karma=30)
        _create_profile(
            db, sub,
            moderation_profile={"removal_rate": 0.4, "aggressiveness": "high"},
        )

        result = evaluate_fitness(db, avatar, "extreme_sub3")
        assert result.passed is True


# ---------------------------------------------------------------------------
# Tests: evaluate_fitness - dangerous hours (Req 3.8)
# ---------------------------------------------------------------------------


class TestFitnessGateDangerousHours:
    """Req 3.8: Block during dangerous hours + <200 karma."""

    def test_blocks_during_dangerous_hour(self, db):
        sub = _create_subreddit(db, "danger_sub1")
        avatar = _create_avatar(db, username="danger_avatar1")
        _create_karma(db, avatar, "danger_sub1", karma=100)
        _create_profile(
            db, sub,
            dangerous_hours=[14, 15, 22],
            dominant_timezone="UTC",
        )

        result = evaluate_fitness(db, avatar, "danger_sub1", current_hour=14)
        assert result.passed is False
        assert result.blocked_by == "dangerous_hours"

    def test_passes_outside_dangerous_hour(self, db):
        sub = _create_subreddit(db, "danger_sub2")
        avatar = _create_avatar(db, username="danger_avatar2")
        _create_karma(db, avatar, "danger_sub2", karma=100)
        _create_profile(
            db, sub,
            dangerous_hours=[14, 15, 22],
            dominant_timezone="UTC",
        )

        result = evaluate_fitness(db, avatar, "danger_sub2", current_hour=10)
        assert result.passed is True

    def test_passes_sufficient_karma_during_dangerous_hour(self, db):
        """>=200 karma should pass even during dangerous hours."""
        sub = _create_subreddit(db, "danger_sub3")
        avatar = _create_avatar(db, username="danger_avatar3")
        _create_karma(db, avatar, "danger_sub3", karma=250)
        _create_profile(
            db, sub,
            dangerous_hours=[14, 15, 22],
            dominant_timezone="UTC",
        )

        result = evaluate_fitness(db, avatar, "danger_sub3", current_hour=14)
        assert result.passed is True


# ---------------------------------------------------------------------------
# Tests: fitness score computation (Req 3.9)
# ---------------------------------------------------------------------------


class TestFitnessScoreComputation:
    """Req 3.9: Compute fitness_score 0-100."""

    def test_full_compliance_high_karma_old_account(self):
        avatar = Avatar(
            reddit_username="score_avatar",
            reddit_account_created=datetime.now(timezone.utc) - timedelta(days=500),
            active=True,
        )
        rules = [
            {"category": "min_karma", "description": "100 karma", "threshold_value": "100"},
            {"category": "min_account_age", "description": "30 days", "threshold_value": "30"},
        ]
        score = _compute_fitness_score(
            extracted_rules=rules,
            avatar_karma=1100,
            avatar=avatar,
        )
        assert score == 100

    def test_no_rules_max_score(self):
        avatar = Avatar(
            reddit_username="score_avatar2",
            reddit_account_created=datetime.now(timezone.utc) - timedelta(days=100),
            active=True,
        )
        score = _compute_fitness_score(
            extracted_rules=[],
            avatar_karma=500,
            avatar=avatar,
        )
        # compliance: 100% (no rules), karma headroom: 500/1000=50%, age headroom: 100% (no rule)
        # 100*0.4 + 50*0.3 + 100*0.3 = 40 + 15 + 30 = 85
        assert score == 85

    def test_zero_karma_with_min_karma_rule(self):
        avatar = Avatar(
            reddit_username="score_avatar3",
            reddit_account_created=datetime.now(timezone.utc) - timedelta(days=100),
            active=True,
        )
        rules = [
            {"category": "min_karma", "description": "500 karma", "threshold_value": "500"},
        ]
        score = _compute_fitness_score(
            extracted_rules=rules,
            avatar_karma=0,
            avatar=avatar,
        )
        # compliance: 0/1 = 0%, karma headroom: (0-500)/1000 clamped to 0%, age headroom: 100%
        # 0*0.4 + 0*0.3 + 100*0.3 = 0 + 0 + 30 = 30
        assert score == 30

    def test_score_stored_on_compatibility(self, db):
        """Score is stored on AvatarSubredditCompatibility."""
        sub = _create_subreddit(db, "score_store_sub1")
        avatar = _create_avatar(db, username="score_store_avatar1")
        _create_karma(db, avatar, "score_store_sub1", karma=600)
        _create_profile(db, sub, extracted_rules=[
            {"category": "min_karma", "description": "100 karma", "threshold_value": "100"}
        ])

        result = evaluate_fitness(db, avatar, "score_store_sub1")
        assert result.passed is True

        compat = (
            db.query(AvatarSubredditCompatibility)
            .filter(
                AvatarSubredditCompatibility.avatar_id == avatar.id,
                AvatarSubredditCompatibility.subreddit_name == "score_store_sub1",
            )
            .first()
        )
        assert compat is not None
        assert compat.fitness_score == result.score
        assert compat.fitness_computed_at is not None


# ---------------------------------------------------------------------------
# Tests: batch_evaluate_fitness (Req 8.5)
# ---------------------------------------------------------------------------


class TestBatchEvaluateFitness:
    """Req 8.5: Batch evaluation with preloaded data."""

    def test_empty_list_returns_empty(self, db):
        avatar = _create_avatar(db, username="batch_avatar1")
        results = batch_evaluate_fitness(db, avatar, [])
        assert results == []

    def test_multiple_subreddits(self, db):
        """Evaluate multiple subreddits in one call."""
        sub1 = _create_subreddit(db, "batch_sub1")
        sub2 = _create_subreddit(db, "batch_sub2")
        avatar = _create_avatar(db, username="batch_avatar2")
        _create_karma(db, avatar, "batch_sub1", karma=600)
        _create_karma(db, avatar, "batch_sub2", karma=20)

        _create_profile(db, sub1, extracted_rules=[
            {"category": "min_karma", "description": "100 karma", "threshold_value": "100"}
        ])
        _create_profile(db, sub2, extracted_rules=[
            {"category": "min_karma", "description": "500 karma", "threshold_value": "500"}
        ])

        pairs = [
            (uuid.uuid4(), "batch_sub1"),
            (uuid.uuid4(), "batch_sub2"),
        ]
        results = batch_evaluate_fitness(db, avatar, pairs)

        assert len(results) == 2
        assert results[0].passed is True
        assert results[1].passed is False
        assert results[1].blocked_by == "min_karma"

    def test_missing_profile_fail_open_in_batch(self, db):
        """Subreddits without profiles should pass (fail-open)."""
        avatar = _create_avatar(db, username="batch_avatar3")
        pairs = [(uuid.uuid4(), "nonexistent_batch_sub")]
        results = batch_evaluate_fitness(db, avatar, pairs)

        assert len(results) == 1
        assert results[0].passed is True
        assert results[0].score == 50


# ---------------------------------------------------------------------------
# Tests: activity events (Req 3.6)
# ---------------------------------------------------------------------------


class TestFitnessGateActivityEvents:
    """Req 3.6: Blocked events emit fitness_gate_blocked."""

    def test_blocked_emits_event(self, db):
        from app.models.activity_event import ActivityEvent

        sub = _create_subreddit(db, "event_sub1")
        avatar = _create_avatar(db, username="event_avatar1")
        _create_karma(db, avatar, "event_sub1", karma=10)
        _create_profile(db, sub, extracted_rules=[
            {"category": "min_karma", "description": "500 karma", "threshold_value": "500"}
        ])

        evaluate_fitness(db, avatar, "event_sub1")

        event = (
            db.query(ActivityEvent)
            .filter(ActivityEvent.event_type == "fitness_gate_blocked")
            .order_by(ActivityEvent.created_at.desc())
            .first()
        )
        assert event is not None
        assert "event_avatar1" in event.message
        assert "event_sub1" in event.message

    def test_failopen_emits_warning(self, db):
        from app.models.activity_event import ActivityEvent

        avatar = _create_avatar(db, username="event_avatar2")
        evaluate_fitness(db, avatar, "missing_profile_sub_for_event")

        event = (
            db.query(ActivityEvent)
            .filter(ActivityEvent.event_type == "fitness_gate_warning")
            .order_by(ActivityEvent.created_at.desc())
            .first()
        )
        assert event is not None
        assert "missing_profile_sub_for_event" in event.message
