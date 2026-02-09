"""
Array management API endpoints.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Body, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..core.agent_deployer import AgentDeployer
from ..core.ssh_pool import get_ssh_pool, SSHPool
from ..core.system_alert import sys_error, sys_warning, sys_info
from ..db.database import get_db
from ..models.array import (
    ArrayModel, ArrayCreate, ArrayUpdate, ArrayResponse,
    ArrayStatus, ConnectionState
)


class BatchActionRequest(BaseModel):
    """Request model for batch operations"""
    array_ids: List[str]
    password: Optional[str] = None  # For batch connect

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/arrays", tags=["arrays"])

# In-memory status cache
_array_status_cache: Dict[str, ArrayStatus] = {}

# Track last sync position per array (line count of alerts.log)
_sync_positions: Dict[str, int] = {}


async def _get_array_or_404(array_id: str, db: AsyncSession) -> ArrayModel:
    """Verify array exists in DB, raise 404 if not found."""
    result = await db.execute(
        select(ArrayModel).where(ArrayModel.array_id == array_id)
    )
    arr = result.scalar_one_or_none()
    if not arr:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Array {array_id} not found"
        )
    return arr


def _get_array_status(array_id: str) -> ArrayStatus:
    """Get or create array status"""
    if array_id not in _array_status_cache:
        _array_status_cache[array_id] = ArrayStatus(
            array_id=array_id,
            name="",
            host="",
        )
    return _array_status_cache[array_id]


@router.get("", response_model=List[ArrayResponse])
async def list_arrays(
    db: AsyncSession = Depends(get_db),
):
    """Get all arrays (database records only, no connection state)"""
    result = await db.execute(select(ArrayModel))
    arrays = result.scalars().all()
    return arrays


@router.get("/statuses", response_model=List[ArrayStatus])
async def list_array_statuses(
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Get all array statuses with connection state"""
    from ..models.alert import AlertModel

    result = await db.execute(select(ArrayModel))
    arrays = result.scalars().all()
    
    statuses = []
    for array in arrays:
        status_obj = _get_array_status(array.array_id)
        status_obj.name = array.name
        status_obj.host = array.host
        status_obj.has_saved_password = bool(getattr(array, 'saved_password', ''))
        
        conn = ssh_pool.get_connection(array.array_id)
        if conn:
            status_obj.state = conn.state
            status_obj.last_error = conn.last_error
        
        # Derive observer_status from DB alerts if cache is empty
        if not status_obj.observer_status:
            stmt = (
                select(AlertModel.observer_name, AlertModel.level, AlertModel.message)
                .where(AlertModel.array_id == array.array_id)
                .order_by(AlertModel.timestamp.desc())
            )
            alert_rows = await db.execute(stmt)
            _level_rank = {'critical': 4, 'error': 3, 'warning': 2, 'info': 1}
            _obs_best = {}
            for row in alert_rows.all():
                obs_name = row.observer_name
                rank = _level_rank.get(row.level, 0)
                prev = _obs_best.get(obs_name)
                if prev is None or rank > prev[0]:
                    _obs_best[obs_name] = (rank, row.level, row.message or '')
            for obs_name, (rank, level, msg) in _obs_best.items():
                obs_status = 'ok'
                if level in ('error', 'critical'):
                    obs_status = 'error'
                elif level == 'warning':
                    obs_status = 'warning'
                status_obj.observer_status[obs_name] = {
                    'status': obs_status,
                    'message': msg[:100],
                }
        
        statuses.append(status_obj)
    
    return statuses


