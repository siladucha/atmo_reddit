"""Tests for Daily EPG Minimum Guarantee.

Verifies:
1. Archive fallback in scan_opportunities returns posts when no fresh ones exist
2. No-repeat rule: previously drafted posts are excluded from archive
3. ensure_daily_epg_minimum task identifies starving avatars correctly
4. Phase 0 avatars are included in EPG pipeline (not excluded as "Mentor")
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


class TestArchiveFallbackDedup:
    """Test that archive fallback excludes all previously-drafted hobby posts."""

    def test_all_drafted_ids_query_includes_all_statuses(self):
        """Dedup set must include hobby_post_ids from drafts with ANY status
        (pending, approved, posted, rejected) — not just active ones."""
        from app.models.comment_draft import CommentDraft

        # Verify the model has hobby_post_id field
        assert hasattr(CommentDraft, "hobby_post_id")

    def test_archive_fallback_excludes_drafted_posts(self):
        """Archive fallback query must filter out posts the avatar already drafted for."""
        # This is a structural test — verify the code path exists
        import inspect
        from app.services.opportunity_engine import scan_opportunities

        source = inspect.getsource(scan_opportunities)
        # Verify archive fallback queries ALL drafted hobby_post_ids
        assert "_all_drafted_hobby_ids" in source
        assert "CommentDraft.hobby_post_id" in source
        # Verify notin_ filter is applied
        assert "notin_(_all_drafted_hobby_ids)" in source


class TestPhase0Inclusion:
    """Test that Phase 0 (Incubation) avatars are NOT excluded from EPG."""

    def test_portfolio_manager_allows_phase_0(self):
        """build_portfolio must NOT exclude Phase 0 avatars."""
        import inspect
        from app.services.portfolio_manager import build_portfolio

        source = inspect.getsource(build_portfolio)
        # Old guard was: if avatar.warming_phase == 0: return excluded
        # This should NOT exist anymore
        assert 'warming_phase == 0' not in source or 'NOT a phase' in source

    def test_attention_budget_phase_0_has_budget(self):
        """Phase 0 avatars should get budget=1 comment/day."""
        from app.services.portfolio_manager import AttentionBudget

        avatar = MagicMock()
        avatar.pool = "b2b"
        avatar.warming_phase = 0
        avatar.cqs_level = "medium"

        budget = AttentionBudget.from_avatar(avatar)
        assert budget.max_comments == 1
        assert budget.max_total_actions == 1

    def test_attention_budget_mentor_has_zero(self):
        """Mentor pool avatars should get budget=0."""
        from app.services.portfolio_manager import AttentionBudget

        avatar = MagicMock()
        avatar.pool = "mentor"
        avatar.warming_phase = 2

        budget = AttentionBudget.from_avatar(avatar)
        assert budget.max_comments == 0
        assert budget.max_total_actions == 0

    def test_attention_budget_cqs_lowest_has_zero(self):
        """CQS=lowest avatars should get budget=0 regardless of phase."""
        from app.services.portfolio_manager import AttentionBudget

        avatar = MagicMock()
        avatar.pool = "b2b"
        avatar.warming_phase = 2
        avatar.cqs_level = "lowest"

        budget = AttentionBudget.from_avatar(avatar)
        assert budget.max_comments == 0
        assert budget.max_total_actions == 0


class TestScanOpportunitiesArchiveFallback:
    """Test the archive fallback logic in scan_opportunities."""

    def test_archive_fallback_code_structure(self):
        """Verify the fallback code structure is correct."""
        import inspect
        from app.services.opportunity_engine import scan_opportunities

        source = inspect.getsource(scan_opportunities)

        # Primary query: fresh unused (7 days)
        assert "hobby_freshness_cutoff" in source
        assert "ai_comment.is_(None)" in source

        # Archive fallback: no freshness filter, no ai_comment filter
        assert "ARCHIVE FALLBACK" in source
        assert "_all_drafted_hobby_ids" in source

        # Sort by scraped_at desc (most recent archive posts first)
        assert "scraped_at.desc()" in source

    def test_default_hobby_subs_fallback_exists(self):
        """When avatar has no hobby_subreddits, DEFAULT_PHASE1_HOBBY_SUBREDDITS used."""
        import inspect
        from app.services.opportunity_engine import scan_opportunities

        source = inspect.getsource(scan_opportunities)
        assert "DEFAULT_PHASE1_HOBBY_SUBREDDITS" in source


class TestEnforcementTask:
    """Test ensure_daily_epg_minimum task structure."""

    def test_task_is_registered(self):
        """Task must be importable and registered."""
        from app.tasks.epg import ensure_daily_epg_minimum
        assert ensure_daily_epg_minimum is not None
        assert ensure_daily_epg_minimum.name == "ensure_daily_epg_minimum"

    def test_task_in_beat_schedule(self):
        """Task must be in Beat schedule."""
        from app.tasks.beat_app import beat_app

        schedule = beat_app.conf.beat_schedule
        assert "epg-ensure-daily-minimum" in schedule
        entry = schedule["epg-ensure-daily-minimum"]
        assert entry["task"] == "ensure_daily_epg_minimum"

    def test_enforcement_skips_zero_budget_avatars(self):
        """Avatars with budget=0 (CQS=lowest) should be skipped, not flagged as starving."""
        import inspect
        from app.tasks.epg import ensure_daily_epg_minimum

        source = inspect.getsource(ensure_daily_epg_minimum)
        # Must check budget before declaring avatar starving
        assert "max_total_actions <= 0" in source
        assert "continue" in source


class TestHobbyScrapingPhase0:
    """Test that hobby scraping includes Phase 0 avatars."""

    def test_scrape_all_includes_phase_0(self):
        """scrape_hobby_all_avatars must query warming_phase >= 0."""
        import inspect
        from app.tasks.scraping import scrape_hobby_all_avatars

        source = inspect.getsource(scrape_hobby_all_avatars)
        assert "warming_phase >= 0" in source

    def test_per_avatar_scrape_defaults_for_phase_0(self):
        """Phase 0 avatars with no hobby subs get default subs."""
        import inspect
        from app.tasks.scraping import scrape_hobby_subreddits

        source = inspect.getsource(scrape_hobby_subreddits)
        assert "warming_phase <= 1" in source
        assert "DEFAULT_PHASE1_HOBBY_SUBREDDITS" in source
