"""
Admin authentication API.

支持两种认证模式：
- internal: 内部网络模式，不需要鉴权
- jwt: 标准JWT认证，需要用户名密码
"""

import logging
import time
from typing import Optional
import hashlib
import hmac
import json
from fastapi import APIRouter, Depends, Request, HTTPException, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# ============== 配置 ==============
# 认证模式: "internal" (内部网络) 或 "jwt" (标准JWT)
AUTH_MODE = "internal"

# JWT密钥 (仅在jwt模式下使用)
JWT_SECRET = "observation-web-secret-key-change-in-production"
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

# 硬编码默认管理员账户
DEFAULT_ADMIN = {
    "username": "admin",
    "password": "admin123",
}

# ============== 数据模型 ==============
class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    expires_at: str
    message: str


class UserInfo(BaseModel):
    username: str
    is_admin: bool


# ============== JWT认证 ==============
def _create_token(username: str) -> tuple[str, str]:
    """创建JWT token"""
    expire = int(time.time()) + TOKEN_EXPIRE_HOURS * 3600
    payload = {
        "sub": username,
        "exp": expire,
    }
    # 简单JWT (实际生产应使用pyjwt)
    header = f'{{"alg":"{JWT_ALGORITHM}","typ":"JWT"}}'
    payload_b64 = f'.{base64url_encode(json.dumps(payload))}'
    signature = base64url_encode(
        hmac.new(JWT_SECRET.encode(), f'{header}{payload_b64}'.encode(), hashlib.sha256).digest()
    )
    token = f'{header}{payload_b64}{signature}'
    from datetime import datetime
    expires_at = datetime.fromtimestamp(expire).isoformat()
    return token, expires_at


def base64url_encode(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _verify_token(token: str) -> Optional[dict]:
    """验证JWT token"""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        header, payload_b64, signature = parts
        # 验证签名
        expected_sig = base64url_encode(
            hmac.new(JWT_SECRET.encode(), f'{header}.{payload_b64}'.encode(), hashlib.sha256).digest()
        )
        if signature != expected_sig:
            return None
        # 解析payload
        import base64
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += '=' * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        # 检查过期
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception as e:
        logger.warning(f"Token验证失败: {e}")
        return None


# ============== 认证依赖 ==============
async def require_admin(request: Request) -> dict:
    """
    Dependency: 要求管理员权限
    
    根据AUTH_MODE决定验证方式:
    - internal: 直接返回管理员权限
    - jwt: 验证请求中的token
    """
    if AUTH_MODE == "internal":
        # 内部网络模式：直接返回管理员权限
        return {
            "sub": DEFAULT_ADMIN["username"],
            "username": DEFAULT_ADMIN["username"],
            "is_admin": True,
        }
    
    # JWT模式：验证token
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header"
        )
    
    token = auth_header[7:]
    payload = _verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    
    return {
        "sub": payload.get("sub"),
        "username": payload.get("sub"),
        "is_admin": True,  # 当前只有admin用户
    }


# ============== API路由 ==============
@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    """
    Admin login.
    
    - internal模式: 接受任意账号密码，返回成功
    - jwt模式: 验证账号密码，发放token
    """
    if AUTH_MODE == "internal":
        # 内部网络模式
        return LoginResponse(
            token="internal-network-mode",
            username=body.username,
            expires_at="2099-12-31T23:59:59",
            message="登录成功（内部网络模式）"
        )
    
    # JWT模式
    if body.username != DEFAULT_ADMIN["username"] or body.password != DEFAULT_ADMIN["password"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )
    
    token, expires_at = _create_token(body.username)
    return LoginResponse(
        token=token,
        username=body.username,
        expires_at=expires_at,
        message="登录成功"
    )


@router.get("/me", response_model=UserInfo)
async def get_current_user(admin: dict = Depends(require_admin)):
    """获取当前用户信息"""
    return UserInfo(
        username=admin["username"],
        is_admin=admin.get("is_admin", True)
    )


@router.post("/logout")
async def logout():
    """退出登录"""
    return {"message": "退出成功"}


# 健康检查端点
@router.get("/health")
async def auth_health():
    """认证服务健康检查"""
    return {
        "status": "ok",
        "auth_mode": AUTH_MODE,
    }
