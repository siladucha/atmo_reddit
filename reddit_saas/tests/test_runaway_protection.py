import pytest
pytestmark = pytest.mark.skip(reason="Requires isolated Redis — local Redis has live counters from prod")

"""Tests for R-AI-007 — Runaway LLM Loop protection.

Verifies all 3 layers:
  Layer 1: Per-task call counter (max 50 per task)
  Layer 2: Cost-based circuit breaker ($5 per 10-min window)
  Layer 3: Spend rate alert in dashboard (DB + Redis checks)

Run: PYTHONPATH=. ../.venv/bin/python -m pytest tests/test_runaway_protection.py -v
"""

import datetime
import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
import redis


# ---------------------------------------------------------------------------
# Layer 1: Per-task call counter
# ---------------------------------------------------------------------------

class TestPerTaskCallCounter:
    """Test that a single task cannot make more than _MAX_CALLS_PER_TASK LLM calls."""

    def test_counter_starts_at_zero(self):
        from app.services.ai import _task_call_counter, reset_task_call_counter
        reset_task_call_counter()
        assert _task_call_counter.get() == 0

    def test_counter_increments_on_gate_check(self):
        from app.services.ai import (
            _task_call_counter, reset_task_call_counter, _check_llm_budget_gate
        )
        # Force Redis to None so it only tests the counter
        import app.services.ai as ai_mod
        original = ai_mod._budget_redis_client
        ai_mod._budget_redis_client = None

        try:
            reset_task_call_counter()
            _check_llm_budget_gate("test/model")
            assert _task_call_counter.get() == 1

            _check_llm_budget_gate("test/model")
            assert _task_call_counter.get() == 2
        finally:
            ai_mod._budget_redis_client = original

    def test_raises_at_limit(self):
        from app.services.ai import (
            _task_call_counter, reset_task_call_counter,
            _check_llm_budget_gate, LLMRunawayDetected, _MAX_CALLS_PER_TASK
        )
        import app.services.ai as ai_mod
        original = ai_mod._budget_redis_client
        ai_mod._budget_redis_client = None

        try:
            reset_task_call_counter()
            # Burn through all allowed calls
            for _ in range(_MAX_CALLS_PER_TASK):
                _check_llm_budget_gate("test/model")

            # Next call should raise
            with pytest.raises(LLMRunawayDetected, match="exceeded max LLM calls"):
                _check_llm_budget_gate("test/model")
        finally:
            ai_mod._budget_redis_client = original

    def test_reset_allows_new_calls(self):
        from app.services.ai import (
            _task_call_counter, reset_task_call_counter,
            _check_llm_budget_gate, _MAX_CALLS_PER_TASK
        )
        import app.services.ai as ai_mod
        original = ai_mod._budget_redis_client
        ai_mod._budget_redis_client = None

        try:
            reset_task_call_counter()
            for _ in range(_MAX_CALLS_PER_TASK):
                _check_llm_budget_gate("test/model")

            # Reset counter
            reset_task_call_counter()
            # Should work again
            _check_llm_budget_gate("test/model")
            assert _task_call_counter.get() == 1
        finally:
            ai_mod._budget_redis_client = original

    def test_runaway_is_subclass_of_budget_exceeded(self):
        from app.services.ai import LLMBudgetExceeded, LLMRunawayDetected
        assert issubclass(LLMRunawayDetected, LLMBudgetExceeded)


# ---------------------------------------------------------------------------
# Layer 2: Cost-based circuit breaker (requires Redis)
# ---------------------------------------------------------------------------

