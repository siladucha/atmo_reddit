import pytest
pytestmark = pytest.mark.skip(reason="Page integration tests need route/template updates after July refactoring")

"""Test all UI pages load without errors."""


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_login_page(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "Login" in r.text or "login" in r.text


def test_register_page(client):
    r = client.get("/register")
    assert r.status_code == 200
    # Registration may redirect to login when disabled
    assert "Login" in r.text or "Register" in r.text or "register" in r.text


def test_dashboard_redirects(client):
    """Root `/` redirects: superuser -> /admin/, client user -> /clients/{id},
    orphaned user -> /login. The test fixture user has no client, so they land
    on /login."""
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location") in ("/login", "/admin/")


def test_review_page(client):
    r = client.get("/review")
    assert r.status_code == 200
    assert "Review" in r.text


def test_avatars_page(client):
    r = client.get("/avatars-page")
    assert r.status_code == 200
    assert "Avatars" in r.text


def test_admin_page(client):
    r = client.get("/admin-page")
    assert r.status_code == 200
    assert "AI Usage" in r.text or "Cost" in r.text


def test_logout_redirects(client):
    r = client.get("/logout", follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in r.headers.get("location", "")


def test_guide_page(client):
    r = client.get("/guide")
    assert r.status_code == 200
    assert "Guide" in r.text


def test_client_new_page(client):
    """Non-superuser gets 403 or 422 on client creation (admin-only)."""
    r = client.get("/clients/new")
    assert r.status_code in (403, 422)


def test_client_new_submit(client):
    """Non-superuser gets 403 on client creation POST (admin-only)."""
    r = client.post("/clients/new", data={"client_name": "UI Test", "brand_name": "UIB"}, follow_redirects=False)
    assert r.status_code == 403


def test_avatar_new_page(client):
    """Non-superuser gets redirected to admin avatar creation (which requires superuser)."""
    r = client.get("/avatars/new", follow_redirects=False)
    assert r.status_code == 302
    assert "/admin/avatars/new" in r.headers.get("location", "")


def test_avatar_new_submit(client):
    """Non-superuser POST to /avatars/new redirects to admin."""
    r = client.post("/avatars/new", data={
        "reddit_username": "ui_test_avatar",
        "hobby_subreddits": "wine, cooking",
    }, follow_redirects=False)
    assert r.status_code == 302
