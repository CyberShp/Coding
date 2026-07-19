"""
Active-issues derivation and recovery tracking.

This is pure DB/domain logic (reads AlertModel/AlertAckModel, derives the
per-array "active issues" list, tracks recovery timestamps for the
"recovery invalidates ack" rule). It lives in ``core`` so that low-level
services such as ``core/alert_sync.py`` can call it without importing the
``api`` layer.

``api/array_status.py`` re-exports these symbols for backward compatibility so
existing ``from .array_status import ...`` / ``from .arrays import ...`` call
sites keep working unchanged.
"""
import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.array import ArrayStatus
from ..models.alert import AlertModel, AlertAckModel
from ..models.user_session import UserSessionModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Observer catalog
# ---------------------------------------------------------------------------

_ACTIVE_ISSUE_OBSERVERS = {
    'cpu_usage', 'memory_leak', 'alarm_type', 'pcie_bandwidth', 'card_info',
    'error_code', 'port_error_code',
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
# Small helpers
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


async def _resolve_ips_to_nicknames(db: AsyncSession, ips: List[str]) -> Dict[str, str]:
    """Resolve IP addresses to nicknames from user_sessions."""
    if not ips:
        return {}
    result = await db.execute(
        select(UserSessionModel.ip, UserSessionModel.nickname).where(UserSessionModel.ip.in_(ips))
    )
    return {r[0]: ((r[1] or "").strip()) or r[0] for r in result.all()}


async def cleanup_stale_acks(db) -> int:
    """Physically remove expired dismiss acks. Safe to call from a background task.

    Replaces the state-mutation that used to happen inside GET status endpoints.
    """
    now = datetime.now()
    result = await db.execute(
        sa_delete(AlertAckModel).where(
            AlertAckModel.ack_type == "dismiss",
            AlertAckModel.ack_expires_at.is_not(None),
            AlertAckModel.ack_expires_at < now,
        )
    )
    await db.commit()
    return result.rowcount or 0


# ---------------------------------------------------------------------------
# Recovery tracking — "recovery invalidates ack"
# ---------------------------------------------------------------------------

_recovery_timestamps: Dict[str, Dict[str, str]] = {}  # array_id -> {issue_key -> iso_ts}
_MAX_RECOVERY_ENTRIES = 5000  # cap to prevent unbounded growth of the in-memory map


def _record_recovery(array_id: str, keys: List[str], timestamp: str):
    """Record that the given issue keys have recovered at *timestamp*."""
    bucket = _recovery_timestamps.setdefault(array_id, {})
    for key in keys:
        bucket[key] = timestamp
    # Bound the map: recovery keys that are never matched by _pop_recovery would
    # otherwise accumulate forever.  Keep the most recent half when over cap.
    if len(bucket) > _MAX_RECOVERY_ENTRIES:
        newest = sorted(bucket.items(), key=lambda kv: kv[1], reverse=True)
        _recovery_timestamps[array_id] = dict(newest[: _MAX_RECOVERY_ENTRIES // 2])


def _pop_recovery(array_id: str, key: str) -> Optional[str]:
    """Pop and return the recovery timestamp for *key*, or None."""
    bucket = _recovery_timestamps.get(array_id)
    if bucket:
        return bucket.pop(key, None)
    return None


# ---------------------------------------------------------------------------
# In-memory active-issue update (driven by live alert stream)
# ---------------------------------------------------------------------------

def _update_active_issues(status_obj: ArrayStatus, alert: dict):
    """
    Process a single parsed alert and update ``status_obj.active_issues``.
    """
    observer = alert.get('observer_name', '')
    if observer not in _ACTIVE_ISSUE_OBSERVERS:
        return

    array_id = status_obj.array_id
    details = alert.get('details', {}) or {}
    level = alert.get('level', 'info')
    message = alert.get('message', '')
    timestamp = alert.get('timestamp', '')

    issues = status_obj.active_issues

    if observer == 'alarm_type':
        active_alarms = details.get('active_alarms', [])
        old_keys = {i['key'] for i in issues if i.get('observer') == 'alarm_type'}
        new_keys = {f"alarm_type:{al.get('alarm_id', '?')}" for al in active_alarms}
        recovered_keys = old_keys - new_keys
        if recovered_keys:
            _record_recovery(array_id, list(recovered_keys), timestamp)
        status_obj.active_issues = [i for i in issues if i.get('observer') != 'alarm_type']
        for al in active_alarms:
            aid = al.get('alarm_id', '?')
            otype = al.get('obj_type', '')
            key = f"alarm_type:{aid}"
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

    if observer == 'pcie_bandwidth':
        downgrades = details.get('downgrades', [])
        old_keys = {i['key'] for i in status_obj.active_issues if i.get('observer') == 'pcie_bandwidth'}
        new_keys = set()
        for dg in downgrades:
            dev = dg.split(' ')[0] if isinstance(dg, str) else '?'
            new_keys.add(f"pcie_bandwidth:{dev}")
        recovered_keys = old_keys - new_keys
        if recovered_keys:
            _record_recovery(array_id, list(recovered_keys), timestamp)
        status_obj.active_issues = [
            i for i in status_obj.active_issues if i.get('observer') != 'pcie_bandwidth'
        ]
        for dg in downgrades:
            dev = dg.split(' ')[0] if isinstance(dg, str) else '?'
            key = f"pcie_bandwidth:{dev}"
            _pop_recovery(array_id, key)
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

    recovered = details.get('recovered', False)
    if recovered:
        recovered_keys = [i['key'] for i in issues if i.get('observer') == observer]
        _record_recovery(array_id, recovered_keys, timestamp)
        status_obj.active_issues = [i for i in issues if i.get('observer') != observer]
        return

    if level not in ('warning', 'error', 'critical'):
        return

    if observer == 'cpu_usage':
        key = 'cpu_usage'
        _pop_recovery(array_id, key)
        _upsert_issue(status_obj, key, observer, level, message, details, timestamp)
    elif observer == 'memory_leak':
        key = 'memory_leak'
        _pop_recovery(array_id, key)
        _upsert_issue(status_obj, key, observer, level, message, details, timestamp)
    elif observer == 'port_error_code':
        key = 'port_error_code'
        _pop_recovery(array_id, key)
        _upsert_issue(status_obj, key, observer, level, message, details, timestamp)
    elif observer == 'error_code':
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


# ---------------------------------------------------------------------------
# DB-driven active-issue derivation
# ---------------------------------------------------------------------------

async def _derive_active_issues_from_db_batch(
    db: AsyncSession, array_ids: List[str]
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Batch derive active issues from DB for multiple arrays.
    """
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
        # Do NOT delete here: this runs inside GET status endpoints, and a GET
        # must not mutate state — it breaks idempotency and races real ack
        # writes.  Expired acks are already treated as invalid by the issue
        # derivation above; physical removal is handled by the background sweep
        # cleanup_stale_acks().
        logger.debug("%s stale ack rows pending background cleanup", len(set(stale_ack_ids)))

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
