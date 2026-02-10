"""
Alert acknowledgement API endpoints.

Allows users to acknowledge alerts as "confirmed non-issue",
track who acknowledged (by client IP), and undo acknowledgements.
"""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..models.alert import (
    AlertModel, AlertAckModel, AlertAckCreate, AlertAckResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alerts", tags=["acknowledgements"])


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


@router.get("/{alert_id}/ack", response_model=List[AlertAckResponse])
async def get_alert_ack_details(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Get acknowledgement details for a specific alert (lazy-loaded by detail drawer).
    Returns a list (usually 0 or 1 item).
    """
    result = await db.execute(
        select(AlertAckModel).where(AlertAckModel.alert_id == alert_id)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Helper: clear active issues from in-memory cache after ack
# ---------------------------------------------------------------------------

async def _clear_acked_active_issues(db: AsyncSession, acked_alert_ids: List[int]):
    """
    After acknowledging alerts, try to remove matching entries from
    the in-memory active_issues cache so the active panel updates
    without waiting for the next refresh cycle.
    """
    from .arrays import _array_status_cache

    # Look up the observer_name and array_id for the acked alerts
    result = await db.execute(
        select(AlertModel.id, AlertModel.array_id, AlertModel.observer_name)
        .where(AlertModel.id.in_(acked_alert_ids))
    )
    rows = result.all()
    acked_set = set(acked_alert_ids)

    for _id, array_id, observer_name in rows:
        status_obj = _array_status_cache.get(array_id)
        if status_obj and status_obj.active_issues:
            # Remove issues whose alert_id matches the acked set,
            # or fall back to observer_name match if no alert_id on the issue
            status_obj.active_issues = [
                issue for issue in status_obj.active_issues
                if not (
                    issue.get('alert_id') in acked_set
                    or (not issue.get('alert_id') and issue.get('observer') == observer_name)
                )
            ]
