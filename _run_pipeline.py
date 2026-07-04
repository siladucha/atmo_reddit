"""One-off: create execution task + send email for Hot-Thought2408."""
import uuid
from datetime import datetime, timezone, timedelta
from app.database import SessionLocal
from app.models.epg_slot import EPGSlot
from app.models.comment_draft import CommentDraft
from app.models.execution_task import ExecutionTask
from app.services.settings import get_setting_int
from app.services.execution_tasks import generate_task_code, dispatch_delivery

db = SessionLocal()
slot_id = uuid.UUID("d63b1f6d-3182-4a82-a1fe-dd13e968cd8e")

slot = db.query(EPGSlot).filter(EPGSlot.id == slot_id).first()
avatar_obj = slot.avatar
executor_contact = avatar_obj.executor_email

draft = db.query(CommentDraft).filter(CommentDraft.id == slot.draft_id).first()
generated_text = draft.edited_draft or draft.ai_draft or ""

thread_url = ""
if slot.hobby_post_id:
    from app.models.hobby import HobbySubreddit
    hp = db.query(HobbySubreddit).filter(HobbySubreddit.id == slot.hobby_post_id).first()
    if hp and hp.url:
        thread_url = hp.url
if not thread_url:
    thread_url = "https://reddit.com/r/" + (slot.subreddit or "")

deadline_hours = get_setting_int(db, "email_tasks_deadline_hours", default=4)
deadline = (slot.scheduled_at or datetime.now(timezone.utc)) + timedelta(hours=deadline_hours)

from app.models.client import Client
client = db.query(Client).filter(Client.id == slot.client_id).first()

task = ExecutionTask(
    id=uuid.uuid4(),
    task_code=generate_task_code(db),
    executor_token=uuid.uuid4(),
    epg_slot_id=slot_id,
    draft_id=slot.draft_id,
    avatar_id=slot.avatar_id,
    client_id=slot.client_id,
    thread_id=slot.thread_id,
    executor_contact=executor_contact,
    executor_type="admin",
    delivery_channel="email",
    task_type="comment",
    subreddit=slot.subreddit or "",
    thread_url=thread_url,
    thread_title=slot.thread_title or "",
    avatar_username=avatar_obj.reddit_username,
    client_name=client.client_name if client else "",
    generated_text=generated_text,
    scheduled_at=slot.scheduled_at,
    deadline=deadline,
    status="generated",
    status_history=[{"status": "generated", "at": datetime.now(timezone.utc).isoformat(), "by": "system"}],
    delivery_count=0,
)

try:
    db.add(task)
    db.commit()
    db.refresh(task)
    print(f"CREATED: {task.task_code} text_len={len(task.generated_text)}")

    # Send email
    r = dispatch_delivery(db, task.id)
    if r:
        print(f"EMAIL: status={r.status}")
        if r.error:
            print(f"  error: {r.error}")
    else:
        print("EMAIL: dispatch returned None")
except Exception as e:
    db.rollback()
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

db.close()
print("Done.")
