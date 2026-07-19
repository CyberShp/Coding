"""
Data ingestion API - receives pushed data from remote agents.

Supports two data types:
- alert: Alert data pushed from agent's Reporter
- metrics: Performance metrics (CPU, memory, etc.)
"""

import json
import logging
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.system_alert import sys_info, sys_error
from ..db.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ingest"])

# In-memory metrics store (per array, keyed by source IP or array_id)
# Each entry stores a deque of recent metrics (last 24 hours worth)
MAX_METRICS_PER_ARRAY = 8640  # 24h * 60min * 6 (every 10s) = ~8640 points per day
_metrics_store: Dict[str, deque] = {}

# Last time each array pushed data (monotonic-ish wall clock). Used by the SSH
# alert-sync loop to skip the redundant pull for arrays whose push channel is
# active (both read the same alerts.log).
_last_push_at: Dict[str, float] = {}

# Downsample gate for DB persistence of metrics. Metrics arrive at high
# frequency (~every 10s); persisting every point would hammer SQLite. We keep
# the in-memory deque for fast recent lookups and additionally persist at most
# one row per array per ``METRIC_PERSIST_INTERVAL_S`` seconds.
METRIC_PERSIST_INTERVAL_S = 60.0
_last_persist_at: Dict[str, float] = {}


def mark_pushed(array_id: str) -> None:
    """Record that *array_id* just pushed data."""
    if array_id:
        _last_push_at[array_id] = time.time()


def get_last_push_at(array_id: str) -> float:
    """Wall-clock time of the last push for *array_id* (0.0 if never)."""
    return _last_push_at.get(array_id, 0.0)


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
    model_config = ConfigDict(extra="allow")


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


