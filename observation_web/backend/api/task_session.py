"""
Test Task Session API endpoints.

CRUD for test tasks, start/stop management, summary generation.
Array locking for multi-user exclusivity.
"""

import json
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func, and_, delete, case
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..models.task_session import (
    TaskSessionModel, TaskSessionCreate, TaskSessionResponse,
    TaskSummary, TASK_TYPES,
)
from ..models.alert import AlertModel
from ..models.array_lock import ArrayLockModel, ArrayLockInfo, LockConflict

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/test-tasks", tags=["test-tasks"])

# In-memory active task id for auto-tagging alerts
_active_task_id: Optional[int] = None


def get_active_task_id() -> Optional[int]:
    return _active_task_id


async def _check_lock_conflicts(
    db: AsyncSession,
    array_ids: List[str],
    exclude_task_id: Optional[int] = None,
) -> List[LockConflict]:
    """Check if any of the arrays are locked by another task."""
    if not array_ids:
        return []

    query = select(ArrayLockModel, TaskSessionModel).join(
        TaskSessionModel, ArrayLockModel.task_id == TaskSessionModel.id
    ).where(ArrayLockModel.array_id.in_(array_ids))

    if exclude_task_id:
        query = query.where(ArrayLockModel.task_id != exclude_task_id)

    result = await db.execute(query)
    rows = result.all()

    conflicts = []
    for lock, task in rows:
        conflicts.append(LockConflict(
            array_id=lock.array_id,
            locked_by_task_id=lock.task_id,
            locked_by_task_name=task.name,
            locked_by_ip=lock.locked_by_ip or "",
            locked_by_nickname=lock.locked_by_nickname or "",
            locked_at=lock.locked_at,
        ))
    return conflicts


async def _acquire_locks(
    db: AsyncSession,
    task_id: int,
    array_ids: List[str],
    user_ip: str = "",
    user_nickname: str = "",
):
    """Acquire locks for all arrays."""
    for array_id in array_ids:
        lock = ArrayLockModel(
            array_id=array_id,
            task_id=task_id,
            locked_by_ip=user_ip,
            locked_by_nickname=user_nickname,
        )
        db.add(lock)


async def _release_locks(db: AsyncSession, task_id: int):
    """Release all locks held by a task."""
    await db.execute(
        delete(ArrayLockModel).where(ArrayLockModel.task_id == task_id)
    )


