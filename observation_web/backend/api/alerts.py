"""
Alert management API endpoints.
"""

import csv
import io
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.alert_store import get_alert_store, AlertStore
from ..db.database import get_db
from ..models.alert import AlertResponse, AlertStats, AlertLevel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=List[AlertResponse])
async def list_alerts(
    array_id: Optional[str] = Query(None, description="Filter by array ID"),
    observer_name: Optional[str] = Query(None, description="Filter by observer"),
    level: Optional[str] = Query(None, description="Filter by level"),
    hours: Optional[int] = Query(24, description="Time range in hours"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Get alerts with filters.
    
    Supports filtering by:
    - array_id: Filter by specific array
    - observer_name: Filter by observer type
    - level: Filter by alert level (info/warning/error/critical)
    - hours: Time range (default 24 hours)
    """
    store = get_alert_store()
    
    start_time = None
    if hours:
        start_time = datetime.now() - timedelta(hours=hours)
    
    alerts = await store.get_alerts(
        db,
        array_id=array_id,
        observer_name=observer_name,
        level=level,
        start_time=start_time,
        limit=limit,
        offset=offset,
    )
    
    return alerts


@router.get("/stats", response_model=AlertStats)
async def get_alert_stats(
    hours: int = Query(24, description="Time range in hours"),
    db: AsyncSession = Depends(get_db),
):
    """Get alert statistics"""
    store = get_alert_store()
    return await store.get_stats(db, hours=hours)


@router.get("/recent")
async def get_recent_alerts(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get most recent alerts for dashboard"""
    store = get_alert_store()
    
    alerts = await store.get_alerts(
        db,
        limit=limit,
        offset=0,
    )
    
    return [
        {
            "id": a.id,
            "array_id": a.array_id,
            "observer_name": a.observer_name,
            "level": a.level,
            "message": a.message[:200] if len(a.message) > 200 else a.message,
            "timestamp": a.timestamp.isoformat(),
        }
        for a in alerts
    ]


@router.get("/summary")
async def get_alert_summary(
    db: AsyncSession = Depends(get_db),
):
    """Get quick summary for dashboard cards"""
    store = get_alert_store()
    
    # Last 24 hours
    total_24h = await store.get_alert_count(
        db, start_time=datetime.now() - timedelta(hours=24)
    )
    
    # Last hour
    total_1h = await store.get_alert_count(
        db, start_time=datetime.now() - timedelta(hours=1)
    )
    
    # Error count
    error_count = await store.get_alert_count(
        db, level="error", start_time=datetime.now() - timedelta(hours=24)
    )
    
    critical_count = await store.get_alert_count(
        db, level="critical", start_time=datetime.now() - timedelta(hours=24)
    )
    
    return {
        "total_24h": total_24h,
        "total_1h": total_1h,
        "error_count": error_count + critical_count,
        "warning_count": total_24h - error_count - critical_count,
    }


@router.get("/export")
async def export_alerts(
    format: str = Query("csv", description="Export format: csv"),
    array_id: Optional[str] = Query(None, description="Filter by array ID"),
    observer_name: Optional[str] = Query(None, description="Filter by observer"),
    level: Optional[str] = Query(None, description="Filter by level"),
    hours: int = Query(24, description="Time range in hours"),
    db: AsyncSession = Depends(get_db),
):
    """
    Export alerts to CSV file.
    
    Returns a downloadable CSV file with alerts data.
    """
    store = get_alert_store()
    
    start_time = datetime.now() - timedelta(hours=hours)
    
    alerts = await store.get_alerts(
        db,
        array_id=array_id,
        observer_name=observer_name,
        level=level,
        start_time=start_time,
        limit=10000,  # Max export limit
        offset=0,
    )
    
    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        '时间', '级别', '阵列ID', '观察点', '消息', '详情'
    ])
    
    # Data rows
    for alert in alerts:
        writer.writerow([
            alert.timestamp.strftime('%Y-%m-%d %H:%M:%S') if alert.timestamp else '',
            alert.level,
            alert.array_id,
            alert.observer_name,
            alert.message,
            alert.details if alert.details else '',
        ])
    
    output.seek(0)
    
    # Generate filename with timestamp
    filename = f"alerts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Content-Type": "text/csv; charset=utf-8-sig",
        }
    )


@router.delete("/cleanup")
async def cleanup_old_alerts(
    days: int = Query(30, ge=1, le=365, description="Delete alerts older than days"),
    db: AsyncSession = Depends(get_db),
):
    """Delete old alerts"""
    store = get_alert_store()
    deleted = await store.delete_old_alerts(db, days=days)
    
    return {
        "deleted": deleted,
        "message": f"Deleted {deleted} alerts older than {days} days"
    }
