"""User preferences model for personal view settings."""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func

from ..db.database import Base


class UserPreferenceModel(Base):
    """User preferences stored by IP (no auth)."""
    __tablename__ = "user_preferences"

    ip = Column(String(64), primary_key=True)
    default_tag_id = Column(Integer, ForeignKey("tags.id", ondelete="SET NULL"), nullable=True)
    watched_tag_ids = Column(Text, default="[]")
    watched_array_ids = Column(Text, default="[]")
    watched_observers = Column(Text, default="[]")
    muted_observers = Column(Text, default="[]")
    alert_sound = Column(Boolean, default=True)
    dashboard_l1_tag_id = Column(Integer, ForeignKey("tags.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class UserPreferenceResponse(BaseModel):
    """Schema for preferences response."""
    default_tag_id: Optional[int] = None
    watched_tag_ids: List[int] = []
    watched_array_ids: List[str] = []
    watched_observers: List[str] = []
    muted_observers: List[str] = []
    alert_sound: bool = True

    model_config = ConfigDict(from_attributes=True)
