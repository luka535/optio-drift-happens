from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Enum, JSON, Boolean, Table
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from .database import Base

class SegmentType(str, enum.Enum):
    DYNAMIC = "dynamic"
    STATIC = "static"

class RunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"

class TriggerType(str, enum.Enum):
    MUTATION = "mutation"
    PERIODIC = "periodic"
    MANUAL = "manual"
    CASCADE = "cascade"

class DeltaAction(str, enum.Enum):
    ADDED = "added"
    REMOVED = "removed"


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    transactions = relationship("Transaction", back_populates="user")
    memberships = relationship("SegmentMembershipCurrent", back_populates="user")


class Transaction(Base):
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Integer, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    user = relationship("User", back_populates="transactions")


class Segment(Base):
    __tablename__ = "segments"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    type = Column(Enum(SegmentType), nullable=False)
    rules_json = Column(JSON, nullable=True)  
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    memberships = relationship("SegmentMembershipCurrent", back_populates="segment")
    runs = relationship("SegmentRun", back_populates="segment")
    
    children = relationship(
        "SegmentDependency",
        foreign_keys="[SegmentDependency.parent_segment_id]",
        back_populates="parent"
    )
    parents = relationship(
        "SegmentDependency",
        foreign_keys="[SegmentDependency.child_segment_id]",
        back_populates="child"
    )


class SegmentDependency(Base):
    __tablename__ = "segment_dependencies"
    
    parent_segment_id = Column(Integer, ForeignKey("segments.id"), primary_key=True)
    child_segment_id = Column(Integer, ForeignKey("segments.id"), primary_key=True)
    
    parent = relationship("Segment", foreign_keys=[parent_segment_id], back_populates="children")
    child = relationship("Segment", foreign_keys=[child_segment_id], back_populates="parents")


class SegmentMembershipCurrent(Base):
    """Snapshot of who is currently in the segment right now."""
    __tablename__ = "segment_memberships_current"
    
    segment_id = Column(Integer, ForeignKey("segments.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())
    
    segment = relationship("Segment", back_populates="memberships")
    user = relationship("User", back_populates="memberships")


class SegmentRun(Base):
    """Audit log of every time a segment is evaluated and delta is generated."""
    __tablename__ = "segment_runs"
    
    id = Column(Integer, primary_key=True, index=True)
    segment_id = Column(Integer, ForeignKey("segments.id"), nullable=False, index=True)
    status = Column(Enum(RunStatus), default=RunStatus.PENDING)
    trigger_type = Column(Enum(TriggerType), nullable=False)
    
    added_count = Column(Integer, default=0)
    removed_count = Column(Integer, default=0)
    
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    segment = relationship("Segment", back_populates="runs")
    deltas = relationship("SegmentDeltaMember", back_populates="run")


class SegmentDeltaMember(Base):
    """The explicit +/- list for a specific run. Required for the assignment criteria."""
    __tablename__ = "segment_delta_members"
    
    run_id = Column(Integer, ForeignKey("segment_runs.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    action = Column(Enum(DeltaAction), primary_key=True) 
    
    run = relationship("SegmentRun", back_populates="deltas")