from dataclasses import dataclass


@dataclass
class Variant:
    name: str
    display_value: str  # What the visitor sees (e.g., "$99/month")


@dataclass
class ABTest:
    test_name: str
    page: str  # "mobile" or "proxy"
    variants: list[Variant]


# Active test configuration
ACTIVE_TESTS: list[ABTest] = [
    ABTest(
        test_name="mobile_pricing",
        page="mobile",
        variants=[
            Variant(name="price_99", display_value="$99/month"),
            Variant(name="price_149", display_value="$149/month"),
            Variant(name="price_199", display_value="$199/month"),
        ],
    ),
    ABTest(
        test_name="mobile_model",
        page="mobile",
        variants=[
            Variant(name="subscription", display_value="Monthly subscription"),
            Variant(name="pay_per_comment", display_value="Pay per comment"),
            Variant(name="hybrid", display_value="Hybrid model"),
        ],
    ),
    ABTest(
        test_name="proxy_pricing",
        page="proxy",
        variants=[
            Variant(name="price_999", display_value="$999/month"),
            Variant(name="price_1999", display_value="$1,999/month"),
            Variant(name="contact_sales", display_value="Contact sales"),
        ],
    ),
    ABTest(
        test_name="proxy_guarantee",
        page="proxy",
        variants=[
            Variant(name="no_guarantee", display_value="Standard (lower price)"),
            Variant(name="free_replacement", display_value="Free replacement guarantee"),
        ],
    ),
]


def get_tests_for_page(page: str) -> list[ABTest]:
    """Return active tests applicable to a given page."""
    return [t for t in ACTIVE_TESTS if t.page == page]


def get_default_variants() -> dict[str, str]:
    """Return the first variant of each test (used for no-JS fallback)."""
    return {t.test_name: t.variants[0].name for t in ACTIVE_TESTS}


def is_valid_variant(test_name: str, variant_name: str) -> bool:
    """Check if a variant name is valid for a given test."""
    for test in ACTIVE_TESTS:
        if test.test_name == test_name:
            return any(v.name == variant_name for v in test.variants)
    return False
