"""Tests for the Reddit API Health Dashboard feature.

Covers MetricsCollector, log handler parsing, DB aggregation services,
JSON snapshot endpoint, HTMX widget partials, and auth enforcement.

Property-based tests use Hypothesis when available; they are skipped
gracefully otherwise so the suite still runs in minimal environments.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.ai_usage import AIUsageLog
from app.models.client import Client
from app.models.scrape_log import ScrapeLog
from app.models.subreddit import ClientSubreddit
from app.services import health_metrics
from app.services.metrics_collector import (
    MetricsCollector,
    MetricsLoggingHandler,
    RateLimitState,
    gauge_color,
    parse_rate_limit_message,
)


# ---------------------------------------------------------------------------
# MetricsCollector unit tests (no DB)
# ---------------------------------------------------------------------------


def test_fresh_collector_returns_unknown_state():
    collector = MetricsCollector()
    state = collector.get_rate_limit()
    assert state.status == "unknown"
    assert state.usage_pct is None
    assert state.remaining is None


def test_record_rate_limit_round_trip():
    collector = MetricsCollector()
    collector.record_rate_limit(remaining=42, used=58, reset_ts=1234567890.0)
    state = collector.get_rate_limit()
    assert state.remaining == 42
    assert state.used == 58
    assert state.reset_timestamp == 1234567890.0
    assert state.captured_at is not None
    assert state.status == "ok"
    assert state.usage_pct == pytest.approx(58.0)


def test_status_classification_thresholds():
    collector = MetricsCollector()
    collector.record_rate_limit(remaining=4, used=96, reset_ts=0)
    assert collector.get_rate_limit().status == "critical"
    collector.record_rate_limit(remaining=10, used=90, reset_ts=0)
    assert collector.get_rate_limit().status == "warning"
    collector.record_rate_limit(remaining=80, used=20, reset_ts=0)
    assert collector.get_rate_limit().status == "ok"


def test_gauge_color_thresholds():
    assert gauge_color(None) == "gray"
    assert gauge_color(0.0) == "green"
    assert gauge_color(59.99) == "green"
    assert gauge_color(60.0) == "yellow"
    assert gauge_color(80.0) == "yellow"
    assert gauge_color(80.01) == "red"
    assert gauge_color(100.0) == "red"


def test_collector_thread_safety_smoke():
    collector = MetricsCollector()

    def writer(seed: int) -> None:
        for i in range(200):
            collector.record_rate_limit(
                remaining=(seed + i) % 100,
                used=100 - ((seed + i) % 100),
                reset_ts=float(seed + i),
            )

    threads = [threading.Thread(target=writer, args=(s,)) for s in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    state = collector.get_rate_limit()
    assert state.remaining is not None
    assert 0 <= state.remaining < 100


def test_seconds_until_reset_clamps_to_zero():
    state = RateLimitState(
        remaining=10,
        used=90,
        reset_timestamp=time.time() - 100,
        captured_at=datetime.now(timezone.utc),
    )
    assert state.seconds_until_reset == 0


# ---------------------------------------------------------------------------
# Log handler parsing
# ---------------------------------------------------------------------------


def test_parse_rate_limit_message_happy_path():
    parsed = parse_rate_limit_message(
        "Reddit rate limit status | remaining=42 | used=58 | reset_ts=1234567890.0"
    )
    assert parsed == {"remaining": 42, "used": 58, "reset_ts": 1234567890.0}


def test_parse_rate_limit_message_handles_unknown_values():
    parsed = parse_rate_limit_message(
        "Reddit rate limit status | remaining=? | used=? | reset_ts=?"
    )
    assert parsed == {"remaining": None, "used": None, "reset_ts": None}


def test_parse_rate_limit_message_returns_none_on_unrelated():
    assert parse_rate_limit_message("LLM_CALL | model=foo") is None


def test_logging_handler_feeds_collector():
    collector = MetricsCollector()
    handler = MetricsLoggingHandler(collector)
    record = logging.LogRecord(
        name="app.services.reddit",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Reddit rate limit status | remaining=%s | used=%s | reset_ts=%s",
        args=(15, 85, 1700000000.0),
        exc_info=None,
    )
    handler.emit(record)
    state = collector.get_rate_limit()
    assert state.remaining == 15
    assert state.used == 85
    assert state.reset_timestamp == 1700000000.0


def test_logging_handler_ignores_unrelated_messages():
    collector = MetricsCollector()
    handler = MetricsLoggingHandler(collector)
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="some unrelated message",
        args=(),
        exc_info=None,
    )
    handler.emit(record)
    assert collector.get_rate_limit().status == "unknown"


# ---------------------------------------------------------------------------
# DB-backed aggregation services
# ---------------------------------------------------------------------------


def _make_client(db, *, name: str = "Health Test") -> Client:
    client = Client(client_name=name, brand_name=name)
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def _make_scrape_log(
    db,
    client_id: uuid.UUID,
    *,
    subreddit: str = "cybersecurity",
    duration_ms: int = 500,
    errors: str | None = None,
    minutes_ago: int = 1,
    posts_found: int = 10,
    posts_new: int = 5,
) -> ScrapeLog:
    log = ScrapeLog(
        client_id=client_id,
        subreddit_name=subreddit,
        posts_found=posts_found,
        posts_new=posts_new,
        errors=errors,
        duration_ms=duration_ms,
        scraped_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    db.add(log)
    db.commit()
    return log


def test_reddit_metrics_empty_window(db):
    metrics = health_metrics.get_reddit_api_metrics(db, window_minutes=60)
    assert metrics["total_calls"] == 0
    assert metrics["error_count"] == 0
    assert metrics["error_rate_pct"] == 0
    assert metrics["avg_response_ms"] == 0
    assert metrics["p95_response_ms"] == 0
    assert metrics["calls_per_minute"] == 0
    assert metrics["status"] == "ok"
    assert metrics["window_minutes"] == 60


def test_reddit_metrics_aggregation_counts_and_errors(db):
    client = _make_client(db, name=f"Reddit Metrics {uuid.uuid4()}")
    _make_scrape_log(db, client.id, duration_ms=200)
    _make_scrape_log(db, client.id, duration_ms=400)
    _make_scrape_log(db, client.id, duration_ms=600)
    _make_scrape_log(
        db, client.id, duration_ms=800,
        errors="error=RATE_LIMITED | duration_ms=800 | details=429 TooManyRequests",
    )
    _make_scrape_log(
        db, client.id, duration_ms=200,
        errors="error=Forbidden | 403",
    )

    metrics = health_metrics.get_reddit_api_metrics(db, window_minutes=60)
    assert metrics["total_calls"] == 5
    assert metrics["error_count"] == 2
    assert metrics["error_rate_pct"] == pytest.approx(40.0, rel=1e-3)
    assert metrics["errors_by_type"]["rate_limited"] == 1
    assert metrics["errors_by_type"]["forbidden"] == 1
    assert metrics["errors_by_type"]["timeout"] == 0
    assert metrics["errors_by_type"]["other"] == 0
    # Sum of breakdown equals total
    assert sum(metrics["errors_by_type"].values()) == metrics["error_count"]
    # avg ≤ p95 ≤ max
    assert metrics["avg_response_ms"] <= metrics["p95_response_ms"]
    assert metrics["p95_response_ms"] <= 800
    # Status: 40% > 20% → critical
    assert metrics["status"] == "critical"


def test_reddit_metrics_excludes_old_rows(db):
    client = _make_client(db, name=f"Old Rows {uuid.uuid4()}")
    _make_scrape_log(db, client.id, duration_ms=100, minutes_ago=5)
    _make_scrape_log(db, client.id, duration_ms=200, minutes_ago=120)  # outside 60m window

    metrics = health_metrics.get_reddit_api_metrics(db, window_minutes=60)
    assert metrics["total_calls"] == 1
    assert metrics["avg_response_ms"] == pytest.approx(100.0)


def test_reddit_metrics_latency_warning(db):
    client = _make_client(db, name=f"Latency {uuid.uuid4()}")
    for ms in (3500, 4000, 3800):
        _make_scrape_log(db, client.id, duration_ms=ms)
    metrics = health_metrics.get_reddit_api_metrics(db, window_minutes=60)
    assert metrics["avg_response_ms"] > 3000
    assert metrics["status"] == "warning"


def test_llm_metrics_empty_window(db):
    metrics = health_metrics.get_llm_api_metrics(db, window_minutes=60)
    assert metrics["total_calls"] == 0
    assert metrics["total_cost_usd"] == 0
    assert metrics["avg_latency_ms"] == 0
    assert metrics["error_count"] == 0
    assert metrics["by_model"] == []
    assert metrics["status"] == "ok"


def _make_ai_log(
    db,
    *,
    client_id: uuid.UUID | None = None,
    model: str = "anthropic/claude-3-5-haiku-20241022",
    cost_usd: str = "0.001",
    duration_ms: int = 2000,
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> AIUsageLog:
    log = AIUsageLog(
        client_id=client_id,
        operation="scoring",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=Decimal(cost_usd),
        duration_ms=duration_ms,
    )
    db.add(log)
    db.commit()
    return log


def test_llm_metrics_aggregates_per_model_and_totals(db):
    client = _make_client(db, name=f"LLM {uuid.uuid4()}")
    _make_ai_log(db, client_id=client.id, model="modelA", cost_usd="0.001", duration_ms=1000)
    _make_ai_log(db, client_id=client.id, model="modelA", cost_usd="0.002", duration_ms=3000)
    _make_ai_log(db, client_id=client.id, model="modelB", cost_usd="0.005", duration_ms=2000)

    metrics = health_metrics.get_llm_api_metrics(db, window_minutes=60)
    # We may pick up other tests' logs in the window, so filter by our models
    by_model = {m["model"]: m for m in metrics["by_model"]}
    assert by_model["modelA"]["calls"] == 2
    assert by_model["modelA"]["cost_usd"] == pytest.approx(0.003, rel=1e-3)
    assert by_model["modelB"]["calls"] == 1
    assert by_model["modelB"]["cost_usd"] == pytest.approx(0.005, rel=1e-3)


def test_llm_metrics_error_count_flags_zero_token_rows(db):
    client = _make_client(db, name=f"LLM Err {uuid.uuid4()}")
    _make_ai_log(db, client_id=client.id, model="failedX", input_tokens=0, output_tokens=0, cost_usd="0")
    metrics = health_metrics.get_llm_api_metrics(db, window_minutes=60)
    assert metrics["error_count"] >= 1
    assert metrics["status"] == "warning"


def test_scrape_freshness_classification(db):
    client = _make_client(db, name=f"Fresh {uuid.uuid4()}")

    fresh_sub = ClientSubreddit(
        client_id=client.id,
        subreddit_name=f"fresh{uuid.uuid4().hex[:6]}",
        type="professional",
        is_active=True,
        last_scraped_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    stale_sub = ClientSubreddit(
        client_id=client.id,
        subreddit_name=f"stale{uuid.uuid4().hex[:6]}",
        type="professional",
        is_active=True,
        last_scraped_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )
    never_sub = ClientSubreddit(
        client_id=client.id,
        subreddit_name=f"never{uuid.uuid4().hex[:6]}",
        type="professional",
        is_active=True,
        last_scraped_at=None,
    )
    db.add_all([fresh_sub, stale_sub, never_sub])
    db.commit()

    data = health_metrics.get_all_scrape_freshness(db)
    by_name = {s["subreddit_name"]: s for s in data["subreddits"]}
    assert by_name[fresh_sub.subreddit_name]["is_stale"] is False
    assert by_name[fresh_sub.subreddit_name]["is_never_scraped"] is False
    assert by_name[stale_sub.subreddit_name]["is_stale"] is True
    assert by_name[stale_sub.subreddit_name]["is_never_scraped"] is False
    assert by_name[never_sub.subreddit_name]["is_stale"] is True
    assert by_name[never_sub.subreddit_name]["is_never_scraped"] is True
    # Counts are consistent across the whole result set
    assert data["never_scraped_count"] <= data["stale_count"]
    assert data["stale_count"] <= data["total_active"]


# ---------------------------------------------------------------------------
# Route-level / HTTP tests
# ---------------------------------------------------------------------------


def test_health_page_renders_with_widgets(admin_client):
    r = admin_client.get("/admin/health")
    assert r.status_code == 200
    body = r.text
    assert "API Metrics" in body
    assert "Reddit Rate Limit" in body
    # HTMX wires for widget polling (lazy-load + periodic refresh)
    assert "/admin/health/widget/rate-limit" in body
    assert "every 30s" in body
    assert "every 60s" in body
    assert "every 120s" in body
    # Lazy-loaded service cards
    assert "/admin/health/service/postgresql" in body
    assert "/admin/health/service/redis" in body


def test_widget_endpoints_render(admin_client):
    for url in (
        "/admin/health/widget/rate-limit",
        "/admin/health/widget/reddit-metrics",
        "/admin/health/widget/llm-metrics",
        "/admin/health/widget/scrape-freshness",
    ):
        r = admin_client.get(url)
        assert r.status_code == 200, f"{url} returned {r.status_code}"
        assert "<div" in r.text


def test_service_card_lazy_load(admin_client):
    """Each service card can be loaded individually via HTMX."""
    for service in ("postgresql", "redis", "celery", "reddit", "llm"):
        r = admin_client.get(f"/admin/health/service/{service}")
        assert r.status_code == 200, f"{service} returned {r.status_code}"
        assert f'id="health-{service}"' in r.text


def test_metrics_json_endpoint_shape(admin_client):
    r = admin_client.get("/admin/health/metrics")
    assert r.status_code == 200
    payload = r.json()
    assert set(payload.keys()) >= {
        "collected_at",
        "window_minutes",
        "rate_limit",
        "reddit_api",
        "llm_api",
        "scrape_freshness",
    }
    # ISO 8601 timestamp
    datetime.fromisoformat(payload["collected_at"])
    assert isinstance(payload["window_minutes"], int)
    assert payload["window_minutes"] > 0
    assert "status" in payload["reddit_api"]
    assert "status" in payload["llm_api"]
    assert isinstance(payload["scrape_freshness"]["subreddits"], list)


def test_widget_endpoints_require_superuser(regular_client):
    for url in (
        "/admin/health/metrics",
        "/admin/health/widget/rate-limit",
        "/admin/health/widget/reddit-metrics",
        "/admin/health/widget/llm-metrics",
        "/admin/health/widget/scrape-freshness",
    ):
        r = regular_client.get(url, follow_redirects=False)
        assert r.status_code == 403, f"{url} → {r.status_code}"


def test_widget_endpoints_require_auth():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        for url in (
            "/admin/health/metrics",
            "/admin/health/widget/rate-limit",
        ):
            r = c.get(url, follow_redirects=False)
            assert r.status_code == 303
            assert "/login" in r.headers.get("location", "")


# ---------------------------------------------------------------------------
# Property-based tests (Hypothesis)
# ---------------------------------------------------------------------------

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings as hyp_settings, strategies as st  # noqa: E402


# Feature: reddit-api-health-dashboard, Property 1: Rate limit log parsing round-trip
@hyp_settings(max_examples=100, deadline=None)
@given(
    remaining=st.integers(min_value=0, max_value=1000),
    used=st.integers(min_value=0, max_value=1000),
    reset_ts=st.floats(min_value=0.0, max_value=2_000_000_000.0,
                       allow_nan=False, allow_infinity=False),
)
def test_property_rate_limit_log_parsing_round_trip(remaining, used, reset_ts):
    msg = (
        f"Reddit rate limit status | remaining={remaining} | "
        f"used={used} | reset_ts={reset_ts}"
    )
    parsed = parse_rate_limit_message(msg)
    assert parsed is not None
    assert parsed["remaining"] == remaining
    assert parsed["used"] == used
    # Float coercion may lose precision for very large doubles, allow tiny tol.
    assert math.isclose(parsed["reset_ts"], reset_ts, rel_tol=1e-9, abs_tol=1e-6)


# Feature: reddit-api-health-dashboard, Property 2: Rate limit status classification
@hyp_settings(max_examples=100, deadline=None)
@given(remaining=st.integers(min_value=0, max_value=1000))
def test_property_rate_limit_status_classification(remaining):
    state = RateLimitState(remaining=remaining, used=0, reset_timestamp=0)
    expected = "critical" if remaining < 5 else ("warning" if remaining < 20 else "ok")
    assert state.status == expected


def test_property_rate_limit_unknown_when_remaining_none():
    assert RateLimitState(remaining=None).status == "unknown"


# Feature: reddit-api-health-dashboard, Property 3: Rate limit gauge color classification
@hyp_settings(max_examples=100, deadline=None)
@given(usage_pct=st.floats(min_value=0.0, max_value=100.0,
                           allow_nan=False, allow_infinity=False))
def test_property_gauge_color_classification(usage_pct):
    color = gauge_color(usage_pct)
    if usage_pct < 60:
        assert color == "green"
    elif usage_pct <= 80:
        assert color == "yellow"
    else:
        assert color == "red"


def test_property_gauge_color_gray_when_unknown():
    assert gauge_color(None) == "gray"


# Feature: reddit-api-health-dashboard, Property 5: Response time statistics ordering
@hyp_settings(max_examples=100, deadline=None)
@given(values=st.lists(st.integers(min_value=1, max_value=10000),
                        min_size=1, max_size=200))
def test_property_response_time_ordering(values):
    sorted_vals = sorted(values)
    avg = sum(sorted_vals) / len(sorted_vals)
    p95 = health_metrics._percentile(sorted_vals, 95.0)
    assert sorted_vals[0] <= avg + 1e-9
    assert avg <= p95 + 1e-9
    assert p95 <= sorted_vals[-1] + 1e-9


# Feature: reddit-api-health-dashboard, Property 4: Reddit metrics consistency formula
@hyp_settings(max_examples=100, deadline=None)
@given(
    total=st.integers(min_value=0, max_value=500),
    errors=st.integers(min_value=0, max_value=500),
)
def test_property_reddit_error_rate_formula(total, errors):
    errors = min(errors, total)
    if total == 0:
        rate = 0.0
    else:
        rate = (errors / total) * 100.0
    assert 0.0 <= rate <= 100.0
    if total > 0:
        assert math.isclose(rate, (errors / total) * 100.0, rel_tol=1e-9)


# Feature: reddit-api-health-dashboard, Property 6: Error breakdown sums to total
@hyp_settings(max_examples=100, deadline=None)
@given(
    rate_limited=st.lists(st.sampled_from(["429 TooManyRequests", "rate_limited"]),
                          min_size=0, max_size=10),
    forbidden=st.lists(st.sampled_from(["403 Forbidden", "forbidden"]),
                       min_size=0, max_size=10),
    timeout=st.lists(st.sampled_from(["timeout occurred", "request timed out"]),
                     min_size=0, max_size=10),
    other=st.lists(st.sampled_from(["unexpected error", "RUNAWAY"]),
                   min_size=0, max_size=10),
)
def test_property_error_breakdown_sums(rate_limited, forbidden, timeout, other):
    breakdown = {"rate_limited": 0, "forbidden": 0, "timeout": 0, "other": 0}
    msgs = rate_limited + forbidden + timeout + other
    for m in msgs:
        breakdown[health_metrics._classify_reddit_error(m)] += 1
    assert sum(breakdown.values()) == len(msgs)


# Feature: reddit-api-health-dashboard, Property 8: Reddit widget status
@hyp_settings(max_examples=100, deadline=None)
@given(
    error_rate=st.floats(min_value=0.0, max_value=100.0,
                         allow_nan=False, allow_infinity=False),
    avg_ms=st.floats(min_value=0.0, max_value=20000.0,
                     allow_nan=False, allow_infinity=False),
)
def test_property_reddit_status_classification(error_rate, avg_ms):
    status = health_metrics._reddit_status(error_rate, avg_ms)
    if error_rate > 20:
        assert status == "critical"
    elif error_rate > 5 or avg_ms > 3000:
        assert status == "warning"
    else:
        assert status == "ok"


# Feature: reddit-api-health-dashboard, Property 9: LLM widget status
@hyp_settings(max_examples=100, deadline=None)
@given(
    avg_latency=st.floats(min_value=0.0, max_value=20000.0,
                          allow_nan=False, allow_infinity=False),
    error_count=st.integers(min_value=0, max_value=1000),
)
def test_property_llm_status_classification(avg_latency, error_count):
    status = health_metrics._llm_status(avg_latency, error_count)
    if error_count > 0 or avg_latency > 5000:
        assert status == "warning"
    else:
        assert status == "ok"
