"""Integration tests for Discovery Engine admin routes.

Tests cover:
- GET /admin/discovery returns session list page
- POST /admin/discovery/new requires platform admin
- POST /admin/discovery/new with valid data creates session
- Validation error returns form with error message
- GET /admin/discovery/{id} returns session page
- HTMX partials return proper Content-Type

Note: These tests require a running PostgreSQL database accessible via the app's
database settings. They use the shared conftest db/admin_client/regular_client
fixtures. Tests will be skipped if the database is not available.
"""

import uuid
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy.orm import Session

from app.models.discovery_session import DiscoverySession
from app.services.discovery.session_manager import create_session


def _db_available():
    """Check if the app database is reachable."""
    try:
        from app.database import SessionLocal
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        return True
    except Exception:
        return False


# Skip all tests if DB is unavailable (e.g., Docker not running)
pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="Database not available (Docker not running?)",
)


# --- Tests using admin_client fixture (requires running DB) ---


def test_get_discovery_list_requires_admin(regular_client):
    """Non-admin user cannot access discovery list."""
    response = regular_client.get("/admin/discovery")
    # Should be denied (403 or redirect to login)
    assert response.status_code in (403, 401, 302)


def test_get_discovery_list_as_admin(admin_client):
    """Admin user gets the discovery session list page."""
    response = admin_client.get("/admin/discovery")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


def test_post_discovery_new_requires_admin(regular_client):
    """Non-admin user cannot create discovery sessions."""
    response = regular_client.post(
        "/admin/discovery/new",
        data={"client_brief": "A" * 100, "prospect_name": "Test"},
    )
    assert response.status_code in (403, 401, 302)


@patch("app.routes.discovery.extract_entities")
def test_post_discovery_new_valid_data(mock_extract, admin_client, db: Session):
    """POST with valid brief creates session and redirects."""
    mock_extract.return_value = {
        "entities": [],
        "insufficient": False,
        "count": 3,
    }

    response = admin_client.post(
        "/admin/discovery/new",
        data={
            "client_brief": "A wellness technology company building AI-powered " * 5,
            "prospect_name": "Test Corp",
        },
        follow_redirects=False,
    )

    # Should redirect to session page (303 See Other)
    assert response.status_code == 303
    assert "/admin/discovery/" in response.headers.get("location", "")


def test_post_discovery_new_validation_error(admin_client):
    """POST with brief < 50 chars returns validation error."""
    response = admin_client.post(
        "/admin/discovery/new",
        data={"client_brief": "Too short", "prospect_name": "Test"},
    )

    # Should return 422 with error message in HTML
    assert response.status_code == 422
    assert "50" in response.text or "character" in response.text.lower()


def test_get_discovery_session_page(admin_client, db: Session, superuser):
    """GET session page returns session detail."""
    session = create_session(
        operator_id=superuser.id,
        client_brief="Integration test session for route testing " + "x" * 50,
        prospect_name="Route Test",
        client_id=None,
        db=db,
    )
    db.commit()

    response = admin_client.get(f"/admin/discovery/{session.id}")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


def test_get_discovery_session_not_found(admin_client):
    """GET non-existent session returns 404."""
    fake_id = uuid.uuid4()
    response = admin_client.get(f"/admin/discovery/{fake_id}")
    assert response.status_code == 404


def test_htmx_partials_content_type(admin_client, db: Session, superuser):
    """HTMX partial endpoints return text/html Content-Type."""
    session = create_session(
        operator_id=superuser.id,
        client_brief="HTMX partial test session " + "y" * 50,
        prospect_name="HTMX Test",
        client_id=None,
        db=db,
    )
    db.commit()

    # Test the session page with HX-Request header (returns HTML partial)
    response = admin_client.get(
        f"/admin/discovery/{session.id}",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
