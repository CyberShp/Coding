"""
Array management API endpoints.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..core.ssh_pool import get_ssh_pool, SSHPool
from ..db.database import get_db
from ..models.array import (
    ArrayModel, ArrayCreate, ArrayUpdate, ArrayResponse,
    ArrayStatus, ConnectionState
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/arrays", tags=["arrays"])

# In-memory status cache
_array_status_cache: Dict[str, ArrayStatus] = {}


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
    """Get all arrays"""
    result = await db.execute(select(ArrayModel))
    arrays = result.scalars().all()
    return arrays


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
    
    return status_obj


@router.post("/{array_id}/connect")
async def connect_array(
    array_id: str,
    password: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Connect to array"""
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
    
    # Ensure connection exists
    conn = ssh_pool.get_connection(array_id)
    if not conn:
        conn = ssh_pool.add_connection(
            array_id=array_id,
            host=array.host,
            port=array.port,
            username=array.username,
            password=password,
            key_path=array.key_path or None,
        )
    elif password:
        # Update password if provided
        conn.password = password
    
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
    
    # Check agent status
    exit_code, out, _ = conn.execute("test -d /opt/observation_points && echo 'deployed'")
    status_obj.agent_deployed = 'deployed' in out
    
    exit_code, out, _ = conn.execute("pgrep -f 'python.*observation_points'")
    status_obj.agent_running = exit_code == 0 and out.strip() != ''
    
    return {
        "status": "connected",
        "agent_deployed": status_obj.agent_deployed,
        "agent_running": status_obj.agent_running,
    }


@router.post("/{array_id}/disconnect")
async def disconnect_array(
    array_id: str,
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Disconnect from array"""
    ssh_pool.disconnect(array_id)
    
    # Update status
    status_obj = _get_array_status(array_id)
    status_obj.state = ConnectionState.DISCONNECTED
    
    return {"status": "disconnected"}


@router.post("/{array_id}/refresh")
async def refresh_array(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Refresh array status"""
    conn = ssh_pool.get_connection(array_id)
    
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )
    
    status_obj = _get_array_status(array_id)
    
    # Check agent status
    exit_code, out, _ = conn.execute("test -d /opt/observation_points && echo 'deployed'")
    status_obj.agent_deployed = 'deployed' in out
    
    exit_code, out, _ = conn.execute("pgrep -f 'python.*observation_points'")
    status_obj.agent_running = exit_code == 0 and out.strip() != ''
    
    # Get observer status from alerts.log
    config = get_config()
    content = conn.read_file(config.remote.log_path)
    
    if content:
        # Parse recent alerts
        alerts = []
        for line in content.strip().split('\n')[-50:]:
            try:
                alert = json.loads(line)
                alerts.append(alert)
            except Exception:
                pass
        
        status_obj.recent_alerts = alerts
        
        # Update observer status
        for alert in alerts:
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
    
    status_obj.last_refresh = datetime.now()
    
    return status_obj


@router.get("", response_model=List[ArrayStatus])
async def list_array_statuses(
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Get all array statuses"""
    result = await db.execute(select(ArrayModel))
    arrays = result.scalars().all()
    
    statuses = []
    for array in arrays:
        status_obj = _get_array_status(array.array_id)
        status_obj.name = array.name
        status_obj.host = array.host
        
        conn = ssh_pool.get_connection(array.array_id)
        if conn:
            status_obj.state = conn.state
            status_obj.last_error = conn.last_error
        
        statuses.append(status_obj)
    
    return statuses
