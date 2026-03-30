"""Observer replay tests – comprehensive mocked-external-dependency tests.

Each section covers one observer with multiple replay scenarios:
  1. PortCountersObserver – sysfs delta logic
  2. CardInfoObserver     – card parsing and alerting
  3. LinkStatusObserver   – link state change detection
  4. SfpMonitorObserver   – optical module health checks
  5. StartWorkObserver    – module start-work status
  6. Details cleanliness  – meta-tests across observers
"""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure agent package is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent.core.base import AlertLevel
from agent.observers.card_info import CardInfoObserver
from agent.observers.gate.start_work import StartWorkObserver
from agent.observers.link_status import LinkStatusObserver
from agent.observers.port_counters import PortCountersObserver, _SYSFS_COUNTERS
from agent.observers.sfp_monitor import SfpMonitorObserver


# =====================================================================
#  Helpers
# =====================================================================

def _ts():
    """Shortcut for a timestamp string."""
    return datetime.now().isoformat()


def _port_state(carrier="1", operstate="up", speed="25000", duplex="full"):
    """Build a LinkStatus-compatible port state dict."""
    return {
        "carrier": carrier,
        "operstate": operstate,
        "speed": speed,
        "duplex": duplex,
        "timestamp": _ts(),
    }


# =====================================================================
#  1. PortCountersObserver – sysfs delta tests
# =====================================================================

