"""Web API endpoints for task scheduling."""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...core.scheduler import TaskScheduler
from ...utils.logging import get_logger

logger = get_logger("web.api.scheduler")

router = APIRouter()

# Module-level scheduler instance
_scheduler: Optional[TaskScheduler] = None


def get_scheduler() -> TaskScheduler:
    """Get or create the global scheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler()
        _scheduler.start()
    return _scheduler


class DelayedTaskRequest(BaseModel):
    """Request to create a delayed task."""
    delay_seconds: float
    name: str = ""
    task_id: Optional[str] = None


class PeriodicTaskRequest(BaseModel):
    """Request to create a periodic task."""
    interval_seconds: float
    name: str = ""
    max_runs: int = 0
    start_immediately: bool = False
    task_id: Optional[str] = None


class CronTaskRequest(BaseModel):
    """Request to create a cron task."""
    cron_expression: str
    name: str = ""
    max_runs: int = 0
    task_id: Optional[str] = None


@router.get("/tasks")
async def list_tasks():
    """List all scheduled tasks."""
    scheduler = get_scheduler()
    return {"tasks": scheduler.list_tasks()}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Get a specific task."""
    scheduler = get_scheduler()
    task = scheduler.get_task(task_id)
    if task is None:
        raise HTTPException(404, f"Task '{task_id}' not found")
    return task


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Cancel a scheduled task."""
    scheduler = get_scheduler()
    if scheduler.cancel(task_id):
        return {"status": "cancelled", "task_id": task_id}
    raise HTTPException(404, f"Task '{task_id}' not found or cannot be cancelled")


@router.post("/tasks/{task_id}/pause")
async def pause_task(task_id: str):
    """Pause a recurring task."""
    scheduler = get_scheduler()
    if scheduler.pause(task_id):
        return {"status": "paused", "task_id": task_id}
    raise HTTPException(404, f"Task '{task_id}' not found or cannot be paused")


@router.post("/tasks/{task_id}/resume")
async def resume_task(task_id: str):
    """Resume a paused task."""
    scheduler = get_scheduler()
    if scheduler.resume(task_id):
        return {"status": "resumed", "task_id": task_id}
    raise HTTPException(404, f"Task '{task_id}' not found or cannot be resumed")
