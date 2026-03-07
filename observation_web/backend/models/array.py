"""
Array model definitions.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.sql import func

from ..db.database import Base


class ConnectionState(str, Enum):
    """Connection state enum"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


# SQLAlchemy Model
class ArrayModel(Base):
    """Array database model"""
    __tablename__ = "arrays"

    id = Column(Integer, primary_key=True, index=True)
    array_id = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(128), nullable=False)
    host = Column(String(256), nullable=False, unique=True, index=True)
    port = Column(Integer, default=22)
    username = Column(String(64), default="root")
    key_path = Column(String(512), default="")
    folder = Column(String(128), default="")  # Kept for backward compatibility during migration
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="SET NULL"), nullable=True, index=True)
    saved_password = Column(String(512), default="")
    version = Column(Integer, default=1, nullable=False)  # Optimistic locking
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# Pydantic Models for API
class ArrayBase(BaseModel):
    """Base array schema"""
    name: str
    host: str
    port: int = 22
    username: str = "root"
    key_path: str = ""
    folder: str = ""  # Kept for backward compatibility
    tag_id: Optional[int] = None


class ArrayCreate(ArrayBase):
    """Schema for creating array"""
    password: str = ""  # Not stored, only used for connection

    @field_validator('port')
    @classmethod
    def validate_port(cls, v):
        if not (1 <= v <= 65535):
            raise ValueError('Port must be between 1 and 65535')
        return v

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError('Name cannot be empty')
        return v.strip()


class ArrayUpdate(BaseModel):
    """Schema for updating array"""
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    key_path: Optional[str] = None
    folder: Optional[str] = None
    tag_id: Optional[int] = None
    expected_version: Optional[int] = None  # For optimistic locking


class ArrayResponse(ArrayBase):
    """Schema for array response"""
    id: int
    array_id: str
    tag_id: Optional[int] = None
    tag_name: Optional[str] = None
    tag_color: Optional[str] = None
    tag_l1_name: Optional[str] = None  # L1 group name when tag is L2
    tag_l2_name: Optional[str] = None  # L2 type name (array's tag)
    version: int = 1
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ArrayStatus(BaseModel):
    """Array runtime status"""
    array_id: str
    name: str
    host: str
    state: ConnectionState = ConnectionState.DISCONNECTED
    last_error: str = ""
    agent_deployed: bool = False
    agent_running: bool = False
    has_saved_password: bool = False
    last_refresh: Optional[datetime] = None
    tag_id: Optional[int] = None
    tag_name: Optional[str] = None
    tag_color: Optional[str] = None
    tag_l1_name: Optional[str] = None
    tag_l2_name: Optional[str] = None
    observer_status: Dict[str, Dict[str, str]] = {}
    active_issues: List[Dict[str, Any]] = []
    recent_alerts: List[Dict[str, Any]] = []
    recent_alert_summary: Dict[str, int] = {}


class Array(ArrayBase):
    """Full array model with runtime state"""
    id: int
    array_id: str
    tag_id: Optional[int] = None
    state: ConnectionState = ConnectionState.DISCONNECTED
    last_error: str = ""
    agent_deployed: bool = False
    agent_running: bool = False
    last_refresh: Optional[datetime] = None
    observer_status: Dict[str, Dict[str, str]] = {}

    model_config = ConfigDict(from_attributes=True)