class TestPortCountersSysfs:
    """Test _check_sysfs_counters via mocked _read_sysfs_counters."""

    @staticmethod
    def _obs(**kw):
        cfg = {
            "ports": ["eth0"],
            "pcie_enabled": False,
            "anytest_enabled": False,
            "threshold": 0,
            "error_rate_threshold": 10,
        }
        cfg.update(kw)
        return PortCountersObserver("pc_test", cfg)

    @staticmethod
    def _zeros():
        return {n: 0 for n in _SYSFS_COUNTERS}

    # ---- 1a. Normal – all counters at 0, no change → no alert ----

    def test_normal_no_change(self):
        obs = self._obs()
        with patch.object(obs, "_read_sysfs_counters", return_value=self._zeros()):
            r1 = obs.check()
            assert r1.has_alert is False
            r2 = obs.check()
            assert r2.has_alert is False

    # ---- 1b. Threshold boundary ----

    def test_physical_error_delta_at_threshold_no_alert(self):
        """physical_error uses self.threshold; delta == threshold (0) → no alert."""
        obs = self._obs(threshold=0)
        with patch.object(obs, "_read_sysfs_counters") as m:
            m.return_value = self._zeros()
            obs.check()  # baseline
            m.return_value = self._zeros()  # delta = 0
            r = obs.check()
            assert r.has_alert is False

    def test_physical_error_delta_over_threshold_alert(self):
        """physical_error threshold=0: delta=1 → alert."""
        obs = self._obs(threshold=0)
        base = self._zeros()
        inc = self._zeros()
        inc["rx_crc_errors"] = 1
        with patch.object(obs, "_read_sysfs_counters") as m:
            m.return_value = base
            obs.check()
            m.return_value = inc
            r = obs.check()
        assert r.has_alert is True
        assert any(
            a["counter_name"] == "rx_crc_errors"
            for a in r.details.get("alerts", [])
        )

    def test_drop_delta_at_threshold_no_alert(self):
        """drop uses error_rate_threshold=10: delta=10 → NOT > 10 → no alert."""
        obs = self._obs(error_rate_threshold=10)
        base = self._zeros()
        at = self._zeros()
        at["rx_dropped"] = 10
        with patch.object(obs, "_read_sysfs_counters") as m:
            m.return_value = base
            obs.check()
            m.return_value = at
            r = obs.check()
        assert r.has_alert is False

    def test_drop_delta_over_threshold_alert(self):
        """drop error_rate_threshold=10: delta=11 → alert."""
        obs = self._obs(error_rate_threshold=10)
        base = self._zeros()
        over = self._zeros()
        over["rx_dropped"] = 11
        with patch.object(obs, "_read_sysfs_counters") as m:
            m.return_value = base
            obs.check()
            m.return_value = over
            r = obs.check()
        assert r.has_alert is True

    # ---- 1c. Mixed categories ----

    def test_mixed_categories(self):
        """Different counters map to different alert categories."""
        obs = self._obs(threshold=0, error_rate_threshold=0)
        base = self._zeros()
        mixed = self._zeros()
        mixed["rx_crc_errors"] = 5      # physical_error
        mixed["rx_dropped"] = 3         # drop
        mixed["rx_fifo_errors"] = 2     # fifo_overrun
        with patch.object(obs, "_read_sysfs_counters") as m:
            m.return_value = base
            obs.check()
            m.return_value = mixed
            r = obs.check()
        assert r.has_alert is True
        names = {a["counter_name"] for a in r.details.get("alerts", [])}
        assert "rx_crc_errors" in names
        assert "rx_dropped" in names
        assert "rx_fifo_errors" in names

    def test_category_correctness(self):
        """Verify each counter gets the correct alert category label."""
        obs = self._obs(threshold=0, error_rate_threshold=0)
        base = self._zeros()
        changed = self._zeros()
        changed["rx_crc_errors"] = 1    # physical_error
        changed["tx_dropped"] = 1       # drop
        changed["tx_fifo_errors"] = 1   # fifo_overrun
        changed["collisions"] = 1       # generic_error
        with patch.object(obs, "_read_sysfs_counters") as m:
            m.return_value = base
            obs.check()
            m.return_value = changed
            r = obs.check()
        alerts = r.details.get("alerts", [])
        cat_by_name = {a["counter_name"]: True for a in alerts}
        assert "rx_crc_errors" in cat_by_name
        assert "tx_dropped" in cat_by_name
        assert "tx_fifo_errors" in cat_by_name
        assert "collisions" in cat_by_name

    # ---- 1d. Counter wraparound / anomaly ----

    def test_anomaly_delta_ignored(self):
        """Delta > 10 M (anomaly ceiling) → treated as reset, no alert."""
        obs = self._obs()
        base = self._zeros()
        huge = self._zeros()
        huge["rx_crc_errors"] = 20_000_000
        with patch.object(obs, "_read_sysfs_counters") as m:
            m.return_value = base
            obs.check()
            m.return_value = huge
            r = obs.check()
        assert r.has_alert is False

    def test_anomaly_updates_baseline(self):
        """After anomaly skip, baseline should be updated for next cycle."""
        obs = self._obs()
        base = self._zeros()
        huge = self._zeros()
        huge["rx_crc_errors"] = 20_000_000
        # Third cycle: tiny increment over the huge value → should alert normally
        tiny_over = self._zeros()
        tiny_over["rx_crc_errors"] = 20_000_001
        with patch.object(obs, "_read_sysfs_counters") as m:
            m.return_value = base
            obs.check()       # baseline
            m.return_value = huge
            obs.check()       # anomaly, baseline updated
            m.return_value = tiny_over
            r = obs.check()   # delta=1 from 20M, should alert
        assert r.has_alert is True

    # ---- 1e. Empty / missing sysfs ----

    def test_empty_counters_no_crash(self):
        """_read_sysfs_counters returns empty dict → no crash, no alert."""
        obs = self._obs()
        with patch.object(obs, "_read_sysfs_counters", return_value={}):
            r = obs.check()
            assert r.has_alert is False

    def test_no_ports_no_crash(self):
        """No ports configured and sysfs absent → no crash."""
        obs = self._obs(ports=[])
        with patch.object(obs, "_get_sysfs_ports", return_value=[]):
            r = obs.check()
            assert r.has_alert is False

    # ---- 1f. Recovery ----

    def test_recovery_event(self):
        """Was alerting, counters stop growing → recovery INFO event."""
        obs = self._obs(threshold=0)
        base = self._zeros()
        spike = self._zeros()
        spike["rx_crc_errors"] = 5
        with patch.object(obs, "_read_sysfs_counters") as m:
            m.return_value = base
            obs.check()          # baseline
            m.return_value = spike
            r = obs.check()      # alert
            assert r.has_alert is True
            assert obs._was_alerting is True
            # Same values → delta=0 → no new alerts → recovery
            r = obs.check()
            assert r.has_alert is True
            assert r.alert_level == AlertLevel.INFO
            assert "恢复" in r.message


