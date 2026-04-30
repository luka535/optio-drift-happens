from celery import Celery
from app.redis_client import sweep_dirty_segments, redis_client
from app.database import SessionLocal
from app.evaluator import process_segment_run
from app.models import TriggerType
import time

celery_app = Celery("drift_worker", broker="redis://localhost:6379/0")

@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(5.0, sweep_and_dispatch.s(), name='sweep-dirty-segments')

@celery_app.task
def sweep_and_dispatch():
    dirty_ids = sweep_dirty_segments()
    if dirty_ids:
        print(f"🧹 Swept {len(dirty_ids)} dirty segments. Dispatching workers...")
        for sid in dirty_ids:
            evaluate_segment_task.delay(sid)

@celery_app.task(bind=True)
def evaluate_segment_task(self, segment_id: int):
    lock_key = f"lock:segment:{segment_id}"
    
    acquired = redis_client.set(lock_key, "locked", nx=True, ex=60)
    if not acquired:
        print(f"🔒 Segment {segment_id} is already being evaluated. Skipping.")
        return "Locked"

    db = SessionLocal()
    try:
        run = process_segment_run(db, segment_id, TriggerType.MUTATION)
        print(f"✅ Evaluated Segment {segment_id} | Added: {run.added_count} | Removed: {run.removed_count}")
        return run.id
    except Exception as e:
        print(f"❌ Failed to evaluate Segment {segment_id}: {str(e)}")
        raise e
    finally:
        db.close()
        redis_client.delete(lock_key)