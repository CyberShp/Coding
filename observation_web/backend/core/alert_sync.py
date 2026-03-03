"""
Background alert sync service.

Periodically syncs alerts from connected arrays to the database.
Uses APScheduler to run every 60 seconds. Max 5 concurrent array syncs.
"""

import asyncio
import logging
from typing import Optional, Tuple, TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..config import get_config
from ..core.ssh_pool import get_ssh_pool
from ..core.system_alert import sys_error, sys_warning
from ..db import database as _db_module
from ..api.arrays import sync_array_alerts

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None
_sync_interval_seconds = 60
_max_concurrent = 5


async def _sync_one_array(array_id: str, semaphore: asyncio.Semaphore) -> Tuple[str, Optional[int]]:
    """Sync alerts for one array. Returns (array_id, new_count or None on error)."""
    async with semaphore:
        try:
            ssh_pool = get_ssh_pool()
            conn = ssh_pool.get_connection(array_id)
            if not conn or not conn.is_connected():
                return (array_id, None)

            config = get_config()
            async with _db_module.AsyncSessionLocal() as db:
                count = await sync_array_alerts(array_id, db, conn, config, full_sync=False)
                await db.commit()
                return (array_id, count)
        except Exception as e:
            logger.warning(f"Alert sync failed for {array_id}: {e}")
            sys_warning("alert_sync", f"Sync failed for {array_id}", {"error": str(e)})
            return (array_id, None)


async def _run_sync():
    """Sync alerts from all connected arrays."""
    from ..models.array import ConnectionState

    ssh_pool = get_ssh_pool()
    connected = [
        aid for aid, conn in ssh_pool._connections.items()
        if conn.state == ConnectionState.CONNECTED
    ]
    if not connected:
        return

    semaphore = asyncio.Semaphore(_max_concurrent)
    results = await asyncio.gather(*[_sync_one_array(aid, semaphore) for aid in connected])
    synced = sum(1 for _, c in results if c is not None)
    total_new = sum(c or 0 for _, c in results)
    if total_new > 0:
        logger.info(f"Alert sync: {synced} arrays, {total_new} new alerts")


def start_alert_sync():
    """Start the background alert sync scheduler."""
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _run_sync,
        "interval",
        seconds=_sync_interval_seconds,
        id="alert_sync",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(f"Alert sync started (interval={_sync_interval_seconds}s, max_concurrent={_max_concurrent})")


def stop_alert_sync():
    """Stop the background alert sync scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown()
        _scheduler = None
        logger.info("Alert sync stopped")
