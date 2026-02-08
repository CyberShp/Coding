"""
Port traffic data API.

Endpoints:
- GET  /api/traffic/{array_id}/ports   — list ports with recent traffic data
- GET  /api/traffic/{array_id}/data    — query traffic data for a port
- POST /api/traffic/{array_id}/sync    — sync traffic.jsonl from agent
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..core.ssh_pool import get_ssh_pool, SSHPool
from ..core.traffic_store import get_traffic_store
from ..core.system_alert import sys_error, sys_info
from ..db.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/traffic", tags=["traffic"])


@router.get("/{array_id}/ports")
async def get_traffic_ports(
    array_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get list of ports with recent traffic data for an array."""
    store = get_traffic_store()
    ports = await store.get_ports(db, array_id)
    return {"array_id": array_id, "ports": ports}


@router.get("/{array_id}/data")
async def get_traffic_data(
    array_id: str,
    port: str = Query(..., description="Port name"),
    minutes: int = Query(30, ge=1, le=120, description="Time range (1-120 min)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Query traffic data for a specific port.

    Returns time-series data points with TX/RX rates.
    Max 120 minutes (2 hours).
    """
    store = get_traffic_store()
    data = await store.query(db, array_id, port, minutes)
    return {
        "array_id": array_id,
        "port": port,
        "minutes": minutes,
        "count": len(data),
        "data": data,
    }


@router.post("/{array_id}/sync")
async def sync_traffic(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Sync traffic.jsonl from agent via SSH.

    Reads new lines from the agent's traffic.jsonl file and ingests them
    into the local database.
    """
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected",
        )

    config = get_config()
    traffic_path = config.remote.agent_log_path.replace(
        'alerts.log', 'traffic.jsonl'
    )

    try:
        # Read last 200 lines (covers ~33 min at 30s interval with 48 ports)
        exit_code, content, _ = conn.execute(
            f"tail -n 200 {traffic_path} 2>/dev/null", timeout=10
        )

        if exit_code != 0 or not content or not content.strip():
            return {
                "array_id": array_id,
                "ingested": 0,
                "message": "No traffic data on agent",
            }

        records = []
        for line in content.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                records.append(rec)
            except json.JSONDecodeError:
                continue

        store = get_traffic_store()
        count = await store.ingest(db, array_id, records)

        return {
            "array_id": array_id,
            "ingested": count,
            "total_lines": len(records),
        }

    except Exception as e:
        sys_error("traffic", f"Traffic sync failed for {array_id}", {"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Traffic sync failed: {str(e)}",
        )
