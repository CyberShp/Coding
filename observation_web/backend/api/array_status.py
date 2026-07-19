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
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..core.ssh_pool import get_ssh_pool, SSHPool
from ..core.status_cache import _array_status_cache, _get_array_status
# Active-issues derivation + recovery tracking now live in core/active_issues.py
# (pure DB/domain logic, moved out of api to break the core->api dependency).
# Imported here for use by the status endpoints below AND re-exported for
# backward compatibility with existing "from .array_status import ..." importers
# (arrays.py, array_alert_sync.py, acknowledgements.py, tests).
from ..core.active_issues import (  # noqa: F401
    _ACTIVE_ISSUE_OBSERVERS,
    _OBSERVER_TITLES,
    _parse_alert_details,
    _resolve_ips_to_nicknames,
    cleanup_stale_acks,
    _recovery_timestamps,
    _record_recovery,
    _pop_recovery,
    _update_active_issues,
    _upsert_issue,
    _derive_active_issues_from_db,
    _derive_active_issues_from_db_batch,
)
from ..models.array import ArrayModel, ArrayStatus, ConnectionState
from ..models.alert import AlertModel, AlertAckModel
from ..models.user_session import UserSessionModel
from ..middleware.user_session import get_users_on_page, ip_to_color

logger = logging.getLogger(__name__)
status_router = APIRouter()

# Status cache (_array_status_cache, _get_array_status) now lives in
# core/status_cache.py to break the core->api dependency. Imported above and
# re-exported here so existing "from .array_status import ..." importers work.

# observer_status only reflects recent activity; bound the derivation query to
# this window so it never scans the full alert history into memory.
OBSERVER_STATUS_WINDOW_HOURS = 24


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


def _apply_built_status(status_obj, built: Dict[str, Any], array) -> None:
    """Copy a build_runtime_status() result onto the cached ArrayStatus.

    Single source of truth for this mapping — used by both list_array_statuses
    and get_array_status so the two endpoints can never drift out of sync (they
    previously carried two identical ~20-line copies of this block).
    """
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
        # Bound to a recent window instead of scanning ALL history into memory —
        # observer status only reflects recent activity, and the old unbounded
        # query loaded hundreds of thousands of rows at 50-array scale.
        obs_cutoff = datetime.now() - timedelta(hours=OBSERVER_STATUS_WINDOW_HOURS)
        obs_result = await db.execute(
            select(AlertModel.array_id, AlertModel.observer_name, AlertModel.level, AlertModel.message)
            .where(AlertModel.array_id.in_(need_observer_status))
            .where(AlertModel.timestamp >= obs_cutoff)
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

        _apply_built_status(status_obj, built, array)

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
        obs_cutoff = datetime.now() - timedelta(hours=OBSERVER_STATUS_WINDOW_HOURS)
        stmt = (
            select(AlertModel.observer_name, AlertModel.level, AlertModel.message, AlertModel.timestamp)
            .where(AlertModel.array_id == array_id)
            .where(AlertModel.timestamp >= obs_cutoff)
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

    _apply_built_status(status_obj, built, array)

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
