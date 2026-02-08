"""
Test Task Session data model.

Represents a testing session with start/end times, linked arrays,
and automatic alert tagging.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.sql import func

from ..db.database import Base


class TaskSessionModel(Base):
    """Test task session database model"""
    __tablename__ = "task_sessions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(256), nullable=False)
    task_type = Column(String(64), nullable=False)  # normal_business, controller_poweroff, etc.
    array_ids = Column(Text, default="")  # JSON array of array_id strings
    notes = Column(Text, default="")
    status = Column(String(16), default="created")  # created, running, completed
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


# Task types
TASK_TYPES = {
    'normal_business': '正常业务',
    'controller_poweroff': '控制器下电',
    'card_poweroff': '接口卡下电',
    'port_toggle': '端口开关',
    'cable_pull': '线缆拔插',
    'fault_injection': '系统故障注入',
    'controller_upgrade': '控制器升级',
    'custom': '自定义',
}


class TaskSessionCreate(BaseModel):
    """Schema for creating a test task"""
    name: str
    task_type: str = 'custom'
    array_ids: List[str] = []
    notes: str = ''


class TaskSessionResponse(BaseModel):
    """Schema for task response"""
    id: int
    name: str
    task_type: str
    task_type_label: str = ''
    array_ids: List[str] = []
    notes: str = ''
    status: str = 'created'
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    alert_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class TaskSummary(BaseModel):
    """Summary generated when task ends"""
    task_id: int
    name: str
    task_type: str
    duration_seconds: float = 0
    alert_total: int = 0
    by_level: Dict[str, int] = {}
    by_observer: Dict[str, int] = {}
    critical_events: List[Dict[str, Any]] = []
