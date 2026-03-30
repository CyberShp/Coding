"""
Unified runtime status assembly for arrays.

Single source of truth for array state, agent running/healthy status,
connection state, collect status, and active issues.

All status endpoints (list_array_statuses, get_array_status, dashboard stats)
MUST use ``build_runtime_status`` instead of assembling status independently.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..models.array import ConnectionState

logger = logging.getLogger(__name__)

# ── Configurable thresholds ──────────────────────────────────────────────
HEALTHY_WINDOW_SECONDS = 120  # heartbeat within this window → healthy
DEGRADED_WINDOW_SECONDS = 300  # heartbeat within this but > HEALTHY → degraded

# ── Status version counter (monotonically increasing) ────────────────────
_status_version_counter = 0


def _next_version() -> int:
    global _status_version_counter
    _status_version_counter += 1
    return _status_version_counter


def build_runtime_status(
    *,
    array_id: str,
    name: str,
    host: str,
    # SSH/transport layer
    transport_connected: bool = False,
    transport_state: str = "disconnected",
    last_error: str = "",
    # Agent detection result (from _resolve_running_state)
    agent_running: bool = False,
    running_source: str = "none",
    running_confidence: str = "low",
    service_active: bool = False,
    service_substate: str = "",
    main_pid: Optional[int] = None,
    pidfile_present: bool = False,
    pidfile_pid: Optional[int] = None,
    pidfile_stale: bool = False,
    matched_process_cmdline: str = "",
    # Health signals
    last_heartbeat_at: Optional[datetime] = None,
    last_push_at: Optional[datetime] = None,
    # Issues & alerts (pre-computed by caller)
    active_issues: Optional[List[Dict[str, Any]]] = None,
    recent_alert_summary: Optional[Dict[str, int]] = None,
    observer_status: Optional[Dict[str, Dict[str, str]]] = None,
    # Extra display fields
    agent_deployed: bool = False,
    has_saved_password: bool = False,
    tag_id: Optional[int] = None,
    tag_name: Optional[str] = None,
    tag_color: Optional[str] = None,
    tag_l1_name: Optional[str] = None,
    tag_l2_name: Optional[str] = None,
    display_name: str = "",
    enrollment_status: str = "draft",
    connection_mode: str = "ssh_only",
) -> Dict[str, Any]:
    """Assemble a single, canonical runtime status dict for an array.

    Parameters come from:
    - SSH pool (transport_connected, transport_state, last_error)
    - AgentDeployer._resolve_running_state (agent_running, running_source, …)
    - DB queries (last_heartbeat_at, active_issues, recent_alert_summary)
    - Array model (name, host, tag_*, enrollment_status, …)

    The returned dict is the **only** shape that should be sent to the frontend.
    """

    now = datetime.now()

    # ── Derive agent_healthy ─────────────────────────────────────────────
    agent_healthy = False
    health_source = "none"
    latest_signal: Optional[datetime] = None

    for signal_ts, source_name in [
        (last_heartbeat_at, "heartbeat"),
        (last_push_at, "push"),
    ]:
        if signal_ts and (latest_signal is None or signal_ts > latest_signal):
            latest_signal = signal_ts
            health_source = source_name

    if agent_running and latest_signal:
        age = (now - latest_signal).total_seconds()
        if age <= HEALTHY_WINDOW_SECONDS:
            agent_healthy = True

    # ── Derive composite *state* ─────────────────────────────────────────
    if transport_connected:
        if agent_running and agent_healthy:
            state = "connected"
        elif agent_running and not agent_healthy:
            state = "degraded"
        else:
            state = "connected"  # transport up, agent may not be deployed
    else:
        state = "disconnected"

    # ── Derive collect_status ────────────────────────────────────────────
    if not transport_connected:
        collect_status = "unreachable"
    elif not agent_deployed:
        collect_status = "not_deployed"
    elif not agent_running:
        collect_status = "agent_stopped"
    elif not agent_healthy:
        collect_status = "no_heartbeat"
    else:
        collect_status = "ok"

    return {
        # Primary state
        "array_id": array_id,
        "name": name,
        "host": host,
        "state": state,
        "transport_connected": transport_connected,
        "agent_running": agent_running,
        "agent_healthy": agent_healthy,
        "collect_status": collect_status,
        "active_issues": active_issues or [],
        "last_heartbeat_at": last_heartbeat_at.isoformat() if last_heartbeat_at else None,
        "running_source": running_source,
        "health_source": health_source,
        "updated_at": now.isoformat(),
        "status_version": _next_version(),
        # Connection details
        "last_error": last_error,
        # Agent detection diagnostics
        "agent_deployed": agent_deployed,
        "running_confidence": running_confidence,
        "service_active": service_active,
        "service_substate": service_substate,
        "main_pid": main_pid,
        "pidfile_present": pidfile_present,
        "pidfile_pid": pidfile_pid,
        "pidfile_stale": pidfile_stale,
        "matched_process_cmdline": matched_process_cmdline,
        # Display / metadata
        "has_saved_password": has_saved_password,
        "tag_id": tag_id,
        "tag_name": tag_name,
        "tag_color": tag_color,
        "tag_l1_name": tag_l1_name,
        "tag_l2_name": tag_l2_name,
        "display_name": display_name,
        "enrollment_status": enrollment_status,
        "connection_mode": connection_mode,
        # Alerts
        "recent_alert_summary": recent_alert_summary or {},
        "observer_status": observer_status or {},
        "recent_alerts": [],
    }


# ── Convenience: detect transport state from SSHConnection ───────────────

def get_transport_info(conn) -> Dict[str, Any]:
    """Extract transport info from an SSHConnection object (or None)."""
    if conn is None:
        return {
            "transport_connected": False,
            "transport_state": "disconnected",
            "last_error": "",
        }
    state_val = conn.state.value if hasattr(conn.state, "value") else str(conn.state)
    return {
        "transport_connected": state_val == "connected",
        "transport_state": state_val,
        "last_error": conn.last_error or "",
    }


# ── Recovery event handling ──────────────────────────────────────────────

async def handle_recovery_event(
    array_id: str,
    event_type: str,
    ssh_pool=None,
    db_session=None,
):
    """Trigger status cache update + WebSocket broadcast on recovery.

    Called when:
    - Auto-reconnect succeeds
    - New agent heartbeat received
    - New valid ingest push received
    - Agent running/healthy transitions from False → True

    ``event_type`` is one of: 'reconnect', 'heartbeat', 'ingest_push', 'probe_success'
    """
    from ..api.websocket import broadcast_status_update

    logger.info(
        "Recovery event for array %s: %s",
        array_id,
        event_type,
        extra={"array_id": array_id, "event_type": event_type},
    )

    # Re-build status (caller should update cache) and broadcast
    # The actual cache update is done by the caller who has the full context.
    # Here we just ensure the WebSocket broadcast happens.
    await broadcast_status_update(array_id, {
        "event": "recovery",
        "event_type": event_type,
        "array_id": array_id,
        "timestamp": datetime.now().isoformat(),
    })
