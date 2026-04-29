from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from .models import SegmentType

class SegmentBase(BaseModel):
    name: str
    type: SegmentType
    rules_json: Optional[Dict[str, Any]] = None

class SegmentCreate(SegmentBase):
    pass

class SegmentOut(SegmentBase):
    id: int

    class Config:
        from_attributes = True

class UserOut(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True