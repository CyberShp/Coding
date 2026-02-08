"""
Array State Snapshot model.

Captures full array state at a point in time for later comparison.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func

from ..db.database import Base


class SnapshotModel(Base):
    """Snapshot database model"""
    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True, index=True)
    array_id = Column(String(64), index=True, nullable=False)
    label = Column(String(256), default="")
    task_id = Column(Integer, nullable=True)
    data = Column(Text, default="{}")  # JSON snapshot of all observer states
    created_at = Column(DateTime, server_default=func.now())


class SnapshotResponse(BaseModel):
    id: int
    array_id: str
    label: str = ""
    task_id: Optional[int] = None
    created_at: Optional[datetime] = None
    data: Dict[str, Any] = {}
    model_config = ConfigDict(from_attributes=True)


class SnapshotDiffResponse(BaseModel):
    snapshot_a: SnapshotResponse
    snapshot_b: SnapshotResponse
    changes: List[Dict[str, Any]] = []  # list of { category, key, before, after, change_type }
