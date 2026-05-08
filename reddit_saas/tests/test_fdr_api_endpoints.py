"""FDR API endpoint regression tests.

These tests exercise the JSON/API surface that is useful for demo readiness:
auth gating, core CRUD APIs, dashboard/export APIs, review transitions, and
pipeline dispatch endpoints. External systems are mocked; no Reddit, LLM, or
Celery worker is required.
"""

import uuid

from app.models.activity_event import ActivityEvent
from app.models.ai_usage import AIUsageLog
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.post_draft import PostDraft
from app.models.subreddit import ClientSubredditAssignment, Subreddit
from app.models.thread import RedditThread


class DummyAsyncResult:
    id = "fdr-task-id"


class DummyTask:
    def delay(self, *args, **kwargs):
        return DummyAsyncResult()


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _create_client(db, name_prefix: str = "FDR") -> Client:
    client = Client(
        client_name=_unique(name_prefix),
        brand_name=_unique("Brand"),
        company_profile="FDR API endpoint test client",
        is_active=True,
    )
    db.add(client)
    db.flush()
    return client


def _create_subreddit(db, name_prefix: str = "fdrsub") -> Subreddit:
    subreddit = Subreddit(subreddit_name=_unique(name_prefix), is_active=True)
    db.add(subreddit)
    db.flush()
    return subreddit


def _create_avatar(db, client: Client, username_prefix: str = "fdr_avatar") -> Avatar:
    avatar = Avatar(
        reddit_username=_unique(username_prefix),
        client_ids=[str(client.id)],
        active=True,
        karma_comment=7,
        karma_post=3,
    )
    db.add(avatar)
    db.flush()
    return avatar


def _create_thread(db, client: Client, subreddit: Subreddit) -> RedditThread:
    thread = RedditThread(
        client_id=client.id,
        subreddit_id=subreddit.id,
        type="professional",
        reddit_native_id=_unique("t3"),
        subreddit=subreddit.subreddit_name,
        post_title="FDR test thread",
        post_body="A body for API endpoint tests",
        comments_json="[]",
        author="tester",
    )
    db.add(thread)
    db.flush()
    return thread


def _create_comment_draft(
    db,
    client: Client,
    avatar: Avatar,
    thread: RedditThread,
    status: str = "pending",
) -> CommentDraft:
    draft = CommentDraft(
        thread_id=thread.id,
        client_id=client.id,
        avatar_id=avatar.id,
        ai_draft="Original FDR draft",
        edited_draft=None,
        status=status,
    )
    db.add(draft)
    db.flush()
    return draft


def _create_post_draft(
    db,
    client: Client,
    avatar: Avatar,
    status: str = "pending",
) -> PostDraft:
    draft = PostDraft(
        client_id=client.id,
        avatar_id=avatar.id,
        subreddit="fdrsub",
        ai_title="FDR post title",
        ai_body="FDR post body",
        status=status,
    )
    db.add(draft)
    db.flush()
    return draft


def test_fdr_api_auth_gates(admin_client, regular_client):
    """Protected JSON APIs redirect anonymous users and reject non-admins."""
    admin_client.cookies.clear()

    anonymous = admin_client.get("/clients-api/", follow_redirects=False)
    assert anonymous.status_code == 303
    assert anonymous.headers["location"] == "/login"

    regular = regular_client.get("/clients-api/")
    assert regular.status_code == 403


def test_fdr_clients_api_crud_and_relationships(admin_client):
    """Client API supports CRUD plus subreddit/avatar assignment lifecycle."""
    created = admin_client.post(
        "/clients-api/",
        json={
            "client_name": _unique("FDRClient"),
            "brand_name": "FDRBrand",
            "company_profile": "Created by FDR API test",
        },
    )
    assert created.status_code == 200
    client_id = created.json()["id"]

    updated = admin_client.patch(
        f"/clients-api/{client_id}",
        json={"company_worldview": "FDR worldview"},
    )
    assert updated.status_code == 200
    assert updated.json()["company_worldview"] == "FDR worldview"

    sub_name = _unique("fdrsub")
    added_sub = admin_client.post(
        f"/clients-api/{client_id}/subreddits",
        json={"subreddit_name": sub_name, "type": "professional"},
    )
    assert added_sub.status_code == 200
    assert added_sub.json()["subreddit_name"] == sub_name

    avatar = admin_client.post(
        "/avatars-api/",
        json={"reddit_username": _unique("fdr_avatar")},
    )
    assert avatar.status_code == 200
    avatar_id = avatar.json()["id"]

    assigned = admin_client.post(f"/clients-api/{client_id}/avatars/{avatar_id}")
    assert assigned.status_code == 200
    assert assigned.json()["status"] == "assigned"

    detail = admin_client.get(f"/clients-api/{client_id}")
    assert detail.status_code == 200
    detail_json = detail.json()
    assert detail_json["client"]["id"] == client_id
    assert any(a["id"] == avatar_id for a in detail_json["avatars"])

    unassigned = admin_client.delete(f"/clients-api/{client_id}/avatars/{avatar_id}")
    assert unassigned.status_code == 409
    assert "deleted or deactivated" in unassigned.json()["detail"]

    detail_after_block = admin_client.get(f"/clients-api/{client_id}")
    assert detail_after_block.status_code == 200
    assert any(a["id"] == avatar_id for a in detail_after_block.json()["avatars"])


