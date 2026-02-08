"""
Port traffic data model — stores raw traffic data for up to 2 hours.
"""

from sqlalchemy import Column, Integer, String, Float, BigInteger, DateTime, Index
from sqlalchemy.sql import func

from ..db.database import Base


class PortTrafficModel(Base):
    """端口流量数据（仅保留 2 小时原始数据）"""
    __tablename__ = "port_traffic"

    id = Column(Integer, primary_key=True, index=True)
    array_id = Column(String(64), nullable=False)
    port_name = Column(String(64), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    tx_bytes = Column(BigInteger, default=0)
    rx_bytes = Column(BigInteger, default=0)
    tx_rate_bps = Column(Float, default=0.0)
    rx_rate_bps = Column(Float, default=0.0)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index('ix_traffic_array_port_ts', 'array_id', 'port_name', 'timestamp'),
        Index('ix_traffic_timestamp', 'timestamp'),
    )
