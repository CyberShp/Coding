"""
User management API endpoints.

Lightweight user tracking based on IP address.
No authentication required.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..models.user_session import (
    UserSessionModel,
    UserSessionResponse,
    OnlineUser,
    SetNicknameRequest,
    ClaimNicknameRequest,
)
from ..models.array_lock import ArrayLockModel
from ..models.user_preference import UserPreferenceModel
from ..middleware.user_session import ip_to_color, get_all_presence
from ..core.profanity import check_nickname

logger = logging.getLogger(__name__)


class UserPreferencesResponse(BaseModel):
    default_tag_id: Optional[int] = None
    watched_tag_ids: list[int] = []
    watched_array_ids: list[str] = []
    watched_observers: list[str] = []
    muted_observers: list[str] = []
    alert_sound: bool = True
    dashboard_l1_tag_id: Optional[int] = None


class UserPreferencesUpdate(BaseModel):
    default_tag_id: Optional[int] = None
    watched_tag_ids: Optional[list[int]] = None
    watched_array_ids: Optional[list[str]] = None
    watched_observers: Optional[list[str]] = None
    muted_observers: Optional[list[str]] = None
    alert_sound: Optional[bool] = None
    dashboard_l1_tag_id: Optional[int] = None


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

    compliant, _ = check_nickname(session.nickname or "")
    return UserSessionResponse(
        id=session.id,
        ip=session.ip,
        nickname=session.nickname or "",
        first_seen=session.first_seen,
        last_seen=session.last_seen,
        is_active=session.is_active,
        color=ip_to_color(session.ip),
        nickname_compliant=compliant,
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

    nickname = body.nickname.strip()[:64]
    compliant, reason = check_nickname(nickname)
    if not compliant:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)

    dup = await db.execute(
        select(UserSessionModel).where(
            UserSessionModel.nickname == nickname,
            UserSessionModel.ip != user_ip,
        )
    )
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="昵称已被使用")

    result = await db.execute(
        select(UserSessionModel).where(UserSessionModel.ip == user_ip)
    )
    session = result.scalar_one_or_none()

    if not session:
        session = UserSessionModel(
            ip=user_ip,
            nickname=nickname,
            is_active=True,
        )
        db.add(session)
    else:
        session.nickname = nickname

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
        nickname_compliant=True,
    )


@router.post("/claim", response_model=UserSessionResponse)
async def claim_nickname(
    request: Request,
    body: ClaimNicknameRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Claim existing nickname when user's IP has changed (e.g. after computer restart).
    Migrates the old session to the new IP, including array locks.
    """
    new_ip = getattr(request.state, 'user_ip', None)
    if not new_ip:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to determine user IP"
        )

    nickname = body.nickname.strip()[:64]
    if not nickname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="昵称不能为空"
        )

    # Find session with this nickname (old session)
    result = await db.execute(
        select(UserSessionModel).where(UserSessionModel.nickname == nickname)
    )
    old_session = result.scalar_one_or_none()

    if not old_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="未找到该昵称，请确认昵称正确"
        )

    if old_session.ip == new_ip:
        # Same IP, nothing to migrate
        await db.refresh(old_session)
        compliant, _ = check_nickname(old_session.nickname or "")
        return UserSessionResponse(
            id=old_session.id,
            ip=old_session.ip,
            nickname=old_session.nickname or "",
            first_seen=old_session.first_seen,
            last_seen=old_session.last_seen,
            is_active=old_session.is_active,
            color=ip_to_color(old_session.ip),
            nickname_compliant=compliant,
        )

    old_ip = old_session.ip

    # Delete the new session if it exists (created on first visit with new IP)
    # Must do this before updating old_session.ip to avoid unique constraint violation
    result_new = await db.execute(
        select(UserSessionModel).where(UserSessionModel.ip == new_ip)
    )
    new_session_row = result_new.scalar_one_or_none()
    if new_session_row and new_session_row.id != old_session.id:
        await db.delete(new_session_row)

    # Migrate array locks from old IP to new IP
    await db.execute(
        update(ArrayLockModel)
        .where(ArrayLockModel.locked_by_ip == old_ip)
        .values(locked_by_ip=new_ip)
    )

    # Update previous_ips
    try:
        prev_ips = json.loads(old_session.previous_ips or "[]")
    except (json.JSONDecodeError, TypeError):
        prev_ips = []
    if old_ip not in prev_ips:
        prev_ips.append(old_ip)
    old_session.previous_ips = json.dumps(prev_ips)

    # Update old session's IP to new IP
    old_session.ip = new_ip
    old_session.last_seen = datetime.now()
    old_session.is_active = True

    await db.commit()
    await db.refresh(old_session)

    logger.info(f"User claimed nickname '{nickname}': {old_ip} -> {new_ip}")

    compliant, _ = check_nickname(old_session.nickname or "")
    return UserSessionResponse(
        id=old_session.id,
        ip=old_session.ip,
        nickname=old_session.nickname or "",
        first_seen=old_session.first_seen,
        last_seen=old_session.last_seen,
        is_active=old_session.is_active,
        color=ip_to_color(old_session.ip),
        nickname_compliant=compliant,
    )


