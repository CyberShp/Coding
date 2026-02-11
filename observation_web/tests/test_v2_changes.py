"""
Tests for v2 changes:
  1. SSH connection resilience (is_connected/check_alive/ensure_connected refactor)
  2. TCP probe pre-check
  3. Alert auto-refresh (frontend — not tested here, covered by manual QA)
  4. Enhanced health check (recent_alert_summary)
  5. Acknowledgement workflow (ack_type, expiry, recovery-invalidates-ack)
  6. Agent deployment staging upload + auto-redeploy config
"""

import json
import socket
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.config import AppConfig, RemoteConfig
from backend.core.agent_deployer import AgentDeployer
from backend.core.ssh_pool import SSHConnection, SSHPool, tcp_probe, get_ssh_pool
from backend.models.alert import (
    AlertLevel, AlertModel, AlertAckModel, AlertAckCreate, AlertAckResponse, AckType,
)
from backend.models.array import ArrayModel, ArrayStatus, ConnectionState


# ═══════════════════════════════════════════════════════════════════════════
# 1. TCP Probe
# ═══════════════════════════════════════════════════════════════════════════

class TestTcpProbe:
    """Tests for the new tcp_probe() utility."""

    def test_probe_unreachable_host(self):
        """An unreachable host should return False within the timeout."""
        # 192.0.2.1 is TEST-NET, guaranteed unreachable
        result = tcp_probe("192.0.2.1", 22, timeout=0.5)
        assert result is False

    def test_probe_invalid_host(self):
        """A non-resolving hostname should return False."""
        result = tcp_probe("this.host.does.not.exist.invalid", 22, timeout=0.5)
        assert result is False

    @patch("backend.core.ssh_pool.socket.create_connection")
    def test_probe_success(self, mock_create_conn):
        """When TCP connect succeeds, probe returns True."""
        mock_sock = MagicMock()
        mock_create_conn.return_value.__enter__ = MagicMock(return_value=mock_sock)
        mock_create_conn.return_value.__exit__ = MagicMock(return_value=False)
        result = tcp_probe("10.0.0.1", 22, timeout=2.0)
        assert result is True

    @patch("backend.core.ssh_pool.socket.create_connection", side_effect=OSError("refused"))
    def test_probe_connection_refused(self, _):
        """Connection refused should return False."""
        result = tcp_probe("10.0.0.1", 22, timeout=2.0)
        assert result is False

    @patch("backend.core.ssh_pool.socket.create_connection", side_effect=socket.timeout("timed out"))
    def test_probe_timeout(self, _):
        """Socket timeout should return False."""
        result = tcp_probe("10.0.0.1", 22, timeout=2.0)
        assert result is False


# ═══════════════════════════════════════════════════════════════════════════
# 2. SSH Connection — refactored methods
# ═══════════════════════════════════════════════════════════════════════════

