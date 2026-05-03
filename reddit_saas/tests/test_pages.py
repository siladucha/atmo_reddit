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
    assert "Register" in r.text or "register" in r.text


def test_dashboard(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Dashboard" in r.text


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
    r = client.get("/clients/new")
    assert r.status_code == 200
    assert "New Client" in r.text


def test_client_new_submit(client):
    r = client.post("/clients/new", data={"client_name": "UI Test", "brand_name": "UIB"}, follow_redirects=False)
    assert r.status_code == 303
    assert "/clients/" in r.headers.get("location", "")


def test_avatar_new_page(client):
    r = client.get("/avatars/new")
    assert r.status_code == 200
    assert "New Avatar" in r.text or "Create" in r.text


def test_avatar_new_submit(client):
    r = client.post("/avatars/new", data={
        "reddit_username": "ui_test_avatar",
        "hobby_subreddits": "wine, cooking",
    }, follow_redirects=False)
    assert r.status_code == 303