@router.post("/batch/{action}")
async def batch_action(
    action: str,
    request: BatchActionRequest,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Execute batch operations on multiple arrays.
    
    Supported actions:
    - connect: Connect to arrays (requires password)
    - disconnect: Disconnect from arrays
    - refresh: Refresh array status
    - deploy-agent: Deploy agent to arrays
    - start-agent: Start agent on arrays
    - stop-agent: Stop agent on arrays
    - restart-agent: Restart agent on arrays
    """
    valid_actions = ["connect", "disconnect", "refresh", "deploy-agent", "start-agent", "stop-agent", "restart-agent"]
    if action not in valid_actions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action. Must be one of: {valid_actions}"
        )
    
    if not request.array_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No arrays specified"
        )
    
    async def execute_single(array_id: str) -> Dict[str, Any]:
        """Execute action on a single array"""
        try:
            # Get array info
            result = await db.execute(
                select(ArrayModel).where(ArrayModel.array_id == array_id)
            )
            array = result.scalar()
            
            if not array:
                return {"array_id": array_id, "success": False, "error": "Array not found"}
            
            conn = ssh_pool.get_connection(array_id)
            config = get_config()
            
            if action == "connect":
                if not conn:
                    conn = ssh_pool.add_connection(
                        array_id=array_id,
                        host=array.host,
                        port=array.port,
                        username=array.username,
                        password=request.password,
                        key_path=array.key_path or None,
                    )
                elif request.password:
                    conn.password = request.password
                
                success = conn.connect()
                if success:
                    status_obj = _get_array_status(array_id)
                    status_obj.state = conn.state
                    return {"array_id": array_id, "success": True, "message": "Connected"}
                else:
                    return {"array_id": array_id, "success": False, "error": conn.last_error}
            
            elif action == "disconnect":
                ssh_pool.disconnect(array_id)
                status_obj = _get_array_status(array_id)
                status_obj.state = ConnectionState.DISCONNECTED
                return {"array_id": array_id, "success": True, "message": "Disconnected"}
            
            elif action == "refresh":
                if not conn or not conn.is_connected():
                    return {"array_id": array_id, "success": False, "error": "Array not connected"}
                
                deployer = AgentDeployer(conn, config)
                status_obj = _get_array_status(array_id)
                status_obj.agent_deployed = deployer.check_deployed()
                status_obj.agent_running = deployer.check_running()
                status_obj.last_refresh = datetime.now()
                
                return {"array_id": array_id, "success": True, "message": "Refreshed"}
            
            elif action == "deploy-agent":
                if not conn or not conn.is_connected():
                    return {"array_id": array_id, "success": False, "error": "Array not connected"}
                
                deployer = AgentDeployer(conn, config)
                result = deployer.deploy()
                if result.get("ok"):
                    status_obj = _get_array_status(array_id)
                    status_obj.agent_deployed = True
                    return {"array_id": array_id, "success": True, "message": "Agent deployed"}
                else:
                    return {"array_id": array_id, "success": False, "error": result.get("error")}
            
            elif action == "start-agent":
                if not conn or not conn.is_connected():
                    return {"array_id": array_id, "success": False, "error": "Array not connected"}
                
                deployer = AgentDeployer(conn, config)
                result = deployer.start_agent()
                if result.get("ok"):
                    status_obj = _get_array_status(array_id)
                    status_obj.agent_running = True
                    return {"array_id": array_id, "success": True, "message": "Agent started"}
                else:
                    return {"array_id": array_id, "success": False, "error": result.get("error")}
            
            elif action == "stop-agent":
                if not conn or not conn.is_connected():
                    return {"array_id": array_id, "success": False, "error": "Array not connected"}
                
                deployer = AgentDeployer(conn, config)
                result = deployer.stop_agent()
                if result.get("ok"):
                    status_obj = _get_array_status(array_id)
                    status_obj.agent_running = False
                    return {"array_id": array_id, "success": True, "message": "Agent stopped"}
                else:
                    return {"array_id": array_id, "success": False, "error": result.get("error")}
            
            elif action == "restart-agent":
                if not conn or not conn.is_connected():
                    return {"array_id": array_id, "success": False, "error": "Array not connected"}
                
                deployer = AgentDeployer(conn, config)
                result = deployer.restart_agent()
                if result.get("ok"):
                    status_obj = _get_array_status(array_id)
                    status_obj.agent_running = True
                    return {"array_id": array_id, "success": True, "message": "Agent restarted"}
                else:
                    return {"array_id": array_id, "success": False, "error": result.get("error")}
            
            return {"array_id": array_id, "success": False, "error": "Unknown action"}
            
        except Exception as e:
            sys_error("batch", f"Batch action {action} failed for {array_id}", {"error": str(e)})
            return {"array_id": array_id, "success": False, "error": str(e)}
    
    # Execute all actions concurrently
    results = await asyncio.gather(*[
        execute_single(array_id) for array_id in request.array_ids
    ])
    
    success_count = sum(1 for r in results if r.get("success"))
    sys_info("batch", f"Batch {action} completed", {
        "total": len(request.array_ids),
        "success": success_count,
        "failed": len(request.array_ids) - success_count
    })
    
    return {
        "action": action,
        "total": len(request.array_ids),
        "success_count": success_count,
        "results": results
    }


@router.post("", response_model=ArrayResponse, status_code=status.HTTP_201_CREATED)
async def create_array(
    array: ArrayCreate,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Create a new array"""
    # Generate unique ID
    array_id = f"arr_{uuid.uuid4().hex[:8]}"
    
    # Check if host already exists
    result = await db.execute(
        select(ArrayModel).where(ArrayModel.host == array.host)
    )
    if result.scalar():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Array with host {array.host} already exists"
        )
    
    # Create database record
    db_array = ArrayModel(
        array_id=array_id,
        name=array.name,
        host=array.host,
        port=array.port,
        username=array.username,
        key_path=array.key_path,
        folder=array.folder,
    )
    
    db.add(db_array)
    await db.commit()
    await db.refresh(db_array)
    
    # Initialize SSH connection (don't connect yet)
    ssh_pool.add_connection(
        array_id=array_id,
        host=array.host,
        port=array.port,
        username=array.username,
        password=array.password,
        key_path=array.key_path or None,
    )
    
    # Initialize status cache
    _array_status_cache[array_id] = ArrayStatus(
        array_id=array_id,
        name=array.name,
        host=array.host,
    )
    
    logger.info(f"Created array: {array.name} ({array.host})")
    return db_array


