"""
Issue/feedback model for user suggestions.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func

from ..db.database import Base


class IssueModel(Base):
    """Issue/feedback database model"""
    __tablename__ = "issues"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(256), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String(32), default="open")  # open, resolved, rejected, adopted
    created_by_ip = Column(String(64), nullable=False)
    created_by_nickname = Column(String(64), default="")
    resolved_by_ip = Column(String(64), nullable=True)
    resolved_by_nickname = Column(String(64), nullable=True)
    resolution_note = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class IssueCreate(BaseModel):
    """Create issue request"""
    title: str
    content: str


class IssueUpdateStatus(BaseModel):
    """Update issue status request"""
    status: str  # open, resolved, rejected, adopted
    resolution_note: str = ""


class IssueResponse(BaseModel):
    """Issue response schema"""
    id: int
    title: str
    content: str
    status: str
    created_by_ip: str
    created_by_nickname: str
    resolved_by_ip: Optional[str] = None
    resolved_by_nickname: Optional[str] = None
    resolution_note: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
