"""
Port traffic data API.

Endpoints:
- GET  /api/traffic/{array_id}/ports      — list ports with recent traffic data
- GET  /api/traffic/{array_id}/data       — query traffic data for a port
- POST /api/traffic/{array_id}/sync       — sync traffic.jsonl from agent
- GET  /api/traffic/{array_id}/diagnostic — get traffic collection diagnostic info
"""

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..core.ssh_pool import get_ssh_pool, SSHPool
from ..core.traffic_store import get_traffic_store
from ..core.system_alert import sys_error, sys_info
from ..db.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/traffic", tags=["traffic"])


class TrafficDiagnostic(BaseModel):
    """Traffic collection diagnostic information"""
    array_id: str
    has_rdma: bool = False
    has_toe: bool = False
    rdma_devices: List[Dict[str, Any]] = []
    toe_ports: List[str] = []
    detected_protocol: str = "unknown"
    recommended_mode: str = "auto"
    available_modes: List[str] = ["auto", "ethtool", "sysfs", "rdma", "toe", "command"]
    notes: List[str] = []


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


@router.get("/{array_id}/diagnostic", response_model=TrafficDiagnostic)
async def get_traffic_diagnostic(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Get traffic collection diagnostic information.

    Detects RDMA/RoCE devices, TOE offload capabilities, and recommends
    the best collection mode for the array.
    """
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected",
        )

    result = TrafficDiagnostic(array_id=array_id)
    notes = []

    try:
        # Check for RDMA/InfiniBand devices
        exit_code, rdma_output, _ = conn.execute(
            "ls -la /sys/class/infiniband/ 2>/dev/null | grep -v '^total'", timeout=10
        )
        if exit_code == 0 and rdma_output and rdma_output.strip():
            result.has_rdma = True
            for line in rdma_output.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 9:
                    device_name = parts[-1]
                    if device_name not in ('.', '..'):
                        result.rdma_devices.append({
                            'name': device_name,
                            'type': 'infiniband',
                        })

        # Get RDMA device details
        if result.has_rdma:
            for dev in result.rdma_devices:
                dev_name = dev['name']
                exit_code, link_layer, _ = conn.execute(
                    f"cat /sys/class/infiniband/{dev_name}/ports/1/link_layer 2>/dev/null",
                    timeout=5
                )
                if exit_code == 0 and link_layer:
                    dev['link_layer'] = link_layer.strip()
                    if link_layer.strip() == 'Ethernet':
                        dev['type'] = 'roce'
                        notes.append(f"检测到 RoCE 设备: {dev_name}")
                    else:
                        notes.append(f"检测到 InfiniBand 设备: {dev_name}")

        # Check for TOE support
        exit_code, interfaces, _ = conn.execute(
            "ls /sys/class/net/ | grep -v lo", timeout=5
        )
        if exit_code == 0 and interfaces:
            for iface in interfaces.strip().split('\n'):
                iface = iface.strip()
                if not iface:
                    continue
                exit_code, toe_output, _ = conn.execute(
                    f"ethtool -k {iface} 2>/dev/null | grep -E 'tcp-segmentation-offload|large-receive-offload'",
                    timeout=5
                )
                if exit_code == 0 and toe_output:
                    if ': on' in toe_output:
                        result.has_toe = True
                        result.toe_ports.append(iface)

        if result.toe_ports:
            notes.append(f"检测到 TOE offload 端口: {', '.join(result.toe_ports[:5])}")

        # Determine recommended mode and detected protocol
        if result.has_rdma and result.rdma_devices:
            result.recommended_mode = "rdma"
            result.detected_protocol = "rdma" if any(
                d.get('link_layer') != 'Ethernet' for d in result.rdma_devices
            ) else "roce"
            notes.append("建议使用 rdma 模式采集，可获取绕过内核协议栈的 RDMA/RoCE 流量")
        elif result.has_toe:
            result.recommended_mode = "toe"
            result.detected_protocol = "toe"
            notes.append("检测到 TOE offload，建议使用 toe 模式以获取更完整的统计")
        else:
            result.recommended_mode = "auto"
            result.detected_protocol = "ethernet"
            notes.append("未检测到特殊协议，使用标准 ethtool/sysfs 采集即可")

        # Check current traffic data protocol info
        store = get_traffic_store()
        ports_data = await store.get_ports(db, array_id)
        if ports_data:
            protocols = set()
            for p in ports_data:
                if isinstance(p, dict) and 'protocol' in p:
                    protocols.add(p['protocol'])
            if protocols:
                notes.append(f"当前数据中检测到的协议: {', '.join(protocols)}")

        result.notes = notes

    except Exception as e:
        logger.warning(f"Traffic diagnostic failed for {array_id}: {e}")
        result.notes = [f"诊断过程中出现错误: {str(e)}"]

    return result


@router.get("/{array_id}/mode-info")
async def get_traffic_mode_info(
    array_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get recent traffic data with mode and protocol information.

    Returns the last few data points with their collection mode and protocol type.
    """
    store = get_traffic_store()

    # Get recent data to check mode/protocol
    ports = await store.get_ports(db, array_id)
    result = {
        "array_id": array_id,
        "ports": [],
        "modes_detected": set(),
        "protocols_detected": set(),
    }

    for port_info in ports[:10]:  # Limit to first 10 ports
        port_name = port_info if isinstance(port_info, str) else port_info.get('port', '')
        data = await store.query(db, array_id, port_name, minutes=5)

        if data:
            latest = data[-1] if data else {}
            mode = latest.get('mode', 'unknown')
            protocol = latest.get('protocol', 'unknown')
            result["modes_detected"].add(mode)
            result["protocols_detected"].add(protocol)
            result["ports"].append({
                "port": port_name,
                "mode": mode,
                "protocol": protocol,
                "latest_tx_rate_bps": latest.get('tx_rate_bps', 0),
                "latest_rx_rate_bps": latest.get('rx_rate_bps', 0),
            })

    result["modes_detected"] = list(result["modes_detected"])
    result["protocols_detected"] = list(result["protocols_detected"])

    return result
