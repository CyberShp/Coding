"""
Alert model definitions.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import json

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import Column, Integer, String, DateTime, Text, Index
from sqlalchemy.sql import func

from ..db.database import Base


class AlertLevel(str, Enum):
    """Alert level enum"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# SQLAlchemy Model
class AlertModel(Base):
    """Alert database model"""
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True, index=True)
    array_id = Column(String(64), index=True, nullable=False)
    observer_name = Column(String(64), index=True, nullable=False)
    level = Column(String(16), index=True, nullable=False)
    message = Column(Text, nullable=False)
    details = Column(Text, default="{}")  # JSON string
    timestamp = Column(DateTime, index=True, nullable=False)
    task_id = Column(Integer, nullable=True, index=True)  # Link to test task session
    created_at = Column(DateTime, server_default=func.now())
    
    __table_args__ = (
        Index('ix_alerts_array_timestamp', 'array_id', 'timestamp'),
        Index('ix_alerts_level_timestamp', 'level', 'timestamp'),
        Index('ix_alerts_array_observer_ts', 'array_id', 'observer_name', 'timestamp'),
    )


# Pydantic Models for API
class AlertBase(BaseModel):
    """Base alert schema"""
    observer_name: str
    level: AlertLevel
    message: str
    details: Dict[str, Any] = {}
    timestamp: datetime

    @field_validator('details', mode='before')
    @classmethod
    def parse_details(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return {}
        return v if v is not None else {}


class AlertCreate(AlertBase):
    """Schema for creating alert"""
    array_id: str


class AlertResponse(AlertBase):
    """Schema for alert response"""
    id: int
    array_id: str
    array_name: Optional[str] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class AlertStats(BaseModel):
    """Alert statistics"""
    total: int
    by_level: Dict[str, int]
    by_observer: Dict[str, int]
    by_array: Dict[str, int]
    trend_24h: List[Dict[str, Any]] = []


class Alert(AlertBase):
    """Full alert model"""
    id: int
    array_id: str
    array_name: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)
