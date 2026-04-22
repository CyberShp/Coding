"""
Array status cache, active-issues helpers, and status/presence endpoints.

Owns:
- _array_status_cache (the global in-memory status store)
- Active-issues derivation logic
- GET /arrays/search
- GET /arrays/statuses
- GET /arrays/{array_id}/status
- GET /arrays/{array_id}/watchers
"""
import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..core.ssh_pool import get_ssh_pool, SSHPool
from ..models.array import ArrayModel, ArrayStatus, ConnectionState
from ..models.alert import AlertModel, AlertAckModel
from ..models.user_session import UserSessionModel
from ..middleware.user_session import get_users_on_page, ip_to_color

logger = logging.getLogger(__name__)
status_router = APIRouter()

# ---------------------------------------------------------------------------
# Status cache
# ---------------------------------------------------------------------------

_array_status_cache: Dict[str, ArrayStatus] = {}


def _get_array_status(array_id: str) -> ArrayStatus:
    """Get or create array status from the in-memory cache."""
    if array_id not in _array_status_cache:
        _array_status_cache[array_id] = ArrayStatus(array_id=array_id, name="", host="")
    return _array_status_cache[array_id]


async def _get_array_or_404(array_id: str, db: AsyncSession) -> ArrayModel:
    """Verify array exists in DB, raise 404 if not found."""
    result = await db.execute(select(ArrayModel).where(ArrayModel.array_id == array_id))
    arr = result.scalar_one_or_none()
    if not arr:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Array {array_id} not found",
        )
    return arr


async def _resolve_ips_to_nicknames(db: AsyncSession, ips: List[str]) -> Dict[str, str]:
    """Resolve IP addresses to nicknames from user_sessions."""
    if not ips:
        return {}
    result = await db.execute(
        select(UserSessionModel.ip, UserSessionModel.nickname).where(UserSessionModel.ip.in_(ips))
    )
    return {r[0]: ((r[1] or "").strip()) or r[0] for r in result.all()}


async def _expand_l1_tag_filter(query, tag_id: int, db: AsyncSession):
    """If tag_id is an L1 tag, expand filter to include all child L2 tag arrays."""
    from ..models.tag import TagModel
    tag_check = await db.execute(select(TagModel.level).where(TagModel.id == tag_id))
    tag_level = tag_check.scalar_one_or_none()
    if tag_level == 1:
        child_result = await db.execute(select(TagModel.id).where(TagModel.parent_id == tag_id))
        child_ids = [r[0] for r in child_result.all()]
        all_ids = [tag_id] + child_ids
        return query.where(ArrayModel.tag_id.in_(all_ids))
    return query.where(ArrayModel.tag_id == tag_id)


async def _compute_recent_alert_summary(
    db: AsyncSession, array_id: str, hours: int = 2
) -> Dict[str, int]:
    """Return alert counts by level for the last *hours* hours."""
    from datetime import timedelta
    cutoff = datetime.now() - timedelta(hours=hours)
    result = await db.execute(
        select(AlertModel.level, func.count())
        .where(AlertModel.array_id == array_id)
        .where(AlertModel.timestamp >= cutoff)
        .group_by(AlertModel.level)
    )
    return {level: count for level, count in result.all()}


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


# ---------------------------------------------------------------------------
# Active Issues helpers
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

# Recovery tracking — "recovery invalidates ack"
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


