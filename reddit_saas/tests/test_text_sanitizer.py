"""Tests for text_sanitizer — Reddit-safe comment output."""

import pytest

from app.services.text_sanitizer import sanitize_for_reddit


class TestUnicodeNormalization:
    """Step 1-2: Invisible chars and Unicode punctuation."""

    def test_removes_zero_width_spaces(self):
        text = "hello\u200bworld"
        assert sanitize_for_reddit(text) == "hello world" or sanitize_for_reddit(text) == "helloworld"
        assert "\u200b" not in sanitize_for_reddit(text)

    def test_removes_bom(self):
        text = "\ufeffhello"
        assert sanitize_for_reddit(text) == "hello"

    def test_removes_soft_hyphen(self):
        text = "vul\u00adner\u00adable"
        assert sanitize_for_reddit(text) == "vulnerable"

    def test_smart_quotes_to_straight(self):
        text = '\u201cHello\u201d he said, \u2018world\u2019'
        result = sanitize_for_reddit(text)
        assert '"Hello"' in result
        assert "'world'" in result

    def test_em_dash_to_spaced_hyphen(self):
        text = "security\u2014it matters"
        result = sanitize_for_reddit(text)
        assert "\u2014" not in result
        assert " - " in result

    def test_en_dash_to_hyphen(self):
        text = "2020\u20132024"
        result = sanitize_for_reddit(text)
        assert result == "2020-2024"

    def test_ellipsis_character(self):
        text = "well\u2026 that happened"
        result = sanitize_for_reddit(text)
        assert result == "well... that happened"

    def test_non_breaking_space(self):
        text = "100\u00a0MB"
        result = sanitize_for_reddit(text)
        assert result == "100 MB"


class TestMarkdownRemoval:
    """Step 3: Markdown formatting syntax removal."""

    def test_bold_asterisks(self):
        text = "this is **important** stuff"
        assert sanitize_for_reddit(text) == "this is important stuff"

    def test_bold_underscores(self):
        text = "this is __important__ stuff"
        assert sanitize_for_reddit(text) == "this is important stuff"

    def test_italic_asterisks(self):
        text = "this is *important* stuff"
        assert sanitize_for_reddit(text) == "this is important stuff"

    def test_italic_underscores(self):
        text = "this is _important_ stuff"
        assert sanitize_for_reddit(text) == "this is important stuff"

    def test_strikethrough(self):
        text = "this is ~~wrong~~ right"
        assert sanitize_for_reddit(text) == "this is wrong right"

    def test_inline_code(self):
        text = "use `kubectl` for that"
        assert sanitize_for_reddit(text) == "use kubectl for that"

    def test_blockquote(self):
        text = "> this is a quote\nand this is not"
        result = sanitize_for_reddit(text)
        assert not result.startswith(">")
        assert "this is a quote" in result

    def test_heading(self):
        text = "## My Point\nhere it is"
        result = sanitize_for_reddit(text)
        assert "##" not in result
        assert "My Point" in result

    def test_markdown_link(self):
        text = "check [this article](https://example.com) out"
        result = sanitize_for_reddit(text)
        assert result == "check this article out"

    def test_bullet_list(self):
        text = "reasons:\n- first thing\n- second thing"
        result = sanitize_for_reddit(text)
        assert "- " not in result
        assert "first thing" in result

    def test_numbered_list(self):
        text = "steps:\n1. do this\n2. do that"
        result = sanitize_for_reddit(text)
        assert "1." not in result
        assert "do this" in result


class TestWhitespaceNormalization:
    """Step 4: Whitespace handling."""

    def test_multiple_newlines_collapsed(self):
        text = "first\n\n\n\nsecond"
        result = sanitize_for_reddit(text)
        assert "\n\n\n" not in result
        assert "first" in result and "second" in result

    def test_trailing_whitespace_stripped(self):
        text = "hello   \nworld  "
        result = sanitize_for_reddit(text)
        lines = result.split("\n")
        for line in lines:
            assert line == line.rstrip()

    def test_multiple_spaces_collapsed(self):
        text = "too    many   spaces"
        result = sanitize_for_reddit(text)
        assert "  " not in result


class TestPreservation:
    """Regression prevention — things that should NOT change."""

    def test_plain_text_unchanged(self):
        text = "This is a normal comment about security tools."
        assert sanitize_for_reddit(text) == text

    def test_contractions_preserved(self):
        text = "you're right, it's not that simple and they don't get it"
        assert sanitize_for_reddit(text) == text

    def test_regular_hyphens_preserved(self):
        text = "well-known fact about risk-based approaches"
        assert sanitize_for_reddit(text) == text

    def test_standard_punctuation_preserved(self):
        text = "Really? Yes, I think so (mostly). It works!"
        assert sanitize_for_reddit(text) == text

    def test_single_newline_preserved(self):
        text = "first point\nsecond point"
        assert sanitize_for_reddit(text) == text

    def test_urls_text_extracted(self):
        # URLs in markdown links get text extracted
        text = "see [the docs](https://example.com/path)"
        result = sanitize_for_reddit(text)
        assert "the docs" in result
        assert "https://" not in result

    def test_empty_input(self):
        assert sanitize_for_reddit("") == ""
        assert sanitize_for_reddit(None) == ""

    def test_mid_word_underscores_preserved(self):
        # variable_name should not be treated as italic
        text = "check the variable_name in config_file"
        result = sanitize_for_reddit(text)
        assert "variable_name" in result
        assert "config_file" in result

    def test_asterisk_in_expletive_preserved(self):
        text = "what the f*ck is this config"
        result = sanitize_for_reddit(text)
        assert "f*ck" in result


class TestRealWorldExamples:
    """Test with realistic LLM outputs."""

    def test_typical_ai_comment(self):
        text = (
            "**This** is exactly the problem\u2014most teams are drowning in "
            "vulnerability lists without understanding which ones *actually* "
            "lead to critical assets. The \u201cfix everything\u201d approach "
            "doesn\u2019t scale."
        )
        result = sanitize_for_reddit(text)
        # No markdown formatting
        assert "**" not in result
        assert "*" not in result or "f*" in result  # allow mid-word
        # No unicode
        assert "\u2014" not in result
        assert "\u201c" not in result
        assert "\u2019" not in result
        # Content preserved
        assert "exactly the problem" in result
        assert "critical assets" in result
        assert "doesn't scale" in result

    def test_comment_with_list(self):
        text = (
            "Three things that matter:\n"
            "1. Context over volume\n"
            "2. Exploitability over severity\n"
            "3. Paths over alerts"
        )
        result = sanitize_for_reddit(text)
        assert "1." not in result
        assert "Context over volume" in result
        assert "Paths over alerts" in result
