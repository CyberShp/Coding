"""
Array lock model for test task exclusivity.

When a test task is running, it locks the arrays it uses to prevent
other users from starting a task on the same arrays.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func

from ..db.database import Base


class ArrayLockModel(Base):
    """Array lock database model"""
    __tablename__ = "array_locks"

    id = Column(Integer, primary_key=True, index=True)
    array_id = Column(String(64), unique=True, index=True, nullable=False)
    task_id = Column(Integer, ForeignKey("task_sessions.id"), nullable=False)
    locked_by_ip = Column(String(64), nullable=True)
    locked_by_nickname = Column(String(64), nullable=True)
    locked_at = Column(DateTime, server_default=func.now())


class ArrayLockInfo(BaseModel):
    """Array lock information"""
    array_id: str
    task_id: int
    task_name: str = ""
    locked_by_ip: str = ""
    locked_by_nickname: str = ""
    locked_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class LockConflict(BaseModel):
    """Lock conflict information"""
    array_id: str
    locked_by_task_id: int
    locked_by_task_name: str = ""
    locked_by_ip: str = ""
    locked_by_nickname: str = ""
    locked_at: Optional[datetime] = None
