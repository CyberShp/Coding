"""
Array management API endpoints.
"""

import asyncio
import json
import logging
import shlex
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, status, Body, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, exists, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..core.agent_deployer import AgentDeployer
from ..core.ssh_pool import get_ssh_pool, SSHPool
from ..core.system_alert import sys_error, sys_warning, sys_info
from ..db.database import get_db, AsyncSessionLocal
from ..models.array import (
    ArrayModel, ArrayCreate, ArrayUpdate, ArrayResponse,
    ArrayStatus, ConnectionState
)
from ..models.lifecycle import SyncStateModel
from ..models.alert import AlertModel, AlertAckModel
from ..models.user_session import UserSessionModel
from ..middleware.user_session import get_users_on_page, ip_to_color


async def _resolve_ips_to_nicknames(db: AsyncSession, ips: List[str]) -> Dict[str, str]:
    """Resolve IP addresses to nicknames from user_sessions."""
    if not ips:
        return {}
    result = await db.execute(
        select(UserSessionModel.ip, UserSessionModel.nickname).where(UserSessionModel.ip.in_(ips))
    )
    return {r[0]: ((r[1] or "").strip()) or r[0] for r in result.all()}


class BatchActionRequest(BaseModel):
    """Request model for batch operations"""
    array_ids: List[str]
    password: Optional[str] = None  # For batch connect

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/arrays", tags=["arrays"])

# In-memory status cache
_array_status_cache: Dict[str, ArrayStatus] = {}


