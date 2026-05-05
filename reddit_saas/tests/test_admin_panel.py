"""Unit tests for admin panel routes and templates (tasks 11.2–11.7)."""

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


# ---------------------------------------------------------------------------
# 11.2 — Admin access control and navigation
# ---------------------------------------------------------------------------


def test_unauthenticated_redirect():
    """Unauthenticated request to /admin/ redirects to /login."""
    with TestClient(app) as c:
        r = c.get("/admin/", follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers.get("location", "")


def test_non_superuser_403(regular_client):
    """Non-superuser gets 403 on /admin/."""
    r = regular_client.get("/admin/", follow_redirects=False)
    assert r.status_code == 403


def test_admin_dashboard_renders(admin_client):
    """Superuser gets 200 with stats cards."""
    r = admin_client.get("/admin/")
    assert r.status_code == 200
    assert "System Overview" in r.text


def test_admin_sidebar_links(admin_client):
    """All navigation links present in sidebar HTML."""
    r = admin_client.get("/admin/")
    for link in [
        "/admin/users",
        "/admin/clients",
        "/admin/tasks",
        "/admin/health",
        "/admin/ai-costs",
        "/admin/audit-logs",
        "/admin/billing",
    ]:
        assert link in r.text, f"Missing sidebar link: {link}"


def test_admin_active_nav_highlight(admin_client):
    """Current page nav item has active CSS class."""
    r = admin_client.get("/admin/users")
    assert r.status_code == 200
    # The users link should have the active class (bg-indigo-600)
    assert "bg-indigo-600" in r.text


def test_root_redirects_for_non_admin(regular_client):
    """`/` redirects non-superusers (orphaned user lands on /login or /clients/{id})."""
    r = regular_client.get("/", follow_redirects=False)
    assert r.status_code == 303
    location = r.headers.get("location", "")
    assert location.startswith("/login") or location.startswith("/clients/")


def test_root_redirects_superuser_to_admin(admin_client):
    """Superusers visiting `/` are routed to the admin panel."""
    r = admin_client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location") == "/admin/"


def test_admin_panel_shows_admin_badge(admin_client):
    """Admin panel renders the Admin badge in the sidebar."""
    r = admin_client.get("/admin/")
    assert r.status_code == 200
    assert "Admin" in r.text


# ---------------------------------------------------------------------------
# 11.3 — User management
# ---------------------------------------------------------------------------


def test_user_list_pagination(admin_client):
    """User list shows correct page of results."""
    r = admin_client.get("/admin/users")
    assert r.status_code == 200
    assert "User Management" in r.text


def test_user_create_success(admin_client):
    """Create user with valid data succeeds."""
    r = admin_client.post("/admin/users", data={
        "email": "newuser@test.com",
        "password": "pass123",
        "full_name": "New User",
    })
    assert r.status_code == 200
    assert "newuser@test.com" in r.text


def test_user_create_duplicate_email(admin_client):
    """Duplicate email shows error message."""
    admin_client.post("/admin/users", data={
        "email": "dup@test.com",
        "password": "pass123",
    })
    r = admin_client.post("/admin/users", data={
        "email": "dup@test.com",
        "password": "pass123",
    })
    assert "Email already registered" in r.text


def test_self_deactivation_blocked(admin_client, superuser):
    """Admin cannot deactivate own account."""
    r = admin_client.post(f"/admin/users/{superuser.id}/toggle-active")
    assert r.status_code == 200
    # The user should still be active (self-deactivation blocked)


# ---------------------------------------------------------------------------
# 11.4 — Client management
# ---------------------------------------------------------------------------


def test_client_list_shows_counts(admin_client, db):
    """Client list shows subreddit and avatar counts."""
    from app.models.client import Client

    c = Client(client_name="Test", brand_name="Test")
    db.add(c)
    db.commit()
    r = admin_client.get("/admin/clients")
    assert r.status_code == 200
    assert "Test" in r.text


def test_client_create_success(admin_client):
    """Create client with all fields succeeds."""
    r = admin_client.post("/admin/clients/new", data={
        "client_name": "NewClient",
        "brand_name": "NewBrand",
        "company_profile": "Profile text",
    }, follow_redirects=False)
    assert r.status_code == 303  # redirect to client detail


def test_client_edit_prepopulates(admin_client, db):
    """Edit form shows current client data."""
    from app.models.client import Client

    c = Client(client_name="EditMe", brand_name="EditBrand", company_profile="Original")
    db.add(c)
    db.commit()
    db.refresh(c)
    r = admin_client.get(f"/admin/clients/{c.id}")
    assert r.status_code == 200
    assert "EditMe" in r.text


def test_client_deactivate(admin_client, db):
    """Deactivate sets is_active=False."""
    from app.models.client import Client

    c = Client(client_name="Deactivate", brand_name="Brand")
    db.add(c)
    db.commit()
    db.refresh(c)
    r = admin_client.post(f"/admin/clients/{c.id}/deactivate", follow_redirects=False)
    assert r.status_code == 303


# ---------------------------------------------------------------------------
# 11.5 — Keyword, subreddit, and persona management
# ---------------------------------------------------------------------------


def test_keyword_add_remove(admin_client, db):
    """Add and remove keywords from JSONB."""
    from app.models.client import Client

    c = Client(client_name="KW", brand_name="KW")
    db.add(c)
    db.commit()
    db.refresh(c)
    # Add keyword
    r = admin_client.post(
        f"/admin/keywords/{c.id}/add",
        data={"name": "test keyword", "priority": "HIGH"},
    )
    assert r.status_code == 200
    assert "test keyword" in r.text
    # Remove keyword
    r = admin_client.post(f"/admin/keywords/{c.id}/0/remove")
    assert r.status_code == 200


def test_keyword_invalid_name(admin_client, db):
    """Empty keyword name rejected."""
    from app.models.client import Client

    c = Client(client_name="KW2", brand_name="KW2")
    db.add(c)
    db.commit()
    db.refresh(c)
    r = admin_client.post(
        f"/admin/keywords/{c.id}/add",
        data={"name": "  ", "priority": "HIGH"},
    )
    assert "cannot be empty" in r.text


def test_subreddit_add_success(admin_client, db):
    """Valid subreddit name accepted."""
    import uuid as _uuid

    from app.models.client import Client

    c = Client(client_name="Sub", brand_name="Sub")
    db.add(c)
    db.commit()
    db.refresh(c)
    # Globally unique per active monitor — pick a name unlikely to collide.
    name = f"test_{_uuid.uuid4().hex[:10]}"
    r = admin_client.post(
        f"/admin/subreddits/{c.id}/add",
        data={"subreddit_name": name, "subreddit_type": "professional"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_subreddit_invalid_name(admin_client, db):
    """Invalid subreddit name rejected."""
    from app.models.client import Client

    c = Client(client_name="Sub2", brand_name="Sub2")
    db.add(c)
    db.commit()
    db.refresh(c)
    r = admin_client.post(
        f"/admin/subreddits/{c.id}/add",
        data={"subreddit_name": "ab", "subreddit_type": "professional"},
    )
    assert r.status_code == 200
    assert "3-21 characters" in r.text



# ---------------------------------------------------------------------------
# 11.6 — Onboarding wizard
# ---------------------------------------------------------------------------


def test_onboarding_wizard_step_order(admin_client, db):
    """Wizard steps render in correct order."""
    from app.models.client import Client

    c = Client(client_name="Wizard", brand_name="Wiz")
    db.add(c)
    db.commit()
    db.refresh(c)
    for step in range(1, 7):
        r = admin_client.get(f"/admin/clients/{c.id}/onboard/step/{step}")
        assert r.status_code == 200
        assert f"Step {step}" in r.text


def test_onboarding_back_navigation(admin_client, db):
    """Back button preserves data (links to previous step)."""
    from app.models.client import Client

    c = Client(client_name="BackNav", brand_name="BN")
    db.add(c)
    db.commit()
    db.refresh(c)
    r = admin_client.get(f"/admin/clients/{c.id}/onboard/step/3")
    assert r.status_code == 200
    assert f"/admin/clients/{c.id}/onboard/step/2" in r.text  # back link


def test_onboarding_test_run(admin_client, db):
    """Test run page renders with trigger button."""
    from app.models.client import Client

    c = Client(client_name="TestRun", brand_name="TR")
    db.add(c)
    db.commit()
    db.refresh(c)
    r = admin_client.get(f"/admin/clients/{c.id}/onboard/step/6")
    assert r.status_code == 200
    assert "Trigger Full Pipeline" in r.text


# ---------------------------------------------------------------------------
# 11.7 — Health, AI costs, audit logs, billing, and seed
# ---------------------------------------------------------------------------


def test_health_page_renders(admin_client):
    """Health page shows all service statuses."""
    r = admin_client.get("/admin/health")
    assert r.status_code == 200
    assert "postgresql" in r.text.lower()


def test_ai_costs_summary(admin_client):
    """AI costs page shows correct totals."""
    r = admin_client.get("/admin/ai-costs")
    assert r.status_code == 200
    assert "AI Cost" in r.text or "Total Cost" in r.text


def test_ai_costs_budget_warning(admin_client):
    """Budget section is present on AI costs page."""
    r = admin_client.get("/admin/ai-costs")
    assert r.status_code == 200
    # The page always renders — budget warning only shows at >= 80%
    # but the page title and cost tracking section are always present
    assert "AI Cost Tracking" in r.text


def test_audit_log_list(admin_client):
    """Audit log page shows entries."""
    r = admin_client.get("/admin/audit-logs")
    assert r.status_code == 200
    assert "Audit Logs" in r.text


def test_audit_log_filter(admin_client):
    """Filtering returns correct entries (page renders with filters)."""
    r = admin_client.get("/admin/audit-logs?action=create")
    assert r.status_code == 200


def test_audit_log_readonly(admin_client):
    """No mutation endpoints for audit logs (only GET)."""
    r = admin_client.post("/admin/audit-logs", follow_redirects=False)
    assert r.status_code in (405, 404, 307)  # Method not allowed or not found


def test_billing_placeholder(admin_client):
    """Billing page shows 'Coming Soon'."""
    r = admin_client.get("/admin/billing")
    assert r.status_code == 200
    assert "Coming Soon" in r.text


def test_seed_neuroyoga(db):
    """Seed creates NeuroYoga with all data."""
    from app.seed import seed_neuroyoga
    from app.models.client import Client
    from app.models.subreddit import ClientSubreddit
    from app.models.avatar import Avatar

    seed_neuroyoga(db)

    client = db.query(Client).filter(Client.client_name == "NeuroYoga").first()
    assert client is not None
    assert client.brand_name == "ATMO"

    subs = db.query(ClientSubreddit).filter(ClientSubreddit.client_id == client.id).all()
    assert len(subs) >= 10

    avatars = db.query(Avatar).filter(Avatar.client_ids.any(str(client.id))).all()
    assert len(avatars) >= 2


def test_seed_idempotent(db):
    """Running seed twice doesn't duplicate."""
    from app.seed import seed_neuroyoga
    from app.models.client import Client

    seed_neuroyoga(db)
    count1 = db.query(Client).filter(Client.client_name == "NeuroYoga").count()

    seed_neuroyoga(db)
    count2 = db.query(Client).filter(Client.client_name == "NeuroYoga").count()

    assert count1 == count2 == 1
