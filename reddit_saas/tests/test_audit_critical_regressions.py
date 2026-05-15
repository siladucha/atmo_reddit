"""Regression tests for CRITICAL audit findings (#1-#5).

These are pure unit tests — no DB, no fixtures from conftest. They exercise
the exact code paths that were broken before each fix and ensure the dict-
shaped JSONB / phase-gate / module-export contracts continue to hold.

#1 Phase 2 — TypeError on dict-shaped hobby_subreddits in set()
#2 Phase 1 — `target not in [{"subreddit": target}]` always True
#3 karma_tracker._classify_subreddit — .lower() on dict element
#4 Phase-policy gate bypassed in production call-sites (no client/comment_text)
#5 StrategyDocument missing from app.models package exports
"""

from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.karma_tracker import _classify_subreddit
from app.services.phase import PhasePolicy
from app.services.phase_types import PolicyStatus


# ---------------------------------------------------------------------------
# Helpers — build avatar/client without touching the DB
# ---------------------------------------------------------------------------


def _avatar_stub(
    *,
    warming_phase: int = 1,
    hobby_subreddits=None,
    business_subreddits=None,
    cqs_level=None,
):
    """Build a duck-typed Avatar — only attributes touched by PhasePolicy and
    karma_tracker._classify_subreddit."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        reddit_username="audit_avatar",
        active=True,
        is_shadowbanned=False,
        is_frozen=False,
        warming_phase=warming_phase,
        phase_changed_at=datetime.now(timezone.utc) - timedelta(days=30),
        client_ids=["00000000-0000-0000-0000-000000000001"],
        hobby_subreddits=hobby_subreddits if hobby_subreddits is not None else [],
        business_subreddits=business_subreddits if business_subreddits is not None else [],
        cqs_level=cqs_level,
    )


def _client_stub(*, brand_name="AuditBrand", brand_domain="auditbrand.example"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        client_name="Audit Test Corp",
        brand_name=brand_name,
        brand_domain=brand_domain,
    )


def _zero_count_db():
    """Mock DB session whose count queries always return 0 — keeps the daily-
    limit branches of PhasePolicy happy without a real DB."""
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = 0
    return db


# ---------------------------------------------------------------------------
# Fix #2 — Phase 1 accepts dict-shaped hobby_subreddits
# ---------------------------------------------------------------------------


def test_phase1_accepts_dict_form_hobby_subreddits():
    """Phase 1 must recognize a subreddit when hobby_subreddits is a list of
    dicts in the Ori format (`{"subreddit": "name"}` or `{"name": "name"}`).

    Before the fix: `target_subreddit not in [{"subreddit": "python"}]` was
    always True, so every Phase 1 hobby comment was blocked.
    """
    avatar = _avatar_stub(
        warming_phase=1,
        hobby_subreddits=[{"subreddit": "python"}, {"name": "django"}],
    )
    client = _client_stub()
    policy = PhasePolicy()

    result = policy.check_comment_allowed(
        db=_zero_count_db(),
        avatar=avatar,
        comment_type="hobby",
        target_subreddit="python",
        comment_text="hello",
        client=client,
    )
    assert result.status == PolicyStatus.allowed, (
        f"Phase 1 dict-form should be accepted, got: {result.status}/{result.reason}"
    )


def test_phase1_dict_form_case_insensitive():
    """`Python` in config + `python` from Reddit must still match."""
    avatar = _avatar_stub(warming_phase=1, hobby_subreddits=[{"subreddit": "Python"}])
    policy = PhasePolicy()

    result = policy.check_comment_allowed(
        db=_zero_count_db(),
        avatar=avatar,
        comment_type="hobby",
        target_subreddit="python",
        comment_text="match",
        client=_client_stub(),
    )
    assert result.status == PolicyStatus.allowed, result.reason


def test_phase1_blocks_subreddit_outside_hobby_list():
    """The fix must not weaken the allowlist — random subs are still blocked."""
    avatar = _avatar_stub(warming_phase=1, hobby_subreddits=[{"subreddit": "python"}])
    policy = PhasePolicy()

    result = policy.check_comment_allowed(
        db=_zero_count_db(),
        avatar=avatar,
        comment_type="hobby",
        target_subreddit="randomsub",
        comment_text="hello",
        client=_client_stub(),
    )
    assert result.status == PolicyStatus.blocked
    assert "not in hobby_subreddits" in result.reason


# ---------------------------------------------------------------------------
# Fix #1 — Phase 2 doesn't raise TypeError on dict-shaped JSONB
# ---------------------------------------------------------------------------


def test_phase2_dict_form_no_typeerror():
    """Phase 2 must not crash with `TypeError: unhashable type: 'dict'`.
    Before the fix: `set([{"subreddit": "wine"}])` raised TypeError, which
    safety.py converted to a generic "Phase policy check error".
    """
    avatar = _avatar_stub(
        warming_phase=2,
        hobby_subreddits=[{"subreddit": "wine"}],
        business_subreddits=[{"subreddit": "cybersecurity"}],
    )
    client = _client_stub()
    policy = PhasePolicy()

    for target, ctype in (("cybersecurity", "professional"), ("wine", "hobby")):
        result = policy.check_comment_allowed(
            db=_zero_count_db(),
            avatar=avatar,
            comment_type=ctype,
            target_subreddit=target,
            comment_text="non-brand content",
            client=client,
        )
        assert result.status == PolicyStatus.allowed, (
            f"Phase 2 dict-form failed for r/{target}: {result.reason}"
        )


def test_phase2_dict_form_blocks_unlisted_subreddit():
    """Phase 2 still blocks subreddits not in either list."""
    avatar = _avatar_stub(
        warming_phase=2,
        hobby_subreddits=[{"subreddit": "wine"}],
        business_subreddits=[{"subreddit": "cybersecurity"}],
    )
    policy = PhasePolicy()

    result = policy.check_comment_allowed(
        db=_zero_count_db(),
        avatar=avatar,
        comment_type="professional",
        target_subreddit="randomsub",
        comment_text="non-brand",
        client=_client_stub(),
    )
    assert result.status == PolicyStatus.blocked
    assert "not in allowed" in result.reason


# ---------------------------------------------------------------------------
# Fix #3 — karma_tracker._classify_subreddit handles dict elements
# ---------------------------------------------------------------------------


def test_classify_subreddit_handles_dict_form():
    """_classify_subreddit must return the correct type when subreddit lists
    contain dicts. Before the fix: `.lower()` was called on a dict element.
    """
    avatar = _avatar_stub(
        business_subreddits=[{"subreddit": "cybersecurity"}],
        hobby_subreddits=[{"name": "wine"}],
    )
    assert _classify_subreddit(avatar, "cybersecurity") == "professional"
    assert _classify_subreddit(avatar, "wine") == "hobby"
    assert _classify_subreddit(avatar, "random") == "unknown"


def test_classify_subreddit_mixed_string_and_dict():
    """Mixed list (some strings, some dicts) must still classify both kinds."""
    avatar = _avatar_stub(
        business_subreddits=["cybersecurity", {"subreddit": "networking"}],
        hobby_subreddits=[{"name": "wine"}, "cooking"],
    )
    assert _classify_subreddit(avatar, "cybersecurity") == "professional"
    assert _classify_subreddit(avatar, "networking") == "professional"
    assert _classify_subreddit(avatar, "wine") == "hobby"
    assert _classify_subreddit(avatar, "cooking") == "hobby"


def test_classify_subreddit_legacy_dict_root():
    """JSONB stored as object (not list) — pre-existing branch must still work."""
    # clean_subreddit_list returns [] for a bare dict root; classification = unknown.
    # The pre-fix code attempted `list(business.keys())` for this case — we no
    # longer support it (the data shape is documented as a list), so this just
    # confirms behaviour is well-defined (no crash, returns "unknown").
    avatar = _avatar_stub(
        business_subreddits={"cybersecurity": True},  # object-shaped JSONB
        hobby_subreddits=[],
    )
    # Either "professional" (if someone re-adds dict-root support) or "unknown"
    # is acceptable — what matters is NO exception.
    result = _classify_subreddit(avatar, "cybersecurity")
    assert result in ("professional", "unknown")


# ---------------------------------------------------------------------------
# Fix #4 — phase-policy gate is invoked when call-sites pass full args
# ---------------------------------------------------------------------------


def test_phase1_avatar_blocked_from_professional_subreddit_via_gate():
    """When call-sites pass target_subreddit + client + comment_text (even
    empty), PhasePolicy must block Phase 1 from professional subs.

    This is the contract `tasks/ai_pipeline.generate_comments` and
    `routes/avatar_pipeline.pipeline_generate` rely on after Fix #4.
    """
    avatar = _avatar_stub(
        warming_phase=1, hobby_subreddits=["python"], business_subreddits=[]
    )
    policy = PhasePolicy()

    result = policy.check_comment_allowed(
        db=_zero_count_db(),
        avatar=avatar,
        comment_type="professional",
        target_subreddit="cybersecurity",
        comment_text="",
        client=_client_stub(),
    )
    assert result.status == PolicyStatus.blocked, (
        "Phase 1 avatar must be blocked from professional comment in "
        "non-hobby subreddit when caller passes target+client."
    )
    assert "phase 1" in result.reason.lower()


def test_generate_comments_callsite_passes_client_to_safety():
    """The fixed call-site in tasks.ai_pipeline.generate_comments must pass
    `client=...` to check_avatar_can_post — proves Fix #4 is wired in."""
    from app.tasks import ai_pipeline

    source = inspect.getsource(ai_pipeline.generate_comments)
    assert "target_subreddit=thread.subreddit" in source, (
        "generate_comments must pass target_subreddit to check_avatar_can_post"
    )
    assert "client=client" in source, (
        "generate_comments must pass client to check_avatar_can_post"
    )