async def _run_blocking(func, _timeout: float, *args, **kwargs):
    """Run sync I/O in threadpool to avoid blocking event loop.

    _timeout is deliberately underscore-prefixed so that **kwargs can forward
    a ``timeout`` keyword to the wrapped *func* without colliding.
    """
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, lambda: func(*args, **kwargs)),
        timeout=_timeout,
    )


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
    from sqlalchemy import update as sa_update, insert as sa_insert

    result = await db.execute(
        select(SyncStateModel).where(SyncStateModel.array_id == array_id)
    )
    row = result.scalar_one_or_none()

    if row is None:
        # First time — insert new row
        new_row = SyncStateModel(
            array_id=array_id,
            last_position=new_position,
            last_sync_at=datetime.now(),
        )
        db.add(new_row)
        await db.flush()
        return True

    # Optimistic lock: only update if position matches what we read
    if row.last_position != expected_old:
        # Another instance already advanced the position — skip
        return False

    row.last_position = new_position
    row.last_sync_at = datetime.now()
    await db.flush()
    return True


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

    from ..models.alert import AlertAckModel

    now = datetime.now()

    # Observers with confirmed_ok (permanent only) - inherit for new alerts.
    # Design: Time-limited confirmed_ok (e.g. 8h) is NOT inherited; only ack_expires_at=NULL
    # is inherited. Rationale: User chose a time limit, so new alerts should surface after expiry.
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

    # Observers with unexpired dismiss - inherit for new alerts (use max expiry per observer)
    dismiss_result = await db.execute(
        select(
            AlertModel.observer_name,
            func.max(AlertAckModel.ack_expires_at).label("expires_at"),
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

    # Create acks for new alerts that should inherit
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


async def sync_array_alerts(
    array_id: str,
    db: AsyncSession,
    conn: "SSHConnection",
    config,
    full_sync: bool = False,
) -> int:
    """
    Sync alerts from array's alerts.log to DB. Used by refresh endpoint and background sync.
    Returns count of new alerts synced. Raises on fatal error.
    """
    from ..core.alert_store import get_alert_store
    from ..models.alert import AlertCreate, AlertLevel
    from .websocket import broadcast_alert

    log_path = config.remote.agent_log_path
    new_alerts_count = 0

    exit_code, total_str, _ = await conn.execute_async(f"wc -l < {log_path} 2>/dev/null", timeout=5)
    if exit_code != 0:
        return 0

    total_lines = int(total_str.strip())
    last_pos = await _get_sync_position(db, array_id)

    if full_sync or total_lines < last_pos:
        last_pos = 0

    new_count = total_lines - last_pos
    content = ""
    if new_count > 0:
        read_count = min(new_count, 500)
        exit_code, content, _ = await conn.execute_async(
            f"tail -n {read_count} {log_path} 2>/dev/null", timeout=10
        )

    if content and content.strip():
        parsed_alerts = []
        for line in content.strip().split('\n'):
            if not line.strip():
                continue
            try:
                parsed_alerts.append(json.loads(line))
            except Exception:
                pass

        if parsed_alerts:
            alert_store = get_alert_store()
            existing_alerts = await alert_store.get_alerts(db, array_id=array_id, limit=100)
            existing_keys = {
                f"{a.timestamp.isoformat()}_{a.observer_name}_{a.message[:50]}"
                for a in existing_alerts
            }

            new_alerts = []
            for alert in parsed_alerts:
                timestamp_str = alert.get('timestamp', '')
                if not timestamp_str:
                    continue
                dedup_key = f"{timestamp_str}_{alert.get('observer_name', '')}_{alert.get('message', '')[:50]}"
                if dedup_key in existing_keys:
                    continue
                existing_keys.add(dedup_key)

                try:
                    level_str = alert.get('level', 'info').lower()
                    level = AlertLevel(level_str) if level_str in [l.value for l in AlertLevel] else AlertLevel.INFO
                    alert_create = AlertCreate(
                        array_id=array_id,
                        observer_name=alert.get('observer_name', 'unknown'),
                        level=level,
                        message=alert.get('message', ''),
                        details=alert.get('details', {}),
                        timestamp=datetime.fromisoformat(
                            timestamp_str.replace('Z', '+00:00').replace('+00:00', '')
                        ),
                    )
                    new_alerts.append(alert_create)
                except Exception as e:
                    sys_error("arrays", "Failed to parse alert", {"error": str(e)})

            if new_alerts:
                new_alerts_count, created_db_alerts = await alert_store.create_alerts_batch(db, new_alerts)
                await _auto_ack_new_alerts(db, array_id, created_db_alerts)
                for alert in new_alerts[-10:]:
                    await broadcast_alert({
                        'array_id': alert.array_id,
                        'observer_name': alert.observer_name,
                        'level': alert.level.value,
                        'message': alert.message,
                        'timestamp': alert.timestamp.isoformat(),
                    })

    await _update_sync_position(db, array_id, total_lines, last_pos)
    return new_alerts_count


async def _get_array_or_404(array_id: str, db: AsyncSession) -> ArrayModel:
    """Verify array exists in DB, raise 404 if not found."""
    result = await db.execute(
        select(ArrayModel).where(ArrayModel.array_id == array_id)
    )
    arr = result.scalar_one_or_none()
    if not arr:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Array {array_id} not found"
        )
    return arr


async def _expand_l1_tag_filter(query, tag_id: int, db: AsyncSession):
    """If tag_id is an L1 tag, expand filter to include all child L2 tag arrays."""
    from ..models.tag import TagModel
    tag_check = await db.execute(
        select(TagModel.level).where(TagModel.id == tag_id)
    )
    tag_level = tag_check.scalar_one_or_none()
    if tag_level == 1:
        child_result = await db.execute(
            select(TagModel.id).where(TagModel.parent_id == tag_id)
        )
        child_ids = [r[0] for r in child_result.all()]
        all_ids = [tag_id] + child_ids
        return query.where(ArrayModel.tag_id.in_(all_ids))
    return query.where(ArrayModel.tag_id == tag_id)


def _get_array_status(array_id: str) -> ArrayStatus:
    """Get or create array status"""
    if array_id not in _array_status_cache:
        _array_status_cache[array_id] = ArrayStatus(
            array_id=array_id,
            name="",
            host="",
        )
    return _array_status_cache[array_id]


async def _apply_observer_overrides(conn, config, db: AsyncSession):
    """After deploy, merge observer_configs overrides into remote config.json."""
    try:
        from .observer_configs import get_all_observer_overrides
        overrides = await get_all_observer_overrides(db)
        if not overrides:
            return
        agent_path = config.remote.agent_deploy_path
        config_path = f"/etc/observation-points/config.json"
        content = await _run_blocking(conn.read_file, 10, config_path)
        if not content:
            return
        config_data = json.loads(content)
        observers = config_data.setdefault("observers", {})
        for obs_name, ov in overrides.items():
            obs = observers.setdefault(obs_name, {})
            obs.update(ov)
        import base64
        config_json = json.dumps(config_data, indent=2, ensure_ascii=False)
        encoded = base64.b64encode(config_json.encode("utf-8")).decode("ascii")
        await _run_blocking(conn.execute, 10, f"echo '{encoded}' | base64 -d > {config_path}")
    except Exception as e:
        logging.getLogger(__name__).warning(f"Failed to apply observer overrides: {e}")


async def _compute_recent_alert_summary(
    db: AsyncSession, array_id: str, hours: int = 2
) -> Dict[str, int]:
    """
    Return alert counts by level for the last *hours* hours.

    Example return: ``{"error": 3, "warning": 5, "info": 12}``
    """
    from ..models.alert import AlertModel
    from datetime import timedelta

    cutoff = datetime.now() - timedelta(hours=hours)
    result = await db.execute(
        select(AlertModel.level, func.count())
        .where(AlertModel.array_id == array_id)
        .where(AlertModel.timestamp >= cutoff)
        .group_by(AlertModel.level)
    )
    return {level: count for level, count in result.all()}


# ---------------------------------------------------------------------------
# Active Issues helpers
# ---------------------------------------------------------------------------

# Observers that contribute to the "active issues" panel
_ACTIVE_ISSUE_OBSERVERS = {
    'cpu_usage', 'memory_leak', 'alarm_type', 'pcie_bandwidth', 'card_info',
    'error_code', 'port_error_code',  # 端口误码（不含丢包）
}

_OBSERVER_TITLES = {
    'cpu_usage': 'CPU 利用率过高',
    'memory_leak': '内存疑似泄漏',
    'alarm_type': '告警未恢复',
    'pcie_bandwidth': 'PCIe 带宽降级',
    'card_info': '卡件异常',
    'error_code': '端口误码',
    'port_error_code': '端口误码',
}

# ---------------------------------------------------------------------------
# Recovery tracking — "recovery invalidates ack"
# ---------------------------------------------------------------------------
# Tracks when an observer/key last recovered for each array.
# Key: (array_id, issue_key) -> recovery timestamp (ISO string).
# When a new problem alert arrives for a key with a recorded recovery
# timestamp, any existing ack older than the recovery is stale and should
# be auto-invalidated.
_recovery_timestamps: Dict[str, Dict[str, str]] = {}  # array_id -> {issue_key -> iso_ts}


def _record_recovery(array_id: str, keys: List[str], timestamp: str):
    """Record that the given issue keys have recovered at *timestamp*."""
    bucket = _recovery_timestamps.setdefault(array_id, {})
    for key in keys:
        bucket[key] = timestamp


def _pop_recovery(array_id: str, key: str) -> Optional[str]:
    """Pop and return the recovery timestamp for *key*, or None."""
    bucket = _recovery_timestamps.get(array_id)
    if bucket:
        return bucket.pop(key, None)
    return None


def _update_active_issues(status_obj: ArrayStatus, alert: dict):
    """
    Process a single parsed alert and update ``status_obj.active_issues``.

    Rules per observer:
    * cpu_usage / pcie_bandwidth / card_info / memory_leak — if ``details.recovered`` is
      truthy, remove all matching issues and record recovery; otherwise upsert.
    * alarm_type — rebuild from ``details.active_alarms`` list each time.
    """
    observer = alert.get('observer_name', '')
    if observer not in _ACTIVE_ISSUE_OBSERVERS:
        return

    array_id = status_obj.array_id
    details = alert.get('details', {}) or {}
    level = alert.get('level', 'info')
    message = alert.get('message', '')
    timestamp = alert.get('timestamp', '')

    issues = status_obj.active_issues  # mutable list reference

    if observer == 'alarm_type':
        # Rebuild from active_alarms in details
        active_alarms = details.get('active_alarms', [])

        # Detect which alarm keys disappeared (recovered)
        old_keys = {i['key'] for i in issues if i.get('observer') == 'alarm_type'}
        new_keys = {f"alarm_type:{al.get('alarm_id', '?')}" for al in active_alarms}
        recovered_keys = old_keys - new_keys
        if recovered_keys:
            _record_recovery(array_id, list(recovered_keys), timestamp)

        # Remove all old alarm_type issues
        status_obj.active_issues = [i for i in issues if i.get('observer') != 'alarm_type']
        # Re-add currently active alarms
        for al in active_alarms:
            aid = al.get('alarm_id', '?')
            otype = al.get('obj_type', '')
            key = f"alarm_type:{aid}"
            # Check if this key had a recovery → it's a relapse
            _pop_recovery(array_id, key)
            status_obj.active_issues.append({
                'key': key,
                'observer': 'alarm_type',
                'level': 'warning',
                'title': _OBSERVER_TITLES['alarm_type'],
                'message': f"AlarmId:{aid} objType:{otype}",
                'details': al,
                'since': al.get('timestamp', timestamp),
                'latest': timestamp,
            })
        return

    # ---- Observers that always rebuild from their detail payload ----
    # These must be processed regardless of alert level, because an info-level
    # report with an empty list means "everything recovered".

    if observer == 'pcie_bandwidth':
        downgrades = details.get('downgrades', [])
        # Detect recovered keys
        old_keys = {i['key'] for i in status_obj.active_issues if i.get('observer') == 'pcie_bandwidth'}
        new_keys = set()
        for dg in downgrades:
            dev = dg.split(' ')[0] if isinstance(dg, str) else '?'
            new_keys.add(f"pcie_bandwidth:{dev}")
        recovered_keys = old_keys - new_keys
        if recovered_keys:
            _record_recovery(array_id, list(recovered_keys), timestamp)

        # Remove old entries, re-add current ones
        status_obj.active_issues = [
            i for i in status_obj.active_issues if i.get('observer') != 'pcie_bandwidth'
        ]
        for dg in downgrades:
            dev = dg.split(' ')[0] if isinstance(dg, str) else '?'
            key = f"pcie_bandwidth:{dev}"
            _pop_recovery(array_id, key)  # relapse → invalidate ack
            status_obj.active_issues.append({
                'key': key,
                'observer': 'pcie_bandwidth',
                'level': level,
                'title': _OBSERVER_TITLES['pcie_bandwidth'],
                'message': dg if isinstance(dg, str) else str(dg),
                'details': details,
                'since': timestamp,
                'latest': timestamp,
            })
        return

    if observer == 'card_info':
        card_alerts = details.get('alerts', [])
        # Detect recovered card keys
        old_keys = {i['key'] for i in status_obj.active_issues if i.get('observer') == 'card_info'}
        new_keys = set()
        for ca in card_alerts:
            card = ca.get('card', '?')
            for fi in ca.get('fields', []):
                field = fi.get('field', '?')
                new_keys.add(f"card_info:{card}:{field}")
        recovered_keys = old_keys - new_keys
        if recovered_keys:
            _record_recovery(array_id, list(recovered_keys), timestamp)

        # Remove old entries, re-add current ones
        status_obj.active_issues = [
            i for i in status_obj.active_issues if i.get('observer') != 'card_info'
        ]
        for ca in card_alerts:
            card = ca.get('card', '?')
            board_id = ca.get('board_id', '')
            label = card
            if board_id:
                label = f"{card} (BoardId:{board_id})"
            for fi in ca.get('fields', []):
                field = fi.get('field', '?')
                value = fi.get('value', '?')
                key = f"card_info:{card}:{field}"
                _pop_recovery(array_id, key)
                status_obj.active_issues.append({
                    'key': key,
                    'observer': 'card_info',
                    'level': fi.get('level', ca.get('level', level)),
                    'title': _OBSERVER_TITLES['card_info'],
                    'message': f"卡件 {label} {field}={value}",
                    'details': ca,
                    'since': timestamp,
                    'latest': timestamp,
                })
        return

    # ---- Observers that use generic recovery logic ----

    # For observers with recovery logic
    recovered = details.get('recovered', False)
    if recovered:
        recovered_keys = [i['key'] for i in issues if i.get('observer') == observer]
        _record_recovery(array_id, recovered_keys, timestamp)
        status_obj.active_issues = [
            i for i in issues if i.get('observer') != observer
        ]
        return

    # Only track WARNING / ERROR level alerts as active issues
    if level not in ('warning', 'error', 'critical'):
        return

    if observer == 'cpu_usage':
        key = 'cpu_usage'
        _pop_recovery(array_id, key)  # relapse after recovery → invalidate ack
        _upsert_issue(status_obj, key, observer, level, message, details, timestamp)

    elif observer == 'memory_leak':
        key = 'memory_leak'
        _pop_recovery(array_id, key)  # relapse after recovery → invalidate ack
        _upsert_issue(status_obj, key, observer, level, message, details, timestamp)

    elif observer == 'port_error_code':
        key = 'port_error_code'
        _pop_recovery(array_id, key)
        _upsert_issue(status_obj, key, observer, level, message, details, timestamp)

    elif observer == 'error_code':
        # 仅误码/PCIe 类别加入 active issues，不含丢包
        by_cat = details.get('by_category', {})
        if by_cat.get('error_code', 0) > 0 or by_cat.get('pcie', 0) > 0:
            key = 'error_code'
            _pop_recovery(array_id, key)
            _upsert_issue(status_obj, key, observer, level, message, details, timestamp)


def _upsert_issue(
    status_obj: ArrayStatus, key: str, observer: str,
    level: str, message: str, details: dict, timestamp: str,
):
    """Insert or update a single active issue by key."""
    for issue in status_obj.active_issues:
        if issue.get('key') == key:
            issue['level'] = level
            issue['message'] = message[:200]
            issue['details'] = details
            issue['latest'] = timestamp
            return
    status_obj.active_issues.append({
        'key': key,
        'observer': observer,
        'level': level,
        'title': _OBSERVER_TITLES.get(observer, observer),
        'message': message[:200],
        'details': details,
        'since': timestamp,
        'latest': timestamp,
    })


async def _derive_active_issues_from_db_batch(
    db: AsyncSession, array_ids: List[str]
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Batch derive active issues from DB for multiple arrays.
    Uses one query to fetch latest alerts per observer and one query to fetch
    acknowledgement rows for all latest alert IDs.
    """
    from ..models.alert import AlertModel, AlertAckModel
    from sqlalchemy import delete as sa_delete

    if not array_ids:
        return {}

    issues_by_array: Dict[str, List[Dict[str, Any]]] = {aid: [] for aid in array_ids}

    ranked_alerts = (
        select(
            AlertModel.id.label("id"),
            AlertModel.array_id.label("array_id"),
            AlertModel.observer_name.label("observer_name"),
            AlertModel.level.label("level"),
            AlertModel.message.label("message"),
            AlertModel.details.label("details"),
            AlertModel.timestamp.label("timestamp"),
            func.row_number()
            .over(
                partition_by=(AlertModel.array_id, AlertModel.observer_name),
                order_by=AlertModel.timestamp.desc(),
            )
            .label("rn"),
        )
        .where(AlertModel.array_id.in_(array_ids))
        .where(AlertModel.observer_name.in_(_ACTIVE_ISSUE_OBSERVERS))
        .subquery()
    )

    rows_result = await db.execute(
        select(
            ranked_alerts.c.id,
            ranked_alerts.c.array_id,
            ranked_alerts.c.observer_name,
            ranked_alerts.c.level,
            ranked_alerts.c.message,
            ranked_alerts.c.details,
            ranked_alerts.c.timestamp,
            ranked_alerts.c.rn,
        ).where(ranked_alerts.c.rn <= 2)
    )

    grouped_rows: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in rows_result.all():
        grouped_rows[row.array_id][row.observer_name].append(
            {
                "id": row.id,
                "level": row.level,
                "message": row.message or "",
                "details": _parse_alert_details(row.details),
                "timestamp": row.timestamp,
                "rn": row.rn,
            }
        )

    latest_alert_ids = []
    for aid in grouped_rows:
        for obs_name in grouped_rows[aid]:
            rows = sorted(grouped_rows[aid][obs_name], key=lambda r: r["rn"])
            if rows:
                latest_alert_ids.append(rows[0]["id"])

    ack_map: Dict[int, AlertAckModel] = {}
    if latest_alert_ids:
        ack_result = await db.execute(
            select(AlertAckModel).where(AlertAckModel.alert_id.in_(latest_alert_ids))
        )
        ack_map = {ack.alert_id: ack for ack in ack_result.scalars().all()}

    stale_ack_ids: List[int] = []

    for array_id in array_ids:
        issues: List[Dict[str, Any]] = []
        observers = grouped_rows.get(array_id, {})

        for obs_name in _ACTIVE_ISSUE_OBSERVERS:
            recent_rows = sorted(observers.get(obs_name, []), key=lambda r: r["rn"])
            if not recent_rows:
                continue

            latest = recent_rows[0]
            alert_id = latest["id"]
            details = latest["details"]

            if details.get("recovered"):
                continue

            suppressed_info = None
            ack_row = ack_map.get(alert_id)
            if ack_row is not None:
                ack_is_stale = False
                if len(recent_rows) >= 2:
                    prev_row = recent_rows[1]
                    prev_details = prev_row["details"]
                    if prev_details.get("recovered"):
                        ack_is_stale = True
                    if obs_name == "card_info" and prev_row["level"] == "info":
                        ack_is_stale = True

                recovery_ts = _recovery_timestamps.get(array_id, {}).get(obs_name)
                if recovery_ts and ack_row.acked_at:
                    try:
                        rec_dt = datetime.fromisoformat(recovery_ts)
                        if rec_dt > ack_row.acked_at:
                            ack_is_stale = True
                    except (ValueError, TypeError):
                        pass

                if not ack_is_stale:
                    suppressed_info = {
                        "suppressed": True,
                        "acked_by_ip": ack_row.acked_by_ip,
                        "ack_expires_at": ack_row.ack_expires_at.isoformat() if ack_row.ack_expires_at else None,
                    }
                else:
                    stale_ack_ids.append(ack_row.id)

            level = latest["level"] or "info"
            message = latest["message"] or ""
            ts = latest["timestamp"].isoformat() if latest["timestamp"] else ""

            if obs_name == "alarm_type":
                for al in details.get("active_alarms", []):
                    aid = al.get("alarm_id", "?")
                    otype = al.get("obj_type", "")
                    issues.append(
                        {
                            "key": f"alarm_type:{aid}",
                            "observer": "alarm_type",
                            "level": "warning",
                            "title": _OBSERVER_TITLES["alarm_type"],
                            "message": f"AlarmId:{aid} objType:{otype}",
                            "details": al,
                            "alert_id": alert_id,
                            "since": al.get("timestamp", ts),
                            "latest": ts,
                            **(suppressed_info or {}),
                        }
                    )
            elif obs_name in ("cpu_usage", "memory_leak"):
                if level in ("warning", "error", "critical"):
                    since_ts = ts
                    for prev_row in reversed(recent_rows[1:]):
                        prev_details = prev_row["details"]
                        if prev_details.get("recovered"):
                            break
                        if prev_row["level"] in ("warning", "error", "critical"):
                            since_ts = prev_row["timestamp"].isoformat() if prev_row["timestamp"] else ts
                    issues.append(
                        {
                            "key": obs_name,
                            "observer": obs_name,
                            "level": level,
                            "title": _OBSERVER_TITLES[obs_name],
                            "message": message[:200],
                            "details": details,
                            "alert_id": alert_id,
                            "since": since_ts,
                            "latest": ts,
                            **(suppressed_info or {}),
                        }
                    )
            elif obs_name == "pcie_bandwidth":
                if level in ("warning", "error", "critical"):
                    for dg in details.get("downgrades", []):
                        dev = dg.split(" ")[0] if isinstance(dg, str) else "?"
                        issues.append(
                            {
                                "key": f"pcie_bandwidth:{dev}",
                                "observer": "pcie_bandwidth",
                                "level": level,
                                "title": _OBSERVER_TITLES["pcie_bandwidth"],
                                "message": dg if isinstance(dg, str) else str(dg),
                                "details": details,
                                "alert_id": alert_id,
                                "since": ts,
                                "latest": ts,
                                **(suppressed_info or {}),
                            }
                        )
            elif obs_name == "card_info":
                if level in ("warning", "error", "critical"):
                    for ca in details.get("alerts", []):
                        card = ca.get("card", "?")
                        board_id = ca.get("board_id", "")
                        label = card
                        if board_id:
                            label = f"{card} (BoardId:{board_id})"
                        for fi in ca.get("fields", []):
                            field = fi.get("field", "?")
                            value = fi.get("value", "?")
                            issues.append(
                                {
                                    "key": f"card_info:{card}:{field}",
                                    "observer": "card_info",
                                    "level": fi.get("level", ca.get("level", level)),
                                    "title": _OBSERVER_TITLES["card_info"],
                                    "message": f"卡件 {label} {field}={value}",
                                    "details": ca,
                                    "alert_id": alert_id,
                                    "since": ts,
                                    "latest": ts,
                                    **(suppressed_info or {}),
                                }
                            )
            elif obs_name == "port_error_code":
                if level in ("warning", "error", "critical"):
                    alerts_list = details.get("alerts", [])
                    msg = "; ".join(alerts_list[:3]) if alerts_list else message[:200]
                    issues.append(
                        {
                            "key": "port_error_code",
                            "observer": "port_error_code",
                            "level": level,
                            "title": _OBSERVER_TITLES["port_error_code"],
                            "message": msg[:200],
                            "details": details,
                            "alert_id": alert_id,
                            "since": ts,
                            "latest": ts,
                            **(suppressed_info or {}),
                        }
                    )
            elif obs_name == "error_code":
                by_cat = details.get("by_category", {})
                if level in ("warning", "error", "critical") and (
                    by_cat.get("error_code", 0) > 0 or by_cat.get("pcie", 0) > 0
                ):
                    issues.append(
                        {
                            "key": "error_code",
                            "observer": "error_code",
                            "level": level,
                            "title": _OBSERVER_TITLES["error_code"],
                            "message": message[:200],
                            "details": details,
                            "alert_id": alert_id,
                            "since": ts,
                            "latest": ts,
                            **(suppressed_info or {}),
                        }
                    )

        issues_by_array[array_id] = issues

    if stale_ack_ids:
        await db.execute(sa_delete(AlertAckModel).where(AlertAckModel.id.in_(set(stale_ack_ids))))
        await db.flush()
        logger.info("Auto-invalidated %s stale ack rows", len(set(stale_ack_ids)))

    ack_ips = list(
        {
            issue.get("acked_by_ip")
            for issues in issues_by_array.values()
            for issue in issues
            if issue.get("suppressed") and issue.get("acked_by_ip")
        }
    )
    if ack_ips:
        nick_map = await _resolve_ips_to_nicknames(db, ack_ips)
        for issues in issues_by_array.values():
            for issue in issues:
                if issue.get("suppressed") and issue.get("acked_by_ip"):
                    issue["acked_by_nickname"] = nick_map.get(issue["acked_by_ip"]) or issue["acked_by_ip"]

    return issues_by_array


async def _derive_active_issues_from_db(db: AsyncSession, array_id: str) -> List[Dict[str, Any]]:
    """Compatibility wrapper around batch active-issues query."""
    result = await _derive_active_issues_from_db_batch(db, [array_id])
    return result.get(array_id, [])


@router.get("", response_model=List[ArrayResponse])
async def list_arrays(
    tag_id: Optional[int] = Query(None, description="Filter by tag ID"),
    db: AsyncSession = Depends(get_db),
):
    """Get all arrays (database records only, no connection state)"""
    from ..models.tag import TagModel

    query = select(ArrayModel)
    if tag_id is not None:
        query = await _expand_l1_tag_filter(query, tag_id, db)

    result = await db.execute(query)
    arrays = result.scalars().all()

    # Fetch tag info and parent names for L2 tags
    tag_ids = {a.tag_id for a in arrays if a.tag_id}
    tags_map = {}
    parent_map = {}
    if tag_ids:
        tag_result = await db.execute(
            select(TagModel).where(TagModel.id.in_(tag_ids))
        )
        tags_map = {t.id: t for t in tag_result.scalars().all()}
        parent_ids = {t.parent_id for t in tags_map.values() if t.parent_id}
        if parent_ids:
            parent_result = await db.execute(
                select(TagModel.id, TagModel.name).where(TagModel.id.in_(parent_ids))
            )
            parent_map = {r[0]: r[1] for r in parent_result.all()}

    def _l1_l2(tag):
        if not tag:
            return None, None
        if tag.level == 2 and tag.parent_id:
            return parent_map.get(tag.parent_id), tag.name
        if tag.level == 1:
            return tag.name, None
        return None, tag.name  # fallback

    responses = []
    for arr in arrays:
        tag = tags_map.get(arr.tag_id) if arr.tag_id else None
        l1, l2 = _l1_l2(tag)
        responses.append(ArrayResponse(
            id=arr.id,
            array_id=arr.array_id,
            name=arr.name,
            host=arr.host,
            port=arr.port,
            username=arr.username,
            key_path=arr.key_path or "",
            folder=arr.folder or "",
            tag_id=arr.tag_id,
            tag_name=tag.name if tag else None,
            tag_color=tag.color if tag else None,
            tag_l1_name=l1,
            tag_l2_name=l2,
            created_at=arr.created_at,
            updated_at=arr.updated_at,
        ))

    return responses


@router.get("/search")
async def search_arrays(
    ip: str = Query(..., description="IP address to search for"),
    db: AsyncSession = Depends(get_db),
):
    """
    Search arrays by IP address.

    Returns matching arrays with their tag information. Used for:
    - Filtering tag cards on main page (shows only tags containing this IP)
    - Filtering arrays within a tag (shows only matching arrays)
    """
    from ..models.tag import TagModel

    result = await db.execute(
        select(ArrayModel).where(ArrayModel.host.contains(ip))
    )
    arrays = result.scalars().all()

    # Fetch tag info
    tag_ids = {a.tag_id for a in arrays if a.tag_id}
    tags_map = {}
    if tag_ids:
        tag_result = await db.execute(
            select(TagModel).where(TagModel.id.in_(tag_ids))
        )
        tags_map = {t.id: t for t in tag_result.scalars().all()}

    # Group arrays by tag
    arrays_by_tag = {}
    untagged_arrays = []
    for arr in arrays:
        tag = tags_map.get(arr.tag_id) if arr.tag_id else None
        arr_info = {
            "id": arr.id,
            "array_id": arr.array_id,
            "name": arr.name,
            "host": arr.host,
            "port": arr.port,
            "tag_id": arr.tag_id,
        }
        if tag:
            if tag.id not in arrays_by_tag:
                arrays_by_tag[tag.id] = {
                    "tag_id": tag.id,
                    "tag_name": tag.name,
                    "tag_color": tag.color,
                    "arrays": [],
                }
            arrays_by_tag[tag.id]["arrays"].append(arr_info)
        else:
            untagged_arrays.append(arr_info)

    return {
        "search_ip": ip,
        "total_count": len(arrays),
        "tags": list(arrays_by_tag.values()),
        "untagged_arrays": untagged_arrays,
    }


@router.get("/statuses", response_model=List[ArrayStatus])
async def list_array_statuses(
    tag_id: Optional[int] = Query(None, description="Filter by tag ID"),
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Get all array statuses with connection state"""
    from ..models.alert import AlertModel
    from ..models.tag import TagModel

    query = select(ArrayModel)
    if tag_id is not None:
        query = await _expand_l1_tag_filter(query, tag_id, db)

    result = await db.execute(query)
    arrays = result.scalars().all()

    # Fetch tag info and parent names for L2 tags
    tag_ids = {a.tag_id for a in arrays if a.tag_id}
    tags_map = {}
    parent_map = {}
    if tag_ids:
        tag_result = await db.execute(
            select(TagModel).where(TagModel.id.in_(tag_ids))
        )
        tags_map = {t.id: t for t in tag_result.scalars().all()}
        parent_ids = {t.parent_id for t in tags_map.values() if t.parent_id}
        if parent_ids:
            parent_result = await db.execute(
                select(TagModel.id, TagModel.name).where(TagModel.id.in_(parent_ids))
            )
            parent_map = {r[0]: r[1] for r in parent_result.all()}

    def _l1_l2(tag):
        if not tag:
            return None, None
        if tag.level == 2 and tag.parent_id:
            return parent_map.get(tag.parent_id), tag.name
        if tag.level == 1:
            return tag.name, None
        return None, tag.name

    # --- Batch preload to avoid N+1 queries ---
    array_ids = [a.array_id for a in arrays]
    need_observer_status = []
    need_active_issues = []

    for array in arrays:
        status_obj = _get_array_status(array.array_id)
        if not status_obj.observer_status:
            need_observer_status.append(array.array_id)
        if not status_obj.active_issues:
            need_active_issues.append(array.array_id)

    # Batch: recent alert summary for ALL arrays (single query)
    from datetime import timedelta
    cutoff_2h = datetime.now() - timedelta(hours=2)
    summary_result = await db.execute(
        select(AlertModel.array_id, AlertModel.level, func.count())
        .where(AlertModel.array_id.in_(array_ids))
        .where(AlertModel.timestamp >= cutoff_2h)
        .group_by(AlertModel.array_id, AlertModel.level)
    )
    summary_map: Dict[str, Dict[str, int]] = {}
    for aid, level, count in summary_result.all():
        summary_map.setdefault(aid, {})[level] = count

    # Batch: observer status for arrays missing cache (single query)
    obs_status_map: Dict[str, Dict] = {}
    if need_observer_status:
        obs_result = await db.execute(
            select(AlertModel.array_id, AlertModel.observer_name, AlertModel.level, AlertModel.message)
            .where(AlertModel.array_id.in_(need_observer_status))
            .order_by(AlertModel.timestamp.desc())
        )
        _level_rank = {'critical': 4, 'error': 3, 'warning': 2, 'info': 1}
        for row in obs_result.all():
            aid_obs = obs_status_map.setdefault(row.array_id, {})
            rank = _level_rank.get(row.level, 0)
            prev = aid_obs.get(row.observer_name)
            if prev is None or rank > prev[0]:
                aid_obs[row.observer_name] = (rank, row.level, row.message or '')

    active_issues_map: Dict[str, list] = {}
    if need_active_issues:
        active_issues_map = await _derive_active_issues_from_db_batch(db, need_active_issues)

    statuses = []
    for array in arrays:
        status_obj = _get_array_status(array.array_id)
        status_obj.name = array.name
        status_obj.host = array.host
        status_obj.has_saved_password = bool(getattr(array, 'saved_password', ''))

        tag = tags_map.get(array.tag_id) if array.tag_id else None
        status_obj.tag_id = array.tag_id
        status_obj.tag_name = tag.name if tag else None
        status_obj.tag_color = tag.color if tag else None
        l1, l2 = _l1_l2(tag)
        status_obj.tag_l1_name = l1
        status_obj.tag_l2_name = l2

        conn = ssh_pool.get_connection(array.array_id)
        if conn:
            status_obj.state = conn.state
            status_obj.last_error = conn.last_error

        # Apply batch-loaded observer status
        if not status_obj.observer_status and array.array_id in obs_status_map:
            for obs_name, (rank, level, msg) in obs_status_map[array.array_id].items():
                obs_status = 'ok'
                if level in ('error', 'critical'):
                    obs_status = 'error'
                elif level == 'warning':
                    obs_status = 'warning'
                status_obj.observer_status[obs_name] = {
                    'status': obs_status,
                    'message': msg[:100],
                }

        # Apply batch-loaded active issues
        if not status_obj.active_issues and array.array_id in active_issues_map:
            status_obj.active_issues = active_issues_map[array.array_id]

        # Apply batch-loaded recent alert summary
        status_obj.recent_alert_summary = summary_map.get(array.array_id, {})

        statuses.append(status_obj)

    return statuses


@router.post("/batch/{action}")
async def batch_action(
    action: str,
    request: BatchActionRequest,
    stream: bool = Query(False, description="Return SSE progress stream"),
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Execute batch operations on multiple arrays.
    
    Supported actions:
    - connect: Connect to arrays (requires password)
    - disconnect: Disconnect from arrays
    - refresh: Refresh array status
    - deploy-agent: Deploy agent to arrays
    - start-agent: Start agent on arrays
    - stop-agent: Stop agent on arrays
    - restart-agent: Restart agent on arrays
    """
    valid_actions = ["connect", "disconnect", "refresh", "deploy-agent", "start-agent", "stop-agent", "restart-agent"]
    if action not in valid_actions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action. Must be one of: {valid_actions}"
        )
    
    if not request.array_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No arrays specified"
        )
    
    array_result = await db.execute(
        select(ArrayModel).where(ArrayModel.array_id.in_(request.array_ids))
    )
    array_map: Dict[str, ArrayModel] = {arr.array_id: arr for arr in array_result.scalars().all()}

    async def _update_saved_password(array_id: str, effective_password: str) -> None:
        """Persist saved password using an isolated DB session for parallel safety."""
        if not AsyncSessionLocal or not effective_password:
            return
        try:
            async with AsyncSessionLocal() as session:
                row = await session.execute(
                    select(ArrayModel).where(ArrayModel.array_id == array_id)
                )
                array = row.scalar_one_or_none()
                if array and array.saved_password != effective_password:
                    array.saved_password = effective_password
                    await session.commit()
        except Exception:
            logger.debug("Failed to persist saved password for %s", array_id)

    async def execute_single(array_id: str) -> Dict[str, Any]:
        """Execute action on a single array"""
        try:
            array = array_map.get(array_id)
            if not array:
                return {"array_id": array_id, "success": False, "error": "Array not found"}
            
            conn = ssh_pool.get_connection(array_id)
            config = get_config()
            
            if action == "connect":
                effective_password = (request.password or getattr(array, "saved_password", "") or "").strip()
                if not conn:
                    conn = ssh_pool.add_connection(
                        array_id=array_id,
                        host=array.host,
                        port=array.port,
                        username=array.username,
                        password=effective_password,
                        key_path=array.key_path or None,
                    )
                else:
                    conn.password = effective_password
                
                success = await _run_blocking(
                    conn.connect,
                    max(15, get_config().ssh.timeout + 5),
                )
                if success:
                    status_obj = _get_array_status(array_id)
                    status_obj.state = conn.state
                    if effective_password and (not array.saved_password or array.saved_password != effective_password):
                        await _update_saved_password(array_id, effective_password)
                    return {"array_id": array_id, "success": True, "message": "Connected"}
                else:
                    return {"array_id": array_id, "success": False, "error": conn.last_error}
            
            elif action == "disconnect":
                ssh_pool.disconnect(array_id)
                status_obj = _get_array_status(array_id)
                status_obj.state = ConnectionState.DISCONNECTED
                return {"array_id": array_id, "success": True, "message": "Disconnected"}
            
            elif action == "refresh":
                if not conn or not conn.is_connected():
                    return {"array_id": array_id, "success": False, "error": "Array not connected"}
                
                deployer = AgentDeployer(conn, config)
                status_obj = _get_array_status(array_id)
                status_obj.agent_deployed = await _run_blocking(deployer.check_deployed, 10)
                status_obj.agent_running = await _run_blocking(deployer.check_running, 10)
                status_obj.last_refresh = datetime.now()
                
                return {"array_id": array_id, "success": True, "message": "Refreshed"}
            
            elif action == "deploy-agent":
                if not conn or not conn.is_connected():
                    return {"array_id": array_id, "success": False, "error": "Array not connected"}
                
                deployer = AgentDeployer(conn, config)
                result = await _run_blocking(deployer.deploy, 120)
                if result.get("ok"):
                    status_obj = _get_array_status(array_id)
                    status_obj.agent_deployed = True
                    return {
                        "array_id": array_id,
                        "success": True,
                        "message": "Agent deployed",
                        "warnings": result.get("warnings", []),
                    }
                else:
                    return {"array_id": array_id, "success": False, "error": result.get("error")}
            
            elif action == "start-agent":
                if not conn or not conn.is_connected():
                    return {"array_id": array_id, "success": False, "error": "Array not connected"}
                
                deployer = AgentDeployer(conn, config)
                result = await _run_blocking(deployer.start_agent, 60)
                if result.get("ok"):
                    status_obj = _get_array_status(array_id)
                    status_obj.agent_running = True
                    return {"array_id": array_id, "success": True, "message": "Agent started"}
                else:
                    return {"array_id": array_id, "success": False, "error": result.get("error")}
            
            elif action == "stop-agent":
                if not conn or not conn.is_connected():
                    return {"array_id": array_id, "success": False, "error": "Array not connected"}
                
                deployer = AgentDeployer(conn, config)
                result = await _run_blocking(deployer.stop_agent, 30)
                if result.get("ok"):
                    status_obj = _get_array_status(array_id)
                    status_obj.agent_running = False
                    return {"array_id": array_id, "success": True, "message": "Agent stopped"}
                else:
                    return {"array_id": array_id, "success": False, "error": result.get("error")}
            
            elif action == "restart-agent":
                if not conn or not conn.is_connected():
                    return {"array_id": array_id, "success": False, "error": "Array not connected"}
                
                deployer = AgentDeployer(conn, config)
                result = await _run_blocking(deployer.restart_agent, 60)
                if result.get("ok"):
                    status_obj = _get_array_status(array_id)
                    status_obj.agent_running = True
                    return {"array_id": array_id, "success": True, "message": "Agent restarted"}
                else:
                    return {"array_id": array_id, "success": False, "error": result.get("error")}
            
            return {"array_id": array_id, "success": False, "error": "Unknown action"}
            
        except Exception as e:
            sys_error("batch", f"Batch action {action} failed for {array_id}", {"error": str(e)})
            return {"array_id": array_id, "success": False, "error": str(e)}

    async def _run_batch() -> Dict[str, Any]:
        max_concurrency = 5
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _with_limit(array_id: str) -> Dict[str, Any]:
            async with semaphore:
                return await execute_single(array_id)

        tasks = [_with_limit(array_id) for array_id in request.array_ids]
        results = await asyncio.gather(*tasks)
        success_count = sum(1 for r in results if r.get("success"))
        sys_info("batch", f"Batch {action} completed", {
            "total": len(request.array_ids),
            "success": success_count,
            "failed": len(request.array_ids) - success_count
        })
        return {
            "action": action,
            "total": len(request.array_ids),
            "success_count": success_count,
            "results": results
        }

    if not stream:
        return await _run_batch()

    async def _sse_stream():
        total = len(request.array_ids)
        completed = 0
        success_count = 0
        results = []
        max_concurrency = 5
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _with_limit(array_id: str) -> Dict[str, Any]:
            async with semaphore:
                return await execute_single(array_id)

        # Kick off event
        yield f"data: {json.dumps({'type': 'start', 'action': action, 'total': total}, ensure_ascii=False)}\n\n"
        tasks = {asyncio.create_task(_with_limit(array_id)): array_id for array_id in request.array_ids}
        for task in asyncio.as_completed(tasks):
            res = await task
            results.append(res)
            completed += 1
            if res.get("success"):
                success_count += 1
            event = {
                "type": "progress",
                "action": action,
                "completed": completed,
                "total": total,
                "success_count": success_count,
                "result": res,
            }
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        summary = {
            "type": "done",
            "action": action,
            "completed": completed,
            "total": total,
            "success_count": success_count,
            "results": results,
        }
        yield f"data: {json.dumps(summary, ensure_ascii=False)}\n\n"

    return StreamingResponse(_sse_stream(), media_type="text/event-stream")


# High-contrast color pool for auto-created tags during import (plan PRESET_COLORS)
_IMPORT_TAG_COLORS = [
    "#409EFF", "#67C23A", "#E6A23C", "#F56C6C", "#909399",
    "#00BCD4", "#9C27B0", "#FF5722", "#795548", "#607D8B",
    "#E91E63", "#3F51B5", "#009688", "#FF9800", "#8BC34A",
    "#CDDC39", "#03A9F4", "#673AB7", "#F44336", "#4CAF50",
]


def _parse_import_file(content: bytes, filename: str) -> List[Dict[str, Any]]:
    """Parse CSV or Excel file into list of dicts. Expected columns: name, host, port?, username?, tag?"""
    import csv
    import io

    name_lower = (filename or "").lower()
    rows = []

    if name_lower.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        for r in reader:
            rows.append({k.strip() if k else k: (v.strip() if v else "") for k, v in (r or {}).items()})
    elif name_lower.endswith((".xlsx", ".xls")):
        try:
            import openpyxl
        except ImportError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Excel support requires openpyxl. Install with: pip install openpyxl",
            )
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        if not ws:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Excel file has no sheets")
        headers = [str(c.value or "").strip() for c in next(ws.iter_rows(min_row=1, max_row=1))]
        for row in ws.iter_rows(min_row=2):
            vals = [str(c.value or "").strip() if c.value is not None else "" for c in row]
            rows.append(dict(zip(headers, vals)))
        wb.close()
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported format. Use .csv or .xlsx",
        )
    return rows


def _normalize_import_row(row: Dict[str, Any]) -> tuple[Optional[Dict[str, Any]], str]:
    """Normalize row to array fields. Returns (None, reason) if row is invalid."""
    # Support common column name variants (case-insensitive)
    def get(key_variants, default=""):
        for k in key_variants:
            for rk, rv in row.items():
                if (rk or "").strip().lower() == k.lower():
                    return (rv or "").strip()
        return default

    name = get(["name", "名称", "array_name"])
    host = get(["host", "ip", "地址", "hostname"])
    if not name and not host:
        return None, "name_and_host_empty"
    if not name:
        return None, "name_empty"
    if not host:
        return None, "host_empty"
    port_s = get(["port", "端口"], "22")
    try:
        port = int(port_s) if port_s else 22
    except ValueError:
        port = 22
    username = get(["username", "user", "用户名"], "root")
    password = get(["password", "密码"], "")
    tag_name = get(["tag", "标签", "tag_name"])
    tag_l1 = get(["tag_l1", "一级标签", "tag_l1_name"])
    tag_l2 = get(["tag_l2", "二级标签", "tag_l2_name"])
    color = get(["color", "颜色"])
    # Validate color if provided
    if color and (not color.startswith("#") or len(color) not in (4, 7)):
        color = ""
    return {
        "name": name,
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "tag_name": tag_name or None,
        "tag_l1": tag_l1 or None,
        "tag_l2": tag_l2 or None,
        "color": color or None,
    }, ""


@router.post("/import")
async def import_arrays(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Import arrays from CSV or Excel. Columns: name, host, port?, username?, tag?, tag_l1?, tag_l2?, color?"""
    from ..models.tag import TagModel
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large (max 10MB)")
    filename = file.filename or ""
    rows = _parse_import_file(content, filename)
    tag_cache: Dict[tuple, int] = {}  # (l1_name or "", l2_name) -> tag_id
    color_idx = [0]

    async def get_or_create_tag_from_import(norm: Dict[str, Any]) -> Optional[int]:
        """Resolve tag_id from tag_l1, tag_l2, tag_name (legacy), color. Arrays use level-2 tag."""
        tag_l1 = (norm.get("tag_l1") or "").strip()
        tag_l2 = (norm.get("tag_l2") or norm.get("tag_name") or "").strip()
        if not tag_l2 and tag_l1:
            tag_l2 = tag_l1
            tag_l1 = ""
        if not tag_l2:
            return None
        color = (norm.get("color") or "").strip()
        if not color or not color.startswith("#") or len(color) not in (4, 7):
            color = _IMPORT_TAG_COLORS[color_idx[0] % len(_IMPORT_TAG_COLORS)]
            color_idx[0] += 1
        cache_key = (tag_l1, tag_l2)
        if cache_key in tag_cache:
            return tag_cache[cache_key]
        parent_id = None
        if tag_l1:
            # Get or create L1 tag
            r1 = await db.execute(select(TagModel).where(TagModel.name == tag_l1))
            l1 = r1.scalar_one_or_none()
            if not l1:
                l1 = TagModel(name=tag_l1, color=color, level=1, parent_id=None)
                db.add(l1)
                await db.flush()
                await db.refresh(l1)
            parent_id = l1.id
        r2 = await db.execute(
            select(TagModel).where(TagModel.name == tag_l2, TagModel.parent_id == parent_id)
        )
        l2 = r2.scalar_one_or_none()
        if not l2:
            l2 = TagModel(name=tag_l2, color=color, level=2, parent_id=parent_id)
            db.add(l2)
            await db.flush()
            await db.refresh(l2)
        tag_cache[cache_key] = l2.id
        return l2.id

    created = 0
    skipped = 0
    invalid = 0
    errors: List[Dict[str, Any]] = []
    existing_hosts = set()
    result = await db.execute(select(ArrayModel.host))
    existing_hosts = {r[0] for r in result.all()}

    for i, row in enumerate(rows):
        norm, reason = _normalize_import_row(row)
        if not norm:
            invalid += 1
            errors.append({"row": i + 2, "reason": reason or "parse_error"})
            logger.info("Import row %s invalid: %s | raw=%s", i + 2, reason, row)
            continue
        host = norm["host"]
        if host in existing_hosts:
            skipped += 1
            errors.append({"row": i + 2, "host": host, "reason": "host_already_exists"})
            continue
        array_id = f"arr_{uuid.uuid4().hex[:8]}"
        try:
            tag_id = await get_or_create_tag_from_import(norm)
            db_array = ArrayModel(
                array_id=array_id,
                name=norm["name"],
                host=host,
                port=norm.get("port", 22),
                username=norm.get("username", "root"),
                saved_password=norm.get("password", ""),
                key_path="",
                folder="",
                tag_id=tag_id,
            )
            db.add(db_array)
            ssh_pool.add_connection(
                array_id=array_id,
                host=host,
                port=norm.get("port", 22),
                username=norm.get("username", "root"),
                password=norm.get("password", ""),
                key_path=None,
            )
            _array_status_cache[array_id] = ArrayStatus(array_id=array_id, name=norm["name"], host=host)
            existing_hosts.add(host)
            created += 1
        except Exception as e:
            logger.exception("Import row %s failed: %s", i + 2, e)
            errors.append({"row": i + 2, "host": host, "reason": str(e)})
    await db.commit()
    return {
        "created": created,
        "skipped": skipped,
        "invalid": invalid,
        "errors": errors,
        "total_rows": len(rows),
    }


@router.post("", response_model=ArrayResponse, status_code=status.HTTP_201_CREATED)
async def create_array(
    array: ArrayCreate,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Create a new array"""
    # Generate unique ID
    array_id = f"arr_{uuid.uuid4().hex[:8]}"
    
    # Check if host already exists
    result = await db.execute(
        select(ArrayModel).where(ArrayModel.host == array.host)
    )
    if result.scalar():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Array with host {array.host} already exists"
        )
    
    # Create database record
    db_array = ArrayModel(
        array_id=array_id,
        name=array.name,
        host=array.host,
        port=array.port,
        username=array.username,
        key_path=array.key_path,
        folder=array.folder,
        tag_id=array.tag_id,
    )

    db.add(db_array)
    await db.commit()
    await db.refresh(db_array)
    
    # Initialize SSH connection (don't connect yet)
    ssh_pool.add_connection(
        array_id=array_id,
        host=array.host,
        port=array.port,
        username=array.username,
        password=array.password,
        key_path=array.key_path or None,
    )
    
    # Initialize status cache
    _array_status_cache[array_id] = ArrayStatus(
        array_id=array_id,
        name=array.name,
        host=array.host,
    )
    
    logger.info(f"Created array: {array.name} ({array.host})")
    return db_array


@router.get("/{array_id}", response_model=ArrayResponse)
async def get_array(
    array_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get array by ID"""
    result = await db.execute(
        select(ArrayModel).where(ArrayModel.array_id == array_id)
    )
    array = result.scalar()
    
    if not array:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Array {array_id} not found"
        )
    
    return array


@router.put("/{array_id}", response_model=ArrayResponse)
async def update_array(
    array_id: str,
    update: ArrayUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Update array with optimistic locking support.

    If expected_version is provided, the update will only succeed if
    the current version matches. This prevents concurrent update conflicts.
    """
    result = await db.execute(
        select(ArrayModel).where(ArrayModel.array_id == array_id)
    )
    array = result.scalar()

    if not array:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Array {array_id} not found"
        )

    # Optimistic locking check
    if update.expected_version is not None:
        current_version = getattr(array, 'version', 1) or 1
        if current_version != update.expected_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"数据已被其他用户修改，请刷新后重试 (expected version {update.expected_version}, current {current_version})"
            )

    # Update fields
    update_data = update.model_dump(exclude_unset=True)
    update_data.pop('expected_version', None)  # Don't set this as a field
    for field, value in update_data.items():
        setattr(array, field, value)

    # Increment version
    array.version = (getattr(array, 'version', 1) or 1) + 1

    await db.commit()
    await db.refresh(array)

    # Update status cache
    if array_id in _array_status_cache:
        if update.name:
            _array_status_cache[array_id].name = update.name
        if update.host:
            _array_status_cache[array_id].host = update.host
    
    return array


@router.delete("/{array_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_array(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Delete array"""
    result = await db.execute(
        select(ArrayModel).where(ArrayModel.array_id == array_id)
    )
    array = result.scalar()
    
    if not array:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Array {array_id} not found"
        )
    
    # Remove SSH connection
    ssh_pool.remove_connection(array_id)
    
    # Remove from status cache
    if array_id in _array_status_cache:
        del _array_status_cache[array_id]
    
    # Delete from database
    await db.delete(array)
    await db.commit()
    
    logger.info(f"Deleted array: {array_id}")


@router.get("/{array_id}/status", response_model=ArrayStatus)
async def get_array_status(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Get array runtime status"""
    # Get array info
    result = await db.execute(
        select(ArrayModel).where(ArrayModel.array_id == array_id)
    )
    array = result.scalar()
    
    if not array:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Array {array_id} not found"
        )
    
    # Get or create status
    status_obj = _get_array_status(array_id)
    status_obj.name = array.name
    status_obj.host = array.host
    
    # Get connection state — lightweight read, no SSH probe or reconnect
    conn = ssh_pool.get_connection(array_id)
    if conn:
        status_obj.state = conn.state  # cached state, no network I/O
        status_obj.last_error = conn.last_error
    
    # If observer_status is empty, derive it from DB alerts
    if not status_obj.observer_status:
        from ..models.alert import AlertModel
        stmt = (
            select(AlertModel.observer_name, AlertModel.level, AlertModel.message)
            .where(AlertModel.array_id == array_id)
            .order_by(AlertModel.timestamp.desc())
        )
        alert_rows = await db.execute(stmt)
        _level_rank = {'critical': 4, 'error': 3, 'warning': 2, 'info': 1}
        _obs_best = {}  # track highest severity per observer
        for row in alert_rows.all():
            obs_name = row.observer_name
            level = row.level
            rank = _level_rank.get(level, 0)
            prev = _obs_best.get(obs_name)
            if prev is None or rank > prev[0]:
                _obs_best[obs_name] = (rank, level, row.message or '')
        for obs_name, (rank, level, msg) in _obs_best.items():
            obs_status = 'ok'
            if level in ('error', 'critical'):
                obs_status = 'error'
            elif level == 'warning':
                obs_status = 'warning'
            status_obj.observer_status[obs_name] = {
                'status': obs_status,
                'message': msg[:100],
            }

    # Derive active_issues from DB if cache is empty
    if not status_obj.active_issues:
        status_obj.active_issues = await _derive_active_issues_from_db(db, array_id)

    # Populate recent alert summary (last 2 hours) for health classification
    status_obj.recent_alert_summary = await _compute_recent_alert_summary(db, array_id)

    # Populate tag info for detail page
    from ..models.tag import TagModel
    status_obj.tag_id = array.tag_id
    if array.tag_id:
        tag_result = await db.execute(select(TagModel).where(TagModel.id == array.tag_id))
        tag = tag_result.scalar_one_or_none()
        if tag:
            status_obj.tag_name = tag.name
            status_obj.tag_color = tag.color
            if tag.level == 2 and tag.parent_id:
                pr = await db.execute(select(TagModel.name).where(TagModel.id == tag.parent_id))
                status_obj.tag_l1_name = pr.scalar_one_or_none()
                status_obj.tag_l2_name = tag.name
            elif tag.level == 1:
                status_obj.tag_l1_name = tag.name
                status_obj.tag_l2_name = None
            else:
                status_obj.tag_l1_name = None
                status_obj.tag_l2_name = tag.name

    return status_obj


class ArrayWatcher(BaseModel):
    """User currently viewing this array"""
    ip: str
    nickname: str = ""
    color: str = ""


@router.get("/{array_id}/watchers", response_model=List[ArrayWatcher])
async def get_array_watchers(
    array_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get list of users currently viewing this array (presence + nickname)."""
    from ..middleware.user_session import get_users_on_page, ip_to_color

    # Verify array exists
    result = await db.execute(select(ArrayModel).where(ArrayModel.array_id == array_id))
    if not result.scalars().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Array {array_id} not found")

    page = f"/arrays/{array_id}"
    watcher_ips = get_users_on_page(page, max_age_seconds=90)
    if not watcher_ips:
        return []

    # Resolve nicknames
    nick_result = await db.execute(
        select(UserSessionModel.ip, UserSessionModel.nickname).where(UserSessionModel.ip.in_(watcher_ips))
    )
    nick_map = {r[0]: (r[1] or "").strip() for r in nick_result.all()}

    return [
        ArrayWatcher(ip=ip, nickname=nick_map.get(ip, "") or "", color=ip_to_color(ip))
        for ip in watcher_ips
    ]


@router.post("/{array_id}/connect")
async def connect_array(
    array_id: str,
    password: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Connect to array.
    
    密码策略：
    1. 如果提供了 password 参数，优先使用
    2. 如果未提供，自动使用数据库中已保存的密码
    3. 连接成功后，自动将密码保存到数据库（下次免密连接）
    """
    # Get array info
    result = await db.execute(
        select(ArrayModel).where(ArrayModel.array_id == array_id)
    )
    array = result.scalar()
    
    if not array:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Array {array_id} not found"
        )
    
    # 密码优先级：参数传入 > 数据库已保存
    effective_password = password or getattr(array, 'saved_password', '') or ''
    
    # Ensure connection exists
    conn = ssh_pool.get_connection(array_id)
    if not conn:
        conn = ssh_pool.add_connection(
            array_id=array_id,
            host=array.host,
            port=array.port,
            username=array.username,
            password=effective_password,
            key_path=array.key_path or None,
        )
    elif effective_password:
        # Update password if we have one
        conn.password = effective_password
    
    # Connect in executor to avoid blocking event loop
    success = await _run_blocking(
        conn.connect,
        max(15, get_config().ssh.timeout + 5),
    )
    
    # Update status
    status_obj = _get_array_status(array_id)
    status_obj.state = conn.state
    status_obj.last_error = conn.last_error
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Connection failed: {conn.last_error}"
        )
    
    # 连接成功 → 保存密码到数据库（下次免密使用）
    if effective_password and (not array.saved_password or array.saved_password != effective_password):
        try:
            array.saved_password = effective_password
            await db.commit()
        except Exception:
            pass  # 保存密码失败不影响连接
    
    # Check agent status
    config = get_config()
    deployer = AgentDeployer(conn, config)
    status_obj.agent_deployed = await _run_blocking(deployer.check_deployed, 10)
    status_obj.agent_running = await _run_blocking(deployer.check_running, 10)

    if not status_obj.agent_deployed:
        return {
            "status": "connected",
            "agent_status": "not_deployed",
            "hint": "Agent 未部署，是否立即部署？",
            "agent_deployed": status_obj.agent_deployed,
            "agent_running": status_obj.agent_running,
            "has_saved_password": True,
        }

    return {
        "status": "connected",
        "agent_deployed": status_obj.agent_deployed,
        "agent_running": status_obj.agent_running,
        "has_saved_password": True,
    }


@router.post("/{array_id}/disconnect")
async def disconnect_array(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Disconnect from array"""
    await _get_array_or_404(array_id, db)
    ssh_pool.disconnect(array_id)
    
    # Update status
    status_obj = _get_array_status(array_id)
    status_obj.state = ConnectionState.DISCONNECTED
    
    return {"status": "disconnected"}


@router.post("/{array_id}/refresh")
async def refresh_array(
    array_id: str,
    full_sync: bool = Query(False, description="Force full sync instead of incremental"),
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Refresh array status and sync alerts incrementally.
    
    Uses tail-based incremental sync to avoid reading the entire alerts.log file.
    Only new lines since last sync are fetched and parsed.
    """
    await _get_array_or_404(array_id, db)
    from ..core.alert_store import get_alert_store
    from ..models.alert import AlertCreate, AlertLevel
    from .websocket import broadcast_alert
    
    from ..core.ssh_pool import tcp_probe

    conn = ssh_pool.get_connection(array_id)

    if not conn:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="阵列未连接，请先添加并连接阵列"
        )

    # Fast-fail: TCP probe before attempting any SSH operation
    reachable = await _run_blocking(tcp_probe, 3, conn.host, conn.port, 2.0)
    if not reachable:
        conn._mark_disconnected()
        status_obj = _get_array_status(array_id)
        status_obj.state = conn.state
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"阵列 {conn.host} 网络不可达，请检查阵列是否在线"
        )

    if not conn.check_alive():
        # TCP OK but SSH dead — try one reconnect
        if not conn._try_reconnect():
            status_obj = _get_array_status(array_id)
            status_obj.state = conn.state
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SSH连接已断开且重连失败，请手动重新连接"
            )
    
    status_obj = _get_array_status(array_id)
    
    # Check agent status — wrap with timeout to prevent stale SSH hangs
    config = get_config()
    deployer = AgentDeployer(conn, config)
    loop = asyncio.get_event_loop()
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
    
    # Get detailed agent info — also timeout-protected
    try:
        agent_info = await asyncio.wait_for(
            loop.run_in_executor(None, deployer.get_agent_status), timeout=10
        )
        status_obj.agent_running = agent_info.get("running", False)
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"Agent info fetch failed for {array_id}: {e}")
        agent_info = {"running": False}
        status_obj.agent_running = False
    
    log_path = config.remote.agent_log_path
    new_alerts_count = 0
    
    try:
        # Step 1: Get total line count of alerts.log (async with timeout protection)
        exit_code, total_str, _ = await conn.execute_async(f"wc -l < {log_path} 2>/dev/null", timeout=5)
        if exit_code != 0:
            # File may not exist yet
            status_obj.last_refresh = datetime.now()
            return {
                "state": status_obj.state.value if hasattr(status_obj.state, 'value') else status_obj.state,
                "agent_deployed": status_obj.agent_deployed,
                "agent_running": status_obj.agent_running,
                "agent_pid": agent_info.get("pid"),
                "new_alerts_synced": 0,
                "observer_status": status_obj.observer_status,
                "last_refresh": status_obj.last_refresh.isoformat() if status_obj.last_refresh else None,
            }
        
        total_lines = int(total_str.strip())
        last_pos = await _get_sync_position(db, array_id)
        
        # Reset position if full_sync or if file was truncated/rotated
        if full_sync or total_lines < last_pos:
            last_pos = 0
        
        new_count = total_lines - last_pos
        
        content = ""
        if new_count > 0:
            # Step 2: Only read new lines using tail
            # Cap at 500 lines per sync to avoid large reads
            read_count = min(new_count, 500)
            exit_code, content, _ = await conn.execute_async(
                f"tail -n {read_count} {log_path} 2>/dev/null", timeout=10
            )
        
        if content and content.strip():
            parsed_alerts = []
            for line in content.strip().split('\n'):
                if not line.strip():
                    continue
                try:
                    alert = json.loads(line)
                    parsed_alerts.append(alert)
                except Exception:
                    pass
            
            if parsed_alerts:
                # Use hash-based dedup (much faster than DB query)
                alert_store = get_alert_store()
                existing_alerts = await alert_store.get_alerts(db, array_id=array_id, limit=100)
                existing_keys = set()
                for a in existing_alerts:
                    key = f"{a.timestamp.isoformat()}_{a.observer_name}_{a.message[:50]}"
                    existing_keys.add(key)
                
                new_alerts = []
                for alert in parsed_alerts:
                    timestamp_str = alert.get('timestamp', '')
                    if not timestamp_str:
                        continue
                    
                    dedup_key = f"{timestamp_str}_{alert.get('observer_name', '')}_{alert.get('message', '')[:50]}"
                    if dedup_key in existing_keys:
                        continue
                    existing_keys.add(dedup_key)
                    
                    try:
                        level_str = alert.get('level', 'info').lower()
                        level = AlertLevel(level_str) if level_str in [l.value for l in AlertLevel] else AlertLevel.INFO
                        
                        alert_create = AlertCreate(
                            array_id=array_id,
                            observer_name=alert.get('observer_name', 'unknown'),
                            level=level,
                            message=alert.get('message', ''),
                            details=alert.get('details', {}),
                            timestamp=datetime.fromisoformat(
                                timestamp_str.replace('Z', '+00:00').replace('+00:00', '')
                            ),
                        )
                        new_alerts.append(alert_create)
                    except Exception as e:
                        sys_error("arrays", f"Failed to parse alert", {"error": str(e)})
                
                if new_alerts:
                    new_alerts_count, created_db_alerts = await alert_store.create_alerts_batch(db, new_alerts)
                    await _auto_ack_new_alerts(db, array_id, created_db_alerts)
                    sys_info("arrays", f"Synced {new_alerts_count} new alerts for {array_id}")
                    
                    for alert in new_alerts[-10:]:
                        await broadcast_alert({
                            'array_id': alert.array_id,
                            'observer_name': alert.observer_name,
                            'level': alert.level.value,
                            'message': alert.message,
                            'timestamp': alert.timestamp.isoformat(),
                        })
                
                # Update observer status from recent alerts
                for alert in parsed_alerts[-50:]:
                    observer = alert.get('observer_name', '')
                    level = alert.get('level', 'info')
                    message = alert.get('message', '')
                    
                    if observer:
                        if level in ('error', 'critical'):
                            status_obj.observer_status[observer] = {
                                'status': 'error',
                                'message': message[:100],
                            }
                        elif level == 'warning':
                            if observer not in status_obj.observer_status or \
                               status_obj.observer_status[observer].get('status') != 'error':
                                status_obj.observer_status[observer] = {
                                    'status': 'warning',
                                    'message': message[:100],
                                }

                # Update active issues from parsed alerts (chronological order)
                for alert in parsed_alerts:
                    _update_active_issues(status_obj, alert)

                # Re-derive from DB to get alert_ids and filter out acked issues
                status_obj.active_issues = await _derive_active_issues_from_db(db, array_id)
        
        # Update sync position in DB (optimistic lock — skip if another instance advanced)
        await _update_sync_position(db, array_id, total_lines, last_pos)
        
    except Exception as e:
        sys_error("arrays", f"Refresh failed for {array_id}", {"error": str(e)})
    
    # Also sync traffic data
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
    
    # Return slim response (no recent_alerts blob)
    return {
        "state": status_obj.state.value if hasattr(status_obj.state, 'value') else status_obj.state,
        "agent_deployed": status_obj.agent_deployed,
        "agent_running": status_obj.agent_running,
        "agent_pid": agent_info.get("pid"),
        "new_alerts_synced": new_alerts_count,
        "observer_status": status_obj.observer_status,
        "last_refresh": status_obj.last_refresh.isoformat() if status_obj.last_refresh else None,
    }


@router.get("/{array_id}/metrics")
async def get_array_metrics(
    array_id: str,
    minutes: int = Query(60, description="Time range in minutes"),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Get performance metrics (CPU, memory) from the remote array.
    
    Reads from the agent's metrics.jsonl file which records time-series data.
    Also checks for pushed metrics from the ingest endpoint.
    """
    from .ingest import get_metrics_for_ip
    
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )
    
    config = get_config()
    metrics_path = config.remote.agent_log_path.replace('alerts.log', 'metrics.jsonl')
    
    # Calculate how many lines to fetch (roughly 6 per minute if 10s interval)
    lines_needed = min(minutes * 6, 2000)
    
    metrics = []
    
    # Try to read from remote metrics.jsonl
    exit_code, content, _ = await _run_blocking(
        conn.execute,
        12,
        f"tail -n {lines_needed} {metrics_path} 2>/dev/null",
        timeout=10,
    )
    
    if exit_code == 0 and content and content.strip():
        for line in content.strip().split('\n'):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                metrics.append(record)
            except Exception:
                pass
    
    # Also check for pushed metrics (by host IP)
    # Find the host IP for this array
    for aid, conn_obj in ssh_pool._connections.items():
        if aid == array_id:
            pushed = get_metrics_for_ip(conn_obj.host, minutes)
            if pushed:
                metrics.extend(pushed)
            break
    
    # Sort by timestamp
    metrics.sort(key=lambda m: m.get('ts', ''))
    
    # Filter to requested time range
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat()
    metrics = [m for m in metrics if m.get('ts', '') >= cutoff]
    
    return {
        "array_id": array_id,
        "minutes": minutes,
        "count": len(metrics),
        "metrics": metrics,
    }


@router.post("/{array_id}/deploy-agent")
async def deploy_agent(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Deploy observation_points agent to array"""
    await _get_array_or_404(array_id, db)
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )

    config = get_config()
    deployer = AgentDeployer(conn, config)
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(loop.run_in_executor(None, deployer.deploy), timeout=120)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Deploy timed out (120s)")
    if not result.get("ok"):
        sys_error(
            "arrays",
            f"Agent deploy failed for array {array_id}",
            {"array_id": array_id, "error": result.get("error")}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Deploy failed")
        )

    await _apply_observer_overrides(conn, config, db)

    status_obj = _get_array_status(array_id)
    status_obj.agent_deployed = await _run_blocking(deployer.check_deployed, 10)
    status_obj.agent_running = await _run_blocking(deployer.check_running, 10)
    sys_info("arrays", f"Agent deployed for array {array_id}", {"array_id": array_id})

    return result


@router.post("/{array_id}/start-agent")
async def start_agent(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Start observation_points agent on array"""
    await _get_array_or_404(array_id, db)
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )

    config = get_config()
    deployer = AgentDeployer(conn, config)
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(loop.run_in_executor(None, deployer.start_agent), timeout=60)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Start agent timed out (60s)")
    if not result.get("ok"):
        sys_error(
            "arrays",
            f"Agent start failed for array {array_id}",
            {"array_id": array_id, "error": result.get("error")}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Start failed")
        )

    status_obj = _get_array_status(array_id)
    status_obj.agent_running = await _run_blocking(deployer.check_running, 10)
    status_obj.agent_deployed = await _run_blocking(deployer.check_deployed, 10)
    sys_info("arrays", f"Agent started for array {array_id}", {"array_id": array_id})

    return result


@router.post("/{array_id}/stop-agent")
async def stop_agent(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Stop observation_points agent on array"""
    await _get_array_or_404(array_id, db)
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )

    config = get_config()
    deployer = AgentDeployer(conn, config)
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(loop.run_in_executor(None, deployer.stop_agent), timeout=30)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Stop agent timed out (30s)")
    if not result.get("ok"):
        sys_error(
            "arrays",
            f"Agent stop failed for array {array_id}",
            {"array_id": array_id, "error": result.get("error")}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Stop failed")
        )

    status_obj = _get_array_status(array_id)
    status_obj.agent_running = await _run_blocking(deployer.check_running, 10)
    status_obj.agent_deployed = await _run_blocking(deployer.check_deployed, 10)
    sys_info("arrays", f"Agent stopped for array {array_id}", {"array_id": array_id})

    return result


@router.post("/{array_id}/restart-agent")
async def restart_agent(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Restart observation_points agent on array"""
    await _get_array_or_404(array_id, db)
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )

    config = get_config()
    deployer = AgentDeployer(conn, config)
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(loop.run_in_executor(None, deployer.restart_agent), timeout=60)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Restart agent timed out (60s)")
    if not result.get("ok"):
        sys_error(
            "arrays",
            f"Agent restart failed for array {array_id}",
            {"array_id": array_id, "error": result.get("error")}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Restart failed")
        )

    status_obj = _get_array_status(array_id)
    status_obj.agent_running = await _run_blocking(deployer.check_running, 10)
    status_obj.agent_deployed = await _run_blocking(deployer.check_deployed, 10)
    sys_info("arrays", f"Agent restarted for array {array_id}", {"array_id": array_id})

    return result


# Allowed log file path prefixes (security: prevent path traversal /etc/shadow etc.)
ALLOWED_LOG_PREFIXES = ("/var/log", "/OSM/log")

# Common log file paths for quick selection
COMMON_LOG_PATHS = [
    "/var/log/messages",
    "/var/log/syslog",
    "/var/log/dmesg",
    "/var/log/auth.log",
    "/var/log/secure",
    "/var/log/kern.log",
]


@router.get("/{array_id}/logs")
async def get_logs(
    array_id: str,
    file_path: str = "/var/log/messages",
    lines: int = 100,
    keyword: Optional[str] = None,
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Get log content from remote array.
    
    Args:
        array_id: Array identifier
        file_path: Path to log file on remote system
        lines: Number of lines to retrieve (from tail)
        keyword: Optional keyword to filter (grep)
    
    Returns:
        Log content and metadata
    """
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )

    # Validate file_path: must be under allowed prefixes, no path traversal
    if ".." in file_path or not any(file_path.startswith(p) for p in ALLOWED_LOG_PREFIXES):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file_path: must start with {ALLOWED_LOG_PREFIXES}"
        )

    safe_path = shlex.quote(file_path)
    safe_keyword = shlex.quote(keyword) if keyword else None

    # Build command - using sudo to read system logs (keyword/path quoted to prevent injection)
    if safe_keyword:
        cmd = f"sudo tail -n {lines * 3} {safe_path} 2>/dev/null | grep -i -e {safe_keyword} | tail -n {lines}"
    else:
        cmd = f"sudo tail -n {lines} {safe_path} 2>/dev/null"
    
    try:
        exit_code, output, error = await _run_blocking(conn.execute, 12, cmd, timeout=10)
        
        if error and "permission denied" in error.lower():
            # Try without sudo
            if safe_keyword:
                cmd = f"tail -n {lines * 3} {safe_path} 2>/dev/null | grep -i -e {safe_keyword} | tail -n {lines}"
            else:
                cmd = f"tail -n {lines} {safe_path} 2>/dev/null"
            exit_code, output, error = await _run_blocking(conn.execute, 12, cmd, timeout=10)
        
        # Get file info
        stat_cmd = f"stat --format='%s %Y' {safe_path} 2>/dev/null || stat -f '%z %m' {safe_path} 2>/dev/null"
        _, stat_output, _ = await _run_blocking(conn.execute, 7, stat_cmd, timeout=5)
        
        file_size = 0
        modified_at = None
        if stat_output and stat_output.strip():
            parts = stat_output.strip().split()
            if len(parts) >= 2:
                try:
                    file_size = int(parts[0])
                    modified_at = datetime.fromtimestamp(int(parts[1])).isoformat()
                except (ValueError, TypeError):
                    pass
        
        return {
            "content": output or "",
            "file_path": file_path,
            "lines_returned": len((output or "").strip().split("\n")) if output else 0,
            "file_size": file_size,
            "modified_at": modified_at,
            "keyword": keyword,
        }
        
    except Exception as e:
        sys_error("logs", f"Failed to read logs from {array_id}", {"file": file_path, "error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read log file: {str(e)}"
        )


@router.get("/{array_id}/log-files")
async def list_log_files(
    array_id: str,
    directory: str = "/var/log",
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    List available log files on remote array.
    
    Args:
        array_id: Array identifier
        directory: Directory to list log files from
    
    Returns:
        List of log files with metadata
    """
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )
    
    # List files with details
    cmd = f"find {directory} -maxdepth 2 -type f \\( -name '*.log' -o -name 'messages*' -o -name 'syslog*' \\) 2>/dev/null | head -50"
    _, output, _ = await _run_blocking(conn.execute, 12, cmd, timeout=10)
    
    files = []
    if output:
        for path in output.strip().split("\n"):
            path = path.strip()
            if not path:
                continue
            
            # Get file info
            stat_cmd = f"stat --format='%s %Y' {path} 2>/dev/null || stat -f '%z %m' {path} 2>/dev/null"
            _, stat_output, _ = await _run_blocking(conn.execute, 7, stat_cmd, timeout=5)
            
            size = 0
            modified = None
            if stat_output and stat_output.strip():
                parts = stat_output.strip().split()
                if len(parts) >= 2:
                    try:
                        size = int(parts[0])
                        modified = datetime.fromtimestamp(int(parts[1])).isoformat()
                    except (ValueError, TypeError):
                        pass
            
            files.append({
                "path": path,
                "name": path.split("/")[-1],
                "size": size,
                "size_human": _format_bytes(size),
                "modified": modified,
            })
    
    # Sort by modification time (newest first)
    files.sort(key=lambda x: x.get("modified") or "", reverse=True)
    
    return {
        "directory": directory,
        "files": files,
        "common_paths": COMMON_LOG_PATHS,
    }


def _format_bytes(size: int) -> str:
    """Format bytes to human readable string"""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _compute_config_hash(content: str) -> str:
    """Compute MD5 hash of config content for optimistic locking."""
    import hashlib
    return hashlib.md5(content.encode('utf-8')).hexdigest()


@router.get("/{array_id}/agent-config")
async def get_agent_config(
    array_id: str,
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Get Agent configuration from remote array.
    
    Returns the current config.json content and a config_hash for optimistic locking.
    """
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )
    
    config = get_config()
    # Get agent deploy path (e.g., /home/permitdir/observation_points)
    agent_path = config.remote.agent_deploy_path
    config_path = f"{agent_path}/config.json"
    
    try:
        content = await _run_blocking(conn.read_file, 10, config_path)
        if not content:
            return {
                "exists": False,
                "config": None,
                "config_path": config_path,
                "config_hash": None,
                "error": "Config file not found or empty"
            }
        
        config_hash = _compute_config_hash(content)
        
        # Parse JSON
        try:
            config_data = json.loads(content)
            return {
                "exists": True,
                "config": config_data,
                "config_path": config_path,
                "config_hash": config_hash,
                "raw": content,
            }
        except json.JSONDecodeError as e:
            return {
                "exists": True,
                "config": None,
                "config_path": config_path,
                "config_hash": config_hash,
                "raw": content,
                "error": f"Invalid JSON: {str(e)}"
            }
            
    except Exception as e:
        sys_error("agent-config", f"Failed to read agent config from {array_id}", {"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read config: {str(e)}"
        )


@router.put("/{array_id}/agent-config")
async def update_agent_config(
    array_id: str,
    body: Dict[str, Any] = Body(...),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Update Agent configuration on remote array.
    
    Writes the config to config.json and optionally restarts the Agent.
    If config_hash is provided in the body, the server re-reads the remote file
    and verifies the hash matches before writing.  A mismatch returns 409 Conflict.
    
    Body fields:
    - restart_agent (bool):  whether to restart agent after save
    - config_hash (str|null): MD5 hash from GET for optimistic locking
    - (all other keys):       treated as the agent config JSON
    """
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )
    
    # Extract control fields from body; the rest is config data
    restart_agent_flag = body.pop("restart_agent", False)
    config_hash = body.pop("config_hash", None)
    config_data = body  # remaining keys are the agent config
    
    config = get_config()
    agent_path = config.remote.agent_deploy_path
    config_path = f"{agent_path}/config.json"
    
    try:
        # Optimistic lock: verify remote file hasn't changed since the client read it
        if config_hash:
            current_content = await _run_blocking(conn.read_file, 10, config_path)
            if current_content:
                current_hash = _compute_config_hash(current_content)
                if current_hash != config_hash:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="配置已被其他人修改，请刷新后重试"
                    )

        # Validate JSON
        config_json = json.dumps(config_data, indent=2, ensure_ascii=False)
        
        # Backup existing config
        backup_cmd = f"cp {config_path} {config_path}.bak 2>/dev/null || true"
        await _run_blocking(conn.execute, 10, backup_cmd)
        
        # Write new config using base64 to avoid shell escaping issues
        import base64
        encoded = base64.b64encode(config_json.encode('utf-8')).decode('ascii')
        write_cmd = f"echo '{encoded}' | base64 -d > {config_path}"
        
        exit_code, output, error = await _run_blocking(conn.execute, 15, write_cmd)
        if exit_code != 0:
            raise Exception(f"Write failed: {error}")
        
        # Verify the write and return new hash
        verify_content = await _run_blocking(conn.read_file, 10, config_path)
        if not verify_content:
            raise Exception("Failed to verify config write")
        
        new_hash = _compute_config_hash(verify_content)
        
        result = {
            "success": True,
            "config_path": config_path,
            "config_hash": new_hash,
            "message": "Configuration updated successfully"
        }
        
        # Optionally restart agent (non-blocking)
        if restart_agent_flag:
            deployer = AgentDeployer(conn, config)
            loop = asyncio.get_event_loop()
            try:
                restart_result = await asyncio.wait_for(
                    loop.run_in_executor(None, deployer.restart_agent), timeout=60
                )
            except asyncio.TimeoutError:
                restart_result = {"ok": False, "error": "restart timed out (60s)"}
            result["agent_restarted"] = restart_result.get("ok", False)
            if not restart_result.get("ok"):
                result["restart_error"] = restart_result.get("error")
        
        sys_info("agent-config", f"Updated agent config for {array_id}", {
            "restart": restart_agent_flag
        })
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        sys_error("agent-config", f"Failed to update agent config for {array_id}", {"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update config: {str(e)}"
        )


@router.post("/{array_id}/agent-config/restore")
async def restore_agent_config(
    array_id: str,
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Restore Agent configuration from backup.
    """
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Array not connected"
        )
    
    config = get_config()
    agent_path = config.remote.agent_deploy_path
    config_path = f"{agent_path}/config.json"
    backup_path = f"{config_path}.bak"
    
    try:
        # Check if backup exists
        check_cmd = f"test -f {backup_path} && echo 'exists'"
        _, output, _ = await _run_blocking(conn.execute, 10, check_cmd)
        
        if "exists" not in (output or ""):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No backup file found"
            )
        
        # Restore from backup
        restore_cmd = f"cp {backup_path} {config_path}"
        exit_code, output, error = await _run_blocking(conn.execute, 10, restore_cmd)
        
        if exit_code != 0:
            raise Exception(f"Restore failed: {error}")
        
        sys_info("agent-config", f"Restored agent config for {array_id}")
        
        return {
            "success": True,
            "message": "Configuration restored from backup"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        sys_error("agent-config", f"Failed to restore agent config for {array_id}", {"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restore config: {str(e)}"
        )
