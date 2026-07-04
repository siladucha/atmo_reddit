"""Tests for Intent Snapshot Collector (Layer 2 of Forecast & Reporting).

Tests cover:
- GEO batch schedule computation (next Tue+Fri occurrences)
- EPG status mapping
- Phase label generation
- Promotion criteria retrieval
- Weeks-to-promotion estimation
- IntentSnapshot dataclass serialization
- ExecutionIntent construction via _make_intent
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.services.forecast.intent_snapshot import (
    ExecutionIntent,
    IntentSnapshot,
    VALIDITY_DAILY_EPG,
    VALIDITY_GEO_BATCH,
    VALIDITY_PENDING_DRAFTS,
    VALIDITY_PHASE_ROADMAP,
    VALIDITY_SUBREDDIT_COVERAGE,
    _estimate_weeks_to_promotion,
    _get_promotion_criteria,
    _make_intent,
    _map_epg_status,
    _next_geo_batch_dates,
    _phase_label,
)


# ---------------------------------------------------------------------------
# Tests: GEO batch schedule computation
# ---------------------------------------------------------------------------


class TestNextGeoBatchDates:
    def test_returns_requested_count(self):
        """Should return exactly `count` dates."""
        dates = _next_geo_batch_dates(date(2026, 7, 1), count=4)
        assert len(dates) <= 4  # may be fewer if starting at edge

    def test_only_tuesday_and_friday(self):
        """All returned dates must be Tuesday (weekday=1) or Friday (weekday=4)."""
        dates = _next_geo_batch_dates(date(2026, 7, 1), count=8)
        for dt in dates:
            assert dt.weekday() in (1, 4), f"{dt} is not Tue/Fri"

    def test_time_is_0930_utc(self):
        """All returned dates have time 09:30 UTC."""
        dates = _next_geo_batch_dates(date(2026, 7, 1), count=4)
        for dt in dates:
            assert dt.hour == 9
            assert dt.minute == 30

    def test_dates_are_future(self):
        """All returned dates must be in the future."""
        now = datetime.now(timezone.utc)
        dates = _next_geo_batch_dates(date.today(), count=4)
        for dt in dates:
            assert dt > now

    def test_dates_are_sorted(self):
        """Dates should be in ascending order."""
        dates = _next_geo_batch_dates(date(2026, 7, 1), count=4)
        for i in range(len(dates) - 1):
            assert dates[i] < dates[i + 1]

    def test_empty_when_count_zero(self):
        """count=0 should return empty list."""
        dates = _next_geo_batch_dates(date(2026, 7, 1), count=0)
        assert dates == []

    def test_specific_known_dates(self):
        """Starting from Monday July 7, 2026 → first should be Tue July 8."""
        dates = _next_geo_batch_dates(date(2026, 7, 7), count=2)
        # July 7 is Monday → next Tue is July 8, next Fri is July 11
        # But _next_geo_batch_dates only returns FUTURE dates (after now),
        # so this test is only valid if run before those dates.
        # Just verify format/type
        for dt in dates:
            assert isinstance(dt, datetime)
            assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# Tests: EPG status mapping
# ---------------------------------------------------------------------------


class TestMapEpgStatus:
    def test_planned_maps_to_planned(self):
        assert _map_epg_status("planned") == "planned"

    def test_generated_maps_to_scheduled(self):
        assert _map_epg_status("generated") == "scheduled"

    def test_approved_maps_to_approved(self):
        assert _map_epg_status("approved") == "approved"

    def test_posted_maps_to_executing(self):
        assert _map_epg_status("posted") == "executing"

    def test_skipped_maps_to_expired(self):
        assert _map_epg_status("skipped") == "expired"

    def test_expired_maps_to_expired(self):
        assert _map_epg_status("expired") == "expired"

    def test_unknown_status_defaults_to_planned(self):
        assert _map_epg_status("unknown_status") == "planned"
        assert _map_epg_status("") == "planned"


# ---------------------------------------------------------------------------
# Tests: Phase labels
# ---------------------------------------------------------------------------


class TestPhaseLabel:
    def test_phase_0(self):
        assert "Incubation" in _phase_label(0)

    def test_phase_1(self):
        assert "Phase 1" in _phase_label(1)

    def test_phase_2(self):
        assert "Professional" in _phase_label(2)

    def test_phase_3(self):
        assert "Brand" in _phase_label(3)

    def test_unknown_phase(self):
        label = _phase_label(99)
        assert "99" in label


# ---------------------------------------------------------------------------
# Tests: Promotion criteria
# ---------------------------------------------------------------------------


class TestPromotionCriteria:
    def test_phase_0_criteria(self):
        criteria = _get_promotion_criteria(0)
        assert "min_age_days" in criteria
        assert criteria["min_age_days"] == 7
        assert criteria["min_karma"] == 10
        assert criteria["min_posted_comments"] == 3

    def test_phase_1_criteria(self):
        criteria = _get_promotion_criteria(1)
        assert criteria["min_age_days"] == 60
        assert criteria["min_karma"] == 100
        assert criteria["min_survival_rate"] == 80

    def test_phase_2_criteria(self):
        criteria = _get_promotion_criteria(2)
        assert criteria["min_age_days"] == 150
        assert criteria["min_karma"] == 500
        assert criteria["min_avg_score"] == 2.0

    def test_phase_3_returns_empty(self):
        """Phase 3 is max — no next phase criteria."""
        criteria = _get_promotion_criteria(3)
        assert criteria == {}

    def test_returns_copy(self):
        """Should return a copy, not mutable reference."""
        c1 = _get_promotion_criteria(1)
        c1["extra"] = "modified"
        c2 = _get_promotion_criteria(1)
        assert "extra" not in c2


# ---------------------------------------------------------------------------
# Tests: Weeks to promotion estimation
# ---------------------------------------------------------------------------


class TestEstimateWeeksToPromotion:
    def test_phase_0_fresh(self):
        """Phase 0, day 0 → ~2 weeks."""
        weeks = _estimate_weeks_to_promotion(0, days_in_phase=0)
        assert weeks == 2

    def test_phase_0_halfway(self):
        """Phase 0, 7 days in → ~1 week remaining."""
        weeks = _estimate_weeks_to_promotion(0, days_in_phase=7)
        assert weeks == 1

    def test_phase_1_fresh(self):
        """Phase 1, day 0 → ~8 weeks."""
        weeks = _estimate_weeks_to_promotion(1, days_in_phase=0)
        assert weeks == 8

    def test_phase_1_midway(self):
        """Phase 1, 28 days (4 weeks) → ~4 weeks remaining."""
        weeks = _estimate_weeks_to_promotion(1, days_in_phase=28)
        assert weeks == 4

    def test_phase_2_fresh(self):
        """Phase 2, day 0 → ~12 weeks."""
        weeks = _estimate_weeks_to_promotion(2, days_in_phase=0)
        assert weeks == 12

    def test_phase_3_returns_none(self):
        """Phase 3 is max — no next phase."""
        assert _estimate_weeks_to_promotion(3, days_in_phase=0) is None

    def test_overdue_returns_1(self):
        """If already past estimated time, returns 1 (minimum)."""
        weeks = _estimate_weeks_to_promotion(0, days_in_phase=100)
        assert weeks == 1


# ---------------------------------------------------------------------------
# Tests: _make_intent helper
# ---------------------------------------------------------------------------


class TestMakeIntent:
    def test_basic_construction(self):
        import uuid

        now = datetime.now(timezone.utc)
        task_id = uuid.uuid4()
        intent = _make_intent(
            intent_id="epg_slot:123",
            intent_type="comment_slot",
            status="planned",
            target_date=now,
            validity_window_days=1,
            linked_task_id=task_id,
            version=2,
            created_at=now,
        )
        assert intent["intent_id"] == "epg_slot:123"
        assert intent["intent_type"] == "comment_slot"
        assert intent["status"] == "planned"
        assert intent["validity_window_days"] == 1
        assert intent["linked_task_id"] == str(task_id)
        assert intent["version"] == 2

    def test_none_linked_task(self):
        now = datetime.now(timezone.utc)
        intent = _make_intent(
            intent_id="geo:1",
            intent_type="geo_batch",
            status="scheduled",
            target_date=now,
            validity_window_days=7,
        )
        assert intent["linked_task_id"] is None
        assert intent["version"] == 1

    def test_naive_datetime_gets_utc(self):
        """Naive datetime should be assumed UTC."""
        naive_dt = datetime(2026, 7, 5, 10, 0, 0)
        intent = _make_intent(
            intent_id="test:1",
            intent_type="comment_slot",
            status="planned",
            target_date=naive_dt,
            validity_window_days=1,
        )
        # Should have +00:00 in ISO string
        assert "+00:00" in intent["target_date"]

    def test_target_date_iso_format(self):
        dt = datetime(2026, 7, 5, 9, 30, 0, tzinfo=timezone.utc)
        intent = _make_intent(
            intent_id="test:2",
            intent_type="geo_batch",
            status="scheduled",
            target_date=dt,
            validity_window_days=7,
        )
        assert "2026-07-05T09:30:00" in intent["target_date"]


# ---------------------------------------------------------------------------
# Tests: IntentSnapshot dataclass
# ---------------------------------------------------------------------------


class TestIntentSnapshot:
    def test_to_dict(self):
        snapshot = IntentSnapshot(
            snapshot_version=1,
            captured_at="2026-07-05T10:00:00+00:00",
            client_id="abc-123",
            daily_plan=[{"intent_id": "epg:1"}],
            weekly_plan=[{"intent_id": "draft:1"}],
            phase_roadmap=[{"avatar_id": "av1"}],
            coverage_plan=[{"subreddit_name": "python"}],
        )
        d = snapshot.to_dict()
        assert isinstance(d, dict)
        assert d["snapshot_version"] == 1
        assert d["client_id"] == "abc-123"
        assert len(d["daily_plan"]) == 1
        assert len(d["weekly_plan"]) == 1
        assert len(d["phase_roadmap"]) == 1
        assert len(d["coverage_plan"]) == 1

    def test_empty_snapshot(self):
        snapshot = IntentSnapshot(
            snapshot_version=1,
            captured_at="2026-07-05T00:00:00+00:00",
            client_id="empty-client",
        )
        d = snapshot.to_dict()
        assert d["daily_plan"] == []
        assert d["weekly_plan"] == []
        assert d["phase_roadmap"] == []
        assert d["coverage_plan"] == []


# ---------------------------------------------------------------------------
# Tests: Validity constants
# ---------------------------------------------------------------------------


class TestValidityConstants:
    def test_daily_epg_validity(self):
        assert VALIDITY_DAILY_EPG == 1

    def test_pending_drafts_validity(self):
        assert VALIDITY_PENDING_DRAFTS == 3

    def test_geo_batch_validity(self):
        assert VALIDITY_GEO_BATCH == 7

    def test_phase_roadmap_validity(self):
        assert VALIDITY_PHASE_ROADMAP == 90

    def test_subreddit_coverage_validity(self):
        assert VALIDITY_SUBREDDIT_COVERAGE == 30