def test_fdr_avatars_api_health_and_safety(admin_client, monkeypatch):
    """Avatar API covers create/list/detail/health/quarantine/reactivation."""
    monkeypatch.setattr(
        "app.routes.avatars.scrape_hobby_subreddits",
        DummyTask(),
        raising=False,
    )

    created = admin_client.post(
        "/avatars-api/",
        json={
            "reddit_username": _unique("fdr_health"),
            "voice_profile_md": "FDR voice",
            "hobby_subreddits": ["running"],
        },
    )
    assert created.status_code == 200
    avatar_id = created.json()["id"]

    listing = admin_client.get("/avatars-api/")
    assert listing.status_code == 200
    assert any(a["id"] == avatar_id for a in listing.json())

    detail = admin_client.get(f"/avatars-api/{avatar_id}")
    assert detail.status_code == 200
    assert detail.json()["avatar"]["id"] == avatar_id

    health = admin_client.get(f"/avatars-api/{avatar_id}/health")
    assert health.status_code == 200
    assert health.json()["username"] == created.json()["reddit_username"]

    quarantined = admin_client.post(f"/avatars-api/{avatar_id}/quarantine?reason=fdr")
    assert quarantined.status_code == 200
    assert quarantined.json()["status"] == "quarantined"

    reactivated = admin_client.post(f"/avatars-api/{avatar_id}/reactivate")
    assert reactivated.status_code == 200
    assert reactivated.json()["status"] == "reactivated"


def test_fdr_review_api_comment_and_post_transitions(admin_client, db):
    """Review API validates status transitions and persists edits."""
    client = _create_client(db)
    subreddit = _create_subreddit(db)
    avatar = _create_avatar(db, client)
    thread = _create_thread(db, client, subreddit)
    comment = _create_comment_draft(db, client, avatar, thread)
    post = _create_post_draft(db, client, avatar)
    db.commit()

    comments = admin_client.get(f"/review-api/comments?client_id={client.id}")
    assert comments.status_code == 200
    assert any(item["id"] == str(comment.id) for item in comments.json())

    invalid = admin_client.patch(
        f"/review-api/comments/{comment.id}",
        json={"status": "not-a-status"},
    )
    assert invalid.status_code == 422

    approved = admin_client.patch(
        f"/review-api/comments/{comment.id}",
        json={"status": "approved", "edited_draft": "Approved FDR draft"},
    )
    assert approved.status_code == 200
    db.refresh(comment)
    assert comment.status == "approved"
    assert comment.edited_draft == "Approved FDR draft"

    posts = admin_client.get(f"/review-api/posts?client_id={client.id}")
    assert posts.status_code == 200
    assert any(item["id"] == str(post.id) for item in posts.json())

    rejected = admin_client.patch(
        f"/review-api/posts/{post.id}",
        json={"status": "rejected", "edited_title": "Rejected FDR title"},
    )
    assert rejected.status_code == 200
    db.refresh(post)
    assert post.status == "rejected"
    assert post.edited_title == "Rejected FDR title"