@router.get("", response_model=List[TaskSessionResponse])
async def list_tasks(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List test tasks"""
    query = select(TaskSessionModel).order_by(TaskSessionModel.created_at.desc())
    if status:
        query = query.where(TaskSessionModel.status == status)
    query = query.limit(limit)
    result = await db.execute(query)
    tasks = result.scalars().all()

    responses = []
    for t in tasks:
        r = _to_response(t)
        # Count alerts during task window
        if t.started_at:
            cond = [AlertModel.timestamp >= t.started_at]
            if t.ended_at:
                cond.append(AlertModel.timestamp <= t.ended_at)
            arr_ids = _parse_array_ids(t.array_ids)
            if arr_ids:
                cond.append(AlertModel.array_id.in_(arr_ids))
            cnt = await db.execute(
                select(func.count(AlertModel.id)).where(and_(*cond))
            )
            r.alert_count = cnt.scalar() or 0
        responses.append(r)
    return responses


@router.post("", response_model=TaskSessionResponse)
async def create_task(
    body: TaskSessionCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new test task"""
    task = TaskSessionModel(
        name=body.name,
        task_type=body.task_type,
        array_ids=json.dumps(body.array_ids),
        expected_observers=json.dumps(body.expected_observers or [], ensure_ascii=False),
        notes=body.notes,
        status='created',
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return _to_response(task)


@router.get("/{task_id}", response_model=TaskSessionResponse)
async def get_task(task_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single test task"""
    task = await db.get(TaskSessionModel, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return _to_response(task)


@router.post("/{task_id}/start", response_model=TaskSessionResponse)
async def start_task(
    task_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Start a test task (mark begin timestamp)"""
    global _active_task_id
    task = await db.get(TaskSessionModel, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status == 'running':
        raise HTTPException(400, "Task already running")

    array_ids = _parse_array_ids(task.array_ids)

    # Check for lock conflicts
    conflicts = await _check_lock_conflicts(db, array_ids, exclude_task_id=task_id)
    if conflicts:
        conflict_info = [
            f"{c.array_id} (被 {c.locked_by_nickname or c.locked_by_ip or '未知用户'} 的任务 '{c.locked_by_task_name}' 锁定)"
            for c in conflicts
        ]
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"阵列被其他任务锁定: {', '.join(conflict_info)}",
                "conflicts": [c.model_dump() for c in conflicts],
            }
        )

    # Get user info from request
    user_ip = getattr(request.state, 'user_ip', '') or ''
    user_nickname = ''

    # Acquire locks
    await _acquire_locks(db, task.id, array_ids, user_ip, user_nickname)

    task.status = 'running'
    task.started_at = datetime.now()
    task.ended_at = None
    _active_task_id = task.id
    await db.commit()
    await db.refresh(task)
    logger.info(f"Test task started: {task.name} (id={task.id}) by {user_ip}")
    return _to_response(task)


@router.post("/{task_id}/stop", response_model=TaskSessionResponse)
async def stop_task(task_id: int, db: AsyncSession = Depends(get_db)):
    """Stop a test task (mark end timestamp)"""
    global _active_task_id
    task = await db.get(TaskSessionModel, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status != 'running':
        raise HTTPException(400, "Task is not running")

    task.status = 'completed'
    task.ended_at = datetime.now()
    if _active_task_id == task.id:
        _active_task_id = None

    # Release all locks held by this task
    await _release_locks(db, task.id)

    # Tag alerts created during this task window
    arr_ids = _parse_array_ids(task.array_ids)
    cond = [
        AlertModel.timestamp >= task.started_at,
        AlertModel.timestamp <= task.ended_at,
    ]
    if arr_ids:
        cond.append(AlertModel.array_id.in_(arr_ids))

    tagged = await db.execute(
        select(AlertModel).where(and_(*cond))
    )
    for alert in tagged.scalars().all():
        alert.task_id = task.id
    await db.commit()
    await db.refresh(task)

    logger.info(f"Test task stopped: {task.name} (id={task.id})")
    return _to_response(task)


@router.delete("/{task_id}")
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a test task"""
    task = await db.get(TaskSessionModel, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    await db.delete(task)
    await db.commit()
    return {"message": "Task deleted"}


@router.get("/{task_id}/summary", response_model=TaskSummary)
async def get_task_summary(task_id: int, db: AsyncSession = Depends(get_db)):
    """Generate summary for a completed task"""
    task = await db.get(TaskSessionModel, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if not task.started_at:
        raise HTTPException(400, "Task has not started")

    end = task.ended_at or datetime.now()
    duration = (end - task.started_at).total_seconds()

    arr_ids = _parse_array_ids(task.array_ids)
    cond = [AlertModel.timestamp >= task.started_at, AlertModel.timestamp <= end]
    if arr_ids:
        cond.append(AlertModel.array_id.in_(arr_ids))

    alerts = await db.execute(select(AlertModel).where(and_(*cond)))
    alert_list = alerts.scalars().all()

    by_level = {}
    by_observer = {}
    critical_events = []
    expected_observers = _parse_array_ids(getattr(task, "expected_observers", "") or "")
    expected_set = set(expected_observers)
    expected_count = 0
    unexpected_count = 0
    for a in alert_list:
        by_level[a.level] = by_level.get(a.level, 0) + 1
        by_observer[a.observer_name] = by_observer.get(a.observer_name, 0) + 1
        if expected_set:
            if a.observer_name in expected_set:
                expected_count += 1
            else:
                unexpected_count += 1
        if a.level in ('error', 'critical'):
            critical_events.append({
                'id': a.id,
                'observer': a.observer_name,
                'level': a.level,
                'message': (a.message or '')[:100],
                'timestamp': a.timestamp.isoformat() if a.timestamp else '',
            })

    return TaskSummary(
        task_id=task.id,
        name=task.name,
        task_type=task.task_type,
        duration_seconds=duration,
        alert_total=len(alert_list),
        expected_count=expected_count,
        unexpected_count=unexpected_count if expected_set else max(0, len(alert_list) - expected_count),
        by_level=by_level,
        by_observer=by_observer,
        critical_events=critical_events[:50],
    )


@router.get("/{task_id}/live-status")
async def get_task_live_status(task_id: int, db: AsyncSession = Depends(get_db)):
    """Return per-array ingestion freshness and alert counts for a test task."""
    from ..models.array import ArrayModel
    from ..models.lifecycle import SyncStateModel

    task = await db.get(TaskSessionModel, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    array_ids = _parse_array_ids(task.array_ids)
    arrays_query = select(ArrayModel.array_id, ArrayModel.name)
    if array_ids:
        arrays_query = arrays_query.where(ArrayModel.array_id.in_(array_ids))
    arrays_result = await db.execute(arrays_query.order_by(ArrayModel.name))
    arrays = arrays_result.all()
    effective_ids = [row.array_id for row in arrays]

    sync_map = {}
    alert_map = {}
    if effective_ids:
        sync_result = await db.execute(
            select(SyncStateModel).where(SyncStateModel.array_id.in_(effective_ids))
        )
        sync_map = {row.array_id: row for row in sync_result.scalars().all()}

        alert_result = await db.execute(
            select(
                AlertModel.array_id,
                func.count(AlertModel.id).label("alert_count"),
                func.sum(case(
                    (AlertModel.level.in_(["error", "critical"]), 1),
                    else_=0,
                )).label("critical_count"),
                func.max(AlertModel.timestamp).label("last_alert_at"),
            )
            .where(
                AlertModel.array_id.in_(effective_ids),
                AlertModel.task_id == task.id,
            )
            .group_by(AlertModel.array_id)
        )
        alert_map = {row.array_id: row for row in alert_result.all()}

    now = datetime.now()
    array_statuses = []
    for array in arrays:
        sync = sync_map.get(array.array_id)
        alert_stats = alert_map.get(array.array_id)
        last_sync_at = sync.last_sync_at if sync else None
        sync_age = max(0, int((now - last_sync_at).total_seconds())) if last_sync_at else None
        freshness = (
            "never" if sync_age is None else
            "fresh" if sync_age <= 90 else
            "delayed" if sync_age <= 300 else
            "stale"
        )
        array_statuses.append({
            "array_id": array.array_id,
            "array_name": array.name,
            "freshness": freshness,
            "last_sync_at": last_sync_at.isoformat() if last_sync_at else None,
            "sync_age_seconds": sync_age,
            "alert_count": int(alert_stats.alert_count or 0) if alert_stats else 0,
            "critical_count": int(alert_stats.critical_count or 0) if alert_stats else 0,
            "last_alert_at": (
                alert_stats.last_alert_at.isoformat()
                if alert_stats and alert_stats.last_alert_at else None
            ),
        })

    return {
        "task_id": task.id,
        "task_name": task.name,
        "task_status": task.status,
        "server_time": now.isoformat(),
        "arrays": array_statuses,
        "fresh_count": sum(1 for item in array_statuses if item["freshness"] == "fresh"),
        "attention_count": sum(1 for item in array_statuses if item["freshness"] != "fresh"),
    }


def _parse_array_ids(raw: str) -> List[str]:
    try:
        ids = json.loads(raw) if raw else []
        return [str(i) for i in ids] if isinstance(ids, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _to_response(task: TaskSessionModel) -> TaskSessionResponse:
    duration = None
    if task.started_at:
        end = task.ended_at or datetime.now()
        duration = (end - task.started_at).total_seconds()

    return TaskSessionResponse(
        id=task.id,
        name=task.name,
        task_type=task.task_type,
        task_type_label=TASK_TYPES.get(task.task_type, task.task_type),
        array_ids=_parse_array_ids(task.array_ids),
        expected_observers=_parse_array_ids(getattr(task, "expected_observers", "") or ""),
        notes=task.notes or '',
        status=task.status or 'created',
        started_at=task.started_at,
        ended_at=task.ended_at,
        created_at=task.created_at,
        duration_seconds=duration,
    )


# ==================== Lock Management Endpoints ====================

@router.get("/locks/all", response_model=List[ArrayLockInfo])
async def get_all_locks(db: AsyncSession = Depends(get_db)):
    """Get all current array locks."""
    query = select(ArrayLockModel, TaskSessionModel).join(
        TaskSessionModel, ArrayLockModel.task_id == TaskSessionModel.id
    )
    result = await db.execute(query)
    rows = result.all()

    return [
        ArrayLockInfo(
            array_id=lock.array_id,
            task_id=lock.task_id,
            task_name=task.name,
            locked_by_ip=lock.locked_by_ip or "",
            locked_by_nickname=lock.locked_by_nickname or "",
            locked_at=lock.locked_at,
        )
        for lock, task in rows
    ]


@router.get("/locks/check")
async def check_locks(
    array_ids: str = Query(..., description="Comma-separated array IDs"),
    db: AsyncSession = Depends(get_db),
):
    """Check if specific arrays are locked."""
    ids = [a.strip() for a in array_ids.split(",") if a.strip()]
    if not ids:
        return {"conflicts": [], "all_available": True}

    conflicts = await _check_lock_conflicts(db, ids)
    return {
        "conflicts": [c.model_dump() for c in conflicts],
        "all_available": len(conflicts) == 0,
        "locked_arrays": [c.array_id for c in conflicts],
        "available_arrays": [a for a in ids if a not in [c.array_id for c in conflicts]],
    }


@router.get("/locks/array/{array_id}")
async def get_array_lock(array_id: str, db: AsyncSession = Depends(get_db)):
    """Get lock status for a specific array."""
    query = select(ArrayLockModel, TaskSessionModel).join(
        TaskSessionModel, ArrayLockModel.task_id == TaskSessionModel.id
    ).where(ArrayLockModel.array_id == array_id)
    result = await db.execute(query)
    row = result.first()

    if not row:
        return {"locked": False, "array_id": array_id}

    lock, task = row
    return {
        "locked": True,
        "array_id": array_id,
        "task_id": lock.task_id,
        "task_name": task.name,
        "locked_by_ip": lock.locked_by_ip or "",
        "locked_by_nickname": lock.locked_by_nickname or "",
        "locked_at": lock.locked_at.isoformat() if lock.locked_at else None,
    }


@router.delete("/locks/force/{array_id}")
async def force_unlock(
    array_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Force release a lock (admin operation)."""
    result = await db.execute(
        select(ArrayLockModel).where(ArrayLockModel.array_id == array_id)
    )
    lock = result.scalar_one_or_none()

    if not lock:
        raise HTTPException(404, "Array is not locked")

    user_ip = getattr(request.state, 'user_ip', '') or 'unknown'
    logger.warning(f"Force unlock: {array_id} by {user_ip} (was locked by task {lock.task_id})")

    await db.delete(lock)
    await db.commit()
    return {"message": f"Lock for {array_id} forcefully released"}