# =====================================================================
#  2. CardInfoObserver – parsing and alert tests
# =====================================================================

class TestCardInfoObserver:
    """Test CardInfoObserver by mocking run_command."""

    @staticmethod
    def _obs(**kw):
        cfg = {"command": "show card info"}
        cfg.update(kw)
        return CardInfoObserver("ci_test", cfg)

    NORMAL_OUTPUT = (
        "No001  BoardId: ABC123\n"
        "No001  Name: ControllerCard\n"
        "No001  Model: X9000\n"
        "No001  RunningState: RUNNING\n"
        "No001  HealthState: NORMAL\n"
        "------------------\n"
        "No002  BoardId: DEF456\n"
        "No002  Name: InterfaceCard\n"
        "No002  Model: Y8000\n"
        "No002  RunningState: RUNNING\n"
        "No002  HealthState: NORMAL\n"
    )

    # ---- 2a. Normal – all OK → no alert ----

    @patch("agent.observers.card_info.run_command")
    def test_normal_all_ok(self, mock_cmd):
        mock_cmd.return_value = (0, self.NORMAL_OUTPUT, "")
        r = self._obs().check()
        assert r.has_alert is False
        assert r.details.get("total_cards") == 2

    # ---- 2b. RunningState != RUNNING → ERROR ----

    @patch("agent.observers.card_info.run_command")
    def test_running_state_error(self, mock_cmd):
        out = (
            "No001  BoardId: B1\n"
            "No001  Model: X9\n"
            "No001  RunningState: STOPPED\n"
            "No001  HealthState: NORMAL\n"
        )
        mock_cmd.return_value = (0, out, "")
        r = self._obs().check()
        assert r.has_alert is True
        assert r.alert_level == AlertLevel.ERROR

    # ---- 2c. HealthState != NORMAL → ERROR ----

    @patch("agent.observers.card_info.run_command")
    def test_health_state_error(self, mock_cmd):
        out = (
            "No001  BoardId: B1\n"
            "No001  Model: X9\n"
            "No001  RunningState: RUNNING\n"
            "No001  HealthState: FAULT\n"
        )
        mock_cmd.return_value = (0, out, "")
        r = self._obs().check()
        assert r.has_alert is True
        assert r.alert_level == AlertLevel.ERROR

    # ---- 2d. Empty Model → WARNING ----

    @patch("agent.observers.card_info.run_command")
    def test_empty_model_warning(self, mock_cmd):
        out = (
            "No001  BoardId: B1\n"
            "No001  Model:\n"
            "No001  RunningState: RUNNING\n"
            "No001  HealthState: NORMAL\n"
        )
        mock_cmd.return_value = (0, out, "")
        r = self._obs().check()
        assert r.has_alert is True
        alerts = r.details.get("alerts", [])
        assert len(alerts) == 1
        assert alerts[0]["level"] == "warning"

    # ---- 2e. Model = "undefined" → WARNING ----

    @patch("agent.observers.card_info.run_command")
    def test_model_undefined_warning(self, mock_cmd):
        out = (
            "No001  BoardId: B1\n"
            "No001  Model: undefined\n"
            "No001  RunningState: RUNNING\n"
            "No001  HealthState: NORMAL\n"
        )
        mock_cmd.return_value = (0, out, "")
        r = self._obs().check()
        assert r.has_alert is True
        alerts = r.details.get("alerts", [])
        assert any(
            any(f["field"] == "Model" for f in a.get("fields", []))
            for a in alerts
        )

    # ---- 2f. Empty output → "无有效卡件数据" ----

    @patch("agent.observers.card_info.run_command")
    def test_empty_output(self, mock_cmd):
        mock_cmd.return_value = (0, "", "")
        r = self._obs().check()
        assert r.has_alert is False
        assert "无有效卡件数据" in r.message

    # ---- 2g. Command failure → WARNING ----

    @patch("agent.observers.card_info.run_command")
    def test_command_failure(self, mock_cmd):
        mock_cmd.return_value = (1, "", "command not found")
        r = self._obs().check()
        assert r.has_alert is True
        assert r.alert_level == AlertLevel.WARNING
        assert "失败" in r.message

    # ---- 2h. Mixed: some OK, some issues → only issues in alerts ----

    @patch("agent.observers.card_info.run_command")
    def test_mixed_cards(self, mock_cmd):
        out = (
            "No001  BoardId: OK1\n"
            "No001  Model: X9\n"
            "No001  RunningState: RUNNING\n"
            "No001  HealthState: NORMAL\n"
            "------------------\n"
            "No002  BoardId: BAD1\n"
            "No002  Model: Y8\n"
            "No002  RunningState: STOPPED\n"
            "No002  HealthState: NORMAL\n"
        )
        mock_cmd.return_value = (0, out, "")
        r = self._obs().check()
        assert r.has_alert is True
        alert_cards = [a["card"] for a in r.details.get("alerts", [])]
        assert "No002" in alert_cards
        assert "No001" not in alert_cards

    # ---- 2i. Recovery → sticky=True ----

    @patch("agent.observers.card_info.run_command")
    def test_recovery(self, mock_cmd):
        bad = (
            "No001  BoardId: B1\n"
            "No001  Model: X9\n"
            "No001  RunningState: STOPPED\n"
            "No001  HealthState: NORMAL\n"
        )
        good = (
            "No001  BoardId: B1\n"
            "No001  Model: X9\n"
            "No001  RunningState: RUNNING\n"
            "No001  HealthState: NORMAL\n"
        )
        obs = self._obs()

        mock_cmd.return_value = (0, bad, "")
        r = obs.check()
        assert r.has_alert is True  # alert active

        mock_cmd.return_value = (0, good, "")
        r = obs.check()
        assert r.has_alert is True          # recovery event
        assert r.alert_level == AlertLevel.INFO
        assert r.sticky is True
        assert r.details.get("recovered") is True

    # ---- 2j. Duplicate BoardId ----

    @patch("agent.observers.card_info.run_command")
    def test_duplicate_board_id(self, mock_cmd):
        out = (
            "No001  BoardId: SAME\n"
            "No001  Model: X9\n"
            "No001  RunningState: RUNNING\n"
            "No001  HealthState: NORMAL\n"
            "------------------\n"
            "No002  BoardId: SAME\n"
            "No002  Model: Y8\n"
            "No002  RunningState: RUNNING\n"
            "No002  HealthState: NORMAL\n"
        )
        mock_cmd.return_value = (0, out, "")
        r = self._obs().check()
        assert r.has_alert is False
        assert r.details.get("total_cards") == 2

    # ---- 2k. No command configured ----

    def test_no_command_configured(self):
        obs = CardInfoObserver("ci_test", {"command": ""})
        r = obs.check()
        assert r.has_alert is False
        assert "未配置" in r.message


