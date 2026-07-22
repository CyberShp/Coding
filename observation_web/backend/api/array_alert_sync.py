"""
Alert sync helpers and the refresh endpoint.

Owns:
- _parse_alert_details, _get_sync_position, _update_sync_position
- _auto_ack_new_alerts
- sync_array_alerts (imported by core/alert_sync.py)
- POST /arrays/{array_id}/refresh
"""
import asyncio
import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..core.agent_deployer import AgentDeployer
from ..core.ssh_pool import get_ssh_pool, SSHPool
from ..core.system_alert import sys_error, sys_info
from ..db.database import get_db, AsyncSessionLocal
from ..models.array import ArrayModel, ConnectionState
from ..models.lifecycle import SyncStateModel
from ..models.alert import AlertModel, AlertAckModel

from .auth import require_user
from .array_status import (
    _array_status_cache,
    _get_array_status,
    _get_array_or_404,
    _update_active_issues,
    _derive_active_issues_from_db,
)

logger = logging.getLogger(__name__)
sync_router = APIRouter()


# ---------------------------------------------------------------------------
# Shared async helper (local copy to avoid circular import)
# ---------------------------------------------------------------------------

async def _run_blocking(func, _timeout: float, *args, **kwargs):
    """Run sync I/O in threadpool to avoid blocking event loop."""
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, lambda: func(*args, **kwargs)),
        timeout=_timeout,
    )


# ---------------------------------------------------------------------------
# Sync position tracking
# ---------------------------------------------------------------------------

def _parse_alert_details(raw_details: Any) -> Dict[str, Any]:
    """Parse alert details payload to dict safely."""
    if not raw_details:
        return {}
    if isinstance(raw_details, dict):
        return raw_details
    if isinstance(raw_details, str):
        try:
            return json.loads(raw_details)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


async def _get_sync_position(db: AsyncSession, array_id: str) -> int:
    """Get last sync position from DB (multi-instance safe)."""
    result = await db.execute(
        select(SyncStateModel).where(SyncStateModel.array_id == array_id)
    )
    row = result.scalar_one_or_none()
    return row.last_position if row else 0


async def _update_sync_position(
    db: AsyncSession, array_id: str, new_position: int, expected_old: int
) -> bool:
    """
    Update sync position with optimistic locking (compare-and-swap).
    Returns True if update succeeded, False if another instance already advanced.
    """
    result = await db.execute(
        select(SyncStateModel).where(SyncStateModel.array_id == array_id)
    )
    row = result.scalar_one_or_none()

    if row is None:
        new_row = SyncStateModel(
            array_id=array_id,
            last_position=new_position,
            last_sync_at=datetime.now(),
        )
        db.add(new_row)
        await db.flush()
        return True

    if row.last_position != expected_old:
        return False

    row.last_position = new_position
    row.last_sync_at = datetime.now()
    await db.flush()
    return True