async def _derive_active_issues_from_db_batch(
    db: AsyncSession, array_ids: List[str]
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Batch derive active issues from DB for multiple arrays.
    """
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


# ---------------------------------------------------------------------------
# Presence model
# ---------------------------------------------------------------------------

class ArrayWatcher(BaseModel):
    """User currently viewing this array"""
    ip: str
    nickname: str = ""
    color: str = ""


# ---------------------------------------------------------------------------
# Sub-router endpoints (included into /arrays by arrays.py)
# ---------------------------------------------------------------------------

@status_router.get("/search")
async def search_arrays(
    ip: str = Query(..., description="IP address to search for"),
    db: AsyncSession = Depends(get_db),
):
    """Search arrays by IP address."""
    from ..models.tag import TagModel

    result = await db.execute(select(ArrayModel).where(ArrayModel.host.contains(ip)))
    arrays = result.scalars().all()

    tag_ids = {a.tag_id for a in arrays if a.tag_id}
    tags_map = {}
    if tag_ids:
        tag_result = await db.execute(select(TagModel).where(TagModel.id.in_(tag_ids)))
        tags_map = {t.id: t for t in tag_result.scalars().all()}

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


@status_router.get("/statuses", response_model=List[ArrayStatus])
async def list_array_statuses(
    tag_id: Optional[int] = Query(None, description="Filter by tag ID"),
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Get all array statuses with connection state"""
    from ..models.tag import TagModel

    query = select(ArrayModel)
    if tag_id is not None:
        query = await _expand_l1_tag_filter(query, tag_id, db)

    result = await db.execute(query)
    arrays = result.scalars().all()

    tag_ids = {a.tag_id for a in arrays if a.tag_id}
    tags_map = {}
    parent_map = {}
    if tag_ids:
        tag_result = await db.execute(select(TagModel).where(TagModel.id.in_(tag_ids)))
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

    array_ids = [a.array_id for a in arrays]
    need_observer_status = []
    need_active_issues = []

    for array in arrays:
        status_obj = _get_array_status(array.array_id)
        if not status_obj.observer_status:
            need_observer_status.append(array.array_id)
        if not status_obj.active_issues:
            need_active_issues.append(array.array_id)

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
        tag = tags_map.get(array.tag_id) if array.tag_id else None
        l1, l2 = _l1_l2(tag)
        conn = ssh_pool.get_connection(array.array_id)

        obs_dict = dict(status_obj.observer_status)
        if not obs_dict and array.array_id in obs_status_map:
            for obs_name, (rank, level, msg) in obs_status_map[array.array_id].items():
                obs_status_val = 'ok'
                if level in ('error', 'critical'):
                    obs_status_val = 'error'
                elif level == 'warning':
                    obs_status_val = 'warning'
                obs_dict[obs_name] = {
                    'status': obs_status_val,
                    'message': msg[:100],
                    'last_active_ts': datetime.now().isoformat(),
                }

        issues = status_obj.active_issues
        if not issues and array.array_id in active_issues_map:
            issues = active_issues_map[array.array_id]

        from ..core.runtime_status import build_runtime_status, get_transport_info
        transport = get_transport_info(conn)
        built = build_runtime_status(
            array_id=array.array_id,
            name=array.name,
            host=array.host,
            transport_connected=transport["transport_connected"],
            transport_state=transport["transport_state"],
            last_error=transport["last_error"],
            agent_running=status_obj.agent_running,
            running_source=status_obj.running_source,
            running_confidence=status_obj.running_confidence,
            service_active=status_obj.service_active,
            service_substate=status_obj.service_substate,
            main_pid=status_obj.main_pid,
            pidfile_present=status_obj.pidfile_present,
            pidfile_pid=status_obj.pidfile_pid,
            pidfile_stale=status_obj.pidfile_stale,
            matched_process_cmdline=status_obj.matched_process_cmdline,
            last_heartbeat_at=array.last_heartbeat_at,
            agent_deployed=status_obj.agent_deployed,
            has_saved_password=bool(getattr(array, 'saved_password', '')),
            tag_id=array.tag_id,
            tag_name=tag.name if tag else None,
            tag_color=tag.color if tag else None,
            tag_l1_name=l1,
            tag_l2_name=l2,
            display_name=getattr(array, 'display_name', '') or '',
            enrollment_status=getattr(array, 'enrollment_status', 'draft') or 'draft',
            connection_mode=getattr(array, 'connection_mode', 'ssh_only') or 'ssh_only',
            active_issues=issues,
            recent_alert_summary=summary_map.get(array.array_id, {}),
            observer_status=obs_dict,
        )

        status_obj.name = array.name
        status_obj.host = array.host
        status_obj.state = ConnectionState(built["state"]) if built["state"] in [e.value for e in ConnectionState] else status_obj.state
        status_obj.transport_connected = built["transport_connected"]
        status_obj.agent_healthy = built["agent_healthy"]
        status_obj.collect_status = built["collect_status"]
        status_obj.health_source = built["health_source"]
        status_obj.has_saved_password = built["has_saved_password"]
        status_obj.tag_id = built["tag_id"]
        status_obj.tag_name = built["tag_name"]
        status_obj.tag_color = built["tag_color"]
        status_obj.tag_l1_name = built["tag_l1_name"]
        status_obj.tag_l2_name = built["tag_l2_name"]
        status_obj.last_error = built["last_error"]
        status_obj.active_issues = built["active_issues"]
        status_obj.observer_status = built["observer_status"]
        status_obj.recent_alert_summary = built["recent_alert_summary"]
        status_obj.last_heartbeat_at = array.last_heartbeat_at
        status_obj.status_version = built["status_version"]
        status_obj.updated_at = datetime.fromisoformat(built["updated_at"])

        statuses.append(status_obj)

    return statuses


@status_router.get("/{array_id}/status", response_model=ArrayStatus)
async def get_array_status(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Get array runtime status (uses unified build_runtime_status)"""
    result = await db.execute(select(ArrayModel).where(ArrayModel.array_id == array_id))
    array = result.scalar()
    if not array:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Array {array_id} not found",
        )

    status_obj = _get_array_status(array_id)
    conn = ssh_pool.get_connection(array_id)

    obs_dict = dict(status_obj.observer_status)
    if not obs_dict:
        stmt = (
            select(AlertModel.observer_name, AlertModel.level, AlertModel.message, AlertModel.timestamp)
            .where(AlertModel.array_id == array_id)
            .order_by(AlertModel.timestamp.desc())
        )
        alert_rows = await db.execute(stmt)
        _level_rank = {'critical': 4, 'error': 3, 'warning': 2, 'info': 1}
        _obs_best = {}
        _obs_last_ts = {}
        for row in alert_rows.all():
            obs_name = row.observer_name
            level = row.level
            rank = _level_rank.get(level, 0)
            prev = _obs_best.get(obs_name)
            if prev is None or rank > prev[0]:
                _obs_best[obs_name] = (rank, level, row.message or '')
            if obs_name not in _obs_last_ts and row.timestamp:
                _obs_last_ts[obs_name] = row.timestamp.isoformat() if hasattr(row.timestamp, 'isoformat') else str(row.timestamp)
        for obs_name, (rank, level, msg) in _obs_best.items():
            obs_status_val = 'ok'
            if level in ('error', 'critical'):
                obs_status_val = 'error'
            elif level == 'warning':
                obs_status_val = 'warning'
            obs_dict[obs_name] = {
                'status': obs_status_val,
                'message': msg[:100],
                'last_active_ts': _obs_last_ts.get(obs_name, ''),
            }

    issues = status_obj.active_issues
    if not issues:
        issues = await _derive_active_issues_from_db(db, array_id)

    alert_summary = await _compute_recent_alert_summary(db, array_id)

    from ..models.tag import TagModel
    tag_name = None
    tag_color = None
    tag_l1 = None
    tag_l2 = None
    if array.tag_id:
        tag_result = await db.execute(select(TagModel).where(TagModel.id == array.tag_id))
        tag = tag_result.scalar_one_or_none()
        if tag:
            tag_name = tag.name
            tag_color = tag.color
            if tag.level == 2 and tag.parent_id:
                pr = await db.execute(select(TagModel.name).where(TagModel.id == tag.parent_id))
                tag_l1 = pr.scalar_one_or_none()
                tag_l2 = tag.name
            elif tag.level == 1:
                tag_l1 = tag.name
            else:
                tag_l2 = tag.name

    from ..core.runtime_status import build_runtime_status, get_transport_info
    transport = get_transport_info(conn)
    built = build_runtime_status(
        array_id=array_id,
        name=array.name,
        host=array.host,
        transport_connected=transport["transport_connected"],
        transport_state=transport["transport_state"],
        last_error=transport["last_error"],
        agent_running=status_obj.agent_running,
        running_source=status_obj.running_source,
        running_confidence=status_obj.running_confidence,
        service_active=status_obj.service_active,
        service_substate=status_obj.service_substate,
        main_pid=status_obj.main_pid,
        pidfile_present=status_obj.pidfile_present,
        pidfile_pid=status_obj.pidfile_pid,
        pidfile_stale=status_obj.pidfile_stale,
        matched_process_cmdline=status_obj.matched_process_cmdline,
        last_heartbeat_at=array.last_heartbeat_at,
        agent_deployed=status_obj.agent_deployed,
        has_saved_password=bool(getattr(array, 'saved_password', '')),
        tag_id=array.tag_id,
        tag_name=tag_name,
        tag_color=tag_color,
        tag_l1_name=tag_l1,
        tag_l2_name=tag_l2,
        display_name=getattr(array, 'display_name', '') or '',
        enrollment_status=getattr(array, 'enrollment_status', 'draft') or 'draft',
        connection_mode=getattr(array, 'connection_mode', 'ssh_only') or 'ssh_only',
        active_issues=issues,
        recent_alert_summary=alert_summary,
        observer_status=obs_dict,
    )

    status_obj.name = array.name
    status_obj.host = array.host
    status_obj.state = ConnectionState(built["state"]) if built["state"] in [e.value for e in ConnectionState] else status_obj.state
    status_obj.transport_connected = built["transport_connected"]
    status_obj.agent_healthy = built["agent_healthy"]
    status_obj.collect_status = built["collect_status"]
    status_obj.health_source = built["health_source"]
    status_obj.has_saved_password = built["has_saved_password"]
    status_obj.tag_id = built["tag_id"]
    status_obj.tag_name = built["tag_name"]
    status_obj.tag_color = built["tag_color"]
    status_obj.tag_l1_name = built["tag_l1_name"]
    status_obj.tag_l2_name = built["tag_l2_name"]
    status_obj.last_error = built["last_error"]
    status_obj.active_issues = built["active_issues"]
    status_obj.observer_status = built["observer_status"]
    status_obj.recent_alert_summary = built["recent_alert_summary"]
    status_obj.last_heartbeat_at = array.last_heartbeat_at
    status_obj.status_version = built["status_version"]
    status_obj.updated_at = datetime.fromisoformat(built["updated_at"])

    return status_obj


@status_router.get("/{array_id}/watchers", response_model=List[ArrayWatcher])
async def get_array_watchers(
    array_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get list of users currently viewing this array (presence + nickname)."""
    result = await db.execute(select(ArrayModel).where(ArrayModel.array_id == array_id))
    if not result.scalars().first():
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=f"Array {array_id} not found")

    page = f"/arrays/{array_id}"
    watcher_ips = get_users_on_page(page, max_age_seconds=90)
    if not watcher_ips:
        return []

    nick_result = await db.execute(
        select(UserSessionModel.ip, UserSessionModel.nickname).where(UserSessionModel.ip.in_(watcher_ips))
    )
    nick_map = {r[0]: (r[1] or "").strip() for r in nick_result.all()}

    return [
        ArrayWatcher(ip=ip, nickname=nick_map.get(ip, "") or "", color=ip_to_color(ip))
        for ip in watcher_ips
    ]
