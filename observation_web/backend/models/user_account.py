"""
User account models for the multi-user account system (Phase 1).

Lightweight accounts: nickname + password. Anonymous users keep read
access; any write operation requires login (see ``require_user``).

Password storage: PBKDF2-HMAC-SHA256 with a random salt, stored as
``salt_hex$hash_hex``. No third-party dependencies.
"""

import hashlib
import hmac
import secrets
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from ..db.database import Base

_PBKDF2_ITERATIONS = 100_000


# ---------------------------------------------------------------------------
# Password helpers (sha256 + random salt, stdlib only)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 and a random salt.

    Returns ``salt_hex$hash_hex`` (fits in String(128)).
    """
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored ``salt$hash`` value."""
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
    except (ValueError, AttributeError):
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(digest.hex(), hash_hex)


# ---------------------------------------------------------------------------
# SQLAlchemy models
# ---------------------------------------------------------------------------

class UserAccountModel(Base):
    """User account (nickname + password login)."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    nickname = Column(String(64), unique=True, index=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    last_login_at = Column(DateTime, nullable=True)


class UserTeamModel(Base):
    """User <-> team (L1 tag) membership. Self-selected, multiple allowed."""
    __tablename__ = "user_teams"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    tag_id = Column(Integer, index=True, nullable=False)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class UserRegisterRequest(BaseModel):
    nickname: str
    password: str


class UserLoginRequest(BaseModel):
    nickname: str
    password: str


class UserTokenResponse(BaseModel):
    token: str
    user_id: int
    nickname: str
    is_admin: bool
    expires_at: str


class UserTeamsUpdateRequest(BaseModel):
    tag_ids: List[int]


class WhoAmIResponse(BaseModel):
    anonymous: bool = False
    user_id: Optional[int] = None
    nickname: Optional[str] = None
    is_admin: bool = False
    teams: List[int] = []
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
