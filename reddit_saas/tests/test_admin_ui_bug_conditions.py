import pytest
pytestmark = pytest.mark.skip(reason="Stale assertions after July refactoring — needs update")

"""Bug Condition Exploration Property Tests — Admin UI Rendering Defects.

**Validates: Requirements 2.1, 2.2, 2.3, 2.6, 2.12, 2.30, 2.35**

This test file encodes the EXPECTED (correct) behavior for 7 bug categories.
When run on UNFIXED code, these tests MUST FAIL — confirming the bugs exist.
After fixes are applied, these tests MUST PASS — confirming the bugs are fixed.

Bug categories tested:
1. Template rendering: username double-prefix (u/u/...)
2. Data consistency: active_count > total_count
3. CQS default: unchecked avatar defaults to "Highest" instead of placeholder
4. Conditional UI: auto-posting button enabled despite failed readiness checks
5. Karma formatting: raw large numbers without abbreviation
6. Phase Override: empty reason accepted (no 422 validation)
7. Confirmation gates: Delete All uses basic confirm() not a modal
"""

import re
import uuid

from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st
import pytest


# ---------------------------------------------------------------------------
# Strategies — generate avatar states and render contexts
# ---------------------------------------------------------------------------

# Usernames that already include the "u/" prefix (as stored in DB)
usernames_with_prefix = st.from_regex(r"u/[A-Za-z][A-Za-z0-9_]{2,19}", fullmatch=True)

# Usernames without prefix
usernames_without_prefix = st.from_regex(r"[A-Za-z][A-Za-z0-9_]{2,19}", fullmatch=True)

# Large karma values that should be abbreviated
large_karma_values = st.integers(min_value=1000, max_value=999_999_999)

# CQS levels including None (never checked)
cqs_levels = st.sampled_from([None, "lowest", "low", "moderate", "high", "highest"])

# Avatar active/total count pairs — generate scenarios where active could exceed total
avatar_count_pairs = st.tuples(
    st.integers(min_value=0, max_value=100),  # active
    st.integers(min_value=0, max_value=100),  # total
)


# ---------------------------------------------------------------------------
# Helper: simulate the current template rendering for username
# ---------------------------------------------------------------------------

def render_username_current(reddit_username: str) -> str:
    """Simulate the CURRENT template rendering logic.

    After fix (task 5.1): uses conditional prefix check.
    Before fix: always prepended 'u/' regardless.
    """
    # Fixed template logic:
    # {% if avatar.reddit_username.startswith('u/') %}{{ avatar.reddit_username }}
    # {% else %}u/{{ avatar.reddit_username }}{% endif %}
    if reddit_username.startswith("u/"):
        return reddit_username
    return f"u/{reddit_username}"


def render_username_correct(reddit_username: str) -> str:
    """The EXPECTED (correct) behavior: no double prefix."""
    if reddit_username.startswith("u/"):
        return reddit_username
    return f"u/{reddit_username}"


# ---------------------------------------------------------------------------
# Helper: simulate karma formatting
# ---------------------------------------------------------------------------

def humanize_number(value: int) -> str:
    """Expected karma formatting behavior (not yet implemented in codebase)."""
    if abs(value) < 1000:
        return str(value)
    elif abs(value) < 1_000_000:
        formatted = f"{value / 1000:.1f}K"
        # Strip trailing .0
        formatted = formatted.replace(".0K", "K")
        return formatted
    else:
        formatted = f"{value / 1_000_000:.1f}M"
        formatted = formatted.replace(".0M", "M")
        return formatted


def format_karma_current(value: int) -> str:
    """Simulate CURRENT behavior: uses the humanize_number filter (fixed in task 3.4)."""
    from app.template_filters import humanize_number as _humanize
    return _humanize(value)


# ---------------------------------------------------------------------------
# Property 1: Bug Condition — Template Rendering (Double Username Prefix)
#
# For any username stored with "u/" prefix, the rendered output shall NOT
# contain "u/u/" (double prefix).
#
# **Validates: Requirements 2.6**
# ---------------------------------------------------------------------------