@router.get("/{array_id}", response_model=ArrayResponse)
async def get_array(
    array_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get array by ID"""
    result = await db.execute(
        select(ArrayModel).where(ArrayModel.array_id == array_id)
    )
    array = result.scalar()
    
    if not array:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Array {array_id} not found"
        )
    
    return array


@router.put("/{array_id}", response_model=ArrayResponse)
async def update_array(
    array_id: str,
    update: ArrayUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update array"""
    result = await db.execute(
        select(ArrayModel).where(ArrayModel.array_id == array_id)
    )
    array = result.scalar()
    
    if not array:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Array {array_id} not found"
        )
    
    # Update fields
    update_data = update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(array, field, value)
    
    await db.commit()
    await db.refresh(array)
    
    # Update status cache
    if array_id in _array_status_cache:
        if update.name:
            _array_status_cache[array_id].name = update.name
        if update.host:
            _array_status_cache[array_id].host = update.host
    
    return array


@router.delete("/{array_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_array(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Delete array"""
    result = await db.execute(
        select(ArrayModel).where(ArrayModel.array_id == array_id)
    )
    array = result.scalar()
    
    if not array:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Array {array_id} not found"
        )
    
    # Remove SSH connection
    ssh_pool.remove_connection(array_id)
    
    # Remove from status cache
    if array_id in _array_status_cache:
        del _array_status_cache[array_id]
    
    # Delete from database
    await db.delete(array)
    await db.commit()
    
    logger.info(f"Deleted array: {array_id}")


