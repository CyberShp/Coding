from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.arrays import (
    _apply_agent_snapshot,
    _array_status_cache,
    _mark_agent_unknown,
)
from backend.api.ingest import IngestPayload, _handle_metrics
from backend.models.array import AgentState, ArrayStatus, DeploymentState
from backend.api.websocket import ConnectionManager


def test_unknown_probe_preserves_last_confirmed_agent_facts():
    status = ArrayStatus(
        array_id="array-1",
        name="A",
        host="10.0.0.1",
        agent_deployed=True,
        agent_running=True,
        agent_state=AgentState.RUNNING,
    )

    _mark_agent_unknown(
        status,
        "探测超时",
        observed_at=datetime.now(),
        source="test",
    )

    assert status.agent_state == AgentState.UNKNOWN
    assert status.agent_deployed is True
    assert status.agent_running is True


def test_older_process_probe_cannot_overwrite_newer_heartbeat():
    heartbeat_at = datetime.now()
    status = ArrayStatus(
        array_id="array-1",
        name="A",
        host="10.0.0.1",
        agent_deployed=True,
        agent_running=True,
        agent_state=AgentState.RUNNING,
        agent_observed_at=heartbeat_at,
        agent_heartbeat_at=heartbeat_at,
    )

    applied = _apply_agent_snapshot(
        status,
        {"deployed": True, "running": False, "source": "systemd"},
        observed_at=heartbeat_at - timedelta(seconds=1),
    )

    assert applied is False
    assert status.agent_state == AgentState.RUNNING
    assert status.agent_running is True


def test_fast_status_transitions_are_not_throttled_away():
    manager = ConnectionManager()

    assert manager.should_send_status("array-1", {"deployment_state": "deploying"}) is True
    assert manager.should_send_status("array-1", {"deployment_state": "succeeded"}) is True
    assert manager.should_send_status("array-1", {"deployment_state": "succeeded"}) is False


@pytest.mark.asyncio
async def test_agent_health_heartbeat_updates_live_status():
    _array_status_cache.clear()
    _array_status_cache["array-health"] = ArrayStatus(
        array_id="array-health",
        name="health",
        host="10.0.0.2",
        deployment_state=DeploymentState.VERIFYING,
    )
    payload = IngestPayload(
        type="metrics",
        array_id="array-health",
        observer="__agent_health__",
        agent_health={
            "cpu_usage": {"status": "ok"},
            "port_fec": {"status": "degraded", "last_error": "命令超时"},
        },
    )

    with patch("backend.api.arrays._publish_array_status", new=AsyncMock()) as publish:
        result = await _handle_metrics(payload, "10.0.0.2")

    status = _array_status_cache["array-health"]
    assert result == {"ok": True}
    assert status.agent_running is True
    assert status.agent_state == AgentState.DEGRADED
    assert status.agent_status_source == "agent_heartbeat"
    assert status.deployment_state == DeploymentState.SUCCEEDED
    assert status.observer_status["port_fec"]["status"] == "warning"
    publish.assert_awaited_once()
    _array_status_cache.clear()
