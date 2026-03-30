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
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.system_alert import sys_info, sys_error
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
    array_id: Optional[str] = None  # Real array_id — required for alert ingestion
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
    """Process an incoming alert from agent push.

    The payload MUST carry a real ``array_id``.  If it is missing we
    attempt an IP → array_id mapping lookup.  If that also fails we
    reject the request — we never generate ``push_xxx`` pseudo IDs.
    """
    from ..core.alert_store import get_alert_store
    from ..models.alert import AlertCreate, AlertLevel
    from .websocket import broadcast_alert
    from ..core.runtime_status import (
        resolve_array_id_by_ip,
        record_heartbeat,
        on_recovery_event,
    )
    
    try:
        # --- Resolve array_id ---
        real_array_id = payload.array_id
        if not real_array_id:
            real_array_id = resolve_array_id_by_ip(source_ip)
        if not real_array_id:
            raise HTTPException(
                status_code=400,
                detail=f"Missing array_id in payload and no IP mapping for {source_ip}",
            )
        # Reject any pseudo ID pattern
        if real_array_id.startswith("push_"):
            raise HTTPException(
                status_code=400,
                detail=f"Rejected pseudo array_id '{real_array_id}'; provide a real array_id",
            )

        level_str = (payload.level or "info").lower()
        level = AlertLevel(level_str) if level_str in [l.value for l in AlertLevel] else AlertLevel.INFO
        
        timestamp = datetime.now()
        if payload.timestamp:
            try:
                timestamp = datetime.fromisoformat(
                    payload.timestamp.replace('Z', '+00:00').replace('+00:00', '')
                )
            except Exception:
                pass
        
        alert_create = AlertCreate(
            array_id=real_array_id,
            observer_name=payload.observer_name or "unknown",
            level=level,
            message=payload.message or "",
            details=payload.details or {},
            timestamp=timestamp,
        )
        
        alert_store = get_alert_store()
        await alert_store.create_alert(db, alert_create)
        
        # Record heartbeat for health tracking
        record_heartbeat(real_array_id, source="ingest")

        # Broadcast via WebSocket
        await broadcast_alert({
            'array_id': alert_create.array_id,
            'observer_name': alert_create.observer_name,
            'level': alert_create.level.value,
            'message': alert_create.message,
            'timestamp': alert_create.timestamp.isoformat(),
            'source': 'push',
        })
        
        return {"ok": True, "message": "Alert ingested", "array_id": real_array_id}
        
    except HTTPException:
        raise
    except Exception as e:
        sys_error("ingest", f"Failed to process pushed alert from {source_ip}", {"error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))


async def _handle_metrics(payload: IngestPayload, source_ip: str):
    """Process incoming metrics from agent push"""
    from ..core.runtime_status import resolve_array_id_by_ip, record_heartbeat

    try:
        # Resolve real array_id (metrics can fall back to source_ip key)
        real_array_id = payload.array_id
        if not real_array_id:
            real_array_id = resolve_array_id_by_ip(source_ip)
        store_key = real_array_id or source_ip

        # Build metrics record
        record = {
            "ts": payload.ts or datetime.now().isoformat(),
            "source_ip": source_ip,
            "array_id": store_key,
        }
        
        # Extract known metrics fields
        extra = payload.dict(exclude={"type", "ts", "array_id"}, exclude_none=True)
        record.update(extra)
        
        # Store in memory
        if store_key not in _metrics_store:
            _metrics_store[store_key] = deque(maxlen=MAX_METRICS_PER_ARRAY)
        _metrics_store[store_key].append(record)

        # Record heartbeat for health tracking
        if real_array_id:
            record_heartbeat(real_array_id, source="ingest")
        
        return {"ok": True}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def get_metrics_for_ip(source_ip: str, minutes: int = 60) -> List[Dict]:
    """Get stored metrics for a source IP"""
    if source_ip not in _metrics_store:
        return []
    
    cutoff = datetime.now().timestamp() - (minutes * 60)
    results = []
    
    for record in _metrics_store[source_ip]:
        try:
            ts = datetime.fromisoformat(record["ts"]).timestamp()
            if ts >= cutoff:
                results.append(record)
        except Exception:
            results.append(record)
    
    return results


def get_all_metrics_sources() -> List[str]:
    """Get list of all source IPs with metrics"""
    return list(_metrics_store.keys())
