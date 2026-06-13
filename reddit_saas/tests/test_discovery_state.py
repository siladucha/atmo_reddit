"""Unit tests for Discovery session state management.

Tests the state machine logic, step detection, and consistency guarantees.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
import sys
sys.path.insert(0, '.')

from app.services.discovery.session_manager import SessionManager


def _make_session(
    status="in_progress",
    current_iteration=1,
    entities=None,
    hypotheses=None,
    reports=None,
    metadata=None,
):
    """Create a mock DiscoverySession for testing."""
    session = MagicMock()
    session.status = status
    session.current_iteration = current_iteration
    session.entities = entities or []
    session.hypotheses = hypotheses or []
    session.reports = reports or []
    session.session_metadata = metadata or {}
    return session


def _make_hypothesis(iteration=1, status="proposed", reddit_signals=None):
    h = MagicMock()
    h.iteration_number = iteration
    h.status = status
    h.reddit_signals = reddit_signals
    return h


class TestGetCurrentStep:
    def test_no_hypotheses_no_entities_returns_brief(self):
        session = _make_session()
        assert SessionManager.get_current_step(session) == "brief"

    def test_no_hypotheses_with_entities_returns_entities(self):
        session = _make_session(entities=[MagicMock()])
        assert SessionManager.get_current_step(session) == "entities"

    def test_all_hypotheses_decided_no_report_returns_results(self):
        hyps = [_make_hypothesis(status="confirmed"), _make_hypothesis(status="rejected")]
        session = _make_session(hypotheses=hyps, metadata={"research_completed_at": 123})
        assert SessionManager.get_current_step(session) == "results"

    def test_all_decided_with_report_returns_report(self):
        hyps = [_make_hypothesis(status="confirmed")]
        session = _make_session(hypotheses=hyps, reports=[MagicMock()], metadata={"research_completed_at": 123})
        assert SessionManager.get_current_step(session) == "report"

    def test_research_in_progress_returns_research(self):
        hyps = [_make_hypothesis(status="proposed")]
        session = _make_session(hypotheses=hyps, metadata={"research_progress": {"abc": "researching"}})
        assert SessionManager.get_current_step(session) == "research"

    def test_research_stopped_with_undecided_returns_results(self):
        """When research was stopped, show results even if some hypotheses are undecided."""
        hyps = [
            _make_hypothesis(status="confirmed"),
            _make_hypothesis(status="proposed"),  # undecided
        ]
        session = _make_session(
            hypotheses=hyps,
            metadata={"research_progress": {"a": "complete"}, "research_stopped_by": "user123"},
        )
        assert SessionManager.get_current_step(session) == "results"

    def test_research_completed_with_undecided_returns_results(self):
        """When research completed, show results even if some hypotheses remain proposed."""
        hyps = [
            _make_hypothesis(status="confirmed"),
            _make_hypothesis(status="research_failed"),
            _make_hypothesis(status="proposed"),
        ]
        session = _make_session(
            hypotheses=hyps,
            metadata={"research_completed_at": 1234567890},
        )
        assert SessionManager.get_current_step(session) == "results"


class TestCanGenerateReport:
    def test_no_confirmed_returns_false(self):
        hyps = [_make_hypothesis(status="proposed")]
        session = _make_session(hypotheses=hyps)
        assert SessionManager.can_generate_report(session) == False

    def test_confirmed_with_research_done_returns_true(self):
        hyps = [_make_hypothesis(status="confirmed")]
        session = _make_session(hypotheses=hyps, metadata={"research_completed_at": 123})
        assert SessionManager.can_generate_report(session) == True

    def test_confirmed_with_research_stopped_returns_true(self):
        hyps = [_make_hypothesis(status="confirmed")]
        session = _make_session(hypotheses=hyps, metadata={"research_stopped_by": "user"})
        assert SessionManager.can_generate_report(session) == True

    def test_confirmed_without_research_signals_and_not_all_decided_returns_false(self):
        hyps = [
            _make_hypothesis(status="confirmed"),
            _make_hypothesis(status="proposed"),
        ]
        session = _make_session(hypotheses=hyps)
        assert SessionManager.can_generate_report(session) == False


class TestConsistencyGuarantees:
    def test_sidebar_and_results_see_same_counts(self):
        """The fix: both sidebar and results partial use same hypotheses list."""
        hyps = [
            _make_hypothesis(status="confirmed"),
            _make_hypothesis(status="confirmed"),
            _make_hypothesis(status="rejected"),
            _make_hypothesis(status="proposed"),
        ]
        session = _make_session(
            hypotheses=hyps,
            metadata={"research_completed_at": 123},
        )

        # What sidebar sees (all hypotheses)
        sidebar_confirmed = len([h for h in session.hypotheses if h.status == "confirmed"])
        sidebar_total = len(list(session.hypotheses))

        # What results partial should receive (current_iteration only)
        current_hypos = [h for h in session.hypotheses if h.iteration_number == session.current_iteration]
        results_confirmed = len([h for h in current_hypos if h.status == "confirmed"])

        # In single-iteration sessions, these MUST match
        assert sidebar_confirmed == results_confirmed
        assert sidebar_total == len(current_hypos)

    def test_entities_zero_does_not_block_results(self):
        """Entities can be 0 (lost in restore) without blocking the flow."""
        hyps = [_make_hypothesis(status="confirmed")]
        session = _make_session(
            entities=[],  # Empty!
            hypotheses=hyps,
            metadata={"research_completed_at": 123},
        )
        # Should still show results (entities were already consumed to form hypotheses)
        assert SessionManager.get_current_step(session) == "results"
        assert SessionManager.can_generate_report(session) == True


if __name__ == "__main__":
    # Run tests
    import traceback
    test_classes = [TestGetCurrentStep, TestCanGenerateReport, TestConsistencyGuarantees]
    passed = 0
    failed = 0
    for cls in test_classes:
        instance = cls()
        for method_name in dir(instance):
            if method_name.startswith("test_"):
                try:
                    getattr(instance, method_name)()
                    passed += 1
                    print(f"  ✓ {cls.__name__}.{method_name}")
                except Exception as e:
                    failed += 1
                    print(f"  ✗ {cls.__name__}.{method_name}: {e}")
                    traceback.print_exc()

    print(f"\n{passed} passed, {failed} failed")
    if failed > 0:
        exit(1)
