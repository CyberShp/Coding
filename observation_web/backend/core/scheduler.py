"""
Task scheduler using APScheduler.

Manages scheduled tasks for periodic query execution.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..db import database as _db_module
from ..models.scheduler import (
    ScheduledTaskModel, TaskResultModel,
    ScheduledTaskCreate, ScheduledTaskUpdate
)
from .ssh_pool import get_ssh_pool
from .system_alert import sys_error, sys_info, sys_warning

logger = logging.getLogger(__name__)


class TaskScheduler:
    """Task scheduler manager"""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._running = False
    
    async def start(self):
        """Start the scheduler and load all tasks"""
        if self._running:
            return
        
        try:
            self.scheduler.start()
            self._running = True
            logger.info("Task scheduler started")
            
            # Load existing tasks
            await self._load_tasks()
            # Load auto-monitor query templates (custom observers)
            await self._load_auto_monitors()

        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
            sys_error("scheduler", "Failed to start task scheduler", {"error": str(e)})
    
    def stop(self):
        """Stop the scheduler"""
        if self._running:
            self.scheduler.shutdown()
            self._running = False
            logger.info("Task scheduler stopped")
    
    async def _load_tasks(self):
        """Load all enabled tasks from database"""
        async with _db_module.AsyncSessionLocal() as db:
            result = await db.execute(
                select(ScheduledTaskModel).where(ScheduledTaskModel.enabled == True)
            )
            tasks = result.scalars().all()
            
            for task in tasks:
                self._add_job(task)

            logger.info(f"Loaded {len(tasks)} scheduled tasks")

    # ------------------------------------------------------------------
    # Auto-monitor query templates (custom observers running from the backend)
    # ------------------------------------------------------------------

    async def _load_auto_monitors(self):
        """Register every auto_monitor query template as a periodic job."""
        from ..models.query import QueryTemplateModel
        async with _db_module.AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(QueryTemplateModel).where(QueryTemplateModel.auto_monitor == True)  # noqa: E712
            )).scalars().all()
            for t in rows:
                self.add_auto_monitor(t)
            logger.info("Loaded %d auto-monitors", len(rows))

    def add_auto_monitor(self, template) -> None:
        """(Re)register an auto_monitor query template as an interval job.

        Called on startup and whenever a template is created/updated so the
        "定时监测" toggle in CustomQuery actually results in periodic execution
        with alerting — previously auto_monitor/monitor_interval were stored but
        never consumed by anything.
        """
        if not self._running:
            return
        job_id = f"automon_{template.id}"
        if not getattr(template, "auto_monitor", False):
            self.remove_auto_monitor(template.id)
            return
        from apscheduler.triggers.interval import IntervalTrigger
        interval = max(int(template.monitor_interval or 300), 30)
        self.scheduler.add_job(
            self._execute_auto_monitor,
            trigger=IntervalTrigger(seconds=interval),
            id=job_id,
            args=[template.id],
            name=f"automon:{template.name}",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=30,
        )
        logger.info("Registered auto-monitor '%s' every %ss", template.name, interval)

    def remove_auto_monitor(self, template_id: int) -> None:
        """Remove an auto-monitor job (template disabled or deleted)."""
        if not self._running:
            return
        job_id = f"automon_{template_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            logger.info("Removed auto-monitor job %s", job_id)

    async def _execute_auto_monitor(self, template_id: int):
        """Run one auto-monitor cycle: execute commands, apply rule, alert on anomaly."""
        from ..models.query import QueryTemplateModel
        async with _db_module.AsyncSessionLocal() as db:
            tmpl = (await db.execute(
                select(QueryTemplateModel).where(QueryTemplateModel.id == template_id)
            )).scalar()
            if not tmpl or not tmpl.auto_monitor:
                self.remove_auto_monitor(template_id)
                return

            try:
                commands = json.loads(tmpl.commands) if tmpl.commands else []
            except (ValueError, TypeError):
                commands = []
            try:
                arrays = json.loads(tmpl.monitor_arrays) if tmpl.monitor_arrays else []
            except (ValueError, TypeError):
                arrays = []

            ssh_pool = get_ssh_pool()
            if not arrays:
                arrays = [aid for aid, c in ssh_pool._connections.items() if c.is_connected()]

            for array_id in arrays:
                conn = ssh_pool.get_connection(array_id)
                if not conn or not conn.is_connected():
                    continue
                for cmd in commands:
                    try:
                        exit_code, stdout, stderr = await conn.execute_async(cmd)
                        output = (stdout or "") + (stderr or "")
                        await self._alert_from_rule(db, tmpl, array_id, cmd, output)
                    except Exception as e:
                        logger.warning("Auto-monitor %s on %s failed: %s", tmpl.name, array_id, e)
            await db.commit()

    async def _alert_from_rule(self, db, template, array_id: str, cmd: str, output: str) -> None:
        """Apply a query template's rule to command output; create an Alert on anomaly."""
        if not getattr(template, "alert_on_mismatch", True):
            return
        from .query_engine import QueryEngine
        from ..models.query import QueryRule, RuleType
        from ..core.alert_store import get_alert_store
        from ..models.alert import AlertCreate, AlertLevel
        # Alerting must never break the monitoring run itself.
        try:
            try:
                rule = QueryRule(
                    rule_type=RuleType(template.rule_type) if template.rule_type else RuleType.VALID_MATCH,
                    pattern=template.pattern or "",
                    expect_match=template.expect_match if template.expect_match is not None else True,
                )
            except ValueError:
                rule = QueryRule(pattern=template.pattern or "")
            result = QueryEngine()._apply_rule(output, rule)
            if result.is_normal:
                return
            await get_alert_store().create_alert(db, AlertCreate(
                array_id=array_id,
                observer_name=f"custom:{template.name}",
                level=AlertLevel.WARNING,
                message=f"自定义监测 '{template.name}' 异常：命令 `{cmd}` 输出不符合预期",
                details={"command": cmd, "output": output[:500], "matched": result.matched_values},
                timestamp=datetime.now(),
            ))
        except Exception:
            logger.warning(
                "Rule-based alerting failed for template '%s' on %s",
                getattr(template, "name", "?"), array_id, exc_info=True,
            )

    def _add_job(self, task: ScheduledTaskModel):
        """Add a job to the scheduler"""
        try:
            # Parse cron expression
            cron_parts = task.cron_expr.split()
            if len(cron_parts) == 5:
                minute, hour, day, month, day_of_week = cron_parts
            else:
                logger.warning(f"Invalid cron expression for task {task.id}: {task.cron_expr}")
                return
            
            trigger = CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week
            )
            
            job_id = f"task_{task.id}"
            
            # Remove existing job if any
            existing = self.scheduler.get_job(job_id)
            if existing:
                self.scheduler.remove_job(job_id)
            
            # Add new job
            self.scheduler.add_job(
                self._execute_task,
                trigger=trigger,
                id=job_id,
                args=[task.id],
                name=task.name,
                replace_existing=True,
                # A long multi-array run must not be silently skipped by the 1s
                # default misfire grace; coalesce a backlog into a single run.
                misfire_grace_time=3600,
                coalesce=True,
                max_instances=1,
            )
            
            # Update next run time
            job = self.scheduler.get_job(job_id)
            if job:
                asyncio.create_task(self._update_next_run(task.id, job.next_run_time))
            
            logger.info(f"Added scheduled task: {task.name} ({task.cron_expr})")
            
        except Exception as e:
            logger.error(f"Failed to add job for task {task.id}: {e}")
    
    async def _update_next_run(self, task_id: int, next_run: datetime):
        """Update next run time in database"""
        async with _db_module.AsyncSessionLocal() as db:
            await db.execute(
                update(ScheduledTaskModel)
                .where(ScheduledTaskModel.id == task_id)
                .values(next_run_at=next_run)
            )
            await db.commit()
    
    async def _execute_task(self, task_id: int):
        """Execute a scheduled task"""
        async with _db_module.AsyncSessionLocal() as db:
            # Get task
            result = await db.execute(
                select(ScheduledTaskModel).where(ScheduledTaskModel.id == task_id)
            )
            task = result.scalar()
            
            if not task:
                logger.warning(f"Task {task_id} not found")
                return
            
            if not task.enabled:
                logger.info(f"Task {task.name} is disabled, skipping")
                return
            
            sys_info("scheduler", f"Executing task: {task.name}", {"task_id": task_id})
            
            # Create result record
            task_result = TaskResultModel(
                task_id=task_id,
                task_name=task.name,
                status="running",
                started_at=datetime.now()
            )
            db.add(task_result)
            await db.commit()
            await db.refresh(task_result)
            
            try:
                # Execute on each array
                ssh_pool = get_ssh_pool()
                outputs = []
                errors = []

                # Resolve commands once before iterating arrays
                commands_to_run: List[str] = []
                template = None  # set when the task is backed by a query template
                if task.command:
                    commands_to_run = [task.command]
                elif task.query_template_id:
                    from ..models.query import QueryTemplateModel
                    tmpl_result = await db.execute(
                        select(QueryTemplateModel).where(
                            QueryTemplateModel.id == task.query_template_id
                        )
                    )
                    template = tmpl_result.scalar()
                    if template and template.commands:
                        try:
                            commands_to_run = json.loads(template.commands)
                        except (ValueError, TypeError):
                            commands_to_run = []

                array_ids = task.array_ids or []
                if not array_ids:
                    # If no specific arrays, run on all connected
                    for array_id, conn in ssh_pool._connections.items():
                        if conn.is_connected():
                            array_ids.append(array_id)

                for array_id in array_ids:
                    conn = ssh_pool.get_connection(array_id)
                    if not conn or not conn.is_connected():
                        errors.append(f"{array_id}: Not connected")
                        continue

                    if not commands_to_run:
                        errors.append(f"{array_id}: No command defined")
                        continue

                    try:
                        for cmd in commands_to_run:
                            exit_code, stdout, stderr = await conn.execute_async(cmd)
                            if stdout:
                                outputs.append(f"[{array_id}]\n{stdout}")
                            if exit_code != 0:
                                err_msg = stderr.strip() if stderr else f"exit code {exit_code}"
                                errors.append(f"[{array_id}] {cmd}: {err_msg}")
                            elif stderr:
                                # exit_code=0 but stderr has content (warning, not failure)
                                errors.append(f"[{array_id}] {stderr}")
                            # Template-backed tasks apply their matching rule and
                            # raise a real alert on anomaly (not just store stdout).
                            if template is not None:
                                await self._alert_from_rule(
                                    db, template, array_id, cmd, (stdout or "") + (stderr or "")
                                )
                    except Exception as e:
                        errors.append(f"{array_id}: {str(e)}")
                
                # Update result
                task_result.status = "success" if not errors else "partial" if outputs else "failed"
                task_result.output = "\n\n".join(outputs) if outputs else None
                task_result.error = "\n".join(errors) if errors else None
                task_result.finished_at = datetime.now()
                
                # Update task last run time
                task.last_run_at = datetime.now()
                
                # Update next run time
                job = self.scheduler.get_job(f"task_{task_id}")
                if job:
                    task.next_run_at = job.next_run_time
                
                await db.commit()
                
                sys_info("scheduler", f"Task completed: {task.name}", {
                    "status": task_result.status,
                    "arrays": len(array_ids)
                })
                
            except Exception as e:
                task_result.status = "failed"
                task_result.error = str(e)
                task_result.finished_at = datetime.now()
                await db.commit()
                
                sys_error("scheduler", f"Task failed: {task.name}", {"error": str(e)})
    
    async def add_task(self, db: AsyncSession, data: ScheduledTaskCreate) -> ScheduledTaskModel:
        """Create and schedule a new task"""
        task = ScheduledTaskModel(
            name=data.name,
            description=data.description,
            query_template_id=data.query_template_id,
            command=data.command,
            cron_expr=data.cron_expr,
            array_ids=data.array_ids,
            enabled=data.enabled,
        )
        
        db.add(task)
        await db.commit()
        await db.refresh(task)
        
        if task.enabled:
            self._add_job(task)
        
        return task
    
    async def update_task(self, db: AsyncSession, task_id: int, data: ScheduledTaskUpdate) -> Optional[ScheduledTaskModel]:
        """Update a task"""
        result = await db.execute(
            select(ScheduledTaskModel).where(ScheduledTaskModel.id == task_id)
        )
        task = result.scalar()
        
        if not task:
            return None
        
        # Update fields
        update_data = data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(task, field, value)
        
        await db.commit()
        await db.refresh(task)
        
        # Update scheduler
        job_id = f"task_{task_id}"
        if task.enabled:
            self._add_job(task)
        else:
            existing = self.scheduler.get_job(job_id)
            if existing:
                self.scheduler.remove_job(job_id)
        
        return task
    
    async def delete_task(self, db: AsyncSession, task_id: int) -> bool:
        """Delete a task"""
        result = await db.execute(
            select(ScheduledTaskModel).where(ScheduledTaskModel.id == task_id)
        )
        task = result.scalar()
        
        if not task:
            return False
        
        # Remove from scheduler
        job_id = f"task_{task_id}"
        existing = self.scheduler.get_job(job_id)
        if existing:
            self.scheduler.remove_job(job_id)
        
        # Delete from database
        await db.delete(task)
        await db.commit()
        
        return True
    
    async def run_task_now(self, task_id: int):
        """Run a task immediately"""
        await self._execute_task(task_id)


# Global scheduler instance
_scheduler: Optional[TaskScheduler] = None


def get_scheduler() -> TaskScheduler:
    """Get or create scheduler instance"""
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler()
    return _scheduler
