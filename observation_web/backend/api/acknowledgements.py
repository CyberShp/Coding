"""
Alert acknowledgement API endpoints.

Allows users to acknowledge alerts with different types:
- dismiss:      Temporarily hide (default, auto-expires in 24h)
- confirmed_ok: Permanently confirmed as non-issue
- deferred:     Acknowledged but needs revisiting (user-set expiry)

Track who acknowledged (by client IP), and undo acknowledgements.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query, status, Body
from pydantic import BaseModel
from sqlalchemy import select, delete, exists, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..models.alert import (
    AlertModel, AlertAckModel, AlertAckCreate, AlertAckResponse, AckType,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alerts", tags=["acknowledgements"])

# Default expiry hours for dismiss type
_DISMISS_DEFAULT_HOURS = 24


@router.post("/ack", response_model=List[AlertAckResponse])
async def ack_alerts(
    body: AlertAckCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Acknowledge one or more alerts.

    Creates ack records for the given alert IDs.
    Skips alerts that are already acknowledged (idempotent).
    Uses ``request.client.host`` as the acknowledger identity.
    """
    client_ip = request.client.host if request.client else "unknown"

    if not body.alert_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="alert_ids must not be empty",
        )

    # Validate ack_type
    valid_types = {t.value for t in AckType}
    ack_type = body.ack_type if body.ack_type in valid_types else AckType.DISMISS.value

    # Compute expiry
    expires_at = None
    if ack_type == AckType.DISMISS.value:
        expires_at = datetime.now() + timedelta(hours=_DISMISS_DEFAULT_HOURS)
    elif ack_type == AckType.DEFERRED.value:
        hours = body.expires_hours or 72  # default 3 days for deferred
        expires_at = datetime.now() + timedelta(hours=hours)
    elif ack_type == AckType.CONFIRMED_OK.value and body.expires_hours:
        # confirmed_ok with optional expiry: 2/4/6/8/12/24 hours
        h = body.expires_hours
        if h not in (2, 4, 6, 8, 12, 24):
            h = 24
        expires_at = datetime.now() + timedelta(hours=h)

    # Verify all alert IDs exist
    result = await db.execute(
        select(AlertModel.id).where(AlertModel.id.in_(body.alert_ids))
    )
    existing_ids = {row[0] for row in result.all()}
    missing = set(body.alert_ids) - existing_ids
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert IDs not found: {sorted(missing)}",
        )

    # Find which are already acked (skip those)
    result = await db.execute(
        select(AlertAckModel.alert_id).where(
            AlertAckModel.alert_id.in_(body.alert_ids)
        )
    )
    already_acked = {row[0] for row in result.all()}
    to_ack = [aid for aid in body.alert_ids if aid not in already_acked]

    created = []
    for alert_id in to_ack:
        ack = AlertAckModel(
            alert_id=alert_id,
            acked_by_ip=client_ip,
            comment=body.comment,
            ack_type=ack_type,
            ack_expires_at=expires_at,
            note=body.comment,
        )
        db.add(ack)
        created.append(ack)

    if created:
        await db.commit()
        for ack in created:
            await db.refresh(ack)

        # Attempt to clear matching active issues from in-memory cache
        try:
            await _clear_acked_active_issues(db, to_ack)
        except Exception:
            logger.debug("Failed to clear active issues cache (non-critical)")

    return created


