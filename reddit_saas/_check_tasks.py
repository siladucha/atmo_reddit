from app.database import SessionLocal
from app.models.execution_task import ExecutionTask
from app.models.delivery_attempt import DeliveryAttempt
from sqlalchemy import desc, func
from datetime import datetime, timedelta, timezone

db = SessionLocal()
now = datetime.now(timezone.utc)
yesterday = now - timedelta(hours=48)

tasks = db.query(ExecutionTask).filter(ExecutionTask.created_at >= yesterday).order_by(desc(ExecutionTask.created_at)).limit(30).all()
print(f"=== ExecutionTasks last 48h: {len(tasks)} ===")
for t in tasks:
    ts = t.created_at.strftime("%m-%d %H:%M") if t.created_at else "?"
    sched = t.scheduled_at.strftime("%H:%M") if t.scheduled_at else "?"
    print(f"  {ts} | status={t.status} | sched={sched} | code={t.task_code}")

print()

# Check delivery attempts
deliveries = db.query(DeliveryAttempt).filter(DeliveryAttempt.created_at >= yesterday).order_by(desc(DeliveryAttempt.created_at)).limit(20).all()
print(f"=== DeliveryAttempts last 48h: {len(deliveries)} ===")
for d in deliveries:
    ts = d.created_at.strftime("%m-%d %H:%M") if d.created_at else "?"
    print(f"  {ts} | channel={d.channel} | recipient={d.recipient} | success={d.success}")

print()

# Count by status
status_counts = db.query(ExecutionTask.status, func.count()).group_by(ExecutionTask.status).all()
print("=== All-time status distribution ===")
for status, count in status_counts:
    print(f"  {status}: {count}")

db.close()
