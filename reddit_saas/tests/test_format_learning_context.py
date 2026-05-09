"""Unit tests for LearningService.format_learning_context method."""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.services.learning import LearningService


# ---------------------------------------------------------------------------
# Helpers — create mock EditRecord and CorrectionPattern objects
# ---------------------------------------------------------------------------


def make_edit_record(
    ai_draft: str = "Original AI draft text.",
    edited_draft: str | None = "Human edited text.",
    final_status: str = "approved",
    subreddit: str = "cybersecurity",
) -> MagicMock:
    """Create a mock EditRecord with the given fields."""
    record = MagicMock()
    record.ai_draft = ai_draft
    record.edited_draft = edited_draft
    record.final_status = final_status
    record.subreddit = subreddit
    return record


def make_correction_pattern(
    rule_text: str = "Keep comments under 50 words",
    pattern_type: str = "length_adjustment",
    frequency: int = 5,
) -> MagicMock:
    """Create a mock CorrectionPattern with the given fields."""
    pattern = MagicMock()
    pattern.rule_text = rule_text
    pattern.pattern_type = pattern_type
    pattern.frequency = frequency
    return pattern


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFormatLearningContext:
    """Tests for LearningService.format_learning_context."""

    def setup_method(self):
        self.service = LearningService()

    def test_empty_inputs_returns_empty_string(self):
        """Both empty examples and patterns returns empty string."""
        result = self.service.format_learning_context([], [])
        assert result == ""

    def test_patterns_only(self):
        """Only patterns (no examples) produces correction rules section."""
        patterns = [
            make_correction_pattern("Keep comments under 50 words"),
            make_correction_pattern("Never use em-dashes"),
        ]

        result = self.service.format_learning_context([], patterns)

        assert "## Learned Corrections from Past Reviews" in result
        assert "### Correction Rules" in result
        assert "- Keep comments under 50 words" in result
        assert "- Never use em-dashes" in result
        assert "### Examples of Past Corrections" not in result

    def test_examples_only_approved(self):
        """Only approved examples (no patterns) produces examples section."""
        examples = [
            make_edit_record(
                ai_draft="The landscape of cybersecurity is shifting.",
                edited_draft="honestly most orgs are still running vuln scanners.",
                final_status="approved",
            ),
        ]

        result = self.service.format_learning_context(examples, [])

        assert "## Learned Corrections from Past Reviews" in result
        assert "### Examples of Past Corrections" in result
        assert "**Example 1 (approved edit):**" in result
        assert 'BEFORE: "The landscape of cybersecurity is shifting."' in result
        assert 'AFTER: "honestly most orgs are still running vuln scanners."' in result
        assert "### Correction Rules" not in result

    def test_rejected_example_has_rejection_indicator(self):
        """Rejected examples show rejection indicator instead of AFTER text."""
        examples = [
            make_edit_record(
                ai_draft="I'd argue that the ecosystem has evolved.",
                edited_draft=None,
                final_status="rejected",
            ),
        ]

        result = self.service.format_learning_context(examples, [])

        assert "rejected draft" in result
        assert "avoid this style" in result
        assert 'BEFORE: "I\'d argue that the ecosystem has evolved."' in result
        assert "(This was rejected by the reviewer)" in result
        assert "AFTER:" not in result

    def test_mixed_examples_and_patterns(self):
        """Both examples and patterns produce full formatted output."""
        patterns = [
            make_correction_pattern("Keep comments under 50 words"),
            make_correction_pattern("Never use em-dashes"),
            make_correction_pattern("Use casual tone, avoid formal language"),
        ]
        examples = [
            make_edit_record(
                ai_draft="The landscape of cybersecurity is shifting.",
                edited_draft="honestly most orgs are still running vuln scanners.",
                final_status="approved",
            ),
            make_edit_record(
                ai_draft="I'd argue that the ecosystem has evolved.",
                edited_draft=None,
                final_status="rejected",
            ),
        ]

        result = self.service.format_learning_context(examples, patterns)

        # Header
        assert "## Learned Corrections from Past Reviews" in result
        # Patterns section
        assert "### Correction Rules" in result
        assert "- Keep comments under 50 words" in result
        assert "- Never use em-dashes" in result
        assert "- Use casual tone, avoid formal language" in result
        # Examples section
        assert "### Examples of Past Corrections" in result
        assert "**Example 1 (approved edit):**" in result
        assert "**Example 2 (rejected draft" in result
        assert "(This was rejected by the reviewer)" in result

    def test_patterns_appear_before_examples(self):
        """Correction rules section appears before examples section."""
        patterns = [make_correction_pattern("Keep it short")]
        examples = [make_edit_record()]

        result = self.service.format_learning_context(examples, patterns)

        rules_pos = result.index("### Correction Rules")
        examples_pos = result.index("### Examples of Past Corrections")
        assert rules_pos < examples_pos

    def test_approved_example_with_none_edited_draft_uses_ai_draft(self):
        """If edited_draft is None for an approved record, AFTER uses ai_draft."""
        examples = [
            make_edit_record(
                ai_draft="Some text here.",
                edited_draft=None,
                final_status="approved",
            ),
        ]

        result = self.service.format_learning_context(examples, [])

        assert 'AFTER: "Some text here."' in result

    def test_multiple_approved_examples_numbered_correctly(self):
        """Multiple examples are numbered sequentially."""
        examples = [
            make_edit_record(ai_draft="Draft 1", edited_draft="Edit 1"),
            make_edit_record(ai_draft="Draft 2", edited_draft="Edit 2"),
            make_edit_record(ai_draft="Draft 3", edited_draft="Edit 3"),
        ]

        result = self.service.format_learning_context(examples, [])

        assert "**Example 1 (approved edit):**" in result
        assert "**Example 2 (approved edit):**" in result
        assert "**Example 3 (approved edit):**" in result
