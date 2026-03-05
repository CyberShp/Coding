"""
AI interpretation model for alert human-readable summaries.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func

from ..db.database import Base


class AIInterpretationModel(Base):
    """Cached AI interpretation for an alert"""
    __tablename__ = "ai_interpretations"

    id = Column(Integer, primary_key=True, index=True)
    alert_id = Column(Integer, unique=True, index=True, nullable=False)
    interpretation = Column(Text, nullable=False)
    model_name = Column(String(64), default="")
    created_at = Column(DateTime, server_default=func.now())
