from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
from .models import SegmentType, RunStatus, TriggerType, DeltaAction

class SegmentBase(BaseModel):
    name: str
    type: SegmentType
    rules_json: Optional[Dict[str, Any]] = None

class SegmentCreate(SegmentBase):
    pass

class SegmentOut(SegmentBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

class UserOut(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True

class SegmentRunOut(BaseModel):
    id: int
    segment_id: int
    status: RunStatus
    trigger_type: TriggerType
    added_count: int
    removed_count: int
    started_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True

class DeltaMemberOut(BaseModel):
    user_id: int
    action: DeltaAction

    class Config:
        from_attributes = True

class TransactionCreate(BaseModel):
    user_id: int
    amount: int 