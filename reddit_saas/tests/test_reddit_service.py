"""Test Reddit service — deduplication logic (no actual API calls)."""

from app.services.reddit import deduplicate_posts


def test_deduplicate_removes_existing():
    posts = [
        {"reddit_native_id": "abc123", "title": "Post 1"},
        {"reddit_native_id": "def456", "title": "Post 2"},
        {"reddit_native_id": "ghi789", "title": "Post 3"},
    ]
    existing = {"abc123", "ghi789"}
    result = deduplicate_posts(posts, existing)
    assert len(result) == 1
    assert result[0]["reddit_native_id"] == "def456"


def test_deduplicate_removes_internal_dupes():
    posts = [
        {"reddit_native_id": "aaa", "title": "Post 1"},
        {"reddit_native_id": "aaa", "title": "Post 1 dupe"},
        {"reddit_native_id": "bbb", "title": "Post 2"},
    ]
    result = deduplicate_posts(posts, set())
    assert len(result) == 2


def test_deduplicate_empty_input():
    result = deduplicate_posts([], set())
    assert result == []


def test_deduplicate_all_existing():
    posts = [{"reddit_native_id": "x"}, {"reddit_native_id": "y"}]
    result = deduplicate_posts(posts, {"x", "y"})
    assert result == []
