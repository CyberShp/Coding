"""
Scheduler models for scheduled tasks.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON
from sqlalchemy.sql import func

from ..db.database import Base


# SQLAlchemy Models

class ScheduledTaskModel(Base):
    """Scheduled task model"""
    __tablename__ = "scheduled_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    query_template_id = Column(Integer, nullable=True)  # Reference to query template
    command = Column(Text, nullable=True)  # Or direct command
    cron_expr = Column(String(64), nullable=False)  # Cron expression
    array_ids = Column(JSON, default=list)  # List of array IDs to run on
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)


class TaskResultModel(Base):
    """Task execution result"""
    __tablename__ = "task_results"
    
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, index=True, nullable=False)
    task_name = Column(String(128), nullable=True)
    array_id = Column(String(64), index=True, nullable=True)
    status = Column(String(32), default="pending")  # pending, running, success, failed
    output = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    executed_at = Column(DateTime, server_default=func.now())


# Pydantic Models

class ScheduledTaskCreate(BaseModel):
    """Create scheduled task"""
    name: str
    description: Optional[str] = None
    query_template_id: Optional[int] = None
    command: Optional[str] = None
    cron_expr: str
    array_ids: List[str] = []
    enabled: bool = True


class ScheduledTaskUpdate(BaseModel):
    """Update scheduled task"""
    name: Optional[str] = None
    description: Optional[str] = None
    query_template_id: Optional[int] = None
    command: Optional[str] = None
    cron_expr: Optional[str] = None
    array_ids: Optional[List[str]] = None
    enabled: Optional[bool] = None


class ScheduledTaskResponse(BaseModel):
    """Scheduled task response"""
    id: int
    name: str
    description: Optional[str] = None
    query_template_id: Optional[int] = None
    command: Optional[str] = None
    cron_expr: str
    array_ids: List[str] = []
    enabled: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


class TaskResultResponse(BaseModel):
    """Task result response"""
    id: int
    task_id: int
    task_name: Optional[str] = None
    array_id: Optional[str] = None
    status: str
    output: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)