@router.get("/{array_id}/status", response_model=ArrayStatus)
async def get_array_status(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Get array runtime status"""
    # Get array info
    result = await db.execute(
        select(ArrayModel).where(ArrayModel.array_id == array_id)
    )
    array = result.scalar()
    
    if not array:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Array {array_id} not found"
        )
    
    # Get or create status
    status_obj = _get_array_status(array_id)
    status_obj.name = array.name
    status_obj.host = array.host
    
    # Get connection state
    conn = ssh_pool.get_connection(array_id)
    if conn:
        status_obj.state = conn.state
        status_obj.last_error = conn.last_error
    
    # If observer_status is empty, derive it from DB alerts
    if not status_obj.observer_status:
        from ..models.alert import AlertModel
        stmt = (
            select(AlertModel.observer_name, AlertModel.level, AlertModel.message)
            .where(AlertModel.array_id == array_id)
            .order_by(AlertModel.timestamp.desc())
        )
        alert_rows = await db.execute(stmt)
        _level_rank = {'critical': 4, 'error': 3, 'warning': 2, 'info': 1}
        _obs_best = {}  # track highest severity per observer
        for row in alert_rows.all():
            obs_name = row.observer_name
            level = row.level
            rank = _level_rank.get(level, 0)
            prev = _obs_best.get(obs_name)
            if prev is None or rank > prev[0]:
                _obs_best[obs_name] = (rank, level, row.message or '')
        for obs_name, (rank, level, msg) in _obs_best.items():
            obs_status = 'ok'
            if level in ('error', 'critical'):
                obs_status = 'error'
            elif level == 'warning':
                obs_status = 'warning'
            status_obj.observer_status[obs_name] = {
                'status': obs_status,
                'message': msg[:100],
            }
    
    return status_obj


@router.post("/{array_id}/connect")
async def connect_array(
    array_id: str,
    password: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Connect to array.
    
    密码策略：
    1. 如果提供了 password 参数，优先使用
    2. 如果未提供，自动使用数据库中已保存的密码
    3. 连接成功后，自动将密码保存到数据库（下次免密连接）
    """
    # Get array info
    result = await db.execute(
        select(ArrayModel).where(ArrayModel.array_id == array_id)
    )
    array = result.scalar()
    
    if not array:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Array {array_id} not found"
        )
    
    # 密码优先级：参数传入 > 数据库已保存
    effective_password = password or getattr(array, 'saved_password', '') or ''
    
    # Ensure connection exists
    conn = ssh_pool.get_connection(array_id)
    if not conn:
        conn = ssh_pool.add_connection(
            array_id=array_id,
            host=array.host,
            port=array.port,
            username=array.username,
            password=effective_password,
            key_path=array.key_path or None,
        )
    elif effective_password:
        # Update password if we have one
        conn.password = effective_password
    
    # Connect
    success = conn.connect()
    
    # Update status
    status_obj = _get_array_status(array_id)
    status_obj.state = conn.state
    status_obj.last_error = conn.last_error
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Connection failed: {conn.last_error}"
        )
    
    # 连接成功 → 保存密码到数据库（下次免密使用）
    if effective_password and (not array.saved_password or array.saved_password != effective_password):
        try:
            array.saved_password = effective_password
            await db.commit()
        except Exception:
            pass  # 保存密码失败不影响连接
    
    # Check agent status
    config = get_config()
    deployer = AgentDeployer(conn, config)
    status_obj.agent_deployed = deployer.check_deployed()
    status_obj.agent_running = deployer.check_running()

    if not status_obj.agent_deployed:
        return {
            "status": "connected",
            "agent_status": "not_deployed",
            "hint": "Agent 未部署，是否立即部署？",
            "agent_deployed": status_obj.agent_deployed,
            "agent_running": status_obj.agent_running,
            "has_saved_password": True,
        }

    return {
        "status": "connected",
        "agent_deployed": status_obj.agent_deployed,
        "agent_running": status_obj.agent_running,
        "has_saved_password": True,
    }