# =====================================================================
#  3. LinkStatusObserver – link state change detection
# =====================================================================

class TestLinkStatusObserver:
    """Test LinkStatusObserver by mocking _get_port_state."""

    @staticmethod
    def _obs(**kw):
        cfg = {"ports": ["eth0"]}
        cfg.update(kw)
        return LinkStatusObserver("ls_test", cfg)

    # ---- 3a. First run → baseline, no alerts ----

    def test_first_run_no_alerts(self):
        obs = self._obs()
        with patch.object(obs, "_get_port_state", return_value=_port_state()):
            r = obs.check()
        assert r.has_alert is False

    # ---- 3b. Link down: carrier 1 → 0 ----

    def test_link_down(self):
        obs = self._obs()
        with patch.object(obs, "_get_port_state") as m:
            m.return_value = _port_state(carrier="1")
            obs.check()  # baseline
            m.return_value = _port_state(carrier="0", operstate="down")
            r = obs.check()
        assert r.has_alert is True
        assert any("DOWN" in c.get("change", "") for c in r.details.get("changes", []))

    # ---- 3c. Link up: carrier 0 → 1 ----

    def test_link_up(self):
        obs = self._obs()
        with patch.object(obs, "_get_port_state") as m:
            m.return_value = _port_state(carrier="0", operstate="down")
            obs.check()
            m.return_value = _port_state(carrier="1", operstate="up")
            r = obs.check()
        assert r.has_alert is True
        assert any("UP" in c.get("change", "") for c in r.details.get("changes", []))

    # ---- 3d. Operstate change: up → down ----

    def test_operstate_change(self):
        obs = self._obs()
        with patch.object(obs, "_get_port_state") as m:
            # Same carrier but different operstate
            m.return_value = _port_state(carrier="1", operstate="up")
            obs.check()
            m.return_value = _port_state(carrier="1", operstate="down")
            r = obs.check()
        assert r.has_alert is True
        changes = [c.get("change", "") for c in r.details.get("changes", [])]
        assert any("operstate" in c for c in changes)

    # ---- 3e. Speed decrease: 25000 → 10000 ----

    def test_speed_decrease(self):
        obs = self._obs()
        with patch.object(obs, "_get_port_state") as m:
            m.return_value = _port_state(speed="25000")
            obs.check()
            m.return_value = _port_state(speed="10000")
            r = obs.check()
        assert r.has_alert is True
        changes = [c.get("change", "") for c in r.details.get("changes", [])]
        assert any("速率" in c or "speed" in c.lower() for c in changes)

    # ---- 3f. Whitelisted port → no alert ----

    def test_whitelist_no_alert(self):
        """Whitelisted ports should be skipped even on state change."""
        obs = self._obs(ports=["eth0", "wl_port"], whitelist=["wl_port"])
        with patch.object(obs, "_get_port_state") as m:
            m.return_value = _port_state(carrier="1")
            obs.check()
            m.return_value = _port_state(carrier="0", operstate="down")
            r = obs.check()
        # eth0 should alert, wl_port should not
        assert r.has_alert is True
        changes = [c.get("change", "") for c in r.details.get("changes", [])]
        assert any("eth0" in c for c in changes)
        assert not any("wl_port" in c for c in changes)

    # ---- 3g. Port disappears → "link DOWN (端口消失)" ----

    def test_port_disappears(self):
        obs = self._obs(ports=["eth0", "eth1"])
        with patch.object(obs, "_get_port_state") as m:
            m.return_value = _port_state(carrier="1")
            obs.check()

        # Now eth1 is gone
        obs.ports = ["eth0"]
        with patch.object(obs, "_get_port_state") as m:
            m.return_value = _port_state(carrier="1")
            r = obs.check()
        assert r.has_alert is True
        changes = [c.get("change", "") for c in r.details.get("changes", [])]
        assert any("端口消失" in c for c in changes)

    # ---- 3h. No sysfs available → no crash ----

    def test_no_sysfs_no_crash(self):
        obs = self._obs()
        with patch.object(obs, "_get_port_state", return_value=None):
            r = obs.check()
        assert r.has_alert is False


