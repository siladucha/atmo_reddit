"""Shared proxy that makes a HobbySubreddit look like a RedditThread for templates.

Used by: admin review queue, avatar workflow, portal review — anywhere we need
to display hobby draft context in a template designed for RedditThread objects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.hobby import HobbySubreddit


class HobbyThreadProxy:
    """Lightweight proxy that makes a HobbySubreddit look like a RedditThread for templates.

    Provides all attributes that templates access from `item.thread`:
    - subreddit, post_title, post_body, url (for "Open thread on Reddit" link)
    - author, ups, score, comment_count (stats row)
    - is_locked, type (badges)
    - created_at, reddit_created_at (age display)
    - comments_json (for comment count computation — always None for hobby)
    """

    def __init__(self, hobby_post: "HobbySubreddit"):
        self.subreddit = hobby_post.subreddit or ""
        self.post_title = hobby_post.post_title or "(hobby post)"
        self.post_body = hobby_post.post_body or ""
        self.author = hobby_post.author or ""
        self.ups = hobby_post.post_ups or 0
        self.score = hobby_post.post_ups or 0
        self.comment_count = 0
        self.is_locked = False
        self.type = "hobby"
        self.comments_json = None
        self.created_at = hobby_post.scraped_at or hobby_post.created_at
        self.reddit_created_at = hobby_post.scraped_at or hobby_post.created_at

        # Build a proper Reddit URL from permalink or url
        if hobby_post.permalink:
            self.url = (
                f"https://www.reddit.com{hobby_post.permalink}"
                if not hobby_post.permalink.startswith("http")
                else hobby_post.permalink
            )
        elif hobby_post.url:
            self.url = hobby_post.url
        else:
            self.url = f"https://www.reddit.com/r/{hobby_post.subreddit}/" if hobby_post.subreddit else ""
