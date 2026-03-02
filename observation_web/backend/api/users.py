"""
User management API endpoints.

Lightweight user tracking based on IP address.
No authentication required.
"""

import logging
from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..models.user_session import (
    UserSessionModel,
    UserSessionResponse,
    OnlineUser,
    SetNicknameRequest,
)
from ..middleware.user_session import ip_to_color, get_all_presence

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])

# Consider user "online" if active within last 5 minutes
ONLINE_THRESHOLD_MINUTES = 5


@router.get("/online", response_model=List[OnlineUser])
async def get_online_users(
    db: AsyncSession = Depends(get_db),
):
    """
    Get list of currently online users.

    Users are considered online if they have been active in the last 5 minutes.
    """
    cutoff = datetime.now() - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)

    result = await db.execute(
        select(UserSessionModel)
        .where(UserSessionModel.last_seen >= cutoff)
        .where(UserSessionModel.is_active == True)
        .order_by(UserSessionModel.last_seen.desc())
    )
    sessions = result.scalars().all()

    # Get current presence info
    presence = get_all_presence()

    users = []
    for session in sessions:
        viewing_page = None
        if session.ip in presence:
            viewing_page = presence[session.ip].get('page')

        users.append(OnlineUser(
            ip=session.ip,
            nickname=session.nickname or "",
            color=ip_to_color(session.ip),
            last_seen=session.last_seen,
            viewing_page=viewing_page,
        ))

    return users


@router.get("/me", response_model=UserSessionResponse)
async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Get current user's session info.
    """
    user_ip = getattr(request.state, 'user_ip', None)
    if not user_ip:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to determine user IP"
        )

    result = await db.execute(
        select(UserSessionModel).where(UserSessionModel.ip == user_ip)
    )
    session = result.scalar_one_or_none()

    if not session:
        # Create new session
        session = UserSessionModel(
            ip=user_ip,
            nickname="",
            is_active=True,
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)

    return UserSessionResponse(
        id=session.id,
        ip=session.ip,
        nickname=session.nickname or "",
        first_seen=session.first_seen,
        last_seen=session.last_seen,
        is_active=session.is_active,
        color=ip_to_color(session.ip),
    )


@router.post("/me/nickname", response_model=UserSessionResponse)
async def set_nickname(
    request: Request,
    body: SetNicknameRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Set current user's nickname.
    """
    user_ip = getattr(request.state, 'user_ip', None)
    if not user_ip:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to determine user IP"
        )

    result = await db.execute(
        select(UserSessionModel).where(UserSessionModel.ip == user_ip)
    )
    session = result.scalar_one_or_none()

    if not session:
        session = UserSessionModel(
            ip=user_ip,
            nickname=body.nickname.strip()[:64],
            is_active=True,
        )
        db.add(session)
    else:
        session.nickname = body.nickname.strip()[:64]

    await db.commit()
    await db.refresh(session)

    logger.info(f"User {user_ip} set nickname to '{session.nickname}'")

    return UserSessionResponse(
        id=session.id,
        ip=session.ip,
        nickname=session.nickname or "",
        first_seen=session.first_seen,
        last_seen=session.last_seen,
        is_active=session.is_active,
        color=ip_to_color(session.ip),
    )


@router.get("/count")
async def get_user_count(
    db: AsyncSession = Depends(get_db),
):
    """
    Get count of online users.
    """
    from sqlalchemy import func

    cutoff = datetime.now() - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)

    result = await db.execute(
        select(func.count(UserSessionModel.id))
        .where(UserSessionModel.last_seen >= cutoff)
        .where(UserSessionModel.is_active == True)
    )
    count = result.scalar() or 0

    return {"online_count": count}
