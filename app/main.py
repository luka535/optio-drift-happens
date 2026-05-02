import os
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List

from app.database import engine, Base, get_db
from app import models, schemas
from app.evaluator import process_segment_run
from app.redis_client import mark_segments_dirty

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Drift Happens API", version="1.0.0")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/", response_class=HTMLResponse)
def serve_ui():
    with open(os.path.join("app", "static", "index.html"), "r", encoding="utf-8") as f:
        return f.read()

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "Segment drift system is online."}


@app.post("/api/segments/{segment_id}/evaluate", response_model=schemas.SegmentRunOut)
def evaluate_segment_endpoint(segment_id: int, db: Session = Depends(get_db)):
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

    runs = db.query(models.SegmentRun).filter(
        models.SegmentRun.segment_id == segment_id
    ).order_by(models.SegmentRun.started_at.desc()).all()
    return runs

@app.get("/api/runs/{run_id}/delta", response_model=List[schemas.DeltaMemberOut])
def get_run_delta(run_id: int, db: Session = Depends(get_db)):

    deltas = db.query(models.SegmentDeltaMember).filter(
        models.SegmentDeltaMember.run_id == run_id
    ).all()
    return deltas

@app.get("/api/activity")
def get_recent_activity(db: Session = Depends(get_db)):
    deltas = db.query(
        models.SegmentDeltaMember.action,
        models.User.name.label("user_name"),
        models.Segment.name.label("segment_name"),
        models.SegmentRun.completed_at
    ).join(models.User, models.SegmentDeltaMember.user_id == models.User.id)\
     .join(models.SegmentRun, models.SegmentDeltaMember.run_id == models.SegmentRun.id)\
     .join(models.Segment, models.SegmentRun.segment_id == models.Segment.id)\
     .order_by(desc(models.SegmentRun.completed_at), desc(models.SegmentDeltaMember.run_id))\
     .limit(10).all()
    
    return [
        {
            "action": d.action,
            "user": d.user_name,
            "segment": d.segment_name,
            "time": d.completed_at.strftime("%H:%M:%S") if d.completed_at else "Pending"
        } for d in deltas
    ]

@app.post("/api/simulations/transactions", response_model=dict)
def simulate_new_transaction(tx_in: schemas.TransactionCreate, db: Session = Depends(get_db)):

    user = db.query(models.User).filter(models.User.id == tx_in.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_tx = models.Transaction(user_id=tx_in.user_id, amount=tx_in.amount)
    db.add(new_tx)
    stat = db.query(models.UserStat).filter(models.UserStat.user_id == tx_in.user_id).first()
    if stat:
        stat.total_spend += tx_in.amount
        stat.transaction_count += 1
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

@app.post("/api/simulations/users", response_model=schemas.UserOut)
def create_new_user(user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    new_user = models.User(name=user_in.name)
    db.add(new_user)
    db.flush()    
    db.add(models.UserStat(user_id=new_user.id, total_spend=0, transaction_count=0))
    db.commit() 
    return new_user

@app.post("/api/simulations/bulk", response_model=dict)
def simulate_bulk_transactions(bulk_in: schemas.BulkTransactionCreate, db: Session = Depends(get_db)):

    user = db.query(models.User).filter(models.User.id == bulk_in.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    transactions = [
        models.Transaction(user_id=bulk_in.user_id, amount=bulk_in.amount)
        for _ in range(bulk_in.count)
    ]
    db.add_all(transactions)
    stat = db.query(models.UserStat).filter(models.UserStat.user_id == bulk_in.user_id).first()
    if stat:
        stat.total_spend += (bulk_in.amount * bulk_in.count)
        stat.transaction_count += bulk_in.count
    db.commit()

    dynamic_segments = db.query(models.Segment.id).filter(
        models.Segment.type == models.SegmentType.DYNAMIC
    ).all()
    segment_ids = [s[0] for s in dynamic_segments]
    
    from app.redis_client import mark_segments_dirty
    mark_segments_dirty(segment_ids)

    return {
        "message": f"Successfully injected {bulk_in.count} transactions for User {bulk_in.user_id}",
        "note": "Watch the Celery worker - it will only evaluate the segments ONE time!"
    }

@app.get("/api/users", response_model=List[schemas.UserOut])
def get_all_users(db: Session = Depends(get_db)):
    return db.query(models.User).order_by(models.User.id).all()