async def _set_sync_position(db: AsyncSession, array_id: str, new_position: int) -> None:
    """Force-set the sync cursor (single-instance; no compare-and-swap).

    The old CAS path broke on log rotation: the rotation branch reset the local
    cursor to 0 and then compared-and-swapped against 0 while the DB still held
    the old large value, so the write silently failed and the cursor got stuck —
    re-reading the same tail forever.  The service runs single-instance
    (workers=1, one sync loop), so an unconditional set is both correct and
    rotation-safe.
    """
    result = await db.execute(
        select(SyncStateModel).where(SyncStateModel.array_id == array_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        db.add(SyncStateModel(
            array_id=array_id,
            last_position=new_position,
            last_sync_at=datetime.now(),
        ))
    else:
        row.last_position = new_position
        row.last_sync_at = datetime.now()
    await db.flush()


def _parse_alert_ts(timestamp_str: str) -> datetime:
    """Parse an agent alert timestamp into a naive local datetime.

    The backend compares timestamps against ``datetime.now()`` (naive local),
    so aware timestamps are normalised to naive to avoid aware/naive comparison
    errors.  Falls back to now() on unparseable input.
    """
    try:
        return datetime.fromisoformat(
            timestamp_str.replace('Z', '+00:00').replace('+00:00', '')
        )
    except Exception:
        return datetime.now()


def _dedup_key(timestamp_str: str, observer: str, message: str) -> str:
    """Build a dedup key from the FULL message (hashed), not a 50-char prefix.

    The old key truncated the message to 50 chars, which merged distinct alerts
    that shared a common prefix (silent alert loss).  Hashing the whole message
    fixes that while keeping the key compact.
    """
    digest = hashlib.md5((message or "").encode("utf-8", "ignore")).hexdigest()
    return f"{timestamp_str}|{observer}|{digest}"


def _apply_observer_status(status_obj, parsed_alerts: List[Dict[str, Any]]) -> None:
    """Update the in-memory observer_status map from parsed alerts (refresh path)."""
    for alert in parsed_alerts[-200:]:
        observer = alert.get('observer_name', '')
        if not observer:
            continue
        level = alert.get('level', 'info')
        message = alert.get('message', '')
        alert_ts = alert.get('timestamp', datetime.now().isoformat())
        if level in ('error', 'critical'):
            status_obj.observer_status[observer] = {
                'status': 'error', 'message': message[:100], 'last_active_ts': alert_ts,
            }
        elif level == 'warning':
            if observer not in status_obj.observer_status or \
               status_obj.observer_status[observer].get('status') != 'error':
                status_obj.observer_status[observer] = {
                    'status': 'warning', 'message': message[:100], 'last_active_ts': alert_ts,
                }
        else:
            if observer not in status_obj.observer_status:
                status_obj.observer_status[observer] = {
                    'status': 'ok', 'message': '', 'last_active_ts': alert_ts,
                }
            else:
                status_obj.observer_status[observer]['last_active_ts'] = alert_ts


# ---------------------------------------------------------------------------
# Auto-ack on new alerts
# ---------------------------------------------------------------------------

async def _auto_ack_new_alerts(
    db: AsyncSession,
    array_id: str,
    created_alerts: List[AlertModel],
) -> None:
    """
    Auto-ack new alerts if the same array_id+observer_name was previously
    confirmed_ok or has an unexpired dismiss ack.
    """
    if not created_alerts:
        return

    from sqlalchemy import func
    now = datetime.now()

    confirmed_result = await db.execute(
        select(AlertModel.observer_name).distinct()
        .join(AlertAckModel, AlertAckModel.alert_id == AlertModel.id)
        .where(
            AlertModel.array_id == array_id,
            AlertAckModel.ack_type == "confirmed_ok",
            AlertAckModel.ack_expires_at.is_(None),
        )
    )
    confirmed_observers = {r[0] for r in confirmed_result.all()}

    from sqlalchemy import func as sa_func
    dismiss_result = await db.execute(
        select(
            AlertModel.observer_name,
            sa_func.max(AlertAckModel.ack_expires_at).label("expires_at"),
        )
        .join(AlertAckModel, AlertAckModel.alert_id == AlertModel.id)
        .where(
            AlertModel.array_id == array_id,
            AlertAckModel.ack_type == "dismiss",
            AlertAckModel.ack_expires_at > now,
        )
        .group_by(AlertModel.observer_name)
    )
    dismiss_map = {r[0]: r[1] for r in dismiss_result.all()}

    created_acks = []
    for alert in created_alerts:
        obs = alert.observer_name
        if obs in confirmed_observers:
            ack = AlertAckModel(
                alert_id=alert.id,
                acked_by_ip="system",
                ack_type="confirmed_ok",
                ack_expires_at=None,
            )
            db.add(ack)
            created_acks.append(ack)
        elif obs in dismiss_map and obs not in confirmed_observers:
            ack = AlertAckModel(
                alert_id=alert.id,
                acked_by_ip="system",
                ack_type="dismiss",
                ack_expires_at=dismiss_map[obs],
            )
            db.add(ack)
            created_acks.append(ack)

    if created_acks:
        await db.flush()


# ---------------------------------------------------------------------------
# Core sync function (used by core/alert_sync.py)
# ---------------------------------------------------------------------------

# Max lines pulled per SSH round; a large backlog is read across several
# batches so we never load an unbounded burst fully into memory, and — unlike
# the old `tail -n 500` — never silently drop the lines in between.
MAX_LINES_PER_BATCH = 5000


async def sync_array_alerts(
    array_id: str,
    db: AsyncSession,
    conn: "SSHConnection",
    config,
    full_sync: bool = False,
    status_obj=None,
) -> int:
    """
    Sync alerts from array's alerts.log to DB.

    Reads every new line since the last cursor using ``tail -n +K`` (line-offset
    based, batched) so alert bursts are never truncated.  Handles log rotation
    by resyncing from the start, dedups against an adaptive window using the full
    message hash, force-advances the cursor, and stamps a heartbeat on success.

    When ``status_obj`` is provided (refresh endpoint) the in-memory observer
    status and active issues are updated too.

    Returns count of new alerts synced. Raises on fatal error.
    """
    from ..core.alert_store import get_alert_store
    from ..models.alert import AlertCreate, AlertLevel
    from .websocket import broadcast_alert
    from .ingest import touch_heartbeat

    log_path = config.remote.agent_log_path

    exit_code, total_str, _ = await conn.execute_async(f"wc -l < {log_path} 2>/dev/null", timeout=5)
    if exit_code != 0:
        return 0
    try:
        total_lines = int(total_str.strip())
    except (ValueError, AttributeError):
        return 0

    # A successful wc means the collection channel to the agent is alive.
    await touch_heartbeat(db, array_id)

    db_pos = await _get_sync_position(db, array_id)
    rotated = total_lines < db_pos
    if rotated:
        logger.info(
            "Log rotation/truncation detected for %s (total=%d < cursor=%d); resyncing from start",
            array_id, total_lines, db_pos,
        )
    start_pos = 0 if (full_sync or rotated) else db_pos

    new_count = total_lines - start_pos
    if new_count <= 0:
        # Nothing new (or file unchanged) — still keep the cursor consistent.
        await _set_sync_position(db, array_id, total_lines)
        return 0

    alert_store = get_alert_store()
    # Adaptive dedup window: cover at least this sync's own volume (not a fixed
    # 100), capped to avoid pulling an unbounded history into memory.
    dedup_limit = min(max(new_count + 100, 200), 5000)
    existing_alerts = await alert_store.get_alerts(db, array_id=array_id, limit=dedup_limit)
    existing_keys = {
        _dedup_key(a.timestamp.isoformat(), a.observer_name, a.message or "")
        for a in existing_alerts
    }

    if new_count > MAX_LINES_PER_BATCH:
        logger.warning(
            "Large alert backlog for %s: %d new lines, reading in batches of %d",
            array_id, new_count, MAX_LINES_PER_BATCH,
        )

    total_new = 0
    all_parsed: List[Dict[str, Any]] = []
    pos = start_pos
    while pos < total_lines:
        batch = min(MAX_LINES_PER_BATCH, total_lines - pos)
        exit_code, content, _ = await conn.execute_async(
            f"tail -n +{pos + 1} {log_path} 2>/dev/null | head -n {batch}", timeout=20
        )
        pos += batch
        if exit_code != 0 or not content or not content.strip():
            continue

        parsed_alerts = []
        for line in content.strip().split('\n'):
            if not line.strip():
                continue
            try:
                parsed_alerts.append(json.loads(line))
            except Exception:
                pass
        if not parsed_alerts:
            continue
        all_parsed.extend(parsed_alerts)

        new_alerts = []
        for alert in parsed_alerts:
            timestamp_str = alert.get('timestamp', '')
            if not timestamp_str:
                continue
            key = _dedup_key(timestamp_str, alert.get('observer_name', ''), alert.get('message', ''))
            if key in existing_keys:
                continue
            existing_keys.add(key)
            try:
                level_str = alert.get('level', 'info').lower()
                level = AlertLevel(level_str) if level_str in [l.value for l in AlertLevel] else AlertLevel.INFO
                new_alerts.append(AlertCreate(
                    array_id=array_id,
                    observer_name=alert.get('observer_name', 'unknown'),
                    level=level,
                    message=alert.get('message', ''),
                    details=alert.get('details', {}),
                    timestamp=_parse_alert_ts(timestamp_str),
                ))
            except Exception as e:
                sys_error("arrays", "Failed to parse alert", {"error": str(e)})

        if new_alerts:
            cnt, created_db_alerts = await alert_store.create_alerts_batch(db, new_alerts)
            total_new += cnt
            await _auto_ack_new_alerts(db, array_id, created_db_alerts)
            for db_alert in created_db_alerts[-50:]:
                await broadcast_alert({
                    'id': db_alert.id,
                    'array_id': db_alert.array_id,
                    'observer_name': db_alert.observer_name,
                    'level': db_alert.level,
                    'message': db_alert.message,
                    'timestamp': db_alert.timestamp.isoformat() if db_alert.timestamp else None,
                    'created_at': db_alert.created_at.isoformat() if db_alert.created_at else None,
                })

    if status_obj is not None and all_parsed:
        _apply_observer_status(status_obj, all_parsed)
        for alert in all_parsed:
            _update_active_issues(status_obj, alert)
        status_obj.active_issues = await _derive_active_issues_from_db(db, array_id)

    # Force-advance the cursor regardless of prior value (rotation-safe).
    await _set_sync_position(db, array_id, total_lines)
    if total_new:
        sys_info("arrays", f"Synced {total_new} new alerts for {array_id}")
    return total_new


# ---------------------------------------------------------------------------
# Refresh endpoint
# ---------------------------------------------------------------------------

@sync_router.post("/{array_id}/refresh", dependencies=[Depends(require_user)])
async def refresh_array(
    array_id: str,
    full_sync: bool = Query(False, description="Force full sync instead of incremental"),
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Refresh array status and sync alerts incrementally.
    """
    await _get_array_or_404(array_id, db)
    from ..core.alert_store import get_alert_store
    from ..models.alert import AlertCreate, AlertLevel
    from .websocket import broadcast_alert
    from ..core.ssh_pool import tcp_probe

    conn = ssh_pool.get_connection(array_id)

    if not conn:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="阵列未连接，请先添加并连接阵列",
        )

    reachable = await _run_blocking(tcp_probe, 3, conn.host, conn.port, 2.0)
    if not reachable:
        conn._mark_disconnected()
        status_obj = _get_array_status(array_id)
        status_obj.state = conn.state
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"阵列 {conn.host} 网络不可达，请检查阵列是否在线",
        )

    if not conn.check_alive():
        if not conn._try_reconnect():
            status_obj = _get_array_status(array_id)
            status_obj.state = conn.state
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="SSH连接已断开且重连失败，请手动重新连接",
            )

    status_obj = _get_array_status(array_id)

    config = get_config()
    deployer = AgentDeployer(conn, config)
    loop = asyncio.get_running_loop()
    try:
        status_obj.agent_deployed = await asyncio.wait_for(
            loop.run_in_executor(None, deployer.check_deployed), timeout=10
        )
        status_obj.agent_running = await asyncio.wait_for(
            loop.run_in_executor(None, deployer.check_running), timeout=10
        )
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"Agent status check failed for {array_id}: {e}")
        status_obj.agent_deployed = False
        status_obj.agent_running = False

    try:
        agent_info = await asyncio.wait_for(
            loop.run_in_executor(None, deployer.get_agent_status), timeout=10
        )
        status_obj.agent_running = agent_info.get("running", False)
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"Agent info fetch failed for {array_id}: {e}")
        agent_info = {"running": False}
        status_obj.agent_running = False

    new_alerts_count = 0
    try:
        # Single source of truth for alert syncing (line-offset based, batched,
        # rotation-safe, adaptive dedup, heartbeat on success).  status_obj is
        # passed so observer_status / active_issues get updated for the UI.
        new_alerts_count = await sync_array_alerts(
            array_id, db, conn, config, full_sync=full_sync, status_obj=status_obj
        )
    except Exception as e:
        sys_error("arrays", f"Refresh failed for {array_id}", {"error": str(e)})

    try:
        from ..core.traffic_store import get_traffic_store
        traffic_path = config.remote.agent_log_path.replace('alerts.log', 'traffic.jsonl')
        exit_code_t, traffic_content, _ = await conn.execute_async(
            f"tail -n 200 {traffic_path} 2>/dev/null", timeout=10
        )
        if exit_code_t == 0 and traffic_content and traffic_content.strip():
            traffic_records = []
            for line in traffic_content.strip().split('\n'):
                line = line.strip()
                if not line:
                    continue
                try:
                    traffic_records.append(json.loads(line))
                except Exception:
                    pass
            if traffic_records:
                traffic_store = get_traffic_store()
                await traffic_store.ingest(db, array_id, traffic_records)
    except Exception as e:
        logger.debug(f"Traffic sync during refresh: {e}")

    status_obj.last_refresh = datetime.now()

    return {
        "state": status_obj.state.value if hasattr(status_obj.state, 'value') else status_obj.state,
        "agent_deployed": status_obj.agent_deployed,
        "agent_running": status_obj.agent_running,
        "agent_pid": agent_info.get("pid"),
        "new_alerts_synced": new_alerts_count,
        "observer_status": status_obj.observer_status,
        "last_refresh": status_obj.last_refresh.isoformat() if status_obj.last_refresh else None,
    }
