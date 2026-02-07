"""
Data lifecycle models for sync state, archive, and configuration.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, LargeBinary
from sqlalchemy.sql import func

from ..db.database import Base


# SQLAlchemy Models

class SyncStateModel(Base):
    """Sync state for tracking import position per array"""
    __tablename__ = "sync_state"
    
    array_id = Column(String(64), primary_key=True)
    log_file = Column(String(256), default="alerts.log")
    last_position = Column(Integer, default=0)
    last_timestamp = Column(DateTime, nullable=True)
    last_sync_at = Column(DateTime, nullable=True)
    total_imported = Column(Integer, default=0)


class AlertsArchiveModel(Base):
    """Archived alerts with compression"""
    __tablename__ = "alerts_archive"
    
    id = Column(Integer, primary_key=True, index=True)
    array_id = Column(String(64), index=True, nullable=False)
    year_month = Column(String(7), index=True, nullable=False)  # e.g., "2026-02"
    data_compressed = Column(LargeBinary, nullable=False)  # gzip compressed JSON
    record_count = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())


class ArchiveConfigModel(Base):
    """Archive configuration"""
    __tablename__ = "archive_config"
    
    id = Column(Integer, primary_key=True)
    active_retention_days = Column(Integer, default=7)
    archive_retention_days = Column(Integer, default=30)
    archive_enabled = Column(Boolean, default=True)
    auto_cleanup = Column(Boolean, default=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# Pydantic Models for API

class SyncState(BaseModel):
    """Sync state response"""
    array_id: str
    log_file: str
    last_position: int
    last_timestamp: Optional[datetime] = None
    last_sync_at: Optional[datetime] = None
    total_imported: int
    
    model_config = ConfigDict(from_attributes=True)


class LogFileInfo(BaseModel):
    """Remote log file info"""
    name: str
    size: int
    size_human: str
    modified: Optional[str] = None


class ImportRequest(BaseModel):
    """Import history request"""
    mode: str = "incremental"  # incremental/full/selective
    days: int = 7  # for incremental mode
    log_files: Optional[List[str]] = None  # for selective mode


class ImportResult(BaseModel):
    """Import result"""
    success: bool
    imported_count: int
    skipped_count: int
    message: str


class ArchiveConfig(BaseModel):
    """Archive configuration"""
    active_retention_days: int = 7
    archive_retention_days: int = 30
    archive_enabled: bool = True
    auto_cleanup: bool = True
    
    model_config = ConfigDict(from_attributes=True)


class ArchiveStats(BaseModel):
    """Archive statistics"""
    active_count: int
    archive_count: int
    archive_size_bytes: int
    oldest_active: Optional[datetime] = None
    oldest_archive: Optional[str] = None  # year_month
