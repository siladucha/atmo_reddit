"""Test script: verify automated posting works end-to-end.

Usage (inside Docker):
    docker compose exec app python scripts/test_posting.py

What it does:
1. Registers smi_parser_bot as a RedditApp
2. Configures Hot-Thought2408 for password auth posting (no proxy for test)
3. Creates a PRAW client and verifies auth works
4. Posts a test comment to r/test (a subreddit specifically for testing)
"""

import sys
import os

sys.path.insert(0, "/app")
os.environ.setdefault("DATABASE_URL", os.environ.get("DATABASE_URL", ""))

from datetime import datetime, timezone

from app.database import SessionLocal
from app.models.avatar import Avatar
from app.models.reddit_app import RedditApp
from app.services.encryption import get_encryptor


def main():
    db = SessionLocal()
    encryptor = get_encryptor()

    print("=" * 60)
    print("AUTOMATED POSTING — END-TO-END TEST")
    print("=" * 60)

    # --- Step 1: Register Reddit App ---
    print("\n[1/5] Registering Reddit App (smi_parser_bot)...")

    app = db.query(RedditApp).filter(RedditApp.client_id_reddit == "qknsE3byn2vbyZMqheuOQg").first()
    if not app:
        app = RedditApp(
            client_id_reddit="qknsE3byn2vbyZMqheuOQg",
            client_secret_encrypted=encryptor.encrypt("uipx2upS94aLUTvRs59DHrD17tU0EQ"),
            app_name="smi_parser_bot",
            app_type="script",
            registered_under_username="Hot-Thought2408",
            redirect_uri="http://localhost:8080",
            is_active=True,
            health_status="healthy",
        )
        db.add(app)
        db.commit()
        db.refresh(app)
        print(f"  Created: {app.app_name} (id={app.id})")
    else:
        print(f"  Already exists: {app.app_name} (id={app.id})")

    # --- Step 2: Configure Avatar ---
    print("\n[2/5] Configuring avatar Hot-Thought2408...")

    avatar = db.query(Avatar).filter(Avatar.reddit_username == "Hot-Thought2408").first()
    if not avatar:
        print("  ERROR: Avatar Hot-Thought2408 not found in database!")
        print("  Available avatars:")
        for a in db.query(Avatar).limit(10).all():
            print(f"    - {a.reddit_username}")
        db.close()
        return

    # Set posting fields
    avatar.reddit_password_encrypted = encryptor.encrypt("MethodB2024!")
    avatar.user_agent_string = "RAMP/1.0 (by u/Hot-Thought2408)"
    avatar.declared_timezone = "Asia/Jerusalem"
    avatar.posting_mode = "auto"
    avatar.reddit_app_id = app.id
    # No proxy for this test (direct connection)
    # avatar.proxy_url_encrypted = encryptor.encrypt("socks5://...")

    db.commit()
    print(f"  Configured: posting_mode=auto, timezone=Asia/Jerusalem")
    print(f"  Auth: password auth via {app.app_name}")

    # --- Step 3: Test PRAW Auth ---
    print("\n[3/5] Testing PRAW authentication...")

    import praw

    reddit = praw.Reddit(
        client_id="qknsE3byn2vbyZMqheuOQg",
        client_secret="uipx2upS94aLUTvRs59DHrD17tU0EQ",
        username="Hot-Thought2408",
        password="MethodB2024!",
        user_agent="RAMP/1.0 (by u/Hot-Thought2408)",
    )

    # Verify auth works
    try:
        me = reddit.user.me()
        print(f"  Authenticated as: u/{me.name}")
        print(f"  Comment karma: {me.comment_karma}")
        print(f"  Link karma: {me.link_karma}")
    except Exception as e:
        print(f"  AUTH FAILED: {e}")
        db.close()
        return

    # --- Step 4: Find a test thread ---
    print("\n[4/5] Finding a thread in r/test...")

    try:
        test_sub = reddit.subreddit("test")
        # Get the newest post in r/test
        post = next(test_sub.new(limit=1))
        print(f"  Found: '{post.title}' (id={post.id}, {post.num_comments} comments)")
    except Exception as e:
        print(f"  ERROR finding thread: {e}")
        db.close()
        return

    # --- Step 5: Post a test comment ---
    print("\n[5/5] Posting test comment...")

    test_comment = f"Automated posting test — RAMP system verification. Timestamp: {datetime.now(timezone.utc).isoformat()}"

    try:
        comment = post.reply(test_comment)
        print(f"  ✅ SUCCESS!")
        print(f"  Comment ID: {comment.id}")
        print(f"  URL: https://www.reddit.com{comment.permalink}")
        print(f"  Text: {test_comment[:80]}...")
    except Exception as e:
        print(f"  ❌ POSTING FAILED: {e}")
        db.close()
        return

    # --- Done ---
    print("\n" + "=" * 60)
    print("TEST PASSED — Automated posting works!")
    print("=" * 60)
    print(f"\nNext steps:")
    print(f"  1. Buy proxy from ProxyJet")
    print(f"  2. Set avatar.proxy_url_encrypted")
    print(f"  3. Create approved EPG slot")
    print(f"  4. Let Celery Beat pick it up automatically")

    db.close()


if __name__ == "__main__":
    main()
