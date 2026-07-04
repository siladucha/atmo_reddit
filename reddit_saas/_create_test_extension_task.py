"""Create a test ExecutionTask for browser extension testing.

Usage:
    cd reddit_saas
    python _create_test_extension_task.py

Creates an ExecutionTask with task_lifecycle_status='CREATED' that the extension
will pick up on its next poll cycle (30s). Uses Hot-Thought2408 as the avatar.

Requires: local PostgreSQL running with reddit_saas database.
"""

import uuid
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.database import SessionLocal
from app.models.execution_task import ExecutionTask
from app.models.avatar import Avatar


# ─── Configuration ──────────────────────────────────────────────────────────

# Change these for your test:
AVATAR_USERNAME = "Hot-Thought2408"
THREAD_URL = "https://www.reddit.com/r/test/comments/1l6hpng/test/"
THREAD_TITLE = "Test thread for extension prepare mode"
SUBREDDIT = "test"
COMMENT_TEXT = (
    "This is a test comment from RAMP extension prepare_only mode. "
    "If you see this text inserted in the Reddit editor but NOT submitted, "
    "the prepare pipeline is working correctly. "
    "This comment should NOT appear on Reddit."
)

# ─── Main ───────────────────────────────────────────────────────────────────


def main():
    db = SessionLocal()
    try:
        # Find avatar
        avatar = (
            db.query(Avatar)
            .filter(Avatar.reddit_username == AVATAR_USERNAME)
            .first()
        )

        if not avatar:
            print(f"❌ Avatar '{AVATAR_USERNAME}' not found in DB.")
            print("   Available avatars:")
            all_avatars = db.query(Avatar.reddit_username, Avatar.id).filter(Avatar.active == True).all()
            for a in all_avatars[:10]:
                print(f"     - {a.reddit_username} ({a.id})")
            return

        # Create task
        now = datetime.now(timezone.utc)
        task_code = f"TEST-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
        idempotency_key = f"ext-test-{uuid.uuid4().hex[:8]}"

        task = ExecutionTask(
            task_code=task_code,
            executor_token=uuid.uuid4(),
            avatar_id=avatar.id,
            client_id=uuid.UUID(avatar.client_ids[0]) if avatar.client_ids else None,
            avatar_username=AVATAR_USERNAME,
            client_name="Test Client",
            executor_contact="test@ramp.local",
            executor_type="admin",
            delivery_channel="extension",
            task_type="post_comment",
            subreddit=SUBREDDIT,
            thread_url=THREAD_URL,
            thread_title=THREAD_TITLE,
            generated_text=COMMENT_TEXT,
            scheduled_at=None,  # Immediate
            deadline=now + timedelta(hours=4),
            status="generated",
            # Extension-specific fields:
            task_lifecycle_status="CREATED",
            idempotency_key=idempotency_key,
            priority="content",
        )

        db.add(task)
        db.commit()
        db.refresh(task)

        print("✅ Extension test task created!")
        print(f"   Task ID:     {task.id}")
        print(f"   Task Code:   {task_code}")
        print(f"   Avatar:      {AVATAR_USERNAME}")
        print(f"   Subreddit:   r/{SUBREDDIT}")
        print(f"   Thread:      {THREAD_URL}")
        print(f"   Idempotency: {idempotency_key}")
        print(f"   Lifecycle:   CREATED (ready for extension pickup)")
        print()
        print("   Next steps:")
        print("   1. Extension will fetch this task within 30 seconds")
        print("   2. Task appears in popup 'Needs Review' section")
        print("   3. Click 'Prepare' to start prepare_only execution")
        print("   4. Extension opens Reddit, inserts text, does NOT submit")
        print("   5. Proof appears in popup 'Execution State' panel")

    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
