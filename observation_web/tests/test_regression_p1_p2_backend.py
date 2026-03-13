"""P1/P2 backend regression tests."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from backend.config import AppConfig
from backend.core.agent_deployer import AgentDeployer
from backend.models.alert import AlertModel
from backend.models.task_session import TaskSessionModel


class TestDeployWarningTolerance:
    """P1: deploy succeeds even with non-critical observer warnings."""

    def _make_deployer(self, connected=True):
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = connected
        mock_conn.host = "10.0.0.1"
        mock_conn.execute.return_value = (0, "", "")
        mock_conn.upload_file.return_value = (True, "")
        config = AppConfig()
        return AgentDeployer(mock_conn, config)

    @patch.object(AgentDeployer, "_build_package", return_value="/tmp/test.tar.gz")
    @patch.object(
        AgentDeployer,
        "start_agent",
        return_value={"ok": True, "message": "started", "pid": 1234, "warnings": ["observer x failed"]},
    )
    @patch("pathlib.Path.exists", return_value=False)
    def test_deploy_propagates_warnings_but_keeps_success(self, _exists, _start, _build):
        deployer = self._make_deployer(connected=True)
        result = deployer.deploy()
        assert result["ok"] is True
        assert "warnings" in result
        assert result["warnings"] == ["observer x failed"]


@pytest.mark.asyncio
class TestTaskExpectedObservers:
    """P2: expected_observers selector and summary expected/unexpected counts."""

    async def test_create_task_persists_expected_observers(self, app_client):
        payload = {
            "name": "P2 expected observers",
            "task_type": "custom",
            "array_ids": ["arr-eo-1"],
            "expected_observers": ["card_info", "start_work"],
            "notes": "regression",
        }
        resp = await app_client.post("/api/test-tasks", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["expected_observers"] == ["card_info", "start_work"]

        task_id = data["id"]
        get_resp = await app_client.get(f"/api/test-tasks/{task_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["expected_observers"] == ["card_info", "start_work"]

    async def test_summary_counts_expected_and_unexpected_alerts(self, app_client_with_db):
        client, db = app_client_with_db

        started_at = datetime.now() - timedelta(minutes=10)
        ended_at = datetime.now() - timedelta(minutes=5)
        task = TaskSessionModel(
            name="P2 summary split",
            task_type="custom",
            array_ids=json.dumps(["arr-eo-2"]),
            expected_observers=json.dumps(["card_info"], ensure_ascii=False),
            status="completed",
            started_at=started_at,
            ended_at=ended_at,
        )
        db.add(task)
        await db.flush()

        db.add_all(
            [
                AlertModel(
                    array_id="arr-eo-2",
                    observer_name="card_info",
                    level="warning",
                    message="expected alert",
                    details="{}",
                    timestamp=started_at + timedelta(minutes=1),
                ),
                AlertModel(
                    array_id="arr-eo-2",
                    observer_name="cpu_usage",
                    level="error",
                    message="unexpected alert",
                    details="{}",
                    timestamp=started_at + timedelta(minutes=2),
                ),
            ]
        )
        await db.commit()

        resp = await client.get(f"/api/test-tasks/{task.id}/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["alert_total"] == 2
        assert data["expected_count"] == 1
        assert data["unexpected_count"] == 1
        assert data["by_observer"]["card_info"] == 1
        assert data["by_observer"]["cpu_usage"] == 1
