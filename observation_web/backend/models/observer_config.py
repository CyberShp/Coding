"""
Observer config overrides for built-in observers.

Stores admin-configured overrides (enabled, interval, custom params)
that get merged into agent config.json on deploy.
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.sql import func

from ..db.database import Base


class ObserverConfigModel(Base):
    """Global override settings for built-in observers"""
    __tablename__ = "observer_configs"

    id = Column(Integer, primary_key=True, index=True)
    observer_name = Column(String(64), nullable=False, unique=True, index=True)
    enabled = Column(Boolean, default=True)
    interval = Column(Integer, nullable=True)
    params_json = Column(Text, default="{}")
    updated_by = Column(String(64), default="")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
