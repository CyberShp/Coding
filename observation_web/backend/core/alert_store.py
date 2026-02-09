"""
Alert Storage and Management.

Handles storing, querying, and analyzing alerts.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.alert import AlertModel, AlertCreate, AlertResponse, AlertStats, AlertLevel
from ..db.database import get_db

logger = logging.getLogger(__name__)


class AlertStore:
    """
    Alert storage and query manager.
    
    Features:
    - Store alerts to database
    - Query with filters
    - Generate statistics
    """
    
    async def create_alert(
        self,
        db: AsyncSession,
        alert: AlertCreate,
    ) -> AlertModel:
        """Create a new alert"""
        db_alert = AlertModel(
            array_id=alert.array_id,
            observer_name=alert.observer_name,
            level=alert.level.value,
            message=alert.message,
            details=json.dumps(alert.details, ensure_ascii=False),
            timestamp=alert.timestamp,
        )
        
        db.add(db_alert)
        await db.commit()
        await db.refresh(db_alert)
        
        return db_alert
    
    async def create_alerts_batch(
        self,
        db: AsyncSession,
        alerts: List[AlertCreate],
    ) -> int:
        """Create multiple alerts in batch"""
        if not alerts:
            return 0
        
        db_alerts = [
            AlertModel(
                array_id=a.array_id,
                observer_name=a.observer_name,
                level=a.level.value,
                message=a.message,
                details=json.dumps(a.details, ensure_ascii=False),
                timestamp=a.timestamp,
            )
            for a in alerts
        ]
        
        db.add_all(db_alerts)
        await db.commit()
        
        return len(db_alerts)
    
    async def get_alerts(
        self,
        db: AsyncSession,
        array_id: Optional[str] = None,
        observer_name: Optional[str] = None,
        level: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AlertModel]:
        """Query alerts with filters"""
        query = select(AlertModel)
        
        conditions = []
        if array_id:
            conditions.append(AlertModel.array_id == array_id)
        if observer_name:
            conditions.append(AlertModel.observer_name == observer_name)
        if level:
            conditions.append(AlertModel.level == level)
        if start_time:
            conditions.append(AlertModel.timestamp >= start_time)
        if end_time:
            conditions.append(AlertModel.timestamp <= end_time)
        
        if conditions:
            query = query.where(and_(*conditions))
        
        query = query.order_by(desc(AlertModel.timestamp))
        query = query.offset(offset).limit(limit)
        
        result = await db.execute(query)
        return result.scalars().all()
    
    async def get_alert_count(
        self,
        db: AsyncSession,
        array_id: Optional[str] = None,
        level: Optional[str] = None,
        start_time: Optional[datetime] = None,
    ) -> int:
        """Get alert count with filters"""
        query = select(func.count(AlertModel.id))
        
        conditions = []
        if array_id:
            conditions.append(AlertModel.array_id == array_id)
        if level:
            conditions.append(AlertModel.level == level)
        if start_time:
            conditions.append(AlertModel.timestamp >= start_time)
        
        if conditions:
            query = query.where(and_(*conditions))
        
        result = await db.execute(query)
        return result.scalar() or 0
    
    async def get_stats(
        self,
        db: AsyncSession,
        hours: int = 24,
    ) -> AlertStats:
        """Get alert statistics"""
        start_time = datetime.now() - timedelta(hours=hours)
        
        # Total count
        total = await self.get_alert_count(db, start_time=start_time)
        
        # By level
        by_level = {}
        for level in AlertLevel:
            count = await self.get_alert_count(db, level=level.value, start_time=start_time)
            by_level[level.value] = count
        
        # By observer
        query = select(
            AlertModel.observer_name,
            func.count(AlertModel.id)
        ).where(
            AlertModel.timestamp >= start_time
        ).group_by(AlertModel.observer_name)
        
        result = await db.execute(query)
        by_observer = {row[0]: row[1] for row in result.all()}
        
        # By array
        query = select(
            AlertModel.array_id,
            func.count(AlertModel.id)
        ).where(
            AlertModel.timestamp >= start_time
        ).group_by(AlertModel.array_id)
        
        result = await db.execute(query)
        by_array = {row[0]: row[1] for row in result.all()}
        
        # Dynamic trend: for <=4 hours use 10-min buckets, otherwise hourly
        trend = []
        now = datetime.now()
        if hours <= 4:
            num_buckets = hours * 6          # 10-min intervals
            bucket_minutes = 10
        else:
            num_buckets = min(hours, 48)     # hourly, cap at 48
            bucket_minutes = 60

        for i in range(num_buckets):
            bucket_start = now - timedelta(minutes=bucket_minutes * (num_buckets - i))
            bucket_end   = now - timedelta(minutes=bucket_minutes * (num_buckets - i - 1))

            count_from_start = await self.get_alert_count(db, start_time=bucket_start)
            count_from_end   = await self.get_alert_count(db, start_time=bucket_end)
            bucket_count = count_from_start - count_from_end if i < num_buckets - 1 else count_from_start

            trend.append({
                'hour': bucket_start.strftime('%H:%M'),
                'count': max(0, bucket_count),
            })

        return AlertStats(
            total=total,
            by_level=by_level,
            by_observer=by_observer,
            by_array=by_array,
            trend_24h=trend,
        )
    
    async def delete_old_alerts(
        self,
        db: AsyncSession,
        days: int = 30,
    ) -> int:
        """Delete alerts older than specified days"""
        cutoff = datetime.now() - timedelta(days=days)
        
        query = select(AlertModel).where(AlertModel.timestamp < cutoff)
        result = await db.execute(query)
        alerts = result.scalars().all()
        
        for alert in alerts:
            await db.delete(alert)
        
        await db.commit()
        return len(alerts)


# Global instance
_alert_store: Optional[AlertStore] = None


def get_alert_store() -> AlertStore:
    """Get global alert store instance"""
    global _alert_store
    if _alert_store is None:
        _alert_store = AlertStore()
    return _alert_store