class TestCostCircuitBreaker:
    """Test the 10-min cost window circuit breaker."""

    @pytest.fixture(autouse=True)
    def setup_redis(self):
        """Get a live Redis connection and clean up test keys."""
        try:
            self.redis = redis.from_url("redis://localhost:6379", decode_responses=True)
            self.redis.ping()
        except Exception:
            pytest.skip("Redis not available")

        # Clean up any test keys before/after
        self._cleanup()
        yield
        self._cleanup()

    def _cleanup(self):
        """Remove test cost window keys."""
        now = datetime.datetime.now(datetime.timezone.utc)
        cost_bucket = f"{now.strftime('%Y%m%d%H')}:{now.minute // 10}"
        key = f"ramp:llm:cost:window:{cost_bucket}"
        self.redis.delete(key)

    def test_record_cost_accumulates(self):
        from app.services.ai import _record_cost_in_window, _get_budget_redis, reset_task_call_counter
        import app.services.ai as ai_mod

        # Ensure ai.py uses our local Redis
        ai_mod._budget_redis_client = self.redis

        try:
            _record_cost_in_window(1.50)
            _record_cost_in_window(0.75)

            now = datetime.datetime.now(datetime.timezone.utc)
            cost_bucket = f"{now.strftime('%Y%m%d%H')}:{now.minute // 10}"
            key = f"ramp:llm:cost:window:{cost_bucket}"
            stored = self.redis.get(key)
            assert stored is not None
            assert abs(float(stored) - 2.25) < 0.01
        finally:
            ai_mod._budget_redis_client = None

    def test_circuit_breaker_trips_at_threshold(self):
        from app.services.ai import (
            _check_llm_budget_gate, _record_cost_in_window,
            LLMRunawayDetected, _COST_WINDOW_LIMIT_USD,
            reset_task_call_counter
        )
        import app.services.ai as ai_mod
        ai_mod._budget_redis_client = self.redis

        try:
            reset_task_call_counter()

            # Simulate accumulated cost just at the threshold
            now = datetime.datetime.now(datetime.timezone.utc)
            cost_bucket = f"{now.strftime('%Y%m%d%H')}:{now.minute // 10}"
            key = f"ramp:llm:cost:window:{cost_bucket}"
            self.redis.set(key, str(_COST_WINDOW_LIMIT_USD))
            self.redis.expire(key, 900)

            # Next call should trip the breaker
            with pytest.raises(LLMRunawayDetected, match="circuit breaker tripped"):
                _check_llm_budget_gate("anthropic/claude-sonnet-4-20250514")
        finally:
            ai_mod._budget_redis_client = None

    def test_circuit_breaker_allows_below_threshold(self):
        from app.services.ai import (
            _check_llm_budget_gate, reset_task_call_counter, _COST_WINDOW_LIMIT_USD
        )
        import app.services.ai as ai_mod
        ai_mod._budget_redis_client = self.redis

        try:
            reset_task_call_counter()

            # Set cost below threshold
            now = datetime.datetime.now(datetime.timezone.utc)
            cost_bucket = f"{now.strftime('%Y%m%d%H')}:{now.minute // 10}"
            key = f"ramp:llm:cost:window:{cost_bucket}"
            self.redis.set(key, "2.50")  # well below $5
            self.redis.expire(key, 900)

            # Should NOT raise
            _check_llm_budget_gate("gemini/gemini-2.5-flash")
        finally:
            ai_mod._budget_redis_client = None

    def test_zero_cost_not_recorded(self):
        from app.services.ai import _record_cost_in_window
        import app.services.ai as ai_mod
        ai_mod._budget_redis_client = self.redis

        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            cost_bucket = f"{now.strftime('%Y%m%d%H')}:{now.minute // 10}"
            key = f"ramp:llm:cost:window:{cost_bucket}"
            self.redis.delete(key)

            _record_cost_in_window(0.0)
            _record_cost_in_window(-1.0)

            assert self.redis.get(key) is None
        finally:
            ai_mod._budget_redis_client = None


# ---------------------------------------------------------------------------
# Layer 3: Alert integration
# ---------------------------------------------------------------------------

class TestSpendRateAlert:
    """Test the alert_aggregation integration for LLM spend alerts."""

    def test_alert_function_exists_and_returns_list(self):
        from app.services.alert_aggregation import _get_llm_spend_rate_alert
        # Call with a mock DB session — should return empty list (no data)
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.scalar.return_value = 0

        result = _get_llm_spend_rate_alert(mock_db)
        assert isinstance(result, list)

    def test_alert_triggers_on_spike(self):
        """Simulate a cost spike: $10 in last hour, avg $0.50/hr."""
        from app.services.alert_aggregation import _get_llm_spend_rate_alert, Alert

        mock_db = MagicMock()

        # First query: cost in last hour = $10.00
        # Second query: cost in 7 days = $84.00 ($84 / 168 hours = $0.50/hr avg)
        mock_db.query.return_value.filter.return_value.scalar.side_effect = [
            Decimal("10.00"),  # cost last hour
            Decimal("84.00"),  # cost 7 days
        ]

        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value.redis_url = "redis://localhost:6379"
            result = _get_llm_spend_rate_alert(mock_db)

        # Should have at least the critical alert (10 > 0.50 * 3)
        critical_alerts = [a for a in result if a.severity == "critical" and a.type == "llm_spend_spike"]
        assert len(critical_alerts) >= 1
        assert "$10.00" in critical_alerts[0].message

    def test_no_alert_on_normal_spend(self):
        """Normal spend: $0.40 in last hour, avg $0.50/hr."""
        from app.services.alert_aggregation import _get_llm_spend_rate_alert

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.scalar.side_effect = [
            Decimal("0.40"),   # cost last hour
            Decimal("84.00"),  # cost 7 days (avg $0.50/hr)
        ]

        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value.redis_url = "redis://localhost:6379"
            result = _get_llm_spend_rate_alert(mock_db)

        # Filter out Redis-based alerts (which depend on actual Redis state)
        db_alerts = [a for a in result if a.type in ("llm_spend_spike", "llm_spend_elevated")]
        assert len(db_alerts) == 0


# ---------------------------------------------------------------------------
# Integration: verify reset_task_call_counter is importable from tasks
# ---------------------------------------------------------------------------

class TestTaskIntegration:
    """Verify that task files correctly import and use the counter."""

    def test_ai_pipeline_imports_reset(self):
        from app.tasks.ai_pipeline import reset_task_call_counter
        assert callable(reset_task_call_counter)

    def test_epg_can_import_reset(self):
        # EPG does a local import inside the loop, verify it resolves
        from app.services.ai import reset_task_call_counter
        assert callable(reset_task_call_counter)