@router.post("/ack-all-visible", response_model=dict)
async def ack_all_visible(
    request: Request,
    db: AsyncSession = Depends(get_db),
    hours: int = Query(2, ge=1, le=168, description="Only ack alerts within this many hours"),
    ack_type: str = Query("dismiss", description="dismiss | confirmed_ok"),
):
    """
    Batch acknowledge all currently unacked alerts within the time range.
    Used by the banner "全部忽略 24 小时" to clear all visible alerts.
    """
    from datetime import datetime

    client_ip = request.client.host if request and request.client else "unknown"
    valid_types = {t.value for t in AckType}
    ack_type_val = ack_type if ack_type in valid_types else AckType.DISMISS.value

    expires_at = None
    if ack_type_val == AckType.DISMISS.value:
        expires_at = datetime.now() + timedelta(hours=_DISMISS_DEFAULT_HOURS)
    elif ack_type_val == AckType.DEFERRED.value:
        expires_at = datetime.now() + timedelta(hours=72)
    elif ack_type_val == AckType.CONFIRMED_OK.value:
        expires_at = datetime.now() + timedelta(hours=24)  # ack-all default 24h for confirmed_ok

    # Find unacked alerts in time range
    since = datetime.now() - timedelta(hours=hours)
    ack_exists = exists().where(AlertAckModel.alert_id == AlertModel.id)
    stmt = (
        select(AlertModel.id)
        .where(AlertModel.timestamp >= since)
        .where(~ack_exists)
    )
    result = await db.execute(stmt)
    unacked_ids = [row[0] for row in result.all()]

    if not unacked_ids:
        return {"acked_count": 0, "message": "No unacked alerts in range"}

    created = []
    for alert_id in unacked_ids:
        ack = AlertAckModel(
            alert_id=alert_id,
            acked_by_ip=client_ip,
            comment="",
            ack_type=ack_type_val,
            ack_expires_at=expires_at,
            note="Batch ack (ack-all-visible)",
        )
        db.add(ack)
        created.append(ack)

    await db.commit()
    try:
        await _clear_acked_active_issues(db, unacked_ids)
    except Exception:
        logger.debug("Failed to clear active issues cache (non-critical)")

    return {"acked_count": len(created), "message": f"Acknowledged {len(created)} alerts"}


@router.delete("/ack/{alert_id}")
async def unack_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Revoke acknowledgement for a specific alert.
    Deletes the ack record so the alert becomes unacknowledged again.
    """
    result = await db.execute(
        select(AlertAckModel).where(AlertAckModel.alert_id == alert_id)
    )
    ack = result.scalar_one_or_none()
    if not ack:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No acknowledgement found for alert {alert_id}",
        )
    await db.delete(ack)
    await db.commit()
    return {"status": "unacknowledged", "alert_id": alert_id}


class BatchUndoRequest(BaseModel):
    alert_ids: List[int]


class BatchModifyRequest(BaseModel):
    alert_ids: List[int]
    new_ack_type: str = "dismiss"
    expires_hours: Optional[int] = None  # For confirmed_ok: 2/4/6/8/12/24


@router.post("/ack/batch-undo", response_model=dict)
async def batch_undo_ack(
    body: BatchUndoRequest,
    db: AsyncSession = Depends(get_db),
):
    """Batch revoke acknowledgements for multiple alerts."""
    if not body.alert_ids:
        return {"undone_count": 0, "message": "No alert IDs provided"}
    result = await db.execute(delete(AlertAckModel).where(AlertAckModel.alert_id.in_(body.alert_ids)))
    await db.commit()
    undone = result.rowcount
    try:
        await _clear_acked_active_issues(db, [])  # Cache invalidation not needed for undo
    except Exception:
        pass
    return {"undone_count": undone, "message": f"Revoked {undone} acknowledgements"}


@router.post("/ack/batch-modify", response_model=dict)
async def batch_modify_ack(
    body: BatchModifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Batch change ack type for multiple alerts. Updates existing ack records."""
    if not body.alert_ids:
        return {"modified_count": 0, "message": "No alert IDs provided"}
    valid_types = {t.value for t in AckType}
    ack_type = body.new_ack_type if body.new_ack_type in valid_types else AckType.DISMISS.value
    expires_at = None
    if ack_type == AckType.DISMISS.value:
        expires_at = datetime.now() + timedelta(hours=_DISMISS_DEFAULT_HOURS)
    elif ack_type == AckType.DEFERRED.value:
        hours = body.expires_hours or 72
        expires_at = datetime.now() + timedelta(hours=hours)
    elif ack_type == AckType.CONFIRMED_OK.value and body.expires_hours:
        h = body.expires_hours
        if h not in (2, 4, 6, 8, 12, 24):
            h = 24
        expires_at = datetime.now() + timedelta(hours=h)

    result = await db.execute(
        update(AlertAckModel)
        .where(AlertAckModel.alert_id.in_(body.alert_ids))
        .values(ack_type=ack_type, ack_expires_at=expires_at)
    )
    await db.commit()
    modified = result.rowcount
    return {"modified_count": modified, "message": f"Modified {modified} acknowledgements"}


