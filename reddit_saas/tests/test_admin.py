"""Test admin dashboard API."""


def test_admin_stats(client):
    r = client.get("/admin/stats")
    assert r.status_code == 200
    data = r.json()
    assert "clients" in data
    assert "active_avatars" in data
    assert "comment_drafts" in data
    assert "ai" in data
    assert "total_cost_usd" in data["ai"]


def test_admin_ai_usage(client):
    r = client.get("/admin/ai-usage")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
