"""
Expected window model for test scenario time windows.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func

from ..db.database import Base


# SQLAlchemy Model
class ExpectedWindowModel(Base):
    """Expected window database model"""
    __tablename__ = "expected_windows"

    id = Column(Integer, primary_key=True, index=True)
    array_id = Column(String(64), index=True, nullable=False)
    name = Column(String(128), nullable=False)
    category_pattern = Column(String(256), nullable=False)
    start_at = Column(DateTime, nullable=False)
    end_at = Column(DateTime, nullable=True)
    created_by = Column(String(128), default="")
    note = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())


# Pydantic Models for API
class ExpectedWindowCreate(BaseModel):
    """Schema for creating expected window"""
    array_id: str
    name: str
    category_pattern: str
    start_at: datetime
    end_at: Optional[datetime] = None
    created_by: str = ""
    note: str = ""


class ExpectedWindowResponse(BaseModel):
    """Schema for expected window response"""
    id: int
    array_id: str
    name: str
    category_pattern: str
    start_at: datetime
    end_at: Optional[datetime] = None
    created_by: str = ""
    note: str = ""
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
