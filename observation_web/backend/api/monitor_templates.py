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

from ..config import get_config
from ..core.ssh_pool import get_ssh_pool
from ..db.database import get_db
from ..models.monitor_template import MonitorTemplateModel
from ..models.array import ArrayModel
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
    is_enabled: bool = True


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


class DeployRequest(BaseModel):
    template_ids: List[int]
    target_type: str  # "tag" | "array"
    target_ids: List[int]  # tag ids or array ids (array.id from DB, we need array_id string)


def _template_to_agent_config(t: MonitorTemplateModel) -> Dict[str, Any]:
    """Convert template to agent custom_monitors item format."""
    return {
        "name": t.name,
        "command": t.command,
        "command_type": t.command_type or "shell",
        "interval": t.interval or 60,
        "timeout": t.timeout or 30,
        "match_type": t.match_type or "regex",
        "match_expression": t.match_expression,
        "match_condition": t.match_condition or "found",
        "match_threshold": t.match_threshold,
        "alert_level": t.alert_level or "warning",
        "alert_message_template": t.alert_message_template or "",
        "cooldown": t.cooldown or 300,
    }


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
        "is_enabled": m.is_enabled if m.is_enabled is not None else True,
        "is_builtin": m.is_builtin or False,
        "created_by": m.created_by or "",
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
    return [_model_to_dict(r) for r in rows]


@router.post("", response_model=dict)
async def create_template(
    body: MonitorTemplateCreate,
    request: Request,
    _payload: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new monitor template."""
    created_by = ""
    if request.client:
        created_by = request.client.host
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
        is_enabled=body.is_enabled,
        is_builtin=False,
        created_by=created_by,
    )
    db.add(m)
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
    for k, v in updates.items():
        setattr(m, k, v)
    await db.commit()
    await db.refresh(m)
    return _model_to_dict(m)


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


# ---------------------------------------------------------------------------
# Deploy endpoint
# ---------------------------------------------------------------------------

@router.post("/deploy")
async def deploy_templates(
    body: DeployRequest,
    _payload: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Deploy selected templates to target arrays.
    target_type: "tag" -> target_ids are tag IDs; "array" -> target_ids are array.id (DB primary key)
    """
    if not body.template_ids:
        raise HTTPException(status_code=400, detail="template_ids required")
    if not body.target_ids:
        raise HTTPException(status_code=400, detail="target_ids required")

    # Resolve array_ids
    if body.target_type == "tag":
        result = await db.execute(
            select(ArrayModel.array_id).where(ArrayModel.tag_id.in_(body.target_ids))
        )
        array_ids = [row[0] for row in result.all() if row[0]]
    elif body.target_type == "array":
        result = await db.execute(
            select(ArrayModel.array_id).where(ArrayModel.id.in_(body.target_ids))
        )
        array_ids = [row[0] for row in result.all() if row[0]]
    else:
        raise HTTPException(status_code=400, detail="target_type must be 'tag' or 'array'")

    if not array_ids:
        raise HTTPException(status_code=400, detail="No arrays found for target")

    # Fetch templates
    result = await db.execute(
        select(MonitorTemplateModel).where(
            MonitorTemplateModel.id.in_(body.template_ids),
            MonitorTemplateModel.is_enabled == True,
        )
    )
    templates = result.scalars().all()
    if not templates:
        raise HTTPException(status_code=400, detail="No enabled templates found")

    custom_monitors = [_template_to_agent_config(t) for t in templates]

    from .observer_configs import get_all_observer_overrides
    observer_overrides = await get_all_observer_overrides(db)

    ssh_pool = get_ssh_pool()
    config = get_config()
    agent_path = config.remote.agent_deploy_path
    config_path = f"{agent_path}/config.json"

    results = []
    for array_id in array_ids:
        conn = ssh_pool.get_connection(array_id)
        if not conn or not conn.is_connected():
            results.append({"array_id": array_id, "ok": False, "error": "Array not connected"})
            continue
        try:
            content = conn.read_file(config_path)
            config_data = json.loads(content) if content else {}
            config_data["custom_monitors"] = custom_monitors

            if observer_overrides:
                observers = config_data.setdefault("observers", {})
                for obs_name, overrides in observer_overrides.items():
                    obs = observers.setdefault(obs_name, {})
                    obs.update(overrides)
            config_json = json.dumps(config_data, indent=2, ensure_ascii=False)
            import base64
            encoded = base64.b64encode(config_json.encode("utf-8")).decode("ascii")
            backup_cmd = f"cp {config_path} {config_path}.bak 2>/dev/null || true"
            conn.execute(backup_cmd)
            write_cmd = f"echo '{encoded}' | base64 -d > {config_path}"
            conn.execute(write_cmd)
            from ..core.agent_deployer import AgentDeployer
            deployer = AgentDeployer(conn, config)
            restart_result = deployer.restart_agent()
            results.append({
                "array_id": array_id,
                "ok": True,
                "restart_ok": restart_result.get("ok", False),
            })
        except Exception as e:
            logger.exception("Deploy failed for %s", array_id)
            results.append({"array_id": array_id, "ok": False, "error": str(e)})

    return {"results": results}
