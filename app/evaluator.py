from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Set, List
from .models import (
    Segment, SegmentMembershipCurrent, SegmentRun, 
    SegmentDeltaMember, Transaction, TriggerType, RunStatus, DeltaAction
)
from app.redis_client import mark_segments_dirty
from app.models import SegmentDependency

def evaluate_dynamic_rules(db: Session, rules_json: dict) -> Set[int]:
    """
    Parses our JSON DSL rules and returns a set of user_ids that match.
    """
    if not rules_json:
        return set()

    field = rules_json.get("field")
    op = rules_json.get("op")
    value = rules_json.get("value")

    if field == "transaction_count" and op == ">=":
        results = db.query(Transaction.user_id).group_by(Transaction.user_id).having(func.count() >= value).all()
        return {r[0] for r in results}

    elif field == "total_spend" and op == ">":
        value_in_cents = value * 100 
        results = db.query(Transaction.user_id).group_by(Transaction.user_id).having(func.sum(Transaction.amount) > value_in_cents).all()
        return {r[0] for r in results}

    elif field == "segment_id" and op == "in":
        target_segment_ids = value
        results = db.query(SegmentMembershipCurrent.user_id).filter(
            SegmentMembershipCurrent.segment_id.in_(target_segment_ids)
        ).all()
        return {r[0] for r in results}

    return set()


def process_segment_run(db: Session, segment_id: int, trigger: TriggerType) -> SegmentRun:
    """
    Evaluates the segment, calculates the +/- Delta, and updates the database.
    This exactly matches Section 6 of your Master Plan.
    """
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    if not segment:
        raise ValueError(f"Segment {segment_id} not found")

    new_user_ids = evaluate_dynamic_rules(db, segment.rules_json)

    current_memberships = db.query(SegmentMembershipCurrent.user_id).filter(
        SegmentMembershipCurrent.segment_id == segment_id
    ).all()
    old_user_ids = {m[0] for m in current_memberships}

    added_ids = new_user_ids - old_user_ids
    removed_ids = old_user_ids - new_user_ids

    run = SegmentRun(
        segment_id=segment.id,
        trigger_type=trigger,
        status=RunStatus.RUNNING,
        added_count=len(added_ids),
        removed_count=len(removed_ids)
    )
    db.add(run)
    db.flush()

    delta_records = []
    for uid in added_ids:
        delta_records.append(SegmentDeltaMember(run_id=run.id, user_id=uid, action=DeltaAction.ADDED))
        db.add(SegmentMembershipCurrent(segment_id=segment.id, user_id=uid))
        
    for uid in removed_ids:
        delta_records.append(SegmentDeltaMember(run_id=run.id, user_id=uid, action=DeltaAction.REMOVED))
        db.query(SegmentMembershipCurrent).filter(
            SegmentMembershipCurrent.segment_id == segment.id,
            SegmentMembershipCurrent.user_id == uid
        ).delete()

    if delta_records:
        db.add_all(delta_records)

    run.status = RunStatus.SUCCESS
    run.completed_at = func.now()
    
    db.commit()
    db.refresh(run)
    if run.added_count > 0 or run.removed_count > 0:
        children = db.query(SegmentDependency.child_segment_id).filter(
            SegmentDependency.parent_segment_id == segment.id
        ).all()
        
        child_ids = [c[0] for c in children]
        if child_ids:
            # Send the signal to Redis!
            mark_segments_dirty(child_ids)
                
    return run