async def touch_heartbeat(db: AsyncSession, array_id: str) -> None:
    """Stamp arrays.last_heartbeat_at with a fresh collection signal.

    This is the single writer of last_heartbeat_at.  It must be called whenever
    we get positive evidence that collection is alive — an agent HTTP push here,
    or a successful SSH pull in array_alert_sync.  Without it the health window
    never sees a fresh signal and every running array is stuck at
    degraded / no_heartbeat (which is what the frontend was papering over).
    """
    if not array_id:
        return
    from sqlalchemy import update
    from ..models.array import ArrayModel
    try:
        await db.execute(
            update(ArrayModel)
            .where(ArrayModel.array_id == array_id)
            .values(last_heartbeat_at=datetime.now())
        )
    except Exception:
        logger.debug("heartbeat touch failed for %s", array_id, exc_info=True)


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
        return await _handle_metrics(payload, source_ip, db)
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
                await _handle_metrics(payload, source_ip, db)
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

        mark_pushed(real_array_id)

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

        # Dedup: push and SSH-pull read the SAME alerts.log line, so the same
        # alert can arrive via both paths (mixed mode). Skip if an identical one
        # (same array/observer/timestamp/message) already exists.
        from sqlalchemy import select as _select
        from ..models.alert import AlertModel as _AlertModel
        dup = await db.execute(
            _select(_AlertModel.id).where(
                _AlertModel.array_id == real_array_id,
                _AlertModel.observer_name == alert_create.observer_name,
                _AlertModel.timestamp == timestamp,
                _AlertModel.message == alert_create.message,
            ).limit(1)
        )
        if dup.scalar_one_or_none() is not None:
            await touch_heartbeat(db, real_array_id)
            return {"ok": True, "message": "Duplicate alert skipped", "array_id": real_array_id}

        db_alert = await alert_store.create_alert(db, alert_create)

        # Push is positive evidence the agent is alive and collecting.
        await touch_heartbeat(db, real_array_id)

        # Broadcast via WebSocket (include id for AI auto-translation)
        await broadcast_alert({
            'id': db_alert.id,
            'array_id': alert_create.array_id,
            'observer_name': alert_create.observer_name,
            'level': alert_create.level.value,
            'message': alert_create.message,
            'timestamp': alert_create.timestamp.isoformat(),
            'created_at': db_alert.created_at.isoformat() if db_alert.created_at else None,
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


async def _handle_metrics(payload: IngestPayload, source_ip: str, db: AsyncSession = None):
    """Process incoming metrics from agent push"""
    try:
        # Resolve real array_id for metrics storage
        real_array_id = _resolve_array_id(payload.array_id, source_ip)
        store_key = real_array_id or source_ip  # fallback to IP for metrics (non-critical)
        if real_array_id:
            mark_pushed(real_array_id)

        # Build metrics record
        record = {
            "ts": payload.ts or datetime.now().isoformat(),
            "source_ip": source_ip,
            "array_id": real_array_id or "",
        }
        
        # Extract known metrics fields
        extra = payload.model_dump(exclude={"type", "ts", "array_id"}, exclude_none=True)
        record.update(extra)
        
        # Store in memory keyed by real array_id when available
        if store_key not in _metrics_store:
            _metrics_store[store_key] = deque(maxlen=MAX_METRICS_PER_ARRAY)
        _metrics_store[store_key].append(record)

        # Downsampled persistence: only write to DB when we have a real array_id
        # and a live session, and at most once per METRIC_PERSIST_INTERVAL_S per
        # array (protects SQLite from high-frequency metric pushes).
        if db is not None and real_array_id:
            await _persist_metric_sample(db, real_array_id, record)

        # Metrics push is also a liveness signal for the agent.
        if db is not None and real_array_id:
            await touch_heartbeat(db, real_array_id)

        return {"ok": True}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _parse_ts(value: Any) -> datetime:
    """Best-effort parse of a metric timestamp into a naive datetime."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(
                value.replace("Z", "+00:00").replace("+00:00", "")
            )
        except Exception:
            pass
    return datetime.now()


async def _persist_metric_sample(db: AsyncSession, array_id: str, record: Dict) -> None:
    """Persist a downsampled metric sample, rate-limited per array.

    Writes at most one row per METRIC_PERSIST_INTERVAL_S seconds per array_id.
    Failures are swallowed (metrics persistence is non-critical) so a DB hiccup
    never breaks the ingest path.
    """
    now = time.time()
    last = _last_persist_at.get(array_id, 0.0)
    if now - last < METRIC_PERSIST_INTERVAL_S:
        return
    _last_persist_at[array_id] = now

    try:
        from ..models.metric_sample import MetricSampleModel

        ts = _parse_ts(record.get("ts"))
        # Everything except the promoted columns goes into extra as JSON.
        promoted = {"ts", "cpu0", "mem_used_mb", "mem_total_mb", "array_id", "source_ip"}
        extra = {k: v for k, v in record.items() if k not in promoted}
        db.add(MetricSampleModel(
            array_id=array_id,
            ts=ts,
            cpu0=record.get("cpu0"),
            mem_used_mb=record.get("mem_used_mb"),
            mem_total_mb=record.get("mem_total_mb"),
            extra=json.dumps(extra) if extra else None,
        ))
        await db.flush()
    except Exception:
        # Roll back so the surrounding request (heartbeat commit) stays clean,
        # and allow a retry on the next window.
        _last_persist_at[array_id] = last
        logger.debug("metric sample persist failed for %s", array_id, exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass


async def get_metrics_from_db(
    db: AsyncSession, array_id: str, minutes: int = 60
) -> List[Dict]:
    """Read persisted metric samples for *array_id* within the last *minutes*.

    Returns records shaped like the in-memory store (ts as ISO string plus the
    flattened metric fields), ordered by ts ascending. Empty list if none.
    """
    from datetime import timedelta
    from sqlalchemy import select as _select
    from ..models.metric_sample import MetricSampleModel

    cutoff = datetime.now() - timedelta(minutes=minutes)
    result = await db.execute(
        _select(MetricSampleModel)
        .where(
            MetricSampleModel.array_id == array_id,
            MetricSampleModel.ts >= cutoff,
        )
        .order_by(MetricSampleModel.ts.asc())
    )
    rows = result.scalars().all()

    out: List[Dict] = []
    for row in rows:
        rec: Dict[str, Any] = {
            "ts": row.ts.isoformat() if row.ts else None,
            "array_id": row.array_id,
        }
        if row.cpu0 is not None:
            rec["cpu0"] = row.cpu0
        if row.mem_used_mb is not None:
            rec["mem_used_mb"] = row.mem_used_mb
        if row.mem_total_mb is not None:
            rec["mem_total_mb"] = row.mem_total_mb
        if row.extra:
            try:
                rec.update(json.loads(row.extra))
            except Exception:
                pass
        out.append(rec)
    return out


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
