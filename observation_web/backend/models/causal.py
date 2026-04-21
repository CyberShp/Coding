"""
F200: Causal Rule model — stores learned observer→observer causal edges.

Each row represents a discovered precedence relationship:
  antecedent_observer → consequent_observer on a given array_id,
  with frequency count, average lag, and confidence score.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, UniqueConstraint
from ..db.database import Base


class CausalRuleModel(Base):
    __tablename__ = "causal_rules"

    id = Column(Integer, primary_key=True)
    array_id = Column(String(64), nullable=False, index=True)
    antecedent = Column(String(64), nullable=False)   # observer_name that fires first
    consequent = Column(String(64), nullable=False)    # observer_name that follows
    co_occurrence_count = Column(Integer, default=0)   # how many times seen together
    avg_lag_seconds = Column(Float, default=0.0)       # mean time gap A→B
    confidence = Column(Float, default=0.0)            # P(B|A) estimate
    last_seen_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("array_id", "antecedent", "consequent", name="uq_causal_edge"),
    )