@router.post("/{array_id}/disconnect")
async def disconnect_array(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Disconnect from array"""
    await _get_array_or_404(array_id, db)
    ssh_pool.disconnect(array_id)
    
    # Update status
    status_obj = _get_array_status(array_id)
    status_obj.state = ConnectionState.DISCONNECTED
    
    return {"status": "disconnected"}


@router.post("/{array_id}/refresh")
async def refresh_array(
    array_id: str,
    full_sync: bool = Query(False, description="Force full sync instead of incremental"),
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Refresh array status and sync alerts incrementally.
    
    Uses tail-based incremental sync to avoid reading the entire alerts.log file.
    Only new lines since last sync are fetched and parsed.
    """
    await _get_array_or_404(array_id, db)
    from ..core.alert_store import get_alert_store
    from ..models.alert import AlertCreate, AlertLevel
    from .websocket import broadcast_alert
    
    conn = ssh_pool.get_connection(array_id)
    
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )
    
    status_obj = _get_array_status(array_id)
    
    # Check agent status
    config = get_config()
    deployer = AgentDeployer(conn, config)
    status_obj.agent_deployed = deployer.check_deployed()
    status_obj.agent_running = deployer.check_running()
    
    # Get detailed agent info
    agent_info = deployer.get_agent_status()
    status_obj.agent_running = agent_info.get("running", False)
    
    log_path = config.remote.agent_log_path
    new_alerts_count = 0
    
    try:
        # Step 1: Get total line count of alerts.log
        exit_code, total_str, _ = conn.execute(f"wc -l < {log_path} 2>/dev/null", timeout=5)
        if exit_code != 0:
            # File may not exist yet
            status_obj.last_refresh = datetime.now()
            return {
                "state": status_obj.state.value if hasattr(status_obj.state, 'value') else status_obj.state,
                "agent_deployed": status_obj.agent_deployed,
                "agent_running": status_obj.agent_running,
                "agent_pid": agent_info.get("pid"),
                "new_alerts_synced": 0,
                "observer_status": status_obj.observer_status,
                "last_refresh": status_obj.last_refresh.isoformat() if status_obj.last_refresh else None,
            }
        
        total_lines = int(total_str.strip())
        last_pos = _sync_positions.get(array_id, 0)
        
        # Reset position if full_sync or if file was truncated/rotated
        if full_sync or total_lines < last_pos:
            last_pos = 0
        
        new_count = total_lines - last_pos
        
        content = ""
        if new_count > 0:
            # Step 2: Only read new lines using tail
            # Cap at 500 lines per sync to avoid large reads
            read_count = min(new_count, 500)
            exit_code, content, _ = conn.execute(
                f"tail -n {read_count} {log_path} 2>/dev/null", timeout=10
            )
        
        if content and content.strip():
            parsed_alerts = []
            for line in content.strip().split('\n'):
                if not line.strip():
                    continue
                try:
                    alert = json.loads(line)
                    parsed_alerts.append(alert)
                except Exception:
                    pass
            
            if parsed_alerts:
                # Use hash-based dedup (much faster than DB query)
                alert_store = get_alert_store()
                existing_alerts = await alert_store.get_alerts(db, array_id=array_id, limit=100)
                existing_keys = set()
                for a in existing_alerts:
                    key = f"{a.timestamp.isoformat()}_{a.observer_name}_{a.message[:50]}"
                    existing_keys.add(key)
                
                new_alerts = []
                for alert in parsed_alerts:
                    timestamp_str = alert.get('timestamp', '')
                    if not timestamp_str:
                        continue
                    
                    dedup_key = f"{timestamp_str}_{alert.get('observer_name', '')}_{alert.get('message', '')[:50]}"
                    if dedup_key in existing_keys:
                        continue
                    existing_keys.add(dedup_key)
                    
                    try:
                        level_str = alert.get('level', 'info').lower()
                        level = AlertLevel(level_str) if level_str in [l.value for l in AlertLevel] else AlertLevel.INFO
                        
                        alert_create = AlertCreate(
                            array_id=array_id,
                            observer_name=alert.get('observer_name', 'unknown'),
                            level=level,
                            message=alert.get('message', ''),
                            details=alert.get('details', {}),
                            timestamp=datetime.fromisoformat(
                                timestamp_str.replace('Z', '+00:00').replace('+00:00', '')
                            ),
                        )
                        new_alerts.append(alert_create)
                    except Exception as e:
                        sys_error("arrays", f"Failed to parse alert", {"error": str(e)})
                
                if new_alerts:
                    new_alerts_count = await alert_store.create_alerts_batch(db, new_alerts)
                    sys_info("arrays", f"Synced {new_alerts_count} new alerts for {array_id}")
                    
                    for alert in new_alerts[-10:]:
                        await broadcast_alert({
                            'array_id': alert.array_id,
                            'observer_name': alert.observer_name,
                            'level': alert.level.value,
                            'message': alert.message,
                            'timestamp': alert.timestamp.isoformat(),
                        })
                
                # Update observer status from recent alerts
                for alert in parsed_alerts[-50:]:
                    observer = alert.get('observer_name', '')
                    level = alert.get('level', 'info')
                    message = alert.get('message', '')
                    
                    if observer:
                        if level in ('error', 'critical'):
                            status_obj.observer_status[observer] = {
                                'status': 'error',
                                'message': message[:100],
                            }
                        elif level == 'warning':
                            if observer not in status_obj.observer_status or \
                               status_obj.observer_status[observer].get('status') != 'error':
                                status_obj.observer_status[observer] = {
                                    'status': 'warning',
                                    'message': message[:100],
                                }
        
        # Update sync position
        _sync_positions[array_id] = total_lines
        
    except Exception as e:
        sys_error("arrays", f"Refresh failed for {array_id}", {"error": str(e)})
    
    # Also sync traffic data
    try:
        from ..core.traffic_store import get_traffic_store
        traffic_path = config.remote.agent_log_path.replace('alerts.log', 'traffic.jsonl')
        exit_code_t, traffic_content, _ = conn.execute(
            f"tail -n 200 {traffic_path} 2>/dev/null", timeout=10
        )
        if exit_code_t == 0 and traffic_content and traffic_content.strip():
            traffic_records = []
            for line in traffic_content.strip().split('\n'):
                line = line.strip()
                if not line:
                    continue
                try:
                    traffic_records.append(json.loads(line))
                except Exception:
                    pass
            if traffic_records:
                traffic_store = get_traffic_store()
                await traffic_store.ingest(db, array_id, traffic_records)
    except Exception as e:
        logger.debug(f"Traffic sync during refresh: {e}")

    status_obj.last_refresh = datetime.now()
    
    # Return slim response (no recent_alerts blob)
    return {
        "state": status_obj.state.value if hasattr(status_obj.state, 'value') else status_obj.state,
        "agent_deployed": status_obj.agent_deployed,
        "agent_running": status_obj.agent_running,
        "agent_pid": agent_info.get("pid"),
        "new_alerts_synced": new_alerts_count,
        "observer_status": status_obj.observer_status,
        "last_refresh": status_obj.last_refresh.isoformat() if status_obj.last_refresh else None,
    }


