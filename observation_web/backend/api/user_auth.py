"""
User account API (multi-user Phase 1).

Lightweight accounts: nickname + password. Tokens reuse the HMAC signing
mechanism from ``api/auth.py`` with payload::

    {sub: str(user.id), typ: "user", nickname, is_admin, exp, iat}

Endpoints:
- POST /auth/register        register (first user becomes admin)
- POST /auth/user-login      login, returns token
- GET  /auth/whoami          current user info (anonymous-friendly)
- PUT  /auth/me/teams        replace own team memberships (L1 tag ids)
- POST /auth/admin/grant/{user_id}   grant admin (admin only)
"""

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..models.user_account import (
    UserAccountModel,
    UserLoginRequest,
    UserRegisterRequest,
    UserTeamModel,
    UserTeamsUpdateRequest,
    UserTokenResponse,
    hash_password,
    verify_password,
)
from .auth import _get_secret, get_current_user, require_admin, require_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["user-auth"])

_TOKEN_EXPIRES_DAYS = 7


def _create_user_token(user: UserAccountModel) -> UserTokenResponse:
    """Create a signed user token (same HMAC scheme as admin tokens)."""
    expires_at = datetime.utcnow() + timedelta(days=_TOKEN_EXPIRES_DAYS)
    payload = {
        "sub": str(user.id),
        "typ": "user",
        "nickname": user.nickname,
        "is_admin": bool(user.is_admin),
        "exp": expires_at.isoformat(),
        "iat": datetime.utcnow().isoformat(),
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(_get_secret(), payload_b64.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return UserTokenResponse(
        token=f"{payload_b64}.{sig_b64}",
        user_id=user.id,
        nickname=user.nickname,
        is_admin=bool(user.is_admin),
        expires_at=expires_at.isoformat(),
    )


async def _get_team_ids(db: AsyncSession, user_id: int) -> list:
    result = await db.execute(
        select(UserTeamModel.tag_id).where(UserTeamModel.user_id == user_id)
    )
    return [row[0] for row in result.all()]


@router.post("/register", response_model=UserTokenResponse)
async def register(body: UserRegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new account. The first registered user becomes admin."""
    nickname = (body.nickname or "").strip()
    if not nickname:
        raise HTTPException(status_code=400, detail="昵称不能为空")
    if len(nickname) > 64:
        raise HTTPException(status_code=400, detail="昵称过长（最多 64 字符）")
    if not body.password or len(body.password) < 4:
        raise HTTPException(status_code=400, detail="口令至少 4 位")

    result = await db.execute(
        select(UserAccountModel).where(UserAccountModel.nickname == nickname)
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="昵称已被注册")

    count = (await db.execute(select(func.count(UserAccountModel.id)))).scalar() or 0
    user = UserAccountModel(
        nickname=nickname,
        password_hash=hash_password(body.password),
        is_admin=(count == 0),  # first registered user is admin
        last_login_at=datetime.now(),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("User registered: %s (id=%s, admin=%s)", nickname, user.id, user.is_admin)
    return _create_user_token(user)


@router.post("/user-login", response_model=UserTokenResponse)
async def user_login(body: UserLoginRequest, db: AsyncSession = Depends(get_db)):
    """Login with nickname + password. Returns a 7-day token."""
    nickname = (body.nickname or "").strip()
    result = await db.execute(
        select(UserAccountModel).where(UserAccountModel.nickname == nickname)
    )
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password or "", user.password_hash):
        raise HTTPException(status_code=401, detail="昵称或口令错误")

    user.last_login_at = datetime.now()
    await db.commit()
    await db.refresh(user)
    return _create_user_token(user)


@router.get("/whoami")
async def whoami(request: Request, db: AsyncSession = Depends(get_db)):
    """Current user info (teams included). Anonymous returns {anonymous: true}."""
    user = await get_current_user(request)
    if user is None:
        return {"anonymous": True}
    teams = await _get_team_ids(db, user.id) if user.id else []
    return {
        "anonymous": False,
        "user_id": user.id,
        "nickname": user.nickname,
        "is_admin": bool(user.is_admin),
        "teams": teams,
        "legacy_admin": user.id == 0,
    }


@router.put("/me/teams")
async def set_my_teams(
    body: UserTeamsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: UserAccountModel = Depends(require_user),
):
    """Replace the caller's team memberships (full replace)."""
    if user.id == 0:
        raise HTTPException(status_code=400, detail="legacy admin 无个人小组")
    tag_ids = sorted({int(t) for t in body.tag_ids})
    await db.execute(delete(UserTeamModel).where(UserTeamModel.user_id == user.id))
    for tag_id in tag_ids:
        db.add(UserTeamModel(user_id=user.id, tag_id=tag_id))
    await db.commit()
    return {"user_id": user.id, "teams": tag_ids}


@router.post("/admin/grant/{user_id}")
async def grant_admin(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _payload: dict = Depends(require_admin),
):
    """Grant admin to a user (admin only)."""
    target = await db.get(UserAccountModel, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    target.is_admin = True
    await db.commit()
    return {"user_id": target.id, "nickname": target.nickname, "is_admin": True}