@router.get("/{alert_id}/ack", response_model=List[AlertAckResponse])
async def get_alert_ack_details(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Get acknowledgement details for a specific alert (lazy-loaded by detail drawer).
    Returns a list (usually 0 or 1 item). Includes acked_by_nickname when available.
    """
    result = await db.execute(
        select(AlertAckModel).where(AlertAckModel.alert_id == alert_id)
    )
    acks = result.scalars().all()
    if not acks:
        return []
    from .arrays import _resolve_ips_to_nicknames
    ips = list({a.acked_by_ip for a in acks})
    nick_map = await _resolve_ips_to_nicknames(db, ips)
    return [
        AlertAckResponse(
            id=a.id, alert_id=a.alert_id, acked_by_ip=a.acked_by_ip, acked_at=a.acked_at,
            comment=a.comment or "", ack_type=a.ack_type or "dismiss",
            ack_expires_at=a.ack_expires_at, note=a.note or "",
            acked_by_nickname=nick_map.get(a.acked_by_ip) or None,
        )
        for a in acks
    ]


# ---------------------------------------------------------------------------
# Helper: clear active issues from in-memory cache after ack
# ---------------------------------------------------------------------------

async def _clear_acked_active_issues(db: AsyncSession, acked_alert_ids: List[int]):
    """
    After acknowledging alerts, update matching entries in the in-memory
    active_issues cache to mark them as suppressed (仍显示，灰色样式).
    Fetches ack details (acked_by_ip, ack_expires_at, acked_by_nickname) and merges into issues.
    """
    from .arrays import _array_status_cache, _resolve_ips_to_nicknames

    if not acked_alert_ids:
        return

    # Fetch alert + ack info for acked alerts
    result = await db.execute(
        select(
            AlertModel.id,
            AlertModel.array_id,
            AlertModel.observer_name,
            AlertAckModel.acked_by_ip,
            AlertAckModel.ack_expires_at,
        )
        .join(AlertAckModel, AlertAckModel.alert_id == AlertModel.id)
        .where(AlertModel.id.in_(acked_alert_ids))
    )
    rows = result.all()
    ips = list({r[3] for r in rows if r[3]})
    nick_map = await _resolve_ips_to_nicknames(db, ips)
    ack_info = {
        r[0]: {
            'acked_by_ip': r[3],
            'ack_expires_at': r[4].isoformat() if r[4] else None,
            'acked_by_nickname': nick_map.get(r[3]) or None,
        }
        for r in rows
    }

    for _id, array_id, observer_name, _, _ in rows:
        status_obj = _array_status_cache.get(array_id)
        if not status_obj or not status_obj.active_issues:
            continue
        info = ack_info.get(_id, {})
        suppressed = {
            'suppressed': True,
            'acked_by_ip': info.get('acked_by_ip'),
            'ack_expires_at': info.get('ack_expires_at'),
            'acked_by_nickname': info.get('acked_by_nickname'),
        }
        for issue in status_obj.active_issues:
            if issue.get('alert_id') == _id:
                issue.update(suppressed)
                break
            if not issue.get('alert_id') and issue.get('observer') == observer_name:
                issue.update(suppressed)
                break
