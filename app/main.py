from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database import engine, Base, get_db
from app import models, schemas
from app.evaluator import process_segment_run
from app.redis_client import mark_segments_dirty

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Drift Happens API", version="1.0.0")

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "Segment drift system is online."}


@app.post("/api/segments/{segment_id}/evaluate", response_model=schemas.SegmentRunOut)
def evaluate_segment_endpoint(segment_id: int, db: Session = Depends(get_db)):
    """
    (Manual) Triggers an evaluation of a segment.
    In a real scenario, this is called by the Celery worker for dynamic segments,
    and called by the UI for static segment manual refresh.
    """
    segment = db.query(models.Segment).filter(models.Segment.id == segment_id).first()
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
        
    trigger = models.TriggerType.MANUAL if segment.type == models.SegmentType.STATIC else models.TriggerType.MUTATION
        
    try:
        run = process_segment_run(db, segment_id=segment_id, trigger=trigger)
        return run
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/segments/{segment_id}/members", response_model=List[schemas.UserOut])
def get_segment_members(segment_id: int, db: Session = Depends(get_db)):

    users = db.query(models.User).join(models.SegmentMembershipCurrent).filter(
        models.SegmentMembershipCurrent.segment_id == segment_id
    ).all()
    return users

@app.get("/api/segments/{segment_id}/runs", response_model=List[schemas.SegmentRunOut])
def get_segment_runs(segment_id: int, db: Session = Depends(get_db)):
    """
    Returns the history of evaluations for a segment.
    """
    runs = db.query(models.SegmentRun).filter(
        models.SegmentRun.segment_id == segment_id
    ).order_by(models.SegmentRun.started_at.desc()).all()
    return runs

@app.get("/api/runs/{run_id}/delta", response_model=List[schemas.DeltaMemberOut])
def get_run_delta(run_id: int, db: Session = Depends(get_db)):
    """
    Implements the Claim-Check/Large Payload pattern.
    Consumers fetch the exact Added/Removed list via this endpoint using the run_id.
    """
    deltas = db.query(models.SegmentDeltaMember).filter(
        models.SegmentDeltaMember.run_id == run_id
    ).all()
    return deltas

@app.post("/api/simulations/transactions", response_model=dict)
def simulate_new_transaction(tx_in: schemas.TransactionCreate, db: Session = Depends(get_db)):

    user = db.query(models.User).filter(models.User.id == tx_in.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_tx = models.Transaction(user_id=tx_in.user_id, amount=tx_in.amount)
    db.add(new_tx)
    db.commit()
    db.refresh(new_tx)

    dynamic_segments = db.query(models.Segment.id).filter(
        models.Segment.type == models.SegmentType.DYNAMIC
    ).all()
    
    segment_ids = [s[0] for s in dynamic_segments]
    mark_segments_dirty(segment_ids)

    return {
        "message": "Transaction added successfully", 
        "transaction_id": new_tx.id,
        "note": f"Marked {len(segment_ids)} segments as dirty in Redis."
    }