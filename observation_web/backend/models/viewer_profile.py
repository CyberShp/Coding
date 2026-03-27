"""
Viewer profile and preferences models for browser-based identity.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func

from ..db.database import Base


# SQLAlchemy Models
class ViewerProfileModel(Base):
    """Browser-based viewer identity"""
    __tablename__ = "viewer_profiles"

    id = Column(Integer, primary_key=True, index=True)
    viewer_id = Column(String(64), unique=True, index=True, nullable=False)
    nickname = Column(String(64), default="")
    ip_address = Column(String(64), default="")
    first_seen_at = Column(DateTime, server_default=func.now())
    last_seen_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ViewerFollowTagModel(Base):
    """Viewer tag follow relationship"""
    __tablename__ = "viewer_follow_tags"

    id = Column(Integer, primary_key=True, index=True)
    viewer_id = Column(String(64), index=True, nullable=False)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint('viewer_id', 'tag_id', name='uq_viewer_follow_tag'),
    )


class ViewerFollowArrayModel(Base):
    """Viewer array follow relationship"""
    __tablename__ = "viewer_follow_arrays"

    id = Column(Integer, primary_key=True, index=True)
    viewer_id = Column(String(64), index=True, nullable=False)
    array_id = Column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint('viewer_id', 'array_id', name='uq_viewer_follow_array'),
    )


class ViewerPreferenceModel(Base):
    """Viewer UI preferences"""
    __tablename__ = "viewer_preferences"

    id = Column(Integer, primary_key=True, index=True)
    viewer_id = Column(String(64), unique=True, index=True, nullable=False)
    default_time_window = Column(String(16), default="24h")
    default_tag_filter = Column(Text, default="[]")
    alert_sound = Column(Integer, default=1)
    dashboard_expanded_sections = Column(Text, default="[]")
    recent_filters_json = Column(Text, default="{}")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ViewerSavedViewModel(Base):
    """Viewer saved filter views"""
    __tablename__ = "viewer_saved_views"

    id = Column(Integer, primary_key=True, index=True)
    viewer_id = Column(String(64), index=True, nullable=False)
    name = Column(String(128), nullable=False)
    filters_json = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


# Pydantic Models for API
class ViewerProfileResponse(BaseModel):
    """Schema for viewer profile response"""
    id: int
    viewer_id: str
    nickname: str = ""
    ip_address: str = ""
    first_seen_at: datetime
    last_seen_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ViewerPreferenceResponse(BaseModel):
    """Schema for viewer preference response"""
    id: int
    viewer_id: str
    default_time_window: str = "24h"
    default_tag_filter: str = "[]"
    alert_sound: int = 1
    dashboard_expanded_sections: str = "[]"
    recent_filters_json: str = "{}"
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ViewerSavedViewResponse(BaseModel):
    """Schema for viewer saved view response"""
    id: int
    viewer_id: str
    name: str
    filters_json: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
