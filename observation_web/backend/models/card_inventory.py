"""Card inventory model for global card catalog.

Phase 1: Manual CRUD catalog (current).
TODO Phase 2: Sync from connected arrays via card_info observer - add array_id, card_no,
board_id, health_state, running_state, raw_fields, last_updated; see plan Feature 10.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func

from ..db.database import Base


# Predefined device types (预埋器件类型)
DEVICE_TYPES = [
    "FC卡",
    "以太网卡",
    "RAID卡",
    "控制器卡",
    "扩展卡",
    "其他",
]


class CardInventoryModel(Base):
    """Card inventory database model."""
    __tablename__ = "card_inventory"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False, index=True)
    device_type = Column(String(64), nullable=False, index=True)
    model = Column(String(128), default="")
    description = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class CardInventoryCreate(BaseModel):
    """Schema for creating card inventory entry."""
    name: str
    device_type: str
    model: str = ""
    description: str = ""

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError('Name cannot be empty')
        return v.strip()

    @field_validator('device_type')
    @classmethod
    def validate_device_type(cls, v):
        if not v or not v.strip():
            raise ValueError('Device type cannot be empty')
        return v.strip()


class CardInventoryUpdate(BaseModel):
    """Schema for updating card inventory entry."""
    name: Optional[str] = None
    device_type: Optional[str] = None
    model: Optional[str] = None
    description: Optional[str] = None


class CardInventoryResponse(BaseModel):
    """Schema for card inventory response."""
    id: int
    name: str
    device_type: str
    model: str
    description: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
