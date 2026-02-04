"""
Query model definitions for custom queries.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.sql import func

from ..db.database import Base


class RuleType(str, Enum):
    """Query rule type"""
    VALID_MATCH = "valid_match"      # Match = normal
    INVALID_MATCH = "invalid_match"  # Match = abnormal
    REGEX_EXTRACT = "regex_extract"  # Extract fields


class QueryStatus(str, Enum):
    """Query execution status"""
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    PENDING = "pending"


# SQLAlchemy Model
class QueryTemplateModel(Base):
    """Query template database model"""
    __tablename__ = "query_templates"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    commands = Column(Text, nullable=False)  # JSON array
    rule_type = Column(String(32), nullable=False)
    pattern = Column(Text, default="")
    expect_match = Column(Boolean, default=True)
    extract_fields = Column(Text, default="[]")  # JSON array
    is_builtin = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# Pydantic Models for API
class ExtractField(BaseModel):
    """Field extraction definition"""
    name: str
    pattern: str


class QueryRule(BaseModel):
    """Query matching rule"""
    rule_type: RuleType = RuleType.VALID_MATCH
    pattern: str = ""
    expect_match: bool = True
    extract_fields: List[ExtractField] = []


class QueryTemplateBase(BaseModel):
    """Base query template schema"""
    name: str
    description: str = ""
    commands: List[str]
    rule: QueryRule


class QueryTemplateCreate(QueryTemplateBase):
    """Schema for creating query template"""
    pass


class QueryTemplateResponse(QueryTemplateBase):
    """Schema for query template response"""
    id: int
    is_builtin: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True


class QueryTemplate(QueryTemplateBase):
    """Full query template model"""
    id: int
    is_builtin: bool = False
    
    class Config:
        orm_mode = True


class QueryTask(BaseModel):
    """Query execution task"""
    name: str = ""
    commands: List[str]
    target_arrays: List[str]
    rule: QueryRule
    loop_interval: int = 0  # 0 = single execution


class QueryResultItem(BaseModel):
    """Single query result item"""
    array_id: str
    array_name: str
    command: str
    output: str
    status: QueryStatus
    matched_values: List[str] = []
    extracted_fields: Dict[str, List[str]] = {}
    error: str = ""
    execution_time_ms: int = 0


class QueryResult(BaseModel):
    """Query execution result"""
    task_id: str
    task_name: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    results: List[QueryResultItem] = []
    is_loop: bool = False
    loop_count: int = 0
