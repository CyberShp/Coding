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
from .auth import require_admin
from ..models.observer_config import ObserverConfigModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/observer-configs", tags=["observer-configs"])

VALID_OBSERVERS = [
    'error_code', 'link_status', 'port_fec', 'port_speed', 'port_traffic',
    'port_error_code', 'sfp_monitor', 'card_recovery', 'card_info',
    'pcie_bandwidth', 'alarm_type', 'cpu_usage', 'memory_leak',
    'process_crash', 'process_restart', 'io_timeout', 'abnormal_reset',
    'cmd_response', 'sig_monitor', 'sensitive_info', 'custom_commands',
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
