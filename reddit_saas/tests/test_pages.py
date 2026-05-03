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
