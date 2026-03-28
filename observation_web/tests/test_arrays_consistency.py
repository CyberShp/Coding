"""Consistency tests for backend/api/arrays.py — deploy, start, status.

Validates:
- deploy-agent: success, success+warnings, failure
- start-agent: success, failure
- status: agent_running consistent with deployer
- End-to-end: deploy → refresh status → running flag correct
"""

import json
import pytest
import pytest_asyncio
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock

from tests.conftest import create_test_array


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_deployer(deploy_ok=True, deploy_warnings=None, start_ok=True,
                   check_running=True, check_deployed=True):
    """Create a mock AgentDeployer for API-level tests."""
    deployer = MagicMock()
    deploy_result = {"ok": deploy_ok, "message": "Deployed successfully"}
    if not deploy_ok:
        deploy_result = {"ok": False, "error": "Deploy failed"}
    elif deploy_warnings:
        deploy_result["warnings"] = deploy_warnings
        deploy_result["message"] += f" (with {len(deploy_warnings)} warning(s))"
    deployer.deploy.return_value = deploy_result

    start_result = {"ok": start_ok}
    if start_ok:
        start_result["message"] = "Agent started (PID: 1234)"
        start_result["pid"] = 1234
    else:
        start_result["error"] = "Start failed"
    deployer.start_agent.return_value = start_result

    deployer.check_running.return_value = check_running
    deployer.check_deployed.return_value = check_deployed
    deployer.stop_agent.return_value = {"ok": True}
    deployer.restart_agent.return_value = {"ok": True, "message": "restarted"}

    return deployer


@pytest.mark.asyncio
class TestDeployAgentAPI:
    """API-level deploy-agent tests."""

    async def test_deploy_success(self, app_client_with_db):
        """deploy-agent success returns 200."""
        client, db = app_client_with_db
        await create_test_array(db, "arr-dep-1", host="10.0.0.1", name="TestArray")
        await db.commit()

        mock_dep = _mock_deployer(deploy_ok=True)
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = True

        with patch("backend.api.arrays.get_ssh_pool") as mock_pool_fn, \
             patch("backend.api.arrays.AgentDeployer", return_value=mock_dep), \
             patch("backend.api.arrays._apply_observer_overrides", new=AsyncMock()):
            mock_pool = MagicMock()
            mock_pool.get_connection.return_value = mock_conn
            mock_pool_fn.return_value = mock_pool

            resp = await client.post("/api/arrays/arr-dep-1/deploy-agent")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    async def test_deploy_success_with_warnings(self, app_client_with_db):
        """deploy-agent success with warnings: 200 OK, not 500."""
        client, db = app_client_with_db
        await create_test_array(db, "arr-dep-2", host="10.0.0.2", name="WarnArray")
        await db.commit()

        mock_dep = _mock_deployer(deploy_ok=True, deploy_warnings=["systemd failed"])
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = True

        with patch("backend.api.arrays.get_ssh_pool") as mock_pool_fn, \
             patch("backend.api.arrays.AgentDeployer", return_value=mock_dep), \
             patch("backend.api.arrays._apply_observer_overrides", new=AsyncMock()):
            mock_pool = MagicMock()
            mock_pool.get_connection.return_value = mock_conn
            mock_pool_fn.return_value = mock_pool

            resp = await client.post("/api/arrays/arr-dep-2/deploy-agent")

        assert resp.status_code == 200, "Deploy with warnings must not return 500"
        data = resp.json()
        assert data["ok"] is True
        assert "warnings" in data

    async def test_deploy_real_failure(self, app_client_with_db):
        """deploy-agent failure returns 500."""
        client, db = app_client_with_db
        await create_test_array(db, "arr-dep-3", host="10.0.0.3", name="FailArray")
        await db.commit()

        mock_dep = _mock_deployer(deploy_ok=False)
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = True

        with patch("backend.api.arrays.get_ssh_pool") as mock_pool_fn, \
             patch("backend.api.arrays.AgentDeployer", return_value=mock_dep):
            mock_pool = MagicMock()
            mock_pool.get_connection.return_value = mock_conn
            mock_pool_fn.return_value = mock_pool

            resp = await client.post("/api/arrays/arr-dep-3/deploy-agent")

        assert resp.status_code == 500

    async def test_deploy_array_not_connected(self, app_client_with_db):
        """deploy-agent on disconnected array returns 400."""
        client, db = app_client_with_db
        await create_test_array(db, "arr-dep-4", host="10.0.0.4", name="DiscoArray")
        await db.commit()

        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = False

        with patch("backend.api.arrays.get_ssh_pool") as mock_pool_fn:
            mock_pool = MagicMock()
            mock_pool.get_connection.return_value = mock_conn
            mock_pool_fn.return_value = mock_pool

            resp = await client.post("/api/arrays/arr-dep-4/deploy-agent")

        assert resp.status_code == 400


