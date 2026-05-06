"""Test avatar CRUD and health."""


def test_create_avatar(admin_client):
    r = admin_client.post("/avatars-api/", json={
        "reddit_username": "test_avatar_1",
        "voice_profile_md": "A test avatar voice profile",
        "hobby_subreddits": ["wine", "cooking"],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["reddit_username"] == "test_avatar_1"
    assert data["active"] is True


def test_create_duplicate_avatar(admin_client):
    admin_client.post("/avatars-api/", json={"reddit_username": "dup_avatar"})
    r = admin_client.post("/avatars-api/", json={"reddit_username": "dup_avatar"})
    assert r.status_code == 400


def test_list_avatars(admin_client):
    admin_client.post("/avatars-api/", json={"reddit_username": "list_av_1"})
    r = admin_client.get("/avatars-api/")
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_update_avatar(admin_client):
    r = admin_client.post("/avatars-api/", json={"reddit_username": "upd_avatar"})
    aid = r.json()["id"]
    r = admin_client.patch(f"/avatars-api/{aid}", json={"tone_principles": "Be sarcastic"})
    assert r.status_code == 200
    assert r.json()["tone_principles"] == "Be sarcastic"


def test_avatar_health(admin_client):
    r = admin_client.post("/avatars-api/", json={"reddit_username": "health_av"})
    aid = r.json()["id"]
    r = admin_client.get(f"/avatars-api/{aid}/health")
    assert r.status_code == 200
    data = r.json()
    assert data["username"] == "health_av"
    assert "karma_comment" in data
    assert "brand_ratio" in data


def test_quarantine_avatar(admin_client):
    r = admin_client.post("/avatars-api/", json={"reddit_username": "quar_av"})
    aid = r.json()["id"]
    r = admin_client.post(f"/avatars-api/{aid}/quarantine?reason=test")
    assert r.status_code == 200
    assert r.json()["status"] == "quarantined"


def test_reactivate_avatar(admin_client):
    r = admin_client.post("/avatars-api/", json={"reddit_username": "react_av"})
    aid = r.json()["id"]
    admin_client.post(f"/avatars-api/{aid}/quarantine")
    r = admin_client.post(f"/avatars-api/{aid}/reactivate")
    assert r.status_code == 200
    assert r.json()["status"] == "reactivated"


def test_assign_avatar_to_client(admin_client):
    rc = admin_client.post("/clients-api/", json={"client_name": "AV Client", "brand_name": "AV"})
    cid = rc.json()["id"]
    ra = admin_client.post("/avatars-api/", json={"reddit_username": "assign_av"})
    aid = ra.json()["id"]
    r = admin_client.post(f"/clients-api/{cid}/avatars/{aid}")
    assert r.status_code == 200
    assert r.json()["status"] == "assigned"


def test_avatar_not_found(admin_client):
    r = admin_client.get("/avatars-api/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
