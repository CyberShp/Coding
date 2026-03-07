"""
Event Timeline API.

Provides cross-observer, time-ordered events for the timeline visualization.
Also returns active test task windows for background marking.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..models.alert import AlertModel
from ..models.task_session import TaskSessionModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/timeline", tags=["timeline"])


# Category -> observer_name mapping (port/card/system)
CATEGORIES = {
    'port': ['error_code', 'link_status', 'port_fec', 'port_speed', 'port_traffic'],
    'card': ['card_recovery', 'card_info', 'pcie_bandwidth', 'controller_state', 'disk_state'],
    'system': ['alarm_type', 'memory_leak', 'cpu_usage', 'cmd_response', 'sig_monitor', 'sensitive_info', 'process_crash', 'io_timeout'],
}


@router.get("/{array_id}")
async def get_timeline(
    array_id: str,
    hours: int = Query(24, ge=1, le=168),
    observer: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=500, description="Events per page"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get timeline events for a specific array.
    Returns events sorted by time, grouped by observer category.
    Pagination: limit (default 20) per page, offset for page navigation.

    - observer: exact observer_name match
    - category: port/card/system - filters by observer category (expands to observer_name.in_())
    """
    start_time = datetime.now() - timedelta(hours=hours)

    # Build conditions
    cond = [
        AlertModel.array_id == array_id,
        AlertModel.timestamp >= start_time,
    ]
    if observer:
        cond.append(AlertModel.observer_name == observer)
    elif category and category in CATEGORIES:
        cond.append(AlertModel.observer_name.in_(CATEGORIES[category]))

    # Total count
    from sqlalchemy import func
    count_result = await db.execute(
        select(func.count(AlertModel.id)).where(and_(*cond))
    )
    total = count_result.scalar() or 0

    # Fetch alerts with pagination
    result = await db.execute(
        select(AlertModel)
        .where(and_(*cond))
        .order_by(AlertModel.timestamp.desc())
        .offset(offset)
        .limit(limit)
    )
    alerts = result.scalars().all()

    # Group by observer category
    CATEGORY_LABELS = {'port': '端口级', 'card': '卡件级', 'system': '系统级'}

    def _get_category(obs_name):
        for cat, observers in CATEGORIES.items():
            if obs_name in observers:
                return cat
        return 'system'

    events = []
    for a in alerts:
        cat = _get_category(a.observer_name)
        det = {}
        if a.details:
            try:
                det = json.loads(a.details) if isinstance(a.details, str) else a.details
            except Exception:
                det = {}

        events.append({
            'id': a.id,
            'timestamp': a.timestamp.isoformat() if a.timestamp else '',
            'observer_name': a.observer_name,
            'level': a.level,
            'category': cat,
            'category_label': CATEGORY_LABELS.get(cat, cat),
            'message': (a.message or '')[:120],
            'task_id': a.task_id,
        })

    # Fetch overlapping test tasks
    task_result = await db.execute(
        select(TaskSessionModel)
        .where(
            TaskSessionModel.started_at != None,  # noqa: E711
            TaskSessionModel.started_at <= datetime.now(),
        )
        .order_by(TaskSessionModel.started_at.desc())
        .limit(20)
    )
    tasks_raw = task_result.scalars().all()
    task_windows = []
    for t in tasks_raw:
        arr_ids = []
        try:
            arr_ids = json.loads(t.array_ids) if t.array_ids else []
        except Exception:
            pass
        if arr_ids and array_id not in arr_ids:
            continue
        task_windows.append({
            'id': t.id,
            'name': t.name,
            'task_type': t.task_type,
            'started_at': t.started_at.isoformat() if t.started_at else '',
            'ended_at': t.ended_at.isoformat() if t.ended_at else '',
            'status': t.status,
        })

    return {
        'events': events,
        'task_windows': task_windows,
        'total': total,
    }