@pytest.mark.asyncio
class TestStartAgentAPI:
    """API-level start-agent tests."""

    async def test_start_success(self, app_client_with_db):
        client, db = app_client_with_db
        await create_test_array(db, "arr-st-1", host="10.0.0.10", name="StartOk")
        await db.commit()

        mock_dep = _mock_deployer(start_ok=True)
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = True

        with patch("backend.api.arrays.get_ssh_pool") as mock_pool_fn, \
             patch("backend.api.arrays.AgentDeployer", return_value=mock_dep):
            mock_pool = MagicMock()
            mock_pool.get_connection.return_value = mock_conn
            mock_pool_fn.return_value = mock_pool

            resp = await client.post("/api/arrays/arr-st-1/start-agent")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    async def test_start_failure(self, app_client_with_db):
        client, db = app_client_with_db
        await create_test_array(db, "arr-st-2", host="10.0.0.11", name="StartFail")
        await db.commit()

        mock_dep = _mock_deployer(start_ok=False)
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = True

        with patch("backend.api.arrays.get_ssh_pool") as mock_pool_fn, \
             patch("backend.api.arrays.AgentDeployer", return_value=mock_dep):
            mock_pool = MagicMock()
            mock_pool.get_connection.return_value = mock_conn
            mock_pool_fn.return_value = mock_pool

            resp = await client.post("/api/arrays/arr-st-2/start-agent")

        assert resp.status_code == 500


@pytest.mark.asyncio
class TestStatusConsistency:
    """Status endpoint: agent_running must reflect deployer's check_running()."""

    async def test_status_running_true(self, app_client_with_db):
        client, db = app_client_with_db
        await create_test_array(db, "arr-stat-1", host="10.0.0.20", name="Running")
        await db.commit()

        mock_dep = _mock_deployer(check_running=True, check_deployed=True)
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = True
        mock_conn.state = "connected"
        mock_conn.last_error = ""

        with patch("backend.api.arrays.get_ssh_pool") as mock_pool_fn, \
             patch("backend.api.arrays.AgentDeployer", return_value=mock_dep):
            mock_pool = MagicMock()
            mock_pool.get_connection.return_value = mock_conn
            mock_pool_fn.return_value = mock_pool

            resp = await client.get("/api/arrays/arr-stat-1/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_running"] is True

    async def test_status_running_false(self, app_client_with_db):
        client, db = app_client_with_db
        await create_test_array(db, "arr-stat-2", host="10.0.0.21", name="Stopped")
        await db.commit()

        mock_dep = _mock_deployer(check_running=False, check_deployed=True)
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = True
        mock_conn.state = "connected"
        mock_conn.last_error = ""

        with patch("backend.api.arrays.get_ssh_pool") as mock_pool_fn, \
             patch("backend.api.arrays.AgentDeployer", return_value=mock_dep):
            mock_pool = MagicMock()
            mock_pool.get_connection.return_value = mock_conn
            mock_pool_fn.return_value = mock_pool

            resp = await client.get("/api/arrays/arr-stat-2/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_running"] is False


@pytest.mark.asyncio
class TestDeployRefreshStatusChain:
    """E2E: deploy → refresh status → agent_running correct."""

    async def test_deploy_then_status_reflects_running(self, app_client_with_db):
        """After a successful deploy, querying status should show running if deployer says so."""
        client, db = app_client_with_db
        await create_test_array(db, "arr-chain-1", host="10.0.0.30", name="ChainTest")
        await db.commit()

        mock_dep = _mock_deployer(deploy_ok=True, check_running=True, check_deployed=True)
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = True
        mock_conn.state = "connected"
        mock_conn.last_error = ""

        with patch("backend.api.arrays.get_ssh_pool") as mock_pool_fn, \
             patch("backend.api.arrays.AgentDeployer", return_value=mock_dep), \
             patch("backend.api.arrays._apply_observer_overrides", new=AsyncMock()):
            mock_pool = MagicMock()
            mock_pool.get_connection.return_value = mock_conn
            mock_pool_fn.return_value = mock_pool

            # Step 1: deploy
            resp = await client.post("/api/arrays/arr-chain-1/deploy-agent")
            assert resp.status_code == 200

            # Step 2: get status
            resp = await client.get("/api/arrays/arr-chain-1/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["agent_deployed"] is True
            assert data["agent_running"] is True