class TestSSHConnectionRefactored:
    """Tests for the refactored is_connected / check_alive / ensure_connected."""

    def test_is_connected_no_client(self):
        conn = SSHConnection("a1", "10.0.0.1", 22, "root")
        assert conn.is_connected() is False

    def test_is_connected_active_transport(self):
        """is_connected returns True when transport reports active."""
        conn = SSHConnection("a1", "10.0.0.1", 22, "root")
        mock_client = MagicMock()
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = True
        mock_client.get_transport.return_value = mock_transport
        conn._client = mock_client
        assert conn.is_connected() is True

    def test_is_connected_inactive_transport(self):
        """is_connected returns False when transport is inactive — NO reconnect."""
        conn = SSHConnection("a1", "10.0.0.1", 22, "root")
        mock_client = MagicMock()
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = False
        mock_client.get_transport.return_value = mock_transport
        conn._client = mock_client
        assert conn.is_connected() is False

    def test_is_connected_no_transport(self):
        conn = SSHConnection("a1", "10.0.0.1", 22, "root")
        mock_client = MagicMock()
        mock_client.get_transport.return_value = None
        conn._client = mock_client
        assert conn.is_connected() is False

    def test_check_alive_succeeds(self):
        conn = SSHConnection("a1", "10.0.0.1", 22, "root")
        mock_client = MagicMock()
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = True
        mock_client.get_transport.return_value = mock_transport
        conn._client = mock_client
        conn._state = ConnectionState.CONNECTED
        assert conn.check_alive() is True

    def test_check_alive_probe_fails(self):
        """send_ignore raises → check_alive returns False, state becomes DISCONNECTED."""
        conn = SSHConnection("a1", "10.0.0.1", 22, "root")
        mock_client = MagicMock()
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = True
        mock_transport.send_ignore.side_effect = EOFError("dead")
        mock_client.get_transport.return_value = mock_transport
        conn._client = mock_client
        conn._state = ConnectionState.CONNECTED
        assert conn.check_alive() is False
        assert conn._state == ConnectionState.DISCONNECTED

    def test_check_alive_not_connected(self):
        conn = SSHConnection("a1", "10.0.0.1", 22, "root")
        assert conn.check_alive() is False

    @patch("backend.core.ssh_pool.tcp_probe", return_value=False)
    def test_ensure_connected_tcp_fails(self, _):
        """ensure_connected falls through to _try_reconnect which TCP-probes first."""
        conn = SSHConnection("a1", "10.0.0.1", 22, "root", password="pw")
        # No client → check_alive False → _try_reconnect → tcp_probe False
        assert conn.ensure_connected() is False

    def test_mark_disconnected(self):
        conn = SSHConnection("a1", "10.0.0.1", 22, "root")
        conn._client = MagicMock()
        conn._sftp = MagicMock()
        conn._state = ConnectionState.CONNECTED
        conn._mark_disconnected()
        assert conn._state == ConnectionState.DISCONNECTED
        assert conn._client is None
        assert conn._sftp is None

    @patch("backend.core.ssh_pool.tcp_probe", return_value=False)
    def test_connect_tcp_probe_fails(self, _):
        """connect() should fail fast when TCP probe returns False."""
        conn = SSHConnection("a1", "192.0.2.1", 22, "root", password="pw")
        result = conn.connect()
        assert result is False
        assert conn._state == ConnectionState.DISCONNECTED
        assert "unreachable" in conn.last_error.lower()

    @patch("backend.core.ssh_pool.tcp_probe", return_value=False)
    def test_try_reconnect_tcp_probe_fails(self, _):
        """_try_reconnect should skip SSH when TCP probe fails."""
        conn = SSHConnection("a1", "192.0.2.1", 22, "root", password="pw")
        result = conn._try_reconnect()
        assert result is False


# ═══════════════════════════════════════════════════════════════════════════
# 3. Config — new RemoteConfig fields
# ═══════════════════════════════════════════════════════════════════════════

class TestRemoteConfigNewFields:
    def test_defaults(self):
        rc = RemoteConfig()
        assert rc.upload_staging_path == "/home/permitdir"
        assert rc.auto_redeploy is True

    def test_custom_values(self):
        rc = RemoteConfig(upload_staging_path="/tmp/staging", auto_redeploy=False)
        assert rc.upload_staging_path == "/tmp/staging"
        assert rc.auto_redeploy is False

    def test_app_config_save_includes_new_fields(self):
        import tempfile, json
        from pathlib import Path
        c = AppConfig()
        c.remote.upload_staging_path = "/custom/path"
        c.remote.auto_redeploy = False
        fp = Path(tempfile.mktemp(suffix=".json"))
        try:
            c.save(fp)
            data = json.loads(fp.read_text())
            assert data["remote"]["upload_staging_path"] == "/custom/path"
            assert data["remote"]["auto_redeploy"] is False
        finally:
            fp.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════
# 4. AlertAckModel — new fields and AckType enum
# ═══════════════════════════════════════════════════════════════════════════

class TestAckTypeEnum:
    def test_values(self):
        assert AckType.DISMISS.value == "dismiss"
        assert AckType.CONFIRMED_OK.value == "confirmed_ok"
        assert AckType.DEFERRED.value == "deferred"


class TestAlertAckCreateSchema:
    def test_defaults(self):
        body = AlertAckCreate(alert_ids=[1, 2])
        assert body.ack_type == "dismiss"
        assert body.expires_hours is None

    def test_deferred_with_hours(self):
        body = AlertAckCreate(alert_ids=[1], ack_type="deferred", expires_hours=72)
        assert body.ack_type == "deferred"
        assert body.expires_hours == 72


class TestAlertAckResponseSchema:
    def test_includes_new_fields(self):
        resp = AlertAckResponse(
            id=1, alert_id=100, acked_by_ip="127.0.0.1",
            acked_at=datetime.now(), comment="test",
            ack_type="confirmed_ok", ack_expires_at=None, note="all good",
        )
        assert resp.ack_type == "confirmed_ok"
        assert resp.ack_expires_at is None
        assert resp.note == "all good"


