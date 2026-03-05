"""
Monitor template model for admin-defined custom monitors.

Templates can be deployed to arrays via SSH config.json.
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.sql import func

from ..db.database import Base


class MonitorTemplateModel(Base):
    """Monitor template database model"""
    __tablename__ = "monitor_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    category = Column(String(32), default="custom")

    # 执行配置
    command = Column(Text, nullable=False)
    command_type = Column(String(16), default="shell")
    interval = Column(Integer, default=60)
    timeout = Column(Integer, default=30)

    # 匹配规则
    match_type = Column(String(16), default="regex")
    match_expression = Column(Text, nullable=False)
    match_condition = Column(String(16), default="found")
    match_threshold = Column(Text, nullable=True)

    # 告警配置
    alert_level = Column(String(16), default="warning")
    alert_message_template = Column(Text, default="")
    cooldown = Column(Integer, default=300)

    # 管理
    is_enabled = Column(Boolean, default=True)
    is_builtin = Column(Boolean, default=False)
    created_by = Column(String(64), default="")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
