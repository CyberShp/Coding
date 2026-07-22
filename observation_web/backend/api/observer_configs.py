"""
API for managing built-in observer configuration overrides.

Allows admins to toggle enabled/disabled, change interval,
and set custom parameters for built-in observers.
These overrides are merged into the agent config.json on deploy.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from .auth import require_admin, require_user, get_current_user
from ..models.observer_config import ObserverConfigModel, ObserverConfigOverrideModel
from ..models.array import ArrayModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/observer-configs", tags=["observer-configs"])

VALID_OBSERVERS = [
    'error_code', 'link_status', 'port_fec', 'port_speed', 'port_traffic',
    'port_error_code', 'sfp_monitor', 'card_recovery', 'card_info',
    'pcie_bandwidth', 'alarm_type', 'cpu_usage', 'memory_leak',
    'process_crash', 'process_restart', 'io_timeout', 'abnormal_reset',
    'cmd_response', 'sig_monitor', 'sensitive_info', 'custom_commands', 'start_work',
    'controller_state', 'disk_state',
]


class ObserverConfigOut(BaseModel):
    observer_name: str
    enabled: bool
    interval: Optional[int] = None
    params: Dict[str, Any] = {}


class ObserverConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    interval: Optional[int] = None
    params: Optional[Dict[str, Any]] = None


VALID_SCOPE_TYPES = ("tag", "array")


class ObserverOverrideOut(BaseModel):
    observer_name: str
    scope_type: str
    scope_id: str
    params: Dict[str, Any] = {}
    enabled: Optional[bool] = None
    updated_by: str = ""


class ObserverOverrideUpsert(BaseModel):
    scope_type: str
    scope_id: str
    params: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


@router.get("", response_model=List[ObserverConfigOut])
async def list_observer_configs(
    _payload: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all observer config overrides."""
    result = await db.execute(select(ObserverConfigModel))
    rows = result.scalars().all()
    return [
        ObserverConfigOut(
            observer_name=r.observer_name,
            enabled=r.enabled,
            interval=r.interval,
            params=json.loads(r.params_json) if r.params_json else {},
        )
        for r in rows
    ]


