"""
Port traffic data storage — ingest, query, and cleanup.

Storage strategy: keep only the last 2 hours of raw data.
Cleanup runs every 2 minutes to delete expired records.
"""

import json
import logging
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select, delete, func, distinct, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

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
            records: List of {ts, port, tx_bytes, rx_bytes, tx_rate_bps?, rx_rate_bps?, mode?, protocol?}

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
                    mode=rec.get('mode', 'auto'),
                    protocol=rec.get('protocol', 'ethernet'),
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

        base_where = and_(
            PortTrafficModel.array_id == array_id,
            PortTrafficModel.port_name == port_name,
            PortTrafficModel.timestamp >= cutoff,
        )

        total = (await db.execute(
            select(func.count(PortTrafficModel.id)).where(base_where)
        )).scalar() or 0

        if total <= MAX_QUERY_POINTS:
            # Small enough to return in full — no sampling needed.
            result = await db.execute(
                select(PortTrafficModel)
                .where(base_where)
                .order_by(PortTrafficModel.timestamp.asc())
            )
            rows = result.scalars().all()
        else:
            # Uniformly downsample across the WHOLE window instead of silently
            # truncating to the oldest 500 points. Pick every `stride`-th row by
            # timestamp order so the returned series spans the full time range.
            stride = math.ceil(total / MAX_QUERY_POINTS)
            numbered = (
                select(
                    PortTrafficModel,
                    func.row_number()
                    .over(order_by=PortTrafficModel.timestamp.asc())
                    .label("rn"),
                )
                .where(base_where)
                .subquery()
            )
            sampled_model = aliased(PortTrafficModel, numbered)
            result = await db.execute(
                select(sampled_model)
                .where(((numbered.c.rn - 1) % stride) == 0)
                .order_by(numbered.c.timestamp.asc())
                .limit(MAX_QUERY_POINTS)
            )
            rows = result.scalars().all()
            logger.info(
                "Traffic query downsampled %s/%s: %d points -> %d (stride %d)",
                array_id, port_name, total, len(rows), stride,
            )

        return [
            {
                'ts': r.timestamp.isoformat(),
                'tx_bytes': r.tx_bytes,
                'rx_bytes': r.rx_bytes,
                'tx_rate_bps': r.tx_rate_bps or 0.0,
                'rx_rate_bps': r.rx_rate_bps or 0.0,
                'mode': r.mode or 'auto',
                'protocol': r.protocol or 'ethernet',
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
