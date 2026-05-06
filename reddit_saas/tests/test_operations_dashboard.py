"""Tests for the unified Operations Dashboard at `/admin/`."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.activity_event import ActivityEvent
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.subreddit import ClientSubreddit, Subreddit
from app.models.thread import RedditThread
from app.services import operations_dashboard


# ---------------------------------------------------------------------------
# Service-layer unit tests
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded(db):
    """Seed two clients with assorted threads/drafts/subreddits/avatars/events."""
    now = datetime.now(timezone.utc)

    c1 = Client(client_name="Alpha Co", brand_name="Alpha", is_active=True)
    c2 = Client(client_name="Bravo Co", brand_name="Bravo", is_active=True)
    db.add_all([c1, c2])
    db.flush()

    # Shared subreddit registry entry (required FK for threads)
    sub = Subreddit(subreddit_name="alpha_fresh", is_active=True)
    db.add(sub)
    db.flush()

    # Subreddits — c1 has one fresh, one stale, one never-scraped
    db.add_all([
        ClientSubreddit(client_id=c1.id, subreddit_name="alpha_fresh", last_scraped_at=now - timedelta(hours=2)),
        ClientSubreddit(client_id=c1.id, subreddit_name="alpha_stale", last_scraped_at=now - timedelta(hours=48)),
        ClientSubreddit(client_id=c1.id, subreddit_name="alpha_never", last_scraped_at=None),
        ClientSubreddit(client_id=c2.id, subreddit_name="bravo_fresh", last_scraped_at=now - timedelta(hours=1)),
    ])

    # Threads in last 24h
    threads = [
        RedditThread(
            client_id=c1.id, subreddit_id=sub.id, reddit_native_id=f"t1_{i}",
            subreddit="alpha_fresh", post_title=f"post {i}",
            tag="engage" if i < 2 else None,
        ) for i in range(3)
    ]
    db.add_all(threads)

    # Avatars
    a1 = Avatar(reddit_username="a1", active=True, reddit_status="active",
                warming_phase=1, last_phase_evaluated_at=now - timedelta(days=60))
    a2 = Avatar(reddit_username="a2", active=True, reddit_status="shadowbanned",
                warming_phase=2)
    a3 = Avatar(reddit_username="a3", active=True, reddit_status="active",
                warming_phase=3)
    a4 = Avatar(reddit_username="a4", active=False, reddit_status="suspended",
                warming_phase=1)
    db.add_all([a1, a2, a3, a4])
    db.flush()

    # Comment drafts (need real thread + avatar FKs)
    db.add_all([
        CommentDraft(
            client_id=c1.id, thread_id=threads[0].id, avatar_id=a1.id, status="pending",
        ),
    ])

    # Activity events
    db.add_all([
        ActivityEvent(client_id=c1.id, event_type="scrape", message="scraped 5 posts from r/alpha"),
        ActivityEvent(client_id=c1.id, event_type="score", message="scored 3 threads"),
        ActivityEvent(client_id=c2.id, event_type="generate", message="generated 1 draft"),
        ActivityEvent(client_id=c1.id, event_type="review", message="approved a draft"),  # filtered out
    ])

    db.commit()
    return {"c1": c1, "c2": c2}


def test_top_metrics(db, seeded):
    metrics = operations_dashboard.get_top_metrics(db)
    # The test DB is shared, so assert relative bounds and presence of the
    # schedule fields rather than exact totals.
    assert metrics["total_clients"] >= 2
    assert metrics["total_avatars"] >= 3  # only `active=True` avatars counted
    assert metrics["next_run_in"]
    assert metrics["next_run_label"]
    assert metrics["pending_reviews"] >= 1


def test_client_status_cards(db, seeded):
    cards = operations_dashboard.get_client_status_cards(db)
    by_name = {c["client_name"]: c for c in cards}

    assert "Alpha Co" in by_name and "Bravo Co" in by_name
    alpha = by_name["Alpha Co"]
    assert alpha["threads_24h"] == 3
    assert alpha["scored_24h"] == 2  # two threads with tag set
    assert alpha["is_idle"] is False

    bravo = by_name["Bravo Co"]
    assert bravo["threads_24h"] == 0
    assert bravo["is_idle"] is True


def test_scrape_freshness_grouped(db, seeded):
    groups = operations_dashboard.get_scrape_freshness_grouped(db)
    by_name = {g["client_name"]: g for g in groups}
    alpha = by_name["Alpha Co"]
    assert alpha["total"] == 3
    assert alpha["stale_count"] == 2  # stale + never
    # Stale subs sorted to top within the group
    assert alpha["subreddits"][0]["is_stale"] is True
    assert alpha["subreddits"][-1]["is_stale"] is False


def test_run_history_filters_pipeline_events(db, seeded):
    events = operations_dashboard.get_run_history(db, limit=20)
    types = {e["event_type"] for e in events}
    assert types == {"scrape", "score", "generate"}
    assert all(e["since_human"] for e in events)


def test_run_history_filtered_by_client(db, seeded):
    c2_id = seeded["c2"].id
    events = operations_dashboard.get_run_history(db, client_id=c2_id)
    assert len(events) == 1
    assert events[0]["event_type"] == "generate"


def test_avatar_health_summary(db, seeded):
    summary = operations_dashboard.get_avatar_health_summary(db)
    # Shared DB — assert lower bounds on what the fixture adds, and that the
    # structure has the expected keys.
    assert summary["status_counts"]["active"] >= 2
    assert summary["status_counts"]["shadowbanned"] >= 1
    assert summary["total_active"] >= 3
    assert summary["phase_counts"]["phase_1"] >= 1
    assert summary["phase_counts"]["phase_3"] >= 1
    # a1 (60d-old eval, phase<3) and a2 (NULL eval, phase<3) are both eligible.
    assert summary["eligible_for_promotion"] >= 2


def test_schedule_display_orders_by_next_run():
    schedule = operations_dashboard.get_schedule_display()
    assert len(schedule) == 5
    # Sorted soonest-first, only the head is flagged
    assert schedule[0]["is_next"] is True
    assert all(not e["is_next"] for e in schedule[1:])


# ---------------------------------------------------------------------------
# Route smoke tests
# ---------------------------------------------------------------------------


def test_dashboard_renders_top_metrics_bar(admin_client):
    r = admin_client.get("/admin/")
    assert r.status_code == 200
    assert "Pending Reviews" in r.text
    assert "Active Clients" in r.text
    assert "Active Avatars" in r.text
    assert "Next Scheduled Run" in r.text


def test_dashboard_renders_run_all_buttons(admin_client):
    r = admin_client.get("/admin/")
    assert "/admin/dashboard/run-all/scrape" in r.text
    assert "/admin/dashboard/run-all/full-pipeline" in r.text


def test_dashboard_partial_clients(admin_client):
    r = admin_client.get("/admin/dashboard/clients")
    assert r.status_code == 200


def test_dashboard_partial_freshness(admin_client):
    r = admin_client.get("/admin/dashboard/freshness")
    assert r.status_code == 200


def test_dashboard_partial_run_history(admin_client):
    r = admin_client.get("/admin/dashboard/run-history")
    assert r.status_code == 200


def test_dashboard_partial_avatar_health(admin_client):
    r = admin_client.get("/admin/dashboard/avatar-health")
    assert r.status_code == 200
    assert "Warming Phases" in r.text


def test_dashboard_partial_schedule(admin_client):
    r = admin_client.get("/admin/dashboard/schedule")
    assert r.status_code == 200


def test_dashboard_trigger_unknown_action_returns_400(admin_client):
    # uuid is irrelevant for the validation path
    r = admin_client.post("/admin/dashboard/trigger/bogus/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 400


def test_dashboard_run_all_unknown_action_returns_400(admin_client):
    r = admin_client.post("/admin/dashboard/run-all/bogus")
    assert r.status_code == 400