# =====================================================================
#  4. SfpMonitorObserver – optical module health tests
# =====================================================================

class TestSfpMonitorObserver:
    """Test SfpMonitorObserver by mocking run_command."""

    @staticmethod
    def _obs(**kw):
        cfg = {"command": "anytest sfpallinfo"}
        cfg.update(kw)
        return SfpMonitorObserver("sfp_test", cfg)

    NORMAL_BLOCK = (
        "PortId: 0x1\n"
        "parentID: 1\n"
        "Name: P0\n"
        "TempReal(`C): 45\n"
        "HealthState: NORMAL\n"
        "RunningState: LINK_UP\n"
    )

    @staticmethod
    def _multi_block(*blocks):
        return "\n-------------------\n".join(blocks)

    # ---- 4a. Normal → no alert ----

    @patch("agent.observers.sfp_monitor.run_command")
    def test_normal_healthy(self, mock_cmd):
        mock_cmd.return_value = (0, self.NORMAL_BLOCK, "")
        r = self._obs().check()
        assert r.has_alert is False

    # ---- 4b. High temperature (≥ 105 °C) ----

    @patch("agent.observers.sfp_monitor.run_command")
    def test_high_temperature(self, mock_cmd):
        block = (
            "PortId: 0x1\nparentID: 1\nName: P0\n"
            "TempReal(`C): 110\n"
            "HealthState: NORMAL\nRunningState: LINK_UP\n"
        )
        mock_cmd.return_value = (0, block, "")
        r = self._obs().check()
        assert r.has_alert is True
        assert "温度" in r.message

    @patch("agent.observers.sfp_monitor.run_command")
    def test_temperature_at_threshold_alert(self, mock_cmd):
        """TempReal exactly at threshold (105) → alert."""
        block = (
            "PortId: 0x1\nparentID: 1\nName: P0\n"
            "TempReal(`C): 105\n"
            "HealthState: NORMAL\nRunningState: LINK_UP\n"
        )
        mock_cmd.return_value = (0, block, "")
        r = self._obs().check()
        assert r.has_alert is True

    @patch("agent.observers.sfp_monitor.run_command")
    def test_temperature_below_threshold_ok(self, mock_cmd):
        """TempReal just below threshold → no alert."""
        block = (
            "PortId: 0x1\nparentID: 1\nName: P0\n"
            "TempReal(`C): 104\n"
            "HealthState: NORMAL\nRunningState: LINK_UP\n"
        )
        mock_cmd.return_value = (0, block, "")
        r = self._obs().check()
        assert r.has_alert is False

    # ---- 4c. HealthState not NORMAL ----

    @patch("agent.observers.sfp_monitor.run_command")
    def test_health_state_abnormal(self, mock_cmd):
        block = (
            "PortId: 0x1\nparentID: 1\nName: P0\n"
            "TempReal(`C): 45\n"
            "HealthState: FAULT\nRunningState: LINK_UP\n"
        )
        mock_cmd.return_value = (0, block, "")
        r = self._obs().check()
        assert r.has_alert is True
        assert "HealthState" in r.message

    # ---- 4d. RunningState not LINK_UP ----

    @patch("agent.observers.sfp_monitor.run_command")
    def test_running_state_abnormal(self, mock_cmd):
        block = (
            "PortId: 0x1\nparentID: 1\nName: P0\n"
            "TempReal(`C): 45\n"
            "HealthState: NORMAL\nRunningState: OFFLINE\n"
        )
        mock_cmd.return_value = (0, block, "")
        r = self._obs().check()
        assert r.has_alert is True
        assert "RunningState" in r.message

    # ---- 4e. FC speed mismatch ----

    @patch("agent.observers.sfp_monitor.run_command")
    def test_fc_speed_mismatch(self, mock_cmd):
        block = (
            "PortId: 0x2\nparentID: 2\nName: FC0\n"
            "TempReal(`C): 40\n"
            "HealthState: NORMAL\nRunningState: LINK_UP\n"
            "MaxSpeed: 16G\nRunSpeed: 8G\nConfSpeed: 16G\n"
        )
        mock_cmd.return_value = (0, block, "")
        r = self._obs().check()
        assert r.has_alert is True
        assert "速率不一致" in r.message or "speed" in r.message.lower()

    # ---- 4f. FC RunSpeed unknown ----

    @patch("agent.observers.sfp_monitor.run_command")
    def test_fc_run_speed_unknown(self, mock_cmd):
        block = (
            "PortId: 0x2\nparentID: 2\nName: FC0\n"
            "TempReal(`C): 40\n"
            "HealthState: NORMAL\nRunningState: LINK_UP\n"
            "MaxSpeed: 16G\nRunSpeed: unknown speed\nConfSpeed: 16G\n"
        )
        mock_cmd.return_value = (0, block, "")
        r = self._obs().check()
        assert r.has_alert is True
        assert "unknown" in r.message.lower()

    # ---- 4g. Command failure → no alert (graceful skip) ----

    @patch("agent.observers.sfp_monitor.run_command")
    def test_command_failure_graceful(self, mock_cmd):
        mock_cmd.return_value = (1, "", "timeout")
        r = self._obs().check()
        assert r.has_alert is False

    # ---- 4h. Empty output → no alert ----

    @patch("agent.observers.sfp_monitor.run_command")
    def test_empty_output(self, mock_cmd):
        mock_cmd.return_value = (0, "", "")
        r = self._obs().check()
        assert r.has_alert is False

    # ---- 4i. Mixed: some healthy, some issues ----

    @patch("agent.observers.sfp_monitor.run_command")
    def test_mixed_modules(self, mock_cmd):
        healthy = (
            "PortId: 0x1\nparentID: 1\nName: P0\n"
            "TempReal(`C): 45\n"
            "HealthState: NORMAL\nRunningState: LINK_UP\n"
        )
        sick = (
            "PortId: 0x2\nparentID: 2\nName: P1\n"
            "TempReal(`C): 110\n"
            "HealthState: NORMAL\nRunningState: LINK_UP\n"
        )
        mock_cmd.return_value = (0, self._multi_block(healthy, sick), "")
        r = self._obs().check()
        assert r.has_alert is True
        # Only P1 should appear (P0 is healthy)
        assert "P1" in r.message
        # P0 should NOT trigger an alert
        alerts_str = str(r.details.get("alerts", []))
        assert "P1" in alerts_str


