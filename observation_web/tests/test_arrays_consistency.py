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
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from httpx import AsyncClient, ASGITransport

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


def _mock_ssh_pool(connected=True):
    """Create a mock SSH pool with a mock connection."""
    mock_conn = MagicMock()
    mock_conn.is_connected.return_value = connected
    mock_conn.state = "connected" if connected else "disconnected"
    mock_conn.last_error = ""

    mock_pool = MagicMock()
    mock_pool.get_connection.return_value = mock_conn if connected else None
    return mock_pool


@pytest_asyncio.fixture
async def deploy_test_client():
    """Create test client with SSH pool dependency override for deploy/start tests."""
    import backend.db.database as db_mod
    from backend.main import create_app
    from backend.core.ssh_pool import get_ssh_pool

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    old_engine = db_mod._async_engine
    old_session = db_mod.AsyncSessionLocal
    db_mod._async_engine = engine
    db_mod.AsyncSessionLocal = session_factory

    from backend.models import array, alert, query, lifecycle, scheduler, traffic, task_session, snapshot, tag, user_session, user_preference  # noqa: F401
    from backend.db.database import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    mock_pool = _mock_ssh_pool(connected=True)

    app = create_app()
    app.dependency_overrides[get_ssh_pool] = lambda: mock_pool

    transport = ASGITransport(app=app)
    async with session_factory() as session:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, session, mock_pool, app

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    db_mod._async_engine = old_engine
    db_mod.AsyncSessionLocal = old_session


@pytest.mark.asyncio
class TestDeployAgentAPI:
    """API-level deploy-agent tests."""

    async def test_deploy_success(self, deploy_test_client):
        """deploy-agent success returns 200."""
        client, db, mock_pool, app = deploy_test_client
        await create_test_array(db, "arr-dep-1", host="10.0.0.1", name="TestArray")
        await db.commit()

        mock_dep = _mock_deployer(deploy_ok=True)

        with patch("backend.api.arrays.AgentDeployer", return_value=mock_dep), \
             patch("backend.api.arrays._apply_observer_overrides", new=AsyncMock()):
            resp = await client.post("/api/arrays/arr-dep-1/deploy-agent")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    async def test_deploy_success_with_warnings(self, deploy_test_client):
        """deploy-agent success with warnings: 200 OK, not 500."""
        client, db, mock_pool, app = deploy_test_client
        await create_test_array(db, "arr-dep-2", host="10.0.0.2", name="WarnArray")
        await db.commit()

        mock_dep = _mock_deployer(deploy_ok=True, deploy_warnings=["systemd failed"])

        with patch("backend.api.arrays.AgentDeployer", return_value=mock_dep), \
             patch("backend.api.arrays._apply_observer_overrides", new=AsyncMock()):
            resp = await client.post("/api/arrays/arr-dep-2/deploy-agent")

        assert resp.status_code == 200, "Deploy with warnings must not return 500"
        data = resp.json()
        assert data["ok"] is True
        assert "warnings" in data

    async def test_deploy_real_failure(self, deploy_test_client):
        """deploy-agent failure returns 500."""
        client, db, mock_pool, app = deploy_test_client
        await create_test_array(db, "arr-dep-3", host="10.0.0.3", name="FailArray")
        await db.commit()

        mock_dep = _mock_deployer(deploy_ok=False)

        with patch("backend.api.arrays.AgentDeployer", return_value=mock_dep):
            resp = await client.post("/api/arrays/arr-dep-3/deploy-agent")

        assert resp.status_code == 500

    async def test_deploy_array_not_connected(self, deploy_test_client):
        """deploy-agent on disconnected array returns 400."""
        client, db, mock_pool, app = deploy_test_client
        await create_test_array(db, "arr-dep-4", host="10.0.0.4", name="DiscoArray")
        await db.commit()

        # Override to disconnected
        mock_pool.get_connection.return_value = None
        resp = await client.post("/api/arrays/arr-dep-4/deploy-agent")
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestStartAgentAPI:
    """API-level start-agent tests."""

    async def test_start_success(self, deploy_test_client):
        client, db, mock_pool, app = deploy_test_client
        await create_test_array(db, "arr-st-1", host="10.0.0.10", name="StartOk")
        await db.commit()

        mock_dep = _mock_deployer(start_ok=True)

        with patch("backend.api.arrays.AgentDeployer", return_value=mock_dep):
            resp = await client.post("/api/arrays/arr-st-1/start-agent")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    async def test_start_failure(self, deploy_test_client):
        client, db, mock_pool, app = deploy_test_client
        await create_test_array(db, "arr-st-2", host="10.0.0.11", name="StartFail")
        await db.commit()

        mock_dep = _mock_deployer(start_ok=False)

        with patch("backend.api.arrays.AgentDeployer", return_value=mock_dep):
            resp = await client.post("/api/arrays/arr-st-2/start-agent")

        assert resp.status_code == 500


@pytest.mark.asyncio
class TestStatusConsistency:
    """Status endpoint: returns cached agent_running status."""

    async def test_status_reflects_cached_running(self, app_client_with_db):
        """After deploy sets agent_running, status returns that value."""
        client, db = app_client_with_db
        await create_test_array(db, "arr-stat-1", host="10.0.0.20", name="Running")
        await db.commit()

        from backend.api.arrays import _get_array_status
        status_obj = _get_array_status("arr-stat-1")
        status_obj.agent_running = True
        status_obj.agent_deployed = True

        resp = await client.get("/api/arrays/arr-stat-1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_running"] is True

    async def test_status_reflects_not_running(self, app_client_with_db):
        client, db = app_client_with_db
        await create_test_array(db, "arr-stat-2", host="10.0.0.21", name="Stopped")
        await db.commit()

        from backend.api.arrays import _get_array_status
        status_obj = _get_array_status("arr-stat-2")
        status_obj.agent_running = False
        status_obj.agent_deployed = True

        resp = await client.get("/api/arrays/arr-stat-2/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_running"] is False


@pytest.mark.asyncio
class TestDeployRefreshStatusChain:
    """E2E: deploy then status shows correct running state."""

    async def test_deploy_then_status_reflects_running(self, deploy_test_client):
        """After deploy sets agent_running via cache, status reflects it."""
        client, db, mock_pool, app = deploy_test_client
        await create_test_array(db, "arr-chain-1", host="10.0.0.30", name="ChainTest")
        await db.commit()

        mock_dep = _mock_deployer(deploy_ok=True, check_running=True, check_deployed=True)

        with patch("backend.api.arrays.AgentDeployer", return_value=mock_dep), \
             patch("backend.api.arrays._apply_observer_overrides", new=AsyncMock()):
            # Step 1: deploy
            resp = await client.post("/api/arrays/arr-chain-1/deploy-agent")
            assert resp.status_code == 200

        # Step 2: get status
        resp = await client.get("/api/arrays/arr-chain-1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_deployed"] is True
        assert data["agent_running"] is True