@router.put("/{observer_name}")
async def update_observer_config(
    observer_name: str,
    body: ObserverConfigUpdate,
    _payload: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create or update an observer config override."""
    if observer_name not in VALID_OBSERVERS:
        raise HTTPException(status_code=400, detail=f"Unknown observer: {observer_name}")

    result = await db.execute(
        select(ObserverConfigModel).where(ObserverConfigModel.observer_name == observer_name)
    )
    row = result.scalars().first()

    if row is None:
        row = ObserverConfigModel(
            observer_name=observer_name,
            enabled=body.enabled if body.enabled is not None else True,
            interval=body.interval,
            params_json=json.dumps(body.params or {}, ensure_ascii=False),
            updated_by=_payload.get("sub", ""),
        )
        db.add(row)
    else:
        if body.enabled is not None:
            row.enabled = body.enabled
        if body.interval is not None:
            row.interval = body.interval
        if body.params is not None:
            row.params_json = json.dumps(body.params, ensure_ascii=False)
        row.updated_by = _payload.get("sub", "")

    await db.flush()
    return {
        "ok": True,
        "observer_name": observer_name,
        "enabled": row.enabled,
        "interval": row.interval,
        "params": json.loads(row.params_json) if row.params_json else {},
    }


async def get_all_observer_overrides(db: AsyncSession) -> Dict[str, Dict]:
    """
    Utility for deploy: returns a dict of observer_name -> override config.
    Called by deploy endpoints to merge into agent config.json.
    """
    result = await db.execute(select(ObserverConfigModel))
    rows = result.scalars().all()
    overrides = {}
    for r in rows:
        override = {}
        override["enabled"] = r.enabled
        if r.interval is not None:
            override["interval"] = r.interval
        if r.params_json:
            try:
                extra = json.loads(r.params_json)
                if isinstance(extra, dict):
                    override.update(extra)
            except json.JSONDecodeError:
                pass
        overrides[r.observer_name] = override
    return overrides


# ---------------------------------------------------------------------------
# Per-tag / per-array override layer (multi-user Phase 3)
# ---------------------------------------------------------------------------

@router.get("/{observer_name}/overrides", response_model=List[ObserverOverrideOut])
async def list_observer_overrides(
    observer_name: str,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all tag/array overrides for a given observer."""
    result = await db.execute(
        select(ObserverConfigOverrideModel).where(
            ObserverConfigOverrideModel.observer_name == observer_name
        )
    )
    rows = result.scalars().all()
    return [
        ObserverOverrideOut(
            observer_name=r.observer_name,
            scope_type=r.scope_type,
            scope_id=r.scope_id,
            params=json.loads(r.params_json) if r.params_json else {},
            enabled=r.enabled,
            updated_by=r.updated_by or "",
        )
        for r in rows
    ]


@router.post("/{observer_name}/overrides")
async def upsert_observer_override(
    observer_name: str,
    body: ObserverOverrideUpsert,
    user=Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or update a per-tag / per-array override for an observer.

    Uses require_user (not require_admin): per the design, anyone logged in may
    tune their own group/array, with attribution recorded via updated_by.
    """
    if observer_name not in VALID_OBSERVERS:
        raise HTTPException(status_code=400, detail=f"Unknown observer: {observer_name}")
    if body.scope_type not in VALID_SCOPE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scope_type: {body.scope_type} (expected tag|array)",
        )
    if not body.scope_id:
        raise HTTPException(status_code=400, detail="scope_id is required")

    result = await db.execute(
        select(ObserverConfigOverrideModel).where(
            ObserverConfigOverrideModel.observer_name == observer_name,
            ObserverConfigOverrideModel.scope_type == body.scope_type,
            ObserverConfigOverrideModel.scope_id == body.scope_id,
        )
    )
    row = result.scalars().first()
    nickname = getattr(user, "nickname", "") or ""

    if row is None:
        row = ObserverConfigOverrideModel(
            observer_name=observer_name,
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            params_json=json.dumps(body.params or {}, ensure_ascii=False),
            enabled=body.enabled,
            updated_by=nickname,
        )
        db.add(row)
    else:
        if body.params is not None:
            row.params_json = json.dumps(body.params, ensure_ascii=False)
        # enabled is tri-state; the upsert always applies the sent value
        # (including None to clear the switch override).
        row.enabled = body.enabled
        row.updated_by = nickname

    await db.flush()
    return {
        "ok": True,
        "observer_name": observer_name,
        "scope_type": row.scope_type,
        "scope_id": row.scope_id,
        "params": json.loads(row.params_json) if row.params_json else {},
        "enabled": row.enabled,
        "updated_by": row.updated_by or "",
    }


@router.delete("/{observer_name}/overrides/{scope_type}/{scope_id}")
async def delete_observer_override(
    observer_name: str,
    scope_type: str,
    scope_id: str,
    _user=Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a per-tag / per-array override."""
    result = await db.execute(
        select(ObserverConfigOverrideModel).where(
            ObserverConfigOverrideModel.observer_name == observer_name,
            ObserverConfigOverrideModel.scope_type == scope_type,
            ObserverConfigOverrideModel.scope_id == scope_id,
        )
    )
    row = result.scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Override not found")
    await db.delete(row)
    await db.flush()
    return {"ok": True}


async def resolve_observer_config(
    db: AsyncSession, observer_name: str, array_id: str
) -> Dict[str, Any]:
    """Resolve the effective config for an observer on a specific array.

    Layers, least to most specific (more specific wins):
      1. global default  -> observer_configs row (enabled/interval/params)
      2. L1 tag override  -> the array's tag_id override
      3. array override    -> this array's own override

    params dicts are deep-merged via successive ``dict.update``; ``enabled`` is
    only overridden when a layer sets a non-None value.  Returns a dict shaped
    like the per-observer block written into the agent config.json (``enabled``
    plus optional ``interval`` plus merged params).
    """
    effective: Dict[str, Any] = {}
    params: Dict[str, Any] = {}

    # Layer 1: global default
    global_row = (
        await db.execute(
            select(ObserverConfigModel).where(
                ObserverConfigModel.observer_name == observer_name
            )
        )
    ).scalars().first()
    if global_row is not None:
        effective["enabled"] = global_row.enabled
        if global_row.interval is not None:
            effective["interval"] = global_row.interval
        if global_row.params_json:
            try:
                extra = json.loads(global_row.params_json)
                if isinstance(extra, dict):
                    params.update(extra)
            except json.JSONDecodeError:
                pass

    # Determine the array's L1 tag for the tag layer.
    array_row = (
        await db.execute(
            select(ArrayModel).where(ArrayModel.array_id == array_id)
        )
    ).scalars().first()
    tag_scope_id = (
        str(array_row.tag_id) if array_row is not None and array_row.tag_id is not None else None
    )

    # Fetch tag + array overrides in one query, apply in order.
    ov_rows = (
        await db.execute(
            select(ObserverConfigOverrideModel).where(
                ObserverConfigOverrideModel.observer_name == observer_name
            )
        )
    ).scalars().all()
    by_key = {(r.scope_type, r.scope_id): r for r in ov_rows}

    ordered = []
    if tag_scope_id is not None:
        tag_ov = by_key.get(("tag", tag_scope_id))
        if tag_ov is not None:
            ordered.append(tag_ov)
    array_ov = by_key.get(("array", str(array_id)))
    if array_ov is not None:
        ordered.append(array_ov)

    for ov in ordered:
        if ov.enabled is not None:
            effective["enabled"] = ov.enabled
        if ov.params_json:
            try:
                extra = json.loads(ov.params_json)
                if isinstance(extra, dict):
                    params.update(extra)
            except json.JSONDecodeError:
                pass

    effective.update(params)
    return effective


async def get_resolved_observer_overrides(
    db: AsyncSession, array_id: str
) -> Dict[str, Dict]:
    """Per-array counterpart of ``get_all_observer_overrides`` for deploy.

    Returns observer_name -> resolved config (global default merged with the
    array's L1 tag override and its own array override). The observer set is the
    union of observers that have a global config row and observers with any
    override applicable to this array (its tag or the array itself).
    """
    # Observers with a global default row.
    global_names = set(
        (
            await db.execute(select(ObserverConfigModel.observer_name))
        ).scalars().all()
    )

    # Resolve the array's L1 tag once.
    array_row = (
        await db.execute(select(ArrayModel).where(ArrayModel.array_id == array_id))
    ).scalars().first()
    tag_scope_id = (
        str(array_row.tag_id) if array_row is not None and array_row.tag_id is not None else None
    )

    # Observers with an override that applies to this array (tag or array scope).
    ov_rows = (
        await db.execute(
            select(
                ObserverConfigOverrideModel.observer_name,
                ObserverConfigOverrideModel.scope_type,
                ObserverConfigOverrideModel.scope_id,
            )
        )
    ).all()
    override_names = set()
    for name, scope_type, scope_id in ov_rows:
        if scope_type == "array" and scope_id == str(array_id):
            override_names.add(name)
        elif scope_type == "tag" and tag_scope_id is not None and scope_id == tag_scope_id:
            override_names.add(name)

    resolved: Dict[str, Dict] = {}
    for name in global_names | override_names:
        resolved[name] = await resolve_observer_config(db, name, array_id)
    return resolved
