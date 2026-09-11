"""SSH switch inventory and last successful topology observations."""

from sqlalchemy import Column, DateTime, Integer, String, Text

from ..db.database import Base


class TopologySwitchModel(Base):
    __tablename__ = "topology_switches"

    device_id = Column(String(80), primary_key=True)
    name = Column(String(128), nullable=False)
    host = Column(String(256), unique=True, nullable=False)
    port = Column(Integer, nullable=False, default=22)
    username = Column(String(64), nullable=False)
    saved_password = Column(String(512), nullable=False, default="")
    key_path = Column(String(512), nullable=False, default="")


class TopologySnapshotModel(Base):
    __tablename__ = "topology_snapshots"

    device_id = Column(String(80), primary_key=True)
    payload = Column(Text, nullable=False, default="{}")
    collected_at = Column(DateTime, nullable=True)
    attempted_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=False, default="")


class TopologyCableModel(Base):
    __tablename__ = "topology_cables"

    cable_id = Column(String(80), primary_key=True)
    source = Column(String(80), nullable=False)
    source_port = Column(String(128), nullable=False)
    target = Column(String(80), nullable=False)
    target_port = Column(String(128), nullable=False)
    confirmed_by = Column(String(128), nullable=False)
    confirmed_at = Column(DateTime, nullable=False)
