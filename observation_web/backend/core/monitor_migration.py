"""Idempotent migration of legacy monitor definitions into the unified
monitor_templates base (exec_location=backend).

Folds query auto-monitors and query-template-backed scheduled tasks into backend
monitor definitions. Pure-command scheduled tasks are left as ops tasks.
Safe to run repeatedly: keyed on the generated name so re-runs don't duplicate.
"""
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.monitor_template import MonitorTemplateModel
from .monitor_rule import query_template_to_backend_fields
from .monitor_template_service import add_version_snapshot, ensure_template_identity

logger = logging.getLogger(__name__)


async def _exists(db: AsyncSession, name: str) -> bool:
    return (await db.execute(
        select(MonitorTemplateModel.id).where(MonitorTemplateModel.name == name)
    )).scalar_one_or_none() is not None


async def _create_backend_def(db, *, name, commands_json, monitor_arrays,
                              rule_spec_json, interval, created_by):
    commands = json.loads(commands_json) if commands_json else []
    rule = json.loads(rule_spec_json) if rule_spec_json else {}
    m = MonitorTemplateModel(
        name=name,
        command=(commands[0] if commands else "true"),
        match_type="regex",
        match_expression=rule.get("pattern") or ".",
        match_condition="found",
        interval=interval or 300,
        exec_location="backend",
        commands_json=commands_json,
        monitor_arrays=monitor_arrays,
        rule_spec_json=rule_spec_json,
        visibility="team",
        created_by=created_by,
        is_enabled=True,
        version=1,
    )
    ensure_template_identity(m)
    db.add(m)
    await db.flush()
    add_version_snapshot(db, m, created_by)
    return m


async def migrate_query_auto_monitors(db: AsyncSession) -> int:
    """query_templates.auto_monitor -> backend monitor definitions."""
    from ..models.query import QueryTemplateModel
    rows = (await db.execute(
        select(QueryTemplateModel).where(QueryTemplateModel.auto_monitor == True)  # noqa: E712
    )).scalars().all()
    created = 0
    for qt in rows:
        name = f"query:{qt.name}"
        if await _exists(db, name):
            continue
        f = query_template_to_backend_fields(qt)
        await _create_backend_def(
            db, name=name, commands_json=f["commands_json"],
            monitor_arrays=f["monitor_arrays"], rule_spec_json=f["rule_spec_json"],
            interval=f["interval"], created_by="migration",
        )
        created += 1
    await db.commit()
    logger.info("Migrated %d query auto-monitors to backend definitions", created)
    return created


async def migrate_scheduled_templates(db: AsyncSession) -> int:
    """scheduled_tasks backed by a query_template -> backend definitions."""
    from ..models.scheduler import ScheduledTaskModel
    from ..models.query import QueryTemplateModel
    rows = (await db.execute(
        select(ScheduledTaskModel).where(ScheduledTaskModel.query_template_id.isnot(None))
    )).scalars().all()
    created = 0
    for task in rows:
        qt = (await db.execute(
            select(QueryTemplateModel).where(QueryTemplateModel.id == task.query_template_id)
        )).scalar_one_or_none()
        if qt is None:
            continue
        name = f"scheduled:{task.name}"
        if await _exists(db, name):
            continue
        f = query_template_to_backend_fields(qt)
        await _create_backend_def(
            db, name=name, commands_json=f["commands_json"],
            monitor_arrays=json.dumps(task.array_ids or []),
            rule_spec_json=f["rule_spec_json"], interval=f["interval"],
            created_by="migration",
        )
        created += 1
    await db.commit()
    logger.info("Migrated %d scheduled query-templates to backend definitions", created)
    return created


async def migrate_all(db: AsyncSession) -> dict:
    return {
        "query_auto_monitors": await migrate_query_auto_monitors(db),
        "scheduled_templates": await migrate_scheduled_templates(db),
    }
