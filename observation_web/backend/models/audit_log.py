"""
Audit log model for tracking user operations.

Records important user actions for accountability in multi-user environments.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, DateTime, Text, Index
from sqlalchemy.sql import func

from ..db.database import Base


class AuditLogModel(Base):
    """Audit log database model"""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, server_default=func.now(), index=True)
    user_ip = Column(String(64), index=True)
    user_nickname = Column(String(64), default="")
    action = Column(String(64), index=True)  # e.g., 'array.connect', 'task.start'
    resource_type = Column(String(32))  # e.g., 'array', 'task', 'alert'
    resource_id = Column(String(64))  # ID of the affected resource
    details = Column(Text, default="{}")  # JSON details
    result = Column(String(16), default="success")  # success, failure, error

    __table_args__ = (
        Index('ix_audit_timestamp_action', 'timestamp', 'action'),
        Index('ix_audit_user_ip', 'user_ip'),
    )


# Pydantic models
class AuditLogResponse(BaseModel):
    """Audit log response schema"""
    id: int
    timestamp: datetime
    user_ip: str
    user_nickname: str
    action: str
    resource_type: str
    resource_id: str
    details: Dict[str, Any] = {}
    result: str

    model_config = ConfigDict(from_attributes=True)


# Action constants
class AuditAction:
    """Audit action constants"""
    # Array operations
    ARRAY_CREATE = "array.create"
    ARRAY_UPDATE = "array.update"
    ARRAY_DELETE = "array.delete"
    ARRAY_CONNECT = "array.connect"
    ARRAY_DISCONNECT = "array.disconnect"
    
    # Agent operations
    AGENT_DEPLOY = "agent.deploy"
    AGENT_START = "agent.start"
    AGENT_STOP = "agent.stop"
    
    # Task operations
    TASK_CREATE = "task.create"
    TASK_START = "task.start"
    TASK_STOP = "task.stop"
    TASK_DELETE = "task.delete"
    
    # Alert operations
    ALERT_ACK = "alert.acknowledge"
    
    # Tag operations
    TAG_CREATE = "tag.create"
    TAG_UPDATE = "tag.update"
    TAG_DELETE = "tag.delete"
    
    # Rule operations
    RULE_CREATE = "rule.create"
    RULE_UPDATE = "rule.update"
    RULE_DELETE = "rule.delete"
