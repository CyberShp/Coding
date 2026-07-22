"""
Monitor template model for admin-defined custom monitors.

Templates can be deployed to arrays via SSH config.json.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from ..db.database import Base


class MonitorTemplateModel(Base):
    """Monitor template database model"""
    __tablename__ = "monitor_templates"

    id = Column(Integer, primary_key=True)
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
    consecutive_threshold = Column(Integer, default=1)

    # 管理
    is_enabled = Column(Boolean, default=True)
    is_builtin = Column(Boolean, default=False)
    created_by = Column(String(64), default="")
    # Precise ownership for multi-user Phase 2 (created_by keeps the nickname
    # for display/attribution; owner_user_id is the authoritative FK for
    # permission checks). Nullable: builtin/legacy rows have no owner.
    owner_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    template_key = Column(String(64), unique=True, index=True, nullable=True)
    version = Column(Integer, default=1, nullable=False)
    visibility = Column(String(16), default="team", nullable=False)
    team_scope = Column(String(128), default="")
    config_fingerprint = Column(String(80), default="")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class MonitorTemplateVersionModel(Base):
    """Immutable snapshot of one custom observer template revision."""

    __tablename__ = "monitor_template_versions"

    id = Column(Integer, primary_key=True)
    template_id = Column(
        Integer,
        ForeignKey("monitor_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = Column(Integer, nullable=False)
    snapshot = Column(Text, nullable=False)
    config_fingerprint = Column(String(80), nullable=False)
    created_by = Column(String(64), default="")
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("template_id", "version", name="uq_monitor_template_version"),
    )


class MonitorAssignmentModel(Base):
    """Persistent desired assignment to one array or tag."""

    __tablename__ = "monitor_assignments"

    id = Column(Integer, primary_key=True)
    template_id = Column(
        Integer,
        ForeignKey("monitor_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_type = Column(String(16), nullable=False)
    target_id = Column(Integer, nullable=False)
    desired_version = Column(Integer, nullable=False)
    is_enabled = Column(Boolean, default=True, nullable=False)
    status = Column(String(16), default="pending", nullable=False)
    status_message = Column(Text, default="")
    created_by = Column(String(64), default="")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "template_id", "target_type", "target_id",
            name="uq_monitor_assignment_target",
        ),
        Index("ix_monitor_assignment_target", "target_type", "target_id"),
    )


class MonitorDeploymentModel(Base):
    """Observed deployment state for one template on one resolved array."""

    __tablename__ = "monitor_deployments"

    id = Column(Integer, primary_key=True)
    assignment_id = Column(
        Integer,
        ForeignKey("monitor_assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_id = Column(Integer, nullable=False, index=True)
    array_id = Column(String(64), nullable=False, index=True)
    desired_version = Column(Integer, nullable=False)
    desired_hash = Column(String(80), default="")
    loaded_hash = Column(String(80), default="")
    status = Column(String(16), default="pending", nullable=False)
    status_message = Column(Text, default="")
    attempted_at = Column(DateTime, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("assignment_id", "array_id", name="uq_monitor_deployment_array"),
    )
