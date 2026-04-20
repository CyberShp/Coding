"""
Data ingestion API - receives pushed data from remote agents.

Supports two data types:
- alert: Alert data pushed from agent's Reporter
- metrics: Performance metrics (CPU, memory, etc.)
"""

import json
import logging
import threading
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
    array_id: Optional[str] = None  # Real array_id (required for proper attribution)
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


# ── Source IP → array_id mapping for backward compatibility ──────────────
_ip_to_array_id: Dict[str, str] = {}
_ip_mapping_lock = threading.Lock()


def register_ip_array_mapping(source_ip: str, array_id: str):
    """Register a mapping from source_ip to array_id for ingest resolution."""
    with _ip_mapping_lock:
        _ip_to_array_id[source_ip] = array_id


def _resolve_array_id(payload_array_id: Optional[str], source_ip: str) -> Optional[str]:
    """Resolve real array_id from payload or controlled IP mapping.

    Returns None if resolution fails (caller should reject the write).
    """
    if payload_array_id and not payload_array_id.startswith("push_"):
        return payload_array_id
    # Fallback: controlled mapping
    with _ip_mapping_lock:
        mapped = _ip_to_array_id.get(source_ip)
    if mapped:
        return mapped
    return None


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
    from ..models.alert import AlertCreate, AlertLevel
    from .websocket import broadcast_alert
    
    try:
        # Resolve real array_id – reject push_xxx pseudo IDs
        real_array_id = _resolve_array_id(payload.array_id, source_ip)
        if not real_array_id:
            logger.warning(
                "Ingest alert rejected: no real array_id (payload=%s, source_ip=%s)",
                payload.array_id, source_ip,
            )
            raise HTTPException(
                status_code=400,
                detail="Missing or unresolvable array_id. "
                       "Agent must include a real array_id in the payload.",
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
        db_alert = await alert_store.create_alert(db, alert_create)

        # Broadcast via WebSocket (include id for AI auto-translation)
        await broadcast_alert({
            'id': db_alert.id,
            'array_id': alert_create.array_id,
            'observer_name': alert_create.observer_name,
            'level': alert_create.level.value,
            'message': alert_create.message,
            'timestamp': alert_create.timestamp.isoformat(),
            'source': 'push',
            'source_ip': source_ip,
        })

        # Trigger recovery-event handling (valid ingest push)
        from ..core.runtime_status import handle_recovery_event
        try:
            await handle_recovery_event(real_array_id, "ingest_push")
        except Exception:
            pass  # non-fatal

        return {"ok": True, "message": "Alert ingested", "array_id": real_array_id}
        
    except HTTPException:
        raise
    except Exception as e:
        sys_error("ingest", f"Failed to process pushed alert from {source_ip}", {"error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))


async def _handle_metrics(payload: IngestPayload, source_ip: str):
    """Process incoming metrics from agent push"""
    try:
        # Resolve real array_id for metrics storage
        real_array_id = _resolve_array_id(payload.array_id, source_ip)
        store_key = real_array_id or source_ip  # fallback to IP for metrics (non-critical)

        # Build metrics record
        record = {
            "ts": payload.ts or datetime.now().isoformat(),
            "source_ip": source_ip,
            "array_id": real_array_id or "",
        }
        
        # Extract known metrics fields
        extra = payload.dict(exclude={"type", "ts", "array_id"}, exclude_none=True)
        record.update(extra)
        
        # Store in memory keyed by real array_id when available
        if store_key not in _metrics_store:
            _metrics_store[store_key] = deque(maxlen=MAX_METRICS_PER_ARRAY)
        _metrics_store[store_key].append(record)
        
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
