"""
Monitor templates API (multi-user Phase 2).

CRUD for custom monitor templates and deploy to arrays. Any logged-in user can
create/read/deploy their own monitors; visibility (draft/team/global) controls
who sees them and owner/admin gates mutation. Builtin templates stay admin-only.
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
    VISIBILITY_ORDER,
    VISIBILITY_VALUES,
    add_version_snapshot,
    ensure_template_identity,
    get_user_team_ids,
    template_to_agent_config,
)
from ..models.user_account import UserAccountModel
from .auth import get_current_user, require_user

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
    # Unified monitor: exec_location=backend runs via the scheduler over SSH.
    exec_location: str = "agent"
    commands: Optional[List[str]] = None       # backend multi-command
    monitor_arrays: Optional[List[str]] = None  # backend target array_ids
    rule_spec: Optional[Dict[str, Any]] = None  # backend QueryEngine rule


class PublishRequest(BaseModel):
    visibility: str


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
        "owner_user_id": m.owner_user_id,
        "template_key": m.template_key or "",
        "version": m.version or 1,
        "visibility": m.visibility or "team",
        "team_scope": m.team_scope or "",
        "config_fingerprint": m.config_fingerprint or "",
        "exec_location": m.exec_location or "agent",
        "commands": json.loads(m.commands_json) if m.commands_json else [],
        "monitor_arrays": json.loads(m.monitor_arrays) if m.monitor_arrays else [],
        "rule_spec": json.loads(m.rule_spec_json) if m.rule_spec_json else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------

def _is_owner_or_admin(user: UserAccountModel, template: MonitorTemplateModel) -> bool:
    """Owner (by precise FK) or any admin may mutate a template."""
    if user.is_admin:
        return True
    return (
        template.owner_user_id is not None
        and user.id
        and template.owner_user_id == user.id
    )


def _is_visible(
    template: MonitorTemplateModel,
    user: Optional[UserAccountModel],
    team_ids: set,
) -> bool:
    """Visibility rule (list_templates contract):
    global ∪ builtin(default) ∪ (team ∧ team_scope∈user teams) ∪ owned-by-user.
    Anonymous users see only global + builtin defaults.
    """
    visibility = template.visibility or "team"
    if visibility == "global" or template.is_builtin:
        return True
    if user is None:
        return False
    if user.is_admin:
        return True
    if template.owner_user_id is not None and user.id and template.owner_user_id == user.id:
        return True
    if visibility == "team" and template.team_scope and str(template.team_scope) in team_ids:
        return True
    return False


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=List[dict])
async def list_templates(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """List monitor templates visible to the caller.

    Anonymous callers see only global + builtin defaults; logged-in users
    additionally see team templates scoped to their L1 tags and everything they
    own; admins see all.
    """
    user = await get_current_user(request)
    team_ids: set = set()
    if user is not None and user.id:
        team_ids = {str(t) for t in await get_user_team_ids(db, user.id)}
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
    visible = [r for r in rows if _is_visible(r, user, team_ids)]
    return [_model_to_dict(r) for r in visible]


@router.post("", response_model=dict)
async def create_template(
    body: MonitorTemplateCreate,
    user: UserAccountModel = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new monitor template (any logged-in user)."""
    created_by = user.nickname or ""
    if body.visibility not in VISIBILITY_VALUES:
        raise HTTPException(status_code=400, detail="visibility must be draft, team or global")
    # team_scope: the user's first L1 tag id (string); empty => personal-only.
    team_scope = body.team_scope or ""
    if not team_scope and user.id:
        team_ids = await get_user_team_ids(db, user.id)
        if team_ids:
            team_scope = str(team_ids[0])
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
        owner_user_id=(user.id or None),
        visibility=body.visibility,
        team_scope=team_scope,
        version=1,
        exec_location=body.exec_location or "agent",
        commands_json=json.dumps(body.commands) if body.commands is not None else None,
        monitor_arrays=json.dumps(body.monitor_arrays) if body.monitor_arrays is not None else None,
        rule_spec_json=json.dumps(body.rule_spec, ensure_ascii=False) if body.rule_spec is not None else None,
    )
    ensure_template_identity(m)
    db.add(m)
    await db.flush()
    add_version_snapshot(db, m, created_by)
    await db.commit()
    await db.refresh(m)
    # Backend-exec definitions are driven by the scheduler; register the job.
    if m.exec_location == "backend":
        try:
            from ..core.scheduler import get_scheduler
            get_scheduler().add_backend_monitor(m)
        except Exception:
            logger.warning("Failed to register backend monitor %s", m.id, exc_info=True)
    return _model_to_dict(m)


