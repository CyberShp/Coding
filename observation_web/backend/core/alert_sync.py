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
from ..core.status_cache import _array_status_cache
from ..core.active_issues import _derive_active_issues_from_db, cleanup_stale_acks
from ..db import database as _db_module

# NOTE: sync_array_alerts and broadcast_status_update remain in the api layer
# (they orchestrate api-layer concerns — SSH sync flow + WebSocket broadcast).
# They are imported lazily inside the functions below to keep core -> api out of
# the module import graph (no top-level "from ..api" in core).

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None
_sync_interval_seconds = 20
_max_concurrent = 5
_sync_round = 0  # for periodic maintenance (stale-ack cleanup)
# If an array pushed within this window, skip its (redundant) SSH pull — the push
# channel already delivered the same alerts.log content.
_PUSH_FRESH_SECONDS = 120


def _push_is_fresh(array_id: str) -> bool:
    import time
    from ..api.ingest import get_last_push_at
    return (time.time() - get_last_push_at(array_id)) < _PUSH_FRESH_SECONDS


async def _sync_one_array(array_id: str, semaphore: asyncio.Semaphore) -> Tuple[str, Optional[int]]:
    """Sync alerts for one array. Returns (array_id, new_count or None on error)."""
    async with semaphore:
        try:
            ssh_pool = get_ssh_pool()
            conn = ssh_pool.get_connection(array_id)
            if not conn or not conn.is_connected():
                return (array_id, None)

            config = get_config()
            # Lazy import: breaks the core->api cycle. sync_array_alerts lives in
            # api/array_alert_sync.py (it drives the SSH sync + api concerns).
            from ..api.array_alert_sync import sync_array_alerts
            async with _db_module.AsyncSessionLocal() as db:
                push_fresh = _push_is_fresh(array_id)
                if push_fresh:
                    # Push channel is active — its alerts are already in the DB.
                    # Skip the redundant SSH pull (wc/tail), but still refresh
                    # derived active issues below so the dashboard reflects them.
                    count = 0
                else:
                    count = await sync_array_alerts(array_id, db, conn, config, full_sync=False)
                    await db.commit()

                # Refresh in-memory active issues so dashboard stays current
                # (also when push delivered alerts but we skipped the SSH pull).
                if array_id in _array_status_cache and ((count and count > 0) or push_fresh):
                    try:
                        issues = await _derive_active_issues_from_db(db, array_id)
                        _array_status_cache[array_id].active_issues = issues
                        # Broadcast so ArrayDetail pages pick up new issues without manual refresh.
                        # Lazy import: breaks the core->api cycle (websocket is an api
                        # orchestration concern).
                        from ..api.websocket import broadcast_status_update
                        status_obj = _array_status_cache[array_id]
                        await broadcast_status_update(array_id, {
                            "array_id": array_id,
                            "state": status_obj.state.value,
                            "agent_running": status_obj.agent_running,
                            "agent_deployed": status_obj.agent_deployed,
                            "active_issues": issues,
                            "event": "alert_sync",
                        })
                    except Exception as e:
                        logger.warning("Failed to refresh active issues for %s: %s", array_id, e)

                return (array_id, count)
        except Exception as e:
            err_str = str(e)
            if "no such table" in err_str.lower():
                logger.error(f"Alert sync failed for {array_id}: missing table - {e}")
                sys_error(
                    "alert_sync",
                    f"DB table missing for {array_id}, run create_tables",
                    {"error": err_str},
                    exception=e,
                )
            else:
                logger.warning(f"Alert sync failed for {array_id}: {e}")
                sys_warning("alert_sync", f"Sync failed for {array_id}", {"error": err_str})
            return (array_id, None)


async def _run_sync():
    """Sync alerts from all connected arrays."""
    global _sync_round
    _sync_round += 1
    # Periodic maintenance (~every 10 min): physically remove expired acks that
    # GET status endpoints no longer delete inline.
    if _sync_round % 30 == 0:
        try:
            async with _db_module.AsyncSessionLocal() as db:
                removed = await cleanup_stale_acks(db)
                if removed:
                    logger.info("Cleaned %d stale ack rows", removed)
        except Exception as e:
            logger.warning("Stale ack cleanup failed: %s", e)

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
        # Without these, APScheduler's defaults (max_instances=1,
        # misfire_grace_time=1s) silently DROP a whole cycle whenever the
        # previous run overruns the 20s interval — which is exactly what happens
        # at 50-array scale.  coalesce collapses a backlog into one run.
        max_instances=1,
        coalesce=True,
        misfire_grace_time=_sync_interval_seconds,
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