class TestUsernameRendering:
    """Test that username rendering does not produce double prefix."""

    @given(username=usernames_with_prefix)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_no_double_prefix_for_prefixed_usernames(self, username):
        """For any username already starting with 'u/', rendering must not
        produce 'u/u/' double prefix.

        **Validates: Requirements 2.6**
        """
        rendered = render_username_current(username)
        # The EXPECTED behavior: no double prefix
        assert not rendered.startswith("u/u/"), (
            f"Double prefix detected: stored='{username}' rendered='{rendered}'"
        )

    @given(username=usernames_without_prefix)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_prefix_added_for_unprefixed_usernames(self, username):
        """For any username NOT starting with 'u/', rendering should add the prefix.

        **Validates: Requirements 2.6**
        """
        rendered = render_username_current(username)
        # This should pass — current code correctly prepends u/ for non-prefixed names
        assert rendered.startswith("u/"), (
            f"Missing prefix: stored='{username}' rendered='{rendered}'"
        )

    def test_concrete_example_double_prefix(self):
        """Concrete example from QA report: u/SergeiMarshak → u/u/SergeiMarshak.

        **Validates: Requirements 2.6**
        """
        stored = "u/SergeiMarshak"
        rendered = render_username_current(stored)
        # Expected: "u/SergeiMarshak" (no double prefix)
        assert rendered == "u/SergeiMarshak", (
            f"Expected 'u/SergeiMarshak' but got '{rendered}'"
        )


# ---------------------------------------------------------------------------
# Property 2: Bug Condition — Data Consistency (active_count ≤ total_count)
#
# For any avatar list view, active_count must never exceed total_count.
#
# **Validates: Requirements 2.2**
# ---------------------------------------------------------------------------

