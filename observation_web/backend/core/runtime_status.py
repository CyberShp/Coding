"""
Unified runtime status assembly — single source of truth.

Every status endpoint (/arrays/statuses, /arrays/{id}/status, dashboard
statistics, ingest recovery, etc.) MUST call ``build_runtime_status()``
instead of assembling state fields ad-hoc.

The module also exposes helpers for:
* Recording heartbeat / ingest events  (``record_heartbeat``)
* IP → array_id mapping for ingest  (``register_ip_array_mapping`` / ``resolve_array_id_by_ip``)
* Recovery-driven cache refresh  (``on_recovery_event``)
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from ..models.array import ArrayStatus, ConnectionState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Heartbeat / health tracking  (in-memory, keyed by array_id)
# ---------------------------------------------------------------------------

HEALTHY_WINDOW_SECONDS: int = 120  # configurable

_heartbeat_store: Dict[str, float] = {}       # array_id → epoch timestamp
_health_source_store: Dict[str, str] = {}     # array_id → source label

# IP → array_id mapping for ingest
_ip_to_array_id: Dict[str, str] = {}

# Status version counter (monotonically increasing per array)
_status_versions: Dict[str, int] = {}


def _next_version(array_id: str) -> int:
    v = _status_versions.get(array_id, 0) + 1
    _status_versions[array_id] = v
    return v


# ---------------------------------------------------------------------------
# Heartbeat helpers
# ---------------------------------------------------------------------------

def record_heartbeat(array_id: str, source: str = "heartbeat") -> None:
    """Record that we received a fresh signal from *array_id*."""
    _heartbeat_store[array_id] = time.time()
    _health_source_store[array_id] = source
    logger.debug("Heartbeat recorded for %s via %s", array_id, source)


def get_last_heartbeat(array_id: str) -> Optional[float]:
    return _heartbeat_store.get(array_id)


def is_agent_healthy(array_id: str, window: int = HEALTHY_WINDOW_SECONDS) -> bool:
    last = _heartbeat_store.get(array_id)
    if last is None:
        return False
    return (time.time() - last) < window


# ---------------------------------------------------------------------------
# IP → array_id mapping
# ---------------------------------------------------------------------------

def register_ip_array_mapping(ip: str, array_id: str) -> None:
    _ip_to_array_id[ip] = array_id


def resolve_array_id_by_ip(ip: str) -> Optional[str]:
    return _ip_to_array_id.get(ip)


# ---------------------------------------------------------------------------
# Unified status builder
# ---------------------------------------------------------------------------

def build_runtime_status(
    status_obj: ArrayStatus,
    *,
    ssh_conn: Any = None,
    deployer_info: Optional[Dict[str, Any]] = None,
    probe_mode: str = "cached",
) -> ArrayStatus:
    """Assemble a consistent runtime status snapshot.

    Parameters
    ----------
    status_obj : ArrayStatus
        The mutable cached status object for this array.  It is updated
        **in-place** and also returned for convenience.
    ssh_conn :
        The ``SSHConnection`` from the pool (may be ``None``).
    deployer_info : dict | None
        Result of ``AgentDeployer.get_agent_status()`` when ``probe_mode``
        is ``"strict"``; otherwise the cached ``agent_running`` is kept.
    probe_mode : ``"cached"`` | ``"strict"``
        ``"cached"`` → rely on in-memory state (fast, no SSH).
        ``"strict"`` → use live deployer probe (slower, accurate).
    """
    now = datetime.now()
    array_id = status_obj.array_id

    # 1. Transport / connection state -----------------------------------
    if ssh_conn is not None:
        transport_up = getattr(ssh_conn, "is_connected", lambda: False)()
        status_obj.transport_connected = transport_up
        raw_state = getattr(ssh_conn, "state", ConnectionState.DISCONNECTED)
        status_obj.last_error = getattr(ssh_conn, "last_error", "")
    else:
        transport_up = False
        status_obj.transport_connected = False
        raw_state = ConnectionState.DISCONNECTED

    # 2. Agent running / deployed (strict or cached) --------------------
    if deployer_info is not None:
        status_obj.agent_deployed = deployer_info.get("deployed", False)
        status_obj.agent_running = deployer_info.get("running", False)
        status_obj.running_confidence = deployer_info.get("running_confidence", "low")
        status_obj.running_source = deployer_info.get("running_source", "none")
    # else: keep whatever was cached on status_obj

    # 3. Agent healthy --------------------------------------------------
    healthy = is_agent_healthy(array_id)
    status_obj.agent_healthy = healthy
    last_hb = get_last_heartbeat(array_id)
    if last_hb is not None:
        status_obj.last_heartbeat_at = datetime.fromtimestamp(last_hb)
    status_obj.health_source = _health_source_store.get(array_id, "none")

    # 4. Composite state for display ------------------------------------
    if transport_up:
        if status_obj.agent_running and not healthy:
            status_obj.state = ConnectionState.CONNECTED  # show connected, but agent_healthy=False
        else:
            status_obj.state = raw_state
    else:
        status_obj.state = ConnectionState.DISCONNECTED

    # 5. Collect status -------------------------------------------------
    _recompute_collect_status(status_obj)

    # 6. Metadata -------------------------------------------------------
    status_obj.status_version = _next_version(array_id)
    status_obj.updated_at = now

    return status_obj


# ---------------------------------------------------------------------------
# Collect-status recomputation
# ---------------------------------------------------------------------------

def _recompute_collect_status(status_obj: ArrayStatus) -> None:
    """Derive ``collect_status`` from running + healthy + active_issues."""
    if not status_obj.agent_running:
        status_obj.collect_status = "unknown"
        return

    if status_obj.agent_healthy:
        # If there are error-level active issues, mark degraded
        has_errors = any(
            i.get("level") in ("error", "critical")
            for i in (status_obj.active_issues or [])
        )
        status_obj.collect_status = "degraded" if has_errors else "ok"
    else:
        status_obj.collect_status = "error"


# ---------------------------------------------------------------------------
# Recovery event handler
# ---------------------------------------------------------------------------

async def on_recovery_event(array_id: str, reason: str, *, status_cache: dict = None) -> None:
    """Called when a recovery event occurs — auto-clears stale failure state.

    Triggers:
    * Reconnect success
    * Fresh heartbeat / ingest push
    * Agent running/healthy transition False → True
    * Explicit backend probe success

    Actions:
    1. Update heartbeat
    2. Refresh the unified status cache (including agent_healthy)
    3. Broadcast via status WebSocket
    """
    from ..api.websocket import broadcast_status_update

    logger.info("Recovery event for %s: %s", array_id, reason)
    record_heartbeat(array_id, source=reason)

    # Refresh cached status if cache dict is provided
    if status_cache is not None and array_id in status_cache:
        status_obj = status_cache[array_id]
        # Update healthy based on fresh heartbeat
        status_obj.agent_healthy = is_agent_healthy(array_id)
        last_hb = get_last_heartbeat(array_id)
        if last_hb is not None:
            status_obj.last_heartbeat_at = datetime.fromtimestamp(last_hb)
        status_obj.health_source = _health_source_store.get(array_id, "none")
        # Recompute collect_status and clear stale issues
        _recompute_collect_status(status_obj)
        status_obj.status_version = _next_version(array_id)
        status_obj.updated_at = datetime.now()

        # Broadcast via WebSocket
        await broadcast_status_update(array_id, status_obj.model_dump(mode="json"))
