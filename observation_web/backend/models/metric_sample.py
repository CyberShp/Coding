"""
Persistent metric sample model.

Stores downsampled performance metrics (CPU, memory, ...) so that history
survives a restart and can be queried across workers.  The high-frequency
in-memory deque in ``api/ingest.py`` is kept for fast recent lookups; this
table is written at most once per array per downsample window (~60s).
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Index
from sqlalchemy.sql import func

from ..db.database import Base


class MetricSampleModel(Base):
    """Downsampled performance metric sample (persisted)."""
    __tablename__ = "metric_samples"

    id = Column(Integer, primary_key=True)  # rowid PK; no separate index
    array_id = Column(String(64), index=True, nullable=False)
    ts = Column(DateTime, index=True, nullable=False)
    cpu0 = Column(Float, nullable=True)
    mem_used_mb = Column(Float, nullable=True)
    mem_total_mb = Column(Float, nullable=True)
    # Remaining metric fields serialised as a JSON object.
    extra = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_metric_samples_array_ts", "array_id", "ts"),
    )
