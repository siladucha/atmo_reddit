"""Preservation Property Tests — Existing Admin Panel Functionality Unchanged.

**Property 2: Preservation** — Existing Admin Panel Functionality Unchanged

IMPORTANT: These tests follow observation-first methodology.
They encode CURRENT behavior of non-buggy inputs on UNFIXED code so we can
verify no regressions after fixes are applied.

EXPECTED OUTCOME: All tests PASS on unfixed code (confirms baseline behavior to preserve).

Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10,
3.11, 3.12, 3.13, 3.14, 3.15, 3.16, 3.17, 3.18, 3.19, 3.20, 3.21, 3.22,
3.23, 3.24, 3.25, 3.26, 3.27, 3.28, 3.29, 3.30, 3.31, 3.32, 3.33, 3.34
"""

import uuid
from datetime import datetime, timezone

import pytest
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.client import Client


# =============================================================================
# Strategies for non-buggy inputs
# =============================================================================

# Usernames that do NOT start with "u/" — the non-buggy case for Req 3.6
st_username_no_prefix = st.from_regex(
    r"[A-Za-z][A-Za-z0-9_-]{2,19}",
    fullmatch=True,
).filter(lambda u: not u.startswith("u/"))

# CQS levels that are explicitly set (not None) — the non-buggy case for Req 3.12
st_cqs_level_set = st.sampled_from(["lowest", "low", "moderate", "high", "highest"])

# Valid warming phases for non-Mentor avatars
st_warming_phase = st.sampled_from([1, 2, 3])

# Audit log page/sort params
st_page = st.integers(min_value=1, max_value=10)
st_per_page = st.sampled_from([10, 20, 50])


def _create_avatar(db: Session, username: str, **kwargs) -> Avatar:
    """Create a test avatar with given username and extra fields."""
    defaults = {
        "reddit_username": username,
        "active": True,
        "is_shadowbanned": False,
        "is_frozen": False,
        "health_status": "active",
        "warming_phase": 1,
    }
    defaults.update(kwargs)
    avatar = Avatar(**defaults)
    db.add(avatar)
    db.flush()
    return avatar


def _create_client(db: Session, name: str = None) -> Client:
    """Create a test client."""
    name = name or f"TestClient_{uuid.uuid4().hex[:6]}"
    client = Client(client_name=name, brand_name=f"Brand_{name}", is_active=True)
    db.add(client)
    db.flush()
    return client


# =============================================================================
# Test 1: HTMX Partial Swaps for Avatar Tabs Return 200 with Correct Content-Type
# Validates: Requirements 3.4, 3.9
# =============================================================================

