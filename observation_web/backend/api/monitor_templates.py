"""
Admin monitor templates API.

CRUD for custom monitor templates and deploy to arrays.
Admin-only (require_admin).
"""

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..models.monitor_template import (
    MonitorAssignmentModel,
    MonitorTemplateModel,
    MonitorTemplateVersionModel,
)
from ..core.monitor_template_service import (
    CONFIG_FIELDS,
    add_version_snapshot,
    ensure_template_identity,
    template_to_agent_config,
)
from .auth import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/monitor-templates", tags=["admin-monitors"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class MonitorTemplateCreate(BaseModel):
    name: str
    description: str = ""
    category: str = "custom"
    command: str
    command_type: str = "shell"
    interval: int = 60
    timeout: int = 30
    match_type: str = "regex"
    match_expression: str
    match_condition: str = "found"
    match_threshold: Optional[str] = None
    alert_level: str = "warning"
    alert_message_template: str = ""
    cooldown: int = 300
    consecutive_threshold: int = 1
    is_enabled: bool = True
    visibility: str = "team"
    team_scope: str = ""


class MonitorTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    command: Optional[str] = None
    command_type: Optional[str] = None
    interval: Optional[int] = None
    timeout: Optional[int] = None
    match_type: Optional[str] = None
    match_expression: Optional[str] = None
    match_condition: Optional[str] = None
    match_threshold: Optional[str] = None
    alert_level: Optional[str] = None
    alert_message_template: Optional[str] = None
    cooldown: Optional[int] = None
    is_enabled: Optional[bool] = None
    visibility: Optional[str] = None
    team_scope: Optional[str] = None
    consecutive_threshold: Optional[int] = None


def _template_to_agent_config(t: MonitorTemplateModel) -> Dict[str, Any]:
    """Convert template to agent custom_monitors item format."""
    return template_to_agent_config(t)


