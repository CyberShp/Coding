"""Card inventory model - cards synced from connected arrays via card_info observer."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, Text, DateTime, UniqueConstraint
from sqlalchemy.sql import func

from ..db.database import Base


class CardInventoryModel(Base):
    """Card inventory - one row per physical card across all arrays."""
    __tablename__ = "card_inventory"

    id = Column(Integer, primary_key=True, index=True)
    array_id = Column(String(64), nullable=False, index=True)
    card_no = Column(String(32), default="")
    board_id = Column(String(64), default="", index=True)
    health_state = Column(String(32), default="")
    running_state = Column(String(32), default="")
    model = Column(String(256), default="", index=True)
    raw_fields = Column(Text, default="{}")
    last_updated = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("array_id", "card_no", name="uq_card_array_cardno"),
    )


class CardInventoryResponse(BaseModel):
    """Response schema including joined array info."""
    id: int
    array_id: str
    card_no: str
    board_id: str
    health_state: str
    running_state: str
    model: str
    raw_fields: str
    last_updated: Optional[datetime] = None
    array_name: str = ""
    array_host: str = ""
    tag_l1: str = ""
    tag_l2: str = ""

    model_config = ConfigDict(from_attributes=True)


class CardSyncResult(BaseModel):
    """Result of a card sync operation."""
    synced: int = 0
    errors: list[str] = []
    skipped_arrays: list[str] = []
    synced_arrays: list[str] = []
