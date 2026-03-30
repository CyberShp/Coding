"""
Observer snapshot model for tracking observer execution status.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, DateTime, Text, UniqueConstraint
from sqlalchemy.sql import func

from ..db.database import Base


# SQLAlchemy Model
class ObserverSnapshotModel(Base):
    """Observer snapshot database model"""
    __tablename__ = "observer_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    array_id = Column(String(64), index=True, nullable=False)
    observer_name = Column(String(64), nullable=False)
    last_run_at = Column(DateTime)
    last_success_at = Column(DateTime, nullable=True)
    last_failure_reason = Column(Text, default="")
    avg_duration_ms = Column(Integer, default=0)
    is_enabled = Column(Integer, default=1)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('array_id', 'observer_name', name='uq_observer_snapshot_array_observer'),
    )


# Pydantic Models for API
class ObserverSnapshotResponse(BaseModel):
    """Schema for observer snapshot response"""
    id: int
    array_id: str
    observer_name: str
    last_run_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_failure_reason: str = ""
    avg_duration_ms: int = 0
    is_enabled: int = 1
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