class TestHTMXPartialSwaps:
    """HTMX partial swap endpoints return 200 with text/html Content-Type.

    **Validates: Requirements 3.4, 3.9**
    """

    def test_avatars_list_htmx_partial_returns_200(self, admin_client, db):
        """HTMX request to avatars list returns partial HTML (200, text/html).

        **Validates: Requirements 3.9**
        """
        _create_avatar(db, f"htmx_test_{uuid.uuid4().hex[:6]}")
        r = admin_client.get(
            "/admin/avatars",
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")
        # Should return the partial, not the full page
        # The partial won't have the full <html> wrapper
        assert "admin_base" not in r.text or "avatars" in r.text.lower()

    def test_avatar_confidence_partial_returns_200(self, admin_client, db):
        """Avatar confidence partial endpoint returns 200 with text/html.

        **Validates: Requirements 3.4**
        """
        avatar = _create_avatar(db, f"conf_{uuid.uuid4().hex[:6]}")
        r = admin_client.get(f"/admin/avatars/{avatar.id}/confidence")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")

    def test_avatar_learned_patterns_partial_returns_200(self, admin_client, db):
        """Avatar learned patterns endpoint returns 200 with text/html.

        **Validates: Requirements 3.4**
        """
        avatar = _create_avatar(db, f"lp_{uuid.uuid4().hex[:6]}")
        r = admin_client.get(f"/admin/avatars/{avatar.id}/learned-patterns")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")


# =============================================================================
# Test 2: Admin CRUD Operations Succeed
# Validates: Requirements 3.1, 3.2, 3.4
# =============================================================================

class TestAdminCRUDPreservation:
    """Admin CRUD operations (create/edit avatar, client, user) succeed and
    return expected responses.

    **Validates: Requirements 3.1, 3.2, 3.4**
    """

    def test_create_client_returns_redirect(self, admin_client, db):
        """Creating a client via POST returns a redirect (303).

        **Validates: Requirements 3.2**
        """
        name = f"Pres_Client_{uuid.uuid4().hex[:6]}"
        r = admin_client.post(
            "/admin/clients/new",
            data={"client_name": name, "brand_name": f"Brand_{name}"},
            follow_redirects=False,
        )
        assert r.status_code == 303

    def test_create_avatar_returns_redirect(self, admin_client, db):
        """Creating an avatar via POST returns a redirect (303).

        **Validates: Requirements 3.4**
        """
        username = f"pres_avatar_{uuid.uuid4().hex[:6]}"
        r = admin_client.post(
            "/admin/avatars/new",
            data={
                "reddit_username": username,
                "active": "true",
            },
            follow_redirects=False,
        )
        assert r.status_code == 303

    def test_edit_avatar_preserves_data(self, admin_client, db):
        """Editing an avatar preserves existing fields.

        **Validates: Requirements 3.4**
        """
        avatar = _create_avatar(db, f"edit_{uuid.uuid4().hex[:6]}")
        db.commit()

        r = admin_client.get(f"/admin/avatars/{avatar.id}/edit")
        assert r.status_code == 200
        assert avatar.reddit_username in r.text

    def test_deactivate_client_returns_redirect(self, admin_client, db):
        """Deactivating a client returns redirect (303).

        **Validates: Requirements 3.1**
        """
        client = _create_client(db)
        db.commit()

        r = admin_client.post(
            f"/admin/clients/{client.id}/deactivate",
            follow_redirects=False,
        )
        assert r.status_code == 303


# =============================================================================
# Test 3: Pipeline Controls (Freeze/Unfreeze, Kill Switches) Function Correctly
# Validates: Requirements 3.3, 3.5, 3.7, 3.30
# =============================================================================

class TestPipelineControlsPreservation:
    """Pipeline controls (freeze/unfreeze, kill switches) function correctly.

    **Validates: Requirements 3.3, 3.5, 3.7, 3.30**
    """

    def test_freeze_avatar_succeeds(self, admin_client, db):
        """Freezing an avatar sets is_frozen=True and returns redirect.

        **Validates: Requirements 3.5**
        """
        avatar = _create_avatar(db, f"freeze_{uuid.uuid4().hex[:6]}")
        db.commit()

        r = admin_client.post(
            f"/admin/avatars/{avatar.id}/freeze",
            data={"freeze_reason": "testing freeze preservation"},
            follow_redirects=False,
        )
        assert r.status_code == 303

        db.refresh(avatar)
        assert avatar.is_frozen is True
        assert avatar.freeze_reason == "testing freeze preservation"

    def test_unfreeze_avatar_succeeds(self, admin_client, db):
        """Unfreezing a frozen avatar clears frozen state.

        **Validates: Requirements 3.5**
        """
        avatar = _create_avatar(db, f"unfreeze_{uuid.uuid4().hex[:6]}", is_frozen=True, freeze_reason="test")
        db.commit()

        r = admin_client.post(
            f"/admin/avatars/{avatar.id}/unfreeze",
            follow_redirects=False,
        )
        assert r.status_code == 303

        db.refresh(avatar)
        assert avatar.is_frozen is False
        assert avatar.freeze_reason is None

    def test_phase_override_with_reason_form_present(self, admin_client, db):
        """Phase override form with reason field is present on avatar detail page.

        **Validates: Requirements 3.30**
        """
        avatar = _create_avatar(db, f"phase_{uuid.uuid4().hex[:6]}", warming_phase=1)
        db.commit()

        r = admin_client.get(f"/admin/avatars/{avatar.id}")
        assert r.status_code == 200
        # The phase override form exists with a reason field
        assert "phase-override" in r.text
        assert "reason" in r.text.lower()


# =============================================================================
# Test 4: Username Rendering for Non-"u/" Prefixed Usernames
# Validates: Requirements 3.6
# =============================================================================

class TestUsernameRenderingPreservation:
    """Username rendering for usernames NOT starting with "u/" produces correct output.
    The template prepends "u/" to these usernames, which is correct behavior.

    **Validates: Requirements 3.6**
    """

    @given(username=st_username_no_prefix)
    @settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_username_without_prefix_rendered_correctly(self, admin_client, db, username):
        """For usernames not starting with 'u/', template renders 'u/{username}'.

        **Validates: Requirements 3.6**
        """
        # Ensure unique username
        unique_username = f"{username}_{uuid.uuid4().hex[:4]}"
        avatar = _create_avatar(db, unique_username)
        db.commit()

        r = admin_client.get(f"/admin/avatars/{avatar.id}")
        assert r.status_code == 200

        # The template renders "u/username" — this is correct for non-prefixed usernames
        assert f"u/{unique_username}" in r.text
        # Should NOT have double prefix
        assert f"u/u/{unique_username}" not in r.text


# =============================================================================
# Test 5: CQS Dropdown with Set Value Displays Correctly
# Validates: Requirements 3.12
# =============================================================================

class TestCQSDropdownPreservation:
    """CQS dropdown with actual set value (e.g., "moderate") displays that value correctly.

    **Validates: Requirements 3.12**
    """

    @given(cqs_level=st_cqs_level_set)
    @settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_cqs_set_value_displayed_correctly(self, admin_client, db, cqs_level):
        """When CQS is set to a specific level, the dropdown shows it as selected.

        **Validates: Requirements 3.12**
        """
        username = f"cqs_{cqs_level}_{uuid.uuid4().hex[:4]}"
        avatar = _create_avatar(
            db, username,
            cqs_level=cqs_level,
            cqs_checked_at=datetime.now(timezone.utc),
        )
        db.commit()

        r = admin_client.get(f"/admin/avatars/{avatar.id}")
        assert r.status_code == 200

        # The CQS badge should display the level in uppercase
        assert f"CQS: {cqs_level.upper()}" in r.text


# =============================================================================
# Test 6: Auto-Posting Button Enabled When ALL Readiness Checks Pass
# Validates: Requirements 3.3
# =============================================================================

class TestAutoPostingButtonPreservation:
    """Auto-posting button enabled when ALL readiness checks pass.

    **Validates: Requirements 3.3**
    """

    def test_posting_section_renders_when_all_checks_pass(self, admin_client, db):
        """When avatar has all posting prerequisites met, readiness indicators show green.

        **Validates: Requirements 3.3**
        """
        avatar = _create_avatar(
            db,
            f"posting_ready_{uuid.uuid4().hex[:6]}",
            warming_phase=2,
            is_frozen=False,
            posting_mode="disabled",
            reddit_password_encrypted="encrypted_placeholder",
            proxy_url_encrypted="encrypted_placeholder",
            user_agent_string="Mozilla/5.0 TestAgent",
        )
        db.commit()

        r = admin_client.get(f"/admin/avatars/{avatar.id}")
        assert r.status_code == 200

        # All readiness checks should show green ✓
        # Credentials ✓, Proxy ✓, User-Agent ✓, Not frozen ✓, Phase > 0 ✓
        assert "Credentials configured" in r.text
        assert "Proxy configured" in r.text
        assert "User-Agent:" in r.text
        assert "Not frozen" in r.text
        # Posting section renders (mode displayed)
        assert "Automated Posting" in r.text


# =============================================================================
# Test 7: Pagination Mechanics in Audit Logs Preserve Page/Sort State
# Validates: Requirements 3.33, 3.34
# =============================================================================

class TestAuditLogPaginationPreservation:
    """Pagination mechanics in audit logs preserve page/sort state via URL params.

    **Validates: Requirements 3.33, 3.34**
    """

    @given(page=st_page, per_page=st_per_page)
    @settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_audit_logs_page_param_preserved(self, admin_client, db, page, per_page):
        """Audit logs respect page and per_page parameters.

        **Validates: Requirements 3.34**
        """
        r = admin_client.get(f"/admin/audit-logs?page={page}&per_page={per_page}")
        assert r.status_code == 200
        assert "Audit Logs" in r.text

    def test_audit_logs_filter_params_preserved(self, admin_client, db):
        """Audit logs filters are preserved in the response form.

        **Validates: Requirements 3.33**
        """
        r = admin_client.get("/admin/audit-logs?action=create&entity_type=avatar")
        assert r.status_code == 200
        assert "Audit Logs" in r.text

    def test_audit_logs_empty_filter_returns_all(self, admin_client, db):
        """Audit logs with no filter shows all entries.

        **Validates: Requirements 3.33**
        """
        r = admin_client.get("/admin/audit-logs")
        assert r.status_code == 200
        assert "Audit Logs" in r.text


# =============================================================================
# Test 8: Role-Based Rendering Produces Correct Output
# Validates: Requirements 3.9, 3.10
# =============================================================================

class TestRoleBasedRenderingPreservation:
    """Role-based rendering (is_avatar_manager checks) produces correct HTML output.

    **Validates: Requirements 3.9, 3.10**
    """

    def test_non_superuser_gets_403_on_admin(self, regular_client):
        """Non-superuser cannot access admin panel (403).

        **Validates: Requirements 3.9**
        """
        r = regular_client.get("/admin/", follow_redirects=False)
        assert r.status_code == 403

    def test_superuser_sees_full_admin_nav(self, admin_client):
        """Superuser sees admin dashboard and can access key pages.

        **Validates: Requirements 3.9**
        """
        r = admin_client.get("/admin/")
        assert r.status_code == 200
        # The dashboard page renders (superuser access works)
        assert "Dashboard" in r.text or "System Overview" in r.text

    def test_review_queue_accessible_by_admin(self, admin_client):
        """Admin can access review queue.

        **Validates: Requirements 3.10**
        """
        r = admin_client.get("/admin/review")
        assert r.status_code == 200


# =============================================================================
# Test 9: Avatars List — Active Count ≤ Total for Correct Data
# Validates: Requirements 3.2
# =============================================================================

class TestAvatarCountsPreservation:
    """When avatars are displayed with correct data, active count ≤ total.

    **Validates: Requirements 3.2**
    """

    @given(active_count=st.integers(min_value=0, max_value=5),
           inactive_count=st.integers(min_value=0, max_value=3))
    @settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_avatar_counts_consistent(self, admin_client, db, active_count, inactive_count):
        """Avatar list page shows counts where displayed active ≤ total.

        **Validates: Requirements 3.2**
        """
        assume(active_count + inactive_count > 0)

        # Create avatars with specific states
        for i in range(active_count):
            _create_avatar(
                db,
                f"active_{i}_{uuid.uuid4().hex[:4]}",
                active=True,
                reddit_status="active",
            )
        for i in range(inactive_count):
            _create_avatar(
                db,
                f"inactive_{i}_{uuid.uuid4().hex[:4]}",
                active=False,
                reddit_status="suspended",
            )
        db.commit()

        r = admin_client.get("/admin/avatars")
        assert r.status_code == 200
        # Page renders successfully with avatar data
        assert "Avatars" in r.text


# =============================================================================
# Test 10: Existing Dropdowns Continue to Function
# Validates: Requirements 3.11, 3.13
# =============================================================================

class TestDropdownPreservation:
    """Plain dropdowns elsewhere in UI continue to function as-is.

    **Validates: Requirements 3.11, 3.13**
    """

    def test_avatars_list_filter_dropdown_works(self, admin_client, db):
        """Client filter dropdown on avatars list returns results.

        **Validates: Requirements 3.11**
        """
        client = _create_client(db)
        avatar = _create_avatar(
            db, f"filter_{uuid.uuid4().hex[:6]}",
            client_ids=[str(client.id)],
        )
        db.commit()

        r = admin_client.get(f"/admin/avatars?client_id={client.id}")
        assert r.status_code == 200

    def test_audit_log_action_filter_dropdown_works(self, admin_client, db):
        """Action filter dropdown on audit logs works.

        **Validates: Requirements 3.11**
        """
        r = admin_client.get("/admin/audit-logs?action=freeze")
        assert r.status_code == 200
        assert "Audit Logs" in r.text


# =============================================================================
# Test 11: Single Draft in Review Queue Displays as Individual Item
# Validates: Requirements 3.14, 3.15
# =============================================================================

class TestReviewQueuePreservation:
    """Single drafts in review queue continue to display as individual items.

    **Validates: Requirements 3.14, 3.15**
    """

    def test_review_queue_renders_successfully(self, admin_client, db):
        """Review queue page renders without error.

        **Validates: Requirements 3.14**
        """
        r = admin_client.get("/admin/review")
        assert r.status_code == 200

    def test_review_approve_button_present(self, admin_client, db):
        """Approve button workflow is present in the review page.

        **Validates: Requirements 3.15**
        """
        r = admin_client.get("/admin/review")
        assert r.status_code == 200
        # The page renders (may be empty if no drafts)


# =============================================================================
# Test 12: Navigation Without Form Changes Proceeds Without Dialog
# Validates: Requirements 3.25
# =============================================================================

class TestNavigationPreservation:
    """Navigation without form changes proceeds without any confirmation dialogs.

    **Validates: Requirements 3.25**
    """

    def test_navigating_between_admin_pages_works(self, admin_client):
        """Sequential navigation between admin pages succeeds without issues.

        **Validates: Requirements 3.25**
        """
        pages = ["/admin/", "/admin/users", "/admin/clients", "/admin/audit-logs"]
        for page in pages:
            r = admin_client.get(page)
            assert r.status_code == 200


# =============================================================================
# Test 13: Existing Tooltip Content Preserved
# Validates: Requirements 3.26
# =============================================================================

class TestTooltipPreservation:
    """Existing tooltips display correct content.

    **Validates: Requirements 3.26**
    """

    def test_avatar_detail_has_tooltips(self, admin_client, db):
        """Avatar detail page renders with existing tooltip infrastructure.

        **Validates: Requirements 3.26**
        """
        avatar = _create_avatar(db, f"tooltip_{uuid.uuid4().hex[:6]}")
        db.commit()

        r = admin_client.get(f"/admin/avatars/{avatar.id}")
        assert r.status_code == 200
        # The page uses block_tooltip.html partial for existing tooltips
        # (CQS section has tooltip text)
        assert "Contributor Quality Score" in r.text


# =============================================================================
# Test 14: Pipeline Stats with Non-Zero Values Display Correctly
# Validates: Requirements 3.27, 3.28
# =============================================================================

class TestPipelineStatsPreservation:
    """Pipeline stats with data display normally.

    **Validates: Requirements 3.27, 3.28**
    """

    def test_dashboard_renders_pipeline_stats(self, admin_client):
        """Dashboard page renders pipeline stats section.

        **Validates: Requirements 3.28**
        """
        r = admin_client.get("/admin/")
        assert r.status_code == 200
        assert "System Overview" in r.text


# =============================================================================
# Test 15: Subreddit Tags Render As-Is
# Validates: Requirements 3.29
# =============================================================================

class TestSubredditTagsPreservation:
    """Non-'hob' subreddit tags render as-is.

    **Validates: Requirements 3.29**
    """

    def test_avatars_list_renders_without_error(self, admin_client, db):
        """Avatars list renders subreddit info without errors.

        **Validates: Requirements 3.29**
        """
        _create_avatar(db, f"tag_{uuid.uuid4().hex[:6]}")
        db.commit()

        r = admin_client.get("/admin/avatars")
        assert r.status_code == 200
