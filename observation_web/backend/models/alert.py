"""
Alert model definitions.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import json

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import Column, Integer, String, DateTime, Text, Index, ForeignKey
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
    is_expected = Column(Integer, default=0)  # 0=unknown, 1=expected, -1=unexpected
    matched_rule_id = Column(Integer, nullable=True)  # ID of the rule that matched
    created_at = Column(DateTime, server_default=func.now())
    
    __table_args__ = (
        Index('ix_alerts_array_timestamp', 'array_id', 'timestamp'),
        Index('ix_alerts_level_timestamp', 'level', 'timestamp'),
        Index('ix_alerts_array_observer_ts', 'array_id', 'observer_name', 'timestamp'),
        Index('ix_alerts_is_expected', 'is_expected'),
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
    is_acked: bool = False
    is_expected: int = 0  # 0=unknown, 1=expected, -1=unexpected
    matched_rule_id: Optional[int] = None
    task_id: Optional[int] = None
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


# ---------------------------------------------------------------------------
# Alert Acknowledgement
# ---------------------------------------------------------------------------

class AckType(str, Enum):
    """Acknowledgement type"""
    DISMISS = "dismiss"            # Temporarily hide (default, expires in 24h)
    CONFIRMED_OK = "confirmed_ok"  # Permanently confirmed as non-issue
    DEFERRED = "deferred"          # Acknowledged but revisit later (user-set expiry)


class AlertAckModel(Base):
    """Alert acknowledgement record"""
    __tablename__ = "alert_acknowledgements"

    id = Column(Integer, primary_key=True, index=True)
    alert_id = Column(Integer, ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, index=True)
    acked_by_ip = Column(String(64), nullable=False)
    acked_at = Column(DateTime, server_default=func.now())
    comment = Column(Text, default="")
    ack_type = Column(String(32), default="dismiss")       # dismiss | confirmed_ok | deferred
    ack_expires_at = Column(DateTime, nullable=True)        # NULL = no expiry (confirmed_ok)
    note = Column(Text, default="")                         # Detailed reason / notes

    __table_args__ = (
        Index('ix_ack_alert_id', 'alert_id'),
    )


class AlertAckCreate(BaseModel):
    """Schema for creating acknowledgements (batch)"""
    alert_ids: List[int]
    comment: str = ""
    ack_type: str = "dismiss"           # dismiss | confirmed_ok | deferred
    expires_hours: Optional[int] = None  # For deferred or confirmed_ok: 2/4/6/8/12/24


class AlertAckResponse(BaseModel):
    """Schema for acknowledgement response"""
    id: int
    alert_id: int
    acked_by_ip: str
    acked_at: datetime
    comment: str = ""
    ack_type: str = "dismiss"
    ack_expires_at: Optional[datetime] = None
    note: str = ""
    acked_by_nickname: Optional[str] = None  # Resolved from user_sessions

    model_config = ConfigDict(from_attributes=True)
