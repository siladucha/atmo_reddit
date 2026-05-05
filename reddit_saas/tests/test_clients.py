"""Test client CRUD and relationships."""


def test_create_client(client):
    r = client.post("/clients-api/", json={
        "client_name": "Test Corp",
        "brand_name": "TestBrand",
        "company_profile": "A test company",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["client_name"] == "Test Corp"
    assert data["brand_name"] == "TestBrand"
    assert data["is_active"] is True
    assert "id" in data


def test_list_clients(client):
    client.post("/clients-api/", json={"client_name": "C1", "brand_name": "B1"})
    client.post("/clients-api/", json={"client_name": "C2", "brand_name": "B2"})
    r = client.get("/clients-api/")
    assert r.status_code == 200
    assert len(r.json()) >= 2


def test_get_client_detail(client):
    r = client.post("/clients-api/", json={"client_name": "Detail", "brand_name": "D"})
    cid = r.json()["id"]
    r = client.get(f"/clients-api/{cid}")
    assert r.status_code == 200
    data = r.json()
    assert data["client"]["client_name"] == "Detail"
    assert "avatars" in data
    assert "subreddits" in data


def test_update_client(client):
    r = client.post("/clients-api/", json={"client_name": "Old", "brand_name": "Old"})
    cid = r.json()["id"]
    r = client.patch(f"/clients-api/{cid}", json={"client_name": "New"})
    assert r.status_code == 200
    assert r.json()["client_name"] == "New"


def test_deactivate_client(client):
    r = client.post("/clients-api/", json={"client_name": "Del", "brand_name": "Del"})
    cid = r.json()["id"]
    r = client.delete(f"/clients-api/{cid}")
    assert r.status_code == 200
    assert r.json()["status"] == "deactivated"


def test_add_subreddit(client):
    import uuid as _uuid

    r = client.post("/clients-api/", json={"client_name": "Sub", "brand_name": "Sub"})
    cid = r.json()["id"]
    # Subreddit names are globally unique per active monitor, so use a fresh
    # name for each run rather than something like "cybersecurity" that may
    # already be in the dev DB.
    name = f"test_{_uuid.uuid4().hex[:10]}"
    r = client.post(f"/clients-api/{cid}/subreddits", json={"subreddit_name": name})
    assert r.status_code == 200
    assert r.json()["subreddit_name"] == name


def test_client_not_found(client):
    r = client.get("/clients-api/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
