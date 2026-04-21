"""
F202: Adaptive Baseline — per-array per-observer rolling statistics.

Stores 30-day rolling median and standard deviation for numeric alert metrics.
Used to classify alerts as baseline-normal (within 3σ) or anomalous.
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, UniqueConstraint
from sqlalchemy.sql import func

from ..db.database import Base


class BaselineStats(Base):
    """Rolling baseline statistics per array + observer + metric."""
    __tablename__ = "baseline_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    array_id = Column(String(64), nullable=False, index=True)
    observer_name = Column(String(64), nullable=False)
    metric_key = Column(String(100), nullable=False)  # e.g. "error_count", "cpu_usage"
    median_value = Column(Float, nullable=False, default=0.0)
    stddev_value = Column(Float, nullable=False, default=0.0)
    sample_count = Column(Integer, nullable=False, default=0)
    window_days = Column(Integer, nullable=False, default=30)
    updated_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint('array_id', 'observer_name', 'metric_key', name='uix_baseline'),
    )
