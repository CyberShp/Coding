"""
Port traffic data storage — ingest, query, and cleanup.

Storage strategy: keep only the last 2 hours of raw data.
Cleanup runs every 2 minutes to delete expired records.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select, delete, func, distinct, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.traffic import PortTrafficModel

logger = logging.getLogger(__name__)

# Maximum data points returned per query (prevents UI/API stall)
MAX_QUERY_POINTS = 500
# Retention period
RETENTION_HOURS = 2


class TrafficStore:
    """Port traffic data store."""

    async def ingest(
        self,
        db: AsyncSession,
        array_id: str,
        records: List[Dict[str, Any]],
    ) -> int:
        """
        Ingest raw traffic records from agent's traffic.jsonl.

        Args:
            db: Database session
            array_id: Array identifier
            records: List of {ts, port, tx_bytes, rx_bytes, tx_rate_bps?, rx_rate_bps?}

        Returns:
            Number of records ingested
        """
        if not records:
            return 0

        db_records = []
        for rec in records:
            try:
                ts = rec.get('ts', '')
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace('Z', ''))
                elif not isinstance(ts, datetime):
                    ts = datetime.now()

                db_records.append(PortTrafficModel(
                    array_id=array_id,
                    port_name=rec.get('port', 'unknown'),
                    timestamp=ts,
                    tx_bytes=rec.get('tx_bytes', 0),
                    rx_bytes=rec.get('rx_bytes', 0),
                    tx_rate_bps=rec.get('tx_rate_bps', 0.0),
                    rx_rate_bps=rec.get('rx_rate_bps', 0.0),
                ))
            except Exception as e:
                logger.debug(f"Skip bad traffic record: {e}")
                continue

        if db_records:
            db.add_all(db_records)
            await db.commit()

        return len(db_records)

    async def query(
        self,
        db: AsyncSession,
        array_id: str,
        port_name: str,
        minutes: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Query traffic data for a specific port.

        Args:
            array_id: Array ID
            port_name: Port name
            minutes: Time range in minutes (max 120)

        Returns:
            List of data points
        """
        minutes = min(minutes, 120)
        cutoff = datetime.now() - timedelta(minutes=minutes)

        query = (
            select(PortTrafficModel)
            .where(and_(
                PortTrafficModel.array_id == array_id,
                PortTrafficModel.port_name == port_name,
                PortTrafficModel.timestamp >= cutoff,
            ))
            .order_by(PortTrafficModel.timestamp.asc())
            .limit(MAX_QUERY_POINTS)
        )

        result = await db.execute(query)
        rows = result.scalars().all()

        return [
            {
                'ts': r.timestamp.isoformat(),
                'tx_bytes': r.tx_bytes,
                'rx_bytes': r.rx_bytes,
                'tx_rate_bps': r.tx_rate_bps or 0.0,
                'rx_rate_bps': r.rx_rate_bps or 0.0,
            }
            for r in rows
        ]

    async def get_ports(
        self,
        db: AsyncSession,
        array_id: str,
    ) -> List[str]:
        """
        Get available port names for an array.
        Only returns ports with recent data (last 2 hours).
        """
        cutoff = datetime.now() - timedelta(hours=RETENTION_HOURS)

        query = (
            select(distinct(PortTrafficModel.port_name))
            .where(and_(
                PortTrafficModel.array_id == array_id,
                PortTrafficModel.timestamp >= cutoff,
            ))
            .order_by(PortTrafficModel.port_name)
        )

        result = await db.execute(query)
        return [row[0] for row in result.all()]

    async def cleanup_expired(self, db: AsyncSession) -> int:
        """
        Delete all traffic records older than RETENTION_HOURS.
        Should be called periodically (every ~2 minutes).
        """
        cutoff = datetime.now() - timedelta(hours=RETENTION_HOURS)

        stmt = delete(PortTrafficModel).where(
            PortTrafficModel.timestamp < cutoff
        )
        result = await db.execute(stmt)
        await db.commit()

        deleted = result.rowcount
        if deleted > 0:
            logger.info(f"Traffic cleanup: deleted {deleted} expired records")
        return deleted


# Global instance
_traffic_store: Optional[TrafficStore] = None


def get_traffic_store() -> TrafficStore:
    global _traffic_store
    if _traffic_store is None:
        _traffic_store = TrafficStore()
    return _traffic_store
