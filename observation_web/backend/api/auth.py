"""
Admin authentication API.

JWT-like tokens for admin-only operations (Issue status, etc.).
No global auth - normal users browse without login.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from ..config import get_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# Secret for signing tokens (derived from config)
def _get_secret() -> bytes:
    cfg = get_config()
    raw = f"{cfg.admin.username}:{cfg.admin.password}:observation_web"
    return hashlib.sha256(raw.encode()).digest()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    expires_at: str


def _create_token(username: str, expires_minutes: int = 60 * 24) -> str:
    """Create a signed token (JWT-like)."""
    payload = {
        "sub": username,
        "exp": (datetime.utcnow() + timedelta(minutes=expires_minutes)).isoformat(),
        "iat": datetime.utcnow().isoformat(),
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(_get_secret(), payload_b64.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{payload_b64}.{sig_b64}"


def _verify_token(token: str) -> Optional[dict]:
    """Verify token and return payload or None."""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        payload_b64 = parts[0]
        # Restore padding
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload_json = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_json)

        expected_sig = hmac.new(_get_secret(), parts[0].encode(), hashlib.sha256).digest()
        sig_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        actual_sig = base64.urlsafe_b64decode(sig_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        exp = datetime.fromisoformat(payload.get("exp", ""))
        if datetime.utcnow() > exp:
            return None
        return payload
    except Exception:
        return None


async def require_admin(request: Request) -> dict:
    """Dependency: require valid admin token. Raise 401 if not authenticated."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
    else:
        token = request.query_params.get("token", "")
    if not token:
        raise HTTPException(status_code=401, detail="需要管理员登录")
    payload = _verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="token 无效或已过期")
    return payload


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    """Admin login. Returns JWT token."""
    cfg = get_config()
    if body.username != cfg.admin.username or body.password != cfg.admin.password:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    expires_minutes = 60 * 24  # 24 hours
    token = _create_token(body.username, expires_minutes)
    expires_at = (datetime.utcnow() + timedelta(minutes=expires_minutes)).isoformat()
    return LoginResponse(token=token, username=body.username, expires_at=expires_at)


@router.get("/me")
async def get_me(payload: dict = Depends(require_admin)):
    """Verify token and return admin info."""
    return {"username": payload.get("sub"), "valid": True}


@router.post("/logout")
async def logout():
    """Logout (client clears token). No server-side session."""
    return {"ok": True}