def _model_to_dict(m: MonitorTemplateModel) -> dict:
    return {
        "id": m.id,
        "name": m.name,
        "description": m.description or "",
        "category": m.category or "custom",
        "command": m.command,
        "command_type": m.command_type or "shell",
        "interval": m.interval or 60,
        "timeout": m.timeout or 30,
        "match_type": m.match_type or "regex",
        "match_expression": m.match_expression,
        "match_condition": m.match_condition or "found",
        "match_threshold": m.match_threshold,
        "alert_level": m.alert_level or "warning",
        "alert_message_template": m.alert_message_template or "",
        "cooldown": m.cooldown or 300,
        "consecutive_threshold": m.consecutive_threshold if m.consecutive_threshold is not None else 1,
        "is_enabled": m.is_enabled if m.is_enabled is not None else True,
        "is_builtin": m.is_builtin or False,
        "created_by": m.created_by or "",
        "template_key": m.template_key or "",
        "version": m.version or 1,
        "visibility": m.visibility or "team",
        "team_scope": m.team_scope or "",
        "config_fingerprint": m.config_fingerprint or "",
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=List[dict])
async def list_templates(
    _payload: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all monitor templates."""
    result = await db.execute(select(MonitorTemplateModel).order_by(MonitorTemplateModel.id))
    rows = result.scalars().all()
    if rows:
        version_result = await db.execute(
            select(MonitorTemplateVersionModel.template_id).where(
                MonitorTemplateVersionModel.template_id.in_([row.id for row in rows]),
                MonitorTemplateVersionModel.version == 1,
            )
        )
        versioned_ids = set(version_result.scalars().all())
        repaired = False
        for row in rows:
            if not row.template_key:
                ensure_template_identity(row)
                repaired = True
            if row.id not in versioned_ids:
                row.version = row.version or 1
                add_version_snapshot(db, row, row.created_by or "migration")
                repaired = True
        if repaired:
            await db.commit()
            for row in rows:
                await db.refresh(row)
    return [_model_to_dict(r) for r in rows]


@router.post("", response_model=dict)
async def create_template(
    body: MonitorTemplateCreate,
    request: Request,
    _payload: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new monitor template."""
    created_by = _payload.get("sub") or (request.client.host if request.client else "")
    if body.visibility not in {"private", "team", "global"}:
        raise HTTPException(status_code=400, detail="visibility must be private, team or global")
    m = MonitorTemplateModel(
        name=body.name,
        description=body.description,
        category=body.category,
        command=body.command,
        command_type=body.command_type,
        interval=body.interval,
        timeout=body.timeout,
        match_type=body.match_type,
        match_expression=body.match_expression,
        match_condition=body.match_condition,
        match_threshold=body.match_threshold,
        alert_level=body.alert_level,
        alert_message_template=body.alert_message_template,
        cooldown=body.cooldown,
        consecutive_threshold=body.consecutive_threshold,
        is_enabled=body.is_enabled,
        is_builtin=False,
        created_by=created_by,
        visibility=body.visibility,
        team_scope=body.team_scope,
        version=1,
    )
    ensure_template_identity(m)
    db.add(m)
    await db.flush()
    add_version_snapshot(db, m, created_by)
    await db.commit()
    await db.refresh(m)
    return _model_to_dict(m)


@router.put("/{template_id}", response_model=dict)
async def update_template(
    template_id: int,
    body: MonitorTemplateUpdate,
    _payload: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a monitor template."""
    result = await db.execute(select(MonitorTemplateModel).where(MonitorTemplateModel.id == template_id))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Template not found")
    updates = body.model_dump(exclude_unset=True)
    visibility = updates.get("visibility")
    if visibility is not None and visibility not in {"private", "team", "global"}:
        raise HTTPException(status_code=400, detail="visibility must be private, team or global")
    for k, v in updates.items():
        setattr(m, k, v)
    m.version = (m.version or 1) + 1
    await db.flush()
    add_version_snapshot(db, m, _payload.get("sub", ""))
    assignment_result = await db.execute(
        select(MonitorAssignmentModel).where(MonitorAssignmentModel.template_id == m.id)
    )
    for assignment in assignment_result.scalars().all():
        assignment.desired_version = m.version
        assignment.status = "pending"
        assignment.status_message = "模板已更新，等待重新下发"
    await db.commit()
    await db.refresh(m)
    return _model_to_dict(m)


@router.get("/{template_id}/versions", response_model=List[dict])
async def list_template_versions(
    template_id: int,
    _payload: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MonitorTemplateVersionModel)
        .where(MonitorTemplateVersionModel.template_id == template_id)
        .order_by(MonitorTemplateVersionModel.version.desc())
    )
    return [
        {
            "id": row.id,
            "template_id": row.template_id,
            "version": row.version,
            "snapshot": json.loads(row.snapshot),
            "config_fingerprint": row.config_fingerprint,
            "created_by": row.created_by or "",
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in result.scalars().all()
    ]


@router.post("/{template_id}/versions/{version}/restore", response_model=dict)
async def restore_template_version(
    template_id: int,
    version: int,
    _payload: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Restore a historical snapshot as a new immutable version."""
    template_result = await db.execute(
        select(MonitorTemplateModel).where(MonitorTemplateModel.id == template_id)
    )
    template = template_result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    version_result = await db.execute(
        select(MonitorTemplateVersionModel).where(
            MonitorTemplateVersionModel.template_id == template_id,
            MonitorTemplateVersionModel.version == version,
        )
    )
    historical = version_result.scalar_one_or_none()
    if not historical:
        raise HTTPException(status_code=404, detail="Template version not found")
    snapshot = json.loads(historical.snapshot)
    for field in CONFIG_FIELDS:
        if field in snapshot:
            setattr(template, field, snapshot[field])
    template.version = (template.version or 1) + 1
    await db.flush()
    add_version_snapshot(db, template, _payload.get("sub", ""))
    assignment_result = await db.execute(
        select(MonitorAssignmentModel).where(MonitorAssignmentModel.template_id == template.id)
    )
    for assignment in assignment_result.scalars().all():
        assignment.desired_version = template.version
        assignment.status = "pending"
        assignment.status_message = f"已恢复 v{version}，等待重新下发"
    await db.commit()
    await db.refresh(template)
    return _model_to_dict(template)


@router.delete("/{template_id}")
async def delete_template(
    template_id: int,
    _payload: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a monitor template. Builtin templates cannot be deleted."""
    result = await db.execute(select(MonitorTemplateModel).where(MonitorTemplateModel.id == template_id))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Template not found")
    if m.is_builtin:
        raise HTTPException(status_code=400, detail="Builtin templates cannot be deleted")
    await db.delete(m)
    await db.commit()
    return {"ok": True}


from .monitor_deployments import router as monitor_deployments_router

router.include_router(monitor_deployments_router)