def test_fdr_dashboard_and_export_apis(admin_client, db):
    """Dashboard and export APIs return stable JSON envelopes."""
    client = _create_client(db)
    subreddit = _create_subreddit(db)
    avatar = _create_avatar(db, client)
    thread = _create_thread(db, client, subreddit)
    _create_comment_draft(db, client, avatar, thread)
    db.add(ClientSubredditAssignment(client_id=client.id, subreddit_id=subreddit.id))
    db.add(
        AIUsageLog(
            client_id=client.id,
            operation="scoring",
            model="fdr-test-model",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.01,
        )
    )
    db.add(
        ActivityEvent(
            client_id=client.id,
            event_type="score",
            message="FDR score event",
            event_metadata={"source": "test"},
        )
    )
    db.commit()

    stats = admin_client.get("/api/admin/stats")
    assert stats.status_code == 200
    stats_json = stats.json()
    assert {"clients", "active_avatars", "comment_drafts", "ai"} <= stats_json.keys()

    ai_usage = admin_client.get("/api/admin/ai-usage")
    assert ai_usage.status_code == 200
    assert any(row["client"] == client.client_name for row in ai_usage.json())

    for path in [
        "/export/clients",
        "/export/avatars",
        "/export/threads",
        "/export/comments",
        "/export/subreddits",
        "/export/ai-costs",
        "/export/audit-logs",
        "/export/users",
        "/export/activity",
        "/admin/inspector/export.json",
    ]:
        response = admin_client.get(path)
        assert response.status_code == 200, path
        payload = response.json()
        assert "exported_at" in payload
        assert "data" in payload
        assert "attachment;" in response.headers["content-disposition"]


def test_fdr_subreddit_detail_shows_ai_costs(admin_client, db):
    """Subreddit detail page exposes AI usage tracked for that subreddit."""
    client = _create_client(db)
    subreddit = _create_subreddit(db)
    db.add(ClientSubredditAssignment(client_id=client.id, subreddit_id=subreddit.id))
    db.add(
        AIUsageLog(
            client_id=client.id,
            subreddit_name=subreddit.subreddit_name,
            operation="generation",
            model="fdr-detail-model",
            input_tokens=100,
            output_tokens=40,
            duration_ms=1200,
            cost_usd=0.0123,
        )
    )
    db.commit()

    response = admin_client.get(f"/admin/subreddits/detail/{subreddit.subreddit_name}")

    assert response.status_code == 200
    assert "AI Costs" in response.text
    assert "$0.0123" in response.text
    assert "fdr-detail-model" in response.text


def test_fdr_pipeline_dispatch_endpoints(admin_client, monkeypatch, db):
    """Pipeline trigger APIs enqueue work without requiring a real worker."""
    monkeypatch.setattr("app.routes.pipeline.scrape_subreddit_shared", DummyTask())
    monkeypatch.setattr("app.routes.pipeline.score_threads", DummyTask())
    monkeypatch.setattr("app.routes.pipeline.generate_comments", DummyTask())
    monkeypatch.setattr("app.routes.pipeline.scrape_hobby_subreddits", DummyTask())
    monkeypatch.setattr("app.tasks.karma_tracking.track_karma_single_avatar", DummyTask())
    monkeypatch.setattr("app.tasks.karma_tracking.track_karma_all_avatars", DummyTask())

    # Create a client with an active subreddit assignment for scrape/full-pipeline tests
    from app.models.client import Client
    from app.models.subreddit import Subreddit, ClientSubredditAssignment

    client = Client(client_name="Pipeline Test", brand_name="PT", is_active=True)
    db.add(client)
    db.flush()

    subreddit = Subreddit(subreddit_name="testpipeline", is_active=True)
    db.add(subreddit)
    db.flush()

    assignment = ClientSubredditAssignment(
        client_id=client.id, subreddit_id=subreddit.id, is_active=True
    )
    db.add(assignment)
    db.commit()

    avatar_id = uuid.uuid4()

    # Test scrape endpoint (now returns task_ids list)
    response = admin_client.post(f"/pipeline/scrape/{client.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["action"] == "scrape_shared"
    assert data["count"] == 1

    # Test score endpoint
    response = admin_client.post(f"/pipeline/score/{client.id}")
    assert response.status_code == 200
    assert response.json() == {
        "task_id": "fdr-task-id",
        "status": "queued",
        "action": "score_threads",
    }

    # Test generate endpoint
    response = admin_client.post(f"/pipeline/generate/{client.id}")
    assert response.status_code == 200
    assert response.json() == {
        "task_id": "fdr-task-id",
        "status": "queued",
        "action": "generate_comments",
    }

    # Test hobby endpoint
    response = admin_client.post(f"/pipeline/hobby/{avatar_id}")
    assert response.status_code == 200
    assert response.json() == {
        "task_id": "fdr-task-id",
        "status": "queued",
        "action": "hobby_pipeline",
    }

    # Test karma-track endpoints
    response = admin_client.post(f"/pipeline/karma-track/{avatar_id}")
    assert response.status_code == 200
    assert response.json() == {
        "task_id": "fdr-task-id",
        "status": "queued",
        "action": "karma_track_avatar",
    }

    response = admin_client.post("/pipeline/karma-track-all")
    assert response.status_code == 200
    assert response.json() == {
        "task_id": "fdr-task-id",
        "status": "queued",
        "action": "karma_track_all",
    }