@router.get("/{array_id}/metrics")
async def get_array_metrics(
    array_id: str,
    minutes: int = Query(60, description="Time range in minutes"),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Get performance metrics (CPU, memory) from the remote array.
    
    Reads from the agent's metrics.jsonl file which records time-series data.
    Also checks for pushed metrics from the ingest endpoint.
    """
    from .ingest import get_metrics_for_ip
    
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )
    
    config = get_config()
    metrics_path = config.remote.agent_log_path.replace('alerts.log', 'metrics.jsonl')
    
    # Calculate how many lines to fetch (roughly 6 per minute if 10s interval)
    lines_needed = min(minutes * 6, 2000)
    
    metrics = []
    
    # Try to read from remote metrics.jsonl
    exit_code, content, _ = conn.execute(
        f"tail -n {lines_needed} {metrics_path} 2>/dev/null", timeout=10
    )
    
    if exit_code == 0 and content and content.strip():
        for line in content.strip().split('\n'):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                metrics.append(record)
            except Exception:
                pass
    
    # Also check for pushed metrics (by host IP)
    # Find the host IP for this array
    for aid, conn_obj in ssh_pool._connections.items():
        if aid == array_id:
            pushed = get_metrics_for_ip(conn_obj.host, minutes)
            if pushed:
                metrics.extend(pushed)
            break
    
    # Sort by timestamp
    metrics.sort(key=lambda m: m.get('ts', ''))
    
    # Filter to requested time range
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat()
    metrics = [m for m in metrics if m.get('ts', '') >= cutoff]
    
    return {
        "array_id": array_id,
        "minutes": minutes,
        "count": len(metrics),
        "metrics": metrics,
    }


@router.post("/{array_id}/deploy-agent")
async def deploy_agent(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Deploy observation_points agent to array"""
    await _get_array_or_404(array_id, db)
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )

    config = get_config()
    deployer = AgentDeployer(conn, config)
    result = deployer.deploy()
    if not result.get("ok"):
        sys_error(
            "arrays",
            f"Agent deploy failed for array {array_id}",
            {"array_id": array_id, "error": result.get("error")}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Deploy failed")
        )

    status_obj = _get_array_status(array_id)
    status_obj.agent_deployed = deployer.check_deployed()
    status_obj.agent_running = deployer.check_running()
    sys_info("arrays", f"Agent deployed for array {array_id}", {"array_id": array_id})

    return result


@router.post("/{array_id}/start-agent")
async def start_agent(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Start observation_points agent on array"""
    await _get_array_or_404(array_id, db)
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )

    config = get_config()
    deployer = AgentDeployer(conn, config)
    result = deployer.start_agent()
    if not result.get("ok"):
        sys_error(
            "arrays",
            f"Agent start failed for array {array_id}",
            {"array_id": array_id, "error": result.get("error")}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Start failed")
        )

    status_obj = _get_array_status(array_id)
    status_obj.agent_running = deployer.check_running()
    status_obj.agent_deployed = deployer.check_deployed()
    sys_info("arrays", f"Agent started for array {array_id}", {"array_id": array_id})

    return result


@router.post("/{array_id}/stop-agent")
async def stop_agent(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Stop observation_points agent on array"""
    await _get_array_or_404(array_id, db)
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )

    config = get_config()
    deployer = AgentDeployer(conn, config)
    result = deployer.stop_agent()
    if not result.get("ok"):
        sys_error(
            "arrays",
            f"Agent stop failed for array {array_id}",
            {"array_id": array_id, "error": result.get("error")}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Stop failed")
        )

    status_obj = _get_array_status(array_id)
    status_obj.agent_running = deployer.check_running()
    status_obj.agent_deployed = deployer.check_deployed()
    sys_info("arrays", f"Agent stopped for array {array_id}", {"array_id": array_id})

    return result


