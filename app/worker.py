import os
from celery import Celery
from app.redis_client import sweep_dirty_segments, redis_client
from app.database import SessionLocal
from app.evaluator import process_segment_run
from app.models import TriggerType
import time
from app.models import TriggerType, SegmentDeltaMember, DeltaAction

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("drift_worker", broker=REDIS_URL)

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
        
        if run.added_count > 0 or run.removed_count > 0:
            campaign_consumer_task.delay(run.id)
            
        return run.id
    except Exception as e:
        print(f"❌ Failed to evaluate Segment {segment_id}: {str(e)}")
        raise e
    finally:
        db.close()
        redis_client.delete(lock_key)


@celery_app.task(bind=True)
def campaign_consumer_task(self, run_id: int):
    """
    Acts as a background consumer that listens for segment changes.
    It fetches the exact Delta payload for the run and "reacts" to it.
    """
    db = SessionLocal()
    try:
        # Fetch the explicit +/- delta for this specific run
        deltas = db.query(SegmentDeltaMember).filter(
            SegmentDeltaMember.run_id == run_id
        ).all()

        if not deltas:
            return "No changes to consume."

        print(f"📣 CAMPAIGN CONSUMER triggered for Run {run_id}")
        
        for delta in deltas:
            if delta.action == DeltaAction.ADDED:
                print(f"   [+] Sending 'Welcome to the Segment' email to User {delta.user_id}")
            elif delta.action == DeltaAction.REMOVED:
                print(f"   [-] Sending 'We Miss You' discount to User {delta.user_id}")
                
        return f"Consumed {len(deltas)} delta events."
    finally:
        db.close()