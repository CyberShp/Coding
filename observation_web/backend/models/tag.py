"""
Tag model for array grouping/classification.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func

from ..db.database import Base


# SQLAlchemy Model
class TagModel(Base):
    """Tag database model for organizing arrays"""
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), unique=True, nullable=False, index=True)
    color = Column(String(32), default="#409eff")
    description = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# Pydantic Models for API
class TagBase(BaseModel):
    """Base tag schema"""
    name: str
    color: str = "#409eff"
    description: str = ""


class TagCreate(TagBase):
    """Schema for creating tag"""

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError('Tag name cannot be empty')
        return v.strip()

    @field_validator('color')
    @classmethod
    def validate_color(cls, v):
        if not v:
            return "#409eff"
        if not v.startswith('#') or len(v) not in (4, 7):
            raise ValueError('Invalid color format, use #RGB or #RRGGBB')
        return v


class TagUpdate(BaseModel):
    """Schema for updating tag"""
    name: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None


class TagResponse(TagBase):
    """Schema for tag response"""
    id: int
    created_at: datetime
    updated_at: datetime
    array_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class TagWithArrays(TagResponse):
    """Tag with arrays list"""
    arrays: List[dict] = []
