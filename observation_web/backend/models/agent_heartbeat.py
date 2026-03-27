"""
Agent heartbeat model for tracking agent liveness.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func

from ..db.database import Base


# SQLAlchemy Model
class AgentHeartbeatModel(Base):
    """Agent heartbeat database model"""
    __tablename__ = "agent_heartbeats"

    id = Column(Integer, primary_key=True, index=True)
    array_id = Column(String(64), unique=True, index=True, nullable=False)
    agent_version = Column(String(32), default="")
    config_version = Column(String(32), default="")
    last_seen_at = Column(DateTime, nullable=False)
    ip_address = Column(String(64), default="")
    uptime_seconds = Column(Integer, default=0)
    observer_count = Column(Integer, default=0)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# Pydantic Models for API
class AgentHeartbeatCreate(BaseModel):
    """Schema for creating/updating agent heartbeat"""
    array_id: str
    agent_version: str = ""
    config_version: str = ""
    last_seen_at: datetime
    ip_address: str = ""
    uptime_seconds: int = 0
    observer_count: int = 0


class AgentHeartbeatResponse(BaseModel):
    """Schema for agent heartbeat response"""
    id: int
    array_id: str
    agent_version: str = ""
    config_version: str = ""
    last_seen_at: datetime
    ip_address: str = ""
    uptime_seconds: int = 0
    observer_count: int = 0
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
