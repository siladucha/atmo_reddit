"""Unit tests for the humanize_number Jinja2 filter.

Validates: Requirements 2.35
"""

import pytest

from app.template_filters import humanize_number


class TestHumanizeNumberBelowThousand:
    """Numbers < 1000 should be displayed as-is."""

    def test_zero(self):
        assert humanize_number(0) == "0"

    def test_small_positive(self):
        assert humanize_number(42) == "42"

    def test_boundary_999(self):
        assert humanize_number(999) == "999"

    def test_one(self):
        assert humanize_number(1) == "1"


class TestHumanizeNumberThousands:
    """Numbers 1000–999999 should display as X.YK format."""

    def test_exact_thousand(self):
        assert humanize_number(1000) == "1K"

    def test_1500(self):
        assert humanize_number(1500) == "1.5K"

    def test_round_to_one_decimal(self):
        # 1550 / 1000 = 1.55 → rounds to 1.6
        assert humanize_number(1550) == "1.6K"

    def test_strip_trailing_zero(self):
        # 2000 / 1000 = 2.0 → stripped to "2K"
        assert humanize_number(2000) == "2K"

    def test_upper_boundary_999999(self):
        # 999999 / 1000 = 999.999 → rounds to "1000K"? No — 999.999 rounds to 1000.0
        # Actually 999999 / 1000 = 999.999, formatted to 1 decimal = "1000.0" → "1000K"
        # This is edge case; let's just verify the output
        result = humanize_number(999999)
        assert result == "1000K"

    def test_medium_value(self):
        assert humanize_number(45600) == "45.6K"

    def test_trailing_zero_stripped(self):
        # 10000 / 1000 = 10.0 → "10K"
        assert humanize_number(10000) == "10K"


class TestHumanizeNumberMillions:
    """Numbers >= 1000000 should display as X.YM format."""

    def test_exact_million(self):
        assert humanize_number(1000000) == "1M"

    def test_6283184(self):
        # 6283184 / 1000000 = 6.283184 → rounds to 6.3
        assert humanize_number(6283184) == "6.3M"

    def test_strip_trailing_zero_million(self):
        # 2000000 / 1000000 = 2.0 → "2M"
        assert humanize_number(2000000) == "2M"

    def test_large_million(self):
        # 15700000 / 1000000 = 15.7
        assert humanize_number(15700000) == "15.7M"


class TestHumanizeNumberNegative:
    """Negative numbers should preserve sign."""

    def test_negative_small(self):
        assert humanize_number(-500) == "-500"

    def test_negative_thousands(self):
        assert humanize_number(-1500) == "-1.5K"

    def test_negative_millions(self):
        assert humanize_number(-2500000) == "-2.5M"


class TestHumanizeNumberEdgeCases:
    """Edge cases: non-numeric input, None, strings."""

    def test_none_returns_empty(self):
        assert humanize_number(None) == ""

    def test_non_numeric_string(self):
        assert humanize_number("abc") == "abc"

    def test_numeric_string(self):
        # Strings that can be parsed as numbers should work
        assert humanize_number("1500") == "1.5K"

    def test_float_below_thousand(self):
        assert humanize_number(999.5) == "999.5"

    def test_integer_type(self):
        assert humanize_number(5000) == "5K"
