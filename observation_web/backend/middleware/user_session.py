"""
User session middleware for IP-based user tracking.

Extracts user IP from requests and maintains session records.
"""

import hashlib
import logging
from datetime import datetime, timedelta

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# In-memory cache for user sessions to reduce DB writes
_session_cache: dict = {}
_CACHE_UPDATE_INTERVAL = 60  # seconds


def get_client_ip(request: Request) -> str:
    """
    Extract client IP from request.

    Handles X-Forwarded-For and X-Real-IP headers for proxy setups.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    if request.client:
        return request.client.host

    return "unknown"


def ip_to_color(ip: str) -> str:
    """
    Generate a consistent color from IP address.

    Uses hash to create a unique color for each IP.
    """
    hash_hex = hashlib.md5(ip.encode()).hexdigest()[:6]
    r = int(hash_hex[0:2], 16)
    g = int(hash_hex[2:4], 16)
    b = int(hash_hex[4:6], 16)

    # Ensure colors are not too light (for visibility)
    r = min(r, 200)
    g = min(g, 200)
    b = min(b, 200)

    return f"#{r:02x}{g:02x}{b:02x}"


class UserSessionMiddleware(BaseHTTPMiddleware):
    """
    Middleware to track user sessions by IP.

    Updates session records on each request (with caching to reduce DB load).
    Injects user_ip into request.state for use by endpoints.
    """

    async def dispatch(self, request: Request, call_next):
        user_ip = get_client_ip(request)

        # Inject IP into request state
        request.state.user_ip = user_ip
        request.state.user_color = ip_to_color(user_ip)

        # Update session in background (non-blocking)
        await self._update_session(user_ip, str(request.url.path))

        response = await call_next(request)
        return response

    async def _update_session(self, ip: str, current_page: str):
        """
        Update user session record.

        Uses caching to reduce DB writes - only updates if more than
        CACHE_UPDATE_INTERVAL seconds have passed since last update.
        """
        now = datetime.now()

        # Check cache
        cached = _session_cache.get(ip)
        if cached and (now - cached['last_update']).seconds < _CACHE_UPDATE_INTERVAL:
            return

        # Update cache
        _session_cache[ip] = {
            'last_update': now,
            'current_page': current_page,
        }

        # Update database (async, non-blocking)
        try:
            from ..db.database import AsyncSessionLocal
            from ..models.user_session import UserSessionModel
            from sqlalchemy import select

            if not AsyncSessionLocal:
                return

            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserSessionModel).where(UserSessionModel.ip == ip)
                )
                user_session = result.scalar_one_or_none()

                if user_session:
                    user_session.last_seen = now
                    user_session.is_active = True
                else:
                    user_session = UserSessionModel(
                        ip=ip,
                        nickname="",
                        is_active=True,
                    )
                    session.add(user_session)

                await session.commit()

        except Exception as e:
            logger.debug(f"Failed to update user session: {e}")


# Store for tracking which page each user is viewing (for presence)
_user_presence: dict = {}


def update_user_presence(ip: str, page: str):
    """Update which page a user is currently viewing."""
    _user_presence[ip] = {
        'page': page,
        'timestamp': datetime.now(),
    }


def get_users_on_page(page: str, max_age_seconds: int = 60) -> list:
    """Get list of user IPs currently viewing a specific page."""
    cutoff = datetime.now() - timedelta(seconds=max_age_seconds)
    return [
        ip for ip, info in _user_presence.items()
        if info['page'] == page and info['timestamp'] > cutoff
    ]


def get_all_presence() -> dict:
    """Get all user presence info."""
    cutoff = datetime.now() - timedelta(seconds=120)
    return {
        ip: info for ip, info in _user_presence.items()
        if info['timestamp'] > cutoff
    }