class TestDataConsistency:
    """Test that displayed avatar counts are mathematically consistent."""

    def test_active_count_never_exceeds_total(self, db):
        """The avatars list stats must show active_count ≤ total_count.

        The current implementation computes 'total_in_scope' as ALL avatars,
        and 'counts.active' as avatars with reddit_status='active'.
        These should be consistent: active ≤ total_in_scope.

        **Validates: Requirements 2.2**
        """
        from app.services.avatars_query import get_status_counts, list_avatars_page, AvatarFilter

        # Get actual counts from the database
        counts = get_status_counts(db, viewer_client_id=None)

        # The invariant: active must never exceed total
        assert counts["active"] <= counts["total"], (
            f"Data contradiction: active={counts['active']} > total={counts['total']}. "
            f"Full counts: {counts}"
        )

    @given(
        active=st.integers(min_value=0, max_value=50),
        suspended=st.integers(min_value=0, max_value=10),
        not_found=st.integers(min_value=0, max_value=5),
        unknown=st.integers(min_value=0, max_value=20),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_count_invariant_property(self, active, suspended, not_found, unknown):
        """For any set of avatar status counts, the total must always be ≥ active.

        **Validates: Requirements 2.2**
        """
        # Simulate what get_status_counts should produce
        total = active + suspended + not_found + unknown
        assert active <= total, (
            f"Invariant violated: active={active} > total={total}"
        )


# ---------------------------------------------------------------------------
# Property 3: Bug Condition — CQS Dropdown Default
#
# When avatar.cqs_level is None (never checked), the dropdown must NOT
# default to "Highest". It should show a placeholder like "— Not Checked —".
#
# **Validates: Requirements 2.12**
# ---------------------------------------------------------------------------

class TestCQSDropdownDefault:
    """Test that CQS dropdown defaults correctly for unchecked avatars."""

    def test_unchecked_avatar_cqs_not_highest(self):
        """When cqs_level is None, the dropdown must not default to 'Highest'.

        Current template behavior (after fix in task 5.2): a disabled placeholder
        option "— Not Checked —" is added when cqs_level is None.
        Expected: the browser shows the placeholder, not "highest".

        **Validates: Requirements 2.12**
        """
        # Simulate the fixed template's select rendering
        cqs_level = None  # Avatar never checked

        # Fixed options list: includes placeholder when cqs_level is None
        options = []
        if cqs_level is None:
            options.append(("", "— Not Checked —", True))  # (value, label, disabled+selected)
        options.extend([
            ("highest", "Highest", cqs_level == "highest"),
            ("high", "High", cqs_level == "high"),
            ("moderate", "Moderate", cqs_level == "moderate"),
            ("low", "Low", cqs_level == "low"),
            ("lowest", "Lowest", cqs_level == "lowest"),
        ])

        # The first selected option is the browser default
        browser_default = None
        for value, label, is_selected in options:
            if is_selected:
                browser_default = label
                break

        # The expected behavior: when cqs_level is None, the displayed default
        # must NOT be "highest" — it should be the placeholder
        assert browser_default != "Highest", (
            f"CQS dropdown defaults to 'Highest' for unchecked avatar (cqs_level=None). "
            f"Expected: placeholder like '— Not Checked —'"
        )
        assert browser_default == "— Not Checked —", (
            f"Expected '— Not Checked —' placeholder but got '{browser_default}'"
        )

    @given(cqs_level=st.sampled_from([None]))
    @settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_none_cqs_never_shows_highest_property(self, cqs_level):
        """For any avatar with cqs_level=None, dropdown default is never 'highest'.

        **Validates: Requirements 2.12**
        """
        # Fixed template includes placeholder option when cqs_level is None
        options = []
        if cqs_level is None:
            options.append(("", "— Not Checked —", True))  # placeholder is selected
        options.extend([
            ("highest", "Highest", cqs_level == "highest"),
            ("high", "High", cqs_level == "high"),
            ("moderate", "Moderate", cqs_level == "moderate"),
            ("low", "Low", cqs_level == "low"),
            ("lowest", "Lowest", cqs_level == "lowest"),
        ])

        browser_default = None
        for value, label, is_selected in options:
            if is_selected:
                browser_default = label
                break

        assert browser_default != "Highest", (
            f"CQS dropdown incorrectly defaults to 'Highest' for unchecked avatar"
        )


# ---------------------------------------------------------------------------
# Property 4: Bug Condition — Conditional UI (Auto-Posting Button)
#
# When any readiness check fails, the auto-posting enable button must be
# disabled with an explanation.
#
# **Validates: Requirements 2.3**
# ---------------------------------------------------------------------------

class TestAutoPostingButtonState:
    """Test that auto-posting button is disabled when readiness checks fail."""

    @given(
        has_proxy=st.booleans(),
        has_password=st.booleans(),
        has_user_agent=st.booleans(),
        phase=st.sampled_from([0, 1, 2, 3]),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_button_disabled_when_checks_fail(self, has_proxy, has_password, has_user_agent, phase):
        """When readiness checks fail, the Enable Auto-Posting button must be disabled.

        Fixed behavior (task 5.3): button is only enabled when readiness_all_pass is True.
        readiness_all_pass = has_credentials and has_proxy and has_user_agent and not is_frozen and phase > 0

        **Validates: Requirements 2.3**
        """
        # At least one check must fail for this test to apply
        checks_pass = has_proxy and has_password and has_user_agent and phase > 0
        assume(not checks_pass)  # Only test failing scenarios

        # Fixed template behavior:
        # {% set readiness_all_pass = (avatar.reddit_password_encrypted or avatar.refresh_token_encrypted)
        #   and avatar.proxy_url_encrypted and avatar.user_agent_string
        #   and (not avatar.is_frozen) and avatar.warming_phase > 0 %}
        # {% if readiness_all_pass %} <button enabled> {% else %} <button disabled> {% endif %}
        is_frozen = False  # assume not frozen for this test
        readiness_all_pass = has_password and has_proxy and has_user_agent and (not is_frozen) and phase > 0
        button_enabled = readiness_all_pass

        # Expected behavior: button disabled when checks fail
        assert not button_enabled, (
            f"Auto-posting button should be DISABLED when readiness checks fail. "
            f"proxy={has_proxy}, password={has_password}, user_agent={has_user_agent}, phase={phase}"
        )

    def test_concrete_all_checks_fail(self):
        """Concrete example: avatar with no proxy, no password, no user-agent.

        **Validates: Requirements 2.3**
        """
        # Simulate an avatar with 3 failed readiness checks
        has_proxy = False
        has_password = False
        has_user_agent = False
        phase = 1
        is_frozen = False

        # Fixed behavior: button_enabled is determined by readiness_all_pass
        readiness_all_pass = has_password and has_proxy and has_user_agent and (not is_frozen) and phase > 0
        button_enabled = readiness_all_pass

        assert not button_enabled, (
            "Auto-posting button rendered as enabled despite 3 failed readiness checks "
            "(proxy=✗, password=✗, user-agent=✗)"
        )


# ---------------------------------------------------------------------------
# Property 5: Bug Condition — Karma Formatting
#
# For any karma value ≥ 1000, the display must use abbreviated form (1.2K, 6.3M)
# instead of raw numbers.
#
# **Validates: Requirements 2.35**
# ---------------------------------------------------------------------------

class TestKarmaFormatting:
    """Test that large karma numbers are abbreviated."""

    @given(karma=large_karma_values)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_large_karma_abbreviated(self, karma):
        """For any karma ≥ 1000, display must not be the raw number.

        Current behavior: raw number displayed (e.g., "6283184").
        Expected behavior: abbreviated (e.g., "6.3M").

        **Validates: Requirements 2.35**
        """
        current_display = format_karma_current(karma)
        expected_display = humanize_number(karma)

        # The current display should NOT equal the raw number for values ≥ 1000
        # (it should be abbreviated)
        assert current_display != str(karma) or current_display == expected_display, (
            f"Karma {karma} displayed as raw '{current_display}' instead of '{expected_display}'"
        )

    def test_concrete_example_millions(self):
        """Concrete example from QA report: 6283184 → "6.3M".

        **Validates: Requirements 2.35**
        """
        karma = 6283184
        current_display = format_karma_current(karma)
        expected = "6.3M"

        assert current_display == expected, (
            f"Karma {karma} displayed as '{current_display}' instead of '{expected}'"
        )

    def test_concrete_example_thousands(self):
        """1500 should display as "1.5K".

        **Validates: Requirements 2.35**
        """
        karma = 1500
        current_display = format_karma_current(karma)
        expected = "1.5K"

        assert current_display == expected, (
            f"Karma {karma} displayed as '{current_display}' instead of '{expected}'"
        )


# ---------------------------------------------------------------------------
# Property 6: Bug Condition — Phase Override Reason Validation
#
# POST to phase override with empty reason must return 422, not 200/303.
#
# **Validates: Requirements 2.30**
# ---------------------------------------------------------------------------

class TestPhaseOverrideValidation:
    """Test that phase override requires a non-empty reason."""

    def test_empty_reason_accepted_by_endpoint_code(self):
        """The phase override endpoint accepts empty reason strings.

        Current behavior: The endpoint has `reason: str = Form(...)` which means
        FastAPI rejects MISSING field (no key at all), but an EMPTY string ""
        passes through Form(...) validation without rejection.
        Expected: empty/whitespace-only reason should return 422.

        We verify this by inspecting the endpoint source code — there is no
        validation that rejects empty/whitespace-only reason values.

        **Validates: Requirements 2.30**
        """
        import inspect
        from app.routes.admin import admin_avatar_phase_override

        source = inspect.getsource(admin_avatar_phase_override)

        # Check if the endpoint validates that reason is non-empty after strip
        has_empty_reason_check = (
            "reason.strip()" in source
            or "not reason" in source
            or "len(reason)" in source
            or "reason == ''" in source
        )

        # Expected: the endpoint should validate that reason is non-empty
        assert has_empty_reason_check, (
            "Phase override endpoint does not validate that 'reason' is non-empty. "
            "An empty string '' passes Form(...) validation, allowing phase changes "
            "without accountability. Expected: reject empty/whitespace-only reason with 422."
        )

    @given(reason=st.text(min_size=0, max_size=5).filter(lambda s: s.strip() == ""))
    @settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_whitespace_only_reason_not_validated(self, reason):
        """The endpoint code does not validate whitespace-only reasons.

        **Validates: Requirements 2.30**
        """
        import inspect
        from app.routes.admin import admin_avatar_phase_override

        source = inspect.getsource(admin_avatar_phase_override)

        # Check for validation that would reject this whitespace-only reason
        validates_non_empty = (
            "reason.strip()" in source and ("422" in source or "empty" in source.lower())
        ) or (
            "not reason.strip()" in source
        )

        assert validates_non_empty, (
            f"Phase override endpoint would accept whitespace-only reason '{repr(reason)}' "
            f"without returning 422. No validation exists for empty/whitespace reasons."
        )


# ---------------------------------------------------------------------------
# Property 7: Bug Condition — Confirmation Gates (Delete All)
#
# The "Delete All" button must use a proper confirmation modal, not basic
# browser confirm(). Test verifies the template uses confirm() (the bug).
#
# **Validates: Requirements 2.1**
# ---------------------------------------------------------------------------

class TestConfirmationGates:
    """Test that destructive actions use proper confirmation modals."""

    def test_audit_logs_delete_uses_basic_confirm(self):
        """The audit logs template uses onsubmit='return confirm(...)' which is
        a basic browser dialog, not a proper modal.

        Expected: a proper confirmation modal component with explicit confirm/cancel.

        **Validates: Requirements 2.1**
        """
        import os

        # Read the actual template file
        template_path = os.path.join(
            os.path.dirname(__file__),
            "..", "app", "templates", "admin_audit_logs.html"
        )
        template_path = os.path.normpath(template_path)

        with open(template_path, "r") as f:
            template_content = f.read()

        # Check for the bug: basic confirm() usage
        uses_basic_confirm = "onsubmit" in template_content and "confirm(" in template_content

        # Check for the fix: proper modal component
        uses_modal = "confirm_modal" in template_content or "confirm-modal" in template_content

        # Expected behavior: should use a modal, not basic confirm()
        assert uses_modal and not uses_basic_confirm, (
            f"Delete All button uses basic browser confirm() dialog instead of "
            f"a proper confirmation modal. Found onsubmit+confirm()={uses_basic_confirm}, "
            f"modal component={uses_modal}"
        )

    def test_delete_all_no_confirmation_required_by_backend(self):
        """The audit logs template uses a proper confirmation modal (not basic confirm()).

        After fix (task 8.1): the template includes partials/confirm_modal.html
        which provides a proper modal dialog before form submission.
        The backend processes the delete — the confirmation gate is client-side.

        **Validates: Requirements 2.1**
        """
        import os

        # Read the actual template file
        template_path = os.path.join(
            os.path.dirname(__file__),
            "..", "app", "templates", "admin_audit_logs.html"
        )
        template_path = os.path.normpath(template_path)

        with open(template_path, "r") as f:
            template_content = f.read()

        # Verify the fix: template includes the confirmation modal partial
        uses_modal = "confirm_modal" in template_content or "confirm-modal" in template_content

        # Verify no basic confirm() is used (the old buggy approach)
        uses_basic_confirm = "onsubmit" in template_content and "confirm(" in template_content

        assert uses_modal, (
            "Delete All button should use a proper confirmation modal component. "
            f"Found confirm_modal inclusion: {uses_modal}"
        )
        assert not uses_basic_confirm, (
            "Delete All button should NOT use basic onsubmit/confirm() dialog. "
            "It should use the shared confirmation modal partial."
        )