@router.post("/{array_id}/restart-agent")
async def restart_agent(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Restart observation_points agent on array"""
    await _get_array_or_404(array_id, db)
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )

    config = get_config()
    deployer = AgentDeployer(conn, config)
    result = deployer.restart_agent()
    if not result.get("ok"):
        sys_error(
            "arrays",
            f"Agent restart failed for array {array_id}",
            {"array_id": array_id, "error": result.get("error")}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Restart failed")
        )

    status_obj = _get_array_status(array_id)
    status_obj.agent_running = deployer.check_running()
    status_obj.agent_deployed = deployer.check_deployed()
    sys_info("arrays", f"Agent restarted for array {array_id}", {"array_id": array_id})

    return result


# Common log file paths for quick selection
COMMON_LOG_PATHS = [
    "/var/log/messages",
    "/var/log/syslog",
    "/var/log/dmesg",
    "/var/log/auth.log",
    "/var/log/secure",
    "/var/log/kern.log",
]


@router.get("/{array_id}/logs")
async def get_logs(
    array_id: str,
    file_path: str = "/var/log/messages",
    lines: int = 100,
    keyword: Optional[str] = None,
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Get log content from remote array.
    
    Args:
        array_id: Array identifier
        file_path: Path to log file on remote system
        lines: Number of lines to retrieve (from tail)
        keyword: Optional keyword to filter (grep)
    
    Returns:
        Log content and metadata
    """
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )
    
    # Build command - using sudo to read system logs
    if keyword:
        # tail + grep with keyword
        cmd = f"sudo tail -n {lines * 3} {file_path} 2>/dev/null | grep -i '{keyword}' | tail -n {lines}"
    else:
        cmd = f"sudo tail -n {lines} {file_path} 2>/dev/null"
    
    try:
        exit_code, output, error = conn.execute(cmd, timeout=10)
        
        if error and "permission denied" in error.lower():
            # Try without sudo
            if keyword:
                cmd = f"tail -n {lines * 3} {file_path} 2>/dev/null | grep -i '{keyword}' | tail -n {lines}"
            else:
                cmd = f"tail -n {lines} {file_path} 2>/dev/null"
            exit_code, output, error = conn.execute(cmd, timeout=10)
        
        # Get file info
        stat_cmd = f"stat --format='%s %Y' {file_path} 2>/dev/null || stat -f '%z %m' {file_path} 2>/dev/null"
        _, stat_output, _ = conn.execute(stat_cmd, timeout=5)
        
        file_size = 0
        modified_at = None
        if stat_output and stat_output.strip():
            parts = stat_output.strip().split()
            if len(parts) >= 2:
                try:
                    file_size = int(parts[0])
                    modified_at = datetime.fromtimestamp(int(parts[1])).isoformat()
                except (ValueError, TypeError):
                    pass
        
        return {
            "content": output or "",
            "file_path": file_path,
            "lines_returned": len((output or "").strip().split("\n")) if output else 0,
            "file_size": file_size,
            "modified_at": modified_at,
            "keyword": keyword,
        }
        
    except Exception as e:
        sys_error("logs", f"Failed to read logs from {array_id}", {"file": file_path, "error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read log file: {str(e)}"
        )


@router.get("/{array_id}/log-files")
async def list_log_files(
    array_id: str,
    directory: str = "/var/log",
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    List available log files on remote array.
    
    Args:
        array_id: Array identifier
        directory: Directory to list log files from
    
    Returns:
        List of log files with metadata
    """
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )
    
    # List files with details
    cmd = f"find {directory} -maxdepth 2 -type f \\( -name '*.log' -o -name 'messages*' -o -name 'syslog*' \\) 2>/dev/null | head -50"
    _, output, _ = conn.execute(cmd, timeout=10)
    
    files = []
    if output:
        for path in output.strip().split("\n"):
            path = path.strip()
            if not path:
                continue
            
            # Get file info
            stat_cmd = f"stat --format='%s %Y' {path} 2>/dev/null || stat -f '%z %m' {path} 2>/dev/null"
            _, stat_output, _ = conn.execute(stat_cmd, timeout=5)
            
            size = 0
            modified = None
            if stat_output and stat_output.strip():
                parts = stat_output.strip().split()
                if len(parts) >= 2:
                    try:
                        size = int(parts[0])
                        modified = datetime.fromtimestamp(int(parts[1])).isoformat()
                    except (ValueError, TypeError):
                        pass
            
            files.append({
                "path": path,
                "name": path.split("/")[-1],
                "size": size,
                "size_human": _format_bytes(size),
                "modified": modified,
            })
    
    # Sort by modification time (newest first)
    files.sort(key=lambda x: x.get("modified") or "", reverse=True)
    
    return {
        "directory": directory,
        "files": files,
        "common_paths": COMMON_LOG_PATHS,
    }


def _format_bytes(size: int) -> str:
    """Format bytes to human readable string"""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


@router.get("/{array_id}/agent-config")
async def get_agent_config(
    array_id: str,
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Get Agent configuration from remote array.
    
    Returns the current config.json content from the deployed Agent.
    """
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )
    
    config = get_config()
    # Get agent deploy path (e.g., /home/permitdir/observation_points)
    agent_path = config.remote.agent_deploy_path
    config_path = f"{agent_path}/config.json"
    
    try:
        content = conn.read_file(config_path)
        if not content:
            return {
                "exists": False,
                "config": None,
                "config_path": config_path,
                "error": "Config file not found or empty"
            }
        
        # Parse JSON
        try:
            config_data = json.loads(content)
            return {
                "exists": True,
                "config": config_data,
                "config_path": config_path,
                "raw": content,
            }
        except json.JSONDecodeError as e:
            return {
                "exists": True,
                "config": None,
                "config_path": config_path,
                "raw": content,
                "error": f"Invalid JSON: {str(e)}"
            }
            
    except Exception as e:
        sys_error("agent-config", f"Failed to read agent config from {array_id}", {"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read config: {str(e)}"
        )


@router.put("/{array_id}/agent-config")
async def update_agent_config(
    array_id: str,
    config_data: Dict[str, Any] = Body(...),
    restart_agent_flag: bool = Body(False, alias="restart_agent"),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Update Agent configuration on remote array.
    
    Writes the config to config.json and optionally restarts the Agent.
    """
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )
    
    config = get_config()
    agent_path = config.remote.agent_deploy_path
    config_path = f"{agent_path}/config.json"
    
    try:
        # Validate JSON
        config_json = json.dumps(config_data, indent=2, ensure_ascii=False)
        
        # Backup existing config
        backup_cmd = f"cp {config_path} {config_path}.bak 2>/dev/null || true"
        conn.execute(backup_cmd)
        
        # Write new config using base64 to avoid shell escaping issues
        import base64
        encoded = base64.b64encode(config_json.encode('utf-8')).decode('ascii')
        write_cmd = f"echo '{encoded}' | base64 -d > {config_path}"
        
        exit_code, output, error = conn.execute(write_cmd)
        if exit_code != 0:
            raise Exception(f"Write failed: {error}")
        
        # Verify the write
        verify_content = conn.read_file(config_path)
        if not verify_content:
            raise Exception("Failed to verify config write")
        
        result = {
            "success": True,
            "config_path": config_path,
            "message": "Configuration updated successfully"
        }
        
        # Optionally restart agent
        if restart_agent_flag:
            deployer = AgentDeployer(conn, config)
            restart_result = deployer.restart_agent()
            result["agent_restarted"] = restart_result.get("ok", False)
            if not restart_result.get("ok"):
                result["restart_error"] = restart_result.get("error")
        
        sys_info("agent-config", f"Updated agent config for {array_id}", {
            "restart": restart_agent_flag
        })
        
        return result
        
    except Exception as e:
        sys_error("agent-config", f"Failed to update agent config for {array_id}", {"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update config: {str(e)}"
        )


@router.post("/{array_id}/agent-config/restore")
async def restore_agent_config(
    array_id: str,
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Restore Agent configuration from backup.
    """
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )
    
    config = get_config()
    agent_path = config.remote.agent_deploy_path
    config_path = f"{agent_path}/config.json"
    backup_path = f"{config_path}.bak"
    
    try:
        # Check if backup exists
        check_cmd = f"test -f {backup_path} && echo 'exists'"
        _, output, _ = conn.execute(check_cmd)
        
        if "exists" not in (output or ""):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No backup file found"
            )
        
        # Restore from backup
        restore_cmd = f"cp {backup_path} {config_path}"
        exit_code, output, error = conn.execute(restore_cmd)
        
        if exit_code != 0:
            raise Exception(f"Restore failed: {error}")
        
        sys_info("agent-config", f"Restored agent config for {array_id}")
        
        return {
            "success": True,
            "message": "Configuration restored from backup"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        sys_error("agent-config", f"Failed to restore agent config for {array_id}", {"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restore config: {str(e)}"
        )