@router.put("/{template_id}", response_model=dict)
async def update_template(
    template_id: int,
    body: MonitorTemplateUpdate,
    user: UserAccountModel = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a monitor template. Owner or admin only; builtin => admin only."""
    result = await db.execute(select(MonitorTemplateModel).where(MonitorTemplateModel.id == template_id))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Template not found")
    if m.is_builtin and not user.is_admin:
        raise HTTPException(status_code=403, detail="内置模板仅管理员可修改")
    if not _is_owner_or_admin(user, m):
        raise HTTPException(status_code=403, detail="仅创建者或管理员可修改")
    updates = body.model_dump(exclude_unset=True)
    visibility = updates.get("visibility")
    if visibility is not None and visibility not in VISIBILITY_VALUES:
        raise HTTPException(status_code=400, detail="visibility must be draft, team or global")
    for k, v in updates.items():
        setattr(m, k, v)
    m.version = (m.version or 1) + 1
    await db.flush()
    add_version_snapshot(db, m, user.nickname or "")
    assignment_result = await db.execute(
        select(MonitorAssignmentModel).where(MonitorAssignmentModel.template_id == m.id)
    )
    for assignment in assignment_result.scalars().all():
        assignment.desired_version = m.version
        assignment.status = "pending"
        assignment.status_message = "模板已更新，等待重新下发"
    await db.commit()
    await db.refresh(m)
    # Keep the backend scheduler job in sync (interval/rule may have changed, or
    # exec_location switched away from backend).
    try:
        from ..core.scheduler import get_scheduler
        if m.exec_location == "backend":
            get_scheduler().add_backend_monitor(m)
        else:
            get_scheduler().remove_backend_monitor(m.id)
    except Exception:
        logger.warning("Failed to sync backend monitor job for %s", m.id, exc_info=True)
    return _model_to_dict(m)


@router.post("/{template_id}/publish", response_model=dict)
async def publish_template(
    template_id: int,
    body: PublishRequest,
    user: UserAccountModel = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Change a template's visibility (publish). Owner or admin only.

    Only upgrades along draft -> team -> global are allowed (never a downgrade),
    matching the lifecycle in the design contract.
    """
    if body.visibility not in VISIBILITY_VALUES:
        raise HTTPException(status_code=400, detail="visibility must be draft, team or global")
    result = await db.execute(
        select(MonitorTemplateModel).where(MonitorTemplateModel.id == template_id)
    )
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Template not found")
    if not _is_owner_or_admin(user, m):
        raise HTTPException(status_code=403, detail="仅创建者或管理员可发布")
    current = m.visibility or "team"
    if VISIBILITY_ORDER[body.visibility] < VISIBILITY_ORDER[current]:
        raise HTTPException(
            status_code=400,
            detail=f"不可降级可见性（{current} -> {body.visibility}）",
        )
    m.visibility = body.visibility
    await db.commit()
    await db.refresh(m)
    return _model_to_dict(m)


@router.get("/{template_id}/versions", response_model=List[dict])
async def list_template_versions(
    template_id: int,
    _user: UserAccountModel = Depends(require_user),
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
    user: UserAccountModel = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Restore a historical snapshot as a new immutable version."""
    template_result = await db.execute(
        select(MonitorTemplateModel).where(MonitorTemplateModel.id == template_id)
    )
    template = template_result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if template.is_builtin and not user.is_admin:
        raise HTTPException(status_code=403, detail="内置模板仅管理员可修改")
    if not _is_owner_or_admin(user, template):
        raise HTTPException(status_code=403, detail="仅创建者或管理员可恢复版本")
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
    add_version_snapshot(db, template, user.nickname or "")
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
    user: UserAccountModel = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a monitor template. Owner or admin only; builtin => admin only."""
    result = await db.execute(select(MonitorTemplateModel).where(MonitorTemplateModel.id == template_id))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Template not found")
    if m.is_builtin:
        # Builtin add/edit/delete stays admin-gated regardless of ownership.
        if not user.is_admin:
            raise HTTPException(status_code=403, detail="内置模板仅管理员可删除")
        raise HTTPException(status_code=400, detail="Builtin templates cannot be deleted")
    if not _is_owner_or_admin(user, m):
        raise HTTPException(status_code=403, detail="仅创建者或管理员可删除")
    was_backend = m.exec_location == "backend"
    tid = m.id
    await db.delete(m)
    await db.commit()
    if was_backend:
        try:
            from ..core.scheduler import get_scheduler
            get_scheduler().remove_backend_monitor(tid)
        except Exception:
            logger.warning("Failed to remove backend monitor job %s", tid, exc_info=True)
    return {"ok": True}


from .monitor_deployments import router as monitor_deployments_router

router.include_router(monitor_deployments_router)
