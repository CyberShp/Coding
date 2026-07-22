"""
Observer config overrides for built-in observers.

Stores admin-configured overrides (enabled, interval, custom params)
that get merged into agent config.json on deploy.
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, UniqueConstraint
from sqlalchemy.sql import func

from ..db.database import Base


class ObserverConfigModel(Base):
    """Global override settings for built-in observers (default layer)"""
    __tablename__ = "observer_configs"

    id = Column(Integer, primary_key=True)
    observer_name = Column(String(64), nullable=False, unique=True, index=True)
    enabled = Column(Boolean, default=True)
    interval = Column(Integer, nullable=True)
    params_json = Column(Text, default="{}")
    updated_by = Column(String(64), default="")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ObserverConfigOverrideModel(Base):
    """Per-scope (L1 tag / array) overlay on top of the global observer default.

    The global ``observer_configs`` row is the default; a ``tag`` override applies
    to every array under that L1 tag; an ``array`` override is the most specific.
    ``resolve_observer_config`` merges them global < tag < array.
    """
    __tablename__ = "observer_config_overrides"
    __table_args__ = (
        UniqueConstraint(
            "observer_name", "scope_type", "scope_id",
            name="uq_observer_override_scope",
        ),
    )

    id = Column(Integer, primary_key=True)
    observer_name = Column(String(64), nullable=False, index=True)
    scope_type = Column(String(16), nullable=False)  # 'tag' | 'array'
    scope_id = Column(String(64), nullable=False)     # tag_id or array_id as string
    params_json = Column(Text, default="{}")          # JSON dict of param overrides
    # None = do not override the enable switch, only params
    enabled = Column(Boolean, nullable=True)
    updated_by = Column(String(64), default="")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