def test_avatar_pipeline_route_passes_client_to_safety():
    """Same assertion for the manual pipeline routes."""
    from app.routes import avatar_pipeline as ap

    src_generate = inspect.getsource(ap.pipeline_generate)
    src_regen = inspect.getsource(ap.pipeline_regenerate)

    for src, fn in [(src_generate, "pipeline_generate"), (src_regen, "pipeline_regenerate")]:
        assert "target_subreddit=thread.subreddit" in src, (
            f"{fn} must pass target_subreddit=thread.subreddit to check_avatar_can_post"
        )
        assert "client=client" in src, (
            f"{fn} must pass client=client to check_avatar_can_post"
        )


# ---------------------------------------------------------------------------
# Fix #5 — StrategyDocument is exported from app.models
# ---------------------------------------------------------------------------


def test_strategy_document_exported_in_models_init():
    """StrategyDocument must be importable from `app.models` so Alembic
    autogenerate sees the table and does not emit a spurious DROP."""
    from app import models

    assert hasattr(models, "StrategyDocument"), (
        "StrategyDocument not exported from app.models — autogenerate may "
        "emit DROP TABLE strategy_documents."
    )
    from app.models import StrategyDocument

    assert StrategyDocument.__tablename__ == "strategy_documents"
    assert "StrategyDocument" in models.__all__
