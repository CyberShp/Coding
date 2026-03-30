"""
System configuration and schema version models.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func

from ..db.database import Base


# SQLAlchemy Models
class SystemConfigModel(Base):
    """Platform configuration key-value store"""
    __tablename__ = "system_config"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(128), unique=True, index=True, nullable=False)
    value = Column(Text, nullable=False)
    description = Column(Text, default="")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class SchemaVersionModel(Base):
    """Schema version tracking"""
    __tablename__ = "schema_version"

    id = Column(Integer, primary_key=True, index=True)
    version = Column(String(32), nullable=False)
    applied_at = Column(DateTime, server_default=func.now())
    description = Column(Text, default="")


# Pydantic Models for API
class SystemConfigResponse(BaseModel):
    """Schema for system config response"""
    id: int
    key: str
    value: str
    description: str = ""
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SchemaVersionResponse(BaseModel):
    """Schema for schema version response"""
    id: int
    version: str
    applied_at: datetime
    description: str = ""

    model_config = ConfigDict(from_attributes=True)
