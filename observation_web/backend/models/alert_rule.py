"""
Alert expectation rules for test tasks.

Allows users to define which alerts are "expected" during specific test types,
so they can filter out expected alarms and focus on unexpected ones.
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.sql import func

from ..db.database import Base


class AlertExpectationRuleModel(Base):
    """Alert expectation rule database model"""
    __tablename__ = "alert_expectation_rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    task_types = Column(Text, default="[]")  # JSON array of task_type strings
    observer_patterns = Column(Text, default="[]")  # JSON array of observer name patterns
    level_patterns = Column(Text, default="[]")  # JSON array of levels to match
    message_patterns = Column(Text, default="[]")  # JSON array of regex patterns for message
    is_builtin = Column(Boolean, default=False)
    is_enabled = Column(Boolean, default=True)
    priority = Column(Integer, default=100)  # Lower = higher priority
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# Built-in rules for common test scenarios
BUILTIN_RULES = [
    {
        "name": "端口开关-链路状态变化",
        "description": "端口 down/up 操作期间，链路状态变化是预期的",
        "task_types": ["port_toggle", "cable_pull"],
        "observer_patterns": ["link_status"],
        "level_patterns": ["warning", "info"],
        "message_patterns": [r".*link.*(down|up).*", r".*链路状态.*"],
    },
    {
        "name": "端口开关-速率变化",
        "description": "端口 down/up 操作期间，速率变为 unknown 是预期的",
        "task_types": ["port_toggle", "cable_pull"],
        "observer_patterns": ["port_speed"],
        "level_patterns": ["warning", "info"],
        "message_patterns": [r".*speed.*(unknown|changed).*", r".*速率.*"],
    },
    {
        "name": "端口开关-ETH_PORT告警",
        "description": "端口操作期间的 ETH_PORT 类型告警是预期的",
        "task_types": ["port_toggle", "cable_pull"],
        "observer_patterns": ["alarm_type"],
        "level_patterns": ["warning", "info"],
        "message_patterns": [r".*ETH_PORT.*"],
    },
    {
        "name": "控制器下电-心跳丢失",
        "description": "控制器下电期间，心跳丢失是预期的",
        "task_types": ["controller_poweroff"],
        "observer_patterns": ["controller_state", "heartbeat"],
        "level_patterns": ["warning", "error"],
        "message_patterns": [r".*heartbeat.*(lost|timeout).*", r".*心跳.*"],
    },
    {
        "name": "控制器下电-状态变化",
        "description": "控制器下电期间，控制器状态变化是预期的",
        "task_types": ["controller_poweroff"],
        "observer_patterns": ["controller_state"],
        "level_patterns": ["warning", "error"],
        "message_patterns": [r".*controller.*(offline|unavailable).*", r".*控制器.*"],
    },
    {
        "name": "接口卡下电-卡状态变化",
        "description": "接口卡下电期间，卡状态变化是预期的",
        "task_types": ["card_poweroff"],
        "observer_patterns": ["card_info", "card_recovery"],
        "level_patterns": ["warning", "error"],
        "message_patterns": [r".*card.*(offline|removed|recovery).*", r".*接口卡.*"],
    },
    {
        "name": "故障注入-通用",
        "description": "故障注入期间，相关观察点的告警是预期的",
        "task_types": ["fault_injection"],
        "observer_patterns": ["error_code", "alarm_type"],
        "level_patterns": ["warning", "error"],
        "message_patterns": [],
    },
    {
        "name": "升级-进程重启",
        "description": "升级期间，进程重启相关告警是预期的",
        "task_types": ["controller_upgrade"],
        "observer_patterns": ["process_crash", "controller_state"],
        "level_patterns": ["warning", "error"],
        "message_patterns": [r".*restart.*", r".*upgrade.*"],
    },
]


# Pydantic models for API
class AlertRuleBase(BaseModel):
    """Base alert rule schema"""
    name: str
    description: str = ""
    task_types: List[str] = []
    observer_patterns: List[str] = []
    level_patterns: List[str] = []
    message_patterns: List[str] = []
    is_enabled: bool = True
    priority: int = 100


class AlertRuleCreate(AlertRuleBase):
    """Schema for creating alert rule"""
    pass


class AlertRuleUpdate(BaseModel):
    """Schema for updating alert rule"""
    name: Optional[str] = None
    description: Optional[str] = None
    task_types: Optional[List[str]] = None
    observer_patterns: Optional[List[str]] = None
    level_patterns: Optional[List[str]] = None
    message_patterns: Optional[List[str]] = None
    is_enabled: Optional[bool] = None
    priority: Optional[int] = None


class AlertRuleResponse(AlertRuleBase):
    """Schema for alert rule response"""
    id: int
    is_builtin: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator('task_types', 'observer_patterns', 'level_patterns', 'message_patterns', mode='before')
    @classmethod
    def parse_json_list(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return []
        return v if v is not None else []
