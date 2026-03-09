"""
User session model for IP-based user tracking.

No authentication required - users are identified by their IP address.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.sql import func

from ..db.database import Base


# SQLAlchemy Model
class UserSessionModel(Base):
    """User session database model"""
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    ip = Column(String(64), unique=True, index=True, nullable=False)
    nickname = Column(String(64), default="")
    previous_ips = Column(Text, default="[]")  # JSON array of historical IPs after claim
    first_seen = Column(DateTime, server_default=func.now())
    last_seen = Column(DateTime, server_default=func.now(), onupdate=func.now())
    is_active = Column(Boolean, default=True)


# Pydantic Models for API
class UserSessionBase(BaseModel):
    """Base user session schema"""
    ip: str
    nickname: str = ""


class UserSessionResponse(UserSessionBase):
    """User session response schema"""
    id: int
    first_seen: datetime
    last_seen: datetime
    is_active: bool
    color: str = ""  # Computed from IP hash
    nickname_compliant: bool = True

    model_config = ConfigDict(from_attributes=True)


class OnlineUser(BaseModel):
    """Online user info"""
    ip: str
    nickname: str
    color: str
    last_seen: datetime
    viewing_page: Optional[str] = None


class SetNicknameRequest(BaseModel):
    """Request to set user nickname"""
    nickname: str


class ClaimNicknameRequest(BaseModel):
    """Request to claim existing nickname (e.g. after IP change)"""
    nickname: str