# =====================================================================
#  5. StartWorkObserver – module start-work status
# =====================================================================

class TestStartWorkObserver:
    """Test StartWorkObserver by mocking run_command."""

    @staticmethod
    def _obs(**kw):
        cfg = {"command": "anytest sysgetstartwork"}
        cfg.update(kw)
        return StartWorkObserver("sw_test", cfg)

    # ---- 5a. All modules state=1 → no alert ----

    @patch("agent.observers.gate.start_work.run_command")
    def test_all_started(self, mock_cmd):
        out = "ModuleA: 1\nModuleB: 1\nModuleC: 1\n"
        mock_cmd.return_value = (0, out, "")
        r = self._obs().check()
        assert r.has_alert is False
        assert r.details.get("started") is True
        assert r.details.get("total_modules") == 3

    # ---- 5b. Some modules not started → WARNING ----

    @patch("agent.observers.gate.start_work.run_command")
    def test_some_not_started(self, mock_cmd):
        out = "ModuleA: 1\nModuleB: 0\nModuleC: 1\nModuleD: 0\n"
        mock_cmd.return_value = (0, out, "")
        r = self._obs().check()
        assert r.has_alert is True
        assert r.alert_level == AlertLevel.WARNING
        assert "ModuleB" in r.message
        assert "ModuleD" in r.message
        assert r.details.get("started") is False
        assert set(r.details.get("failed_modules", [])) == {"ModuleB", "ModuleD"}

    # ---- 5c. Command failure → WARNING ----

    @patch("agent.observers.gate.start_work.run_command")
    def test_command_failure(self, mock_cmd):
        mock_cmd.return_value = (1, "", "timeout")
        r = self._obs().check()
        assert r.has_alert is True
        assert r.alert_level == AlertLevel.WARNING
        assert r.details.get("reason") == "command_failed"

    # ---- 5d. Empty output → WARNING "parse_failed" ----

    @patch("agent.observers.gate.start_work.run_command")
    def test_empty_output_parse_failed(self, mock_cmd):
        mock_cmd.return_value = (0, "", "")
        r = self._obs().check()
        assert r.has_alert is True
        assert r.alert_level == AlertLevel.WARNING
        assert r.details.get("reason") == "parse_failed"

    @patch("agent.observers.gate.start_work.run_command")
    def test_unparseable_output(self, mock_cmd):
        """Garbled output with no 'key: number' lines → parse_failed."""
        mock_cmd.return_value = (0, "random junk\n\nno parseable data here\n", "")
        r = self._obs().check()
        assert r.has_alert is True
        assert r.details.get("reason") == "parse_failed"

    # ---- 5e. Single module not started → correct message ----

    @patch("agent.observers.gate.start_work.run_command")
    def test_single_module_not_started(self, mock_cmd):
        out = "ModuleA: 1\nModuleB: 0\nModuleC: 1\n"
        mock_cmd.return_value = (0, out, "")
        r = self._obs().check()
        assert r.has_alert is True
        assert "ModuleB" in r.message
        assert len(r.details.get("failed_modules", [])) == 1