# ═══════════════════════════════════════════════════════════════════════════
# 5. ArrayStatus — recent_alert_summary field
# ═══════════════════════════════════════════════════════════════════════════

class TestArrayStatusNewFields:
    def test_recent_alert_summary_default(self):
        s = ArrayStatus(array_id="a1", name="Test", host="1.2.3.4")
        assert s.recent_alert_summary == {}

    def test_recent_alert_summary_populated(self):
        s = ArrayStatus(
            array_id="a1", name="Test", host="1.2.3.4",
            recent_alert_summary={"error": 3, "warning": 5, "info": 12}
        )
        assert s.recent_alert_summary["error"] == 3


# ═══════════════════════════════════════════════════════════════════════════
# 6. Active Issues — recovery tracking
# ═══════════════════════════════════════════════════════════════════════════

class TestActiveIssuesRecoveryTracking:
    """Tests for _update_active_issues with recovery-invalidates-ack logic."""

    def _make_status(self, array_id="arr-001"):
        return ArrayStatus(array_id=array_id, name="Test", host="10.0.0.1")

    def test_card_info_recovery_records_timestamp(self):
        from backend.api.arrays import _update_active_issues, _recovery_timestamps

        status_obj = self._make_status()
        # First: card A is not running → active issue created
        alert1 = {
            "observer_name": "card_info",
            "level": "error",
            "message": "card fault",
            "timestamp": "2025-01-15T10:00:00",
            "details": {
                "alerts": [{"card": "CardA", "field": "status", "value": "NOT_RUNNING"}]
            },
        }
        _update_active_issues(status_obj, alert1)
        assert len(status_obj.active_issues) == 1
        assert status_obj.active_issues[0]["key"] == "card_info:CardA:status"

        # Second: card A recovers (disappears from alerts list)
        alert2 = {
            "observer_name": "card_info",
            "level": "info",
            "message": "card ok",
            "timestamp": "2025-01-15T11:00:00",
            "details": {"alerts": []},  # empty → all recovered
        }
        _update_active_issues(status_obj, alert2)
        assert len(status_obj.active_issues) == 0
        # Recovery should be recorded
        assert "card_info:CardA:status" in _recovery_timestamps.get("arr-001", {})

        # Cleanup
        _recovery_timestamps.pop("arr-001", None)

    def test_card_info_relapse_pops_recovery(self):
        from backend.api.arrays import _update_active_issues, _recovery_timestamps

        status_obj = self._make_status()

        # Seed recovery
        _recovery_timestamps.setdefault("arr-001", {})["card_info:CardA:status"] = "2025-01-15T11:00:00"

        # Card A relapses
        alert = {
            "observer_name": "card_info",
            "level": "error",
            "message": "card fault again",
            "timestamp": "2025-01-15T12:00:00",
            "details": {
                "alerts": [{"card": "CardA", "field": "status", "value": "NOT_RUNNING"}]
            },
        }
        _update_active_issues(status_obj, alert)
        assert len(status_obj.active_issues) == 1
        # Recovery entry should be popped (consumed)
        assert "card_info:CardA:status" not in _recovery_timestamps.get("arr-001", {})

        # Cleanup
        _recovery_timestamps.pop("arr-001", None)

    def test_recovered_flag_records_recovery(self):
        from backend.api.arrays import _update_active_issues, _recovery_timestamps

        status_obj = self._make_status()
        # Create an issue first
        status_obj.active_issues = [
            {"key": "cpu_usage", "observer": "cpu_usage", "level": "warning",
             "title": "CPU", "message": "high", "details": {}, "since": "", "latest": ""}
        ]
        # Recovery alert
        alert = {
            "observer_name": "cpu_usage",
            "level": "info",
            "message": "cpu normal",
            "timestamp": "2025-01-15T10:30:00",
            "details": {"recovered": True},
        }
        _update_active_issues(status_obj, alert)
        assert len(status_obj.active_issues) == 0
        assert "cpu_usage" in _recovery_timestamps.get("arr-001", {})

        # Cleanup
        _recovery_timestamps.pop("arr-001", None)

    def test_alarm_type_recovery_on_key_disappearance(self):
        from backend.api.arrays import _update_active_issues, _recovery_timestamps

        status_obj = self._make_status()
        # alarm_type with 2 active alarms
        alert1 = {
            "observer_name": "alarm_type",
            "level": "warning",
            "message": "alarms",
            "timestamp": "2025-01-15T09:00:00",
            "details": {
                "active_alarms": [
                    {"alarm_id": "100", "obj_type": "disk"},
                    {"alarm_id": "200", "obj_type": "fan"},
                ],
            },
        }
        _update_active_issues(status_obj, alert1)
        assert len(status_obj.active_issues) == 2

        # One alarm recovers
        alert2 = {
            "observer_name": "alarm_type",
            "level": "warning",
            "message": "alarms",
            "timestamp": "2025-01-15T10:00:00",
            "details": {
                "active_alarms": [
                    {"alarm_id": "100", "obj_type": "disk"},
                    # alarm 200 recovered
                ],
            },
        }
        _update_active_issues(status_obj, alert2)
        assert len(status_obj.active_issues) == 1
        assert "alarm_type:200" in _recovery_timestamps.get("arr-001", {})

        # Cleanup
        _recovery_timestamps.pop("arr-001", None)


