"""
Card presence tracking models (current state + history).
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, DateTime, Index, UniqueConstraint
from sqlalchemy.sql import func

from ..db.database import Base


class CardPresenceStatus(str, Enum):
    """Card presence status enum"""
    PRESENT = "present"
    SUSPECT_MISSING = "suspect_missing"
    REMOVED = "removed"


# SQLAlchemy Models
class CardPresenceCurrentModel(Base):
    """Current card presence state"""
    __tablename__ = "card_presence_current"

    id = Column(Integer, primary_key=True, index=True)
    array_id = Column(String(64), index=True, nullable=False)
    board_id = Column(String(64), index=True, nullable=False)
    card_no = Column(String(32), default="")
    model = Column(String(256), default="")
    status = Column(String(32), default="present")
    last_confirmed_at = Column(DateTime)
    first_seen_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('array_id', 'board_id', name='uq_card_presence_current_array_board'),
    )


class CardPresenceHistoryModel(Base):
    """Historical card presence records"""
    __tablename__ = "card_presence_history"

    id = Column(Integer, primary_key=True, index=True)
    board_id = Column(String(64), index=True, nullable=False)
    array_id = Column(String(64), nullable=False)
    card_no = Column(String(32), default="")
    model = Column(String(256), default="")
    seen_at = Column(DateTime, nullable=False)
    removed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index('ix_card_presence_history_board_seen', 'board_id', 'seen_at'),
    )


# Pydantic Models for API
class CardPresenceCurrentResponse(BaseModel):
    """Schema for current card presence response"""
    id: int
    array_id: str
    board_id: str
    card_no: str = ""
    model: str = ""
    status: str = "present"
    last_confirmed_at: Optional[datetime] = None
    first_seen_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CardPresenceHistoryResponse(BaseModel):
    """Schema for card presence history response"""
    id: int
    board_id: str
    array_id: str
    card_no: str = ""
    model: str = ""
    seen_at: datetime
    removed_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
