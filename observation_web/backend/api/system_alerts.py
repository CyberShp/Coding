"""
System alerts API endpoints.

Provides access to backend error logs and system alerts.
"""

import sys
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from ..core.ssh_pool import get_ssh_pool, SSHPool
from ..core.system_alert import (
    AlertLevel,
    get_system_alert_store,
)

router = APIRouter(prefix="/system-alerts", tags=["system-alerts"])


@router.get("")
async def list_alerts(
    level: Optional[str] = Query(None, description="Filter by alert level"),
    module: Optional[str] = Query(None, description="Filter by module name"),
    limit: int = Query(100, le=500, description="Maximum number of alerts"),
):
    """Get system alerts with optional filtering"""
    store = get_system_alert_store()
    
    alert_level = None
    if level:
        try:
            alert_level = AlertLevel(level.lower())
        except ValueError:
            pass
    
    return store.get_all(level=alert_level, module=module, limit=limit)


@router.get("/stats")
async def get_stats():
    """Get alert statistics"""
    store = get_system_alert_store()
    return store.get_stats()


@router.delete("")
async def clear_alerts():
    """Clear all alerts"""
    store = get_system_alert_store()
    store.clear()
    return {"ok": True, "message": "Alerts cleared"}


@router.get("/debug")
async def get_debug_info(
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Get system debug information.
    
    Returns runtime state for troubleshooting:
    - SSH connection states
    - Memory cache status
    - System info
    """
    from ..api.arrays import _array_status_cache
    
    # SSH connection states
    ssh_states = {}
    for array_id, conn in ssh_pool._connections.items():
        ssh_states[array_id] = {
            "host": conn.host,
            "port": conn.port,
            "username": conn.username,
            "state": conn.state.value,
            "last_error": conn.last_error,
            "has_password": bool(conn.password),
            "has_key": bool(conn.key_path),
        }
    
    # Array status cache
    status_cache = {}
    for array_id, status in _array_status_cache.items():
        status_cache[array_id] = {
            "name": status.name,
            "host": status.host,
            "state": status.state.value if status.state else "unknown",
            "agent_deployed": status.agent_deployed,
            "agent_running": status.agent_running,
            "last_refresh": status.last_refresh.isoformat() if status.last_refresh else None,
            "recent_alerts_count": len(status.recent_alerts) if status.recent_alerts else 0,
        }
    
    # System info
    system_info = {
        "python_version": sys.version,
        "platform": sys.platform,
        "current_time": datetime.now().isoformat(),
    }
    
    return {
        "ssh_connections": ssh_states,
        "array_status_cache": status_cache,
        "system_info": system_info,
        "alert_stats": get_system_alert_store().get_stats(),
    }


@router.post("/test")
async def create_test_alert(
    level: str = Query("info", description="Alert level"),
    message: str = Query("Test alert", description="Alert message"),
):
    """Create a test system alert for debugging"""
    from ..core.system_alert import sys_debug, sys_info, sys_warning, sys_error
    
    funcs = {
        "debug": sys_debug,
        "info": sys_info,
        "warning": sys_warning,
        "error": sys_error,
    }
    
    func = funcs.get(level.lower(), sys_info)
    func("test", message, {"test": True, "timestamp": datetime.now().isoformat()})
    
    return {"ok": True, "message": f"Created {level} alert: {message}"}