# ═══════════════════════════════════════════════════════════════════════════
# 7. Agent Deployer — staging upload
# ═══════════════════════════════════════════════════════════════════════════

class TestAgentDeployerStagingUpload:
    """Tests for the two-step staging upload in deploy()."""

    def _make_deployer(self, connected=True):
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = connected
        mock_conn.host = "10.0.0.1"
        mock_conn.execute.return_value = (0, "", "")
        mock_conn.upload_file.return_value = (True, "")
        config = AppConfig()
        config.remote.upload_staging_path = "/home/permitdir"
        deployer = AgentDeployer(mock_conn, config)
        return deployer, mock_conn

    def test_deploy_not_connected(self):
        deployer, _ = self._make_deployer(False)
        result = deployer.deploy()
        assert result["ok"] is False

    @patch.object(AgentDeployer, "_build_package", return_value="/tmp/test.tar.gz")
    @patch.object(AgentDeployer, "start_agent", return_value={"ok": True, "message": "started", "pid": 1234})
    @patch("pathlib.Path.exists", return_value=False)  # skip cleanup of tmpfile
    def test_deploy_uses_staging_path(self, _exists, _start, _build):
        deployer, mock_conn = self._make_deployer(True)
        result = deployer.deploy()
        assert result["ok"] is True

        # Verify upload went to staging path
        upload_calls = mock_conn.upload_file.call_args_list
        assert len(upload_calls) == 1
        _, staging_path = upload_calls[0][0]
        assert "/home/permitdir/" in staging_path

        # Verify cp command from staging to deploy dir
        execute_calls = [c[0][0] for c in mock_conn.execute.call_args_list]
        cp_commands = [c for c in execute_calls if c.startswith("cp ")]
        assert len(cp_commands) >= 1
        assert "/home/permitdir/" in cp_commands[0]

    @patch.object(AgentDeployer, "_build_package", return_value="/tmp/test.tar.gz")
    @patch("pathlib.Path.exists", return_value=False)
    def test_deploy_upload_staging_fails(self, _exists, _build):
        deployer, mock_conn = self._make_deployer(True)
        mock_conn.upload_file.return_value = (False, "Permission denied")
        result = deployer.deploy()
        assert result["ok"] is False
        assert "staging" in result["error"].lower() or "upload" in result["error"].lower()

    def test_start_agent_not_connected(self):
        deployer, _ = self._make_deployer(False)
        result = deployer.start_agent()
        assert result["ok"] is False

    def test_stop_agent_not_connected(self):
        deployer, _ = self._make_deployer(False)
        result = deployer.stop_agent()
        assert result["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════
# 8. Acknowledgement API (integration tests via app_client)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestAckAPI:
    async def test_ack_empty_ids(self, app_client):
        resp = await app_client.post("/api/alerts/ack", json={"alert_ids": []})
        assert resp.status_code == 400

    async def test_ack_nonexistent_alert(self, app_client):
        resp = await app_client.post("/api/alerts/ack", json={
            "alert_ids": [99999],
            "ack_type": "dismiss",
        })
        assert resp.status_code == 404

    async def test_unack_nonexistent(self, app_client):
        resp = await app_client.delete("/api/alerts/ack/99999")
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestAckAPIWithData:
    """Create a real alert in DB, then test full ack lifecycle."""

    async def _create_alert(self, db_session):
        alert = AlertModel(
            array_id="arr-test",
            observer_name="card_info",
            level="error",
            message="card fault",
            details=json.dumps({"alerts": [{"card": "CardA", "field": "status"}]}),
            timestamp=datetime.now(),
        )
        db_session.add(alert)
        await db_session.commit()
        await db_session.refresh(alert)
        return alert

    async def test_ack_dismiss_sets_expiry(self, db_session):
        alert = await self._create_alert(db_session)
        ack = AlertAckModel(
            alert_id=alert.id,
            acked_by_ip="127.0.0.1",
            comment="test",
            ack_type="dismiss",
            ack_expires_at=datetime.now() + timedelta(hours=24),
        )
        db_session.add(ack)
        await db_session.commit()
        await db_session.refresh(ack)

        assert ack.ack_type == "dismiss"
        assert ack.ack_expires_at is not None
        assert ack.ack_expires_at > datetime.now()

    async def test_ack_confirmed_ok_no_expiry(self, db_session):
        alert = await self._create_alert(db_session)
        ack = AlertAckModel(
            alert_id=alert.id,
            acked_by_ip="127.0.0.1",
            comment="confirmed",
            ack_type="confirmed_ok",
            ack_expires_at=None,
        )
        db_session.add(ack)
        await db_session.commit()
        await db_session.refresh(ack)

        assert ack.ack_type == "confirmed_ok"
        assert ack.ack_expires_at is None

    async def test_ack_deferred_custom_expiry(self, db_session):
        alert = await self._create_alert(db_session)
        expire_time = datetime.now() + timedelta(hours=72)
        ack = AlertAckModel(
            alert_id=alert.id,
            acked_by_ip="127.0.0.1",
            comment="later",
            ack_type="deferred",
            ack_expires_at=expire_time,
            note="revisit next week",
        )
        db_session.add(ack)
        await db_session.commit()
        await db_session.refresh(ack)

        assert ack.ack_type == "deferred"
        assert ack.note == "revisit next week"
        assert ack.ack_expires_at is not None

    async def test_expired_ack_cleanup(self, db_session):
        """Simulate expired acks being cleaned up (what _idle_connection_cleaner does)."""
        alert = await self._create_alert(db_session)
        # Create an already-expired ack
        ack = AlertAckModel(
            alert_id=alert.id,
            acked_by_ip="127.0.0.1",
            ack_type="dismiss",
            ack_expires_at=datetime.now() - timedelta(hours=1),  # already expired
        )
        db_session.add(ack)
        await db_session.commit()

        # Simulate cleanup query
        from sqlalchemy import delete as sa_delete
        result = await db_session.execute(
            sa_delete(AlertAckModel).where(
                AlertAckModel.ack_expires_at.isnot(None),
                AlertAckModel.ack_expires_at <= datetime.now(),
            )
        )
        await db_session.commit()
        assert result.rowcount == 1

        # Verify ack is gone
        remaining = await db_session.execute(
            select(AlertAckModel).where(AlertAckModel.alert_id == alert.id)
        )
        assert remaining.scalar_one_or_none() is None


# ═══════════════════════════════════════════════════════════════════════════
# 9. _compute_recent_alert_summary
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestComputeRecentAlertSummary:
    async def test_empty_db(self, db_session):
        from backend.api.arrays import _compute_recent_alert_summary
        result = await _compute_recent_alert_summary(db_session, "arr-nonexist")
        assert result == {}

    async def test_with_alerts(self, db_session):
        from backend.api.arrays import _compute_recent_alert_summary

        now = datetime.now()
        for level in ["error", "error", "warning", "info"]:
            a = AlertModel(
                array_id="arr-test",
                observer_name="test_obs",
                level=level,
                message="test msg",
                details="{}",
                timestamp=now - timedelta(minutes=30),  # within 2h
            )
            db_session.add(a)
        # One old alert — should NOT be counted
        old = AlertModel(
            array_id="arr-test",
            observer_name="test_obs",
            level="critical",
            message="old",
            details="{}",
            timestamp=now - timedelta(hours=5),
        )
        db_session.add(old)
        await db_session.commit()

        result = await _compute_recent_alert_summary(db_session, "arr-test")
        assert result.get("error") == 2
        assert result.get("warning") == 1
        assert result.get("info") == 1
        assert result.get("critical") is None  # old alert not counted


# ═══════════════════════════════════════════════════════════════════════════
# 10. _derive_active_issues_from_db — recovery-invalidates-ack
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestDeriveActiveIssuesRecoveryAck:
    """
    Tests that _derive_active_issues_from_db auto-invalidates stale acks
    when an intermediate recovery is detected.
    """

    async def test_acked_latest_alert_skipped(self, db_session):
        """Standard behavior: acked latest alert → no active issue."""
        from backend.api.arrays import _derive_active_issues_from_db

        now = datetime.now()
        alert = AlertModel(
            array_id="arr-test",
            observer_name="cpu_usage",
            level="error",
            message="CPU high",
            details=json.dumps({}),
            timestamp=now,
        )
        db_session.add(alert)
        await db_session.commit()
        await db_session.refresh(alert)

        ack = AlertAckModel(
            alert_id=alert.id,
            acked_by_ip="127.0.0.1",
            ack_type="confirmed_ok",
        )
        db_session.add(ack)
        await db_session.commit()

        issues = await _derive_active_issues_from_db(db_session, "arr-test")
        cpu_issues = [i for i in issues if i["observer"] == "cpu_usage"]
        assert len(cpu_issues) == 0

    async def test_recovery_between_ack_and_latest_invalidates(self, db_session):
        """
        Scenario:
          1. Alert A (problem) → acked
          2. Alert B (recovery)
          3. Alert C (problem again) — should NOT be suppressed
        """
        from backend.api.arrays import _derive_active_issues_from_db

        now = datetime.now()
        # Older alert — recovery
        recovery = AlertModel(
            array_id="arr-test2",
            observer_name="cpu_usage",
            level="info",
            message="CPU normal",
            details=json.dumps({"recovered": True}),
            timestamp=now - timedelta(minutes=10),
        )
        db_session.add(recovery)

        # Latest alert — problem again
        relapse = AlertModel(
            array_id="arr-test2",
            observer_name="cpu_usage",
            level="error",
            message="CPU high again",
            details=json.dumps({}),
            timestamp=now,
        )
        db_session.add(relapse)
        await db_session.commit()
        await db_session.refresh(relapse)

        # Ack the latest (simulating stale ack from before the cycle)
        ack = AlertAckModel(
            alert_id=relapse.id,
            acked_by_ip="127.0.0.1",
            ack_type="confirmed_ok",
        )
        db_session.add(ack)
        await db_session.commit()

        # The function should detect recovery between the two alerts
        # and auto-invalidate the ack
        issues = await _derive_active_issues_from_db(db_session, "arr-test2")
        cpu_issues = [i for i in issues if i["observer"] == "cpu_usage"]
        assert len(cpu_issues) == 1  # relapse should surface

    async def test_no_recovery_ack_stays_valid(self, db_session):
        """Without intermediate recovery, ack remains valid."""
        from backend.api.arrays import _derive_active_issues_from_db

        now = datetime.now()
        # Two problem alerts — no recovery in between
        older = AlertModel(
            array_id="arr-test3",
            observer_name="cpu_usage",
            level="error",
            message="CPU high",
            details=json.dumps({}),
            timestamp=now - timedelta(minutes=10),
        )
        db_session.add(older)

        latest = AlertModel(
            array_id="arr-test3",
            observer_name="cpu_usage",
            level="error",
            message="CPU still high",
            details=json.dumps({}),
            timestamp=now,
        )
        db_session.add(latest)
        await db_session.commit()
        await db_session.refresh(latest)

        ack = AlertAckModel(
            alert_id=latest.id,
            acked_by_ip="127.0.0.1",
            ack_type="confirmed_ok",
        )
        db_session.add(ack)
        await db_session.commit()

        issues = await _derive_active_issues_from_db(db_session, "arr-test3")
        cpu_issues = [i for i in issues if i["observer"] == "cpu_usage"]
        assert len(cpu_issues) == 0  # ack is valid, no recovery


# ═══════════════════════════════════════════════════════════════════════════
# 11. Integration: statuses endpoint returns recent_alert_summary
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestStatusesEndpoint:
    async def test_statuses_returns_recent_alert_summary(self, app_client):
        """GET /api/arrays/statuses should include recent_alert_summary field."""
        resp = await app_client.get("/api/arrays/statuses")
        assert resp.status_code == 200
        data = resp.json()
        # Even if empty, each status should have the field
        for status in data:
            assert "recent_alert_summary" in status
