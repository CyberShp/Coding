"""
Test Task Session API endpoints.

CRUD for test tasks, start/stop management, summary generation.
"""

import json
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..models.task_session import (
    TaskSessionModel, TaskSessionCreate, TaskSessionResponse,
    TaskSummary, TASK_TYPES,
)
from ..models.alert import AlertModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/test-tasks", tags=["test-tasks"])

# In-memory active task id for auto-tagging alerts
_active_task_id: Optional[int] = None


def get_active_task_id() -> Optional[int]:
    return _active_task_id


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
async def start_task(task_id: int, db: AsyncSession = Depends(get_db)):
    """Start a test task (mark begin timestamp)"""
    global _active_task_id
    task = await db.get(TaskSessionModel, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status == 'running':
        raise HTTPException(400, "Task already running")

    task.status = 'running'
    task.started_at = datetime.now()
    task.ended_at = None
    _active_task_id = task.id
    await db.commit()
    await db.refresh(task)
    logger.info(f"Test task started: {task.name} (id={task.id})")
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
    for a in alert_list:
        by_level[a.level] = by_level.get(a.level, 0) + 1
        by_observer[a.observer_name] = by_observer.get(a.observer_name, 0) + 1
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
        by_level=by_level,
        by_observer=by_observer,
        critical_events=critical_events[:50],
    )


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
        notes=task.notes or '',
        status=task.status or 'created',
        started_at=task.started_at,
        ended_at=task.ended_at,
        created_at=task.created_at,
        duration_seconds=duration,
    )
