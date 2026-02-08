"""
Snapshot API — capture and compare array states.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..models.snapshot import SnapshotModel, SnapshotResponse, SnapshotDiffResponse
from ..models.alert import AlertModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/snapshots", tags=["snapshots"])


@router.post("/{array_id}", response_model=SnapshotResponse)
async def create_snapshot(
    array_id: str,
    label: str = Query("", description="Optional label"),
    task_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Capture current array state as a snapshot.
    Gathers the latest alert per observer to represent current state.
    """
    # Build snapshot data from latest alerts per observer
    from sqlalchemy import func as sqlfunc

    # Get the latest alert from each observer for this array
    subq = (
        select(
            AlertModel.observer_name,
            sqlfunc.max(AlertModel.id).label('max_id'),
        )
        .where(AlertModel.array_id == array_id)
        .group_by(AlertModel.observer_name)
        .subquery()
    )

    result = await db.execute(
        select(AlertModel).join(subq, AlertModel.id == subq.c.max_id)
    )
    latest_alerts = result.scalars().all()

    snapshot_data = {}
    for a in latest_alerts:
        det = {}
        try:
            det = json.loads(a.details) if isinstance(a.details, str) else (a.details or {})
        except Exception:
            pass
        snapshot_data[a.observer_name] = {
            'level': a.level,
            'message': a.message,
            'timestamp': a.timestamp.isoformat() if a.timestamp else '',
            'details': det,
        }

    snap = SnapshotModel(
        array_id=array_id,
        label=label or f"快照 {datetime.now().strftime('%m-%d %H:%M')}",
        task_id=task_id,
        data=json.dumps(snapshot_data, ensure_ascii=False),
    )
    db.add(snap)
    await db.commit()
    await db.refresh(snap)

    return _to_response(snap)


@router.get("/{array_id}", response_model=List[SnapshotResponse])
async def list_snapshots(
    array_id: str,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List snapshots for an array"""
    result = await db.execute(
        select(SnapshotModel)
        .where(SnapshotModel.array_id == array_id)
        .order_by(SnapshotModel.created_at.desc())
        .limit(limit)
    )
    return [_to_response(s) for s in result.scalars().all()]


@router.get("/diff", response_model=SnapshotDiffResponse)
async def diff_snapshots(
    id1: int = Query(..., description="First snapshot ID"),
    id2: int = Query(..., description="Second snapshot ID"),
    db: AsyncSession = Depends(get_db),
):
    """Compare two snapshots and return differences"""
    snap_a = await db.get(SnapshotModel, id1)
    snap_b = await db.get(SnapshotModel, id2)
    if not snap_a or not snap_b:
        raise HTTPException(404, "Snapshot not found")

    data_a = _parse_data(snap_a.data)
    data_b = _parse_data(snap_b.data)

    changes = _compute_diff(data_a, data_b)

    return SnapshotDiffResponse(
        snapshot_a=_to_response(snap_a),
        snapshot_b=_to_response(snap_b),
        changes=changes,
    )


def _compute_diff(a: Dict, b: Dict) -> List[Dict[str, Any]]:
    """Compare two snapshot data dicts."""
    changes = []
    all_keys = set(list(a.keys()) + list(b.keys()))

    for key in sorted(all_keys):
        val_a = a.get(key)
        val_b = b.get(key)

        if val_a is None and val_b is not None:
            changes.append({
                'category': key,
                'key': key,
                'change_type': 'added',
                'before': None,
                'after': val_b,
            })
        elif val_a is not None and val_b is None:
            changes.append({
                'category': key,
                'key': key,
                'change_type': 'removed',
                'before': val_a,
                'after': None,
            })
        elif val_a != val_b:
            # Compare level and message
            level_a = val_a.get('level', '') if isinstance(val_a, dict) else ''
            level_b = val_b.get('level', '') if isinstance(val_b, dict) else ''
            msg_a = val_a.get('message', '') if isinstance(val_a, dict) else str(val_a)
            msg_b = val_b.get('message', '') if isinstance(val_b, dict) else str(val_b)

            if level_a != level_b or msg_a != msg_b:
                changes.append({
                    'category': key,
                    'key': key,
                    'change_type': 'changed',
                    'before': val_a,
                    'after': val_b,
                })

    return changes


def _parse_data(raw: str) -> Dict:
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _to_response(snap: SnapshotModel) -> SnapshotResponse:
    return SnapshotResponse(
        id=snap.id,
        array_id=snap.array_id,
        label=snap.label or '',
        task_id=snap.task_id,
        created_at=snap.created_at,
        data=_parse_data(snap.data),
    )
