"""
Alert Storage and Management.

Handles storing, querying, and analyzing alerts.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, desc, and_, cast, delete, Integer
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
    ) -> tuple[int, List["AlertModel"]]:
        """Create multiple alerts in batch. Returns (count, created_alert_models)."""
        if not alerts:
            return 0, []
        
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
        await db.flush()  # Assign IDs before commit
        await db.commit()
        
        return len(db_alerts), db_alerts
    
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
        """Query alerts with filters, each with an ``is_acked`` attribute."""
        from ..models.alert import AlertAckModel

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
        alerts = result.scalars().all()

        # Batch-check acknowledgement status (single extra query)
        if alerts:
            alert_ids = [a.id for a in alerts]
            ack_result = await db.execute(
                select(AlertAckModel.alert_id).where(
                    AlertAckModel.alert_id.in_(alert_ids)
                )
            )
            acked_ids = {row[0] for row in ack_result.all()}
            for alert in alerts:
                alert.is_acked = alert.id in acked_ids
        
        return alerts
    
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
        """Get alert statistics.

        All aggregation is done with a handful of GROUP BY queries instead of
        looping per-level/per-bucket COUNTs (previously ~100 serial queries).
        """
        start_time = datetime.now() - timedelta(hours=hours)

        # Total count
        total = await self.get_alert_count(db, start_time=start_time)

        # By level — single GROUP BY, pre-seeded with all levels at 0 so the
        # response shape stays stable regardless of which levels have data.
        by_level = {level.value: 0 for level in AlertLevel}
        level_result = await db.execute(
            select(AlertModel.level, func.count(AlertModel.id))
            .where(AlertModel.timestamp >= start_time)
            .group_by(AlertModel.level)
        )
        for level_name, count in level_result.all():
            by_level[level_name] = count

        # By observer
        result = await db.execute(
            select(AlertModel.observer_name, func.count(AlertModel.id))
            .where(AlertModel.timestamp >= start_time)
            .group_by(AlertModel.observer_name)
        )
        by_observer = {row[0]: row[1] for row in result.all()}

        # By array
        result = await db.execute(
            select(AlertModel.array_id, func.count(AlertModel.id))
            .where(AlertModel.timestamp >= start_time)
            .group_by(AlertModel.array_id)
        )
        by_array = {row[0]: row[1] for row in result.all()}

        # Dynamic trend: for <=4 hours use 10-min buckets, otherwise hourly.
        # Computed with ONE GROUP BY over a time-bucket expression rather than
        # two COUNTs per bucket.
        now = datetime.now()
        if hours <= 4:
            num_buckets = hours * 6          # 10-min intervals
            bucket_minutes = 10
        else:
            num_buckets = min(hours, 48)     # hourly, cap at 48
            bucket_minutes = 60

        bucket_seconds = bucket_minutes * 60
        base = now - timedelta(minutes=bucket_minutes * num_buckets)
        # Interpret the naive base as UTC to match SQLite's strftime('%s', ...),
        # which also treats stored naive datetimes as UTC — keeps bucket edges
        # aligned regardless of the server's local timezone.
        base_epoch = int(base.replace(tzinfo=timezone.utc).timestamp())

        # Integer bucket index relative to `base`.
        bucket_expr = cast(
            (cast(func.strftime('%s', AlertModel.timestamp), Integer) - base_epoch)
            / bucket_seconds,
            Integer,
        )
        trend_result = await db.execute(
            select(bucket_expr.label('bucket'), func.count(AlertModel.id))
            .where(AlertModel.timestamp >= base)
            .group_by('bucket')
        )
        bucket_counts = {row[0]: row[1] for row in trend_result.all()}

        trend = []
        for i in range(num_buckets):
            bucket_start = base + timedelta(minutes=bucket_minutes * i)
            trend.append({
                'hour': bucket_start.strftime('%H:%M'),
                'count': max(0, bucket_counts.get(i, 0)),
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
        """Delete alerts older than specified days.

        Uses a single range DELETE instead of loading every expired row into
        memory and deleting one at a time.
        """
        cutoff = datetime.now() - timedelta(days=days)

        result = await db.execute(
            delete(AlertModel).where(AlertModel.timestamp < cutoff)
        )
        await db.commit()
        return result.rowcount or 0


# Global instance
_alert_store: Optional[AlertStore] = None


def get_alert_store() -> AlertStore:
    """Get global alert store instance"""
    global _alert_store
    if _alert_store is None:
        _alert_store = AlertStore()
    return _alert_store
