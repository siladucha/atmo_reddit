"""Test safety service — content checks, rate limits."""

from app.services.safety import check_comment_content, SafetyCheckResult


def test_normal_comment_passes():
    result = check_comment_content("this is a normal comment about security practices")
    assert result.allowed


def test_promotional_link_blocked():
    result = check_comment_content("check out www.example.com for more info")
    assert not result.allowed
    assert "promotional" in result.reason.lower() or "www." in result.reason


def test_promotional_phrases_blocked():
    phrases = ["check out our platform", "visit our website", "sign up now", "free trial available"]
    for phrase in phrases:
        result = check_comment_content(phrase)
        assert not result.allowed, f"Should block: {phrase}"


def test_long_comment_blocked():
    result = check_comment_content("x" * 301)
    assert not result.allowed
    assert "long" in result.reason.lower()


def test_comment_at_limit_passes():
    result = check_comment_content("x" * 300)
    assert result.allowed


def test_empty_comment_passes():
    result = check_comment_content("")
    assert result.allowed


def test_safety_result_bool():
    ok = SafetyCheckResult(True)
    assert bool(ok) is True

    blocked = SafetyCheckResult(False, "test reason")
    assert bool(blocked) is False
    assert blocked.reason == "test reason"
