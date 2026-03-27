"""
Unified alert model v2.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import json

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import Column, Integer, String, DateTime, Text, Index, ForeignKey
from sqlalchemy.sql import func

from ..db.database import Base


class AlertCategory(str, Enum):
    """Alert category enum"""
    PHYSICAL_ERROR = "physical_error"
    DROP = "drop"
    FIFO_OVERRUN = "fifo_overrun"
    GENERIC_ERROR = "generic_error"
    LINK_DOWN = "link_down"
    LINK_FLAP = "link_flap"
    CONTROLLER_REBOOT = "controller_reboot"
    CARD_MISSING = "card_missing"
    COLLECTOR_FAILURE = "collector_failure"
    OBSERVER_TIMEOUT = "observer_timeout"
    PARSE_FAILURE = "parse_failure"
    EXPECTED_TEST_EVENT = "expected_test_event"
    RECOVERY_EVENT = "recovery_event"


class AlertState(str, Enum):
    """Alert state enum"""
    ACTIVE = "active"
    MUTED = "muted"
    EXPECTED = "expected"
    RECOVERED = "recovered"
    CLOSED = "closed"


class ReviewStatus(str, Enum):
    """Review status enum"""
    PENDING = "pending"
    CONFIRMED_OK = "confirmed_ok"
    NEEDS_FOLLOWUP = "needs_followup"
    FALSE_POSITIVE = "false_positive"


# SQLAlchemy Model
class AlertV2Model(Base):
    """Unified alert database model v2"""
    __tablename__ = "alerts_v2"

    id = Column(Integer, primary_key=True, index=True)
    array_id = Column(String(64), ForeignKey("arrays.array_id"), index=True, nullable=False)
    category = Column(String(64), index=True, nullable=False)
    object_type = Column(String(64), default="")
    object_key = Column(String(256), default="")
    symptom_code = Column(String(128), default="")
    message_raw = Column(Text, nullable=False)
    message_cn = Column(Text, default="")
    evidence_json = Column(Text, default="{}")
    occurred_at = Column(DateTime, index=True, nullable=False)
    ingested_at = Column(DateTime, server_default=func.now())
    first_seen_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    fingerprint = Column(String(128), index=True)
    state = Column(String(32), index=True, default="active")
    review_status = Column(String(32), default="pending")
    is_expected = Column(Integer, default=0)
    expected_window_id = Column(Integer, ForeignKey("expected_windows.id"), nullable=True)
    mute_until = Column(DateTime, nullable=True)
    observer_name = Column(String(64), index=True)
    level = Column(String(16), index=True, default="warning")
    task_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index('ix_alerts_v2_array_occurred', 'array_id', 'occurred_at'),
        Index('ix_alerts_v2_category_state', 'category', 'state'),
        Index('ix_alerts_v2_fingerprint', 'fingerprint'),
    )


# Pydantic Models for API
class AlertV2Create(BaseModel):
    """Schema for creating alert v2"""
    array_id: str
    category: AlertCategory
    object_type: str = ""
    object_key: str = ""
    symptom_code: str = ""
    message_raw: str
    message_cn: str = ""
    evidence_json: str = "{}"
    occurred_at: datetime
    fingerprint: Optional[str] = None
    state: AlertState = AlertState.ACTIVE
    review_status: ReviewStatus = ReviewStatus.PENDING
    is_expected: int = 0
    expected_window_id: Optional[int] = None
    mute_until: Optional[datetime] = None
    observer_name: Optional[str] = None
    level: str = "warning"
    task_id: Optional[int] = None

    @field_validator('evidence_json', mode='before')
    @classmethod
    def parse_evidence(cls, v):
        if isinstance(v, dict):
            return json.dumps(v, ensure_ascii=False)
        return v if v else "{}"


class AlertV2Response(BaseModel):
    """Schema for alert v2 response"""
    id: int
    array_id: str
    category: str
    object_type: str = ""
    object_key: str = ""
    symptom_code: str = ""
    message_raw: str
    message_cn: str = ""
    evidence_json: str = "{}"
    occurred_at: datetime
    ingested_at: Optional[datetime] = None
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    fingerprint: Optional[str] = None
    state: str = "active"
    review_status: str = "pending"
    is_expected: int = 0
    expected_window_id: Optional[int] = None
    mute_until: Optional[datetime] = None
    observer_name: Optional[str] = None
    level: str = "warning"
    task_id: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator('evidence_json', mode='before')
    @classmethod
    def parse_evidence(cls, v):
        if isinstance(v, str):
            return v
        if isinstance(v, dict):
            return json.dumps(v, ensure_ascii=False)
        return "{}"


class AlertV2Stats(BaseModel):
    """Alert v2 statistics"""
    total: int
    by_category: Dict[str, int] = {}
    by_state: Dict[str, int] = {}
    by_level: Dict[str, int] = {}
    by_array: Dict[str, int] = {}
    trend_24h: List[Dict[str, Any]] = []
