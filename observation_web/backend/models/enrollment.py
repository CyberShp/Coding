"""
Array import and enrollment job models.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.sql import func

from ..db.database import Base


# SQLAlchemy Models
class ArrayImportJobModel(Base):
    """Batch import job record"""
    __tablename__ = "array_import_jobs"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(64), nullable=False)
    total_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    error_summary = Column(Text, default="")
    initiated_by = Column(String(128), default="")
    started_at = Column(DateTime, server_default=func.now())
    finished_at = Column(DateTime, nullable=True)


class ArrayEnrollmentJobModel(Base):
    """Per-array enrollment step tracking"""
    __tablename__ = "array_enrollment_jobs"

    id = Column(Integer, primary_key=True, index=True)
    import_job_id = Column(Integer, ForeignKey("array_import_jobs.id"), nullable=True)
    array_id = Column(String(64), index=True, nullable=False)
    step = Column(String(64), default="")
    status = Column(String(32), default="pending")
    error_message = Column(Text, default="")
    retry_count = Column(Integer, default=0)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class AgentRegistrationModel(Base):
    """Agent registration record"""
    __tablename__ = "agent_registrations"

    id = Column(Integer, primary_key=True, index=True)
    array_id = Column(String(64), unique=True, index=True, nullable=False)
    registration_token = Column(String(256), default="")
    agent_version = Column(String(32), default="")
    config_version = Column(String(32), default="")
    last_seen_at = Column(DateTime, nullable=True)
    registration_state = Column(String(32), default="pending")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# Pydantic Models for API
class ArrayImportJobResponse(BaseModel):
    """Schema for import job response"""
    id: int
    source: str
    total_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    error_summary: str = ""
    initiated_by: str = ""
    started_at: datetime
    finished_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ArrayEnrollmentJobResponse(BaseModel):
    """Schema for enrollment job response"""
    id: int
    import_job_id: Optional[int] = None
    array_id: str
    step: str = ""
    status: str = "pending"
    error_message: str = ""
    retry_count: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentRegistrationResponse(BaseModel):
    """Schema for agent registration response"""
    id: int
    array_id: str
    registration_token: str = ""
    agent_version: str = ""
    config_version: str = ""
    last_seen_at: Optional[datetime] = None
    registration_state: str = "pending"
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
