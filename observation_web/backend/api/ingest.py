"""
Data ingestion API - receives pushed data from remote agents.

Supports two data types:
- alert: Alert data pushed from agent's Reporter
- metrics: Performance metrics (CPU, memory, etc.)
"""

import json
import logging
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.system_alert import sys_info, sys_error
from ..core.time_utils import parse_event_timestamp, timestamp_epoch
from ..db.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ingest"])

# In-memory metrics store (per array, keyed by source IP or array_id)
# Each entry stores a deque of recent metrics (last 24 hours worth)
MAX_METRICS_PER_ARRAY = 8640  # 24h * 60min * 6 (every 10s) = ~8640 points per day
_metrics_store: Dict[str, deque] = {}


class IngestPayload(BaseModel):
    """Payload from agent push"""
    type: str  # "alert" or "metrics"
    event_id: Optional[str] = None
    array_id: Optional[str] = None
    observer_name: Optional[str] = None
    level: Optional[str] = None
    message: Optional[str] = None
    timestamp: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    # Metrics fields
    ts: Optional[str] = None
    cpu0: Optional[float] = None
    mem_used_mb: Optional[float] = None
    mem_total_mb: Optional[float] = None
    # Allow extra fields
    class Config:
        extra = "allow"


@router.post("/ingest")
async def ingest_data(
    payload: IngestPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Receive pushed data from remote agents.
    
    Agents can push alerts and metrics directly to this endpoint,
    eliminating the need for SSH-based polling.
    """
    source_ip = request.client.host if request.client else "unknown"
    
    if payload.type == "alert":
        return await _handle_alert(payload, source_ip, db)
    elif payload.type == "metrics":
        return await _handle_metrics(payload, source_ip)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown type: {payload.type}")


@router.post("/ingest/batch")
async def ingest_batch(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Receive a batch of data points from an agent.
    Expects a JSON array of payloads.
    """
    source_ip = request.client.host if request.client else "unknown"
    body = await request.json()
    
    if not isinstance(body, list):
        raise HTTPException(status_code=400, detail="Expected a JSON array")
    
    results = {"alerts": 0, "metrics": 0, "errors": 0}
    
    for item in body:
        try:
            payload = IngestPayload(**item)
            if payload.type == "alert":
                await _handle_alert(payload, source_ip, db)
                results["alerts"] += 1
            elif payload.type == "metrics":
                await _handle_metrics(payload, source_ip)
                results["metrics"] += 1
        except Exception:
            results["errors"] += 1
    
    return results


async def _handle_alert(payload: IngestPayload, source_ip: str, db: AsyncSession):
    """Process an incoming alert from agent push"""
    from ..core.alert_store import get_alert_store
    from ..core.alert_identity import build_source_event_id
    from ..models.array import ArrayModel
    from ..models.alert import AlertCreate, AlertLevel, AlertModel
    from .websocket import broadcast_alert
    
    try:
        level_str = (payload.level or "info").lower()
        level = AlertLevel(level_str) if level_str in [l.value for l in AlertLevel] else AlertLevel.INFO
        
        timestamp = parse_event_timestamp(payload.timestamp)
        
        array_id = payload.array_id or ""
        if not array_id:
            match = await db.execute(
                select(ArrayModel.array_id).where(ArrayModel.host == source_ip).limit(1)
            )
            array_id = match.scalar_one_or_none() or f"push_{source_ip}"

        payload_data = payload.model_dump(exclude_none=True)
        alert_create = AlertCreate(
            array_id=array_id,
            observer_name=payload.observer_name or "unknown",
            level=level,
            message=payload.message or "",
            details=payload.details or {},
            timestamp=timestamp,
            source_event_id=build_source_event_id(array_id, payload_data),
        )
        
        alert_store = get_alert_store()
        existing = await db.execute(
            select(AlertModel).where(
                AlertModel.array_id == array_id,
                AlertModel.source_event_id == alert_create.source_event_id,
            )
        )
        db_alert = existing.scalar_one_or_none()
        if db_alert:
            return {"ok": True, "message": "Alert already ingested", "id": db_alert.id, "duplicate": True}

        db_alert = await alert_store.create_alert(db, alert_create)
        
        # Broadcast via WebSocket
        await broadcast_alert({
            'id': db_alert.id,
            'array_id': alert_create.array_id,
            'observer_name': alert_create.observer_name,
            'level': alert_create.level.value,
            'message': alert_create.message,
            'timestamp': alert_create.timestamp.isoformat(),
            'source_event_id': alert_create.source_event_id,
            'source': 'push',
        })
        
        return {"ok": True, "message": "Alert ingested", "id": db_alert.id, "duplicate": False}
        
    except Exception as e:
        sys_error("ingest", f"Failed to process pushed alert from {source_ip}", {"error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))


async def _handle_metrics(payload: IngestPayload, source_ip: str):
    """Process incoming metrics from agent push"""
    try:
        # Build metrics record
        metrics_key = payload.array_id or source_ip
        record = {
            "ts": payload.ts or datetime.now().isoformat(),
            "source_ip": source_ip,
            "array_id": payload.array_id,
        }
        
        # Extract known metrics fields
        extra = payload.model_dump(exclude={"type", "ts"}, exclude_none=True)
        record.update(extra)
        
        # Store in memory
        if metrics_key not in _metrics_store:
            _metrics_store[metrics_key] = deque(maxlen=MAX_METRICS_PER_ARRAY)
        _metrics_store[metrics_key].append(record)

        if record.get("observer") == "__agent_health__" and payload.array_id:
            await _apply_agent_health(payload.array_id, record)
        
        return {"ok": True}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _apply_agent_health(array_id: str, record: Dict[str, Any]) -> None:
    """Turn the Agent's own heartbeat into the authoritative live status."""
    from ..models.array import AgentState, DeploymentState
    from .arrays import _get_array_status, _publish_array_status

    health = record.get("agent_health") or {}
    if not isinstance(health, dict):
        health = {}

    status_obj = _get_array_status(array_id)
    observed_at = datetime.now()
    states = [
        str(item.get("status", "unknown"))
        for item in health.values()
        if isinstance(item, dict)
    ]
    failed = sum(state in {"degraded", "error"} for state in states)
    warming = any(state in {"waiting", "running"} for state in states)

    status_obj.agent_deployed = True
    status_obj.agent_running = True
    status_obj.agent_observed_at = observed_at
    status_obj.agent_heartbeat_at = observed_at
    status_obj.agent_status_source = "agent_heartbeat"
    status_obj.observer_health = health

    if status_obj.deployment_state in {
        DeploymentState.DEPLOYING,
        DeploymentState.CONFIGURING,
        DeploymentState.VERIFYING,
    }:
        status_obj.deployment_state = DeploymentState.SUCCEEDED
        status_obj.deployment_message = "Agent 已启动并通过健康心跳确认"
        status_obj.deployment_updated_at = observed_at

    if failed:
        status_obj.agent_state = AgentState.DEGRADED
        status_obj.agent_status_message = f"Agent 运行中，{failed} 个观察点采集异常"
    elif warming:
        status_obj.agent_state = AgentState.STARTING
        status_obj.agent_status_message = "Agent 已启动，观察点正在完成首轮采集"
    else:
        status_obj.agent_state = AgentState.RUNNING
        status_obj.agent_status_message = f"Agent 运行正常，{len(health)} 个观察点已就绪"

    mapped_status = {
        "ok": "ok",
        "waiting": "waiting",
        "running": "running",
        "degraded": "warning",
        "error": "error",
    }
    for name, item in health.items():
        if not isinstance(item, dict):
            continue
        raw_state = str(item.get("status", "unknown"))
        status_obj.observer_status[name] = {
            "status": mapped_status.get(raw_state, "unknown"),
            "message": str(item.get("last_error") or raw_state),
        }

    await _publish_array_status(status_obj)


def get_metrics_for_ip(source_ip: str, minutes: int = 60) -> List[Dict]:
    """Get stored metrics for an array id or legacy source IP."""
    if source_ip not in _metrics_store:
        return []
    
    cutoff = datetime.now().timestamp() - (minutes * 60)
    results = []
    
    for record in _metrics_store[source_ip]:
        try:
            ts = timestamp_epoch(record.get("ts"))
            if ts is None or ts >= cutoff:
                results.append(record)
        except Exception:
            results.append(record)
    
    return results


def get_all_metrics_sources() -> List[str]:
    """Get list of all source IPs with metrics"""
    return list(_metrics_store.keys())
