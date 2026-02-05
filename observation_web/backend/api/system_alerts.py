"""
System alerts API endpoints.

Provides access to backend error logs and system alerts.
"""

from typing import List, Optional

from fastapi import APIRouter, Query

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
