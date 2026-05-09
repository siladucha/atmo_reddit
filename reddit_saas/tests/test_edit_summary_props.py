"""Property-based tests for Edit Summary computation.

Tests determinism (Property 2), format invariants (Property 3), and null on identity (Property 4)
using Hypothesis.
"""

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.learning import compute_edit_summary


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate realistic comment drafts
draft_text = st.text(
    min_size=10,
    max_size=500,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
)


# ---------------------------------------------------------------------------
# Property 2: Round trip consistency
# ---------------------------------------------------------------------------

# Feature: self-learning-loop, Property 2: Round trip consistency


@settings(max_examples=100)
@given(ai_draft=draft_text, edited_draft=draft_text)
def test_property_2_edit_summary_determinism(ai_draft: str, edited_draft: str):
    """**Validates: Requirements 7.1**

    For any two strings (ai_draft, edited_draft), calling compute_edit_summary
    multiple times with the same inputs always produces the same output.
    """
    result1 = compute_edit_summary(ai_draft, edited_draft)
    result2 = compute_edit_summary(ai_draft, edited_draft)
    result3 = compute_edit_summary(ai_draft, edited_draft)

    assert result1 == result2
    assert result2 == result3


# ---------------------------------------------------------------------------
# Property 3: Edit summary format invariants
# ---------------------------------------------------------------------------

# Feature: self-learning-loop, Property 3: Edit summary format invariants


@settings(max_examples=100)
@given(ai_draft=draft_text, edited_draft=draft_text)
def test_property_3_edit_summary_format_invariants(ai_draft: str, edited_draft: str):
    """**Validates: Requirements 7.2, 7.3**

    For any two distinct strings (ai_draft, edited_draft) where ai_draft ≠ edited_draft,
    the resulting Edit_Summary SHALL be a non-empty semicolon-separated string with
    length ≤ 500 characters.
    """
    assume(ai_draft != edited_draft)

    result = compute_edit_summary(ai_draft, edited_draft)

    # Result must not be None for distinct inputs
    assert result is not None

    # Result must be a non-empty string
    assert isinstance(result, str)
    assert len(result) > 0

    # Result must respect the 500 character limit
    assert len(result) <= 500


# ---------------------------------------------------------------------------
# Property 4: Edit summary null on identity
# ---------------------------------------------------------------------------

# Feature: self-learning-loop, Property 4: Edit summary null on identity


@settings(max_examples=100)
@given(s=st.text(min_size=0, max_size=500))
def test_property_4_edit_summary_null_on_identity(s: str):
    """**Validates: Requirements 7.4**

    For any string s, compute_edit_summary(s, s) returns None.
    """
    result = compute_edit_summary(s, s)
    assert result is None
