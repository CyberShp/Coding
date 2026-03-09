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
    expected_observers = Column(Text, default="[]")  # JSON array of observer names
    notes = Column(Text, default="")
    status = Column(String(16), default="created")  # created, running, completed
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


# Task types - comprehensive list for various test scenarios
TASK_TYPES = {
    # Basic operations
    'normal_business': '正常业务',
    'custom': '自定义',

    # Power operations
    'controller_poweroff': '控制器下电',
    'card_poweroff': '接口卡下电',
    'full_poweroff': '整机下电',
    'ups_test': 'UPS 切换测试',

    # Network/Port operations
    'port_toggle': '端口开关',
    'cable_pull': '线缆拔插',
    'network_isolation': '网络隔离',
    'link_flapping': '链路抖动测试',

    # Fault injection
    'fault_injection': '系统故障注入',
    'disk_fault': '磁盘故障注入',
    'memory_pressure': '内存压力测试',
    'io_error_injection': 'IO 错误注入',

    # Upgrade/Maintenance
    'controller_upgrade': '控制器升级',
    'firmware_upgrade': '固件升级',
    'hot_upgrade': '热升级',
    'rollback_test': '回滚测试',

    # High availability
    'failover_test': '故障切换测试',
    'takeover_test': '接管测试',
    'split_brain': '脑裂测试',

    # Performance
    'stress_test': '压力测试',
    'endurance_test': '耐久测试',
    'benchmark': '性能基准测试',

    # Recovery
    'disaster_recovery': '灾难恢复',
    'data_migration': '数据迁移',
    'rebuild_test': '重建测试',
}


class TaskSessionCreate(BaseModel):
    """Schema for creating a test task"""
    name: str
    task_type: str = 'custom'
    array_ids: List[str] = []
    expected_observers: List[str] = []
    notes: str = ''


class TaskSessionResponse(BaseModel):
    """Schema for task response"""
    id: int
    name: str
    task_type: str
    task_type_label: str = ''
    array_ids: List[str] = []
    expected_observers: List[str] = []
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
    expected_count: int = 0
    unexpected_count: int = 0
    by_level: Dict[str, int] = {}
    by_observer: Dict[str, int] = {}
    critical_events: List[Dict[str, Any]] = []
