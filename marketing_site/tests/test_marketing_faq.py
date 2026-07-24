"""Tests for FAQ routes and data compliance."""

import re

import pytest

from app.data.faq_data import FAQ_ITEMS


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_faq_route_returns_200(client):
    """GET /faq → HTTP 200, contains heading and CTA."""
    resp = await client.get("/faq")
    assert resp.status_code == 200
    body = resp.text
    assert "FREQUENTLY ASKED QUESTIONS" in body
    assert "Start Your Free Trial" in body


@pytest.mark.asyncio
async def test_pricing_has_faq_section(client):
    """GET /pricing → HTTP 200, contains FAQ heading and accordion elements."""
    resp = await client.get("/pricing")
    assert resp.status_code == 200
    body = resp.text
    assert "FREQUENTLY ASKED QUESTIONS" in body
    assert "aria-expanded" in body


# ---------------------------------------------------------------------------
# Data validation tests
# ---------------------------------------------------------------------------


def test_faq_items_count_bounds():
    """FAQ_ITEMS has between 3 and 10 entries."""
    assert 3 <= len(FAQ_ITEMS) <= 10


def test_faq_items_have_required_keys():
    """Each FAQ item has 'question' and 'answer' keys with non-empty strings."""
    for item in FAQ_ITEMS:
        assert "question" in item and isinstance(item["question"], str) and item["question"].strip()
        assert "answer" in item and isinstance(item["answer"], str) and item["answer"].strip()


def test_faq_content_parity():
    """Both /faq and /pricing routes reference the same FAQ_ITEMS data source.

    Structural test: the routes module imports FAQ_ITEMS from app.data.faq_data.
    """
    from app.routes import pages as pages_module

    assert hasattr(pages_module, "FAQ_ITEMS")
    assert pages_module.FAQ_ITEMS is FAQ_ITEMS


# ---------------------------------------------------------------------------
# Compliance tests
# ---------------------------------------------------------------------------

PROHIBITED_TERMS = [
    "fake accounts",
    "fake account",
    "bot",
    "bots",
    "automated posting",
    "evading detection",
    "avatar",
    "avatars",
    "VPN",
    "karma farming",
    "karma farm",
    "account warming",
    "account warm-up",
    "proxy",
    "residential IP",
    "rotating IP",
    "ban",
    "shadowban",
    "suspended",
    "terms of service",
    "ToS",
    "Reddit rules",
    "platform rules",
    "rule violation",
    "policy violation",
    "against the rules",
]


def _contains_prohibited_term(text: str) -> str | None:
    """Return the first prohibited term found (whole-word, case-insensitive) or None."""
    for term in PROHIBITED_TERMS:
        pattern = r"\b" + re.escape(term) + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            return term
    return None


def test_compliance_no_prohibited_terms():
    """No FAQ item contains any prohibited term (whole-word, case-insensitive)."""
    for item in FAQ_ITEMS:
        for field in ("question", "answer"):
            found = _contains_prohibited_term(item[field])
            assert found is None, (
                f"Prohibited term '{found}' found in FAQ {field}: "
                f"{item['question'][:60]}..."
            )


APPROVED_PHRASES = [
    "community engagement management",
    "persona-driven content strategy",
    "human-in-the-loop",
]


def test_compliance_approved_phrases():
    """Every FAQ answer contains at least one approved descriptor phrase."""
    for item in FAQ_ITEMS:
        answer_lower = item["answer"].lower()
        has_phrase = any(phrase in answer_lower for phrase in APPROVED_PHRASES)
        assert has_phrase, (
            f"FAQ answer missing approved phrase: {item['question'][:60]}..."
        )


def test_compound_words_not_flagged():
    """Verify 'robot' and 'chatbot' are NOT caught by the prohibited 'bot' check."""
    # These contain 'bot' as a substring but should not match whole-word check
    assert _contains_prohibited_term("robot") is None
    assert _contains_prohibited_term("chatbot") is None
    assert _contains_prohibited_term("robotics and chatbots discussion") is None


# ---------------------------------------------------------------------------
# SEO / meta tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_faq_meta_title_length(client):
    """GET /faq response title is ≤60 chars and contains 'FAQ'."""
    resp = await client.get("/faq")
    body = resp.text
    # Extract <title> content
    match = re.search(r"<title>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    assert match, "No <title> tag found"
    title = match.group(1).strip()
    assert len(title) <= 60, f"Title too long ({len(title)} chars): {title}"
    assert "FAQ" in title


@pytest.mark.asyncio
async def test_faq_has_cta_link(client):
    """GET /faq response contains CTA link to /onboard/trial."""
    resp = await client.get("/faq")
    assert 'href="/onboard/trial"' in resp.text