# =====================================================================
#  6. Details cleanliness meta-tests
# =====================================================================

class TestDetailsCleanliness:
    """Verify observer alert details dict hygiene across all observers."""

    def test_port_counters_only_changed_counters(self):
        """Details contain only counters with non-zero delta."""
        obs = PortCountersObserver("pc", {
            "ports": ["eth0"],
            "pcie_enabled": False,
            "anytest_enabled": False,
            "threshold": 0,
            "error_rate_threshold": 0,
        })
        base = {n: 0 for n in _SYSFS_COUNTERS}
        inc = dict(base)
        inc["rx_crc_errors"] = 5  # only this changes
        with patch.object(obs, "_read_sysfs_counters") as m:
            m.return_value = base
            obs.check()
            m.return_value = inc
            r = obs.check()
        alerts = r.details.get("alerts", [])
        # Only changed counter should appear
        for a in alerts:
            assert a.get("delta", 0) > 0, f"Zero delta leaked into details: {a}"
        counter_names = [a["counter_name"] for a in alerts]
        assert "rx_crc_errors" in counter_names

    @patch("agent.observers.card_info.run_command")
    def test_card_info_alerts_contain_only_issue_cards(self, mock_cmd):
        """alerts list should only include cards that have issues."""
        out = (
            "No001  BoardId: OK1\nNo001  Model: X9\n"
            "No001  RunningState: RUNNING\nNo001  HealthState: NORMAL\n"
            "------------------\n"
            "No002  BoardId: BAD1\nNo002  Model: Y8\n"
            "No002  RunningState: STOPPED\nNo002  HealthState: NORMAL\n"
        )
        mock_cmd.return_value = (0, out, "")
        r = CardInfoObserver("ci", {"command": "test"}).check()
        for a in r.details.get("alerts", []):
            assert len(a.get("fields", [])) > 0, "Alert entry without field issues"

    @patch("agent.observers.sfp_monitor.run_command")
    def test_sfp_no_raw_command_in_details(self, mock_cmd):
        """Details should not leak raw command output."""
        block = (
            "PortId: 0x1\nparentID: 1\nName: P0\n"
            "TempReal(`C): 110\n"
            "HealthState: NORMAL\nRunningState: LINK_UP\n"
        )
        mock_cmd.return_value = (0, block, "")
        r = SfpMonitorObserver("sfp", {}).check()
        details_str = str(r.details)
        # Should not contain the raw command name or stderr
        assert "anytest sfpallinfo" not in details_str

    @patch("agent.observers.gate.start_work.run_command")
    def test_start_work_no_zero_state_in_failed_modules(self, mock_cmd):
        """failed_modules should list names, not contain raw state values."""
        out = "Mod1: 1\nMod2: 0\nMod3: 1\n"
        mock_cmd.return_value = (0, out, "")
        r = StartWorkObserver("sw", {"command": "test"}).check()
        failed = r.details.get("failed_modules", [])
        for mod in failed:
            assert isinstance(mod, str), "Expected module name string"
            # Should not be a numeric string
            assert not mod.isdigit(), f"Module list leaking state values: {mod}"

    def test_port_counters_no_unchanged_fields(self):
        """Unchanged counters must not appear in details at all."""
        obs = PortCountersObserver("pc", {
            "ports": ["eth0"],
            "pcie_enabled": False,
            "anytest_enabled": False,
            "threshold": 0,
            "error_rate_threshold": 0,
        })
        base = {n: 0 for n in _SYSFS_COUNTERS}
        inc = dict(base)
        inc["rx_crc_errors"] = 3
        inc["tx_dropped"] = 7
        with patch.object(obs, "_read_sysfs_counters") as m:
            m.return_value = base
            obs.check()
            m.return_value = inc
            r = obs.check()
        counter_names = {a["counter_name"] for a in r.details.get("alerts", [])}
        # Only the two changed counters should be present
        assert counter_names == {"rx_crc_errors", "tx_dropped"}