@router.get("/me/preferences", response_model=UserPreferencesResponse)
async def get_my_preferences(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get current user's preferences for personal view."""
    user_ip = getattr(request.state, 'user_ip', None)
    if not user_ip:
        raise HTTPException(status_code=400, detail="Unable to determine user IP")
    result = await db.execute(
        select(UserPreferenceModel).where(UserPreferenceModel.ip == user_ip)
    )
    pref = result.scalar_one_or_none()
    if not pref:
        return UserPreferencesResponse()
    return UserPreferencesResponse(
        default_tag_id=pref.default_tag_id,
        watched_tag_ids=json.loads(pref.watched_tag_ids or "[]"),
        watched_array_ids=json.loads(pref.watched_array_ids or "[]"),
        watched_observers=json.loads(pref.watched_observers or "[]"),
        muted_observers=json.loads(pref.muted_observers or "[]"),
        alert_sound=pref.alert_sound if pref.alert_sound is not None else True,
        dashboard_l1_tag_id=getattr(pref, 'dashboard_l1_tag_id', None),
    )


@router.put("/me/preferences", response_model=UserPreferencesResponse)
async def update_my_preferences(
    request: Request,
    body: UserPreferencesUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update current user's preferences."""
    user_ip = getattr(request.state, 'user_ip', None)
    if not user_ip:
        raise HTTPException(status_code=400, detail="Unable to determine user IP")
    result = await db.execute(
        select(UserPreferenceModel).where(UserPreferenceModel.ip == user_ip)
    )
    pref = result.scalar_one_or_none()
    if not pref:
        pref = UserPreferenceModel(ip=user_ip)
        db.add(pref)
    if body.default_tag_id is not None:
        pref.default_tag_id = body.default_tag_id
    elif 'default_tag_id' in body.model_fields_set:
        pref.default_tag_id = None
    if body.watched_tag_ids is not None:
        pref.watched_tag_ids = json.dumps(body.watched_tag_ids)
    if body.watched_array_ids is not None:
        pref.watched_array_ids = json.dumps(body.watched_array_ids)
    if body.watched_observers is not None:
        pref.watched_observers = json.dumps(body.watched_observers)
    if body.muted_observers is not None:
        pref.muted_observers = json.dumps(body.muted_observers)
    if body.alert_sound is not None:
        pref.alert_sound = body.alert_sound
    if body.dashboard_l1_tag_id is not None:
        pref.dashboard_l1_tag_id = body.dashboard_l1_tag_id
    elif 'dashboard_l1_tag_id' in body.model_fields_set:
        pref.dashboard_l1_tag_id = None
    pref.updated_at = datetime.now()
    await db.commit()
    await db.refresh(pref)
    return UserPreferencesResponse(
        default_tag_id=pref.default_tag_id,
        watched_tag_ids=json.loads(pref.watched_tag_ids or "[]"),
        watched_array_ids=json.loads(pref.watched_array_ids or "[]"),
        watched_observers=json.loads(pref.watched_observers or "[]"),
        muted_observers=json.loads(pref.muted_observers or "[]"),
        alert_sound=pref.alert_sound if pref.alert_sound is not None else True,
        dashboard_l1_tag_id=getattr(pref, 'dashboard_l1_tag_id', None),
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
