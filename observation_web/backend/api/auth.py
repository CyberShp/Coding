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


def _extract_token(request: Request) -> str:
    """Extract bearer token from Authorization header or ?token= query param."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.query_params.get("token", "")


def _is_user_payload(payload: dict) -> bool:
    return payload.get("typ") == "user"


async def get_current_user(request: Request):
    """Optional dependency: resolve the current user from a bearer token.

    Returns a ``UserAccountModel`` instance, or ``None`` for anonymous
    requests.  A legacy admin token (issued by /auth/login) is mapped to a
    virtual admin identity (detached model, id=0) so existing admin
    workflows keep working.
    """
    from ..models.user_account import UserAccountModel

    token = _extract_token(request)
    if not token:
        return None
    payload = _verify_token(token)
    if not payload:
        return None

    if _is_user_payload(payload):
        try:
            user_id = int(payload.get("sub", ""))
        except (TypeError, ValueError):
            return None
        from ..db.database import AsyncSessionLocal
        if AsyncSessionLocal is None:
            return None
        async with AsyncSessionLocal() as session:
            user = await session.get(UserAccountModel, user_id)
        return user

    # Legacy admin token (config.json account) -> virtual admin identity
    virtual = UserAccountModel(
        id=0,
        nickname=str(payload.get("sub") or "admin"),
        password_hash="",
        is_admin=True,
    )
    return virtual


async def require_user(request: Request):
    """Dependency: require a logged-in user for write operations.

    Raises 401 {"detail": "login_required"} for anonymous requests.
    """
    user = await get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="login_required")
    return user


async def require_admin(request: Request) -> dict:
    """Dependency: require admin identity. Raise 401 if not authenticated.

    Accepts either a legacy admin token (issued via /auth/login from the
    config.json emergency account) or a user token whose account has
    is_admin=True.
    """
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="需要管理员登录")
    payload = _verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="token 无效或已过期")
    if _is_user_payload(payload):
        user = await get_current_user(request)
        if user is None or not user.is_admin:
            raise HTTPException(status_code=403, detail="需要管理员权限")
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
