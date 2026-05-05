"""In-memory metrics collector for Reddit and LLM API observability.

Captures structured log events emitted by ``app.services.reddit`` (and PRAW
rate limit logs) inside the FastAPI process. The collector is a thread-safe
singleton accessed via ``get_metrics_collector()``.

Note: Celery worker processes are isolated and their logs do NOT reach this
collector. Long-window aggregation for Reddit/LLM metrics happens via DB
queries against ``scrape_log`` and ``ai_usage_log`` (see ``health_metrics``).
The collector is the source of truth only for PRAW rate-limit data captured
during health-check API calls performed inside the FastAPI process.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# Pattern emitted by reddit.py::_log_rate_limit:
#   "Reddit rate limit status | remaining=X | used=Y | reset_ts=Z"
_RATE_LIMIT_RE = re.compile(
    r"Reddit rate limit status \| remaining=(?P<remaining>[^|]+) \| "
    r"used=(?P<used>[^|]+) \| reset_ts=(?P<reset_ts>\S+)"
)


@dataclass
class RateLimitState:
    """Snapshot of Reddit API rate limit captured from PRAW."""

    remaining: Optional[int] = None
    used: Optional[int] = None
    reset_timestamp: Optional[float] = None
    captured_at: Optional[datetime] = None

    @property
    def status(self) -> str:
        if self.remaining is None:
            return "unknown"
        if self.remaining < 5:
            return "critical"
        if self.remaining < 20:
            return "warning"
        return "ok"

    @property
    def usage_pct(self) -> Optional[float]:
        if self.used is None or self.remaining is None:
            return None
        total = self.used + self.remaining
        if total == 0:
            return 0.0
        return (self.used / total) * 100

    @property
    def seconds_until_reset(self) -> Optional[int]:
        if self.reset_timestamp is None:
            return None
        delta = self.reset_timestamp - datetime.now(timezone.utc).timestamp()
        return max(0, int(delta))

    def to_dict(self) -> dict:
        return {
            "remaining": self.remaining,
            "used": self.used,
            "reset_timestamp": self.reset_timestamp,
            "seconds_until_reset": self.seconds_until_reset,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
            "status": self.status,
            "usage_pct": self.usage_pct,
        }


def gauge_color(usage_pct: Optional[float]) -> str:
    """Map a usage percentage (0-100) to the gauge color name.

    Returns one of "green", "yellow", "red", or "gray" (unknown state).
    """
    if usage_pct is None:
        return "gray"
    if usage_pct < 60:
        return "green"
    if usage_pct <= 80:
        return "yellow"
    return "red"


class MetricsCollector:
    """Thread-safe in-memory rate-limit tracker.

    The collector intentionally only stores the most recent rate-limit
    snapshot. Time-windowed Reddit/LLM aggregation lives in the DB-backed
    ``health_metrics`` service so multi-process workers contribute too.
    """

    def __init__(self, window_minutes: int = 60) -> None:
        self._lock = threading.Lock()
        self._rate_limit: RateLimitState = RateLimitState()
        self._window_minutes = max(1, int(window_minutes))

    def record_rate_limit(
        self,
        remaining: Optional[int],
        used: Optional[int],
        reset_ts: Optional[float],
    ) -> None:
        with self._lock:
            self._rate_limit = RateLimitState(
                remaining=remaining,
                used=used,
                reset_timestamp=reset_ts,
                captured_at=datetime.now(timezone.utc),
            )

    def get_rate_limit(self) -> RateLimitState:
        with self._lock:
            rl = self._rate_limit
            return RateLimitState(
                remaining=rl.remaining,
                used=rl.used,
                reset_timestamp=rl.reset_timestamp,
                captured_at=rl.captured_at,
            )

    def get_window_minutes(self) -> int:
        return self._window_minutes

    def reset(self) -> None:
        """Clear the captured state. Primarily used in tests."""
        with self._lock:
            self._rate_limit = RateLimitState()


def _coerce_int(value: str) -> Optional[int]:
    value = value.strip()
    if value in ("", "?", "None"):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_float(value: str) -> Optional[float]:
    value = value.strip()
    if value in ("", "?", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_rate_limit_message(message: str) -> Optional[dict]:
    """Parse the structured rate limit log line. Returns ``None`` on failure."""
    match = _RATE_LIMIT_RE.search(message)
    if not match:
        return None
    return {
        "remaining": _coerce_int(match.group("remaining")),
        "used": _coerce_int(match.group("used")),
        "reset_ts": _coerce_float(match.group("reset_ts")),
    }


class MetricsLoggingHandler(logging.Handler):
    """Logging handler that feeds rate-limit events into the collector."""

    def __init__(self, collector: MetricsCollector) -> None:
        super().__init__()
        self.collector = collector

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            return

        if "Reddit rate limit status" not in message:
            return

        parsed = parse_rate_limit_message(message)
        if not parsed:
            return

        try:
            self.collector.record_rate_limit(
                remaining=parsed["remaining"],
                used=parsed["used"],
                reset_ts=parsed["reset_ts"],
            )
        except Exception:
            # Never propagate exceptions out of a logging handler.
            return


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_collector: Optional[MetricsCollector] = None
_handler: Optional[MetricsLoggingHandler] = None
_init_lock = threading.Lock()


def get_metrics_collector(window_minutes: int = 60) -> MetricsCollector:
    """Return the process-wide MetricsCollector, creating it on first use."""
    global _collector
    if _collector is None:
        with _init_lock:
            if _collector is None:
                _collector = MetricsCollector(window_minutes=window_minutes)
    return _collector


def install_metrics_logging_handler(
    collector: Optional[MetricsCollector] = None,
) -> MetricsLoggingHandler:
    """Attach a MetricsLoggingHandler to the root logger (idempotent)."""
    global _handler
    with _init_lock:
        if _handler is not None:
            return _handler
        target = collector or get_metrics_collector()
        handler = MetricsLoggingHandler(target)
        handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(handler)
        _handler = handler
        return handler
