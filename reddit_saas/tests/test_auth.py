"""Test auth: register, login, JWT."""

from app.services.auth import hash_password, verify_password, create_access_token, decode_access_token


def test_password_hashing():
    hashed = hash_password("mypassword")
    assert hashed != "mypassword"
    assert verify_password("mypassword", hashed)
    assert not verify_password("wrongpassword", hashed)


def test_jwt_create_and_decode():
    token = create_access_token(data={"sub": "user123", "email": "test@test.com"})
    assert len(token) > 0

    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "user123"
    assert payload["email"] == "test@test.com"


def test_jwt_invalid_token():
    payload = decode_access_token("invalid.token.here")
    assert payload is None


def test_register_via_api(client):
    r = client.post("/auth/register", json={
        "email": "newuser@test.com",
        "password": "testpass123",
        "full_name": "Test User",
    })
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_register_duplicate_email(client):
    client.post("/auth/register", json={"email": "dup@test.com", "password": "pass123"})
    r = client.post("/auth/register", json={"email": "dup@test.com", "password": "pass456"})
    assert r.status_code == 400


def test_login_via_api(client):
    client.post("/auth/register", json={"email": "login@test.com", "password": "pass123"})
    r = client.post("/auth/login", json={"email": "login@test.com", "password": "pass123"})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_login_wrong_password(client):
    client.post("/auth/register", json={"email": "wrong@test.com", "password": "pass123"})
    r = client.post("/auth/login", json={"email": "wrong@test.com", "password": "badpass"})
    assert r.status_code == 401


def test_login_via_form(client):
    client.post("/auth/register", json={"email": "form@test.com", "password": "pass123"})
    r = client.post("/login", data={"email": "form@test.com", "password": "pass123"}, follow_redirects=False)
    assert r.status_code == 303
    assert "access_token" in r.cookies


def test_login_form_bad_password(client):
    client.post("/auth/register", json={"email": "formbad@test.com", "password": "pass123"})
    r = client.post("/login", data={"email": "formbad@test.com", "password": "wrong"})
    assert r.status_code == 200
    assert "Invalid" in r.text
