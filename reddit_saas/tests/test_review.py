"""Test review API endpoints."""


def test_list_pending_comments_empty(admin_client):
    r = admin_client.get("/review-api/comments?status=pending")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_list_pending_posts_empty(admin_client):
    r = admin_client.get("/review-api/posts?status=pending")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_update_nonexistent_comment(admin_client):
    r = admin_client.patch(
        "/review-api/comments/00000000-0000-0000-0000-000000000000",
        json={"status": "approved"},
    )
    assert r.status_code == 404


def test_update_nonexistent_post(admin_client):
    r = admin_client.patch(
        "/review-api/posts/00000000-0000-0000-0000-000000000000",
        json={"status": "approved"},
    )
    assert r.status_code == 404
