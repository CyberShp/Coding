"""User preferences model for personal view settings.

Phase 1: default_tag_id only. Plan called for watched_tag_ids, watched_array_ids,
watched_observers, muted_observers, alert_sound - see TODO in users.py.
"""

from typing import Optional

from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func

from ..db.database import Base


class UserPreferenceModel(Base):
    """User preferences stored by IP (no auth)."""
    __tablename__ = "user_preferences"

    ip = Column(String(64), primary_key=True)
    default_tag_id = Column(Integer, ForeignKey("tags.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class UserPreferenceResponse(BaseModel):
    """Schema for preferences response."""
    default_tag_id: Optional[int] = None

    class Config:
        from_attributes = True
