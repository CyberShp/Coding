"""
Admin authentication API (简化版).

内部网络不需要鉴权，直接返回管理员权限。
保留登录接口用于兼容性，但不强制要求。
"""

import logging
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# 硬编码默认管理员账户
DEFAULT_ADMIN = {
    "username": "admin",
    "password": "admin123",
}


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    expires_at: str
    message: str = "登录成功（内部网络模式）"


async def require_admin(request: Request) -> dict:
    """
    Dependency: 内部网络不需要鉴权，直接返回管理员权限。
    
    对于需要管理员权限的 API 调用，此依赖直接返回默认管理员信息，
    无需验证 token。适用于内部部署场景。
    """
    # 直接返回默认管理员权限
    return {
        "sub": DEFAULT_ADMIN["username"],
        "username": DEFAULT_ADMIN["username"],
        "is_admin": True,
    }


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    """
    Admin login (保留接口用于兼容性).
    
    内部网络模式下不验证密码，仅返回成功响应。
    """
    # 内部网络模式：接受任意登录，返回成功
    return LoginResponse(
        token="internal-network-mode",
        username=body.username,
        expires_at="2099-12-31T23:59:59",
    )


@router.get("/me")
async def get_me(request: Request):
    """返回当前管理员信息."""
    return {
        "username": DEFAULT_ADMIN["username"],
        "is_admin": True,
        "mode": "internal",
    }


@router.post("/logout")
async def logout():
    """Logout (内部网络模式无状态)."""
    return {"ok": True, "message": "已退出登录"}
