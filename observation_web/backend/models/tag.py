"""
Tag model for array grouping/classification.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func

from ..db.database import Base


class TagType(str, Enum):
    """Tag type enum"""
    TEAM = "team"
    BUSINESS = "business"
    ENV = "env"
    TEST_TYPE = "test_type"
    HARDWARE_FAMILY = "hardware_family"
    RISK = "risk"
    GENERAL = "general"


# SQLAlchemy Model
class TagModel(Base):
    """Tag database model for organizing arrays. level=1: group/team, level=2: array type."""
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), unique=True, nullable=False, index=True)
    color = Column(String(32), default="#409eff")
    description = Column(Text, default="")
    parent_id = Column(Integer, ForeignKey("tags.id", ondelete="SET NULL"), nullable=True, index=True)
    level = Column(Integer, default=1)  # 1=一级(小组), 2=二级(类型)
    tag_type = Column(String(64), default="general")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ArrayTagModel(Base):
    """Many-to-many junction table for arrays and tags"""
    __tablename__ = "array_tags"

    id = Column(Integer, primary_key=True, index=True)
    array_id = Column(String(64), index=True, nullable=False)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), index=True, nullable=False)

    __table_args__ = (
        UniqueConstraint('array_id', 'tag_id', name='uq_array_tag'),
    )


# Pydantic Models for API
class TagBase(BaseModel):
    """Base tag schema"""
    name: str
    color: str = "#409eff"
    description: str = ""
    parent_id: Optional[int] = None
    level: int = 2  # 1=一级(小组), 2=二级(类型)
    tag_type: str = "general"


class TagCreate(TagBase):
    """Schema for creating tag. parent_id links to L1 tag; level 1=group, 2=array type."""

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
    parent_id: Optional[int] = None
    level: Optional[int] = None


class TagResponse(TagBase):
    """Schema for tag response"""
    id: int
    parent_id: Optional[int] = None
    level: int = 2
    tag_type: str = "general"
    parent_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    array_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class TagWithArrays(TagResponse):
    """Tag with arrays list"""
    arrays: List[dict] = []
