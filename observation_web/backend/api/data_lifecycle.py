"""
Data lifecycle API endpoints.

Handles:
- History import
- Archive management
- Sync state queries
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.data_lifecycle import get_lifecycle_manager, DataLifecycleManager
from ..core.ssh_pool import get_ssh_pool, SSHPool
from ..db.database import get_db
from ..models.lifecycle import (
    SyncState, ImportRequest, ImportResult,
    ArchiveConfig, ArchiveStats, LogFileInfo
)
from ..config import get_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/data", tags=["data-lifecycle"])


@router.get("/sync-state/{array_id}", response_model=Optional[SyncState])
async def get_sync_state(
    array_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get sync state for an array"""
    manager = get_lifecycle_manager()
    return await manager.get_sync_state(db, array_id)


@router.get("/log-files/{array_id}", response_model=List[LogFileInfo])
async def get_log_files(
    array_id: str,
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Get available log files from remote array"""
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(status_code=400, detail="Array not connected")
    
    config = get_config()
    log_dir = "/".join(config.remote.agent_log_path.rsplit("/", 1)[:-1]) or "/var/log/observation-points"
    
    manager = get_lifecycle_manager()
    manager.set_connection(conn)
    
    return await manager.get_remote_log_files(log_dir)


@router.post("/import/{array_id}", response_model=ImportResult)
async def import_history(
    array_id: str,
    request: ImportRequest,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Import historical alerts from remote array.
    
    Modes:
    - incremental: Import last N days (default)
    - full: Import all available log files
    - selective: Import specified log files
    """
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(status_code=400, detail="Array not connected")
    
    config = get_config()
    
    manager = get_lifecycle_manager()
    manager.set_connection(conn)
    
    return await manager.import_history(
        db,
        array_id=array_id,
        mode=request.mode,
        days=request.days,
        log_files=request.log_files,
        log_path=config.remote.agent_log_path
    )


@router.get("/archive/config", response_model=ArchiveConfig)
async def get_archive_config(
    db: AsyncSession = Depends(get_db),
):
    """Get archive configuration"""
    manager = get_lifecycle_manager()
    return await manager.get_archive_config(db)


@router.put("/archive/config", response_model=ArchiveConfig)
async def update_archive_config(
    config: ArchiveConfig,
    db: AsyncSession = Depends(get_db),
):
    """Update archive configuration"""
    manager = get_lifecycle_manager()
    return await manager.update_archive_config(db, config)


@router.post("/archive/run")
async def run_archive(
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger archive process"""
    manager = get_lifecycle_manager()
    result = await manager.archive_old_data(db)
    return {
        "success": True,
        "archived": result["archived"],
        "deleted": result["deleted"],
        "message": f"归档 {result['archived']} 条, 清理 {result['deleted']} 条"
    }


@router.get("/archive/stats", response_model=ArchiveStats)
async def get_archive_stats(
    db: AsyncSession = Depends(get_db),
):
    """Get archive statistics"""
    manager = get_lifecycle_manager()
    return await manager.get_archive_stats(db)


@router.get("/archive/query")
async def query_archive(
    array_id: Optional[str] = Query(None),
    year_month: Optional[str] = Query(None, description="Format: YYYY-MM"),
    limit: int = Query(500, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
):
    """Query archived alerts"""
    manager = get_lifecycle_manager()
    alerts = await manager.query_archive(db, array_id, year_month)
    return alerts[:limit]
