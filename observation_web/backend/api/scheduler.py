"""
Scheduler API endpoints.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.scheduler import get_scheduler
from ..db.database import get_db
from ..models.scheduler import (
    ScheduledTaskModel, TaskResultModel,
    ScheduledTaskCreate, ScheduledTaskUpdate, 
    ScheduledTaskResponse, TaskResultResponse
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["scheduler"])


@router.get("", response_model=List[ScheduledTaskResponse])
async def list_tasks(
    enabled_only: bool = Query(False, description="Only show enabled tasks"),
    db: AsyncSession = Depends(get_db),
):
    """List all scheduled tasks"""
    query = select(ScheduledTaskModel)
    if enabled_only:
        query = query.where(ScheduledTaskModel.enabled == True)
    query = query.order_by(desc(ScheduledTaskModel.created_at))
    
    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=ScheduledTaskResponse)
async def create_task(
    data: ScheduledTaskCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new scheduled task"""
    scheduler = get_scheduler()
    task = await scheduler.add_task(db, data)
    return task


@router.get("/{task_id}", response_model=ScheduledTaskResponse)
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a task by ID"""
    result = await db.execute(
        select(ScheduledTaskModel).where(ScheduledTaskModel.id == task_id)
    )
    task = result.scalar()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return task


@router.put("/{task_id}", response_model=ScheduledTaskResponse)
async def update_task(
    task_id: int,
    data: ScheduledTaskUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a task"""
    scheduler = get_scheduler()
    task = await scheduler.update_task(db, task_id, data)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return task


@router.delete("/{task_id}")
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a task"""
    scheduler = get_scheduler()
    deleted = await scheduler.delete_task(db, task_id)
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return {"status": "deleted"}


@router.post("/{task_id}/run")
async def run_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Run a task immediately"""
    result = await db.execute(
        select(ScheduledTaskModel).where(ScheduledTaskModel.id == task_id)
    )
    task = result.scalar()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    scheduler = get_scheduler()
    await scheduler.run_task_now(task_id)
    
    return {"status": "executed", "task_name": task.name}


@router.get("/{task_id}/results", response_model=List[TaskResultResponse])
async def get_task_results(
    task_id: int,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get execution results for a task"""
    result = await db.execute(
        select(TaskResultModel)
        .where(TaskResultModel.task_id == task_id)
        .order_by(desc(TaskResultModel.executed_at))
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/results/recent", response_model=List[TaskResultResponse])
async def get_recent_results(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Get recent task results across all tasks"""
    result = await db.execute(
        select(TaskResultModel)
        .order_by(desc(TaskResultModel.executed_at))
        .limit(limit)
    )
    return result.scalars().all()
