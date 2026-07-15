"""
Alert Storage and Management.

Handles storing, querying, and analyzing alerts.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, desc, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.alert import AlertModel, AlertCreate, AlertResponse, AlertStats, AlertLevel
from ..db.database import get_db

logger = logging.getLogger(__name__)


async def _assign_task_ids(db: AsyncSession, alerts: List[AlertModel]) -> None:
    """Attach alerts to matching running or completed tasks, including late data."""
    if not alerts:
        return

    from ..models.task_session import TaskSessionModel

    min_ts = min(a.timestamp for a in alerts)
    max_ts = max(a.timestamp for a in alerts)
    result = await db.execute(
        select(TaskSessionModel)
        .where(
            TaskSessionModel.started_at.is_not(None),
            TaskSessionModel.started_at <= max_ts,
            or_(
                TaskSessionModel.status == "running",
                TaskSessionModel.ended_at >= min_ts,
            ),
        )
        .order_by(TaskSessionModel.started_at.desc())
    )
    tasks = result.scalars().all()

    for alert in alerts:
        for task in tasks:
            if alert.timestamp < task.started_at:
                continue
            if task.ended_at and alert.timestamp > task.ended_at:
                continue
            try:
                array_ids = json.loads(task.array_ids or "[]")
            except (json.JSONDecodeError, TypeError):
                array_ids = []
            if not array_ids or alert.array_id in array_ids:
                alert.task_id = task.id
                break


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
            source_event_id=alert.source_event_id,
        )
        
        db.add(db_alert)
        await _assign_task_ids(db, [db_alert])
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
        
        source_ids = {a.source_event_id for a in alerts if a.source_event_id}
        existing_ids = set()
        if source_ids:
            result = await db.execute(
                select(AlertModel.source_event_id).where(
                    AlertModel.source_event_id.in_(source_ids)
                )
            )
            existing_ids = {row[0] for row in result.all()}

        seen_ids = set(existing_ids)
        unique_alerts = []
        for alert in alerts:
            if alert.source_event_id and alert.source_event_id in seen_ids:
                continue
            if alert.source_event_id:
                seen_ids.add(alert.source_event_id)
            unique_alerts.append(alert)

        db_alerts = [
            AlertModel(
                array_id=a.array_id,
                observer_name=a.observer_name,
                level=a.level.value,
                message=a.message,
                details=json.dumps(a.details, ensure_ascii=False),
                timestamp=a.timestamp,
                source_event_id=a.source_event_id,
            )
            for a in unique_alerts
        ]

        if not db_alerts:
            return 0, []
        
        db.add_all(db_alerts)
        await _assign_task_ids(db, db_alerts)
        await db.flush()  # Assign IDs before commit
        await db.commit()
        
        return len(db_alerts), db_alerts
    
    async def get_alerts(
        self,
        db: AsyncSession,
        array_id: Optional[str] = None,
        array_ids: Optional[List[str]] = None,
        observer_name: Optional[str] = None,
        observer_names: Optional[List[str]] = None,
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
        elif array_ids is not None:
            conditions.append(AlertModel.array_id.in_(array_ids) if array_ids else False)
        if observer_name:
            conditions.append(AlertModel.observer_name == observer_name)
        elif observer_names is not None:
            conditions.append(AlertModel.observer_name.in_(observer_names) if observer_names else False)
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
        array_ids: Optional[List[str]] = None,
        observer_names: Optional[List[str]] = None,
        level: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> int:
        """Get alert count with filters"""
        query = select(func.count(AlertModel.id))
        
        conditions = []
        if array_id:
            conditions.append(AlertModel.array_id == array_id)
        elif array_ids is not None:
            conditions.append(AlertModel.array_id.in_(array_ids) if array_ids else False)
        if observer_names is not None:
            conditions.append(AlertModel.observer_name.in_(observer_names) if observer_names else False)
        if level:
            conditions.append(AlertModel.level == level)
        if start_time:
            conditions.append(AlertModel.timestamp >= start_time)
        if end_time:
            conditions.append(AlertModel.timestamp < end_time)
        
        if conditions:
            query = query.where(and_(*conditions))
        
        result = await db.execute(query)
        return result.scalar() or 0
    
    async def get_stats(
        self,
        db: AsyncSession,
        hours: int = 24,
        array_ids: Optional[List[str]] = None,
        observer_names: Optional[List[str]] = None,
    ) -> AlertStats:
        """Get alert statistics"""
        start_time = datetime.now() - timedelta(hours=hours)
        
        # Total count
        total = await self.get_alert_count(
            db, start_time=start_time, array_ids=array_ids, observer_names=observer_names
        )
        
        # By level
        by_level = {}
        for level in AlertLevel:
            count = await self.get_alert_count(
                db, level=level.value, start_time=start_time,
                array_ids=array_ids, observer_names=observer_names,
            )
            by_level[level.value] = count
        
        # By observer
        scope_conditions = [AlertModel.timestamp >= start_time]
        if array_ids is not None:
            scope_conditions.append(AlertModel.array_id.in_(array_ids) if array_ids else False)
        if observer_names is not None:
            scope_conditions.append(AlertModel.observer_name.in_(observer_names) if observer_names else False)

        query = select(
            AlertModel.observer_name,
            func.count(AlertModel.id)
        ).where(*scope_conditions).group_by(AlertModel.observer_name)
        
        result = await db.execute(query)
        by_observer = {row[0]: row[1] for row in result.all()}
        
        # By array
        query = select(
            AlertModel.array_id,
            func.count(AlertModel.id)
        ).where(*scope_conditions).group_by(AlertModel.array_id)
        
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

            bucket_count = await self.get_alert_count(
                db, start_time=bucket_start, end_time=bucket_end,
                array_ids=array_ids, observer_names=observer_names,
            )

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
