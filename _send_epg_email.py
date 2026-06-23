"""One-off script: create execution tasks from today's approved EPG slots and send emails."""
import uuid
from app.database import SessionLocal
from app.services.execution_tasks import create_execution_task, dispatch_delivery
from app.models.epg_slot import EPGSlot
from app.models.execution_task import ExecutionTask

db = SessionLocal()

slot_ids = [
    "4c103b43-62d3-4dc8-b78f-d5c92d136fd6",  # yoga 14:35
    "92be6ab3-7534-49f4-b055-4053690a61eb",  # Biohackers 17:31
    "33142047-9147-417c-addb-a3d78c09ec88",  # whoop 20:31
]

for slot_id in slot_ids:
    sid = uuid.UUID(slot_id)
    existing = db.query(ExecutionTask).filter(ExecutionTask.epg_slot_id == sid).first()
    if existing:
        print(f"Slot {slot_id[:8]}... already has task {existing.task_code} (status={existing.status})")
        if existing.status == "generated":
            result = dispatch_delivery(db, existing.id)
            if result and result.status == "sent":
                print("  -> Email sent!")
            else:
                err = result.error if result else "no result"
                print(f"  -> Send failed: {err}")
        elif existing.status == "emailed":
            print("  -> Already emailed, skipping")
        continue

    task = create_execution_task(db, sid)
    if task:
        print(f"Created task: {task.task_code} for r/{task.subreddit} at {task.scheduled_at}")
        result = dispatch_delivery(db, task.id)
        if result and result.status == "sent":
            print(f"  -> Email sent to {task.executor_contact}!")
        else:
            err = result.error if result else "no result"
            print(f"  -> Send failed: {err}")
    else:
        print(f"Failed to create task for slot {slot_id[:8]}...")

db.close()
print("\nDone.")
